# -*- coding: utf-8 -*-
"""Regression tests for actual game input, scene replication and fishing authority."""
import copy
import math
import time
from pathlib import Path

import pytest

from avatar_animation import WalkCycle, AvatarAtlas
from character_avatars import IDS
from fishing_core import FishingRound, FISH_BY_ID
from farm_core import new_state
from kabuball_core import KabuballMatch, screen_aim, cpu_input, valid_input
from multiplayer import RoomServer, RoomClient
from area_world import OUTDOOR, NEIGHBOR, area_view, at_facility
from world_map import INTERACTION_POINTS, TRAVEL_STOPS
from profile_progress import public_profile


def wait_until(predicate, timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return True
        time.sleep(.015)
    return False


@pytest.fixture
def game(monkeypatch,tmp_path):
    monkeypatch.setenv('APPDATA',str(tmp_path))
    monkeypatch.setenv('SDL_VIDEODRIVER','dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER','dummy')
    import ambera_farm as app
    monkeypatch.setattr(app.Game,'fetch_mails',lambda self:None)
    monkeypatch.setattr(app.Game,'refresh_notices',lambda self,force=False:None)
    g=app.Game()
    g.scene='world'
    yield g
    if g.online_client:g.stop_online()
    app.pygame.quit()


def test_real_arena_keyboard_input_and_far_mouse_no_longer_freeze(game):
    import pygame
    game.do_action('arena_practice',None)
    m=game.practice_match
    game.mouse=(1279,40)  # used to exceed the protocol's 100-unit limit
    start=m.players[0]['x']
    cpu_start=m.players[1]['x']
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_d))
    game.events()
    for n in range(45):game.update_gameplay(1/60,now=m.started+.01+n/60)
    assert m.players[0]['x']>start+60
    assert m.players[1]['x']<cpu_start-60
    assert valid_input(m.inputs['local']) is not None
    pygame.event.post(pygame.event.Event(pygame.KEYUP,key=pygame.K_d))
    game.events()
    previous=m.players[0]['x']
    game.update_gameplay(1/60,now=m.last+1/60)
    assert m.players[0]['x']==pytest.approx(previous)


def test_actual_charge_release_and_escape_exits_practice(game):
    import pygame
    game.do_action('arena_practice',None)
    m=game.practice_match
    m.players[0].update(x=450.,y=270.)
    m.players[1].update(x=790.,y=410.)
    m.ball.update(owner='local')
    game.mouse=(1040,383)
    game.held_keys={pygame.K_j}
    now=m.started+.01
    for n in range(28):game.tick_arena(1/60,now+n/60)
    assert m.players[0]['charge']>.4
    game.held_keys.clear()
    game.tick_arena(1/60,now+29/60)
    assert m.ball['owner'] is None and m.ball['vx']>300
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE))
    game.events()
    assert game.modal=='arena' and game.practice_match is None


def test_room_keyboard_diagonal_speed_chat_return_and_nested_menu(game):
    import pygame
    game.enter_area('room:hall')
    assert game.interior_pos==[637.,519.]
    before=tuple(game.interior_pos)
    game.held_keys={pygame.K_w,pygame.K_d}
    game.move_in_area(.05)
    assert math.dist(before,game.interior_pos)==pytest.approx(9.)
    game.toggle_chat()
    game.close_chat()
    assert game.modal=='interior' and game.area=='room:hall'
    game.modal='arena'
    game.close_overlay()
    assert game.modal=='interior'
    game.close_overlay()
    assert game.area==OUTDOOR and game.interior is None and game.modal is None


def test_focus_loss_clears_arena_and_room_controls(game):
    import pygame
    game.enter_area('room:home')
    game.held_keys={pygame.K_w,pygame.K_j}
    pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    game.events()
    pos=list(game.interior_pos)
    game.move_in_area(.05)
    assert game.interior_pos==pos and not game.held_keys


def test_avatar_sheets_all_directions_and_costume_are_used(game):
    assert len(game.avatar_atlas.frames)==len(IDS)*16
    import pygame
    for aid in IDS:
        images=[game.avatar_atlas.sprite(aid,d,1,(50,65)) for d in ('up','down','left','right')]
        assert all(s is not None and s.get_bounding_rect().height>30 for s in images)
        assert len({pygame.image.tobytes(s,'RGBA') for s in images})==4
    original=game.avatar_atlas.sprite('original_girl','down',1,(50,65))
    dyed=game.avatar_atlas.sprite('original_girl','down',1,(50,65),{'shirt':3,'hat':5})
    assert pygame.image.tobytes(original,'RGBA')!=pygame.image.tobytes(dyed,'RGBA')
    game.state['outfits'].append({'name':'青い服','shirt':3,'hat':5})
    game.state['outfit_index']=1
    assert public_profile(game.state)['outfit']=={'shirt':3,'hat':5}
    for modal in ('avatars','costume','arena','neighbor_town','neighbor_shop'):
        game.modal=modal
        game.render()  # catches missing asset APIs and UI crashes


