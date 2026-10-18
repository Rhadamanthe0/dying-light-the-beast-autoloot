"""Exercise Windows startup registration and update drainage without touching real Startup."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import venv

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32', 'Windows deployment')
class StartupScriptTests(unittest.TestCase):
    def run_script(self, folder, text):
        script = folder / 'exercise.ps1'
        script.write_text(text, encoding='utf-8')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def sandbox(self, folder):
        for name in ('AutoLoot-Common.ps1', 'Arreter-AutoLoot.ps1'):
            shutil.copy2(ROOT / name, folder / name)
        return ". (Join-Path $PSScriptRoot 'AutoLoot-Common.ps1')\nfunction Get-AutoLootStartupPath { Join-Path $PSScriptRoot 'test-startup.lnk' }\n"

    def test_real_shortcut_roundtrip_and_foreign_shortcut_refused(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-startup-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder) + '''
Register-AutoLootStartup $PSScriptRoot
if ((Get-AutoLootPreviousRoot) -ne $PSScriptRoot) { throw 'Root roundtrip failed' }
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Get-AutoLootStartupPath))
if ($link.TargetPath -ne (Join-Path $PSScriptRoot '.venv\\Scripts\\pythonw.exe')) { throw 'Wrong GUI target' }
if ($link.Arguments -ne ('"' + (Join-Path $PSScriptRoot 'tools\\autoloot_watch.py') + '" --live')) { throw 'Wrong arguments' }
$link.Description = 'some other shortcut'
$link.Save()
$refused = $false
try { Get-AutoLootPreviousRoot } catch { $refused = $true }
if (-not $refused) { throw 'Unrecognized shortcut accepted' }
'''
            self.run_script(folder, script)

    def test_update_waits_for_both_watcher_and_runtime(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-update-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder) + 'Stop-AutoLootInstallation $PSScriptRoot\n'
            evidence = folder / 'evidence/autoloot5m'
            evidence.mkdir(parents=True)
            code = '''
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
p=Path(sys.argv[1]); kind=sys.argv[2]
status='watch-status.json' if kind=='watch' else 'status.json'
signal='watch.stop' if kind=='watch' else 'stop.request'
(p/status).write_text(json.dumps({'host_pid':os.getpid(),'running':True,
    'updated_at_utc':datetime.now(timezone.utc).isoformat()}))
deadline=time.monotonic()+15
while time.monotonic()<deadline:
    if (p/signal).exists():
        time.sleep(1.2 if kind=='watch' else .4)
        break
    time.sleep(.01)
'''
            children = [subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', code,
                                          str(evidence), kind], creationflags=subprocess.CREATE_NO_WINDOW)
                        for kind in ('watch', 'runtime')]
            try:
                deadline = time.monotonic() + 5
                for name in ('watch-status.json', 'status.json'):
                    while not (evidence / name).exists():
                        if time.monotonic() > deadline:
                            self.fail('Owned process did not publish state')
                        time.sleep(.02)
                    json.loads((evidence / name).read_text())
                self.run_script(folder, script)
                self.assertTrue((evidence / 'watch.pause').exists())
                for child in children:
                    self.assertIsNotNone(child.poll(), 'Update returned before owned process drained')
            finally:
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=5)

    def test_update_refuses_to_continue_after_stop_timeout_without_watcher(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-update-refusal-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder)
            # Exercise the actual caller contract for the stop script's timeout exit.
            (folder / 'Arreter-AutoLoot.ps1').write_text('param([string]$Root)\nexit 1\n')
            script += '''
$refused = $false
try { Stop-AutoLootInstallation $PSScriptRoot } catch { $refused = $true }
if (-not $refused) { throw 'Update continued after failed stop' }
'''
            self.run_script(folder, script)

    def test_resume_replaces_watcher_that_published_error_before_exiting(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-resume-closing-') as temp:
            folder = Path(temp)
            self.sandbox(folder)
            shutil.copy2(ROOT / 'Lancer-AutoLoot.ps1', folder / 'Lancer-AutoLoot.ps1')
            venv.EnvBuilder(with_pip=False).create(folder / '.venv')
            (folder / 'tools').mkdir()
            (folder / 'tools/autoloot_watch.py').write_text('''
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'evidence/autoloot5m/watch-status.json'
p.write_text(json.dumps({'host_pid':os.getpid(),'running':True,'phase':'waiting_game',
 'launch_token':sys.argv[sys.argv.index('--launch-token')+1],
 'updated_at_utc':datetime.now(timezone.utc).isoformat()}))
time.sleep(1)
''')
            evidence = folder / 'evidence/autoloot5m'
            evidence.mkdir(parents=True)
            code = '''
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({'host_pid':os.getpid(),'running':False,'phase':'error',
 'updated_at_utc':datetime.now(timezone.utc).isoformat()}))
time.sleep(1)
'''
            child = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-c', code,
                                      str(evidence / 'watch-status.json')], creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline = time.monotonic() + 5
                while not (evidence / 'watch-status.json').exists():
                    if time.monotonic() > deadline:
                        self.fail('Owned closing process did not publish state')
                    time.sleep(.01)
                result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                         str(folder / 'Lancer-AutoLoot.ps1')], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                status = json.loads((evidence / 'watch-status.json').read_text())
                self.assertNotEqual(status['host_pid'], child.pid)
                self.assertEqual(status['phase'], 'waiting_game')
                self.assertIsNotNone(child.poll())
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=5)
                # The owned replacement has a fixed 1s lifetime, never a real watcher.
                time.sleep(1.1)


if __name__ == '__main__':
    unittest.main()
