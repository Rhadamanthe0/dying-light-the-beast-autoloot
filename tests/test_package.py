"""Publication/install contract, independent of the installed game."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
RUNTIME_FILES=('autoloot_runtime.py','autoloot_runtime.c','autoloot_runtime.js',
               'autoloot_runtime_fixture.js','autoloot_runtime_fixture.py','discover_session.py','inspect_native.py',
               'observe_runtime.py','game_paths.py','runtime_control.py','autoloot_watch.py',
               'runtime_paths.py','runtime_profile.py','discovery_181.py','control.py',
               'autoloot_update.py','update_trust.py','mod_version.py')

class PackageTests(unittest.TestCase):
    def test_installer_requires_the_builder_version(self):
        installer=(ROOT/'installer/autoloot.iss').read_text(encoding='utf-8')
        required=re.search(r'#ifndef AppVersion\s+([^\n]+)',installer)
        self.assertIsNotNone(required)
        self.assertTrue(required[1].strip().startswith('#error '))
        builder=(ROOT/'tools/build_installer.py').read_text(encoding='utf-8')
        self.assertIn("'/DAppVersion=' + VERSION",builder)
        self.assertIn('from mod_version import VERSION',builder)

    def test_release_runpy_import_resolves_adjacent_profile(self):
        command="import runpy; print(runpy.run_path('tools/build_installer.py')['VERSION'])"
        result=subprocess.run([sys.executable,'-c',command],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertRegex(result.stdout.strip(),r'^\d+\.\d+\.\d+$')

    def staged_qualification(self, folder, failure=None):
        sys.path.insert(0, str(ROOT/'tools'))
        import build_installer as builder
        from runtime_profile import PROFILE_171, PROFILE_181, compiled_core, profile_digest
        stage, logs = folder/'stage', folder/'logs'
        (stage/'tools').mkdir(parents=True)
        logs.mkdir()
        for name in ('autoloot_runtime.c', 'autoloot_runtime_fixture.js'):
            shutil.copy2(ROOT/'tools'/name, stage/'tools'/name)
        commands=[]

        def run(command, log, **kwargs):
            commands.append([str(value) for value in command])
            if '-c' in command:
                log.write_text(json.dumps({'passed': True}))
                return 0
            name=command[command.index('--profile')+1] if '--profile' in command else '1.7.1.0na'
            profile=next(value for value in (PROFILE_171, PROFILE_181) if name in (value['id'], value['id'].removesuffix('.0na')))
            if profile == PROFILE_181 and failure == 'exit':
                return 1
            proof={'passed': True, 'mode': 'owned_runtime_fixture_no_game_access', 'live_executed': False,
                   'errors': [], 'profile_id': profile['id'], 'profile_sha256': profile_digest(profile),
                   'core_sha256': hashlib.sha256(compiled_core((stage/'tools/autoloot_runtime.c').read_text(encoding='utf-8'), profile).encode()).hexdigest(),
                   'fixture_sha256': builder.digest(stage/'tools/autoloot_runtime_fixture.js'),
                   'cases': [{'name': str(index), 'passed': True} for index in range(158)], 'host_tests': {'passed': True}}
            if profile == PROFILE_181:
                if failure == 'missing':
                    return 0
                if failure in ('profile_id', 'profile_sha256', 'core_sha256', 'fixture_sha256'):
                    proof[failure]='stale'
                if failure == 'host':
                    proof['host_tests']['passed']=False
                if failure == 'case':
                    proof['cases'][0]['passed']=False
                if failure == 'count':
                    proof['cases'].pop()
            suffix='' if profile == PROFILE_171 else '-'+profile['id']
            evidence=stage/'evidence'/('autoloot-runtime-dummy'+suffix+'.json')
            evidence.parent.mkdir(exist_ok=True)
            evidence.write_text(json.dumps(proof), encoding='utf-8')
            return 0
        return builder, stage, logs, commands, run

    def test_builder_qualifies_both_profiles_and_retains_distinct_proofs(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-package-qualify-') as temp:
            builder, stage, logs, commands, run=self.staged_qualification(Path(temp))
            report={}
            with patch.object(builder, 'run', side_effect=run):
                builder.qualify(stage, Path(temp)/'downloads', logs, report)
            profiles=[command[command.index('--profile')+1] for command in commands if '--dummy' in command]
            self.assertEqual(profiles, ['1.7.1.0na', '1.8.1.0na'])
            self.assertEqual(set(report['native_qualifications']), set(profiles))
            for profile in profiles:
                self.assertTrue((logs/('native-qualification-'+profile+'.json')).is_file())

    def test_builder_refuses_failed_missing_or_stale_second_profile(self):
        for failure in ('exit', 'missing', 'profile_id', 'profile_sha256', 'core_sha256', 'fixture_sha256', 'host', 'case', 'count'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix='autoloot-package-refuse-') as temp:
                builder, stage, logs, commands, run=self.staged_qualification(Path(temp), failure)
                with patch.object(builder, 'run', side_effect=run), self.assertRaises((RuntimeError, ValueError, FileNotFoundError)):
                    builder.qualify(stage, Path(temp)/'downloads', logs, {})

    def test_generated_qualification_proofs_are_not_packaged(self):
        with tempfile.TemporaryDirectory(prefix='autoloot-package-clean-') as temp:
            builder, stage, logs, commands, run=self.staged_qualification(Path(temp))
            evidence=stage/'evidence'
            evidence.mkdir()
            for name in ('autoloot-runtime-dummy.json', 'autoloot-runtime-dummy-1.8.1.0na.json'):
                (evidence/name).write_text('{}')
            builder.clean_generated(stage)
            self.assertFalse(evidence.exists())
            self.assertTrue((stage/'tools/autoloot_runtime.c').is_file())

    def test_builder_manifest_and_native_case_count_match_sources(self):
        tree = ast.parse((ROOT/'tools/build_installer.py').read_text(encoding='utf-8'))
        manifest = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('TOOLS', 'NATIVE_CASE_COUNT'):
                manifest[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertTrue(set(RUNTIME_FILES) | {'manage.ps1', 'DIAGNOSTIC.md'} <= set(manifest['TOOLS']))
        runtime = ast.parse((ROOT/'tools/autoloot_runtime.py').read_text(encoding='utf-8'))
        modes = next(ast.literal_eval(node.value) for node in ast.walk(runtime)
                     if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id == 'modes' and isinstance(node.value, ast.List))
        self.assertEqual(manifest['NATIVE_CASE_COUNT'], len(modes))

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
        for name in ('Install','Pause','Resume','Uninstall'):
            gui=ROOT/(name+'-AutoLoot.vbs')
            self.assertTrue(gui.exists())
            self.assertIn('tools\\manage.ps1',gui.read_text())
            self.assertIn('-Action '+name,gui.read_text())
            self.assertIn('shell.Run(command, 0, True)',gui.read_text())
        launcher=(ROOT/'tools/manage.ps1').read_text()
        self.assertIn('autoloot_watch.py',launcher)
        self.assertNotIn('autoloot_corpses.py',launcher)
        self.assertIn('.venv\\Scripts\\pythonw.exe',launcher)
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
