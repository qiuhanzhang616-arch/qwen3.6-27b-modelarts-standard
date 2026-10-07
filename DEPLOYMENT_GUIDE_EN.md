# Deploy Qwen3.6 27B on Huawei Cloud ModelArts Standard

## Purpose and deployment scope

Follow this guide to deploy a non-production chatbot using official **Qwen3.6-27B BF16** weights, one **8-card Ascend A2 node**, and a **262,144-token context limit** on Huawei Cloud public-cloud **ModelArts Standard, new-version real-time inference**. The result is an authenticated OpenAI-compatible chat API. A chatbot web interface is a separate application.

The runtime settings below come from a successful eight-card reference deployment. Public-cloud resource names, service URLs, storage associations, drivers, and image availability must be resolved in your own account. The public release image selected in Step 5 is available and its ARM64 digest was checked on 7 October 2026; it is different from the retained image used in the reference deployment. Complete the acceptance steps with your selected image before handing over the service.

The accompanying ZIP contains the guide, executable preparation and startup files, request examples, an acceptance script, and a final checklist. Appendices A, B and C provide the complete download-address inventory, a field-by-field console selection checklist, and the full script source. It does **not** contain the 55.6 GB weights, container image, API keys, or account-specific configuration.

### Target configuration

| Item | Setting for this procedure |
|---|---|
| Workload | Text chatbot, including multi-turn and streaming chat |
| Model repository | `Qwen/Qwen3.6-27B` |
| Weight revision | `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` |
| Weight precision | BF16, no quantization |
| Snapshot inventory | 29 files, 15 weight shards, 55,586,107,940 bytes |
| Compute | One dedicated node, 8 × Ascend A2, 64 GB HBM per card |
| Engine topology | TP8 / DP1, one deployment replica, one unit instance |
| Context | 262,144 tokens, including input, chat template, reasoning and output |
| Model alias | `qwen3.6-27b` |
| Container API | HTTP, port 8000 |
| Client authentication | ModelArts API key |
| Model storage acceleration | Enabled |
| Graceful shutdown | Enabled, 1,200 seconds |
| Automatic rebuild | Disabled |
| Model prefix caching | Disabled in this initial runtime profile |

