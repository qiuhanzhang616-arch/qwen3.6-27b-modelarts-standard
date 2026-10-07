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
