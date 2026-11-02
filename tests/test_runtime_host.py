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
        self.actual_prepare = self.runtime.prepare
        self.runtime.prepare = Mock(side_effect=forbidden)
        self.runtime.lifecycle = SimpleNamespace(
            launch=immediate_launch, bounded=lambda function, seconds=5: function())

    def test_diagnostic_only_overrides_every_collection_switch(self):
        self.frida.__version__ = '17.24.0'
        root = self.args.output.parent
        (root / 'evidence').mkdir()
        (root / 'evidence/autoloot-runtime-dummy.json').write_text(
            json.dumps({'passed': True, 'core_sha256': 'core'}))
        module = {'sha256': 'game', 'name': 'game', 'path': 'game', 'base': '0x100000', 'size': 1}
        current = {'ready': True, 'pid': 42, 'modules': {'game': module, 'engine': module},
                   'process_identity': {'creation_time_100ns': 1, 'executable': {}},
                   'objects': {'game': {'address': '0x200000'}, 'player': {'address': '0x300000'}},
                   'guarded_prologues': [], 'discovery_prologues': [],
                   'chain': {key: '0x400000' for key in ('game_global_slot', 'level', 'client', 'player_gate')}}
        self.discovery.HASHES = {'game': 'game', 'engine': 'game'}
        self.discovery.discover = Mock(return_value=current)
        with patch.object(self.runtime, 'ROOT', root), patch.object(self.runtime, 'static_proof',
                return_value={'core_sha256': 'core', 'function_guards': []}):
            for diagnostic in (False, True):
                config, _ = self.actual_prepare(ground_items=True, containers=True,
                                               dropped_items=True, diagnostic_only=diagnostic)
                self.assertEqual([config['values'][i] for i in (11, 13, 14, 15)],
                                 ['0' if diagnostic else '1'] * 4)

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

    def test_launch_token_is_preserved_independently_of_host_pid(self):
        self.args.launch_token = 'launcher-generation-1234'
        with patch.object(self.runtime.os, 'getpid', return_value=9876):
            code, status, _ = self.run_host()
        self.assertEqual(code, 0)
        self.assertEqual(status['host_pid'], 9876)
        self.assertEqual(status['launch_token'], self.args.launch_token)

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

    def test_persistent_pause_before_host_refuses_setup_without_clearing_it(self):
        self.args.pause_file = self.args.status.with_name('watch.pause')
        self.args.pause_file.write_text('paused before host birth')
        self.args.stop_file.write_text('old request')
        def clear_old_stop(path):
            path.unlink()
            return False
        self.control.clear_stale_stop.side_effect = clear_old_stop
        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        self.assertEqual(status['phase'], 'stopped')
        self.control.clear_stale_stop.assert_not_called()
        self.discovery.api_setup.assert_not_called()
        self.frida.attach.assert_not_called()
        self.assertEqual(self.args.pause_file.read_text(), 'paused before host birth')

    def pause_transport(self, phase):
        self.args.pause_file = self.args.status.with_name('watch.pause')
        trace, callbacks = [], {}
        def pause():
            self.args.pause_file.write_text('persistent user pause')
        def load():
            trace.append('load')
            if phase == 'load':pause()
            callbacks['message']({'type': 'send', 'payload': {'type': 'armed'}}, None)
        def create(*args, **kwargs):
            trace.append('create')
            if phase == 'create':pause()
            return script
        def active_poll():
            trace.append('poll')
            self.args.stop_file.write_text('end isolated old-version test')
            return {'type': 'poll', 'result': {'ready': False}}
        def stop():
            trace.append('stop')
            return {'type': 'stopped', 'restoration_verified': True, 'detach_done': True,
                    'errors': [], 'cleanup_errors': [], 'result': {}}
        script = SimpleNamespace(on=Mock(side_effect=lambda name, callback: callbacks.__setitem__(name, callback)),
                load=Mock(side_effect=load), unload=Mock(side_effect=lambda: trace.append('unload')),
                exports_sync=SimpleNamespace(poll=Mock(side_effect=active_poll), stop=Mock(side_effect=stop)))
        session = SimpleNamespace(on=Mock(), create_script=Mock(side_effect=create),
                                  detach=Mock(side_effect=lambda: trace.append('detach')))
        self.frida.attach.side_effect = None
        self.frida.attach.return_value = session
        self.discovery.process_ids.return_value = [42]
        self.runtime.prepare.side_effect = None
        self.runtime.prepare.return_value = ({'pid': 42}, {'query': {
            'core_sha256': hashlib.sha256(SOURCE.with_suffix('.c').read_bytes()).hexdigest()}})
        return script, trace

    def test_pause_during_creation_never_loads(self):
        script, trace = self.pause_transport('create')
        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        script.load.assert_not_called()
        self.assertEqual(trace, ['create', 'detach'])
        self.assertTrue(report['cleanup']['no_script_execution'])
        self.assertTrue(self.args.pause_file.exists())

    def test_pause_during_load_uses_normal_unload_barrier(self):
        script, trace = self.pause_transport('load')
        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        script.exports_sync.poll.assert_not_called()
        self.assertEqual(trace, ['create', 'load', 'stop', 'unload', 'detach'])
        self.assertTrue(report['cleanup']['script_unloaded'])
        self.assertTrue(report['cleanup']['session_detached'])
        self.assertTrue(self.args.pause_file.exists())

    def test_cli_accepts_optional_persistent_pause_path(self):
        pause = self.args.status.with_name('watch.pause')
        with patch.object(self.runtime.sys, 'argv', ['autoloot_runtime.py', '--live', '--pause-file', str(pause)]), \
                patch.object(self.runtime, 'live', return_value=0) as live:
            self.assertEqual(self.runtime.main(), 0)
        self.assertEqual(live.call_args.args[0].pause_file, pause)

    def closing_transport(self, phase='stop', *, crash=None, reason='process-terminated', native_fault=False, stop_fault=False, cleanup_fault=False, js_fault=False, poll_error=None, destroyed_message='script has been destroyed'):
        callbacks, trace = {}, []
        invalid = type('InvalidOperationError', (Exception,), {})
        self.frida.InvalidOperationError = invalid
        def close():
            callbacks['detached'](reason, crash)
        def load():
            callbacks['message']({'type': 'send', 'payload': {'type': 'armed'}}, None)
            if js_fault:
                callbacks['message']({'type': 'error', 'description': 'script fault before exit'}, None)
        polls = []
        def poll():
            trace.append('poll')
            if not polls:
                polls.append(True)
                return {'type': 'poll', 'result': {'ready': True, 'stats': {'cycles': 7, 'disabled': int(native_fault)}}}
            if phase in ('poll_stopped','send_stopped'):
                value={'type':'stopped','errors':['stopped native fault'] if stop_fault else [],
                       'cleanup_errors':['stopped cleanup fault'] if cleanup_fault else [],
                       'result':{'ready':True,'stats':{'cycles':8}}}
                if phase=='send_stopped':callbacks['message']({'type':'send','payload':value},None)
                close()
                return value if phase=='poll_stopped' else {'type':'poll'}
            if phase == 'unload_clean':return {'type': 'stopped'}
            if phase == 'poll':close()
            raise poll_error if poll_error is not None else TimeoutError('poll interrupted during target exit')
        def stop():
            trace.append('stop')
            if phase == 'stop':
                close()
                raise invalid(destroyed_message)
            return {'type': 'stopped', 'restoration_verified': True, 'detach_done': True,
                    'errors': ['native stop fault'] if stop_fault else [], 'cleanup_errors': ['cleanup fault'] if cleanup_fault else []}
        def unload():
            trace.append('unload')
            if phase in ('unload', 'unload_clean'):
                close()
                if phase == 'unload':raise invalid(destroyed_message)
        script = SimpleNamespace(on=Mock(side_effect=lambda name, callback: callbacks.__setitem__(name, callback)),
                                 load=Mock(side_effect=load), unload=Mock(side_effect=unload),
                                 exports_sync=SimpleNamespace(poll=Mock(side_effect=poll), stop=Mock(side_effect=stop)))
        session = SimpleNamespace(on=Mock(side_effect=lambda name, callback: callbacks.__setitem__(name, callback)),
                                  create_script=Mock(return_value=script), detach=Mock(side_effect=forbidden))
        self.frida.attach.side_effect = None
        self.frida.attach.return_value = session
        self.discovery.process_ids.return_value = [42]
        self.runtime.prepare.side_effect = None
        self.runtime.prepare.return_value = ({'pid': 42}, {'query': {
            'core_sha256': hashlib.sha256(SOURCE.with_suffix('.c').read_bytes()).hexdigest()}})
        return script, session, trace

    def test_poll_timeout_then_exit_during_stop_is_clean_and_skips_unload(self):
        for text in ('script has been destroyed', 'script is destroyed'):
            with self.subTest(message=text):
                script, session, trace = self.closing_transport(destroyed_message=text)
                code, status, report = self.run_host()
                self.assertEqual(code, 0)
                self.assertEqual(status['phase'], 'game_closed')
                self.assertEqual(report['result']['stats']['cycles'], 7)
                self.assertEqual([row['phase'] for row in report['rpc_interruptions']], ['poll', 'stop'])
                self.assertNotIn('script_unloaded', report['cleanup'])
                script.unload.assert_not_called()
                session.detach.assert_not_called()

    def test_exit_during_unload_keeps_transport_diagnostics_without_false_failure(self):
        for text in ('script has been destroyed', 'script is destroyed'):
            with self.subTest(message=text):
                script, session, trace = self.closing_transport('unload', destroyed_message=text)
                code, status, report = self.run_host()
                self.assertEqual(code, 0)
                self.assertEqual([row['phase'] for row in report['rpc_interruptions']], ['poll', 'unload'])
                self.assertNotIn('script_unloaded', report['cleanup'])
                session.detach.assert_not_called()

    def test_confirmed_exit_does_not_hide_faults_or_other_disconnects(self):
        cases = [dict(native_fault=True), dict(phase='poll', crash='access violation'),
                 dict(phase='poll', reason='connection-terminated'),
                 dict(phase='unload_clean', stop_fault=True), dict(phase='unload_clean', cleanup_fault=True), dict(phase='unload_clean', js_fault=True)]
        for options in cases:
            with self.subTest(options=options):
                script, session, trace = self.closing_transport(**options)
                with redirect_stdout(io.StringIO()):code = self.runtime._live(self.args)
                report = json.loads(self.args.output.read_text(encoding='utf-8'))
                self.assertEqual(code, 1)
                self.assertFalse(report['ok'])
                if options.get('native_fault'):
                    self.assertTrue(any('Native runtime disabled' in error for error in report['errors']))
                if options.get('js_fault'):
                    self.assertTrue(any('script fault before exit' in error for error in report['errors']))
                session.detach.assert_not_called()

    def test_stopped_payload_from_poll_or_send_survives_target_exit(self):
        for phase in ('poll_stopped', 'send_stopped'):
            for fault in ('stop_fault', 'cleanup_fault'):
                with self.subTest(phase=phase, fault=fault):
                    script, session, trace = self.closing_transport(phase, **{fault: True})
                    with redirect_stdout(io.StringIO()):code = self.runtime._live(self.args)
                    report = json.loads(self.args.output.read_text(encoding='utf-8'))
                    self.assertEqual(code, 1)
                    self.assertFalse(report['ok'])
                    self.assertEqual(report['result']['stats']['cycles'], 8)
                    self.assertTrue(report['cleanup']['stop_rpc']['errors'] or report['cleanup']['stop_rpc']['cleanup_errors'])
                    script.unload.assert_not_called()
                    session.detach.assert_not_called()

    def test_nontransport_poll_fault_survives_confirmed_process_exit(self):
        for error in (ValueError('poll payload bug'), RuntimeError('arbitrary runtime fault'), RuntimeError('RPCException: JavaScript bug'),
                      RuntimeError('InvalidOperationError: unrelated invalid API operation'),
                      RuntimeError('RuntimeError: InvalidOperationError: arbitrary nested fault')):
            with self.subTest(error=error):
                self.closing_transport('poll', poll_error=error)
                with redirect_stdout(io.StringIO()):code = self.runtime._live(self.args)
                report = json.loads(self.args.output.read_text(encoding='utf-8'))
                self.assertEqual(code, 1)
                self.assertTrue(report['errors'])
                self.assertFalse(report.get('rpc_interruptions'))

    def test_bounded_backend_transport_wrapper_is_classified_narrowly(self):
        script, session, trace = self.closing_transport('poll',
                poll_error=RuntimeError('InvalidOperationError: script has been destroyed'))
        code, status, report = self.run_host()
        self.assertEqual(code, 0)
        self.assertEqual([row['phase'] for row in report['rpc_interruptions']], ['poll'])
        script.unload.assert_not_called()
        session.detach.assert_not_called()

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
