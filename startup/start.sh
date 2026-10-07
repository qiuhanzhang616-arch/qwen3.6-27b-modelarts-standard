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
