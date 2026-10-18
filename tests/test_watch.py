"""Watcher control tests. All game/process/spawn boundaries use disposable fakes."""
import importlib.util
from contextlib import nullcontext
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('autoloot_watch', ROOT / 'tools/autoloot_watch.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class Child:
    pid = 30
    code = None
    def poll(self):
        return self.code


class Backend:
    def __init__(self, args):
        self.args = args
        self.mutex = False
        self.identities = {10: '1000', 40: '4000'}
        self.proof = {'ready': True, 'pid': 10, 'process_identity': {'creation_time_100ns': '1000'}}
        self.child = Child()
        self.spawns = []
        self.ready_calls = 0
        self.during_ready = self.during_spawn = None
        self.held = False
        self.released = []
    def runtime_running(self):
        return self.mutex
    def identity(self, pid):
        return self.identities.get(pid)
    def retain_host(self, pid, birth):
        if self.identity(pid) == birth:
            self.held = True
            return (pid, birth)
    def host_alive(self, held):
        return self.held
    def release_host(self, held):
        self.released.append(held)
    def ready(self):
        self.ready_calls += 1
        if self.during_ready:
            self.during_ready()
        return self.proof
    def spawn(self, proof, token):
        self.spawns.append((proof, token))
        if self.during_spawn:
            self.during_spawn()
        return self.child


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.args = SimpleNamespace(status=root/'watch-status.json', runtime_status=root/'status.json',
                    pause_file=root/'watch.pause', stop_file=root/'stop.request', watch_stop_file=root/'watch.stop',
                    worker_log=root/'watch-worker.log', poll_seconds=10, launch_token='watcher-test')
        self.backend = Backend(self.args)
        self.now = 0
        self.watcher = watch.Watcher(self.args, self.backend, lambda: self.now)

    def publish_worker(self):
        self.args.runtime_status.write_text(json.dumps({'launch_token': self.watcher.token, 'host_pid': 40}))

    def test_initial_status_failure_never_constructs_backend(self):
        with patch.object(watch, 'WatcherInstance', return_value=nullcontext()), \
                patch.object(watch, 'write_json', return_value=False), \
                patch.object(watch, 'WindowsBackend', side_effect=OSError('Backend must not be reached')) as backend:
            with self.assertRaises(OSError):
                watch.live(self.args)
        backend.assert_not_called()

    def test_status_failure_before_spawn_refuses_new_worker(self):
        with patch.object(watch, 'write_json', return_value=False):
            with self.assertRaises(OSError):
                self.watcher.step()
        self.assertFalse(self.backend.spawns)
        self.assertIsNone(self.watcher.worker)

    def test_game_absent_does_not_launch(self):
        self.backend.proof = {'ready': False, 'phase': 'waiting_game'}
        state = self.watcher.step()
        self.assertEqual(state['state'], 'waiting_game')
        self.assertEqual(self.backend.spawns, [])
        self.assertEqual(state['host_pid'], watch.os.getpid())
        self.assertEqual(state['launch_token'], 'watcher-test')

    def test_menu_waits_until_ready(self):
        self.backend.proof = {'ready': False, 'phase': 'waiting_session'}
        self.assertEqual(self.watcher.step()['state'], 'waiting_session')
        self.assertFalse(self.backend.spawns)
        self.backend.proof = {'ready': True, 'pid': 10, 'process_identity': {'creation_time_100ns': '1000'}}
        self.watcher.step()
        self.assertEqual(len(self.backend.spawns), 1)

    def test_running_worker_has_no_repeat_discovery_or_overlap(self):
        self.watcher.step()
        self.publish_worker()
        self.backend.mutex = True
        for _ in range(4):
            state = self.watcher.step()
        self.assertEqual(state['state'], 'worker_running')
        self.assertEqual(self.backend.ready_calls, 1)
        self.assertEqual(len(self.backend.spawns), 1)
        self.assertEqual(state['worker_host_pid'], 40)
        self.assertEqual(state['worker_host_creation_time_100ns'], '4000')

    def test_existing_manual_runtime_is_not_duplicated(self):
        self.backend.mutex = True
        self.assertEqual(self.watcher.step()['state'], 'worker_running')
        self.assertEqual(self.backend.ready_calls, 0)
        self.assertFalse(self.backend.spawns)

    def test_pause_persists_and_resume_launches(self):
        self.args.pause_file.write_text('user pause')
        self.assertEqual(self.watcher.step()['state'], 'paused')
        self.assertTrue(self.args.stop_file.exists())
        self.assertFalse(self.backend.spawns)
        self.args.pause_file.unlink()
        self.watcher.step()
        self.assertEqual(len(self.backend.spawns), 1)

    def test_stop_then_resume_between_polls_does_not_repause(self):
        self.watcher.step()
        self.args.pause_file.write_text('manual stop')
        self.args.stop_file.write_text('manual stop')
        stop_ns = watch.stamp(self.args.stop_file)
        resume = self.args.status.with_name('watch.resume')
        resume.write_text('new nonce')
        watch.os.utime(resume, ns=(stop_ns+1000000, stop_ns+1000000))
        self.args.pause_file.unlink()
        state = self.watcher.step()
        self.assertFalse(self.args.pause_file.exists())
        self.assertEqual(state['state'], 'worker_running')

    def test_stop_newer_than_resume_still_pauses(self):
        resume = self.args.status.with_name('watch.resume')
        resume.write_text('old resume')
        birth = watch.stamp(resume)
        self.args.stop_file.write_text('new stop')
        watch.os.utime(self.args.stop_file, ns=(birth+1000000, birth+1000000))
        self.assertEqual(self.watcher.step()['state'], 'paused')
        self.assertTrue(self.args.pause_file.exists())

    def test_resume_does_not_override_existing_pause(self):
        self.args.pause_file.write_text('stop remains in progress')
        self.args.status.with_name('watch.resume').write_text('resume before pause removal')
        self.assertEqual(self.watcher.step()['state'], 'paused')
        self.assertFalse(self.backend.spawns)

    def test_stop_written_during_readiness_blocks_activation(self):
        self.backend.during_ready = lambda: self.args.pause_file.write_text('manual stop')
        self.assertEqual(self.watcher.step()['state'], 'paused')
        self.assertFalse(self.backend.spawns)

    def test_legacy_stop_written_during_readiness_is_persistent_pause(self):
        self.backend.during_ready = lambda: self.args.stop_file.write_text('manual stop')
        self.assertEqual(self.watcher.step()['state'], 'paused')
        self.assertTrue(self.args.pause_file.exists())
        self.assertFalse(self.backend.spawns)

    def test_pause_during_spawn_requests_cooperative_stop(self):
        self.backend.during_spawn = lambda: self.args.pause_file.write_text('manual stop')
        self.watcher.step()
        self.assertTrue(self.args.stop_file.exists())
        self.assertEqual(len(self.backend.spawns), 1)
        self.assertEqual(self.watcher.step()['phase'], 'stopping')
        self.assertEqual(len(self.backend.spawns), 1)

    def test_watcher_shutdown_persists_pause_before_real_host_birth(self):
        self.watcher.step()
        self.args.watch_stop_file.write_text('watcher stop before actual host starts')
        self.assertEqual(self.watcher.step()['phase'], 'stopping')
        self.assertTrue(self.args.pause_file.exists())
        self.assertTrue(self.args.stop_file.exists())

    def test_shutdown_during_spawn_persists_pause(self):
        self.backend.during_spawn = lambda: self.args.watch_stop_file.write_text('stop during handoff')
        self.watcher.step()
        self.assertTrue(self.args.pause_file.exists())
        self.assertTrue(self.args.stop_file.exists())
        self.assertEqual(len(self.backend.spawns), 1)

    def test_game_pid_reuse_refuses_start(self):
        self.backend.identities[10] = 'other-birth'
        with self.assertRaisesRegex(ValueError, 'Game identity changed'):
            self.watcher.step()
        self.assertFalse(self.backend.spawns)

    def test_redirector_exit_does_not_mean_host_exit(self):
        self.watcher.step()
        self.publish_worker()
        self.backend.child.code = 0
        self.now = 100
        state = self.watcher.step()
        self.assertEqual(state['state'], 'worker_running')
        self.assertIsNotNone(self.watcher.worker)
        self.assertEqual(len(self.backend.spawns), 1)

    def test_wrong_nonce_does_not_adopt_host(self):
        self.watcher.step()
        self.args.runtime_status.write_text(json.dumps({'launch_token': 'old', 'host_pid': 40}))
        self.watcher.step()
        self.assertIsNone(self.watcher.host_pid)
        self.assertFalse(self.backend.held)

    def test_close_game_then_restart_is_new_identity(self):
        self.watcher.step()
        self.publish_worker()
        self.watcher.step()
        del self.backend.identities[10]
        self.assertEqual(self.watcher.step()['phase'], 'stopping')
        self.assertTrue(self.args.stop_file.exists())
        self.backend.child.code = 0
        self.backend.held = False
        self.backend.proof = {'ready': False, 'phase': 'waiting_game'}
        self.assertEqual(self.watcher.step()['state'], 'waiting_game')
        self.assertTrue(self.backend.released)
        self.backend.proof = {'ready': True, 'pid': 11, 'process_identity': {'creation_time_100ns': '1100'}}
        self.backend.identities[11] = '1100'
        self.backend.child = Child()
        self.watcher.step()
        self.assertEqual(len(self.backend.spawns), 2)
        self.assertEqual(self.watcher.game_pid, 11)
        self.assertFalse(self.args.pause_file.exists())

    def test_watcher_stop_waits_for_real_host_handle(self):
        self.watcher.step()
        self.publish_worker()
        self.watcher.step()
        self.backend.child.code = 0
        self.args.watch_stop_file.write_text('uninstall')
        self.assertEqual(self.watcher.step()['phase'], 'stopping')
        self.assertTrue(self.args.stop_file.exists())
        self.backend.held = False
        self.assertEqual(self.watcher.step()['state'], 'stopped')
        self.assertEqual(len(self.backend.spawns), 1)

    def test_gui_binary_is_required(self):
        path = Path(self.temp.name)/'pythonw.exe'
        data = bytearray(200)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 64)
        data[64:68] = b'PE\0\0'
        struct.pack_into('<H', data, 68, 0x8664)
        struct.pack_into('<H', data, 88, 0x20b)
        struct.pack_into('<H', data, 156, 2)
        path.write_bytes(data)
        self.assertEqual(watch.gui_python(path), path)
        struct.pack_into('<H', data, 156, 3)
        path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'GUI'):
            watch.gui_python(path)

    def test_actual_spawn_contract_no_console_or_shell(self):
        backend = object.__new__(watch.WindowsBackend)
        backend.args = self.args
        backend.pythonw = Path(self.temp.name)/'pythonw.exe'
        with patch.object(watch.subprocess, 'Popen', return_value=Child()) as popen, \
                patch.object(watch.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True):
            backend.spawn(self.backend.proof, 'nonce')
        command = popen.call_args.args[0]
        options = popen.call_args.kwargs
        self.assertEqual(command[0], str(backend.pythonw))
        self.assertIn('--ground-items', command)
        self.assertIn('--containers', command)
        self.assertIn('--pause-file', command)
        self.assertEqual(command[command.index('--pause-file')+1], str(self.args.pause_file))
        self.assertEqual(command[command.index('--launch-token')+1], 'nonce')
        self.assertEqual(options['creationflags'], 0x08000000)
        self.assertNotIn('shell', options)
        self.assertIsNotNone(options['stdout'])
        self.assertEqual(options['stderr'], watch.subprocess.STDOUT)

    @unittest.skipUnless(watch.os.name == 'nt', 'Windows GUI process contract')
    def test_installed_pythonw_owned_child_has_no_console(self):
        try:
            executable = watch.python_executable(watch.ROOT, windowed=True)
        except FileNotFoundError:
            self.skipTest('Run installer before the real pythonw fixture')
        watch.gui_python(executable)
        output = Path(self.temp.name)/'owned-gui-child.json'
        code = ("import ctypes,json,os;from pathlib import Path;"
                "kernel=ctypes.WinDLL('kernel32');kernel.GetConsoleWindow.restype=ctypes.c_void_p;"
                "Path(" + repr(str(output)) + ").write_text(json.dumps({'pid':os.getpid(),'console':kernel.GetConsoleWindow()}))")
        child = watch.subprocess.Popen([str(executable), '-c', code], stdin=watch.subprocess.DEVNULL,
                    stdout=watch.subprocess.DEVNULL, stderr=watch.subprocess.DEVNULL,
                    creationflags=watch.subprocess.CREATE_NO_WINDOW)
        try:
            self.assertEqual(child.wait(timeout=10), 0)
            result = json.loads(output.read_text())
            self.assertGreater(result['pid'], 0)
            self.assertIn(result['console'], (None, 0))
        finally:
            if child.poll() is None:
                child.terminate()  # Disposable fixture child only; never a game/runtime process.
                child.wait(timeout=5)

    def test_status_io_failure_does_not_drop_owned_child(self):
        self.watcher.step()
        with patch.object(watch, 'write_json', return_value=False):
            self.assertEqual(self.watcher.step()['state'], 'worker_running')
        self.assertIsNotNone(self.watcher.worker)

    def test_backend_resolves_interpreter_before_gui_validation(self):
        api = SimpleNamespace(OpenMutexW=Mock(), WaitForSingleObject=Mock())
        discovery = SimpleNamespace(api_setup=Mock(return_value=api))
        expected = self.args.status.parent/'runtime/pythonw.exe'
        with patch.dict(sys.modules, {'discover_session': discovery}), \
                patch.object(watch, 'python_executable', return_value=expected) as resolve, \
                patch.object(watch, 'gui_python', return_value=expected) as validate:
            backend = watch.WindowsBackend(self.args)
        resolve.assert_called_once_with(watch.ROOT, windowed=True)
        validate.assert_called_once_with(expected)
        self.assertEqual(backend.pythonw, expected)

    def test_empty_game_enumeration_does_not_parse_pe_or_discover(self):
        backend = object.__new__(watch.WindowsBackend)
        backend.api = object()
        backend.discovery = SimpleNamespace(process_ids=Mock(return_value=[]), discover=Mock())
        self.assertEqual(backend.ready()['phase'], 'waiting_game')
        backend.discovery.discover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
