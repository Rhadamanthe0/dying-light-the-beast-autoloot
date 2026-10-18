 'use strict';
const pid=__OWNED_PID__,coreSource=__CORE_SOURCE__;
if(Process.id!==pid||Frida.version!=='17.24.0'||Script.runtime!=='QJS'||Process.platform!=='windows'||Process.arch!=='x64')throw new Error('Owned fixture required');
const kernel=Process.getModuleByName('kernel32.dll'),address=n=>kernel.getExportByName(n);
const cfg=Memory.alloc(256),bindingCfg=Memory.alloc(256),runtimeConfig=Memory.alloc(128),state=Memory.alloc(32768),fixtureStats=Memory.alloc(128),controls=Memory.alloc(32),tickAddress=Memory.alloc(8);
const fixtureSource=`
#include <glib.h>
extern guint64 cfg[32],runtime_config[16],stats[16];extern volatile gint controls[8];extern gpointer tick_address;
extern void Sleep(guint);extern guint GetCurrentThreadId(void);extern guint64 GetTickCount64(void);extern gboolean QueryPerformanceCounter(gint64*);
extern gpointer GetProcessHeap(void);extern gpointer HeapAlloc(gpointer,guint,gsize);extern gboolean HeapFree(gpointer,guint,gpointer);
typedef guint64(*Tick)(gpointer,guint64,guint64);
typedef struct {gpointer player;guint count,pad;guint64 failures,done,thread_id;} Worker;
static gint load(volatile gint*p){return g_atomic_int_add(p,0);}
static void block(gint point){if(load(controls)==point){g_atomic_int_add(controls+1,1);while(!load(controls+2))Sleep(1);}}
guint64 clock_now(void){return GetTickCount64()+(guint64)load(controls+6);}
gboolean clock_qpc(gint64*out){gboolean okay=QueryPerformanceCounter(out);*out+=(gint64)load(controls+6)*(gint64)runtime_config[10]/1000;return okay;}
void ctor(gpointer ctx,gpointer actor,gint action,guint8 fourth,guint8 fifth){guint i;stats[0]++;
 if((guint64)actor!=cfg[0]+0x1b0||action||fourth||fifth!=1||((guint64)ctx&15))stats[1]++;
 for(i=0;i<48;i++)if(((guint8*)ctx)[i])stats[1]++;
 *(gpointer*)ctx=actor;((guint8*)ctx)[0x18]=0x20;block(1);
 if(load(controls+4)==9)((guint8*)ctx)[48]=0;
 if(load(controls+4)==12)((guint8*)ctx)[0x18]=0x24;
}
gpointer resolve(gpointer pool,guint64 handle){stats[2]++;
 if((guint64)pool!=cfg[16]){stats[3]++;return NULL;}
 if(handle==cfg[13])return(gpointer)cfg[9];if(handle==cfg[27])return(gpointer)cfg[28];stats[3]++;return NULL;
}
gint select(gpointer component,gpointer ctx){guint64 h;stats[4]++;
 if((guint64)ctx!=cfg[14]||((guint64)component!=cfg[9]&&(guint64)component!=cfg[28]))stats[5]++;
 if(!load(controls+5)){h=*(guint64*)(*(guint64*)((guint8*)component+0x598)+0x28);*(guint*)(h+0x239c)=123;}block(2);return load(controls+3);
}
guint8 eligibility(gpointer component,gint action,gpointer ctx){stats[6]++;
 if(action!=1||(guint64)ctx!=cfg[14]||((guint64)component!=cfg[9]&&(guint64)component!=cfg[28]))stats[7]++;
 block(4);return load(controls+4)==2?0:0x81;
}
guint8 dispatch(gpointer player,guint64 handle,gpointer ctx){guint64 component,human,body;stats[8]++;
 if((guint64)player!=cfg[0]||(guint64)ctx!=cfg[14]||*(guint64*)ctx!=cfg[0]+0x1b0||((guint8*)ctx)[0x18]!=0x20)stats[9]++;
 if(handle==cfg[13])component=cfg[9];else if(handle==cfg[27])component=cfg[28];else{stats[9]++;return 0;}
 if(load(controls+5)){
   body=component==cfg[9]?cfg[7]:cfg[26];block(3);
   if(load(controls+4)==10)return 0; /* Internal re-selection changedTake1 toSwap24: vanilla rejects. */
   if(load(controls+4)!=3){if(load(controls+5)==2){*(guint*)(body+0x4d0)=0;*(guint*)(body+0x388)=5;}else *(guint8*)(body+0x4f0)|=1;}stats[15]++;return 1;
 }
 human=*(guint64*)(*(guint64*)(component+0x598)+0x28);body=*(guint64*)(human+0x2558);
 block(3);if(load(controls+4)!=3&&load(controls+4)!=8){*(guint*)(body+0x4d0)=0;*(guint*)(body+0x388)=5;}return 1;
}
guint8 query(gpointer level,gpointer vector,gpointer centre,float radius,gpointer type,guint8 flag,gpointer optional){
 guint64*v=vector,*data;guint n=2,i;float*c=centre;stats[10]++;
 if((guint64)level!=cfg[29]||(guint64)type!=cfg[30]||radius!=5.0f||flag||optional||
    c[0]!=0||c[1]!=0||c[2]!=0||(v[0]&0xffffffffffffULL)!=(guint64)((guint8*)vector+8)||*(guint16*)((guint8*)vector+6)!=0x0101)stats[11]++;
 block(5);if(load(controls+4)==4)Sleep(320);
 if(load(controls+4)==5)n=0;if(load(controls+4)==6)n=18;
 if(n){data=HeapAlloc(GetProcessHeap(),0,n*8);stats[12]++;
   for(i=0;i<n;i++)data[i]=i&1?cfg[26]+0x10:cfg[7]+0x10;
   v[0]=(guint64)data&0xffffffffffffULL;((guint*)vector)[2]=n;((guint*)vector)[3]=n;
 }return 0x81;
}
void destroy(gpointer vector){guint64*v=vector;stats[14]++;
 if(!((guint8*)vector)[7]){if(!HeapFree(GetProcessHeap(),0,(gpointer)(v[0]&0xffffffffffffULL)))stats[11]++;else stats[13]++;}
 v[0]=((guint64)vector+8)&0xffffffffffffULL;*(guint16*)((guint8*)vector+6)=0x0101;block(6);
}
guint64 tick(gpointer player,guint64 value,guint64 depth){
 if(load(controls+5)&&(load(controls+4)==7||load(controls+4)==11)){
   guint k;for(k=0;k<2;k++){
     guint64 body=k?cfg[26]:cfg[7],component=k?cfg[28]:cfg[9],proxy=*(guint64*)(body+0x38);
     guint64 node=*(guint64*)(component+0x78),entity=*(guint64*)(proxy+0x10),handles=*(guint64*)(entity+0x78)&0xffffffffffffULL;
     *(guint64*)(proxy+8)+=1ULL<<44;*(guint64*)(node+8)=*(guint64*)(proxy+8);*(guint64*)(handles+8)=*(guint64*)(proxy+8);
     *(guint8*)(body+0x4f0)&=0xfe;
   }
 }
 if(load(controls+4)==7||load(controls+4)==8){
   /* New full generation each natural tick, same valid allocation slot. */
   cfg[13]+=1ULL<<44;cfg[27]+=1ULL<<44;
   *(guint64*)(cfg[9]+8)=cfg[13];*(guint64*)cfg[19]=cfg[13];
   *(guint64*)(cfg[28]+8)=cfg[27];*(guint64*)cfg[31]=cfg[27];
   *(guint*)(cfg[7]+0x4d0)=2;*(guint*)(cfg[7]+0x388)=1;
   *(guint*)(cfg[26]+0x4d0)=2;*(guint*)(cfg[26]+0x388)=1;stats[15]++;
 }
 return ((guint64)player^value)+0x1234;}
guint worker(gpointer a){Worker*w=a;guint i;w->thread_id=GetCurrentThreadId();
 for(i=0;i<w->count;i++){if(load(controls+7))g_atomic_int_add(controls+6,250);
   if(((Tick)tick_address)(w->player,i,0)!=(((guint64)w->player^i)+0x1234))w->failures++;Sleep(load(controls+7)?1:16);}
 w->done=1;return 0;}
`;
const fixture=new CModule(fixtureSource,{cfg,runtime_config:runtimeConfig,stats:fixtureStats,controls,tick_address:tickAddress,
 Sleep:address('Sleep'),GetCurrentThreadId:address('GetCurrentThreadId'),GetTickCount64:address('GetTickCount64'),
 QueryPerformanceCounter:address('QueryPerformanceCounter'),GetProcessHeap:address('GetProcessHeap'),HeapAlloc:address('HeapAlloc'),HeapFree:address('HeapFree')});
