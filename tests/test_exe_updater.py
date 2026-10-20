"""Tests executable updater on any OS using mock EXE bytes.
Never pretends Windows EXEs were compiled on Linux.
"""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile
import pytest

import exe_launcher as U
from pack_windows_release import pack


def payload_bytes(version='0.5.1', updates=None):
    contents = {
        'app/AmberaGame.exe': b'MZ\x00game-NEW',
        'app/AmberaStoryEditor.exe': b'MZ\x00editor-NEW',
        'version.json': json.dumps({'version': version}).encode('utf-8'),
    }
    if updates:
        contents.update(updates)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        for name, data in contents.items():
            z.writestr(name, data)
    return buf.getvalue()


def init_game(root):
    app = root / 'app'
    app.mkdir()
    (app / 'AmberaGame.exe').write_bytes(b'MZ\x00game-OLD')
    (app / 'AmberaStoryEditor.exe').write_bytes(b'MZ\x00editor-OLD')
    (root / 'version.json').write_text('{"version":"0.5.0"}', encoding='utf-8')
    return root


def test_apply_replaces_only_game_and_preserves_save(tmp_path, monkeypatch):
    init_game(tmp_path)
    archive = tmp_path / 'release.zip'
    archive.write_bytes(payload_bytes())
    protected = tmp_path / 'save.json'
    protected.write_bytes(b'NEVER TOUCH SAVES')
    U.apply_update(tmp_path, archive, '0.5.1')
    assert U.read_version(tmp_path) == '0.5.1'
    assert (tmp_path / 'app/AmberaGame.exe').read_bytes().endswith(b'NEW')
    assert protected.read_bytes() == b'NEVER TOUCH SAVES'
    assert not list(tmp_path.glob('.ambera_*'))


def test_partial_error_rolls_back(tmp_path, monkeypatch):
    init_game(tmp_path)
    original = {(tmp_path / name): (tmp_path / name).read_bytes()
                for name in U.UPDATE_FILES}
    archive = tmp_path / 'release.zip'
    archive.write_bytes(payload_bytes())
    real_replace = U.os.replace
    counts = {'n': 0}
    def fail_once(src, dst):
        if Path(dst) == tmp_path / 'version.json' and Path(src).name == 'version.json':
            if counts['n'] == 0:
                counts['n'] += 1
                raise OSError('simulated disk failure')
        return real_replace(src, dst)
    monkeypatch.setattr(U.os, 'replace', fail_once)
    with pytest.raises(OSError):
        U.apply_update(tmp_path, archive, '0.5.1')
    assert counts['n'] == 1
    assert all(path.read_bytes() == content for path, content in original.items())


@pytest.mark.parametrize('bad', [
    '../save.json', '/tmp/escape.txt', 'app/../../oops.exe',
    'update_config.json', 'app\\AmberaGame.exe',
])
def test_reject_zip_member_names(tmp_path, bad):
    archive = tmp_path / 'bad.zip'
    archive.write_bytes(payload_bytes(updates={bad: b'not allowed'}))
    with zipfile.ZipFile(archive) as z:
        with pytest.raises(ValueError):
            U.list_payload(z, '0.5.1')


def test_reject_missing_editor(tmp_path):
    p = io.BytesIO()
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('app/AmberaGame.exe', b'MZ')
        z.writestr('version.json', '{"version":"0.5.1"}')
    with zipfile.ZipFile(io.BytesIO(p.getvalue())) as z:
        with pytest.raises(ValueError, match='required'):
            U.list_payload(z, '0.5.1')


def test_reject_manifest_version_mismatch(tmp_path):
    f = tmp_path / 'release.zip'
    f.write_bytes(payload_bytes(version='0.5.2'))
    with zipfile.ZipFile(f) as z:
        with pytest.raises(ValueError, match='version'):
            U.list_payload(z, '0.5.1')


def test_version_validation():
    assert U.parse_version('0.6.0') > U.parse_version('0.5.12')
    for bad in ['1.2', '1.2.3.4', 'v1.2.3', '1.02.3', '../a']:
        with pytest.raises(ValueError): U.parse_version(bad)


def test_repo_pinning():
    m = 'https://github.com/Owner/Repo/releases/latest/download/update_manifest.json'
    p = 'https://github.com/Owner/Repo/releases/download/v0.5.1/AmberaFarm_payload_v0.5.1.zip'
    U.same_release_repo(m,p)
    for bad in ['https://github.com/Other/Repo/releases/download/v0.5.1/a.zip',
                'http://github.com/Owner/Repo/releases/download/v0.5.1/a.zip',
                'https://evil.example/Owner/Repo/releases/download/v0.5.1/a.zip']:
        with pytest.raises(ValueError): U.same_release_repo(m,bad)


def test_fetch_and_download_with_local_mocks(tmp_path, monkeypatch):
    m = 'https://github.com/test/farm/releases/latest/download/update_manifest.json'
    p = 'https://github.com/test/farm/releases/download/v0.5.1/AmberaFarm_payload_v0.5.1.zip'
    data = payload_bytes()
    digest = hashlib.sha256(data).hexdigest()
    info = {'version':'0.5.1','package_url':p,'sha256':digest}
    class Response(io.BytesIO):
        def geturl(self):return self.uri
        def __init__(self,uri,data):super().__init__(data);self.uri=uri
    def open_mock(uri, timeout=6):
        if uri == m: return Response(uri, json.dumps(info).encode('utf-8'))
        if uri == p: return Response(uri, data)
        raise AssertionError(uri)
    monkeypatch.setattr(U, 'open_https', open_mock)
    assert U.fetch_manifest(m, '0.5.0') == info
    assert U.fetch_manifest(m, '0.5.1') is None
    path = tmp_path / 'temp.zip'
    U.download_update(p,digest,path)
    assert path.read_bytes() == data
    with pytest.raises(ValueError,match='SHA-256'):
        U.download_update(p,'0'*64,path)


def test_pack_creates_installer_and_release(tmp_path):
    exe_dir = tmp_path / 'exe'
    exe_dir.mkdir()
    for name in ('AmberaFarm.exe','AmberaGame.exe','AmberaStoryEditor.exe'):
        (exe_dir / name).write_bytes(b'MZ' + name.encode('ascii'))
    install, update, manifest = pack(exe_dir, tmp_path / 'release', 'ExampleUser/AmberaFarm', '0.5.1')
    manifest_data = json.loads(manifest.read_text(encoding='utf-8'))
    assert manifest_data['sha256'] == hashlib.sha256(update.read_bytes()).hexdigest()
    with zipfile.ZipFile(install) as bundle:
        assert set(bundle.namelist()) == {'AmberaFarm.exe','app/AmberaGame.exe',
            'app/AmberaStoryEditor.exe','version.json','update_config.json','START_HERE.txt'}
        c = json.loads(bundle.read('update_config.json'))
        assert c['auto_update'] and 'ExampleUser/AmberaFarm' in c['manifest_url']
        assert all(name.isascii() for name in bundle.namelist())
    with zipfile.ZipFile(update) as bundle:
        U.list_payload(bundle, '0.5.1')


def test_update_failure_still_launches_game(tmp_path, monkeypatch):
    init_game(tmp_path)
    (tmp_path / 'update_config.json').write_text(json.dumps({
        'auto_update':True,
        'manifest_url':'https://github.com/u/r/releases/latest/download/update_manifest.json',
    }))
    def failed_request(*args,**kwargs):
        raise OSError('offline')
    monkeypatch.setattr(U,'open_https', failed_request)
    assert U.check_update(tmp_path) == 'failed'
    assert U.read_version(tmp_path) == '0.5.0'