@pytest.mark.parametrize('direction,delta',[('right',(1,0)),('left',(-1,0)),('up',(0,-1)),('down',(0,1))])
def test_walk_cycle_uses_actual_travel_and_stops(direction,delta):
    cycle=WalkCycle()
    pos=[500.,500.]
    cycle.observe(pos)
    frames=set()
    for _ in range(48):
        pos=[pos[0]+delta[0],pos[1]+delta[1]]
        facing,frame=cycle.observe(pos)
        assert facing==direction
        frames.add(frame)
    assert frames=={0,1,2,3}
    assert cycle.observe(pos)==(direction,0)
    assert not cycle.moving
    # A camera / scene warp is not a walking stride.
    assert cycle.observe((600,500),'room:home')[1]==0


@pytest.mark.parametrize('mouse',[(0,0),(1279,719),(640,360),(900,40)])
def test_every_screen_aim_is_valid(mouse):
    aim=screen_aim(mouse,{'x':298,'y':270})
    command=valid_input({'dx':1,'ax':aim[0],'ay':aim[1]})
    assert command is not None
    assert math.hypot(command['ax'],command['ay'])<=1.000001


@pytest.mark.parametrize('difficulty',['easy','normal','hard'])
def test_cpu_commands_are_valid_at_kickoff_and_when_far(difficulty):
    m=KabuballMatch(1,'local','cpu',now=0)
    m.accept(now=0)
    for x,y in ((480,270),(121,100),(839,444)):
        m.ball.update(x=x,y=y)
        assert valid_input(cpu_input(m,4,difficulty)) is not None


def play_expert(fish_id,seed=7,dt=1/60):
    r=FishingRound(fish_id,seed=seed)
    for _ in range(math.ceil(29/dt)):
        delta=r.fish_y-r.bobber_y
        direction=1 if delta>.012 else -1 if delta<-.012 else 0
        reeling=not r.struggling and r.tension<66 and abs(delta)<r.tolerance*.9
        r.step(dt,direction,reeling)
        if r.result:break
    return r


def test_fishing_is_harder_for_rare_fish_and_still_winnable():
    easy=play_expert('medaka')
    hard=play_expert('gold_koi')
    assert easy.result==hard.result=='caught'
    assert easy.elapsed>4.5 and hard.elapsed>easy.elapsed*1.7
    assert hard.tolerance<easy.tolerance*.55


def test_holding_reel_all_the_time_breaks_line_even_when_tracking():
    r=FishingRound('gold_koi',seed=3)
    for _ in range(2000):
        r.bobber_y=r.fish_y
        r.step(1/60,0,True)
        if r.result:break
    assert r.result=='escaped' and r.tension==100


def test_fishing_fixed_steps_are_equal_at_30_and_120_fps():
    a=FishingRound('koi',seed=11)
    b=FishingRound('koi',seed=11)
    for _ in range(180):a.step(1/30,0,False)
    for _ in range(720):b.step(1/120,0,False)
    assert a.elapsed==pytest.approx(b.elapsed,abs=1/120)
    assert a.fish_y==pytest.approx(b.fish_y,abs=.01)
    assert a.remaining==pytest.approx(b.remaining,abs=1/120)


@pytest.fixture
def connected_room(tmp_path):
    room=RoomServer(new_state(),tmp_path/'room.json',port=0)
    a=b=None
    try:
        url=f'127.0.0.1:{room.port}'
        a=RoomClient(url,room.pin,'Host',profile=new_state(),host_token=room.host_token)
        b=RoomClient(url,room.pin,'Guest',profile=new_state())
        assert wait_until(lambda:len(room.players)==2)
        yield room,a,b
    finally:
        if a:a.close()
        if b:b.close()
        room.close()


def test_room_entry_is_authorized_and_replicated_over_real_tcp(connected_room):
    room,a,b=connected_room
    with room.lock:
        p=room.players[a.id]
        assert room._enter_area(a.id,'room:hall')!='移動しました'
        p['x'],p['y']=INTERACTION_POINTS['hall']
    assert a.action('area_enter','room:hall')
    assert wait_until(lambda:room.players[a.id].get('area')=='room:hall')
    collected=[]
    def replicated():
        collected.extend(b.poll())
        return any(any(p.get('id')==a.id and p.get('area')=='room:hall' for p in packet.get('players',[])) for packet in collected)
    assert wait_until(replicated)
    assert any(p.get('type') in ('positions','snapshot') for p in collected)
    with room.lock:
        p=room.players[a.id]
        p['scene_last']=time.monotonic()-.2
        revision=p['scene_revision']
    assert a.send('area_move',area='room:hall',revision=revision,seq=1,x=647.,y=509.,facing='up')
    assert wait_until(lambda:room.players[a.id]['scene_seq']==1)
    assert room.players[a.id]['scene_x']==647
    with room.lock:
        p=room.players[a.id]
        room._area_move(a.id,{'area':'room:hall','revision':revision,'seq':2,'x':999,'y':300})
        assert (p['scene_x'],p['scene_y'])==(647,509)
        room._enter_area(a.id,OUTDOOR)
        assert p['area']==OUTDOOR


