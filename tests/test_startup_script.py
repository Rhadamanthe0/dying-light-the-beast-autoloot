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
        (folder / 'tools').mkdir()
        (folder / '.venv/Scripts').mkdir(parents=True)
        (folder / '.venv/Scripts/pythonw.exe').touch()
        shutil.copy2(ROOT / 'tools/manage.ps1', folder / 'tools/manage.ps1')
        return ". (Join-Path $PSScriptRoot 'tools/manage.ps1')\nfunction Get-AutoLootStartupPath { Join-Path $PSScriptRoot 'test-startup.lnk' }\n"

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

    def test_bundled_shortcut_and_missing_runtime_refuses_fallback(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-bundled-startup-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder) + '''
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'runtime') | Out-Null
New-Item -ItemType File -Path (Join-Path $PSScriptRoot 'runtime\\pythonw.exe') | Out-Null
Register-AutoLootStartup $PSScriptRoot
if ((Get-AutoLootPreviousRoot) -ne $PSScriptRoot) { throw 'Bundled root roundtrip failed' }
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Get-AutoLootStartupPath))
if ($link.TargetPath -ne (Join-Path $PSScriptRoot 'runtime\\pythonw.exe')) { throw 'Wrong bundled target' }
Remove-Item -LiteralPath (Join-Path $PSScriptRoot 'runtime\\pythonw.exe')
$refused = $false
try { Get-AutoLootPython $PSScriptRoot -Windowed } catch { $refused = $true }
if (-not $refused) { throw 'Incomplete bundle fell back to source Python' }
'''
            self.run_script(folder, script)

    def test_prepare_preserves_pause_before_its_own_stop_and_drains_both_roots(self):
        for paused in (False, True):
            with self.subTest(paused=paused), tempfile.TemporaryDirectory(prefix='autoloot-prepare-') as temp:
                folder = Path(temp)
                script = self.sandbox(folder)
                previous = folder / 'previous'
                previous.mkdir()
                if paused:
                    (previous / 'evidence/autoloot5m').mkdir(parents=True)
                    (previous / 'evidence/autoloot5m/watch.pause').write_text('user pause')
                script += '''
function Get-AutoLootPreviousRoot { Join-Path $PSScriptRoot 'previous' }
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json')
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'state.json') -Raw | ConvertFrom-Json
if ($state.keep_paused -ne EXPECTED_PAUSE) { throw 'Pause snapshot included installation shutdown' }
foreach ($root in @($PSScriptRoot, (Join-Path $PSScriptRoot 'previous'))) {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'evidence\\autoloot5m\\watch.stop'))) { throw 'An installation was not stopped' }
}
'''.replace('EXPECTED_PAUSE', '$true' if paused else '$false')
                self.run_script(folder, script)

    def test_keep_paused_does_not_publish_resume_or_remove_pause(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-preserve-pause-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder) + '''
function Get-AutoLootWatcher([string]$InstallationRoot) { [Diagnostics.Process]::GetCurrentProcess() }
Resume-AutoLoot $PSScriptRoot -KeepPaused
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.pause'))) { throw 'User pause removed' }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.resume')) { throw 'Unexpected resume acknowledgement' }
'''
            self.run_script(folder, script)

    def test_prepare_retry_preserves_original_pause_intent(self):
        for paused in (False, True):
            with self.subTest(paused=paused), tempfile.TemporaryDirectory(prefix='autoloot-prepare-retry-') as temp:
                folder = Path(temp)
                script = self.sandbox(folder) + '''
if (ORIGINAL_PAUSE) { Pause-AutoLoot $PSScriptRoot }
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'first.json') -SkipAutoStart
# The watcher may rewrite pause text while finishing shutdown.
Set-Content -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.pause') -Value 'Watcher shutdown requested'
# A new installer attempt has a different temporary state path.
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'retry.json') -SkipAutoStart
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'retry.json') -Raw | ConvertFrom-Json
if ($state.keep_paused -ne ORIGINAL_PAUSE) { throw 'Retry changed the original user pause intent' }
'''.replace('ORIGINAL_PAUSE', '$true' if paused else '$false')
                self.run_script(folder, script)

    def test_manual_pause_after_interrupted_prepare_wins_on_retry(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-retry-manual-pause-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder) + '''
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'first.json') -SkipAutoStart
Pause-AutoLoot $PSScriptRoot
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'retry.json') -SkipAutoStart
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'retry.json') -Raw | ConvertFrom-Json
if (-not $state.keep_paused) { throw 'Retry lost an explicit user pause' }
'''
            self.run_script(folder, script)

    def test_resume_clears_interrupted_installation_pause_before_retry(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-retry-resume-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder) + '''
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'first.json') -SkipAutoStart
# An inert existing watcher exercises resume controls without starting the real backend.
Remove-Item -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.stop')
function Get-AutoLootWatcher([string]$InstallationRoot) { [Diagnostics.Process]::GetCurrentProcess() }
Resume-AutoLoot $PSScriptRoot
foreach ($name in @('watch.pause', 'installation.pause')) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot ('evidence\\autoloot5m\\' + $name))) { throw 'Resume left a pause marker' }
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.resume'))) { throw 'Resume acknowledgement missing' }
function Get-AutoLootWatcher([string]$InstallationRoot) { return $null }
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'retry.json') -SkipAutoStart
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'retry.json') -Raw | ConvertFrom-Json
if ($state.keep_paused) { throw 'Retry ignored an explicit resume' }
'''
            self.run_script(folder, script)

    def test_configure_honors_manual_pause_after_prepare(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-configure-late-pause-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder)
            (folder / 'tools/autoloot_runtime.py').write_text('raise SystemExit(0)\n')
            base_python = str(getattr(sys, '_base_executable', sys.executable)).replace("'", "''")
            script += f"function Get-AutoLootPython {{ '{base_python}' }}\n" + '''
function Resume-AutoLoot([string]$InstallationRoot, [switch]$KeepPaused) {
    if (-not $KeepPaused) { throw 'Configure ignored a newer manual pause' }
}
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json')
Pause-AutoLoot $PSScriptRoot
Configure-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json')
'''
            self.run_script(folder, script)

    def test_source_install_preserves_manual_pause_with_offline_empty_dependencies(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-source-paused-update-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder)
            venv.EnvBuilder(with_pip=True).create(folder / '.venv')
            (folder / 'requirements.txt').write_text('')
            (folder / 'tools/autoloot_runtime.py').write_text('raise SystemExit(0)\n')
            script += '''
$env:PIP_NO_INDEX = '1'
$env:PIP_CONFIG_FILE = 'NUL'
function Resume-AutoLoot([string]$InstallationRoot, [switch]$KeepPaused) {
    if (-not $KeepPaused) { throw 'Source installation lost user pause' }
}
Pause-AutoLoot $PSScriptRoot
Install-AutoLoot $PSScriptRoot
if ((Get-AutoLootPreviousRoot) -ne $PSScriptRoot) { throw 'Source startup registration failed' }
'''
            self.run_script(folder, script)

    def test_configure_honors_resume_after_prepare_from_paused_installation(self):
        for migration in (False, True):
            with self.subTest(migration=migration), tempfile.TemporaryDirectory(prefix='autoloot-configure-resume-') as temp:
                folder = Path(temp)
                script = self.sandbox(folder)
                (folder / 'tools/autoloot_runtime.py').write_text('raise SystemExit(0)\n')
                base_python = str(getattr(sys, '_base_executable', sys.executable)).replace("'", "''")
                script += '''
$pausedRoot = if (MIGRATION) { Join-Path $PSScriptRoot 'previous' } else { $PSScriptRoot }
function Get-AutoLootPreviousRoot { if (MIGRATION) { Join-Path $PSScriptRoot 'previous' } }
Pause-AutoLoot $pausedRoot
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json')
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'state.json') -Raw | ConvertFrom-Json
if (-not $state.keep_paused) { throw 'Initial manual pause was not captured' }
Remove-Item -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.stop')
function Get-AutoLootWatcher { [Diagnostics.Process]::GetCurrentProcess() }
Resume-AutoLoot $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.pause')) { throw 'Explicit resume did not clear pause' }
function Register-AutoLootStartup { }
function Resume-AutoLoot([string]$InstallationRoot, [switch]$KeepPaused) {
    if ($KeepPaused) { throw 'Configure undid a newer explicit resume' }
}
'''.replace('MIGRATION', '$true' if migration else '$false')
                script += f"function Get-AutoLootPython {{ '{base_python}' }}\n"
                script += "Configure-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json')\n"
                self.run_script(folder, script)

    def test_no_autostart_prepares_qualifies_and_uninstalls_without_startup_access(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-no-autostart-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder)
            (folder / 'tools/autoloot_runtime.py').write_text('import sys\nassert sys.argv[1:] == ["--dummy"]\n')
            base_python = str(getattr(sys, '_base_executable', sys.executable)).replace("'", "''")
            script += f"function Get-AutoLootPython {{ '{base_python}' }}\n" + '''
function Get-AutoLootStartupPath { throw 'Real Startup must not be accessed' }
function Register-AutoLootStartup { throw 'Startup must not be registered' }
function Resume-AutoLoot { throw 'Watcher must not be started' }
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json') -SkipAutoStart
Configure-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json') -SkipAutoStart
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.pause'))) { throw 'Audit install is not paused' }
Uninstall-AutoLoot $PSScriptRoot -SkipAutoStart
'''
            self.run_script(folder, script)

    def test_qualification_failure_never_registers_or_starts(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-qualification-refusal-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder)
            (folder / 'tools/autoloot_runtime.py').write_text('raise SystemExit(3)\n')
            base_python = str(getattr(sys, '_base_executable', sys.executable)).replace("'", "''")
            script += f"function Get-AutoLootPython {{ '{base_python}' }}\n" + '''
function Register-AutoLootStartup { Set-Content -LiteralPath (Join-Path $PSScriptRoot 'registered') -Value 'bad' }
function Resume-AutoLoot { Set-Content -LiteralPath (Join-Path $PSScriptRoot 'started') -Value 'bad' }
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json')
$refused = $false
try { Configure-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'state.json') } catch {
    if ($_ -notlike '*Offline checks failed*') { throw }
    $refused = $true
}
if (-not $refused) { throw 'Failed qualification was accepted' }
if ((Test-Path -LiteralPath (Join-Path $PSScriptRoot 'registered')) -or
    (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'started'))) { throw 'Failed bundle was activated' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'evidence\\autoloot5m\\watch.pause'))) { throw 'Failed bundle is not paused' }
Prepare-AutoLoot $PSScriptRoot (Join-Path $PSScriptRoot 'retry.json')
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'retry.json') -Raw | ConvertFrom-Json
if ($state.keep_paused) { throw 'Qualification failure became a manual pause on retry' }
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

    def test_update_refuses_to_continue_after_stop_failure_without_watcher(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-update-refusal-') as temp:
            folder = Path(temp)
            script = self.sandbox(folder)
            # Exercise the caller contract when cooperative worker shutdown fails.
            script += '''
function Pause-AutoLoot([string]$InstallationRoot) { throw 'Owned shutdown failure' }
$refused = $false
try { Stop-AutoLootInstallation $PSScriptRoot } catch { $refused = $true }
if (-not $refused) { throw 'Update continued after failed stop' }
'''
            self.run_script(folder, script)

    def test_resume_replaces_watcher_that_published_error_before_exiting(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-resume-closing-') as temp:
            folder = Path(temp)
            self.sandbox(folder)
            venv.EnvBuilder(with_pip=False).create(folder / '.venv')
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
                                         str(folder / 'tools/manage.ps1'), '-Action', 'Resume'], capture_output=True, text=True, timeout=10)
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
