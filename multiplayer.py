# -*- coding: utf-8 -*-
"""LAN co-op protocol v2.

Only plots are shared. Each connection has a separate inventory, money, stats,
missions and story flags. Guests save their own profile on their own computer.
Host saves the common plots with the host's profile. PINs are not encryption;
never forward this prototype's port to the public internet.
"""
from __future__ import annotations
import copy
import json
import math
import queue
import secrets
import select
import socket
import socketserver
import threading
import time
from pathlib import Path
from farm_core import (plant, harvest, buy_seeds, sell_crops, claim_mission,
                       SaveError, save_state, PLOT_COUNT, CROP_BY_ID, validate_state,
                       new_state)
from fishing_core import FISH_BY_ID, add_catch, sell_fish
from story_engine import finish_story
from world_map import can_stand, plot_world, INTERACTION_POINTS

PORT = 47821
MAX_PLAYERS = 8
MAX_PACKET = 131072
PROTOCOL = 2
SPAWN = (336., 368.)


def pack(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def safe_name(name):
    return ''.join(c for c in str(name) if c.isprintable() and c not in '\r\n\t')[:18].strip() or 'Player'


def safe_chat(message):
    if not isinstance(message, str):
        return ''
    return ''.join(c for c in message if c.isprintable() and c not in '\r\n\t')[:160].strip()


def merged_view(profile, shared_plots):
    """Expose this player's private economy over the authoritative shared farm."""
    view = copy.deepcopy(profile)
    view['plots'] = copy.deepcopy(shared_plots)
    return view


class _GameServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 12


class RoomServer:
    def __init__(self, state, save_file, port=PORT, pin=None, story_nodes=None):
        self.pin = str(pin if pin is not None else secrets.randbelow(900000) + 100000)
        self.host_token = secrets.token_hex(24)
        self.state = validate_state(copy.deepcopy(state))
        self.host_profile = copy.deepcopy(self.state)
        self.save_file = Path(save_file)
        self.lock = threading.RLock()
        self.players = {}
        self.sockets = {}
        self.host_id = None
        self.chat_log = []
        self.chat_seq = 0.
        self.story_nodes = copy.deepcopy(story_nodes or [])
        parent = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                sock = self.request
                sock.settimeout(7)
                file = sock.makefile('rb')
                pid = None
                try:
                    raw = file.readline(MAX_PACKET + 1)
                    if not raw or len(raw) > MAX_PACKET:
                        return
                    hello = json.loads(raw.decode('utf-8'))
                    if (not isinstance(hello, dict) or hello.get('type') != 'hello'
                            or hello.get('protocol') != PROTOCOL or str(hello.get('pin')) != parent.pin):
                        sock.sendall(pack({'type': 'error', 'message': 'PIN / version mismatch'}))
                        return
                    is_host = secrets.compare_digest(str(hello.get('host_token', '')), parent.host_token)
                    with parent.lock:
                        if len(parent.players) >= MAX_PLAYERS:
                            sock.sendall(pack({'type': 'error', 'message': 'Room full'}))
                            return
                        if is_host:
                            if parent.host_id is not None:
                                sock.sendall(pack({'type': 'error', 'message': 'Host already connected'}))
                                return
                            profile = parent.host_profile
                        else:
                            try:
                                profile = validate_state(hello.get('profile'))
                            except (SaveError, ValueError, TypeError):
                                sock.sendall(pack({'type': 'error', 'message': 'Invalid player save'}))
                                return
                        pid = secrets.token_hex(6)
                        x, y = profile['player']
                        if not can_stand(x, y):
                            x, y = SPAWN
                        parent.players[pid] = {
                            'id': pid, 'name': safe_name(hello.get('name')),
                            'x': x, 'y': y, 'last': time.monotonic(),
                            'profile': profile, 'last_chat': 0., 'last_rescue': 0.,
                        }
                        if is_host:
                            parent.host_id = pid
                        parent.sockets[pid] = sock
                    sock.sendall(pack({'type': 'welcome', 'id': pid, 'pin': parent.pin, 'spawn': [x, y]}))
                    sock.settimeout(None)
                    last_sent = 0.
                    while True:
                        if time.monotonic() - last_sent >= .28:
                            with parent.lock:
                                player = parent.players.get(pid)
                                if player is None:
                                    break
                                snap = {
                                    'type': 'snapshot',
                                    'state': merged_view(player['profile'], parent.state['plots']),
                                    'story_nodes': parent.story_nodes,
                                    'players': [{k: p[k] for k in ('id', 'name', 'x', 'y')}
                                                for p in parent.players.values()],
                                    'self_pos': [player['x'], player['y']],
                                    'chat': list(parent.chat_log[-30:]),
                                }
                            sock.sendall(pack(snap))
                            last_sent = time.monotonic()
                        readable, _, _ = select.select([sock], [], [], .13)
                        if not readable:
                            continue
                        raw = file.readline(MAX_PACKET + 1)
                        if not raw or len(raw) > MAX_PACKET:
                            break
                        try:
                            incoming = json.loads(raw.decode('utf-8'))
                            if not isinstance(incoming, dict):
                                continue
                        except (ValueError, UnicodeDecodeError):
                            continue
                        with parent.lock:
                            if pid not in parent.players:
                                break
                            kind = incoming.get('type')
                            if kind == 'move':
                                parent._move(pid, incoming)
                            elif kind == 'action':
                                result = parent._action(pid, incoming)
                                profile = parent.players[pid]['profile']
                                sock.sendall(pack({'type': 'result', 'message': result,
                                    'state': merged_view(profile, parent.state['plots'])}))
                            elif kind == 'chat':
                                parent._chat(pid, incoming.get('message'))
                except (OSError, ValueError, TypeError, OverflowError):
                    pass
                finally:
                    if pid:
                        with parent.lock:
                            parent.players.pop(pid, None)
                            parent.sockets.pop(pid, None)
                            if pid == parent.host_id:
                                parent.host_id = None
                    try:
                        file.close()
                    except OSError:
                        pass

        self.server = _GameServer(('0.0.0.0', int(port)), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.08}, daemon=True)
        self.thread.start()

    def _save_host(self):
        # Host profile is the local save. Guest balances never enter this file.
        self.state = merged_view(self.host_profile, self.state['plots'])
        save_state(self.state, self.save_file)

    def _chat(self, pid, message):
        player = self.players[pid]
        message = safe_chat(message)
        now = time.monotonic()
        if not message or now - player['last_chat'] < .7:
            return
        player['last_chat'] = now
        self.chat_seq += 1
        self.chat_log.append({'name': player['name'], 'text': message, 'at': round(time.time(), 2), 'seq': self.chat_seq})
        self.chat_log = self.chat_log[-30:]

    def _move(self, pid, data):
        p = self.players[pid]
        try:
            x = float(data.get('x'))
            y = float(data.get('y'))
            if not math.isfinite(x) or not math.isfinite(y):
                return
        except (ValueError, TypeError):
            return
        now = time.monotonic()
        elapsed = max(.01, min(2., now - p['last']))
        distance = math.dist((x, y), (p['x'], p['y']))
        if distance > max(38, 280 * elapsed) or not can_stand(x, y):
            return
        steps = max(1, math.ceil(distance / 6))
        if any(not can_stand(p['x'] + (x-p['x'])*i/steps, p['y'] + (y-p['y'])*i/steps)
               for i in range(1, steps + 1)):
            return
        p.update(x=x, y=y, last=now)

    def _action(self, pid, msg):
        action = msg.get('action')
        data = msg.get('value')
        p = self.players[pid]
        profile = p['profile']
        # Only the plot list belongs to everyone. Each player's other fields are private.
        profile['plots'] = self.state['plots']
        loc = lambda key, radius: math.dist((p['x'], p['y']), INTERACTION_POINTS[key]) <= radius
        if action == 'rescue':
            now = time.monotonic()
            if now - p['last_rescue'] < 12:
                return '緊急脱出は12秒ごとに使えます'
            p.update(x=SPAWN[0], y=SPAWN[1], last=now, last_rescue=now)
            p['profile']['player'] = list(SPAWN)
            return '安全な場所に移動しました'
        ok = False
        try:
            if action == 'plot' and isinstance(data, dict):
                idx, crop = data.get('index'), data.get('crop')
                if type(idx) is not int or not 0 <= idx < PLOT_COUNT or crop not in CROP_BY_ID:
                    return '畑の指定が不正です'
                if math.dist((p['x'], p['y']), plot_world(idx)) > 54:
                    return '畑から遠すぎます'
                if self.state['plots'][idx] is None:
                    ok = plant(profile, idx, crop)
                else:
                    ok = harvest(profile, idx) is not None
            elif action == 'buy' and loc('shop', 98):
                crop, amount = data
                ok = buy_seeds(profile, crop, amount)
            elif action == 'ship' and loc('shipping', 98):
                crop, amount = data
                if crop not in CROP_BY_ID:
                    return '不明な作物'
                ok = sell_crops(profile, crop, profile['warehouse'][crop] if amount == -1 else amount)
            elif action == 'fish_sell' and loc('fish_market', 98):
                fish_id, amount = data
                if fish_id not in FISH_BY_ID:
                    return '不明な魚'
                ok = sell_fish(profile, fish_id, profile['fish_inventory'][fish_id] if amount == -1 else amount)
            elif action == 'fish_caught' and loc('fishing', 65):
                if data not in FISH_BY_ID:
                    return '不明な魚'
                add_catch(profile, data)
                ok = True
            elif action == 'claim':
                ok = claim_mission(profile, data)
            elif action == 'story':
                ok = isinstance(data, str) and len(data) < 129 and finish_story(profile, data)
            else:
                return '施設から離れているか、不明な操作です'
            if ok:
                self._save_host()
                return '反映しました（お金・所持品・ミッションは個人別）'
            return '操作できませんでした（所持数や育成状況を確認してください）'
        except (KeyError, ValueError, TypeError, IndexError, OverflowError):
            return '操作データが不正です'
        except (OSError, SaveError):
            return 'ホスト側でセーブに失敗しました'

    def close(self):
        with self.lock:
            connections = list(self.sockets.values())
            self.sockets.clear()
            self.players.clear()
        for sock in connections:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        with self.lock:
            self._save_host()


