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
