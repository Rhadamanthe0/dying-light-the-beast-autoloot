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
from runtime_profile import PROFILE_171, select_profile, profile_digest, compiled_core, fixture_image_size, profile_by_name, require_live_profile, make_trial_181


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


def core_source(profile=None):
    return compiled_core(Path(__file__).with_suffix('.c').read_text(encoding='utf-8'),profile)


def qualification_binding(profile=None):
    profile=PROFILE_171 if profile is None else profile
    return {'profile_id':profile['id'],'profile_sha256':profile_digest(profile),
            'core_sha256':hashlib.sha256(core_source(profile).encode('utf-8')).hexdigest(),
            'fixture_sha256':hashlib.sha256((ROOT/'tools/autoloot_runtime_fixture.js').read_bytes()).hexdigest()}


def static_proof():
    game=Image(discovery.BIN/discovery.GAME_DLL);engine=Image(discovery.BIN/discovery.ENGINE_DLL)
    profile=select_profile(hashlib.sha256(game.data).hexdigest(),hashlib.sha256(engine.data).hexdigest())
    guards=[]
    for name,address_key in [
        ('FindObjectsInRadius','ENGINE_FIND_RADIUS'), ('RadiusImpl','ENGINE_RADIUS_IMPL'),
        ('GetLevel','ENGINE_GET_LEVEL'), ('VectorDestructor','GAME_VECTOR_DESTRUCTOR'),
        ('ContextCtor','GAME_CONTEXT_CTOR'), ('GetComponentImpl','ENGINE_GET_COMPONENT'),
        ('GetAction','GAME_GET_ACTION'), ('CanUse','GAME_CAN_USE'),
        ('PlayerDispatch','GAME_PLAYER_DISPATCH'), ('BagCanUse','GAME_BAG_CAN_USE'),
        ('BagTake','GAME_BAG_TAKE'), ('GroundMessageWrapper','GAME_GROUND_MESSAGE_WRAPPER'),
        ('GroundItemTake','GAME_GROUND_TAKE'), ('DroppedCanUse','GAME_DROPPED_CAN_USE'),
        ('DroppedTake','GAME_DROPPED_TAKE'), ('DroppedInventoryTake','GAME_DROPPED_INVENTORY_TAKE'),
        ('OpportunityFalse','GAME_OPPORTUNITY_FALSE'), ('OpportunityFlag','GAME_OPPORTUNITY_FLAG'),
        ('OpportunityContext','GAME_OPPORTUNITY_CONTEXT'), ('ProxyTargetThunk','GAME_PROXY_TARGET_THUNK'),
        ('ContainerCanUse','GAME_CONTAINER_CAN_USE'), ('ContainerTake','GAME_CONTAINER_TAKE'),
        ('ContainerTakeAll','GAME_CONTAINER_TAKE_ALL')]:
        module=address_key.split('_',1)[0].lower();rva=profile['rvas'][address_key]
        image=game if module=='game' else engine;offset=image.offset(rva)
        guards.append({'name':name,'module':module,'rva':rva,'hex':image.data[offset:offset+16].hex()})
    return {'function_guards':guards,'game_sha256':profile['hashes']['game'],'engine_sha256':profile['hashes']['engine'],
            **qualification_binding(profile),'profile':profile,
            'interval_ms':INTERVAL_MS,'radius_metres':RADIUS_METRES,'page_size':8,'budget_ms_between_calls':8,'rpm_limit':4096}


