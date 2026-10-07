# Deploy Qwen3.6 35B A3B on Huawei Cloud ModelArts Standard

## Purpose and deployment scope

Follow this guide to deploy a non-production chatbot using official **Qwen3.6-35B-A3B BF16** weights, one **8-card Ascend A2 node**, and a **262,144-token context limit** on Huawei Cloud public-cloud **ModelArts Standard, new-version real-time inference**. The result is an authenticated OpenAI-compatible chat API. A chatbot web interface is a separate application.

Here, **A3B means approximately 3B activated parameters per token**, not Ascend A3 hardware. This guide continues to target Ascend A2. Download the complete 35B MoE snapshot; the activated-parameter count does not reduce the weight inventory to 3B.

This is a proposed 35B-A3B deployment profile based on the official model configuration and versioned Ascend recipe. It retains the eight-card public-cloud infrastructure workflow. The 35B-A3B model has not been deployed or runtime-tested as part of preparing this guide. Complete compatibility and functional acceptance with the selected image in your account. Earlier 27B results do not establish 35B behavior; see [the historical reference note](HISTORICAL_27B_REFERENCE.md).

The accompanying ZIP contains the guide, executable preparation and startup files, request examples, an acceptance script, and a final checklist. Appendices A, B and C provide the complete download-address inventory, a field-by-field console selection checklist, and the full script source. It does **not** contain the 71.9 GB weights, container image, API keys, or account-specific configuration.

### Proposed target configuration

| Item | Setting for this procedure |
|---|---|
| Workload | Text chatbot, including multi-turn and streaming chat |
| Model repository | `Qwen/Qwen3.6-35B-A3B` |
| Weight revision | `995ad96eacd98c81ed38be0c5b274b04031597b0` |
| Model architecture | Sparse MoE, 35B total parameters and approximately 3B activated per token |
| Weight precision | BF16, no quantization |
| Snapshot inventory | 40 files, 26 weight shards, 71,926,865,825 bytes |
| Compute | One dedicated node, 8 × Ascend A2, 64 GB HBM per card |
| Engine topology | TP8 / DP1 / EP8, one deployment replica, one unit instance |
| Context | 262,144 tokens, including input, chat template, reasoning and output |
| Model alias | `qwen3.6-35b-a3b` |
| Container API | HTTP, port 8000 |
| Client authentication | ModelArts API key |
| Model storage acceleration | Enabled |
| Graceful shutdown | Enabled, 1,200 seconds |
| Automatic rebuild | Disabled |
| Model prefix caching | Disabled in this initial runtime profile |

The native model context is 262,144 tokens. This procedure does not apply a context extension or change RoPE settings. The weight configuration can legitimately identify the architecture as `Qwen3_5MoeForConditionalGeneration`: verify the repository revision rather than treating that architecture name as evidence that the wrong model was downloaded. See the [official model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B).

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
| Service name | `qwen36-35b-a3b-8a2-test` |
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
7. Check the node's data disk and image disk capacity. The container image is separate from the local model cache. Budget for expanded image layers, approximately 71.9 GB of cached weights, graph caches and logs; also meet the local-cache disk requirements shown by ModelArts for your pool/storage option.

The proposed request is **8 NPUs, 120 vCPUs and 900,000 MiB of RAM**. These CPU and RAM values reuse the previous infrastructure allocation; they are not measured minimum requirements for 35B-A3B. Use them only if your selected node can allocate them. A preset eight-card shape may ask for more CPU than the node currently has available; use a permitted custom specification rather than reducing the NPU count.

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
export QWEN_MODEL_ROOT=/mnt/qwen-weights/qwen36-35b-a3b
export QWEN_RUNTIME_ROOT=/mnt/qwen-runtime/qwen36-35b-a3b
mkdir -p "$QWEN_MODEL_ROOT/weights" "$QWEN_MODEL_ROOT/logs"
mkdir -p "$QWEN_RUNTIME_ROOT/startup" "$QWEN_RUNTIME_ROOT/logs" "$QWEN_RUNTIME_ROOT/run"
```

Provide at least 150 GiB of free model-storage space for this 71.9 GB snapshot and preparation overhead, while also meeting the cloud file system's provisioning minimum. Keep runtime storage space for retained logs. Actual SFS provisioning minima and billing depend on the selected type.

**Checkpoint:** Both mount points are actual mounted file systems, have sufficient space, and are writable by the preparation operator. Do not download into an unmounted directory that happens to have the same name.

## Step 4 Download and verify the official weights

### Official download addresses

| Source | Address and use |
|---|---|
| Official Hugging Face repository | [Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) |
| Exact snapshot file browser | [Revision 995ad96eacd98c81ed38be0c5b274b04031597b0](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/tree/995ad96eacd98c81ed38be0c5b274b04031597b0) |
| Pinned download manifest | [Immutable revision metadata with file sizes and LFS hashes](https://huggingface.co/api/models/Qwen/Qwen3.6-35B-A3B/revision/995ad96eacd98c81ed38be0c5b274b04031597b0?blobs=true) |
| Official ModelScope mirror | [Qwen/Qwen3.6-35B-A3B](https://www.modelscope.cn/models/Qwen/Qwen3.6-35B-A3B) |

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
COMPLETE 40 71926865825
```

