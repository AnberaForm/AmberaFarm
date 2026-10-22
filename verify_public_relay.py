# -*- coding: utf-8 -*-
"""Manual production check. Run separately from offline release preflight."""
import json
import argparse
import secrets
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from farm_core import new_state
from multiplayer import RoomClient, RoomServer, PROTOCOL
from online_rooms import RelayHost, RelayError, connect_guest, search_rooms, _websocket, _reply, _abort
from room_saves import load_room, member_key
from online_ui import wait_for_relay
from area_world import NEIGHBOR
from scene_maps import NEIGHBOR_STORE
from world_map import INTERACTION_POINTS, TRAVEL_STOPS

parser = argparse.ArgumentParser(description='Opt-in live relay integration check. Creates only temporary test rooms and saves.')
parser.add_argument('--endpoint')
parser.add_argument('--report', type=Path)
args = parser.parse_args()
config = json.loads(Path(__file__).with_name('online_config.json').read_text(encoding='utf-8-sig'))
ENDPOINT = args.endpoint or config.get('relay_url', '')
if not ENDPOINT:
    parser.error('Configure online_config.json or supply --endpoint')
checks = []


def check(condition, label):
    assert condition, label
    checks.append(label)
    print('PASS', label, flush=True)


def until(predicate, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.03)
    return False