const cm=new CModule(coreSource,{runtime_config:runtimeConfig,cfg:bindingCfg,state,ReadProcessMemory:address('ReadProcessMemory'),
 GetTickCount64:fixture.clock_now,GetCurrentThreadId:address('GetCurrentThreadId'),QueryPerformanceCounter:fixture.clock_qpc,
 context_ctor:fixture.ctor,get_component:fixture.resolve,select_action:fixture.select,can_use:fixture.eligibility,
 player_dispatch:fixture.dispatch,find_radius:fixture.query,vector_destroy:fixture.destroy});
const disable=new NativeFunction(cm.disable,'void',[]),pending=new NativeFunction(cm.pending,'uint',[]),snap=new NativeFunction(cm.snapshot,'uint',['pointer']);
const size=new NativeFunction(cm.state_size,'uint',[])(),snapSize=new NativeFunction(cm.snapshot_size,'uint',[])();
if(size>32768||snapSize!==13312)throw new Error('Unexpected runtime layout');
const snapBuffer=Memory.alloc(snapSize),createThread=new NativeFunction(address('CreateThread'),'pointer',['pointer','size_t','pointer','pointer','uint','pointer']);
const wait=new NativeFunction(address('WaitForSingleObject'),'uint',['pointer','uint']),close=new NativeFunction(address('CloseHandle'),'bool',['pointer']);
const image=Memory.alloc(0x3707000),player=Memory.alloc(0x4000),player2=Memory.alloc(0x4000),game=Memory.alloc(0x200),level=Memory.alloc(0xf00),client=Memory.alloc(0x100);
const pool=Memory.alloc(16),storage=Memory.alloc(0x8000),gameSlot=Memory.alloc(8),entityLevel=Memory.alloc(0x80),levelHost=Memory.alloc(0x700),ilevel=Memory.alloc(8),typeObj=Memory.alloc(8),rtti=Memory.alloc(8);
const vectorBlock=Memory.alloc(64),vector=vectorBlock.add(31).and(ptr('0xfffffffffffffff0')),ctxBlock=Memory.alloc(96),ctx=ctxBlock.add(31).and(ptr('0xfffffffffffffff0'));
const qpfOut=Memory.alloc(8);if(!new NativeFunction(address('QueryPerformanceFrequency'),'bool',['pointer'])(qpfOut))throw new Error('QPF unavailable');
const frequency=qpfOut.readU64().toNumber();const sources=[],matrices=[],groundMeta=[];
function q(a,b){a.writePointer(b);}function n(a,b){a.writeU64(uint64(b.toString()));}
function transform(object,x){const obj=Memory.alloc(0x150),t=Memory.alloc(0x30),page=Memory.alloc(0x90),matrix=Memory.alloc(48),flags=Memory.alloc(1);
 q(object.add(0x18),obj);q(obj.add(0x148),t);q(t.add(0x20),page);t.add(0x28).writeU32(0);
 q(page.add(0x58),matrix);q(page.add(0x70),matrix);q(page.add(0x80),flags);flags.writeU8(4);
 [1,0,0,x,0,1,0,0,0,0,1,0].forEach((v,i)=>matrix.add(i*4).writeFloat(v));matrices.push({object,obj,t,page,matrix,flags});}
