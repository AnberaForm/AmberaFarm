# -*- coding: utf-8 -*-
"""Four independent character saves (2 offline + 2 online), with legacy migration.

These are *client-side* saves. Online balances are NOT fraud-proof until moved to a
trusted remotely hosted account service; see SECURITY_AND_SAVES.md.
"""
from __future__ import annotations
from pathlib import Path
import shutil
import hashlib, hmac, secrets, os
from farm_core import SaveError, state_path, load_state, save_state, load_json, new_state
from v8_features import init_v8

KINDS = ('offline', 'online')
SLOTS_PER_KIND = 2

def slots_root(root=None):
    return Path(root) if root is not None else state_path().parent / 'save_slots'

def slot_file(kind, index, root=None):
    if kind not in KINDS or type(index) is not int or index not in (1, 2):
        raise ValueError('セーブスロットの指定が不正です。')
    return slots_root(root) / f'{kind}_{index}.json'

def legacy_migrate(root=None, legacy=None):
    """Never delete the old save: copy it only when offline slot 1 is empty."""
    dest = slot_file('offline',1,root)
    src = Path(legacy) if legacy is not None else state_path()
    if dest.exists() or not src.exists():return False
    # Validate BEFORE copying (fail closed on corrupted save).
    load_json(src)
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,dest)
    return True

def _mac_key(root=None):
    directory=slots_root(root)
    directory.mkdir(parents=True,exist_ok=True)
    p=directory/'.integrity_key'
    if not p.exists():
        try:
            flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
            fd=os.open(str(p),flags,0o600)
            with os.fdopen(fd,'wb') as f:f.write(secrets.token_bytes(32))
        except FileExistsError:pass
    return p.read_bytes()

def _sig_path(path):return path.with_suffix('.hmac')

def _sign(path,root=None):
    raw=Path(path).read_bytes()
    digest=hmac.new(_mac_key(root),raw,hashlib.sha256).hexdigest()
    _sig_path(path).write_text(digest,encoding='ascii')

def load_slot(kind,index,root=None):
    path=slot_file(kind,index,root)
    if kind=='online' and path.exists():
        sig=_sig_path(path)
        if not sig.exists():raise SaveError('オンライン保存の検証ファイルがありません。変更や破損の可能性があります。')
        expected=hmac.new(_mac_key(root),path.read_bytes(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,sig.read_text(encoding='ascii').strip()):
            raise SaveError('オンライン保存の改ざんまたは破損を検知しました。')
    return load_state(path)

def save_slot(state,kind,index,root=None):
    path=slot_file(kind,index,root)
    save_state(state,path)
    if kind=='online':_sign(path,root)

def slot_summaries(root=None):
    out=[]
    for kind in KINDS:
        for index in (1,2):
            path=slot_file(kind,index,root)
            status='空き'
            if path.exists():
                try:
                    state,_=load_slot(kind,index,root)
                    status=f"{state.get('player_name','牧場主')} / {state.get('coins',0)}G"
                except SaveError:status='読み込みエラー / 保護中'
            out.append((kind,index,status))
    return out

def new_slot(kind,index,root=None):
    path=slot_file(kind,index,root)
    if path.exists():raise SaveError('使用中のセーブ枠です。上書きはできません。')
    save_slot(init_v8(new_state()),kind,index,root)
    return path

def import_offline_to_online(offline_index,online_index,root=None):
    """Kept as a failing compatibility entry point; no save can be imported."""
    raise SaveError('通常データはオンラインへ持ち込めません。部屋専用データで始まります。')

def delete_slot(kind,index,root=None):
    path=slot_file(kind,index,root)
    if not path.exists():return False
    # Recoverable deletion, not irreversible wiping.
    backup=path.with_suffix('.deleted.json')
    shutil.copy2(path,backup)
    path.unlink()
    _sig_path(path).unlink(missing_ok=True)
    return True
