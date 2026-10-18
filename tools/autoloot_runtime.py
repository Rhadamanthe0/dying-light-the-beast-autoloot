"""Resident native corpse autoloot every100ms, radius2m.

--dummy tests only a fresh disposable Python child with native fixture stubs.
--preflight-only --session PATH validates without Frida attach.
--live --session PATH activates the resident native runtime after review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
INTERVAL_MS=100
RADIUS_METRES=2
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'.deps'))
sys.path.insert(0,str(ROOT/'tools'))
import frida
import os
from types import SimpleNamespace
from runtime_control import SingleInstance, AlreadyRunning, clear_stale_stop
from inspect_native import Image
import discover_session as discovery


def launch(function):
    done,result=threading.Event(),{}
    def work():
        try:result['value']=function()
        except BaseException as error:result['error']=type(error).__name__+': '+str(error)
        finally:done.set()
    threading.Thread(target=work,daemon=True).start();return done,result


def bounded(function,seconds=5):
    done,result=launch(function)
    if not done.wait(seconds):raise TimeoutError('Operation pending; resources must remain retained')
    if 'error' in result:raise RuntimeError(result['error'])
    return result.get('value')


lifecycle=SimpleNamespace(launch=launch,bounded=bounded)
class _StopRequested(Exception):pass


def static_proof():
    game=Image(discovery.BIN/discovery.GAME_DLL);engine=Image(discovery.BIN/discovery.ENGINE_DLL)
    if hashlib.sha256(game.data).hexdigest()!=discovery.HASHES['game'] or hashlib.sha256(engine.data).hexdigest()!=discovery.HASHES['engine']:
        raise ValueError('Reviewed game/engine images required')
    guards=[]
    for name,module,rva in [('FindObjectsInRadius','engine',0xf3ab0),('RadiusImpl','engine',0xb812c0),
                             ('GetLevel','engine',0x82e3d0),('VectorDestructor','game',0x1731f0),
                             ('ContextCtor','game',0x1727890),('GetComponentImpl','engine',0x4515c0),
                             ('GetAction','game',0xca1ac0),('CanUse','game',0xc88470),('PlayerDispatch','game',0x12d9aa0),
                             ('GroundMessageWrapper','game',0x80cb40),('GroundItemTake','game',0x11944b0),('ProxyTargetThunk','game',0x24ec9b6),('ContainerTake','game',0x1194280),('ContainerTakeAll','game',0x1185870)]:
        image=game if module=='game' else engine;offset=image.offset(rva)
        guards.append({'name':name,'module':module,'rva':rva,'hex':image.data[offset:offset+16].hex()})
    return {'function_guards':guards,'game_sha256':discovery.HASHES['game'],'engine_sha256':discovery.HASHES['engine'],
            'core_sha256':hashlib.sha256(Path(__file__).with_suffix('.c').read_bytes()).hexdigest(),
            'interval_ms':INTERVAL_MS,'radius_metres':RADIUS_METRES,'page_size':8,'budget_ms_between_calls':8,'rpm_limit':4096}


def prepare(session_path=None,duration=0,pid=None,ground_items=False,max_dispatches=0,ground_only=False,containers=False,containers_only=False):
    if type(max_dispatches) is not int or not 0<=max_dispatches<=1000000:raise ValueError('max_dispatches must be0..1000000')
    if frida.__version__!='17.24.0':raise ValueError('Reviewed Frida17.24.0 required')
    if not 0<=duration<=86400:raise ValueError('Duration must be0(resident)..86400s')
    static=static_proof()
    qualification=json.loads((ROOT/'evidence/autoloot-runtime-dummy.json').read_text())
    if qualification.get('passed') is not True or qualification.get('core_sha256')!=static['core_sha256']:
        raise ValueError('Current runtime has no matching successful owned-fixture qualification; run --dummy')
    current=discovery.validate_session(session_path,max_age_seconds=120) if session_path else discovery.discover(pid)
    if not current.get('ready'):raise ValueError('Current local player not ready')
    game=current['modules']['game'];engine=current['modules']['engine'];identity=current['process_identity'];chain=current['chain']
    if game['sha256']!=discovery.HASHES['game'] or engine['sha256']!=discovery.HASHES['engine']:raise ValueError('Exact reviewed module hashes required')
    config={'pid':current['pid'],'phase':'player-update','interval_ms':INTERVAL_MS,'radius_metres':RADIUS_METRES,'duration_ms':int(duration*1000),
      'process_creation_time_100ns':str(identity['creation_time_100ns']),'executable':identity['executable'],'engine_module':engine,
      'module_name':game['name'],'module_path':game['path'],'module_base':game['base'],'module_size':game['size'],
      'game_instance':current['objects']['game']['address'],'player_instance':current['objects']['player']['address'],
      'prologues':[{**g,'module':'game'} for g in current['guarded_prologues']+current['discovery_prologues']]+static['function_guards']}
    config['values']=[config['player_instance'],config['game_instance'],chain['game_global_slot'],game['base'],chain['level'],chain['client'],chain['player_gate'],engine['base'],'0','0','0',str(int(bool((ground_items or ground_only) and not containers_only))),str(max_dispatches),str(int(not (ground_only or containers_only))),str(int(bool(containers or containers_only)))]
    return config,{'validated_session':current,'query':static,
      'javascript_sha256':hashlib.sha256(Path(__file__).with_suffix('.js').read_bytes()).hexdigest(),
      'lifecycle_contract':'Only successful normal QuickJS17.24 unload permits session detach; no manual CModule disposal'}


def dummy():
    report={'mode':'owned_runtime_fixture_no_game_access','cases':[],'errors':[],'live_executed':False,
      'core_sha256':hashlib.sha256(Path(__file__).with_suffix('.c').read_bytes()).hexdigest(),
      'fixture_sha256':hashlib.sha256((ROOT/'tools/autoloot_runtime_fixture.js').read_bytes()).hexdigest()}
    child=subprocess.Popen([sys.executable,'-u','-c','import time; time.sleep(180)'],creationflags=subprocess.CREATE_NO_WINDOW)
    session=None
    try:
        report['stage']='attach';session=bounded(lambda:frida.attach(child.pid))
        session.on('detached',lambda reason,crash:report.update(detached_event={'reason':reason,'crash':str(crash)}))
        source=(ROOT/'tools/autoloot_runtime_fixture.js').read_text().replace('__OWNED_PID__',str(child.pid)).replace('__CORE_SOURCE__',json.dumps(Path(__file__).with_suffix('.c').read_text()))
        script=bounded(lambda:session.create_script(source,runtime='qjs'))
        script.on('message',lambda m,d:report.setdefault('messages',[]).append(m))
        report['stage']='load';bounded(script.load);rpc=script.exports_sync
        modes=['valid','continuous_arrivals','zero_count','near2','far','dirty','wrong_handle','forwarding','extra','mode','nested','null_manager',
          'wrong_owner','ambiguous','other_action','eligibility_false','no_progress','empty','pagination','concurrency',
          'blocked_query','blocked_dispatch','blocked_dtor','slow_query','context_overflow','respawn','bounded_logs','cooldown_pressure',
          'ground_valid','ground_swap','ground_swap_during_dispatch','ground_forward','ground_forward_448','ground_forward_458',
          'ground_callback','ground_consumed','ground_blocked_dispatch','ground_continuous','ground_receiver_generation','ground_no_progress',
          'container_valid','container_wrong_state','container_other_action','container_flag','container_mode','container_nested','container_forward','container_iloot',
          'container_context','container_blocked_dispatch','container_blocked_select','container_no_progress','container_disabled','container_complex_layout',
          'body_near2','body_far2','body_range_changed','ground_near2','ground_far2','ground_range_changed','container_near2','container_far2','container_range_changed']
        for mode in modes:
            report['stage']='configure '+mode;rpc.configure(mode)
            ticks=6 if mode=='slow_query' else 85 if mode in ('valid','continuous_arrivals','no_progress','ground_continuous','ground_receiver_generation','ground_no_progress','container_no_progress') else 80 if mode in ('bounded_logs','cooldown_pressure') else 35
            report['stage']='run '+mode;rpc.run(ticks,4 if mode=='concurrency' else 1,False);deadline=time.monotonic()+12
            if 'blocked_' in mode:
                while not rpc.poll()['blocked']:
                    if time.monotonic()>deadline:raise TimeoutError('Native fixture did not block')
                    time.sleep(.005)
                stop_pending=rpc.stop();assert stop_pending.get('deferred'),mode;rpc.release()
            while True:
                report['stage']='poll '+mode;result=rpc.poll()
                if result['joined']:break
                if time.monotonic()>deadline:raise TimeoutError('Owned workers did not finish')
                time.sleep(.01)
            if mode=='respawn':
                rpc.respawn();rpc.run(35,1,True)
                while True:
                    result=rpc.poll()
                    if result['joined']:break
                    if time.monotonic()>deadline:raise TimeoutError('Respawn workers did not finish')
                    time.sleep(.01)
            stop=rpc.stop();v=[int(x) for x in result['values']];stats=result['stats']
            assert stop['restored'] and stop['joined'] and result['snapshot_available'],(mode,result)
            assert result['register_failures']==0 and all(not w['failures'] for w in result['workers']),(mode,result)
            assert not any(stats[i] for i in (1,3,5,7,9,11)),(mode,result)
            assert stats[12]==stats[13] and v[1]==v[2]==stats[10]==stats[14],(mode,result)
            assert v[17]<=4096 and len(result['events'])<=64 and len(result['cadence'])<=64,(mode,result)
            cadence=sorted(result['cadence'],key=lambda c:int(c[0]));qpc=[int(c[4]) for c in cadence]
            frequency=v[39]
            if cadence:
                assert v[11]-int(cadence[-1][1])==INTERVAL_MS,(mode,result)
                assert v[38]-int(cadence[-1][4])==(frequency*INTERVAL_MS+999)//1000,(mode,result)
            assert all(b-a>=frequency*INTERVAL_MS/1000 for a,b in zip(qpc,qpc[1:])),(mode,result)
            if mode=='valid':assert v[0]>=4 and v[1]>=4 and v[3]==2 and v[4]==2 and v[36]>=frequency*INTERVAL_MS/1000,(mode,result)
            if mode=='continuous_arrivals':
                completed_cycles={int(e[0]) for e in result['events'] if int(e[5])==1}
                assert len(completed_cycles)>=4 and v[3]>=8 and v[4]==v[3],(mode,result)
            if mode in ('zero_count','near2'):assert v[3]==2 and all(b['state']==5 and b['count']==0 for b in result['body_states']),(mode,result)
            if mode in ('far','dirty','wrong_handle','forwarding','extra','mode','nested','null_manager','wrong_owner','ambiguous'):assert result['body_states'][0]['state']==1 and v[3]<=1,(mode,result)
            if mode in ('other_action','eligibility_false','slow_query','empty','blocked_query','blocked_dtor'):assert v[3]==0,(mode,result)
            if mode=='no_progress':assert v[3]==2 and v[4]==0 and v[0]>=4,(mode,result)
            if mode=='blocked_dispatch':assert v[3]==1 and v[4]==1,(mode,result)
            if mode=='context_overflow':assert v[23]>0 and v[3]==0,(mode,result)
            if mode=='respawn':assert v[3]==4 and v[0]>=3,(mode,result)
            if mode=='bounded_logs':assert v[13]>=64 and len(result['events'])==64,(mode,result)
            if mode=='cooldown_pressure':assert v[3]==64 and v[4]==0 and v[35]>0,(mode,result)
            if mode=='slow_query':assert all(b-a>=frequency*.320 for a,b in zip(qpc,qpc[1:])),(mode,result)
            if mode=='valid':
                assert v[31]==INTERVAL_MS and v[0]==v[1],(mode,result)
            if mode=='body_near2':assert v[3]==v[4]==2,(mode,result)
            if mode.endswith('_far2') or mode.endswith('_range_changed'):assert v[3]==0,(mode,result)
            if mode.startswith('ground_'):
                assert v[4]==0 and v[40]==1,(mode,result)
                if mode in ('ground_continuous','ground_receiver_generation'):
                    assert v[41]==0 and v[43]>=8 and v[44]==v[43] and v[42]==0,(mode,result)
                elif mode=='ground_no_progress':assert v[41]==0 and v[43]==2 and v[44]==0 and v[0]>=4,(mode,result)
                elif mode in ('ground_valid','ground_blocked_dispatch','ground_near2'):
                    assert v[3]==1 and v[43]==1 and v[44]==1 and v[42]==1 and stats[15]==1,(mode,result)
                elif mode=='ground_swap_during_dispatch':
                    assert v[3]==1 and v[42]==1 and v[44]==0 and stats[15]==0,(mode,result)
                else:assert v[3]==0 and stats[15]==0,(mode,result)
            if mode.startswith('container_'):
                assert v[4]==v[43]==v[44]==0 and v[40]==0,(mode,result)
                if mode in ('container_valid','container_blocked_dispatch','container_near2'):
                    assert v[3]==v[47]==v[48]==1 and v[42]==1 and stats[15]==1,(mode,result)
                elif mode=='container_no_progress':assert v[47]==2 and v[48]==0 and v[0]>=4,(mode,result)
                else:assert v[3]==v[47]==v[48]==stats[15]==0,(mode,result)
            report['cases'].append({'name':mode,'passed':True,'clock':'accelerated_tick_and_qpc' if mode in ('bounded_logs','cooldown_pressure') else 'real_windows_clocks',
              'result':result,'cleanup':stop,'qpc_intervals_ms':[(b-a)/frequency*1000 for a,b in zip(qpc,qpc[1:])]})
        bounded(script.unload);report['script_unloaded']=True;bounded(session.detach);session=None;report['session_detached']=True
        host_tests=subprocess.run([sys.executable,str(ROOT/'tools/autoloot_runtime_fixture.py')],capture_output=True,text=True,encoding='utf-8',timeout=30)
        report['host_tests']={'passed':host_tests.returncode==0,'exit_code':host_tests.returncode,
          'output':(host_tests.stdout+host_tests.stderr)[-4000:]}
        if host_tests.returncode:raise AssertionError('Host-control regression tests failed')
        report['passed']=True
    except Exception as error:report['passed']=False;report['errors'].append(type(error).__name__+': '+str(error))
    finally:
        report['child_exit_before_cleanup']=child.poll()
        if child.poll() is None:child.terminate()
        child.wait(timeout=5)
        if session:
            try:bounded(session.detach)
            except Exception as error:report['detach_note']=str(error)
        report['owned_child_exited']=child.poll() is not None
        output=ROOT/'evidence/autoloot-runtime-dummy.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'cases':len(report['cases']),'errors':report['errors'],'output':str(output)}))
    return 0 if report['passed'] else 1


def live(args):
    try:
        with SingleInstance():return _live(args)
    except AlreadyRunning as error:
        print(json.dumps({'already_running':True,'message':str(error)}));return 2


def _live(args):
    report={'mode':'resident_native_autoloot','started_at_utc':datetime.now(timezone.utc).isoformat(),
            'messages':[],'errors':[],'cleanup':{},'live_executed':False,
            'radius_metres':RADIUS_METRES,'interval_ms':INTERVAL_MS,
            'limitations':['The100ms cadence is verified only in the owned fixture until an in-game run is performed.',
              'Eight millisecond budget is checked BETWEEN native calls; an engine call may exceed it.',
              'Pause/menu/death guards are not established; activate only during normal gameplay.',
              'Spatial pagination observes a changing vector; coverage is not atomic.',
              'No-progress slots are retained60s; full64-slot pressure refuses new dispatches.',
              'Post count0/state5 does not establish inventory credit or cooperative ownership.']}
    lock=threading.Lock();io_lock=threading.Lock();armed=threading.Event();stopped=threading.Event();detached=threading.Event()
    session=script=None;load_requested=False;config=None
    status_path=getattr(args,'status',ROOT/'evidence/autoloot5m/status.json');stop_path=getattr(args,'stop_file',ROOT/'evidence/autoloot5m/stop.request')
    def write_json(path,value):
        # Windows readers can briefly deny replacement. I/O failure must never
        # unwind past a live CModule or skip the normal unload barrier.
        try:
            with io_lock:
                path.parent.mkdir(parents=True,exist_ok=True)
                temporary=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
                temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
                for attempt in range(6):
                    try:os.replace(temporary,path);return True
                    except PermissionError:
                        if attempt==5:raise
                        time.sleep(.05)
        except OSError as error:
            with lock:
                report['io_failures_count']=report.get('io_failures_count',0)+1
                report['last_io_error']=str(error)
            return False
    def save():
        with lock:value=json.loads(json.dumps(report))
        return write_json(args.output,value)
    def status(phase,running,ready,message_text=''):
        value={'host_pid':os.getpid(),'launch_token':getattr(args,'launch_token',None),'running':running,'phase':phase,'ready':ready,'interval_ms':INTERVAL_MS,'radius_metres':RADIUS_METRES,
          'updated_at_utc':datetime.now(timezone.utc).isoformat(),'message':message_text,'pid':config['pid'] if config else None,
          'result':report.get('result')}
        return write_json(status_path,value)
    def message(m,data):
        with lock:report['messages'].append(m)
        kind=m.get('payload',{}).get('type') if m.get('type')=='send' else None
        if kind=='armed':
            report['live_executed']=True;armed.set()
            if not status('active',True,True,'AutoLoot actif : rayon2m, intervalle100ms'):
                report['errors'].append('Active status could not be published; stopping cooperatively');stopped.set()
            print('armed: resident native100ms autoloot',flush=True)
        if kind=='stopped' or m.get('type')=='error':stopped.set()
    def disconnect(reason,crash):
        report['detached_event']={'reason':reason,'crash':str(crash) if crash else None}
        detached.set();stopped.set()
    def setup(function,seconds,label):
        done,outcome=lifecycle.launch(function)
        try:late=not done.wait(seconds)
        except KeyboardInterrupt:late=True
        if late:
            report['errors'].append(label+' still pending; retaining transport/resources');save()
            print(label+' pending: retaining host, no force-free',flush=True)
            while not done.is_set() and not detached.is_set():
                try:done.wait(1)
                except KeyboardInterrupt:print('pending operation retained',flush=True)
        if not done.is_set():raise RuntimeError(label+' target disconnected')
        if 'error' in outcome:raise RuntimeError(outcome['error'])
        return outcome.get('value'),late
    try:
        if clear_stale_stop(stop_path):
            report['stop_before_setup']=True;status('stopped',False,False,'Arrêt demandé avant activation');raise _StopRequested()
        if not status('starting',True,False,'Vérification de la partie et du runtime'):
            raise OSError('Startup status could not be published; no hook installed')
        api=discovery.api_setup();pids=discovery.process_ids(api)
        if not pids or (getattr(args,'pid',None) is not None and args.pid not in pids):
            report['game_closed']=True;status('game_closed',False,False,'Le jeu est fermé');raise _StopRequested()
        config,proof=prepare(getattr(args,'session',None),args.duration,getattr(args,'pid',None),getattr(args,'ground_items',False),getattr(args,'max_dispatches',0),getattr(args,'ground_only',False),getattr(args,'containers',False),getattr(args,'containers_only',False));report['preflight']=proof
        if stop_path.exists():report['stop_before_setup']=True;raise _StopRequested()
        raw=Path(__file__).with_suffix('.c').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=proof['query']['core_sha256']:raise ValueError('Core changed after preflight')
        source=Path(__file__).with_suffix('.js').read_text()
        if source.count('__QUERY_CONFIG__')!=1 or source.count('__QUERY_CORE__')!=1:raise ValueError('Source marker mismatch')
        source=source.replace('__QUERY_CONFIG__',json.dumps(config)).replace('__QUERY_CORE__',json.dumps(raw.decode('utf-8')))
        session,late=setup(lambda:frida.attach(config['pid']),10,'attach');session.on('detached',disconnect)
        if late:raise TimeoutError('Late attach; resident runtime not loaded')
        if stop_path.exists():report['stop_before_setup']=True;raise _StopRequested()
        script,late=setup(lambda:session.create_script(source,name='autoloot-runtime',runtime='qjs'),5,'create_script')
        script.on('message',message)
        if late:raise TimeoutError('Late creation; resident runtime not loaded')
        if stop_path.exists():report['stop_before_setup']=True;raise _StopRequested()
        load_requested=True;_,late=setup(script.load,10,'load')
        if late:raise TimeoutError('Late load; stopping resident runtime')
        if stop_path.exists():report['stop_after_load']=True;raise _StopRequested()
        if not armed.wait(1):raise RuntimeError('Resident hook did not report armed')
        deadline=time.monotonic()+args.duration if args.duration else None
        while not stopped.is_set() and (deadline is None or time.monotonic()<deadline) and not stop_path.exists():
            value=lifecycle.bounded(script.exports_sync.poll,3)
            if value.get('type')=='stopped':break
            if value.get('result',{}).get('ready'):
                report['result']=value['result']
                if value['result'].get('stats',{}).get('disabled',0)>0:
                    report['errors'].append('Native runtime disabled itself; stopping after a guard/canary fault');break
                if value['result'].get('stats',{}).get('dispatch_limit_reached',0)>0:
                    report['dispatch_limit_reached']=True;break
                if not status('active',True,True,'AutoLoot actif'):
                    report['errors'].append('Status publication failed; stopping cooperatively');break
                save()
            stopped.wait(.5)
    except _StopRequested:report['stop_requested']=True
    except KeyboardInterrupt:report['user_interrupt']=True
    except Exception as error:
        if not detached.is_set():report['errors'].append(type(error).__name__+': '+str(error))
    finally:
        if script is not None and load_requested and not detached.is_set():
            status('stopping',True,False,'Arrêt coopératif et drainage des appels natifs')
            try:report['cleanup']['stop_rpc']=lifecycle.bounded(script.exports_sync.stop,3)
            except (Exception,KeyboardInterrupt) as error:report['cleanup']['stop_error']=str(error)
            if 'stop_error' in report['cleanup']:
                report['errors'].append('Stop state unknown; retaining transport until target exit');save()
                print('stop state unknown: retaining native resources, no forced release',flush=True)
                while not detached.is_set():
                    try:detached.wait(1)
                    except KeyboardInterrupt:print('native resources retained',flush=True)
            while report['cleanup'].get('stop_rpc',{}).get('type')=='stop_deferred' and not detached.is_set():
                report['cleanup']['native_completion_pending']=True;save()
                try:
                    value=lifecycle.bounded(script.exports_sync.poll,3)
                    if value.get('type')=='stopped':report['cleanup']['stop_rpc']=value;break
                    detached.wait(.1)
                except (Exception,KeyboardInterrupt) as error:
                    report['cleanup']['completion_wait_note']=str(error)
                    try:detached.wait(.2)
                    except KeyboardInterrupt:pass
            done,outcome=lifecycle.launch(script.unload)
            try:pending=not done.wait(10)
            except KeyboardInterrupt:pending=True
            if pending:
                report['errors'].append('Normal QJS unload pending: retaining host/session');save()
                print('unload pending: retaining native code/state until normal completion or target exit',flush=True)
                while not done.is_set() and not detached.is_set():
                    try:done.wait(1)
                    except KeyboardInterrupt:print('native resources retained; no forced release',flush=True)
            if done.is_set() and 'error' not in outcome:report['cleanup']['script_unloaded']=True
            elif done.is_set():
                report['cleanup']['unload_error']=outcome['error'];report['errors'].append('Normal unload failed; resources retained');save()
                while not detached.is_set():
                    try:detached.wait(1)
                    except KeyboardInterrupt:print('failed unload: retaining transport until target exit',flush=True)
        elif script is None or not load_requested:
            report['cleanup']['no_script_execution']=True;report['cleanup']['script_unloaded']=True
        if session is not None and not detached.is_set() and report['cleanup'].get('script_unloaded'):
            try:lifecycle.bounded(session.detach,5);report['cleanup']['session_detached']=True
            except Exception as error:report['cleanup']['detach_error']=str(error)
        if detached.is_set():report['cleanup']['session_detached']=True
        stop=report['cleanup'].get('stop_rpc',{});result=stop.get('result') or {}
        report['result']=result;report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        report['ok']=(not report['errors'] and stop.get('restoration_verified') is True and stop.get('detach_done') is True and
                      not stop.get('errors') and not stop.get('cleanup_errors') and report['cleanup'].get('script_unloaded') is True and
                      report['cleanup'].get('session_detached') is True)
        closed=report.get('detached_event',{}).get('reason')=='process-terminated' or report.get('game_closed')
        if closed:report['ok']=not report['errors'];report['game_closed']=True
        if report.get('stop_before_setup'):report['ok']=not report['errors']
        phase='game_closed' if closed else 'stopped' if report['ok'] else 'error'
        status(phase,False,False,'Le jeu est fermé' if closed else 'AutoLoot arrêté' if report['ok'] else '; '.join(report['errors']) or 'Nettoyage incomplet')
        save()
    print(json.dumps({'output':str(args.output),'ok':report['ok'],'status':report['result'].get('status'),'errors':report['errors']}))
    return 0 if report['ok'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--dummy',action='store_true')
    modes.add_argument('--preflight-only',action='store_true')
    modes.add_argument('--static-only',action='store_true')
    modes.add_argument('--live',action='store_true')
    parser.add_argument('--session',type=Path)
    parser.add_argument('--duration',type=float,default=0)
    parser.add_argument('--pid',type=int)
    parser.add_argument('--launch-token',default=None)
    parser.add_argument('--containers',action='store_true',help='Experimental exact local Container Take1 route')
    parser.add_argument('--containers-only',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--ground-only',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--ground-items',action='store_true',help='Experimental standard ground Take1 route, in addition to corpses')
    parser.add_argument('--max-dispatches',type=int,default=0,help='Global native dispatch cap;0 means unlimited')
    parser.add_argument('--status',type=Path,default=ROOT/'evidence/autoloot5m/status.json')
    parser.add_argument('--stop-file',type=Path,default=ROOT/'evidence/autoloot5m/stop.request')
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/autoloot5m/runtime-report.json')
    args=parser.parse_args()
    if args.dummy:return dummy()
    if args.static_only:
        print(json.dumps({'static_only':True,'process_opened':False,'proof':static_proof()}));return 0
    if not 0<=args.duration<=86400:parser.error('duration must be0..86400s')
    if args.preflight_only:
        config,proof=prepare(args.session,args.duration,args.pid,args.ground_items,args.max_dispatches,args.ground_only,args.containers,args.containers_only)
        print(json.dumps({'preflight_ok':True,'frida_attached':False,'output_written':False,'config':config,
                          'core_sha256':proof['query']['core_sha256']}));return 0
    return live(args)


if __name__=='__main__':raise SystemExit(main())
