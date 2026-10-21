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
from fishing_core import FISH_BY_ID, FishingRound, roll_fish, add_catch, sell_fish
from story_engine import finish_story
from world_map import can_stand, plot_world, INTERACTION_POINTS, TRAVEL_STOPS, nearest_travel_stop
from farm_mailbox import load as load_public_mail
from v8_features import (field_action, buy_consumable, use_consumable, init_v8, restore_stamina,
                         exchange_event, new_outfit, OUTFIT_COLORS, receive_public_mail)
from town_features import move_chest, rest_in_bed
from life_hub import claim_login_reward, craft_decor, set_decor, claim_all_mail, EMOTES
from player_movement import walkable_short_path, path_is_clear
from coop_orders import new_board, view as board_view, contribute as contribute_order
from kabuball_core import KabuballMatch
from character_avatars import IDS as AVATAR_IDS
from neighbor_town import town_buy
from interior_world import SPAWN as ROOM_SPAWN
from scene_maps import (NEIGHBOR_STORE, NEIGHBOR_DOOR, spawn as scene_spawn,
                        path_clear as scene_path_clear, nearby as scene_nearby)
from area_world import (OUTDOOR, NEIGHBOR, AREAS, can_enter, at_facility,
                        area_view, valid_scene_point, DIRECTIONS)
from profile_progress import (init_profile, public_profile, refresh_progress,
                              claim_daily, apply_arena_result, clean_bio, unlocked_titles)