Confirm the receipt and configuration:

```bash
python - "$QWEN_MODEL_ROOT" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
receipt = json.loads((root / 'weights-verified.json').read_text())
assert receipt['complete']
assert receipt['revision'] == '995ad96eacd98c81ed38be0c5b274b04031597b0'
assert len(receipt['files']) == 40
assert receipt['total_bytes'] == 71926865825
assert not list((root / 'weights').rglob('*.incomplete'))
config = json.loads((root / 'weights/config.json').read_text())
assert config['text_config']['max_position_embeddings'] == 262144
print('VERIFIED:', config['architectures'], config['text_config'].get('dtype'))
PY
```

If interrupted, rerun the same downloader against the same directory. Do not run two downloaders concurrently against that directory. If a hash mismatch persists, quarantine the affected file, investigate the source/network/storage, and rerun verification. A directory's existence is not proof of a complete snapshot.

**Checkpoint:** The success receipt exists, all indexed shards are present, and no incomplete files remain.

## Step 5 Prepare an ARM64 inference image in your regional SWR

The main path uses the official A2 image **vLLM-Ascend v0.23.0.post1**, which is named in the [versioned Qwen3.6-35B-A3B A2 deployment tutorial](https://docs.vllm.ai/projects/ascend/en/v0.23.0/tutorials/models/Qwen3.6-35B-A3B.html). Use the ARM64 image, not the `-a3`, `-a5` or `-310p` variant. The [release notes](https://github.com/vllm-project/vllm-ascend/releases/tag/v0.23.0.post1) describe this release.

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

### Compatibility and validation gate

Use the pinned public A2 image only after confirming its driver/CANN compatibility with your selected pool. The official 35B-A3B recipe supports BF16 on eight-card A2 and expert parallelism, but its W8A8 performance example is not a BF16 acceptance result for this proposed TP8/EP8 profile. Do not substitute a retained 27B image merely because it started a different model.

**Checkpoint:** The selected ARM64 image is accessible from your pool, its dependencies match the hardware, and the exact SWR tag/digest is recorded.

## Step 6 Stage the startup package and verification receipt

Copy only the runtime files and model verification metadata to the runtime file system:

```bash
cp startup/start.sh startup/stop.sh startup/supervisor.py \
  startup/preflight.py startup/stop.py startup/thread_preflight.py "$QWEN_RUNTIME_ROOT/startup/"
cp "$QWEN_MODEL_ROOT/weights-verified.json" "$QWEN_RUNTIME_ROOT/weights-verified.json"
cp "$QWEN_MODEL_ROOT/weight-manifest.json" "$QWEN_RUNTIME_ROOT/weight-manifest.json"
cp scripts/acceptance.py "$QWEN_RUNTIME_ROOT/acceptance.py"
chmod 0755 "$QWEN_RUNTIME_ROOT/startup/start.sh" "$QWEN_RUNTIME_ROOT/startup/stop.sh"
bash -n "$QWEN_RUNTIME_ROOT/startup/start.sh"
bash -n "$QWEN_RUNTIME_ROOT/startup/stop.sh"
python -m py_compile "$QWEN_RUNTIME_ROOT/startup/supervisor.py" \
  "$QWEN_RUNTIME_ROOT/startup/thread_preflight.py" \
  "$QWEN_RUNTIME_ROOT/startup/preflight.py" "$QWEN_RUNTIME_ROOT/startup/stop.py"
(cd "$QWEN_RUNTIME_ROOT/startup" && sha256sum *.sh *.py > SHA256SUMS)
```

The inference container must be able to read the scripts and receipt, and write to `logs/` and `run/`. The selected public image uses the default root identity in its metadata. If your organization runs it under another permitted UID, set ownership and directory permissions for that UID before deployment; also ensure its compiler/cache locations are writable. Keep permission changes confined to the new deployment directory.

Expected layout:

```text
Weight SFS root                     Runtime SFS root
/qwen36-35b-a3b/weights/                 /qwen36-35b-a3b/startup/start.sh
  config.json                       /qwen36-35b-a3b/startup/stop.sh
  model.safetensors.index.json       /qwen36-35b-a3b/startup/supervisor.py
  model-00001-of-00026...             /qwen36-35b-a3b/startup/thread_preflight.py
  tokenizer and processor files     /qwen36-35b-a3b/weights-verified.json
                                    /qwen36-35b-a3b/logs/
                                    /qwen36-35b-a3b/run/
```

The supervisor checks the mounted snapshot and exactly eight visible allocated NPUs before launching vLLM, records the actual package versions and arguments, sends logs to stdout and SFS, and forwards stop signals to the API server. PID files are isolated by Pod hostname. The thread preflight leaves the platform's security policy intact; it applies a narrow clone3 error-code compatibility rule only if a thread failure and inherited clone3 EPERM are actually observed. Its conditional compatibility branch was not needed by the earlier 27B runtime; requirements for 35B must be checked on the target node.

**Checkpoint:** All six startup files pass syntax checks, their checksums are saved, and the runtime receipt matches the weight snapshot.

## Step 7 Create the real-time service

1. Open **ModelArts → Model Inference → Real-Time Inference**.
2. Click **Deploy**.
3. Enter the service information below.
4. Choose the access route approved for your test clients. This proposed profile uses private access. Public-cloud private access must be configured for your own VPC using the service's **Intranet Access Management** workflow; selecting private access alone does not establish connectivity.
5. Click **Next** to open deployment configuration. See the [public-cloud service information workflow](https://support.huaweicloud.com/intl/id-id/inference-modelarts/inference2.0-modelarts-0016.html).

| Service information field | Value |
|---|---|
| Service Name | `qwen36-35b-a3b-8a2-test` |
| Description | `Nonproduction Qwen3.6-35B-A3B BF16 chatbot, 8 A2, 262144 context` |
| Service Protocol | HTTPS |
| Authentication Mode | API KEY |
| External Network Access | Disabled for the private baseline |
| Intranet Access Without Approval | Disabled; retain your normal approval process |
| Request Size Limit | 20 MB, if supported |
| Request Timeout | 1,200 seconds, if supported |
| Requests Per Second Limit | 200 as an initial gateway cap, not a throughput claim |
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
| File System Directory | `/qwen36-35b-a3b/weights` |
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
| CPU | 120 vCPUs for the proposed allocation |
| Memory | 900,000 MiB for the proposed allocation |
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
| File System Directory | `/qwen36-35b-a3b` |
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

The pre-stop hook verifies the supervisor PID and process-start time, requests termination, and waits for at most 1150 seconds. The engine receives --shutdown-timeout 1080 within the 1200-second platform grace. Read MODELARTS_STARTUP_EN.md for the lifecycle contract and verify actual request draining in Step 15.

### Runtime arguments used by the package

```text
model                       /model/weights
served-model-name           qwen3.6-35b-a3b
host                        0.0.0.0
port                        8000
tensor-parallel-size        8
data-parallel-size          1
expert parallelism          enabled, EP8 with TP8/DP1
dtype                       bfloat16
max-model-len               262144
max-num-seqs                16
max-num-batched-tokens      8192
gpu-memory-utilization      0.90
reasoning-parser            qwen3
seed                        1024
prefix caching              disabled
compilation graph mode      FULL_DECODE_ONLY
engine shutdown timeout     1080 seconds (inside the 1200-second platform grace)
MTP                         disabled in this initial profile
quantization                none
```

These are proposed BF16 starting settings, not the official tutorial's W8A8 performance recipe. Expert parallelism distributes MoE experts across the eight workers, while attention remains TP8. The 3B activation count does not mean only 3B of weights must be downloaded or loaded. Do not add `--quantization ascend` to official BF16 weights. Sixteen maximum active sequences is a scheduler setting, not proof that sixteen simultaneous 256K conversations meet a service-level target.

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
- Weight SFS path `/qwen36-35b-a3b/weights` → `/model/weights`, read-only, **local acceleration enabled**.
- Runtime SFS path `/qwen36-35b-a3b` → `/qwen-data`, read/write, uncached.
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

During startup, a probe can report connection refused before the server begins listening. Continue observing if loading/compilation logs are advancing and the startup window has not expired. If the process exits, a traceback occurs, or repeated OOM/HCCL errors appear, investigate instead of waiting indefinitely. The earlier 27B model started in about eight minutes in another environment. No startup duration has been measured for this 35B profile.

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

Expected: the list contains `qwen3.6-35b-a3b`; the answer to the arithmetic request is `43` with a normal stop reason.

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
| Devices and topology | Eight ranks, TP8 / DP1 / EP8 |
| Model listing | Alias is present; effective max context is 262144 |
| Ordinary and multi-turn chat | Correct final text, normal finish reason |
| Streaming | Non-empty valid UTF-8 output and `[DONE]` |
| Thinking | Reasoning and final answer are returned separately |
| Long context | At least 261,000 measured input tokens, correct marker response, no OOM |
| Over-context input | HTTP 400 |
| Missing API key | HTTP 401 or 403 on the authenticated ModelArts route |
| After the requests | Health returns 200 and the service remains ready |

The acceptance script targets at least 261,000 input tokens, but no 35B long-context result is claimed here. The earlier 27B long-context and chatbot tests must not be reused as evidence for 35B. Run all checks with this model and the actual public-cloud image. This is functional acceptance, not a QPS, latency, concurrency or production-quality benchmark.

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

The earlier 27B deployment was stopped with zero active requests and is separate from this guide. No 35B shutdown, request-draining or restart/recovery drill has been executed. An enabled platform grace period does not prove that the selected runtime drains in-flight requests; validate that behavior before production use.

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
| Receipt or startup file missing | Verify that runtime SFS `/qwen36-35b-a3b` is mounted at `/qwen-data` and the receipt was copied after verification. |
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

All addresses refer to the fixed official 35B-A3B snapshot. There are 40 files and 26 model weight shards. Download the complete snapshot and verify it using Step 4.

| File | Bytes | Direct fixed revision download |
|---|---:|---|
| `.gitattributes` | 1,570 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/.gitattributes) |
| `LICENSE` | 11,343 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/LICENSE) |
| `README.md` | 64,550 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/README.md) |
| `chat_template.jinja` | 7,764 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/chat_template.jinja) |
| `config.json` | 3,686 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/config.json) |
| `configuration.json` | 58 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/configuration.json) |
| `generation_config.json` | 202 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/generation_config.json) |
| `merges.txt` | 3,353,259 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/merges.txt) |
| `model-00001-of-00026.safetensors` | 3,996,199,712 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00001-of-00026.safetensors) |
| `model-00002-of-00026.safetensors` | 1,284,907,696 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00002-of-00026.safetensors) |
| `model-00003-of-00026.safetensors` | 3,357,898,360 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00003-of-00026.safetensors) |
| `model-00004-of-00026.safetensors` | 3,370,808,712 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00004-of-00026.safetensors) |
| `model-00005-of-00026.safetensors` | 3,357,898,360 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00005-of-00026.safetensors) |
| `model-00006-of-00026.safetensors` | 3,959,424,904 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00006-of-00026.safetensors) |
| `model-00007-of-00026.safetensors` | 1,096,788,232 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00007-of-00026.safetensors) |
| `model-00008-of-00026.safetensors` | 3,946,842,008 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00008-of-00026.safetensors) |
| `model-00009-of-00026.safetensors` | 1,096,460,848 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00009-of-00026.safetensors) |
| `model-00010-of-00026.safetensors` | 3,946,841,992 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00010-of-00026.safetensors) |
| `model-00011-of-00026.safetensors` | 1,096,460,752 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00011-of-00026.safetensors) |
| `model-00012-of-00026.safetensors` | 3,409,971,080 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00012-of-00026.safetensors) |
| `model-00013-of-00026.safetensors` | 1,633,331,664 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00013-of-00026.safetensors) |
| `model-00014-of-00026.safetensors` | 3,422,553,872 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00014-of-00026.safetensors) |
| `model-00015-of-00026.safetensors` | 1,633,659,224 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00015-of-00026.safetensors) |
| `model-00016-of-00026.safetensors` | 3,946,842,136 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00016-of-00026.safetensors) |
| `model-00017-of-00026.safetensors` | 1,096,460,608 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00017-of-00026.safetensors) |
| `model-00018-of-00026.safetensors` | 3,946,841,992 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00018-of-00026.safetensors) |
| `model-00019-of-00026.safetensors` | 1,096,460,808 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00019-of-00026.safetensors) |
| `model-00020-of-00026.safetensors` | 3,409,971,072 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00020-of-00026.safetensors) |
| `model-00021-of-00026.safetensors` | 1,633,331,744 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00021-of-00026.safetensors) |
| `model-00022-of-00026.safetensors` | 3,370,808,752 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00022-of-00026.safetensors) |
| `model-00023-of-00026.safetensors` | 3,357,898,392 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00023-of-00026.safetensors) |
| `model-00024-of-00026.safetensors` | 3,370,808,752 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00024-of-00026.safetensors) |
| `model-00025-of-00026.safetensors` | 3,832,888,256 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00025-of-00026.safetensors) |
| `model-00026-of-00026.safetensors` | 2,231,416,848 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model-00026-of-00026.safetensors) |
| `model.safetensors.index.json` | 98,383 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/model.safetensors.index.json) |
| `preprocessor_config.json` | 390 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/preprocessor_config.json) |
| `tokenizer.json` | 12,807,982 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/tokenizer.json) |
| `tokenizer_config.json` | 16,718 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/tokenizer_config.json) |
| `video_preprocessor_config.json` | 385 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/video_preprocessor_config.json) |
| `vocab.json` | 6,722,759 | [Download](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/resolve/995ad96eacd98c81ed38be0c5b274b04031597b0/vocab.json) |

