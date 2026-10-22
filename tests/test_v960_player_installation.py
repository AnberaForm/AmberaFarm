"""Installer-compatible launcher defaults and player-only automatic updates."""
import json
import sys
import zipfile

import exe_launcher as launcher


def test_frozen_launcher_updates_without_external_configuration(tmp_path,monkeypatch):
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    config=launcher.read_config(tmp_path)
    assert config['auto_update'] is True
    assert config['manifest_url']=='https://github.com/AnberaForm/AmberaFarm/releases/latest/download/update_manifest.json'
    assert not (tmp_path/'update_config.json').exists()


def test_player_update_does_not_install_legacy_editor(tmp_path):
    (tmp_path/'app').mkdir()
    (tmp_path/'app'/'AmberaGame.exe').write_bytes(b'MZ old game')
    (tmp_path/'version.json').write_text('{"version":"9.5.0"}',encoding='utf-8')
    package=tmp_path/'payload.zip'
    with zipfile.ZipFile(package,'w') as archive:
        archive.writestr('app/AmberaGame.exe',b'MZ new game')
        archive.writestr('app/AmberaStoryEditor.exe',b'MZ legacy editor')
        archive.writestr('version.json',json.dumps({'version':'9.6.0'}))
    launcher.apply_update(tmp_path,package,'9.6.0')
    assert launcher.read_version(tmp_path)=='9.6.0'
    assert (tmp_path/'app'/'AmberaGame.exe').read_bytes()==b'MZ new game'
    assert not (tmp_path/'app'/'AmberaStoryEditor.exe').exists()