The native model context is 262,144 tokens. This procedure does not apply a context extension or change RoPE settings. The weight configuration can legitimately identify the architecture as `Qwen3_5ForConditionalGeneration`: verify the repository revision rather than treating that architecture name as evidence that the wrong model was downloaded. See the [official model card](https://huggingface.co/Qwen/Qwen3.6-27B).

## Step 1 Prepare the account and resource worksheet

1. Sign in to the Huawei Cloud console and choose the deployment region.
2. Open **ModelArts Standard**. Locate **Model Inference → Real-Time Inference**. Some consoles display **Model Deployment → Online Services** for the same workflow.
3. Select the **new version**. The following field tables do not describe the legacy custom-model import workflow.
4. Confirm that your account can use a dedicated A2 inference resource pool in this region. If the region lacks the eight-card A2 specification, resolve resource availability before proceeding.
5. Confirm permissions for ModelArts service deployment, SWR image access, SFS Turbo association, the preparation ECS, and the selected VPC/subnet. Have your administrator configure the required ModelArts agency. Restrict permissions to the project and resources used by this deployment.
6. Confirm the cost and lifetime of the test. A dedicated resource pool may continue to incur charges after an inference deployment is stopped. Include ECS, SFS Turbo and image storage in the budget.

Fill in this worksheet. All `CHANGE_ME` entries are placeholders and must be replaced.

| Value to record | Your value |
|---|---|
| Region and project | `CHANGE_ME_REGION`, `CHANGE_ME_PROJECT` |
| Dedicated resource pool and network | `CHANGE_ME_POOL`, `CHANGE_ME_POOL_NETWORK` |
| Selected idle eight-card node | `CHANGE_ME_NODE_NAME` |
| Weight SFS Turbo file system | `CHANGE_ME_WEIGHT_SFS` |
| Runtime SFS Turbo file system | `CHANGE_ME_RUNTIME_SFS` |
| Preparation ECS | `CHANGE_ME_PREPARATION_ECS` |
| SWR registry and organization | `CHANGE_ME_SWR_REGISTRY`, `CHANGE_ME_SWR_ORG` |
| Service name | `qwen36-27b-8a2-test` |
| Deployment name | `deploy-qwen36-bf16-tp8` |
| Authorized client network | `CHANGE_ME_CLIENT_VPC_OR_NETWORK` |
| API key owner | `CHANGE_ME_KEY_OWNER` |

**Checkpoint:** The region, eight-card capacity, storage, image registry, client access route and resource owner are known. No existing production deployment needs to be changed.

## Step 2 Prepare one idle eight-card A2 node

1. Go to **Resource Management → Dedicated Compute Resources → Resource Pools**. Older navigation may say **Dedicated Resource Pools**.
2. Reuse an approved inference pool, or create a separate non-production pool with one eight-card A2 node.
3. Open the pool and select **Nodes**.
4. Verify the hardware family, ARM64 CPU architecture, driver version, node health and schedulability.
5. Select a node with **8 available NPUs**, not merely eight total NPUs. Record its actual available CPU and memory as well.
6. Confirm compatibility between the pool driver, the selected CANN image, and A2 hardware using the image release guidance. Do not upgrade a shared pool driver as an incidental part of this procedure.
7. Check the node's data disk and image disk capacity. The container image is separate from the local model cache. Budget for expanded image layers, approximately 55.6 GB of cached weights, graph caches and logs; also meet the local-cache disk requirements shown by ModelArts for your pool/storage option.

The reference request was **8 NPUs, 120 vCPUs and 900,000 MiB of RAM**. These CPU and RAM values are a reproducible reference allocation, not a universal minimum for Qwen. Use them only if your selected node can allocate them. A preset eight-card shape may ask for more CPU than the node currently has available; use a permitted custom specification rather than reducing the NPU count.

**Checkpoint:** Exactly one suitable non-production node can provide the full eight-card allocation. Record its driver and available resources.

## Step 3 Prepare model storage and runtime storage

Use two distinct file systems in the main procedure:

| File system | Data | Mount on preparation ECS | Mount inside inference container |
|---|---|---|---|
| Weight SFS Turbo | Official snapshot | `/mnt/qwen-weights` | `/model/weights`, read-only, cached |
| Runtime SFS Turbo | Startup scripts, verification receipt, logs and PID files | `/mnt/qwen-runtime` | `/qwen-data`, read/write, uncached |

The public-cloud storage documentation limits repeat mounting of one SFS Turbo file system. Two distinct file systems avoid relying on the reference environment's ability to mount different subdirectories of the same file system twice. You can reuse two existing approved file systems. If you have only one, an alternative is a cached OBS parallel file system for the weights and SFS Turbo for runtime files; that is a storage variation and requires the appropriate OBS upload and agency configuration. See [Storage Mounting](https://support.huaweicloud.com/intl/en-us/inference-modelarts/inference2.0-modelarts-0090.html).

### Associate both SFS Turbo file systems

1. In the SFS Turbo console, create or select file systems supported by ModelArts network association in your region. Use a type eligible for this feature; the association documentation specifies HPC file systems.
2. Keep the file systems in the deployment region and choose a VPC/subnet reachable from the preparation ECS.
3. Go to the ModelArts **Resource Pool Networks** page, or **Resource Management → Network** in the older navigation.
4. Locate the network used by the dedicated pool.
5. Choose **More → Associate SFS Turbo** or **Add SFS Turbo**.
6. Select the weight and runtime file systems and the required subnet, then confirm.
7. Verify **Associated** status for both. An SFS Turbo file system already associated with another network must not be silently reassociated.
8. Keep these associations while the service is running. Follow the [official association procedure](https://support.huaweicloud.com/intl/en-us/usermanual-standard-modelarts/resmgmt-modelarts_0096.html).

### Mount them on the preparation ECS

Use a Linux ARM64 ECS with Python 3.10 or later, Docker, and access to Hugging Face, Quay and your regional SWR. The preparation ECS does not need an NPU. Allocate enough local disk for image layers and temporary image transfers; 100 GiB is a practical starting allocation to assess against your selected image.

1. On each SFS Turbo details page, copy its actual mount command.
2. Install the NFS client package for the ECS operating system if required.
3. Create the two mount points, then run the console-provided commands against those mount points.
4. Verify the mounts:

```bash
findmnt /mnt/qwen-weights
findmnt /mnt/qwen-runtime
df -h /mnt/qwen-weights /mnt/qwen-runtime
```

5. Extract this deployment package on the ECS and enter its directory.
6. Set these variables in the same shell used for the preparation commands:

```bash
export QWEN_MODEL_ROOT=/mnt/qwen-weights/qwen36-27b
export QWEN_RUNTIME_ROOT=/mnt/qwen-runtime/qwen36-27b
mkdir -p "$QWEN_MODEL_ROOT/weights" "$QWEN_MODEL_ROOT/logs"
mkdir -p "$QWEN_RUNTIME_ROOT/startup" "$QWEN_RUNTIME_ROOT/logs" "$QWEN_RUNTIME_ROOT/run"
```

Provide at least 100 GiB of free model-storage space for this 55.6 GB snapshot and preparation overhead, while also meeting the cloud file system's provisioning minimum. Keep runtime storage space for retained logs. Actual SFS provisioning minima and billing depend on the selected type.

**Checkpoint:** Both mount points are actual mounted file systems, have sufficient space, and are writable by the preparation operator. Do not download into an unmounted directory that happens to have the same name.

## Step 4 Download and verify the official weights

### Official download addresses

| Source | Address and use |
|---|---|
| Official Hugging Face repository | [Qwen/Qwen3.6-27B](https://huggingface.co/Qwen/Qwen3.6-27B) |
| Exact snapshot file browser | [Revision 6a9e13bd6fc8f0983b9b99948120bc37f49c13e9](https://huggingface.co/Qwen/Qwen3.6-27B/tree/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9) |
| Pinned download manifest | [Immutable revision metadata with file sizes and LFS hashes](https://huggingface.co/api/models/Qwen/Qwen3.6-27B/revision/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9?blobs=true) |
| Official ModelScope mirror | [Qwen/Qwen3.6-27B](https://www.modelscope.cn/models/Qwen/Qwen3.6-27B) |

The executable procedure downloads the fixed Hugging Face snapshot. ModelScope is an alternative official source, but its revision identifier and file inventory must be established separately; a Hugging Face Git revision must not be assumed to identify the same ModelScope revision. Do not substitute FP8, W8A8 or a different Qwen variant.

Every file's direct fixed-revision URL is listed in Appendix A. Use the full snapshot downloader below instead of downloading only one `.safetensors` shard. Keep the tokenizer, processor, chat template, generation configuration and weight index with the model.

Run on the preparation ECS, from the extracted deployment package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install requests==2.32.5
set -o pipefail
python scripts/download_weights.py \
  --root "$QWEN_MODEL_ROOT" \
  --workers 8 \
  2>&1 | tee "$QWEN_MODEL_ROOT/logs/download.log"
```

The downloader fixes the repository revision, checks the manifest, downloads all files, supports interrupted transfers, verifies published SHA256 values for weight shards, and records SHA256 values for the remaining files. It creates `weights-verified.json` only after successful verification.

Expected final output:

```text
COMPLETE 29 55586107940
```

Confirm the receipt and configuration:

```bash
python - "$QWEN_MODEL_ROOT" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
receipt = json.loads((root / 'weights-verified.json').read_text())
assert receipt['complete']
assert receipt['revision'] == '6a9e13bd6fc8f0983b9b99948120bc37f49c13e9'
assert len(receipt['files']) == 29
assert receipt['total_bytes'] == 55586107940
assert not list((root / 'weights').rglob('*.incomplete'))
config = json.loads((root / 'weights/config.json').read_text())
assert config['text_config']['max_position_embeddings'] == 262144
print('VERIFIED:', config['architectures'], config['text_config'].get('dtype'))
PY
```

If interrupted, rerun the same downloader against the same directory. Do not run two downloaders concurrently against that directory. If a hash mismatch persists, quarantine the affected file, investigate the source/network/storage, and rerun verification. A directory's existence is not proof of a complete snapshot.

**Checkpoint:** The success receipt exists, all indexed shards are present, and no incomplete files remain.

## Step 5 Prepare an ARM64 inference image in your regional SWR

The main path uses the official A2 image **vLLM-Ascend v0.23.0.post1**, which is named in the [versioned Qwen3.6 A2 deployment tutorial](https://docs.vllm.ai/projects/ascend/en/v0.23.0/tutorials/models/Qwen3.5-27B-Qwen3.6-27B.html). Use the ARM64 image, not the `-a3`, `-a5` or `-310p` variant. The [release notes](https://github.com/vllm-project/vllm-ascend/releases/tag/v0.23.0.post1) describe this release.

### Pull the public image by its ARM64 digest

```bash
export QWEN_SOURCE_IMAGE='quay.io/ascend/vllm-ascend@sha256:e62e85cb1bef9625cf568d0e8e2ac8e4b76f946eb6e8d9d459cfcf99565bea5d'
docker pull --platform linux/arm64 "$QWEN_SOURCE_IMAGE"
docker image inspect "$QWEN_SOURCE_IMAGE" \
  --format '{{.Architecture}} {{.Os}} {{json .RepoDigests}}'
```

Expected architecture and OS: **arm64 linux**. The pinned ARM64 manifest is distinct from the multiarchitecture index digest recorded in `image-candidate.json`.

On an ARM64 preparation ECS, inspect the package metadata without starting a model:

```bash
docker run --rm --platform linux/arm64 \
  --entrypoint python \
  -v "$PWD/scripts/inspect_image.py:/tmp/inspect_image.py:ro" \
  "$QWEN_SOURCE_IMAGE" /tmp/inspect_image.py
```

Record the reported vLLM, vLLM-Ascend, Transformers and torch_npu versions. The public image metadata identifies CANN 9.1.0; confirm that the target pool driver is compatible. This metadata check does not replace an NPU runtime test.

An x86 preparation ECS can pull and retag an ARM64 image with `--platform linux/arm64`; it cannot normally execute that image without emulation. Use an ARM64 preparation host for the Python inspection, or perform the inspection in the inference container after deployment.

### Push to your SWR repository

1. Open **SWR → Organizations** and create or select your deployment organization.
2. Obtain the SWR login instructions from the regional console. Authenticate using approved temporary credentials; do not put credentials into the deployment package or image.
3. Set the real registry and organization:

```bash
export QWEN_SWR_REGISTRY='CHANGE_ME_SWR_REGISTRY'
export QWEN_SWR_ORG='CHANGE_ME_SWR_ORG'
export QWEN_DEST_IMAGE="$QWEN_SWR_REGISTRY/$QWEN_SWR_ORG/qwen36-vllm-ascend:v023-post1-arm64"
docker tag "$QWEN_SOURCE_IMAGE" "$QWEN_DEST_IMAGE"
docker push "$QWEN_DEST_IMAGE"
```

4. In **SWR → My Images**, verify the repository and tag.
5. Open **View Manifest**, record the destination digest and architecture, and retain the push output. Deploy by digest if your console accepts it. Otherwise use a versioned tag and prevent that tag from being overwritten.

The image provides the inference dependencies; mounted storage provides the weights and startup files. ModelArts starts the container and supplies devices. Do not put a nested `docker run`, `--privileged`, or manual device mounting into the ModelArts boot command. Image health endpoints and stdout logging follow [Preparing an Inference Image](https://support.huaweicloud.com/intl/en-us/inference-modelarts/inference2.0-modelarts-0003.html).

### If you need the exact reference image

The successful reference runtime used manifest `sha256:26e8a40f1b7a4ed6b7242578aac79f07d6525ffad1427fa4ebd7e3ed166a6bcb`. Its historical Quay manifest was not publicly available when checked. Obtain an authorized export from the owner of the retained image, load it with `docker load`, verify ARM64 and its identity, then push it to your own SWR. Do not assume that the public release image is byte-identical to it. Do not use the reference environment's private registry address in another cloud account.

**Checkpoint:** The selected ARM64 image is accessible from your pool, its dependencies match the hardware, and the exact SWR tag/digest is recorded.

## Step 6 Stage the startup package and verification receipt

Copy only the runtime files and model verification metadata to the runtime file system:

```bash
cp startup/start.sh startup/stop.sh startup/supervisor.py \
  startup/thread_preflight.py "$QWEN_RUNTIME_ROOT/startup/"
cp "$QWEN_MODEL_ROOT/weights-verified.json" "$QWEN_RUNTIME_ROOT/weights-verified.json"
cp "$QWEN_MODEL_ROOT/weight-manifest.json" "$QWEN_RUNTIME_ROOT/weight-manifest.json"
cp scripts/acceptance.py "$QWEN_RUNTIME_ROOT/acceptance.py"
chmod 0755 "$QWEN_RUNTIME_ROOT/startup/start.sh" "$QWEN_RUNTIME_ROOT/startup/stop.sh"
bash -n "$QWEN_RUNTIME_ROOT/startup/start.sh"
bash -n "$QWEN_RUNTIME_ROOT/startup/stop.sh"
python -m py_compile "$QWEN_RUNTIME_ROOT/startup/supervisor.py" \
  "$QWEN_RUNTIME_ROOT/startup/thread_preflight.py"
(cd "$QWEN_RUNTIME_ROOT/startup" && sha256sum start.sh stop.sh supervisor.py thread_preflight.py > SHA256SUMS)
```

The inference container must be able to read the scripts and receipt, and write to `logs/` and `run/`. The selected public image uses the default root identity in its metadata. If your organization runs it under another permitted UID, set ownership and directory permissions for that UID before deployment; also ensure its compiler/cache locations are writable. Keep permission changes confined to the new deployment directory.

Expected layout:

```text
Weight SFS root                     Runtime SFS root
/qwen36-27b/weights/                 /qwen36-27b/startup/start.sh
  config.json                       /qwen36-27b/startup/stop.sh
  model.safetensors.index.json       /qwen36-27b/startup/supervisor.py
  model-00001-of-00015...             /qwen36-27b/startup/thread_preflight.py
  tokenizer and processor files     /qwen36-27b/weights-verified.json
                                    /qwen36-27b/logs/
                                    /qwen36-27b/run/
```

The supervisor checks the cached model's file inventory before launching vLLM, records the actual package versions and arguments, sends logs to stdout and SFS, and forwards stop signals to the API server. PID files are isolated by Pod hostname. The thread preflight leaves the platform's security policy intact; it applies a narrow clone3 error-code compatibility rule only if a thread failure and inherited clone3 EPERM are actually observed. It was not needed by the reference runtime.

**Checkpoint:** All four startup files pass syntax checks, their checksums are saved, and the runtime receipt matches the weight snapshot.

## Step 7 Create the real-time service

1. Open **ModelArts → Model Inference → Real-Time Inference**.
2. Click **Deploy**.
3. Enter the service information below.
4. Choose the access route approved for your test clients. The reference profile uses private access. Public-cloud private access must be configured for your own VPC using the service's **Intranet Access Management** workflow; selecting private access alone does not establish connectivity.
5. Click **Next** to open deployment configuration. See the [public-cloud service information workflow](https://support.huaweicloud.com/intl/id-id/inference-modelarts/inference2.0-modelarts-0016.html).

| Service information field | Value |
|---|---|
| Service Name | `qwen36-27b-8a2-test` |
| Description | `Nonproduction Qwen3.6-27B BF16 chatbot, 8 A2, 262144 context` |
| Service Protocol | HTTPS |
| Authentication Mode | API KEY |
| External Network Access | Disabled for the private baseline |
| Intranet Access Without Approval | Disabled; retain your normal approval process |
| Request Size Limit | 20 MB, if supported |
| Request Timeout | 1,200 seconds, if supported |
| Requests Per Second Limit | 200 as the reference gateway cap, not a throughput claim |
| LTS Logging | Enable an approved LTS destination if required; stdout and SFS logs are always provided by the package |

If a limit is unavailable or the allowed maximum is lower, record the effective limit. Do not silently shorten the model context or claim a timeout that the platform did not save. For a public client route, deliberately configure the supported public endpoint or ELB and access policy rather than copying a private deployment's addresses.

**Checkpoint:** You are creating an independent test service with the intended protocol, authentication and client access scope.

## Step 8 Configure the deployment and cached model mount

| Deployment field | Value |
|---|---|
| Deployment Name | `deploy-qwen36-bf16-tp8` |
| Resource Pool | Your dedicated A2 inference pool |
| Deployment Replicas | 1 |
| Model Source | Custom Model |
| Model Storage Type | SFS Turbo |
| File System | `CHANGE_ME_WEIGHT_SFS` |
| File System Directory | `/qwen36-27b/weights` |
| Container Mount Path | `/model/weights` |
| Mount Mode | Read-only |
| Local Storage Acceleration | **Enabled** |

The **File System Directory** is relative to the SFS file system root. Do not enter `/mnt/qwen-weights/...` into this field: that prefix exists only on the preparation ECS.

Local storage acceleration caches weight files on the platform node. It is different from model prefix caching, which reuses computation for repeated prompts. This profile enables the former and disables the latter. If local storage acceleration is not exposed for your chosen storage/pool, report that limitation and select a supported storage path before treating the required setting as satisfied.

Keep the completed weight directory immutable during inference. New weights should use a new directory/version and a controlled deployment update; modifying the source does not guarantee that an existing local cache refreshes.

**Checkpoint:** The selected file system is the weight file system, the container path is `/model/weights`, and acceleration is enabled.

## Step 9 Configure the single inference unit

### Compute and image

| Unit field | Value |
|---|---|
| Deployment Mode | Basic Mode |
| Unit Name | `role-0` |
| Unit Instances or Replicas | 1 |
| Specification Type | Custom, if available and needed |
| NPU Count | **8** |
| CPU | 120 vCPUs for the reference allocation |
| Memory | 900,000 MiB for the reference allocation |
| Image Type | Custom Image |
| Image | Your SWR image from Step 5 |
| Environment Variables | None required in the form; `start.sh` sets the runtime environment |

If you use a preset shape, ensure it is an eight-card **A2** shape and fits the selected node's available CPU and memory. A single four-card instance or two unrelated four-card nodes does not reproduce TP8 on one node.

### Runtime file mount

1. Enable **Mount File Storage**.
2. Click **Configure** or **Modify Configuration**.
3. Under **File Storage**, add one entry.

| Mount field | Value |
|---|---|
| Storage Type | SFS Turbo |
| File System | `CHANGE_ME_RUNTIME_SFS`, distinct from the weight file system |
| File System Directory | `/qwen36-27b` |
| Container Mount Path | `/qwen-data` |
| Mount Mode | Read/Write |
| Local Storage Acceleration | Disabled for this mutable runtime mount |

4. Confirm the dialog. This mount contains logs and Pod state that must remain visible immediately; weight acceleration remains enabled on the separate model mount.

### Boot command and shutdown settings

1. Expand **Unit → More Settings**.
2. Paste this exact boot command into the command editor:

```bash
bash /qwen-data/startup/start.sh
```

3. Read the editor's displayed text to make sure it was saved correctly.
4. Set **Automatic Rebuild = Disabled**.
5. Leave **Auto Restart upon Hardware Fault = Disabled** for this initial isolated test profile, or preserve an existing approved policy when adapting the procedure.
6. Enable **Graceful Shutdown**.
7. Set **Shutdown Timeout = 1200 seconds**, subject to your platform's supported range.
8. Set the shutdown command:

```bash
bash /qwen-data/startup/stop.sh
```

9. Enable **Affinity Scheduling → Node Affinity → Strong Affinity**.
10. Select your approved idle eight-card node. If the dialog uses an **Add Node** action, add the selected row and verify the selected-node count is **1** before confirming.

The shutdown hook requests termination from the API server and waits for the supervisor to exit. Actual draining remains bounded by the platform's grace period and the server's shutdown behavior. Verify draining in Step 15 before production use.

### Runtime arguments used by the package

```text
model                       /model/weights
served-model-name           qwen3.6-27b
host                        0.0.0.0
port                        8000
tensor-parallel-size        8
data-parallel-size          1
dtype                       bfloat16
max-model-len               262144
max-num-seqs                16
max-num-batched-tokens      8192
gpu-memory-utilization      0.90
reasoning-parser            qwen3
seed                        1024
prefix caching              disabled
compilation graph mode      FULL_DECODE_ONLY
MTP                         disabled in this initial profile
quantization                none
```

These are the BF16 reference settings, not the official tutorial's W8A8/MTP performance recipe. Do not add `--quantization ascend` to official BF16 weights. Sixteen maximum active sequences is a scheduler setting, not proof that sixteen simultaneous 256K conversations meet a service-level target.

**Checkpoint:** One unit instance requests eight NPUs, uses the correct image and mounts, and has the correct boot command, disabled rebuild and enabled shutdown settings.

## Step 10 Configure health checks and deployment management

1. Enable **Health Check** and open its configuration.
2. Enable all three probes. Set the path to `/health`, with HTTP requests against the inference container's port 8000.

| Probe | Protocol | Period | Initial Delay | Timeout | Failure Threshold |
|---|---|---:|---:|---:|---:|
| Startup | HTTP | 10 s | 30 s | 5 s | 360 |
| Readiness | HTTP | 10 s | 1 s | 5 s | 3 |
| Liveness | HTTP | 30 s | 1 s | 10 s | 10 |

3. Confirm the dialog and verify all three probes appear in the summary.
4. Set **Container Protocol = HTTP** and **Container Port = 8000**. The client-facing HTTPS setting is separate from this container-side protocol.
5. Expand deployment management settings:

| Field | Value |
|---|---:|
| Deployment Timeout | 120 minutes, if accepted |
| Maximum Surge Replicas | 0% |
| Maximum Unavailable Replicas | 100% |
| Scheduling Priority | Normal/default |

This one-replica test profile allows interruption during replacement. It is not a zero-downtime production upgrade plan. Startup probes allow initial model loading and graph preparation; readiness prevents traffic before the API is available. Liveness may restart an unhealthy container even when **Automatic Rebuild** is disabled, because these mechanisms serve different purposes.

The public-cloud [single-node deployment documentation](https://support.huaweicloud.com/intl/en-us/inference-modelarts/inference2.0-modelarts-0004.html) describes these controls. Record any region-specific field names or range differences in the final checklist.

**Checkpoint:** Port, protocol, all three probes, startup timeout and replacement settings are correct.

## Step 11 Review and submit

Click **Next** and review **Confirmation**. Before clicking **Confirm Deployment**, verify:

- Correct non-production service and pool.
- Deployment replicas **1**, unit instances **1**, NPU count **8**.
- Correct ARM64 SWR image tag/digest.
- Weight SFS path `/qwen36-27b/weights` → `/model/weights`, read-only, **local acceleration enabled**.
- Runtime SFS path `/qwen36-27b` → `/qwen-data`, read/write, uncached.
- Boot command exactly `bash /qwen-data/startup/start.sh`.
- Automatic rebuild **disabled**.
- Graceful shutdown **enabled**, effective timeout saved, correct stop command.
- Strong affinity selects exactly the approved node.
- HTTP container port **8000**, three health probes, correct deployment timeout.
- Intended HTTPS client route and API key authentication.
- Rechecked node availability and approved resource cost.

Save the configuration preview or a screenshot, then click **Confirm Deployment**. Record the service ID, deployment ID, version and submission time.

**Checkpoint:** The new service is listed as **Deploying** and references the intended deployment. Do not create a second copy because initial startup takes time.

## Step 12 Wait for actual readiness

1. Open the service's **Deployment** tab.
2. Open **Replica Details** or **View Details** and inspect the Pod's node.
3. Confirm that the Pod is scheduled to the approved node.
4. Inspect **Events** for image retrieval, successful storage mounting, and container start.
5. Open **Logs**. Also inspect the runtime SFS logs from the preparation ECS:

```bash
ls -lt "$QWEN_RUNTIME_ROOT/logs"
tail -n 80 "$QWEN_RUNTIME_ROOT"/logs/runtime-*.log
```

6. Verify the actual startup record in `$QWEN_RUNTIME_ROOT/run/<pod-hostname>/launch-<timestamp>.json`.
7. Look for the actual model path, BF16 precision, TP8, 262144 context, eight worker ranks, completed graph capture and **Application startup complete**.
8. Wait until the service and deployment show **Running** and **1/1 ready**.
9. Use **Cloud Shell** in the service, when available, to inspect `npu-smi info` and call `http://127.0.0.1:8000/health` inside the selected container.

During startup, a probe can report connection refused before the server begins listening. Continue observing if loading/compilation logs are advancing and the startup window has not expired. If the process exits, a traceback occurs, or repeated OOM/HCCL errors appear, investigate instead of waiting indefinitely. The reference startup took about eight minutes; that is an observation from one environment, not an ETA for another region or image.

**Checkpoint:** All eight worker ranks belong to the intended model, and both platform readiness and the health endpoint succeed.

## Step 13 Configure the client route and API key

1. On the service page, choose **Service Calling**.
2. For private access, complete the service's **Intranet Access Management** process for your approved client VPC and verify the connection/application is effective.
3. Copy the actual invocation URL shown for that route. Public-cloud URLs can use `/v2/infers/...`, while some other environments use `/v2/infer/...`. Do not construct the URL from a private example or by guessing the hostname.
4. Open **API Key Authorization Management**.
5. Reuse an approved key that is authorized for the new service, or create a key with the intended owner, expiration and service scope. If its scope is **Specified real-time services**, bind it to this service.
6. Store the key in your client's secret manager or protected environment. The API key is separate from the SWR login and from IAM AK/SK credentials.
7. Test from a client host that can reach the selected endpoint. Keep TLS certificate verification enabled. Use your approved CA bundle if the private route uses an enterprise CA.

The new-version service uses `Authorization: Bearer <API_KEY>` as documented in [API Key Authentication](https://support.huaweicloud.com/intl/en-us/inference-modelarts/inference2.0-modelarts-0008.html).

For the examples below, `QWEN_SERVICE_ROOT` means the copied ModelArts invocation prefix **before** the container's custom paths. For example, if the copied prefix ends with the service ID, `/v1/chat/completions` is appended to that prefix. If the console presents a complete chat URL, derive the prefix by removing that exact suffix once. Do not append `/v1` twice.

```bash
export QWEN_SERVICE_ROOT='CHANGE_ME_ACTUAL_SERVICE_INVOCATION_PREFIX'
read -r -s -p 'ModelArts API key: ' QWEN_MODELARTS_API_KEY
echo
export QWEN_MODELARTS_API_KEY
```

**Checkpoint:** The client's route reaches this service and its key is authorized for this service. No old service ID or private account address has been copied.

## Step 14 Validate chatbot behavior and native context

Run the short tests first, then the long-context test. Use the same selected service throughout and do not use fallback routing.

### Model listing and ordinary chat

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $QWEN_MODELARTS_API_KEY" \
  "$QWEN_SERVICE_ROOT/v1/models"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $QWEN_MODELARTS_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @examples/chat.json \
  "$QWEN_SERVICE_ROOT/v1/chat/completions"
```

Expected: the list contains `qwen3.6-27b`; the answer to the arithmetic request is `43` with a normal stop reason.

### Streaming chat

```bash
curl --fail-with-body --silent --show-error --no-buffer \
  -H "Authorization: Bearer $QWEN_MODELARTS_API_KEY" \
  -H 'Content-Type: application/json' \
  --data-binary @examples/stream.json \
  "$QWEN_SERVICE_ROOT/v1/chat/completions"
```

Expected: incremental SSE data, readable output and a final `[DONE]` marker. Preserve Unicode and parse the stream as UTF-8.

### Complete automated functional checks

```bash
python scripts/acceptance.py \
  --service-root "$QWEN_SERVICE_ROOT" \
  --output "acceptance-short-$(date -u +%Y%m%dT%H%M%SZ)"

python scripts/acceptance.py \
  --service-root "$QWEN_SERVICE_ROOT" \
  --long \
  --output "acceptance-256k-$(date -u +%Y%m%dT%H%M%SZ)"
```

For an approved private CA, add `--ca-bundle /path/to/approved-ca.pem`. The script keeps TLS verification enabled and never saves the API key.

The checks cover ordinary chat, Portuguese/Chinese text, multi-turn memory, streaming JSON, default thinking, a request close to the configured context limit, rejection of an oversized request, missing-key rejection and post-test health. The long test uses `/tokenize` to measure the chat input before generation. If your access gateway does not forward that path, you can run the staged test through Cloud Shell inside the inference container:

```bash
python /qwen-data/acceptance.py \
  --service-root http://127.0.0.1:8000 \
  --local-container --long \
  --output "/qwen-data/local-acceptance-$(date -u +%Y%m%dT%H%M%SZ)"
```

That local test validates the runtime, skips gateway authentication checks, and does not prove that a long request passes through the external client route. Retain the short gateway tests and record the remaining route limitation. For end-to-end long-context acceptance, measure tokens with the matching local tokenizer and send the long chat request through the actual gateway.

Acceptance conditions:

| Check | Pass condition |
|---|---|
| Platform | Running, 1/1 ready |
| Devices and topology | Eight ranks, TP8 / DP1 |
| Model listing | Alias is present; effective max context is 262144 |
| Ordinary and multi-turn chat | Correct final text, normal finish reason |
| Streaming | Non-empty valid UTF-8 output and `[DONE]` |
| Thinking | Reasoning and final answer are returned separately |
| Long context | At least 261,000 measured input tokens, correct marker response, no OOM |
| Over-context input | HTTP 400 |
| Missing API key | HTTP 401 or 403 on the authenticated ModelArts route |
| After the requests | Health returns 200 and the service remains ready |

The reference accepted **261,797 input tokens** and returned the correct marker; it also passed chat, multi-turn, streaming Unicode JSON, thinking, over-context rejection and missing-key rejection. These observations apply to the recorded reference runtime. Repeat the checks in the new region and selected public image. This is functional acceptance, not a QPS, latency, concurrency or production-quality benchmark.

**Checkpoint:** Preserve the acceptance JSON files, runtime log and selected image digest. Stop handover if a required check fails.

## Step 15 Verify shutdown and recovery before production use

For a controlled non-production drill:

1. Save the current configuration, script checksums, weight receipt, image digest and acceptance output.
2. Stop sending new client requests. For a draining test, keep one small, bounded synthetic request active and record its completion or interruption.
3. In **Deployment**, select only this Qwen test deployment and click **Stop**.
4. Observe the runtime log for signal forwarding and server shutdown. Confirm the process exits within the saved grace period and the allocation is released or stopped according to the platform.
5. Start the same saved deployment version. Before submission, recheck local weight acceleration, graceful shutdown and disabled automatic rebuild.
6. Wait for 1/1 readiness, inspect actual ranks and repeat the short chat/stream checks.
7. Record elapsed recovery time and whether the local model cache was reused. A changed/destroyed node may need to reload the weights.

The reference deployment was later stopped after documentation was completed, with zero running and queued requests. Its supervisor forwarded the termination signal and the API process exited with code 0. The engine log also showed an internal abort shutdown timeout of zero and force cleanup of a remaining process. A restart/recovery drill and an in-flight-request draining drill were not executed. Therefore the enabled platform grace period is not proof that every in-flight request survives the selected runtime's shutdown; validate draining separately before production use.

For a first deployment with no previous version, rollback means stopping the new Qwen service and retaining its evidence; no existing chatbot endpoint is switched by this procedure. For a later upgrade, retain the old immutable image, weight directory and scripts, and restore that saved version if the candidate fails acceptance. Stopping a deployment does not necessarily stop billing for its resource pool or storage.

**Checkpoint:** The operating team understands and, where required, has demonstrated shutdown, restart and rollback on the new environment.

## Step 16 Troubleshoot by the failing layer

| Symptom | Check and corrective action |
|---|---|
| A2 or new-version inference is unavailable | Resolve region, quota and product availability. Do not apply this recipe to another accelerator family without redesigning it. |
| SFS Turbo is absent from the selector | Verify the dedicated pool, same region, eligible file system type, agency and network association. |
| Mount rejected or PVC stays unbound | Confirm both associations and directories. Use distinct file systems and non-nested mount paths. |
| Eight cards cannot be scheduled | Recheck available NPUs, CPU and RAM on the affinity node. A preset's requested CPU may exceed current allocatable CPU. |
| `exec format error` | The image/host architecture is wrong. Select ARM64 for the A2 pool. |
| Image cannot be pulled | Check the regional SWR address, repository permissions, pool connectivity and disk capacity. |
| Receipt or startup file missing | Verify that runtime SFS `/qwen36-27b` is mounted at `/qwen-data` and the receipt was copied after verification. |
| Cached model inventory mismatch | Check weight source and cached contents. Preserve evidence and refresh through a controlled deployment update; do not edit cached weight files in place. |
| Port remains closed while logs advance | Allow loading and graph capture within the configured startup window. |
| OOM, unsupported operator, HCCL failure | Preserve all rank logs and check image/driver compatibility. Do not hide the failure by reducing the promised context without an explicit change of scope. |
| Thread creation fails | Inspect the preflight result and exact errno. The bundled compatibility branch is conditional; do not disable the platform's seccomp protection. |
| CPU NUMA binding is skipped | Record the warning and check allowed CPU/NUMA placement. Functional success does not establish that CPU placement is optimal. |
| Platform Running but chat fails | Verify readiness, health, gateway route, API key binding, actual alias and container protocol/port. |
| HTTP 404 | Check the copied invocation URL, singular/plural path, service ID, service version and readiness. Do not assume the model is missing based only on a gateway error. |
| HTTP 401 or 403 | Check key expiration, owner and service scope/binding. Do not substitute IAM AK/SK or SWR credentials. |
| TLS verification error | Use the correct endpoint hostname and approved CA. Do not make `curl -k` or disabled certificate validation the deployment default. |
| Output is truncated | Check finish reason and output budget, including reasoning tokens. A transport 200 does not prove a complete answer. |
| Long request exceeds the gateway timeout | Check the effective gateway/client timeout; record the constraint separately from the model's context capability. |
| Changed SFS weights are not visible | A local model cache can remain stale. Use a new immutable source directory/version and a controlled update. |

## Step 17 Complete the handover record

Fill in `FINAL_CHECKLIST.md` and retain:

- Service/deployment IDs, version, region and client invocation URL.
- Selected node, hardware family, driver, eight-rank topology and actual package versions.
- Source and SWR image digests, weight revision, verification receipt and startup checksums.
- Effective model and runtime mounts, permissions and acceleration values.
- Effective shutdown setting/command, automatic rebuild setting, probes and timeouts.
- Short, streaming, thinking and long-context acceptance output.
- Authentication and oversized-input negative results.
- Log locations, ownership, retention, restart/rollback instructions and unresolved constraints.

Keep API keys and login credentials outside this record. The deployment is ready for non-production chatbot use when the required functional checks pass. Establish workload-specific concurrency and performance limits separately before production traffic.

## Appendix A Complete weight download addresses

All addresses below refer to the same immutable official snapshot. The list contains all 29 files; 15 are model weight shards. The complete download and SHA256 verification procedure is in Step 4.

| File | Bytes | Direct fixed revision download |
|---|---:|---|
| `.gitattributes` | 1,570 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/.gitattributes) |
| `LICENSE` | 11,343 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/LICENSE) |
| `README.md` | 62,593 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/README.md) |
| `chat_template.jinja` | 7,764 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/chat_template.jinja) |
| `config.json` | 4,308 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/config.json) |
| `configuration.json` | 51 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/configuration.json) |
| `generation_config.json` | 202 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/generation_config.json) |
| `merges.txt` | 3,353,259 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/merges.txt) |
| `model-00001-of-00015.safetensors` | 3,968,861,352 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00001-of-00015.safetensors) |
| `model-00002-of-00015.safetensors` | 3,921,677,136 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00002-of-00015.safetensors) |
| `model-00003-of-00015.safetensors` | 3,921,677,128 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00003-of-00015.safetensors) |
| `model-00004-of-00015.safetensors` | 3,921,677,128 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00004-of-00015.safetensors) |
| `model-00005-of-00015.safetensors` | 3,921,677,112 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00005-of-00015.safetensors) |
| `model-00006-of-00015.safetensors` | 3,900,710,888 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00006-of-00015.safetensors) |
| `model-00007-of-00015.safetensors` | 3,994,391,976 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00007-of-00015.safetensors) |
| `model-00008-of-00015.safetensors` | 3,879,219,776 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00008-of-00015.safetensors) |
| `model-00009-of-00015.safetensors` | 3,921,677,136 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00009-of-00015.safetensors) |
| `model-00010-of-00015.safetensors` | 3,921,677,128 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00010-of-00015.safetensors) |
| `model-00011-of-00015.safetensors` | 3,921,677,136 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00011-of-00015.safetensors) |
| `model-00012-of-00015.safetensors` | 3,921,677,136 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00012-of-00015.safetensors) |
| `model-00013-of-00015.safetensors` | 3,995,081,848 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00013-of-00015.safetensors) |
| `model-00014-of-00015.safetensors` | 3,942,652,952 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00014-of-00015.safetensors) |
| `model-00015-of-00015.safetensors` | 508,670,568 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model-00015-of-00015.safetensors) |
| `model.safetensors.index.json` | 112,216 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/model.safetensors.index.json) |
| `preprocessor_config.json` | 390 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/preprocessor_config.json) |
| `tokenizer.json` | 12,807,982 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/tokenizer.json) |
| `tokenizer_config.json` | 16,718 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/tokenizer_config.json) |
| `video_preprocessor_config.json` | 385 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/video_preprocessor_config.json) |
| `vocab.json` | 6,722,759 | [Download](https://huggingface.co/Qwen/Qwen3.6-27B/resolve/6a9e13bd6fc8f0983b9b99948120bc37f49c13e9/vocab.json) |

`WEIGHT_DOWNLOAD_URLS.txt` contains the same complete URLs as plain text. Published weight-shard hashes are checked by the downloader; the verification receipt records SHA256 for every downloaded file.

## Appendix B Complete console option selection checklist

Use this checklist alongside the deployment wizard. It specifies selections for the isolated eight-card BF16 chatbot baseline, including fields that should stay blank or disabled. Labels vary slightly by region and console release. Hidden dependent controls do not need to be filled when their parent option is disabled. If your console exposes an additional mandatory field, resolve its platform requirement rather than guessing.

### Before entering the deployment wizard

| Console option | Select or enter | How to verify |
|---|---|---|
| Region | Your approved region with A2 inference capacity | ModelArts, SWR and both SFS file systems use that region |
| Project or workspace | Your authorized non-production project/workspace | Resources are visible in that scope |
| ModelArts product | ModelArts Standard | New-version real-time inference workflow is available |
| Inference service version | New version | Do not select the legacy online-service workflow |
| Resource pool | Dedicated A2 pool | One node has eight available NPUs |
| Resource pool network | Network belonging to the selected pool | Both SFS associations are effective |
| SFS association | Weight SFS and runtime SFS | Distinct file systems, Associated status |
| SWR organization/repository | Your organization and `qwen36-vllm-ascend` | ARM64 image pushed and digest recorded |

### Service information page

| Console option | Select or enter | Notes |
|---|---|---|
| Service Name | `qwen36-27b-8a2-test` | Use a unique name if this already exists |
| Description | `Nonproduction Qwen3.6-27B BF16 chatbot, 8 A2, 262144 context` | Plain descriptive text |
| Service Access Type | Default | Do not select a custom ELB route unless it has been separately configured |
| Service Protocol | HTTPS | Client-facing protocol |
| Authentication Mode | API KEY | Do not choose No Authentication; IAM Token would require a different client setup |
| Network More Settings | Expand and review | Do not rely only on collapsed summaries |
| Dedicated Channel / Direct Channel | Unchecked | Baseline uses the normal approved private invocation route |
| External Network Access | Unchecked | Private baseline; select only when intentionally deploying a public client route |
| Intranet Access Without Approval | Unchecked | Preserve normal connection approvals |
| Access Control switch | Unchecked for the baseline | An approved existing whitelist policy should be preserved rather than removed |
| Whitelist / blacklist fields | Leave unset while Access Control is disabled | Populate only for a deliberately configured access policy |
| Availability More Settings | Expand | Review all request limits |
| Requests Per Second Limit | `200` if allowed | Gateway cap, not guaranteed model QPS |
| Request Size Limit | `20` MB if allowed | Save the actual platform-accepted limit |
| Request Timeout | `1200` seconds if allowed | Save the actual platform-accepted limit |
| Advanced Settings | Expand and review | Optional settings are not silently enabled |
| Connect Logs to LTS | Unchecked for the minimal baseline | If enabled, choose an approved LTS destination and retention policy |
| LTS group / stream fields | Not configured while LTS is disabled | Do not create unrelated log resources |
| Tags | Leave empty, or add required organization tags | For example, an approved non-production classification |
| Only Create Service button | Do not use for the main procedure | It creates service information without the inference deployment |
| Next button | Select after reviewing service settings | Continue to Deployment Settings |

### Deployment basics and model configuration

| Console option | Select or enter | Notes |
|---|---|---|
| Deployment Name | `deploy-qwen36-bf16-tp8` | Independent deployment |
| Deployment Description | `Official BF16 Qwen3.6-27B, TP8, chatbot, native 262144 context` | Optional; do not put secrets here |
| Resource Pool selector | Your approved dedicated A2 pool | Review available NPU/CPU/memory numbers |
| Deployment Replicas | `1` | One node for this baseline |
| Model Source | Custom Model | Not a preset/other model |
| Model Storage Type | SFS Turbo | Main procedure uses the weight file system |
| Weight File System | Your weight SFS | Different from runtime SFS |
| Weight File System Directory | `/qwen36-27b/weights` | Relative to file system root, not an ECS mount prefix |
| Weight Container Mount Path | `/model/weights` | Matches supervisor argument |
| Weight Mount Mode | Read-only | The inference engine must not edit the snapshot |
| Weight Local Storage Acceleration | Enabled | Platform weight cache; independent of model prefix caching |
| Additional Models / Add Model | Do not add another model | One complete snapshot is used |
| Pre-warmed Model option | Do not select for this procedure | Requires a separate prewarming process |
| Model preheating URL, if shown | Leave empty for this baseline | Do not invent a URL or copy one from another service |

### Unit compute and image configuration

| Console option | Select or enter | Notes |
|---|---|---|
| Deployment Mode | Basic Mode | Do not select Multi-role / PD Disaggregation |
| Unit Name | `role-0` | One unit hosts the full service |
| Specification Type | Custom if needed and available | Preset is acceptable only if it is eight-card A2 and fits the node |
| NPU Cards | `8` | Not 4 and not 8 replicas of a one-card shape |
| CPU | `120` vCPUs | Reference allocation; must fit available CPU |
| Memory | `900000` MiB | Reference allocation; must fit available RAM |
| Unit Instances / Replicas | `1` | Total allocation remains one eight-card node |
| Preset Flavor, when using Custom | Not applicable | Do not also select a conflicting preset |
| Image Type | Custom Image | Not Preset Image or Resource Pool Pre-warmed Image |
| Image Source | SWR → your repository → selected ARM64 tag | Use the artifact prepared in Step 5 |
| Image tag/digest | Your fixed SWR tag/digest | Record the exact manifest; do not select an arbitrary latest/nightly tag |
| Environment Variables | Leave empty in the form | `start.sh` sets all required environment variables |
| Add Environment Variable button | No entries for this baseline | Do not place API keys here |
| Local Upload of Environment Variables | Do not use | No separate environment file is required |

### File storage configuration dialog

| Console option | Select or enter | Notes |
|---|---|---|
| Mount File Storage switch | Checked | Startup files and live logs require this mount |
| Modify Configuration | Open | Review the saved mount entry |
| File Storage → Add | Add exactly one runtime mount | Model mount is configured separately |
| Runtime Storage Type | SFS Turbo | Main procedure uses runtime SFS |
| Runtime File System | Your runtime SFS | Distinct from weight SFS |
| Runtime File System Directory | `/qwen36-27b` | Contains startup, receipt, logs and run directories |
| Runtime Container Mount Path | `/qwen-data` | Matches boot and shutdown commands |
| Runtime Mount Mode | Read/Write | Logs and per-Pod PID state are written here |
| Runtime Local Storage Acceleration | Disabled | Keep live logs and mutable state directly on SFS |
| Additional File Storage entries | None | Do not add unnecessary or nested mounts |
| Artifact Dumping → Add | No entry | Supervisor already writes logs to the runtime mount |
| Confirm in the dialog | Select after verifying the entry | The summary must show one runtime mount |

### Unit More Settings and affinity dialog

| Console option | Select or enter | Notes |
|---|---|---|
| Unit More Settings | Expand | Review both command editors and every switch |
| Boot Command | `bash /qwen-data/startup/start.sh` | Copy exactly; no nested Docker command |
| Automatic Rebuild | Unchecked | Required deployment default |
| Rebuild Policy / Strategy | Not configured because rebuild is disabled | Do not select Deployment Replica / Unit / Pod rebuild policies |
| Auto Restart upon Hardware Fault | Unchecked for this isolated initial baseline | Preserve an existing approved policy if adapting a service |
| Graceful Shutdown | Checked | Required deployment default |
| Shutdown Timeout | `1200` seconds if allowed | Record the saved effective value |
| Shutdown Command | `bash /qwen-data/startup/stop.sh` | Full script appears in Appendix C |
| Affinity Scheduling | Checked | Choose an approved non-production node |
| Affinity Type | Node Affinity | Not Node Anti-affinity |
| Affinity Strength | Strong Affinity | Not Weak Affinity for this fixed-node baseline |
| Selected Node | Your idle eight-card A2 node | Node name comes from your pool; no private example IP is supplied |
| Add Node action, if present | Add the selected row | Merely highlighting a row may not add it |
| Selected-node count | `1` | Recheck before confirming the dialog |
| Specify Container Running User ID | Unchecked for the selected image's default root identity | If policy mandates a different UID, configure it explicitly and fix scoped ownership/cache permissions |
| Container UID field while switch is disabled | Not configured | No guessed UID |

### Health check dialog

Enable HTTP Request Check for all three probes. Do not choose Execute Command Check for this baseline. Each probe uses the container's HTTP port 8000.

| Option | Startup probe | Readiness probe | Liveness probe |
|---|---|---|---|
| Enable switch | Checked | Checked | Checked |
| Check Method | HTTP Request Check | HTTP Request Check | HTTP Request Check |
| Health URL | `/health` | `/health` | `/health` |
| Health Command field | Not applicable | Not applicable | Not applicable |
| Protocol | HTTP | HTTP | HTTP |
| Period in seconds | `10` | `10` | `30` |
| Initial delay in seconds | `30` | `1` | `1` |
| Timeout in seconds | `5` | `5` | `10` |
| Failure threshold | `360` | `3` | `10` |

After confirmation, the unit summary must list Startup, Readiness and Liveness. Do not assume that checking the parent Health Check switch saved the three probe definitions.

### Deployment management and advanced settings

| Console option | Select or enter | Notes |
|---|---|---|
| Container Protocol | HTTP | Separate from client-facing HTTPS |
| Container Port | `8000` | Do not use the image documentation's generic 8080 example |
| Deployment Management More Settings | Expand | Review timing and replacement limits |
| Deployment Timeout | `120` minutes if allowed | Record any lower effective platform limit |
| Maximum Surge Replicas | `0` percent | Avoid allocating an additional eight-card replacement Pod |
| Maximum Unavailable Replicas | `100` percent | This single-replica test allows an interruption during replacement |
| Scheduling Priority | Default / `1` where this scale is shown | Do not raise priority to preempt another workload |
| Secret Configuration switch, if present | Unchecked for this SFS-only, offline-model startup baseline | If the platform requires a storage credential, use its approved agency/DEW workflow instead of disabling that requirement |
| Secret bindings/paths while switch is disabled | None | API key remains on the caller side |
| System Log Reporting | Unchecked for the minimal baseline | Stdout and runtime SFS logs remain available |
| Additional Deployment / Unit entries | None | Exactly one deployment and one unit are used |
| Confirmation page | Review all saved values | Especially both cache values, shutdown, rebuild and counts |
| Confirm Deployment button | Select only after the review | Record service ID, deployment ID, version and time |

### After deployment

| Console option | Select or enter | Notes |
|---|---|---|
| Service status | Running | Must also have a ready inference replica |
| Deployment status | Running, `1/1` ready | Do not rely solely on the service banner |
| Traffic Weight | `100` for this service's only deployment | Does not mean production traffic was switched |
| Image/Mirror Traffic | Disabled | No mirror deployment is configured |
| Automatic Scaling | Not configured | Start with one fixed test replica |
| Intranet Access Management | Configure/approve only the intended client route | Verify connection/application status |
| API Key Authorization Scope | Specified real-time service(s), or an approved existing scope | Bind the key to this service when required |
| API Key expiration/name/owner | Approved organization values | No reusable secret is embedded in the guide |
| Service Calling URL | Copy the exact current invocation URL | Do not guess singular/plural URL paths |
| Stop | Select this Qwen deployment when ending the test | Wait for Stopped and zero ready replicas; retain weights/scripts |
| Delete | Do not select as part of stopping | Deletion is a separate resource-management action |

## Appendix C Complete deployment script source

The following code blocks are complete copies of the distributed script files. Prefer the files from the ZIP, verify `SHA256SUMS`, and use Step 6 to stage them. The included startup and stop hooks use the portable public-cloud paths; they do not depend on a private account, registry, IP address or secret file.

### scripts/download_weights.py

```python
#!/usr/bin/env python3
"""Download and verify the pinned official Qwen3.6-27B snapshot."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import requests

REPO = 'Qwen/Qwen3.6-27B'
REVISION = '6a9e13bd6fc8f0983b9b99948120bc37f49c13e9'
EXPECTED_BYTES = 55586107940

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error('--workers must be between 1 and 16')
    root = args.root.resolve()
    weights = root / 'weights'
    weights.mkdir(parents=True, exist_ok=True)
    response = requests.get(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=60)
    response.raise_for_status()
    manifest = response.json()
    if manifest['sha'] != REVISION or sum(x['size'] for x in manifest['siblings']) != EXPECTED_BYTES:
        raise RuntimeError('Pinned snapshot manifest does not match the reference inventory')
    (root / 'weight-manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'MANIFEST {REVISION} {len(manifest["siblings"])} files {EXPECTED_BYTES} bytes', flush=True)
    if args.metadata_only:
        return
    # An old success receipt must not survive a failed repeat verification.
    receipt = root / 'weights-verified.json'
    if receipt.exists():
        os.replace(receipt, root / 'weights-verified.previous.json')

    def get_file(item):
        name, size = item['rfilename'], item['size']
        target = weights / name
        if not target.resolve().is_relative_to(weights.resolve()):
            raise RuntimeError('Unsafe manifest path')
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.incomplete')
        expected = item.get('lfs', {}).get('sha256')
        candidate = target
        if not target.exists() or target.stat().st_size != size:
            candidate = partial
            for attempt in range(6):
                try:
                    offset = partial.stat().st_size if partial.exists() else 0
                    if offset > size:
                        raise RuntimeError(f'Oversized partial file: {partial}; inspect before repairing')
                    if offset == size:
                        break
                    headers = {'Range': f'bytes={offset}-'} if offset else {}
                    with requests.get(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}', headers=headers, stream=True, timeout=(30, 120)) as result:
                        result.raise_for_status()
                        if offset and result.status_code == 206:
                            actual = result.headers.get('Content-Range', '').split(' ')[-1].split('-')[0]
                            if actual != str(offset):
                                raise RuntimeError('Unexpected Content-Range; partial file preserved')
                        elif offset:
                            offset = 0  # Server ignored Range: safely replace the partial byte stream.
                        with partial.open('ab' if offset else 'wb') as output:
                            for chunk in result.iter_content(8 * 1024 * 1024):
                                output.write(chunk)
                    if partial.stat().st_size != size:
                        raise RuntimeError(f'Incomplete size for {name}: {partial.stat().st_size}/{size}')
                    break
                except Exception as error:
                    print('RETRY', name, attempt + 1, type(error).__name__, flush=True)
                    if attempt == 5:
                        raise
                    time.sleep(3)
        digest = hashlib.sha256()
        with candidate.open('rb') as source:
            for chunk in iter(lambda: source.read(16 * 1024 * 1024), b''):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected and actual != expected:
            raise RuntimeError(f'SHA256 mismatch for {candidate}; do not deploy this snapshot')
        if candidate == partial:
            os.replace(partial, target)
        print('VERIFIED', name, size, actual, flush=True)
        return {'file': name, 'bytes': size, 'sha256': actual, 'published_sha256_checked': bool(expected)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        files = list(pool.map(get_file, manifest['siblings']))
    index = json.loads((weights / 'model.safetensors.index.json').read_text())
    if not all((weights / name).is_file() for name in set(index['weight_map'].values())):
        raise RuntimeError('Incomplete weight index')
    if list(weights.rglob('*.incomplete')):
        raise RuntimeError('Unfinished downloads remain')
    result = {'revision': REVISION, 'files': files, 'total_bytes': sum(x['bytes'] for x in files), 'complete': True}
    temporary = root / 'weights-verified.json.tmp'
    temporary.write_text(json.dumps(result, indent=2))
    os.replace(temporary, receipt)
    print('COMPLETE', len(files), result['total_bytes'], flush=True)

if __name__ == '__main__':
    main()
```

### scripts/inspect_image.py

```python
#!/usr/bin/env python3
"""Metadata inspection inside the selected inference image; no model start."""
import importlib.metadata
import importlib.util
import json
import platform
from pathlib import Path
versions = {}
for name in ['vllm', 'vllm-ascend', 'torch', 'torch-npu', 'transformers']:
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = 'MISSING'
spec = importlib.util.find_spec('vllm')
registry_found = False
if spec and spec.submodule_search_locations:
    registry = Path(next(iter(spec.submodule_search_locations))) / 'model_executor/models/registry.py'
    registry_found = registry.is_file() and 'Qwen3_5ForConditionalGeneration' in registry.read_text()
facts = {'architecture': platform.machine(), 'versions': versions,
         'qwen_architecture_in_registry': registry_found}
print(json.dumps(facts, indent=2))
if platform.machine() not in ['aarch64', 'arm64'] or 'MISSING' in versions.values() or not registry_found:
    raise SystemExit('Image metadata inspection failed')
```

### startup/start.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
for f in /usr/local/Ascend/ascend-toolkit/set_env.sh /usr/local/Ascend/nnal/atb/set_env.sh; do
  if [[ -f "$f" ]]; then set +u; source "$f"; set -u; fi
done
export PYTHONUNBUFFERED=1
export HCCL_BUFFSIZE=512
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export OMP_NUM_THREADS=8
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export OTEL_SDK_DISABLED=true
exec python /qwen-data/startup/supervisor.py
```

### startup/supervisor.py

```python
"""ModelArts-native vLLM process and stdout/file log supervisor."""
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from thread_preflight import ensure_threads

ROOT = Path('/qwen-data')
HOST = os.uname().nodename
RUN = ROOT / 'run' / HOST
RUN.mkdir(parents=True, exist_ok=True)
verified = json.loads((ROOT / 'weights-verified.json').read_text())
if not verified.get('complete') or verified['revision'] != '6a9e13bd6fc8f0983b9b99948120bc37f49c13e9':
    raise RuntimeError('Pinned snapshot verification receipt is missing or invalid')
for item in verified['files']:
    path = Path('/model/weights') / item['file']
    if not path.is_file() or path.stat().st_size != item['bytes']:
        raise RuntimeError(f'Cached weight inventory mismatch: {path}')
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
log = (ROOT / 'logs' / f'runtime-{stamp}-{HOST}.log').open('a', buffering=1)
def emit(line):
    print(line, end='', flush=True)
    log.write(line)
    log.flush()
args = [sys.executable, '-m', 'vllm.entrypoints.openai.api_server',
        '--model', '/model/weights', '--served-model-name', 'qwen3.6-27b',
        '--host', '0.0.0.0', '--port', '8000', '--tensor-parallel-size', '8',
        '--data-parallel-size', '1', '--dtype', 'bfloat16', '--max-model-len', '262144',
        '--max-num-seqs', '16', '--max-num-batched-tokens', '8192',
        '--gpu-memory-utilization', '0.90', '--no-enable-prefix-caching',
        '--reasoning-parser', 'qwen3', '--seed', '1024',
        '--compilation-config', '{"cudagraph_mode":"FULL_DECODE_ONLY"}']
versions = {}
for name in ['vllm', 'vllm-ascend', 'torch', 'torch-npu', 'transformers']:
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = 'missing'
facts = {'started_utc': stamp, 'args': args, 'versions': versions, 'hostname': HOST,
         'pod_ip': os.environ.get('POD_IP'), 'required_context': 262144,
         'required_npus': 8, 'quantization': None, 'mtp': False,
         'thread_preflight': ensure_threads()}
(RUN / f'launch-{stamp}.json').write_text(json.dumps(facts, indent=2))
emit(json.dumps(facts) + '\n')
(RUN / 'supervisor.pid').write_text(str(os.getpid()))
subprocess.run(['npu-smi', 'info'], stdout=log, stderr=log, check=False)
child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, start_new_session=True)
(RUN / 'engine-parent.pid').write_text(str(child.pid))
def forward(signum, frame):
    emit(f'SHUTDOWN forwarding signal {signum} to API server {child.pid}\n')
    try:
        child.send_signal(signum)
    except ProcessLookupError:
        pass
signal.signal(signal.SIGTERM, forward)
signal.signal(signal.SIGINT, forward)
for line in child.stdout:
    emit(line)
code = child.wait()
emit(f'ENGINE_EXIT {code}\n')
sys.exit(code)
```

### startup/thread_preflight.py

```python
"""Probe thread creation; add an errno-only clone3 deny rule if required.

Existing seccomp rules remain active. The denied syscall remains denied.
No compatibility filter is applied when threads already work.
"""
import ctypes, errno, platform, threading

def probe():
    worker=threading.Thread(target=lambda:None)
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), 'thread probe did not complete'

def ensure_threads():
    try:
        probe()
        return {'thread_probe':'passed','compatibility_filter_applied':False}
    except RuntimeError:
        if platform.machine() not in ('aarch64','arm64'):raise
    libc=ctypes.CDLL(None,use_errno=True)
    libc.syscall.restype=ctypes.c_long
    libc.prctl.restype=ctypes.c_int
    libc.prctl.argtypes=[ctypes.c_int]+[ctypes.c_ulong]*4
    ctypes.set_errno(0)
    result=libc.syscall(ctypes.c_long(435),ctypes.c_void_p(0),ctypes.c_size_t(88))
    before=ctypes.get_errno()
    if (result,before)!=(-1,errno.EPERM):
        raise RuntimeError(f'Thread failure is not verified clone3 EPERM: {result}/{before}')
    class Filter(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    rules=(Filter*6)(Filter(0x20,0,0,4),Filter(0x15,0,3,0xC00000B7),Filter(0x20,0,0,0),Filter(0x15,0,1,435),Filter(0x06,0,0,0x00050000|errno.ENOSYS),Filter(0x06,0,0,0x7FFF0000))
    program=Program(len(rules),rules)
    assert libc.prctl(38,1,0,0,0)==0,'no_new_privs failed'
    assert libc.prctl(22,2,ctypes.addressof(program),0,0)==0,'additive deny filter failed'
    ctypes.set_errno(0)
    result=libc.syscall(ctypes.c_long(435),ctypes.c_void_p(0),ctypes.c_size_t(88))
    after=ctypes.get_errno()
    assert (result,after)==(-1,errno.ENOSYS)
    probe()
    return {'thread_probe':'passed','compatibility_filter_applied':True,'clone3_errno_before':before,'clone3_errno_after':after,'inherited_seccomp':'preserved','clone3':'still denied'}
```

### startup/stop.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
pidfile="/qwen-data/run/$(hostname)/supervisor.pid"
if [[ ! -f "$pidfile" ]]; then exit 0; fi
pid=$(cat "$pidfile")
if ! [[ "$pid" =~ ^[0-9]+$ ]]; then echo 'Invalid supervisor PID' >&2; exit 1; fi
if ! kill -0 "$pid" 2>/dev/null; then exit 0; fi
if ! tr '\0' ' ' < "/proc/$pid/cmdline" | grep -Fq '/qwen-data/startup/supervisor.py'; then
  echo 'PID does not refer to this deployment supervisor; stop hook refused' >&2
  exit 1
fi
kill -TERM "$pid"
while kill -0 "$pid" 2>/dev/null; do sleep 1; done
```

### scripts/acceptance.py

```python
#!/usr/bin/env python3
"""Functional chatbot smoke checks; no performance or quality benchmark."""
import argparse
import datetime
import json
import os
from pathlib import Path
import time
import requests

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-root', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--long', action='store_true')
    parser.add_argument('--ca-bundle', type=Path)
    parser.add_argument('--local-container', action='store_true', help='Use only for an authorized container-local route; skips gateway authentication checks')
    args = parser.parse_args()
    base = args.service_root.rstrip('/')
    if 'CHANGE_ME' in base or not base.startswith(('https://', 'http://')) or base.endswith('/v1'):
        parser.error('Provide the actual invocation prefix, before custom /v1 paths')
    if not args.local_container and not base.startswith('https://'):
        parser.error('Use the HTTPS ModelArts invocation route; HTTP is permitted only for an authorized container-local test')
    key = os.environ.get('QWEN_MODELARTS_API_KEY')
    if not args.local_container and not key:
        parser.error('Set QWEN_MODELARTS_API_KEY without placing it in a command argument')
    if args.ca_bundle and not args.ca_bundle.is_file():
        parser.error('CA bundle does not exist')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    session.verify = str(args.ca_bundle) if args.ca_bundle else True
    if key:
        session.headers['Authorization'] = 'Bearer ' + key
    model = 'qwen3.6-27b'
    results = []

    def save(name, data):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def post(path, body, timeout=1200):
        start = time.monotonic()
        response = session.post(base + path, json=body, timeout=timeout)
        response.raise_for_status()
        return response.json(), time.monotonic() - start

    assert session.get(base + '/health', timeout=20).status_code == 200
    response = session.get(base + '/v1/models', timeout=20)
    response.raise_for_status()
    models = response.json()
    save('models.json', models)
    entry = next(x for x in models['data'] if x['id'] == model)
    if entry.get('max_model_len') is not None:
        assert entry['max_model_len'] == 262144, entry
    results.append({'case': 'model_listing', 'passed': True, 'reported_context': entry.get('max_model_len')})
    cases = [
        ('basic', [{'role': 'user', 'content': 'Return only the integer result of 19 + 24.'}], '43'),
        ('unicode', [{'role': 'user', 'content': 'Copy exactly this text without quotes or commentary: Olá, Brasil! 你好！'}], 'Olá, Brasil! 你好！'),
        ('multiturn', [{'role': 'system', 'content': 'You are a helpful chatbot. Answer concisely.'},
                       {'role': 'user', 'content': 'My favorite color is turquoise.'},
                       {'role': 'assistant', 'content': 'I will remember turquoise.'},
                       {'role': 'user', 'content': 'What is my favorite color? Return only its name.'}], 'turquoise')
    ]
    for name, messages, expected in cases:
        data, elapsed = post('/v1/chat/completions', {'model': model, 'messages': messages,
                              'max_tokens': 256, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}})
        save(name + '.json', data)
        answer = data['choices'][0]['message']['content'].strip()
        assert answer.strip('"').lower() == expected.lower(), (name, answer)
        assert data['choices'][0]['finish_reason'] == 'stop'
        results.append({'case': name, 'passed': True, 'seconds': elapsed, 'usage': data.get('usage')})

    body = {'model': model, 'messages': [{'role': 'user', 'content': 'Return exactly this JSON with no formatting: {"answer":43,"text":"Olá 你好"}'}],
            'max_tokens': 256, 'temperature': 0, 'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    start = time.monotonic()
    with session.post(base + '/v1/chat/completions', json=body, stream=True, timeout=1200) as response:
        response.raise_for_status()
        answer, done, events = '', False, []
        for line in response.iter_lines():
            if not line.startswith(b'data: '):
                continue
            payload = line[6:].decode('utf-8')
            if payload == '[DONE]':
                done = True
                break
            event = json.loads(payload)
            events.append(event)
            for choice in event.get('choices', []):
                answer += choice.get('delta', {}).get('content') or ''
    save('stream.json', {'events': events, 'done': done, 'content': answer})
    assert done and json.loads(answer) == {'answer': 43, 'text': 'Olá 你好'}
    results.append({'case': 'stream_unicode_json', 'passed': True, 'seconds': time.monotonic() - start})

    data, elapsed = post('/v1/chat/completions', {'model': model,
                        'messages': [{'role': 'user', 'content': 'What is 7 plus 8? Give only the final integer.'}],
                        'max_tokens': 512, 'temperature': 0})
    save('default-thinking.json', data)
    message = data['choices'][0]['message']
    assert message['content'].strip() == '15'
    assert message.get('reasoning') or message.get('reasoning_content'), 'Default reasoning field is empty'
    assert data['choices'][0]['finish_reason'] == 'stop'
    results.append({'case': 'default_thinking', 'passed': True, 'seconds': elapsed, 'usage': data.get('usage')})

    if args.long:
        def messages(n):
            return [{'role': 'user', 'content': 'Read this filler document.\n' + (' neutral text.' * n) +
                     '\nThe secret marker is QWEN256KOK. Return only the secret marker.'}]
        n = 85000
        for attempt in range(5):
            tokens, _ = post('/tokenize', {'model': model, 'messages': messages(n),
                             'add_generation_prompt': True, 'chat_template_kwargs': {'enable_thinking': False}})
            count = tokens['count']
            save(f'long-token-count-{attempt}.json', {'repetitions': n, 'count': count})
            if 261000 <= count <= 262016:
                break
            n = int(n * (261800 / max(count, 1)))
        assert 261000 <= count <= 262016, count
        data, elapsed = post('/v1/chat/completions', {'model': model, 'messages': messages(n),
                             'max_tokens': 128, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}})
        save('long-context.json', data)
        assert data['choices'][0]['message']['content'].strip() == 'QWEN256KOK'
        assert data['choices'][0]['finish_reason'] == 'stop'
        assert data['usage']['prompt_tokens'] >= 261000
        results.append({'case': 'near_262144_context', 'passed': True, 'seconds': elapsed, 'usage': data['usage']})
        rejected = session.post(base + '/v1/chat/completions', json={'model': model, 'messages': messages(n + 1000),
                                'max_tokens': 128, 'chat_template_kwargs': {'enable_thinking': False}}, timeout=120)
        save('over-context.json', {'http': rejected.status_code, 'response': rejected.json()})
        assert rejected.status_code == 400
        results.append({'case': 'over_context_rejected', 'passed': True})

    if not args.local_container:
        unauthenticated = requests.Session()
        unauthenticated.verify = session.verify
        rejected = unauthenticated.post(base + '/v1/chat/completions', json={'model': model,
                                         'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 4}, timeout=20)
        save('authentication-negative.json', {'status': rejected.status_code, 'body': rejected.text[:1000]})
        assert rejected.status_code in (401, 403)
        results.append({'case': 'missing_key_rejected', 'passed': True})
    assert session.get(base + '/health', timeout=20).status_code == 200
    save('summary.json', {'passed': True, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         'service_root': base, 'results': results, 'performance_claim': False,
                         'gateway_authentication_checked': not args.local_container})
    print(json.dumps({'passed': True, 'results': results}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
```
