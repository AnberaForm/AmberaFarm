# -*- coding: utf-8 -*-
from pathlib import Path
import tempfile
import unittest
import time
from farm_core import new_state, validate_state, save_state, load_json
from town_features import (init_town, validate_town, move_chest, rest_in_bed)
from world_map import (BUILDINGS, INTERACTION_POINTS, TRAVEL_STOPS, district_at, path_at,
                       water_at, flower_at, nearest_travel_stop, test_reachability as reachability,
                       can_stand, obstacle_tile)
from multiplayer import RoomServer, RoomClient

ROOT=Path(__file__).resolve().parents[1]

class TownRedesignTests(unittest.TestCase):
    def test_nine_building_sprites_represent_all_real_facilities(self):
        self.assertEqual(len(BUILDINGS),9)
        keys={b.key for b in BUILDINGS}
        self.assertEqual(keys,{'home','shop','general_store','workshop','greenhouse',
                               'hall','cafe','shipping','fish_market'})
        for b in BUILDINGS:
            self.assertTrue((ROOT/'assets'/'buildings'/f'{b.key}.png').is_file())
            self.assertTrue(can_stand(*b.door()),b.key)
            self.assertTrue(obstacle_tile(b.tile_x,b.tile_y))
        self.assertEqual(reachability(),[])
        self.assertTrue(path_at(30,10))
        self.assertTrue(water_at(8,29))
        self.assertFalse(flower_at(8,29))
        self.assertIn('アリーナ',district_at(*INTERACTION_POINTS['hall']))

    def test_carriage_stops_are_safe_and_host_checks_proximity(self):
        self.assertEqual(len(TRAVEL_STOPS),4)
        for key,(name,point) in TRAVEL_STOPS.items():
            self.assertTrue(can_stand(*point), key)
            self.assertEqual(nearest_travel_stop(*point),key)
        with tempfile.TemporaryDirectory() as td:
            host=validate_state(new_state())
            room=RoomServer(host,Path(td)/'host.json',port=0,pin='333333')
            client=None
            try:
                client=RoomClient(f'127.0.0.1:{room.port}',room.pin,'Host',profile=host,host_token=room.host_token)
                end=time.monotonic()+3
                while len(room.players)!=1 and time.monotonic()<end:time.sleep(.02)
                self.assertEqual(len(room.players),1)
                with room.lock:
                    result=room._action(client.id,{'action':'travel','value':'plaza'})
                    self.assertIn('停留所',result)
                    room.players[client.id].update(x=TRAVEL_STOPS['home'][1][0],
                                                   y=TRAVEL_STOPS['home'][1][1])
                    before=room.players[client.id]['profile']['coins']
                    result=room._action(client.id,{'action':'travel','value':'plaza'})
                    self.assertIn('馬車で移動',result)
                    self.assertEqual((room.players[client.id]['x'],room.players[client.id]['y']),
                                     TRAVEL_STOPS['plaza'][1])
                    self.assertEqual(room.players[client.id]['profile']['coins'],before)
                    self.assertNotIn('馬車で移動',room._action(client.id,{'action':'travel','value':[]}))
            finally:
                if client:client.close()
                room.close()

    def test_chest_roundtrip_old_save(self):
        old=new_state(now=1234)
        old['warehouse']['tomato']=7
        old['fish_inventory']['medaka']=4
        old['seeds']['radish']=3
        normalized=validate_state(old)
        self.assertIn('home_chest',normalized)
        self.assertTrue(move_chest(normalized,'warehouse','tomato',5))
        self.assertEqual(normalized['warehouse']['tomato'],2)
        self.assertEqual(normalized['home_chest']['warehouse']['tomato'],5)
        self.assertTrue(move_chest(normalized,'warehouse','tomato',3,True))
        self.assertEqual(normalized['warehouse']['tomato'],5)
        self.assertFalse(move_chest(normalized,'warehouse','tomato',9000,True))
        self.assertFalse(move_chest(normalized,'warehouse','tomato',True,True))
        self.assertFalse(move_chest(normalized,'warehouse','tomato',-1,False))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'save.json'
            save_state(normalized,path)
            restored=load_json(path)
            self.assertEqual(restored['home_chest']['warehouse']['tomato'],2)
            self.assertEqual(restored['warehouse']['tomato'],5)
            self.assertEqual(restored['plots'],old['plots'])
        self.assertTrue(rest_in_bed(restored, now=2000) is False)  # already full
        restored['stamina']=1
        self.assertTrue(rest_in_bed(restored,now=2001))
        self.assertEqual(restored['stamina'],5)
        self.assertEqual(restored['stamina_updated_at'],2001)

    def test_corrupt_chest_rejected(self):
        state=validate_state(new_state())
        state['home_chest']['seeds']['radish']=-3
        with self.assertRaises(ValueError):validate_town(state)
        with self.assertRaises(Exception):validate_state(state)

    def test_online_server_only_accepts_chest_at_home_and_keeps_balances_private(self):
        with tempfile.TemporaryDirectory() as td:
            host=validate_state(new_state());guest=validate_state(new_state())
            guest['warehouse']['tomato']=3
            room=RoomServer(host,Path(td)/'host.json',port=0,pin='246810')
            try:
                a=RoomClient(f'127.0.0.1:{room.port}',room.pin,'Host',profile=host,host_token=room.host_token)
                b=RoomClient(f'127.0.0.1:{room.port}',room.pin,'Guest',profile=guest)
                try:
                    end=time.monotonic()+3
                    while len(room.players)!=2 and time.monotonic()<end:time.sleep(.03)
                    self.assertEqual(len(room.players),2)
                    # Execute at server boundary under same lock as gameplay network.
                    with room.lock:
                        assert room._action(b.id,{'action':'home_chest','value':{'category':'warehouse',
                                             'item':'tomato','count':1,'withdraw':False}}).startswith('施設から')
                        room.players[b.id]['x'],room.players[b.id]['y']=INTERACTION_POINTS['home']
                        self.assertIn('更新',room._action(b.id,{'action':'home_chest',
                                     'value':{'category':'warehouse','item':'tomato','count':2,'withdraw':False}}))
                        self.assertEqual(room.players[b.id]['profile']['warehouse']['tomato'],1)
                        self.assertEqual(room.players[b.id]['profile']['home_chest']['warehouse']['tomato'],2)
                        self.assertEqual(room.players[a.id]['profile']['warehouse']['tomato'],0)
                        self.assertEqual(room.players[a.id]['profile']['home_chest']['warehouse']['tomato'],0)
                        # Invalid category cannot trick server into moving wallet balance.
                        self.assertNotIn('更新',room._action(b.id,{'action':'home_chest',
                                     'value':{'category':'coins','item':'tomato','count':100,'withdraw':True}}))
                        room.players[b.id]['profile']['stamina']=1
                        self.assertIn('回復',room._action(b.id,{'action':'home_rest','value':None}))
                        self.assertEqual(room.players[b.id]['profile']['stamina'],5)
                finally:
                    a.close();b.close()
            finally:room.close()

if __name__=='__main__':unittest.main()
