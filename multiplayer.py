# -*- coding: utf-8 -*-
"""LAN co-op protocol v4: low-bandwidth position streaming and async outgoing queue.

Only plots are shared. Each connection has a separate inventory, money, stats,
missions and story flags. Guests save their own profile on their own computer.
Host saves the common plots with the host's profile. PINs are not encryption;
never forward this prototype's port to the public internet.
"""
from __future__ import annotations
import copy
import json
import math
import random
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
from farm_mailbox import load as load_public_mail
from v8_features import (field_action, buy_consumable, use_consumable, init_v8, restore_stamina,
                         exchange_event, new_outfit, OUTFIT_COLORS, receive_public_mail)
from coop_orders import new_board, view as board_view, contribute as contribute_order

PORT = 47821
MAX_PLAYERS = 8
MAX_PACKET = 131072
PROTOCOL = 5
POSITION_INTERVAL = 1.0 / 12.0
STATE_INTERVAL = 1.5
CHAT_INTERVAL = 0.08
SPAWN = (336., 368.)


def pack(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def safe_name(name):
    return ''.join(c for c in str(name) if c.isprintable() and c not in '\r\n\t')[:18].strip() or 'Player'


def safe_chat(message):
    if not isinstance(message, str):
        return ''
    return ''.join(c for c in message if c.isprintable() and c not in '\r\n\t')[:160].strip()


def merged_view(profile, shared_plots, shared_preparation=None):
    """Expose this player's private economy over the authoritative shared farm."""
    view = copy.deepcopy(profile)
    view['plots'] = copy.deepcopy(shared_plots)
    if shared_preparation is not None:
        view['plot_preparation']=copy.deepcopy(shared_preparation)
    return view


class _GameServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 12


class RoomServer:
    def __init__(self, state, save_file, port=PORT, pin=None, story_nodes=None, fresh=False):
        self.pin = str(pin if pin is not None else secrets.randbelow(900000) + 100000)
        self.host_token = secrets.token_hex(24)
        self.state = validate_state(copy.deepcopy(state))
        if fresh:
            self.state['plots']=[None] * PLOT_COUNT
            init_v8(self.state)['plot_preparation']=[0]*PLOT_COUNT
        self.host_profile = copy.deepcopy(self.state)
        self.save_file = Path(save_file)
        self.lock = threading.RLock()
        self.players = {}
        self.sockets = {}
        self.host_id = None
        self.chat_log = []
        self.chat_seq = 0
        self.coop_board = new_board()
        self.world_revision = 0
        self.friend_invites={}
        self.duels = {}  # temporary server-authoritative mini-game matches
        self.next_duel_id = 0
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
                            'uid':profile['player_uid'],
                        }
                        if is_host:
                            parent.host_id = pid
                        parent.sockets[pid] = sock
                    sock.sendall(pack({'type': 'welcome', 'id': pid, 'pin': parent.pin, 'spawn': [x, y]}))
                    # Keep TCP packets small and disable Nagle's delay on position inputs.
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.settimeout(None)
                    last_state = -STATE_INTERVAL
                    last_positions = -POSITION_INTERVAL
                    last_chat = -CHAT_INTERVAL
                    last_chat_seq = 0
                    seen_world_revision = -1
                    last_position_hash = None
                    last_position_sent = 0.
                    while True:
                        now = time.monotonic()
                        packets = []
                        with parent.lock:
                            player = parent.players.get(pid)
                            if player is None:
                                break
                            # Full state is sent initially, following farm edits and
                            # periodically as a recovery / stamina synchronization.
                            if (now - last_state >= STATE_INTERVAL
                                    or seen_world_revision != parent.world_revision):
                                restore_stamina(player['profile'])
                                packets.append({
                                    'type': 'snapshot',
                                    'state': merged_view(player['profile'], parent.state['plots'],
                                                         parent.state['plot_preparation']),
                                    'duel': parent.duel_view(pid),
                                    'coop_board': board_view(parent.coop_board),
                                    'friend_invites': [{'id': x, 'name': parent.players[x]['name']}
                                                       for x in parent.friend_invites.get(pid, []) if x in parent.players],
                                    'story_nodes': parent.story_nodes,
                                    'players': [{k: member[k] for k in ('id', 'name', 'x', 'y', 'uid')}
                                                for member in parent.players.values()],
                                    'self_pos': [player['x'], player['y']],
                                    'chat': list(parent.chat_log[-30:]),
                                })
                                last_state = now
                                seen_world_revision = parent.world_revision
                            # Position-only updates: roughly 12Hz; no deep copied profile.
                            if now - last_positions >= POSITION_INTERVAL:
                                positions = tuple((key, round(member['x'], 2), round(member['y'], 2))
                                                  for key, member in parent.players.items())
                                if positions != last_position_hash or now - last_position_sent >= 1.0:
                                    packets.append({
                                        'type': 'positions',
                                        'players': [{k: member[k] for k in ('id', 'name', 'x', 'y', 'uid')}
                                                    for member in parent.players.values()],
                                        'self_pos': [player['x'], player['y']],
                                    })
                                    last_position_hash = positions
                                    last_position_sent = now
                                last_positions = now
                            # Chat is a separate, tiny and prompt message.
                            if parent.chat_seq > last_chat_seq and now - last_chat >= CHAT_INTERVAL:
                                messages = [m for m in parent.chat_log if m['seq'] > last_chat_seq]
                                if messages:
                                    packets.append({'type': 'chat_delta', 'chat': messages})
                                    last_chat_seq = messages[-1]['seq']
                                last_chat = now
                        # Network writes MUST NOT hold parent.lock: a slow client
                        # must not stall every other player on the host.
                        for outgoing in packets:
                            sock.sendall(pack(outgoing))
                        readable, _, _ = select.select([sock], [], [], .025)
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
                        response = None
                        with parent.lock:
                            if pid not in parent.players:
                                break
                            kind = incoming.get('type')
                            if kind == 'move':
                                parent._move(pid, incoming)
                            elif kind == 'action':
                                result = parent._action(pid, incoming)
                                # Notify peers quickly (also for friend/duel changes).
                                parent.world_revision += 1
                                profile = parent.players[pid]['profile']
                                response = {'type': 'result', 'message': result,
                                    'state': merged_view(profile, parent.state['plots'], parent.state['plot_preparation']),
                                    'duel': parent.duel_view(pid),
                                    'coop_board': board_view(parent.coop_board),
                                    'friend_invites': [{'id': x, 'name': parent.players[x]['name']}
                                                      for x in parent.friend_invites.get(pid, []) if x in parent.players]}
                            elif kind == 'chat':
                                parent._chat(pid, incoming.get('message'))
                            elif kind == 'ping':
                                nonce = incoming.get('nonce')
                                if isinstance(nonce, (int, float)) and math.isfinite(nonce):
                                    response = {'type': 'pong', 'nonce': nonce}
                        if response is not None:
                            sock.sendall(pack(response))
                except (OSError, ValueError, TypeError, OverflowError):
                    pass
                finally:
                    if pid:
                        with parent.lock:
                            parent._duel_disconnect(pid)
                            parent.friend_invites.pop(pid,None)
                            for invites in parent.friend_invites.values():
                                if pid in invites:invites.remove(pid)
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
        self.state = merged_view(self.host_profile, self.state['plots'], self.state['plot_preparation'])
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

    def duel_view(self,pid):
        now=time.monotonic()
        for ident,d in list(self.duels.items()):
            if d['status']=='finished' and now-d['finished_at']>12:
                del self.duels[ident]
        for d in self.duels.values():
            if pid not in (d['a'],d['b']):continue
            opponent=d['b'] if pid==d['a'] else d['a']
            other=self.players.get(opponent)
            return {'id':d['id'],'status':d['status'],'challenger':d['a']==pid,
                    'kind':d['kind'],'stake':d['stake'],
                    'opponent':other['name'] if other else 'Player',
                    'ready':now>=d.get('ready_at',now+1),
                    'submitted':pid in d['moves'],
                    'elapsed':round(now-d.get('started_at',now),3),
                    'outcome':d.get('outcomes',{}).get(pid,'')}
        return None

    def _duel_disconnect(self,pid):
        for ident,d in list(self.duels.items()):
            if pid not in (d['a'],d['b']):continue
            if d['status']=='active':
                # Stake escrow refunds on incomplete matches or disconnections.
                for player_id in (d['a'],d['b']):
                    if player_id in self.players:self.players[player_id]['profile']['coins']+=d['stake']
            del self.duels[ident]
            try:self._save_host()
            except (OSError,SaveError):pass

    def _friend_action(self,pid,action,data):
        me=self.players[pid]
        other=self.players.get(data) if isinstance(data,str) else None
        if not other or other is me:return '相手が見つかりません'
        if action=='friend_request':
            if other['uid'] in me['profile']['friend_ids']:return 'すでにフレンドです'
            invites=self.friend_invites.setdefault(data,[])
            if pid not in invites and len(invites)<12:invites.append(pid)
            return 'フレンド申請を送りました'
        if action=='friend_accept':
            invites=self.friend_invites.get(pid,[])
            if data not in invites:return '申請を確認できません'
            invites.remove(data)
            for owner,peer in ((me,other),(other,me)):
                if peer['uid'] not in owner['profile']['friend_ids']:
                    owner['profile']['friend_ids'].append(peer['uid'])
                if peer['name'] not in owner['profile']['friends']:
                    owner['profile']['friends'].append(peer['name'])
            self._save_host()
            return 'フレンドになりました！'
        return '対応していない申請です'

    def _duel_action(self,pid,action,data):
        """Room-only competitive games; only virtual G. Two-party consent & escrow.

        All scoring uses authoritative server time and server-generated targets.
        """
        me=self.players[pid]
        nearby=lambda x:math.dist((x['x'],x['y']),INTERACTION_POINTS['hall'])<=100
        mine=next((d for d in self.duels.values() if pid in (d['a'],d['b']) and d['status']!='finished'),None)
        if action=='duel_challenge':
            if mine or not isinstance(data,dict):return '対戦中、または招待データが不正です'
            other=self.players.get(data.get('target'))
            kind=data.get('kind');stake=data.get('stake')
            if (not other or other is me or kind not in ('guess','timing','reaction') or
                    type(stake) is not int or stake not in (0,10,50,100) or
                    not nearby(me) or not nearby(other) or me['profile']['coins']<stake or
                    any(other['id'] in (d['a'],d['b']) and d['status']!='finished' for d in self.duels.values())):
                return '集会所に双方がいること、所持金・対戦相手を確認してください'
            self.next_duel_id+=1
            self.duels[self.next_duel_id]=dict(id=self.next_duel_id,a=pid,b=other['id'],
                kind=kind,stake=stake,status='pending',created=time.monotonic(),moves={},outcomes={})
            return '対戦を招待しました。相手の承諾を待っています。'
        if not mine:return '有効な対戦がありません'
        if action=='duel_reject' and mine['status']=='pending' and mine['b']==pid:
            del self.duels[mine['id']]
            return '対戦を断りました'
        if action=='duel_accept' and mine['status']=='pending' and mine['b']==pid:
            opponent=self.players.get(mine['a'])
            if not opponent or not nearby(me) or not nearby(opponent) or any(
                    self.players[x]['profile']['coins']<mine['stake'] for x in (mine['a'],mine['b'])):
                del self.duels[mine['id']]
                return '参加条件を満たしていません'
            for player_id in (mine['a'],mine['b']):
                self.players[player_id]['profile']['coins']-=mine['stake']
            now=time.monotonic()
            mine.update(status='active',started_at=now,ready_at=now+1.6,
                        target=(random.randint(1,3) if mine['kind']=='guess' else (2.6 if mine['kind']=='timing' else 1.6)))
            self._save_host()
            return '対戦開始！ 相手と勝負してください'
        if action=='duel_move' and mine['status']=='active':
            now=time.monotonic()
            if pid in mine['moves']:return 'すでに回答しました'
            if mine['kind']=='guess':
                if type(data) is not int or not 1<=data<=3:return '1〜3を選んでください'
                score=abs(data-mine['target'])
            elif mine['kind']=='timing':
                # Server measured: aim for 2.6sec since start.
                score=abs((now-mine['started_at'])-2.6)
            else:
                # Early press forfeits this reaction round.
                score=(now-mine['ready_at']) if now>=mine['ready_at'] else 999
            mine['moves'][pid]=round(score,5)
            if len(mine['moves'])==2:
                a,b=mine['a'],mine['b'];sa,sb=mine['moves'][a],mine['moves'][b]
                if abs(sa-sb)<0.025:
                    self.players[a]['profile']['coins']+=mine['stake']
                    self.players[b]['profile']['coins']+=mine['stake']
                    mine['outcomes']={a:'引き分け（掛け金返却）',b:'引き分け（掛け金返却）'}
                else:
                    winner=a if sa<sb else b;loser=b if winner==a else a
                    self.players[winner]['profile']['coins']+=mine['stake']*2
                    mine['outcomes']={winner:'勝利！掛け金を獲得',loser:'敗北。再挑戦しよう'}
                mine['status']='finished';mine['finished_at']=now
                self._save_host()
            return '回答しました。結果を確認してください'
        return 'この操作はまだできません'

    def _action(self, pid, msg):
        action = msg.get('action')
        data = msg.get('value')
        p = self.players[pid]
        profile = p['profile']
        # Farm plots and soil preparation are shared; the economy remains private.
        profile['plots'] = self.state['plots']
        profile['plot_preparation'] = self.state['plot_preparation']
        loc = lambda key, radius: math.dist((p['x'], p['y']), INTERACTION_POINTS[key]) <= radius
        if action == 'coop_contribute':
            if not isinstance(data, dict):return '納品内容を確認してください'
            result = contribute_order(self.coop_board, data.get('id'), pid, profile,
                                      self.players, data.get('count', 1))
            if '共同納品 +' in result or '達成！' in result:
                try:self._save_host()
                except (OSError,SaveError):return '納品結果のセーブに失敗しました（ホストに連絡してください）'
            return result
        if action in ('friend_request','friend_accept'):
            return self._friend_action(pid,action,data)
        if isinstance(action,str) and action.startswith('duel_'):
            return self._duel_action(pid,action,data)
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
            elif action == 'field_v8' and isinstance(data, dict):
                idx,crop=data.get('index'),data.get('crop')
                if type(idx) is not int or not 0<=idx<PLOT_COUNT or crop not in CROP_BY_ID:
                    return '畑の指定が不正です'
                if math.dist((p['x'],p['y']),plot_world(idx))>54:
                    return '畑から遠すぎます'
                outcome=field_action(profile,idx,crop)
                ok=outcome in ('till','water','plant','harvest')
            elif action == 'event_trade':
                ok=exchange_event(profile,data)
            elif action == 'mail_claim':
                gift=next((x for x in load_public_mail() if x['id']==data),None)
                ok=bool(gift and receive_public_mail(profile,gift))
            elif action == 'costume_color' and data in ('shirt','hat'):
                draft=profile['outfit_draft']
                draft[data]=(draft[data]+1)%len(OUTFIT_COLORS)
                ok=True
            elif action == 'costume_save':
                ok=new_outfit(profile)
            elif action == 'costume_equip' and type(data) is int:
                ok=0<=data<len(profile['outfits'])
                if ok:profile['outfit_index']=data
            elif action == 'buy_item':
                ok=buy_consumable(profile,data)
            elif action == 'use_item':
                ok=use_consumable(profile,data)
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
        self.inbox = queue.Queue(maxsize=64)
        self.out_lock = threading.Lock()
        self.active = True
        self.sock.settimeout(None)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.send_queue = queue.Queue(maxsize=128)
        self.latest_move = None
        self.latency_ms = None
        self.move_lock = threading.Lock()
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.writer = threading.Thread(target=self._writer_loop, daemon=True)
        self.thread.start()
        self.writer.start()

    def _reader_loop(self):
        try:
            while self.active:
                raw = self.reader.readline(MAX_PACKET + 1)
                if not raw or len(raw) > MAX_PACKET:
                    break
                msg = json.loads(raw.decode('utf-8'))
                if msg.get('type') == 'pong':
                    sent = msg.get('nonce')
                    if isinstance(sent, (int, float)) and math.isfinite(sent):
                        self.latency_ms = max(0, min(60000, (time.monotonic() - sent) * 1000))
                    continue
                if self.inbox.full():
                    # A full queue indicates a stalled renderer. Drop the oldest
                    # item to preserve connection / newest state; position packets
                    # are coalesced on the game side via interpolation.
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

    def _writer_loop(self):
        """Serialize writes away from Pygame's render/input thread.

        Movement is coalesced: older coordinates are discarded rather than queued
        behind chat or farm actions during network congestion.
        """
        try:
            last_ping = 0.
            while self.active:
                try:
                    packet = self.send_queue.get(timeout=.012)
                except queue.Empty:
                    packet = None
                with self.move_lock:
                    move = self.latest_move
                    self.latest_move = None
                if move is not None:
                    self.sock.sendall(pack(move))
                if packet is not None:
                    self.sock.sendall(pack(packet))
                if time.monotonic() - last_ping >= 2.0:
                    last_ping = time.monotonic()
                    self.sock.sendall(pack({'type': 'ping', 'nonce': last_ping}))
        except OSError:
            self.active = False

    def send(self, kind, **kwargs):
        if not self.active:
            return False
        packet = {'type': kind, **kwargs}
        if kind == 'move':
            with self.move_lock:
                self.latest_move = packet
            return True
        try:
            self.send_queue.put_nowait(packet)
            return True
        except queue.Full:
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
