# -*- coding: utf-8 -*-
"""Server-only username authentication and two isolated save namespaces."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import time

from account_protocol import (Account, AccountError, EMPTY_FARM, ID, SavedFarm,
                              encode_state, password_bytes, token_digest,
                              username_parts, valid_revision)
from farm_core import new_state
from v8_features import init_v8

LOG = logging.getLogger(__name__)
SESSION_SECONDS = 24 * 60 * 60
# scrypt with 32 MiB per worker. The relay bounds concurrent password checks.
SCRYPT = dict(n=2**15, r=8, p=3, dklen=32, maxmem=64 * 1024 * 1024)
DUMMY_SALT = bytes(16)
DUMMY_HASH = bytes(32)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
    salt TEXT NOT NULL, password_hash TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS sessions_account ON sessions (account_id);
CREATE TABLE IF NOT EXISTS farm_saves (
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('normal', 'online')),
    revision INTEGER NOT NULL CHECK (revision > 0),
    operation TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (account_id, mode)
);
"""


@dataclass(frozen=True)
class OnlineWrite:
    account_id: str
    revision: int
    operation: str
    state: dict = field(repr=False)


class AccountStore:
    """Postgres in production. SQLite is an explicit local/dev setting."""
    def __init__(self, *, sqlite_path=None, database_url=None):
        if bool(sqlite_path) == bool(database_url):
            raise ValueError('Configure exactly one AmberaFarm database')
        self.path = Path(sqlite_path) if sqlite_path else None
        self.database_url = database_url
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._transaction() as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.executescript(SQLITE_SCHEMA)
        else:
            from psycopg_pool import ConnectionPool
            # Pool works with transaction pooling (disable named prepared statements).
            # libpq validates the server hostname and certificate.
            self.pool = ConnectionPool(database_url, min_size=0, max_size=6, timeout=6,
                                       kwargs={'connect_timeout': 5, 'sslmode': 'verify-full',
                                               'sslrootcert': 'system', 'prepare_threshold': None},
                                       open=False)
            self.pool.open()

    @classmethod
    def configured(cls):
        url = os.environ.get('AMBERA_DATABASE_URL')
        local_path = os.environ.get('AMBERA_LOCAL_DATABASE')
        if os.environ.get('RENDER') and local_path:
            raise ValueError('Render requires a persistent account database')
        return cls(database_url=url, sqlite_path=local_path) if url or local_path else None

    def close(self):
        if not self.path:
            self.pool.close()

    def _db_error(self, exc):
        LOG.warning('Account database unavailable: %s', type(exc).__name__)
        return AccountError('account_unavailable')

    @contextmanager
    def _transaction(self):
        if self.path:
            db = None
            try:
                db = sqlite3.connect(self.path, timeout=5)
                db.execute('PRAGMA foreign_keys=ON')
                with db:
                    yield db
            except sqlite3.Error as exc:
                raise self._db_error(exc) from None
            finally:
                if db:
                    db.close()
        else:
            from psycopg import Error
            from psycopg_pool import PoolTimeout
            try:
                with self.pool.connection() as db:
                    # SET LOCAL works with the hosted transaction pooler.
                    db.execute('SET LOCAL statement_timeout = 5000')
                    db.execute('SET LOCAL search_path TO ambera_game')
                    yield db
            except (Error, PoolTimeout) as exc:
                raise self._db_error(exc) from None

    def _execute(self, db, sql, params=()):
        return db.execute(sql if self.path else sql.replace('?', '%s'), params)

    def readiness(self):
        with self._transaction() as db:
            for table in ('accounts', 'sessions', 'farm_saves'):
                self._execute(db, f'SELECT 1 FROM {table} LIMIT 1')

    def _make_session(self, db, account_id):
        token = secrets.token_hex(32)
        now = int(time.time())
        self._execute(db, 'DELETE FROM sessions WHERE expires_at <= ?', (now,))
        self._execute(db, 'INSERT INTO sessions VALUES (?, ?, ?)',
                      (token_digest(token), account_id, now + SESSION_SECONDS))
        return token

    def register(self, username, password):
        name, key = username_parts(username)
        password = password_bytes(password)
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password, salt=salt, **SCRYPT)
        account = Account(secrets.token_hex(16), name)
        with self._transaction() as db:
            inserted = self._execute(db, """
                INSERT INTO accounts (id, name, name_key, salt, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (name_key) DO NOTHING
                """, (account.id, name, key, salt.hex(), digest.hex(), int(time.time())))
            if inserted.rowcount != 1:
                raise AccountError('name_taken')
            token = self._make_session(db, account.id)
        return account, token

    def login(self, username, password):
        try:
            _, key = username_parts(username)
            password = password_bytes(password)
        except AccountError:
            raise AccountError('bad_login') from None
        with self._transaction() as db:
            row = self._execute(db, 'SELECT id, name, salt, password_hash FROM accounts WHERE name_key = ?',
                                (key,)).fetchone()
        salt = bytes.fromhex(row[2]) if row else DUMMY_SALT
        expected = bytes.fromhex(row[3]) if row else DUMMY_HASH
        digest = hashlib.scrypt(password, salt=salt, **SCRYPT)
        if not hmac.compare_digest(digest, expected) or row is None:
            raise AccountError('bad_login')
        account = Account(row[0], row[1])
        with self._transaction() as db:
            token = self._make_session(db, account.id)
        return account, token

    def authenticate(self, token):
        with self._transaction() as db:
            row = self._execute(db, """
                SELECT a.id, a.name FROM sessions s JOIN accounts a ON a.id = s.account_id
                WHERE s.token_hash = ? AND s.expires_at > ?
                """, (token_digest(token), int(time.time()))).fetchone()
        if not row:
            raise AccountError('auth_required')
        return Account(*row)

    def logout(self, token):
        with self._transaction() as db:
            self._execute(db, 'DELETE FROM sessions WHERE token_hash = ?', (token_digest(token),))

    def _load(self, db, account_id, mode):
        row = self._execute(db, """
            SELECT revision, operation, data FROM farm_saves WHERE account_id = ? AND mode = ?
            """, (account_id, mode)).fetchone()
        if not row:
            return EMPTY_FARM
        try:
            clean, _ = encode_state(json.loads(row[2]))
        except (ValueError, TypeError, RecursionError) as exc:
            raise AccountError('bad_save') from exc
        return SavedFarm(row[0], row[1], clean)

    def normal_info(self, account):
        with self._transaction() as db:
            return self._load(db, account.id, 'normal')

    def write_normal(self, account, revision, operation, raw):
        if not valid_revision(revision) or not isinstance(operation, str) or not ID.fullmatch(operation):
            raise AccountError('bad_save')
        state, encoded = encode_state(raw)
        with self._transaction() as db:
            return self._write(db, account.id, 'normal', revision, operation, state, encoded)

    def get_online(self, account):
        with self._transaction() as db:
            current = self._load(db, account.id, 'online')
            if current.revision:
                return current
            # The online profile and home farm are initialized only here. No
            # client fields or data from the normal save ever enter this path.
            state = init_v8(new_state())
            state['player_name'] = account.name
            state['player_uid'] = account.id
            clean, encoded = encode_state(state)
            try:
                return self._write(db, account.id, 'online', 0, secrets.token_hex(16), clean, encoded)
            except AccountError as exc:
                if exc.code != 'save_conflict':
                    raise
                return self._load(db, account.id, 'online')

    def existing_online(self, account):
        with self._transaction() as db:
            return self._load(db, account.id, 'online')

    def has_online(self, account):
        with self._transaction() as db:
            return self._execute(db, "SELECT 1 FROM farm_saves WHERE account_id = ? AND mode = 'online'",
                                 (account.id,)).fetchone() is not None

    def write_online_batch(self, writes):
        encoded_writes = [(w, *encode_state(w.state)) for w in writes]
        result = {}
        with self._transaction() as db:
            # A trade and shared farm changes either all commit, or none do.
            # Consistent lock order for a batch across overlapping deploys.
            for write, state, encoded in sorted(encoded_writes, key=lambda x: x[0].account_id):
                result[write.account_id] = self._write(
                    db, write.account_id, 'online', write.revision, write.operation, state, encoded)
        return result

    def _write(self, db, account_id, mode, expected, operation, state, encoded):
        if expected == 0:
            cursor = self._execute(db, """
                INSERT INTO farm_saves VALUES (?, ?, 1, ?, ?)
                ON CONFLICT (account_id, mode) DO NOTHING
                """, (account_id, mode, operation, encoded))
        else:
            cursor = self._execute(db, """
                UPDATE farm_saves SET revision = revision + 1, operation = ?, data = ?
                WHERE account_id = ? AND mode = ? AND revision = ?
                """, (operation, encoded, account_id, mode, expected))
        if cursor.rowcount == 1:
            return SavedFarm(expected + 1, operation, state)
        current = self._load(db, account_id, mode)
        if current.operation == operation and current.revision == expected + 1:
            # Same write retried after a response was lost.
            return current
        raise AccountError('save_conflict')
