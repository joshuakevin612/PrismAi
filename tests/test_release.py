"""Release integrity, clean extraction, persistent state, and rollback regressions."""
import json
from pathlib import Path
import zipfile
import pytest
from scripts import release
from shared.instance import instance_lock


@pytest.fixture
def archives(tmp_path, monkeypatch):
    source = tmp_path/'source'
    source.mkdir()
    files = {'backend/main.py':b'# synthetic release\n', 'frontend/dist/index.html':b'<html>unchanged UI</html>',
        '.env.example':b'ALLOWED_ROOT=./demo-workspace\nAPPROVAL_SECRET=replace-with-a-random-local-secret\nNVIDIA_API_KEY=\n'}
    monkeypatch.setattr(release,'source_files',lambda root:files)
    def runtime(target):
        python = release.python_path(target)
        python.parent.mkdir(parents=True)
        python.write_bytes(b'synthetic-runtime')
    monkeypatch.setattr(release,'create_environment',runtime)
    paths = []
    for version in ['1.0.0','1.0.1']:
        output = tmp_path/(version+'.zip')
        release.pack(source,version,output,'sha256:'+'a'*64)
        paths.append(output)
    return paths


def test_install_activate_rollback_preserves_external_configuration(tmp_path, archives):
    home = tmp_path/'installed'
    for archive in archives:
        release.install(archive,home)
    configuration = home/'config.env'
    before = configuration.read_bytes()
    assert 'ALLOWED_ROOT='+ (home/'workspace').as_posix() in before.decode()
    assert 'replace-with-a-random-local-secret' not in before.decode()
    assert release.activate(home,'1.0.0') == '1.0.0'
    assert release.activate(home,'1.0.1') == '1.0.1'
    assert release.activate(home,rollback=True) == '1.0.0'
    assert configuration.read_bytes() == before
    assert release.verify_installed(home,'1.0.0').name == '1.0.0'
    with instance_lock(home/'state'):
        with pytest.raises(RuntimeError):
            release.activate(home,'1.0.1')


def test_archive_tampering_and_path_escape_are_rejected(tmp_path, archives):
    bad = tmp_path/'bad.zip'
    with zipfile.ZipFile(archives[0]) as source, zipfile.ZipFile(bad,'w') as dest:
        for name in source.namelist():
            dest.writestr(name,b'tampered' if name=='backend/main.py' else source.read(name))
    with pytest.raises(ValueError,match='integrity'):
        release.verify_archive(bad)
    with zipfile.ZipFile(bad,'w') as dest:
        dest.writestr('../outside.txt','escape')
    with pytest.raises(ValueError,match='Unsafe'):
        release.verify_archive(bad)
    assert not (tmp_path/'outside.txt').exists()


def test_changed_install_cannot_be_activated_and_existing_version_is_immutable(tmp_path, archives):
    home = tmp_path/'installed'
    target = release.install(archives[0],home)
    (target/'backend/main.py').write_text('tampered')
    with pytest.raises(ValueError,match='changed'):
        release.activate(home,'1.0.0')
    assert not (home/'current.json').exists()
    with pytest.raises(FileExistsError):
        release.install(archives[0],home)
    for value in ['../escape','1.0.0/../../escape','latest',None]:
        with pytest.raises(ValueError):
            release.validate_version(value)


def test_package_is_reproducible_and_refuses_overwrite(tmp_path, archives):
    second = tmp_path/'same-version.zip'
    release.pack(tmp_path,'1.0.0',second,'sha256:'+'a'*64)
    assert second.read_bytes() == archives[0].read_bytes()
    with pytest.raises(FileExistsError):
        release.pack(tmp_path,'1.0.0',second,'sha256:'+'a'*64)


@pytest.mark.parametrize('name',['../escape','C:/escape','a\\escape','backend/NUL.py','a/aux','a/file.','a/file ','a/x:stream'])
def test_windows_and_posix_archive_aliases_are_refused(name):
    assert not release.safe_name(name)
