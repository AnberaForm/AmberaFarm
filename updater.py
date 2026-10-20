# -*- coding: utf-8 -*-
"""Opt-in prelaunch updater for Python distribution, no installer required.
Manifest example is in UPDATE_GUIDE.md. HTTPS is required; zip contents SHA256 pinned.
Save/story overrides under %APPDATA% are never touched.
"""
import hashlib
import io
import json
import os
import sys
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
import zipfile

ROOT=(Path(sys.executable).resolve().parent.parent if getattr(sys, 'frozen', False)
      else Path(__file__).resolve().parent)
CONFIG=ROOT/'update_config.json'
VERSION=ROOT/'version.json'
ALLOWED={
    'ambera_farm.py','farm_core.py','fishing_core.py','story_engine.py','story_editor.py',
    'world_map.py','multiplayer.py','updater.py','start_game.py',
    'START_GAME.cmd','DIAGNOSE.cmd','START_STORY_EDITOR.cmd','BUILD_EXE.cmd',
    'requirements.txt','data/story_events.json',
    *{'assets/crops/'+name+'.png' for name in (
        'kaiware','radish','kabu','ichigo','kyuri','tomato','potato','corn',
        'komugi','kabotya','suika','kin_ringo')},
}
MAX_PACKAGE=12*1024*1024

def current_version():
    try:return str(json.loads(VERSION.read_text(encoding='utf-8'))['version'])
    except (OSError,ValueError,KeyError):return '0.0.0'

def version_parts(value):
    parts=value.split('.')
    if not 1<=len(parts)<=4 or not all(p.isascii() and p.isdigit() and len(p)<8 for p in parts):
        raise ValueError('Invalid numeric version')
    return tuple(int(part) for part in parts)+(0,)*(4-len(parts))

def get_config():
    try:
        value=json.loads(CONFIG.read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}

def _url(value):
    from urllib.parse import urlsplit
    if not isinstance(value,str):raise ValueError('Missing update URL')
    u=urlsplit(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password:
        raise ValueError('Update URL must use HTTPS')
    return value

def fetch(url,max_bytes=500000):
    req=urllib.request.Request(_url(url),headers={'User-Agent':'AmberaFarmUpdater/0.4'})
    with urllib.request.urlopen(req,timeout=8) as response:
        _url(response.geturl())
        length=response.headers.get('Content-Length')
        if length and int(length)>max_bytes:raise ValueError('Update too large')
        data=response.read(max_bytes+1)
        if len(data)>max_bytes:raise ValueError('Update too large')
        return data

def fetch_manifest(config=None):
    config=get_config() if config is None else config
    if not config.get('manifest_url'):return None
    manifest=json.loads(fetch(config['manifest_url']).decode('utf-8'))
    if not isinstance(manifest,dict):raise ValueError('Invalid manifest')
    ver=manifest.get('version')
    version_parts(ver)
    if version_parts(ver)<=version_parts(current_version()):return None
    _url(manifest.get('package_url'))
    digest=manifest.get('sha256')
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid sha256')
    return manifest

def inspect_package(data):
    """Reject disallowed names, symlinks and huge or repeated members."""
    if len(data)>MAX_PACKAGE:raise ValueError('Package too big')
    out={};total=0
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        for info in zipped.infolist():
            if info.is_dir():continue
            posix=PurePosixPath(info.filename)
            normalized=posix.as_posix()
            if '\\' in info.filename or posix.is_absolute() or '..' in posix.parts or normalized not in ALLOWED:
                raise ValueError('Unexpected update file: '+info.filename)
            if (info.external_attr>>16)&0o170000==0o120000:raise ValueError('No symlinks allowed')
            if normalized in out:raise ValueError('Repeated filename in ZIP')
            if info.file_size>MAX_PACKAGE:raise ValueError('File too big')
            total+=info.file_size
            if total>MAX_PACKAGE*2:raise ValueError('Uncompressed data too large')
            out[normalized]=zipped.read(info)
    if 'ambera_farm.py' not in out:raise ValueError('Not an Ambera Farm package')
    return out

def apply_package(data,expected_sha,root=ROOT,new_version=None):
    digest=hashlib.sha256(data).hexdigest()
    if digest!=expected_sha:raise ValueError('SHA256 verification failed')
    root=Path(root)
    files=inspect_package(data)
    # First stage all files, then atomic replace with rollback copies on errors.
    backup_dir=Path(tempfile.mkdtemp(prefix='.ambera_rollback_',dir=root))
    stage_dir=Path(tempfile.mkdtemp(prefix='.ambera_update_',dir=root))
    applied=[]
    try:
        for name,payload in files.items():
            staged=stage_dir/name;staged.parent.mkdir(parents=True,exist_ok=True);staged.write_bytes(payload)
        if new_version is not None:
            version_parts(new_version)
            (stage_dir/'version.json').write_text(json.dumps({'version':new_version}),encoding='utf-8')
            files['version.json']=None
        for name in files:
            dst=root/name
            if dst.exists():
                old=backup_dir/name;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,old)
            dst.parent.mkdir(parents=True,exist_ok=True)
            os.replace(stage_dir/name,dst)
            applied.append(name)
    except (OSError,ValueError):
        for name in reversed(applied):
            old=backup_dir/name
            if old.exists():shutil.copy2(old,root/name)
            elif (root/name).exists():(root/name).unlink()
        raise
    finally:shutil.rmtree(backup_dir,ignore_errors=True);shutil.rmtree(stage_dir,ignore_errors=True)
    return len(applied)

def check_and_apply(log=print):
    config=get_config()
    if not config.get('auto_update') or not config.get('manifest_url'):
        return 'disabled'
    try:
        data=fetch_manifest(config)
        if not data:return 'up_to_date'
        log('[UPDATE] Downloading '+data['version'])
        package=fetch(data['package_url'],MAX_PACKAGE)
        count=apply_package(package,data['sha256'],ROOT,data['version'])
        log('[UPDATE] Installed '+str(count)+' files.')
        return 'updated'
    except Exception as exc:
        log('[UPDATE ERROR] '+str(exc).encode('ascii','backslashreplace').decode('ascii'))
        return 'failed'

if __name__=='__main__':
    print('AmberaFarm updater: '+check_and_apply())
