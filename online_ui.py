# -*- coding: utf-8 -*-
"""Background co-op connection jobs and Pygame UI state."""
from __future__ import annotations

import json
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from multiplayer import RoomClient
from account_protocol import ACCOUNT_PROTOCOL, AccountError
from online_rooms import (RelayHost, RelayError, connect_guest, invitation, parse_invitation,
                          relay_url, search_rooms, request_admission, format_code)
from farm_core import new_state
from v8_features import init_v8


def wait_for_relay(endpoint, cancelled, progress, max_wait=75, require_accounts=False):
    """Allow a sleeping managed service to wake without blocking the renderer."""
    u = urlsplit(relay_url(endpoint))
    health = urlunsplit(('https' if u.scheme == 'wss' else 'http', u.netloc, '/health', '', ''))
    until = time.monotonic() + max_wait
    while not cancelled.is_set():
        progress('サーバーの起動を待っています（最大75秒）')
        try:
            request = urllib.request.Request(health, headers={'User-Agent': 'AmberaFarm/9.7'})
            with urllib.request.urlopen(request, timeout=5) as response:
                actual = urlsplit(response.geturl())
                if actual.scheme != urlsplit(health).scheme or actual.netloc != u.netloc:
                    raise ValueError('Unexpected relay redirect')
                data = json.loads(response.read(1025))
                if (not isinstance(data, dict) or data.get('service') != 'AmberaFarm Relay'
                        or data.get('status') != 'ok'):
                    raise ValueError('Unexpected health response')
                if require_accounts and data.get('accounts') is not True:
                    raise AccountError('account_unavailable')
                return
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 429, 502, 503, 504):
                raise ConnectionError('中継サーバーのURLを確認してください。') from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.gaierror, ssl.SSLError, ConnectionRefusedError)):
                raise ConnectionError('中継サーバーに接続できません。URLを確認してください。') from exc
        except (TimeoutError, ConnectionResetError):
            pass
        except (ValueError, AttributeError) as exc:
            raise ConnectionError('接続先はアンベラ牧場の中継サーバーではありません。') from exc
        if time.monotonic() >= until:
            raise ConnectionError('サーバーの起動待ちがタイムアウトしました。少し待って再接続してください。')
        cancelled.wait(2)
    raise ConnectionError('接続をキャンセルしました。')


def close_bundle(bundle):
    for key in ('relay', 'client'):
        resource = bundle.get(key)
        if resource is not None:
            try:
                resource.close()
            except (OSError, ValueError):
                pass


class ConnectionJob:
    """Network operations run off the game loop; no local saves enter this job."""
    def __init__(self, kind, fields, endpoint, session):
        self.kind = kind
        self.fields = dict(fields)
        self.endpoint = relay_url(endpoint)
        self.session = session
        self.lock = threading.Lock()
        self.cancelled = False
        self.cancel_event = threading.Event()
        self.progress = '部屋に接続しています'
        self.result = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        bundle = {}
        error = None
        try:
            name = self.session.account.name
            token = self.session.token
            if self.kind == 'join':
                target, code, pin = parse_invitation(self.fields['pin'], self.endpoint)
                if target != self.endpoint:
                    raise ConnectionError('この招待はアンベラ牧場のアカウント用サーバーに対応していません。')
            wait_for_relay(self.endpoint, self.cancel_event, self._progress, require_accounts=True)
            self._progress('オンライン専用の牧場に接続しています')
            approval = None
            if self.kind == 'host':
                pin = str(secrets.randbelow(900000) + 100000)
                host = RelayHost(self.endpoint, None, pin, ACCOUNT_PROTOCOL, name=name,
                                 title=self.fields.get('title', ''),
                                 public=self.fields.get('public', False), session=token)
                bundle['relay'] = host
                code = host.code
            elif self.kind == 'request':
                code = self.fields['room_id']
                reply = request_admission(self.endpoint, code, name, ACCOUNT_PROTOCOL,
                                          self.cancel_event, self._progress, session=token)
                pin, approval = reply['pin'], reply['approval']
            if self.cancel_event.is_set():
                raise ConnectionError('接続をキャンセルしました。')
            try:
                transport = connect_guest(self.endpoint, code, pin, ACCOUNT_PROTOCOL,
                                          approval=approval, session=token)
            except RelayError as exc:
                if exc.code != 'approval_required' or self.kind != 'join':
                    raise
                reply = request_admission(self.endpoint, code, name, ACCOUNT_PROTOCOL,
                                          self.cancel_event, self._progress, session=token)
                pin = reply['pin']
                transport = connect_guest(self.endpoint, code, pin, ACCOUNT_PROTOCOL,
                                          approval=reply['approval'], session=token)
            try:
                bundle['client'] = RoomClient('relay', pin, connection=transport,
                                              relay_authenticated=True)
            except BaseException:
                transport.close()
                raise
            bundle.update(code=format_code(code, pin), pin=pin, endpoint=self.endpoint)
        except Exception as exc:
            close_bundle(bundle)
            bundle = {}
            error = str(exc)[:180] or '接続に失敗しました。'
        with self.lock:
            if self.cancelled:
                dispose = bundle
            else:
                self.result = (bundle, error)
                dispose = {}
            self.ready.set()
        close_bundle(dispose)

    def _progress(self, message):
        self.progress = message

    def take(self):
        with self.lock:
            result, self.result = self.result, None
            return result

    def cancel(self):
        self.cancel_event.set()
        with self.lock:
            self.cancelled = True
            result, self.result = self.result, None
        if result:
            threading.Thread(target=close_bundle, args=(result[0],), daemon=True).start()