`WEIGHT_DOWNLOAD_URLS.txt` contains the same complete addresses as plain text.

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
| Service Name | `qwen36-35b-a3b-8a2-test` | Use a unique name if this already exists |
| Description | `Nonproduction Qwen3.6-35B-A3B BF16 chatbot, 8 A2, 262144 context` | Plain descriptive text |
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
| Deployment Description | `Official BF16 Qwen3.6-35B-A3B, TP8, chatbot, native 262144 context` | Optional; do not put secrets here |
| Resource Pool selector | Your approved dedicated A2 pool | Review available NPU/CPU/memory numbers |
| Deployment Replicas | `1` | One node for this baseline |
| Model Source | Custom Model | Not a preset/other model |
| Model Storage Type | SFS Turbo | Main procedure uses the weight file system |
| Weight File System | Your weight SFS | Different from runtime SFS |
| Weight File System Directory | `/qwen36-35b-a3b/weights` | Relative to file system root, not an ECS mount prefix |
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
| CPU | `120` vCPUs | Proposed allocation; must fit available CPU |
| Memory | `900000` MiB | Proposed allocation; must fit available RAM |
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
| Runtime File System Directory | `/qwen36-35b-a3b` | Contains startup, receipt, logs and run directories |
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

These are complete copies of the 35B-A3B scripts in this package. The runtime profile is proposed and requires target-pool acceptance.

