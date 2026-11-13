"""Authentification des mises à jour par RSA/SHA-256 de Windows."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = 'Rhadamanthe0/dying-light-the-beast-autoloot'
PUBLIC_KEY_XML = '<RSAKeyValue><Modulus>3amHmy9nujmJ1vuAIKXgSP6iZuHNWvwYK+v5ca7e8FFRS+1HNx+69RohBe2YO6si5Uwi5w5yylZz6EC0ypExQDd2g4SOE98I+SJSKQ8t7MBImdUb/z0cQu6Kz+DmzGHStMQzk15zAfZclA80v55kp8ZZxijtqwoN2GS+wAksAaPVXDmPfOGhfPVU0QHtQD+v/rnti3I5PqsnWMcdhT2oVleoo16G4x0u7BXS9PLv4S7eshL+/zRCpRujagxC5wtcpTDtOPwS23PMJAQbPTNBtzFsF9TawAkiuOp72itK44/G346kAmSRzHVXE6yfsEZ25L+D3XYeepMYxgCjA8rJOIYjZYEvjoVpUsYFDxd4c3r/PbhvBDMZQpKDHPDOoNbCCDL3GMg8qO9RFrdqP7N+VWqUOW4806IJYg3cnC/LQ5hwTP7jw8KhobDTEytcsG9xNCbjf5P7C2eEwgjgvNpLcHrPmCLLRseiiTdSgEJinSyFuxqdfbjlIIYuTFEK1UtR</Modulus><Exponent>AQAB</Exponent></RSAKeyValue>'


def version_tuple(version):
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Invalid stable version')
    if len(version) > 32:
        raise ValueError('Version exceeds bound')
    return tuple(int(part) for part in version.split('.'))


def rsa_operation(payload, key_xml, signature=None):
    """Les octets et la clé passent par stdin, sans fichier ni argument secret."""
    operation = '''
$ErrorActionPreference='Stop'
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
$rsa=New-Object System.Security.Cryptography.RSACryptoServiceProvider
try {
 $rsa.FromXmlString($request.key)
 $data=[Convert]::FromBase64String($request.data)
 if ($request.signature) {
  $ok=$rsa.VerifyData($data,'SHA256',[Convert]::FromBase64String($request.signature))
  if (!$ok) { exit 3 }
  [Console]::Out.Write('verified')
 } else {
  [Console]::Out.Write([Convert]::ToBase64String($rsa.SignData($data,'SHA256')))
 }
} finally { $rsa.Dispose() }
'''
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    request = {'key': key_xml, 'data': base64.b64encode(payload).decode('ascii'), 'signature': signature}
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', operation],
                            input=json.dumps(request), text=True, encoding='utf-8', errors='replace', capture_output=True,
                            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError('RSA signature operation failed')
    return result.stdout.strip()


def verify_manifest(manifest_bytes, signature_bytes, current_version):
    if not isinstance(manifest_bytes, bytes) or not 1 <= len(manifest_bytes) <= 8192:
        raise ValueError('Manifest exceeds bound')
    if not isinstance(signature_bytes, bytes) or len(signature_bytes) > 2048:
        raise ValueError('Signature exceeds bound')
    try:
        signature = signature_bytes.decode('ascii').strip()
        if len(base64.b64decode(signature, validate=True)) != 384:
            raise ValueError('Unexpected RSA signature size')
        rsa_operation(manifest_bytes, PUBLIC_KEY_XML, signature)
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('Malformed update manifest') from error
    expected = {'schema', 'repository', 'version', 'filename', 'size', 'sha256'}
    if type(manifest) is not dict or set(manifest) != expected:
        raise ValueError('Unexpected manifest fields')
    if type(manifest['schema']) is not int or manifest['schema'] != 1 or manifest['repository'] != REPOSITORY:
        raise ValueError('Unexpected manifest identity')
    version = manifest['version']
    if version_tuple(version) <= version_tuple(current_version):
        raise ValueError('Update must be newer than installed version')
    if manifest['filename'] != 'BetterAutoLoot-Setup-' + version + '.exe':
        raise ValueError('Unexpected installer filename')
    if type(manifest['size']) is not int or not 1 <= manifest['size'] <= 512 * 1024 * 1024:
        raise ValueError('Installer size exceeds bound')
    if not isinstance(manifest['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', manifest['sha256']):
        raise ValueError('Unexpected installer hash')
    return manifest


def verify_installer(path, manifest):
    path = Path(path)
    if path.stat().st_size != manifest['size']:
        raise ValueError('Installer size differs')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != manifest['sha256']:
        raise ValueError('Installer checksum differs')