wait_for_relay(ENDPOINT, threading.Event(), lambda _: None, max_wait=75)
check(True, 'Game service warmup with verified HTTPS health')
clients, resources = [], []
with tempfile.TemporaryDirectory(prefix='ambera_public_probe_') as folder:
    try:
        state = new_state()
        state.update(player_name='DeployHost', coins=117)
        room = RoomServer(state, Path(folder) / 'host.json', port=0,
                          bind='127.0.0.1', pin=f'{secrets.randbelow(1000000):06d}',room_owned=True)
        resources.append(room)
        host = RoomClient(f'127.0.0.1:{room.port}', room.pin, 'DeployHost',
                          profile=state, host_token=room.host_token)
        clients.append(host)
        title='通信テスト_'+secrets.token_hex(4)
        relay = RelayHost(ENDPOINT, room.port, room.pin, PROTOCOL,title=title,name='通信確認',public=True)
        resources.append(relay)
        check(relay.active and len(relay.code) == 8, 'Public WSS searchable room creation')
        rows=search_rooms(ENDPOINT,title,PROTOCOL)
        check(len(rows)==1 and rows[0]['id']==relay.code and set(rows[0])=={'id','title','host','players','max_players'},
              'Room search returns matching room without invitation secrets')
        try:
            bad=connect_guest(ENDPOINT,relay.code,relay.pin,PROTOCOL)
        except RelayError as exc:
            check(exc.code=='approval_required','Public room requires host approval even with correct PIN')
        else:
            bad.close()
            raise AssertionError('Public room admitted an unapproved guest')

        def admission(name,accept=True):
            ws=_websocket(ENDPOINT)
            try:
                ws.send(json.dumps({'op':'request','version':1,'protocol':PROTOCOL,'code':relay.code,'name':name}))
                pending=_reply(ws)
                assert pending['type']=='pending'
                assert until(lambda:any(r['id']==pending['id'] for r in relay.pending_requests()))
                relay.decide(pending['id'],accept)
                return _reply(ws)
            finally:_abort(ws)

        rejected=False
        try:admission('見送り確認',False)
        except RelayError as exc:rejected=exc.code=='rejected'
        check(rejected,'Host rejection reaches applicant')
        withdrawn=_websocket(ENDPOINT)
        withdrawn.send(json.dumps({'op':'request','version':1,'protocol':PROTOCOL,'code':relay.code,'name':'取消確認'}))
        pending=_reply(withdrawn)
        check(until(lambda:any(r['id']==pending['id'] for r in relay.pending_requests())),'Pending request reaches host inbox')
        _abort(withdrawn)
        check(until(lambda:all(r['id']!=pending['id'] for r in relay.pending_requests())),'Cancelled request is removed from host inbox')
        guests = []
        identities=[]
        for name, coins in [('DeployGuestA', 83), ('DeployGuestB', 41)]:
            profile = new_state()
            profile['coins'] = coins
            grant=admission(name)
            check(grant['type']=='approved','Host approves '+name)
            transport = connect_guest(ENDPOINT, relay.code, relay.pin, PROTOCOL,approval=grant['approval'])
            identity=secrets.token_hex(32)
            identities.append(identity)
            guest = RoomClient('relay', relay.pin, name, profile=profile,
                               connection=transport,identity=identity)
            clients.append(guest)
            guests.append(guest)
        check(until(lambda: len(room.players) == 3), 'Two guests via Render WSS to loopback host')
        for guest in guests:
            packets = []

            def personal_snapshot():
                packets.extend(guest.poll())
                return any(p.get('type') == 'snapshot' and p['state']['coins'] == 200
                           and all('coins' not in x for x in p['players']) for p in packets)

            check(until(personal_snapshot), 'Room starter wallet ignores client save and hides other balances')
        check(room.host_profile['coins']==200,'Host cannot bring personal save balance into room')
        with room.lock:
            room.players[guests[0].id]['profile']['coins']=319
            room._save_host()
        guests[0].close()
        check(until(lambda:guests[0].id not in room.players),'Guest disconnect saved by host')
        grant=admission('DeployGuestA')
        transport=connect_guest(ENDPOINT,relay.code,relay.pin,PROTOCOL,approval=grant['approval'])
        rejoined=RoomClient('relay',relay.pin,'DeployGuestA',connection=transport,identity=identities[0])
        clients.append(rejoined);guests[0]=rejoined
        packets=[]
        def resumed():
            packets.extend(rejoined.poll())
            return any(p.get('type')=='snapshot' and p['state']['coins']==319 for p in packets)
        check(until(resumed),'Returning guest resumes only progress earned in this farm')
        check(load_room(Path(folder)/'host.json')[1][member_key(identities[0])]['coins']==319,
              'Room progress persisted on host, not imported from guest PC')
        guests[0].chat('公開サーバー接続確認')
        packets = []

        def receive_chat():
            packets.extend(guests[1].poll())
            return any(any(m.get('text') == '公開サーバー接続確認'
                           for m in p.get('chat', [])) for p in packets)

        check(until(receive_chat), 'Japanese chat between guests')
        with room.lock:
            room.players[guests[0].id].update(x=INTERACTION_POINTS['hall'][0],
                                             y=INTERACTION_POINTS['hall'][1])
        guests[0].action('area_enter', 'room:hall')
        check(until(lambda: room.players[guests[0].id]['area'] == 'room:hall'),
              'Interior map warp through public relay')
        with room.lock:
            room.players[host.id]['x'], room.players[host.id]['y'] = next(iter(TRAVEL_STOPS.values()))[1]
        host.action('area_enter', NEIGHBOR)
        check(until(lambda: room.players[host.id]['area'] == NEIGHBOR), 'Neighbor town warp')
        with room.lock:
            room.players[host.id].update(scene_x=637., scene_y=350.)
        host.action('area_enter', NEIGHBOR_STORE)
        packets = []

        def neighbor_snapshot():
            packets.extend(guests[1].poll())
            return any(any(p.get('id') == host.id and p.get('area') == NEIGHBOR_STORE
                           for p in packet.get('players', [])) for packet in packets)

        check(until(neighbor_snapshot), 'Neighbor store map reaches guest')
        denied = False
        try:
            bad = connect_guest(ENDPOINT, relay.code, '000001' if relay.pin == '000000' else '000000', PROTOCOL)
        except ConnectionError:
            denied = True
        else:
            bad.close()
        check(denied, 'Incorrect room PIN rejected')
        check(until(lambda: guests[0].latency_ms is not None), 'Game heartbeat round trip')
        relay.close()
        check(until(lambda: all(not g.active for g in guests)), 'Host leaving disconnects guests')
        denied = False
        try:
            bad = connect_guest(ENDPOINT, relay.code, relay.pin, PROTOCOL)
        except ConnectionError:
            denied = True
        else:
            bad.close()
        check(denied, 'Closed room cannot be rejoined')
    finally:
        for client in reversed(clients):
            client.close()
        for resource in reversed(resources):
            resource.close()
report = {'endpoint': ENDPOINT, 'checks_passed': len(checks), 'checks': checks,
          'scope': 'One runner through public Render; separate player PCs and internet connections unverified'}
if args.report:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False), flush=True)
