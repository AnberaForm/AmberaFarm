# -*- coding: utf-8 -*-
"""Release preflight: real WebSocket -> TCP -> game authority integration.

Kept at repository root so browser uploads cannot flatten it out of CI's path.
Run: python -m unittest -q verify_online_rooms
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from websockets.asyncio.server import serve
from farm_core import new_state
from multiplayer import RoomClient, RoomServer, PROTOCOL
from online_rooms import (RelayHost, _websocket, _reply, _abort, connect_guest, format_code,
                          invitation, parse_invitation, relay_url)
from relay_server import RelayServer, health_response


def wait_for(predicate, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return True
        time.sleep(.01)
    return False


class RunningRelay:
    def __init__(self):
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError('Relay test server failed to start')

    def _run(self):
        async def run():
            self.loop = asyncio.get_running_loop()
            self.stop = asyncio.Event()
            self.relay = RelayServer(max_rooms=30, pair_timeout=.8)
            async with serve(self.relay.handle, '127.0.0.1', 0,
                             process_request=health_response, compression=None,
                             max_size=131072, max_queue=8, close_timeout=.2,
                             ping_interval=.2, ping_timeout=1) as server:
                port = server.sockets[0].getsockname()[1]
                self.endpoint = f'ws://127.0.0.1:{port}/relay'
                self.ready.set()
                await self.stop.wait()
        asyncio.run(run())

    def close(self):
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(5)


class RelayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.running = RunningRelay()

    @classmethod
    def tearDownClass(cls):
        cls.running.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ambera_relay_test_')
        self.clients = []
        self.resources = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        for resource in reversed(self.resources):
            resource.close()
        self.temp.cleanup()
        self.assertTrue(wait_for(lambda: not self.running.relay.rooms), 'Relay leaked a room')

    def room(self, name='Host', room_owned=False):
        state = new_state()
        state['player_name'] = name
        room = RoomServer(state, Path(self.temp.name) / f'{name}.json', port=0,
                          bind='127.0.0.1', pin='123456', room_owned=room_owned)
        self.resources.append(room)
        host = RoomClient(f'127.0.0.1:{room.port}', room.pin, name,
                          profile=state, host_token=room.host_token)
        self.clients.append(host)
        relay = RelayHost(self.running.endpoint, room.port, room.pin, PROTOCOL)
        self.resources.append(relay)
        return room, host, relay

    def guest(self, relay, name='Guest', coins=83):
        state = new_state()
        state['coins'] = coins
        transport = connect_guest(self.running.endpoint, relay.code, relay.pin, PROTOCOL)
        guest = RoomClient('relay', relay.pin, name, profile=state, connection=transport)
        self.clients.append(guest)
        return guest

    def test_invitation_and_secure_endpoint_validation(self):
        code = format_code('ABCDEFGH', '123456')
        endpoint = 'wss://farm.example/relay'
        self.assertEqual(parse_invitation(invitation(endpoint, code)),
                         (endpoint, 'ABCDEFGH', '123456'))
        self.assertEqual(parse_invitation(' abcd-efgh-123456 ', endpoint),
                         (endpoint, 'ABCDEFGH', '123456'))
        self.assertEqual(relay_url('https://farm.example'), endpoint)
        for bad in ('ws://farm.example/relay', 'wss://u:p@farm.example/relay',
                    'wss://farm.example/relay?q=secret', 'wss://farm.example/other',
                    'ftp://farm.example', 'wss://farm.example:99999', ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                relay_url(bad)
        for bad in ('ABCDEFGH', 'ABCD-EFGH-１２３４５６',
                    'amberafarm://join?relay=x&relay=y&code=z'):
            with self.subTest(code=bad), self.assertRaises(ValueError):
                parse_invitation(bad, endpoint)

    def test_real_chat_and_private_wallets_through_relay(self):
        room, host, relay = self.room()
        a, b = self.guest(relay, 'A', 83), self.guest(relay, 'B', 41)
        self.assertEqual(room.server.server_address[0], '127.0.0.1')
        self.assertTrue(wait_for(lambda: len(room.players) == 3))
        packets = {a.id: [], b.id: []}
        def snapshots():
            for peer in (a, b):
                packets[peer.id].extend(peer.poll())
            return all(any(p.get('type') == 'snapshot' for p in items) for items in packets.values())
        self.assertTrue(wait_for(snapshots))
        for peer, coins in ((a, 83), (b, 41)):
            snap = next(p for p in packets[peer.id] if p.get('type') == 'snapshot')
            self.assertEqual(snap['state']['coins'], coins)
            self.assertTrue(all('coins' not in p for p in snap['players']))
        self.assertTrue(a.chat('部屋コードで接続できた！'))
        received = []
        def chat():
            received.extend(b.poll())
            return any(any(m.get('text') == '部屋コードで接続できた！' for m in p.get('chat', []))
                       for p in received)
        self.assertTrue(wait_for(chat))
        self.assertTrue(wait_for(lambda: a.latency_ms is not None))

    def test_wrong_code_pin_and_version_are_rejected(self):
        room, _, relay = self.room()
        for code, pin, protocol in ((relay.code, '000000', PROTOCOL),
                                    ('ZZZZZZZZ', relay.pin, PROTOCOL),
                                    (relay.code, relay.pin, PROTOCOL + 1)):
            with self.subTest(code=code, pin=pin), self.assertRaises(ConnectionError):
                connect_guest(self.running.endpoint, code, pin, protocol)
        self.assertEqual(len(room.players), 1)

    def test_interiors_and_neighbor_store_warps_replicate_through_relay(self):
        from area_world import NEIGHBOR
        from scene_maps import NEIGHBOR_STORE
        from world_map import INTERACTION_POINTS, TRAVEL_STOPS
        room, host, relay = self.room()
        guest = self.guest(relay)
        with room.lock:
            room.players[guest.id]['x'], room.players[guest.id]['y'] = INTERACTION_POINTS['hall']
        guest.action('area_enter', 'room:hall')
        self.assertTrue(wait_for(lambda: room.players[guest.id]['area'] == 'room:hall'))
        packets = []
        def visible():
            packets.extend(host.poll())
            return any(any(p.get('id') == guest.id and p.get('area') == 'room:hall'
                           for p in packet.get('players', [])) for packet in packets)
        self.assertTrue(wait_for(visible))
        with room.lock:
            room.players[host.id]['x'], room.players[host.id]['y'] = next(iter(TRAVEL_STOPS.values()))[1]
        host.action('area_enter', NEIGHBOR)
        self.assertTrue(wait_for(lambda: room.players[host.id]['area'] == NEIGHBOR))
        with room.lock:
            room.players[host.id].update(scene_x=637., scene_y=350.)
        host.action('area_enter', NEIGHBOR_STORE)
        self.assertTrue(wait_for(lambda: room.players[host.id]['area'] == NEIGHBOR_STORE))
        received = []
        def neighbor_visible():
            received.extend(guest.poll())
            return any(any(p.get('id') == host.id and p.get('area') == NEIGHBOR_STORE
                           for p in packet.get('players', [])) for packet in received)
        self.assertTrue(wait_for(neighbor_visible))

    def test_tunnel_requires_host_secret_and_one_use_ticket(self):
        _, _, relay = self.room()
        ws = _websocket(self.running.endpoint)
        try:
            ws.send(json.dumps({'op': 'tunnel', 'version': 1, 'code': relay.code,
                                'key': '0' * 48, 'ticket': '0' * 48}))
            with self.assertRaises(ConnectionError):
                _reply(ws)
        finally:
            _abort(ws)

    def test_consumed_tunnel_ticket_cannot_be_replayed(self):
        control = _websocket(self.running.endpoint)
        tunnel = replay = transport = None
        pending = {}
        try:
            control.send(json.dumps({'op': 'create', 'version': 1, 'protocol': PROTOCOL, 'pin': '123456'}))
            created = _reply(control)
            def join():
                try:pending['transport'] = connect_guest(self.running.endpoint, created['code'], '123456', PROTOCOL)
                except Exception as exc:pending['error'] = exc
            thread = threading.Thread(target=join, daemon=True)
            thread.start()
            ticket = _reply(control)['ticket']
            request = {'op': 'tunnel', 'version': 1, 'code': created['code'],
                       'key': created['key'], 'ticket': ticket}
            tunnel = _websocket(self.running.endpoint)
            tunnel.send(json.dumps(request))
            self.assertEqual(_reply(tunnel)['type'], 'connected')
            thread.join(3)
            self.assertNotIn('error', pending)
            transport = pending['transport']
            tunnel.send_binary(b'paired bytes\n')
            self.assertEqual(transport.makefile('rb').readline(100), b'paired bytes\n')
            replay = _websocket(self.running.endpoint)
            replay.send(json.dumps(request))
            with self.assertRaises(ConnectionError):_reply(replay)
        finally:
            if transport:transport.close()
            for ws in (control, tunnel, replay):
                if ws:_abort(ws)

    def test_eighth_remote_guest_is_refused_without_kicking_players(self):
        room, _, relay = self.room()
        for i in range(7):
            self.guest(relay, f'Guest{i}')
        self.assertTrue(wait_for(lambda: len(room.players) == 8))
        with self.assertRaises(ConnectionError):
            self.guest(relay, 'TooMany')
        self.assertEqual(len(room.players), 8)

    def test_rooms_are_isolated(self):
        room_a, _, relay_a = self.room('HostA')
        room_b, host_b, relay_b = self.room('HostB')
        self.assertNotEqual(relay_a.code, relay_b.code)
        guest = self.guest(relay_a)
        self.assertTrue(wait_for(lambda: len(room_a.players) == 2))
        self.assertEqual(len(room_b.players), 1)
        guest.chat('Room A only')
        self.assertTrue(wait_for(lambda: bool(room_a.chat_log)))
        self.assertFalse(any(m.get('text') == 'Room A only' for m in room_b.chat_log))

    def test_host_leaving_closes_guest_and_invalidates_room(self):
        room, _, relay = self.room()
        guest = self.guest(relay)
        control = self.running.relay.rooms[relay.code].control
        relay.close()
        self.assertTrue(wait_for(lambda: not guest.active))
        self.assertTrue(wait_for(lambda: relay.code not in self.running.relay.rooms))
        # Proxies can retain upstream TCP after an abrupt socket abort. The
        # close frame must reach the real relay, not just end the local reader.
        self.assertTrue(wait_for(lambda: control.close_code == 1000))
        with self.assertRaises(ConnectionError):
            self.guest(relay)

    def test_authenticated_host_leave_is_acknowledged(self):
        control = _websocket(self.running.endpoint)
        try:
            control.send(json.dumps({'op': 'create', 'version': 1,
                                     'protocol': PROTOCOL, 'pin': '123456'}))
            code = _reply(control)['code']
            control.send(json.dumps({'op': 'leave'}))
            self.assertEqual(_reply(control), {'type': 'closed'})
            self.assertTrue(wait_for(lambda: code not in self.running.relay.rooms))
        finally:
            _abort(control)

    def test_dead_host_pairing_times_out_and_frees_guest_slot(self):
        ws = _websocket(self.running.endpoint)
        try:
            ws.send(json.dumps({'op': 'create', 'version': 1, 'protocol': PROTOCOL, 'pin': '123456'}))
            created = _reply(ws)
            with self.assertRaises(ConnectionError):
                connect_guest(self.running.endpoint, created['code'], '123456', PROTOCOL)
            room = self.running.relay.rooms[created['code']]
            self.assertTrue(wait_for(lambda: not room.guests and not room.tickets))
        finally:
            _abort(ws)

    def test_cancelled_background_job_closes_late_connection(self):
        from online_ui import ConnectionJob
        gate = threading.Event()
        started = threading.Event()
        def delayed_relay(*args, **kwargs):
            started.set()
            gate.wait(3)
            return RelayHost(*args, **kwargs)
        with patch('online_ui.RelayHost', delayed_relay), patch.dict(os.environ,{'APPDATA':self.temp.name}):
            job = ConnectionJob('host', {'address': self.running.endpoint, 'pin': '', 'name': 'Host',
                                        'world_file': Path(self.temp.name) / 'room.json'},
                                new_state(), Path(self.temp.name) / 'profile.json', [])
            self.assertTrue(started.wait(3))
            job.cancel()
            gate.set()
            job.thread.join(5)
        self.assertFalse(job.thread.is_alive())
        self.assertIsNone(job.take())
        self.assertTrue(wait_for(lambda: not self.running.relay.rooms))

    def test_health_endpoint_and_keepalive(self):
        import urllib.request
        url = self.running.endpoint.replace('ws:', 'http:').replace('/relay', '/health')
        with urllib.request.urlopen(url, timeout=2) as response:
            self.assertEqual(json.load(response)['status'], 'ok')
        _, _, relay = self.room()
        time.sleep(.6)  # Several actual server ping/pong exchanges.
        self.assertTrue(relay.active)
        self.guest(relay)

    def test_server_warmup_can_be_cancelled_immediately(self):
        from online_ui import wait_for_relay
        import urllib.error
        cancelled, called = threading.Event(), threading.Event()
        result = []
        def unavailable(*args, **kwargs):
            called.set()
            raise urllib.error.HTTPError('http://127.0.0.1/health', 503, 'Starting', {}, None)
        def run():
            try:wait_for_relay(self.running.endpoint, cancelled, lambda value: None)
            except ConnectionError:result.append('cancelled')
        with patch('online_ui.urllib.request.urlopen', unavailable):
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            self.assertTrue(called.wait(2))
            start = time.monotonic()
            cancelled.set()
            thread.join(1)
        self.assertEqual(result, ['cancelled'])
        self.assertLess(time.monotonic() - start, 1)

    def test_pygame_guest_disconnect_restores_original_save_without_carrying_items(self):
        from ambera_farm import Game, pygame
        from save_slots import load_slot
        room, _, relay = self.room(room_owned=True)
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
        with patch.dict(os.environ, {'APPDATA': self.temp.name}), \
             patch.object(Game, 'fetch_mails', lambda self: None), \
             patch.object(Game, 'refresh_notices', lambda self, force=False: None):
            game = Game()
            try:
                game.select_slot('online', 1)
                game.state['plots'][0] = {'crop': 'kabu', 'planted_at': time.time()}
                game.state['coins'] = 73
                original = copy.deepcopy(game.state['plots'])
                game.persist(True)
                game.open_online_dialog('join')
                # A full invitation supplies the endpoint even when URL is blank.
                game.join_fields['address'] = ''
                game.join_fields['pin'] = invitation(self.running.endpoint, relay.share_code)
                game.begin_internet_connection()
                def connected():
                    game.update_gameplay(.01)
                    return game.online_client is not None and game.online_profile_received
                self.assertTrue(wait_for(connected))
                self.assertTrue(game.online_guest)
                self.assertEqual(game.state['coins'], 200)
                self.assertTrue(game.online_room_owned)
                self.assertNotEqual(game.state['plots'], original)
                with room.lock:
                    room.players[game.online_client.id]['profile']['coins'] = 419
                def earned():
                    game.update_gameplay(.01)
                    return game.state['coins'] == 419
                self.assertTrue(wait_for(earned))
                relay.close()
                def disconnected():
                    game.update_gameplay(.01)
                    return game.online_client is None
                self.assertTrue(wait_for(disconnected))
                saved, _ = load_slot('online', 1)
                self.assertEqual(saved['coins'], 73)
                self.assertEqual(saved['plots'], original)
                self.assertEqual(room.host_profile['coins'], 200)
            finally:
                if game.online_job:game.online_job.cancel()
                if game.online_client:game.stop_online()
                pygame.quit()

    def test_pygame_host_connect_render_and_save_on_disconnect(self):
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
        from ambera_farm import Game, pygame
        from save_slots import load_slot
        with patch.dict(os.environ, {'APPDATA': self.temp.name}), \
             patch.object(Game, 'fetch_mails', lambda self: None), \
             patch.object(Game, 'refresh_notices', lambda self, force=False: None):
            game = Game()
            try:
                game.select_slot('online', 1)
                game.open_online_dialog('host')
                game.join_fields['address'] = self.running.endpoint
                game.render()
                start = time.monotonic()
                game.begin_internet_connection()
                self.assertLess(time.monotonic() - start, .5)
                self.assertEqual(game.modal, 'online_connect')
                game.render()
                def connected():
                    game.update_gameplay(.01)
                    return game.online_client is not None
                self.assertTrue(wait_for(connected))
                self.assertTrue(game.online_room_code)
                self.assertFalse(game.online_guest)
                game.modal = 'pause'
                game.render()
                # Server-owned earned balance must survive a relay disconnect.
                with game.online_server.lock:
                    game.online_server.host_profile['coins'] = 317
                game.online_relay.close()
                game.poll_internet_connection()
                self.assertIsNone(game.online_client)
                saved, _ = load_slot('online', 1)
                self.assertEqual(saved['coins'], 200)
                from room_saves import load_room, room_file
                self.assertEqual(load_room(room_file(1))[0]['coins'], 317)
                self.assertFalse(game.online_room_code)
                self.assertFalse(game.settings.get('online_room_code'))
            finally:
                if game.online_job:game.online_job.cancel()
                if game.online_client:game.stop_online()
                pygame.quit()


if __name__ == '__main__':
    unittest.main()
