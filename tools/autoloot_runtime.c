/* Resident native collector, radius 2 metres, cadence 100 milliseconds. No JavaScript in game callbacks.
 * All native calls finish normally; stop/budget checks occur BETWEEN calls.
 * Fixed page8, RPM4096, event/cadence rings64; no unbounded owned storage. */
#include <gum/guminterceptor.h>
#include <glib.h>
extern gboolean ReadProcessMemory(gpointer,gconstpointer,gpointer,gsize,gsize*);
extern guint64 GetTickCount64(void);
extern guint GetCurrentThreadId(void);
extern gboolean QueryPerformanceCounter(gint64*);
extern guint8 find_radius(gpointer,gpointer,gpointer,float,gpointer,guint8,gpointer);
extern void vector_destroy(gpointer);
extern void context_ctor(gpointer,gpointer,gint,guint8,guint8);
extern gpointer get_component(gpointer,guint64);
extern gint select_action(gpointer,gpointer);
extern guint8 can_use(gpointer,gint,gpointer);
extern guint8 player_dispatch(gpointer,guint64,gpointer);
extern guint64 runtime_config[16];
/* Writable storage is external: CModule's own data pages are read-only. */
extern guint64 cfg[32];
enum { COLLECTION_INTERVAL_MS=100,COLLECTION_RADIUS_MM=2000,COLLECTION_BUDGET_MS=8 };
#define COLLECTION_RADIUS_METRES 2.0f
#define COLLECTION_RADIUS_SQUARED (COLLECTION_RADIUS_METRES*COLLECTION_RADIUS_METRES)
static guint64 interval_ticks(void){return (runtime_config[10]*COLLECTION_INTERVAL_MS+999)/1000;}
enum {PLAYER,GAME,GAME_SLOT,BASE,LEVEL,CLIENT,GATE,BODY,HUMAN,COMPONENT,STRATEGY,MANAGER,
POOL_SLOT,HANDLE,CONTEXT,DEADLINE,POOL,STORAGE,ENTITY,VECTOR_DATA,VECTOR_PACKED,VECTOR_COUNT,
COMPONENT_INDEX,EXPECTED_COUNT,EXPECTED_STATE,RADIUS_MM,SOURCE_KIND,RECEIVER_HANDLE,PROXY,SENDER_NODE,RECEIVER_CALLBACK,RECEIVER_TABLE};
typedef struct {guint count,body_state,cache;float player[3],body[3];guint64 manager,component,strategy,human,body_pointer,control_human,control_body;} Witness;
typedef struct {guint valid,count,body_state,ground_flags,invalidated;} Post;
typedef struct {guint64 body,human,handle,until,receiver_handle;guint failed;} Cooldown;
typedef struct {
  volatile gint disabled,gate,inflight,selected,matching,ignored,contended;
  guint reason,reads,take_mode,status,post_phase;guint64 nested_container;
  guint64 next_due,cycle_start,next_offset,cycles,queries,dtors,dispatches,completed,refused,budget_stops;
  guint64 query_ticks,total_ticks,last_start,minimum_interval,maximum_interval,last_native_count;
  guint64 events_total,event_cursor,cadence_cursor,cooldown_cursor;
  guint64 events[64][16],cadence[64][5];Cooldown cooldowns[64];
  guint64 dispatch_inflight,thread_id,last_cycle_reads,query_al,last_processed,last_copied,cooldown_pressure;
  guint64 next_due_qpc,last_start_qpc,minimum_interval_qpc,maximum_interval_qpc;
  guint64 cycle_start_qpc;
  guint64 limit_reached,ground_dispatches,ground_completed,ground_refused;
  guint64 event_extra[64][4];
  guint64 container_dispatches,container_completed,container_refused;
} State;
extern State state;
typedef struct {gpointer player;} Invocation;
static gint atomic_get(volatile gint *p) { return g_atomic_int_add(p, 0); }
static gpointer p(guint which) { return (gpointer)cfg[which]; }
static void copy(gpointer dst, gconstpointer src, guint n) {
  guint i; for (i=0;i<n;i++) ((guint8 *)dst)[i]=((const guint8 *)src)[i];
}
static gboolean budget(void);
static gboolean rpm(guint64 address, gpointer out, guint size) {
  gsize got=0;
  if(!state.post_phase&&budget()){state.reason=102;return FALSE;}
  if (state.reads>=4096 || size==0 || size>256 || address<0x10000 ||
      address+size<address || address+size>0x7fffffff0000ULL) { state.reason=100; return FALSE; }
  state.reads++;
  if (!ReadProcessMemory((gpointer)-1,(gpointer)address,out,size,&got) || got!=size) {
    state.reason=101; return FALSE;
  }
  return TRUE;
}
static gboolean q(guint64 address, guint64 *out) { return rpm(address,out,8); }
static guint64 u64(const guint8 *b) { guint64 v; copy(&v,b,8); return v; }
static guint u32(const guint8 *b) { guint v; copy(&v,b,4); return v; }
static gboolean is_type(guint64 object, guint rva) {
  guint64 vt; return q(object,&vt) && vt==cfg[BASE]+rva;
}
static gboolean position(guint64 object, float *xyz) {
  guint64 a,b,page,arrays[6]; guint8 part[16], matrix[48],flags; guint slot,i;
  if (!q(object+0x18,&a) || !q(a+0x148,&b) || !rpm(b+0x20,part,12)) return FALSE;
  page=u64(part); slot=u32(part+8)&0xfff;
  if (!rpm(page+0x58,arrays,48) || !rpm(arrays[5]+slot,&flags,1) || (flags&2) ||
      !rpm(arrays[3]+48*slot,matrix,48)) return FALSE;
  for (i=0;i<12;i++) {
    guint bits=u32(matrix+i*4); float f;
    copy(&f,&bits,4);
    if ((bits&0x7f800000)==0x7f800000 || f < -10000000.0 || f > 10000000.0) return FALSE;
  }
  for(i=0;i<3;i++) copy(&xyz[i],matrix+12+i*16,4);
  return TRUE;
}
static gboolean pool_guard(void) {
  guint64 pool, block[2], metadata, bitmap, stored, product, value;
  guint offset=(guint)(cfg[HANDLE]<<4), page_offset=offset&0xffffc000;
  guint delta=((offset&0x3fff)-0x70), shift,slot,count;
  guint64 page; guint8 header[48];
  if (!q(cfg[POOL_SLOT],&pool) || pool!=cfg[POOL] || !rpm(pool,block,16) ||
      block[0]!=cfg[STORAGE] || offset>=block[1]) return FALSE;
  page=block[0]+page_offset;
  if (!rpm(page,header,48) || u32(header)!=0x79534243 ||
      u32(header+4)!=((cfg[HANDLE]>>28)&0x3f) || u32(header+8)!=((cfg[HANDLE]>>34)&0x3ff)) return FALSE;
  metadata=u64(header+0x20); shift=(guint)(metadata>>32);
  product=(guint64)(guint)metadata*delta;
  value=(product>>32)+(shift>=64 ? delta : 0);
  slot=(guint)(value>>(shift&63)); count=header[0x2e]|(header[0x2f]<<8);
  if (slot>=count || !q(page+0x30+(slot>>6)*8,&bitmap) || !(bitmap&(1ULL<<(slot&63))) ||
      !q(cfg[COMPONENT]+8,&stored) || stored!=cfg[HANDLE]) return FALSE;
  return cfg[COMPONENT]==block[0]+offset;
}
#define QEQ(address,value) do { if(!q((address),&v) || v!=(guint64)(value)) return FALSE; } while(0)
static gboolean guard_body(Witness *w) {
  guint64 v,body_control,human_control; guint8 bytes[48], packed[16]; guint count,i; float d,dist=0;
  state.reason=1;
  QEQ(cfg[GAME_SLOT],cfg[GAME]);
  if (!is_type(cfg[GAME],0x259fe08) || !is_type(cfg[PLAYER],0x259c450)) return FALSE;
  QEQ(cfg[GAME]+0x138,cfg[LEVEL]); QEQ(cfg[LEVEL]+0xec8,cfg[CLIENT]);
  QEQ(cfg[CLIENT]+0x88,cfg[GATE]); QEQ(cfg[CLIENT]+0x90,cfg[PLAYER]);
  state.reason=2;
  if (!is_type(cfg[BODY],0x29e84f0) || !is_type(cfg[HUMAN],0x2962618) ||
      !is_type(cfg[COMPONENT],0x293c8c0) || !is_type(cfg[STRATEGY],0x2a6fda0) || !pool_guard()) return FALSE;
  QEQ(cfg[COMPONENT]+0x598,cfg[STRATEGY]); QEQ(cfg[STRATEGY]+0x28,cfg[HUMAN]);
  QEQ(cfg[HUMAN]+0x10,cfg[ENTITY]); QEQ(cfg[COMPONENT]+0x10,cfg[ENTITY]);
  if (!rpm(cfg[BASE]+0x2a6fda0+0x2e8,bytes,40) || u64(bytes)!=cfg[BASE]+0x147e190 ||
      u64(bytes+8)!=cfg[BASE]+0x149dd40 || u64(bytes+32)!=cfg[BASE]+0x1492690) return FALSE;
  state.reason=3;
  if (!q(cfg[HUMAN]+0x2550,&human_control) || !human_control ||
      !q(cfg[BODY]+0x5e8,&body_control) || !body_control) return FALSE;
  QEQ(cfg[HUMAN]+0x2558,cfg[BODY]); QEQ(cfg[BODY]+0x5f0,cfg[HUMAN]+0x70);
  if (!cfg[MANAGER]) return FALSE;
  QEQ(cfg[HUMAN]+0x5e8,cfg[MANAGER]);
  if (!rpm(cfg[ENTITY]+0x78,packed,16) || u64(packed)!=cfg[VECTOR_PACKED]) return FALSE;
  count=packed[7] ? packed[7]-1 : u32(packed+8);
  if (count!=cfg[VECTOR_COUNT] || count==0 || count>128 || cfg[COMPONENT_INDEX]>=count ||
      (u64(packed)&0xffffffffffffULL)!=cfg[VECTOR_DATA]) return FALSE;
  QEQ(cfg[VECTOR_DATA]+cfg[COMPONENT_INDEX]*8,cfg[HANDLE]);
  state.reason=4;
  if (!rpm(cfg[COMPONENT]+0x448,bytes,24) || u64(bytes)!=~0ULL || u64(bytes+8)!=0 || u64(bytes+16)!=0) return FALSE;
  if (!rpm(cfg[HUMAN]+0x2830,bytes,48) || u32(bytes)!=0 ||
      (bytes[15] ? bytes[15]-1 : u32(bytes+16))!=0 || u64(bytes+32)!=0 || u64(bytes+40)!=0) return FALSE;
  state.reason=5;
  if (!rpm(cfg[BODY]+0x4c8,bytes,16)) return FALSE;
  count=bytes[7] ? bytes[7]-1 : u32(bytes+8);
  if (count>512 || count!=cfg[EXPECTED_COUNT] || !rpm(cfg[BODY]+0x388,&w->body_state,4) ||
      w->body_state!=1 || w->body_state!=cfg[EXPECTED_STATE]) return FALSE;
  if(!rpm(cfg[BODY]+0x508,&state.take_mode,4) || state.take_mode!=1 ||
     !q(cfg[BODY]+0x570,&state.nested_container) || state.nested_container!=0) return FALSE;
  state.reason=6;
  if (!position(cfg[PLAYER],w->player) || !position(cfg[BODY],w->body)) return FALSE;
  for(i=0;i<3;i++) {d=w->player[i]-w->body[i]; dist+=d*d;}
  if (cfg[RADIUS_MM]!=COLLECTION_RADIUS_MM || dist>COLLECTION_RADIUS_SQUARED) return FALSE;
  if (!rpm(cfg[HUMAN]+0x239c,&w->cache,4)) return FALSE;
  w->count=count; w->manager=cfg[MANAGER]; w->component=cfg[COMPONENT];
  w->strategy=cfg[STRATEGY]; w->human=cfg[HUMAN]; w->body_pointer=cfg[BODY];
  w->control_human=human_control; w->control_body=body_control;
  state.reason=0; return TRUE;
}
static gboolean canaries(void) {
  guint i; guint8 *ctx=p(CONTEXT);
  if ((cfg[CONTEXT]&15)!=0) return FALSE;
  for(i=0;i<16;i++) if(ctx[-16+(gint)i]!=0xa5 || ctx[48+i]!=0x5a) return FALSE;
  return TRUE;
}

