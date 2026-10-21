# -*- coding: utf-8 -*-
"""Map transitions, collision paths, real TCP authority and shipped pixel assets."""
from collections import deque
import math
from pathlib import Path
import time

import pytest

from area_world import OUTDOOR, NEIGHBOR, can_enter
from farm_core import new_state
from multiplayer import RoomClient, RoomServer
from pixel_art import PROPS, FISH_IDS
from scene_maps import (MAPS, NEIGHBOR_STORE, NEIGHBOR_DOOR, at_exit, can_stand,
                        contains, move, nearby, path_clear, spawn, stations)


@pytest.fixture
def game(monkeypatch,tmp_path):
    monkeypatch.setenv('APPDATA',str(tmp_path))
    monkeypatch.setenv('SDL_VIDEODRIVER','dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER','dummy')
    import ambera_farm as app
    monkeypatch.setattr(app.Game,'fetch_mails',lambda self:None)
    monkeypatch.setattr(app.Game,'refresh_notices',lambda self,force=False:None)
    g=app.Game();g.scene='world'
    yield g
    if g.online_client:g.stop_online()
    app.pygame.quit()


def wait_until(predicate,timeout=4):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if predicate():return True
        time.sleep(.01)
    return False


@pytest.fixture
def peers(tmp_path):
    room=RoomServer(new_state(),tmp_path/'room.json',port=0)
    host=guest=None
    try:
        url=f'127.0.0.1:{room.port}'
        host=RoomClient(url,room.pin,'Host',profile=new_state(),host_token=room.host_token)
        guest=RoomClient(url,room.pin,'Guest',profile=new_state())
        assert wait_until(lambda:len(room.players)==2)
        yield room,host,guest
    finally:
        if host:host.close()
        if guest:guest.close()
        room.close()


@pytest.mark.parametrize('area',tuple(MAPS))
def test_spawn_exit_and_each_facility_share_a_reachable_floor(area):
    spec=MAPS[area]
    assert can_stand(area,*spawn(area))
    # Flood-fill actual swept collision paths, not just a list of expected IDs.
    start=tuple(round(v/16)*16 for v in spawn(area))
    assert can_stand(area,*start)
    seen={start};queue=deque([start])
    while queue:
        x,y=queue.popleft()
        for end in ((x-16,y),(x+16,y),(x,y-16),(x,y+16)):
            if end not in seen and path_clear(area,(x,y),end):
                seen.add(end);queue.append(end)
    assert any(at_exit(area,point) for point in seen),area
    for station in stations(area):
        assert any(math.dist(point,(station.x,station.y))<80 for point in seen),station
    if area==NEIGHBOR:
        assert any(math.dist(point,NEIGHBOR_DOOR)<80 for point in seen)


def test_collision_refuses_counter_crossing_and_nonfinite_positions():
    point=move('room:shop',(430.,380.),0.,-100.)
    assert point[1]>=334 and can_stand('room:shop',*point)
    assert not path_clear('room:home',(960.,380.),(1120.,380.))
    assert can_stand('room:home',960.,380.) and can_stand('room:home',1120.,380.)
    for invalid in (float('nan'),float('inf'),True,'500'):
        assert not can_stand('room:home',invalid,519.)
    assert move('room:home',(637.,519.),float('inf'),0)==(637.,519.)


def test_room_warp_does_not_render_or_move_the_farm(game,monkeypatch):
    import pygame
    original=list(game.player)
    game.enter_area('room:home')
    assert game.area=='room:home' and game.modal is None
    monkeypatch.setattr(game,'draw_world',lambda:pytest.fail('Farm drawn underneath a room'))
    game.warp_started=0;game.render()
    # Physical key events drive the new map, without an interior overlay.
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_d))
    game.events();before=list(game.interior_pos)
    game.update_gameplay(.05)
    assert game.interior_pos[0]>before[0] and game.player==original
    pygame.event.post(pygame.event.Event(pygame.KEYUP,key=pygame.K_d));game.events()
    game.interior_pos=[637.,648.];game.warp_cooldown=0
    game.held_keys={pygame.K_s};game.update_gameplay(.05)
    assert game.area==OUTDOOR and game.player==original and not game.held_keys


def test_escape_and_inventory_close_to_the_same_room(game):
    import pygame
    game.enter_area('room:greenhouse')
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_ESCAPE));game.events()
    assert game.modal=='pause' and game.area=='room:greenhouse'
    game.do_action('resume',None)
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_i));game.events()
    assert game.modal=='inventory'
    game.close_overlay()
    assert game.modal is None and game.area=='room:greenhouse'


def test_home_and_greenhouse_stations_open_real_menus(game):
    game.enter_area('room:home');game.interior_pos=[400.,355.]
    before=game.state['stamina'];game.state['stamina']=max(0,before-1)
    game.area_interact()
    assert game.state['stamina']==before
    game.enter_area('room:greenhouse');game.interior_pos=[505.,340.]
    game.area_interact()
    assert game.modal=='daily_board'