def test_interior_facilities_neighbor_shop_and_remote_gift_distance(connected_room):
    room,a,b=connected_room
    with room.lock:
        p=room.players[a.id]
        p['x'],p['y']=INTERACTION_POINTS['shop']
        assert room._enter_area(a.id,'room:shop')=='移動しました'
        p.update(scene_x=430.,scene_y=330.)
        assert at_facility(p,'shop')
        before=p['profile']['seeds']['kaiware']
        result=room._action(a.id,{'action':'buy','value':['kaiware',1]})
        assert '反映' in result and p['profile']['seeds']['kaiware']==before+1
        assert not at_facility(p,'shipping')
        room._enter_area(a.id,OUTDOOR)
        p['x'],p['y']=next(iter(TRAVEL_STOPS.values()))[1]
        assert room._enter_area(a.id,NEIGHBOR)=='移動しました'
        coins=p['profile']['coins']
        assert '近づいて' in room._action(a.id,{'action':'neighbor_buy','value':{'crop':'corn','count':1}})
        assert p['profile']['coins']==coins
        p.update(scene_x=637.,scene_y=330.)
        assert '購入しました' in room._action(a.id,{'action':'neighbor_buy','value':{'crop':'corn','count':1}})


def test_server_validates_fishing_and_grants_exactly_one_catch(connected_room,monkeypatch):
    import multiplayer
    monkeypatch.setattr(multiplayer,'roll_fish',lambda:FISH_BY_ID['medaka'])
    room,a,b=connected_room
    with room.lock:
        p=room.players[a.id]
        p['x'],p['y']=INTERACTION_POINTS['fishing']
        before=p['profile']['stats']['fish_caught']
        room._action(a.id,{'action':'fish_caught','value':'gold_koi'})
        assert p['profile']['stats']['fish_caught']==before
        assert '開始' in room._action(a.id,{'action':'fish_start','value':None})
        session=p['fishing'];r=session['round']
        now=session['last']
        for _ in range(28*60+1):
            now+=1/60
            delta=r.fish_y-r.bobber_y
            session.update(input_at=now,direction=1 if delta>.012 else -1 if delta<-.012 else 0,
                           reeling=not r.struggling and r.tension<66 and abs(delta)<r.tolerance*.9)
            room._fishing_tick(now)
            if r.result:break
        assert r.result=='caught'
        assert p['profile']['stats']['fish_caught']==before+1
        assert p['profile']['fish_inventory']['medaka']==1
        for _ in range(5):room._fishing_tick(now+1)
        assert p['profile']['fish_inventory']['medaka']==1
        # Old, forged and out-of-order commands cannot change a finished round.
        view=copy.deepcopy(r.view())
        room._fish_input(a.id,{'id':'wrong','direction':1,'reeling':True})
        assert r.view()==view


def test_cannot_start_fishing_or_edit_round_from_another_scene(connected_room):
    room,a,b=connected_room
    with room.lock:
        p=room.players[a.id]
        assert '近づいて' in room._action(a.id,{'action':'fish_start','value':None})
        assert p['fishing'] is None
        p['x'],p['y']=INTERACTION_POINTS['home']
        room._enter_area(a.id,'room:home')
        assert '近づいて' in room._action(a.id,{'action':'fish_start','value':None})


def test_real_online_arena_input_moves_both_peers_and_exit_cancels(connected_room):
    room,a,b=connected_room
    with room.lock:
        for p in room.players.values():p['x'],p['y']=INTERACTION_POINTS['hall']
        room._arena_action(a.id,'arena_challenge',{'target':b.id,'stake':0})
        room._arena_action(b.id,'arena_accept',None)
        m=next(iter(room.arena_matches.values()))
        m.started=time.monotonic()-.1;m.pause_until=0.;m.last=time.monotonic()
        before=[p['x'] for p in m.players]
    ax,ay=screen_aim((1279,0),m.players[0])
    assert a.send('arena_input',input={'dx':1,'ax':ax,'ay':ay})
    assert b.send('arena_input',input={'dx':-1,'ax':-1})
    assert wait_until(lambda:m.players[0]['x']>before[0]+8 and m.players[1]['x']<before[1]-8)
    assert a.action('arena_forfeit',None)
    assert wait_until(lambda:m.status=='canceled')
    with room.lock:
        assert all(p['profile']['coins']==200 for p in room.players.values())


def test_python_update_contains_new_modules_and_walking_images(tmp_path):
    from make_release import make
    from updater import inspect_package
    package,_=make('https://example.com/AmberaFarm_update_9_3_0.zip',tmp_path)
    contents=inspect_package(package.read_bytes())
    for name in ('avatar_animation.py','area_world.py','character_avatars.py','save_slots.py',
                 'kabuball_core.py','interior_world.py','profile_progress.py'):
        assert name in contents
    for aid in IDS:
        assert 'assets/avatars/'+aid+'_walk.png' in contents
