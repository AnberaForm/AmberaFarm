"""v9.0.1 online correction: corner sliding, ACKs and anti-wall-clipping."""
import math
import time
from types import SimpleNamespace

from farm_core import new_state
from multiplayer import RoomServer, RoomClient, SPAWN, PROTOCOL
from player_movement import (path_is_clear, walkable_short_path,
                             reconcile_prediction, move_character)
from world_map import TREE_POSITIONS, TILE, can_stand


def receive_ack(client, seq, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for packet in client.poll():
            if packet.get('type') in ('positions', 'snapshot') and packet.get('move_seq') == seq:
                return packet
        time.sleep(.014)
    raise AssertionError(f'no acknowledgement for movement seq={seq}')


def test_real_world_corner_sliding_does_not_require_clear_diagonal():
    start = (44., 708.)
    target = (64., 696.)
    assert can_stand(*start) and can_stand(*target)
    assert not path_is_clear(start, target)
    assert walkable_short_path(start, target)
    assert walkable_short_path(start, target, max_length=34)
    assert not walkable_short_path(start, target, max_length=25)


def test_server_accepts_short_turn_without_teleporting(tmp_path):
    room = RoomServer(new_state(), tmp_path/'room.json', port=0)
    try:
        start=(44., 708.)
        dest=(64., 696.)
        room.players['dummy']={'x':start[0], 'y':start[1],
                               'last':time.monotonic()-.24, 'move_seq':-1}
        room._move('dummy', {'x':dest[0], 'y':dest[1], 'seq':1})
        p=room.players['dummy']
        assert (p['x'], p['y'])==dest
        assert p['move_seq']==1
        room._move('dummy', {'x':dest[0]+1000, 'y':dest[1], 'seq':2})
        assert (p['x'], p['y'])==dest
        assert p['move_seq']==2  # rejected input is still acknowledged
        room._move('dummy', {'x':dest[0]+2000, 'y':dest[1], 'seq':1})
        assert p['move_seq']==2  # ignore out-of-order stale inputs
    finally:
        room.close()


def test_server_refuses_movement_through_a_solid_tree(tmp_path):
    tree=next((tx,ty) for tx,ty in sorted(TREE_POSITIONS)
              if can_stand(tx*TILE-9, ty*TILE+16)
              and can_stand((tx+1)*TILE+9, ty*TILE+16))
    tx,ty=tree
    start=(tx*TILE-9.,ty*TILE+16.)
    end=((tx+1)*TILE+9.,ty*TILE+16.)
    assert not walkable_short_path(start,end)
    room=RoomServer(new_state(),tmp_path/'room.json',port=0)
    try:
        room.players['dummy']={'x':start[0], 'y':start[1],
                               'last':time.monotonic()-.45, 'move_seq':-1}
        room._move('dummy', {'x':end[0], 'y':end[1], 'seq':1})
        p=room.players['dummy']
        assert (p['x'],p['y']) == start
        assert p['move_seq'] == 1
    finally:
        room.close()


def test_ack_rejects_impossible_teleport_then_accepts_nearby(tmp_path):
    assert PROTOCOL == 9
    room=RoomServer(new_state(),tmp_path/'room.json',port=0)
    client=None
    try:
        client=RoomClient(f'127.0.0.1:{room.port}',room.pin,'Host',host_token=room.host_token)
        client.send('move', x=SPAWN[0]+500., y=SPAWN[1], seq=1)
        ack=receive_ack(client,1)
        assert math.dist(ack['self_pos'],SPAWN)<.01
        client.send('move', x=SPAWN[0]+5., y=SPAWN[1], seq=2)
        ack=receive_ack(client,2)
        assert math.dist(ack['self_pos'],(SPAWN[0]+5,SPAWN[1]))<.01
    finally:
        if client: client.close()
        room.close()


def test_reconciliation_ignores_normal_lag_and_repairs_stuck_player():
    # ACK on an older frame: no error; do not pull new client position back.
    origin=(SPAWN[0],SPAWN[1])
    current=(SPAWN[0]+16,SPAWN[1])
    assert reconcile_prediction(current,origin,origin)==list(current)
    # Error at ACKed frame is a valid path: fix prediction by that offset.
    sent=(SPAWN[0]+18,SPAWN[1])
    authoritative=(SPAWN[0]+7,SPAWN[1])
    result=reconcile_prediction((SPAWN[0]+27,SPAWN[1]),sent,authoritative)
    assert math.dist(result,(SPAWN[0]+27,SPAWN[1]))>2
    # Server refuses an impossible wall-crossing: snap to safe server coordinate.
    start=(44.,708.)
    end=(64.,696.)
    assert reconcile_prediction(end,end,start)==list(start)
