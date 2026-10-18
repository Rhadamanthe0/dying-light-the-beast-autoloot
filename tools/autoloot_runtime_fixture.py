"""Host-control regression tests. No game or Frida target is contacted.

Native pipeline/cadence qualification is separately exercised by --dummy.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import autoloot_runtime as runtime


class HostTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        folder=Path(self.directory.name)
        self.args=SimpleNamespace(session=None,pid=None,duration=0,
          output=folder/'report.json',status=folder/'status.json',stop_file=folder/'stop.request')
        self.trace=[];self.replace_attempts=0

    def invoke(self,mode='normal',pids=None,fresh_stop=False,replace_failures=0):
        test=self;trace=self.trace;args=self.args
        class Rpc:
            polls=0
            def result(self):
                return {'type':'stopped','restoration_verified':True,'detach_done':True,
                  'errors':[],'cleanup_errors':[],'result':{'ready':True,'stats':{'cycles':1}}}
            def stop(self):
                trace.append('stop')
                return {'type':'stop_deferred'} if mode=='deferred' else self.result()
            def poll(self):
                self.polls+=1
                if mode=='terminated':session.handlers['detached']('process-terminated',None)
                if mode=='deferred':return self.result() if self.polls>=2 else {'type':'poll'}
                if mode=='native_disabled':
                    # A second poll terminates the isolated old-version regression
                    # so a missing disabled check fails deterministically, not by timeout.
                    if self.polls>=2:args.stop_file.write_text('stop')
                    return {'type':'poll','result':{'ready':True,'stats':{'disabled':1,'last_cycle_status':6}}}
                if mode=='dispatch_limit':return {'type':'poll','result':{'ready':True,'stats':{'dispatch_limit_reached':1}}}
                args.stop_file.write_text('stop')
                return {'type':'poll','result':{'ready':False}}
        class Script:
            exports_sync=Rpc()
            def on(self,name,callback):self.message=callback
            def load(self):
                trace.append('load');self.message({'type':'send','payload':{'type':'armed'}},None)
                if mode=='deferred':args.stop_file.write_text('stop')
            def unload(self):trace.append('unload')
        class Session:
            handlers={}
            def on(self,name,callback):self.handlers[name]=callback
            def create_script(self,*unused,**ignored):
                trace.append('create')
                if mode=='stop_create':args.stop_file.write_text('stop')
                return Script()
            def detach(self):
                trace.append('detach')
                if 'detached' in self.handlers:self.handlers['detached']('application-requested',None)
        session=Session()
        def attach(pid):
            trace.append('attach')
            if mode=='stop_attach':args.stop_file.write_text('stop')
            return session
        original_replace=runtime.os.replace
        def replace(source,destination):
            test.replace_attempts+=1
            if test.replace_attempts<=replace_failures:raise PermissionError('simulated Windows reader')
            return original_replace(source,destination)
        core=hashlib.sha256(Path(runtime.__file__).with_suffix('.c').read_bytes()).hexdigest()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(runtime,'SingleInstance',return_value=contextlib.nullcontext()))
            stack.enter_context(patch.object(runtime,'clear_stale_stop',return_value=fresh_stop))
            api=stack.enter_context(patch.object(runtime.discovery,'api_setup',return_value=object()))
            stack.enter_context(patch.object(runtime.discovery,'process_ids',return_value=[12345] if pids is None else pids))
            prepare=stack.enter_context(patch.object(runtime,'prepare',return_value=({'pid':12345},{'query':{'core_sha256':core}})))
            actual_attach=stack.enter_context(patch.object(runtime.frida,'attach',side_effect=attach))
            stack.enter_context(patch.object(runtime.os,'replace',side_effect=replace))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code=runtime.live(args)
        return code,json.loads(args.output.read_text(encoding='utf-8')),json.loads(args.status.read_text(encoding='utf-8')),api,prepare,actual_attach

    def test_game_closed_exits_normally_without_attach(self):
        code,report,status,_,prepare,attach=self.invoke(pids=[])
        self.assertEqual(code,0);self.assertTrue(report['ok']);self.assertEqual(status['phase'],'game_closed')
        self.assertFalse(status['running']);prepare.assert_not_called();attach.assert_not_called()

    def test_fresh_stop_prevents_discovery_and_attach(self):
        self.args.stop_file.write_text('fresh')
        code,report,status,api,_,attach=self.invoke(fresh_stop=True)
        self.assertEqual(code,0);self.assertEqual(status['phase'],'stopped')
        self.assertEqual(self.args.stop_file.read_text(),'fresh');api.assert_not_called();attach.assert_not_called()

    def test_duplicate_does_not_write_or_clear_other_host_control(self):
        self.args.status.write_text('existing');self.args.stop_file.write_text('fresh')
        with patch.object(runtime,'SingleInstance',side_effect=runtime.AlreadyRunning('already active')),contextlib.redirect_stdout(io.StringIO()):
            code=runtime.live(self.args)
        self.assertEqual(code,2);self.assertEqual(self.args.status.read_text(),'existing')
        self.assertEqual(self.args.stop_file.read_text(),'fresh');self.assertFalse(self.args.output.exists())

    def test_stop_during_attach_never_creates_script(self):
        code,report,status,*_=self.invoke(mode='stop_attach')
        self.assertEqual(code,0);self.assertNotIn('create',self.trace)
        self.assertEqual(self.trace,['attach','detach']);self.assertTrue(report['cleanup']['no_script_execution'])

    def test_stop_during_creation_never_loads_script(self):
        code,report,status,*_=self.invoke(mode='stop_create')
        self.assertEqual(code,0);self.assertNotIn('load',self.trace)
        self.assertTrue(report['cleanup']['no_script_execution'])

    def test_normal_stop_unloads_before_detaching(self):
        code,report,status,*_=self.invoke()
        self.assertEqual(code,0);self.assertTrue(report['ok']);self.assertEqual(status['phase'],'stopped')
        self.assertLess(self.trace.index('stop'),self.trace.index('unload'))
        self.assertLess(self.trace.index('unload'),self.trace.index('detach'))

    def test_deferred_stop_retains_resources_until_native_completion(self):
        code,report,status,*_=self.invoke(mode='deferred')
        self.assertEqual(code,0);self.assertTrue(report['cleanup']['native_completion_pending'])
        self.assertEqual(self.trace[-3:],['stop','unload','detach'])

    def test_target_exit_is_normal_without_forced_unload(self):
        code,report,status,*_=self.invoke(mode='terminated')
        self.assertEqual(code,0);self.assertTrue(report['ok']);self.assertEqual(status['phase'],'game_closed')
        self.assertNotIn('unload',self.trace);self.assertNotIn('detach',self.trace)

    def test_transient_reader_denial_is_retried(self):
        code,report,status,*_=self.invoke(pids=[],replace_failures=2)
        self.assertEqual(code,0);self.assertTrue(report['ok']);self.assertGreater(self.replace_attempts,2)
        self.assertEqual(status['phase'],'game_closed')

    def test_native_disable_causes_error_and_normal_cleanup(self):
        code,report,status,*_=self.invoke(mode='native_disabled')
        self.assertEqual(code,1);self.assertFalse(report['ok']);self.assertEqual(status['phase'],'error')
        self.assertFalse(status['running']);self.assertTrue(any('disabled itself' in e for e in report['errors']))
        self.assertEqual(self.trace[-3:],['stop','unload','detach'])

    def test_dispatch_cap_is_normal_stop_not_native_fault(self):
        code,report,status,*_=self.invoke(mode='dispatch_limit')
        self.assertEqual(code,0);self.assertTrue(report['ok']);self.assertTrue(report['dispatch_limit_reached'])
        self.assertEqual(status['phase'],'stopped');self.assertEqual(report['errors'],[])
        self.assertEqual(self.trace[-3:],['stop','unload','detach'])


if __name__=='__main__':unittest.main()
