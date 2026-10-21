"""Regressions for multiplayer's v4 low-latency update path."""
from pathlib import Path
import time

from farm_core import new_state
from multiplayer import (RoomServer, RoomClient, POSITION_INTERVAL,
                         STATE_INTERVAL, PROTOCOL, pack, SPAWN)


def collect(client, kind, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        packets = client.poll()
        for packet in packets:
            if packet.get('type') == kind:
                return packet
        time.sleep(.012)
    raise AssertionError(f'Timed out waiting for {kind}')


def test_position_updates_are_separate_and_smaller(tmp_path):
    assert PROTOCOL == 9
    assert POSITION_INTERVAL < STATE_INTERVAL
    room = RoomServer(new_state(), tmp_path / 'room.json', port=0)
    a = b = None
    try:
        address = f'127.0.0.1:{room.port}'
        a = RoomClient(address, room.pin, 'A', host_token=room.host_token)
        b = RoomClient(address, room.pin, 'B')
        snap = collect(a, 'snapshot')
        assert 'state' in snap and 'plots' in snap['state']
        # Position packets hold no economy and are far smaller than full syncs.
        assert len(pack({'type': 'positions', 'players': [
            {'id': 'x', 'name': 'A', 'x': 336, 'y': 368, 'uid': '1'}]})) * 3 < len(pack(snap))
        b.send('move', x=SPAWN[0] + 4, y=SPAWN[1])
        position = collect(a, 'positions')
        assert 'state' not in position
        assert 'players' in position
    finally:
        if a: a.close()
        if b: b.close()
        room.close()


def test_chat_delta_and_round_trip_ping(tmp_path):
    room = RoomServer(new_state(), tmp_path / 'room.json', port=0)
    a = b = None
    try:
        address = f'127.0.0.1:{room.port}'
        a = RoomClient(address, room.pin, 'Host', host_token=room.host_token)
        b = RoomClient(address, room.pin, 'Guest')
        # No synchronous socket send from the Pygame main loop.
        t = time.monotonic()
        assert b.chat('通信テスト')
        assert time.monotonic() - t < .1
        packet = collect(a, 'chat_delta')
        assert packet['chat'][-1]['text'] == '通信テスト'
        end = time.monotonic() + 3
        while b.latency_ms is None and time.monotonic() < end:
            time.sleep(.02)
        assert b.latency_ms is not None
        assert b.latency_ms >= 0
    finally:
        if a: a.close()
        if b: b.close()
        room.close()


def test_fast_player_actions_still_apply_to_individual_profiles(tmp_path):
    state = new_state()
    room = RoomServer(state, tmp_path / 'room.json', port=0)
    c = None
    try:
        c = RoomClient(f'127.0.0.1:{room.port}', room.pin, 'Host', profile=state,
                       host_token=room.host_token)
        # Multiple queued actions must remain in order, unlike coalesced moves.
        assert c.action('rescue', None)
        assert c.action('rescue', None)
        first = collect(c, 'result')
        assert '移動' in first['message']
    finally:
        if c: c.close()
        room.close()