static gboolean stopped(void){return atomic_get(&state.disabled)!=0;}
static gboolean budget(void){guint64 now;QueryPerformanceCounter((gint64*)&now);
  return now-state.cycle_start_qpc>=(runtime_config[10]*COLLECTION_BUDGET_MS+999)/1000 || state.reads>=4096;}
static gboolean checkpoint(void){return !stopped()&&!state.limit_reached&&!budget()&&atomic_get(&state.inflight)==1;}
static gboolean local_guard(void){guint64 v;
  QEQ(cfg[GAME_SLOT],cfg[GAME]);
  if(!is_type(cfg[PLAYER],0x259c450)||!is_type(cfg[GAME],0x259fe08))return FALSE;
  QEQ(cfg[PLAYER]+0x20,cfg[BASE]+0x259d100);
  QEQ(cfg[GAME]+0x138,cfg[LEVEL]);QEQ(cfg[LEVEL]+0xec8,cfg[CLIENT]);
  QEQ(cfg[CLIENT]+0x88,cfg[GATE]);QEQ(cfg[CLIENT]+0x90,cfg[PLAYER]);return TRUE;
}
static gboolean bind_body(guint64 body){
  guint64 reciprocal,v,poolwords[2],packed,handle,component,strategy,owner,found=0;
  guint count,i,offset;guint8 vector[16],contents[16];
  cfg[SOURCE_KIND]=0;cfg[BODY]=body;cfg[HUMAN]=cfg[HANDLE]=cfg[COMPONENT]=0;
  state.reason=20;
  if(!is_type(body,0x29e84f0)||!q(body+0x5f0,&reciprocal)||reciprocal<0x10070)return FALSE;
  cfg[HUMAN]=reciprocal-0x70;
  if(!is_type(cfg[HUMAN],0x2962618)||!q(cfg[HUMAN]+0x10,&cfg[ENTITY])||
     !rpm(cfg[ENTITY]+0x78,vector,16)||!q(cfg[POOL_SLOT],&cfg[POOL])||!rpm(cfg[POOL],poolwords,16))return FALSE;
  cfg[STORAGE]=poolwords[0];packed=u64(vector);count=vector[7]?vector[7]-1:u32(vector+8);
  if(!count||count>128)return FALSE;
  cfg[VECTOR_PACKED]=packed;cfg[VECTOR_DATA]=packed&0xffffffffffffULL;cfg[VECTOR_COUNT]=count;
  for(i=0;i<count;i++){
    if(!checkpoint()){state.reason=21;return FALSE;}
    if(!q(cfg[VECTOR_DATA]+8*i,&handle))return FALSE;
    offset=(guint)(handle<<4);
    if(offset>=poolwords[1]||offset<0x70)continue;
    component=cfg[STORAGE]+offset;
    if(!q(component,&v))return FALSE;
    if(v!=cfg[BASE]+0x293c8c0)continue;
    if(!q(component+0x598,&strategy)||!is_type(strategy,0x2a6fda0)||!q(strategy+0x28,&owner))return FALSE;
    if(owner!=cfg[HUMAN])continue;
    if(found++) {state.reason=22;return FALSE;} /* Ambiguous exact owner: fail closed. */
    cfg[HANDLE]=handle;cfg[COMPONENT]=component;cfg[STRATEGY]=strategy;cfg[COMPONENT_INDEX]=i;
  }
  if(found!=1||!q(cfg[HUMAN]+0x5e8,&cfg[MANAGER])||!cfg[MANAGER]||!rpm(body+0x4c8,contents,16))return FALSE;
  cfg[EXPECTED_COUNT]=contents[7]?contents[7]-1:u32(contents+8);cfg[EXPECTED_STATE]=1;
  if(cfg[EXPECTED_COUNT]>512)return FALSE;
  return pool_guard();
}

