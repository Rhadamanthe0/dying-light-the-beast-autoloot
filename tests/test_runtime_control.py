import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'tools/runtime_control.py'
spec=importlib.util.spec_from_file_location('runtime_control_tested',SOURCE)
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)

@unittest.skipUnless(os.name=='nt','Windows kernel contract')
class RuntimeControlTests(unittest.TestCase):
    def test_duplicate_host_refused_and_lock_released(self):
        with patch.dict(os.environ,{'USERNAME':'autoloot-fixture-'+str(os.getpid())}):
            code='import sys;sys.path.insert(0,'+repr(str(SOURCE.parent))+');from runtime_control import SingleInstance,AlreadyRunning\ntry:\n with SingleInstance(): sys.exit(2)\nexcept AlreadyRunning: sys.exit(0)'
            with control.SingleInstance():
                with self.assertRaises(control.AlreadyRunning):
                    with control.SingleInstance():pass
                result=subprocess.run([sys.executable,'-c',code],timeout=5,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            with control.SingleInstance():pass
    def test_stop_created_during_startup_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stop.request';path.write_text('stop now')
            self.assertTrue(control.clear_stale_stop(path));self.assertTrue(path.exists())
    def test_old_stop_removed_but_missing_stop_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stop.request'
            self.assertFalse(control.clear_stale_stop(path));path.write_text('old stop')
            os.utime(path,ns=(0,0))
            self.assertFalse(control.clear_stale_stop(path));self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
