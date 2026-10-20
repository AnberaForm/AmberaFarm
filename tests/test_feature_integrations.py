# -*- coding: utf-8 -*-
import hashlib
import io
import json
import socket
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from farm_core import CROPS, new_state, progress_for,validate_state,save_state,load_json
from story_editor import save_events, validate_event
from story_engine import available_story,load_story,finish_story
from world_map import (TILE,BUILDINGS,INTERACTION_POINTS,TREE_POSITIONS,
                       fence_at,water_at,can_stand,blocked,plot_world,test_reachability as walkable_targets)
from multiplayer import RoomServer,RoomClient
from updater import inspect_package,apply_package,version_parts,ALLOWED

BASE=Path(__file__).resolve().parents[1]

class TestFeatures(unittest.TestCase):
    def test_walkable_map(self):
        self.assertFalse(walkable_targets(),walkable_targets())
        for b in BUILDINGS:
            x,y,w,h=b.bounds()
            self.assertTrue(blocked(x+w/2,y+h/2))
            self.assertTrue(can_stand(*b.door()),b)
        self.assertTrue(fence_at(8,10))
        self.assertFalse(fence_at(12,20))
        self.assertFalse(fence_at(19,14))
        self.assertTrue(water_at(8,29))
        self.assertTrue(can_stand(*INTERACTION_POINTS['fishing']))

    def test_all_crop_times(self):
        for crop in CROPS:
            plot={'crop':crop.id,'planted_at':1_000.0}
            self.assertFalse(progress_for(plot,1_000+crop.grow_seconds-1)[2])
            self.assertTrue(progress_for(plot,1_000+crop.grow_seconds)[2])
        self.assertEqual(next(c for c in CROPS if c.id=='kaiware').grow_seconds,600)

    def test_story_editor_save_and_triggers(self):
        nodes=load_story(BASE/'data/story_events.json')
        state=new_state()
        self.assertEqual(available_story(nodes,state,'guide')['id'],'guide_first')
        self.assertEqual(available_story(nodes,state,'nagi')['id'],'intro_lake')
        finish_story(state,'intro_lake')
        self.assertIsNone(available_story(nodes,state,'nagi'))
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'story.json'
            for n in nodes:validate_event(n)
            save_events(nodes,f)
            self.assertEqual(json.loads(f.read_text(encoding='utf-8')),nodes)
            save_events(nodes,f)
            self.assertTrue(f.with_suffix('.backup.json').exists())

    def test_update_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:
                z.writestr('ambera_farm.py','VERSION = 9\n')
                z.writestr('world_map.py','LOCATION = 10\n')
            raw=data.getvalue()
            count=apply_package(raw,hashlib.sha256(raw).hexdigest(),root,'1.2.3')
            self.assertEqual(count,3)
            self.assertEqual((root/'version.json').read_text(encoding='utf-8'),json.dumps({'version':'1.2.3'}))
            self.assertEqual((root/'world_map.py').read_text(),'LOCATION = 10\n')
            malicious=io.BytesIO()
            with zipfile.ZipFile(malicious,'w') as z:z.writestr('../steal.json','bad')
            with self.assertRaises(ValueError):inspect_package(malicious.getvalue())
            with self.assertRaises(ValueError):apply_package(raw,'0'*64,root,'1.2.4')

    def test_network_shared_farm(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=new_state()
            room=RoomServer(state,Path(tmp)/'host_save.json',port=0,pin='234567')
            c1=c2=None
            try:
                host='127.0.0.1:'+str(room.port)
                with self.assertRaises(ConnectionError):RoomClient(host,'wrong','Guest')
                c1=RoomClient(host,'234567','PlayerA',profile=state,host_token=room.host_token)
                c2=RoomClient(host,'234567','PlayerB')
                self.assertTrue(c1.active and c2.active)
                deadline=time.monotonic()+3
                received=False
                while time.monotonic()<deadline:
                    received=any(m.get('type')=='snapshot' for m in c1.poll())
                    if received:break
                    time.sleep(.05)
                self.assertTrue(received,'Expected snapshot from host')
                # Starting player (336,352) is close to first plot (272,400), distance=80;
                # server must REJECT purchases from far away and unauthorized plot action.
                c1.action('buy',['kaiware',1]);time.sleep(.2)
                with room.lock:self.assertEqual(room.state['seeds']['kaiware'],4)
                c1.action('plot',{'index':0,'crop':'kaiware'});time.sleep(.2)
                with room.lock:self.assertIsNone(room.state['plots'][0])
                # Move near the first plot in a few realistic steps.
                with room.lock:
                    room.players[c1.id].update(x=272,y=414,last=time.monotonic())
                c1.action('plot',{'index':0,'crop':'kaiware'})
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    with room.lock:
                        if room.state['plots'][0] is not None:break
                    time.sleep(.05)
                with room.lock:self.assertIsNotNone(room.state['plots'][0]);self.assertEqual(room.state['seeds']['kaiware'],3)
                self.assertTrue((Path(tmp)/'host_save.json').exists())
            finally:
                for c in (c1,c2):
                    if c:c.close()
                room.close()

if __name__=='__main__':unittest.main()