PORT = 47821
MAX_PLAYERS = 8
MAX_PACKET = 131072
PROTOCOL = 13
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
        self.party_invites={}
        self.duels = {}  # temporary server-authoritative mini-game matches
        self.next_duel_id = 0
        self.arena_matches = {}
        self.next_arena_id = time.time_ns()
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
                            'x': x, 'y': y, 'last': time.monotonic(), 'move_seq': -1, 'move_step_seq': 0,
                            'profile': profile, 'last_chat': 0., 'last_rescue': 0.,
                            'uid':profile['player_uid'], 'emote':'', 'emote_seq':0, 'emote_until':0., 'last_emote':0., 'party_id':None,
                            'area':OUTDOOR, 'scene_x':ROOM_SPAWN[0], 'scene_y':ROOM_SPAWN[1],
                            'scene_seq':-1, 'scene_revision':0, 'scene_last':time.monotonic(),
                            'facing':'down', 'fishing':None,
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
                    last_ack_seq = -1
                    last_scene_ack = -1
                    while True:
                        now = time.monotonic()
                        packets = []
                        with parent.lock:
                            parent._arena_tick(now)
                            parent._fishing_tick(now)
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
                                    'arena': parent.arena_view(pid),
                                    'leaderboard': parent.arena_leaderboard(),
                                    'coop_board': board_view(parent.coop_board),
                                    'friend_invites': [{'id': x, 'name': parent.players[x]['name']}
                                                       for x in parent.friend_invites.get(pid, []) if x in parent.players],
                                    'party': parent.party_view(pid),
                                    'story_nodes': parent.story_nodes,
                                    'players': [dict({k: member[k] for k in ('id', 'name', 'x', 'y', 'uid', 'emote', 'emote_seq', 'area', 'scene_x', 'scene_y', 'facing')},
                                                     public_profile=public_profile(member['profile']))
                                                for member in parent.players.values()],
                                    'self_pos': [player['x'], player['y']],
                                    'self_area': area_view(player),
                                    'fishing': parent.fishing_view(pid),
                                    'move_seq': player['move_seq'],
                                    'move_step_seq': player['move_step_seq'],
                                    'chat': list(parent.chat_log[-30:]),
                                })
                                last_state = now
                                seen_world_revision = parent.world_revision
                            # Position-only updates: roughly 12Hz; no deep copied profile.
                            if now - last_positions >= POSITION_INTERVAL:
                                positions = tuple((key, round(member['x'], 2), round(member['y'], 2),
                                                   member.get('area',OUTDOOR), round(member.get('scene_x',0),2),
                                                   round(member.get('scene_y',0),2), member.get('scene_revision',0))
                                                  for key, member in parent.players.items())
                                arena_running=parent.arena_view(pid) and parent.arena_view(pid)['status']=='active'
                                if (positions != last_position_hash or now - last_position_sent >= 1.0
                                        or player['move_seq'] != last_ack_seq
                                        or player.get('scene_seq',-1) != last_scene_ack
                                        or arena_running or player.get('fishing')):
                                    packets.append({
                                        'type': 'positions',
                                        'players': [dict({k: member[k] for k in ('id', 'name', 'x', 'y', 'uid', 'emote', 'emote_seq', 'area', 'scene_x', 'scene_y', 'facing')},
                                                         public_profile=public_profile(member['profile']))
                                                    for member in parent.players.values()],
                                        'self_pos': [player['x'], player['y']],
                                        'self_area': area_view(player),
                                        'fishing': parent.fishing_view(pid),
                                        'move_seq': player['move_seq'],
                                    'move_step_seq': player['move_step_seq'],
                                        'arena': parent.arena_view(pid),
                                    })
                                    last_position_hash = positions
                                    last_position_sent = now
                                    last_ack_seq = player['move_seq']
                                    last_scene_ack = player.get('scene_seq',-1)
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
                            elif kind == 'arena_input':
                                parent._arena_input(pid, incoming.get('input'))
                            elif kind == 'area_move':
                                parent._area_move(pid, incoming)
                            elif kind == 'fish_input':
                                parent._fish_input(pid, incoming)
                            elif kind == 'action':
                                result = parent._action(pid, incoming)
                                # Notify peers quickly (also for friend/duel changes).
                                parent.world_revision += 1
                                profile = parent.players[pid]['profile']
                                response = {'type': 'result', 'message': result,
                                    'warp_to': list(TRAVEL_STOPS[incoming.get('value')][1])
                                        if incoming.get('action')=='travel' and isinstance(result,str)
                                        and result.startswith('馬車で移動') else None,
                                    'state': merged_view(profile, parent.state['plots'], parent.state['plot_preparation']),
                                    'duel': parent.duel_view(pid),
                                    'arena': parent.arena_view(pid),
                                    'leaderboard': parent.arena_leaderboard(),
                                    'coop_board': board_view(parent.coop_board),
                                    'friend_invites': [{'id': x, 'name': parent.players[x]['name']}
                                                      for x in parent.friend_invites.get(pid, []) if x in parent.players],
                                    'party': parent.party_view(pid)}
                                response['self_area'] = area_view(parent.players[pid])
                                response['fishing'] = parent.fishing_view(pid)
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
                            parent._arena_disconnect(pid)
                            parent.friend_invites.pop(pid,None)
                            parent.party_invites.pop(pid,None)
                            for target,inviter in list(parent.party_invites.items()):
                                if inviter==pid:parent.party_invites.pop(target,None)
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

    def party_view(self,pid):
        player=self.players[pid]
        ident=player.get('party_id')
        members=[{'id':q['id'],'name':q['name']}
                 for q in self.players.values() if ident is not None and q.get('party_id')==ident]
        inviter=self.players.get(self.party_invites.get(pid))
        return {'members':members, 'invite':{'id':inviter['id'],'name':inviter['name']} if inviter else None}

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
        """Accept frame-by-frame validated trails, not a blind line from A to B.

        The writer coalesces 12Hz movement packets. Under network lag, the old
        endpoint-only validation could reject a completely legal route around
        a building. Trail steps have monotonic IDs and are replayed only until
        acknowledged; the server validates every segment and cumulative speed.
        """
        p = self.players[pid]
        if p.get('area', OUTDOOR) != OUTDOOR:
            return
        if data.get('facing') in DIRECTIONS:
            p['facing'] = data['facing']
        seq = data.get('seq')
        if type(seq) is int and 0 <= seq <= 2_147_483_647:
            if seq <= p['move_seq']:
                return
            p['move_seq'] = seq  # ACK invalid or rejected moves too.
        try:
            x, y = float(data.get('x')), float(data.get('y'))
            if not (math.isfinite(x) and math.isfinite(y)):
                return
        except (ValueError, TypeError, OverflowError):
            return
        now = time.monotonic()
        elapsed = max(.01, min(1.5, now - p['last']))
        allowed_distance = max(23., 205. * elapsed * 1.35 + 9.)
        start = (p['x'], p['y'])

        if 'path' in data:
            path = data['path']
            if not isinstance(path, list) or len(path) > 144:
                return
            last_id = p.get('move_step_seq', 0)
            new_steps = []
            previous_id = -1
            for point in path:
                if (not isinstance(point, (list, tuple)) or len(point) != 3
                        or type(point[0]) is not int or not 0 <= point[0] <= 2_147_483_647
                        or point[0] <= previous_id):
                    return
                previous_id = point[0]
                if point[0] <= last_id:
                    continue
                try:
                    sx, sy = float(point[1]), float(point[2])
                except (TypeError, ValueError, OverflowError):
                    return
                if not (math.isfinite(sx) and math.isfinite(sy)):
                    return
                new_steps.append((point[0], sx, sy))
            if not new_steps:
                return
            # The last frame must be the destination, so the path itself cannot
            # conceal an unchecked extra teleport at the end.
            if math.dist((new_steps[-1][1], new_steps[-1][2]), (x, y)) > .035:
                return
            cursor = start
            travelled = 0.0
            for _, sx, sy in new_steps:
                nxt = (sx, sy)
                delta = math.dist(cursor, nxt)
                travelled += delta
                # Individual 60Hz render steps are normally ~3.5 px. 15px
                # tolerates frame stalls while forbidding arbitrary jumps.
                if (delta > 15.0 or not walkable_short_path(cursor, nxt, max_length=15.0)
                        or travelled > allowed_distance):
                    return
                cursor = nxt
            p.update(x=cursor[0], y=cursor[1], last=now,
                     move_step_seq=new_steps[-1][0])
            return

        # Keep the old validator for direct unit tests and legacy internal
        # callers. Network peers use PROTOCOL 9 and always send a trail.
        if (math.dist(start, (x,y)) > allowed_distance or not can_stand(x,y)
                or not walkable_short_path(start, (x,y), max_length=allowed_distance)):
            return
        p.update(x=x, y=y, last=now)

    def _enter_area(self, pid, target):
        p = self.players[pid]
        if not isinstance(target, str) or not can_enter(p, target):
            return '入口または馬車の停留所に近づいてください'
        if any(pid in m.ids and m.status in ('pending','active') for m in self.arena_matches.values()):
            return '対戦中は移動できません'
        sx, sy = scene_spawn(target, p.get('area', OUTDOOR))
        p.update(area=target, scene_x=sx, scene_y=sy,
                 scene_seq=-1, scene_revision=p.get('scene_revision',0)+1,
                 scene_last=time.monotonic(), fishing=None, facing='up')
        return '移動しました'

    def _area_move(self, pid, data):
        p = self.players[pid]
        seq = data.get('seq')
        if (p.get('area', OUTDOOR) == OUTDOOR or data.get('area') != p['area']
                or data.get('revision') != p.get('scene_revision',0)
                or type(seq) is not int or not 0 <= seq <= 2_147_483_647
                or seq <= p.get('scene_seq',-1)):
            return
        p['scene_seq'] = seq
        x, y = data.get('x'), data.get('y')
        if not valid_scene_point(x,y,p['area']):
            return
        now = time.monotonic()
        allowed = max(14., 205*min(.6,max(0,now-p['scene_last']))*1.35+9)
        if math.dist((p['scene_x'],p['scene_y']),(x,y)) > allowed:
            return
        if not scene_path_clear(p['area'], (p['scene_x'],p['scene_y']), (x,y)):
            return
        p.update(scene_x=x, scene_y=y, scene_last=now)
        if data.get('facing') in DIRECTIONS:
            p['facing'] = data['facing']

    def fishing_view(self, pid):
        session = self.players[pid].get('fishing')
        if session is None:
            return None
        return dict(session['round'].view(), id=session['id'])

    def _fish_input(self, pid, data):
        p = self.players[pid]
        session = p.get('fishing')
        direction, reeling = data.get('direction'), data.get('reeling')
        if (session is None or data.get('id') != session['id']
                or type(direction) is not int or direction not in (-1,0,1)
                or type(reeling) is not bool or session['round'].result):
            return
        session.update(direction=direction, reeling=reeling, input_at=time.monotonic())

    def _fishing_tick(self, now):
        changed = False
        for p in self.players.values():
            session = p.get('fishing')
            if session is None or session['round'].result:
                continue
            r = session['round']
            dt = max(0., min(.12,now-session['last']))
            session['last'] = now
            if p.get('area',OUTDOOR) != OUTDOOR or not at_facility(p,'fishing',65):
                r.result = 'escaped'
            else:
                fresh = now-session['input_at'] < .4
                r.step(dt, session['direction'] if fresh else 0, session['reeling'] and fresh)
            if r.result:
                changed = True
                if r.result == 'caught' and not session['claimed']:
                    add_catch(p['profile'],r.fish_id)
                    refresh_progress(p['profile'])
                    session['claimed'] = True
        if changed:
            self.world_revision += 1
            self._save_host()

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
                owner['profile']['profile_cache'][peer['uid']]=public_profile(peer['profile'])
            self._save_host()
            return 'フレンドになりました！'
        return '対応していない申請です'

    def arena_view(self,pid):
        now=time.monotonic()
        eligible=[m for m in self.arena_matches.values() if pid in m.ids
                  and (m.status in ('pending','active') or now-m.ended_at<35)]
        if eligible:
            m=max(eligible,key=lambda x:(x.status in ('pending','active'),x.id))
            view=m.view(pid,now)
            enemy=m.ids[1-view['side']]
            view['opponent']=self.players.get(enemy,{}).get('name','相手')
            return view
        return None

    def arena_leaderboard(self):
        values=[]
        for player in self.players.values():
            rec=player['profile']['arena_record']
            values.append({'name':player['name'], 'rating':rec['rating'], 'wins':rec['wins'], 'uid':player['uid']})
        return sorted(values,key=lambda x:(-x['rating'],-x['wins'],x['name']))[:8]

    def _arena_tick(self,now=None):
        now=time.monotonic() if now is None else now
        for ident,m in list(self.arena_matches.items()):
            if m.status=='pending' and now-m.created>40:
                m.abort(now)
            if m.status=='active':m.step(now)
            if m.status=='finished' and not m.completed:
                # Unique completion; no virtual-currency transfers in LAN games.
                for idx,pid in enumerate(m.ids):
                    player=self.players.get(pid)
                    opponent=self.players.get(m.ids[1-idx])
                    if player is None or opponent is None:continue
                    apply_arena_result(player['profile'],m.scores[idx],m.scores[1-idx],
                        opponent['name'],m.id)
                m.completed=True
                self.world_revision+=1
                try:self._save_host()
                except (OSError,SaveError):pass
            if m.status in ('finished','canceled') and now-m.ended_at>40:
                self.arena_matches.pop(ident,None)

    def _arena_disconnect(self,pid):
        for m in self.arena_matches.values():
            if pid in m.ids and m.status in ('pending','active'):
                m.reason='相手が切断しました。試合は無効です。'
                m.abort()
                self.world_revision+=1

    def _arena_input(self,pid,data):
        m=next((m for m in self.arena_matches.values() if pid in m.ids and m.status=='active'),None)
        if m is not None:m.update_input(pid,data)

    def _arena_action(self,pid,action,data):
        me=self.players[pid]
        near=lambda p:at_facility(p,'hall',120)
        match=next((m for m in self.arena_matches.values() if pid in m.ids and m.status in ('pending','active')),None)
        finished=next((m for m in reversed(list(self.arena_matches.values())) if pid in m.ids and m.status=='finished'),None)
        if action=='arena_challenge':
            if match:return 'すでに対戦中です'
            if not isinstance(data,dict) or data.get('stake',0)!=0:
                return 'ゲーム内Gを賭ける機能は安全な中央サーバーができるまで無効です'
            target=self.players.get(data.get('target'))
            if not target or target is me or not near(me) or not near(target):
                return '集会所の近くにいるプレイヤーを選んでください'
            if any(target['id'] in m.ids and m.status in ('pending','active') for m in self.arena_matches.values()):
                return '相手はすでに対戦中です'
            self.next_arena_id+=1
            m=KabuballMatch(self.next_arena_id,pid,target['id'])
            self.arena_matches[m.id]=m
            return 'カブボールの招待を送りました！'
        if action=='arena_replay':
            if match is not None or finished is None or time.monotonic()-finished.ended_at>35:
                return '再戦できる相手が見つかりません'
            finished.invited_replay.add(pid)
            if len(finished.invited_replay)==2 and all(x in self.players for x in finished.ids):
                self.next_arena_id+=1
                newer=KabuballMatch(self.next_arena_id,*finished.ids)
                self.arena_matches[newer.id]=newer
                newer.accept()
                return '再戦が始まります！'
            return '再戦を申請しました。相手の承諾待ちです'
        if match is None:return '対戦が見つかりません'
        if action=='arena_forfeit' and match.status=='active':
            match.reason='プレイヤーが対戦から退出しました'
            match.abort()
            self.world_revision+=1
            return '対戦を終了しました'
        if action=='arena_accept' and match.status=='pending' and pid==match.ids[1]:
            if not all(x in self.players for x in match.ids):return '参加者が切断しました'
            match.accept();return 'カブボール開始！ WASD移動・Jシュート・K奪取'
        if action=='arena_reject' and match.status=='pending' and pid==match.ids[1]:
            match.reason='相手が招待を断りました';match.abort();return '招待を断りました'
        if action=='arena_cancel' and match.status=='pending':
            match.reason='招待が取り消されました';match.abort();return '招待を取り消しました'
        return '現在この操作はできません'

    def _duel_action(self,pid,action,data):
        """Room-only competitive games; only virtual G. Two-party consent & escrow.

        All scoring uses authoritative server time and server-generated targets.
        """
        me=self.players[pid]
        nearby=lambda x:at_facility(x,'hall',100)
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
        loc = lambda key, radius: at_facility(p,key,radius)
        if action == 'area_enter':
            return self._enter_area(pid,data)
        if action == 'fish_start':
            if p.get('area',OUTDOOR) != OUTDOOR or not loc('fishing',65):
                return '湖の釣り場に近づいてください'
            active = p.get('fishing')
            if active and not active['round'].result:
                return '釣りはすでに始まっています'
            now = time.monotonic()
            p['fishing'] = {'id':secrets.token_hex(8), 'round':FishingRound(roll_fish().id),
                            'last':now, 'input_at':now, 'direction':0, 'reeling':False, 'claimed':False}
            return '釣り開始！ 魚が暴れたらSPACEを離そう'
        if action == 'fish_cancel':
            p['fishing'] = None
            return '釣りを終了しました'
        if action == 'fish_caught':
            return '釣果はホストが判定します'
        # Room-host-validated personal rewards and non-currency social actions.
        if action == 'party_invite':
            target=self.players.get(data) if isinstance(data,str) else None
            if not target or target is p:return '同じ部屋のプレイヤーを選択してください'
            if target['uid'] not in profile.get('friend_ids',[]):return 'フレンドを招待してください'
            if p.get('party_id') and p['party_id']==target.get('party_id'):
                return '既に同じパーティです'
            self.party_invites[target['id']]=pid
            return f'{target["name"]}さんを協力パーティに招待しました'
        if action == 'party_accept':
            inviter=self.players.get(self.party_invites.pop(pid,None))
            if not inviter:return '招待は期限切れか取り消されました'
            party=inviter.get('party_id') or inviter['id']
            inviter['party_id']=party;p['party_id']=party
            return f'{inviter["name"]}さんのパーティに参加しました'
        if action == 'party_leave':
            if p.get('party_id') is None:return 'パーティに参加していません'
            p['party_id']=None
            return 'パーティから離脱しました'
        if action == 'login_claim':
            if claim_login_reward(profile):
                self._save_host();return '本日のログイン報酬を受け取りました！'
            return '本日のログイン報酬は受取済みです'
        if action == 'mail_claim_all':
            count = claim_all_mail(profile, load_public_mail())
            if count:self._save_host()
            return f'プレゼント {count}件を受け取りました'
        if action == 'avatar_select':
            if data not in AVATAR_IDS:return '選択できないキャラクターです'
            profile['avatar_id']=data
            self._save_host()
            return 'キャラクター外観を切り替えました'
        if action == 'neighbor_buy':
            if not isinstance(data,dict):return '購入情報が不正です'
            if p.get('area') != NEIGHBOR_STORE or scene_nearby(NEIGHBOR_STORE,(p['scene_x'],p['scene_y']),115) is None:
                return 'みずほ町のお店に近づいてください'
            if town_buy(profile,data.get('crop'),data.get('count')):
                self._save_host();return '隣町の種を購入しました'
            return '購入できません。所持金・商品を確認してください'
        if action == 'profile_favorite':
            if not isinstance(data,str) or data not in CROP_BY_ID:return '作物を選んでください'
            profile['favorite_crop']=data
            self._save_host();return 'お気に入り作物を変更しました'
        if action in ('decor_craft','decor_equip'):
            if not loc('home', 100):return '自宅の近くで模様替えしてください'
            if not isinstance(data,str):return '家具の指定が不正です'
            ok = craft_decor(profile,data) if action=='decor_craft' else set_decor(profile,data)
            if ok:self._save_host()
            return '模様替えを保存しました' if ok else '材料が足りない、または選択できない家具です'
        if action == 'emote':
            now=time.monotonic()
            if not isinstance(data,str) or data not in EMOTES:return 'エモートの指定が不正です'
            if now-p.get('last_emote',0)<1.5:return 'エモートは少し時間をあけてください'
            p['emote']=data;p['emote_seq']+=1;p['emote_until']=now+3.5;p['last_emote']=now
            return 'エモートを表示しました'
        if action == 'gift_item':
            if not isinstance(data,dict):return 'プレゼント内容が不正です'
            target_id=data.get('target')
            target=self.players.get(target_id) if isinstance(target_id,str) else None
            item=data.get('item');qty=data.get('count')
            if (not target or target is p or item not in ('tea','riceball','lunch')
                    or type(qty) is not int or qty not in (1,2,3)):
                return '贈り物の宛先・数量が不正です'
            if target['uid'] not in profile.get('friend_ids',[]):return 'フレンドにだけ送れます'
            if p.get('area',OUTDOOR) != target.get('area',OUTDOOR):
                return '同じ場所にいるフレンドに近づいてください'
            a = (p['x'],p['y']) if p.get('area',OUTDOOR)==OUTDOOR else (p['scene_x'],p['scene_y'])
            b = (target['x'],target['y']) if target.get('area',OUTDOOR)==OUTDOOR else (target['scene_x'],target['scene_y'])
            if math.dist(a,b)>115:
                return '相手に近づいてください'
            if profile['consumables'][item]<qty:return 'プレゼントするアイテムが不足しています'
            if target['profile']['consumables'][item]+qty>9999:return '相手の持ち物がいっぱいです'
            profile['consumables'][item]-=qty
            target['profile']['consumables'][item]+=qty
            self._save_host()
            return f'{target["name"]}さんにアイテムを{qty}個送りました'
        if action == 'coop_contribute':
            if not isinstance(data, dict):return '納品内容を確認してください'
            result = contribute_order(self.coop_board, data.get('id'), pid, profile,
                                      self.players, data.get('count', 1))
            if '共同納品 +' in result or '達成！' in result:
                try:self._save_host()
                except (OSError,SaveError):return '納品結果のセーブに失敗しました（ホストに連絡してください）'
            return result
        if isinstance(action,str) and action.startswith('arena_'):
            return self._arena_action(pid,action,data)
        if action=='profile_bio':
            if not isinstance(data,str) or len(data)>90:return '自己紹介は90文字以内です'
            profile['profile_bio']=clean_bio(data)
            for other in self.players.values():
                if p['uid'] in other['profile']['friend_ids']:
                    other['profile']['profile_cache'][p['uid']]=public_profile(profile)
            self._save_host();return '自己紹介を更新しました'
        if action=='goal_effect':
            if type(data) is not int or data not in (0,1,2) or (data==1 and profile['arena_record']['wins']<1) or (data==2 and profile['arena_record']['wins']<5):
                return 'ゴール演出は勝利数によって解放されます'
            profile['goal_effect']=data
            self._save_host();return 'ゴール演出を変更しました'
        if action=='profile_title':
            if data not in unlocked_titles(profile):return '未取得の称号です'
            profile['profile_title']=data
            for other in self.players.values():
                if p['uid'] in other['profile']['friend_ids']:
                    other['profile']['profile_cache'][p['uid']]=public_profile(profile)
            self._save_host();return '称号を設定しました'
        if action=='daily_claim':
            refresh_progress(profile)
            if claim_daily(profile,data):
                self._save_host();return '村の依頼を達成しました！'
            return '依頼がまだ未達成か、受取済みです'
        if action in ('friend_request','friend_accept'):
            return self._friend_action(pid,action,data)
        if isinstance(action,str) and action.startswith('duel_'):
            return self._duel_action(pid,action,data)
        if action == 'travel':
            if p.get('area',OUTDOOR) != OUTDOOR:return '町の馬車の停留所に戻ってください'
            from_stop=nearest_travel_stop(p['x'],p['y'],75)
            if not isinstance(data,str) or data not in TRAVEL_STOPS or from_stop is None:
                return '馬車の停留所に近づいてください'
            target_name,(tx,ty)=TRAVEL_STOPS[data]
            if not can_stand(tx,ty):return '行き先に障害物があります'
            now=time.monotonic()
            if now-p.get('last_travel',0)<2.0:return '馬車の次の便を待ってください'
            if any(pid in match.ids and match.status in ('pending','active')
                   for match in self.arena_matches.values()):
                return '対戦中は馬車を使えません'
            p.update(x=tx,y=ty,last=now,last_travel=now)
            profile['player']=[tx,ty]
            self._save_host()
            return f'馬車で移動しました：{target_name}'
        if action == 'home_rest' and loc('home', 100):
            if rest_in_bed(profile):self._save_host();return 'ベッドで休憩して体力が回復しました'
            return 'すでに元気いっぱいです'
        if action == 'home_chest' and loc('home', 100):
            if not isinstance(data,dict):return '収納内容が不正です'
            if move_chest(profile,data.get('category'),data.get('item'),data.get('count'),data.get('withdraw',False)):
                self._save_host();return '自宅の収納を更新しました'
            return '持ち物の数を確認してください'
        if action == 'rescue':
            now = time.monotonic()
            if now - p['last_rescue'] < 12:
                return '緊急脱出は12秒ごとに使えます'
            p.update(x=SPAWN[0], y=SPAWN[1], last=now, last_rescue=now, area=OUTDOOR,
                     scene_revision=p.get('scene_revision',0)+1, fishing=None)
            p['profile']['player'] = list(SPAWN)
            return '安全な場所に移動しました'
        ok = False
        try:
            if action == 'plot' and isinstance(data, dict):
                if p.get('area',OUTDOOR) != OUTDOOR:return '畑へ戻ってください'
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
                if p.get('area',OUTDOOR) != OUTDOOR:return '畑へ戻ってください'
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
            elif action == 'claim':
                ok = claim_mission(profile, data)
            elif action == 'story':
                ok = isinstance(data, str) and len(data) < 129 and finish_story(profile, data)
            else:
                return '施設から離れているか、不明な操作です'
            if ok:
                refresh_progress(profile)
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

    def clear_unsent_movement(self):
        with self.move_lock:
            self.latest_move = None

    def send(self, kind, **kwargs):
        if not self.active:
            return False
        packet = {'type': kind, **kwargs}
        if kind in ('move','area_move'):
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
