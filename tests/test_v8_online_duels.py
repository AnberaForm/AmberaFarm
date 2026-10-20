# -*- coding: utf-8 -*-
import time
from farm_core import new_state
from multiplayer import RoomServer,RoomClient
from world_map import INTERACTION_POINTS
from v8_features import init_v8


def test_room_starts_with_clean_fields_and_independent_balances(tmp_path):
    st=init_v8(new_state())
    st['plots'][1]={'crop':'radish','planted_at':100}
    st['plot_preparation'][2]=1
    room=RoomServer(st,tmp_path/'online.json',port=0,fresh=True)
    try:
        assert room.state['plots'][1] is None
        assert room.state['plot_preparation'][2]==0
        assert room.host_profile['coins']==st['coins']
    finally:room.close()


def test_duel_consent_escrow_and_payout(tmp_path):
    st=init_v8(new_state());st['coins']=300
    guest=init_v8(new_state());guest['coins']=400
    room=RoomServer(st,tmp_path/'online.json',port=0,pin='123456')
    host=guest_client=None
    try:
        host=RoomClient('127.0.0.1:'+str(room.port),'123456','ホスト',profile=st,host_token=room.host_token)
        guest_client=RoomClient('127.0.0.1:'+str(room.port),'123456','日本語の友人',profile=guest)
        with room.lock:
            location=INTERACTION_POINTS['hall']
            for pl in room.players.values():pl['x'],pl['y']=location
            host_coins=room.players[host.id]['profile']['coins']
            guest_coins=room.players[guest_client.id]['profile']['coins']
            result=room._duel_action(host.id,'duel_challenge',{'target':guest_client.id,'kind':'guess','stake':50})
            assert '招待' in result
            assert room.players[host.id]['profile']['coins']==host_coins
            assert room.players[guest_client.id]['profile']['coins']==guest_coins
            assert room._duel_action(guest_client.id,'duel_accept',None).startswith('対戦開始')
            assert room.players[host.id]['profile']['coins']==host_coins-50
            assert room.players[guest_client.id]['profile']['coins']==guest_coins-50
            assert room._duel_action(host.id,'duel_move',1).startswith('回答')
            assert room._duel_action(guest_client.id,'duel_move',3).startswith('回答')
            assert sum(room.players[x]['profile']['coins'] for x in (host.id,guest_client.id))==host_coins+guest_coins
            assert room.duel_view(host.id)['status']=='finished'
    finally:
        if host:host.close()
        if guest_client:guest_client.close()
        room.close()


def test_friend_request_requires_acceptance(tmp_path):
    room=RoomServer(init_v8(new_state()),tmp_path/'room.json',port=0,pin='888888')
    a=b=None
    try:
        a=RoomClient('127.0.0.1:'+str(room.port),'888888','Alice',profile=init_v8(new_state()),host_token=room.host_token)
        b=RoomClient('127.0.0.1:'+str(room.port),'888888','あおい',profile=init_v8(new_state()))
        with room.lock:
            assert '申請' in room._friend_action(a.id,'friend_request',b.id)
            assert a.id in room.friend_invites[b.id]
            assert room.players[a.id]['profile']['friend_ids']==[]
            assert 'フレンド' in room._friend_action(b.id,'friend_accept',a.id)
            assert room.players[b.id]['profile']['player_uid'] in room.players[a.id]['profile']['friend_ids']
            assert room.players[a.id]['profile']['player_uid'] in room.players[b.id]['profile']['friend_ids']
    finally:
        if a:a.close()
        if b:b.close()
        room.close()