### scripts/download_weights.py

```python
#!/usr/bin/env python3
"""Download and verify the pinned official Qwen3.6-35B-A3B snapshot."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import requests

REPO = 'Qwen/Qwen3.6-35B-A3B'
REVISION = '995ad96eacd98c81ed38be0c5b274b04031597b0'
EXPECTED_BYTES = 71926865825

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
    if manifest['sha'] != REVISION or len(manifest['siblings']) != 40 or sum(x['size'] for x in manifest['siblings']) != EXPECTED_BYTES:
        raise RuntimeError('Pinned 35B-A3B snapshot manifest does not match its inventory')
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
    config = json.loads((weights / 'config.json').read_text())
    if config['architectures'] != ['Qwen3_5MoeForConditionalGeneration'] or config['text_config']['max_position_embeddings'] != 262144:
        raise RuntimeError('Unexpected 35B-A3B architecture or native context')
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
    registry_found = registry.is_file() and 'Qwen3_5MoeForConditionalGeneration' in registry.read_text()
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
export HCCL_BUFFSIZE=1024
export PYTORCH_NPU_ALLOC_CONF=expandable_segments:True
export OMP_NUM_THREADS=1
export TASK_QUEUE_ENABLE=1
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export OTEL_SDK_DISABLED=true
runtime_dir="${QWEN_RUNTIME_DIR:-/qwen-data}"
python_bin="${QWEN_PYTHON_BIN:-python}"
command -v "$python_bin" >/dev/null
if [[ ! -f "$runtime_dir/startup/supervisor.py" ]]; then
  echo 'ModelArts runtime mount or startup package is missing' >&2
  exit 1
fi
exec "$python_bin" "$runtime_dir/startup/supervisor.py"
```

