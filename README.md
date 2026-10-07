# Qwen3.6 35B A3B on ModelArts Standard

Deploy a non-production BF16 chatbot on one eight-card Ascend A2 node using Huawei Cloud ModelArts Standard new-version real-time inference.

## Start here

- [Complete English deployment guide](DEPLOYMENT_GUIDE_EN.md): 17 steps, direct weight download addresses, console option selections and complete script source.
- [Printable HTML guide](DEPLOYMENT_GUIDE_EN.html): download and view locally; GitHub shows the HTML source.
- [Direct snapshot download URLs](WEIGHT_DOWNLOAD_URLS.txt): all 40 files from the fixed official revision.
- [Handover checklist](FINAL_CHECKLIST.md).
- [ModelArts Standard script integration](MODELARTS_STARTUP_EN.md): container entry, platform mounts, NPU visibility and bounded shutdown.

The target profile uses official `Qwen/Qwen3.6-35B-A3B` BF16 weights, TP8 / DP1 / EP8, and a native 262,144-token context. It enables platform local model-storage acceleration and graceful shutdown, and disables automatic rebuild.

## Files

| Directory or file | Purpose |
|---|---|
| `scripts/download_weights.py` | Fixed-revision download, resume and SHA256 verification |
| `scripts/inspect_image.py` | Inspect image architecture and package metadata |
| `scripts/acceptance.py` | Chat, streaming, thinking, authentication and optional long-context checks |
| `startup/` | ModelArts-native startup, process supervision, conditional thread preflight and stop hook |
| `MODELARTS_CONSOLE_VALUES.json` | Human-readable platform configuration reference; not an API import file |
| `tests/` | Synthetic control-flow checks; no NPU runtime or model load |
| `examples/` | Chat and streaming request bodies |
| `image-candidate.json` | Public ARM64 image digest and 35B validation scope |
| `weight-snapshot.json` | Fixed 35B revision, 40-file inventory, sizes and published shard hashes |
| `SHA256SUMS` | Checksums for the deployment package files |

Follow the guide before running any script. Replace account, region, pool, storage and endpoint placeholders with values from your own environment. Keep API keys in an approved secret store or protected environment.

The repository contains documentation and scripts only. Download the approximately 71.9 GB model snapshot and obtain the inference image separately. No credentials, model weights or private environment configuration are included.

This 35B-A3B profile has not been runtime-tested. The model is MoE with 35B total parameters and approximately 3B activated per token; the complete approximately 71.9 GB snapshot is still required. Validate compatibility and run every supplied acceptance check in the target region. Previous [27B results](HISTORICAL_27B_REFERENCE.md) are historical only. This update does not start a model service.

The underlying model and runtime retain their respective licenses. Consult their official repositories before redistribution or deployment.
