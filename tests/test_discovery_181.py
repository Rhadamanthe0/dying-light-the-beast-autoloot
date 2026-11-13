"""Refus statiques de correspondances absentes, ambiguës ou mal formées."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from discovery_181 import unique, exact_table, guard_function, exported


class Discovery181Tests(unittest.TestCase):
    def test_primary_table_must_be_unique_and_exact(self):
        primary = {'subobject_offset': 0, 'vtable_rva': '0x100'}
        secondary = {'subobject_offset': 8, 'vtable_rva': '0x180'}
        image = SimpleNamespace(vtables=lambda name: [primary, secondary])
        self.assertEqual(exact_table(image, 'Known', 0, 0x100), primary)
        for tables in ([], [primary, primary]):
            image.vtables = lambda name: tables
            with self.subTest(tables=tables), self.assertRaises(ValueError):
                exact_table(image, 'Known', 0, 0x100)
        image.vtables = lambda name: [primary]
        with self.assertRaises(ValueError):
            exact_table(image, 'Known', 0, 0x101)

    def test_prefix_ambiguity_and_nonentry_are_refused(self):
        image = SimpleNamespace(data=b'\x90\xc3\0\0', offset=lambda rva: rva,
                                function=lambda rva: (rva, rva + 1, 0))
        self.assertEqual(guard_function(image, 'Known', 1, 'c3', True, True)['rva'], 1)
        image.data = b'\x90\xc3\xc3\0'
        with self.assertRaisesRegex(ValueError, 'ambigu'):
            guard_function(image, 'Known', 1, 'c3', True, True)
        image.data = b'\x90\xc3\0\0'
        image.function = lambda rva: (0, 2, 0)
        with self.assertRaises(ValueError):
            guard_function(image, 'Known', 1, 'c3', True, True)
        image.function = lambda rva: None
        with self.assertRaises(ValueError):
            guard_function(image, 'Known', 1, 'c3', True, True)

    def export_image(self, count=1, ordinal=0, target=0x300):
        data = bytearray(2048)
        struct.pack_into('<5I', data, 0x100 + 20, 1, count, 0x200, 0x220, 0x240)
        struct.pack_into('<I', data, 0x200, target)
        for index in range(count):
            struct.pack_into('<I', data, 0x220 + 4 * index, 0x280)
            struct.pack_into('<H', data, 0x240 + 2 * index, ordinal)
        data[0x280:0x286] = b'Known\0'
        directory = SimpleNamespace(VirtualAddress=0x100, Size=0x40)
        return SimpleNamespace(data=bytes(data), offset=lambda rva: rva,
                               pe=SimpleNamespace(OPTIONAL_HEADER=SimpleNamespace(DATA_DIRECTORY=[directory])))

    def test_exports_require_unique_name_valid_ordinal_and_no_forwarder(self):
        self.assertEqual(exported(self.export_image(), 'Known'), 0x300)
        for image, name in [(self.export_image(), 'Missing'), (self.export_image(count=2), 'Known'),
                            (self.export_image(ordinal=1), 'Known'), (self.export_image(target=0x110), 'Known')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                exported(image, name)


if __name__ == '__main__':
    unittest.main()