### startup/preflight.py

```python
"""Validate mounted ModelArts artifacts and the allocated NPU visibility."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys

REVISION = '995ad96eacd98c81ed38be0c5b274b04031597b0'
ARCHITECTURE = 'Qwen3_5MoeForConditionalGeneration'
FILE_COUNT = 40
TOTAL_BYTES = 71926865825

def runtime_paths(environment=None, hostname=None):
    env = os.environ if environment is None else environment
    host = hostname or socket.gethostname()
    if not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in host):
        raise RuntimeError('Unsafe Pod hostname')
    root = Path(env.get('QWEN_RUNTIME_DIR', '/qwen-data'))
    model = Path(env.get('QWEN_MODEL_DIR', '/model/weights'))
    if not root.is_absolute() or not model.is_absolute():
        raise RuntimeError('Container mount paths must be absolute')
    root, model = root.resolve(), model.resolve()
    return root, model, root / 'run' / host, root / 'logs', host

def validate_model(model, receipt_path):
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    files = receipt.get('files', [])
    if receipt.get('complete') is not True or receipt.get('revision') != REVISION:
        raise RuntimeError('Mounted verification receipt is incomplete or for another revision')
    if len(files) != FILE_COUNT or receipt.get('total_bytes') != TOTAL_BYTES:
        raise RuntimeError('Wrong 35B snapshot inventory')
    names = [item['file'] for item in files]
    if len(set(names)) != FILE_COUNT or sum(item['bytes'] for item in files) != TOTAL_BYTES:
        raise RuntimeError('Duplicate files or inconsistent receipt sizes')
    for item in files:
        path = (model / item['file']).resolve()
        if not path.is_relative_to(model.resolve()):
            raise RuntimeError('Receipt path escapes the model mount')
        if not path.is_file() or path.stat().st_size != item['bytes']:
            raise RuntimeError(f'Mounted model file missing or wrong size: {item["file"]}')
    if list(model.rglob('*.incomplete')):
        raise RuntimeError('Incomplete files remain in the mounted model')
    config = json.loads((model / 'config.json').read_text(encoding='utf-8'))
    if config.get('architectures') != [ARCHITECTURE]:
        raise RuntimeError('Expected official 35B-A3B MoE architecture')
    text = config['text_config']
    if text.get('max_position_embeddings') != 262144 or text.get('dtype') != 'bfloat16':
        raise RuntimeError('Unexpected native context or weight precision')
    index = json.loads((model / 'model.safetensors.index.json').read_text(encoding='utf-8'))
    shards = set(index['weight_map'].values())
    if len(shards) != 26 or not shards.issubset(set(names)):
        raise RuntimeError('Weight index does not reference the expected 26 shards')
    return {'revision': REVISION, 'files': FILE_COUNT, 'bytes': TOTAL_BYTES,
            'architecture': ARCHITECTURE, 'dtype': 'bfloat16', 'native_context': 262144}

def package_versions():
    return {name: importlib.metadata.version(name) for name in
            ('vllm', 'vllm-ascend', 'torch', 'torch-npu', 'transformers')}

def visible_devices():
    if platform.system() != 'Linux' or platform.machine() not in ('aarch64', 'arm64'):
        raise RuntimeError('This profile requires a Linux ARM64 A2 inference container')
    probe = ('import json,torch,torch_npu; '
             'print("MODELARTS_NPU_FACTS="+json.dumps({"available":torch.npu.is_available(),'
             '"count":torch.npu.device_count()}))')
    result = subprocess.run([sys.executable, '-c', probe], text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError('NPU runtime import/probe failed: ' + result.stderr[-1500:])
    lines = [line for line in result.stdout.splitlines() if line.startswith('MODELARTS_NPU_FACTS=')]
    if len(lines) != 1:
        raise RuntimeError('NPU probe did not return an unambiguous inventory')
    facts = json.loads(lines[0].split('=', 1)[1])
    if not facts['available'] or facts['count'] != 8:
        raise RuntimeError(f'Expected exactly 8 allocated visible NPUs; got {facts}')
    return facts
```

