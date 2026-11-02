"""RTTI resolution reads synthetic local PE bytes, never a process."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from inspect_native import Image


class ClassNameTests(unittest.TestCase):
    def image(self):
        image = Image.__new__(Image)
        image.base = 0x100000
        image.offset = lambda rva: rva if 0 <= rva < 512 else 1024
        data = bytearray(512)
        struct.pack_into('<Q', data, 56, image.base + 128)
        struct.pack_into('<6I', data, 128, 1, 0, 0, 256, 0, 128)
        data[272:293] = b'.?AVContainerItem@@\0xx'
        image.data = bytes(data)
        return image

    def test_class_name_and_invalid_rva(self):
        image = self.image()
        self.assertEqual(image.class_name(64), '.?AVContainerItem@@')
        self.assertIsNone(image.class_name(0))
        self.assertIsNone(image.class_name(10000))

    def test_rejects_invalid_complete_object_locator(self):
        image = self.image()
        data = bytearray(image.data)
        struct.pack_into('<I', data, 148, 129)
        image.data = bytes(data)
        self.assertIsNone(image.class_name(64))
