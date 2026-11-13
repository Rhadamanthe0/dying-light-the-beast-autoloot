"""Discovery's real memory traversal with only OS/PE boundaries substituted."""
import ctypes as C
import importlib.util
import os
from pathlib import Path
import struct
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_discovery():
    image = ModuleType('inspect_native')
    image.Image = Mock()
    with patch.dict(sys.modules, {'inspect_native': image}):
        spec = importlib.util.spec_from_file_location('memory_discovery', ROOT/'tools/discover_session.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


D = load_discovery()


class MemoryAPI:
    def __init__(self):
        self.memory = {}
        self.pages = {}
        self.reads = []
        self.fail = self.partial = None
        self.after_read = None
        self.CloseHandle = Mock(return_value=True)
        self.OpenProcess = Mock(return_value=1)

    def put(self, address, data):
        self.memory.update((address+i, value) for i, value in enumerate(data))

    def q(self, address, value):
        self.put(address, struct.pack('<Q', value))

    def VirtualQueryEx(self, handle, address, info, size):
        page = address & ~0xfff
        info._obj.BaseAddress = page
        info._obj.RegionSize = 0x1000
        info._obj.State, info._obj.Protect = self.pages.get(page, (D.observer.MEM_COMMIT, 0x04))
        return size

    def ReadProcessMemory(self, handle, address, buf, size, count):
        self.reads.append((address, size))
        data = bytes(self.memory.get(address+i, 0) for i in range(size))
        C.memmove(buf, data, size)
        count._obj.value = size-1 if address == self.partial else size
        if self.after_read:
            self.after_read(address, size)
        return address != self.fail

    def GetExitCodeProcess(self, handle, code):
        code._obj.value = 259
        return True


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.api = MemoryAPI()
        self.reader = D.Reader(self.api, 1)

    def test_fully_readable_prefix_is_identical(self):
        data = bytes(range(256))*256
        self.api.put(0x10003, data)
        self.assertEqual(self.reader.readable_prefix(0x10003, len(data)), data)
        self.assertEqual(self.reader.bytes_requested, len(data))
        self.assertTrue(all(size <= 0x1000 and address//0x1000 == (address+size-1)//0x1000
                            for address, size in self.api.reads))

    def test_holes_preserve_offsets_and_pointers_after_hole(self):
        for state, protect in [(D.observer.MEM_COMMIT, 0x104), (0x2000, 0x04),
                               (D.observer.MEM_COMMIT, 0x01)]:
            with self.subTest(state=state, protect=protect):
                api = MemoryAPI()
                api.pages[0x11000] = (state, protect)
                api.q(0x10008, 0x30000)
                api.q(0x12008, 0x40000)
                result = D.Reader(api, 1).readable_prefix(0x10000, D.PLAYER_PREFIX_BYTES)
                self.assertEqual(D.pointer_values(result), {0x30000: [8], 0x40000: [0x2008]})
                self.assertEqual(result[0x1000:0x2000], bytes(0x1000))
                self.assertFalse(any(address == 0x11000 for address, _ in api.reads))

    def test_unaligned_straddles_cannot_form_partial_pointers(self):
        # The first fragment alone would decode as a false pointer 0x20000.
        self.api.pages[0x11000] = (D.observer.MEM_COMMIT, 0x01)
        self.api.put(0x10ffb, b'\x00\x00\x02\x00\x00')
        # A later readable page must not recreate the word touching the hole.
        self.api.put(0x12000, b'\x00\x00\x03\x00\x00')
        self.api.q(0x1200b, 0x40000)
        result = self.reader.readable_prefix(0x10003, D.PLAYER_PREFIX_BYTES)
        self.assertEqual(result[0xff8:0x1000], bytes(8))
        self.assertEqual(result[0x1ff8:0x2000], bytes(8))
        self.assertEqual(D.pointer_values(result), {0x40000: [0x2008]})

    def test_invalid_ranges_rejected_before_allocation(self):
        for address, size in [(0xffff, 8), (D.MAX_POINTER, 8), (D.MAX_POINTER-4, 8),
                              (0x10000, 0), (0x10000, -1),
                              (0x10000, D.PLAYER_PREFIX_BYTES+1), (0x10000, 10**30)]:
            with self.subTest(address=address, size=size), patch.object(D, 'bytearray', create=True) as allocate:
                with self.assertRaises(ValueError):
                    self.reader.readable_prefix(address, size)
                allocate.assert_not_called()
        self.assertEqual(self.reader.queries, 0)

    def test_required_read_remains_strict(self):
        self.api.pages[0x11000] = (D.observer.MEM_COMMIT, 0x01)
        with self.assertRaisesRegex(ValueError, 'Unreadable required range'):
            self.reader.read(0x10000, 0x2000)
        self.assertEqual(self.api.reads, [])

    def test_rpm_failure_and_partial_read_propagate(self):
        for field in ['fail', 'partial']:
            with self.subTest(field=field):
                api = MemoryAPI()
                setattr(api, field, 0x11000)
                with self.assertRaisesRegex(OSError, 'Failed or partial ReadProcessMemory'):
                    D.Reader(api, 1).readable_prefix(0x10000, 0x2000)

    def test_budgets_are_enforced(self):
        for field, value, message in [('bytes_requested', D.MAX_BYTES-0x1000, '8 MiB'),
                                      ('read_calls', D.MAX_READS-2, 'memory-read budget'),
                                      ('queries', D.MAX_READS-1, 'memory-query budget')]:
            with self.subTest(field=field):
                reader = D.Reader(MemoryAPI(), 1)
                setattr(reader, field, value)
                with self.assertRaisesRegex(RuntimeError, message):
                    reader.readable_prefix(0x10000, 0x3000)
        self.reader.started -= D.MEMORY_SECONDS
        with self.assertRaises(TimeoutError):
            self.reader.readable_prefix(0x10000, 8)

    def test_deadline_after_os_read_propagates(self):
        self.api.after_read = lambda *_: setattr(self.reader, 'started', self.reader.started-2)
        with self.assertRaises(TimeoutError):
            self.reader.readable_prefix(0x10000, 8)

    def test_deadline_with_only_unreadable_pages(self):
        self.api.pages[0x10000] = (0, 0)
        query = self.api.VirtualQueryEx
        def expired(*args):
            result = query(*args)
            self.reader.started -= 2
            return result
        self.api.VirtualQueryEx = expired
        with self.assertRaises(TimeoutError):
            self.reader.readable_prefix(0x10000, 8)


class DiscoveryMemoryTests(unittest.TestCase):
    def setUp(self):
        self.api = MemoryAPI()
        self.base, self.game, self.level, self.client = 0x10000000, 0x300000, 0x310000, 0x320000
        self.player, self.host, self.registry, self.data, self.trigger = 0x500000, 0x600000, 0x610000, 0x620000, 0x630000
        self.proof = {'profile_id':'1.7.1.0na','runtime_live_allowed':True,
                      'images': {'game': {'path': str(ROOT/'fake'/D.GAME_DLL),'sha256':D.HASHES['game']},
                                 'engine':{'sha256':D.HASHES['engine']}},
                      'guarded_prologues': [{'name': 'guard', 'rva': 0x1000, 'hex': 'c3'}],
                      'discovery_prologues': [], 'vtables': {}, 'game_global_rva': '0x2000',
                      'chain': {'trigger_owner_getter_rva':'0x17f800'}, 'limits': []}
        self.api.put(self.base+0x1000, b'\xc3')
        for i, (key, rva) in enumerate(D.VTABLE_RVAS.items()):
            table = {'class': key, 'rva': rva, 'col_rva': 0x3000+i*0x100,
                     'col_hex': '00'*24, 'first_eight_function_rvas': list(range(0x4000, 0x4040, 8)),
                     'type_descriptor_rva': 0x5000+i*0x100, 'rtti_name': key}
            self.proof['vtables'][key] = table
            self.api.q(self.base+rva-8, self.base+table['col_rva'])
            for offset, function in enumerate(table['first_eight_function_rvas']):
                self.api.q(self.base+rva+offset*8, self.base+function)
            self.api.put(self.base+table['type_descriptor_rva']+16, key.encode()+b'\0')
        for address, value in [(self.base+D.VTABLE_RVAS['trigger']+0x4a8, self.base+0x17f800),
                               (self.base+0x2000, self.game), (self.game, self.base+D.VTABLE_RVAS['game']),
                               (self.game+0x138, self.level), (self.level+0xec8, self.client),
                               (self.client+0x88, 1), (self.client+0x90, self.player),
                               (self.player, self.base+D.VTABLE_RVAS['player']),
                               (self.player+0x200, self.host), (self.host+0x1c8, self.registry),
                               (self.registry+0x1d8, self.data), (self.data, self.trigger),
                               (self.trigger, self.base+D.VTABLE_RVAS['trigger']), (self.trigger+8, self.player)]:
            self.api.q(address, value)
        self.api.put(self.registry+0x1e0, struct.pack('<I', 1))
        self.api.pages[self.player+0x1000] = (D.observer.MEM_COMMIT, 0x104)
        modules = [{'name': name, 'path': str(ROOT/'fake'/name), 'base': hex(self.base), 'size': 0x4000000}
                   for name in [D.GAME_DLL, D.ENGINE_DLL, D.EXE]]
        patches = [patch.object(D, 'prepare_static', return_value=self.proof),
                   patch.object(D, 'api_setup', return_value=self.api),
                   patch.object(D, 'process_ids', return_value=[42]),
                   patch.object(D, 'creation_time', return_value='123'),
                   patch.object(D, 'digest', side_effect=lambda path: D.HASHES['game'] if Path(path).name == D.GAME_DLL else D.HASHES['engine']),
                   patch.object(D.observer, 'modules', return_value=modules)]
        for context in patches:
            context.start()
            self.addCleanup(context.stop)

    def test_optional_hole_reaches_native_vector_and_rechecks(self):
        result = D.discover(42)
        self.assertTrue(result['ready'])
        self.assertEqual(result['objects']['trigger']['native_vector_indices'], [0])
        self.assertEqual(result['objects']['trigger']['player_field_offsets'], [])
        self.assertGreaterEqual(self.api.reads.count((self.client+0x90, 8)), 2)
        self.assertGreaterEqual(self.api.reads.count((self.host+0x1c8, 8)), 2)
        self.assertGreaterEqual(self.api.reads.count((self.trigger+8, 8)), 2)
        self.api.CloseHandle.assert_called_once_with(1)

    def test_direct_pointer_after_hole_keeps_original_offset(self):
        self.api.q(self.player+0x2010, self.trigger)
        result = D.discover(42)
        self.assertEqual(result['objects']['trigger']['player_field_offsets'], ['0x2010'])

    def test_required_host_vector_and_player_pages_still_refuse(self):
        for page in [self.host, self.data, self.player]:
            with self.subTest(page=hex(page)):
                self.api.pages[page] = (D.observer.MEM_COMMIT, 0x01)
                with self.assertRaisesRegex(ValueError, 'Unreadable required range'):
                    D.discover(42)
                del self.api.pages[page]

    def test_wrong_owner_or_class_refuses_readiness(self):
        for address in [self.trigger, self.trigger+8]:
            with self.subTest(address=address):
                original = bytes(self.api.memory[address+i] for i in range(8))
                self.api.q(address, 0xdead0000)
                with self.assertRaisesRegex(ValueError, 'Expected one exact owned TriggerController'):
                    D.discover(42)
                self.api.put(address, original)

    def test_chain_and_trigger_changes_refuse_readiness(self):
        for address, message in [(self.client+0x88, 'chain changed'), (self.trigger+8, 'identity changed'),
                                  (self.registry+0x1d8, 'vector changed')]:
            with self.subTest(address=hex(address)):
                original = bytes(self.api.memory[address+i] for i in range(8))
                # Change after capturing the initial owner, before final identity checks.
                self.api.after_read = lambda current, size: self.api.q(address, 0x700000) if current == self.trigger+8 else None
                with self.assertRaisesRegex(ValueError, message):
                    D.discover(42)
                self.api.after_read = None
                self.api.put(address, original)


@unittest.skipUnless(os.name == 'nt', 'Windows memory protection contract')
class WindowsMemoryTests(unittest.TestCase):
    def test_real_noaccess_page_is_optional_but_required_read_refuses(self):
        api = D.observer.windows_api()
        api.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, D.W.DWORD, D.W.DWORD]
        api.VirtualAlloc.restype = C.c_void_p
        api.VirtualProtect.argtypes = [C.c_void_p, C.c_size_t, D.W.DWORD, C.POINTER(D.W.DWORD)]
        api.VirtualProtect.restype = D.W.BOOL
        api.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, D.W.DWORD]
        api.VirtualFree.restype = D.W.BOOL
        allocation = api.VirtualAlloc(None, D.PLAYER_PREFIX_BYTES, 0x3000, 0x04)
        self.assertTrue(allocation, 'VirtualAlloc failed')
        self.addCleanup(api.VirtualFree, allocation, 0, 0x8000)
        handle = api.OpenProcess(D.observer.PROCESS_ACCESS, False, os.getpid())
        self.assertTrue(handle, 'OpenProcess failed')
        self.addCleanup(api.CloseHandle, handle)
        C.memmove(allocation+0x2008, struct.pack('<Q', allocation), 8)
        old = D.W.DWORD()
        self.assertTrue(api.VirtualProtect(allocation+0x1000, 0x1000, 0x01, C.byref(old)))
        reader = D.Reader(api, handle)
        prefix = reader.readable_prefix(allocation, D.PLAYER_PREFIX_BYTES)
        self.assertEqual(D.pointer_values(prefix), {allocation: [0x2008]})
        self.assertEqual(prefix[0x1000:0x2000], bytes(0x1000))
        with self.assertRaisesRegex(ValueError, 'Unreadable required range'):
            reader.read(allocation, D.PLAYER_PREFIX_BYTES)


if __name__ == '__main__':
    unittest.main()
