# -*- coding: utf-8 -*-
import copy
from pathlib import Path
import tempfile
import time
import unittest

from farm_core import new_state, load_json, progress_for, harvest
from multiplayer import RoomServer, RoomClient, merged_view, safe_chat
from player_movement import move_character, safe_destination
from story_admin_auth import validate_admin
from world_map import can_stand, BUILDINGS


def wait_until(pred, timeout=3):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if pred():
            return True
        time.sleep(.025)
    return False


class FeatureV06Tests(unittest.TestCase):
    def test_admin_login(self):
        self.assertTrue(validate_admin('admin', 'pass123'))
        self.assertFalse(validate_admin('admin', 'wrong'))
        self.assertFalse(validate_admin('ADMIN', 'pass123'))
        self.assertFalse(validate_admin(0, 'pass123'))

    def test_chat_input_limit(self):
        self.assertEqual(safe_chat('  こんにちは\nみんな  '), 'こんにちはみんな')
        self.assertEqual(len(safe_chat('X' * 1000)), 160)
        self.assertEqual(safe_chat({}), '')

    def test_movement_no_tunneling_and_rescue(self):
        # Old game spawned overlapping a fence and could get stuck.
        self.assertFalse(can_stand(336, 352))
        start = safe_destination()
        self.assertEqual(start, [336.0, 368.0])
        self.assertTrue(can_stand(*start))
        self.assertEqual(move_character(start, (0, 0), .04), start)
        diagonal = move_character(start, (1, 1), 0.04)
        self.assertTrue(can_stand(*diagonal))
        # Collision against home building: cannot pass through at high speed.
        building = BUILDINGS[0]
        x, y, w, h = building.bounds()
        before = [x + w / 2, y + h + 12]
        self.assertTrue(can_stand(*before))
        blocked = move_character(before, (0, -1), 0.5, speed=1500)
        self.assertTrue(can_stand(*blocked))
        self.assertGreaterEqual(blocked[1], y + h)

    def test_distinct_wallet_inventory_and_shared_plots(self):
        with tempfile.TemporaryDirectory() as td:
            host = new_state()
            guest = new_state()
            guest['coins'] = 900
            guest['seeds']['kaiware'] = 7
            guest['warehouse']['tomato'] = 3
            room = RoomServer(host, Path(td)/'host_save.json', port=0, pin='246810')
            a = b = None
            try:
                address = f'127.0.0.1:{room.port}'
                a = RoomClient(address, room.pin, 'Host', profile=host, host_token=room.host_token)
                b = RoomClient(address, room.pin, 'Guest', profile=guest)
                self.assertTrue(wait_until(lambda: len(room.players) == 2))
                with room.lock:
                    room.players[b.id].update(x=272, y=414, last=time.monotonic())
                b.action('plot', {'index': 0, 'crop': 'kaiware'})
                self.assertTrue(wait_until(lambda: room.state['plots'][0] is not None))
                with room.lock:
                    self.assertEqual(room.players[b.id]['profile']['seeds']['kaiware'], 6)
                    self.assertEqual(room.players[a.id]['profile']['seeds']['kaiware'], 4)
                    self.assertEqual(room.players[b.id]['profile']['coins'], 900)
                    self.assertEqual(room.players[a.id]['profile']['coins'], 200)
                    self.assertEqual(room.players[b.id]['profile']['warehouse']['tomato'], 3)
                    self.assertEqual(room.players[a.id]['profile']['warehouse']['tomato'], 0)
                # Public snapshots: world is identical; profile is different.
                with room.lock:
                    host_view = merged_view(room.players[a.id]['profile'], room.state['plots'])
                    guest_view = merged_view(room.players[b.id]['profile'], room.state['plots'])
                self.assertEqual(host_view['plots'], guest_view['plots'])
                self.assertNotEqual(host_view['coins'], guest_view['coins'])
                self.assertNotEqual(host_view['seeds'], guest_view['seeds'])
                self.assertNotEqual(host_view['warehouse'], guest_view['warehouse'])
                # Guest purchasing cannot take cash from host.
                with room.lock:
                    room.players[b.id].update(x=40.5*32, y=13.65*32, last=time.monotonic())
                b.action('buy', ['radish', 1])
                self.assertTrue(wait_until(lambda: room.players[b.id]['profile']['coins'] == 884))
                with room.lock:
                    self.assertEqual(room.players[a.id]['profile']['coins'], 200)
                self.assertEqual(load_json(room.save_file)['coins'], 200)
                # Server chat gets broadcast in the same room only.
                b.chat('こんにちは 牧場！')
                self.assertTrue(wait_until(lambda: bool(room.chat_log)))
                self.assertEqual(room.chat_log[-1]['name'], 'Guest')
                self.assertEqual(room.chat_log[-1]['text'], 'こんにちは 牧場！')
                self.assertTrue(wait_until(lambda: any(m.get('type') == 'snapshot' and
                                    m.get('chat') for m in a.poll())))
                # Rescue requires a host-approved teleport.
                with room.lock:
                    room.players[b.id].update(x=1000, y=1000)
                b.action('rescue', None)
                self.assertTrue(wait_until(lambda: tuple(room.players[b.id]['x'] for _ in range(1)) == (336.0,)))
                with room.lock:
                    self.assertTrue(can_stand(room.players[b.id]['x'], room.players[b.id]['y']))
            finally:
                if a:a.close()
                if b:b.close()
                room.close()


if __name__ == '__main__':
    unittest.main()
