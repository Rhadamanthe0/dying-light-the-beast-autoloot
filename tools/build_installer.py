"""Build a self-contained Windows installer; never installs or starts AutoLoot.

Build-time Python needs pip. End users need only the resulting setup EXE.
Every stage is new and qualified with its own embedded Python before packaging.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.1.0'
PYTHON_VERSION = '3.14.7'
PYTHON_EMBED_URL = 'https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip'
PYTHON_EMBED_SHA256 = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'
PACKAGES = {'frida': '17.24.0', 'pefile': '2024.8.26', 'capstone': '5.0.9'}
TOOLS = ('autoloot_runtime.py', 'autoloot_runtime.js', 'autoloot_runtime.c',
         'autoloot_runtime_fixture.py', 'autoloot_runtime_fixture.js', 'autoloot_watch.py',
         'runtime_paths.py', 'runtime_control.py', 'game_paths.py', 'discover_session.py',
         'inspect_native.py', 'observe_runtime.py', 'manage.ps1', 'control.py')
FILES = ('README.md', 'requirements.txt', 'autoloot.local.example.json')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(path, expected):
    actual = digest(path)
    if actual != expected:
        raise ValueError('SHA256 mismatch for ' + str(path) + ': ' + actual)


def download(url, target, expected=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if expected:
            verify(target, expected)
        return target
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'BetterAutoLoot-InstallerBuilder/1.1.0'})
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open('xb') as output:
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 512 * 1024 * 1024:
                raise ValueError('Download exceeded the 512 MiB archive bound')
            output.write(chunk)
    if expected:
        verify(temporary, expected)
    os.replace(temporary, target)
    return target


def inside(root, target):
    root, target = root.resolve(), target.resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError('Refusing a path outside the owned staging directory: ' + str(target))
    return target


def extract_zip(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > 50000 or sum(item.file_size for item in members) > 1024**3:
            raise ValueError('Archive exceeds extraction bounds')
        for item in members:
            name = PurePosixPath(item.filename.replace('\\', '/'))
            if name.is_absolute() or '..' in name.parts or any(':' in part for part in name.parts) or \
                    stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Unsafe archive entry: ' + item.filename)
            target = inside(destination, destination.joinpath(*name.parts))
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                if target.exists():
                    raise ValueError('Archive collision: ' + str(target))
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as input_file, target.open('xb') as output:
                    shutil.copyfileobj(input_file, output)


def run(command, log, timeout=600, *, env=None, cwd=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('wb') as output:
        result = subprocess.run([str(value) for value in command], cwd=str(cwd or ROOT), env=env, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode


def wheel_files(downloads, logs, report):
    releases = {}
    for name, version in PACKAGES.items():
        url = 'https://pypi.org/pypi/' + name + '/' + version + '/json'
        path = download(url, downloads / 'pypi' / (name + '-' + version + '.json'))
        metadata = json.loads(path.read_text(encoding='utf-8'))
        if metadata['info']['version'] != version or metadata['info']['name'].casefold() != name.casefold():
            raise ValueError('Unexpected PyPI release metadata for ' + name)
        for item in metadata['urls']:
            if item['packagetype'] == 'bdist_wheel':
                releases[item['filename']] = (name, item['digests']['sha256'])
    cache = downloads / 'wheels'
    cache.mkdir(parents=True, exist_ok=True)
    # Do not let a corrupted cached wheel reach pip's candidate finder.
    for path in cache.glob('*.whl'):
        if path.name in releases:
            verify(path, releases[path.name][1])
    selected = downloads / ('wheel-selection-' + uuid.uuid4().hex)
    selected.mkdir()
    command = [sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check', '--no-deps',
               '--only-binary=:all:', '--platform', 'win_amd64', '--python-version', '314',
               '--implementation', 'cp', '--abi', 'cp314', '--abi', 'abi3',
               '--index-url', 'https://pypi.org/simple', '--find-links', cache, '--dest', selected]
    command.extend(name + '==' + version for name, version in PACKAGES.items())
    if run(command, logs / 'pip-download.log'):
        raise RuntimeError('Wheel download failed; see ' + str(logs / 'pip-download.log'))
    result, found = [], set()
    for path in sorted(selected.glob('*.whl')):
        if path.name not in releases:
            raise ValueError('Downloaded wheel is absent from pinned-release PyPI metadata: ' + path.name)
        name, expected = releases[path.name]
        if name in found:
            raise ValueError('Multiple wheels selected for ' + name)
        verify(path, expected)
        target = cache / path.name
        if target.exists():
            verify(target, expected)
            path.unlink()
        else:
            path.rename(target)
        result.append(target)
        found.add(name)
        report.setdefault('wheels', []).append({'package': name, 'version': PACKAGES[name],
                                               'filename': target.name, 'sha256': expected})
    selected.rmdir()
    if found != set(PACKAGES):
        raise ValueError('Expected exactly the three pinned runtime distributions')
    return result


PROBE = r'''
import json,sys
from pathlib import Path
try:
 import unittest.mock,frida,capstone,pefile,ordlookup,runtime_paths
 from importlib.metadata import version
 root=Path(sys.executable).resolve().parent
 bundle=root.parent
 assert sys.flags.isolated==1,sys.flags
 assert all(Path(entry).resolve().is_relative_to(bundle) for entry in sys.path),sys.path
 assert not any(".venv" in Path(entry).parts for entry in sys.path),sys.path
 assert Path(runtime_paths.__file__).resolve().is_relative_to(bundle),runtime_paths.__file__
 assert sys.version_info[:3]==(3,14,7),sys.version
 assert frida.__version__=='17.24.0'
 assert version('capstone')=='5.0.9',version('capstone')
 assert pefile.__version__=='2024.8.26'
 for module in (frida,frida._frida,capstone,pefile,ordlookup,unittest):
  assert Path(module.__file__).resolve().is_relative_to(root),module.__file__
 assert Path(capstone._cs._name).resolve().is_relative_to(root),capstone._cs._name
 assert next(capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64).disasm(b'\xc3',0)).mnemonic=='ret'
 print(json.dumps({'passed':True,'version':sys.version,'executable':sys.executable,'sys_path':sys.path,'versions':{name:version(name) for name in ('frida','capstone','pefile')},'capstone_binding_version':capstone.__version__,'capstone_native_version':capstone.cs_version(),'capstone_library':capstone._cs._name}))
except ModuleNotFoundError as error:
 print(json.dumps({'missing':error.name,'error':str(error)}));sys.exit(2)
except Exception as error:
 print(json.dumps({'error':type(error).__name__+': '+str(error)}));sys.exit(1)
'''


def qualify(stage, downloads, logs, report):
    python = stage / 'runtime/python.exe'
    system_root=os.environ.get('SystemRoot',r'C:\Windows')
    env=dict(os.environ, PATH=str(Path(system_root)/'System32'), SystemRoot=system_root,
             PYTHONHOME=str(logs/'poison-python-home'), PYTHONPATH=str(logs/'poison-python-path'))
    report['isolated_environment']={'path':'Windows System32 only','pythonhome':'deliberately invalid','pythonpath':'deliberately invalid','cwd':'build logs directory'}
    log=logs/'embedded-import.log'
    code=run([python,'-B','-c',PROBE],log,timeout=60,env=env,cwd=logs)
    result=None
    for line in reversed(log.read_text(encoding='utf-8',errors='replace').splitlines()):
        try:
            result=json.loads(line)
            break
        except ValueError:
            pass
    if code!=0 or not isinstance(result,dict) or result.get('passed') is not True:
        raise RuntimeError('Embedded import check failed; see '+str(log))
    report['embedded_imports']=result
    print('Qualifying embedded runtime with an owned dummy child only...', flush=True)
    log = logs / 'embedded-dummy.log'
    if run([python, '-B', stage / 'tools/autoloot_runtime.py', '--dummy'], log, timeout=300, env=env, cwd=logs):
        raise RuntimeError('Embedded native qualification failed; see ' + str(log))
    proof_file = stage / 'evidence/autoloot-runtime-dummy.json'
    proof = json.loads(proof_file.read_text(encoding='utf-8'))
    if proof.get('passed') is not True or len(proof.get('cases', [])) != 64 or not proof.get('host_tests', {}).get('passed') or \
            proof.get('core_sha256') != digest(stage / 'tools/autoloot_runtime.c') or \
            proof.get('fixture_sha256') != digest(stage / 'tools/autoloot_runtime_fixture.js'):
        raise ValueError('Embedded qualification evidence does not match the staged sources')
    shutil.copy2(proof_file, logs / 'native-qualification.json')
    report['native_qualification'] = {'passed': True, 'cases': len(proof['cases']),
                                      'host_tests_passed': True, 'core_sha256': proof['core_sha256'],
                                      'fixture_sha256': proof['fixture_sha256']}


def clean_generated(stage):
    # Stage is a newly created UUID directory. Never remove source/user data.
    for target in list(stage.rglob('__pycache__')):
        shutil.rmtree(inside(stage, target))
    evidence = stage / 'evidence'
    if evidence.exists():
        shutil.rmtree(inside(stage, evidence))
    if any(stage.rglob('*.pyc')) or (stage / '.venv').exists() or (stage / '.deps').exists():
        raise ValueError('Generated caches or source environments remain in payload')


def build(args):
    if os.name != 'nt':
        raise RuntimeError('Build and native qualification require a Windows host')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    downloads = ROOT / '.build/downloads'
    stage = ROOT / '.build/payload' / stamp
    logs = ROOT / '.build/reports' / stamp
    stage.mkdir(parents=True, exist_ok=False)
    logs.mkdir(parents=True, exist_ok=False)
    output = ROOT / 'dist'
    report = {'version': VERSION, 'python_version': PYTHON_VERSION, 'stage': str(stage), 'logs': str(logs),
              'stage_only': args.stage_only, 'game_access': False, 'installed': False, 'passed': False}
    try:
        print('Staging standalone payload: ' + str(stage), flush=True)
        for name in TOOLS:
            source = ROOT / 'tools' / name
            target = stage / 'tools' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for name in FILES:
            shutil.copy2(ROOT / name, stage / name)
        report['source_files']={str(path.relative_to(stage)):digest(path) for path in stage.rglob('*') if path.is_file()}
        embed = download(PYTHON_EMBED_URL, downloads / 'python-3.14.7-embed-amd64.zip', PYTHON_EMBED_SHA256)
        extract_zip(embed, stage / 'runtime')
        report['python_embed_sha256'] = PYTHON_EMBED_SHA256
        for wheel in wheel_files(downloads, logs, report):
            extract_zip(wheel, stage / 'runtime/Lib/site-packages')
        (stage / 'runtime/python314._pth').write_text('python314.zip\n.\nLib/site-packages\n../tools\n', encoding='ascii')
        with zipfile.ZipFile(stage / 'runtime/python314.zip') as stdlib:
            report['embed_includes_unittest'] = any(name.startswith('unittest/') for name in stdlib.namelist())
        qualify(stage, downloads, logs, report)
        clean_generated(stage)
        if not args.stage_only:
            compiler = args.iscc.resolve()
            if not compiler.is_file():
                raise FileNotFoundError('Inno Setup compiler not found: ' + str(compiler))
            output.mkdir(parents=True, exist_ok=True)
            log = logs / 'iscc.log'
            command = [compiler, '/DPayloadDir=' + str(stage), '/DOutputDir=' + str(output),
                       '/DAppVersion=' + VERSION, ROOT / 'installer/autoloot.iss']
            print('Compiling installer; log: ' + str(log), flush=True)
            if run(command, log, timeout=600):
                raise RuntimeError('Installer compilation failed; see ' + str(log))
            installer = output / ('BetterAutoLoot-Setup-' + VERSION + '.exe')
            if not installer.is_file():
                raise FileNotFoundError('Compiler did not produce the expected setup executable')
            report['installer'] = str(installer)
            report['installer_sha256'] = digest(installer)
            report['installer_bytes'] = installer.stat().st_size
        report['passed'] = True
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        path = logs / 'build-report.json'
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'stage': str(stage), 'report': str(path),
                          'installer': report.get('installer'), 'error': report.get('error')}), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, help='Path to a trusted Inno Setup ISCC.exe')
    parser.add_argument('--stage-only', action='store_true', help='Build and qualify a payload without compiling setup')
    args = parser.parse_args()
    if not args.stage_only and args.iscc is None:
        parser.error('--iscc is required unless --stage-only is used')
    return build(args)


if __name__ == '__main__':
    raise SystemExit(main())
