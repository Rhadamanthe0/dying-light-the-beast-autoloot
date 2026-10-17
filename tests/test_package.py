"""Publication/install contract, independent of the installed game."""
import ast
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
RUNTIME_FILES=('autoloot_runtime.py','autoloot_runtime.c','autoloot_runtime.js',
               'autoloot_runtime_fixture.js','autoloot_runtime_fixture.py','discover_session.py','inspect_native.py',
               'observe_runtime.py','game_paths.py','runtime_control.py')

class PackageTests(unittest.TestCase):
    def test_runtime_inputs_present(self):
        for name in RUNTIME_FILES:
            with self.subTest(name=name):self.assertTrue((ROOT/'tools'/name).is_file())
    def test_all_python_runtime_imports_are_packaged_or_declared(self):
        available=set(sys.stdlib_module_names)|{'pefile','capstone','frida'}
        available|={Path(name).stem for name in RUNTIME_FILES if name.endswith('.py')}
        for name in RUNTIME_FILES:
            if not name.endswith('.py'):continue
            path=ROOT/'tools'/name
            if not path.exists():continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                imports=[]
                if isinstance(node,ast.Import):imports=[alias.name.split('.')[0] for alias in node.names]
                if isinstance(node,ast.ImportFrom) and node.module:imports=[node.module.split('.')[0]]
                for module in imports:
                    with self.subTest(file=name,module=module):self.assertIn(module,available)
    def test_windows_entrypoints_refer_to_packaged_scripts(self):
        for name in ('Installer','Lancer','Arreter','Verifier'):
            cmd=ROOT/(name+'-AutoLoot.cmd');ps=ROOT/(name+'-AutoLoot.ps1')
            self.assertTrue(cmd.exists());self.assertTrue(ps.exists())
            self.assertIn(ps.name,cmd.read_text())
        launcher=(ROOT/'Lancer-AutoLoot.ps1').read_text()
        self.assertIn('autoloot_runtime.py',launcher)
        self.assertNotIn('autoloot_corpses.py',launcher)
        self.assertIn('.venv\\Scripts\\python.exe',launcher)
    def test_no_local_user_paths_in_runtime_sources(self):
        for name in RUNTIME_FILES:
            path=ROOT/'tools'/name
            if path.exists():
                with self.subTest(name=name):
                    self.assertIsNone(re.search(r'[A-Za-z]:[\\/]+Users[\\/]',path.read_text(),re.I))
    def test_install_declares_pinned_native_dependencies(self):
        self.assertEqual((ROOT/'requirements.txt').read_text().splitlines(),
                         ['frida==17.24.0','pefile==2024.8.26','capstone==5.0.9'])

if __name__=='__main__':unittest.main()
