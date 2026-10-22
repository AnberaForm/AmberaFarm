# -*- coding: utf-8 -*-
"""Private-room WebSocket relay. Run behind a managed HTTPS/WSS endpoint.

One process owns the room registry. No accounts, saves or chat logs are stored.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import json
import os
import re
import secrets
import signal
import time

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response
from websockets.datastructures import Headers

from online_rooms import RELAY_PROTOCOL, CODE_ALPHABET, MAX_FRAME


@dataclass
class Room:
    control: object
    pin: str
    protocol: int
    key: str = field(default_factory=lambda: secrets.token_hex(24))
    tickets: dict = field(default_factory=dict)
    guests: set = field(default_factory=set)
    tunnels: set = field(default_factory=set)


class RelayServer:
    def __init__(self, max_rooms=100, max_connections=1600, pair_timeout=8):
        self.rooms = {}
        self.max_rooms = max_rooms
        self.max_connections = max_connections
        self.pair_timeout = pair_timeout
        self.connections = 0
        self.attempts = OrderedDict()
        self.creators = {}

    def _allow(self, remote):
        # Never trust unverified X-Forwarded-For. Behind a proxy this is a shared
        # limit; provider-level rate limiting can be configured separately.
        address = remote[0] if isinstance(remote, tuple) else str(remote)
        now = time.monotonic()
        samples = self.attempts.pop(address, deque())
        while samples and now - samples[0] > 60:
            samples.popleft()
        self.attempts[address] = samples
        while len(self.attempts) > 4096:
            self.attempts.popitem(last=False)
        if len(samples) >= 120:
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
            if self.connections > self.max_connections or not self._allow(ws.remote_address):
                await self._error(ws, 'busy')
                return
            if ws.request.path != '/relay':
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
            if op == 'create':
                await self._create(ws, data)
            elif op == 'join':
                await self._join(ws, data)
            elif op == 'tunnel':
                await self._tunnel(ws, data)
            else:
                await self._error(ws, 'denied')
        except (ConnectionClosed, asyncio.TimeoutError, ValueError, TypeError, KeyError):
            pass
        finally:
            self.connections -= 1

    async def _create(self, ws, data):
        pin, protocol = data.get('pin'), data.get('protocol')
        if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{6}', pin) or type(protocol) is not int:
            await self._error(ws, 'denied')
            return
        address = str(ws.remote_address[0])
        if len(self.rooms) >= self.max_rooms or self.creators.get(address, 0) >= 20:
            await self._error(ws, 'busy')
            return
        code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        while code in self.rooms:
            code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        room = Room(ws, pin, protocol)
        self.rooms[code] = room
        self.creators[address] = self.creators.get(address, 0) + 1
        try:
            await self._send(ws, {'type': 'created', 'code': code, 'key': room.key})
            # Only the authenticated host control connection can end this room.
            # Ping/pong still detects hosts that disappear without a leave.
            async for raw in ws:
                if isinstance(raw, str) and len(raw) <= 64 and json.loads(raw) == {'op': 'leave'}:
                    await self._send(ws, {'type': 'closed'})
                else:
                    await ws.close(code=1008, reason='Unexpected control message')
                break
        finally:
            self.rooms.pop(code, None)
            self.creators[address] -= 1
            if not self.creators[address]:
                self.creators.pop(address)
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

    async def _join(self, ws, data):
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
        if len(room.guests) >= 7:
            await self._error(ws, 'full')
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


def health_response(connection, request):
    if request.path in ('/', '/health') and request.headers.get('Upgrade', '').lower() != 'websocket':
        body = b'{"service":"AmberaFarm Relay","status":"ok","protocol":1}\n'
        return Response(200, 'OK', Headers({'Content-Type': 'application/json',
                                          'Content-Length': str(len(body)),
                                          'Cache-Control': 'no-store'}), body)


async def run(host, port):
    relay = RelayServer(max_rooms=int(os.environ.get('AMBERA_MAX_ROOMS', '100')))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    async with serve(relay.handle, host, port, process_request=health_response,
                     compression=None, max_size=MAX_FRAME, max_queue=8,
                     open_timeout=8, ping_interval=20, ping_timeout=20, close_timeout=2):
        print(f'AmberaFarm relay listening on {host}:{port}', flush=True)
        await stop.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8080')))
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port))
