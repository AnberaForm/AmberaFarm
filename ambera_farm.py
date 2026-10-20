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
from collections import OrderedDict
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
from farm_mailbox import load as load_public_mail, fetch as fetch_public_mail
from v8_features import (init_v8, field_action, field_phase, restore_stamina, MAX_STAMINA, ITEMS,
                         buy_consumable, use_consumable, OUTFIT_COLORS, new_outfit,
                         time_of_day, active_event, EVENT_GOODS, exchange_event,
                         add_friend, receive_public_mail, duel_practice)

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
        self.render_cache = OrderedDict()

    def render(self, words, size, bold, color):
        """Cache stable Japanese UI text, bounded to avoid unbounded VRAM use."""
        key = (str(words), int(size), bool(bold), tuple(color))
        cached = self.render_cache.get(key)
        if cached is not None:
            self.render_cache.move_to_end(key)
            return cached
        surface = self.get(size, bold).render(str(words), True, color)
        self.render_cache[key] = surface
        if len(self.render_cache) > 768:
            self.render_cache.popitem(last=False)
        return surface

    def get(self, size: int, bold: bool = False):
        key = (size, bold)
        if key not in self.cache:
            font = pygame.font.Font(self.path, size)
            font.set_bold(bold)
            self.cache[key] = font
        return self.cache[key]


