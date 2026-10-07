"""Run vLLM directly inside a ModelArts Standard inference container."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from preflight import ARCHITECTURE, package_versions, runtime_paths, validate_model, visible_devices
from thread_preflight import ensure_threads

ENGINE_SHUTDOWN_SECONDS = 1080
PLATFORM_GRACE_SECONDS = 1200

def process_start_ticks(pid, proc_root=Path('/proc')):
    return (proc_root / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()[19]

def write_state(path, state):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    os.replace(temporary, path)

def engine_arguments(model):
    return [sys.executable, '-m', 'vllm.entrypoints.openai.api_server',
            '--model', str(model), '--served-model-name', 'qwen3.6-35b-a3b',
            '--host', '0.0.0.0', '--port', '8000', '--tensor-parallel-size', '8',
            '--data-parallel-size', '1', '--enable-expert-parallel', '--dtype', 'bfloat16',
            '--max-model-len', '262144', '--max-num-seqs', '16',
            '--max-num-batched-tokens', '8192', '--gpu-memory-utilization', '0.90',
            '--no-enable-prefix-caching', '--reasoning-parser', 'qwen3', '--seed', '1024',
            '--shutdown-timeout', str(ENGINE_SHUTDOWN_SECONDS),
            '--compilation-config', '{"cudagraph_mode":"FULL_DECODE_ONLY"}']

class Lifecycle:
    def __init__(self, emit, persist):
        self.emit, self.persist = emit, persist
        self.child = None
        self.stop_requested = False
        self.stop_signal = signal.SIGTERM
        self.stop_notice_written = False

    def terminate(self, signum, frame):
        if self.stop_requested:
            return
        self.stop_requested = True
        self.stop_signal = signum
        # No file/log writes in a signal handler: it may interrupt those same writes.
        if self.child is not None:
            self.send(signum)

    def flush_stop_notice(self):
        if self.stop_requested and not self.stop_notice_written:
            self.persist('stopping')
            target = f'API server {self.child.pid}' if self.child is not None else 'preflight (launch cancelled)'
            self.emit(f'SHUTDOWN signal {self.stop_signal}, target {target}\n')
            self.stop_notice_written = True

    def send(self, signum):
        try:
            self.child.send_signal(signum)
        except ProcessLookupError:
            pass

    def attach(self, child):
        self.child = child
        if self.stop_requested:
            self.send(self.stop_signal)

def main():
    import fcntl  # ModelArts is Linux; import here so pure helpers can be tested elsewhere.
    root, model, run, logs, host = runtime_paths()
    if not root.is_dir() or not model.is_dir():
        raise RuntimeError('ModelArts model/runtime mounts are missing; configure console mounts first')
    run.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    lock = (run / '.supervisor.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    state_path = run / 'supervisor-state.json'
    state = {'pid': os.getpid(), 'start_ticks': process_start_ticks(os.getpid()),
             'script': str(Path(__file__).resolve()), 'hostname': host,
             'started_utc': stamp, 'engine_shutdown_seconds': ENGINE_SHUTDOWN_SECONDS,
             'expected_platform_grace_seconds': PLATFORM_GRACE_SECONDS}
    with (logs / f'runtime-{stamp}-{host}.log').open('a', buffering=1, encoding='utf-8') as log:
        def emit(line):
            print(line, end='', flush=True)
            try:
                log.write(line)
                log.flush()
            except OSError as error:
                print(f'Runtime file log unavailable: {error}; stdout continues', file=sys.stderr, flush=True)

        def persist(phase):
            state['phase'] = phase
            write_state(state_path, state)

        lifecycle = Lifecycle(emit, persist)
        previous = {sig: signal.signal(sig, lifecycle.terminate) for sig in (signal.SIGTERM, signal.SIGINT)}
        code = 1
        try:
            persist('preflight')
            facts = {'model': validate_model(model, root / 'weights-verified.json')}
            if lifecycle.stop_requested:
                lifecycle.flush_stop_notice()
                code = 143
                return code
            facts.update(thread_preflight=ensure_threads(), versions=package_versions())
            if lifecycle.stop_requested:
                lifecycle.flush_stop_notice()
                code = 143
                return code
            facts.update(devices=visible_devices(), hostname=host, pod_ip=os.environ.get('POD_IP'),
                         model_mount=str(model), runtime_mount=str(root), tp=8, dp=1, ep=8,
                         expected_architecture=ARCHITECTURE,
                         engine_shutdown_seconds=ENGINE_SHUTDOWN_SECONDS,
                         platform_settings='Verify in ModelArts console; container cannot change them')
            if lifecycle.stop_requested:
                lifecycle.flush_stop_notice()
                code = 143
                return code
            args = engine_arguments(model)
            facts['args'] = args
            (run / f'launch-{stamp}.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')
            emit(json.dumps(facts) + '\n')
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding='utf-8', errors='replace', bufsize=1,
                                     start_new_session=True)
            lifecycle.attach(child)
            state['engine_pid'] = child.pid
            persist('stopping' if lifecycle.stop_requested else 'engine_started')
            for line in child.stdout:
                lifecycle.flush_stop_notice()
                emit(line)
            lifecycle.flush_stop_notice()
            child_code = child.wait()
            code = child_code if child_code >= 0 else 128 - child_code
            emit(f'ENGINE_EXIT {child_code}\n')
            return code
        except Exception as error:
            emit(f'BOOT_ERROR {type(error).__name__}: {error}\n')
            raise
        finally:
            if lifecycle.child is not None and lifecycle.child.poll() is None:
                lifecycle.child.terminate()
                lifecycle.child.wait(timeout=ENGINE_SHUTDOWN_SECONDS + 30)
            state['exit_code'] = code
            persist('exited')
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

if __name__ == '__main__':
    sys.exit(main())
