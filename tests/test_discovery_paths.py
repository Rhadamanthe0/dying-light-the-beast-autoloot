"""Fresh path discovery with real config resolution and a mocked PE boundary."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class PEBoundary(RuntimeError):
    pass


class DiscoveryPathsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        config = self.root/'app'
        config.mkdir()
        spec = importlib.util.spec_from_file_location('fresh_game_paths', ROOT/'tools/game_paths.py')
        self.paths = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.paths)
        self.paths.ROOT = config
        self.paths.steam_roots = Mock(return_value=[self.root/'missing Steam'])
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        image_module = ModuleType('inspect_native')
        image_module.GAME = self.paths.locate_game()
        self.image = image_module.Image = Mock(side_effect=PEBoundary('Stopped at the PE reader'))
        self.observer = ModuleType('observe_runtime')
        self.observer.windows_api = Mock(side_effect=AssertionError('No process APIs permitted'))
        self.observer.INVALID_HANDLE = -1
        self.observer.PROCESS_ACCESS = 0x410
        with patch.dict(sys.modules, {'game_paths': self.paths, 'inspect_native': image_module,
                                      'observe_runtime': self.observer}):
            spec = importlib.util.spec_from_file_location('fresh_discovery', ROOT/'tools/discover_session.py')
            self.discovery = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.discovery)
        self.initial_bin = self.discovery.BIN

    def game(self, name):
        root = self.root/name
        executable = root/self.paths.RELATIVE_EXE
        executable.parent.mkdir(parents=True)
        executable.touch()
        return root.resolve()

    def select(self, game):
        (self.paths.ROOT/'autoloot.local.json').write_text(json.dumps({'game_path': str(game)}), encoding='utf-8')

    def assert_preflight_reads(self, root):
        self.image.reset_mock()
        with self.assertRaises(PEBoundary):
            self.discovery.prepare_static()
        self.image.assert_called_once_with(root/'ph_ft/work/bin/x64'/self.discovery.GAME_DLL)
        self.assertEqual(self.discovery.BIN, root/'ph_ft/work/bin/x64')
        self.observer.windows_api.assert_not_called()

    def test_config_added_after_import_replaces_failed_steam_fallback(self):
        selected = self.game('newly selected game')
        self.assertNotEqual(self.initial_bin, selected/'ph_ft/work/bin/x64')
        self.select(selected)
        self.assert_preflight_reads(selected)

    def test_each_preflight_observes_changed_config(self):
        first, second = self.game('first game'), self.game('second game')
        self.select(first)
        self.assert_preflight_reads(first)
        self.select(second)
        self.assert_preflight_reads(second)

    def test_invalid_selected_root_does_not_reuse_cached_valid_root(self):
        selected = self.game('valid game')
        self.select(selected)
        with self.assertRaises(PEBoundary):
            self.discovery.prepare_static()
        self.image.reset_mock()
        self.select(self.root/'missing game')
        with self.assertRaisesRegex(ValueError, 'Game executable not found'):
            self.discovery.prepare_static()
        self.image.assert_not_called()
        self.observer.windows_api.assert_not_called()

    def test_fresh_discovery_resolves_before_process_api(self):
        selected = self.game('fresh session')
        self.select(selected)
        with self.assertRaises(PEBoundary):
            self.discovery.discover(42)
        self.image.assert_called_once_with(selected/'ph_ft/work/bin/x64'/self.discovery.GAME_DLL)
        self.observer.windows_api.assert_not_called()

    def test_module_paths_are_checked_against_the_same_proof_snapshot(self):
        selected, other = self.game('proof root'), self.game('different root')
        fresh_bin, other_bin = selected/'ph_ft/work/bin/x64', other/'ph_ft/work/bin/x64'
        proof = {'images': {'game': {'path': str(fresh_bin/self.discovery.GAME_DLL)}}}
        # A separate refresh must not replace the path captured by this proof.
        self.discovery.BIN = other_bin
        modules = [{'name': name, 'path': str(other_bin/name)} for name in
                   (self.discovery.GAME_DLL, self.discovery.ENGINE_DLL, self.discovery.EXE)]
        api = SimpleNamespace(OpenProcess=Mock(side_effect=AssertionError('No process may be opened')))
        self.observer.modules = Mock(return_value=modules)
        with patch.object(self.discovery, 'prepare_static', return_value=proof), \
                patch.object(self.discovery, 'api_setup', return_value=api), \
                patch.object(self.discovery, 'process_ids', return_value=[42]), \
                patch.object(self.discovery, 'digest', side_effect=AssertionError('Wrong DLL must not be read')):
            with self.assertRaisesRegex(ValueError, 'Expected module/path not unique'):
                self.discovery.discover(42)
        api.OpenProcess.assert_not_called()

    def test_fresh_root_preserves_exact_dll_hash_refusal(self):
        selected = self.game('unsupported game')
        self.select(selected)
        self.image.side_effect = None
        self.image.return_value = SimpleNamespace(data=b'unsupported DLL build')
        with self.assertRaisesRegex(ValueError, 'Installed DLL hash differs'):
            self.discovery.prepare_static()
        self.image.assert_called_once_with(selected/'ph_ft/work/bin/x64'/self.discovery.GAME_DLL)
        self.observer.windows_api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
