# -*- coding: utf-8 -*-
"""Outbound-only WSS transport for the existing private co-op protocol.

The relay forwards bytes; the room host remains responsible for game rules.
No local ports, filesystem paths or host tokens are accepted from relay peers.
"""
from __future__ import annotations

import json
import re
import socket
import threading
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

RELAY_PROTOCOL = 1
MAX_FRAME = 131072
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def relay_url(value):
    value = str(value).strip()
    try:
        u = urlsplit(value)
        scheme = {'https': 'wss', 'http': 'ws'}.get(u.scheme, u.scheme)
        port = u.port
        if (not u.hostname or u.username or u.password or u.query or u.fragment
                or scheme not in ('wss', 'ws') or len(value) > 240
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        if scheme == 'ws' and u.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError
        if (u.path or '/relay').rstrip('/') != '/relay':
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('中継サーバーのURLを確認してください。例: wss://サーバー名/relay') from None
    return urlunsplit((scheme, u.netloc, '/relay', '', ''))


def format_code(code, pin):
    if (not isinstance(code, str) or len(code) != 8
            or any(c not in CODE_ALPHABET for c in code)
            or not re.fullmatch(r'[0-9]{6}', str(pin))):
        raise ValueError('部屋コードの形式が違います。')
    return f'{code[:4]}-{code[4:]}-{pin}'


def invitation(endpoint, code):
    return 'amberafarm://join?' + urlencode({'relay': relay_url(endpoint), 'code': code})


def parse_invitation(value, endpoint=''):
    value = str(value).strip()
    if value.startswith('amberafarm:'):
        u = urlsplit(value)
        args = parse_qs(u.query)
        if (u.netloc != 'join' or u.path or u.fragment or set(args) != {'relay', 'code'}
                or any(len(v) != 1 for v in args.values())):
            raise ValueError('招待リンクの形式が違います。')
        endpoint, value = args['relay'][0], args['code'][0]
    value = re.sub(r'[\s-]', '', value).upper()
    if (len(value) != 14 or any(c not in CODE_ALPHABET for c in value[:8])
            or not re.fullmatch(r'[0-9]{6}', value[8:])):
        raise ValueError('部屋コードを入力してください。例: ABCD-EFGH-123456')
    return relay_url(endpoint), value[:8], value[8:]


def _websocket(endpoint, timeout=8):
    # Lazy import keeps offline play and LAN usable without optional packages.
    try:
        import websocket
    except ImportError:
        raise ConnectionError('通信ライブラリがありません。最新版のゲームを使用してください。') from None
    try:
        return websocket.create_connection(relay_url(endpoint), timeout=timeout,
                                           enable_multithread=True, suppress_origin=True,
                                           redirect_limit=0)
    except Exception as exc:
        raise ConnectionError('中継サーバーに接続できません。URLと通信状態を確認してください。') from exc


def _reply(ws):
    try:
        raw = ws.recv()
        if not isinstance(raw, str) or len(raw) > 2048:
            raise ValueError
        reply = json.loads(raw)
        if not isinstance(reply, dict):
            raise ValueError
    except Exception as exc:
        raise ConnectionError('中継サーバーの応答を受信できませんでした。') from exc
    if reply.get('type') == 'error':
        messages = {'not_found': '部屋が見つかりません。コードと部屋主の接続を確認してください。',
                    'denied': '部屋コードが違います。', 'full': '部屋は満員です。',
                    'busy': '中継サーバーが混雑しています。少し待ってからお試しください。',
                    'timeout': '部屋主への接続が間に合いませんでした。もう一度お試しください。',
                    'version': '通信バージョンが違います。全員が最新版を使用してください。'}
        raise ConnectionError(messages.get(reply.get('code'), '中継サーバーが接続を拒否しました。'))
    return reply


def _abort(ws):
    try:
        ws.abort()
    except Exception:
        pass
    # send_close() marks the WebSocket disconnected before returning, so its
    # abort() can skip the still-blocking socket reader. Always wake it too.
    try:
        if ws.sock is not None:
            ws.sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    # close() may return early after recv() marked a peer disconnected. shutdown()
    # also releases that underlying socket, and never waits for a close handshake.
    try:
        ws.shutdown()
    except Exception:
        pass


class _LineReader:
    def __init__(self, connection):
        self.connection = connection
        self.buffer = bytearray()

    def readline(self, limit=-1):
        limit = min(limit if limit > 0 else MAX_FRAME + 1, MAX_FRAME + 1)
        while True:
            newline = self.buffer.find(b'\n')
            if newline >= 0 or len(self.buffer) >= limit:
                count = min(newline + 1 if newline >= 0 else limit, limit)
                data = bytes(self.buffer[:count])
                del self.buffer[:count]
                return data
            chunk = self.connection.recv(MAX_FRAME)
            if not chunk:
                data = bytes(self.buffer)
                self.buffer.clear()
                return data
            self.buffer.extend(chunk)

    def close(self):
        self.buffer.clear()


class RelaySocket:
    """Socket subset consumed by RoomClient; WSS errors become socket errors."""
    def __init__(self, ws):
        self.ws = ws
        self.pending = bytearray()

    def sendall(self, data):
        try:
            for offset in range(0, len(data), 65536):
                self.ws.send_binary(data[offset:offset + 65536])
        except Exception as exc:
            raise ConnectionError('中継接続が切れました。') from exc

    def recv(self, size):
        if not self.pending:
            try:
                message = self.ws.recv()
            except Exception as exc:
                raise ConnectionError('中継接続が切れました。') from exc
            if message in ('', b''):
                return b''
            if not isinstance(message, bytes) or len(message) > MAX_FRAME:
                raise ConnectionError('中継パケットの形式が違います。')
            self.pending.extend(message)
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result

    def makefile(self, mode):
        if mode != 'rb':
            raise ValueError('Only binary reading is supported')
        return _LineReader(self)

    def settimeout(self, value):
        self.ws.settimeout(value)

    def setsockopt(self, *args):
        pass

    def shutdown(self, *args):
        _abort(self.ws)

    def close(self):
        _abort(self.ws)


def connect_guest(endpoint, code, pin, protocol):
    ws = _websocket(endpoint)
    try:
        ws.send(json.dumps({'op': 'join', 'version': RELAY_PROTOCOL, 'protocol': protocol,
                            'code': code, 'pin': str(pin)}))
        if _reply(ws).get('type') != 'connected':
            raise ConnectionError('部屋に接続できませんでした。')
        return RelaySocket(ws)
    except BaseException:
        _abort(ws)
        raise


class RelayHost:
    def __init__(self, endpoint, local_port, pin, protocol):
        self.endpoint = relay_url(endpoint)
        self.local_port = int(local_port)
        self.pin = str(pin)
        self.protocol = protocol
        self.lock = threading.Lock()
        self.links = set()
        self.active = False
        self._closing = False
        self.control = _websocket(self.endpoint)
        try:
            self.control.send(json.dumps({'op': 'create', 'version': RELAY_PROTOCOL,
                                          'protocol': protocol, 'pin': self.pin}))
            reply = _reply(self.control)
            if reply.get('type') != 'created':
                raise ConnectionError('部屋コードを作成できませんでした。')
            self.code = reply['code']
            self.key = reply['key']
            self.share_code = format_code(self.code, self.pin)
            if not isinstance(self.key, str) or not re.fullmatch(r'[0-9a-f]{48}', self.key):
                raise ConnectionError('部屋の認証情報が不正です。')
            self.control.settimeout(None)
            self.active = True
            self.thread = threading.Thread(target=self._listen, daemon=True)
            self.thread.start()
        except BaseException:
            self.close()
            raise

    def _listen(self):
        try:
            while self.active:
                message = _reply(self.control)
                ticket = message.get('ticket', '')
                if (message.get('type') != 'incoming' or not isinstance(ticket, str)
                        or not re.fullmatch(r'[0-9a-f]{48}', ticket)):
                    raise ConnectionError('Invalid relay control message')
                threading.Thread(target=self._bridge, args=(ticket,), daemon=True).start()
        except (OSError, ValueError):
            pass
        finally:
            self.close()

    def _track(self, link):
        with self.lock:
            if not self.active:
                raise ConnectionError('Room closed')
            self.links.add(link)

    def _bridge(self, ticket):
        ws = local = None
        try:
            ws = _websocket(self.endpoint)
            self._track(ws)
            ws.send(json.dumps({'op': 'tunnel', 'version': RELAY_PROTOCOL,
                                'code': self.code, 'key': self.key, 'ticket': ticket}))
            if _reply(ws).get('type') != 'connected':
                return
            ws.settimeout(None)
            local = socket.create_connection(('127.0.0.1', self.local_port), timeout=5)
            local.settimeout(None)
            local.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._track(local)
            def upload():
                try:
                    while self.active:
                        data = local.recv(65536)
                        if not data:
                            break
                        ws.send_binary(data)
                except Exception:
                    pass
                finally:
                    _abort(ws)
            threading.Thread(target=upload, daemon=True).start()
            transport = RelaySocket(ws)
            while self.active:
                data = transport.recv(65536)
                if not data:
                    break
                local.sendall(data)
        except Exception:
            pass
        finally:
            if ws:
                _abort(ws)
            if local:
                try:
                    local.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                local.close()
            with self.lock:
                self.links.discard(ws)
                self.links.discard(local)

    def close(self):
        with self.lock:
            if self._closing:
                return
            self._closing = True
            self.active = False
            links = list(self.links)
            self.links.clear()
        # A managed proxy may keep its upstream socket alive after a bare TCP
        # abort. Send the WebSocket close frame so the relay removes the room
        # and disconnects guests immediately, without waiting for its heartbeat.
        try:
            self.control.settimeout(.25)
            self.control.send_close()
        except Exception:
            pass
        _abort(self.control)
        for link in links:
            if isinstance(link, socket.socket):
                try:
                    link.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                link.close()
            else:
                _abort(link)