static gboolean pool_pair(guint64 component,guint64 handle){gboolean okay;guint64 c=cfg[COMPONENT],h=cfg[HANDLE];
  cfg[COMPONENT]=component;cfg[HANDLE]=handle;okay=pool_guard();cfg[COMPONENT]=c;cfg[HANDLE]=h;return okay;}
static gboolean item_callbacks(void){
  guint8 b[192],header[16];guint count,i,j,mask=0,seen=0;guint64 data,guid,fn;gint delta;
  if(!rpm(cfg[RECEIVER_TABLE]+8,header,16))return FALSE;
  count=header[7]?header[7]-1:u32(header+8);data=u64(header)&0xffffffffffffULL;
  if(count>128)return FALSE;
  for(i=0;i<count;i+=8){guint n=count-i<8?count-i:8;if(!rpm(data+24*i,b,n*24))return FALSE;
    for(j=0;j<n;j++){guint bit=0;guint rva=0;guid=u64(b+24*j);fn=u64(b+24*j+8);copy(&delta,b+24*j+16,4);
      if(guid==0x53139e0185c9a12fULL){bit=1;rva=0x16e8c20;}
      if(guid==0xcbbfaec882b2a3eaULL){bit=2;rva=0x16e9040;}
      if(guid==0x5f2b7eb72fee8475ULL){bit=4;rva=0x16e8cd0;}
      if(bit){if((mask&bit)||fn!=cfg[BASE]+rva||delta!=0x20)return FALSE;mask|=bit;seen++;}
    }
  }
  return mask==7&&seen==3;
}
static gboolean guard_cbs(Witness*w){
  guint64 v;guint8 vector[16],flag,forwarding[24];guint count,i,primary,control,igs;float d,dist=0;
  switch(cfg[SOURCE_KIND]){case 1:primary=0x29ec228;control=0x29ec8f0;igs=0x29ecbc8;break;
    case 2:primary=0x29e6ff8;control=0x29e7730;igs=0x29e7a08;break;default:return FALSE;}
  state.reason=40;
  if(!local_guard()||!is_type(cfg[BODY],primary)||!is_type(cfg[PROXY],0x2d326f8)||
     !is_type(cfg[COMPONENT],0x293c8c0)||!pool_guard()||!pool_pair(cfg[PROXY],cfg[RECEIVER_HANDLE]))return FALSE;
  QEQ(cfg[BODY]+0x10,cfg[BASE]+control);QEQ(cfg[BODY]+0x20,cfg[BASE]+igs);
  QEQ(cfg[BODY]+0x38,cfg[PROXY]);QEQ(cfg[PROXY]+0x10,cfg[ENTITY]);QEQ(cfg[PROXY]+0x48,cfg[BODY]+0x20);
  QEQ(cfg[BASE]+0x2d326f8+0x128,cfg[BASE]+0x24ec9b6);QEQ(cfg[BASE]+0x257b948,runtime_config[7]+0xfba70);
  QEQ(cfg[COMPONENT]+0x10,cfg[ENTITY]);QEQ(cfg[COMPONENT]+0x598,0);
  if(!rpm(cfg[COMPONENT]+0x448,forwarding,24)||u64(forwarding)!=~0ULL||u64(forwarding+8)||u64(forwarding+16))return FALSE;
  if(!rpm(cfg[ENTITY]+0x78,vector,16)||u64(vector)!=cfg[VECTOR_PACKED])return FALSE;
  count=vector[7]?vector[7]-1:u32(vector+8);
  if(count!=cfg[VECTOR_COUNT]||count>128||cfg[COMPONENT_INDEX]>=count)return FALSE;
  QEQ(cfg[VECTOR_DATA]+cfg[COMPONENT_INDEX]*8,cfg[HANDLE]);
  state.reason=41;
  QEQ(cfg[COMPONENT]+0x70,cfg[BASE]+0x27ecf30);QEQ(cfg[COMPONENT]+0x78,cfg[SENDER_NODE]);
  QEQ(cfg[SENDER_NODE],0);QEQ(cfg[SENDER_NODE]+8,cfg[RECEIVER_HANDLE]);QEQ(cfg[SENDER_NODE]+0x10,cfg[BODY]+0x270);
  QEQ(cfg[BODY]+0x270,cfg[BASE]+0x27ecee0);QEQ(cfg[BASE]+0x27ecee0+8,cfg[BASE]+0x80cb40);
  QEQ(cfg[BODY]+0x280,cfg[BODY]+0x268);QEQ(cfg[BODY]+0x278,cfg[RECEIVER_TABLE]);
  if(!rpm(cfg[BODY]+0x2a0,&flag,1)||flag||!item_callbacks())return FALSE;
  state.reason=42;
  switch(cfg[SOURCE_KIND]){
    case 1:if(!rpm(cfg[BODY]+0x4f0,&flag,1)||(flag&1))return FALSE;w->count=1;w->body_state=flag;cfg[EXPECTED_COUNT]=flag;break;
    case 2:
      if(!rpm(cfg[BODY]+0x59e,&flag,1)||!(flag&8)||!rpm(cfg[BODY]+0x508,&state.take_mode,4)||state.take_mode!=1||
         !q(cfg[BODY]+0x570,&state.nested_container)||state.nested_container)return FALSE;
      QEQ(cfg[BODY]+0x3d8,cfg[BASE]+0x29e8448);QEQ(cfg[BASE]+0x29e8448+0x20,cfg[BASE]+0x1185870);
      if(!rpm(cfg[BODY]+0x4c8,vector,16)||!rpm(cfg[BODY]+0x388,&w->body_state,4)||w->body_state!=1)return FALSE;
      w->count=vector[7]?vector[7]-1:u32(vector+8);if(w->count>512||w->count!=cfg[EXPECTED_COUNT])return FALSE;break;
    default:return FALSE;
  }
  if(!position(cfg[PLAYER],w->player)||!position(cfg[BODY],w->body))return FALSE;
  for(i=0;i<3;i++){d=w->player[i]-w->body[i];dist+=d*d;}if(dist>COLLECTION_RADIUS_SQUARED)return FALSE;
  w->body_pointer=cfg[BODY];w->component=cfg[COMPONENT];w->human=cfg[PROXY];
  state.reason=0;return TRUE;
}
static gboolean guard(Witness*w){switch(cfg[SOURCE_KIND]){case 0:return guard_body(w);case 1:case 2:return guard_cbs(w);default:return FALSE;}}
static gboolean bind_cbs(guint64 item,guint kind){
  guint64 v,poolwords[2],packed,handle,c,owner;guint8 vec[16];guint count,i,offset,found=0,primary;
  switch(kind){case 1:primary=0x29ec228;break;case 2:primary=0x29e6ff8;break;default:return FALSE;}
  cfg[SOURCE_KIND]=kind;cfg[BODY]=item;cfg[HUMAN]=cfg[PROXY]=cfg[HANDLE]=cfg[COMPONENT]=0;
  state.reason=43;
  if(!is_type(item,primary)||!q(item+0x38,&cfg[PROXY])||!is_type(cfg[PROXY],0x2d326f8)||
     !q(cfg[PROXY]+0x10,&cfg[ENTITY])||!rpm(cfg[ENTITY]+0x78,vec,16)||!q(cfg[POOL_SLOT],&cfg[POOL])||!rpm(cfg[POOL],poolwords,16))return FALSE;
  cfg[HUMAN]=cfg[PROXY];cfg[STORAGE]=poolwords[0];packed=u64(vec);count=vec[7]?vec[7]-1:u32(vec+8);
  if(!count||count>128)return FALSE;
  cfg[VECTOR_PACKED]=packed;cfg[VECTOR_DATA]=packed&0xffffffffffffULL;cfg[VECTOR_COUNT]=count;
  for(i=0;i<count;i++){if(!checkpoint())return FALSE;if(!q(cfg[VECTOR_DATA]+i*8,&handle))return FALSE;
    offset=(guint)(handle<<4);if(offset<0x70||offset>=poolwords[1])continue;c=cfg[STORAGE]+offset;
    if(!q(c,&v))return FALSE;if(v!=cfg[BASE]+0x293c8c0)continue;
    if(!q(c+0x10,&owner)||owner!=cfg[ENTITY]||!q(c+0x598,&v))return FALSE;if(v)continue;
    if(found++)return FALSE;cfg[COMPONENT]=c;cfg[HANDLE]=handle;cfg[COMPONENT_INDEX]=i;
  }
  if(found!=1||!q(cfg[COMPONENT]+0x78,&cfg[SENDER_NODE])||!cfg[SENDER_NODE]||!q(cfg[SENDER_NODE]+8,&cfg[RECEIVER_HANDLE])||
     !q(cfg[SENDER_NODE]+0x10,&cfg[RECEIVER_CALLBACK])||cfg[RECEIVER_CALLBACK]!=item+0x270||
     !q(item+0x278,&cfg[RECEIVER_TABLE]))return FALSE;
  if(kind==2){if(!rpm(item+0x4c8,vec,16))return FALSE;cfg[EXPECTED_COUNT]=vec[7]?vec[7]-1:u32(vec+8);if(cfg[EXPECTED_COUNT]>512)return FALSE;}
  return TRUE;
}
static gboolean ground_context(void){guint8*ctx=p(CONTEXT);
  return u64(ctx)==cfg[PLAYER]+0x1b0&&u32(ctx+8)==0&&ctx[0x18]==0x20;}
