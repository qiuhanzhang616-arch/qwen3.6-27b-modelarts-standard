"""Control-flow tests with synthetic files; no NPU/model runtime is started."""
import contextlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'startup'))
import preflight
import stop
import supervisor

class ModelArtsRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = self.root / 'model'
        self.model.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self):
        config = {'architectures': [preflight.ARCHITECTURE],
                  'text_config': {'max_position_embeddings': 262144, 'dtype': 'bfloat16'}}
        (self.model / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        shards = [f'model-{i:05d}-of-00026.safetensors' for i in range(1, 27)]
        for name in shards:
            (self.model / name).write_bytes(b'x')
        (self.model / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': dict(enumerate(shards))}), encoding='utf-8')
        for i in range(12):
            (self.model / f'aux-{i}').write_bytes(b'x')
        files = [{'file': p.name, 'bytes': p.stat().st_size} for p in sorted(self.model.iterdir())]
        total = sum(f['bytes'] for f in files)
        receipt = self.root / 'weights-verified.json'
        receipt.write_text(json.dumps({'complete': True, 'revision': preflight.REVISION,
                                      'files': files, 'total_bytes': total}), encoding='utf-8')
        return receipt, total

    def test_valid_mounted_snapshot(self):
        receipt, total = self.fixture()
        with patch.object(preflight, 'TOTAL_BYTES', total):
            self.assertEqual(preflight.validate_model(self.model, receipt)['files'], 40)

    def test_missing_cached_shard_is_rejected(self):
        receipt, total = self.fixture()
        (self.model / 'model-00002-of-00026.safetensors').unlink()
        with patch.object(preflight, 'TOTAL_BYTES', total), self.assertRaisesRegex(RuntimeError, 'missing or wrong size'):
            preflight.validate_model(self.model, receipt)

    def test_wrong_revision_is_rejected(self):
        receipt, _ = self.fixture()
        value = json.loads(receipt.read_text())
        value['revision'] = 'wrong-revision'
        receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'another revision'):
            preflight.validate_model(self.model, receipt)

    def test_receipt_cannot_escape_model_mount(self):
        receipt, total = self.fixture()
        value = json.loads(receipt.read_text())
        value['files'][0]['file'] = '../escape'
        receipt.write_text(json.dumps(value))
        with patch.object(preflight, 'TOTAL_BYTES', total), self.assertRaisesRegex(RuntimeError, 'escapes'):
            preflight.validate_model(self.model, receipt)

    def test_state_is_isolated_by_pod(self):
        env = {'QWEN_RUNTIME_DIR': str(self.root), 'QWEN_MODEL_DIR': str(self.model)}
        first = preflight.runtime_paths(env, 'pod-a')[2]
        second = preflight.runtime_paths(env, 'pod-b')[2]
        self.assertNotEqual(first, second)
        with self.assertRaises(RuntimeError):
            preflight.runtime_paths(env, '../pod')

    def test_device_allocation_must_be_eight(self):
        result = subprocess.CompletedProcess([], 0, 'MODELARTS_NPU_FACTS={"available":true,"count":4}\n', '')
        with patch.object(preflight.platform, 'system', return_value='Linux'), \
             patch.object(preflight.platform, 'machine', return_value='aarch64'), \
             patch.object(preflight.subprocess, 'run', return_value=result), \
             self.assertRaisesRegex(RuntimeError, 'exactly 8'):
            preflight.visible_devices()

    def test_shutdown_before_launch_and_spawn_race(self):
        phases, messages = [], []
        lifecycle = supervisor.Lifecycle(messages.append, phases.append)
        lifecycle.terminate(signal.SIGTERM, None)
        self.assertTrue(lifecycle.stop_requested)
        self.assertIsNone(lifecycle.child)
        child = Mock(pid=101)
        lifecycle.attach(child)
        child.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_duplicate_stop_does_not_abort_draining(self):
        lifecycle = supervisor.Lifecycle(lambda _: None, lambda _: None)
        child = Mock(pid=101)
        lifecycle.attach(child)
        lifecycle.terminate(signal.SIGTERM, None)
        lifecycle.terminate(signal.SIGTERM, None)
        child.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_signal_handler_defers_file_io(self):
        emit, persist = Mock(), Mock()
        lifecycle = supervisor.Lifecycle(emit, persist)
        lifecycle.attach(Mock(pid=101))
        lifecycle.terminate(signal.SIGTERM, None)
        emit.assert_not_called()
        persist.assert_not_called()
        lifecycle.flush_stop_notice()
        lifecycle.flush_stop_notice()
        persist.assert_called_once_with('stopping')
        emit.assert_called_once()

    def proc_fixture(self, ticks='123'):
        proc = self.root / 'proc'
        directory = proc / '101'
        directory.mkdir(parents=True)
        tail = ['0'] * 20
        tail[19] = ticks
        (directory / 'stat').write_text('101 (name with spaces) ' + ' '.join(tail))
        script = str(Path(supervisor.__file__).resolve())
        (directory / 'cmdline').write_bytes(b'python\0' + script.encode() + b'\0')
        return proc, {'pid': 101, 'start_ticks': '123', 'script': script}

    def test_pid_reuse_is_not_signalled(self):
        proc, state = self.proc_fixture(ticks='999')
        self.assertFalse(stop.same_process(state, proc))

    def test_pid_and_start_time_match(self):
        proc, state = self.proc_fixture()
        self.assertTrue(stop.same_process(state, proc))
        (proc / '101' / 'cmdline').write_bytes(b'python\0another-script.py\0')
        self.assertFalse(stop.same_process(state, proc))

    def test_hook_timeout_leaves_enforcement_to_platform(self):
        run = self.root / 'run'
        run.mkdir()
        state = {'pid': 101, 'script': str(Path(supervisor.__file__).resolve()),
                 'start_ticks': '123', 'phase': 'engine_started'}
        (run / 'supervisor-state.json').write_text(json.dumps(state))
        with patch.object(stop, 'runtime_paths', return_value=(self.root, self.model, run, self.root, 'pod-a')), \
             patch.object(stop, 'same_process', return_value=True), \
             patch.object(stop.os, 'kill') as send, \
             patch.object(stop.time, 'monotonic', side_effect=[0, 1151]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(stop.main(), 124)
            send.assert_called_once_with(101, signal.SIGTERM)

    def test_engine_grace_is_inside_platform_budget(self):
        args = supervisor.engine_arguments(self.model)
        timeout = int(args[args.index('--shutdown-timeout') + 1])
        self.assertLess(timeout, stop.HOOK_TIMEOUT_SECONDS)
        self.assertLess(stop.HOOK_TIMEOUT_SECONDS, supervisor.PLATFORM_GRACE_SECONDS)
        self.assertIn('--enable-expert-parallel', args)

if __name__ == '__main__':
    unittest.main()