transform(player,0);transform(player2,0);
for(let i=0;i<2;i++){const s={body:Memory.alloc(0x620),human:Memory.alloc(0x2870),entity:Memory.alloc(0x90),strategy:Memory.alloc(0x40),manager:Memory.alloc(8),handles:Memory.alloc(16),
 component:storage.add(i*0x4000+0x180),handle:uint64('0x52e1c4f400000018').add(i*0x400)};sources.push(s);transform(s.body,2+i);}
for(let i=0;i<2;i++)groundMeta.push({proxy:storage.add(i*0x4000+0x780),handle:sources[i].handle.add(0x60),node:Memory.alloc(24),table:Memory.alloc(24),records:Memory.alloc(72)});
function initialize(mode){
 state.writeByteArray(new Uint8Array(32768));bindingCfg.writeByteArray(new Uint8Array(256));cfg.writeByteArray(new Uint8Array(256));runtimeConfig.writeByteArray(new Uint8Array(128));fixtureStats.writeByteArray(new Uint8Array(128));controls.writeByteArray(new Uint8Array(32));controls.add(12).writeS32(1);
 q(gameSlot,game);q(game,image.add(0x259fe08));q(game.add(0x138),level);q(level.add(0xec8),client);q(client.add(0x88),client);q(client.add(0x90),player);
 for(const p of [player,player2]){q(p,image.add(0x259c450));q(p.add(0x20),image.add(0x259d100));q(p.add(0x40),entityLevel);}
 q(entityLevel.add(0x48),levelHost);q(levelHost.add(0x6d8),ilevel);q(image.add(0x260ebf8),typeObj);q(typeObj,rtti);q(image.add(0x37069b0),pool);q(pool,storage);n(pool.add(8),0x8000);
 image.add(0x2a6fda0+0x2e8).writePointer(image.add(0x147e190));image.add(0x2a6fda0+0x2f0).writePointer(image.add(0x149dd40));image.add(0x2a6fda0+0x308).writePointer(image.add(0x1492690));
 for(let i=0;i<2;i++){const s=sources[i],page=storage.add(i*0x4000);
 q(s.body,image.add(0x29e84f0));q(s.human,image.add(0x2962618));q(s.component,image.add(0x293c8c0));q(s.strategy,image.add(0x2a6fda0));
 q(s.component.add(0x598),s.strategy);q(s.strategy.add(0x28),s.human);q(s.component.add(0x10),s.entity);q(s.human.add(0x10),s.entity);
 q(s.human.add(0x2550),s.human);q(s.human.add(0x2558),s.body);q(s.body.add(0x5e8),s.body);q(s.body.add(0x5f0),s.human.add(0x70));q(s.human.add(0x5e8),s.manager);
 n(s.handles,s.handle);n(s.entity.add(0x78),s.handles);s.entity.add(0x80).writeU32(1);n(s.component.add(8),s.handle);
 page.writeU32(0x79534243);page.add(4).writeU32(s.handle.shr(28).and(uint64(0x3f)).toNumber());page.add(8).writeU32(s.handle.shr(34).and(uint64(0x3ff)).toNumber());n(page.add(0x20),uint64('0x4000000000'));page.add(0x2e).writeU16(300);n(page.add(0x50),1<<16);
 n(s.component.add(0x448),uint64('0xffffffffffffffff'));n(s.component.add(0x450),0);n(s.component.add(0x458),0);s.human.add(0x2830).writeByteArray(new Uint8Array(48));
 s.body.add(0x4c8).writeByteArray(new Uint8Array(16));s.body.add(0x4d0).writeU32(i===0&&mode==='zero_count'?0:2);s.body.add(0x388).writeU32(1);s.body.add(0x508).writeU32(1);q(s.body.add(0x570),NULL);
 }
 matrices.forEach(m=>m.flags.writeU8(4));matrices[2].matrix.add(12).writeFloat(2);matrices[3].matrix.add(12).writeFloat(3);
 ctx.sub(16).writeByteArray(new Uint8Array(16).fill(0xa5));ctx.writeByteArray(new Uint8Array(48));ctx.add(48).writeByteArray(new Uint8Array(16).fill(0x5a));vector.sub(16).writeByteArray(new Uint8Array(16).fill(0xa5));vector.writeByteArray(new Uint8Array(16));vector.add(16).writeByteArray(new Uint8Array(16).fill(0x5a));
 const s=sources[0],t=sources[1];[player,game,gameSlot,image,level,client,client,s.body,s.human,s.component,s.strategy,s.manager,image.add(0x37069b0),s.handle,ctx,0,pool,storage,s.entity,s.handles,s.handles,1,0,2,1,5000,t.body,t.handle,t.component,ilevel,typeObj,t.handles].forEach((v,i)=>n(cfg.add(i*8),v));
 [player,game,gameSlot,image,level,client,client,image,vector,ctx,frequency,0,0,1].forEach((v,i)=>n(runtimeConfig.add(i*8),v));
 if(mode==='far')matrices[2].matrix.add(12).writeFloat(5.1);if(mode==='near5')matrices[2].matrix.add(12).writeFloat(5);
 if(mode==='dirty')matrices[2].flags.writeU8(6);if(mode==='wrong_handle')n(s.component.add(8),s.handle.add(1));
 if(mode==='forwarding')n(s.component.add(0x450),1);if(mode==='extra')q(s.human.add(0x2858),s.body);
 if(mode==='mode')s.body.add(0x508).writeU32(0);if(mode==='nested')q(s.body.add(0x570),s.body);
 if(mode==='null_manager')q(s.human.add(0x5e8),NULL);if(mode==='wrong_owner')q(s.strategy.add(0x28),t.human);
 if(mode==='eligibility_false')controls.add(16).writeS32(2);if(mode==='no_progress')controls.add(16).writeS32(3);
 if(mode==='slow_query')controls.add(16).writeS32(4);if(mode==='empty')controls.add(16).writeS32(5);if(mode==='pagination')controls.add(16).writeS32(6);
 if(mode==='continuous_arrivals')controls.add(16).writeS32(7);
 if(mode==='cooldown_pressure'){controls.add(16).writeS32(8);controls.add(28).writeS32(1);}
 if(mode==='context_overflow')controls.add(16).writeS32(9);if(mode==='other_action')controls.add(12).writeS32(0x17);
 if(mode==='blocked_query')controls.writeS32(5);if(mode==='blocked_dispatch')controls.writeS32(3);if(mode==='blocked_dtor')controls.writeS32(6);
 if(mode==='bounded_logs'){controls.add(28).writeS32(1);controls.add(12).writeS32(0x17);}
 if(mode==='ambiguous'){n(s.handles.add(8),s.handle);s.entity.add(0x80).writeU32(2);}

 if(mode.startsWith('ground_')||mode.startsWith('container_')){
  controls.add(20).writeS32(1);n(runtimeConfig.add(11*8),1);n(runtimeConfig.add(12*8),1);n(runtimeConfig.add(13*8),0);
  image.add(0x2d326f8+0x128).writePointer(image.add(0x24ec9b6));image.add(0x257b948).writePointer(image.add(0xfba70));image.add(0x27ecee0+8).writePointer(image.add(0x80cb40));
  for(let i=0;i<2;i++){const a=sources[i],m=groundMeta[i],pg=storage.add(i*0x4000);
   q(a.body,image.add(0x29ec228));q(a.body.add(0x10),image.add(0x29ec8f0));q(a.body.add(0x20),image.add(0x29ecbc8));q(a.body.add(0x38),m.proxy);
   q(m.proxy,image.add(0x2d326f8));n(m.proxy.add(8),m.handle);q(m.proxy.add(0x10),a.entity);q(m.proxy.add(0x48),a.body.add(0x20));
   pg.add(0x2e).writeU16(2000);n(pg.add(0x110),1<<16);
   n(a.handles,a.handle);n(a.handles.add(8),m.handle);a.entity.add(0x80).writeU32(2);
   q(a.component.add(0x598),NULL);q(a.component.add(0x70),image.add(0x27ecf30));q(a.component.add(0x78),m.node);
   q(m.node,NULL);n(m.node.add(8),m.handle);q(m.node.add(0x10),a.body.add(0x270));
   q(a.body.add(0x270),image.add(0x27ecee0));q(a.body.add(0x278),m.table);q(a.body.add(0x280),a.body.add(0x268));a.body.add(0x2a0).writeU8(0);a.body.add(0x4f0).writeU8(0);
   n(m.table.add(8),m.records);m.table.add(0x10).writeU32(3);
   [['0x53139e0185c9a12f',0x16e8c20],['0xcbbfaec882b2a3ea',0x16e9040],['0x5f2b7eb72fee8475',0x16e8cd0]].forEach(([guid,rva],j)=>{n(m.records.add(j*24),uint64(guid));q(m.records.add(j*24+8),image.add(rva));m.records.add(j*24+16).writeS32(0x20);});
  }
  if(mode==='ground_swap')controls.add(12).writeS32(24);
  if(mode==='ground_swap_during_dispatch')controls.add(16).writeS32(10);
  if(mode==='ground_forward')sources.forEach(a=>a.body.add(0x2a0).writeU8(1));
  if(mode==='ground_callback')groundMeta.forEach(m=>m.records.add(2*24+8).writePointer(image.add(0x16e8cd1)));
  if(mode==='ground_consumed')sources.forEach(a=>a.body.add(0x4f0).writeU8(1));
  if(mode==='ground_forward_448')sources.forEach(a=>n(a.component.add(0x448),0));
  if(mode==='ground_forward_458')sources.forEach(a=>n(a.component.add(0x458),1));
  if(mode==='ground_blocked_dispatch')controls.writeS32(3);
  if(mode==='ground_continuous'){n(runtimeConfig.add(12*8),0);controls.add(16).writeS32(7);}
  if(mode==='ground_receiver_generation'){n(runtimeConfig.add(12*8),0);controls.add(16).writeS32(11);}
  if(mode==='ground_no_progress'){n(runtimeConfig.add(12*8),0);controls.add(16).writeS32(3);}
  if(mode.startsWith('container_')){
   controls.add(20).writeS32(2);n(runtimeConfig.add(11*8),0);n(runtimeConfig.add(14*8),1);
   image.add(0x29e8448+0x20).writePointer(image.add(0x1185870));
   for(const a of sources){q(a.body,image.add(0x29e6ff8));q(a.body.add(0x10),image.add(0x29e7730));q(a.body.add(0x20),image.add(0x29e7a08));q(a.body.add(0x3d8),image.add(0x29e8448));a.body.add(0x59e).writeU8(0x2f);a.body.add(0x4c8).writeByteArray(new Uint8Array(16));a.body.add(0x4d0).writeU32(3);}
   if(mode==='container_wrong_state')sources.forEach(a=>a.body.add(0x388).writeU32(2));
   if(mode==='container_other_action')controls.add(12).writeS32(7);
   if(mode==='container_context')controls.add(16).writeS32(12);
   if(mode==='container_flag')sources.forEach(a=>a.body.add(0x59e).writeU8(0x27));
   if(mode==='container_mode')sources.forEach(a=>a.body.add(0x508).writeS32(-1));
   if(mode==='container_nested')sources.forEach(a=>q(a.body.add(0x570),a.body));
   if(mode==='container_forward')sources.forEach(a=>n(a.component.add(0x450),1));
   if(mode==='container_iloot')sources.forEach(a=>q(a.body.add(0x3d8),image.add(0x29e8440)));
   if(mode==='container_blocked_dispatch')controls.writeS32(3);
   if(mode==='container_blocked_select')controls.writeS32(2);
   if(mode==='container_no_progress'){n(runtimeConfig.add(12*8),0);controls.add(16).writeS32(3);}
   if(mode==='container_disabled')n(runtimeConfig.add(14*8),0);
   if(mode==='container_complex_layout')sources.forEach(a=>{q(a.body,image.add(0x29ed590));a.body.add(0x4d0).writeU32(0xffffffff);});
  }
 }
}
// Wrapper sets/checks Win64 callee-saved GPR and SIMD canaries and preserves RAX.
const registerFailures=Memory.alloc(4),wrapper=Memory.alloc(Process.pageSize);
Memory.patchCode(wrapper,Process.pageSize,code=>{
  const w=new X86Writer(code,{pc:wrapper}),regs=['rbx','rbp','rsi','rdi','r12','r13','r14','r15'];
  const imm=v=>[v&255,(v>>>8)&255,(v>>>16)&255,(v>>>24)&255];
  const vec=(op,i,off)=>w.putBytes([0xf3,...(i>=8?[0x44]:[]),0x0f,op,0x84|((i&7)<<3),0x24,...imm(off)]);
  const check=label=>{w.putJccShortLabel('je',label,'no-hint');w.putMovRegAddress('r11',registerFailures);w.putBytes([0xf0,0x41,0xff,0x03]);w.putLabel(label);};
  regs.forEach(r=>w.putPushReg(r));w.putSubRegImm('rsp',0xc8);
  for(let i=6;i<=15;i++){vec(0x7f,i,0x20+(i-6)*16);w.putBytes([0x66,...(i>=8?[0x45]:[]),0x0f,0x76,0xc0|((i&7)<<3)|(i&7)]);}
  regs.forEach((r,i)=>w.putMovRegU64(r,0x11111000+i));w.putMovRegAddress('r11',fixture.tick);w.putCallReg('r11');
  regs.forEach((r,i)=>{w.putCmpRegI32(r,0x11111000+i);check('g'+i);});
  for(let i=6;i<=15;i++){w.putBytes([0x66,0x0f,0x76,0xc0]);w.putBytes([0x66,...(i>=8?[0x41]:[]),0x0f,0x74,0xc0|(i&7)]);
    w.putBytes([0x66,0x44,0x0f,0xd7,0xd0]);w.putCmpRegI32('r10d',0xffff);check('v'+i);vec(0x6f,i,0x20+(i-6)*16);}
  w.putAddRegImm('rsp',0xc8);regs.slice().reverse().forEach(r=>w.putPopReg(r));w.putRet();w.flush();w.dispose();
});
q(tickAddress,wrapper);

