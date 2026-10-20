# -*- coding: utf-8 -*-
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from farm_core import (new_state,load_state,save_state,validate_state,mission_progress,claim_mission,
                       plant,CROPS,progress_for)
from fishing_core import FISH,FISH_BY_ID, FishingRound,roll_fish,add_catch,sell_fish
from story_engine import load_story,available_story,finish_story

class FishingStoryTests(unittest.TestCase):
    def test_fish_ids_and_difficulty(self):
        self.assertEqual(len(FISH),8)
        self.assertEqual(len({f.id for f in FISH}),8)
        self.assertEqual(FISH_BY_ID['medaka'].difficulty,1)
        self.assertEqual(FISH_BY_ID['gold_koi'].difficulty,5)
        self.assertGreater(FISH_BY_ID['gold_koi'].price,FISH_BY_ID['medaka'].price)
        self.assertTrue(all(roll_fish(random.Random(i)).id in FISH_BY_ID for i in range(100)))

    def test_fishing_skill_and_failure(self):
        easy=FishingRound('medaka')
        for i in range(500):
            easy.bobber_y=easy.fish_y
            easy.step(.1,reeling=True)
            if easy.result:break
        self.assertEqual(easy.result,'caught')
        self.assertGreater(easy.remaining,0)
        hard=FishingRound('gold_koi')
        for i in range(370):
            hard.step(.1,direction=0,reeling=False)
        self.assertEqual(hard.result,'escaped')
        self.assertEqual(hard.progress,0)

    def test_tension_break(self):
        hard=FishingRound('gold_koi', fish_y=.07,fish_direction=-1,bobber_y=.97)
        for i in range(200):
            hard.bobber_y=.97 if hard.fish_y<.5 else .02
            hard.step(.1,reeling=True)
            if hard.result:break
        self.assertEqual(hard.result,'escaped')
        self.assertGreaterEqual(hard.tension,99.5)

    def test_catch_sell_and_missions(self):
        s=new_state(1000)
        self.assertTrue(add_catch(s,'medaka'))
        self.assertTrue(add_catch(s,'funa'))
        self.assertTrue(add_catch(s,'koi'))
        self.assertEqual(s['fish_inventory']['medaka'],1)
        self.assertEqual(s['stats']['fish_caught'],3)
        self.assertEqual(mission_progress(s,'fishvariety'),(3,3))
        self.assertTrue(claim_mission(s,'fishvariety'))
        self.assertFalse(claim_mission(s,'fishvariety'))
        balance=s['coins']
        self.assertFalse(sell_fish(s,'medaka',2))
        self.assertTrue(sell_fish(s,'medaka',1))
        self.assertEqual(s['coins'],balance+FISH_BY_ID['medaka'].price)
        self.assertEqual(s['stats']['fish_sold'],1)
        self.assertFalse(sell_fish(s,'medaka',1))
        self.assertFalse(add_catch(s,'bad_fish'))

    def test_old_v2_save_is_migrated_without_loss(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'save.json'
            old=new_state(1200)
            self.assertTrue(plant(old,0,'kaiware',1200))
            old['coins']=987
            old['player']=[482.,993.]
            for key in ('fish_inventory','fish_caught_types','story_flags'):old.pop(key)
            for key in ('fish_caught','fish_sold'):old['stats'].pop(key)
            file.write_text(json.dumps(old,ensure_ascii=False),'utf-8')
            newer,_=load_state(file,1300)
            self.assertEqual(newer['coins'],987)
            self.assertEqual(newer['player'],[482,993])
            self.assertEqual(newer['plots'][0]['crop'],'kaiware')
            self.assertIn('medaka',newer['fish_inventory'])
            self.assertEqual(newer['stats']['fish_caught'],0)
            add_catch(newer,'koi')
            finish_story(newer,'intro_lake')
            save_state(newer,file)
            reloaded,_=load_state(file)
            self.assertEqual(reloaded['fish_inventory']['koi'],1)
            self.assertEqual(reloaded['story_flags'],['intro_lake'])
            self.assertEqual(reloaded['coins'],987)

    def test_story_json_and_progression(self):
        path=Path(__file__).resolve().parents[1]/'data'/'story_events.json'
        nodes=load_story(path)
        s=new_state(99)
        self.assertEqual(available_story(nodes,s)['id'],'intro_lake')
        self.assertTrue(finish_story(s,'intro_lake'))
        self.assertFalse(finish_story(s,'intro_lake'))
        self.assertIsNone(available_story(nodes,s))
        add_catch(s,'medaka')
        self.assertEqual(available_story(nodes,s)['id'],'first_catch')
        finish_story(s,'first_catch')
        self.assertIsNone(available_story(nodes,s))

if __name__=='__main__':unittest.main(verbosity=2)