class DirectoryJob:
    def __init__(self, endpoint, query, session):
        self.endpoint, self.query, self.session = endpoint, query, session
        self.ready = threading.Event()
        self.cancel_event = threading.Event()
        self.progress = '部屋一覧を取得しています'
        self.rows, self.error = [], ''
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            wait_for_relay(self.endpoint, self.cancel_event, lambda v: setattr(self, 'progress', v),
                           require_accounts=True)
            self.rows = search_rooms(self.endpoint, self.query, ACCOUNT_PROTOCOL, self.session.token)
        except Exception as exc:
            self.error = str(exc)[:180] or '部屋一覧を取得できませんでした。'
        finally:
            self.ready.set()


class InternetRoomsMixin:
    def init_internet_rooms(self):
        self.online_job = None
        self.online_relay = None
        self.online_room_code = ''
        self.online_endpoint = ''
        self.online_intent = 'join'
        self.join_fields = {'title': '', 'pin': ''}
        self.join_cursor = {'title': 0, 'pin': 0}
        self.join_anchor = {'title': None, 'pin': None}
        self.join_field = 'pin'
        self.host_public = True
        self.browser_fields = {'query': ''}
        self.browser_field = 'query'
        self.browser_cursor = {'query': 0}
        self.browser_anchor = {'query': None}
        self.directory_job = None
        self.directory_rows = []
        self.directory_status = '部屋名・部屋主名で検索できます。'
        self.directory_page = 0
        self.directory_updated = -10.
        self.requests_page = 0
        self.seen_admissions = set()
        self.seen_friend_requests = set()

    def join_edit_keys(self):
        return ['title' if self.online_intent == 'host' else 'pin']

    def open_room_browser(self):
        import pygame
        if not self.account_session or self.online_job:
            return
        if self.online_client:
            self.say('部屋を終了してから、ほかの部屋を探してください。', 8)
            return
        self.modal = 'room_browser'
        pygame.key.start_text_input()
        pygame.key.set_repeat(350, 36)
        self.refresh_room_directory()

    def refresh_room_directory(self):
        if (not self.account_session or self.directory_job
                or time.monotonic() - self.directory_updated < 2):
            return
        self.directory_updated = time.monotonic()
        self.directory_status = '部屋一覧を取得しています'
        self.directory_job = DirectoryJob(self.account_endpoint, self.browser_fields['query'],
                                          self.account_session)

    def request_room_entry(self, room_id):
        if not self.account_session or self.online_client or self.online_job:
            return
        if not any(row['id'] == room_id for row in self.directory_rows):
            return
        self._connect_room('request', {'room_id': room_id, 'return_modal': 'room_browser'})

    def pending_requests(self):
        rows = []
        if self.online_relay:
            rows.extend(dict(r, kind='join') for r in self.online_relay.pending_requests())
        rows.extend(dict(r, kind='friend') for r in self.friend_invites)
        return rows

    def open_online_dialog(self, kind):
        import pygame
        if not self.account_session or self.online_client or self.online_job:
            return
        self.online_intent = kind
        self.join_field = self.join_edit_keys()[0]
        if kind == 'host' and not self.join_fields['title']:
            self.join_fields['title'] = self.account_session.account.name + 'の牧場'
        self.join_cursor[self.join_field] = len(self.join_fields[self.join_field])
        self.join_anchor[self.join_field] = None
        self.modal = 'join'
        pygame.key.start_text_input()
        pygame.key.set_repeat(350, 36)

    def begin_internet_connection(self):
        if not self.account_session or self.online_client or self.online_job:
            return
        self._connect_room(self.online_intent, dict(self.join_fields, public=self.host_public))

    def _connect_room(self, kind, fields):
        import pygame
        self.online_job = ConnectionJob(kind, fields, self.account_endpoint, self.account_session)
        self.modal = 'online_connect'
        pygame.key.stop_text_input()
        pygame.key.set_repeat()
        self.held_keys.clear()

    def cancel_internet_connection(self):
        import pygame
        if self.online_job:
            return_modal = self.online_job.fields.get('return_modal', 'join')
            self.online_job.cancel()
            self.online_job = None
        else:
            return_modal = 'join'
        if self.running:
            self.modal = return_modal
            pygame.key.start_text_input()
            pygame.key.set_repeat(350, 36)

    def poll_internet_connection(self):
        import pygame
        directory = self.directory_job
        if directory and directory.ready.is_set():
            self.directory_job = None
            self.directory_rows = directory.rows
            self.directory_page = 0
            self.directory_status = (directory.error or (f'{len(directory.rows)}件の部屋が見つかりました。'
                                    if directory.rows else '検索に表示される部屋はありません。'))
        elif directory:
            self.directory_status = directory.progress
        job = self.online_job
        if job and job.ready.is_set():
            self.online_job = None
            result = job.take()
            if result is None:
                return
            bundle, error = result
            if error:
                self.modal = job.fields.get('return_modal', 'join')
                pygame.key.start_text_input()
                pygame.key.set_repeat(350, 36)
                self.say('接続できません: ' + error, 15)
                return
            self.offline_state = self.state
            self.offline_layout = self.inventory_layout
            self.state = init_v8(new_state())
            self.state['player_name'] = self.account_session.account.name
            self.selected = self.state['selected_crop']
            self.inventory_layout = []
            self.online_client = bundle['client']
            self.online_relay = bundle.get('relay')
            self.online_guest = job.kind != 'host'
            self.online_room_code = bundle['code']
            self.room_pin = bundle['pin']
            self.online_endpoint = bundle['endpoint']
            self.has_online_farm = True
            self.reset_map_state()
            self.player = list(self.online_client.spawn)
            self.movement_trail.clear()
            self.scene = 'world'
            self.modal = None
            pygame.key.stop_text_input()
            pygame.key.set_repeat()
            self.say('オンライン専用データで参加しました。参加申請は Esc →「申請欄」で確認できます。', 12)
        if self.online_relay:
            pending = {r['id'] for r in self.online_relay.pending_requests()}
            if pending - self.seen_admissions:
                self.say('参加申請が届きました！ Esc →「申請欄」で承認・見送りができます。', 12)
            self.seen_admissions = pending
        friends = {r['id'] for r in self.friend_invites}
        if friends - self.seen_friend_requests:
            self.say('フレンド申請が届きました！ Esc →「申請欄」で確認できます。', 12)
        self.seen_friend_requests = friends
        if self.online_relay and not self.online_relay.active:
            self.stop_online()
            self.reload_story()
            self.scene = 'title'
            self.modal = None
            self.say('サーバーとの接続が切れたため部屋を終了しました。', 12)

    def copy_room_invite(self):
        import pygame
        if not self.online_room_code:
            return
        try:
            pygame.scrap.put_text(invitation(self.online_endpoint, self.online_room_code))
            self.say('招待をコピーしました。友達は部屋コード欄に貼り付けて参加できます。', 10)
        except pygame.error:
            self.say('コピーできませんでした。部屋コードを友達に伝えてください。', 10)
