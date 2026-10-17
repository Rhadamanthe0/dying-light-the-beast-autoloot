"""Host shutdown regressions using the real runtime and fake native transport.

No Frida, PE parser, Windows kernel or game discovery backend is imported.
The C/JS sources are read as ordinary files; no CModule is constructed.
"""
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'tools/autoloot_runtime.py'


def forbidden(*args, **kwargs):
    raise AssertionError('A real backend or unexpected native operation was requested')


def immediate_launch(function):
    done, result = threading.Event(), {}
    try:
        result['value'] = function()
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    done.set()
    return done, result


class RuntimeHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='autoloot-host-test-')
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.args = SimpleNamespace(output=directory / 'report.json',
                                    status=directory / 'status.json',
                                    stop_file=directory / 'stop.request',
                                    session=None, duration=0, pid=42)
        self.frida = ModuleType('frida')
        self.frida.attach = Mock(side_effect=forbidden)
        self.discovery = ModuleType('discover_session')
        self.discovery.api_setup = Mock(return_value=object())
        self.discovery.process_ids = Mock(return_value=[])
        self.native = ModuleType('inspect_native')
        self.native.Image = Mock(side_effect=forbidden)
        self.control = ModuleType('runtime_control')
        self.control.SingleInstance = Mock(side_effect=forbidden)
        self.control.AlreadyRunning = type('AlreadyRunning', (RuntimeError,), {})
        self.control.clear_stale_stop = Mock(side_effect=lambda path: path.exists())
        fakes = {'frida': self.frida, 'discover_session': self.discovery,
                 'inspect_native': self.native, 'runtime_control': self.control}
        # Execute the real module with only its external boundaries substituted.
        # sys.modules is restored immediately so discovery of other tests is safe.
        with patch.dict(sys.modules, fakes):
            spec = importlib.util.spec_from_file_location('autoloot_runtime_host_tested', SOURCE)
            self.runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.runtime)
        self.runtime.prepare = Mock(side_effect=forbidden)
        self.runtime.lifecycle = SimpleNamespace(
            launch=immediate_launch, bounded=lambda function, seconds=5: function())

    def run_host(self):
        with redirect_stdout(io.StringIO()):
            code = self.runtime._live(self.args)
        status = json.loads(self.args.status.read_text(encoding='utf-8'))
        report = json.loads(self.args.output.read_text(encoding='utf-8'))
        self.assertFalse(status['running'])
        self.assertFalse(status['ready'])
        self.assertEqual(report['errors'], [])
        self.assertTrue(report['ok'])
        self.native.Image.assert_not_called()
        self.control.SingleInstance.assert_not_called()
        return code, status, report

    def test_game_closed_at_startup_exits_without_attach(self):
        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        self.assertEqual(status['phase'], 'game_closed')
        self.assertTrue(report['game_closed'])
        self.assertTrue(report['cleanup']['no_script_execution'])
        self.discovery.process_ids.assert_called_once()
        self.runtime.prepare.assert_not_called()
        self.frida.attach.assert_not_called()

    def test_stop_file_before_setup_exits_without_hook(self):
        self.args.stop_file.write_text('user stop', encoding='utf-8')
        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        self.assertEqual(status['phase'], 'stopped')
        self.assertTrue(report['stop_before_setup'])
        self.assertTrue(report['cleanup']['no_script_execution'])
        self.assertTrue(self.args.stop_file.exists())
        self.discovery.api_setup.assert_not_called()
        self.runtime.prepare.assert_not_called()
        self.frida.attach.assert_not_called()

    def test_process_terminated_during_poll_skips_dead_process_cleanup(self):
        callbacks = {}
        script = SimpleNamespace()
        session = SimpleNamespace()
        script.on = Mock(side_effect=lambda name, callback: callbacks.__setitem__(name, callback))
        session.on = Mock(side_effect=lambda name, callback: callbacks.__setitem__(name, callback))
        script.load = Mock(side_effect=lambda: callbacks['message'](
            {'type': 'send', 'payload': {'type': 'armed'}}, None))

        def terminate_on_poll():
            callbacks['detached']('process-terminated', None)
            return {'type': 'poll', 'result': {'ready': False}}

        script.exports_sync = SimpleNamespace(poll=Mock(side_effect=terminate_on_poll),
                                              stop=Mock(side_effect=forbidden))
        script.unload = Mock(side_effect=forbidden)
        session.detach = Mock(side_effect=forbidden)
        session.create_script = Mock(return_value=script)
        self.frida.attach.side_effect = None
        self.frida.attach.return_value = session
        self.discovery.process_ids.return_value = [42]
        self.runtime.prepare.side_effect = None
        self.runtime.prepare.return_value = ({'pid': 42}, {'query': {
            'core_sha256': hashlib.sha256(SOURCE.with_suffix('.c').read_bytes()).hexdigest()}})

        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        self.assertEqual(status['phase'], 'game_closed')
        self.assertTrue(report['game_closed'])
        self.assertEqual(report['detached_event']['reason'], 'process-terminated')
        self.assertTrue(report['cleanup']['session_detached'])
        self.frida.attach.assert_called_once_with(42)
        session.create_script.assert_called_once()
        script.load.assert_called_once()
        script.exports_sync.poll.assert_called_once()
        script.exports_sync.stop.assert_not_called()
        script.unload.assert_not_called()
        session.detach.assert_not_called()


if __name__ == '__main__':
    unittest.main()
