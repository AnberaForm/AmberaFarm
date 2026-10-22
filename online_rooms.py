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
import time
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


class RelayError(ConnectionError):
    def __init__(self, code):
        self.code = code
        messages = {'not_found': '部屋が見つかりません。部屋主の接続を確認してください。',
                    'denied': '部屋コードが違います。', 'full': '部屋は満員です。',
                    'busy': '中継サーバーが混雑しています。少し待ってからお試しください。',
                    'timeout': '部屋主への接続が間に合いませんでした。もう一度お試しください。',
                    'version': '通信バージョンが違います。全員が最新版を使用してください。',
                    'rejected': '部屋主が参加申請を見送りました。',
                    'host_left': '部屋主が部屋を閉じました。',
                    'requests_full': '参加申請が混み合っています。少し待ってからお試しください。',
                    'request_timeout': '承認待ちが終了しました。もう一度申請できます。',
                    'approval_required': 'この部屋には部屋主の承認が必要です。'}
        super().__init__(messages.get(code, '中継サーバーが接続を拒否しました。'))


def _decode_reply(raw):
    try:
        if not isinstance(raw, str) or len(raw) > MAX_FRAME:
            raise ValueError
        reply = json.loads(raw)
        if not isinstance(reply, dict):
            raise ValueError
    except Exception as exc:
        raise ConnectionError('中継サーバーの応答を受信できませんでした。') from exc
    if reply.get('type') == 'error':
        raise RelayError(reply.get('code'))
    return reply


def _reply(ws):
    try:
        raw = ws.recv()
    except Exception as exc:
        raise ConnectionError('中継サーバーの応答を受信できませんでした。') from exc
    return _decode_reply(raw)


def search_rooms(endpoint, query, protocol):
    ws = _websocket(endpoint)
    try:
        ws.send(json.dumps({'op': 'list', 'version': RELAY_PROTOCOL,
                            'protocol': protocol, 'query': str(query)[:40]}))
        reply = _reply(ws)
        rows = reply.get('rooms')
        if reply.get('type') != 'rooms' or not isinstance(rows, list) or len(rows) > 100:
            raise ConnectionError('部屋一覧を読み込めませんでした。')
        clean = []
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or len(row['id']) != 8 or any(c not in CODE_ALPHABET for c in row['id'])
                    or not isinstance(row.get('title'), str) or len(row['title']) > 24
                    or not isinstance(row.get('host'), str) or len(row['host']) > 18
                    or type(row.get('players')) is not int or not 1 <= row['players'] <= 8
                    or row.get('max_players') != 8):
                raise ConnectionError('部屋一覧の形式が違います。')
            clean.append({k: row[k] for k in ('id', 'title', 'host', 'players', 'max_players')})
        return clean
    finally:
        _abort(ws)


def request_admission(endpoint, code, name, protocol, cancelled, progress, max_wait=185):
    """Wait off the render thread; a closing socket withdraws a pending request."""
    import websocket
    ws = _websocket(endpoint)
    granted = False
    try:
        ws.send(json.dumps({'op': 'request', 'version': RELAY_PROTOCOL,
                            'protocol': protocol, 'code': code, 'name': str(name)[:18]}))
        pending = _reply(ws)
        if pending.get('type') != 'pending':
            raise ConnectionError('参加申請を送信できませんでした。')
        progress('参加申請を送りました。部屋主の承認を待っています（最大3分）')
        ws.settimeout(1)
        until = time.monotonic() + max_wait
        while not cancelled.is_set() and time.monotonic() < until:
            try:
                reply = _decode_reply(ws.recv())
            except (websocket.WebSocketTimeoutException, socket.timeout):
                continue
            if (reply.get('type') != 'approved' or not isinstance(reply.get('approval'), str)
                    or not re.fullmatch(r'[0-9a-f]{64}', reply['approval'])):
                raise ConnectionError('承認情報の形式が違います。')
            format_code(code, reply.get('pin'))
            granted = True
            return reply
        if cancelled.is_set():
            raise ConnectionError('参加申請を取り消しました。')
        raise RelayError('request_timeout')
    finally:
        if not granted:
            withdraw_request(ws)
        else:
            _abort(ws)