class RoomClient:
    def __init__(self, address, pin, name='Player', timeout=5, profile=None, host_token=None):
        if ':' in address and address.count(':') == 1:
            host, port = address.rsplit(':', 1)
            port = int(port)
        else:
            host, port = address, PORT
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.settimeout(timeout)
        profile = validate_state(copy.deepcopy(profile)) if profile is not None else new_state()
        hello = {'type': 'hello', 'protocol': PROTOCOL, 'pin': str(pin).strip(),
                 'name': safe_name(name), 'profile': profile}
        if host_token:
            hello['host_token'] = host_token
        self.sock.sendall(pack(hello))
        self.reader = self.sock.makefile('rb')
        raw = self.reader.readline(MAX_PACKET + 1)
        if not raw or len(raw) > MAX_PACKET:
            self.sock.close()
            raise ConnectionError('No response from host')
        welcome = json.loads(raw.decode('utf-8'))
        if welcome.get('type') != 'welcome':
            self.sock.close()
            raise ConnectionError(welcome.get('message', 'Connection denied'))
        self.id = welcome['id']
        self.spawn = welcome.get('spawn', list(SPAWN))
        self.inbox = queue.Queue(maxsize=12)
        self.out_lock = threading.Lock()
        self.active = True
        self.sock.settimeout(None)
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()

    def _reader_loop(self):
        try:
            while self.active:
                raw = self.reader.readline(MAX_PACKET + 1)
                if not raw or len(raw) > MAX_PACKET:
                    break
                msg = json.loads(raw.decode('utf-8'))
                if self.inbox.full():
                    try:
                        self.inbox.get_nowait()
                    except queue.Empty:
                        pass
                self.inbox.put_nowait(msg)
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        finally:
            self.active = False
            if not self.inbox.full():
                self.inbox.put_nowait({'type': 'disconnected'})

    def send(self, kind, **kwargs):
        if not self.active:
            return False
        try:
            with self.out_lock:
                self.sock.sendall(pack({'type': kind, **kwargs}))
            return True
        except OSError:
            self.active = False
            return False

    def action(self, action, value):
        return self.send('action', action=action, value=value)

    def chat(self, text):
        return self.send('chat', message=safe_chat(text))

    def poll(self):
        items = []
        while True:
            try:
                items.append(self.inbox.get_nowait())
            except queue.Empty:
                return items

    def close(self):
        self.active = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
