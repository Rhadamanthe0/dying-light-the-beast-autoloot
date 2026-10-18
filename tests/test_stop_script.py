"""Windows stop command must drain an owned host before allowing a restart."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32', 'Windows entrypoint')
class StopScriptTests(unittest.TestCase):
    def test_stop_waits_for_host_exit_instead_of_only_requesting_stop(self):
        self._assert_stop_waits('powershell.exe')

    @unittest.skipUnless(shutil.which('pwsh.exe'), 'PowerShell 7 not installed')
    def test_stop_accepts_json_dates_decoded_as_datetime_by_powershell7(self):
        self._assert_stop_waits('pwsh.exe')

    def _assert_stop_waits(self, powershell):
        with tempfile.TemporaryDirectory(prefix='autoloot-stop-test-') as folder:
            root = Path(folder)
            (root / 'tools').mkdir()
            script = root / 'tools/manage.ps1'
            shutil.copy2(ROOT / 'tools/manage.ps1', script)
            host_code = '''
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
p = Path(sys.argv[1]) / 'evidence' / 'autoloot5m'
p.mkdir(parents=True)
(p / 'status.json').write_text(json.dumps({
    'host_pid': os.getpid(), 'running': True,
    'updated_at_utc': datetime.now(timezone.utc).isoformat()}))
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    if (p / 'stop.request').exists():
        time.sleep(0.8)  # Represents an already-started native call draining.
        break
    time.sleep(0.01)
'''
            # A Windows venv executable may only be a redirector with a different PID.
            child = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', host_code, str(root)],
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                status = root / 'evidence' / 'autoloot5m' / 'status.json'
                deadline = time.monotonic() + 5
                while True:
                    try:
                        if json.loads(status.read_text())['host_pid'] == child.pid:
                            break
                    except (OSError, ValueError):
                        pass
                    if time.monotonic() >= deadline:
                        self.fail('Owned host did not publish its status')
                    time.sleep(0.01)
                result = subprocess.run(
                    [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Action', 'Pause'],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIsNotNone(child.poll(), 'Stop returned while the host was still draining')
                self.assertIn('AutoLoot paused', result.stdout)
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
