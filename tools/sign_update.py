"""Créer le manifeste de mise à jour signé pendant la publication Windows."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from update_trust import REPOSITORY, rsa_operation, verify_manifest, version_tuple


def sign(installer, version, output, key_xml):
    version_tuple(version)
    if installer.name != 'BetterAutoLoot-Setup-' + version + '.exe':
        raise ValueError('Installer filename differs from version')
    with installer.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'schema': 1, 'repository': REPOSITORY, 'version': version,
                'filename': installer.name, 'size': installer.stat().st_size, 'sha256': checksum}
    payload = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')
    signature = rsa_operation(payload, key_xml).encode('ascii')
    # Refuser une clé de publication qui ne correspond pas à la clé embarquée.
    verify_manifest(payload, signature, '0.0.0')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'update-manifest.json').write_bytes(payload)
    (output / 'update-manifest.sig').write_bytes(signature)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get('AUTOLOOT_UPDATE_SIGNING_KEY')
    if not key:
        raise SystemExit('Missing update signing key')
    sign(args.installer, args.version, args.output, key)
