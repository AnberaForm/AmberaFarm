# -*- coding: utf-8 -*-
"""Client for the game account service. Credentials never enter room packets."""
from dataclasses import dataclass, field
import json
import os
import sys
from urllib.parse import urlsplit, urlunsplit

from account_protocol import (ACCOUNT_WIRE_VERSION, Account, AccountError, ID,
                              MAX_ACCOUNT_FRAME, SERVER_ENDPOINT, TOKEN,
                              read_saved_farm, valid_revision)
from online_rooms import _abort, _dial_websocket, relay_url


def account_endpoint():
    # A packaged game always sends logins to the built-in WSS destination.
    # Source development can target a local test server.
    if not getattr(sys, 'frozen', False):
        override = os.environ.get('AMBERA_TEST_RELAY_URL')
        if override:
            endpoint = relay_url(override)
            if urlsplit(endpoint).hostname in ('127.0.0.1', 'localhost', '::1'):
                return endpoint
    return SERVER_ENDPOINT


@dataclass(frozen=True)
class SignedIn:
    account: Account
    token: str = field(repr=False)
    normal: object = field(repr=False)
    has_online: bool


class AccountClient:
    def __init__(self, endpoint, session=None):
        self.endpoint = relay_url(endpoint)
        self.session = session

    def _call(self, op, **fields):
        u = urlsplit(self.endpoint)
        address = urlunsplit((u.scheme, u.netloc, '/accounts', '', ''))
        payload = {'op': op, 'version': ACCOUNT_WIRE_VERSION, **fields}
        if self.session:
            payload['session'] = self.session.token
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        if len(raw.encode('utf-8')) > MAX_ACCOUNT_FRAME:
            raise AccountError('bad_save')
        ws = None
        try:
            ws = _dial_websocket(address, timeout=12)
            ws.send(raw)
            reply = ws.recv()
            if not isinstance(reply, str) or len(reply.encode('utf-8')) > MAX_ACCOUNT_FRAME:
                raise ValueError('account reply')
            body = json.loads(reply)
            if not isinstance(body, dict) or body.get('type') not in ('ok', 'error'):
                raise ValueError('account reply type')
            if body['type'] == 'error':
                code = body.get('code')
                raise AccountError(code if isinstance(code, str) else 'account_unavailable')
            return body
        except AccountError:
            raise
        except Exception:
            raise AccountError('account_unavailable') from None
        finally:
            if ws:
                _abort(ws)

    def sign_in(self, operation, username, password):
        if operation not in ('register', 'login') or self.session:
            raise ValueError('Not a login operation')
        result = self._call(operation, username=username, password=password)
        identifier, name, token = (result.get(k) for k in ('id', 'name', 'session'))
        if (not isinstance(identifier, str) or ID.fullmatch(identifier) is None
                or not isinstance(name, str) or not 1 <= len(name) <= 18
                or not isinstance(token, str) or TOKEN.fullmatch(token) is None):
            raise AccountError('account_unavailable')
        return SignedIn(Account(identifier, name), token, read_saved_farm(result.get('normal')),
                        result.get('has_online') is True)

    def write_normal(self, revision, operation, state):
        result = self._call('write_normal', revision=revision, operation=operation, state=state)
        if (not valid_revision(result.get('revision')) or result['revision'] != revision + 1
                or result.get('operation') != operation):
            raise AccountError('account_unavailable')
        return result['revision']

    def logout(self):
        self._call('logout')
