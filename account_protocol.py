# -*- coding: utf-8 -*-
"""Shared wire limits and validation for authenticated play."""
from dataclasses import dataclass, field
import copy
import hashlib
import json
import re
import unicodedata

from farm_core import SaveError, validate_state

ACCOUNT_PROTOCOL = 15
ACCOUNT_WIRE_VERSION = 1
MAX_SAVE_BYTES = 512 * 1024
MAX_ACCOUNT_FRAME = MAX_SAVE_BYTES + 4096
SERVER_ENDPOINT = 'wss://ambera-farm-relay.onrender.com/relay'
ID = re.compile(r'[0-9a-f]{32}', re.ASCII)
TOKEN = re.compile(r'[0-9a-f]{64}', re.ASCII)

ERROR_MESSAGES = {
    'invalid_name': 'ユーザー名は1〜18文字で入力してください（日本語可）。',
    'invalid_password': 'パスワードは8〜128文字で入力してください。',
    'name_taken': 'そのユーザー名は使用されています。別の名前を入力してください。',
    'bad_login': 'ユーザー名またはパスワードが違います。',
    'auth_required': 'ログインが切れました。タイトルからログインし直してください。',
    'account_unavailable': 'アカウントサーバーが利用できません。時間をおいて再試行してください。',
    'slow_down': 'ログイン・登録の試行が多すぎます。少し待って再試行してください。',
    'save_conflict': '別の端末でセーブが更新されています。古い進行で上書きしません。',
    'bad_save': 'セーブを読み込めません。元データは上書きしません。',
    'already_playing': 'このアカウントは別のオンライン部屋でプレイ中です。',
    'version': 'ゲームとサーバーのバージョンが違います。更新内容を確認してください。',
    'denied': 'この操作は実行できません。',
}


class AccountError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(ERROR_MESSAGES.get(code, 'アカウントの処理に失敗しました。'))


@dataclass(frozen=True)
class Account:
    id: str
    name: str


@dataclass(frozen=True)
class SavedFarm:
    revision: int
    operation: str
    state: dict | None = field(repr=False)

    def as_dict(self):
        return {'revision': self.revision, 'operation': self.operation, 'state': self.state}


EMPTY_FARM = SavedFarm(0, '', None)


def username_parts(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 72:
        raise AccountError('invalid_name')
    name = unicodedata.normalize('NFKC', value).strip()
    if not 1 <= len(name) <= 18 or any(not c.isprintable() for c in name):
        raise AccountError('invalid_name')
    return name, unicodedata.normalize('NFKC', name.casefold())


def password_bytes(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 128 or any(not c.isprintable() for c in value):
        raise AccountError('invalid_password')
    return value.encode('utf-8')


def valid_revision(value):
    return type(value) is int and 0 <= value < 2**31


def encode_state(state):
    """Validate/migrate once at the persistence boundary; bound payload size."""
    try:
        clean = validate_state(copy.deepcopy(state))
        raw = json.dumps(clean, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(raw.encode('utf-8')) > MAX_SAVE_BYTES:
            raise ValueError('save size')
        return clean, raw
    except (SaveError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise AccountError('bad_save') from exc


def read_saved_farm(value):
    if not isinstance(value, dict) or not valid_revision(value.get('revision')):
        raise AccountError('bad_save')
    revision = value['revision']
    if revision == 0 and value.get('state') is None and value.get('operation') == '':
        return EMPTY_FARM
    operation = value.get('operation')
    if not revision or not isinstance(operation, str) or ID.fullmatch(operation) is None:
        raise AccountError('bad_save')
    state, _ = encode_state(value.get('state'))
    return SavedFarm(revision, operation, state)


def token_digest(token):
    if not isinstance(token, str) or TOKEN.fullmatch(token) is None:
        raise AccountError('auth_required')
    return hashlib.sha256(token.encode('ascii')).hexdigest()