const original=Array.from(new Uint8Array(fixture.tick.readByteArray(16)));let listener=null,handles=[],workers=[],joined=true;
function allJoined(){if(handles.some(h=>wait(h,0)!==0))return false;handles.forEach(h=>close(h));handles=[];joined=true;return true;}
function snapshot(){const okay=snap(snapBuffer)!==0;return {snapshot_available:okay,values:okay?Array.from({length:50},(_,i)=>snapBuffer.add(i*8).readU64().toString()):[],
 events:okay?Array.from({length:Math.min(snapBuffer.add(13*8).readU64().toNumber(),64)},(_,i)=>Array.from({length:16},(_,j)=>snapBuffer.add((64+i*16+j)*8).readU64().toString())):[],
 cadence:okay?Array.from({length:Math.min(snapBuffer.add(15*8).readU64().toNumber(),64)},(_,i)=>Array.from({length:5},(_,j)=>snapBuffer.add((64+64*16+i*5+j)*8).readU64().toString())):[],
 stats:Array.from({length:16},(_,i)=>fixtureStats.add(i*8).readU64().toNumber()),blocked:controls.add(4).readS32(),
 register_failures:registerFailures.readU32(),event_extra:okay?Array.from({length:64},(_,i)=>Array.from({length:4},(_,j)=>snapBuffer.add((64+64*16+64*5+i*4+j)*8).readU64().toString())):[],body_states:sources.map(s=>({count:s.body.add(0x4d0).readU32(),state:s.body.add(0x388).readU32(),flags:s.body.add(0x4f0).readU8()}))};}
