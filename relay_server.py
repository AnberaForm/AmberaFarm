# -*- coding: utf-8 -*-
"""WSS room directory, accounts, and authoritative account-owned farms.

The legacy v14 relay remains separate to keep existing installations working.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import time
import unicodedata

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response
from websockets.datastructures import Headers

from online_rooms import RELAY_PROTOCOL, CODE_ALPHABET, MAX_FRAME
from account_protocol import (ACCOUNT_PROTOCOL, ACCOUNT_WIRE_VERSION, MAX_ACCOUNT_FRAME,
                              AccountError, username_parts)
from account_store import AccountStore
from managed_farm import ManagedFarm
from multiplayer import RoomServer, PROTOCOL, pack
from story_engine import load_story

LOG = logging.getLogger(__name__)


@dataclass
class Room:
    control: object
    pin: str
    protocol: int
    key: str = field(default_factory=lambda: secrets.token_hex(24))
    tickets: dict = field(default_factory=dict)
    guests: set = field(default_factory=set)
    tunnels: set = field(default_factory=set)
    title: str = ''
    host_name: str = ''
    public: bool = False
    requests: dict = field(default_factory=dict)
    approvals: dict = field(default_factory=dict)
    game: RoomServer | None = None
    owner: str | None = None
    host_connected: bool = False
    awaiting_save: set = field(default_factory=set)


def clean_label(value, limit=24):
    if not isinstance(value, str):
        return ''
    return ''.join(c for c in value if c.isprintable() and c not in '\r\n\t')[:limit].strip()


def search_key(value):
    return unicodedata.normalize('NFKC', value).casefold()


class RelayServer:
    def __init__(self, max_rooms=100, max_connections=1600, pair_timeout=8, request_timeout=180,
                 accounts=None):
        self.rooms = {}
        self.max_rooms = max_rooms
        self.max_connections = max_connections
        self.pair_timeout = pair_timeout
        self.request_timeout = request_timeout
        self.connections = 0
        self.attempts = OrderedDict()
        self.creators = {}
        self.accounts = accounts
        self.account_capacity = asyncio.Semaphore(2)
        self.active_players = {}
        self.creating = 0

    def _allow(self, remote, bucket='relay', limit=120):
        # Never trust unverified X-Forwarded-For. Behind a proxy this is a shared
        # limit; provider-level rate limiting can be configured separately.
        address = (bucket, remote[0] if isinstance(remote, tuple) else str(remote))
        now = time.monotonic()
        samples = self.attempts.pop(address, deque())
        while samples and now - samples[0] > 60:
            samples.popleft()
        self.attempts[address] = samples
        while len(self.attempts) > 4096:
            self.attempts.popitem(last=False)
        if len(samples) >= limit:
            return False
        samples.append(now)
        return True

    async def _error(self, ws, code):
        try:
            await ws.send(json.dumps({'type': 'error', 'code': code}))
        except ConnectionClosed:
            pass

    async def _send(self, ws, message):
        await asyncio.wait_for(ws.send(json.dumps(message)), 5)

    async def handle(self, ws):
        self.connections += 1
        try:
            path = ws.request.path
            if (self.connections > self.max_connections
                    or not self._allow(ws.remote_address, path if path in ('/relay', '/accounts') else 'other',
                                       120 if path == '/relay' else 240)):
                await self._error(ws, 'busy')
                return
            if path == '/accounts':
                await self._account_request(ws)
                return
            if path != '/relay':
                await self._error(ws, 'denied')
                return
            raw = await asyncio.wait_for(ws.recv(), 8)
            if not isinstance(raw, str) or len(raw) > 1024:
                await self._error(ws, 'denied')
                return
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('version') != RELAY_PROTOCOL:
                await self._error(ws, 'version')
                return
            op = data.get('op')
            account = None
            if data.get('protocol') == ACCOUNT_PROTOCOL and op in ('create', 'join', 'list', 'request'):
                account = await self._authenticate(data)
            if op == 'create':
                await self._create(ws, data, account)
            elif op == 'join':
                await self._join(ws, data, account)
            elif op == 'tunnel':
                await self._tunnel(ws, data)
            elif op == 'list':
                await self._list(ws, data)
            elif op == 'request':
                await self._request(ws, data, account)
            else:
                await self._error(ws, 'denied')
        except AccountError as error:
            await self._error(ws, error.code)
        except (ConnectionClosed, asyncio.TimeoutError, ValueError, TypeError, KeyError, OSError, RecursionError):
            pass
        finally:
            self.connections -= 1

    async def _authenticate(self, data):
        if self.accounts is None:
            raise AccountError('account_unavailable')
        return await asyncio.to_thread(self.accounts.authenticate, data.get('session'))

    async def _account_request(self, ws):
        if self.accounts is None:
            raise AccountError('account_unavailable')
        raw = await asyncio.wait_for(ws.recv(), 8)
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_ACCOUNT_FRAME:
            raise AccountError('denied')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('version') != ACCOUNT_WIRE_VERSION:
            raise AccountError('version')
        op = data.get('op')
        if op in ('register', 'login'):
            if len(raw) > 2048:
                raise AccountError('denied')
            username, password = data.get('username'), data.get('password')
            try:
                _, key = username_parts(username)
            except AccountError:
                raise AccountError('bad_login' if op == 'login' else 'invalid_name') from None
            if (self.account_capacity.locked()
                    or not self._allow(key, 'credential-name', 10)
                    or not self._allow(ws.remote_address, 'credential-address', 80)):
                raise AccountError('slow_down')
            async with self.account_capacity:
                action = self.accounts.register if op == 'register' else self.accounts.login
                account, token = await asyncio.to_thread(action, username, password)
            normal, has_online = await asyncio.gather(
                asyncio.to_thread(self.accounts.normal_info, account),
                asyncio.to_thread(self.accounts.has_online, account))
            await self._send(ws, {'type': 'ok', 'id': account.id, 'name': account.name,
                                  'session': token, 'normal': normal.as_dict(),
                                  'has_online': has_online})
            return
        if op not in ('write_normal', 'logout'):
            # There is deliberately no client-facing online save write API.
            raise AccountError('denied')
        account = await self._authenticate(data)
        if op == 'logout':
            await asyncio.to_thread(self.accounts.logout, data['session'])
            await self._send(ws, {'type': 'ok'})
        else:
            saved = await asyncio.to_thread(self.accounts.write_normal, account,
                                            data.get('revision'), data.get('operation'), data.get('state'))
            await self._send(ws, {'type': 'ok', 'revision': saved.revision, 'operation': saved.operation})

    async def _create(self, ws, data, account=None):
        pin, protocol = data.get('pin'), data.get('protocol')
        if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{6}', pin) or protocol not in (PROTOCOL, ACCOUNT_PROTOCOL):
            await self._error(ws, 'denied')
            return
        address = str(ws.remote_address[0])
        if len(self.rooms) + self.creating >= self.max_rooms or self.creators.get(address, 0) >= 20:
            await self._error(ws, 'busy')
            return
        code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        while code in self.rooms or code in self.active_players.values():
            code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        room = Room(ws, pin, protocol,
                    title=clean_label(data.get('title')) or 'みんなの牧場',
                    host_name=account.name if account else clean_label(data.get('name'), 18) or '牧場主',
                    public=data.get('public') is True)
        if account:
            if self._is_playing(account.id):
                raise AccountError('already_playing')
            room.owner = account.id
            self.active_players[account.id] = code
            self.creating += 1
            try:
                farm = await asyncio.to_thread(self.accounts.get_online, account)
                story_nodes = load_story(Path(__file__).parent / 'data' / 'story_events.json')
                room.game = RoomServer(None, None, port=0, pin=pin, story_nodes=story_nodes,
                                       bind='127.0.0.1', managed=ManagedFarm(self.accounts, account, farm))
            except BaseException:
                self.active_players.pop(account.id, None)
                raise
            finally:
                self.creating -= 1
        self.rooms[code] = room
        self.creators[address] = self.creators.get(address, 0) + 1
        try:
            await self._send(ws, {'type': 'created', 'code': code, 'key': room.key})
            # Only the authenticated host control connection can end this room.
            # Ping/pong still detects hosts that disappear without a leave.
            async for raw in ws:
                if not isinstance(raw, str) or len(raw) > 1024:
                    await ws.close(code=1008, reason='Unexpected control message')
                    break
                message = json.loads(raw)
                if message == {'op': 'leave'}:
                    await self._send(ws, {'type': 'closed'})
                    break
                elif (isinstance(message, dict) and message.get('op') == 'decide'
                      and isinstance(message.get('id'), str)
                      and type(message.get('accept')) is bool):
                    await self._decide(room, message['id'], message['accept'])
                else:
                    await ws.close(code=1008, reason='Unexpected control message')
                    break
        finally:
            self.rooms.pop(code, None)
            self.creators[address] -= 1
            if not self.creators[address]:
                self.creators.pop(address)
            room.approvals.clear()
            for request in list(room.requests.values()):
                if not request['decision'].done():
                    request['decision'].set_result({'type': 'error', 'code': 'host_left'})
            for pair in list(room.tickets.values()):
                if not pair.done():
                    pair.cancel()
            async def end_stream(peer):
                # Empty binary data is the transport's EOF. Send it through the
                # data channel before the WebSocket close handshake so guests
                # also stop promptly when a proxy delays close propagation.
                try:
                    await asyncio.wait_for(peer.send(b''), 1)
                except (ConnectionClosed, asyncio.TimeoutError):
                    pass
                await peer.close(code=1001, reason='Host left')
            await asyncio.gather(*(end_stream(s) for s in list(room.guests | room.tunnels)),
                                 return_exceptions=True)
            if room.game:
                try:
                    stored = await asyncio.to_thread(room.game.close)
                    if not stored:
                        LOG.warning('A closing online room could not complete its final checkpoint')
                finally:
                    if self.active_players.get(room.owner) == code:
                        self.active_players.pop(room.owner, None)
                    for ident in room.awaiting_save:
                        if self.active_players.get(ident) == code:
                            self.active_players.pop(ident, None)

    def _is_playing(self, ident):
        code = self.active_players.get(ident)
        if not code:
            return False
        room = self.rooms.get(code)
        # A temporarily failed departure save holds the seat until a later
        # checkpoint succeeds. Never start a stale copy in another room.
        if room and ident in room.awaiting_save and ident not in room.game.managed.departed:
            room.awaiting_save.discard(ident)
            self.active_players.pop(ident, None)
            return False
        return True

    def _prune_approvals(self, room):
        now = time.monotonic()
        for token, (expires, _) in list(room.approvals.items()):
            if expires <= now:
                room.approvals.pop(token, None)

    async def _list(self, ws, data):
        query = search_key(clean_label(data.get('query'), 40))
        rows = []
        for code, room in list(self.rooms.items()):
            if not room.public or room.protocol != data.get('protocol'):
                continue
            if query and query not in search_key(room.title + ' ' + room.host_name):
                continue
            rows.append({'id': code, 'title': room.title, 'host': room.host_name,
                         'players': len(room.guests) + 1, 'max_players': 8})
        # A directory reply never contains PINs, host secrets, tickets or saves.
        await self._send(ws, {'type': 'rooms', 'rooms': rows[:100]})

    async def _request(self, ws, data, account=None):
        room = self.rooms.get(data.get('code')) if isinstance(data.get('code'), str) else None
        if not room or not room.public:
            await self._error(ws, 'not_found')
            return
        if room.protocol != data.get('protocol'):
            await self._error(ws, 'version')
            return
        if account and self._is_playing(account.id):
            raise AccountError('already_playing')
        self._prune_approvals(room)
        if len(room.guests) + len(room.approvals) >= 7:
            await self._error(ws, 'full')
            return
        if len(room.requests) >= 16:
            await self._error(ws, 'requests_full')
            return
        name = account.name if account else clean_label(data.get('name'), 18)
        if not name:
            await self._error(ws, 'denied')
            return
        request_id = secrets.token_hex(12)
        decision = asyncio.get_running_loop().create_future()
        ident = account.id if account else None
        if ident and any(r.get('account') == ident for r in room.requests.values()):
            raise AccountError('already_playing')
        room.requests[request_id] = {'name': name, 'decision': decision, 'account': ident}
        watcher = None
        try:
            await self._send(ws, {'type': 'pending', 'id': request_id})
            await self._send(room.control, {'type': 'join_request',
                                          'request': {'id': request_id, 'name': name}})
            watcher = asyncio.create_task(ws.recv())
            done, _ = await asyncio.wait([decision, watcher], timeout=self.request_timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
            if decision in done:
                await self._send(ws, decision.result())
            elif watcher in done:
                # Disconnect/cancel withdraws the request immediately.
                try:
                    watcher.result()
                    await self._send(ws, {'type': 'cancelled'})
                except ConnectionClosed:pass
            else:
                await self._error(ws, 'request_timeout')
        finally:
            room.requests.pop(request_id, None)
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if not decision.done():
                decision.cancel()
            try:
                await self._send(room.control, {'type': 'request_removed', 'id': request_id})
            except (ConnectionClosed, asyncio.TimeoutError):
                pass

    async def _decide(self, room, request_id, accept):
        request = room.requests.get(request_id)
        if request is None or request['decision'].done():
            return
        self._prune_approvals(room)
        if not accept:
            result = {'type': 'error', 'code': 'rejected'}
        elif len(room.guests) + len(room.approvals) >= 7:
            result = {'type': 'error', 'code': 'full'}
        else:
            token = secrets.token_hex(32)
            room.approvals[token] = (time.monotonic() + 30, request.get('account'))
            result = {'type': 'approved', 'approval': token, 'pin': room.pin}
        request['decision'].set_result(result)

    async def _join(self, ws, data, account=None):
        code, pin = data.get('code'), data.get('pin')
        if not isinstance(code, str) or not isinstance(pin, str):
            await self._error(ws, 'denied')
            return
        room = self.rooms.get(code)
        # Uniform response prevents probing which codes exist without the PIN.
        if not room or not secrets.compare_digest(pin.encode(), room.pin.encode()):
            await self._error(ws, 'not_found')
            return
        if data.get('protocol') != room.protocol:
            await self._error(ws, 'version')
            return
        if room.game and account is None:
            raise AccountError('auth_required')
        host = bool(account and account.id == room.owner)
        if account and (room.host_connected if host else self._is_playing(account.id)):
            raise AccountError('already_playing')
        self._prune_approvals(room)
        if room.public and not host:
            token = data.get('approval')
            if not isinstance(token, str) or token not in room.approvals:
                await self._error(ws, 'approval_required')
                return
            if room.approvals[token][1] != (account.id if account else None):
                await self._error(ws, 'approval_required')
                return
            room.approvals.pop(token)
        if not host and len(room.guests) >= 7:
            await self._error(ws, 'full')
            return
        if room.game:
            await self._managed_join(ws, code, room, account, host)
            return
        room.guests.add(ws)
        ticket = secrets.token_hex(24)
        pair = asyncio.get_running_loop().create_future()
        room.tickets[ticket] = pair
        tunnel = None
        try:
            await self._send(room.control, {'type': 'incoming', 'ticket': ticket})
            try:
                tunnel, done = await asyncio.wait_for(pair, self.pair_timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                await self._error(ws, 'timeout')
                return
            await self._send(ws, {'type': 'connected'})
            await self._send(tunnel, {'type': 'connected'})
            async def pump(source, destination):
                async for message in source:
                    if not isinstance(message, bytes) or len(message) > MAX_FRAME:
                        await source.close(code=1008, reason='Binary game data required')
                        break
                    # Backpressure and a timeout bound slow consumers and RAM.
                    await asyncio.wait_for(destination.send(message), 8)
            tasks = {asyncio.create_task(pump(ws, tunnel)), asyncio.create_task(pump(tunnel, ws))}
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            room.tickets.pop(ticket, None)
            room.guests.discard(ws)
            await ws.close()
            if tunnel is not None:
                await tunnel.close()
                if not done.done():
                    done.set_result(None)

    async def _managed_join(self, ws, code, room, account, host):
        # Reserve before database awaits so one account cannot play in two rooms.
        if host:
            room.host_connected = True
            room.tunnels.add(ws)
        else:
            self.active_players[account.id] = code
            room.guests.add(ws)
        writer = None
        seat = None
        game = room.game
        try:
            saved = None if host else await asyncio.to_thread(self.accounts.get_online, account)
            if self.rooms.get(code) is not room:
                await self._error(ws, 'host_left')
                return
            def grant():
                with game.lock:
                    return game.managed.authorize(account, saved)
            seat = await asyncio.to_thread(grant)
            reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', game.port), 3)
            # The relay binds the account to this stream before accepting any
            # user traffic. A client's own hello/profile cannot set identity.
            writer.write(pack({'type': 'hello', 'protocol': ACCOUNT_PROTOCOL, 'pin': room.pin,
                               'room_ticket': seat.ticket}))
            await writer.drain()
            await self._send(ws, {'type': 'connected'})

            async def upstream():
                async for frame in ws:
                    if not isinstance(frame, bytes) or len(frame) > MAX_FRAME:
                        await ws.close(code=1008)
                        return
                    writer.write(frame)
                    await asyncio.wait_for(writer.drain(), 8)

            async def downstream():
                while data := await reader.read(65536):
                    await asyncio.wait_for(ws.send(data), 8)
                await self._send_eof(ws)

            tasks = {asyncio.create_task(upstream()), asyncio.create_task(downstream())}
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            room.tunnels.discard(ws)
            room.guests.discard(ws)
            stored = True
            if writer:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 2)
                except (OSError, asyncio.TimeoutError):
                    pass
            if seat:
                def finish():
                    if writer:
                        seat.done.wait(8)
                    with game.lock:
                        game.managed.discard_ticket(seat)
                        if not seat.stored and seat.accepted:
                            return game.checkpoint_account(force=True)
                        return True
                stored = await asyncio.to_thread(finish)
            if host:
                room.host_connected = False
            elif self.active_players.get(account.id) == code:
                if not stored and self.rooms.get(code) is room:
                    room.awaiting_save.add(account.id)
                else:
                    self.active_players.pop(account.id, None)

    async def _send_eof(self, ws):
        try:
            await asyncio.wait_for(ws.send(b''), 1)
        except (ConnectionClosed, asyncio.TimeoutError):
            pass

    async def _tunnel(self, ws, data):
        code, key, ticket = (data.get(k) for k in ('code', 'key', 'ticket'))
        if not all(isinstance(v, str) for v in (code, key, ticket)):
            await self._error(ws, 'denied')
            return
        room = self.rooms.get(code)
        if not room or not secrets.compare_digest(key.encode(), room.key.encode()):
            await self._error(ws, 'denied')
            return
        pair = room.tickets.get(ticket)
        if pair is None or pair.done():
            await self._error(ws, 'denied')
            return
        done = asyncio.get_running_loop().create_future()
        room.tunnels.add(ws)
        pair.set_result((ws, done))
        try:
            await done
        finally:
            room.tunnels.discard(ws)


def health_response(connection, request, accounts=False):
    if request.path in ('/', '/health') and request.headers.get('Upgrade', '').lower() != 'websocket':
        body = json.dumps({'service': 'AmberaFarm Relay', 'status': 'ok', 'protocol': 1,
                           'accounts': bool(accounts)}).encode('ascii') + b'\n'
        return Response(200, 'OK', Headers({'Content-Type': 'application/json',
                                          'Content-Length': str(len(body)),
                                          'Cache-Control': 'no-store'}), body)


async def run(host, port):
    accounts = AccountStore.configured()
    if accounts:
        await asyncio.to_thread(accounts.readiness)
    relay = RelayServer(max_rooms=int(os.environ.get('AMBERA_MAX_ROOMS', '100')), accounts=accounts)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        async with serve(relay.handle, host, port, process_request=lambda c, r: health_response(c, r, accounts),
                         compression=None, max_size=MAX_ACCOUNT_FRAME, max_queue=4,
                         open_timeout=8, ping_interval=20, ping_timeout=20, close_timeout=2):
            print(f'AmberaFarm relay listening on {host}:{port}; accounts enabled={bool(accounts)}', flush=True)
            await stop.wait()
    finally:
        if accounts:
            accounts.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8080')))
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port))