static Post post_item(void){Post out={0};guint64 v;guint8 flag;
  if(!q(cfg[BODY],&v)||v!=cfg[BASE]+0x29ec228)out.invalidated|=1;
  if(!q(cfg[PROXY]+8,&v)||v!=cfg[RECEIVER_HANDLE])out.invalidated|=2;
  if(!q(cfg[PROXY]+0x48,&v)||v!=cfg[BODY]+0x20)out.invalidated|=4;
  if(rpm(cfg[BODY]+0x4f0,&flag,1)){out.ground_flags=flag;out.body_state=flag;out.valid=1;}
  else{out.ground_flags=0xffffffff;out.invalidated|=8;}
  if(out.invalidated)out.valid=1;
  out.count=((out.ground_flags!=0xffffffff&&(out.ground_flags&1))||out.invalidated)?0:1;
  return out;
}
static gboolean cooling(guint64 now){guint i;
  for(i=0;i<64;i++){Cooldown*c=&state.cooldowns[i];if(c->body==cfg[BODY]&&c->human==cfg[HUMAN]&&c->handle==cfg[HANDLE]&&
    c->receiver_handle==(cfg[SOURCE_KIND]?cfg[RECEIVER_HANDLE]:0)&&now<c->until)return TRUE;}return FALSE;
}
static gint reserve_cooldown(void){guint i;guint64 now=GetTickCount64();
  for(i=0;i<64;i++)if(now>=state.cooldowns[i].until||!state.cooldowns[i].failed)return (gint)i;
  state.cooldown_pressure++;return -1;
}
static void cool(gint slot,guint milliseconds,guint failed){Cooldown*c=&state.cooldowns[slot];
  c->body=cfg[BODY];c->human=cfg[HUMAN];c->handle=cfg[HANDLE];c->receiver_handle=cfg[SOURCE_KIND]?cfg[RECEIVER_HANDLE]:0;
  c->until=GetTickCount64()+milliseconds;c->failed=failed;}
