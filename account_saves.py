# -*- coding: utf-8 -*-
"""Legacy-save selection and a durable local outbox for the single normal save."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time

from account_protocol import AccountError, ID, MAX_SAVE_BYTES, encode_state, valid_revision
from farm_core import SaveError, load_state, state_path


@dataclass(frozen=True)
class LegacyFarm:
    label: str
    description: str
    state: dict | None


def legacy_farms(root=None, preferred=('offline', 1)):
    """Read old files in place, including old solo use of the online slots."""
    root = Path(root) if root is not None else state_path().parent
    slots = root / 'save_slots'
    order = [('offline', 1), ('offline', 2), ('online', 1), ('online', 2)]
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    options = []
    seen = set()

    def find(label, path, reader):
        if not path.is_file():
            return
        try:
            if path.stat().st_size > MAX_SAVE_BYTES * 4:
                raise SaveError('oversize legacy file')
            fingerprint = hashlib.sha256(path.read_bytes()).digest()
            if fingerprint in seen:
                return
            state, _ = encode_state(reader())
            seen.add(fingerprint)
            options.append(LegacyFarm(label, f"{state['player_name']}  /  {state['coins']}G", state))
        except (SaveError, OSError, ValueError, AccountError):
            options.append(LegacyFarm(label, '読み込めません。元ファイルは保護されています。', None))

    for kind, slot in order:
        title = ('旧通常枠' if kind == 'offline' else '旧オンライン枠') + str(slot)
        path = slots / f'{kind}_{slot}.json'
        # Version 9.6 signed old online slots even when played solo. Check
        # them without generating keys or writing into the legacy directory.
        def read_legacy(target=path, signed=kind == 'online'):
            if signed:
                raw = target.read_bytes()
                key = (slots / '.integrity_key').read_bytes()
                signature = target.with_suffix('.hmac').read_bytes().strip()
                expected = hmac.new(key, raw, 'sha256').hexdigest().encode('ascii')
                if not hmac.compare_digest(expected, signature):
                    raise SaveError('旧セーブの署名が一致しません')
                return json.loads(raw.decode('utf-8-sig'))
            return load_state(target)[0]
        find(title, path, read_legacy)
    find('旧バージョンの牧場', root / 'save.json', lambda: load_state(root / 'save.json')[0])
    return options


def read_normal_export(path):
    path = Path(path)
    if path.stat().st_size > MAX_SAVE_BYTES * 4:
        raise AccountError('bad_save')
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(value, dict) and set(value) == {'base', 'draft', 'inflight'}:
            # Recovery copies are journal files; restore the most recent
            # usable normal state through the same confirmation screen.
            value = (value['draft'] or value['inflight'])['state']
        state, _ = encode_state(value)
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise AccountError('bad_save') from exc
    return LegacyFarm('選択したバックアップ', f"{state['player_name']}  /  {state['coins']}G", state)


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.normal_', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class FarmSync:
    """One writer, revision checks, and crash-safe retry after a lost response."""
    def __init__(self, client, root=None):
        self.client = client
        session = client.session
        directory = Path(root) if root is not None else state_path().parent
        self.path = directory / 'accounts' / session.account.id / 'normal_pending.json'
        self.cloud = session.normal
        self.state = self.cloud.state
        self.base = self.cloud.revision
        self.inflight = self.draft = None
        self.recovered = False
        self.recovery_warning = ''
        self._resume()
        self.condition = threading.Condition()
        self.thread = None
        self.closed = False
        self.blocked = False
        self.status = 'pending' if (self.inflight or self.draft) else 'saved'
        self.last_state = self.state

    def _resume(self):
        if not self.path.is_file():
            return
        try:
            if self.path.stat().st_size > MAX_SAVE_BYTES * 2 + 4096:
                raise ValueError('outbox size')
            record = json.loads(self.path.read_text(encoding='utf-8'))
            base = record['base']
            if not valid_revision(base):
                raise ValueError('outbox revision')
            flight, draft = record['inflight'], record['draft']
            for item in (flight, draft):
                if item is not None:
                    if not isinstance(item, dict) or not ID.fullmatch(item.get('operation', '')):
                        raise ValueError('outbox operation')
                    item['state'], _ = encode_state(item['state'])
            if (flight and self.cloud.revision == base + 1
                    and flight['operation'] == self.cloud.operation):
                base = self.cloud.revision
                flight = None
            if base != self.base:
                raise AccountError('save_conflict')
            if flight or draft:
                self.inflight, self.draft = flight, draft
                self.state = (draft or flight)['state']
                self.recovered = True
            else:
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, TypeError, RecursionError, AccountError):
            suffix = secrets.token_hex(6)
            try:
                self.path.replace(self.path.with_name(f'normal_recovery_{suffix}.json'))
                self.recovery_warning = 'このPCの未同期データを退避し、サーバーのセーブを開きました。'
            except OSError:
                # If we cannot archive it, do not let a new save overwrite it.
                raise SaveError('未同期のセーブを保護するため開けません。空き容量とアクセス権を確認してください。') from None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._work, name='normal-save-sync', daemon=True)
            self.thread.start()

    def _journal(self):
        if self.draft or self.inflight:
            _atomic_json(self.path, {'base': self.base, 'inflight': self.inflight, 'draft': self.draft})
        else:
            self.path.unlink(missing_ok=True)

    def stage(self, state):
        clean, _ = encode_state(state)
        with self.condition:
            if self.closed:
                raise AccountError('auth_required')
            if clean == self.last_state:
                return
            old = self.draft
            self.draft = {'operation': secrets.token_hex(16), 'state': clean}
            try:
                self._journal()
            except OSError:
                self.draft = old
                raise SaveError('このPCにセーブの控えを書き込めません。') from None
            self.last_state = clean
            if not self.blocked:
                self.status = 'pending'
            self.condition.notify_all()

    def _work(self):
        delay = 1
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or (
                    not self.blocked and (self.inflight is not None or self.draft is not None)))
                if self.closed:
                    return
                try:
                    if self.inflight is None:
                        self.inflight, self.draft = self.draft, None
                        self._journal()
                        self.status = 'pending'
                    base, write = self.base, self.inflight
                except OSError:
                    self.draft, self.inflight = self.inflight, None
                    self.status = 'local_error'
                    self.condition.wait_for(lambda: self.closed, timeout=3)
                    continue
            try:
                updated = self.client.write_normal(base, write['operation'], write['state'])
            except AccountError as error:
                with self.condition:
                    self.status = error.code
                    self.blocked = error.code in ('save_conflict', 'auth_required', 'bad_save', 'denied', 'version')
                    self.condition.notify_all()
                    if not self.blocked and not self.closed:
                        self.condition.wait_for(lambda: self.closed, timeout=delay)
                        delay = min(20, delay * 2)
                continue
            with self.condition:
                self.base, self.inflight = updated, None
                # A failed journal cleanup is safe: the operation ID makes
                # retries idempotent on the next login, even after a crash.
                try:
                    self._journal()
                except OSError:
                    self.status = 'local_error'
                else:
                    self.status = 'pending' if self.draft else 'saved'
                self.condition.notify_all()
                if self.draft and not self.closed:
                    self.condition.wait_for(lambda: self.closed, timeout=.5)
            delay = 1

    def flush(self, timeout=3):
        with self.condition:
            self.condition.wait_for(lambda: (not self.inflight and not self.draft) or self.blocked,
                                    timeout=timeout)
            return not self.inflight and not self.draft

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
