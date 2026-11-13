"""Signatures réelles Windows et frontières du manifeste de mise à jour."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import update_trust as trust
import sign_update


@unittest.skipUnless(os.name == 'nt', 'Windows RSA platform required')
class UpdateTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        command = "$r=New-Object System.Security.Cryptography.RSACryptoServiceProvider(3072); @{private=$r.ToXmlString($true);public=$r.ToXmlString($false)}|ConvertTo-Json -Compress; $r.Dispose()"
        executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, check=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        cls.key = json.loads(result.stdout)

    def setUp(self):
        self.manifest = {'schema': 1, 'repository': trust.REPOSITORY, 'version': '1.4.0',
                         'filename': 'BetterAutoLoot-Setup-1.4.0.exe', 'size': 7,
                         'sha256': hashlib.sha256(b'payload').hexdigest()}
        self.public = patch.object(trust, 'PUBLIC_KEY_XML', self.key['public'])
        self.public.start()
        self.addCleanup(self.public.stop)

    def signed(self, manifest):
        payload = json.dumps(manifest).encode()
        signature = trust.rsa_operation(payload, self.key['private']).encode()
        return payload, signature

    def test_valid_signature_and_installer(self):
        manifest = trust.verify_manifest(*self.signed(self.manifest), '1.3.0')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / manifest['filename']
            path.write_bytes(b'payload')
            trust.verify_installer(path, manifest)
            path.write_bytes(b'payloaX')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                trust.verify_installer(path, manifest)
            path.write_bytes(b'longer payload')
            with self.assertRaisesRegex(ValueError, 'size'):
                trust.verify_installer(path, manifest)

    def test_payload_and_signature_tampering(self):
        payload, signature = self.signed(self.manifest)
        with self.assertRaises(ValueError):
            trust.verify_manifest(payload + b' ', signature, '1.3.0')
        raw = bytearray(base64.b64decode(signature))
        raw[0] ^= 1
        with self.assertRaises(ValueError):
            trust.verify_manifest(payload, base64.b64encode(raw), '1.3.0')

    def test_downgrade_and_same_version_refused(self):
        signed = self.signed(self.manifest)
        for installed in ('1.4.0', '2.0.0'):
            with self.subTest(installed=installed), self.assertRaisesRegex(ValueError, 'newer'):
                trust.verify_manifest(*signed, installed)

    def test_signed_invalid_fields_refused(self):
        changes = {'schema': True, 'repository': 'other/repository', 'filename': '../installer.exe',
                   'size': True, 'sha256': 'F' * 64, 'version': '1.04.0', 'extra': 'field'}
        for field, value in changes.items():
            candidate = dict(self.manifest, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                trust.verify_manifest(*self.signed(candidate), '1.3.0')

    def test_pinned_key_and_signer_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installer = root / self.manifest['filename']
            installer.write_bytes(b'payload')
            sign_update.sign(installer, '1.4.0', root, self.key['private'])
            parsed = trust.verify_manifest((root / 'update-manifest.json').read_bytes(),
                                           (root / 'update-manifest.sig').read_bytes(), '1.3.0')
            self.assertEqual(parsed, self.manifest)
            with patch.object(trust, 'PUBLIC_KEY_XML', '<RSAKeyValue/>'), self.assertRaises(ValueError):
                trust.verify_manifest(*self.signed(self.manifest), '1.3.0')


if __name__ == '__main__':
    unittest.main()
