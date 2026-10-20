# -*- coding: utf-8 -*-
import json
from datetime import datetime
import tempfile
import time
from pathlib import Path
import pytest
from farm_core import CROPS,new_state,save_state,load_json,validate_state,progress_for
from v8_features import (init_v8,field_action,field_phase,buy_consumable,use_consumable,
                         new_outfit,OUTFIT_COLORS,active_event,earn_event_token,exchange_event,
                         receive_public_mail,add_friend,duel_practice)
from farm_mailbox import validate as validate_mail
from world_map import can_stand,INTERACTION_POINTS,test_reachability as map_reachability
from fishing_core import FISH_BY_ID
from pack_windows_release import pack
from exe_launcher import list_payload
import zipfile


def test_four_step_farm_cycle_real_duration():
    st=init_v8(new_state(now=100000.))
    assert field_phase(st,0)=='till'
    assert field_action(st,0,'kaiware',now=100000.)=='till'
    assert field_phase(st,0)=='water'
    assert field_action(st,0,'kaiware',now=100000.)=='water'
    assert field_phase(st,0)=='seed'
    assert field_action(st,0,'kaiware',now=100000.)=='plant'
    assert st['seeds']['kaiware']==3
    p=st['plots'][0]
    assert p['planted_at']==100000.
    assert not progress_for(p,now=100000.+599)[2]
    assert progress_for(p,now=100000.+600)[2]
    assert field_action(st,0,'kaiware',now=100000.+600)=='harvest'
    assert st['stamina']==4  # six hundred seconds also restores hearts naturally
    assert st['warehouse']['kaiware']==1
    assert field_phase(st,0)=='till'


def test_stamina_and_store_inventory():
    st=init_v8(new_state())
    st['stamina']=0
    assert field_action(st,0,'kaiware')=='tired'
    money=st['coins']
    assert buy_consumable(st,'riceball')
    assert st['coins']==money-65
    assert use_consumable(st,'riceball')
    assert st['stamina']==3
    assert field_action(st,0,'kaiware')=='till'
    assert not use_consumable(st,'riceball')


def test_migration_keeps_old_farm_and_restores_v8(tmp_path):
    st=new_state(now=100)
    st['plots'][0]={'crop':'radish','planted_at':123.0}
    st['warehouse']['tomato']=6
    out=tmp_path/'save.json'
    save_state(st,out)
    restored=load_json(out)
    assert restored['plots'][0]['planted_at']==123.0
    assert restored['warehouse']['tomato']==6
    assert restored['stamina']==5
    restored['stamina']=3
    restored['plot_preparation'][1]=2
    restored['consumables']['tea']=3
    save_state(restored,out)
    after=load_json(out)
    assert after['stamina']==3
    assert after['plot_preparation'][1]==2
    assert after['consumables']['tea']==3


def test_event_and_dressup():
    st=init_v8(new_state())
    now=datetime(2026,10,20,12).timestamp()
    assert active_event(now)['name']=='秋の収穫祭'
    for i in range(22):earn_event_token(st,now)
    assert st['event_tokens']==20
    assert exchange_event(st,'autumn_hat',now)
    assert st['event_tokens']==15
    assert not exchange_event(st,'autumn_hat',now)
    st['outfit_draft']={'shirt':1,'hat':2}
    assert new_outfit(st)
    assert st['outfits'][-1]['shirt']==1
    assert add_friend(st,'あおい')
    assert not add_friend(st,'あおい')
    assert len(OUTFIT_COLORS)>=6


def test_mail_validation_claim_once():
    obj={'schema':1,'campaigns':[{'id':'gift1','title':'プレゼント','coins':100,'item':'tea','count':2}]}
    mail=validate_mail(obj)['campaigns'][0]
    st=init_v8(new_state())
    before=st['coins']
    assert receive_public_mail(st,mail)
    assert not receive_public_mail(st,mail)
    assert st['coins']==before+100
    assert st['consumables']['tea']==2
    with pytest.raises(ValueError):validate_mail({'schema':1,'campaigns':[dict(mail,coins=1000000)]})


def test_fishing_rebalanced_relative_to_farming():
    assert FISH_BY_ID['medaka'].price<25
    assert FISH_BY_ID['gold_koi'].price<500
    assert FISH_BY_ID['gold_koi'].price>FISH_BY_ID['medaka'].price


def test_map_reachable_and_lobby():
    assert map_reachability()==[]
    assert can_stand(*INTERACTION_POINTS['hall'])
    assert can_stand(*INTERACTION_POINTS['general_store'])


def test_minigame_rules():
    assert duel_practice('guess',2,2)
    assert not duel_practice('guess',1,2)
    assert duel_practice('timing',.51,.56)
    assert duel_practice('reaction',.22,.6)


def test_release_no_admin_ui_for_new_players(tmp_path):
    exes=tmp_path/'exes';exes.mkdir()
    for name in ('AmberaFarm.exe','AmberaGame.exe','AmberaStoryEditor.exe'):
        (exes/name).write_bytes(b'MZ'+name.encode('ascii'))
    install,payload,_=pack(exes,tmp_path/'output','Example/AmberaFarm','8.0.0')
    with zipfile.ZipFile(install) as z:
        assert 'app/AmberaStoryEditor.exe' not in z.namelist()
    with zipfile.ZipFile(payload) as z:
        assert 'app/AmberaStoryEditor.exe' in z.namelist() # v0.7 launcher backwards compatibility
        list_payload(z,'8.0.0')
