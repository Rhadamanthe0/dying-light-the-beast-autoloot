"""Source and bundled interpreter resolution; no executable is launched here."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_paths_tested', ROOT / 'tools/runtime_paths.py')
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


class RuntimePathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def file(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
        return path

    def test_source_console(self):
        expected = self.file('.venv/Scripts/python.exe')
        self.assertEqual(paths.python_executable(self.root), expected)

    def test_source_windowed(self):
        expected = self.file('.venv/Scripts/pythonw.exe')
        self.assertEqual(paths.python_executable(self.root, windowed=True), expected)

    def test_bundled_console_preferred_over_venv(self):
        self.file('.venv/Scripts/python.exe')
        expected = self.file('runtime/python.exe')
        self.assertEqual(paths.python_executable(self.root), expected)

    def test_bundled_windowed_preferred_over_venv(self):
        self.file('.venv/Scripts/pythonw.exe')
        expected = self.file('runtime/pythonw.exe')
        self.assertEqual(paths.python_executable(self.root, windowed=True), expected)

    def test_partial_bundle_never_falls_back_to_venv(self):
        self.file('.venv/Scripts/python.exe')
        (self.root / 'runtime').mkdir()
        with self.assertRaisesRegex(FileNotFoundError, 'Required Python executable'):
            paths.python_executable(self.root)

    def test_missing_bundled_gui_never_uses_console_or_venv(self):
        self.file('runtime/python.exe')
        self.file('.venv/Scripts/pythonw.exe')
        with self.assertRaises(FileNotFoundError):
            paths.python_executable(self.root, windowed=True)

    def test_missing_source_gui_never_uses_console(self):
        self.file('.venv/Scripts/python.exe')
        with self.assertRaises(FileNotFoundError):
            paths.python_executable(self.root, windowed=True)

    def test_missing_everything_never_searches_path(self):
        with self.assertRaises(FileNotFoundError):
            paths.python_executable(self.root)

    def test_selected_executable_must_be_a_file(self):
        (self.root / 'runtime/python.exe').mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            paths.python_executable(self.root)

    def test_accepts_string_root(self):
        expected = self.file('runtime/python.exe')
        self.assertEqual(paths.python_executable(str(self.root)), expected)


if __name__ == '__main__':
    unittest.main()
