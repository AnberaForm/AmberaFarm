# -*- coding: utf-8 -*-
import time
from farm_core import new_state
from v8_features import init_v8
from life_hub import claim_all_mail, unread_mail_count
from multiplayer import RoomServer, RoomClient


def wait_until(fn, seconds=4):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if fn():return True
        time.sleep(.02)
    return False


def test_real_schema_claim_all_once():
    s=init_v8(new_state())
    mails=[{'id':'gift-1','title':'手紙1','coins':10,'item':'tea','count':1},
           {'id':'gift-2','title':'手紙2','coins':25,'item':'riceball','count':2}]
    assert unread_mail_count(s,mails)==2
    assert claim_all_mail(s,mails)==2
    assert s['coins']==235 and s['consumables']['tea']==1 and s['consumables']['riceball']==2
    assert claim_all_mail(s,mails)==0
    assert s['coins']==235 and unread_mail_count(s,mails)==0


def test_same_room_friends_party_members(tmp_path):
    host=init_v8(new_state());guest=init_v8(new_state())
    room=RoomServer(host,tmp_path/'host.json',port=0)
    a=b=None
    try:
        endpoint=f'127.0.0.1:{room.port}'
        a=RoomClient(endpoint,room.pin,'Host',profile=host,host_token=room.host_token)
        b=RoomClient(endpoint,room.pin,'Friend',profile=guest)
        assert wait_until(lambda:len(room.players)==2)
        with room.lock:
            assert room._action(a.id,{'action':'party_invite','value':b.id})=='フレンドを招待してください'
            room.players[a.id]['profile']['friend_ids'].append(room.players[b.id]['uid'])
            assert '招待しました' in room._action(a.id,{'action':'party_invite','value':b.id})
            invite=room.party_view(b.id)['invite']
            assert invite['id']==a.id
            assert '参加しました' in room._action(b.id,{'action':'party_accept','value':None})
            assert len(room.party_view(a.id)['members'])==2
            assert '離脱' in room._action(b.id,{'action':'party_leave','value':None})
            assert len(room.party_view(a.id)['members'])==1
    finally:
        if a:a.close()
        if b:b.close()
        room.close()