### startup/supervisor.py

```python
"""Run vLLM directly inside a ModelArts Standard inference container."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from preflight import ARCHITECTURE, package_versions, runtime_paths, validate_model, visible_devices
from thread_preflight import ensure_threads

ENGINE_SHUTDOWN_SECONDS = 1080
PLATFORM_GRACE_SECONDS = 1200

def process_start_ticks(pid, proc_root=Path('/proc')):
    return (proc_root / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[19]

def write_state(path, state):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    os.replace(temporary, path)

def engine_arguments(model):
    return [sys.executable, '-m', 'vllm.entrypoints.openai.api_server',
            '--model', str(model), '--served-model-name', 'qwen3.6-35b-a3b',
            '--host', '0.0.0.0', '--port', '8000', '--tensor-parallel-size', '8',
            '--data-parallel-size', '1', '--enable-expert-parallel', '--dtype', 'bfloat16',
            '--max-model-len', '262144', '--max-num-seqs', '16',
            '--max-num-batched-tokens', '8192', '--gpu-memory-utilization', '0.90',
            '--no-enable-prefix-caching', '--reasoning-parser', 'qwen3', '--seed', '1024',
            '--shutdown-timeout', str(ENGINE_SHUTDOWN_SECONDS),
            '--compilation-config', '{"cudagraph_mode":"FULL_DECODE_ONLY"}']

class Lifecycle:
    def __init__(self, emit, persist):
        self.emit, self.persist = emit, persist
        self.child = None
        self.stop_requested = False
        self.stop_signal = signal.SIGTERM
        self.stop_notice_written = False

    def terminate(self, signum, frame):
        if self.stop_requested:
            return
        self.stop_requested = True
        self.stop_signal = signum
        # No file/log writes in a signal handler: it may interrupt those same writes.
        if self.child is not None:
            self.send(signum)

    def flush_stop_notice(self):
        if self.stop_requested and not self.stop_notice_written:
            self.persist('stopping')
            target = f'API server {self.child.pid}' if self.child is not None else 'preflight (launch cancelled)'
            self.emit(f'SHUTDOWN signal {self.stop_signal}, target {target}\n')
            self.stop_notice_written = True

    def send(self, signum):
        try:
            self.child.send_signal(signum)
        except ProcessLookupError:
            pass

    def attach(self, child):
        self.child = child
        if self.stop_requested:
            self.send(self.stop_signal)

def main():
    import fcntl  # ModelArts is Linux; import here so pure helpers can be tested elsewhere.
    root, model, run, logs, host = runtime_paths()
    if not root.is_dir() or not model.is_dir():
        raise RuntimeError('ModelArts model/runtime mounts are missing; configure console mounts first')
    run.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    lock = (run / '.supervisor.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    state_path = run / 'supervisor-state.json'
    state = {'pid': os.getpid(), 'start_ticks': process_start_ticks(os.getpid()),
             'script': str(Path(__file__).resolve()), 'hostname': host,
             'started_utc': stamp, 'engine_shutdown_seconds': ENGINE_SHUTDOWN_SECONDS,
             'expected_platform_grace_seconds': PLATFORM_GRACE_SECONDS}
    with (logs / f'runtime-{stamp}-{host}.log').open('a', buffering=1, encoding='utf-8') as log:
        def emit(line):
            print(line, end='', flush=True)
            try:
                log.write(line)
                log.flush()
            except OSError as error:
                print(f'Runtime file log unavailable: {error}; stdout continues', file=sys.stderr, flush=True)

        def persist(phase):
            state['phase'] = phase
            write_state(state_path, state)

        lifecycle = Lifecycle(emit, persist)
        previous = {sig: signal.signal(sig, lifecycle.terminate) for sig in (signal.SIGTERM, signal.SIGINT)}
        code = 1
        try:
            persist('preflight')
            facts = {'model': validate_model(model, root / 'weights-verified.json')}
            if lifecycle.stop_requested:
                lifecycle.flush_stop_notice()
                code = 143
                return code
            facts.update(thread_preflight=ensure_threads(), versions=package_versions())
            if lifecycle.stop_requested:
                lifecycle.flush_stop_notice()
                code = 143
                return code
            facts.update(devices=visible_devices(), hostname=host, pod_ip=os.environ.get('POD_IP'),
                         model_mount=str(model), runtime_mount=str(root), tp=8, dp=1, ep=8,
                         expected_architecture=ARCHITECTURE,
                         engine_shutdown_seconds=ENGINE_SHUTDOWN_SECONDS,
                         platform_settings='Verify in ModelArts console; container cannot change them')
            if lifecycle.stop_requested:
                lifecycle.flush_stop_notice()
                code = 143
                return code
            args = engine_arguments(model)
            facts['args'] = args
            (run / f'launch-{stamp}.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
            emit(json.dumps(facts) + '\n')
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding='utf-8', errors='replace', bufsize=1,
                                     start_new_session=True)
            lifecycle.attach(child)
            state['engine_pid'] = child.pid
            persist('stopping' if lifecycle.stop_requested else 'engine_started')
            for line in child.stdout:
                lifecycle.flush_stop_notice()
                emit(line)
            lifecycle.flush_stop_notice()
            child_code = child.wait()
            code = child_code if child_code >= 0 else 128 - child_code
            emit(f'ENGINE_EXIT {child_code}\n')
            return code
        except Exception as error:
            emit(f'BOOT_ERROR {type(error).__name__}: {error}\n')
            raise
        finally:
            if lifecycle.child is not None and lifecycle.child.poll() is None:
                lifecycle.child.terminate()
                lifecycle.child.wait(timeout=ENGINE_SHUTDOWN_SECONDS + 30)
            state['exit_code'] = code
            persist('exited')
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

if __name__ == '__main__':
    sys.exit(main())
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
runtime_dir="${QWEN_RUNTIME_DIR:-/qwen-data}"
exec "${QWEN_PYTHON_BIN:-python}" "$runtime_dir/startup/stop.py"
```

