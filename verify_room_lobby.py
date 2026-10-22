# -*- coding: utf-8 -*-
"""Real sockets: directory, admission, room-owned saves and request UI."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from farm_core import new_state, SaveError
from v8_features import init_v8
from multiplayer import RoomClient, RoomServer, PROTOCOL
from online_rooms import (RelayHost, RelayError, search_rooms, request_admission,
                          connect_guest, _websocket, _reply, _abort)
from room_saves import load_room, member_key, local_room_identity
from verify_online_rooms import RunningRelay, wait_for


class LobbyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.running=RunningRelay()

    @classmethod
    def tearDownClass(cls):cls.running.close()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ambera_lobby_test_')
        self.resources=[]
        self.clients=[]
        self.sockets=[]
        self.running.relay.request_timeout=180

    def tearDown(self):
        for ws in self.sockets:_abort(ws)
        for client in self.clients:client.close()
        for resource in reversed(self.resources):resource.close()
        self.assertTrue(wait_for(lambda:not self.running.relay.rooms))
        self.temp.cleanup()

    def room(self,title='まってぃの牧場',name='まってぃ',public=True,path=None):
        state=init_v8(new_state());state['coins']=999999;state['warehouse']['kabu']=99
        path=path or Path(self.temp.name)/(secrets.token_hex(4)+'.json')
        server=RoomServer(state,path,port=0,bind='127.0.0.1',room_owned=True)
        self.resources.append(server)
        host=RoomClient(f'127.0.0.1:{server.port}',server.pin,name,profile=state,
                        host_token=server.host_token)
        self.clients.append(host)
        relay=RelayHost(self.running.endpoint,server.port,server.pin,PROTOCOL,
                        title=title,name=name,public=public)
        self.resources.append(relay)
        return server,host,relay

    def request(self,relay,name='ゲスト'):
        ws=_websocket(self.running.endpoint)
        self.sockets.append(ws)
        ws.send(json.dumps({'op':'request','version':1,'protocol':PROTOCOL,'code':relay.code,'name':name}))
        pending=_reply(ws)
        self.assertEqual(pending['type'],'pending')
        self.assertTrue(wait_for(lambda:any(r['id']==pending['id'] for r in relay.pending_requests())))
        return ws,pending['id']

    def approved(self,relay,name='ゲスト'):
        ws,ident=self.request(relay,name)
        self.assertTrue(relay.decide(ident,True))
        reply=_reply(ws)
        self.assertEqual(reply['type'],'approved')
        return reply

    def guest(self,relay,approval=None,identity=None,profile=None):
        transport=connect_guest(self.running.endpoint,relay.code,relay.pin,PROTOCOL,
                                approval=approval)
        guest=RoomClient('relay',relay.pin,'ゲスト',connection=transport,
                         identity=identity,profile=profile)
        self.clients.append(guest)
        return guest

    def snapshot(self,client):
        packets=[]
        def received():
            packets.extend(p for p in client.poll() if p.get('type')=='snapshot')
            return bool(packets)
        self.assertTrue(wait_for(received))
        return packets[-1]

    def test_search_matches_room_and_host_without_exposing_secrets(self):
        _,_,public=self.room(title='ＡＢＣの畑',name='たろう')
        self.room(title='秘密の畑',public=False)
        rows=search_rooms(self.running.endpoint,'abc',PROTOCOL)
        self.assertEqual([r['id'] for r in rows],[public.code])
        self.assertEqual(search_rooms(self.running.endpoint,'たろう',PROTOCOL),rows)
        self.assertEqual(search_rooms(self.running.endpoint,'',PROTOCOL-1),[])
        self.assertEqual(set(rows[0]),{'id','title','host','players','max_players'})
        self.assertNotIn(public.pin,json.dumps(rows))
        self.assertNotIn(public.key,json.dumps(rows))

    def test_approval_is_required_and_one_use_even_with_correct_invitation(self):
        server,host,relay=self.room()
        with self.assertRaises(RelayError) as error:self.guest(relay)
        self.assertEqual(error.exception.code,'approval_required')
        grant=self.approved(relay)
        forged=init_v8(new_state());forged['coins']=500000;forged['warehouse']['kabu']=500
        guest=self.guest(relay,grant['approval'],profile=forged)
        data=self.snapshot(guest)['state']
        self.assertEqual(data['coins'],200)
        self.assertEqual(data['warehouse']['kabu'],0)
        self.assertNotEqual(data['player_uid'],forged['player_uid'])
        self.assertEqual(self.snapshot(host)['state']['coins'],200)
        with self.assertRaises(RelayError):self.guest(relay,grant['approval'])
        self.assertEqual(search_rooms(self.running.endpoint,'',PROTOCOL)[0]['players'],2)

    def test_rejection_is_delivered_and_request_disappears(self):
        _,_,relay=self.room()
        ws,ident=self.request(relay)
        relay.decide(ident,False)
        with self.assertRaises(RelayError) as error:_reply(ws)
        self.assertEqual(error.exception.code,'rejected')
        self.assertTrue(wait_for(lambda:not relay.pending_requests()))

    def test_cancellation_withdraws_request_without_host_decision(self):
        from online_rooms import withdraw_request
        _,_,relay=self.room()
        for cancel in (withdraw_request, _abort):
            ws,_=self.request(relay)
            cancel(ws)
            self.assertTrue(wait_for(lambda:not relay.pending_requests()))

    def test_closed_host_notifies_waiting_guest(self):
        _,_,relay=self.room()
        ws,_=self.request(relay)
        relay.close()
        with self.assertRaises(RelayError) as error:_reply(ws)
        self.assertEqual(error.exception.code,'host_left')

    def test_timeout_removes_request_and_can_apply_again(self):
        self.running.relay.request_timeout=.15
        _,_,relay=self.room()
        ws,_=self.request(relay)
        with self.assertRaises(RelayError) as error:_reply(ws)
        self.assertEqual(error.exception.code,'request_timeout')
        self.assertTrue(wait_for(lambda:not relay.pending_requests()))
        self.running.relay.request_timeout=180
        ws,_=self.request(relay)
        _abort(ws)

    def test_only_authenticated_host_can_approve(self):
        _,_,relay=self.room()
        waiting,ident=self.request(relay)
        outsider=_websocket(self.running.endpoint);self.sockets.append(outsider)
        outsider.send(json.dumps({'op':'decide','version':1,'id':ident,'accept':True}))
        with self.assertRaises(RelayError):_reply(outsider)
        self.assertEqual(relay.pending_requests()[0]['id'],ident)
        relay.decide(ident,False)
        with self.assertRaises(RelayError):_reply(waiting)

    def test_approval_expiry_and_capacity_reservations(self):
        _,_,relay=self.room()
        grant=self.approved(relay)
        self.running.relay.rooms[relay.code].approvals[grant['approval']]=0
        with self.assertRaises(RelayError):self.guest(relay,grant['approval'])
        for _ in range(7):self.approved(relay)
        ws=_websocket(self.running.endpoint);self.sockets.append(ws)
        ws.send(json.dumps({'op':'request','version':1,'protocol':PROTOCOL,'code':relay.code,'name':'満員'}))
        with self.assertRaises(RelayError) as error:_reply(ws)
        self.assertEqual(error.exception.code,'full')

    def test_identity_resumes_only_that_hosts_farm_and_public_uid_cannot_claim_it(self):
        path=Path(self.temp.name)/'persistent.json'
        server,_,relay=self.room(public=False,path=path)
        identity=secrets.token_hex(32)
        guest=self.guest(relay,identity=identity)
        first=self.snapshot(guest)['state']
        with server.lock:
            server.players[guest.id]['profile']['coins']=321
            server._save_host()
        guest.close()
        self.assertTrue(wait_for(lambda:guest.id not in server.players))
        forged=copy.deepcopy(first);forged['coins']=888888
        other=self.guest(relay,profile=forged)
        self.assertEqual(self.snapshot(other)['state']['coins'],200)
        again=self.guest(relay,identity=identity,profile=forged)
        self.assertEqual(self.snapshot(again)['state']['coins'],321)
        self.room(title='別の牧場',public=False)
        other_relay=self.resources[-1]
        fresh=self.guest(other_relay,identity=identity,profile=forged)
        self.assertEqual(self.snapshot(fresh)['state']['coins'],200)
        loaded,members=load_room(path)
        self.assertEqual(members[member_key(identity)]['coins'],321)
        self.assertEqual(loaded['coins'],200)
        reopened=RoomServer(new_state(),path,port=0,bind='127.0.0.1',room_owned=True)
        self.resources.append(reopened)
        self.assertEqual(reopened.members[member_key(identity)]['coins'],321)

    def test_corrupt_room_is_preserved_and_reopen_uses_server_saved_progress(self):
        path=Path(self.temp.name)/'farm.json'
        server,_,relay=self.room(public=False,path=path)
        with server.lock:
            server.host_profile['coins']=317
            server._save_host()
        state,members=load_room(path)
        self.assertEqual(state['coins'],317)
        path.write_bytes(b'broken room')
        with self.assertRaises(SaveError):load_room(path)
        self.assertEqual(path.read_bytes(),b'broken room')
        # Avoid overwriting the intentional corrupt fixture during teardown.
        server.save_file=Path(self.temp.name)/'after-test.json'

    def test_friend_requests_have_sent_pending_accept_and_reject_states(self):
        server,host,relay=self.room(public=False)
        guest=self.guest(relay)
        self.snapshot(guest)
        guest.action('friend_request',host.id)
        self.assertTrue(wait_for(lambda:guest.id in server.friend_invites.get(host.id,[])))
        host.action('friend_reject',guest.id)
        self.assertTrue(wait_for(lambda:guest.id not in server.friend_invites.get(host.id,[])))
        guest.action('friend_request',host.id)
        self.assertTrue(wait_for(lambda:guest.id in server.friend_invites.get(host.id,[])))
        host.action('friend_accept',guest.id)
        self.assertTrue(wait_for(lambda:server.players[guest.id]['uid'] in server.host_profile['friend_ids']))

    def test_real_pygame_search_request_approval_and_return_preserve_local_save(self):
        from ambera_farm import Game,pygame
        from save_slots import load_slot
        server,_,relay=self.room()
        with patch.dict(os.environ,{'APPDATA':self.temp.name,'SDL_VIDEODRIVER':'dummy','SDL_AUDIODRIVER':'dummy'}), \
             patch.object(Game,'fetch_mails',lambda self:None), \
             patch.object(Game,'refresh_notices',lambda self,force=False:None):
            game=Game()
            try:
                game.state['coins']=8765
                game.persist(True)
                original=game.save_file.read_bytes()
                game.internet_fields['address']=self.running.endpoint
                game.open_room_browser()
                def listed():
                    game.update_gameplay(.01)
                    return game.directory_job is None and bool(game.directory_rows)
                self.assertTrue(wait_for(listed))
                game.render()
                game.request_room_entry(relay.code)
                self.assertTrue(wait_for(lambda:bool(relay.pending_requests())))
                game.render()
                relay.decide(relay.pending_requests()[0]['id'],True)
                def entered():
                    game.update_gameplay(.01)
                    return game.online_profile_received
                self.assertTrue(wait_for(entered))
                self.assertEqual(game.state['coins'],200)
                game.modal='requests';game.render()
                game.stop_online()
                self.assertEqual(game.state['coins'],8765)
                self.assertEqual(game.save_file.read_bytes(),original)
            finally:
                if game.online_job:game.online_job.cancel()
                if game.online_client:game.stop_online()
                pygame.quit()


if __name__=='__main__':unittest.main()