static Post post(void){Post out={0,0,0};guint8 b[16];
  if((cfg[SOURCE_KIND]==0&&(!is_type(cfg[BODY],0x29e84f0)||!is_type(cfg[HUMAN],0x2962618)))||
     (cfg[SOURCE_KIND]==2&&!is_type(cfg[BODY],0x29e6ff8))||!is_type(cfg[PLAYER],0x259c450)||
     !rpm(cfg[BODY]+0x4c8,b,16)||!rpm(cfg[BODY]+0x388,&out.body_state,4))return out;
  out.count=b[7]?b[7]-1:u32(b+8);out.valid=out.count<=512;return out;
}
static void event(guint status,gint action,guint eligible,guint al,Post after,guint reads_before,guint64 start,Witness*before){
  guint64 end,slot=state.event_cursor++%64,*e=state.events[slot],*extra=state.event_extra[slot];guint i;float ds=0,d;
  QueryPerformanceCounter((gint64*)&end);for(i=0;i<16;i++)e[i]=0;
  for(i=0;i<3;i++){d=before->player[i]-before->body[i];ds+=d*d;}
  e[0]=state.cycles;e[1]=GetTickCount64();e[2]=cfg[BODY];e[3]=cfg[HUMAN];e[4]=cfg[HANDLE];e[5]=status;e[6]=state.reason;
  e[7]=before->count;e[8]=after.count;e[9]=after.body_state;e[10]=(guint64)(gint64)action;e[11]=eligible;e[12]=al;
  extra[0]=cfg[SOURCE_KIND];extra[1]=cfg[SOURCE_KIND]==1?cfg[EXPECTED_COUNT]:0;extra[2]=after.ground_flags;extra[3]=after.invalidated;
  e[13]=state.reads-reads_before;e[14]=end-start;e[15]=ds>=0&&ds<=COLLECTION_RADIUS_SQUARED?(guint)(ds*1000000.0f):~0ULL;state.events_total++;
}
static gboolean action(void){
  Witness before={0},after={0};Post result={0};gpointer resolved;guint8*ctx=p(CONTEXT);
  guint i,eligible=0,al=0,status=2,reads_before=state.reads,did_dispatch=0;gint id=-1,cool_slot=-1;guint64 start;
  QueryPerformanceCounter((gint64*)&start);
  if(!checkpoint())return FALSE;
  if(!canaries()){status=6;goto done;}if(!guard(&before))goto done;
  for(i=0;i<48;i++)ctx[i]=0;
  if(!checkpoint())goto cancel;
  context_ctor(ctx,(gpointer)(cfg[PLAYER]+0x1b0),0,0,1);
  if(!canaries()){status=6;goto done;}if(cfg[SOURCE_KIND]&&!ground_context()){status=9;goto done;}if(!checkpoint())goto cancel;
  resolved=get_component(p(POOL),cfg[HANDLE]);
  if(!checkpoint())goto cancel;if(resolved!=p(COMPONENT)){status=3;goto done;}
  if(!cfg[SOURCE_KIND]){guint64 m;if(!q(cfg[HUMAN]+0x5e8,&m)||!m||m!=cfg[MANAGER])goto done;}
  if(!checkpoint())goto cancel;
  id=select_action(resolved,ctx);
  if(!canaries()){status=6;goto done;}if(!checkpoint())goto cancel;
  if(id!=1||(cfg[SOURCE_KIND]&&!ground_context())){status=9;goto done;}
  eligible=can_use(resolved,1,ctx);
  if(!canaries()){status=6;goto done;}if(!checkpoint())goto cancel;
  if(!eligible||(cfg[SOURCE_KIND]&&!ground_context())){status=9;goto done;}
  if(!guard(&after)){status=5;goto done;}if(!checkpoint())goto cancel;
  cool_slot=reserve_cooldown();if(cool_slot<0){status=11;goto done;}
  if(runtime_config[12]&&state.dispatches>=runtime_config[12]){state.limit_reached=1;status=12;goto done;}
  state.dispatch_inflight=1;state.dispatches++;did_dispatch=1;
  switch(cfg[SOURCE_KIND]){case 0:break;case 1:state.ground_dispatches++;break;case 2:state.container_dispatches++;break;}
  if(runtime_config[12]&&state.dispatches>=runtime_config[12])state.limit_reached=1;
  al=player_dispatch(p(PLAYER),cfg[HANDLE],ctx);
  state.dispatch_inflight=0;
  /* Post reads finish even if stop/budget became true inside native dispatch. */
  state.post_phase=1;result=cfg[SOURCE_KIND]==1?post_item():post();state.post_phase=0;
  status=result.valid&&result.count==0&&(cfg[SOURCE_KIND]==1||result.body_state==5)?1:10;
  if(!canaries())status=6;
  if(status==1){switch(cfg[SOURCE_KIND]){case 0:state.completed++;break;case 1:state.ground_completed++;break;case 2:state.container_completed++;break;}}
  goto done;
cancel:
  status=stopped()?7:8;
done:
  if(status!=1){state.refused++;switch(cfg[SOURCE_KIND]){case 1:state.ground_refused++;break;case 2:state.container_refused++;break;}}
  /* Pre-dispatch refusal can change by next tick (e.g. alive->dead): no long cache.
   * Native no-progress is not retried for60s for this exact generation tuple. */
  if(status==1)cool(cool_slot,30000,0);else if(did_dispatch)cool(cool_slot,60000,1);
  event(status,id,eligible,al,result,reads_before,start,&before);
  if(status==6)g_atomic_int_add(&state.disabled,1);
  return did_dispatch || (!stopped()&&!budget());
}
static gboolean vector_canaries(void){guint i;guint8*v=(gpointer)runtime_config[8];
  if(runtime_config[8]&15)return FALSE;
  for(i=0;i<16;i++)if(v[-16+(gint)i]!=0xa5||v[16+i]!=0x5a)return FALSE;return TRUE;}