def prepare(session_path=None,duration=0,pid=None,ground_items=False,max_dispatches=0,ground_only=False,containers=False,containers_only=False,dropped_items=False,diagnostic_only=False,trial_181=False,trial_category=None):
    if type(max_dispatches) is not int or not 0<=max_dispatches<=1000000:raise ValueError('max_dispatches must be0..1000000')
    if type(trial_181) is not bool:raise ValueError('Trial181 marker must be boolean')
    if trial_category is not None and not trial_181:raise ValueError('Trial category requires --trial-181')
    if trial_181 and any((ground_items,ground_only,containers,containers_only,dropped_items)):
        raise ValueError('Trial181 forbids legacy collection flags; use its explicit category')
    if trial_181 and (max_dispatches!=0 if diagnostic_only else not 1<=max_dispatches<=64):
        raise ValueError('Trial181 requires cap0 for diagnosis or an integer cap1..64 for collection')
    if frida.__version__!='17.24.0':raise ValueError('Reviewed Frida17.24.0 required')
    if not 0<=duration<=86400:raise ValueError('Duration must be0(resident)..86400s')
    static=static_proof()
    trial=make_trial_181(static['profile'],duration,diagnostic_only,'corpses' if trial_category is None else trial_category,max_dispatches) if trial_181 else None
    require_live_profile(static['profile'],trial,'trial-181' if trial else 'resident')
    qualification=json.loads(qualification_path(static['profile']).read_text())
    if qualification.get('passed') is not True or any(qualification.get(key)!=static[key] for key in ('profile_id','profile_sha256','core_sha256','fixture_sha256')):
        raise ValueError('Current runtime has no matching successful owned-fixture qualification; run --dummy')
    current=discovery.validate_session(session_path,max_age_seconds=120) if session_path else discovery.discover(pid)
    if not current.get('ready'):raise ValueError('Current local player not ready')
    game=current['modules']['game'];engine=current['modules']['engine'];identity=current['process_identity'];chain=current['chain']
    if game['sha256']!=static['profile']['hashes']['game'] or engine['sha256']!=static['profile']['hashes']['engine']:raise ValueError('Exact reviewed module hashes required')
    config={'profile_id':static['profile_id'],'profile_hashes':dict(static['profile']['hashes']),'game_sha256':game['sha256'],
      'execution_mode':'trial-181' if trial else 'resident','trial_181':trial,
      'rvas':dict(static['profile']['rvas']),'pid':current['pid'],'phase':'player-update','interval_ms':INTERVAL_MS,'radius_metres':RADIUS_METRES,'duration_ms':trial['duration_ms'] if trial else int(duration*1000),
      'process_creation_time_100ns':str(identity['creation_time_100ns']),'executable':identity['executable'],'engine_module':engine,
      'module_name':game['name'],'module_path':game['path'],'module_base':game['base'],'module_size':game['size'],
      'game_instance':current['objects']['game']['address'],'player_instance':current['objects']['player']['address'],
      'prologues':[{**g,'module':'game'} for g in current['guarded_prologues']+current['discovery_prologues']]+static['function_guards']}
    config['values']=[config['player_instance'],config['game_instance'],chain['game_global_slot'],game['base'],chain['level'],chain['client'],chain['player_gate'],engine['base'],'0','0','0',str(int(bool((ground_items or ground_only) and not containers_only))),str(max_dispatches),str(int(not (ground_only or containers_only))),str(int(bool(containers or containers_only))),str(int(bool(dropped_items)))]
    if diagnostic_only:
        for slot in (11,13,14,15):config['values'][slot]='0'
    if trial:
        routes={'corpses':['0','1','1','0','0'],'ground':['1','1','0','0','0'],
                'dropped':['0','1','0','0','1'],'containers':['0','1','0','1','0']}
        config['values'][11:16]=['0','0','0','0','0'] if diagnostic_only else routes[trial['category']]
        config['values'][12]=str(trial['dispatch_cap'])
    return config,{'validated_session':current,'query':static,
      'javascript_sha256':hashlib.sha256(Path(__file__).with_suffix('.js').read_bytes()).hexdigest(),
      'lifecycle_contract':'Only successful normal QuickJS17.24 unload permits session detach; no manual CModule disposal'}


def qualification_path(profile):
    suffix='' if profile['id']==PROFILE_171['id'] else '-'+profile['id']
    return ROOT/'evidence'/('autoloot-runtime-dummy'+suffix+'.json')


