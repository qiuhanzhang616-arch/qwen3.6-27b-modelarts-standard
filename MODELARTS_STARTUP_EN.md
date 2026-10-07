# ModelArts Standard startup and shutdown integration

These scripts execute **inside an existing ModelArts Standard new-version inference container**. ModelArts selects the SWR image, allocates the eight A2 NPUs, injects device/driver access and mounts storage. The scripts do not create another container, start Docker or Ray, install dependencies, download weights, change host sysctl/CPU governors, or override platform device masks.

## Files to stage

Copy all six files from `startup/` into the runtime SFS directory's `startup/` subdirectory:

| File | Responsibility |
|---|---|
| `start.sh` | Load the image's existing Ascend environment and `exec` the Python supervisor |
| `supervisor.py` | Validate preflight, start one foreground TP8/DP1/EP8 engine, relay logs and handle signals |
| `preflight.py` | Check the fixed 35B snapshot, mounted files, package metadata and exactly eight visible NPUs |
| `thread_preflight.py` | Conditional thread compatibility check; retains inherited seccomp rules |
| `stop.sh` | Execute the bounded Python pre-stop hook |
| `stop.py` | Verify supervisor PID, process start time and script identity before signalling it |

The downloader runs on the preparation ECS. It creates `weights-verified.json`, which must be copied to the runtime SFS root after all weights have been verified.

## Console contract

Use [MODELARTS_CONSOLE_VALUES.json](MODELARTS_CONSOLE_VALUES.json) as a field reference. It is **not** a ModelArts API payload and is not an importable service definition.

| Console setting | Required value |
|---|---|
| Deployment mode | Basic Mode |
| Deployment replicas / unit instances | 1 / 1 |
| Allocated NPUs | 8, on one A2 node |
| Model mount | Weight SFS `/qwen36-35b-a3b/weights` → `/model/weights`, read-only |
| Model local storage acceleration | Enabled |
| Runtime mount | Distinct runtime SFS `/qwen36-35b-a3b` → `/qwen-data`, read/write, uncached |
| Boot command | `bash /qwen-data/startup/start.sh` |
| Container protocol / port | HTTP / 8000 |
| Startup, readiness and liveness URL | `/health`, HTTP, port 8000; use the full guide's probe timing |
| Automatic rebuild | Disabled |
| Graceful shutdown | Enabled, 1200 seconds |
| Shutdown command | `bash /qwen-data/startup/stop.sh` |

The container scripts cannot enable the platform's cache or change its shutdown/rebuild switches. Review the **effective saved console settings** before every start, restart or upgrade. If a setting is unsupported in the selected region/pool, record that limitation rather than claiming the script enables it.

## Startup behavior

1. `start.sh` runs the supervisor in the foreground using `exec`. ModelArts observes its exit code.
2. The supervisor requires both container directories to exist and be accessible. Runtime logs and state must be writable by the configured container UID.
3. A per-Pod lock prevents duplicate supervisors. State is stored under `/qwen-data/run/<pod-hostname>/`.
4. The fixed revision, 40-file/26-shard inventory, cached file sizes, native 262144 context and BF16 MoE architecture are checked. SHA256 hashing of the complete 71.9 GB snapshot remains a preparation-stage task; startup does not claim to repeat that expensive hash verification.
5. Thread creation and installed dependency metadata are checked. A bounded separate Python probe imports `torch_npu` and requires exactly eight allocated visible NPUs. The platform's `ASCEND_*` device visibility and `POD_IP` remain intact.
6. The supervisor starts one vLLM API process. That process owns the eight workers. For this single-node profile, no multi-node discovery, external IP list, Ray cluster or hand-written rank table is required.
7. Logs are relayed to stdout for ModelArts collection and to the uncached runtime SFS. If the file log fails after startup, stdout continues and the error is reported.
8. `engine_started` state means the API process exists; it does not mean the model is ready. Only successful platform health probes and actual inference acceptance establish readiness.
9. Startup/model errors exit nonzero. The supervisor does not hide them with retries or a smaller context fallback.

Optional container-side overrides are `QWEN_MODEL_DIR`, `QWEN_RUNTIME_DIR` and `QWEN_PYTHON_BIN`. Leave them unset for the paths above. They are separate from the preparation ECS's `QWEN_MODEL_ROOT`/`QWEN_RUNTIME_ROOT` variables. If overriding the container paths, adjust both console mounts and commands together.

## Shutdown behavior

The budget is **1080 seconds for the engine**, **1150 seconds maximum for the pre-stop hook**, inside the **1200-second ModelArts grace period**. The supervisor passes `--shutdown-timeout 1080` to vLLM; the [v0.23.0 serve CLI](https://docs.vllm.ai/en/v0.23.0/cli/serve/) documents zero as abort and a positive value as wait. Verify that the actual selected image accepts this option.

The pre-stop hook checks PID plus Linux process-start time and the exact script argument. It will not signal a different process that reused an old PID. SIGTERM is forwarded to the API process, allowing vLLM to manage its workers. Duplicate signals do not issue a second abort while it is draining. A stop request received during preflight cancels engine launch; a signal arriving at process creation is forwarded as soon as the child is attached.

The hook exits successfully when the verified supervisor exits. If its deadline is reached, it returns 124 and leaves final termination to ModelArts; it does not send its own SIGKILL. Actual in-flight draining still requires a controlled test with the selected 35B runtime. These scripts and control-flow tests do not constitute that NPU acceptance.

## Verification scope

Run `python -m unittest discover -s tests -v` to check the lifecycle controls with synthetic files and mocked devices. The tests do not load the model, start an NPU engine or establish performance. Then follow the main guide's platform, chat, SSE, native-context, shutdown and recovery acceptance in the target pool. The existing stopped service is not restarted by this documentation/script update.
