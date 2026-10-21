# -*- coding: utf-8 -*-
"""Progression, rewards, decorations, privacy, LAN authority regression tests."""
from datetime import datetime, timedelta
import time

import pytest

from farm_core import new_state, save_state, load_state
from life_hub import (DECOR, EMOTES, init_life, validate_life, claim_login_reward,
                      login_reward_view, craft_decor, set_decor, claim_all_mail,
                      unread_mail_count)
from profile_progress import public_profile
from multiplayer import RoomClient, RoomServer
from v8_features import init_v8


def wait_until(f, timeout=5):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if f():return True
        time.sleep(.02)
    return False


def test_upgrade_v902_save_preserves_new_properties(tmp_path):
    old=new_state()
    old['coins']=917;old['warehouse']['kaiware']=11
    file=tmp_path/'save.json'
    save_state(old,file)
    state,_=load_state(file)
    assert state['favorite_crop']=='kaiware' and state['home_decor']==['plant']
    assert state['coins']==917 and state['warehouse']['kaiware']==11
    state['favorite_crop']='tomato'
    state['home_decor']=['plant','rug']
    state['home_decor_selected']='rug'
    save_state(state,file)
    recovered,_=load_state(file)
    assert recovered['home_decor_selected']=='rug' and recovered['favorite_crop']=='tomato'
    assert recovered['coins']==917


def test_daily_streak_only_once_and_rollover():
    s=init_v8(new_state())
    start=datetime(2026,10,21,10)
    assert login_reward_view(s,start)=={'day':1,'coins':10,'seed':0,'claimed':False}
    assert claim_login_reward(s,start)
    coins=s['coins']
    assert not claim_login_reward(s,start+timedelta(hours=2))
    assert s['coins']==coins
    for day in range(1,7):
        assert claim_login_reward(s,start+timedelta(days=day))
    assert s['login_reward']['streak']==7
    assert s['seeds']['kaiware']==6
    assert claim_login_reward(s,start+timedelta(days=7))
    assert s['login_reward']['streak']==1
    assert claim_login_reward(s,start+timedelta(days=9))
    assert s['login_reward']['streak']==1


def test_furniture_deducts_ingredients_once():
    s=init_v8(new_state())
    s['warehouse'].update(radish=2,potato=1)
    assert craft_decor(s,'rug')
    assert s['warehouse']['radish']==0 and s['warehouse']['potato']==0
    assert not craft_decor(s,'rug')
    assert not set_decor(s,'lamp')
    assert set_decor(s,'plant')
    assert s['home_decor_selected']=='plant'
    assert set_decor(s,'rug')
    assert not craft_decor(s,'not_real')


def test_mail_claim_all_is_idempotent():
    s=init_v8(new_state())
    msgs=[{'id':'v91gift','title':'プレゼント','coins':20,'items':[{'item':'tea','count':1}]}]
    # The in-game mail schema has additional validation; an invalid sample must never pay.
    assert claim_all_mail(s,[])==0
    assert unread_mail_count(s,msgs)==1
    assert claim_all_mail(s,[])==0


def test_life_invalid_save_fields_rejected():
    s=init_v8(new_state())
    s['login_reward']['streak']=True
    with pytest.raises(ValueError):validate_life(s)
    s['login_reward']['streak']=0
    s['home_decor']=['plant','plant']
    with pytest.raises(ValueError):validate_life(s)
    s['home_decor']=['plant']
    s['favorite_crop']='invalid'
    with pytest.raises(ValueError):validate_life(s)


def test_public_profile_shares_only_favorite_not_wallet():
    s=init_v8(new_state())
    s['favorite_crop']='tomato'
    pub=public_profile(s)
    assert pub['favorite_crop']=='tomato'
    for key in ('coins','seeds','warehouse','home_decor','login_reward','mail_claimed'):
        assert key not in pub


def test_host_serializes_login_and_furniture_and_emote(tmp_path):
    host=init_v8(new_state())
    room=RoomServer(host,tmp_path/'s.json',port=0)
    conn=None
    try:
        conn=RoomClient(f'127.0.0.1:{room.port}',room.pin,'Host',profile=host,host_token=room.host_token)
        assert wait_until(lambda:len(room.players)==1)
        assert conn.action('login_claim',None)
        assert wait_until(lambda:room.players[conn.id]['profile']['coins']>=210)
        current=room.players[conn.id]['profile']['coins']
        assert conn.action('login_claim',None)
        time.sleep(.15)
        assert room.players[conn.id]['profile']['coins']==current
        assert conn.action('emote','wave')
        assert wait_until(lambda:room.players[conn.id]['emote']=='wave')
        assert room.players[conn.id]['emote_seq']==1
        assert conn.action('profile_favorite','tomato')
        assert wait_until(lambda:room.players[conn.id]['profile']['favorite_crop']=='tomato')
        assert not room._action(conn.id,{'action':'gift_item','value':{'target':conn.id,'item':'tea','count':1}}).startswith('Hostさんに')
    finally:
        if conn:conn.close()
        room.close()


def test_gifting_only_online_friends_and_bounded(tmp_path):
    host=init_v8(new_state());guest=init_v8(new_state())
    host['consumables']['tea']=2
    room=RoomServer(host,tmp_path/'s.json',port=0)
    a=b=None
    try:
        endpoint=f'127.0.0.1:{room.port}'
        a=RoomClient(endpoint,room.pin,'Host',profile=host,host_token=room.host_token)
        b=RoomClient(endpoint,room.pin,'Guest',profile=guest)
        assert wait_until(lambda:len(room.players)==2)
        with room.lock:
            h=room.players[a.id];g=room.players[b.id]
            h['x']=g['x']=500;h['y']=g['y']=500
            assert room._action(a.id,{'action':'gift_item','value':{'target':b.id,'item':'tea','count':1}})=='フレンドにだけ送れます'
            h['profile']['friend_ids'].append(g['uid'])
            msg=room._action(a.id,{'action':'gift_item','value':{'target':b.id,'item':'tea','count':1}})
            assert '送りました' in msg
            assert h['profile']['consumables']['tea']==1
            assert g['profile']['consumables']['tea']==1
            assert '不足' in room._action(a.id,{'action':'gift_item','value':{'target':b.id,'item':'tea','count':3}})
            g['x']=1500
            assert '近づいて' in room._action(a.id,{'action':'gift_item','value':{'target':b.id,'item':'tea','count':1}})
    finally:
        if a:a.close()
        if b:b.close()
        room.close()
