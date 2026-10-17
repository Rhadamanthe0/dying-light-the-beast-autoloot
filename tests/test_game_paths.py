import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'tools/game_paths.py'
spec=importlib.util.spec_from_file_location('tested_game_paths',SOURCE)
paths=importlib.util.module_from_spec(spec);spec.loader.exec_module(paths)

class GamePathsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.steam=self.root/'Steam';self.local=self.root/'project';self.local.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(paths,'ROOT',self.local).start()
        patch.object(paths,'steam_roots',return_value=[self.steam]).start()
        patch.dict(os.environ,{},clear=True).start()
    def game(self,path):
        exe=path/paths.RELATIVE_EXE;exe.parent.mkdir(parents=True);exe.touch();return path.resolve()
    def test_explicit_environment(self):
        game=self.game(self.root/'custom game');os.environ['AUTOLOOT_GAME_PATH']=str(game)
        self.assertEqual(paths.locate_game(),game)
    def test_invalid_explicit_path_is_not_silently_replaced(self):
        os.environ['AUTOLOOT_GAME_PATH']=str(self.root/'missing')
        with self.assertRaises(ValueError):paths.locate_game()
    def test_local_config(self):
        import json
        game=self.game(self.root/'from config')
        (self.local/'autoloot.local.json').write_text(json.dumps({'game_path':str(game)}))
        self.assertEqual(paths.locate_game(),game)
    def test_second_steam_library_and_manifest(self):
        library=self.root/'Second Library'
        game=self.game(library/'steamapps/common/Custom Name')
        (self.steam/'steamapps').mkdir(parents=True)
        encoded=str(library).replace('\\','\\\\')
        (self.steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+encoded+'" } }')
        (library/'steamapps/appmanifest_3008130.acf').write_text('"AppState" { "installdir" "Custom Name" }')
        self.assertEqual(paths.locate_game(),game)
    def test_manifest_cannot_escape_common_directory(self):
        (self.steam/'steamapps').mkdir(parents=True)
        (self.steam/'steamapps/appmanifest_3008130.acf').write_text('"installdir" "../../outside"')
        fallback=self.steam/'steamapps/common/Dying Light The Beast'
        self.assertEqual(paths.locate_game(),fallback.resolve())
    def test_import_without_game_is_supported_for_offline_fixture(self):
        self.assertFalse((paths.locate_game()/paths.RELATIVE_EXE).exists())

if __name__=='__main__':unittest.main()
