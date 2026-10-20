# -*- coding: utf-8 -*-
"""ASCII-console, CPython 3.10+ launcher for Ambera Farm on Windows.

No console output assumes a particular OEM/ANSI code page. Full logs are UTF-8.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent
LOG = ROOT / 'launcher_log.txt'
PKG = 'pygame-ce==2.5.8'


def report(message: str) -> None:
    print(message, flush=True)
    try:
        with LOG.open('a', encoding='utf-8') as fp:
            fp.write(message + '\n')
    except OSError:
        pass


def run_command(cmd: list[str], label: str, cwd: Path = ROOT) -> int:
    report(label)
    # Collect subprocess diagnostic text without using cmd.exe's character encoding.
    try:
        process = subprocess.run(
            cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', check=False,
        )
        result = process.stdout or ''
        try:
            with LOG.open('a', encoding='utf-8') as f:
                f.write(result + '\n')
        except OSError:
            pass
        if process.returncode:
            report('[ERROR] Step failed, exit code: ' + str(process.returncode))
            # Keep console errors in ASCII; inspect complete trace in UTF-8 log.
            for line in result.splitlines()[-14:]:
                print(line.encode('ascii', 'backslashreplace').decode('ascii'), flush=True)
        return process.returncode
    except (OSError, ValueError) as exc:
        report('[ERROR] Could not execute: ' + str(exc).encode('ascii', 'backslashreplace').decode('ascii'))
        return 1


def probe_pygame(python: str) -> bool:
    result = subprocess.run(
        [python, '-c', 'import pygame;print(pygame.version.ver)'], cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
    )
    return result.returncode == 0


def main() -> int:
    try:
        LOG.write_text(
            'Ambera Farm launcher -- ' + datetime.datetime.now().isoformat(timespec='seconds') + '\n'
            + 'Python: ' + sys.version + '\n'
            + 'Executable: ' + str(sys.executable) + '\n'
            + 'Working dir: ' + str(ROOT) + '\n',
            encoding='utf-8',
        )
    except OSError:
        print('[WARN] Cannot write launcher_log.txt (folder may be read-only).')

    # Update Python sources before the game process imports them.
    try:
        import updater
        report('[UPDATE] '+updater.check_and_apply(report))
    except Exception as exc:
        report('[WARN] Update check failed: '+str(exc).encode('ascii','backslashreplace').decode('ascii'))
    report('[1/3] Checking Python + Pygame ...')
    report('Python version: ' + sys.version.split()[0])
    if sys.version_info < (3, 10):
        report('[ERROR] Please use Python 3.10 or newer.')
        return 1

    python = sys.executable
    try:
        already_installed = probe_pygame(python)
    except (OSError, subprocess.SubprocessError):
        already_installed = False

    if already_installed:
        report('[OK] Pygame is already available.')
    else:
        report('[INFO] Installing a separate local Pygame environment (first run only).')
        env_dir = ROOT / '.ambera_venv'
        venv_python = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not venv_python.exists():
            if run_command([sys.executable, '-m', 'venv', str(env_dir)], '[SETUP] Create virtual environment'):
                report('[ERROR] Python venv creation failed. Please check your Python installation.')
                return 1
        if not probe_pygame(str(venv_python)):
            report('[SETUP] Install pygame-ce (internet required for first run).')
            status = run_command([
                str(venv_python), '-m', 'pip', 'install', '--disable-pip-version-check',
                '--only-binary=:all:', '--no-input', PKG,
            ], '[SETUP] Installing ' + PKG)
            if status:
                report('[ERROR] Package install failed. Check internet or Python configuration.')
                report('[HELP] Windows x64 Python 3.14 is supported by pygame-ce 2.5.8.')
                return 1
        if not probe_pygame(str(venv_python)):
            report('[ERROR] pygame cannot be imported after installation.')
            return 1
        python = str(venv_python)
        report('[OK] pygame-ce is ready.')

    if not (ROOT / 'ambera_farm.py').is_file() or not (ROOT / 'farm_core.py').is_file():
        report('[ERROR] Missing game files. Extract all ZIP files to a normal folder.')
        return 1
    report('[2/3] Python modules checked.')
    report('[3/3] Opening Ambera Farm...')
    os.environ.setdefault('PYTHONUTF8', '1')
    code = run_command([python, '-X', 'utf8', '-u', str(ROOT / 'ambera_farm.py')], '[GAME] Running pygame window')
    if code != 0:
        report('[ERROR] Game failed. Send launcher_log.txt for diagnosis.')
        report('[HELP] Also check %APPDATA%\\AmberaFarm\\error.log')
        return 1
    report('[OK] Game exited normally.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        report('[ERROR] Unexpected launcher error.')
        with LOG.open('a', encoding='utf-8') as fp:
            fp.write(traceback.format_exc() + '\n')
        for line in traceback.format_exc().splitlines()[-12:]:
            print(line.encode('ascii', 'backslashreplace').decode('ascii'), flush=True)
        sys.exit(1)
