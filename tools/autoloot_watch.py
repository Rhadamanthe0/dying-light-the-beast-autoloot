"""Invisible per-user watcher; no Frida attach or game code in this process."""
import argparse
import ctypes
from ctypes import wintypes as W
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'evidence/autoloot5m'
POLL_SECONDS = 10


def write_json(path, value):
    """Readers on Windows may briefly deny replace; never unwind worker cleanup."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return True
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.05)
    except OSError:
        return False


def stamp(path):
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


def gui_python(path):
    """Require the installed GUI executable, never a console fallback."""
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('pythonw.exe: missing DOS header')
        offset = struct.unpack_from('<I', header, 60)[0]
        if not 64 <= offset <= 1024 * 1024:
            raise ValueError('pythonw.exe: invalid PE offset')
        stream.seek(offset)
        pe = stream.read(96)
    if len(pe) != 96 or pe[:4] != b'PE\0\0' or struct.unpack_from('<H', pe, 4)[0] != 0x8664 or \
            struct.unpack_from('<H', pe, 24)[0] != 0x20b or struct.unpack_from('<H', pe, 92)[0] != 2:
        raise ValueError('Installed x64 GUI pythonw.exe required; no console executable allowed')
    return path


def append_log(path, message):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
            os.replace(path, path.with_suffix('.log.old'))
        with path.open('a', encoding='utf-8') as stream:
            stream.write(datetime.now(timezone.utc).isoformat() + ' ' + message + '\n')
    except OSError:
        pass


class AlreadyWatching(RuntimeError):
    pass


class WatcherInstance:
    """Separate from the runtime mutex, scoped like it to this Windows user/session."""
    def __enter__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [W.LPVOID, W.BOOL, W.LPCWSTR]
        self.kernel.CreateMutexW.restype = W.HANDLE
        self.kernel.ReleaseMutex.argtypes = [W.HANDLE]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        ctypes.set_last_error(0)
        self.handle = self.kernel.CreateMutexW(None, True, 'Local\\DLTB_AutoLoot_Watcher_' + os.environ.get('USERNAME', 'user'))
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise AlreadyWatching('AutoLoot watcher is already running.')
        return self

    def __exit__(self, *ignored):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class WindowsBackend:
    def __init__(self, args):
        sys.path.insert(0, str(ROOT / '.deps'))
        sys.path.insert(0, str(ROOT / 'tools'))
        import discover_session
        self.discovery = discover_session
        self.api = discover_session.api_setup()
        self.api.OpenMutexW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
        self.api.OpenMutexW.restype = W.HANDLE
        self.api.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.api.WaitForSingleObject.restype = W.DWORD
        self.pythonw = gui_python(ROOT / '.venv/Scripts/pythonw.exe')
        self.args = args

    def runtime_running(self):
        ctypes.set_last_error(0)
        handle = self.api.OpenMutexW(0x00100000, False, 'Local\\DLTB_AutoLoot_Resident_' + os.environ.get('USERNAME', 'user'))
        if handle:
            self.api.CloseHandle(handle)
            return True
        if ctypes.get_last_error() not in (0, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        return False

    def identity(self, pid):
        handle = self.api.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error in (87, 1168):
                return None
            raise ctypes.WinError(error)
        try:
            code = W.DWORD()
            if not self.api.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            if code.value != 259:
                return None
            return str(self.discovery.creation_time(self.api, handle))
        finally:
            self.api.CloseHandle(handle)

    def retain_host(self, pid, birth):
        handle = self.api.OpenProcess(0x00101000, False, pid)
        if not handle:
            if ctypes.get_last_error() in (87, 1168):
                return None
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if str(self.discovery.creation_time(self.api, handle)) != birth:
                self.api.CloseHandle(handle)
                return None
            return handle
        except BaseException:
            self.api.CloseHandle(handle)
            raise

    def host_alive(self, handle):
        result = self.api.WaitForSingleObject(handle, 0)
        if result not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 258

    def release_host(self, handle):
        self.api.CloseHandle(handle)

    def ready(self):
        pids = self.discovery.process_ids(self.api)
        if not pids:
            return {'ready': False, 'phase': 'waiting_game'}
        if len(pids) != 1:
            return {'ready': False, 'phase': 'waiting_session', 'reason': 'Multiple game processes found; activation refused.'}
        try:
            # Existing discovery has a 1s/4096 reads/8MiB memory budget and no injection.
            return self.discovery.discover(pids[0])
        except (OSError, ValueError) as error:
            return {'ready': False, 'phase': 'waiting_session', 'reason': str(error), 'pid': pids[0]}

    def spawn(self, proof, token):
        session_path = self.args.status.with_name('watch-session.json')
        if not write_json(session_path, proof):
            raise OSError('Cannot save fresh session discovery; no worker started.')
        self.args.worker_log.parent.mkdir(parents=True, exist_ok=True)
        if self.args.worker_log.exists() and self.args.worker_log.stat().st_size > 2 * 1024 * 1024:
            os.replace(self.args.worker_log, self.args.worker_log.with_suffix('.log.old'))
        command = [str(self.pythonw), str(ROOT / 'tools/autoloot_runtime.py'), '--live', '--pid', str(proof['pid']),
                   '--session', str(session_path), '--ground-items', '--containers', '--launch-token', token,
                   '--status', str(self.args.runtime_status), '--stop-file', str(self.args.stop_file),
                   '--pause-file', str(self.args.pause_file),
                   '--output', str(self.args.status.with_name('watch-runtime.json'))]
        with self.args.worker_log.open('ab') as output:
            return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                    cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW)


class Watcher:
    def __init__(self, args, backend, clock=time.monotonic):
        self.args, self.backend, self.clock = args, backend, clock
        self.worker = None
        self.token = self.host_pid = self.host_birth = self.game_pid = self.game_birth = None
        self.host_handle = None
        self.spawned_at = 0
        self.starts = 0
        self.last_exit = None
        self.last_error = ''
        self.stop_stamp = stamp(args.stop_file)
        self.stop_sent = False
        self.logged_state = None
        self.status_published = False

    def pause(self, reason):
        self.args.pause_file.parent.mkdir(parents=True, exist_ok=True)
        self.args.pause_file.write_text(reason + '\n', encoding='utf-8')

    def request_stop(self):
        if not self.stop_sent:
            self.args.stop_file.parent.mkdir(parents=True, exist_ok=True)
            self.args.stop_file.write_text('watcher cooperative stop\n', encoding='utf-8')
            self.stop_stamp = stamp(self.args.stop_file)
            self.stop_sent = True

    def controls(self):
        current = stamp(self.args.stop_file)
        if current is not None and current != self.stop_stamp:
            # Resume acknowledges earlier stops before the pause file is removed.
            # Otherwise Stop->Resume between two 10s polls would recreate the pause.
            resumed = stamp(getattr(self.args, 'resume_file', self.args.status.with_name('watch.resume')))
            if resumed is None or current > resumed:
                self.pause('Manual stop requested')
            self.stop_stamp = current
        return self.args.pause_file.exists(), self.args.watch_stop_file.exists()

    def status(self, phase, reason=''):
        state = {'external_worker': 'worker_running', 'starting_worker': 'waiting_session', 'stopping': 'worker_running'}.get(phase, phase)
        value = {'host_pid': os.getpid(), 'watcher_pid': os.getpid(), 'state': state, 'launch_token': self.args.launch_token, 'running': phase != 'stopped',
                 'phase': phase, 'paused': self.args.pause_file.exists(), 'poll_seconds': self.args.poll_seconds,
                 'updated_at_utc': datetime.now(timezone.utc).isoformat(), 'message': reason,
                 'worker_launcher_pid': self.worker.pid if self.worker else None, 'worker_host_pid': self.host_pid,
                 'worker_host_creation_time_100ns': self.host_birth, 'worker_launch_token': self.token,
                 'game_pid': self.game_pid, 'game_creation_time_100ns': self.game_birth,
                 'worker_starts': self.starts, 'last_exit_code': self.last_exit, 'last_error': self.last_error}
        self.status_published = write_json(self.args.status, value)
        log_state = (phase, reason, self.last_error)
        if log_state != self.logged_state:
            append_log(getattr(self.args, 'log', self.args.status.with_name('watch.log')), json.dumps(value, ensure_ascii=False))
            self.logged_state = log_state
        return value

    def follow_worker(self):
        try:
            status = json.loads(self.args.runtime_status.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            status = {}
        if status.get('launch_token') == self.token and isinstance(status.get('host_pid'), int) and status['host_pid'] > 0:
            candidate = status['host_pid']
            if self.host_pid is None:
                birth = self.backend.identity(candidate)
                if birth is not None:
                    held = self.backend.retain_host(candidate, birth)
                    if held is not None:
                        self.host_pid, self.host_birth, self.host_handle = candidate, birth, held
        host_alive = self.host_handle is not None and self.backend.host_alive(self.host_handle)
        exit_code = self.worker.poll()  # Reaps the launcher; it may have a different PID from the actual host.
        mutex_alive = self.backend.runtime_running()
        if exit_code is None or host_alive or mutex_alive:
            return True
        if self.host_pid is None and self.clock() - self.spawned_at < 30:
            return True  # Unknown redirector handoff: no new launch during the handshake window.
        self.last_exit = exit_code
        if self.host_handle is not None:
            self.backend.release_host(self.host_handle)
            self.host_handle = None
        self.worker = None
        self.host_pid = self.host_birth = self.token = None
        self.stop_sent = False
        return False

    def step(self):
        paused, shutting_down = self.controls()
        if shutting_down and not paused:
            self.pause('Watcher shutdown requested')
            paused = True
        if paused or shutting_down:
            self.request_stop()
        if self.worker is not None:
            try:
                if self.backend.identity(self.game_pid) != self.game_birth:
                    self.request_stop()
            except OSError as error:
                self.last_error = str(error)
                self.request_stop()
            if self.follow_worker():
                return self.status('stopping' if paused or shutting_down or self.stop_sent else 'worker_running')
        if shutting_down:
            # An external/manual host also drains normally; never force termination.
            if self.backend.runtime_running():
                return self.status('stopping')
            return self.status('stopped')
        if paused:
            return self.status('paused')
        if self.backend.runtime_running():
            return self.status('external_worker', 'Another AutoLoot instance is already running.')
        proof = self.backend.ready()
        # Stop/pause may arrive during disk hashing or bounded readiness reads.
        paused, shutting_down = self.controls()
        if paused or shutting_down:
            self.request_stop()
            return self.status('paused' if paused else 'stopping')
        if proof.get('ready') is not True:
            return self.status(proof.get('phase', 'waiting_session'), proof.get('reason', ''))
        pid = proof.get('pid')
        birth = proof.get('process_identity', {}).get('creation_time_100ns')
        if not isinstance(pid, int) or pid <= 0 or not str(birth).isdigit() or self.backend.identity(pid) != str(birth):
            raise ValueError('Game identity changed after discovery; no worker started.')
        if self.backend.runtime_running() or any(p.exists() for p in (self.args.pause_file, self.args.watch_stop_file)):
            return self.status('waiting_session', 'Activation cancelled by a control request or another instance.')
        # A fresh worker requires a visible acknowledgement; existing workers still
        # retain their references and drain normally when later status writes fail.
        self.status('waiting_session', 'Preparing AutoLoot activation')
        if not self.status_published:
            raise OSError('Watcher status could not be published; no worker started')
        paused, shutting_down = self.controls()
        if paused or shutting_down:
            self.request_stop()
            return self.status('paused' if paused else 'stopping')
        self.token = str(uuid.uuid4())
        self.game_pid, self.game_birth = pid, str(birth)
        self.stop_sent = False
        self.worker = self.backend.spawn(proof, self.token)
        self.spawned_at = self.clock()
        self.starts += 1
        if self.args.watch_stop_file.exists() and not self.args.pause_file.exists():
            self.pause('Watcher shutdown during spawn')
        if any(p.exists() for p in (self.args.pause_file, self.args.watch_stop_file)):
            self.request_stop()
        return self.status('starting_worker')


def live(args):
    try:
        with WatcherInstance():
            sys.path.insert(0, str(ROOT / 'tools'))
            from runtime_control import clear_stale_stop
            clear_stale_stop(args.watch_stop_file)
            if not write_json(args.status, {'host_pid': os.getpid(), 'watcher_pid': os.getpid(), 'state': 'waiting_game',
                                    'phase': 'starting', 'running': True, 'launch_token': args.launch_token,
                                    'updated_at_utc': datetime.now(timezone.utc).isoformat(), 'poll_seconds': args.poll_seconds}):
                raise OSError('Initial watcher status could not be published; no backend started')
            backend = WindowsBackend(args)
            watcher = Watcher(args, backend)
            while True:
                started = time.monotonic()
                try:
                    result = watcher.step()
                except KeyboardInterrupt:
                    args.watch_stop_file.parent.mkdir(parents=True, exist_ok=True)
                    args.watch_stop_file.write_text('watcher exit\n', encoding='utf-8')
                    continue
                except Exception as error:
                    watcher.last_error = type(error).__name__ + ': ' + str(error)
                    if watcher.worker is not None:
                        try:
                            watcher.pause('Watcher error; manual resume required')
                        except OSError:
                            pass
                        try:
                            watcher.request_stop()
                        except OSError:
                            pass
                    result = watcher.status('error', watcher.last_error)
                if result['phase'] == 'stopped':
                    return 0
                # Start-to-start polling, no replay of missed intervals.
                try:
                    time.sleep(max(0, started + args.poll_seconds - time.monotonic()))
                except KeyboardInterrupt:
                    args.watch_stop_file.parent.mkdir(parents=True, exist_ok=True)
                    args.watch_stop_file.write_text('watcher exit\n', encoding='utf-8')
    except AlreadyWatching:
        return 0  # Duplicate startup leaves the existing watcher/status/control files intact.


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--poll-seconds', type=float, default=POLL_SECONDS)
    parser.add_argument('--launch-token')
    parser.add_argument('--status', type=Path, default=DATA / 'watch-status.json')
    parser.add_argument('--runtime-status', type=Path, default=DATA / 'status.json')
    parser.add_argument('--pause-file', type=Path, default=DATA / 'watch.pause')
    parser.add_argument('--resume-file', type=Path, default=DATA / 'watch.resume')
    parser.add_argument('--stop-file', type=Path, default=DATA / 'stop.request')
    parser.add_argument('--watch-stop-file', type=Path, default=DATA / 'watch.stop')
    parser.add_argument('--worker-log', type=Path, default=DATA / 'watch-worker.log')
    parser.add_argument('--log', type=Path, default=DATA / 'watch.log')
    args = parser.parse_args(argv)
    if args.poll_seconds != POLL_SECONDS:
        parser.error('The watcher uses a fixed 10-second polling interval.')
    return args


if __name__ == '__main__':
    try:
        raise SystemExit(live(parse_args()))
    except Exception as error:
        # pythonw has no console; failures remain visible to the GUI status reader.
        args = parse_args()
        append_log(args.log, type(error).__name__ + ': ' + str(error))
        write_json(args.status, {'host_pid': os.getpid(), 'watcher_pid': os.getpid(), 'state': 'error', 'updated_at_utc': datetime.now(timezone.utc).isoformat(), 'launch_token': args.launch_token, 'running': False,
                                'phase': 'error', 'last_error': type(error).__name__ + ': ' + str(error)})
        raise SystemExit(1)
