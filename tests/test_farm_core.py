# -*- coding: utf-8 -*-
import copy, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from farm_core import (
    CROPS, PLOT_COUNT, SECONDS_PER_GAME_MINUTE, new_state, plant, harvest,
    progress_for, save_state, load_state, load_json, validate_state,
    buy_seeds, sell_crops, mission_progress, claim_mission, SaveError, clock_at,
)
TIMES = [600,1200,1800,3600,4800,7200,14400,21600,28800,57600,86400,201600]

class FarmGameTests(unittest.TestCase):
    def test_all_12_crop_durations(self):
        self.assertEqual(len(CROPS),12)
        self.assertEqual([c.grow_seconds for c in CROPS],TIMES)
        self.assertEqual(SECONDS_PER_GAME_MINUTE,20)

    def test_all_crops_growth_boundaries(self):
        for crop in CROPS:
            with self.subTest(crop=crop.id):
                obj={'crop':crop.id,'planted_at':100000}
                self.assertEqual(progress_for(obj,100000),(0, float(crop.grow_seconds),False))
                self.assertFalse(progress_for(obj,100000+crop.grow_seconds-.001)[2])
                self.assertTrue(progress_for(obj,100000+crop.grow_seconds)[2])
                self.assertTrue(progress_for(obj,100000+crop.grow_seconds+99999)[2])

    def test_plant_consumes_seeds(self):
        state=new_state(100000)
        self.assertEqual(len(state['plots']),PLOT_COUNT)
        self.assertEqual(state['seeds']['kaiware'],4)
        self.assertTrue(plant(state,0,'kaiware',100000))
        self.assertEqual(state['seeds']['kaiware'],3)
        self.assertFalse(plant(state,0,'kaiware',100000))
        self.assertEqual(state['seeds']['kaiware'],3)
        self.assertFalse(plant(state,1,'suika',100000))

    def test_harvest_and_warehouse(self):
        state=new_state(100000)
        self.assertTrue(plant(state,2,'kaiware',100000))
        self.assertIsNone(harvest(state,2,100599))
        self.assertEqual(harvest(state,2,100600),'kaiware')
        self.assertEqual(state['warehouse']['kaiware'],1)
        self.assertEqual(state['harvest_total'],1)
        self.assertEqual(state['stats']['harvested'],1)
        self.assertEqual(state['harvested_types']['kaiware'],1)
        self.assertIsNone(harvest(state,2,100600))

    def test_buy_debit_and_inventory(self):
        s=new_state(100)
        cash=s['coins']
        self.assertTrue(buy_seeds(s,'radish',3))
        self.assertEqual(s['coins'],cash-3*next(c.buy_price for c in CROPS if c.id=='radish'))
        self.assertEqual(s['seeds']['radish'],3)
        self.assertEqual(s['stats']['bought'],3)
        self.assertFalse(buy_seeds(s,'kin_ringo',20))
        self.assertFalse(buy_seeds(s,'radish',0))
        self.assertFalse(buy_seeds(s,'missing',1))

    def test_sell_and_income(self):
        s=new_state(100)
        s['warehouse']['kaiware']=4
        cash=s['coins']
        self.assertTrue(sell_crops(s,'kaiware',3))
        self.assertEqual(s['warehouse']['kaiware'],1)
        self.assertEqual(s['stats']['shipped'],3)
        self.assertEqual(s['coins'],cash+60)
        self.assertFalse(sell_crops(s,'kaiware',2))
        self.assertFalse(sell_crops(s,'kaiware',-1))

    def test_missions_one_time_rewards(self):
        s=new_state(100)
        self.assertFalse(claim_mission(s,'plant1'))
        plant(s,0,'kaiware',100)
        self.assertEqual(mission_progress(s,'plant1'),(1,1))
        before=s['coins']
        self.assertTrue(claim_mission(s,'plant1'))
        self.assertEqual(s['coins'],before+40)
        self.assertFalse(claim_mission(s,'plant1'))
        self.assertEqual(s['coins'],before+40)
        self.assertFalse(claim_mission(s,'nope'))

    def test_save_restore_offline_growth(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'save.json'
            s=new_state(1000000)
            s['coins'] = 1000
            self.assertTrue(buy_seeds(s,'suika',1))
            plant(s,0,'suika',1000000)
            s['player']=[321.,435.]
            save_state(s,file)
            restored,_=load_state(file,1000000+86400)
            self.assertTrue(progress_for(restored['plots'][0],1000000+86400)[2])
            self.assertEqual(restored['player'],[321,435])
            self.assertEqual(restored['seeds']['suika'],0)
            self.assertEqual(harvest(restored,0,1000000+86400),'suika')
            save_state(restored,file)
            self.assertEqual(load_json(file)['warehouse']['suika'],1)

    def test_backup_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'save.json'
            s=new_state(200)
            save_state(s,path)
            plant(s,0,'kaiware',200)
            save_state(s,path)
            self.assertTrue(path.with_suffix('.bak.json').exists())
            path.write_text('bad')
            s2,msg=load_state(path)
            self.assertIsNone(s2['plots'][0])
            self.assertIn('バックアップ',msg)

    def test_invalid_save_protection(self):
        s=new_state(10)
        s['plots'][0]={'crop':'tomato','planted_at':float('nan')}
        with self.assertRaises(SaveError):validate_state(s)
        s=new_state(10)
        s['coins']=-1
        with self.assertRaises(SaveError):validate_state(s)

    def test_v1_migration(self):
        v1={'version':1,'created_at':1000,'plots':[None]*24,'warehouse':{},
            'harvest_total':5,'history':[{'crop':'radish','at':1400}], 'selected_crop':'radish'}
        v1['plots'][3]={'crop':'kin_ringo','planted_at':1234}
        converted=validate_state(v1)
        self.assertEqual(converted['version'],2)
        self.assertEqual(converted['plots'][3],v1['plots'][3])
        self.assertEqual(converted['harvest_total'],5)
        self.assertEqual(converted['stats']['harvested'],5)
        self.assertEqual(converted['selected_crop'],'radish')
        self.assertGreater(converted['coins'],0)
        self.assertEqual(converted['harvested_types']['radish'],1)

    def test_clock(self):
        s=new_state(10000)
        self.assertEqual(clock_at(s,10000),(1,6,0))
        self.assertEqual(clock_at(s,10020),(1,6,1))
        self.assertEqual(clock_at(s,10000+28800),(2,6,0))

    def test_unicode_json(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.json'
            s=new_state(100)
            save_state(s,path)
            self.assertIn('"seeds"',path.read_text('utf-8'))
            self.assertEqual(load_json(path)['created_at'],100.)

if __name__=='__main__':unittest.main(verbosity=2)
