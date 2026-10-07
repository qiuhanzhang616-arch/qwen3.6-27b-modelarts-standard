"""ModelArts pre-stop hook; verify PID identity and stay within platform grace."""
import json
import os
from pathlib import Path
import signal
import time
from preflight import runtime_paths

HOOK_TIMEOUT_SECONDS = 1150

def same_process(state, proc_root=Path('/proc')):
    pid = state.get('pid')
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        directory = proc_root / str(pid)
        ticks = (directory / 'stat').read_text().rsplit(') ', 1)[1].split()[19]
        arguments = (directory / 'cmdline').read_bytes().split(b'\0')
        return ticks == str(state['start_ticks']) and os.fsencode(state['script']) in arguments
    except (FileNotFoundError, ProcessLookupError):
        return False

def main():
    _, _, run, _, _ = runtime_paths()
    path = run / 'supervisor-state.json'
    if not path.exists():
        print('STOP: no supervisor state yet', flush=True)
        return 0
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('script') != str(Path(__file__).with_name('supervisor.py').resolve()):
        raise RuntimeError('Stop state does not identify this deployment supervisor')
    if state.get('phase') == 'exited' or not same_process(state):
        print('STOP: supervisor exited or Pod state is stale', flush=True)
        return 0
    try:
        os.kill(state['pid'], signal.SIGTERM)
    except ProcessLookupError:
        return 0
    deadline = time.monotonic() + HOOK_TIMEOUT_SECONDS
    while same_process(state):
        if time.monotonic() >= deadline:
            print('STOP: hook deadline reached; ModelArts controls remaining termination', flush=True)
            return 124
        time.sleep(1)
    print('STOP: verified supervisor exited', flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