static void cycle(void){
  guint i,n=0,processed=0,total=0,offset,marker;guint64 a,b,level,type,data,raw[8],begin,end,query_start,query_end;
  float centre[3];guint8*v=(gpointer)runtime_config[8];gboolean initialized=FALSE;
  state.reason=0;state.status=2;state.thread_id=GetCurrentThreadId();state.cycles++;
  QueryPerformanceCounter((gint64*)&begin);
  for(i=7;i<32;i++)cfg[i]=0;
  cfg[POOL_SLOT]=cfg[BASE]+0x37069b0;cfg[CONTEXT]=runtime_config[9];cfg[RADIUS_MM]=COLLECTION_RADIUS_MM;
  if(!checkpoint()||!local_guard()||!vector_canaries()||!canaries()||!position(cfg[PLAYER],centre))goto finish;
  if(!q(cfg[PLAYER]+0x40,&a)||!q(a+0x48,&b)||!b||!q(b+0x6d8,&level)||!level||
     !q(runtime_config[7]+0x260ebf8,&type)||!type||!q(type,&a)||!a)goto finish;
  for(i=0;i<16;i++)v[i]=0;*(guint64*)v=(runtime_config[8]+8)&0xffffffffffffULL;*(guint16*)(v+6)=0x0101;initialized=TRUE;
  if(!checkpoint())goto destroy;
  QueryPerformanceCounter((gint64*)&query_start);state.queries++;
  state.query_al=find_radius((gpointer)level,v,centre,COLLECTION_RADIUS_METRES,(gpointer)type,0,NULL);
  QueryPerformanceCounter((gint64*)&query_end);state.query_ticks+=query_end-query_start;
  if(!vector_canaries()){state.status=6;g_atomic_int_add(&state.disabled,1);goto destroy;}
  marker=v[7];total=marker?marker-1:u32(v+8);state.last_native_count=total;data=u64(v)&0xffffffffffffULL;
  offset=(guint)state.next_offset;if(offset>=total)offset=0;
  /* Copy only; native allocation capacity/count remain untouched. */
  for(i=offset;i<total&&n<8;i++){if(!checkpoint())break;if(!q(data+8*i,&raw[n]))break;n++;}
destroy:
  if(initialized){state.dtors++;vector_destroy(v);initialized=FALSE;}
  if(!vector_canaries()){state.status=6;g_atomic_int_add(&state.disabled,1);goto finish;}
  if(!checkpoint())goto finish;
  state.status=1;
  for(i=0;i<n;i++){
    if(!checkpoint())break;
    if(raw[i]<0x10010){processed++;continue;}
    {guint64 vt;if(!q(raw[i]-0x10,&vt))break;
      if(vt==cfg[BASE]+0x29ec228&&runtime_config[11]){if(bind_cbs(raw[i]-0x10,1))goto bound;}
      else if(vt==cfg[BASE]+0x29e6ff8&&runtime_config[14]){if(bind_cbs(raw[i]-0x10,2))goto bound;}
      else if(vt==cfg[BASE]+0x29e84f0&&runtime_config[13]){if(bind_body(raw[i]-0x10))goto bound;}
      else {processed++;continue;}
    }
    {
      if(!checkpoint())break;
      state.refused++;processed++;continue;
    }
bound:
    if(cooling(GetTickCount64())){processed++;continue;}
    if(!action())break;processed++;
  }
  /* Advance only entries actually handled/refused, never merely copied. */
  state.next_offset=offset+processed<total?offset+processed:0;
finish:
  if(initialized){state.dtors++;vector_destroy(v);}
  if(budget())state.budget_stops++;
  state.last_processed=processed;state.last_copied=n;state.last_cycle_reads=state.reads;
  QueryPerformanceCounter((gint64*)&end);state.total_ticks+=end-begin;
  {guint64*c=state.cadence[state.cadence_cursor++%64];c[0]=state.cycles;c[1]=state.cycle_start;c[2]=GetTickCount64();c[3]=end-begin;c[4]=state.last_start_qpc;}
}
static gboolean refresh_local(void){
  guint64 game,level,client,gate,player,v;
  cfg[BASE]=runtime_config[3];cfg[GAME_SLOT]=runtime_config[2];
  if(!q(cfg[GAME_SLOT],&game)||!is_type(game,0x259fe08)||!q(game+0x138,&level)||
     !q(level+0xec8,&client)||!q(client+0x88,&gate)||!gate||!q(client+0x90,&player)||
     !is_type(player,0x259c450))return FALSE;
  if(cfg[PLAYER]!=player||cfg[GAME]!=game||cfg[LEVEL]!=level){
    guint n;state.next_offset=0;state.cooldown_cursor=0;
    for(n=0;n<64;n++){state.cooldowns[n].body=0;state.cooldowns[n].human=0;state.cooldowns[n].handle=0;state.cooldowns[n].receiver_handle=0;state.cooldowns[n].until=0;state.cooldowns[n].failed=0;}
  }
  /* Publish the complete fresh tuple only after validating all its members. */
  cfg[PLAYER]=player;cfg[GAME]=game;cfg[LEVEL]=level;cfg[CLIENT]=client;cfg[GATE]=gate;
  return TRUE;
}
void on_enter(GumInvocationContext*ic){Invocation*i=gum_invocation_context_get_listener_invocation_data(ic,sizeof(Invocation));
  i->player=gum_invocation_context_get_nth_argument(ic,0);g_atomic_int_add(&state.inflight,1);
}
void on_leave(GumInvocationContext*ic){Invocation*i=gum_invocation_context_get_listener_invocation_data(ic,sizeof(Invocation));guint64 now,delta,qpc;
  if(!stopped()&&!state.limit_reached){
    if(g_atomic_int_add(&state.gate,1)==0){
      now=GetTickCount64();
      QueryPerformanceCounter((gint64*)&qpc);
      if(!stopped()&&now>=state.next_due&&qpc>=state.next_due_qpc){
        state.reads=0;state.cycle_start=now;state.cycle_start_qpc=qpc;
        if(!refresh_local()){state.next_due=now+COLLECTION_INTERVAL_MS;state.next_due_qpc=qpc+interval_ticks();state.status=2;}
        else if(i->player==p(PLAYER)){
          g_atomic_int_add(&state.matching,1);
          if(state.last_start){delta=now-state.last_start;if(!state.minimum_interval||delta<state.minimum_interval)state.minimum_interval=delta;if(delta>state.maximum_interval)state.maximum_interval=delta;}
          if(state.last_start_qpc){delta=qpc-state.last_start_qpc;if(!state.minimum_interval_qpc||delta<state.minimum_interval_qpc)state.minimum_interval_qpc=delta;if(delta>state.maximum_interval_qpc)state.maximum_interval_qpc=delta;}
          state.last_start=now;state.last_start_qpc=qpc;state.next_due=now+COLLECTION_INTERVAL_MS;state.next_due_qpc=qpc+interval_ticks();cycle();
        }else g_atomic_int_add(&state.ignored,1);
      }
      g_atomic_int_add(&state.gate,-1);
    }else{g_atomic_int_add(&state.contended,1);g_atomic_int_add(&state.gate,-1);}
  }
  g_atomic_int_add(&state.inflight,-1);
}
void disable(void){g_atomic_int_add(&state.disabled,1);}
guint state_size(void){return sizeof(State);}
guint snapshot_size(void){return (64+64*16+64*5+64*4)*8;}
/* Snapshot copying uses the same nonblocking gate, so JS never reads partial events. */
guint snapshot(guint64*out){guint i;guint64*s=out;
  if(g_atomic_int_add(&state.gate,1)!=0){g_atomic_int_add(&state.gate,-1);return 0;}
  for(i=0;i<64;i++)s[i]=0;
  s[0]=state.cycles;s[1]=state.queries;s[2]=state.dtors;s[3]=state.dispatches;s[4]=state.completed;s[5]=state.refused;
  s[6]=state.budget_stops;s[7]=state.query_ticks;s[8]=state.total_ticks;s[9]=state.minimum_interval;s[10]=state.maximum_interval;
  s[11]=state.next_due;s[12]=state.next_offset;s[13]=state.events_total;s[14]=state.event_cursor;s[15]=state.cadence_cursor;
  s[16]=state.last_native_count;s[17]=state.last_cycle_reads;s[18]=state.status;s[19]=state.reason;s[20]=state.thread_id;
  s[21]=state.last_processed;s[22]=state.last_copied;s[23]=atomic_get(&state.disabled);s[24]=atomic_get(&state.inflight);
  s[25]=atomic_get(&state.selected);s[26]=atomic_get(&state.matching);s[27]=atomic_get(&state.ignored);s[28]=atomic_get(&state.contended);
  s[29]=state.query_al;s[30]=state.dispatch_inflight;s[31]=COLLECTION_INTERVAL_MS;s[32]=8;s[33]=4096;s[34]=COLLECTION_BUDGET_MS;s[35]=state.cooldown_pressure;s[36]=state.minimum_interval_qpc;s[37]=state.maximum_interval_qpc;s[38]=state.next_due_qpc;s[39]=runtime_config[10];s[40]=runtime_config[11];s[41]=runtime_config[12];s[42]=state.limit_reached;s[43]=state.ground_dispatches;s[44]=state.ground_completed;s[45]=state.ground_refused;s[46]=runtime_config[14];s[47]=state.container_dispatches;s[48]=state.container_completed;s[49]=state.container_refused;
  copy(s+64,state.events,64*16*8);copy(s+64+64*16,state.cadence,64*5*8);copy(s+64+64*16+64*5,state.event_extra,64*4*8);
  g_atomic_int_add(&state.gate,-1);return 1;
}
guint pending(void){return atomic_get(&state.gate)!=0;}
