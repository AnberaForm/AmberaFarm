"""v9.0.2: movement trails survive coalescing, obstacles and stale ACKs."""
import math
import time

from farm_core import new_state
from multiplayer import RoomServer, RoomClient, PROTOCOL
from player_movement import (MovementTrail, path_is_clear,
                             interpolate_around_obstacles)
from world_map import TREE_POSITIONS, TILE, can_stand


def _route_points(start, bend, end, step=2.0):
    points = []
    for p, q in ((start,bend),(bend,end)):
        count = math.ceil(math.dist(p,q) / step)
        for i in range(1,count+1):
            points.append((p[0]+(q[0]-p[0])*i/count,
                           p[1]+(q[1]-p[1])*i/count))
    return points


def _dummy(room, start, elapsed=.4):
    room.players['dummy'] = dict(x=start[0], y=start[1],
                                  last=time.monotonic()-elapsed,
                                  move_seq=-1, move_step_seq=0)


def test_client_retains_all_path_samples_until_ack():
    trace = MovementTrail()
    for point in ((340,368),(343,368),(343,371),(343,375)):
        trace.append(point)
    first = trace.packet_path()
    assert [step[0] for step in first] == [1,2,3,4]
    trace.acknowledge(2)
    assert [p[0] for p in trace.packet_path()] == [3,4]
    trace.append((343,378))
    assert [p[0] for p in trace.packet_path()] == [3,4,5]
    trace.clear()
    trace.append((350,380))
    assert [p[0] for p in trace.packet_path()] == [6]


def test_host_accepts_coalesced_polyline_when_endpoint_line_hits_corner(tmp_path):
    start = (44.,708.)
    bend = (44.,696.)
    target = (64.,696.)
    assert can_stand(*start) and can_stand(*bend) and can_stand(*target)
    assert not path_is_clear(start,target)
    path = _route_points(start,bend,target)
    room = RoomServer(new_state(), tmp_path/'world.json', port=0)
    try:
        _dummy(room,start)
        trace = MovementTrail()
        for p in path:
            trace.append(p)
        # A single replacement of 12Hz packets preserves intermediate turns.
        room._move('dummy', dict(x=target[0],y=target[1],seq=9,path=trace.packet_path()))
        assert math.dist((room.players['dummy']['x'],room.players['dummy']['y']),target)<.02
        assert room.players['dummy']['move_step_seq'] == len(trace.packet_path())
        assert room.players['dummy']['move_seq'] == 9
    finally:
        room.close()


def test_host_ignores_replayed_steps_but_processes_new_ones(tmp_path):
    start=(336.,368.)
    assert can_stand(*start)
    trace=MovementTrail()
    for x in range(338,348,2):
        trace.append((float(x),368.))
    room=RoomServer(new_state(),tmp_path/'world.json',port=0)
    try:
        _dummy(room,start)
        first=trace.packet_path()
        room._move('dummy',dict(seq=1,x=346.,y=368.,path=first))
        assert room.players['dummy']['move_step_seq']==5
        for x in range(348,360,2):
            trace.append((float(x),368.))
        room.players['dummy']['last']=time.monotonic()-.2
        second=trace.packet_path() # Packet coalescing re-sends steps 1..5.
        room._move('dummy',dict(seq=2,x=358.,y=368.,path=second))
        assert room.players['dummy']['x']==358.
        assert room.players['dummy']['move_step_seq']==len(second)
    finally:
        room.close()


def test_host_rejects_short_waypoint_wall_clipping(tmp_path):
    tree=next((tx,ty) for tx,ty in sorted(TREE_POSITIONS)
              if can_stand(tx*TILE-9,ty*TILE+16)
              and can_stand((tx+1)*TILE+9,ty*TILE+16))
    tx,ty=tree
    start=(tx*TILE-9.,ty*TILE+16.)
    end=((tx+1)*TILE+9.,ty*TILE+16.)
    assert not path_is_clear(start,end)
    trace=MovementTrail()
    for i in range(1,28):
        trace.append((start[0]+(end[0]-start[0])*i/27, start[1]))
    room=RoomServer(new_state(),tmp_path/'world.json',port=0)
    try:
        _dummy(room,start)
        room._move('dummy',dict(x=end[0],y=end[1],seq=1,path=trace.packet_path()))
        assert (room.players['dummy']['x'], room.players['dummy']['y']) == start
        assert room.players['dummy']['move_step_seq']==0
        assert room.players['dummy']['move_seq']==1
    finally:
        room.close()