def dummy(profile_name='1.7.1'):
    profile=profile_by_name(profile_name)
    report={'mode':'owned_runtime_fixture_no_game_access','cases':[],'errors':[],'live_executed':False,
      **qualification_binding(profile)}
    child=subprocess.Popen([sys.executable,'-u','-c','import time; time.sleep(180)'],creationflags=subprocess.CREATE_NO_WINDOW)
    session=None
    try:
        report['stage']='attach';session=bounded(lambda:frida.attach(child.pid))
        session.on('detached',lambda reason,crash:report.update(detached_event={'reason':reason,'crash':str(crash)}))
        source=(ROOT/'tools/autoloot_runtime_fixture.js').read_text().replace('__OWNED_PID__',str(child.pid)).replace('__CORE_SOURCE__',json.dumps(core_source(profile))).replace('__FIXTURE_PROFILE__',json.dumps({**profile,'fixture_image_size':fixture_image_size(profile)}))
        script=bounded(lambda:session.create_script(source,runtime='qjs'))
        script.on('message',lambda m,d:report.setdefault('messages',[]).append(m))
        report['stage']='load';bounded(script.load);rpc=script.exports_sync
        modes=['ground_alternate_proxy', 'ground_proxy_changed', 'container_alternate_proxy', 'container_proxy_changed', 'dropped_alternate_proxy', 'dropped_proxy_changed', 'bag_alternate_proxy', 'bag_proxy_changed', 'resource_alternate_proxy', 'resource_proxy_changed','bag_wrong_proxy_type','dropped_wrong_proxy_type','ground_wrong_proxy_type','dropped_proxy_slot','resource_mode_unreadable','resource_vfunc','resource_valid','resource_multiple','resource_empty','resource_count_limit','resource_count_overflow','resource_mode1','resource_mode_invalid','resource_wrong_state','resource_nested','resource_flag','resource_iloot','resource_callback','resource_wrong_owner','resource_strategy','resource_generation_changed','resource_full','resource_swap','resource_no_progress','resource_post_unreadable','resource_mode_changed','resource_count_changed','resource_near2','resource_far2','resource_range_changed','bag_empty','bag_iloot','bag_post_unreadable','bag_human_changed','bag_valid','bag_mode1','bag_human_control','bag_human_reciprocal','bag_strategy','bag_wrong_owner','bag_wrong_receiver','bag_generation_changed','bag_other_action','bag_full','bag_nested','bag_no_progress','bag_corpse_no_rescue','bag_callback','bag_near2','bag_far2','bag_range_changed','ground_canuse_opportunity_changed','dropped_canuse_opportunity_changed','ground_opportunity','dropped_opportunity','ground_opportunity_changed','dropped_opportunity_changed','ground_ordinary_throwable','dropped_ordinary_throwable','ground_unknown_getter','dropped_unknown_getter','ground_unreadable_desc','dropped_unreadable_desc','diagnostic_mix','diagnostic_only','dropped_valid','dropped_near2','dropped_far2','dropped_swap','dropped_full','dropped_no_progress','dropped_header_changed','dropped_desc_changed','dropped_generation_changed','dropped_post_unreadable','dropped_disabled','dropped_callback','unknown_class','valid','continuous_arrivals','zero_count','near2','far','dirty','wrong_handle','forwarding','extra','mode','nested','null_manager',
          'wrong_owner','ambiguous','other_action','eligibility_false','no_progress','empty','pagination','concurrency',
          'blocked_query','blocked_dispatch','blocked_dtor','slow_query','context_overflow','respawn','bounded_logs','cooldown_pressure',
          'ground_valid','ground_swap','ground_swap_during_dispatch','ground_forward','ground_forward_448','ground_forward_458',
          'ground_callback','ground_consumed','ground_blocked_dispatch','ground_continuous','ground_receiver_generation','ground_no_progress',
          'container_valid','container_wrong_state','container_other_action','container_flag','container_mode','container_nested','container_forward','container_iloot',
          'container_context','container_blocked_dispatch','container_blocked_select','container_no_progress','container_disabled','container_complex_layout',
          'body_near2','body_far2','body_range_changed','ground_near2','ground_far2','ground_range_changed','container_near2','container_far2','container_range_changed','prequery_concurrency',
          'unreadable_first','slow_bind_first','slow_action_first','budget_before_candidate','tail_rotation','budget_after_dispatch']
        progression_modes={'unreadable_first','slow_bind_first','slow_action_first','budget_before_candidate','tail_rotation','budget_after_dispatch'}
        for mode in modes:
            report['stage']='configure '+mode;rpc.configure(mode)
            ticks=1 if mode=='resource_mode_changed' else 6 if mode=='slow_query' else 85 if mode in ('valid','continuous_arrivals','no_progress','ground_continuous','ground_receiver_generation','ground_no_progress','container_no_progress') else 80 if mode in ('bounded_logs','cooldown_pressure') else 35
            report['stage']='run '+mode;deadline=time.monotonic()+12
            if mode=='prequery_concurrency':
                rpc.run(1,1,False)
                def until(predicate):
                    while True:
                        value=rpc.diag()
                        if predicate(value):return value
                        if time.monotonic()>deadline:raise TimeoutError('Owned pre-query synchronization failed')
                        time.sleep(.005)
                until(lambda r:r['flags'][0]==1)
                rpc.diagsecond();until(lambda r:r['flags'][2]==1)
                rpc.releaseclock();until(lambda r:r['workers'][0]['done']==1)
                report['prequery_foreign_inflight']=rpc.poll()
                rpc.releasesecond()
            else:rpc.run(1 if mode in progression_modes else ticks,4 if mode=='concurrency' else 1,False)
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
            first=result if mode in progression_modes else None
            if first is not None:
                rpc.run(2 if mode=='tail_rotation' else 1,1,False)
                while True:
                    result=rpc.poll()
                    if result['joined']:break
                    if time.monotonic()>deadline:raise TimeoutError('Progression workers did not finish')
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
            lifecycle=result['vector_lifecycle']
            # A checkpoint can cancel an initialized inline vector before query.
            # Every queried vector still needs exactly one matching destruction.
            assert stats[12]==stats[13],(mode,result)
            assert v[1]==stats[10]==lifecycle[0]==lifecycle[1],(mode,result)
            assert v[2]==stats[14]==lifecycle[1]+lifecycle[2] and v[2]<=v[0],(mode,result)
            assert lifecycle[3]==lifecycle[4]==lifecycle[5]==0,(mode,result)
            if mode=='prequery_concurrency':
                assert v[0]==v[2]==lifecycle[2]==lifecycle[6]==1 and v[1]==0,(mode,result)
                assert v[3]==v[6]==v[23]==v[42]==stats[12]==stats[13]==0,(mode,result)
                assert int(report['prequery_foreign_inflight']['values'][24])==1,(mode,result)
            assert v[17]<=4096 and len(result['events'])<=64 and len(result['cadence'])<=64,(mode,result)
            cadence=sorted(result['cadence'],key=lambda c:int(c[0]));qpc=[int(c[4]) for c in cadence]
            frequency=v[39]
            if cadence:
                assert v[11]-int(cadence[-1][1])==INTERVAL_MS,(mode,result)
                assert v[38]-int(cadence[-1][4])==(frequency*INTERVAL_MS+999)//1000,(mode,result)
            assert all(b-a>=frequency*INTERVAL_MS/1000 for a,b in zip(qpc,qpc[1:])),(mode,result)
            if mode.startswith('resource_'):
                if mode in ('resource_alternate_proxy','resource_valid','resource_multiple','resource_count_limit','resource_near2'):assert v[3]==v[57]==v[58]==1,(mode,result)
                elif mode in ('resource_no_progress','resource_post_unreadable'):assert v[3]==v[57]==1 and v[58]==0,(mode,result)
                elif mode=='resource_mode1':assert v[3]==v[47]==v[48]==1 and v[57]==v[58]==0,(mode,result)
                else:assert v[3]==v[57]==v[58]==0,(mode,result)
            if mode.startswith('bag_'):
                if mode in ('bag_alternate_proxy','bag_valid','bag_near2'):assert v[3]==v[54]==v[55]==1,(mode,result)
                elif mode in ('bag_no_progress','bag_post_unreadable'):assert v[3]==v[54]==1 and v[55]==0,(mode,result)
                else:assert v[3]==v[54]==v[55]==0,(mode,result)
            if mode in ('ground_opportunity','dropped_opportunity'):
                assert all(stats[i]==0 for i in (0,2,4,6,8)),(mode,result)
            if mode=='diagnostic_mix':
                assert v[63]==16 and sum(int(row[1])!=0 for row in result['candidates'])==16,(mode,result)
                tables=[int(row[1]) for row in result['candidates']]
                assert max(tables)-min(tables)==15*16,(mode,result)
            if mode in ('diagnostic_only','diagnostic_mix'):
                assert v[1]>0 and v[62]>0 and v[3]==0 and all(stats[i]==0 for i in (0,2,4,6,8)),(mode,result)
            if mode.startswith('dropped_'):
                if mode in ('dropped_alternate_proxy','dropped_valid','dropped_near2','dropped_ordinary_throwable'):assert v[3]==v[51]==v[52]==1,(mode,result)
                elif mode in ('dropped_no_progress','dropped_post_unreadable'):assert v[3]==v[51]==1 and v[52]==0,(mode,result)
                else:assert v[3]==v[51]==v[52]==0,(mode,result)
            if mode in ('dropped_wrong_proxy_type','ground_wrong_proxy_type','bag_wrong_proxy_type'):
                assert v[3]==0 and all(stats[i]==0 for i in (0,2,4,6,8)),(mode,result)
                assert any(int(row[2])==43 and int(row[5])==1 for row in result['candidates'] if int(row[1])!=0),(mode,result)
            if mode=='dropped_proxy_slot':
                assert v[3]==0 and all(stats[i]==0 for i in (0,2,4,6,8)),(mode,result)
                assert any(int(event[6])==40 for event in result['events']),(mode,result)
            if mode.endswith('_proxy_changed'):
                assert v[3]==0 and stats[6]>0 and stats[8]==0,(mode,result)
                assert any(int(event[6])==40 for event in result['events']),(mode,result)
            if mode=='unknown_class':
                assert v[3]==0 and v[62]>1 and v[63]==1 and int(result['candidates'][0][1])!=0 and int(result['candidates'][0][5])==0,(mode,result)
            if mode=='wrong_owner':
                assert v[62]>0 and any(int(row[1])!=0 and int(row[5])==1 for row in result['candidates']),(mode,result)
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
            if first is not None:
                initial=[int(x) for x in first['values']]
                assert v[3]==v[4]==(2 if mode in ('budget_before_candidate','budget_after_dispatch') else 1),(mode,result)
                assert initial[3]==initial[4]==(1 if mode=='budget_after_dispatch' else 0) and v[12]==0,(mode,first,result)
                assert first['body_states'][1]['count']==2 and first['body_states'][1]['state']==1,(mode,first)
                if mode=='budget_before_candidate':
                    assert initial[12]==initial[21]==0 and initial[22]==2 and initial[6]==1,(mode,first)
                    assert all(b['count']==0 and b['state']==5 for b in result['body_states']),(mode,result)
                else:
                    assert initial[12]==initial[21]==(8 if mode=='tail_rotation' else 1),(mode,first)
                    assert initial[22]==(8 if mode=='tail_rotation' else 2),(mode,first)
                    assert result['body_states'][0]['count']==(0 if mode=='budget_after_dispatch' else 2),(mode,result)
                    assert result['body_states'][0]['state']==(5 if mode=='budget_after_dispatch' else 1),(mode,result)
                    assert result['body_states'][1]['count']==0 and result['body_states'][1]['state']==5,(mode,result)
                assert v[6]==(1 if mode in ('slow_bind_first','slow_action_first','budget_before_candidate','budget_after_dispatch') else 0),(mode,result)
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
                elif mode in ('ground_alternate_proxy','ground_valid','ground_blocked_dispatch','ground_near2','ground_ordinary_throwable'):
                    assert v[3]==1 and v[43]==1 and v[44]==1 and v[42]==1 and stats[15]==1,(mode,result)
                elif mode=='ground_swap_during_dispatch':
                    assert v[3]==1 and v[42]==1 and v[44]==0 and stats[15]==0,(mode,result)
                else:assert v[3]==0 and stats[15]==0,(mode,result)
            if mode.startswith('container_'):
                assert v[4]==v[43]==v[44]==0 and v[40]==0,(mode,result)
                if mode in ('container_alternate_proxy','container_valid','container_blocked_dispatch','container_near2'):
                    assert v[3]==v[47]==v[48]==1 and v[42]==1 and stats[15]==1,(mode,result)
                elif mode=='container_no_progress':assert v[47]==2 and v[48]==0 and v[0]>=4,(mode,result)
                else:assert v[3]==v[47]==v[48]==stats[15]==0,(mode,result)
            report['cases'].append({'name':mode,'passed':True,'clock':'controlled_progression' if mode in progression_modes else 'controlled_frozen_prequery_inflight' if mode=='prequery_concurrency' else 'accelerated_tick_and_qpc' if mode in ('bounded_logs','cooldown_pressure') else 'real_windows_clocks',
              'result':result,'cleanup':stop,'first_cycle':first,'qpc_intervals_ms':[(b-a)/frequency*1000 for a,b in zip(qpc,qpc[1:])]})
        bounded(script.unload);report['script_unloaded']=True;bounded(session.detach);session=None;report['session_detached']=True
        host_tests=subprocess.run([sys.executable,str(ROOT/'tools/autoloot_runtime_fixture.py')],capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
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
        output=qualification_path(profile);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
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
    if getattr(args,'trial_181',False):
        report['mode']='bounded_trial_181'
        report['limitations'].append('Essai expérimental 1.8.1 : diagnostic seul ou nombre explicite d’appels de collecte limité à 64 dans une catégorie; aucun crédit d’inventaire établi par ces compteurs. Une catégorie ne qualifie pas les autres. Conteneurs, sacs et ressources restent des scénarios distincts. La durée limite ne préempte pas un appel natif déjà commencé.')
    lock=threading.Lock();io_lock=threading.Lock();armed=threading.Event();stopped=threading.Event();detached=threading.Event()
    session=script=None;load_requested=False;config=None
    status_path=getattr(args,'status',ROOT/'evidence/autoloot5m/status.json');stop_path=getattr(args,'stop_file',ROOT/'evidence/autoloot5m/stop.request')
    pause_path=getattr(args,'pause_file',None)
    def stop_requested():
        return (pause_path is not None and pause_path.exists()) or stop_path.exists()
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
    def remember_stop(value):
        with lock:
            report['cleanup']['stop_rpc']=value
            if value.get('result'):report['result']=value['result']
            if value.get('errors') or value.get('cleanup_errors'):
                fault='Runtime stop reported faults: '+json.dumps({'errors':value.get('errors'),'cleanup_errors':value.get('cleanup_errors')})
                if fault not in report['errors']:report['errors'].append(fault)
    def message(m,data):
        with lock:report['messages'].append(m)
        kind=m.get('payload',{}).get('type') if m.get('type')=='send' else None
        if kind=='stopped':remember_stop(m['payload'])
        if kind=='armed':
            report['live_executed']=True;armed.set()
            if not status('active',True,True,'AutoLoot active: 2 m radius, 100 ms interval'):
                report['errors'].append('Active status could not be published; stopping cooperatively');stopped.set()
            print('armed: resident native100ms autoloot',flush=True)
        if m.get('type')=='error':report['errors'].append('JavaScript runtime error: '+str(m.get('description') or m))
        if kind=='stopped' or m.get('type')=='error':stopped.set()
    def disconnect(reason,crash):
        report['detached_event']={'reason':reason,'crash':str(crash) if crash else None}
        detached.set();stopped.set()
    def rpc_error(phase,error):
        detail=error if isinstance(error,str) else type(error).__name__+': '+str(error)
        transport=('TimeoutError','InvalidOperationError','TransportError','OperationCancelledError',
                   'ServerNotRunningError','ProcessNotFoundError')
        category=str(error).split(':',1)[0] if isinstance(error,RuntimeError) else detail.split(':',1)[0]
        invalid_closed=category!='InvalidOperationError' or any(text in detail.lower() for text in
            ('script has been destroyed','script is destroyed','session is detached','connection is closed'))
        if category in transport and invalid_closed:
            notes=report.setdefault('rpc_interruptions',[])
            if len(notes)==64:notes.pop(0)
            notes.append({'phase':phase,'error':detail})
            report['rpc_interruptions_count']=report.get('rpc_interruptions_count',0)+1
        elif phase+': '+detail not in report['errors']:report['errors'].append(phase+': '+detail)
        return detail
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
        if (pause_path is not None and pause_path.exists()) or clear_stale_stop(stop_path):
            report['stop_before_setup']=True;status('stopped',False,False,'Stop requested before activation');raise _StopRequested()
        if not status('starting',True,False,'Checking game session and runtime'):
            raise OSError('Startup status could not be published; no hook installed')
        api=discovery.api_setup();pids=discovery.process_ids(api)
        if not pids or (getattr(args,'pid',None) is not None and args.pid not in pids):
            report['game_closed']=True;status('game_closed',False,False,'The game is closed');raise _StopRequested()
        config,proof=prepare(getattr(args,'session',None),args.duration,getattr(args,'pid',None),getattr(args,'ground_items',False),getattr(args,'max_dispatches',0),getattr(args,'ground_only',False),getattr(args,'containers',False),getattr(args,'containers_only',False),getattr(args,'dropped_items',False),getattr(args,'diagnostic_only',False),getattr(args,'trial_181',False),getattr(args,'trial_category',None));report['preflight']=proof
        if config.get('trial_181'):report['trial']=config['trial_181']
        if stop_requested():report['stop_before_setup']=True;raise _StopRequested()
        raw=core_source(proof['query']['profile']).encode('utf-8')
        if hashlib.sha256(raw).hexdigest()!=proof['query']['core_sha256']:raise ValueError('Core changed after preflight')
        source=Path(__file__).with_suffix('.js').read_text()
        if source.count('__QUERY_CONFIG__')!=1 or source.count('__QUERY_CORE__')!=1:raise ValueError('Source marker mismatch')
        source=source.replace('__QUERY_CONFIG__',json.dumps(config)).replace('__QUERY_CORE__',json.dumps(raw.decode('utf-8')))
        session,late=setup(lambda:frida.attach(config['pid']),10,'attach');session.on('detached',disconnect)
        if late:raise TimeoutError('Late attach; resident runtime not loaded')
        if stop_requested():report['stop_before_setup']=True;raise _StopRequested()
        script,late=setup(lambda:session.create_script(source,name='autoloot-runtime',runtime='qjs'),5,'create_script')
        script.on('message',message)
        if late:raise TimeoutError('Late creation; resident runtime not loaded')
        if stop_requested():report['stop_before_setup']=True;raise _StopRequested()
        load_requested=True;_,late=setup(script.load,10,'load')
        if late:raise TimeoutError('Late load; stopping resident runtime')
        if stop_requested():report['stop_after_load']=True;raise _StopRequested()
        if not armed.wait(1):raise RuntimeError('Resident hook did not report armed')
        deadline=time.monotonic()+args.duration if args.duration else None
        while not stopped.is_set() and (deadline is None or time.monotonic()<deadline) and not stop_requested():
            if detached.is_set():break
            try:value=lifecycle.bounded(script.exports_sync.poll,3)
            except Exception as error:
                rpc_error('poll',error);break
            if value.get('type')=='stopped':remember_stop(value);break
            if value.get('result',{}).get('ready'):
                report['result']=value['result']
                if value['result'].get('stats',{}).get('disabled',0)>0:
                    report['errors'].append('Native runtime disabled itself; stopping after a guard/canary fault');break
                if value['result'].get('stats',{}).get('dispatch_limit_reached',0)>0:
                    report['dispatch_limit_reached']=True;break
                if not status('active',True,True,'AutoLoot active'):
                    report['errors'].append('Status publication failed; stopping cooperatively');break
                save()
            stopped.wait(.5)
    except _StopRequested:report['stop_requested']=True
    except KeyboardInterrupt:report['user_interrupt']=True
    except Exception as error:
        report['errors'].append(type(error).__name__+': '+str(error))
    finally:
        if script is not None and load_requested and not detached.is_set():
            status('stopping',True,False,'Stopping cooperatively and waiting for native calls')
            if not detached.is_set():
                try:remember_stop(lifecycle.bounded(script.exports_sync.stop,3))
                except (Exception,KeyboardInterrupt) as error:report['cleanup']['stop_error']=rpc_error('stop',error)
            if 'stop_error' in report['cleanup'] and not detached.is_set():
                report['cleanup']['retained_until_target_exit']=True;save()
                print('stop state unknown: retaining native resources, no forced release',flush=True)
                while not detached.is_set():
                    try:detached.wait(1)
                    except KeyboardInterrupt:print('native resources retained',flush=True)
            while report['cleanup'].get('stop_rpc',{}).get('type')=='stop_deferred' and not detached.is_set():
                report['cleanup']['native_completion_pending']=True;save()
                try:
                    value=lifecycle.bounded(script.exports_sync.poll,3)
                    if value.get('type')=='stopped':remember_stop(value);break
                    detached.wait(.1)
                except (Exception,KeyboardInterrupt) as error:
                    report['cleanup']['completion_wait_note']=rpc_error('completion_poll',error)
                    try:detached.wait(.2)
                    except KeyboardInterrupt:pass
            if not detached.is_set():
                done,outcome=lifecycle.launch(script.unload)
                try:pending=not done.wait(10)
                except KeyboardInterrupt:pending=True
                if pending:
                    rpc_error('unload',TimeoutError('Normal QJS unload pending; retaining host/session'));save()
                    print('unload pending: retaining native code/state until normal completion or target exit',flush=True)
                    while not done.is_set() and not detached.is_set():
                        try:done.wait(1)
                        except KeyboardInterrupt:print('native resources retained; no forced release',flush=True)
                if done.is_set() and 'error' not in outcome:report['cleanup']['script_unloaded']=True
                elif done.is_set():
                    report['cleanup']['unload_error']=rpc_error('unload',outcome['error']);save()
                    while not detached.is_set():
                        try:detached.wait(1)
                        except KeyboardInterrupt:print('failed unload: retaining transport until target exit',flush=True)
        elif script is None or not load_requested:
            report['cleanup']['no_script_execution']=True;report['cleanup']['script_unloaded']=True
        if session is not None and not detached.is_set() and report['cleanup'].get('script_unloaded'):
            try:lifecycle.bounded(session.detach,5);report['cleanup']['session_detached']=True
            except Exception as error:report['cleanup']['detach_error']=rpc_error('detach',error)
        if detached.is_set():report['cleanup']['session_detached']=True
        stop=report['cleanup'].get('stop_rpc',{});result=stop.get('result') or report.get('result') or {}
        report['result']=result;report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        report['ok']=(not report['errors'] and stop.get('restoration_verified') is True and stop.get('detach_done') is True and
                      not stop.get('errors') and not stop.get('cleanup_errors') and report['cleanup'].get('script_unloaded') is True and
                      report['cleanup'].get('session_detached') is True)
        event=report.get('detached_event',{})
        closed=event.get('reason')=='process-terminated' or report.get('game_closed')
        clean_exit=closed and event.get('crash') is None
        if event.get('crash') is not None:report['errors'].append('Target process crashed: '+event['crash'])
        if event.get('reason') not in (None,'application-requested','process-terminated'):
            report['errors'].append('Target disconnected: '+str(event['reason']))
        if report.get('rpc_interruptions') and not clean_exit:
            report['errors'].append('RPC transport interrupted without a confirmed clean target exit')
        if closed:report['ok']=not report['errors'] and clean_exit;report['game_closed']=True
        if report.get('stop_before_setup'):report['ok']=not report['errors']
        report['ok']=report['ok'] and not report['errors']
        phase='game_closed' if closed and report['ok'] else 'stopped' if report['ok'] else 'error'
        status(phase,False,False,'The game is closed' if closed and report['ok'] else 'AutoLoot stopped' if report['ok'] else '; '.join(report['errors']) or 'Incomplete cleanup')
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
    parser.add_argument('--profile',default='1.7.1',help='Profil de la fixture hors jeu; ne permet aucune activation expérimentale')
    parser.add_argument('--trial-181',action='store_true',help='Essai 1.8.1 borné à 30 s et à un cap explicite de 1 à 64 appels; cap0 en diagnostic')
    parser.add_argument('--trial-category',choices=('corpses','ground','dropped','containers'),default=None,help='Catégorie unique de l’essai; corpses par défaut, seule catégorie du diagnostic')
    parser.add_argument('--session',type=Path)
    parser.add_argument('--duration',type=float,default=0)
    parser.add_argument('--pid',type=int)
    parser.add_argument('--launch-token',default=None)
    parser.add_argument('--diagnostic-only',action='store_true',help='Observe nearby classes with all collection routes disabled')
    parser.add_argument('--dropped-items',action='store_true',help='Experimental exact DroppedItem Take1 route')
    parser.add_argument('--containers',action='store_true',help='Experimental exact local Container Take1 route')
    parser.add_argument('--containers-only',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--ground-only',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--ground-items',action='store_true',help='Experimental standard ground Take1 route, in addition to corpses')
    parser.add_argument('--max-dispatches',type=int,default=0,help='Global native dispatch cap;0 means unlimited')
    parser.add_argument('--status',type=Path,default=ROOT/'evidence/autoloot5m/status.json')
    parser.add_argument('--stop-file',type=Path,default=ROOT/'evidence/autoloot5m/stop.request')
    parser.add_argument('--pause-file',type=Path,default=None,help='Optional persistent manual pause; never cleared by this host')
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/autoloot5m/runtime-report.json')
    args=parser.parse_args()
    if args.trial_category is not None and not args.trial_181:parser.error('--trial-category requires --trial-181')
    if args.trial_181 and (args.dummy or args.static_only):parser.error('--trial-181 requires --live or --preflight-only')
    if args.dummy:return dummy(args.profile)
    if args.static_only:
        print(json.dumps({'static_only':True,'process_opened':False,'proof':static_proof()}));return 0
    if not 0<=args.duration<=86400:parser.error('duration must be0..86400s')
    if args.preflight_only:
        config,proof=prepare(args.session,args.duration,args.pid,args.ground_items,args.max_dispatches,args.ground_only,args.containers,args.containers_only,args.dropped_items,args.diagnostic_only,args.trial_181,args.trial_category)
        print(json.dumps({'preflight_ok':True,'frida_attached':False,'output_written':False,'config':config,
                          'core_sha256':proof['query']['core_sha256']}));return 0
    return live(args)


if __name__=='__main__':raise SystemExit(main())
