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
            json.dumps({'passed': True, 'core_sha256': 'core', 'profile_id':self.runtime.PROFILE_171['id'], 'profile_sha256':'profile', 'fixture_sha256':'fixture'}))
        module = {'sha256': self.runtime.PROFILE_171['hashes']['game'], 'name': 'game', 'path': 'game', 'base': '0x100000', 'size': 1}
        current = {'ready': True, 'pid': 42, 'modules': {'game': module, 'engine':{**module,'sha256':self.runtime.PROFILE_171['hashes']['engine']}},
                   'process_identity': {'creation_time_100ns': 1, 'executable': {}},
                   'objects': {'game': {'address': '0x200000'}, 'player': {'address': '0x300000'}},
                   'guarded_prologues': [], 'discovery_prologues': [],
                   'chain': {key: '0x400000' for key in ('game_global_slot', 'level', 'client', 'player_gate')}}
        self.discovery.HASHES = {'game': 'game', 'engine': 'game'}
        profile=self.runtime.PROFILE_171
        self.discovery.discover = Mock(return_value=current)
        with patch.object(self.runtime, 'ROOT', root), patch.object(self.runtime, 'static_proof',
                return_value={'core_sha256': 'core', 'function_guards': [], 'profile_id':self.runtime.PROFILE_171['id'], 'profile_sha256':'profile', 'fixture_sha256':'fixture','profile':profile}):
            for diagnostic in (False, True):
                config, _ = self.actual_prepare(ground_items=True, containers=True,
                                               dropped_items=True, diagnostic_only=diagnostic)
                self.assertEqual([config['values'][i] for i in (11, 13, 14, 15)],
                                 ['0' if diagnostic else '1'] * 4)

    def test_stale_profile_or_fixture_qualification_refuses_before_discovery(self):
        self.frida.__version__ = '17.24.0'
        root = self.args.output.parent
        (root / 'evidence').mkdir()
        proof_path = root / 'evidence/autoloot-runtime-dummy.json'
        binding = {'profile_id': 'reviewed', 'profile_sha256': 'profile',
                   'core_sha256': 'compiled', 'fixture_sha256': 'fixture'}
        self.discovery.discover = Mock(side_effect=forbidden)
        with patch.object(self.runtime, 'ROOT', root), patch.object(self.runtime, 'static_proof', return_value={**binding,'profile':self.runtime.PROFILE_171}):
            for key in binding:
                for value in ('stale', None):
                    proof = {'passed': True, **binding}
                    if value is None:
                        del proof[key]
                    else:
                        proof[key] = value
                    proof_path.write_text(json.dumps(proof))
                    with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'owned-fixture qualification'):
                        self.actual_prepare()
        self.discovery.discover.assert_not_called()

    def test_unreviewed_profile_refuses_before_player_discovery_or_attach(self):
        self.frida.__version__ = '17.24.0'
        profile = {**self.runtime.profile_by_name('1.8.1'),'hashes':self.runtime.PROFILE_171['hashes']}
        self.discovery.discover = Mock(side_effect=forbidden)
        with patch.object(self.runtime, 'static_proof', return_value={'profile': profile}):
            with self.assertRaisesRegex(ValueError, 'Exact reviewed'):
                self.actual_prepare()
        self.discovery.discover.assert_not_called()
        self.frida.attach.assert_not_called()

    def test_native_qualification_paths_are_distinct_by_profile(self):
        legacy = self.runtime.qualification_path(self.runtime.PROFILE_171)
        current = self.runtime.qualification_path(self.runtime.profile_by_name('1.8.1'))
        self.assertEqual(legacy.name, 'autoloot-runtime-dummy.json')
        self.assertNotEqual(legacy, current)
        self.assertIn('1.8.1.0na', current.name)

    def prepare_trial(self, profile=None, trial_181=True, **options):
        profile = self.runtime.profile_by_name('1.8.1') if profile is None else profile
        self.frida.__version__ = '17.24.0'
        binding = self.runtime.qualification_binding(profile)
        proof_path = self.args.output.parent / 'trial-qualification.json'
        proof_path.write_text(json.dumps({'passed': True, **binding}), encoding='utf-8')
        game = {'sha256': profile['hashes']['game'], 'name': 'game', 'path': 'game', 'base': '0x100000', 'size': 1}
        engine = {**game, 'sha256': profile['hashes']['engine']}
        current = {'ready': True, 'pid': 42, 'modules': {'game': game, 'engine': engine},
                   'process_identity': {'creation_time_100ns': 1, 'executable': {}},
                   'objects': {'game': {'address': '0x200000'}, 'player': {'address': '0x300000'}},
                   'guarded_prologues': [], 'discovery_prologues': [],
                   'chain': {key: '0x400000' for key in ('game_global_slot', 'level', 'client', 'player_gate')}}
        self.discovery.discover = Mock(return_value=current)
        with patch.object(self.runtime, 'static_proof', return_value={**binding, 'profile': profile, 'function_guards': []}), \
                patch.object(self.runtime, 'qualification_path', return_value=proof_path):
            config, proof = self.actual_prepare(trial_181=trial_181, **options)
        self.frida.attach.assert_not_called()
        return config, proof

    def test_both_normal_profiles_prepare_without_trial_contract(self):
        for profile in (self.runtime.PROFILE_171,self.runtime.profile_by_name('1.8.1')):
            config,_=self.prepare_trial(profile=profile,trial_181=False,ground_items=True,containers=True,dropped_items=True)
            self.assertIsNone(config['trial_181'])
            self.assertEqual(config['execution_mode'],'resident')
            self.assertEqual(config['profile_id'],profile['id'])
            self.assertEqual(config['profile_hashes'],profile['hashes'])

    def test_trial_prepare_imposes_exact_category_or_diagnostic_configuration(self):
        for diagnostic, category, cap, expected in [(True, 'corpses', 0, ['0', '0', '0', '0', '0']),
                (False, 'corpses', 1, ['0', '1', '1', '0', '0']),
                (False, 'ground', 1, ['1', '1', '0', '0', '0']),
                (False, 'dropped', 1, ['0', '1', '0', '0', '1']),
                (False, 'containers', 1, ['0', '1', '0', '1', '0'])]:
            config, _ = self.prepare_trial(duration=15.0009, diagnostic_only=diagnostic, trial_category=category, max_dispatches=cap)
            self.assertEqual(config['values'][11:16], expected)
            self.assertEqual(config['duration_ms'], 15000)
            self.assertEqual(config['trial_181']['duration_ms'], 15000)
            self.assertEqual(config['trial_181']['category'], category)
            self.assertEqual(config['execution_mode'], 'trial-181')
        config, _ = self.prepare_trial(duration=15, max_dispatches=1)
        self.assertEqual(config['trial_181']['category'], 'corpses')

    def test_trial_prepare_preserves_explicit_dispatch_cap(self):
        for category in ('corpses','ground','dropped','containers'):
            for cap in (1,32,64):
                config,_=self.prepare_trial(duration=15,trial_category=category,max_dispatches=cap)
                self.assertEqual(config['trial_181']['dispatch_cap'],cap)
                self.assertEqual(config['values'][12],str(cap))

    def test_trial_forbidden_options_refuse_before_discovery_or_frida(self):
        for diagnostic, category in [(False, value) for value in ('corpses', 'ground', 'dropped', 'containers')] + [(True, 'corpses')]:
            for option in ('ground_items', 'ground_only', 'containers', 'containers_only', 'dropped_items'):
                with self.subTest(diagnostic=diagnostic, category=category, option=option), self.assertRaisesRegex(ValueError, 'Trial181'):
                    self.prepare_trial(duration=15, diagnostic_only=diagnostic, max_dispatches=0 if diagnostic else 1,
                                       trial_category=category, **{option: True})
                self.discovery.discover.assert_not_called()
                self.frida.attach.assert_not_called()

    def test_trial_duration_caps_and_legacy_profile_refuse_before_frida(self):
        for category in ('corpses', 'ground', 'dropped', 'containers'):
            for duration in (0, -1, 30.001, 0.0009, float('nan'), float('inf')):
                with self.subTest(category=category, duration=duration), self.assertRaises(ValueError):
                    self.prepare_trial(duration=duration, max_dispatches=1, trial_category=category)
                self.discovery.discover.assert_not_called()
            for cap in (0, 65, True, 1.5):
                with self.subTest(category=category, cap=cap), self.assertRaises(ValueError):
                    self.prepare_trial(duration=15, max_dispatches=cap, trial_category=category)
                self.discovery.discover.assert_not_called()
            for profile in (self.runtime.PROFILE_171,
                            {**self.runtime.profile_by_name('1.8.1'), 'hashes': self.runtime.PROFILE_171['hashes']}):
                with self.subTest(category=category, profile=profile['id']), self.assertRaises(ValueError):
                    self.prepare_trial(profile=profile, duration=15, max_dispatches=1, trial_category=category)
                self.discovery.discover.assert_not_called()
        for cap in (1, 2):
            with self.subTest(diagnostic=True, cap=cap), self.assertRaises(ValueError):
                self.prepare_trial(duration=15, diagnostic_only=True, max_dispatches=cap)
            self.discovery.discover.assert_not_called()
        self.frida.attach.assert_not_called()

    def test_trial_category_refuses_outside_trial_or_in_noncorpse_diagnosis(self):
        self.discovery.discover = Mock(side_effect=forbidden)
        for category in ('corpses', 'ground', 'dropped', 'containers'):
            with self.subTest(category=category), self.assertRaises(ValueError):
                self.actual_prepare(trial_category=category)
            if category != 'corpses':
                with self.assertRaises(ValueError):
                    self.prepare_trial(duration=15, diagnostic_only=True, trial_category=category)
            self.discovery.discover.assert_not_called()
        for category in ('unknown', ''):
            with self.subTest(category=category), self.assertRaises(ValueError):
                self.prepare_trial(duration=15, trial_category=category, max_dispatches=1)
            self.discovery.discover.assert_not_called()
        self.frida.attach.assert_not_called()

    def test_trial_cli_rejects_dummy_and_static_before_backend(self):
        for mode in ('--dummy', '--static-only'):
            with self.subTest(mode=mode), patch.object(sys, 'argv', ['autoloot_runtime.py', mode, '--trial-181']), \
                    patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit) as error:
                self.runtime.main()
            self.assertEqual(error.exception.code, 2)
        self.frida.attach.assert_not_called()

    def test_trial_category_cli_requires_trial_marker_in_every_mode(self):
        for mode in ('--dummy', '--static-only', '--preflight-only', '--live'):
            for category in ('corpses', 'ground', 'dropped', 'containers'):
                with self.subTest(mode=mode, category=category), \
                        patch.object(sys, 'argv', ['autoloot_runtime.py', mode, '--trial-category', category]), \
                        patch('sys.stderr', new=io.StringIO()) as errors, self.assertRaises(SystemExit) as error:
                    self.runtime.main()
                self.assertEqual(error.exception.code, 2)
                self.assertIn('requires --trial-181', errors.getvalue())
        self.frida.attach.assert_not_called()

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
            'profile': self.runtime.PROFILE_171, 'core_sha256': hashlib.sha256(self.runtime.core_source().encode('utf-8')).hexdigest()}})
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
            'profile': self.runtime.PROFILE_171, 'core_sha256': hashlib.sha256(self.runtime.core_source().encode('utf-8')).hexdigest()}})
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
            'profile': self.runtime.PROFILE_171, 'core_sha256': hashlib.sha256(self.runtime.core_source().encode('utf-8')).hexdigest()}})

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
