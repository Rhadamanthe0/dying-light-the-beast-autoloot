"""Resolve the app's Python without using PATH or an external installation."""
from pathlib import Path


def python_executable(root, *, windowed=False):
    root = Path(root)
    bundled = root / 'runtime'
    directory = bundled if bundled.is_dir() else root / '.venv/Scripts'
    executable = directory / ('pythonw.exe' if windowed else 'python.exe')
    if not executable.is_file():
        raise FileNotFoundError('Required Python executable not found: ' + str(executable))
    return executable
