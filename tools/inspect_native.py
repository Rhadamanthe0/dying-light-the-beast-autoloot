"""Read-only PE inspection. Never opens a game process or changes game files."""
import argparse
import bisect
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.deps'))
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

from game_paths import locate_game
GAME = locate_game()

class Image:
    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        self.pe = pefile.PE(data=self.data, fast_load=True)
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        self.cs = Cs(CS_ARCH_X86, CS_MODE_64)
        sec = next(s for s in self.pe.sections if s.Name.startswith(b'.pdata'))
        pdata = sec.get_data()
        self.funcs = [struct.unpack_from('<III', pdata, i) for i in range(0, len(pdata)-11, 12)]
        self.funcs = sorted(t for t in self.funcs if t[0] and t[1]>t[0])
        self.starts = [t[0] for t in self.funcs]

    def rva(self, offset):
        return self.pe.get_rva_from_offset(offset)

    def offset(self, rva):
        return self.pe.get_offset_from_rva(rva)

    def function(self, rva):
        i = bisect.bisect_right(self.starts, rva)-1
        return self.funcs[i] if i >= 0 and rva < self.funcs[i][1] else None

    def disasm(self, rva, size=400):
        off = self.offset(rva)
        return [f'{i.address-self.base:08x}: {i.mnemonic} {i.op_str}' for i in self.cs.disasm(self.data[off:off+size], self.base+rva)]

    def exports(self):
        # pefile's default limits truncate this game's 45,764 engine exports.
        data = self.pe.get_memory_mapped_image()
        directory = self.pe.OPTIONAL_HEADER.DATA_DIRECTORY[0].VirtualAddress
        if not directory:
            return []
        fields = struct.unpack_from('<IIHHIIIIIII', data, directory)
        count, names, ordinals, functions = fields[7], fields[9], fields[10], fields[8]
        result = []
        for i in range(count):
            name_rva = struct.unpack_from('<I', data, names+4*i)[0]
            ordinal = struct.unpack_from('<H', data, ordinals+2*i)[0]
            rva = struct.unpack_from('<I', data, functions+4*ordinal)[0]
            result.append({'rva': hex(rva), 'name': data[name_rva:data.find(b'\0', name_rva)].decode(errors='replace')})
        return result

    def vtables(self, cls):
        tag = ('.?AV'+cls+'@@').encode()+b'\0'
        off = self.data.find(tag)
        if off < 0:
            return []
        td = self.rva(off-16)
        result=[]
        for m in re.finditer(re.escape(struct.pack('<I',td)), self.data):
            coloff=m.start()-12
            if coloff<0: continue
            sig,suboff,cd,t,cdsc,selfrva=struct.unpack_from('<6I',self.data,coloff)
            if sig != 1 or selfrva != self.rva(coloff):continue
            ptr=struct.pack('<Q',self.base+selfrva)
            for ref in re.finditer(re.escape(ptr), self.data):
                vf=ref.start()+8
                funcs=[]
                limit = 4096
                for j in range(limit):
                    if vf+8*j+8 > len(self.data):
                        break
                    addr=struct.unpack_from('<Q', self.data,vf+8*j)[0]
                    rr=addr-self.base
                    if not any(s.Characteristics & 0x20000000 and s.VirtualAddress<=rr<s.VirtualAddress+s.Misc_VirtualSize for s in self.pe.sections):break
                    funcs.append(hex(rr))
                if funcs: result.append({'class':cls,'subobject_offset':suboff,'vtable_rva':hex(self.rva(vf)),'scan_limit_reached':len(funcs)==limit,'functions':funcs})
        return result

    def xrefs(self, text):
        targets=[]
        for m in re.finditer(re.escape(text.encode()+b'\0'),self.data):targets.append(self.rva(m.start()))
        refs=[]
        for s in self.pe.sections:
            if not s.Characteristics & 0x20000000:continue
            buf=s.get_data()
            for m in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]',buf):
                pos=m.start()
                if pos+7>len(buf):continue
                at=s.VirtualAddress+pos
                dest=at+7+struct.unpack_from('<i',buf,pos+3)[0]
                if dest in targets:
                    f=self.function(at)
                    refs.append({'instruction':hex(at),'target':hex(dest),'function':hex(f[0]) if f else None})
        return {'text':text,'targets':[hex(x) for x in targets],'xrefs':refs}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll',default='gamedll_ph_x64_rwdi.dll')
    ap.add_argument('--class-name',action='append',default=[])
    ap.add_argument('--xref',action='append',default=[])
    ap.add_argument('--disasm')
    ap.add_argument('--size',type=int,default=400)
    ap.add_argument('--output',type=Path)
    ap.add_argument('--exports',action='store_true')
    ap.add_argument('--quiet',action='store_true')
    args=ap.parse_args()
    img=Image(GAME/'ph_ft/work/bin/x64'/args.dll)
    result={'file':str(img.path),'image_base':hex(img.base),'vtables':[v for c in args.class_name for v in img.vtables(c)],'xrefs':[img.xrefs(t) for t in args.xref]}
    if args.disasm:result['disassembly']=img.disasm(int(args.disasm,0),args.size)
    if args.exports:result['exports']=img.exports()
    data=json.dumps(result,indent=2)
    if args.output:args.output.parent.mkdir(exist_ok=True,parents=True);args.output.write_text(data,encoding='utf8')
    if not args.quiet:print(data)

if __name__=='__main__':main()