def text(surface, fonts, words, pos, size=18, color=INK, bold=False, centered=False, max_width=None):
    font = fonts.get(size, bold)
    result = fonts.render(str(words), size, bold, color)
    if max_width and result.get_width() > max_width:
        # フォントサイズだけ落とすことで極端に長い表記を収める。
        while size > 10 and result.get_width() > max_width:
            size -= 1
            result = fonts.render(str(words), size, bold, color)
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
FPS_CHOICES = (45, 60, 90, 120)
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
    initial = {'volume': 45, 'brightness': 100, 'resolution': 1, 'fullscreen': False, 'fps_limit': 60}
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
    if initial['fps_limit'] not in FPS_CHOICES:
        initial['fps_limit'] = 60
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
        pygame.display.set_caption('アンベラ牧場 - v8 大型アップデート')
        self.settings = load_settings()
        self.screen = None
        self.stage = pygame.Surface((BASE_W, BASE_H)).convert() if pygame.display.get_surface() else pygame.Surface((BASE_W, BASE_H))
        self.set_resolution()
        self.stage = pygame.Surface((BASE_W, BASE_H)).convert()
        self.world_layer = pygame.Surface((BASE_W, VIEW_HEIGHT)).convert()
        self.ground_layer = self.make_ground_layer()
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
        init_v8(self.state)
        self.selected = self.state['selected_crop']
        self.inventory_page='seeds'
        self.clothing_preview=False
        self.large_map=False
        self.friend_input=''
        self.name_draft=self.state['player_name']
        self.name_cursor=len(self.name_draft)
        self.name_anchor=None
        self.chat_cursor=0
        self.chat_anchor=None
        self.chat_scroll=0
        self.chat_mode='local'
        self.join_cursor={'address':0,'pin':0,'name':0}
        self.interior=None
        self.duel_mode='guess'
        self.duel_stake=0
        self.duel_state=None
        self.duel_target=0
        self.duel_started=0
        self.duel_choice=0
        self.mail_items=load_public_mail()
        self.mail_queue=Queue()
        self.mail_busy=False
        self.fetch_mails()
        self.update_available=False
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
        self.host_offline_state=None
        self.online_client = None
        self.online_guest = False
        self.offline_state = None
        self.remote_players = []
        self.friend_invites=[]
        self.room_pin = ''
        self.last_network_pos = 0
        self.remote_targets = {}
        self.display_fps = 0.0
        self.show_performance = False
        self.join_fields = {'address':'127.0.0.1:47821','pin':'','name':self.state['player_name']}
        self.join_field = 'address'
        self.online_profile_received = False
        self.chat_log = []
        self.chat_last_seq = 0
        self.chat_text = ''
        self.held_keys = set()
        self.ime_composing=False
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

    def fetch_mails(self):
        if self.mail_busy:return
        self.mail_busy=True
        def worker():
            try:self.mail_queue.put(('ok',fetch_public_mail()))
            except Exception as exc:self.mail_queue.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def poll_mails(self):
        try:
            while True:
                status,value=self.mail_queue.get_nowait()
                self.mail_busy=False
                if status=='ok':self.mail_items=value
        except Empty:pass

    def load_mail_campaigns(self):
        # Public community rewards, not private messages. Never accept a local
        # 'sender' as proof of administrator authority.
        source = ROOT / 'data' / 'mail_campaigns.json'
        try:
            obj=json.loads(source.read_text(encoding='utf-8-sig'))
            return [m for m in obj.get('campaigns', []) if isinstance(m, dict)][:40]
        except (OSError,ValueError,UnicodeError):
            return []

    def field_interaction(self, index):
        if self.online_client:
            self.online_client.action('field_v8',{'index':index,'crop':self.selected})
            return
        result=field_action(self.state,index,self.selected)
        messages={'till':'クワで畑を耕しました！  次は水やり。',
                  'water':'水をあげました！  次は種をまこう。',
                  'plant':f'{CROP_BY_ID[self.selected].name}を植えました！',
                  'harvest':'収穫成功！ 倉庫に入りました。',
                  'growing':'作物は成長中。畑に近づくと残り時間が確認できます。',
                  'tired':'スタミナ不足！ 雑貨屋の回復アイテムを使おう。',
                  'seeds':'種が足りません。たね屋で購入してください。',
                  'invalid':'畑の操作ができません。'}
        if result in ('till','water','plant','harvest'):
            self.persist(True)
            self.sound.play('harvest' if result=='harvest' else 'plant')
        self.say(messages[result], 6)

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
                self.update_available=bool(info)
                self.update_status = (f'新バージョン {info["version"]} が公開中！ 終了して再起動すると更新できます。'
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
            self.host_offline_state=copy.deepcopy(self.state)
            self.online_server=RoomServer(self.state,
                self.save_file.with_name('coop_room_latest.json'),port=PORT,
                story_nodes=self.story_nodes,fresh=True)
            self.room_pin=self.online_server.pin
            self.online_client=RoomClient('127.0.0.1:'+str(self.online_server.port),self.room_pin,self.state['player_name'],profile=self.state,host_token=self.online_server.host_token)
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
            if self.host_offline_state is not None:
                # Room plots are separate; host's private progression is retained.
                previous=self.host_offline_state
                current=self.state
                for k,value in current.items():
                    if k not in ('plots','plot_preparation','created_at','player','version'):
                        previous[k]=copy.deepcopy(value)
                self.state=previous
                self.host_offline_state=None
                self.persist(True)
        if self.online_guest:
            self.state = self.offline_state if self.offline_state is not None else self.state
            self.player = list(self.state['player'])
        if self.modal == 'chat':
            pygame.key.stop_text_input()
        self.offline_state = None
        self.online_profile_received = False
        self.online_guest = False
        self.remote_players = []
        self.remote_targets = {}
        self.room_pin = ''
        self.chat_log = []
        self.chat_last_seq = 0
        self.chat_text = ''
        self.duel_state=None
        self.held_keys.clear()

    def update_remote_positions(self, players, dt=0):
        """Receive authoritative positions without making remote sprites jump."""
        if not self.online_client or not isinstance(players, list):
            return
        known = {p['id']: p for p in self.remote_players if isinstance(p, dict) and 'id' in p}
        targets = {}
        for player in players:
            if not isinstance(player, dict) or player.get('id') == self.online_client.id:
                continue
            pid = player.get('id')
            try:
                x, y = float(player['x']), float(player['y'])
            except (ValueError, KeyError, TypeError):
                continue
            if not isinstance(pid, str) or not math.isfinite(x) or not math.isfinite(y):
                continue
            targets[pid] = (x, y)
            if pid not in known:
                known[pid] = dict(player)
            else:
                known[pid]['name'] = player.get('name', known[pid].get('name', 'Player'))
                known[pid]['uid'] = player.get('uid', known[pid].get('uid', ''))
        self.remote_targets = targets
        self.remote_players = [known[pid] for pid in targets]

    def interpolate_remote_positions(self, dt):
        factor = 1 - math.exp(-min(.1, max(0, dt)) * 17)
        for player in self.remote_players:
            target = self.remote_targets.get(player['id'])
            if target is None:
                continue
            dx, dy = target[0] - player['x'], target[1] - player['y']
            if dx * dx + dy * dy > 160**2:
                player['x'], player['y'] = target
            else:
                player['x'] += dx * factor
                player['y'] += dy * factor

    def sync_position(self, server_position):
        if (not isinstance(server_position, list) or len(server_position) != 2
                or not can_stand(*server_position)):
            return
        delta = [server_position[i] - self.player[i] for i in (0, 1)]
        distance = math.hypot(*delta)
        if 14 < distance < 650:
            step = min(5.0, distance * .07)
            candidate = [self.player[i] + delta[i] / distance * step for i in (0, 1)]
            if can_stand(*candidate):
                self.player = candidate
        elif distance >= 650:
            self.say('通信位置にズレがあります。F9で安全に位置を修正できます。', 5)

    def receive_chat(self, messages, replace=False):
        if not isinstance(messages, list):
            return
        if replace:
            self.chat_log = messages[-30:]
        else:
            known = {m.get('seq') for m in self.chat_log if isinstance(m, dict)}
            self.chat_log = (self.chat_log + [m for m in messages if isinstance(m, dict)
                                                   and m.get('seq') not in known])[-30:]
        if messages:
            newest = messages[-1]
            seq = newest.get('seq', 0)
            if seq > self.chat_last_seq and self.chat_last_seq and self.modal != 'chat':
                self.say(f'CHAT {newest.get("name", "Player")}: {newest.get("text", "")}', 7)
            self.chat_last_seq = max(self.chat_last_seq, seq)

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
                    self.state = init_v8(incoming)
                    self.online_profile_received = True
                    if isinstance(packet.get('story_nodes'), list):
                        self.story_nodes = packet['story_nodes']
                    self.duel_state=packet.get('duel')
                    self.friend_invites=packet.get('friend_invites',[])
                    self.update_remote_positions(packet.get('players', []))
                    self.sync_position(packet.get('self_pos'))
                    self.receive_chat(packet.get('chat', []), replace=True)
                except (KeyError, TypeError, ValueError):
                    pass
            elif packet.get('type') == 'positions':
                self.update_remote_positions(packet.get('players', []))
                self.sync_position(packet.get('self_pos'))
            elif packet.get('type') == 'chat_delta':
                self.receive_chat(packet.get('chat', []))
            elif packet.get('type') == 'result':
                self.duel_state=packet.get('duel',self.duel_state)
                self.friend_invites=packet.get('friend_invites',self.friend_invites)
                if isinstance(packet.get('state'), dict):
                    incoming = packet['state']
                    incoming['selected_crop'] = self.selected
                    self.state = init_v8(incoming)
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
        if time.monotonic() - self.last_network_pos >= 1.0 / 12.0:
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
            self.chat_mode='local'
        else:
            self.chat_mode='online'
        self.chat_text = ''
        self.chat_cursor=0
        self.chat_anchor=None
        self.chat_scroll=0
        self.modal = 'chat'
        self.held_keys.clear()
        pygame.key.start_text_input()
        pygame.key.set_repeat(350, 36)

    def close_chat(self, send=False):
        if send and self.chat_text.strip():
            if self.online_client:
                self.online_client.chat(self.chat_text)
            else:
                msg={'name':self.state['player_name'],'text':self.chat_text,'at':time.time()}
                self.state['local_chat'].append(msg)
                self.state['local_chat']=self.state['local_chat'][-40:]
                self.persist(True)
        pygame.key.stop_text_input()
        pygame.key.set_repeat()
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
        self.state = init_v8(new_state())
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
                self.state = init_v8(loaded)
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
        if not pygame.key.get_focused() or self.ime_composing:
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
            ('general_store',INTERACTION_POINTS['general_store'],88),('hall',INTERACTION_POINTS['hall'],88),
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
            self.field_interaction(data)
        elif action=='home':self.interior='home';self.modal='interior'
        elif action=='shop':self.interior='shop';self.modal='interior'
        elif action=='shipping':self.interior='shipping';self.modal='interior'
        elif action=='fish_market':self.interior='fish_market';self.modal='interior'
        elif action=='missions':self.modal='missions';self.mission_page=0
        elif action=='general_store':self.interior='general_store';self.modal='interior'
        elif action=='hall':self.interior='hall';self.modal='interior'
        elif action=='fishing':self.start_fishing()
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
        if action=='field':self.field_interaction(int(val))
        elif action=='inventory_page':self.inventory_page=val
        elif action=='interior_open':self.modal=val
        elif action=='open_interior':self.interior=val;self.modal='interior'
        elif action=='shop_item':
            if self.online_client:self.online_client.action('buy_item',val)
            elif buy_consumable(self.state,val):self.persist(True);self.say('回復アイテムを買いました！')
            else:self.say('お金が足りません。')
        elif action=='use_item':
            if self.online_client:self.online_client.action('use_item',val)
            elif use_consumable(self.state,val):self.persist(True);self.say('スタミナ回復！')
            else:self.say('使用できません。スタミナ・在庫を確認。')
        elif action=='name_edit':
            self.modal='name_edit';self.name_draft=self.state['player_name']
            self.name_cursor=len(self.name_draft);self.name_anchor=None
            pygame.key.start_text_input();pygame.key.set_repeat(350,36)
        elif action=='name_save':
            value=''.join(ch for ch in self.name_draft if ch.isprintable() and ch not in '\n\r\t').strip()[:18]
            if value:
                self.state['player_name']=value
                self.join_fields['name']=value
                self.persist(True)
            pygame.key.stop_text_input();pygame.key.set_repeat()
            self.modal='settings'
        elif action=='costume':self.modal='costume'
        elif action=='costume_color':
            if self.online_client:self.online_client.action('costume_color',val);return
            key=val
            self.state['outfit_draft'][key]=(self.state['outfit_draft'][key]+1)%len(OUTFIT_COLORS)
        elif action=='costume_save':
            if self.online_client:self.online_client.action('costume_save',None);return
            if new_outfit(self.state):self.persist(True);self.say('マイ衣装を保存しました！')
            else:self.say('衣装の最大数は20です。')
        elif action=='costume_equip':
            if self.online_client:self.online_client.action('costume_equip',val);return
            self.state['outfit_index']=val;self.persist(True)
        elif action=='event':self.modal='event'
        elif action=='event_trade':
            if self.online_client:self.online_client.action('event_trade',val);return
            if exchange_event(self.state,val):self.persist(True);self.say('限定アイテムを交換しました！')
            else:self.say('交換できません。開催期間とメダルを確認。')
        elif action=='mail':self.modal='mail';self.fetch_mails()
        elif action=='mail_claim':
            if self.online_client:self.online_client.action('mail_claim',val);return
            mail=next((m for m in self.mail_items if m.get('id')==val),None)
            if mail and receive_public_mail(self.state,mail):self.persist(True);self.say('メールのアイテムを受け取りました！')
            else:self.say('受取済み、または無効なメールです。')
        elif action=='friends':self.modal='friends'
        elif action=='friend_request':
            if self.online_client:self.online_client.action('friend_request',val)
        elif action=='friend_accept':
            if self.online_client:self.online_client.action('friend_accept',val)
        elif action=='friend_add':
            if add_friend(self.state,val):self.persist(True);self.say('フレンドメモに追加しました。')
            else:self.say('追加できません。')
        elif action=='duel':self.modal='duel';self.duel_mode='guess';self.duel_choice=0;self.duel_target=random.randrange(1,4);self.duel_started=time.monotonic()
        elif action=='duel_kind':self.duel_mode=val;self.duel_target=random.randrange(1,4) if val=='guess' else random.random();self.duel_started=time.monotonic();self.duel_choice=0
        elif action=='duel_stake':self.duel_stake=val
        elif action=='duel_invite':
            if self.online_client:self.online_client.action('duel_challenge',
                {'target':val,'kind':self.duel_mode,'stake':self.duel_stake})
        elif action=='duel_accept':
            if self.online_client:self.online_client.action('duel_accept',None)
        elif action=='duel_reject':
            if self.online_client:self.online_client.action('duel_reject',None)
        elif action=='duel_submit':
            if self.online_client:self.online_client.action('duel_move',val)
        elif action=='duel_try':
            attempt=(val if self.duel_mode=='guess' else (time.monotonic()-self.duel_started)%1)
            target=self.duel_target if self.duel_mode!='reaction' else .6
            good=duel_practice(self.duel_mode,attempt,target)
            self.say(('練習成功！' if good else '惜しい！もう一度！')+' 対人戦・賭けは未対応です。',6)
            self.duel_target=random.randrange(1,4) if self.duel_mode=='guess' else random.random();self.duel_started=time.monotonic()
        elif action=='map':self.modal='map'
        elif action=='help_menu':self.modal='help'
        elif action=='data_menu':self.modal='data_manage'
        elif action=='notices':self.open_notices()
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
        elif action=='join_dialog':
            self.modal='join'
            self.join_cursor={k:len(v) for k,v in self.join_fields.items()}
            pygame.key.start_text_input();pygame.key.set_repeat(350,36)
        elif action=='join_field':self.join_field=val
        elif action=='join_room':
            pygame.key.stop_text_input();pygame.key.set_repeat()
            self.join_room()
        elif action=='story_editor':self.say('管理者用ツールはゲームから分離されました。')
        elif action=='chat':self.toggle_chat()
        elif action=='chat_scroll':self.chat_scroll=max(0,self.chat_scroll+val)
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
            else:
                if self.modal in ('join','name_edit'):pygame.key.stop_text_input();pygame.key.set_repeat()
                self.modal=None
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
        elif action=='fps_limit':
            current = FPS_CHOICES.index(self.settings['fps_limit'])
            self.settings['fps_limit'] = FPS_CHOICES[(current+val) % len(FPS_CHOICES)]
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

    def edit_text_event(self, event, value, cursor, anchor, limit=160):
        """Text-edit cursor, selection, auto-repeat and Ctrl+A, for Pygame TEXTINPUT."""
        lo,hi=sorted((cursor,anchor if anchor is not None else cursor))
        ctrl=bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
        shift=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        if event.type==pygame.TEXTINPUT:
            incoming=''.join(ch for ch in event.text if ch.isprintable() and ch not in '\r\n')
            result=(value[:lo]+incoming+value[hi:])[:limit]
            cursor=min(len(result),lo+len(incoming))
            return result,cursor,None
        if event.type!=pygame.KEYDOWN:return value,cursor,anchor
        if ctrl and event.key==pygame.K_a:return value,len(value),0
        if event.key in (pygame.K_LEFT,pygame.K_RIGHT,pygame.K_HOME,pygame.K_END):
            new=(max(0,cursor-1) if event.key==pygame.K_LEFT else
                 min(len(value),cursor+1) if event.key==pygame.K_RIGHT else
                 0 if event.key==pygame.K_HOME else len(value))
            return value,new,(anchor if anchor is not None else cursor) if shift else None
        if event.key==pygame.K_BACKSPACE:
            if lo==hi:lo=max(0,lo-1)
            return value[:lo]+value[hi:],lo,None
        if event.key==pygame.K_DELETE:
            if lo==hi:hi=min(len(value),hi+1)
            return value[:lo]+value[hi:],lo,None
        return value,cursor,anchor

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
                self.ime_composing=False
            elif event.type==pygame.TEXTEDITING and self.scene=='world' and self.modal is None:
                self.ime_composing=bool(event.text)
                self.held_keys.clear()
            elif event.type==pygame.TEXTINPUT and self.scene=='world' and self.modal is None:
                self.ime_composing=False
                self.held_keys.clear()
            elif event.type==pygame.TEXTINPUT and self.modal=='chat':
                self.chat_text,self.chat_cursor,self.chat_anchor=self.edit_text_event(
                    event,self.chat_text,self.chat_cursor,self.chat_anchor)
            elif event.type==pygame.TEXTINPUT and self.modal=='name_edit':
                self.name_draft,self.name_cursor,self.name_anchor=self.edit_text_event(
                    event,self.name_draft,self.name_cursor,self.name_anchor,18)
            elif event.type==pygame.TEXTINPUT and self.modal=='join':
                k=self.join_field
                value=self.join_fields[k]
                value,cursor,_=self.edit_text_event(event,value,self.join_cursor[k],None,64)
                self.join_fields[k]=value;self.join_cursor[k]=cursor
            elif event.type==pygame.KEYDOWN:
                if event.key in tuple(getattr(pygame,k,-500) for k in ('K_BACKQUOTE','K_MODE','K_KANJI')):
                    self.ime_composing=False
                    self.held_keys.clear()
                if event.key in (pygame.K_w,pygame.K_a,pygame.K_s,pygame.K_d,
                                 pygame.K_UP,pygame.K_DOWN,pygame.K_LEFT,pygame.K_RIGHT):
                    self.held_keys.add(event.key)
                if self.modal=='name_edit':
                    if event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):self.do_action('name_save',None)
                    elif event.key==pygame.K_ESCAPE:
                        pygame.key.stop_text_input();pygame.key.set_repeat();self.modal='settings'
                    else:
                        self.name_draft,self.name_cursor,self.name_anchor=self.edit_text_event(
                            event,self.name_draft,self.name_cursor,self.name_anchor,18)
                    continue
                if self.modal=='chat':
                    if event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):self.close_chat(send=True)
                    elif event.key==pygame.K_ESCAPE:self.close_chat()
                    else:
                        self.chat_text,self.chat_cursor,self.chat_anchor=self.edit_text_event(
                            event,self.chat_text,self.chat_cursor,self.chat_anchor)
                    continue
                if self.modal=='join' and event.key not in (pygame.K_ESCAPE,pygame.K_F11):
                    if event.key==pygame.K_TAB:
                        order=['address','pin','name']
                        self.join_field=order[(order.index(self.join_field)+1)%len(order)]
                    elif event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):self.join_room()
                    else:
                        k=self.join_field
                        v,cur,_=self.edit_text_event(event,self.join_fields[k],self.join_cursor[k],None,64)
                        self.join_fields[k]=v;self.join_cursor[k]=cur
                    continue
                if event.key==pygame.K_F3:
                    self.show_performance=not self.show_performance
                elif event.key==pygame.K_F11:
                    self.do_action('fullscreen',None)
                elif event.key==pygame.K_F9 and self.scene=='world':self.rescue_player()
                elif event.key==pygame.K_F5 and self.scene=='world':self.persist()
                elif event.key==pygame.K_F6:self.export_save()
                elif event.key==pygame.K_F7:self.import_save()
                elif event.key==pygame.K_ESCAPE:
                    if self.modal=='story':self.next_story_line()
                    elif self.modal=='settings':self.do_action('settings_back',None)
                    elif self.modal is not None:
                        if self.modal in ('join','name_edit'):pygame.key.stop_text_input();pygame.key.set_repeat()
                        self.modal=None
                    elif self.scene=='world':self.modal='pause'
                elif self.modal=='story' and event.key in (pygame.K_e,pygame.K_SPACE,pygame.K_RETURN):
                    self.next_story_line()
                elif self.modal=='fishing_result' and event.key in (pygame.K_e,pygame.K_SPACE,pygame.K_RETURN):
                    self.modal=None
                elif self.scene=='world' and self.modal is None:
                    if event.key==pygame.K_t:self.toggle_chat()
                    elif event.key in (pygame.K_e,pygame.K_SPACE):self.interact()
                    elif event.key in (pygame.K_i,pygame.K_TAB):self.modal='inventory'
                    elif event.key==pygame.K_m:self.modal='missions'
                    elif event.key==pygame.K_h:self.modal='help'
                    elif event.key==pygame.K_f:self.modal='friends'
                    elif event.key==pygame.K_c:self.modal='costume'
                    elif event.key==pygame.K_b:self.modal='event'
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
        self.field_interaction(idx)

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
        roof_top=y+8
        roof_bottom=y+48
        pygame.draw.polygon(s,(122,63,48),((x+1,roof_bottom),(x+width//2,roof_top),(x+width-1,roof_bottom)))
        pygame.draw.line(s,(213,142,91),(x+10,roof_bottom-6),(x+width//2,roof_top+5),4)
        pygame.draw.line(s,(83,43,39),(x+width//2,roof_top+5),(x+width-10,roof_bottom-6),5)
        dx=int(door_pos[0]-self.camera[0]);dy=int(door_pos[1]-self.camera[1])
        pygame.draw.rect(s,(133,108,72),(dx-26,y+height,52,max(3,dy-(y+height)+10)))
        pygame.draw.rect(s,(94,56,47),(dx-20,y+height-55,40,55))
        pygame.draw.rect(s,(239,213,144),(dx+8,y+height-31,4,4))
        sign=(193,179,102) if kind=='shop' else (161,185,119)
        pygame.draw.rect(s,sign,(x+width//2-67,y+48,134,31),border_radius=2)
        text(s,self.fonts,name,(x+width//2,y+64),18,INK,True,True)

    def make_ground_layer(self):
        """Render terrain once. Moving the camera now uses a fast surface blit."""
        ground = pygame.Surface((WORLD_W * TILE, WORLD_H * TILE)).convert()
        ground.fill((86,147,76))
        for ty in range(WORLD_H):
            for tx in range(WORLD_W):
                x=tx*TILE;y=ty*TILE
                shade=(84,150,76) if (tx*13+ty*7)%7 else (93,160,82)
                pygame.draw.rect(ground,shade,(x,y,TILE,TILE))
                if (tx*149+ty*101)%13==0:
                    pygame.draw.rect(ground,(113,172,78),(x+7,y+9,5,3))
                    pygame.draw.rect(ground,(53,109,48),(x+11,y+8,3,9))
                if (tx*19+ty*11)%17==0:
                    pygame.draw.rect(ground,(166,189,95),(x+24,y+24,3,3))
                # Paths connecting home, fields, stores and mission board.
                on_horizontal=(ty in (9,10,11,20,21) and 7<=tx<=42)
                on_vertical=(tx in (22,23,24,35,36) and 10<=ty<=28)
                on_entrance=(37<=tx<=43 and ty in (13,14,27,28))
                if on_horizontal or on_vertical or on_entrance:
                    pygame.draw.rect(ground,(186,153,100),(x,y,TILE,TILE))
                    if (tx*11+ty*5)%9==0:pygame.draw.rect(ground,(165,132,85),(x+5,y+18,9,4))
                if 3<=tx<=13 and 26<=ty<=32:
                    pygame.draw.rect(ground,(71,128,164),(x,y,TILE,TILE))
                    if (tx*7+ty*3)%4==0:
                        pygame.draw.rect(ground,(116,181,185),(x+10,y+14,12,2))
        return ground

    def draw_world(self):
        w=self.world_layer
        self.camera_update()
        cx,cy=self.camera
        w.blit(self.ground_layer, (0, 0), pygame.Rect(int(cx), int(cy), BASE_W, VIEW_HEIGHT))
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
            if plot is None and self.state['plot_preparation'][idx] in (1,2):
                if self.state['plot_preparation'][idx]==2:
                    pygame.draw.rect(w,(76,124,168),(x-20,y-20,40,40),3)
                else:
                    pygame.draw.rect(w,(189,147,84),(x-21,y-21,42,42),3)
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
        outfit=self.state['outfits'][self.state['outfit_index']]
        pygame.draw.rect(w,OUTFIT_COLORS[outfit['shirt']],(px-9,py+1,18,17))
        pygame.draw.rect(w,(55,44,51),(px-7,py+15,5,8))
        pygame.draw.rect(w,(55,44,51),(px+3,py+15,5,8))
        pygame.draw.rect(w,(228,177,120),(px-7,py-15,15,17))
        pygame.draw.rect(w,OUTFIT_COLORS[outfit['hat']],(px-10,py-20,21,7))
        pygame.draw.rect(w,OUTFIT_COLORS[outfit['hat']],(px-13,py-17,27,4))
        if self.facing!='up':
            ex=-4 if self.facing!='right' else 4
            pygame.draw.rect(w,(47,45,40),(px+ex,py-8,3,3))
        if self.facing=='left':pygame.draw.rect(w,(237,202,145),(px-11,py+3,5,9))
        else:pygame.draw.rect(w,(237,202,145),(px+8,py+3,5,9))
        # Lighting uses a translucent overlay; crop PNG pixels remain intact.
        hour=clock_at(self.state)[1]
        if hour<5 or hour>=20:shade=(18,28,74,115)
        elif hour<9:shade=(246,172,96,32)
        elif hour>=17:shade=(220,104,83,52)
        else:shade=None
        if shade:
            light=pygame.Surface((BASE_W,VIEW_HEIGHT),pygame.SRCALPHA)
            light.fill(shade);w.blit(light,(0,0))
        self.stage.blit(w,(0,VIEW_TOP))

    def hud(self):
        if not self.online_client:restore_stamina(self.state)
        s=self.stage
        pygame.draw.rect(s,DARK,(0,0,BASE_W,VIEW_TOP))
        pygame.draw.rect(s,(31,49,37),(0,VIEW_TOP+VIEW_HEIGHT,BASE_W,BASE_H-(VIEW_TOP+VIEW_HEIGHT)))
        day,h,m=clock_at(self.state)
        text(s,self.fonts,'アンベラ牧場',(23,12),27,CREAM,True)
        if self.online_client:text(s,self.fonts,f'ONLINE {len(self.remote_players)+1}/{8}  PIN {self.room_pin}',(22,53),13,GOLD_LIGHT,True)
        if self.show_performance:
            ping = self.online_client.latency_ms if self.online_client else None
            metric = f'FPS {self.display_fps:.0f}' + (f'  PING {ping:.0f}ms' if ping is not None else '')
            text(s,self.fonts,metric,(1080,52),14,GOLD_LIGHT,True,max_width=190)
        text(s,self.fonts,f'{day}日目  {h:02d}:{m:02d} {time_of_day(self.state)}',(316,15),20,WHITE,True)
        text(s,self.fonts,'♥'*self.state['stamina']+'♡'*(MAX_STAMINA-self.state['stamina']),(316,48),20,(247,127,132),True)
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
                if p is None:
                    stage=('耕す','水やり','種まき')[self.state['plot_preparation'][data]]
                    msg=f'E {stage} | 種 {CROP_BY_ID[self.selected].name} ×{self.state["seeds"][self.selected]}'
                else:
                    _,rdy,ready=progress_for(p)
                    msg=f'E {"収穫" if ready else "様子を見る"}  |  {CROP_BY_ID[p["crop"]].name} {time_short(rdy)}'
            else:
                labels={'shop':'たね屋の内装へ','shipping':'出荷所の内装へ','missions':'ミッションを見る','home':'自宅へ入る','fishing':'釣りを始める','fish_market':'魚市場の内装へ','general_store':'雑貨屋へ','hall':'集会所へ','fisherman':'ナギと話す','guide':'ミオと話す','merchant':'店主と話す'}
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
                ('魚市場',26,29,(87,160,209)),
                ('雑貨屋',32,7,(238,207,88)),('集会所',50,24,(170,111,177)))
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
        text(s,self.fonts,'位置 / MAP クリックで拡大',(x+9,y+7),13,DARK,True)
        self.register('map',(x-8,y-8,201,148))

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
        self.ui_button((314,511,206,49),'メール / 贈り物','mail',size=17)
        unseen = unread_count(self.notice_feed, self.notice_seen)
        self.ui_button((537,511,206,49),f'お知らせ {"NEW "+str(unseen) if unseen else ""}','notices',size=17)
        self.ui_button((760,511,206,49),('更新あり！' if self.update_available else '更新を確認'),'check_update',size=17)
        self.ui_button((874,452,170,49),'終了','quit',size=21)
        status='保存データを読み込み済み' if self.save_file.exists() else '初回開始：新しい牧場が用意されています'
        text(s,self.fonts,status,(640,586),18,GREEN_DARK,True,True)
        if self.update_available:
            text(s,self.fonts,'新しいバージョンがあります！ ゲームを終了し、AmberaFarm.exeから再起動してください。',
                 (640,608),14,RED,True,True,max_width=890)
        if self.load_warning and self.read_only:
            text(s,self.fonts,self.load_warning,(640,617),15,RED,True,True,max_width=890)
        text(s,self.fonts,f'Pygame v{current_version()}  /  協力プレイはホスト方式 / 試作用価格',(640,674),16,PALE,False,True)
        if self.message and time.monotonic()<self.message_until:text(s,self.fonts,self.message,(640,626),16,RED,True,True,max_width=900)

    def draw_settings(self):
        self.overlay_panel('ゲーム設定','変更は即時反映。FPS上限は目標値であり、PC性能により実FPSは変動します。F3で実測表示。')
        items=(('音量',f'{self.settings["volume"]} %','volume',10),
               ('明度',f'{self.settings["brightness"]} %','brightness',10),
               ('解像度',f'{RESOLUTIONS[self.settings["resolution"]][0]} × {RESOLUTIONS[self.settings["resolution"]][1]}','resolution',1),
               ('描画FPS上限',f'{self.settings["fps_limit"]} FPS','fps_limit',1))
        for i,(label,value,action,step) in enumerate(items):
            y=172+i*87
            text(self.stage,self.fonts,label,(248,y+12),29,INK,True)
            self.ui_button((646,y,65,52),'−',action,-step,size=29)
            box(self.stage,(730,y,210,52),CREAM,BROWN,5,2)
            text(self.stage,self.fonts,value,(835,y+26),22,INK,True,True)
            self.ui_button((955,y,65,52),'+',action,step,size=29)
        label='フルスクリーン ON' if self.settings['fullscreen'] else 'フルスクリーン OFF'
        self.ui_button((429,535,422,48),label,'fullscreen',size=21)
        self.ui_button((257,535,160,48),'名前の変更','name_edit',size=15)
        if not self.sound.available:
            text(self.stage,self.fonts,'音声デバイスが使えないため、BGM/効果音は無音です。',(640,606),18,RED,False,True)
        self.ui_button((290,595,330,43),'最新版の配布ページ','open_release_page',RELEASES_URL,size=17)
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
        self.overlay_panel('持ち物  /  INVENTORY','カテゴリを選び、種や回復アイテムをクリックして使えます。')
        tabs=[('種','seeds'),('作物','crops'),('魚','fish'),('道具・食料','items')]
        for i,(label,key) in enumerate(tabs):
            self.ui_button((203+219*i,152,204,42),label,'inventory_page',key,selected=self.inventory_page==key,size=17)
        if self.inventory_page in ('seeds','crops'):
            for i,c in enumerate(CROPS):
                col,row=i%3,i//3;x,y=203+col*294,213+row*100
                active=c.id==self.selected and self.inventory_page=='seeds'
                box(self.stage,(x,y,278,86),GREEN_LIGHT if active else CREAM,GOLD if active else BROWN,6,3)
                self.assets.draw_crop(self.stage,c.id,(x+4,y+8,67,67))
                text(self.stage,self.fonts,c.name,(x+77,y+12),18,INK,True,max_width=176)
                count=self.state['seeds'][c.id] if self.inventory_page=='seeds' else self.state['warehouse'][c.id]
                text(self.stage,self.fonts,f'{"種" if self.inventory_page=="seeds" else "在庫"}: {count}',(x+78,y+49),17,BROWN,True)
                if self.inventory_page=='seeds':self.register('pick_crop',(x,y,278,86),c.id)
        elif self.inventory_page=='fish':
            for i,f in enumerate(FISH):
                x,y=227+(i%2)*420,221+(i//2)*100
                box(self.stage,(x,y,392,79),CREAM,BROWN,6,2)
                text(self.stage,self.fonts,f'{f.name}  × {self.state["fish_inventory"][f.id]}',(x+14,y+14),20,INK,True)
                text(self.stage,self.fonts,f'魚市場で {f.price}G / 匹',(x+14,y+47),16,GREEN_DARK)
        else:
            for i,(key,(label,price,hearts)) in enumerate(ITEMS.items()):
                y=228+i*104
                box(self.stage,(247,y,766,89),CREAM,BROWN,5,2)
                text(self.stage,self.fonts,f'{label}   ×{self.state["consumables"][key]}',(267,y+18),23,INK,True)
                text(self.stage,self.fonts,f'スタミナ +{hearts} ♥',(267,y+55),17,GREEN_DARK)
                self.ui_button((797,y+18,174,49),'使う','use_item',key,
                              disabled=self.state['consumables'][key]<1 or self.state['stamina']==MAX_STAMINA,size=17)
            self.ui_button((420,576,420,52),'雑貨屋（購入）','overlay','general_store',size=19)

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

    def draw_interior(self):
        names={'home':'自宅','shop':'たね屋','shipping':'出荷所','fish_market':'魚市場','general_store':'雑貨屋','hall':'集会所'}
        name=names.get(self.interior,'建物')
        self.overlay_panel(name+'  /  建物の中','屋内の家具を配置した仮内装。ここから施設機能を利用できます。')
        # Depth/perspective room with rug, furniture, shelf, doorway
        pygame.draw.rect(self.stage,(180,152,112),(238,164,805,390))
        pygame.draw.rect(self.stage,(232,206,158),(251,175,780,276))
        pygame.draw.rect(self.stage,(147,99,65),(250,438,780,104))
        for i in range(4):
            pygame.draw.rect(self.stage,(115,72,45),(286+i*175,185,88,62))
            pygame.draw.rect(self.stage,(208,189,114),(299+i*175,194,63,38))
        pygame.draw.rect(self.stage,(120,79,47),(505,324,266,120))
        pygame.draw.rect(self.stage,(221,182,111),(519,335,238,95))
        if self.interior=='home':
            pygame.draw.rect(self.stage,(103,71,55),(290,339,180,100))
            pygame.draw.rect(self.stage,(224,232,218),(300,347,160,68))
            pygame.draw.rect(self.stage,(245,243,219),(307,352,65,36))
        elif self.interior=='shop':
            for j in range(5):
                pygame.draw.rect(self.stage,(141,112,55),(280+j*77,347,56,55))
                pygame.draw.circle(self.stage,(103+j*20,155,67),(305+j*77,369),11)
        elif self.interior=='shipping':
            for j in range(3):
                pygame.draw.rect(self.stage,(141,96,62),(279+j*115,355,90,76))
                pygame.draw.line(self.stage,(204,159,94),(279+j*115,355),(369+j*115,431),3)
        elif self.interior=='fish_market':
            pygame.draw.rect(self.stage,(63,142,176),(289,329,316,108))
            for j in range(4):pygame.draw.ellipse(self.stage,(153,190+j*12,187),(308+j*67,359,43,21))
        elif self.interior=='general_store':
            for j in range(4):
                pygame.draw.rect(self.stage,(145,87,56),(273+j*113,331,84,107))
                pygame.draw.circle(self.stage,(238,214-j*20,139),(303+j*113,354),15)
        elif self.interior=='hall':
            pygame.draw.rect(self.stage,(126,75,53),(438,321,393,107))
            text(self.stage,self.fonts,'MINI GAME',(640,352),32,GOLD_LIGHT,True,True)
        text(self.stage,self.fonts,{'home':'ベッド・収納箱','shop':'種の棚・レジ','shipping':'出荷用木箱・伝票','fish_market':'氷の台・魚の水槽',
                                  'general_store':'飲食物と道具の棚','hall':'大会のステージ・掲示板'}[self.interior],(641,295),24,BROWN,True,True)
        if self.interior=='home':
            self.ui_button((408,475,214,55),'セーブ管理','data_menu',size=19)
            self.ui_button((663,475,214,55),'着せ替え','costume',size=19)
        else:
            destination={'general_store':'general_store','hall':'duel'}.get(self.interior,self.interior)
            caption='ミニゲーム練習' if self.interior=='hall' else 'お店を利用する'
            self.ui_button((482,472,316,58),caption,'interior_open',destination,size=21)

    def draw_store(self):
        self.overlay_panel('雑貨屋 / 回復アイテム','スタミナは5ハート。クワ・水やり・種まき・収穫で各1ハート消費。')
        for i,(ident,(label,price,recover)) in enumerate(ITEMS.items()):
            y=225+i*113
            box(self.stage,(254,y,775,95),CREAM,BROWN,5,3)
            text(self.stage,self.fonts,f'{label}   +{recover}♥  {price}G',(280,y+14),24,INK,True)
            text(self.stage,self.fonts,f'所持 {self.state["consumables"][ident]}個',(282,y+52),18,GREEN_DARK)
            self.ui_button((813,y+20,175,51),'購入する','shop_item',ident,size=18)
        text(self.stage,self.fonts,'※ 現在は持ち物画面からいつでも雑貨屋へ入れます。',(641,594),16,GREEN_DARK,False,True)

    def draw_name_edit(self):
        self.overlay_panel('プレイヤー名の設定','日本語にも対応。オンラインではこの名前を表示できます。')
        box(self.stage,(288,280,704,92),WHITE,BROWN,6,3)
        display=self.name_draft[:self.name_cursor]+'｜'+self.name_draft[self.name_cursor:]
        text(self.stage,self.fonts,display,(313,309),27,INK,True,max_width=644)
        self.ui_button((425,435,430,70),'この名前を使う','name_save',size=24)
        text(self.stage,self.fonts,'最大18文字 / Ctrl+A・Shift+矢印・Backspace対応',(640,548),17,GREEN_DARK,False,True)

    def draw_costume(self):
        self.overlay_panel('マイ衣装工房','服と帽子の色を自由に組み合わせて衣装として保存できます。')
        d=self.state['outfit_draft']
        pygame.draw.rect(self.stage,OUTFIT_COLORS[d['shirt']],(290,250,110,136))
        pygame.draw.rect(self.stage,(229,185,134),(312,197,68,56))
        pygame.draw.rect(self.stage,OUTFIT_COLORS[d['hat']],(299,193,95,20))
        for i,(label,key) in enumerate((('服の色','shirt'),('帽子の色','hat'))):
            y=208+i*98
            text(self.stage,self.fonts,label,(508,y),22,INK,True)
            pygame.draw.rect(self.stage,OUTFIT_COLORS[d[key]],(668,y,82,36))
            self.ui_button((802,y-4,144,48),'次の色','costume_color',key,size=17)
        self.ui_button((473,442,327,52),'この衣装を作って保存','costume_save',size=20)
        for i,outfit in enumerate(self.state['outfits'][-6:]):
            index=len(self.state['outfits'])-min(6,len(self.state['outfits']))+i
            x=219+(i%3)*289;y=514+(i//3)*59
            self.ui_button((x,y,265,49),outfit['name'],'costume_equip',index,
                           selected=self.state['outfit_index']==index,size=16)

    def draw_event(self):
        self.overlay_panel('季節のイベント','収穫で限定メダルを獲得。1日最大20枚。')
        event=active_event()
        if not event:
            text(self.stage,self.fonts,'現在、期間限定イベントは開催されていません。',(642,279),23,INK,True,True)
            text(self.stage,self.fonts,'秋の収穫祭：10月 / 冬の星明かり祭：12月〜1月',(642,354),18,GREEN_DARK,False,True)
            return
        text(self.stage,self.fonts,event['name'],(640,188),36,BROWN,True,True)
        text(self.stage,self.fonts,event['description'],(640,257),18,INK,False,True,max_width=778)
        text(self.stage,self.fonts,f'メダル：{self.state["event_tokens"]}枚   |   期限：{event["ends"]}',(640,309),21,GREEN_DARK,True,True)
        goods=[(ident,data) for ident,data in EVENT_GOODS.items() if
               ident.startswith('autumn_' if event['id'].startswith('harvest_') else 'winter_')]
        for i,(ident,(name,price)) in enumerate(goods):
            y=377+i*88
            claimed=event['id']+':'+ident in self.state['event_claimed']
            text(self.stage,self.fonts,name,(296,y+12),20,INK,True)
            self.ui_button((735,y,250,53),('交換済み' if claimed else f'{price}枚で交換'),'event_trade',ident,
                          disabled=claimed or self.state['event_tokens']<price,size=18)

    def draw_mail(self):
        self.overlay_panel('郵便受け  /  MAIL','公式の一斉配布アイテムを受け取れます。個別プレイヤー宛メールは未対応。')
        if not self.mail_items:
            text(self.stage,self.fonts,'現在受け取れる配布メールはありません。',(640,313),24,INK,True,True)
        for i,m in enumerate(self.mail_items[:5]):
            y=191+i*88
            name=str(m.get('title','配布アイテム'))[:36]
            box(self.stage,(242,y,790,75),CREAM,BROWN,5,2)
            text(self.stage,self.fonts,name,(260,y+14),19,INK,True)
            text(self.stage,self.fonts,f'お金 {m.get("coins",0)}G / アイテム ×{m.get("count",1)}',(260,y+44),15,GREEN_DARK)
            claimed=m.get('id') in self.state['mail_claimed']
            self.ui_button((827,y+13,175,48),'受取済み' if claimed else '受け取る','mail_claim',m.get('id'),disabled=claimed,size=16)

    def draw_friends(self):
        self.overlay_panel('フレンド  /  FRIENDS','同じ部屋で申請・承認すると、お互いのフレンド情報を保存できます。')
        for i,p in enumerate(self.remote_players[:5]):
            y=181+i*69
            box(self.stage,(251,y,779,57),CREAM,BROWN,5,2)
            text(self.stage,self.fonts,p['name'],(272,y+15),20,INK,True,max_width=280)
            is_friend=p.get('uid') in self.state['friend_ids']
            self.ui_button((780,y+7,219,43),'フレンド登録済み' if is_friend else '申請する',
                           'friend_request',p['id'],disabled=is_friend,size=16)
        if not self.remote_players:
            text(self.stage,self.fonts,'同じオンライン部屋の参加者はいません。',(640,246),19,INK,False,True)
        if self.friend_invites:
            invite=self.friend_invites[0]
            text(self.stage,self.fonts,invite['name']+' から申請が届いています',(356,564),17,RED,True)
            self.ui_button((817,547,187,49),'承認する','friend_accept',invite['id'],size=16)
        text(self.stage,self.fonts,'登録済み：'+('、'.join(self.state['friends'][:14]) or 'なし'),(263,636),15,GREEN_DARK,max_width=770)

    def draw_map(self):
        self.overlay_panel('拡大マップ  /  MAP','現在地と主要施設を確認できます。Escで戻ります。')
        r=pygame.Rect(268,171,743,417)
        pygame.draw.rect(self.stage,(166,194,122),r,border_radius=5)
        def proj(tx,ty):return int(r.x+tx/WORLD_W*r.w),int(r.y+ty/WORLD_H*r.h)
        for b in BUILDINGS:
            bx,by=proj(b.tile_x,b.tile_y)
            bw=int(b.tile_w/WORLD_W*r.w);bh=int(b.tile_h/WORLD_H*r.h)
            pygame.draw.rect(self.stage,(119,77,48),(bx,by,bw,bh))
            text(self.stage,self.fonts,b.label,(bx,by-17),12,BROWN,True)
        for tx,ty in TREE_POSITIONS:
            pygame.draw.circle(self.stage,(63,130,61),proj(tx,ty),3)
        lx,ly=proj(8,29)
        pygame.draw.ellipse(self.stage,(81,147,188),(lx-60,ly-32,110,75))
        px,py=proj(self.player[0]/TILE,self.player[1]/TILE)
        pygame.draw.circle(self.stage,WHITE,(px,py),9)
        pygame.draw.circle(self.stage,RED,(px,py),6)
        text(self.stage,self.fonts,'● 現在地',(640,617),18,INK,True,True)

    def draw_data_manage(self):
        self.overlay_panel('データ管理','セーブ・復元・画像読込を、遊び方から分離しました。')
        for i,(label,key) in enumerate((('今すぐ保存','save'),('セーブを書き出す','export_save'),
                                       ('セーブを読み込む','import_save'),('元画像ZIPを読む','import_assets'))):
            y=211+i*88
            self.ui_button((392,y,498,66),label,key,size=22)
        text(self.stage,self.fonts,'%APPDATA%\\AmberaFarm\\save.json に自動保存',(640,606),16,GREEN_DARK,False,True)

    def draw_duel(self):
        self.overlay_panel('集会所 / ミニゲーム','同じ部屋にいるプレイヤーと3種類のミニゲーム。掛け金はゲーム内Gのみ。')
        for i,(label,key) in enumerate((('数字あて','guess'),('タイミング','timing'),('反射神経','reaction'))):
            self.ui_button((206+296*i,165,282,48),label,'duel_kind',key,
                           selected=self.duel_mode==key,size=18)
        if not self.online_client:
            text(self.stage,self.fonts,'一人でも遊べる練習モード（賞金なし）',(640,244),24,BROWN,True,True)
            if self.duel_mode=='guess':
                text(self.stage,self.fonts,'1〜3を選んで当てよう！',(640,295),20,INK,False,True)
                for i in range(1,4):self.ui_button((330+(i-1)*207,377,180,72),str(i),'duel_try',i,size=30)
            else:
                pygame.draw.rect(self.stage,(124,94,57),(313,337,650,29))
                t=(time.monotonic()-self.duel_started)%1
                pygame.draw.rect(self.stage,GOLD_LIGHT,(313+int(t*640),330,10,42))
                self.ui_button((494,441,292,71),'ストップ！','duel_try',None,size=25)
            return
        duel=self.duel_state
        if duel and duel['status']=='pending':
            text(self.stage,self.fonts,'対戦相手：'+duel['opponent'],(641,277),28,BROWN,True,True)
            text(self.stage,self.fonts,f'{duel["stake"]}G を賭ける招待です。',(641,336),20,INK,True,True)
            if duel['challenger']:
                text(self.stage,self.fonts,'相手の返事を待っています。',(640,411),20,INK,False,True)
            else:
                self.ui_button((349,411,250,65),'対戦する','duel_accept',size=22)
                self.ui_button((677,411,250,65),'断る','duel_reject',size=22)
            return
        if duel and duel['status']=='active':
            text(self.stage,self.fonts,'対戦中：'+duel['opponent']+f'    掛け金 {duel["stake"]} G',(640,269),23,BROWN,True,True)
            if duel['submitted']:
                text(self.stage,self.fonts,'回答済み。相手の回答を待っています。',(640,396),24,INK,True,True)
            elif duel['kind']=='guess':
                text(self.stage,self.fonts,'サーバーが決めた数字（1〜3）を予想！',(640,329),20,INK,True,True)
                for i in range(1,4):self.ui_button((329+(i-1)*207,407,183,73),str(i),'duel_submit',i,size=28)
            else:
                ready=duel['ready']
                text(self.stage,self.fonts,'合図が出たらストップ！' if duel['kind']=='reaction' else '開始から2.6秒に近いタイミングで押そう！',
                     (640,347),23,INK,True,True)
                self.ui_button((470,429,340,73),'今すぐ押す！' if ready else '合図を待とう',
                               'duel_submit',None,disabled=not ready and duel['kind']!='reaction',size=24)
            return
        if duel and duel['status']=='finished':
            text(self.stage,self.fonts,duel['outcome'],(640,351),30,BROWN,True,True)
            text(self.stage,self.fonts,'少しすると次の対戦に挑戦できます。',(640,435),18,INK,False,True)
            return
        text(self.stage,self.fonts,'対戦を申し込む（同じ部屋で集会所に来た人のみ）',(640,247),21,BROWN,True,True)
        for i,stake in enumerate((0,10,50,100)):
            self.ui_button((279+i*185,287,168,46),f'{stake} G','duel_stake',stake,
                           selected=stake==self.duel_stake,size=17)
        if not self.remote_players:
            text(self.stage,self.fonts,'参加者がいません。ほかの人が部屋に来ると招待できます。',(640,424),18,INK,False,True)
        for i,p in enumerate(self.remote_players[:4]):
            y=373+i*60
            text(self.stage,self.fonts,p['name'],(334,y+10),21,INK,True)
            self.ui_button((768,y,206,47),'対戦を申込む','duel_invite',p['id'],size=17)

    def draw_pause(self):
        self.overlay_panel('ポーズ  /  MENU','ゲームを閉じている間も畑の成長は進みます。')
        unseen = unread_count(self.notice_feed, self.notice_seen)
        labels = [('ゲームに戻る','resume',None),('設定','settings',None),
                  ('種と倉庫','overlay','inventory'),('ミッション','overlay','missions'),
                  ('遊び方','help_menu',None),('お知らせ'+(' NEW' if unseen else ''),'notices',None),
                  ('衣装','costume',None),('イベント','event',None),('データ管理','data_menu',None),
                  ('メール','mail',None),('フレンド','friends',None),('MAP','map',None)]
        labels.append(('チャットを開く T','chat',None))
        labels.append(('タイトルへ戻る','return_title',None))
        for i,(label,act,val) in enumerate(labels):
            x=241+(i%3)*281
            y=153+(i//3)*78
            self.ui_button((x,y,254,55),label,act,val,size=16)
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
        self.ui_button((450,574,380,58),'データ管理を開く','data_menu',size=21)
        text(self.stage,self.fonts,'セーブ・復元はデータ管理画面にまとめました。',(640,647),16,GREEN_DARK,False,True)

    def draw_confirm(self):
        self.overlay_panel('新しい牧場を始めますか？','今の所持金・種・畑・ミッション・収穫履歴は初期化されます。')
        text(self.stage,self.fonts,'既存データを消す前に「書き出し」でバックアップできます。',
             (640,245),25,RED,True,True)
        self.ui_button((321,370,293,78),'新規開始する','confirm_new',size=23)
        self.ui_button((657,370,293,78),'キャンセル','close',size=23)
        self.ui_button((470,494,338,62),'セーブを書き出す','export_save',size=22)

    def draw_chat(self):
        self.overlay_panel('チャット / CHAT', 'オンラインでは参加者間、オフラインでは個人メモとして保存されます。')
        box(self.stage, (228, 174, 826, 340), WHITE, BROWN, 7, 3)
        backlog = self.chat_log if self.online_client else self.state['local_chat']
        maximum=max(0,len(backlog)-9)
        self.chat_scroll=min(self.chat_scroll,maximum)
        start=max(0,len(backlog)-9-self.chat_scroll)
        messages=backlog[start:start+9]
        for i, m in enumerate(messages):
            label = f'{m.get("name", "Player")}: {m.get("text", "")}'
            text(self.stage, self.fonts, label, (245, 187 + i*35), 18,
                 GREEN_DARK if i%2 else INK, max_width=793)
        self.ui_button((984,187,58,49),'▲','chat_scroll',3,size=17)
        self.ui_button((984,459,58,49),'▼','chat_scroll',-3,size=17)
        box(self.stage, (232, 532, 817, 55), PALE, GOLD, 5, 3)
        text(self.stage, self.fonts, (self.chat_text[:self.chat_cursor]+'｜'+self.chat_text[self.chat_cursor:] if self.chat_text else 'ここに入力...'),
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
            elif self.modal=='interior':self.draw_interior()
            elif self.modal=='general_store':self.draw_store()
            elif self.modal=='costume':self.draw_costume()
            elif self.modal=='name_edit':self.draw_name_edit()
            elif self.modal=='event':self.draw_event()
            elif self.modal=='mail':self.draw_mail()
            elif self.modal=='friends':self.draw_friends()
            elif self.modal=='map':self.draw_map()
            elif self.modal=='data_manage':self.draw_data_manage()
            elif self.modal=='duel':self.draw_duel()
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
            dt=min(.05, ticker.tick(self.settings['fps_limit'])/1000)
            self.display_fps=ticker.get_fps()
            self.events()
            self.poll_notices()
            self.poll_mails()
            if self.scene=='world' and self.modal=='fishing':
                self.update_fishing(dt)
            if self.scene=='world' and self.modal is None:self.move(dt)
            if self.online_client:
                self.poll_network()
                self.interpolate_remote_positions(dt)
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
