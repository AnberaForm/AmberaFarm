# -*- coding: utf-8 -*-
"""アンベラ牧場 — 遊べる Pygame 初版。オフライン動作。"""
from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import sys
import time
import json
import math
import random
from array import array
import traceback
import zipfile
import copy
import subprocess
import socket
import threading
from queue import Queue, Empty
import webbrowser

try:
    import pygame
except ImportError:
    print('Pygame が必要です。Windows では「アンベラ牧場を起動.bat」を実行してください。')
    print('手動インストール: py -3 -m pip install pygame-ce==2.5.8')
    raise SystemExit(1)

from farm_core import (
    CROPS, CROP_BY_ID, PLOT_COLUMNS, PLOT_COUNT, PLOT_ROWS,
    MISSIONS, MISSION_BY_ID, STARTING_COINS,
    SaveError, clock_at, duration_text, harvest, load_json, load_state,
    plant, progress_for, save_state, state_path, time_short,
    buy_seeds, sell_crops, claim_mission, mission_progress, new_state,
)
from fishing_core import FISH, FISH_BY_ID, FishingRound, roll_fish, add_catch, sell_fish
from story_engine import load_story, available_story, finish_story
from world_map import BUILDINGS, TREE_POSITIONS, INTERACTION_POINTS, fence_at, blocked as map_blocked, can_stand, plot_world as map_plot_world
from multiplayer import RoomServer, RoomClient, PORT
from player_movement import move_character, safe_destination
from updater import current_version, get_config, fetch_manifest
from notices import (load_offline, fetch_public, load_seen, mark_seen,
                     public_view, unread_count, RELEASES_URL)

BASE_W, BASE_H = 1280, 720
ROOT = Path(__file__).resolve().parent
EXTERNAL_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
                 else ROOT)

# カラーパレットは参考画面を入手していないため、初版用の仮デザイン。
INK = (53, 53, 37)
DARK = (29, 47, 37)
DARK_2 = (44, 68, 47)
CREAM = (239, 226, 180)
PAPER = (250, 241, 204)
PARCHMENT = (231, 214, 162)
PALE = (249, 247, 217)
GREEN = (103, 156, 91)
GREEN_DARK = (65, 102, 59)
GREEN_LIGHT = (148, 181, 102)
BROWN = (108, 67, 43)
SOIL = (123, 80, 55)
SOIL_LIGHT = (155, 104, 67)
GOLD = (232, 171, 63)
GOLD_LIGHT = (248, 209, 96)
WHITE = (255, 251, 233)
RED = (157, 65, 49)


def font_file() -> str | None:
    preferred = [
        r'C:\Windows\Fonts\meiryo.ttc',
        r'C:\Windows\Fonts\msgothic.ttc',
        r'C:\Windows\Fonts\YuGothM.ttc',
        r'C:\Windows\Fonts\YuGothR.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
        '/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc',
    ]
    for candidate in preferred:
        if Path(candidate).is_file():
            return candidate
    for name in ('meiryo', 'msgothic', 'yugothic', 'noto sans cjk jp', 'hiraginosans'):
        match = pygame.font.match_font(name)
        if match:
            return match
    return None


class Fonts:
    def __init__(self):
        self.path = font_file()
        self.cache = {}

    def get(self, size: int, bold: bool = False):
        key = (size, bold)
        if key not in self.cache:
            font = pygame.font.Font(self.path, size)
            font.set_bold(bold)
            self.cache[key] = font
        return self.cache[key]


def text(surface, fonts, words, pos, size=18, color=INK, bold=False, centered=False, max_width=None):
    font = fonts.get(size, bold)
    result = font.render(str(words), True, color)
    if max_width and result.get_width() > max_width:
        # フォントサイズだけ落とすことで極端に長い表記を収める。
        while size > 10 and result.get_width() > max_width:
            size -= 1
            result = fonts.get(size, bold).render(str(words), True, color)
    rect = result.get_rect()
    if centered:
        rect.center = pos
    else:
        rect.topleft = pos
    surface.blit(result, rect)
    return rect


def box(surface, rect, fill, border=None, radius=0, thick=3):
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surface, border, rect, thick, border_radius=radius)


def bar(surface, rect, fraction, fill, border):
    box(surface, rect, (84, 69, 48), border, radius=3, thick=2)
    inner_width = int(max(0, rect.w - 6) * min(1, max(0, fraction)))
    if inner_width:
        pygame.draw.rect(surface, fill, (rect.x + 3, rect.y + 3, inner_width, rect.h - 6), border_radius=1)


def button(surface, fonts, rect, label, mouse, selected=False, disabled=False, size=16):
    hot = rect.collidepoint(mouse)
    face = GREEN_LIGHT if selected else (PARCHMENT if hot else CREAM)
    if disabled:
        face = (195, 187, 158)
    box(surface, rect, face, GOLD if selected else BROWN, 7, 3)
    text(surface, fonts, label, rect.center, size, INK, bold=True, centered=True, max_width=rect.w - 14)
    return hot


class Assets:
    """元ZIPのPNG bytesをデコードするのみ。加工・保存・書換はしない。"""
    def __init__(self):
        self.images = {}
        self.scaled = {}
        self.source = ''
        self.last_error = ''
        self.find_default()

    @staticmethod
    def zip_members(file: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(file) as z:
            members = {}
            for member in z.infolist():
                if not member.is_dir() and member.filename.lower().endswith('.png'):
                    if member.file_size > 12 * 1024 * 1024:
                        continue
                    members.setdefault(Path(member.filename.replace('\\', '/')).name.lower(), member)
            blobs = {c.id:z.read(members[c.filename.lower()]) for c in CROPS
                     if c.filename.lower() in members}
            if not blobs:
                raise ValueError('このZIPに作物のPNGが見つかりません。')
            return blobs

    def _install_data(self, blobs, label):
        loaded = dict(self.images)
        for crop in CROPS:
            if crop.id not in blobs:
                continue
            raw = blobs[crop.id]
            image = pygame.image.load(io.BytesIO(raw), crop.filename).convert_alpha()
            if image.get_width() <= 0 or image.get_height() <= 0:
                raise ValueError('PNGの大きさが不正です')
            loaded[crop.id] = image
        self.images = loaded
        self.scaled.clear()
        self.source = label
        self.last_error = ''

    def import_zip(self, file: Path, remember=True):
        blobs = self.zip_members(file)
        self._install_data(blobs, file.name)
        if remember:
            dest = state_path().parent / 'original_assets.zip'
            dest.parent.mkdir(parents=True, exist_ok=True)
            if file.resolve() != dest.resolve():
                shutil.copyfile(file, dest)

    def find_default(self):
        folders = (ROOT / 'assets' / 'crops', EXTERNAL_ROOT / 'assets' / 'crops', ROOT / 'crops')
        for folder in folders:
            try:
                blobs = {c.id:(folder / c.filename).read_bytes()
                         for c in CROPS if (folder / c.filename).is_file()}
                if blobs:
                    self._install_data(blobs, str(folder))
            except (OSError, pygame.error, ValueError) as exc:
                self.last_error = str(exc)
        zips = [state_path().parent / 'original_assets.zip',
                ROOT / 'アンベラ牧場 (1).zip', ROOT / 'アンベラ牧場.zip',
                ROOT / 'original_assets.zip',
                EXTERNAL_ROOT / 'アンベラ牧場 (1).zip', EXTERNAL_ROOT / 'original_assets.zip']
        zips.extend(sorted(EXTERNAL_ROOT.glob('*.zip')))
        for candidate in dict.fromkeys(zips):
            if candidate.is_file():
                try:
                    self.import_zip(candidate, remember=False)
                except (OSError, pygame.error, ValueError, zipfile.BadZipFile) as exc:
                    self.last_error = f'{candidate.name}: {exc}'

    def draw_crop(self, surface, crop_id, target):
        area = pygame.Rect(target)
        image = self.images.get(crop_id)
        if image:
            ow, oh = image.get_size()
            scale = min(area.w / ow, area.h / oh)
            newsize = (max(1, round(ow * scale)), max(1, round(oh * scale)))
            # ピクセルを補間しない（ドット絵を保つ）。元PNGは変更しない。
            cache_key = (crop_id, newsize)
            resized = self.scaled.get(cache_key)
            if resized is None:
                resized = pygame.transform.scale(image, newsize)
                if len(self.scaled) > 512:
                    self.scaled.clear()
                self.scaled[cache_key] = resized
            surface.blit(resized, resized.get_rect(center=area.center))
            return
        # 元画像が読めない場合は代替の作物絵を描かず、空のアイコンを表示。
        pygame.draw.rect(surface, (90, 78, 62), area, border_radius=2)
        pygame.draw.rect(surface, (208, 189, 143), area, 2, border_radius=2)
        pygame.draw.line(surface, (206, 171, 127), area.topleft, area.bottomright, 2)


def choose_file(title, is_save=False, filetype='zip'):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        if filetype == 'zip':
            selected = filedialog.askopenfilename(title=title, filetypes=[('ZIPファイル', '*.zip')])
        elif is_save:
            selected = filedialog.asksaveasfilename(title=title, defaultextension='.json',
                initialfile='アンベラ牧場_セーブ.json', filetypes=[('JSONファイル', '*.json')])
        else:
            selected = filedialog.askopenfilename(title=title, filetypes=[('JSONファイル', '*.json')])
        root.destroy()
        return Path(selected) if selected else None
    except Exception as exc:
        raise RuntimeError(f'ファイル選択画面を開けません: {exc}') from exc



TILE = 32
WORLD_W, WORLD_H = 56, 36
VIEW_TOP, VIEW_HEIGHT = 70, 576
RESOLUTIONS = ((960, 540), (1280, 720), (1600, 900), (1920, 1080))
FARM_X, FARM_Y = 8, 12
SHOP_DOOR = INTERACTION_POINTS["shop"]
FISH_PIER = INTERACTION_POINTS["fishing"]
FISH_MARKET = INTERACTION_POINTS["fish_market"]
FISHERMAN = INTERACTION_POINTS["fisherman"]
SHIP_DOOR = INTERACTION_POINTS["shipping"]
BOARD_POS = INTERACTION_POINTS["missions"]
HOME_POS = INTERACTION_POINTS["home"]


def plot_world(index):
    return map_plot_world(index)


GUIDE_POS = (24.2 * TILE, 12.2 * TILE)
MERCHANT_POS = (35.5 * TILE, 15.5 * TILE)

def settings_file():
    return state_path().parent / 'settings.json'


def load_settings():
    initial = {'volume': 45, 'brightness': 100, 'resolution': 1, 'fullscreen': False}
    try:
        data = json.loads(settings_file().read_text(encoding='utf-8-sig'))
        if isinstance(data, dict):
            for k in initial:
                if k in data and type(data[k]) is type(initial[k]):
                    initial[k] = data[k]
    except (OSError, ValueError):
        pass
    initial['volume'] = max(0, min(100, initial['volume']))
    initial['brightness'] = max(50, min(130, initial['brightness']))
    initial['resolution'] = max(0, min(len(RESOLUTIONS)-1, initial['resolution']))
    return initial


def store_settings(settings):
    try:
        f = settings_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(f)
        return True
    except OSError:
        return False


class SoundBank:
    """Small generated 8-bit-style tunes, no audio files or network required."""
    def __init__(self, settings):
        self.sounds = {}
        self.music_channel = None
        self.available = False
        self.volume = settings['volume']
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=1024)
            self.available = True
            self.sounds = {
                'move': self.make([660], .075, .18),
                'buy': self.make([523, 784], .17, .27),
                'plant': self.make([330, 440], .18, .2),
                'harvest': self.make([523, 659, 784], .27, .30),
                'mission': self.make([440, 554, 659, 880], .48, .31),
            }
            melody = [262, 330, 392, 330, 294, 349, 440, 349,
                      262, 330, 392, 523, 440, 349, 330, 294]
            self.sounds['music'] = self.make(melody, 5.76, .11)
            self.music_channel = pygame.mixer.Channel(0)
            self.set_volume(settings['volume'])
            self.music_channel.play(self.sounds['music'], loops=-1)
        except (pygame.error, OSError, ValueError):
            self.available = False

    def make(self, notes, duration, strength):
        sample_rate = 22050
        length = int(sample_rate * duration)
        samples = array('h')
        for i in range(length):
            fraction = i / sample_rate / max(duration, .01)
            index = min(len(notes)-1, int(fraction * len(notes)))
            freq = notes[index]
            t = i / sample_rate
            # 2 harmonics, square-chip vibe, short soft envelope at each note edge.
            period_fraction = (t * freq) % 1
            square = 1.0 if period_fraction < .5 else -1.0
            phase = (fraction * len(notes)) % 1
            edge = min(1., phase * 25., (1. - phase) * 25.)
            value = int(32767 * strength * square * max(0., edge))
            samples.append(max(-32768, min(32767, value)))
        return pygame.mixer.Sound(buffer=samples.tobytes())

    def set_volume(self, amount):
        self.volume = amount
        if not self.available:return
        for name, sound in self.sounds.items():
            sound.set_volume((.25 if name=='music' else .7) * amount / 100)
        if self.music_channel:self.music_channel.set_volume(1)

    def play(self, name):
        if self.available and name in self.sounds:
            self.sounds[name].play()


