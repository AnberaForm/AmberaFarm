# -*- coding: utf-8 -*-
"""Background co-op connection jobs and Pygame UI state."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from multiplayer import RoomClient, RoomServer, PROTOCOL
from online_rooms import RelayHost, connect_guest, invitation, parse_invitation, relay_url


def wait_for_relay(endpoint, cancelled, progress, max_wait=75):
    """Allow a sleeping managed service to wake without blocking the renderer."""
    u = urlsplit(relay_url(endpoint))
    health = urlunsplit(('https' if u.scheme == 'wss' else 'http', u.netloc, '/health', '', ''))
    until = time.monotonic() + max_wait
    while not cancelled.is_set():
        progress('中継サーバーの起動を確認しています（最大75秒）')
        try:
            request = urllib.request.Request(health, headers={'User-Agent': 'AmberaFarm/9.5'})
            with urllib.request.urlopen(request, timeout=5) as response:
                actual = urlsplit(response.geturl())
                if actual.scheme != urlsplit(health).scheme or actual.netloc != u.netloc:
                    raise ValueError('Unexpected relay redirect')
                data = json.loads(response.read(1025))
                if (not isinstance(data, dict) or data.get('service') != 'AmberaFarm Relay'
                        or data.get('status') != 'ok'):
                    raise ValueError('Unexpected health response')
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


def configured_relay(settings, roots):
    configured = settings.get('online_relay_url') or os.environ.get('AMBERA_RELAY_URL', '')
    if configured:
        return configured
    for root in roots:
        try:
            data = json.loads((Path(root) / 'online_config.json').read_text(encoding='utf-8-sig'))
            if isinstance(data, dict) and isinstance(data.get('relay_url'), str):
                if data['relay_url'].strip():
                    return data['relay_url'].strip()
        except (OSError, ValueError):
            pass
    return ''


def close_bundle(bundle):
    for key in ('relay', 'client', 'server'):
        resource = bundle.get(key)
        if resource is not None:
            try:
                resource.close()
            except (OSError, ValueError):
                pass


class ConnectionJob:
    """Only the main thread adopts resources; cancellation closes late results."""
    def __init__(self, kind, fields, state, save_file, story_nodes):
        self.kind = kind
        self.fields = dict(fields)
        self.state = copy.deepcopy(state)
        self.save_file = Path(save_file)
        self.story_nodes = copy.deepcopy(story_nodes)
        self.lock = threading.Lock()
        self.cancelled = False
        self.cancel_event = threading.Event()
        self.progress = '中継サーバーに接続しています'
        self.result = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        bundle = {}
        error = None
        try:
            name = self.fields['name']
            if self.kind == 'host':
                endpoint = relay_url(self.fields['address'])
            else:
                endpoint, code, pin = parse_invitation(self.fields['pin'], self.fields['address'])
            wait_for_relay(endpoint, self.cancel_event, lambda value: setattr(self, 'progress', value))
            self.progress = '部屋主と参加者をつないでいます'
            if self.kind == 'host':
                server = RoomServer(self.state, self.save_file.with_name('coop_room_latest.json'),
                                    port=0, bind='127.0.0.1', story_nodes=self.story_nodes)
                bundle['server'] = server
                bundle['client'] = RoomClient(f'127.0.0.1:{server.port}', server.pin, name,
                                               profile=self.state, host_token=server.host_token)
                bundle['relay'] = RelayHost(endpoint, server.port, server.pin, PROTOCOL)
                bundle['code'] = bundle['relay'].share_code
                bundle['pin'] = server.pin
            else:
                transport = connect_guest(endpoint, code, pin, PROTOCOL)
                try:
                    bundle['client'] = RoomClient('relay', pin, name, profile=self.state,
                                                   connection=transport)
                except BaseException:
                    transport.close()
                    raise
                from online_rooms import format_code
                bundle['code'] = format_code(code, pin)
                bundle['pin'] = pin
            bundle['endpoint'] = endpoint
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


class InternetRoomsMixin:
    def init_internet_rooms(self, roots, settings_saver):
        self.online_settings_saver = settings_saver
        self.online_job = None
        self.online_relay = None
        self.online_room_code = ''
        self.online_endpoint = ''
        self.online_intent = 'join'
        self.join_mode = 'lan'
        self.lan_fields = self.join_fields
        self.internet_fields = {'address': configured_relay(self.settings, roots),
                                'pin': '', 'name': self.state['player_name']}

    def set_online_mode(self, mode):
        self.join_mode = mode
        self.join_fields = self.internet_fields if mode == 'internet' else self.lan_fields
        self.join_cursor = {k: len(v) for k, v in self.join_fields.items()}
        self.join_anchor = {k: None for k in self.join_fields}
        self.join_field = 'address'

    def join_edit_keys(self):
        return ['address', 'name'] if self.online_intent == 'host' else ['address', 'pin', 'name']

    def open_online_dialog(self, kind):
        import pygame
        if self.online_client or self.online_job:
            return
        if self.slot_kind != 'online':
            self.modal = 'save_slots'
            self.say('オンラインセーブ枠を選んでください。通常枠からコピーできます。', 9)
            return
        if self.read_only:
            self.say('セーブ復元が必要です。データ保護中は接続できません。', 10)
            return
        self.online_intent = kind
        self.internet_fields['name'] = self.state['player_name']
        self.lan_fields['name'] = self.state['player_name']
        self.set_online_mode('internet')
        self.modal = 'join'
        pygame.key.start_text_input()
        pygame.key.set_repeat(350, 36)

    def begin_internet_connection(self):
        import pygame
        if self.online_client or self.online_job:
            return
        if self.slot_kind != 'online' or self.read_only:
            self.say('使用できるオンラインセーブ枠を選んでください。', 10)
            return
        try:
            if self.online_intent == 'host':
                endpoint = relay_url(self.join_fields['address'])
            else:
                endpoint, _, _ = parse_invitation(self.join_fields['pin'], self.join_fields['address'])
        except ValueError as exc:
            self.say(str(exc), 12)
            return
        self.join_fields['address'] = endpoint
        self.online_job = ConnectionJob(self.online_intent, self.join_fields, self.state,
                                         self.save_file, self.story_nodes)
        self.modal = 'online_connect'
        pygame.key.stop_text_input()
        pygame.key.set_repeat()
        self.held_keys.clear()

    def cancel_internet_connection(self):
        import pygame
        if self.online_job:
            self.online_job.cancel()
            self.online_job = None
        if self.running:
            self.modal = 'join'
            pygame.key.start_text_input()
            pygame.key.set_repeat(350, 36)

    def poll_internet_connection(self):
        import pygame
        job = self.online_job
        if job and job.ready.is_set():
            self.online_job = None
            result = job.take()
            if result is None:
                return
            bundle, error = result
            if error:
                self.modal = 'join'
                pygame.key.start_text_input()
                pygame.key.set_repeat(350, 36)
                self.say('接続できません: ' + error, 15)
                return
            if job.kind == 'host':
                self.host_offline_state = copy.deepcopy(self.state)
                self.online_server = bundle['server']
                self.online_relay = bundle['relay']
            else:
                self.offline_state = copy.deepcopy(self.state)
            self.online_client = bundle['client']
            self.online_guest = job.kind == 'join'
            self.online_room_code = bundle['code']
            self.room_pin = bundle['pin']
            self.online_endpoint = bundle['endpoint']
            self.settings['online_relay_url'] = self.online_endpoint
            # No PIN, invite, or host credential is written to settings.
            self.online_settings_saver(self.settings)
            self.reset_map_state()
            self.player = list(self.online_client.spawn)
            self.movement_trail.clear()
            self.scene = 'world'
            self.modal = None
            pygame.key.stop_text_input()
            pygame.key.set_repeat()
            self.say('部屋コード: ' + self.online_room_code + '  /  Escから招待をコピーできます。', 20)
        if self.online_relay and not self.online_relay.active:
            self.stop_online()
            self.say('中継接続が切れたため部屋を終了しました。所持品を保存しました。', 15)

    def copy_room_invite(self):
        import pygame
        if not self.online_room_code:
            return
        try:
            pygame.scrap.put_text(invitation(self.online_endpoint, self.online_room_code))
            self.say('招待をコピーしました。友達は部屋コード欄に貼り付けて参加できます。', 10)
        except pygame.error:
            self.say('コピーできませんでした。部屋コードを友達に伝えてください。', 10)
