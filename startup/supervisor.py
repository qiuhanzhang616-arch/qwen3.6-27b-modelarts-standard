"""ModelArts-native vLLM process and stdout/file log supervisor."""
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from thread_preflight import ensure_threads

ROOT = Path('/qwen-data')
HOST = os.uname().nodename
RUN = ROOT / 'run' / HOST
RUN.mkdir(parents=True, exist_ok=True)
verified = json.loads((ROOT / 'weights-verified.json').read_text())
if not verified.get('complete') or verified['revision'] != '995ad96eacd98c81ed38be0c5b274b04031597b0':
    raise RuntimeError('Pinned snapshot verification receipt is missing or invalid')
for item in verified['files']:
    path = Path('/model/weights') / item['file']
    if not path.is_file() or path.stat().st_size != item['bytes']:
        raise RuntimeError(f'Cached weight inventory mismatch: {path}')
model_config = json.loads(Path('/model/weights/config.json').read_text())
if model_config['architectures'] != ['Qwen3_5MoeForConditionalGeneration']:
    raise RuntimeError('Expected the 35B-A3B MoE model architecture')
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
log = (ROOT / 'logs' / f'runtime-{stamp}-{HOST}.log').open('a', buffering=1)
def emit(line):
    print(line, end='', flush=True)
    log.write(line)
    log.flush()
args = [sys.executable, '-m', 'vllm.entrypoints.openai.api_server',
        '--model', '/model/weights', '--served-model-name', 'qwen3.6-35b-a3b',
        '--host', '0.0.0.0', '--port', '8000', '--tensor-parallel-size', '8',
        '--data-parallel-size', '1', '--enable-expert-parallel', '--dtype', 'bfloat16', '--max-model-len', '262144',
        '--max-num-seqs', '16', '--max-num-batched-tokens', '8192',
        '--gpu-memory-utilization', '0.90', '--no-enable-prefix-caching',
        '--reasoning-parser', 'qwen3', '--seed', '1024',
        '--compilation-config', '{"cudagraph_mode":"FULL_DECODE_ONLY"}']
versions = {}
for name in ['vllm', 'vllm-ascend', 'torch', 'torch-npu', 'transformers']:
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = 'missing'
facts = {'started_utc': stamp, 'args': args, 'versions': versions, 'hostname': HOST,
         'pod_ip': os.environ.get('POD_IP'), 'required_context': 262144,
         'required_npus': 8, 'quantization': None, 'mtp': False,
         'expected_architecture': 'Qwen3_5MoeForConditionalGeneration', 'expert_parallel_size': 8,
         'thread_preflight': ensure_threads()}
(RUN / f'launch-{stamp}.json').write_text(json.dumps(facts, indent=2))
emit(json.dumps(facts) + '\n')
(RUN / 'supervisor.pid').write_text(str(os.getpid()))
subprocess.run(['npu-smi', 'info'], stdout=log, stderr=log, check=False)
child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, start_new_session=True)
(RUN / 'engine-parent.pid').write_text(str(child.pid))
def forward(signum, frame):
    emit(f'SHUTDOWN forwarding signal {signum} to API server {child.pid}\n')
    try:
        child.send_signal(signum)
    except ProcessLookupError:
        pass
signal.signal(signal.SIGTERM, forward)
signal.signal(signal.SIGINT, forward)
for line in child.stdout:
    emit(line)
code = child.wait()
emit(f'ENGINE_EXIT {code}\n')
sys.exit(code)
