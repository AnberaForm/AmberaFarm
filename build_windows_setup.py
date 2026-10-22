# -*- coding: utf-8 -*-
"""Compile a Japanese per-user Setup EXE using the runner's Inno Setup."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
from exe_launcher import parse_version

BASE=Path(__file__).resolve().parent


def find_compiler():
    executable=shutil.which('ISCC.exe')
    if executable:return Path(executable)
    for env in ('ProgramFiles(x86)','ProgramFiles'):
        root=os.environ.get(env)
        if root:
            compiler=Path(root)/'Inno Setup 6'/'ISCC.exe'
            if compiler.is_file():return compiler
    raise FileNotFoundError('Inno Setup 6 compiler (ISCC.exe) is required on Windows.')


def build(release_folder=None, compiler=None):
    if os.name!='nt':raise RuntimeError('Setup must be compiled on Windows.')
    version=json.loads((BASE/'version.json').read_text(encoding='utf-8'))['version']
    parse_version(version)
    output=Path(release_folder or BASE/'build_output'/'release').resolve()
    portable=output/f'AmberaFarm_Windows_v{version}.zip'
    stage=output.parent/'setup_stage'
    stage.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(portable) as archive:
        for name in ('AmberaFarm.exe','app/AmberaGame.exe','version.json'):
            dest=stage/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(archive.read(name))
    script=stage/'windows_setup.iss'
    script.write_text((BASE/'windows_setup.iss').read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
    subprocess.run([str(compiler or find_compiler()),f'/DAppVersion={version}',
                    f'/DReleaseDir={stage}',f'/DOutputFolder={output}',
                    str(script)],check=True,cwd=BASE)
    setup=output/f'AmberaFarm_Setup_v{version}.exe'
    if not setup.is_file():raise FileNotFoundError(setup)
    print('CREATED',setup,setup.stat().st_size,'bytes',flush=True)
    return setup


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-folder')
    parser.add_argument('--compiler')
    args=parser.parse_args()
    build(args.release_folder,args.compiler)
