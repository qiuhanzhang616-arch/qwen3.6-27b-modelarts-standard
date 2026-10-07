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
