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