def test_neighbor_shop_is_a_second_map_and_returns_to_the_town(game):
    import pygame
    outdoor=list(game.player)
    game.enter_area(NEIGHBOR);game.neighbor_pos=[637.,350.]
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_e));game.events()
    assert game.area==NEIGHBOR_STORE and game.modal is None
    game.interior_pos=[430.,350.];game.area_interact()
    assert game.modal=='neighbor_shop'
    game.close_overlay()
    assert game.area==NEIGHBOR_STORE and game.modal is None
    game.interior_pos=[637.,648.];game.warp_cooldown=0
    game.held_keys={pygame.K_s};game.update_gameplay(.05)
    assert game.area==NEIGHBOR and game.neighbor_pos==[637.,350.]
    game.neighbor_pos=[760.,889.];game.warp_cooldown=0
    game.held_keys={pygame.K_s};game.update_gameplay(.05)
    assert game.area==OUTDOOR and game.player==outdoor


def test_a_nested_menu_cannot_buy_neighbor_seeds_from_another_map(game):
    game.enter_area('room:home')
    before=game.state['coins']
    game.do_action('neighbor_buy',('corn',1))
    assert game.state['coins']==before


def test_old_area_packets_and_bad_positions_do_not_rewind_a_warp(game):
    game.enter_area('room:hall');revision=game.scene_revision
    game.apply_area({'area':OUTDOOR,'revision':revision-1,'pos':[637.,519.]})
    assert game.area=='room:hall'
    game.apply_area({'area':'room:home','revision':revision+1,'pos':None})
    assert game.area=='room:home' and can_stand(game.area,*game.interior_pos)


def test_switching_save_slots_clears_the_previous_map(game):
    game.enter_area('room:home')
    game.select_slot('offline',2)
    assert game.area==OUTDOOR and game.interior is None and game.scene=='title'


def test_every_map_and_atlas_is_loaded_renderable_and_in_updates(game):
    from updater import ALLOWED
    assert game.pixel_art.complete(), '\n'+game.pixel_art.diagnostics()
    assert len(game.pixel_art.sprites)==len(PROPS)+len(FISH_IDS)==24
    import pygame
    raw_maps=set()
    for area,spec in MAPS.items():
        game.enter_area(area);game.warp_started=0;game.render()
        assert game.modal is None
        raw_maps.add(spec.asset)
        assert 'assets/scenes/'+spec.asset+'.png' in ALLOWED
    for key in (*PROPS,*FISH_IDS):
        image=game.pixel_art.sprite(key,(80,80))
        assert image and image.get_bounding_rect(min_alpha=128).height>20
    assert len(raw_maps)==10
    for name in ('scene_maps.py','pixel_art.py','assets/scenery/props.png','assets/scenery/fish.png'):
        assert name in ALLOWED
    build=(Path(__file__).resolve().parents[1]/'build_windows.py').read_text()
    assert "('assets/scenes', 'assets/scenes')" in build
    assert "('assets/scenery', 'assets/scenery')" in build


def test_real_tcp_neighbor_store_warp_is_replicated_and_returns_to_parent(peers):
    room,host,guest=peers
    from world_map import TRAVEL_STOPS
    with room.lock:
        p=room.players[host.id];p['x'],p['y']=next(iter(TRAVEL_STOPS.values()))[1]
    assert host.action('area_enter',NEIGHBOR)
    assert wait_until(lambda:room.players[host.id]['area']==NEIGHBOR)
    with room.lock:
        p=room.players[host.id];p.update(scene_x=637.,scene_y=350.)
        farm=(p['x'],p['y'])
    assert host.action('area_enter',NEIGHBOR_STORE)
    assert wait_until(lambda:room.players[host.id]['area']==NEIGHBOR_STORE)
    packets=[]
    def replicated():
        packets.extend(guest.poll())
        return any(any(p.get('id')==host.id and p.get('area')==NEIGHBOR_STORE
                       for p in packet.get('players',[])) for packet in packets)
    assert wait_until(replicated)
    assert host.action('area_enter',NEIGHBOR)
    assert wait_until(lambda:room.players[host.id]['area']==NEIGHBOR)
    with room.lock:
        p=room.players[host.id]
        assert (p['scene_x'],p['scene_y'])==(637.,350.)
        assert (p['x'],p['y'])==farm


def test_host_rejects_a_swept_path_through_furniture_and_stale_area_revision(peers):
    room,host,_=peers
    from world_map import INTERACTION_POINTS
    with room.lock:
        p=room.players[host.id];p['x'],p['y']=INTERACTION_POINTS['home']
        room._enter_area(host.id,'room:home')
        p.update(scene_x=960.,scene_y=380.,scene_last=time.monotonic()-1)
        revision=p['scene_revision']
        room._area_move(host.id,{'area':'room:home','revision':revision,'seq':1,'x':1120.,'y':380.})
        assert (p['scene_x'],p['scene_y'])==(960.,380.)
        room._area_move(host.id,{'area':'room:home','revision':revision-1,'seq':2,'x':950.,'y':380.})
        assert (p['scene_x'],p['scene_y'])==(960.,380.)
        assert not can_enter(p,NEIGHBOR_STORE)
