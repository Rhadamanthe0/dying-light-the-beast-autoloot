"""Fresh, bounded read-only session discovery; never injects or calls game code.

python tools/discover_session.py --static-only
python tools/discover_session.py --output evidence/session-current.json
The memory phase has a 1 second / 8 MiB / 4096-read budget. No heap scan.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from inspect_native import Image, GAME
import observe_runtime as observer

BIN = GAME / "ph_ft/work/bin/x64"
EXE = "DyingLightGame_TheBeast_x64_rwdi.exe"
GAME_DLL = "gamedll_ph_x64_rwdi.dll"
ENGINE_DLL = "engine_x64_rwdi.dll"
HASHES = {
    "game": "ddb68c8f87ba2afd0e561b2d1adb9235467c29069fb1cd1619db81e1056378eb",
    "engine": "3dcae152c002f1d549df2ed12c21cc38ddb6b25fd989345f0c413c7442243f1b",
}
PROLOGUES = [
    ("PlayerUpdate", 0x12CC7A0, "40534883ec4080b9003c000000488d81"),
    ("PlayerDispatch", 0x12D9AA0, "4885d20f84db00000048895c24104889"),
    ("BodyAction", 0x11936C0, "4055564154415541564881ecd0010000"),
    ("TransferHelper", 0x1185A70, "40564154415541574883ec780fb681cf"),
    ("Tick", 0x1033330, "40534883ec300f29742420488bd90f28"),
    ("Game_coop_count", 0x15AD450, "40534883ec20488b01488bd9ff905008"),
    ("Game_session_present", 0x1774B0, "4883b938010000000f95c0c3cccccccc"),
    ("Session_context_getter", 0x15AC740, "488b8108160000c3cccccccccccccccc"),
    ("Context_coop_count", 0x15AE9D0, "0fb681d723000084c075078b81d82300"),
]
VTABLE_RVAS = {"game": 0x259FE08, "player": 0x259C450, "trigger": 0x29C3F90}
MEMORY_SECONDS, MAX_BYTES, MAX_READS = 1.0, 8 * 1024 * 1024, 4096
PLAYER_PREFIX_BYTES = 0x10000
MAX_POINTER = 0x7FFFFFFF0000
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def path_key(path):
    return str(Path(path).resolve()).casefold()


def unpack_q(data):
    if len(data) != 8:
        raise ValueError("Expected exactly eight pointer bytes")
    return struct.unpack("<Q", data)[0]


def pointer_values(prefix):
    """Unique aligned pointers and all their field offsets in this prefix only."""
    if len(prefix) != PLAYER_PREFIX_BYTES:
        raise ValueError("Full bounded Player prefix required")
    result = {}
    for offset in range(0, len(prefix), 8):
        value = struct.unpack_from("<Q", prefix, offset)[0]
        if 0x10000 <= value < MAX_POINTER and value % 8 == 0:
            result.setdefault(value, []).append(offset)
    return result


def prepare_static():
    image = Image(BIN / GAME_DLL)
    if hashlib.sha256(image.data).hexdigest() != HASHES["game"] or digest(BIN / ENGINE_DLL) != HASHES["engine"]:
        raise ValueError("Installed DLL hash differs from reviewed 1.7.1 build")
    if image.pe.FILE_HEADER.Machine != 0x8664 or image.pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("Reviewed x64 PE required")
    guards = []
    for name, rva, expected in PROLOGUES:
        actual = image.data[image.offset(rva):image.offset(rva) + len(bytes.fromhex(expected))].hex()
        if actual != expected:
            raise ValueError("Disk prologue mismatch: " + name)
        guards.append({"name": name, "rva": rva, "hex": expected})
    # Decode the actual instructions, including instruction length; no absolute VA.
    image.cs.detail = True
    predicate = list(image.cs.disasm(image.data[image.offset(0xDD0EF0):image.offset(0xDD0EF0)+31], image.base+0xDD0EF0))
    call = predicate[1]
    if call.mnemonic != "call" or call.operands[0].type != 2 or call.operands[0].imm-image.base != 0xB347B0:
        raise ValueError("CndIsCoop Game getter call changed")
    getter = next(image.cs.disasm(image.data[image.offset(0xB347B0):image.offset(0xB347B0)+8], image.base+0xB347B0))
    if getter.mnemonic != "mov" or getter.reg_name(getter.operands[1].mem.base) != "rip":
        raise ValueError("Game getter is not the reviewed RIP-relative load")
    global_rva = getter.address + getter.size + getter.operands[1].mem.disp - image.base
    if global_rva != 0x3ACB4F0:
        raise ValueError("Game global RVA changed")
    tables = {}
    for key, cls in [("game", "GameDI_PH"), ("player", "PlayerDI_PH"), ("trigger", "TriggerController")]:
        primary = [table for table in image.vtables(cls) if table["subobject_offset"] == 0]
        if len(primary) != 1 or int(primary[0]["vtable_rva"], 0) != VTABLE_RVAS[key]:
            raise ValueError("Primary RTTI/vtable mismatch: " + cls)
        rva = VTABLE_RVAS[key]
        col = unpack_q(image.data[image.offset(rva)-8:image.offset(rva)]) - image.base
        col_bytes = image.data[image.offset(col):image.offset(col)+24]
        sig, offset, _, td, _, self_rva = struct.unpack("<6I", col_bytes)
        if sig != 1 or offset != 0 or self_rva != col:
            raise ValueError("Invalid primary COL: " + cls)
        entries = [unpack_q(image.data[image.offset(rva)+n:image.offset(rva)+n+8])-image.base for n in range(0, 64, 8)]
        tables[key] = {"class": cls, "rva": rva, "col_rva": col, "col_hex": col_bytes.hex(),
                       "type_descriptor_rva": td, "rtti_name": ".?AV"+cls+"@@", "first_eight_function_rvas": entries}
        if key == "trigger" and primary[0]["functions"][0x4A8//8] != "0x17f800":
            raise ValueError("Trigger owner getter slot changed")
    if image.data[image.offset(0x17F800):image.offset(0x17F800)+5].hex() != "488b4108c3":
        raise ValueError("Trigger owner getter body changed")
    discovery_guards = [{"name": name, "rva": rva,
                         "hex": image.data[image.offset(rva):image.offset(rva)+16].hex()}
                        for name,rva in [("CndIsCoop",0xDD0EF0),("Game_global_getter",0xB347B0),("Trigger_owner_getter",0x17F800),
                                         ("Player_controller_host_getter",0x6E43E0),("Controller_tick_loop",0x1EE6970)]]
    if image.data[image.offset(0x6E43E0):image.offset(0x6E43E0)+8].hex() != '488b8100020000c3':
        raise ValueError('Controller host getter changed')
    # The caller is a chained .pdata fragment; retain its parent unwind record.
    fragment=image.function(0x12CC9C1)
    unwind=image.offset(fragment[2]); header=image.data[unwind:unwind+4]
    if not header[0]>>3 & 4:
        raise ValueError('Expected chained caller unwind record')
    parent=struct.unpack_from('<III',image.data,unwind+4+((header[2]+1)&~1)*2)
    if parent[0]!=0x12CC7A0:
        raise ValueError('Controller caller unwind parent changed')
    return {"schema_version": 1, "mode": "static_PE_only_no_process_access",
            "images": {key:{"path":str(BIN/name),"sha256":HASHES[key]} for key,name in [("game",GAME_DLL),("engine",ENGINE_DLL)]},
            "game_global_rva": hex(global_rva), "guarded_prologues": guards,
            "discovery_prologues": discovery_guards, "vtables": tables,
            "disassembly": {hex(rva):image.disasm(rva,size) for rva,size in [(0xDD0EF0,31),(0xB347B0,8),(0x17F800,5),
                             (0x6E43E0,8),(0x12CC7A0,28),(0x12CC9AB,48),(0x1EE6970,184)]},
            "native_controller_vector": {"player_host_offset":"0x200","host_registry_offset":"0x1c8", "registry_list_offset":"0x1d8",
                                         "registry_count_offset":"0x1e0","pointer_mask":"0xffffffffffff","max_count":256,
                                         "caller_fragment_rvas":[hex(v) for v in fragment],"caller_unwind_parent_rvas":[hex(v) for v in parent],
                                         "proof":"Caller12cc9b6 invokes getter6e43e0 on saved THIS; getter reads+0x200. Returned host is passed to loop1ee6970, which reads host+0x1c8 then its registry vector+0x1d8/count. Final exact Trigger class+owner Player, complete vector and rereads are mandatory; the host itself is not assumed to have a particular RTTI."},
            "chain": {"game_level_offset":"0x138","level_client_offset":"0xec8","client_gate_offset":"0x88","client_player_offset":"0x90",
                      "trigger_owner_pointer_offset":"0x8","trigger_owner_vtable_slot_offset":"0x4a8","trigger_owner_getter_rva":"0x17f800"},
            "discovery": {"method":"Read the first 0x10000 bytes of current Player and the statically evidenced native controller vector via Player+0x200→host+0x1c8→registry vector+0x1d8. Require unique exact TriggerController primary vtable and owner Player. No heap traversal.",
                          "unique_trigger_required":True,"memory_seconds":MEMORY_SECONDS,"max_bytes":MAX_BYTES,"max_reads":MAX_READS},
            "limits": ["Game/Player chain offsets reuse the previously observed native chain, then require exact live identity and a complete reread; the chain is not a guarantee of object lifetime.",
                       "Controller discovery is restricted to direct Player prefix pointers and the native local controller vector. Missing, unreadable, ambiguous or budget-limited discovery refuses readiness.",
                       "Deadlines are checked before and after synchronous OS reads; a kernel call cannot be preempted by this script. Any overrun rejects readiness.",
                       "No game code, hook, engine invocation, item collection or cooperative behavior is exercised."]}


class PROCESSENTRY32W(C.Structure):
    _fields_ = [("dwSize",W.DWORD),("cntUsage",W.DWORD),("th32ProcessID",W.DWORD),
                ("th32DefaultHeapID",C.c_size_t),("th32ModuleID",W.DWORD),("cntThreads",W.DWORD),
                ("th32ParentProcessID",W.DWORD),("pcPriClassBase",W.LONG),("dwFlags",W.DWORD),("szExeFile",W.WCHAR*260)]


def api_setup():
    api = observer.windows_api()
    for name,args,result in [
        ("Process32FirstW",[W.HANDLE,C.POINTER(PROCESSENTRY32W)],W.BOOL),
        ("Process32NextW",[W.HANDLE,C.POINTER(PROCESSENTRY32W)],W.BOOL),
        ("GetProcessTimes",[W.HANDLE,C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME)],W.BOOL),
    ]:
        getattr(api,name).argtypes=args
        getattr(api,name).restype=result
    return api


def process_ids(api):
    snapshot = api.CreateToolhelp32Snapshot(0x02,0)
    if snapshot == observer.INVALID_HANDLE:
        raise C.WinError(C.get_last_error())
    values = []
    try:
        entry=PROCESSENTRY32W(); entry.dwSize=C.sizeof(entry)
        if not api.Process32FirstW(snapshot,C.byref(entry)):
            raise C.WinError(C.get_last_error())
        while True:
            if entry.szExeFile.casefold()==EXE.casefold():
                values.append(entry.th32ProcessID)
            if not api.Process32NextW(snapshot,C.byref(entry)):
                if C.get_last_error()!=18:
                    raise C.WinError(C.get_last_error())
                break
    finally:
        api.CloseHandle(snapshot)
    return values


def creation_time(api,handle):
    created,exited,kernel,user = W.FILETIME(),W.FILETIME(),W.FILETIME(),W.FILETIME()
    if not api.GetProcessTimes(handle,C.byref(created),C.byref(exited),C.byref(kernel),C.byref(user)):
        raise C.WinError(C.get_last_error())
    return str((created.dwHighDateTime<<32)|created.dwLowDateTime)


class Reader:
    def __init__(self,api,handle):
        self.api,self.handle=api,handle
        self.started=time.monotonic()
        self.bytes_requested=self.read_calls=self.queries=0
        self.unreadable_candidates=0
        self.regions=[]

    def check(self):
        if time.monotonic()-self.started>=MEMORY_SECONDS:
            raise TimeoutError("Global 1 second memory-read budget exhausted")
        if self.read_calls>=MAX_READS:
            raise RuntimeError("4096 memory-read budget exhausted")

    def readable(self,address,size):
        self.check()
        if not 0x10000<=address<MAX_POINTER or not 0<size<=PLAYER_PREFIX_BYTES or address+size>MAX_POINTER:
            return False
        cursor=address
        while cursor<address+size:
            self.check()
            region=next((item for item in self.regions if item[0]<=cursor<item[1]),None)
            if region is None:
                if self.queries>=MAX_READS:
                    raise RuntimeError("4096 memory-query budget exhausted")
                info=observer.MEMORY_BASIC_INFORMATION()
                self.queries+=1
                if not self.api.VirtualQueryEx(self.handle,cursor,C.byref(info),C.sizeof(info)):
                    return False
                begin=info.BaseAddress or 0; end=begin+info.RegionSize
                if not begin<=cursor<end:
                    raise RuntimeError("Invalid VirtualQueryEx range")
                region=(begin,end,info.State==observer.MEM_COMMIT and (info.Protect&0xff) in READABLE and not info.Protect&0x100)
                self.regions.append(region)
            if not region[2]:
                return False
            cursor=min(address+size,region[1])
        return True

    def read(self,address,size):
        if not self.readable(address,size):
            raise ValueError("Unreadable required range: "+hex(address))
        if self.bytes_requested+size>MAX_BYTES:
            raise RuntimeError("8 MiB memory-read budget exhausted")
        buf=C.create_string_buffer(size); count=C.c_size_t()
        self.read_calls+=1; self.bytes_requested+=size
        ok=self.api.ReadProcessMemory(self.handle,address,buf,size,C.byref(count))
        self.check()
        if not ok or count.value!=size:
            raise OSError("Failed or partial ReadProcessMemory: "+hex(address))
        return buf.raw

    def q(self,address):
        return unpack_q(self.read(address,8))

    def stats(self):
        return {"elapsed_seconds":round(time.monotonic()-self.started,6),"read_calls":self.read_calls,
                "bytes_requested":self.bytes_requested,"virtual_queries":self.queries,
                "unreadable_pointer_candidates_skipped":self.unreadable_candidates}


def discover(pid=None):
    proof=prepare_static()
    api=api_setup()
    pids=process_ids(api)
    if pid is None:
        if len(pids)!=1:
            raise ValueError(f"Expected exactly one {EXE}; found {len(pids)}")
        pid=pids[0]
    elif pid<=0 or pid not in pids:
        raise ValueError("Requested PID is not the exact expected executable")
    loaded=observer.modules(api,pid)
    modules={}
    for key,name in [("game",GAME_DLL),("engine",ENGINE_DLL),("exe",EXE)]:
        matches=[m for m in loaded if m['name'].casefold()==name.casefold()]
        if len(matches)!=1 or path_key(matches[0]['path'])!=path_key(BIN/name):
            raise ValueError("Expected module/path not unique: "+name)
        module=dict(matches[0]); module['sha256']=digest(module['path'])
        if key in HASHES and module['sha256']!=HASHES[key]:
            raise ValueError("Loaded module disk hash mismatch: "+name)
        modules[key]=module
    base=int(modules['game']['base'],0)
    handle=api.OpenProcess(observer.PROCESS_ACCESS,False,pid)
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        created=creation_time(api,handle)
        rd=Reader(api,handle)
        diagnostic={}
        for guard in proof['guarded_prologues']+proof['discovery_prologues']:
            expected=bytes.fromhex(guard['hex'])
            if rd.read(base+guard['rva'],len(expected))!=expected:
                raise ValueError("Live prologue mismatch: "+guard['name'])
        for table in proof['vtables'].values():
            table_address=base+table['rva']
            if rd.q(table_address-8)!=base+table['col_rva'] or rd.read(base+table['col_rva'],24).hex()!=table['col_hex']:
                raise ValueError("Live RTTI COL mismatch: "+table['class'])
            expected=b''.join(struct.pack('<Q',base+rva) for rva in table['first_eight_function_rvas'])
            if rd.read(table_address,64)!=expected:
                raise ValueError("Live vtable entries mismatch: "+table['class'])
            name=table['rtti_name'].encode()+b'\0'
            if rd.read(base+table['type_descriptor_rva']+16,len(name))!=name:
                raise ValueError("Live RTTI name mismatch: "+table['class'])
        if rd.q(base+VTABLE_RVAS['trigger']+0x4A8)!=base+0x17F800:
            raise ValueError("Live Trigger owner getter slot mismatch")
        global_address=base+int(proof['game_global_rva'],0)
        def get_chain():
            game=rd.q(global_address)
            if rd.q(game)!=base+VTABLE_RVAS['game']:
                raise ValueError("Game not ready or wrong exact vtable")
            level=rd.q(game+0x138)
            client=rd.q(level+0xEC8)
            gate=rd.q(client+0x88)
            if not gate:
                raise ValueError("Player not ready: client gate is null")
            player=rd.q(client+0x90)
            if rd.q(player)!=base+VTABLE_RVAS['player']:
                raise ValueError("Player not ready or wrong exact vtable")
            return game,level,client,gate,player
        game,level,client,gate,player=get_chain()
        diagnostic['chain']={'game':hex(game),'level':hex(level),'client':hex(client),'player':hex(player)}
        prefix=rd.read(player,PLAYER_PREFIX_BYTES)
        candidates=pointer_values(prefix)
        matches={}
        class_candidates=[]
        for pointer,offsets in candidates.items():
            if not rd.readable(pointer,16):
                rd.unreadable_candidates+=1
                continue
            value=rd.q(pointer)
            if value==base+VTABLE_RVAS['trigger']:
                owner=rd.q(pointer+8)
                class_candidates.append({'address':hex(pointer),'owner':hex(owner),'player_field_offsets':[hex(o) for o in offsets]})
                if owner==player:
                    matches[pointer]=offsets
        diagnostic['direct_pointer_count']=len(candidates)
        diagnostic['direct_trigger_class_candidates']=class_candidates
        def get_vector():
            host=rd.q(player+0x200)
            registry=rd.q(host+0x1C8)
            packed=rd.q(registry+0x1D8)
            marker=packed>>56
            count=struct.unpack('<I',rd.read(registry+0x1E0,4))[0] if marker==0 else marker-1
            data=packed&0xFFFFFFFFFFFF
            if not 0<count<=256:
                raise ValueError('Native controller count not ready or beyond cap256: '+str(count))
            return host,registry,packed,marker,count,data
        vector=get_vector()
        host,registry,packed,marker,count,data=vector
        diagnostic['native_vector']={'host':hex(host),'registry':hex(registry),'packed':hex(packed),'marker':marker,'count':count,'data':hex(data)}
        entries=rd.read(data,count*8)
        vector_indices={}
        for index in range(count):
            pointer=struct.unpack_from('<Q',entries,index*8)[0]
            if not pointer:
                continue
            value=rd.q(pointer)
            if value==base+VTABLE_RVAS['trigger']:
                owner=rd.q(pointer+8)
                if owner==player:
                    matches.setdefault(pointer,[])
                    vector_indices.setdefault(pointer,[]).append(index)
        diagnostic['owned_trigger_matches']=[hex(pointer) for pointer in matches]
        if len(matches)!=1:
            raise ValueError(f"Expected one exact owned TriggerController in local Player graph; found {len(matches)}")
        trigger,offsets=next(iter(matches.items()))
        if get_chain()!=(game,level,client,gate,player):
            raise ValueError("Game/player chain changed during bounded read")
        if rd.q(trigger)!=base+VTABLE_RVAS['trigger'] or rd.q(trigger+8)!=player:
            raise ValueError("Trigger identity changed during discovery")
        if any(rd.q(player+offset)!=trigger for offset in offsets):
            raise ValueError("Player/controller field changed during discovery")
        if get_vector()!=vector or any(rd.q(data+index*8)!=trigger for index in vector_indices.get(trigger,[])):
            raise ValueError('Native controller vector changed during discovery')
        exit_code=W.DWORD()
        if not api.GetExitCodeProcess(handle,C.byref(exit_code)) or exit_code.value!=259 or creation_time(api,handle)!=created:
            raise ValueError("Process exited or identity changed")
        rd.check()
        stats=rd.stats()
    except Exception as error:
        if 'rd' in locals():
            error.discovery_diagnostic={'memory_observation':rd.stats(),**diagnostic}
        raise
    finally:
        api.CloseHandle(handle)
    # Toolhelp snapshot has no game memory reads; insist modules stayed in place.
    end_modules=observer.modules(api,pid)
    for module in modules.values():
        if not any(m=={k:module[k] for k in ['name','path','base','size']} for m in end_modules):
            raise ValueError("Loaded module identity changed during discovery")
    result={"schema_version":1,"ready":True,"mode":"read_only_no_native_calls_no_injection",
            "pid":pid,"observed_at_utc":datetime.now(timezone.utc).isoformat(),
            "process_identity":{"creation_time_100ns":created,"executable":modules.pop('exe')},
            "modules":modules,"static_proof_sha256":canonical_hash(proof),
            "objects":{key:{"address":hex(address),"vtable":hex(base+VTABLE_RVAS[key])}
                       for key,address in [('game',game),('player',player),('trigger',trigger)]},
            "chain":{"game_global_slot":hex(global_address),"game_global_rva":proof['game_global_rva'],
                     "level":hex(level),"client":hex(client),"player_gate":hex(gate),**proof['chain']},
            "guarded_prologues":proof['guarded_prologues'],"discovery_prologues":proof['discovery_prologues'],
            "vtables":proof['vtables'],"memory_observation":stats,
            "access":{"mask":hex(observer.PROCESS_ACCESS),"read_only":True},
            "limits":{"memory_seconds":MEMORY_SECONDS,"max_bytes":MAX_BYTES,"max_reads":MAX_READS,"max_virtual_queries":MAX_READS,
                      "player_prefix_bytes":PLAYER_PREFIX_BYTES,"heap_scan":False},
            "limitations":proof['limits']}
    result['objects']['trigger'].update(owner_player=hex(player),player_field_offsets=[hex(offset) for offset in offsets],
                                        owner_slot_offset='0x4a8',owner_pointer_offset='0x8',owner_getter_rva='0x17f800',
                                        native_vector_indices=vector_indices.get(trigger,[]))
    result['chain'].update(controller_host=hex(host),controller_registry=hex(registry),controller_list_data=hex(data),
                           controller_list_packed=hex(packed),controller_count=count,controller_marker=marker,
                           controller_host_offset='0x200',controller_registry_offset='0x1c8',controller_list_offset='0x1d8',controller_count_offset='0x1e0')
    result['session_sha256']=canonical_hash(result)
    return result


def validate_session(path,max_age_seconds=120):
    """Reject stale files/PID reuse; rediscover and compare all live identities."""
    stored=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not stored.get('ready') or stored.get('schema_version')!=1:
        raise ValueError("Session file is not a ready schema1 discovery")
    signed=dict(stored); claimed=signed.pop('session_sha256',None)
    if canonical_hash(signed)!=claimed:
        raise ValueError("Session file integrity hash mismatch")
    stamp=datetime.fromisoformat(stored['observed_at_utc'])
    if stamp.utcoffset() is None or not 0<max_age_seconds<=120:
        raise ValueError("Timezone-aware timestamp and age cap <=120s required")
    age=(datetime.now(timezone.utc)-stamp).total_seconds()
    if not 0<=age<=max_age_seconds:
        raise ValueError("Session file stale or timestamp in the future")
    current=discover(stored['pid'])
    for key in ['pid','process_identity','modules','objects','chain','static_proof_sha256','guarded_prologues','discovery_prologues','vtables']:
        if current[key]!=stored[key]:
            raise ValueError("Fresh session revalidation mismatch: "+key)
    return current


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid',type=int)
    parser.add_argument('--static-only',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or ROOT/'evidence'/('session-discovery-static.json' if args.static_only else 'session-current.json')
    try:
        result=prepare_static() if args.static_only else discover(args.pid)
        ok=True
    except (Exception,KeyboardInterrupt) as error:
        result={'schema_version':1,'ready':False,'pid':args.pid,'observed_at_utc':datetime.now(timezone.utc).isoformat(),
                'mode':'static_PE_only' if args.static_only else 'read_only_no_native_calls_no_injection',
                'errors':[f'{type(error).__name__}: {error}']}
        if hasattr(error,'discovery_diagnostic'):
            result['diagnostic']=error.discovery_diagnostic
        ok=False
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output),'ok':ok,'ready':result.get('ready'),'errors':result.get('errors',[])}))
    return 0 if ok else 1


if __name__=='__main__':
    raise SystemExit(main())
