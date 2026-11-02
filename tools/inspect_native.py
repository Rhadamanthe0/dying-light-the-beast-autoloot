"""Read-only PE inspection. Never opens a game process or changes game files."""
import bisect
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


    def class_name(self, vtable_rva):
        """Resolve an MSVC RTTI name from a local PE, never from game memory."""
        try:
            col_va = struct.unpack_from('<Q', self.data, self.offset(vtable_rva - 8))[0]
            col_rva = col_va - self.base
            col = self.offset(col_rva)
            signature, _, _, descriptor, _, self_rva = struct.unpack_from('<6I', self.data, col)
            if signature != 1 or self_rva != col_rva:
                return None
            start = self.offset(descriptor) + 16
            end = self.data.find(b'\0', start, start + 256)
            if end < 0:
                return None
            name = self.data[start:end].decode('ascii')
            return name if name.startswith(('.?AV', '.?AU')) else None
        except (ValueError, OverflowError, struct.error, UnicodeDecodeError, pefile.PEFormatError):
            return None


if __name__ == '__main__':
    import argparse
    import hashlib
    import json
    parser = argparse.ArgumentParser(description='Resolve candidate classes from a runtime report; reads local files only.')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    image = Image(GAME / 'ph_ft/work/bin/x64/gamedll_ph_x64_rwdi.dll')
    report = json.loads(args.report.read_text(encoding='utf-8-sig'))
    samples = []
    def visit(value):
        if isinstance(value, dict):
            for sample in value.get('candidate_diagnostics', []):
                row = dict(sample)
                rva = row.get('vtable_rva')
                row['class_name'] = image.class_name(int(rva, 16)) if rva else None
                if row not in samples:
                    samples.append(row)
            for key, child in value.items():
                if key != 'candidate_diagnostics':
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(report)
    print(json.dumps({'game_sha256': hashlib.sha256(image.data).hexdigest(),
                      'candidate_diagnostics': samples}, indent=2))
