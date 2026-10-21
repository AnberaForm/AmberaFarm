# -*- coding: utf-8 -*-
"""Data-isolation, room co-op, inventory UI model, and regression tests."""
import time
from farm_core import new_state
from inventory_grid import slots, hotbar, hotbar_offset, GRID_SLOTS
from coop_orders import new_board, view, contribute
from multiplayer import RoomServer, RoomClient, PROTOCOL


def wait_until(pred, timeout=3):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if pred():return True
        time.sleep(.025)
    return False


def test_inventory_slots_only_occupied_and_bounded():
    state=new_state()
    # v8 init adds consumables and other collections
    from v8_features import init_v8
    init_v8(state)
    result=slots(state)
    assert len(result)==GRID_SLOTS
    assert ('seed','kaiware','カイワレ大根の種',4) in result
    assert sum(x is not None for x in result)==1
    assert result[-1] is None
    state['fish_inventory']['medaka']=7
    state['warehouse']['tomato']=1
    owned=[x for x in slots(state) if x]
    assert ('fish','medaka','メダカ',7) in owned
    assert ('crop','tomato','トマト',1) in owned
    assert len(owned)==3
    assert len(hotbar(0))==9
    assert len(hotbar(hotbar_offset(0,1)))==9
    assert hotbar(hotbar_offset(0,1))[-1].id=="kin_ringo"
    assert hotbar_offset(3,-1)==0


def test_coop_donation_deducts_only_donor_and_rewards_only_participants():
    board=new_board()
    a=new_state();b=new_state();c=new_state()
    a['warehouse']['kaiware']=2
    b['warehouse']['kaiware']=2
    players={'a':{'profile':a},'b':{'profile':b},'c':{'profile':c}}
    assert '共同納品 +1' in contribute(board,'sprouts','a',a,players,1)
    assert '共同納品 +1' in contribute(board,'sprouts','a',a,players,1)
    assert board[0]['count']==2
    assert a['warehouse']['kaiware']==0
    assert b['warehouse']['kaiware']==2
    assert '達成！' in contribute(board,'sprouts','b',b,players,1)
    assert board[0]['paid'] is True
    assert a['coins']==240 and b['coins']==240
    assert c['coins']==200
    assert b['warehouse']['kaiware']==1
    assert '終了' in contribute(board,'sprouts','b',b,players,1)
    assert b['coins']==240
    assert all('contributors' not in v for v in view(board))


def test_coop_rejects_invalid_donation_and_short_inventory():
    board=new_board()
    a=new_state();a['warehouse']['kaiware']=1
    players={'a':{'profile':a}}
    assert '不正' in contribute(board,'sprouts','a',a,players,99)
    assert '足りません' in contribute(board,'sprouts','a',a,players,3)
    assert board[0]['count']==0 and a['warehouse']['kaiware']==1
    assert '不正' in contribute(board,'sprouts','a',a,players,True)
    assert '終了' in contribute(board,'bad','a',a,players,1)


def test_coop_network_board_state_and_separate_wallet(tmp_path):
    assert PROTOCOL == 12
    host=new_state();guest=new_state()
    host['warehouse']['kaiware']=2
    guest['warehouse']['kaiware']=1
    room=RoomServer(host,tmp_path/'coop.json',port=0)
    a=b=None
    try:
        url=f'127.0.0.1:{room.port}'
        a=RoomClient(url,room.pin,'Host',profile=host,host_token=room.host_token)
        b=RoomClient(url,room.pin,'Guest',profile=guest)
        assert wait_until(lambda:len(room.players)==2)
        assert b.action('coop_contribute',{'id':'sprouts','count':1})
        assert wait_until(lambda:room.coop_board[0]['count']==1)
        assert a.action('coop_contribute',{'id':'sprouts','count':3})
        assert wait_until(lambda:room.coop_board[0]['paid'])
        with room.lock:
            assert room.players[a.id]['profile']['coins']==240
            assert room.players[b.id]['profile']['coins']==240
            assert room.players[b.id]['profile']['warehouse']['kaiware']==0
            assert room.players[a.id]['profile']['warehouse']['kaiware']==0
            assert room.coop_board[0]['count']==3
        assert wait_until(lambda:any(p.get('coop_board',[{}])[0].get('paid')
                            for p in a.poll() if p.get('type')=='snapshot'))
    finally:
        if a:a.close()
        if b:b.close()
        room.close()
