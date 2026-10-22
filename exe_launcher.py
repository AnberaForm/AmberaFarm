# -*- coding: utf-8 -*-
"""Ambera Farm Windows EXE launcher (Python stdlib only).

Install layout:
    AmberaFarm.exe                <- stable launcher, stays outside update payload
    update_config.json            <- configured by packager
    version.json                  <- installed game version
    app/AmberaGame.exe            <- replaces only while game is not running
    app/AmberaStoryEditor.exe

The launcher checks the HTTPS release manifest and installs only a SHA-256-
verified, strict allow-list of files before it starts the actual Pygame game.
Saves and user-created stories remain in %APPDATA%/AmberaFarm.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request
import zipfile

NAME = 'AmberaFarm'
MAX_MANIFEST = 80_000
MAX_DOWNLOAD = 350 * 1024 * 1024
MAX_EXTRACTED = 600 * 1024 * 1024
UPDATE_FILES = frozenset(('app/AmberaGame.exe', 'app/AmberaStoryEditor.exe', 'version.json'))
REQUIRED_FILES = UPDATE_FILES
GAME_RELATIVE = Path('app') / 'AmberaGame.exe'
LOCK_HANDLE = None
DEFAULT_MANIFEST = 'https://github.com/AnberaForm/AmberaFarm/releases/latest/download/update_manifest.json'


def base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def profile_dir() -> Path:
    base = os.environ.get('APPDATA')
    return (Path(base) if base else Path.home() / '.local' / 'share') / 'AmberaFarm'


def log(message: str) -> None:
    try:
        dest = profile_dir()
        dest.mkdir(parents=True, exist_ok=True)
        with (dest / 'exe_launcher.log').open('a', encoding='utf-8') as handle:
            handle.write(time.strftime('%Y-%m-%d %H:%M:%S') + '  ' + message + '\n')
    except OSError:
        pass


def alert(message: str, title: str = 'Ambera Farm') -> None:
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
            return
        except Exception:
            pass
    print(title + ': ' + message, file=sys.stderr)


def lock_launcher() -> bool:
    """Keep the launcher alive while game is running: don't overwrite open EXEs."""
    global LOCK_HANDLE
    if sys.platform != 'win32':
        return True
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    LOCK_HANDLE = kernel32.CreateMutexW(None, False, 'Local\\AmberaFarm_OneLauncher_v1')
    if not LOCK_HANDLE:
        raise OSError('Could not acquire Windows launcher mutex')
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def parse_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', value):
        raise ValueError('Invalid 3-component version')
    return tuple(int(x) for x in value.split('.'))


def read_version(root: Path) -> str:
    try:
        obj = json.loads((root / 'version.json').read_text(encoding='utf-8-sig'))
        parse_version(obj['version'])
        return obj['version']
    except (OSError, ValueError, KeyError, TypeError):
        return '0.0.0'


def read_config(root: Path) -> dict:
    try:
        config = json.loads((root / 'update_config.json').read_text(encoding='utf-8-sig'))
        return config if isinstance(config, dict) else {}
    except (OSError, ValueError):
        return ({'auto_update':True,'manifest_url':DEFAULT_MANIFEST}
                if getattr(sys,'frozen',False) else {})


def hide_metadata(root: Path) -> None:
    if sys.platform!='win32':return
    import ctypes
    kernel=ctypes.windll.kernel32
    kernel.GetFileAttributesW.argtypes=[ctypes.c_wchar_p]
    kernel.GetFileAttributesW.restype=ctypes.c_uint32
    kernel.SetFileAttributesW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32]
    for name in ('version.json','update_config.json'):
        path=root/name
        if path.is_file():
            attrs=kernel.GetFileAttributesW(str(path))
            if attrs!=0xffffffff:kernel.SetFileAttributesW(str(path),attrs|2)


def require_https(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('Invalid URL')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or
            parts.password or parts.fragment or parts.port not in (None, 443)):
        raise ValueError('Only HTTPS update URLs are allowed')
    return url


def same_release_repo(manifest_url: str, package_url: str) -> None:
    """Lock GitHub-release manifest/package to the same owner and repository."""
    manifest = urlsplit(require_https(manifest_url))
    package = urlsplit(require_https(package_url))
    if manifest.hostname != package.hostname:
        raise ValueError('Update package host does not match manifest host')
    if manifest.hostname == 'github.com':
        parts = manifest.path.split('/')
        if len(parts) != 7 or parts[3:6] != ['releases', 'latest', 'download'] or parts[6] != 'update_manifest.json':
            raise ValueError('Unexpected GitHub manifest path')
        prefix = f'/{parts[1]}/{parts[2]}/releases/download/'
        if not package.path.startswith(prefix):
            raise ValueError('Package must be from the same GitHub release repository')


def open_https(url: str, timeout: float = 6):
    request = urllib.request.Request(require_https(url), headers={
        'User-Agent': 'AmberaFarm-Windows-Updater/0.5',
        'Cache-Control': 'no-cache',
    })
    response = urllib.request.urlopen(request, timeout=timeout)
    try:
        require_https(response.geturl())
    except Exception:
        response.close()
        raise
    return response