class Game:
    def __init__(self):
        pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=1024)
        pygame.init()
        pygame.font.init()
        pygame.display.set_caption('アンベラ牧場  -  湖畔と釣りのアップデート')
        self.settings = load_settings()
        self.screen = None
        self.stage = pygame.Surface((BASE_W, BASE_H)).convert() if pygame.display.get_surface() else pygame.Surface((BASE_W, BASE_H))
        self.set_resolution()
        self.stage = pygame.Surface((BASE_W, BASE_H)).convert()
        self.world_layer = pygame.Surface((BASE_W, VIEW_HEIGHT)).convert()
        self.fonts = Fonts()
        self.assets = Assets()
        self.sound = SoundBank(self.settings)
        self.save_file = state_path()
        self.read_only = False
        self.load_warning = ''
        try:
            self.state, self.load_warning = load_state(self.save_file)
        except SaveError as exc:
            self.state = new_state()
            self.read_only = True
            self.load_warning = f'セーブの読み込み失敗（保存停止）: {exc}'
        self.selected = self.state['selected_crop']
        self.scene = 'title'
        self.modal = None
        self.prev_modal = None
        self.running = True
        self.buttons = []
        self.mouse = (0, 0)
        self.message = self.load_warning
        self.message_until = time.monotonic() + 12
        self.last_save_time = time.monotonic()
        self.title_sway = 0
        self.facing = 'down'
        self.player = list(self.state['player'])
        if not can_stand(*self.player):
            self.player=safe_destination()
            self.state['player'] = list(self.player)
        self.camera = [0., 0.]
        self.scroll = 0
        self.tree_positions = set(TREE_POSITIONS)
        self.online_server = None
        self.online_client = None
        self.online_guest = False
        self.offline_state = None
        self.remote_players = []
        self.room_pin = ''
        self.last_network_pos = 0
        self.join_fields = {'address':'127.0.0.1:47821','pin':'','name':'Player'}
        self.join_field = 'address'
        self.online_profile_received = False
        self.chat_log = []
        self.chat_last_seq = 0
        self.chat_text = ''
        self.held_keys = set()
        self.last_guest_save = time.monotonic()
        self.last_rescue = -100.
        self.update_status = ''
        self.mini_map = True
        self.fishing_round = None
        self.fishing_fish = None
        self.fishing_outcome = ''
        self.story_event = None
        self.story_line = 0
        self.mission_page = 0
        self.notice_feed = load_offline()
        self.notice_seen = load_seen()
        self.notice_page = 0
        self.notice_selection = ''
        self.notice_line_offset = 0
        self.notice_status = '前回取得したお知らせを表示中（ネット接続時に更新）'
        self.notice_queue = Queue()
        self.notice_busy = False
        self.notice_last_check = 0
        try:
            self.story_nodes = load_story(self.story_source())
        except (OSError, ValueError, UnicodeError) as exc:
            self.story_nodes = []
            self.say(f'物語データを読み込めません: {exc}', 8)
        self.refresh_notices()
        if not self.assets.images:
            self.say('元の画像を使用するには、ZIPをゲームフォルダへ置くか「画像ZIP」から指定してください。', 14)

    def refresh_notices(self, force=False):
        if self.notice_busy:
            return
        if not force and time.monotonic() - self.notice_last_check < 300:
            return
        self.notice_busy = True
        self.notice_last_check = time.monotonic()
        self.notice_status = 'お知らせを取得しています...'
        def worker():
            try:
                self.notice_queue.put(('ok', fetch_public()))
            except Exception as exc:
                self.notice_queue.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll_notices(self):
        try:
            while True:
                status, value = self.notice_queue.get_nowait()
                self.notice_busy = False
                if status == 'ok':
                    self.notice_feed = value
                    self.notice_status = '最新のお知らせを取得しました。'
                else:
                    self.notice_status = '通信できないため、前回のお知らせを表示しています。'
        except Empty:
            pass

    def read_notice(self, ident):
        if self.notice_selection != ident:
            self.notice_line_offset = 0
        self.notice_selection = ident
        try:
            self.notice_seen = mark_seen(ident, self.notice_seen)
        except (OSError, ValueError):
            self.say('既読情報を保存できませんでした。', 5)

    def open_notices(self):
        self.modal = 'notices'
        items = public_view(self.notice_feed)
        if items and self.notice_selection not in {n['id'] for n in items}:
            self.notice_selection = items[0]['id']
        if self.notice_selection:
            self.read_notice(self.notice_selection)
        self.refresh_notices()

    def wrap_notice(self, message, max_px, size=18, max_lines=13):
        font = self.fonts.get(size)
        output = []
        for raw_line in str(message).splitlines() or ['']:
            line = ''
            for ch in raw_line:
                if font.size(line + ch)[0] > max_px and line:
                    output.append(line)
                    line = ch
                else:
                    line += ch
            output.append(line)
            if len(output) >= max_lines:
                break
        return output[:max_lines]

    def story_source(self):
        user_path = state_path().parent / 'story_events.json'
        return user_path if user_path.is_file() else ROOT / 'data' / 'story_events.json'

    def reload_story(self):
        try:
            self.story_nodes = load_story(self.story_source())
        except (OSError, ValueError, UnicodeError) as exc:
            self.say(f'会話データの読込エラー: {exc}', 8)

    def open_admin(self):
        try:
            subprocess.Popen(([str(EXTERNAL_ROOT / 'AmberaStoryEditor.exe')] if getattr(sys, 'frozen', False)
                              else [sys.executable, str(ROOT / 'story_editor.py')]), cwd=str(EXTERNAL_ROOT))
            self.say('ストーリー管理画面を開きました。保存後、タイトルに戻って反映してください。', 10)
        except OSError as exc:self.say(f'管理画面を開けません: {exc}', 10)

    def check_updates(self):
        config = get_config()
        if not config.get('manifest_url'):
            self.say('更新先が未設定です。UPDATE_GUIDE.md を参照してください。', 10)
            return
        # Checking from the game is non-destructive. Updates are installed on NEXT startup.
        def work():
            try:
                info=fetch_manifest(config)
                self.update_status = (f'新バージョン {info["version"]} が公開されています。再起動で更新できます。'
                                     if info else '現在のバージョンが最新です。')
            except Exception as exc:self.update_status='更新確認エラー: '+str(exc)[:70]
        import threading
        threading.Thread(target=work,daemon=True).start()
        self.say('更新情報を確認しています。', 6)

    def lan_address(self):
        try:
            probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            try:
                probe.connect(('192.0.2.1', 9))
                return probe.getsockname()[0]
            finally:probe.close()
        except OSError:return 'ipconfig で確認'

    def start_room(self):
        if self.read_only:
            self.say('セーブ復元が必要です。破損セーブ保護中は部屋を開けません。',12);return
        if self.online_client:return
        try:
            self.online_server=RoomServer(self.state,self.save_file,port=PORT,story_nodes=self.story_nodes)
            self.room_pin=self.online_server.pin
            self.online_client=RoomClient('127.0.0.1:'+str(self.online_server.port),self.room_pin,'Host',profile=self.state,host_token=self.online_server.host_token)
            self.online_guest=False
            self.scene='world';self.modal=None
            self.say(f'部屋を作成！ LAN: {self.lan_address()}:{self.online_server.port} / PIN {self.room_pin}', 30)
        except (OSError,ValueError,ConnectionError) as exc:
            if self.online_server:
                self.online_server.close();self.online_server=None
            self.say(f'部屋の作成に失敗: {exc}',15)

    def join_room(self):
        if self.online_client:return
        try:
            self.offline_state=copy.deepcopy(self.state)
            self.online_client=RoomClient(self.join_fields['address'].strip(),self.join_fields['pin'],self.join_fields['name'],profile=self.state)
            self.online_guest=True
            self.player=list(self.online_client.spawn)
            self.room_pin=self.join_fields['pin']
            self.scene='world';self.modal=None
            self.say('オンライン参加！ 畑は共有、お金・所持品・ミッションは個人別です。 Tでチャット',11)
        except (OSError,ValueError,ConnectionError) as exc:
            self.online_client=None;self.offline_state=None
            self.say(f'参加できません: {exc}',12)

    def save_guest_profile(self, quiet=True):
        """Save earned personal items locally WITHOUT replacing the guest's offline farm."""
        if not self.online_guest or not self.online_profile_received or not self.offline_state:
            return False
        if self.read_only:
            return False
        profile = copy.deepcopy(self.state)
        profile['plots'] = copy.deepcopy(self.offline_state['plots'])
        profile['created_at'] = self.offline_state['created_at']
        profile['player'] = [round(v, 2) for v in self.player]
        profile['selected_crop'] = self.selected
        try:
            save_state(profile, self.save_file)
            self.offline_state = profile
            self.last_guest_save = time.monotonic()
            return True
        except SaveError as exc:
            self.say(f'自分の所持品を保存できません: {exc}', 12)
            return False

    def stop_online(self):
        if self.online_guest:
            self.save_guest_profile(True)
        if self.online_client:
            self.online_client.close()
            self.online_client = None
        if self.online_server:
            try:
                self.online_server.close()
                self.state = self.online_server.state
            except (OSError, ValueError, SaveError) as exc:
                self.say(f'ホストの保存に失敗: {exc}', 11)
            self.online_server = None
        if self.online_guest:
            self.state = self.offline_state if self.offline_state is not None else self.state
            self.player = list(self.state['player'])
        if self.modal == 'chat':
            pygame.key.stop_text_input()
        self.offline_state = None
        self.online_profile_received = False
        self.online_guest = False
        self.remote_players = []
        self.room_pin = ''
        self.chat_log = []
        self.chat_last_seq = 0
        self.chat_text = ''
        self.held_keys.clear()

    def poll_network(self):
        if not self.online_client:
            return
        for packet in self.online_client.poll():
            if packet.get('type') == 'snapshot':
                try:
                    incoming = packet['state']
                    if not isinstance(incoming, dict):
                        continue
                    incoming['selected_crop'] = self.selected
                    self.state = incoming
                    self.online_profile_received = True
                    if isinstance(packet.get('story_nodes'), list):
                        self.story_nodes = packet['story_nodes']
                    self.remote_players = [p for p in packet.get('players', [])
                                           if p.get('id') != self.online_client.id]
                    server_position = packet.get('self_pos')
                    if (isinstance(server_position, list) and len(server_position) == 2
                            and math.dist(self.player, server_position) > 85):
                        self.player = list(server_position)
                    messages = packet.get('chat', [])
                    if isinstance(messages, list):
                        self.chat_log = messages[-30:]
                        if messages:
                            newest = messages[-1]
                            seq = newest.get('seq', 0)
                            if seq > self.chat_last_seq and self.chat_last_seq and self.modal != 'chat':
                                self.say(f'CHAT {newest.get("name", "Player")}: {newest.get("text", "")}', 7)
                            self.chat_last_seq = max(self.chat_last_seq, seq)
                except (KeyError, TypeError, ValueError):
                    pass
            elif packet.get('type') == 'result':
                if isinstance(packet.get('state'), dict):
                    incoming = packet['state']
                    incoming['selected_crop'] = self.selected
                    self.state = incoming
                    self.online_profile_received = True
                    if self.online_guest:
                        self.save_guest_profile(True)
                self.say(packet.get('message', '操作を反映しました。'), 4)
            elif packet.get('type') == 'disconnected':
                self.stop_online()
                self.reload_story()
                self.scene = 'title'
                self.modal = None
                self.say('ホストとの接続が切れました。自分の所持金と持ち物を保存しました。', 12)
                return
        if not self.online_client:
            return
        if time.monotonic() - self.last_network_pos >= .10:
            self.online_client.send('move', x=round(self.player[0], 2), y=round(self.player[1], 2))
            self.last_network_pos = time.monotonic()
        if self.online_guest and time.monotonic() - self.last_guest_save >= 12:
            self.save_guest_profile(True)

    def rescue_player(self):
        """F9 always leads to a valid spawn; host also authorizes online teleports."""
        now = time.monotonic()
        if now - self.last_rescue < 12:
            self.say('緊急脱出は12秒ごとに使えます。')
            return
        self.last_rescue = now
        self.player = safe_destination()
        if self.online_client:
            self.online_client.action('rescue', None)
            self.say('緊急脱出を要求しました。ホストの位置情報と同期します。', 5)
        else:
            self.persist(True)
            self.say('スタックを解除！ 自宅近くに移動しました。', 6)

    def toggle_chat(self):
        if not self.online_client:
            self.say('チャットはオンライン参加中に利用できます。', 4)
            return
        self.chat_text = ''
        self.modal = 'chat'
        self.held_keys.clear()
        pygame.key.start_text_input()

    def close_chat(self, send=False):
        if send and self.online_client and self.chat_text.strip():
            self.online_client.chat(self.chat_text)
        pygame.key.stop_text_input()
        self.chat_text = ''
        self.modal = None

    def set_resolution(self):
        width, height = RESOLUTIONS[self.settings['resolution']]
        flags = pygame.FULLSCREEN if self.settings['fullscreen'] else pygame.RESIZABLE
        try:
            self.screen = pygame.display.set_mode((width, height), flags)
        except pygame.error:
            self.settings['resolution'] = 0
            self.settings['fullscreen'] = False
            self.screen = pygame.display.set_mode(RESOLUTIONS[0], pygame.RESIZABLE)
        store_settings(self.settings)

    def point(self, screen_point):
        w, h = self.screen.get_size()
        return (screen_point[0] * BASE_W / max(1,w), screen_point[1] * BASE_H / max(1,h))

    def say(self, phrase, seconds=5):
        self.message = phrase
        self.message_until = time.monotonic() + seconds

    def register(self, action, rect, value=None):
        self.buttons.append((action,pygame.Rect(rect),value))

    def ui_button(self, rect, label, action, val=None, selected=False, disabled=False, size=19):
        button(self.stage,self.fonts,pygame.Rect(rect),label,self.mouse,selected,disabled,size)
        if not disabled:self.register(action,rect,val)

    def persist(self, quiet=False):
        if self.online_client:
            if self.online_guest:
                return self.save_guest_profile(quiet)
            if not quiet:self.say('オンライン中はホストが自動保存しています。')
            return True
        if self.read_only:
            if not quiet:self.say('セーブが破損しているため保存停止中。セーブ読み込みをしてください。',9)
            return False
        self.state['selected_crop'] = self.selected
        self.state['player'] = [round(v,2) for v in self.player]
        try:
            save_state(self.state,self.save_file)
            self.last_save_time = time.monotonic()
            if not quiet:self.say('セーブしました。')
            return True
        except SaveError as exc:
            self.say(f'セーブできません: {exc}',12)
            return False

    def new_game(self):
        if self.online_client:
            self.say('協力プレイ中は新規ゲームを始められません。');return
        if self.read_only:
            self.say('保存データ保護中のため、新規開始はできません。',9)
            return
        self.state = new_state()
        self.selected = 'kaiware'
        self.player = list(self.state['player'])
        self.persist(True)
        self.scene = 'world'
        self.modal = 'help'
        self.say('新しい牧場へようこそ！ 畑と湖の両方を探検できます。',9)

    def import_assets(self):
        try:
            f = choose_file('元のアンベラ牧場ZIPを選択')
            if f:
                self.assets.import_zip(f)
                self.say(f'作物画像 {len(self.assets.images)}/12 点を読み込みました。元データは変更していません。',8)
        except (OSError,pygame.error,ValueError,RuntimeError,zipfile.BadZipFile) as exc:
            self.say(f'画像読込に失敗: {exc}',10)

    def export_save(self):
        try:
            f = choose_file('セーブを書き出す',True,'json')
            if f:
                self.state['player'] = list(self.player)
                save_state(self.state,f,create_backup=False)
                self.say(f'セーブを書き出しました: {f.name}',7)
        except (OSError,RuntimeError,SaveError) as exc:self.say(str(exc),10)

    def import_save(self):
        try:
            f = choose_file('セーブを読み込む',False,'json')
            if f:
                loaded = load_json(f)
                save_state(loaded,self.save_file,create_backup=not self.read_only)
                self.state = loaded
                self.player = list(loaded['player'])
                self.selected = loaded['selected_crop']
                self.read_only = False
                self.say('セーブデータを復元しました。',8)
        except (OSError,RuntimeError,SaveError) as exc:self.say(str(exc),10)

    def make_trees(self):
        return set(TREE_POSITIONS)

    def blocked(self,x,y):
        return map_blocked(x,y)

    def move(self, dt):
        # Poll the current physical key state each frame; KEYUP and focus loss
        # also clear cached keys so input never remains latched after a menu.
        pressed = pygame.key.get_pressed()
        if not pygame.key.get_focused():
            self.held_keys.clear()
            return
        def down(*codes):
            return any(pressed[c] or c in self.held_keys for c in codes)
        dx = int(down(pygame.K_d, pygame.K_RIGHT)) - int(down(pygame.K_a, pygame.K_LEFT))
        dy = int(down(pygame.K_s, pygame.K_DOWN)) - int(down(pygame.K_w, pygame.K_UP))
        if dx == dy == 0:
            return
        self.facing = ('right' if dx > 0 else 'left') if abs(dx) > abs(dy) else ('down' if dy > 0 else 'up')
        self.player = move_character(self.player, (dx, dy), dt)

    def near(self,point,radius):
        return math.dist(self.player,point)<=radius

    def closest_plot(self):
        nearest=min(range(PLOT_COUNT),key=lambda i:math.dist(self.player,plot_world(i)))
        return nearest if self.near(plot_world(nearest),54) else None

    def context(self):
        # Choose nearest action, not last in arbitrary ordering.
        options=[]
        for action,point,radius in (
            ('shop', SHOP_DOOR, 98),('shipping',SHIP_DOOR,98),
            ('missions',BOARD_POS,70),('home',HOME_POS,88),
            ('fishing',FISH_PIER,65),('fish_market',FISH_MARKET,98),
            ('fisherman',FISHERMAN,62),('guide',GUIDE_POS,58),('merchant',MERCHANT_POS,58)):
            distance=math.dist(self.player,point)
            if distance<=radius:options.append((distance,action,None))
        idx=self.closest_plot()
        if idx is not None:
            options.append((math.dist(self.player,plot_world(idx)),'plot',idx))
        if not options:return None,None
        _,action,data=min(options)
        return action,data

    def interact(self):
        action,data=self.context()
        if action is None:
            self.say('看板・施設の入口・畑の近くで E を押してください。');return
        if action=='plot':
            if self.online_client:
                self.online_client.action('plot',{'index':data,'crop':self.selected})
                return
            old=self.state['plots'][data]
            if old is None:
                if plant(self.state,data,self.selected):
                    self.persist(True)
                    self.sound.play('plant')
                    self.say(f'{CROP_BY_ID[self.selected].name}を植えました。種の残り: {self.state["seeds"][self.selected]}')
                else:
                    self.say(f'{CROP_BY_ID[self.selected].name}の種が足りません。種屋で購入できます。')
            else:
                p,remaining,ready=progress_for(old)
                if ready:
                    crop=harvest(self.state,data)
                    self.persist(True)
                    self.sound.play('harvest')
                    self.say(f'収穫！ {CROP_BY_ID[crop].name}が倉庫に入りました。',6)
                else:self.say(f'{CROP_BY_ID[old["crop"]].name}は{int(p*100)}％成長。あと{time_short(remaining)}')
        elif action=='home':
            self.modal='help'; self.say('自宅の掲示板：操作説明とセーブ管理。')
        elif action=='shop':
            self.modal='shop';self.scroll=0
        elif action=='shipping':
            self.modal='shipping';self.scroll=0
        elif action=='missions':self.modal='missions';self.mission_page=0
        elif action=='fishing':self.start_fishing()
        elif action=='fish_market':self.modal='fish_market'
        elif action=='fisherman':self.start_story('nagi')
        elif action=='guide':self.start_story('guide')
        elif action=='merchant':self.start_story('merchant')

    def start_fishing(self):
        fish=roll_fish()
        self.fishing_fish=fish
        self.fishing_round=FishingRound(fish_id=fish.id)
        self.fishing_outcome=''
        self.modal='fishing'
        self.sound.play('move')

    def update_fishing(self,dt):
        if not self.fishing_round or self.fishing_round.result:
            return
        keys=pygame.key.get_pressed()
        direction=int(bool(keys[pygame.K_s] or keys[pygame.K_DOWN]))-int(bool(keys[pygame.K_w] or keys[pygame.K_UP]))
        result=self.fishing_round.step(dt,direction,bool(keys[pygame.K_SPACE]))
        if result:
            self.fishing_outcome=result
            if result=='caught':
                if self.online_client:self.online_client.action('fish_caught',self.fishing_fish.id)
                else:
                    add_catch(self.state,self.fishing_fish.id)
                    self.persist(True)
                self.sound.play('harvest')
                self.say(f'{self.fishing_fish.name}を釣りました！ 魚市場で売れます。',7)
            else:
                self.say(f'{self.fishing_fish.name}に逃げられました。もう一度挑戦！',6)
            self.modal='fishing_result'

    def start_story(self,npc='nagi'):
        event=available_story(self.story_nodes,self.state,npc)
        if event:
            self.story_event=event
            self.story_line=0
            self.modal='story'
        else:
            self.say('また新しい話を聞きに来てね。',7)

    def next_story_line(self):
        if not self.story_event:
            self.modal=None
            return
        self.story_line+=1
        if self.story_line >= len(self.story_event['lines']):
            if self.online_client:self.online_client.action('story',self.story_event['id'])
            else:
                finish_story(self.state,self.story_event['id'])
                self.persist(True)
            self.story_event=None
            self.modal=None

    def do_action(self,action,val):
        if self.online_client and action in ('buy','ship','fish_sell','claim'):
            self.online_client.action(action,list(val) if isinstance(val,tuple) else val)
            return
        if action=='notices':self.open_notices()
        elif action=='notices_refresh':self.refresh_notices(force=True)
        elif action=='notice_pick':self.read_notice(val)
        elif action=='notice_scroll':self.notice_line_offset = max(0, self.notice_line_offset + val)
        elif action=='notice_page':
            items = public_view(self.notice_feed)
            self.notice_page = max(0, min(max(0,(len(items)-1)//5), self.notice_page + val))
            first = self.notice_page*5
            if first < len(items):self.read_notice(items[first]['id'])
        elif action=='open_release_page':webbrowser.open(val or RELEASES_URL)
        elif action=='host_room':self.reload_story();self.start_room()
        elif action=='join_dialog':self.modal='join'
        elif action=='join_field':self.join_field=val
        elif action=='join_room':self.join_room()
        elif action=='story_editor':self.open_admin()
        elif action=='chat':self.toggle_chat()
        elif action=='rescue':
            self.rescue_player()
            if self.modal=='pause':self.modal=None
        elif action=='check_update':self.check_updates()
        elif action=='begin':
            self.reload_story()
            self.scene='world'
            self.modal=None
            self.say('WASDで移動、Eで調べる。南西の湖に釣り場があります！',8)
        elif action=='newgame':
            self.modal='confirm_new'
        elif action=='confirm_new':self.new_game()
        elif action=='return_title':
            if self.modal=='chat':pygame.key.stop_text_input()
            if self.online_client:self.stop_online()
            else:self.persist(True)
            self.reload_story()
            self.scene='title';self.modal=None
        elif action=='resume':self.modal=None
        elif action=='quit':
            if self.online_client:self.stop_online()
            elif self.scene=='world':self.persist(True)
            self.running=False
        elif action=='overlay':
            self.modal=val
            if val=='missions':self.mission_page=0
        elif action=='settings':
            self.prev_modal=self.modal
            self.modal='settings'
        elif action=='settings_back':
            self.modal=self.prev_modal if self.prev_modal!='settings' else None
            self.prev_modal=None
        elif action=='close':
            if self.modal=='chat':self.close_chat()
            else:self.modal=None
        elif action=='fish_again':self.start_fishing()
        elif action=='fish_sell':
            fish_id,count=val
            qty=self.state['fish_inventory'][fish_id] if count==-1 else count
            if sell_fish(self.state,fish_id,qty):
                self.persist(True);self.sound.play('buy')
                self.say(f'{FISH_BY_ID[fish_id].name} ×{qty}を販売しました！ +{qty*FISH_BY_ID[fish_id].price}G',7)
            else:self.say('売れる魚がありません。')
        elif action=='next_story':self.next_story_line()
        elif action=='mission_page':self.mission_page=max(0,min((len(MISSIONS)-1)//7,self.mission_page+val))
        elif action=='pick_crop':
            self.selected=val
            self.state['selected_crop']=val
            self.persist(True)
            self.say(f'種を選択: {CROP_BY_ID[val].name}（{self.state["seeds"][val]}個）')
        elif action=='buy':
            crop_id,count=val
            if buy_seeds(self.state,crop_id,count):
                self.persist(True);self.sound.play('buy')
                self.say(f'{CROP_BY_ID[crop_id].name}の種を{count}個購入。',5)
            else:self.say('所持金が不足しています。作物を出荷して稼ぎましょう。',6)
        elif action=='ship':
            crop_id,count=val
            n=self.state['warehouse'][crop_id] if count==-1 else count
            if sell_crops(self.state,crop_id,n):
                self.persist(True);self.sound.play('buy')
                self.say(f'{CROP_BY_ID[crop_id].name}を{n}個出荷：+{n*CROP_BY_ID[crop_id].sell_price} G',6)
            else:self.say('出荷できる作物がありません。')
        elif action=='claim':
            if claim_mission(self.state,val):
                self.persist(True);self.sound.play('mission')
                self.say(f'ミッション達成！ +{MISSION_BY_ID[val][5]} G',6)
        elif action=='volume':
            self.settings['volume']=max(0,min(100,self.settings['volume']+val))
            self.sound.set_volume(self.settings['volume'])
            self.sound.play('move')
            if not store_settings(self.settings):self.say('設定を保存できません。')
        elif action=='brightness':
            self.settings['brightness']=max(50,min(130,self.settings['brightness']+val))
            if not store_settings(self.settings):self.say('設定を保存できません。')
        elif action=='resolution':
            self.settings['resolution']=(self.settings['resolution']+val)%len(RESOLUTIONS)
            self.set_resolution()
        elif action=='fullscreen':
            self.settings['fullscreen']=not self.settings['fullscreen']
            self.set_resolution()
        elif action=='import_assets':self.import_assets()
        elif action=='import_save':
            if self.online_client:self.say('オンライン中はセーブの読み込み不可')
            else:self.import_save()
        elif action=='export_save':
            if self.online_guest:self.say('ゲストはホストのセーブを書き出せません')
            else:self.export_save()
        elif action=='save':self.persist()
        elif action=='goto_world':
            self.scene='world';self.modal=None

    def events(self):
        for event in pygame.event.get():
            if event.type==pygame.QUIT:self.running=False
            elif event.type==pygame.VIDEORESIZE and not self.settings['fullscreen']:
                if (event.w,event.h)!=(self.screen.get_width(),self.screen.get_height()):
                    self.screen=pygame.display.set_mode((max(640,event.w),max(360,event.h)),pygame.RESIZABLE)
            elif event.type==pygame.KEYUP:
                self.held_keys.discard(event.key)
            elif event.type==getattr(pygame, 'WINDOWFOCUSLOST', -999):
                self.held_keys.clear()
            elif event.type==pygame.TEXTINPUT and self.modal=='chat':
                self.chat_text = (self.chat_text + event.text.replace('\r', '').replace('\n', ''))[:160]
            elif event.type==pygame.KEYDOWN:
                if event.key in (pygame.K_w,pygame.K_a,pygame.K_s,pygame.K_d,
                                 pygame.K_UP,pygame.K_DOWN,pygame.K_LEFT,pygame.K_RIGHT):
                    self.held_keys.add(event.key)
                if self.modal=='chat':
                    if event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):self.close_chat(send=True)
                    elif event.key==pygame.K_ESCAPE:self.close_chat()
                    elif event.key==pygame.K_BACKSPACE:self.chat_text=self.chat_text[:-1]
                    continue
                if self.modal=='join' and event.key not in (pygame.K_ESCAPE,pygame.K_F11):
                    if event.key==pygame.K_TAB:
                        order=['address','pin','name']
                        self.join_field=order[(order.index(self.join_field)+1)%len(order)]
                    elif event.key==pygame.K_BACKSPACE:
                        self.join_fields[self.join_field]=self.join_fields[self.join_field][:-1]
                    elif event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):self.join_room()
                    elif event.unicode and event.unicode.isprintable() and len(self.join_fields[self.join_field])<65:
                        self.join_fields[self.join_field]+=event.unicode
                    continue
                if event.key==pygame.K_F11:
                    self.do_action('fullscreen',None)
                elif event.key==pygame.K_F9 and self.scene=='world':self.rescue_player()
                elif event.key==pygame.K_F5 and self.scene=='world':self.persist()
                elif event.key==pygame.K_F6:self.export_save()
                elif event.key==pygame.K_F7:self.import_save()
                elif event.key==pygame.K_ESCAPE:
                    if self.modal=='story':self.next_story_line()
                    elif self.modal=='settings':self.do_action('settings_back',None)
                    elif self.modal is not None:self.modal=None
                    elif self.scene=='world':self.modal='pause'
                elif self.modal=='story' and event.key in (pygame.K_e,pygame.K_SPACE,pygame.K_RETURN):
                    self.next_story_line()
                elif self.modal=='fishing_result' and event.key in (pygame.K_e,pygame.K_SPACE,pygame.K_RETURN):
                    self.modal=None
                elif self.scene=='world' and self.modal is None:
                    if event.key==pygame.K_t and self.online_client:self.toggle_chat()
                    elif event.key in (pygame.K_e,pygame.K_SPACE):self.interact()
                    elif event.key in (pygame.K_i,pygame.K_TAB):self.modal='inventory'
                    elif event.key==pygame.K_m:self.modal='missions'
                    elif event.key==pygame.K_h:self.modal='help'
                    elif event.key==pygame.K_q:
                        idx=next(i for i,c in enumerate(CROPS) if c.id==self.selected)
                        self.do_action('pick_crop',CROPS[(idx-1)%len(CROPS)].id)
                    elif event.key==pygame.K_r:
                        idx=next(i for i,c in enumerate(CROPS) if c.id==self.selected)
                        self.do_action('pick_crop',CROPS[(idx+1)%len(CROPS)].id)
                    elif pygame.K_1<=event.key<=pygame.K_9:
                        idx=event.key-pygame.K_1
                        self.do_action('pick_crop',CROPS[idx].id)
            elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                self.mouse=self.point(event.pos)
                for action,rect,val in reversed(self.buttons):
                    if rect.collidepoint(self.mouse):
                        self.do_action(action,val)
                        break
                else:
                    if self.scene=='world' and not self.modal:
                        wx=self.mouse[0]+self.camera[0]
                        wy=self.mouse[1]-VIEW_TOP+self.camera[1]
                        for idx in range(PLOT_COUNT):
                            if abs(wx-plot_world(idx)[0])<25 and abs(wy-plot_world(idx)[1])<25:
                                if self.near(plot_world(idx),54):
                                    self.handle_world_plot_click(idx)
                                else:self.say('畑に近づいてからクリックしてください。')
                                break
        self.mouse=self.point(pygame.mouse.get_pos())

    def handle_world_plot_click(self,idx):
        if self.online_client:
            self.online_client.action('plot',{'index':idx,'crop':self.selected});return
        # Clicking a nearby plot behaves like interacting via E.
        p=self.state['plots'][idx]
        if p is None:
            if plant(self.state,idx,self.selected):
                self.persist(True);self.sound.play('plant')
                self.say(f'{CROP_BY_ID[self.selected].name}を植えました。')
            else:self.say('種が足りません。')
        elif progress_for(p)[2]:
            name=CROP_BY_ID[p['crop']].name
            harvest(self.state,idx);self.persist(True);self.sound.play('harvest')
            self.say(f'{name}を収穫しました。')
        else:self.say(f'成長中。あと{time_short(progress_for(p)[1])}')

    def camera_update(self):
        self.camera[0]=max(0,min(WORLD_W*TILE-BASE_W,self.player[0]-BASE_W*.5))
        self.camera[1]=max(0,min(WORLD_H*TILE-VIEW_HEIGHT,self.player[1]-VIEW_HEIGHT*.52))

    def draw_pixel_tree(self,loc_x,loc_y):
        s=self.world_layer
        pygame.draw.rect(s,(70,54,39),(loc_x+12,loc_y+15,10,18))
        for rx,ry,w,h,col in (
            (5,6,26,14,(36,88,51)),(1,10,28,13,(50,112,53)),
            (9,0,17,12,(65,135,67)),(15,3,12,10,(76,145,74))):
            pygame.draw.rect(s,col,(loc_x+rx,loc_y+ry,w,h))

    def draw_house(self,wx,wy,width,height,name,door_pos,kind):
        s=self.world_layer
        x=int(wx-self.camera[0]);y=int(wy-self.camera[1])
        if x>BASE_W+200 or y>VIEW_HEIGHT+200 or x+width<-200 or y+height<-200:return
        pygame.draw.rect(s,(38,69,51),(x+8,y+height-4,width-12,14))
        pygame.draw.rect(s,(229,201,137),(x+7,y+31,width-14,height-29))
        for xx in range(x+25,x+width-20,63):
            pygame.draw.rect(s,(99,137,138),(xx,y+52,32,30))
            pygame.draw.rect(s,(75,56,39),(xx+13,y+52,5,30))
        pygame.draw.polygon(s,(122,63,48),((x,y+42),(x+width//2,y-18),(x+width,y+42)))
        pygame.draw.line(s,(213,142,91),(x+10,y+38),(x+width//2,y-10),4)
        pygame.draw.line(s,(83,43,39),(x+width//2,y-10),(x+width-10,y+38),5)
        dx=int(door_pos[0]-self.camera[0]);dy=int(door_pos[1]-self.camera[1])
        pygame.draw.rect(s,(133,108,72),(dx-26,y+height,52,max(3,dy-(y+height)+10)))
        pygame.draw.rect(s,(94,56,47),(dx-20,y+height-55,40,55))
        pygame.draw.rect(s,(239,213,144),(dx+8,y+height-31,4,4))
        sign=(193,179,102) if kind=='shop' else (161,185,119)
        pygame.draw.rect(s,sign,(x+width//2-67,y+48,134,31),border_radius=2)
        text(s,self.fonts,name,(x+width//2,y+64),18,INK,True,True)

    def draw_world(self):
        w=self.world_layer
        self.camera_update()
        w.fill((86,147,76))
        cx,cy=self.camera
        startx=max(0,int(cx//TILE));endx=min(WORLD_W,int((cx+BASE_W)//TILE)+2)
        starty=max(0,int(cy//TILE));endy=min(WORLD_H,int((cy+VIEW_HEIGHT)//TILE)+2)
        for ty in range(starty,endy):
            for tx in range(startx,endx):
                x=int(tx*TILE-cx);y=int(ty*TILE-cy)
                shade=(84,150,76) if (tx*13+ty*7)%7 else (93,160,82)
                pygame.draw.rect(w,shade,(x,y,TILE,TILE))
                if (tx*149+ty*101)%13==0:
                    pygame.draw.rect(w,(113,172,78),(x+7,y+9,5,3))
                    pygame.draw.rect(w,(53,109,48),(x+11,y+8,3,9))
                if (tx*19+ty*11)%17==0:
                    pygame.draw.rect(w,(166,189,95),(x+24,y+24,3,3))
                # Paths connecting home, fields, stores and mission board.
                on_horizontal=(ty in (9,10,11,20,21) and 7<=tx<=42)
                on_vertical=(tx in (22,23,24,35,36) and 10<=ty<=28)
                on_entrance=(37<=tx<=43 and ty in (13,14,27,28))
                if on_horizontal or on_vertical or on_entrance:
                    pygame.draw.rect(w,(186,153,100),(x,y,TILE,TILE))
                    if (tx*11+ty*5)%9==0:pygame.draw.rect(w,(165,132,85),(x+5,y+18,9,4))
                if 3<=tx<=13 and 26<=ty<=32:
                    pygame.draw.rect(w,(71,128,164),(x,y,TILE,TILE))
                    if (tx*7+ty*3)%4==0:
                        pygame.draw.rect(w,(116,181,185),(x+10,y+14,12,2))
        # Lakeshore details and an east-bank boardwalk to the fishing location.
        for tx in range(12,16):
            x=int(tx*TILE-cx);y=int(29*TILE-cy)
            pygame.draw.rect(w,(130,88,51),(x,y+7,32,22))
            pygame.draw.rect(w,(198,145,86),(x,y+6,32,6))
            pygame.draw.rect(w,(92,61,41),(x+2,y+5,4,27))
            pygame.draw.rect(w,(92,61,41),(x+27,y+5,4,27))
        # Fishing float marker / pier sign.
        px=int(FISH_PIER[0]-cx);py=int(FISH_PIER[1]-cy)
        pygame.draw.rect(w,(102,66,46),(px-3,py-40,7,39))
        pygame.draw.rect(w,(244,223,165),(px-45,py-57,87,26))
        text(w,self.fonts,'釣り場',(px,py-53),16,BROWN,True,True)
        for tx,ty in ((4,27),(7,29),(10,31),(12,26)):
            rx=int(tx*TILE-cx);ry=int(ty*TILE-cy)
            pygame.draw.ellipse(w,(165,210,206),(rx+4,ry+17,19,5),1)
            pygame.draw.rect(w,(198,235,212),(rx+17,ry+16,3,3))
        # Farm fence (open from south and east).
        left,top=(FARM_X-2)*TILE,(FARM_Y-2)*TILE
        right,bottom=(FARM_X+11)*TILE,(FARM_Y+8)*TILE
        for xx in range(left,right+1,TILE):
            for yy in (top,bottom):
                if not fence_at(xx//TILE, yy//TILE):continue
                px=int(xx-cx);py=int(yy-cy)
                pygame.draw.rect(w,(111,73,46),(px+6,py+3,9,24))
                pygame.draw.rect(w,(212,180,119),(px+2,py+10,28,6))
        for yy in range(top,bottom+1,TILE):
            for xx in (left,right):
                if not fence_at(xx//TILE, yy//TILE):continue
                px=int(xx-cx);py=int(yy-cy)
                pygame.draw.rect(w,(111,73,46),(px+9,py+3,10,26))
                pygame.draw.rect(w,(212,180,119),(px+6,py+11,17,6))
        now=time.time()
        for idx in range(PLOT_COUNT):
            wx,wy=plot_world(idx)
            x,y=int(wx-cx),int(wy-cy)
            r=pygame.Rect(x-24,y-24,48,48)
            pygame.draw.rect(w,(97,61,40),r)
            pygame.draw.rect(w,(133,86,52),r.inflate(-5,-5))
            for i in range(3):
                pygame.draw.line(w,(90,56,37),(x-16,y-12+i*10),(x+16,y-12+i*10),2)
            plot=self.state['plots'][idx]
            if plot is not None:
                p,remaining,ready=progress_for(plot,now)
                # The ORIGINAL PNG is displayed without pixel-altering filters.
                side=21+round(24*p)
                self.assets.draw_crop(w,plot['crop'],(x-side//2,y-side//2-5,side,side))
                if ready:pygame.draw.rect(w,(244,207,85),r,3)
                else:
                    pygame.draw.rect(w,(49,72,50),(x-19,y+18,38,5))
                    pygame.draw.rect(w,(124,197,104),(x-19,y+18,int(38*p),5))
        # Mission board marker.
        bx=int(26*TILE-cx);by=int(16*TILE-cy)
        pygame.draw.rect(w,(87,62,40),(bx+4,by+12,6,34))
        pygame.draw.rect(w,(87,62,40),(bx+27,by+12,6,34))
        pygame.draw.rect(w,(232,206,142),(bx-5,by-4,46,37))
        pygame.draw.rect(w,(108,66,44),(bx-5,by-4,46,37),4)
        pygame.draw.rect(w,(175,91,61),(bx+4,by+10,29,4))
        pygame.draw.rect(w,(175,91,61),(bx+8,by+20,19,3))
        for building in BUILDINGS:
            self.draw_house(building.tile_x*TILE,building.tile_y*TILE,
                            building.tile_w*TILE,building.tile_h*TILE,
                            building.label,building.door(),building.key)
        # Talkable fishing NPC in a blue jacket and straw hat; not a supplied asset.
        nx=int(FISHERMAN[0]-cx);ny=int(FISHERMAN[1]-cy)
        pygame.draw.ellipse(w,(46,88,79),(nx-12,ny+11,24,8))
        pygame.draw.rect(w,(48,93,144),(nx-9,ny-2,18,20))
        pygame.draw.rect(w,(232,186,137),(nx-8,ny-19,16,17))
        pygame.draw.rect(w,(149,96,52),(nx-14,ny-22,27,7))
        pygame.draw.rect(w,(214,167,95),(nx-9,ny-27,17,8))
        text(w,self.fonts,'ナギ',(nx,ny-48),16,WHITE,True,True)
        for nxw,nyw,coat,label in ((GUIDE_POS[0],GUIDE_POS[1],(166,81,83),'ミオ'),
                                   (MERCHANT_POS[0],MERCHANT_POS[1],(181,147,55),'店主')):
            ax,ay=int(nxw-cx),int(nyw-cy)
            pygame.draw.ellipse(w,(51,78,48),(ax-10,ay+13,22,8))
            pygame.draw.rect(w,coat,(ax-9,ay-1,18,17))
            pygame.draw.rect(w,(231,186,140),(ax-7,ay-17,15,16))
            pygame.draw.rect(w,(88,60,45),(ax-9,ay-19,19,6))
            text(w,self.fonts,label,(ax,ay-45),15,WHITE,True,True)
        for person in self.remote_players:
            rx,ry=int(person['x']-cx),int(person['y']-cy)
            if -25<rx<BASE_W+25 and -40<ry<VIEW_HEIGHT+40:
                pygame.draw.rect(w,(235,151,64),(rx-9,ry+1,18,18))
                pygame.draw.rect(w,(231,187,145),(rx-8,ry-16,16,18))
                pygame.draw.rect(w,(77,63,52),(rx-11,ry-20,22,6))
                text(w,self.fonts,person['name'],(rx,ry-43),15,WHITE,True,True)

        for tx,ty in self.tree_positions:
            x=int(tx*TILE-cx);y=int(ty*TILE-cy)
            if -40<x<BASE_W+40 and -40<y<VIEW_HEIGHT+40:
                self.draw_pixel_tree(x,y)
        # Player sprite as a discrete pixel character (provisional new character).
        px=int(self.player[0]-cx);py=int(self.player[1]-cy)
        pygame.draw.ellipse(w,(50,79,51),(px-12,py+12,24,9))
        pygame.draw.rect(w,(57,79,134),(px-9,py+1,18,17))
        pygame.draw.rect(w,(55,44,51),(px-7,py+15,5,8))
        pygame.draw.rect(w,(55,44,51),(px+3,py+15,5,8))
        pygame.draw.rect(w,(228,177,120),(px-7,py-15,15,17))
        pygame.draw.rect(w,(112,70,45),(px-10,py-20,21,7))
        pygame.draw.rect(w,(152,97,52),(px-13,py-17,27,4))
        if self.facing!='up':
            ex=-4 if self.facing!='right' else 4
            pygame.draw.rect(w,(47,45,40),(px+ex,py-8,3,3))
        if self.facing=='left':pygame.draw.rect(w,(237,202,145),(px-11,py+3,5,9))
        else:pygame.draw.rect(w,(237,202,145),(px+8,py+3,5,9))
        self.stage.blit(w,(0,VIEW_TOP))

    def hud(self):
        s=self.stage
        pygame.draw.rect(s,DARK,(0,0,BASE_W,VIEW_TOP))
        pygame.draw.rect(s,(31,49,37),(0,VIEW_TOP+VIEW_HEIGHT,BASE_W,BASE_H-(VIEW_TOP+VIEW_HEIGHT)))
        day,h,m=clock_at(self.state)
        text(s,self.fonts,'アンベラ牧場',(23,12),27,CREAM,True)
        if self.online_client:text(s,self.fonts,f'ONLINE {len(self.remote_players)+1}/{8}  PIN {self.room_pin}',(22,53),13,GOLD_LIGHT,True)
        text(s,self.fonts,f'{day}日目  {h:02d}:{m:02d}',(368,13),25,WHITE,True)
        text(s,self.fonts,f'所持金  {self.state["coins"]:,} G',(609,17),24,GOLD_LIGHT,True)
        text(s,self.fonts,f'種：{CROP_BY_ID[self.selected].name} ×{self.state["seeds"][self.selected]}',(889,21),19,WHITE,True,max_width=362)
        # Info / status strip.
        if self.message and time.monotonic()<self.message_until:
            msg=self.message
        elif self.read_only:
            msg='注意：セーブ異常のため保存停止中。F7でセーブを読み込んでください。'
        else:
            action,data=self.context()
            if action=='plot':
                p=self.state['plots'][data]
                if p is None:msg=f'E 植える  |  選択種 {CROP_BY_ID[self.selected].name} ×{self.state["seeds"][self.selected]}'
                else:
                    _,rdy,ready=progress_for(p)
                    msg=f'E {"収穫" if ready else "様子を見る"}  |  {CROP_BY_ID[p["crop"]].name} {time_short(rdy)}'
            else:
                labels={'shop':'種屋へ入る','shipping':'作物を出荷','missions':'ミッションを見る','home':'自宅（説明・セーブ）','fishing':'釣りを始める','fish_market':'魚を売る','fisherman':'ナギと話す','guide':'ミオと話す','merchant':'店主と話す'}
                msg=('E  '+labels[action]) if action in labels else 'WASD/矢印 移動 | F9 緊急脱出 | E 調べる | I 持ち物 | T チャット | Esc メニュー'
        text(s,self.fonts,msg,(22,VIEW_TOP+VIEW_HEIGHT+18),18,CREAM,True,max_width=1040)
        self.ui_button((1094,VIEW_TOP+VIEW_HEIGHT+12,165,42),'メニュー','overlay','pause',size=18)
        self.draw_minimap()

    def draw_minimap(self):
        x,y=BASE_W-209,VIEW_TOP+14
        s=self.stage
        pygame.draw.rect(s,(38,56,42),(x-8,y-8,201,148),border_radius=6)
        pygame.draw.rect(s,(162,191,120),(x,y,185,129))
        points=(('畑',12,15,(110,70,43)),('種屋',40,12,(232,180,79)),
                ('出荷',40,27,(188,92,62)),('掲示板',26,16,(111,90,174)),
                ('自宅',9,7,(230,226,177)),('湖',8,29,(71,128,164)),
                ('魚市場',26,29,(87,160,209)))
        for label,wx,wy,clr in points:
            px=x+int(wx/WORLD_W*185);py=y+int(wy/WORLD_H*129)
            pygame.draw.rect(s,clr,(px-4,py-4,9,9))
        px=x+int(self.player[0]/(WORLD_W*TILE)*185)
        py=y+int(self.player[1]/(WORLD_H*TILE)*129)
        pygame.draw.circle(s,(255,254,250),(px,py),5)
        pygame.draw.circle(s,(42,72,72),(px,py),5,2)
        for other in self.remote_players:
            ox=x+int(other['x']/(WORLD_W*TILE)*185)
            oy=y+int(other['y']/(WORLD_H*TILE)*129)
            pygame.draw.circle(s,GOLD_LIGHT,(ox,oy),4)
        text(s,self.fonts,'位置 / MAP',(x+12,y+7),16,DARK,True)

    def overlay_panel(self,title,sub=''):
        cover=pygame.Surface((BASE_W,BASE_H),pygame.SRCALPHA)
        cover.fill((12,28,23,188))
        self.stage.blit(cover,(0,0))
        box(self.stage,(168,46,944,630),PAPER,BROWN,12,6)
        pygame.draw.rect(self.stage,(186,210,146),(188,65,904,70),border_radius=7)
        text(self.stage,self.fonts,title,(212,81),32,GREEN_DARK,True)
        if sub:text(self.stage,self.fonts,sub,(214,118),15,INK,max_width=775)
        self.ui_button((987,80,83,41),'閉じる','close',size=16)

    def draw_title(self):
        s=self.stage
        s.fill((37,72,63))
        for j in range(40):
            bx=(j*101+73)%BASE_W; by=(j*79+90)%BASE_H
            pygame.draw.rect(s,(64,104,73),(bx,by,20,25))
        pygame.draw.rect(s,(68,123,85),(0,480,BASE_W,240))
        pygame.draw.rect(s,(97,148,92),(0,537,BASE_W,183))
        for idx in range(16):
            x=36+idx*81
            pygame.draw.rect(s,(133,90,55),(x,585,52,74))
            pygame.draw.rect(s,(160,112,66),(x+5,590,42,60))
        box(s,(158,62,964,586),(243,232,189),BROWN,14,7)
        box(s,(183,84,914,163),(201,219,161),GREEN_DARK,8,4)
        text(s,self.fonts,'アンベラ牧場',(640,129),70,BROWN,True,True)
        text(s,self.fonts,'―  畑を育て、湖で釣る。牧場と町を自由に歩こう  ―',(640,206),22,GREEN_DARK,False,True)
        self.ui_button((421,263,438,56),'続きから遊ぶ','begin',size=26)
        self.ui_button((421,326,438,55),'新しい牧場を始める','newgame',size=24)
        self.ui_button((421,391,210,50),'協力部屋を作る','host_room',size=18)
        self.ui_button((649,391,210,50),'オンライン参加','join_dialog',size=18)
        self.ui_button((421,452,210,49),'設定','settings',size=22)
        self.ui_button((649,452,210,49),'遊び方','overlay','help',size=22)
        self.ui_button((314,511,206,49),'ストーリー管理','story_editor',size=17)
        unseen = unread_count(self.notice_feed, self.notice_seen)
        self.ui_button((537,511,206,49),f'お知らせ {"NEW "+str(unseen) if unseen else ""}','notices',size=17)
        self.ui_button((760,511,206,49),'終了','quit',size=22)
        status='保存データを読み込み済み' if self.save_file.exists() else '初回開始：新しい牧場が用意されています'
        text(s,self.fonts,status,(640,586),18,GREEN_DARK,True,True)
        if self.load_warning and self.read_only:
            text(s,self.fonts,self.load_warning,(640,617),15,RED,True,True,max_width=890)
        text(s,self.fonts,f'Pygame v{current_version()}  /  協力プレイはホスト方式 / 試作用価格',(640,674),16,PALE,False,True)
        if self.message and time.monotonic()<self.message_until:text(s,self.fonts,self.message,(640,626),16,RED,True,True,max_width=900)

    def draw_settings(self):
        self.overlay_panel('ゲーム設定','変更内容は即時反映・自動保存されます。明度はゲーム画面全体に適用。')
        items=(('音量',f'{self.settings["volume"]} %','volume',10),
               ('明度',f'{self.settings["brightness"]} %','brightness',10),
               ('解像度',f'{RESOLUTIONS[self.settings["resolution"]][0]} × {RESOLUTIONS[self.settings["resolution"]][1]}','resolution',1))
        for i,(label,value,action,step) in enumerate(items):
            y=189+i*108
            text(self.stage,self.fonts,label,(248,y+12),29,INK,True)
            self.ui_button((646,y,65,52),'−',action,-step,size=29)
            box(self.stage,(730,y,210,52),CREAM,BROWN,5,2)
            text(self.stage,self.fonts,value,(835,y+26),22,INK,True,True)
            self.ui_button((955,y,65,52),'+',action,step,size=29)
        label='フルスクリーン ON' if self.settings['fullscreen'] else 'フルスクリーン OFF'
        self.ui_button((429,522,422,58),label,'fullscreen',size=23)
        if not self.sound.available:
            text(self.stage,self.fonts,'音声デバイスが使えないため、BGM/効果音は無音です。',(640,606),18,RED,False,True)
        self.ui_button((290,595,330,43),'ストーリー管理画面','story_editor',size=17)
        self.ui_button((666,595,322,43),'更新情報を確認','check_update',size=17)
        text(self.stage,self.fonts,self.update_status or '更新先は update_config.json で設定します。',(640,648),15,GREEN_DARK,False,True,max_width=830)

    def draw_shop(self):
        self.overlay_panel('たね屋  /  種の購入','試作用価格です（元ゲームの価格資料は未確認）。買った種はインベントリへ。')
        text(self.stage,self.fonts,f'所持金：{self.state["coins"]:,} G',(845,151),22,BROWN,True)
        for i,c in enumerate(CROPS):
            col,row=i%2,i//2
            x,y=203+col*443,185+row*74
            box(self.stage,(x,y,421,67),CREAM,BROWN,5,2)
            self.assets.draw_crop(self.stage,c.id,(x+5,y+9,49,49))
            text(self.stage,self.fonts,c.name,(x+66,y+7),19,INK,True,max_width=158)
            text(self.stage,self.fonts,f'{c.buy_price}G / 所持 {self.state["seeds"][c.id]}',(x+66,y+39),16,GREEN_DARK)
            self.ui_button((x+245,y+11,75,45),'+1','buy',(c.id,1),disabled=self.state['coins']<c.buy_price,size=17)
            self.ui_button((x+327,y+11,78,45),'+5','buy',(c.id,5),disabled=self.state['coins']<c.buy_price*5,size=17)
        text(self.stage,self.fonts,'※ キュウリと金のリンゴも初版では一度だけ収穫できます。',(218,643),15,GREEN_DARK)

    def draw_shipping(self):
        self.overlay_panel('出荷所  /  収穫物の販売','収穫物を売ってお金を増やせます。売値も試作用です。')
        text(self.stage,self.fonts,f'所持金：{self.state["coins"]:,} G',(845,151),22,BROWN,True)
        for i,c in enumerate(CROPS):
            col,row=i%2,i//2
            x,y=203+col*443,185+row*74
            qty=self.state['warehouse'][c.id]
            box(self.stage,(x,y,421,67),CREAM,BROWN,5,2)
            self.assets.draw_crop(self.stage,c.id,(x+5,y+9,49,49))
            text(self.stage,self.fonts,c.name,(x+63,y+5),18,INK,True,max_width=154)
            text(self.stage,self.fonts,f'{c.sell_price}G / 在庫 {qty}',(x+63,y+38),16,GREEN_DARK)
            self.ui_button((x+236,y+11,78,45),'1個','ship',(c.id,1),disabled=qty<1,size=17)
            self.ui_button((x+324,y+11,82,45),'全部','ship',(c.id,-1),disabled=qty<1,size=17)
        text(self.stage,self.fonts,f'合計収穫 {self.state["harvest_total"]} 個  /  合計出荷 {self.state["stats"]["shipped"]} 個',
             (218,644),17,BROWN,True)

    def draw_inventory(self):
        self.overlay_panel('種と倉庫  /  INVENTORY','種を選択して、畑の近くで E キーで植えましょう。')
        for i,c in enumerate(CROPS):
            col,row=i%3,i//3
            x,y=206+col*295,187+row*107
            active=c.id==self.selected
            box(self.stage,(x,y,277,94),(197,223,156) if active else CREAM,GOLD if active else BROWN,6,3)
            self.assets.draw_crop(self.stage,c.id,(x+9,y+15,62,62))
            text(self.stage,self.fonts,c.name,(x+78,y+7),18,INK,True,max_width=183)
            text(self.stage,self.fonts,f'種：{self.state["seeds"][c.id]}    倉庫：{self.state["warehouse"][c.id]}',(x+78,y+35),15,BROWN,True)
            text(self.stage,self.fonts,'選択中' if active else 'クリックで選択',(x+78,y+64),14,GREEN_DARK,True)
            self.register('pick_crop',(x,y,277,94),c.id)
        text(self.stage,self.fonts,'Q / R で種切替、数字1〜9でも選べます。',(218,642),16,GREEN_DARK)

    def draw_missions(self):
        self.overlay_panel('ミッション  /  QUEST BOARD','畑と釣りの両方に挑戦しよう。条件を満たすと報酬を受け取れます。')
        portion=MISSIONS[self.mission_page*7:(self.mission_page+1)*7]
        for i,mission in enumerate(portion):
            mid,name,description,stat,target,reward=mission
            y=166+i*64
            owned=mid in self.state['missions_claimed']
            prog,goal=mission_progress(self.state,mid)
            box(self.stage,(210,y,859,57),CREAM,BROWN,5,2)
            text(self.stage,self.fonts,name,(223,y+6),19,INK,True)
            text(self.stage,self.fonts,description,(223,y+30),15,GREEN_DARK)
            text(self.stage,self.fonts,f'{prog}/{goal}',(779,y+17),17,INK,True)
            text(self.stage,self.fonts,f'+{reward}G',(855,y+18),15,BROWN,True)
            if owned:
                text(self.stage,self.fonts,'受取済',(987,y+17),17,GREEN_DARK,True)
            else:
                self.ui_button((971,y+7,89,42),'受け取る','claim',mid,disabled=prog<goal,size=15)
        text(self.stage,self.fonts,f'{self.mission_page+1} / {(len(MISSIONS)-1)//7+1} ページ',(640,632),18,GREEN_DARK,True,True)
        self.ui_button((365,614,153,43),'前のページ','mission_page',-1,disabled=self.mission_page==0,size=17)
        self.ui_button((766,614,153,43),'次のページ','mission_page',1,
                       disabled=(self.mission_page+1)*7>=len(MISSIONS),size=17)

    def draw_fishing(self):
        self.overlay_panel('アンベラ湖  /  FISHING','W / ↑ で上へ、S / ↓ で下へ。魚に合わせながら SPACE を押し続けて巻こう。')
        r=self.fishing_round
        if not r or not self.fishing_fish:return
        fish=self.fishing_fish
        text(self.stage,self.fonts,f'魚影：{fish.name}',(240,158),29,GREEN_DARK,True)
        text(self.stage,self.fonts,f'レア度 {fish.rarity}　★{fish.difficulty}',(240,207),20,BROWN,True)
        text(self.stage,self.fonts,'魚を追ってリールを巻こう！',(240,278),20,INK,True)
        text(self.stage,self.fonts,'魚とウキが重なっていると',(240,319),18,INK)
        text(self.stage,self.fonts,'釣りゲージが増えます。',(240,346),18,INK)
        text(self.stage,self.fonts,'離れたまま巻くと糸が切れる！',(240,393),18,RED,True)
        text(self.stage,self.fonts,'SPACE を離せば糸の負担は回復。',(240,425),17,INK)
        rect=pygame.Rect(608,192,110,365)
        box(self.stage,rect,(77,137,167),(40,85,112),6,5)
        for offset in range(10,rect.h,36):
            pygame.draw.line(self.stage,(94,156,176),(rect.x+5,rect.y+offset),(rect.right-5,rect.y+offset),2)
        yy=lambda f:int(rect.y+16+f*(rect.h-32))
        tolerance=.19-(fish.difficulty-1)*.019
        range_h=int(tolerance*(rect.h-32))
        bob_y=yy(r.bobber_y)
        pygame.draw.rect(self.stage,(141,226,153),(rect.x+10,bob_y-range_h,rect.w-20,range_h*2))
        pygame.draw.rect(self.stage,(255,241,195),(rect.x+7,bob_y-8,rect.w-14,16))
        fish_y=yy(r.fish_y)
        pygame.draw.ellipse(self.stage,fish.color,(rect.x+28,fish_y-13,55,26))
        pygame.draw.polygon(self.stage,fish.color,[(rect.x+28,fish_y),(rect.x+9,fish_y-15),(rect.x+9,fish_y+15)])
        pygame.draw.circle(self.stage,(42,48,45),(rect.x+69,fish_y-4),3)
        text(self.stage,self.fonts,'釣れるまで',(759,206),21,INK,True)
        bar(self.stage,pygame.Rect(755,248,267,29),r.progress/100,(121,204,117),(67,97,60))
        text(self.stage,self.fonts,f'{int(r.progress)} %',(858,289),23,GREEN_DARK,True)
        text(self.stage,self.fonts,'糸の負担',(759,348),21,INK,True)
        bar(self.stage,pygame.Rect(755,385,267,29),r.tension/100,(206,87,72),(97,51,44))
        text(self.stage,self.fonts,f'{int(r.tension)} %',(858,425),23,RED,True)
        text(self.stage,self.fonts,f'残り {math.ceil(r.remaining)} 秒',(860,515),24,BROWN,True,True)
        text(self.stage,self.fonts,'Esc：釣りを中断して戻る',(640,613),18,GREEN_DARK,True,True)

    def draw_fishing_result(self):
        self.overlay_panel('釣りの結果  /  RESULT','何度でも釣りに挑戦できます。')
        won=self.fishing_outcome=='caught'
        title=f'{self.fishing_fish.name} を釣り上げた！' if won else '魚に逃げられてしまった！'
        text(self.stage,self.fonts,title,(640,257),36,GREEN_DARK if won else RED,True,True)
        if won:
            text(self.stage,self.fonts,f'レア度：{self.fishing_fish.rarity}    魚市場で {self.fishing_fish.price} G',
                 (640,321),21,BROWN,True,True)
            text(self.stage,self.fonts,f'釣った魚の合計：{self.state["stats"]["fish_caught"]} 匹',
                 (640,364),20,INK,False,True)
        else:
            text(self.stage,self.fonts,'魚の動きに合わせてウキを動かし、糸の負担が増えたらSPACEを離そう。',
                 (640,348),18,INK,False,True,max_width=800)
        self.ui_button((294,479,322,68),'もう一度釣る','fish_again',size=25)
        self.ui_button((652,479,322,68),'マップへ戻る','close',size=25)

    def draw_fish_market(self):
        self.overlay_panel('湖畔の魚市場  /  FISH MARKET','釣った魚をここで売れます。魚の価格は今回追加した試作用です。')
        text(self.stage,self.fonts,f'所持金：{self.state["coins"]:,} G',(830,156),23,BROWN,True)
        for i,f in enumerate(FISH):
            x,y=224+(i%2)*431,196+(i//2)*105
            box(self.stage,(x,y,407,94),CREAM,BROWN,7,3)
            pygame.draw.ellipse(self.stage,f.color,(x+14,y+22,55,28))
            pygame.draw.polygon(self.stage,f.color,[(x+18,y+35),(x+3,y+23),(x+3,y+47)])
            text(self.stage,self.fonts,f.name,(x+81,y+10),19,INK,True,max_width=175)
            qty=self.state['fish_inventory'][f.id]
            text(self.stage,self.fonts,f'{f.rarity} / {f.price} G / 在庫 {qty}',(x+82,y+39),15,GREEN_DARK)
            self.ui_button((x+229,y+59,78,29),'1匹','fish_sell',(f.id,1),disabled=qty<1,size=14)
            self.ui_button((x+316,y+59,78,29),'全部','fish_sell',(f.id,-1),disabled=qty<1,size=14)
        text(self.stage,self.fonts,f'釣った魚：{self.state["stats"]["fish_caught"]}匹  /  販売した魚：{self.state["stats"]["fish_sold"]}匹',
             (643,632),19,GREEN_DARK,True,True)

    def draw_story(self):
        if not self.story_event:
            return
        node=self.story_event
        self.overlay_panel(node.get('title','湖畔の物語'),'後からこの会話データにイベントを追加できます。')
        box(self.stage,(232,189,811,352),PALE,GREEN_DARK,10,4)
        text(self.stage,self.fonts,node.get('speaker','村の人'),(271,223),32,BROWN,True)
        paragraph=node['lines'][self.story_line] if self.story_line<len(node['lines']) else ''
        # automatic line wrap with Japanese characters, without splitting Unicode code points
        available=720
        lines=[]; current=''
        for char in paragraph:
            trial=current+char
            if self.fonts.get(24).size(trial)[0]>available and current:
                lines.append(current);current=char
            else:current=trial
        if current:lines.append(current)
        for i,line in enumerate(lines[:5]):
            text(self.stage,self.fonts,line,(274,316+i*42),24,INK)
        text(self.stage,self.fonts,f'{self.story_line+1} / {len(node["lines"])}',(866,533),17,GREEN_DARK)
        self.ui_button((447,578,385,63),'つづきを読む  ▶','next_story',size=23)

    def draw_notices(self):
        self.overlay_panel('牧場のお知らせ / NEWS', '更新情報・イベント・運営からのお知らせを掲載します。')
        notices = public_view(self.notice_feed)
        total_pages = max(1, (len(notices) + 4)//5)
        self.notice_page = max(0, min(total_pages-1, self.notice_page))
        visible = notices[self.notice_page*5:(self.notice_page+1)*5]
        for index, n in enumerate(visible):
            x, y = 205, 166 + index*80
            selected = n['id'] == self.notice_selection
            fill = (213,234,183) if selected else CREAM
            box(self.stage, (x,y,361,72), fill, GOLD if selected else BROWN, 6, 2)
            unread = '● ' if n['id'] not in self.notice_seen else ''
            kind = {'news':'お知らせ','update':'更新','event':'イベント','maintenance':'メンテ'}[n['category']]
            text(self.stage,self.fonts, unread + kind + (' / 重要' if n['pinned'] else ''), (x+12,y+8),15,RED if unread else GREEN_DARK,True,max_width=335)
            text(self.stage,self.fonts,n['title'], (x+12,y+35),17,INK,True,max_width=335)
            self.register('notice_pick',(x,y,361,72),n['id'])
        box(self.stage,(585,164,481,408),WHITE,BROWN,7,3)
        current = next((n for n in notices if n['id']==self.notice_selection), None)
        if current:
            text(self.stage,self.fonts,current['title'],(603,181),23,BROWN,True,max_width=439)
            text(self.stage,self.fonts,current['published_at'] or '公開日未設定',(604,222),15,GREEN_DARK)
            pygame.draw.line(self.stage,BROWN,(603,249),(1046,249),2)
            all_lines = self.wrap_notice(current['body'], 437, 18, 150)
            max_offset = max(0, len(all_lines)-8)
            self.notice_line_offset = min(self.notice_line_offset, max_offset)
            for i,line in enumerate(all_lines[self.notice_line_offset:self.notice_line_offset+8]):
                text(self.stage,self.fonts,line,(605,271+i*26),18,INK)
            if max_offset:
                text(self.stage,self.fonts,f'{self.notice_line_offset+1} / {max_offset+1}',(615,482),13,GREEN_DARK)
            self.ui_button((603,520,64,43),'▲','notice_scroll',-3,disabled=self.notice_line_offset<=0,size=19)
            self.ui_button((673,520,64,43),'▼','notice_scroll',3,disabled=self.notice_line_offset>=max_offset,size=19)
            if current['url']:
                self.ui_button((747,519,295,43),'公式配布ページを見る','open_release_page',current['url'],size=17)
        else:
            text(self.stage,self.fonts,'公開中のお知らせはまだありません。',(642,275),20,INK)
        text(self.stage,self.fonts,f'{self.notice_page+1}/{total_pages} ページ', (393,598),17,GREEN_DARK,True,True)
        self.ui_button((211,583,103,38),'前へ','notice_page',-1,disabled=self.notice_page==0,size=16)
        self.ui_button((469,583,102,38),'次へ','notice_page',1,disabled=self.notice_page==total_pages-1,size=16)
        self.ui_button((690,588,317,43),'最新情報を再読み込み','notices_refresh',size=18)
        text(self.stage,self.fonts,self.notice_status,(635,646),15,GREEN_DARK,False,True,max_width=820)

    def draw_pause(self):
        self.overlay_panel('ポーズ  /  MENU','ゲームを閉じている間も畑の成長は進みます。')
        unseen = unread_count(self.notice_feed, self.notice_seen)
        labels = [('ゲームに戻る','resume',None),('設定','settings',None),
                  ('種と倉庫','overlay','inventory'),('ミッション','overlay','missions'),
                  ('セーブ管理・操作説明','overlay','help'),('お知らせ'+(' NEW' if unseen else ''),'notices',None)]
        if self.online_client:
            labels.append(('チャットを開く T','chat',None))
        labels.append(('タイトルへ戻る','return_title',None))
        for i,(label,act,val) in enumerate(labels):
            x = 380 + (i%2)*275
            y = 172 + (i//2)*94
            self.ui_button((x,y,252,66),label,act,val,size=18)
        text(self.stage,self.fonts,'F5 セーブ  /  F6 書き出し  /  F7 読み込み',
             (640,564),18,GREEN_DARK,False,True)
        if self.online_client:
            text(self.stage,self.fonts,f'オンライン {self.lan_address()}:{PORT} / PIN {self.room_pin}',
                 (640,591),15,GREEN_DARK,True,True)
        self.ui_button((492,615,296,44),'今すぐセーブ','save',size=18)

    def draw_help(self):
        self.overlay_panel('遊び方・データ管理','マップと各施設は今回の新規仮実装です。元デザインを再現したものではありません。')
        lines=[
            'WASD / 矢印：歩く　　E / Space：調べる・植える・収穫する',
            'I / Tab：種と倉庫　 M：ミッション　 F9：緊急脱出　 T：チャット（オンライン）',
            'Q / R：選択する種を変更（インベントリからも選択可）',
            'たね屋：右上の建物。近くでEを押すと種を購入できます。',
            '出荷所：右下の建物。収穫した作物を出荷してGを獲得。',
            '掲示板：マップ中央。ミッションを進めて報酬を獲得。',
            '湖の桟橋：南西の湖のそば。Eで釣り開始！ ↑↓とSPACEで釣る。',
            '魚市場：南の屋台。釣った魚を売る。近くのナギと会話できます。',
            '現実20秒＝ゲーム内1分。閉じている間も作物は成長します。',
        ]
        for i,line in enumerate(lines):
            text(self.stage,self.fonts,line,(220,161+i*42),17,INK,max_width=844)
        text(self.stage,self.fonts,f'元画像：{len(self.assets.images)}/12  /  元の画像は変更しません。',(220,538),17,GREEN_DARK,True)
        actions=[('保存','save'),('書き出し','export_save'),('読み込み','import_save'),('元画像ZIP','import_assets')]
        for i,(label,act) in enumerate(actions):
            self.ui_button((216+217*i,574,205,59),label,act,size=19)
        text(self.stage,self.fonts,'Windowsの通常セーブ先：%APPDATA%\\AmberaFarm\\save.json',(220,648),16,GREEN_DARK)

    def draw_confirm(self):
        self.overlay_panel('新しい牧場を始めますか？','今の所持金・種・畑・ミッション・収穫履歴は初期化されます。')
        text(self.stage,self.fonts,'既存データを消す前に「書き出し」でバックアップできます。',
             (640,245),25,RED,True,True)
        self.ui_button((321,370,293,78),'新規開始する','confirm_new',size=23)
        self.ui_button((657,370,293,78),'キャンセル','close',size=23)
        self.ui_button((470,494,338,62),'セーブを書き出す','export_save',size=22)

    def draw_chat(self):
        self.overlay_panel('オンライン チャット', 'メッセージは同じ部屋の参加者だけに表示（再接続後は残りません）。')
        box(self.stage, (228, 174, 826, 340), WHITE, BROWN, 7, 3)
        messages = self.chat_log[-9:]
        for i, m in enumerate(messages):
            label = f'{m.get("name", "Player")}: {m.get("text", "")}'
            text(self.stage, self.fonts, label, (245, 187 + i*35), 18,
                 GREEN_DARK if i%2 else INK, max_width=793)
        box(self.stage, (232, 532, 817, 55), PALE, GOLD, 5, 3)
        text(self.stage, self.fonts, (self.chat_text or 'ここに入力...') + '｜',
             (247, 546), 19, INK, max_width=780)
        text(self.stage, self.fonts, 'Enter 送信   /   Esc 閉じる   /   最大160文字',
             (640, 625), 17, GREEN_DARK, False, True)

    def draw_join(self):
        self.overlay_panel('オンラインに参加','ホストのIPアドレス、ポート、6桁のPINを入力してください。LANの接続を推奨します。')
        info=[('address','ホストのIP:PORT 例 192.168.1.10:47821'),('pin','部屋のPIN'),('name','プレイヤー名')]
        for i,(key,caption) in enumerate(info):
            y=207+i*112
            text(self.stage,self.fonts,caption,(264,y),20,BROWN,True)
            active=key==self.join_field
            box(self.stage,(264,y+31,748,57),WHITE,GOLD if active else BROWN,6,3)
            value=self.join_fields[key] + ('▏' if active else '')
            text(self.stage,self.fonts,value,(282,y+45),22,INK,max_width=710)
            self.register('join_field',(264,y+31,748,57),key)
        self.ui_button((460,570,360,58),'部屋に参加する','join_room',size=23)
        text(self.stage,self.fonts,'Tabで入力欄を切替・Enterで接続  |  通信はLAN向けの試験版です。',
             (640,650),15,GREEN_DARK,False,True)

    def apply_brightness(self):
        value=self.settings['brightness']
        if value<100:
            shade=pygame.Surface((BASE_W,BASE_H),pygame.SRCALPHA)
            shade.fill((0,0,0,round((100-value)/100*205)))
            self.stage.blit(shade,(0,0))
        elif value>100:
            shade=pygame.Surface((BASE_W,BASE_H))
            shade.fill((min(76,int((value-100)*2.4)),)*3)
            self.stage.blit(shade,(0,0),special_flags=pygame.BLEND_RGB_ADD)

    def render(self):
        self.buttons.clear()
        if self.scene=='title':self.draw_title()
        else:
            self.draw_world()
            self.hud()
        if self.modal:
            self.buttons.clear()
            if self.modal=='join':self.draw_join()
            elif self.modal=='chat':self.draw_chat()
            elif self.modal=='notices':self.draw_notices()
            elif self.modal=='settings':self.draw_settings()
            elif self.modal=='shop':self.draw_shop()
            elif self.modal=='shipping':self.draw_shipping()
            elif self.modal=='inventory':self.draw_inventory()
            elif self.modal=='missions':self.draw_missions()
            elif self.modal=='pause':self.draw_pause()
            elif self.modal=='help':self.draw_help()
            elif self.modal=='confirm_new':self.draw_confirm()
            elif self.modal=='fishing':self.draw_fishing()
            elif self.modal=='fishing_result':self.draw_fishing_result()
            elif self.modal=='fish_market':self.draw_fish_market()
            elif self.modal=='story':self.draw_story()
        self.apply_brightness()
        if self.screen.get_size()==(BASE_W,BASE_H):
            self.screen.blit(self.stage,(0,0))
        else:
            self.screen.blit(pygame.transform.scale(self.stage,self.screen.get_size()),(0,0))
        pygame.display.flip()

    def run(self):
        ticker=pygame.time.Clock()
        while self.running:
            dt=ticker.tick(45)/1000
            self.events()
            self.poll_notices()
            if self.scene=='world' and self.modal=='fishing':
                self.update_fishing(dt)
            if self.scene=='world' and self.modal is None:self.move(dt)
            if self.online_client:self.poll_network()
            elif self.scene=='world' and time.monotonic()-self.last_save_time>=30:self.persist(True)
            if self.update_status and (not self.message or time.monotonic()>self.message_until):
                self.say(self.update_status,9);self.update_status=''
            self.render()
        if self.online_client:self.stop_online()
        elif self.scene=='world':self.persist(True)
        pygame.quit()


def main():
    try:
        if '--smoke-test' in sys.argv:
            # Windows CI can verify packaged fonts, images, assets and title rendering
            # without opening an interactive game window or touching save files.
            os.environ['SDL_VIDEODRIVER'] = 'dummy'
            os.environ['SDL_AUDIODRIVER'] = 'dummy'
            probe = Game()
            if len(probe.assets.images) != 11:
                raise RuntimeError('Bundled crop sprites are missing')
            if len(probe.story_nodes) == 0:
                raise RuntimeError('Bundled story events are missing')
            probe.render()
            pygame.quit()
            return
        Game().run()
    except Exception:
        logfile=state_path().parent/'error.log'
        try:
            logfile.parent.mkdir(parents=True,exist_ok=True)
            logfile.write_text(traceback.format_exc(),encoding='utf-8')
        except OSError:pass
        traceback.print_exc()
        print('GAME ERROR. See: ',logfile,flush=True)
        sys.exit(1)


if __name__=='__main__':
    main()
