"""Build, verify, install, activate and roll back local immutable Prism releases."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from shared.instance import instance_lock

VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?\Z')
MAX_BYTES = 250_000_000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_version(version):
    if not isinstance(version,str) or len(version)>64 or not VERSION.fullmatch(version):
        raise ValueError('Use a version such as 1.0.0 or 1.0.0-rc.1')
    return version


def safe_name(name):
    path = PurePosixPath(name)
    reserved = {'con','prn','aux','nul',*(f'com{i}' for i in range(1,10)),*(f'lpt{i}' for i in range(1,10))}
    return bool(name and not any(c in name for c in '\\:*?<>|"\x00') and not path.is_absolute()
                and all(p not in {'.','..',''} and not p.endswith(('.', ' ')) and p.split('.')[0].lower() not in reserved for p in name.split('/')))


def source_files(root):
    files = []
    for directory in ('backend','perception','shared','scripts'):
        files.extend(p for p in (root/directory).rglob('*.py') if '__pycache__' not in p.parts)
    files.extend((root/'docs').glob('*.md'))
    files.extend(p for p in (root/'frontend/dist').rglob('*') if p.is_file())
    files.extend(root/p for p in ['README.md','.env.example','requirements.txt',
        'config/requirements/bootstrap.lock','config/requirements/runtime.lock','sandbox/Dockerfile','sandbox/requirements.lock','sandbox/.dockerignore','sandbox/patch_npm.py',
        'frontend/package.json','frontend/package-lock.json','frontend/THIRD_PARTY_NOTICES.txt',
        'docs/THIRD_PARTY_PYTHON_NOTICES.txt'])
    result = {}
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Missing or linked release input: {path.relative_to(root)}')
        result[path.relative_to(root).as_posix()] = path.read_bytes()
    if 'frontend/dist/index.html' not in result:
        raise ValueError('Build the frontend before packaging')
    return result


def pack(root, version, output, sandbox_digest):
    validate_version(version)
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',sandbox_digest):
        raise ValueError('Record the actual sandbox image digest')
    files = dict(source_files(root))
    hashes = {name:digest(data) for name,data in sorted(files.items())}
    revision = digest(json.dumps(hashes,sort_keys=True).encode())
    manifest = {'version':version,'source_tree_sha256':revision,'sandbox_image':sandbox_digest,'files':hashes}
    files['release.json'] = (json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    # No overwriting an existing immutable version artifact.
    with output.open('xb') as stream, zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()):
            entry = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(entry,data)
    return manifest


def verified_payload(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries)>5000 or len(names)!=len(set(names)) or sum(e.file_size for e in entries)>MAX_BYTES:
            raise ValueError('Invalid archive size or duplicate entries')
        if any(not safe_name(e.filename) or stat.S_ISLNK(e.external_attr >> 16) or e.file_size>64_000_000 for e in entries):
            raise ValueError('Unsafe archive entry')
        if 'release.json' not in names or archive.getinfo('release.json').file_size>2_000_000:
            raise ValueError('Missing release manifest')
        manifest = json.loads(archive.read('release.json'))
        validate_version(manifest['version'])
        if set(names) != set(manifest['files']) | {'release.json'}:
            raise ValueError('Archive and manifest disagree')
        payload = {'release.json':archive.read('release.json')}
        for name,expected in manifest['files'].items():
            data = archive.read(name)
            if digest(data) != expected:
                raise ValueError('Release integrity check failed: '+name)
            payload[name] = data
        return manifest,payload


def verify_archive(path):
    return verified_payload(path)[0]


def python_path(release):
    return release/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def create_environment(release):
    if sys.version_info[:2] != (3,11):
        raise ValueError('Install releases with Python 3.11')
    venv.EnvBuilder(with_pip=True).create(release/'.venv')
    for lock in ['config/requirements/bootstrap.lock','requirements.txt']:
        subprocess.run([str(python_path(release)),'-m','pip','install','--disable-pip-version-check',
            '--require-hashes','-r',str(release/lock)],check=True)


def install(archive_path, home):
    home = home.resolve()
    manifest,payload = verified_payload(archive_path)
    target = home/'releases'/manifest['version']
    target.parent.mkdir(parents=True,exist_ok=True)
    target.mkdir()  # Existing releases, including failed attempts, are never overwritten.
    for name,data in payload.items():
        path = target.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    # A failed install is left for diagnosis and cannot be activated.
    create_environment(target)
    (target/'.installed.json').write_text(json.dumps({'manifest_sha256':digest((target/'release.json').read_bytes())}))
    config = home/'config.env'
    if not config.exists():
        workspace = home/'workspace'
        workspace.mkdir(parents=True,exist_ok=True)
        example = (target/'.env.example').read_text(encoding='utf-8')
        example = re.sub(r'^ALLOWED_ROOT=.*$', 'ALLOWED_ROOT='+workspace.as_posix(), example, flags=re.M)
        example = re.sub(r'^APPROVAL_SECRET=.*$', 'APPROVAL_SECRET='+secrets.token_urlsafe(48), example, flags=re.M)
        example += '\nSTATE_DIR='+ (home/'state').as_posix()+'\n'
        with config.open('x',encoding='utf-8') as stream:
            stream.write(example)
        if os.name != 'nt':
            config.chmod(0o600)
    return target


def verify_installed(home, version):
    target = home/'releases'/validate_version(version)
    if target.is_symlink() or not python_path(target).is_file():
        raise ValueError('Release runtime is not installed')
    manifest_bytes = (target/'release.json').read_bytes()
    record = json.loads((target/'.installed.json').read_text())
    if record['manifest_sha256'] != digest(manifest_bytes):
        raise ValueError('Installed manifest changed')
    manifest = json.loads(manifest_bytes)
    for name,expected in manifest['files'].items():
        if not safe_name(name):
            raise ValueError('Invalid installed path')
        path = target.joinpath(*PurePosixPath(name).parts)
        if path.is_symlink() or not path.resolve().is_relative_to(target.resolve()) or digest(path.read_bytes()) != expected:
            raise ValueError('Installed release changed: '+name)
    return target


def activate(home, version=None, rollback=False):
    home = home.resolve()
    with instance_lock(home/'state'):
        pointer = home/'current.json'
        previous = json.loads(pointer.read_text()) if pointer.exists() else {}
        version = previous.get('previous') if rollback else version
        verify_installed(home,validate_version(version))
        current = previous.get('current')
        if current == version:
            return version
        descriptor,name = tempfile.mkstemp(prefix='current-',suffix='.tmp',dir=home)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                json.dump({'current':version,'previous':current},stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name,pointer)
        finally:
            Path(name).unlink(missing_ok=True)
        return version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    build = sub.add_parser('pack')
    build.add_argument('--version',required=True)
    build.add_argument('--output',type=Path,required=True)
    build.add_argument('--sandbox-image',default='prism-sandbox:local')
    verify = sub.add_parser('verify')
    verify.add_argument('archive',type=Path)
    for command in ['install','activate','rollback','run']:
        action = sub.add_parser(command)
        action.add_argument('--home',type=Path,required=True)
        if command == 'install': action.add_argument('archive',type=Path)
        if command == 'activate': action.add_argument('version')
        if command == 'run': action.add_argument('--no-browser',action='store_true')
    args = parser.parse_args()
    if args.command == 'pack':
        result = subprocess.run(['docker','image','inspect','--format','{{.Id}}',args.sandbox_image],capture_output=True,text=True,check=True)
        pack(ROOT,args.version,args.output,result.stdout.strip())
        print('Built',args.output,'sha256:'+digest(args.output.read_bytes()))
    elif args.command == 'verify':
        print('Verified release',verify_archive(args.archive)['version'])
    elif args.command == 'install':
        print('Installed',install(args.archive,args.home))
    elif args.command in {'activate','rollback'}:
        print('Active release',activate(args.home,getattr(args,'version',None),args.command=='rollback'))
    else:
        home = args.home.resolve()
        pointer = json.loads((home/'current.json').read_text())
        target = verify_installed(home,pointer['current'])
        manifest = json.loads((target/'release.json').read_text())
        env = {**os.environ,'PRISM_ENV_FILE':str(home/'config.env'),'SANDBOX_IMAGE':manifest['sandbox_image']}
        result = subprocess.run([str(python_path(target)),str(target/'scripts/run_backend.py'),*(['--no-browser'] if args.no_browser else [])],cwd=target,env=env)
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
