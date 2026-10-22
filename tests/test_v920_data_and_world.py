# -*- coding: utf-8 -*-
"""v9.2: saves and local integrity, avatars, interiors, neighboring-town stock."""
from pathlib import Path
import pytest
from farm_core import SaveError, load_json, new_state, save_state, validate_state
from save_slots import (slot_file,slot_summaries,legacy_migrate,load_slot,
                        save_slot,new_slot,import_offline_to_online)
from character_avatars import IDS, AVATARS, valid_avatar
from neighbor_town import TOWN_STOCK, shop_rows, town_buy
from interior_world import ROOMS, STATIONS, SPAWN, nearby, move, walkable
from v8_features import init_v8
from profile_progress import public_profile


def test_only_four_slots(tmp_path):
    assert len(slot_summaries(tmp_path))==4
    assert len({slot_file(k,i,tmp_path) for k in ('offline','online') for i in (1,2)})==4
    with pytest.raises(ValueError):slot_file('online',3,tmp_path)
    with pytest.raises(ValueError):slot_file('offline',True,tmp_path)


def test_old_single_save_is_copied_and_left_untouched(tmp_path):
    legacy=tmp_path/'legacy.json'
    original=init_v8(new_state())
    original['coins']=319
    save_state(original,legacy)
    before=legacy.read_bytes()
    assert legacy_migrate(tmp_path/'slots',legacy)
    loaded,_=load_slot('offline',1,tmp_path/'slots')
    assert loaded['coins']==319
    assert legacy.read_bytes()==before
    assert not legacy_migrate(tmp_path/'slots',legacy)


def test_offline_import_is_rejected_and_original_is_untouched(tmp_path):
    root=tmp_path/'slots'
    new_slot('offline',1,root)
    original,_=load_slot('offline',1,root)
    original['coins']=91
    save_slot(original,'offline',1,root)
    before=slot_file('offline',1,root).read_bytes()
    with pytest.raises(SaveError,match='持ち込めません'):
        import_offline_to_online(1,1,root)
    assert not slot_file('online',1,root).exists()
    assert slot_file('offline',1,root).read_bytes()==before
    offline,_=load_slot('offline',1,root)
    assert offline['coins']==91


def test_hmac_detects_plain_json_edit(tmp_path):
    root=tmp_path/'slots'
    new_slot('online',2,root)
    slot=slot_file('online',2,root)
    assert load_slot('online',2,root)[0]['coins']==200
    data=slot.read_text(encoding='utf-8')
    slot.write_text(data.replace('"coins": 200','"coins": 9000'),encoding='utf-8')
    with pytest.raises(SaveError,match='改ざん'):load_slot('online',2,root)


def test_hmac_is_optional_only_for_offline_slots(tmp_path):
    root=tmp_path/'slots'
    new_slot('offline',2,root)
    path=slot_file('offline',2,root)
    assert path.exists() and not path.with_suffix('.hmac').exists()
    assert load_slot('offline',2,root)[0]['coins']==200


def test_avatar_migration_validated_and_public(tmp_path):
    state=init_v8(new_state())
    assert state['avatar_id']=='original_girl'
    assert len(IDS)==7 and len(AVATARS)==7
    state['avatar_id']='silver_boy'
    assert public_profile(state)['avatar_id']=='silver_boy'
    loaded=validate_state(state)
    assert loaded['avatar_id']=='silver_boy'
    state['avatar_id']='invalid'
    with pytest.raises(SaveError):validate_state(state)
    assert valid_avatar('hacker')=='original_girl'


def test_real_png_assets_ship_with_build():
    root=Path(__file__).resolve().parents[1]
    for avatar in IDS:
        for frame in range(4):
            path=root/'assets'/'avatars'/f'{avatar}_{frame}.png'
            assert path.is_file()
            assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    for item in ('tea','riceball','lunch'):
        assert (root/'assets'/'items'/f'{item}.png').read_bytes().startswith(b'\x89PNG')
    assert "('assets/avatars', 'assets/avatars')" in (root/'build_windows.py').read_text()


def test_room_geometry_and_stations():
    assert len(ROOMS)==9
    assert all(STATIONS[room] for room in ROOMS)
    assert walkable(*SPAWN)
    assert move(SPAWN,99999,99999)==SPAWN # collision refuses enormous step
    for room in ROOMS:
        for station in STATIONS[room]:
            # Approach station from reachable near-counter floor.
            point=(station.x,max(292,station.y+38))
            assert nearby(room,point) is not None


def test_neighbor_shop_items_and_cost_validation():
    state=init_v8(new_state())
    state['coins']=200
    assert len(TOWN_STOCK)>=5
    assert len(shop_rows(state))==len(TOWN_STOCK)
    assert not town_buy(state,'kaiware',1)
    assert not town_buy(state,TOWN_STOCK[0],-999)
    crop=TOWN_STOCK[0]
    assert town_buy(state,crop,1)
    assert state['seeds'][crop]==1
    assert state['coins']<200


def test_no_permission_to_clone_missing_legacy_slot(tmp_path):
    with pytest.raises(SaveError):import_offline_to_online(2,1,tmp_path)


def test_corrupt_legacy_not_migrated_or_deleted(tmp_path):
    legacy=tmp_path/'save.json'
    legacy.write_text('{not valid json}',encoding='utf-8')
    with pytest.raises(SaveError):legacy_migrate(tmp_path/'slots',legacy)
    assert legacy.read_text(encoding='utf-8')=='{not valid json}'
    assert not slot_file('offline',1,tmp_path/'slots').exists()


def test_host_keeps_existing_online_plots(tmp_path):
    import time
    from multiplayer import RoomServer
    state=init_v8(new_state())
    state['plots'][0]={'crop':'kaiware','planted_at':time.time()-100}
    room=RoomServer(state,tmp_path/'coop.json',port=0,fresh=False)
    try:
        assert room.state['plots'][0]['crop']=='kaiware'
    finally:
        room.close()
