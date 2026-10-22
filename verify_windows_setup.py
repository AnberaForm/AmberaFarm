# -*- coding: utf-8 -*-
"""Windows CI: actual install, shortcuts, launch, update, uninstall, save retention."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from exe_launcher import read_version, apply_update

BASE=Path(__file__).resolve().parent


def shell_folder(csid):
    buffer=ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None,csid,None,0,buffer)!=0:
        raise OSError('Cannot locate Windows shortcut folder')
    return Path(buffer.value)


def verify(release_folder=None):
    if os.name!='nt':raise RuntimeError('Installer verification requires Windows.')
    release=Path(release_folder or BASE/'build_output'/'release').resolve()
    version=json.loads((BASE/'version.json').read_text(encoding='utf-8'))['version']
    setup=release/f'AmberaFarm_Setup_v{version}.exe'
    logs=release.parent/'setup_logs'
    logs.mkdir(parents=True,exist_ok=True)
    checks=[]
    with tempfile.TemporaryDirectory(prefix='ambera_setup_test_') as temporary:
        work=Path(temporary)
        install=work/'installed'
        profile=work/'profiles'/'AmberaFarm'/'save_slots'
        profile.mkdir(parents=True)
        sentinel=profile/'keep_saved_progress.txt'
        sentinel.write_bytes(b'Existing save data must survive setup and uninstall.')
        subprocess.run([str(setup),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',
                        f'/DIR={install}','/TASKS=desktopicon',f'/LOG={logs / "install.log"}'],
                        check=True,timeout=120)
        assert (install/'AmberaFarm.exe').is_file()
        assert (install/'app'/'AmberaGame.exe').is_file()
        assert read_version(install)==version
        assert not (install/'update_config.json').exists()
        assert not list(install.rglob('*.py'))
        assert not (install/'app'/'AmberaStoryEditor.exe').exists()
        checks.append('Actual silent install; player EXEs only; version matches')
        desktop=shell_folder(0x10)/'アンベラ牧場.lnk'
        menu=shell_folder(0x02)/'アンベラ牧場'/'アンベラ牧場.lnk'
        assert desktop.is_file() and menu.is_file()
        checks.append('Desktop and Start menu shortcuts created')
        attrs=ctypes.windll.kernel32.GetFileAttributesW
        attrs.argtypes=[ctypes.c_wchar_p];attrs.restype=ctypes.c_uint32
        assert attrs(str(install/'version.json')) & 2
        checks.append('Internal version metadata hidden from normal Explorer view')
        environment=dict(os.environ,APPDATA=str(work/'profiles'),
                         SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy')
        subprocess.run([str(install/'AmberaFarm.exe'),'--smoke-test'],check=True,
                        timeout=90,env=environment)
        checks.append('Installed launcher starts the bundled game and all screens')
        apply_update(install,release/f'AmberaFarm_payload_v{version}.zip',version)
        assert read_version(install)==version
        assert attrs(str(install/'version.json')) & 2
        assert not (install/'app'/'AmberaStoryEditor.exe').exists()
        checks.append('Update payload applies to setup installation without adding editor')
        subprocess.run([str(install/'AmberaFarm.exe'),'--smoke-test'],check=True,
                        timeout=90,env=environment)
        checks.append('Updated installation starts successfully')
        subprocess.run([str(install/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
                        f'/LOG={logs / "uninstall.log"}'],check=True,timeout=90)
        assert not (install/'AmberaFarm.exe').exists()
        assert not desktop.exists() and not menu.exists()
        assert sentinel.read_bytes()==b'Existing save data must survive setup and uninstall.'
        checks.append('Uninstall removes app/shortcuts and preserves save directory')
    report={'version':version,'installer':setup.name,
            'sha256':hashlib.sha256(setup.read_bytes()).hexdigest(),
            'status':'passed','checks':checks}
    dest=release/'setup_verification.json'
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-folder')
    verify(parser.parse_args().release_folder)
