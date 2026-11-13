"""Vérification quotidienne des publications et installation différée hors jeu."""
import argparse
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

from runtime_paths import python_executable
from mod_version import VERSION

REPOSITORY = 'Rhadamanthe0/dying-light-the-beast-autoloot'
RELEASE_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
INTERVAL = 24 * 60 * 60
RETRY_SECONDS = 60 * 60
ROOT = Path(__file__).resolve().parents[1]


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Invalid stable version')
    return tuple(map(int, value.split('.')))


def read_state(root):
    try:
        value = json.loads((root / 'evidence/updates/state.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def installation_ready(root):
    try:
        return ((root / '.autoloot-owned').read_text() == 'BetterAutoLoot-DLTB-v1'
                and not (root / 'evidence/autoloot5m/watch.stop').exists())
    except OSError:
        return False


def write_state(root, state):
    directory = root / 'evidence/updates'
    if not installation_ready(root):
        return
    temporary = directory / ('state.' + str(os.getpid()) + '.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    temporary.replace(directory / 'state.json')


def download(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'BetterAutoLoot/' + VERSION,
                                                  'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if not response.url.startswith('https://'):
            raise ValueError('HTTPS required')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds size limit')
    return data


def game_running():
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', W.DWORD),
                    ('cntThreads', W.DWORD), ('th32ParentProcessID', W.DWORD),
                    ('pcPriClassBase', W.LONG), ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32FirstW.restype = kernel.Process32NextW.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == 'dyinglightgame_thebeast_x64_rwdi.exe':
                return True
            ok = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise ctypes.WinError(ctypes.get_last_error())
        return False
    finally:
        kernel.CloseHandle(snapshot)


def check_release(root, state):
    from update_trust import verify_manifest
    release = json.loads(download(RELEASE_URL, 1024 * 1024))
    if release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('Stable published release required')
    tag = release.get('tag_name', '')
    if not tag.startswith('v'):
        raise ValueError('Version tag required')
    if version_tuple(tag[1:]) <= version_tuple(VERSION):
        state.pop('pending', None)
        return
    assets = release.get('assets', [])
    prefix = 'https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/'
    def asset(name):
        matches = [a for a in assets if a.get('name') == name]
        if len(matches) != 1 or matches[0].get('browser_download_url') != prefix + name:
            raise ValueError('Missing or ambiguous official asset')
        return prefix + name
    manifest_bytes = download(asset('update-manifest.json'), 65536)
    signature_bytes = download(asset('update-manifest.sig'), 16384)
    manifest = verify_manifest(manifest_bytes, signature_bytes, VERSION)
    if manifest['version'] != tag[1:]:
        raise ValueError('Signed manifest and release differ')
    asset(manifest['filename'])
    directory = root / 'evidence/updates'
    if not installation_ready(root):
        return
    (directory / 'manifest.json').write_bytes(manifest_bytes)
    (directory / 'manifest.sig').write_bytes(signature_bytes)
    if state.get('pending') != manifest['version']:
        state.pop('retry_after', None)
    state['pending'] = manifest['version']


def install_pending(root, state):
    from update_trust import verify_manifest, verify_installer
    directory = root / 'evidence/updates'
    manifest = verify_manifest((directory / 'manifest.json').read_bytes(),
                               (directory / 'manifest.sig').read_bytes(), VERSION)
    if manifest['version'] != state['pending']:
        raise ValueError('Pending version differs from signature')
    if game_running():
        return
    if (state.get('install_attempt') == manifest['version']
            and time.time() - state.get('install_attempt_at', 0) < INTERVAL):
        return
    installer = directory / manifest['filename']
    if installer.exists():
        try:
            verify_installer(installer, manifest)
        except ValueError:
            installer.unlink()
    if not installer.exists():
        url = 'https://github.com/' + REPOSITORY + '/releases/download/v' + manifest['version'] + '/' + manifest['filename']
        data = download(url, min(manifest['size'], 512 * 1024 * 1024))
        temporary = installer.with_suffix('.part')
        temporary.write_bytes(data)
        verify_installer(temporary, manifest)
        temporary.replace(installer)
    verify_installer(installer, manifest)
    if not installation_ready(root) or game_running():
        return
    # Le processus termine après le lancement pour libérer le Python installé.
    state['install_attempt'] = manifest['version']
    state['install_attempt_at'] = time.time()
    state['status'] = 'installer_started'
    write_state(root, state)
    if not installation_ready(root) or game_running():
        state.pop('install_attempt', None)
        state['status'] = 'deferred'
        write_state(root, state)
        return
    try:
        subprocess.Popen([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                          '/DIR=' + str(root)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError:
        state.pop('install_attempt', None)
        raise


def run(root, check):
    state = read_state(root)
    if not installation_ready(root):
        return
    if not check and time.time() < state.get('retry_after', 0):
        return
    try:
        if check:
            state.update(last_checked=time.time(), status='checking', error='')
            write_state(root, state)
            check_release(root, state)
            state['status'] = 'pending_game_exit' if state.get('pending') else 'current'
            write_state(root, state)
        if state.get('pending'):
            install_pending(root, state)
    except Exception as error:
        state['retry_after'] = time.time() + RETRY_SECONDS
        state['status'] = 'error'
        state['error'] = type(error).__name__ + ': ' + str(error)
    write_state(root, state)


class UpdateScheduler:
    """Le réseau et l'installateur s'exécutent dans un enfant indépendant."""
    def __init__(self, root, clock=time.monotonic):
        self.root, self.clock = Path(root), clock
        self.next_check = 0
        self.next_pending = 0
        self.child = None

    def tick(self):
        if not installation_ready(self.root) or (self.root / '.autoloot-disabled').exists():
            return
        if self.child is not None and self.child.poll() is None:
            return
        now = self.clock()
        check = now >= self.next_check
        state = read_state(self.root)
        pending = (state.get('pending')
                   and (state.get('install_attempt') != state['pending']
                        or time.time() - state.get('install_attempt_at', 0) >= INTERVAL)
                   and time.time() >= state.get('retry_after', 0))
        if not check and (not pending or now < self.next_pending):
            return
        command = [str(python_executable(self.root, windowed=True)),
                   str(self.root / 'tools/autoloot_update.py'), '--root', str(self.root)]
        if check:
            command.append('--check')
        self.child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        self.next_pending = now + 60
        if check:
            self.next_check = now + INTERVAL


class UpdateLock:
    def __init__(self, root):
        self.path = root / 'evidence/updates/lock'
        self.stream = None

    def __enter__(self):
        import msvcrt
        if not installation_ready(self.path.parents[2]):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+b')
        self.stream.write(b'0')
        self.stream.flush()
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            self.stream.close()
            self.stream = None
            return False

    def __exit__(self, *ignored):
        if self.stream is not None:
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            self.stream.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.root.resolve() != ROOT or (ROOT / '.autoloot-owned').read_text() != 'BetterAutoLoot-DLTB-v1':
        raise SystemExit('Recognized installation required')
    with UpdateLock(ROOT) as acquired:
        if acquired:
            run(ROOT, args.check)