def test_host_rejects_superhuman_speed_even_with_valid_waypoints(tmp_path):
    start=(336.,368.)
    trace=MovementTrail()
    for x in range(338,390,2):
        trace.append((float(x),368.))
    room=RoomServer(new_state(),tmp_path/'world.json',port=0)
    try:
        _dummy(room,start,elapsed=.02)
        room._move('dummy',dict(x=388.,y=368.,seq=1,path=trace.packet_path()))
        assert (room.players['dummy']['x'],room.players['dummy']['y'])==start
    finally:
        room.close()


def test_remote_interpolation_does_not_cross_solid_corner():
    start=(44.,708.)
    end=(64.,696.)
    assert not path_is_clear(start,end)
    position=start
    for _ in range(50):
        next_pos=interpolate_around_obstacles(position,end,.25)
        assert can_stand(*next_pos)
        assert path_is_clear(position,next_pos)
        position=next_pos
    assert math.dist(position,end)<.2


def test_real_socket_receives_trail_ack_and_server_position(tmp_path):
    room=RoomServer(new_state(), tmp_path/'live_room.json', port=0)
    client=None
    try:
        client=RoomClient(f'127.0.0.1:{room.port}', room.pin, 'Guest')
        start=(44.,708.)
        target=(64.,696.)
        trace=MovementTrail()
        for point in _route_points(start,(44.,696.),target):
            trace.append(point)
        with room.lock:
            player=room.players[client.id]
            player.update(x=start[0],y=start[1],move_step_seq=0,move_seq=-1,
                          last=time.monotonic()-.4)
        assert client.send('move',x=target[0],y=target[1],seq=73,path=trace.packet_path())
        limit=time.monotonic()+3.0
        ack=None
        while time.monotonic()<limit and ack is None:
            for packet in client.poll():
                if packet.get('type') in ('positions','snapshot') and packet.get('move_seq')==73:
                    ack=packet
                    break
            time.sleep(.01)
        assert ack is not None, 'server did not acknowledge the new path packet'
        assert math.dist(ack['self_pos'],target)<.02
        assert ack['move_step_seq']==len(trace.packet_path())
        with room.lock:
            assert math.dist((room.players[client.id]['x'], room.players[client.id]['y']),target)<.02
    finally:
        if client:client.close()
        room.close()


def test_random_collision_sliding_with_coalesced_frames(tmp_path):
    """A long walk through random obstacles must not accumulate host/client drift."""
    import random
    from player_movement import move_character
    rng=random.Random(1723)
    room=RoomServer(new_state(),tmp_path/'stress_world.json',port=0)
    try:
        pos=[336.,368.]
        _dummy(room,pos)
        trace=MovementTrail()
        direction=(1,0)
        last_accepted_frame=-1
        checked=0
        for frame in range(480):
            if frame%34==0:
                direction=rng.choice(((1,0),(0,-1),(-1,0),(0,1),
                                      (1,-1),(-1,-1),(1,1),(-1,1)))
            updated=move_character(pos,direction,1/60)
            if updated!=pos:trace.append(updated)
            pos=updated
            # 12Hz baseline, deliberately skip every third outgoing packet.
            if frame%8!=0 or frame%24==0:
                continue
            room.players['dummy']['last']=time.monotonic()-(frame-last_accepted_frame)/60
            room._move('dummy',{'seq':frame+1,'x':round(pos[0],2),
                                'y':round(pos[1],2),'path':trace.packet_path()})
            actual=(room.players['dummy']['x'],room.players['dummy']['y'])
            assert math.dist(actual,pos)<.025, (frame,actual,pos)
            trace.acknowledge(room.players['dummy']['move_step_seq'])
            last_accepted_frame=frame
            checked+=1
        assert checked>=30
    finally:
        room.close()
