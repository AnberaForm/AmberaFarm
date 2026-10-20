# -*- coding: utf-8 -*-
"""Windows release builder. Creates self-contained EXEs using PyInstaller."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent


def build(destination=None):
    if os.name != 'nt':
        raise RuntimeError('Windows EXE files must be built on Windows (or GitHub Actions windows-latest).')
    destination = Path(destination or BASE / 'build_output').resolve()
    destination.mkdir(parents=True, exist_ok=True)
    work = destination / 'pyinstaller_work'
    work.mkdir(exist_ok=True)

    common = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--onefile',
              '--windowed', '--distpath', str(destination / 'exe'), '--workpath', str(work),
              '--specpath', str(work)]

    def invoke(name, source, datas=()):
        args = common + ['--name', name]
        for source_file, target in datas:
            args += ['--add-data', str((BASE / source_file).resolve()) + ':' + target]
        args.append(str(BASE / source))
        print('Building ' + name, flush=True)
        subprocess.run(args, cwd=BASE, check=True)
        result = destination / 'exe' / (name + '.exe')
        if not result.is_file():
            raise FileNotFoundError(result)
        return result

    crops = ('assets/crops', 'assets/crops')
    story = ('data/story_events.json', 'data')
    announcements = ('data/announcements.json', 'data')
    game = invoke('AmberaGame', 'ambera_farm.py', [crops, story, announcements])
    editor = invoke('AmberaStoryEditor', 'story_editor.py', [story, announcements])
    launcher = invoke('AmberaFarm', 'exe_launcher.py')
    for result in (game, editor, launcher):
        print(result.name, result.stat().st_size, 'bytes')
    return destination / 'exe'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', default=str(BASE / 'build_output'))
    args = parser.parse_args()
    build(args.destination)
