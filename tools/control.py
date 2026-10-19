"""Console-free Start Menu controls, launched by the bundled pythonw.exe."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    if action not in ('Pause', 'Resume'):
        return 2
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run(
            [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
             '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'tools/manage.ps1'),
             '-Action', action, '-Root', str(ROOT)],
            cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode:
            raise RuntimeError('See the log in ' + str(ROOT / 'evidence' / (action + '-AutoLoot.log')))
        message = 'AutoLoot paused.' if action == 'Pause' else 'Automatic looting resumed.'
        ctypes.windll.user32.MessageBoxW(None, message, 'Better AutoLoot', 0x40)
        return 0
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), 'Better AutoLoot', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