### startup/stop.py

```python
"""ModelArts pre-stop hook; verify PID identity and stay within platform grace."""
import json
import os
from pathlib import Path
import signal
import time
from preflight import runtime_paths

HOOK_TIMEOUT_SECONDS = 1150

def same_process(state, proc_root=Path('/proc')):
    pid = state.get('pid')
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        directory = proc_root / str(pid)
        ticks = (directory / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
        arguments = (directory / 'cmdline').read_bytes().split(b'\0')
        return ticks == str(state['start_ticks']) and os.fsencode(state['script']) in arguments
    except (FileNotFoundError, ProcessLookupError):
        return False

def main():
    _, _, run, _, _ = runtime_paths()
    path = run / 'supervisor-state.json'
    if not path.exists():
        print('STOP: no supervisor state yet', flush=True)
        return 0
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('script') != str(Path(__file__).with_name('supervisor.py').resolve()):
        raise RuntimeError('Stop state does not identify this deployment supervisor')
    if state.get('phase') == 'exited' or not same_process(state):
        print('STOP: supervisor exited or Pod state is stale', flush=True)
        return 0
    try:
        os.kill(state['pid'], signal.SIGTERM)
    except ProcessLookupError:
        return 0
    deadline = time.monotonic() + HOOK_TIMEOUT_SECONDS
    while same_process(state):
        if time.monotonic() >= deadline:
            print('STOP: hook deadline reached; ModelArts controls remaining termination', flush=True)
            return 124
        time.sleep(1)
    print('STOP: verified supervisor exited', flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
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
    model = 'qwen3.6-35b-a3b'
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
