# -*- coding: utf-8 -*-
"""v9 arena / profiles / migration / authoritative LAN play."""
import math
import time

import pytest
from world_map import INTERACTION_POINTS
from farm_core import new_state, save_state, load_state
from kabuball_core import KabuballMatch, valid_input, RIGHT, MID_Y, DURATION, OVERTIME
from multiplayer import RoomClient,RoomServer,PROTOCOL
from profile_progress import (init_profile, validate_profile, refresh_progress,
    board_rows,claim_daily,public_profile,apply_arena_result,unlocked_titles,
    level_from_xp,cache_public_profiles)


def wait_until(pred,timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if pred():return True
        time.sleep(.025)
    return False


def test_progress_migration_and_save_preserves_existing_resources(tmp_path):
    s=new_state();s['coins']=777;s['warehouse']['kaiware']=12
    s['stats']['planted']=9
    # Old saves without profile fields remain valid.
    path=tmp_path/'save.json'
    save_state(s,path)
    loaded,_=load_state(path)
    assert loaded['coins']==777 and loaded['warehouse']['kaiware']==12
    assert loaded['farm_level']==1 and loaded['farm_xp']==0
    assert loaded['farm_stat_seen']['planted']==9
    loaded['profile_bio']='みんなよろしく！'
    loaded['stats']['planted']=11
    assert refresh_progress(loaded)==16
    save_state(loaded,path)
    after,_=load_state(path)
    assert after['farm_xp']==16 and after['profile_bio']=='みんなよろしく！'


def test_daily_request_reward_once_and_reset():
    s=new_state();init_profile(s,'2026-10-21')
    assert not claim_daily(s,'planted','2026-10-21')
    s['stats']['planted']+=2
    assert claim_daily(s,'planted','2026-10-21')
    coins=s['coins'];xp=s['farm_xp']
    assert not claim_daily(s,'planted','2026-10-21')
    assert coins==s['coins'] and xp==s['farm_xp']
    assert board_rows(s,'2026-10-21')[0]['claimed']
    assert board_rows(s,'2026-10-22')[0]['progress']==0
    assert not claim_daily(s,'planted','2026-10-22')


def test_profile_public_allowlist_and_titles():
    s=new_state();init_profile(s)
    s['player_name']='あいう'
    s['profile_bio']='こんにちは';s['arena_record']['wins']=1
    s['profile_title']='kabuball'
    public=public_profile(s)
    assert public['title']=='kabuball' and public['bio']=='こんにちは'
    assert not {'coins','warehouse','seeds','friend_ids','plots'} & set(public)
    assert 'kabuball' in unlocked_titles(s)
    s['profile_cache']={}
    cache_public_profiles(s,[{'public_profile':public}])
    assert not s['profile_cache'] # Self must not be cached as a friend.
    assert level_from_xp(0)==1 and level_from_xp(100)==2


def test_result_is_idempotent_and_never_touches_coins():
    s=new_state();init_profile(s)
    coins=s['coins']
    assert apply_arena_result(s,3,1,'Guest',12345)
    assert not apply_arena_result(s,3,1,'Guest',12345)
    assert s['arena_record']['wins']==1 and s['arena_record']['rating']==1015
    assert s['coins']==coins


def test_invalid_input_is_rejected_and_vectors_bounded():
    for raw in ('bad',{},None,{'dx':float('nan')},{'dx':1000000}):
        if raw=={}:continue
        assert valid_input(raw) is None
    v=valid_input({'dx':5,'dy':5,'ax':30,'ay':-50,'shoot':1,'dash':True})
    assert math.isclose(math.hypot(v['dx'],v['dy']),1)
    assert not v['shoot'] and v['dash']


def test_goal_scoring_and_overtime_finish():
    m=KabuballMatch(88,'p1','p2',now=10)
    assert m.accept(now=10)
    m.ball.update(x=RIGHT-12,y=MID_Y,vx=600,vy=0,owner=None)
    m.step(13.05)
    assert m.scores==[1,0]
    assert m.elapsed(16.05)==pytest.approx(.05) # goal celebration freezes game clock
    m.step(13+DURATION+3.1)
    assert m.status=='finished'
    t=KabuballMatch(88,'p1','p2',now=10)
    t.accept(now=10);t.step(13+DURATION+.1)
    assert t.overtime and t.status=='active'
    t.step(13+DURATION+OVERTIME+.1)
    assert t.status=='finished' and t.scores==[0,0]


def test_charge_and_shoot_release():
    m=KabuballMatch(9,'p1','p2',now=1)
    m.accept(now=1)
    m.players[0]['x']=451
    m.step(4.05)
    assert m.ball['owner']=='p1'
    m.update_input('p1',{'shoot':True,'ax':1})
    for n in range(5):m.step(4.10+n*.06)
    assert m.players[0]['charge']>0
    m.update_input('p1',{'shoot':False,'ax':1})
    m.step(4.45)
    assert m.ball['owner'] is None
    assert m.ball['vx']>200


def test_server_arena_start_and_results_with_private_money(tmp_path):
    assert PROTOCOL== 9
    host=new_state();guest=new_state()
    room=RoomServer(host,tmp_path/'arena.json',port=0)
    a=b=None
    try:
        url=f'127.0.0.1:{room.port}'
        a=RoomClient(url,room.pin,'Host',profile=host,host_token=room.host_token)
        b=RoomClient(url,room.pin,'Guest',profile=guest)
        assert wait_until(lambda:len(room.players)==2)
        with room.lock:
            for p in room.players.values():
                p['x'],p['y']=INTERACTION_POINTS['hall']
        assert a.action('arena_challenge',{'target':b.id,'stake':0})
        assert wait_until(lambda:len(room.arena_matches)==1)
        assert b.action('arena_accept',None)
        assert wait_until(lambda:next(iter(room.arena_matches.values())).status=='active')
        m=next(iter(room.arena_matches.values()))
        with room.lock:
            m.scores=[2,0];m.finish(time.monotonic());room._arena_tick()
            assert room.players[a.id]['profile']['arena_record']['wins']==1
            assert room.players[b.id]['profile']['arena_record']['losses']==1
            assert room.players[a.id]['profile']['coins']==200
            assert room.players[b.id]['profile']['coins']==200
        assert wait_until(lambda:any(p.get('arena') and p['arena']['status']=='finished' for p in a.poll()))
        # Rematch requires two explicit confirmations.
        assert a.action('arena_replay',None)
        assert wait_until(lambda:m.invited_replay=={a.id})
        assert b.action('arena_replay',None)
        assert wait_until(lambda:len(room.arena_matches)==2)
    finally:
        if a:a.close()
        if b:b.close()
        room.close()


def test_host_does_not_send_wallet_in_public_profile(tmp_path):
    s=new_state();room=RoomServer(s,tmp_path/'p.json',port=0)
    a=b=None
    try:
        a=RoomClient(f'127.0.0.1:{room.port}',room.pin,profile=s,host_token=room.host_token)
        b=RoomClient(f'127.0.0.1:{room.port}',room.pin,profile=new_state())
        assert wait_until(lambda:len(room.players)==2)
        snapshots=[]
        def got_snapshot():
            snapshots.extend(b.poll())
            return any(p.get('type')=='snapshot' and len(p.get('players',[]))==2 for p in snapshots)
        assert wait_until(got_snapshot)
        snapshot=next(p for p in snapshots if p.get('type')=='snapshot' and len(p.get('players',[]))==2)
        for p in snapshot['players']:
            view=p['public_profile']
            assert 'coins' not in view and 'warehouse' not in view and 'seeds' not in view
    finally:
        if a:a.close()
        if b:b.close()
        room.close()


def test_arena_rejects_stakes_without_trusted_economy(tmp_path):
    room=RoomServer(new_state(),tmp_path/'safe.json',port=0)
    a=b=None
    try:
        a=RoomClient(f'127.0.0.1:{room.port}',room.pin,profile=new_state(),host_token=room.host_token)
        b=RoomClient(f'127.0.0.1:{room.port}',room.pin,profile=new_state())
        assert wait_until(lambda:len(room.players)==2)
        with room.lock:
            for player in room.players.values():player['x'],player['y']=INTERACTION_POINTS['hall']
            result=room._arena_action(a.id,'arena_challenge',{'target':b.id,'stake':50})
            assert '無効' in result
            assert not room.arena_matches
            assert room.players[a.id]['profile']['coins']==200
            assert room.players[b.id]['profile']['coins']==200
    finally:
        if a:a.close()
        if b:b.close()
        room.close()


def test_friend_profile_cached_and_bio_changes(tmp_path):
    room=RoomServer(new_state(),tmp_path/'friends.json',port=0)
    a=b=None
    try:
        a=RoomClient(f'127.0.0.1:{room.port}',room.pin,'A',profile=new_state(),host_token=room.host_token)
        b=RoomClient(f'127.0.0.1:{room.port}',room.pin,'B',profile=new_state())
        assert wait_until(lambda:len(room.players)==2)
        with room.lock:
            assert '申請' in room._friend_action(a.id,'friend_request',b.id)
            assert 'フレンド' in room._friend_action(b.id,'friend_accept',a.id)
            a_uid=room.players[a.id]['uid']
            b_uid=room.players[b.id]['uid']
            assert b_uid in room.players[a.id]['profile']['profile_cache']
            assert a_uid in room.players[b.id]['profile']['profile_cache']
            assert room._action(a.id,{'action':'profile_bio','value':'友達募集中'})=='自己紹介を更新しました'
            cached=room.players[b.id]['profile']['profile_cache'][a_uid]
            assert cached['bio']=='友達募集中'
            assert 'coins' not in cached
    finally:
        if a:a.close()
        if b:b.close()
        room.close()


def test_server_daily_claim_cannot_double_claim(tmp_path):
    room=RoomServer(new_state(),tmp_path/'quests.json',port=0)
    a=None
    try:
        a=RoomClient(f'127.0.0.1:{room.port}',room.pin,profile=new_state(),host_token=room.host_token)
        assert wait_until(lambda:len(room.players)==1)
        with room.lock:
            state=room.players[a.id]['profile']
            rows=board_rows(state)
            initial=state['coins']
            state['stats']['planted']=state['daily_board']['baseline']['planted']+2
            assert '達成' in room._action(a.id,{'action':'daily_claim','value':'planted'})
            assert state['coins']==initial+rows[0]['coins']
            assert '受取済み' in room._action(a.id,{'action':'daily_claim','value':'planted'})
            assert state['coins']==initial+rows[0]['coins']
    finally:
        if a:a.close()
        room.close()