rpc.exports={configure(mode){if(listener||!joined)throw new Error('Must be idle');initialize(mode);registerFailures.writeU32(0);listener=Interceptor.attach(fixture.tick,{onEnter:cm.on_enter,onLeave:cm.on_leave});Interceptor.flush();return {state_size:size,snapshot_size:snapSize};},
 run(count,threads,secondPlayer){joined=false;workers=[];handles=[];for(let i=0;i<threads;i++){const a=Memory.alloc(40);q(a,secondPlayer?player2:player);a.add(8).writeU32(count);workers.push(a);const h=createThread(NULL,0,fixture.worker,a,0,NULL);if(h.isNull())throw new Error('Thread failed');handles.push(h);}return true;},
 respawn(){q(client.add(0x90),player2);n(cfg,player2);sources.forEach(s=>{s.body.add(0x4d0).writeU32(2);s.body.add(0x388).writeU32(1);});return true;},
 poll(){return {joined:allJoined(),...snapshot(),workers:workers.map(a=>({failures:a.add(16).readU64().toNumber(),done:a.add(24).readU64().toNumber()}))};},
 disable(){disable();return true;},release(){controls.add(8).writeS32(1);return true;},
 stop(){disable();if(pending())return {deferred:true,resources_retained:true};if(listener){listener.detach();listener=null;}Interceptor.flush();return {restored:Array.from(new Uint8Array(fixture.tick.readByteArray(16))).every((v,i)=>v===original[i]),joined:allJoined(),resources_retained:true,...snapshot()};}}
