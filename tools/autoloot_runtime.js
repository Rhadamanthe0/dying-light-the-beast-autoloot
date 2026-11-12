'use strict';
// Resident native100ms runtime. No JS executes inside game callbacks.
const config=__QUERY_CONFIG__,coreSource=__QUERY_CORE__;
const rvas=config.rvas;
const INTERVAL_MS=100,RADIUS_METRES=2;
const hold={cfg:null,bindingCfg:null,state:null,vectorBlock:null,contextBlock:null,snapshot:null,module:null,listener:null};
let target=null,original=null,timer=null,stopped=null,pendingStop=null,frequency=0;
let nativeSnapshot=null,nativePending=null,nativeDisable=null;
const errors=[];
function validateExecutionProfile(){
  const trial=config.trial_181;
  const hashes={game:'4f421509f28881c4dd8a744c06d5ccab28017422224809814eeaef127dd075a1',engine:'000fcc064bd512a93cb2eaa6da5f34dcba4e792ba636a897a4630b5637d2c0d4'};
  if(trial===undefined||trial===null){
    const known={'1.7.1.0na':{game:'ddb68c8f87ba2afd0e561b2d1adb9235467c29069fb1cd1619db81e1056378eb',engine:'3dcae152c002f1d549df2ed12c21cc38ddb6b25fd989345f0c413c7442243f1b'},'1.8.1.0na':hashes};
    const expected=Object.prototype.hasOwnProperty.call(known,config.profile_id)?known[config.profile_id]:null;
    if(config.execution_mode!=='resident'||!expected||!config.profile_hashes||
      Object.keys(config.profile_hashes).sort().join(',')!=='engine,game'||
      config.profile_hashes.game!==expected.game||config.profile_hashes.engine!==expected.engine||
      config.game_sha256!==expected.game||!config.engine_module||config.engine_module.sha256!==expected.engine)
      throw new Error('Reviewed profile/hash pair and resident mode required');
    return;
  }
  const keys=['category','dispatch_cap','duration_ms','hashes','kind','mode','profile_id'];
  if(config.execution_mode!=='trial-181'||config.profile_id!=='1.8.1.0na'||
    typeof trial!=='object'||Array.isArray(trial)||Object.keys(trial).sort().join(',')!==keys.join(',')||
    trial.kind!=='bounded_trial_181_v1'||trial.profile_id!==config.profile_id||
    !trial.hashes||Object.keys(trial.hashes).sort().join(',')!=='engine,game'||trial.hashes.game!==hashes.game||trial.hashes.engine!==hashes.engine||
    !config.profile_hashes||Object.keys(config.profile_hashes).sort().join(',')!=='engine,game'||config.profile_hashes.game!==hashes.game||config.profile_hashes.engine!==hashes.engine||
    config.game_sha256!==hashes.game||!config.engine_module||config.engine_module.sha256!==hashes.engine)
    throw new Error('Trial181 contract identity differs');
  if(!Number.isSafeInteger(trial.duration_ms)||trial.duration_ms<1||trial.duration_ms>30000||config.duration_ms!==trial.duration_ms)
    throw new Error('Trial181 contract duration differs');
  if(trial.mode!=='diagnostic-only'&&trial.mode!=='collect')throw new Error('Trial181 contract mode differs');
  if(!Number.isSafeInteger(trial.dispatch_cap)||(trial.mode==='diagnostic-only'?trial.dispatch_cap!==0:trial.dispatch_cap<1||trial.dispatch_cap>64))
    throw new Error('Trial181 contract dispatch cap differs');
  const routes={corpses:['0','1','1','0','0'],ground:['1','1','0','0','0'],dropped:['0','1','0','0','1'],containers:['0','1','0','1','0']};
  if(typeof trial.category!=='string'||!Object.prototype.hasOwnProperty.call(routes,trial.category)||(trial.mode==='diagnostic-only'&&trial.category!=='corpses'))
    throw new Error('Trial181 contract category differs');
  const values=trial.mode==='diagnostic-only'?['0','0','0','0','0']:routes[trial.category];
  values[1]=String(trial.dispatch_cap);
  if(!Array.isArray(config.values)||config.values.length!==16||!values.every((value,index)=>config.values[11+index]===value))
    throw new Error('Trial181 contract routes or dispatch cap differ');
}
function bytes(p,n){return Array.from(new Uint8Array(p.readByteArray(n)));}
function hex(p,n){return bytes(p,n).map(v=>v.toString(16).padStart(2,'0')).join('');}
function normal(p){return p.replace(/\//g,'\\').toLowerCase();}
function identity(module){return {name:module.name,path:module.path,base:module.base.toString(),size:module.size};}
function moduleMatches(module,expected){return module.name.toLowerCase()===expected.name.toLowerCase() &&
  normal(module.path)===normal(expected.path) && module.base.toString()===expected.base && module.size===expected.size;}
function snapshot(){
  if(!nativeSnapshot)return {ready:false};
  if(!nativeSnapshot(hold.snapshot))return {ready:false,busy:true};
  const q=(index)=>hold.snapshot.add(index*8).readU64(),n=index=>q(index).toNumber();
  const names=['cycles','spatial_queries','vector_destructors','native_dispatches','completed_count0_state5','refused',
    'budget_stops','query_ticks','total_ticks','minimum_start_interval_ms','maximum_start_interval_ms','next_due_ms',
    'next_offset','events_total','event_cursor','cadence_cursor','last_native_count','last_cycle_rpm','last_cycle_status',
    'last_guard_reason','thread_id','last_processed','last_copied','disabled','inflight_diagnostic_only','selected_diagnostic_only',
    'local_admissions','foreign_due_entries','contended_entries','last_query_al','dispatch_inflight','interval_ms',
    'page_size','rpm_limit','budget_ms','cooldown_pressure','minimum_start_interval_qpc','maximum_start_interval_qpc','next_due_qpc','native_qpc_frequency','ground_items_enabled','max_dispatches','dispatch_limit_reached','ground_dispatches','ground_source_changed','ground_refused','containers_enabled','container_dispatches','container_completed_count0_state5','container_refused','dropped_items_enabled','dropped_dispatches','dropped_source_changed','dropped_refused','bag_dispatches','bag_completed_count0_state5','bag_refused','resource_dispatches','resource_completed_count0_state5','resource_refused'];
  const stats=Object.fromEntries(names.map((name,i)=>[name,n(i)]));
  const events=Array.from({length:Math.min(stats.events_total,64)},(_,j)=>{
    const i=(stats.event_cursor-Math.min(stats.events_total,64)+j)%64,a=64+i*16,x=64+64*16+64*5+i*4;
    return {source_kind:({0:'corpse',1:'ground_item',2:'container',3:'dropped_item',4:'loot_bag',5:'resource_container'})[n(x)]||'unknown',item_flags_before:n(x+1),item_flags_after:n(x+2),item_invalidation_bits:n(x+3),cycle:n(a),time_ms:n(a+1),body:'0x'+q(a+2).toString(16),human:'0x'+q(a+3).toString(16),
      handle:'0x'+q(a+4).toString(16),status:n(a+5),reason:n(a+6),before_count:n(a+7),post_count:n(a+8),post_state:n(a+9),
      action_id:q(a+10).toString(),eligibility_al:n(a+11),dispatch_return_al_diagnostic:n(a+12),rpm_reads:n(a+13),
      elapsed_ms:n(a+14)/frequency*1000,distance_squared_metres:n(a+15)/1000000};});
  const cadence=Array.from({length:Math.min(stats.cadence_cursor,64)},(_,j)=>{
    const i=(stats.cadence_cursor-Math.min(stats.cadence_cursor,64)+j)%64,a=64+64*16+i*5;
    return {cycle:n(a),started_ms:n(a+1),ended_ms:n(a+2),elapsed_ms:n(a+3)/frequency*1000,started_qpc:q(a+4).toString()};});
  const candidate_diagnostics=Array.from({length:16},(_,i)=>{
    const a=64+64*16+64*5+64*4+i*6,vt=q(a+1);
    return {body:'0x'+q(a).toString(16),vtable:'0x'+vt.toString(16),
      vtable_rva:vt.compare(uint64(config.module_base))>=0&&vt.compare(uint64(config.module_base).add(config.module_size))<0?'0x'+vt.sub(uint64(config.module_base)).toString(16):null,
      reason:n(a+2),cycle:n(a+3),cycle_started_ms:n(a+4),stage:n(a+5)===0?'unsupported_or_disabled_class':'bind_refused'};
  }).filter(row=>row.vtable!=='0x0');
  return {ready:true,stats,events,cadence,candidate_diagnostics,candidate_observations:n(62),candidate_distinct_samples:n(63),qpc_frequency:frequency,helper_observation_available:false,
    inventory_credit_proven:false,resources_retained_until_normal_unload:true};
}
function stop(reason){
  if(stopped)return stopped;
  if(timer!==null)clearTimeout(timer);
  const cleanupErrors=[];
  try{if(nativeDisable)nativeDisable();}catch(e){cleanupErrors.push('disable: '+e);}
  // Keep the hook until any claimed operation has published its post result.
  // This also covers the race between the last stop check and native query.
  if(nativePending&&nativePending()!==0){
    pendingStop=reason;return {type:'stop_deferred',reason,native_operation_pending:true,resources_retained:true};
  }
  let detached=hold.listener===null;
  try{if(hold.listener){hold.listener.detach();detached=true;}Interceptor.flush();}catch(e){cleanupErrors.push('detach: '+e);}
  let restoration=null,result=null;
  try{if(target){const observed=hex(target,16);restoration={expected:original,observed,restored:observed===original};}}
  catch(e){cleanupErrors.push('restoration: '+e);}
  try{result=snapshot();}catch(e){cleanupErrors.push('snapshot: '+e);}
  stopped={type:'stopped',reason,result,detach_done:detached,restoration,
    restoration_verified:!!restoration&&restoration.restored,errors:errors.slice(),cleanup_errors:cleanupErrors,
    resources_retained_until_normal_unload:true,inflight_is_not_quiescence_proof:true};
  send(stopped);return stopped;
}
rpc.exports={poll(){if(stopped)return stopped;if(pendingStop&&nativePending()===0)return stop(pendingStop);return {type:'poll',result:snapshot()};},
  stop(){return stop('host_stop');}};
try{
  if(Frida.version!=='17.24.0'||Script.runtime!=='QJS'||Process.arch!=='x64'||Process.platform!=='windows'||
    Process.pointerSize!==8||Process.id!==config.pid||config.duration_ms<0||config.duration_ms>86400000||
    config.interval_ms!==INTERVAL_MS||config.radius_metres!==RADIUS_METRES||config.phase!=='player-update')throw new Error('Reviewed runtime/one-shot identity required');
  validateExecutionProfile();
  const kernel=Process.getModuleByName('kernel32.dll'),address=n=>kernel.getExportByName(n);
  const times=Memory.alloc(32),getTimes=new NativeFunction(address('GetProcessTimes'),'bool',Array(5).fill('pointer'));
  if(!getTimes(ptr('0xffffffffffffffff'),times,times.add(8),times.add(16),times.add(24))||
    times.readU64().toString()!==config.process_creation_time_100ns)throw new Error('Process creation changed');
  const exe=Process.getModuleByName(config.executable.name);
  const actualExe=new NativeFunction(address('GetModuleHandleW'),'pointer',['pointer'])(NULL);
  if(!moduleMatches(exe,config.executable)||exe.name.toLowerCase()!=='dyinglightgame_thebeast_x64_rwdi.exe'||
    !actualExe.equals(exe.base))throw new Error('Exact Windows executable mismatch: '+JSON.stringify(identity(exe)));
  const game=Process.getModuleByName(config.module_name),engine=Process.getModuleByName(config.engine_module.name);
  if(!moduleMatches(game,{name:config.module_name,path:config.module_path,base:config.module_base,size:config.module_size})||
    !moduleMatches(engine,config.engine_module))throw new Error('Exact game/engine module mismatch');
  for(const guard of config.prologues){const module=guard.module==='engine'?engine:game;
    if(!Number.isSafeInteger(guard.rva)||guard.rva<0||guard.rva+guard.hex.length/2>module.size||
      hex(module.base.add(guard.rva),guard.hex.length/2)!==guard.hex)throw new Error('Code guard mismatch: '+guard.name);}
  const update=config.prologues.filter(g=>g.module!=='engine'&&g.rva===rvas.GAME_PLAYER_UPDATE);
  if(update.length!==1||update[0].hex!=='40534883ec4080b9003c000000488d81')throw new Error('Exact PlayerUpdate guard required');
  target=game.base.add(rvas.GAME_PLAYER_UPDATE);original=update[0].hex;
  const player=ptr(config.player_instance),localGame=ptr(config.game_instance);
  if(!player.readPointer().equals(game.base.add(rvas.GAME_PLAYER_PRIMARY))||!localGame.readPointer().equals(game.base.add(rvas.GAME_PRIMARY)))
    throw new Error('Current Player/Game identity changed');
  const qpfOut=Memory.alloc(8),qpf=new NativeFunction(address('QueryPerformanceFrequency'),'bool',['pointer']);
  if(!qpf(qpfOut)||qpfOut.readS64().toNumber()<=0)throw new Error('QPC frequency unavailable');
  frequency=qpfOut.readS64().toNumber();
  const now=new NativeFunction(address('GetTickCount64'),'uint64',[])();
  const windowMs=config.duration_ms;
  if(!Number.isSafeInteger(windowMs)||windowMs<0)throw new Error('Spatial window invalid');
  hold.cfg=Memory.alloc(256);hold.cfg.writeByteArray(new Uint8Array(256));
  hold.bindingCfg=Memory.alloc(256);hold.bindingCfg.writeByteArray(new Uint8Array(256));
  hold.state=Memory.alloc(32768);hold.state.writeByteArray(new Uint8Array(32768));
  hold.vectorBlock=Memory.alloc(64);
  const vector=hold.vectorBlock.add(31).and(ptr('0xfffffffffffffff0'));
  vector.sub(16).writeByteArray(new Uint8Array(16).fill(0xa5));vector.writeByteArray(new Uint8Array(16));
  vector.add(16).writeByteArray(new Uint8Array(16).fill(0x5a));
  hold.contextBlock=Memory.alloc(96);
  const ctx=hold.contextBlock.add(31).and(ptr('0xfffffffffffffff0'));
  ctx.sub(16).writeByteArray(new Uint8Array(16).fill(0xa5));ctx.writeByteArray(new Uint8Array(48));ctx.add(48).writeByteArray(new Uint8Array(16).fill(0x5a));
  if(config.values.length!==16)throw new Error('Exact immutable native runtime config required');
  config.values.forEach((v,i)=>hold.cfg.add(i*8).writeU64(uint64(v)));
  hold.cfg.add(8*8).writePointer(vector);hold.cfg.add(9*8).writePointer(ctx);hold.cfg.add(10*8).writeU64(uint64(frequency));
  hold.module=new CModule(coreSource,{runtime_config:hold.cfg,cfg:hold.bindingCfg,state:hold.state,
    ReadProcessMemory:address('ReadProcessMemory'),GetTickCount64:address('GetTickCount64'),
    GetCurrentThreadId:address('GetCurrentThreadId'),QueryPerformanceCounter:address('QueryPerformanceCounter'),
    find_radius:engine.base.add(rvas.ENGINE_FIND_RADIUS),vector_destroy:game.base.add(rvas.GAME_VECTOR_DESTRUCTOR),
    context_ctor:game.base.add(rvas.GAME_CONTEXT_CTOR),get_component:engine.base.add(rvas.ENGINE_GET_COMPONENT),
    select_action:game.base.add(rvas.GAME_GET_ACTION),can_use:game.base.add(rvas.GAME_CAN_USE),player_dispatch:game.base.add(rvas.GAME_PLAYER_DISPATCH)});
  const cm=hold.module,stateSize=new NativeFunction(cm.state_size,'uint',[])();
  const snapshotSize=new NativeFunction(cm.snapshot_size,'uint',[])();
  if(stateSize>32768||snapshotSize!==14080)throw new Error('Native runtime layout mismatch');
  hold.snapshot=Memory.alloc(snapshotSize);hold.snapshot.writeByteArray(new Uint8Array(snapshotSize));
  nativeSnapshot=new NativeFunction(cm.snapshot,'uint',['pointer']);nativePending=new NativeFunction(cm.pending,'uint',[]);
  nativeDisable=new NativeFunction(cm.disable,'void',[]);
  hold.listener=Interceptor.attach(target,{onEnter:cm.on_enter,onLeave:cm.on_leave});Interceptor.flush();
  if(windowMs>0)timer=setTimeout(()=>stop('duration_limit'),windowMs);
  send({type:'armed',mode:'resident_native_autoloot',pid:Process.id,target:target.toString(),
    interval_ms:INTERVAL_MS,radius_metres:RADIUS_METRES,page_size:8,budget_ms:8,rpm_limit:4096,
    native_state_bytes:stateSize,duration_ms:config.duration_ms,runtime:Script.runtime});
}catch(error){errors.push(String(error.stack||error));stop('preflight_or_setup_failure');}
