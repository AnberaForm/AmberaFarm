# -*- coding: utf-8 -*-
"""Host-owned farms. Client saves are never used to seed a room economy."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile

from farm_core import SaveError, new_state, state_path, validate_state
from v8_features import init_v8

MAX_MEMBERS = 128
MAX_SAVE_BYTES = 16 * 1024 * 1024


def room_file(index=1):
    if type(index) is not int or index not in (1, 2):
        raise ValueError('オンライン牧場の番号が不正です。')
    return state_path().parent / 'room_worlds' / f'farm_{index}.json'


def local_room_identity(root=None):
    """A private install identity, distinct from public player UIDs and saves."""
    directory = Path(root) if root is not None else state_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.room_identity'
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w', encoding='ascii') as handle:
            handle.write(secrets.token_hex(32))
    value = path.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise SaveError('オンラインの本人情報を読み込めません。元のファイルを復元してください。')
    return value


def member_key(identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}', identity):
        raise ValueError('Invalid room identity')
    return hashlib.sha256(identity.encode('ascii')).hexdigest()


def load_room(path):
    path = Path(path)
    if not path.exists():
        return init_v8(new_state()), {}
    try:
        if path.stat().st_size > MAX_SAVE_BYTES:
            raise ValueError('牧場データが大きすぎます')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema') != 1:
            raise ValueError('牧場データの形式が違います')
        members = data['members']
        if not isinstance(members, dict) or len(members) > MAX_MEMBERS:
            raise ValueError('参加者データの形式が違います')
        if any(not re.fullmatch(r'[0-9a-f]{64}', k) for k in members):
            raise ValueError('参加者の本人情報が不正です')
        return validate_state(data['world']), {k: validate_state(v) for k, v in members.items()}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SaveError('オンライン牧場を読み込めません。元データは上書きしません: ' + str(exc)) from exc


def save_room(path, world, members):
    path = Path(path)
    data = {'schema': 1, 'world': validate_state(world),
            'members': {k: validate_state(v) for k, v in members.items()}}
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.room_', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            shutil.copy2(path, path.with_suffix('.bak.json'))
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as exc:
        raise SaveError('オンライン牧場を保存できません: ' + str(exc)) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