def withdraw_request(ws):
    """Withdraw explicitly: a proxy may delay propagation of a TCP abort."""
    try:
        ws.settimeout(2)
        ws.send(json.dumps({'op': 'cancel'}))
        ws.recv()  # Wait for the relay acknowledgement before closing transport.
    except Exception:
        pass
    finally:
        _abort(ws)


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


def connect_guest(endpoint, code, pin, protocol, approval=None):
    ws = _websocket(endpoint)
    try:
        ws.send(json.dumps({'op': 'join', 'version': RELAY_PROTOCOL, 'protocol': protocol,
                            'code': code, 'pin': str(pin), 'approval': approval}))
        if _reply(ws).get('type') != 'connected':
            raise ConnectionError('部屋に接続できませんでした。')
        return RelaySocket(ws)
    except BaseException:
        _abort(ws)
        raise


class RelayHost:
    def __init__(self, endpoint, local_port, pin, protocol, title='', name='', public=False):
        self.endpoint = relay_url(endpoint)
        self.local_port = int(local_port)
        self.pin = str(pin)
        self.protocol = protocol
        self.lock = threading.Lock()
        self.links = set()
        self.requests = {}
        self.active = False
        self._closing = False
        self._control_done = threading.Event()
        self.control = _websocket(self.endpoint)
        try:
            self.control.send(json.dumps({'op': 'create', 'version': RELAY_PROTOCOL,
                                          'protocol': protocol, 'pin': self.pin,
                                          'title': str(title)[:24], 'name': str(name)[:18],
                                          'public': bool(public)}))
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
            while True:
                message = _reply(self.control)
                if message.get('type') == 'closed':
                    break
                if not self.active:
                    continue
                if message.get('type') == 'join_request':
                    request = message.get('request')
                    if (not isinstance(request, dict) or not isinstance(request.get('id'), str)
                            or not re.fullmatch(r'[0-9a-f]{24}', request['id'])
                            or not isinstance(request.get('name'), str) or len(request['name']) > 18):
                        raise ConnectionError('Invalid admission request')
                    with self.lock:
                        if len(self.requests) < 16:
                            self.requests[request['id']] = dict(request)
                    continue
                if message.get('type') == 'request_removed':
                    with self.lock:
                        self.requests.pop(message.get('id'), None)
                    continue
                ticket = message.get('ticket', '')
                if (message.get('type') != 'incoming' or not isinstance(ticket, str)
                        or not re.fullmatch(r'[0-9a-f]{48}', ticket)):
                    raise ConnectionError('Invalid relay control message')
                threading.Thread(target=self._bridge, args=(ticket,), daemon=True).start()
        except (OSError, ValueError):
            pass
        finally:
            self._control_done.set()
            self.close()

    def pending_requests(self):
        with self.lock:
            return [dict(r) for r in self.requests.values()]

    def decide(self, request_id, accept):
        with self.lock:
            if not self.active or request_id not in self.requests:
                return False
        def send():
            try:
                self.control.send(json.dumps({'op': 'decide', 'id': request_id, 'accept': bool(accept)}))
            except Exception:
                self.close()
        threading.Thread(target=send, daemon=True).start()
        return True

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
            self.requests.clear()
        # Ask the relay to close the room at application level. A reverse proxy
        # can keep the upstream alive after the local TCP socket is gone. Wait
        # for the acknowledgement away from Pygame's main thread.
        def finish_control():
            try:
                self.control.settimeout(1)
                self.control.send(json.dumps({'op': 'leave'}))
                self._control_done.wait(2)
                self.control.send_close()
            except Exception:
                pass
            finally:
                _abort(self.control)
        threading.Thread(target=finish_control, daemon=True).start()
        for link in links:
            if isinstance(link, socket.socket):
                try:
                    link.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                link.close()
            else:
                _abort(link)
