#!/usr/bin/env bash
set -euo pipefail
runtime_dir="${QWEN_RUNTIME_DIR:-/qwen-data}"
exec "${QWEN_PYTHON_BIN:-python}" "$runtime_dir/startup/stop.py"
