# Qwen3.6 27B on ModelArts Standard

Deploy a non-production BF16 chatbot on one eight-card Ascend A2 node using Huawei Cloud ModelArts Standard new-version real-time inference.

## Start here

- [Complete English deployment guide](DEPLOYMENT_GUIDE_EN.md): 17 steps, direct weight download addresses, console option selections and complete script source.
- [Printable HTML guide](DEPLOYMENT_GUIDE_EN.html): download and view locally; GitHub shows the HTML source.
- [Direct snapshot download URLs](WEIGHT_DOWNLOAD_URLS.txt): all 29 files from the fixed official revision.
- [Handover checklist](FINAL_CHECKLIST.md).

The target profile uses official `Qwen/Qwen3.6-27B` BF16 weights, TP8 / DP1, and a native 262,144-token context. It enables platform local model-storage acceleration and graceful shutdown, and disables automatic rebuild.

## Files

| Directory or file | Purpose |
|---|---|
| `scripts/download_weights.py` | Fixed-revision download, resume and SHA256 verification |
| `scripts/inspect_image.py` | Inspect image architecture and package metadata |
| `scripts/acceptance.py` | Chat, streaming, thinking, authentication and optional long-context checks |
| `startup/` | ModelArts-native startup, process supervision, conditional thread preflight and stop hook |
| `examples/` | Chat and streaming request bodies |
| `image-candidate.json` | Public ARM64 image digest and reference-image distinction |
| `SHA256SUMS` | Checksums for the deployment package files |

Follow the guide before running any script. Replace account, region, pool, storage and endpoint placeholders with values from your own environment. Keep API keys in an approved secret store or protected environment.

The repository contains documentation and scripts only. Download the approximately 55.6 GB model snapshot and obtain the inference image separately. No credentials, model weights or private environment configuration are included.

The recorded reference runtime and the public release image are different. Validate compatibility and run the supplied acceptance checks in the target region. A passing functional smoke test does not establish production throughput or concurrency capacity. The reference was stopped with no active requests; in-flight draining and restart recovery were not demonstrated.

The underlying model and runtime retain their respective licenses. Consult their official repositories before redistribution or deployment.