def fetch_manifest(manifest_url: str, installed_version: str) -> dict | None:
    with open_https(manifest_url) as response:
        raw = response.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise ValueError('Update manifest is too big')
    info = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(info, dict):
        raise ValueError('Update manifest is invalid')
    version = info.get('version')
    if parse_version(version) <= parse_version(installed_version):
        return None
    package_url = info.get('package_url')
    same_release_repo(manifest_url, package_url)
    sha = info.get('sha256')
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
        raise ValueError('Invalid SHA-256 checksum')
    return {'version': version, 'package_url': package_url, 'sha256': sha}


def download_update(url: str, expected_sha: str, destination: Path) -> None:
    hasher = hashlib.sha256()
    total = 0
    with open_https(url, timeout=12) as response, destination.open('wb') as output:
        while True:
            block = response.read(256 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_DOWNLOAD:
                raise ValueError('Update exceeds download size limit')
            hasher.update(block)
            output.write(block)
    if hasher.hexdigest() != expected_sha:
        raise ValueError('SHA-256 mismatch; update rejected')


def list_payload(archive: zipfile.ZipFile, version: str) -> list[zipfile.ZipInfo]:
    files: dict[str, zipfile.ZipInfo] = {}
    size = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        normalized = path.as_posix()
        if ('\\' in info.filename or path.is_absolute() or '..' in path.parts or
                normalized not in UPDATE_FILES or normalized in files):
            raise ValueError('Unsafe or unexpected file in update ZIP: ' + info.filename)
        if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
            raise ValueError('Symbolic link not allowed in updates')
        size += info.file_size
        if size > MAX_EXTRACTED or info.file_size > MAX_EXTRACTED:
            raise ValueError('Update exceeds extraction size limit')
        files[normalized] = info
    if set(files) != REQUIRED_FILES:
        raise ValueError('Update ZIP does not include all required files')
    if files['version.json'].file_size > 512:
        raise ValueError('Invalid version metadata size')
    obj = json.loads(archive.read(files['version.json']).decode('utf-8-sig'))
    if not isinstance(obj, dict) or obj.get('version') != version:
        raise ValueError('Update version does not match manifest')
    return [files[name] for name in sorted(files, key=lambda n: n == 'version.json')]


def apply_update(root: Path, zip_path: Path, version: str) -> None:
    """Stage files and rollback on partial failure. Never touch profile saves."""
    root = Path(root).resolve()
    stage = Path(tempfile.mkdtemp(prefix='.ambera_stage_', dir=root))
    backup = Path(tempfile.mkdtemp(prefix='.ambera_backup_', dir=root))
    modified: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            infos = list_payload(archive, version)
            if not (root/'app'/'AmberaStoryEditor.exe').exists():
                infos=[info for info in infos if info.filename!='app/AmberaStoryEditor.exe']
            for entry in infos:
                dst = stage / entry.filename
                dst.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry, 'r') as source, dst.open('wb') as output:
                    shutil.copyfileobj(source, output, 256 * 1024)
        for entry in infos:
            dest = root / entry.filename
            if dest.is_symlink():
                raise ValueError('Update destination is a symbolic link')
            if dest.exists():
                old = backup / entry.filename
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, old)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / entry.filename, dest)
            modified.append(entry.filename)
        hide_metadata(root)
        log('Updated game files to version ' + version)
    except Exception:
        for name in reversed(modified):
            old = backup / name
            dest = root / name
            try:
                if old.exists():
                    os.replace(old, dest)
                elif dest.exists():
                    dest.unlink()
            except OSError as exc:
                log('CRITICAL rollback failed on ' + name + ': ' + repr(exc))
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def check_update(root: Path) -> str:
    settings = read_config(root)
    if not settings.get('auto_update') or not settings.get('manifest_url'):
        return 'disabled'
    try:
        current = read_version(root)
        manifest = fetch_manifest(settings['manifest_url'], current)
        if manifest is None:
            return 'current'
        log('New version: ' + manifest['version'])
        with tempfile.TemporaryDirectory(prefix='ambera_download_') as temp:
            file = Path(temp) / 'package.zip'
            download_update(manifest['package_url'], manifest['sha256'], file)
            apply_update(root, file, manifest['version'])
        return 'updated'
    except Exception as exc:
        log('Update failed (old version will start): ' + repr(exc))
        return 'failed'


def main() -> int:
    if not lock_launcher():
        log('Another game launcher is already running')
        return 0
    root = base_dir()
    log('Launcher started: ' + str(root))
    smoke='--smoke-test' in sys.argv
    status = 'smoke-test' if smoke else check_update(root)
    log('Update status: ' + status)
    executable = root / GAME_RELATIVE
    if not executable.is_file():
        alert('Game files were not found. Run the AmberaFarm Setup again.\n'
              f'Missing: {executable}\nLog: {profile_dir() / "exe_launcher.log"}')
        log('Game executable missing')
        return 1
    try:
        # Wait for game exit, so double-clicking cannot install while game is in use.
        result = subprocess.run([str(executable)]+(['--smoke-test'] if smoke else []),
                                cwd=str(executable.parent), check=False)
        log('Game exited with code ' + str(result.returncode))
        return result.returncode
    except OSError as exc:
        log('Unable to start game: ' + repr(exc))
        alert('Could not start game. See %APPDATA%\\AmberaFarm\\exe_launcher.log.')
        return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        log('Launcher crashed: ' + repr(error))
        alert('Launcher error. Check %APPDATA%\\AmberaFarm\\exe_launcher.log.')
        raise SystemExit(1)
