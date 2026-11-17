# -*- coding: utf-8 -*-
"""Game-loop state for sign-in, first-run migration, and cloud save status."""
import copy
from queue import Queue, Empty
import threading

import pygame

from account_client import AccountClient, account_endpoint
from account_protocol import AccountError, ERROR_MESSAGES, password_bytes, username_parts
from account_saves import FarmSync, legacy_farms
from farm_core import SaveError, new_state
from player_movement import safe_destination
from inventory_grid import reconcile_layout
from v8_features import init_v8
from online_ui import wait_for_relay


class AccountFlowMixin:
    def init_accounts(self):
        self.account_endpoint = account_endpoint()
        self.account_session = None
        self.normal_sync = None
        self.has_normal_farm = False
        self.has_online_farm = False
        self.account_mode = 'login'
        self.account_fields = {'name': self.settings['account_name'], 'password': '', 'confirm': ''}
        self.account_focus = 'name'
        self.account_cursor = len(self.account_fields['name'])
        self.account_anchor = None
        self.account_ime = False
        self.account_feedback = ''
        self.account_wait = ''
        self.account_job = None
        self.account_queue = Queue()
        self.migration_options = []
        self.migration_feedback = ''
        self.normal_import = None
        self.last_sync_status = None

    def account_keys(self):
        return ['name', 'password', 'confirm'] if self.account_mode == 'register' else ['name', 'password']

    def account_set_focus(self, key):
        self.account_focus = key
        self.account_ime = False
        self.account_cursor = len(self.account_fields[key])
        self.account_anchor = None

    def open_account(self, mode):
        if self.account_job or self.account_session:
            return
        self.account_mode = mode
        self.account_feedback = ''
        self.account_fields['password'] = self.account_fields['confirm'] = ''
        self.account_set_focus('name')
        self.modal = 'account'
        pygame.key.start_text_input()
        pygame.key.set_repeat(350, 36)
        self.held_keys.clear()

    def account_input(self, event):
        if self.account_job:
            return
        if event.type == pygame.TEXTEDITING:
            self.account_ime = bool(event.text)
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.close_account()
                return
            if event.key == pygame.K_F11:
                self.do_action('fullscreen', None)
                return
            if event.key == pygame.K_TAB:
                keys = self.account_keys()
                self.account_set_focus(keys[(keys.index(self.account_focus) + 1) % len(keys)])
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and not self.account_ime:
                self.submit_account()
                return
            if (self.account_focus != 'name' and
                    event.key in (pygame.K_c, pygame.K_x) and pygame.key.get_mods() & pygame.KMOD_CTRL):
                return
        elif event.type == pygame.TEXTINPUT:
            self.account_ime = False
        else:
            return
        k = self.account_focus
        value, self.account_cursor, self.account_anchor = self.edit_text_event(
            event, self.account_fields[k], self.account_cursor, self.account_anchor,
            36 if k == 'name' else 128)
        self.account_fields[k] = value

    def close_account(self):
        if self.account_job:
            return
        self.account_fields['password'] = self.account_fields['confirm'] = ''
        self.modal = None
        pygame.key.stop_text_input()
        pygame.key.set_repeat()

    def submit_account(self):
        if self.account_job or self.account_session:
            return
        mode, name, password = self.account_mode, self.account_fields['name'], self.account_fields['password']
        self.account_feedback = ''
        if mode == 'register':
            try:
                username_parts(name)
                password_bytes(password)
            except AccountError as exc:
                self.account_feedback = str(exc)
                return
            if password != self.account_fields['confirm']:
                self.account_feedback = '確認用のパスワードが一致しません。'
                return
        elif not name.strip() or not password:
            self.account_feedback = 'ユーザー名とパスワードを入力してください。'
            return
        self.account_fields['password'] = self.account_fields['confirm'] = ''
        self.account_set_focus('name')
        endpoint = self.account_endpoint
        preferred = (self.settings['slot_kind'], self.settings['slot_index'])
        self.account_wait = 'アカウントサーバーに接続しています…'
        self.account_job = 'sign_in'
        pygame.key.stop_text_input()
        pygame.key.set_repeat()

        def worker():
            try:
                wait_for_relay(endpoint, threading.Event(),
                               lambda message: setattr(self, 'account_wait', message),
                               require_accounts=True)
                session = AccountClient(endpoint).sign_in(mode, name, password)
                sync = FarmSync(AccountClient(endpoint, session))
                options = legacy_farms(preferred=preferred) if sync.state is None else []
                self.account_queue.put(('signin', sync, options))
            except (OSError, AccountError, SaveError, ValueError) as exc:
                self.account_queue.put(('error', str(exc), None))

        threading.Thread(target=worker, name='account-signin', daemon=True).start()

    def set_normal_state(self, state):
        self.state = init_v8(copy.deepcopy(state))
        self.reset_map_state()
        self.player = list(safe_destination(self.state['player']))
        self.selected = self.state['selected_crop']
        self.inventory_layout = reconcile_layout(self.settings.get('inventory_layout'), self.state)
        self.online_profile_received = False
        self.scene = 'title'

    def submit_first_farm(self, option=None):
        if (self.account_job or not self.normal_sync or self.has_normal_farm
                or self.online_client):
            return
        state = copy.deepcopy(option.state) if option else init_v8(new_state())
        if option is None:
            state['player_name'] = self.account_session.account.name
        try:
            self.normal_sync.stage(state)
        except (SaveError, AccountError) as exc:
            self.migration_feedback = str(exc)
            return
        self.has_normal_farm = True
        self.set_normal_state(state)
        self.modal = None
        self.say('以前の牧場を通常セーブに引き継ぎました。' if option else '通常の牧場を作成しました。', 8)

    def begin_logout(self):
        if self.account_job or not self.normal_sync or self.online_client:
            return
        self.account_job = 'logout'
        self.account_wait = 'セーブを確認してログアウトしています…'
        self.modal = 'account_wait'
        sync = self.normal_sync

        def worker():
            saved = sync.flush(3)
            sync.close()
            if sync.thread:
                sync.thread.join()
            # After the writer is gone, the next login can safely replay the
            # same outbox even when the connection failed on the last write.
            try:
                sync.client.logout()
            except AccountError:
                pass
            self.account_queue.put(('logout', saved, None))

        threading.Thread(target=worker, name='account-signout', daemon=True).start()

    def poll_account(self):
        try:
            kind, value, options = self.account_queue.get_nowait()
        except Empty:
            kind = None
        if kind:
            self.account_job = None
        if kind == 'error':
            self.account_feedback = value
            pygame.key.start_text_input()
            pygame.key.set_repeat(350, 36)
        elif kind == 'signin':
            self.normal_sync = value
            self.account_session = value.client.session
            self.has_online_farm = self.account_session.has_online
            self.has_normal_farm = value.state is not None
            self.migration_options = options
            self.migration_feedback = value.recovery_warning
            self.last_sync_status = None
            self.settings['account_name'] = self.account_session.account.name
            self.account_fields['name'] = self.account_session.account.name
            self.save_account_settings(self.settings)
            self.close_account()
            value.start()
            if self.has_normal_farm:
                self.set_normal_state(value.state)
                if value.recovery_warning:
                    self.say(value.recovery_warning, 14)
                elif value.recovered:
                    self.say('このPCの未同期の進行を読み込み、同期を再開しました。', 10)
            else:
                self.modal = 'migration'
        elif kind == 'logout':
            if self.directory_job:
                self.directory_job.cancel_event.set()
            self.init_internet_rooms()
            self.normal_sync = self.account_session = None
            self.has_normal_farm = self.has_online_farm = False
            self.migration_options = []
            self.migration_feedback = ''
            self.normal_import = None
            self.set_normal_state(new_state())
            self.modal = None
            self.say('ログアウトしました。' if value else
                     'ログアウトしました。未同期の進行はこのPCに残しています。', 12)
        if self.normal_sync and not self.account_job:
            status = self.normal_sync.status
            if status != self.last_sync_status:
                if status == 'save_conflict':
                    self.say('別の端末で更新されたため同期を止めました。このPCの進行は控えに残っています。', 14)
                elif status in ('account_unavailable', 'busy'):
                    self.say('接続が切れました。このPCに保存し、再接続時に同期します。', 11)
                elif status in ('auth_required', 'bad_save', 'local_error'):
                    self.say(self.normal_sync_label(), 12)
                self.last_sync_status = status

    def normal_sync_label(self):
        if not self.has_normal_farm:
            return '通常：未作成'
        status = self.normal_sync.status
        if status == 'saved':
            return '通常：同期済み'
        if status == 'pending':
            return '通常：同期中'
        if status == 'local_error':
            return 'このPCのセーブ控えを確認してください。'
        if status in ('account_unavailable', 'busy'):
            return '通常：このPCに保存済み / 同期を再試行中'
        return ERROR_MESSAGES.get(status, '通常：同期を再試行中')

    def close_normal_on_exit(self):
        if self.normal_sync and self.account_job != 'logout':
            self.normal_sync.flush(2.5)
            self.normal_sync.close()
