# -*- coding: utf-8 -*-
"""Admin-only Tk tabs for notices and distribution; GitHub CLI is the real publisher.
Never ship any PAT or credentials to game clients. Requires `gh auth login` on
administrator's PC. The local code/password check is deliberately NOT authority.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import re
import shutil
import subprocess
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from updater import current_version

from notices import (REPO, RELEASES_URL, TYPES, draft_path, load_draft, read_feed,
                     save_feed, validate_feed, fetch_public)

TYPE_LABELS = {'news':'一般のお知らせ','update':'アップデート','event':'イベント','maintenance':'メンテナンス'}


def run_gh(*arguments):
    if not shutil.which('gh'):
        raise RuntimeError('GitHub CLI が見つかりません。https://cli.github.com/ からインストールしてください。')
    result = subprocess.run(['gh', *arguments], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=50, check=False)
    if result.returncode:
        raise RuntimeError('GitHub 操作失敗: ' + (result.stderr or result.stdout or '認証を確認してください')[-600:])
    return result.stdout


def check_gh_auth():
    run_gh('auth', 'status', '-h', 'github.com')


def get_remote_file(path):
    """Read remote content metadata; raises for auth/errors other than 404."""
    from urllib.parse import quote
    check_gh_auth()
    result = subprocess.run(['gh', 'api', f'repos/{REPO}/contents/{path}?ref=main'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=35, check=False)
    if result.returncode:
        if '404' in (result.stderr or ''):
            return None
        raise RuntimeError('GitHub読み込み失敗: ' + (result.stderr or result.stdout)[-500:])
    return json.loads(result.stdout)


def remote_version():
    record = get_remote_file('version.json')
    if not record:
        raise RuntimeError('main に version.json がありません。先にソースをアップロードしてください。')
    payload = base64.b64decode(record['content'])
    version = json.loads(payload.decode('utf-8-sig')).get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise RuntimeError('GitHub main のバージョン形式が不正です')
    return version


def publish_announcements(feed):
    """Authenticated upload via GitHub Contents API, scoped to one JSON document."""
    clean = validate_feed(feed)
    # Private drafts remain in the administrator profile; never commit them.
    clean['notices'] = [n for n in clean['notices'] if n['published']]
    raw = (json.dumps(clean, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(raw) > 65_000:
        raise ValueError('投稿量が多すぎます')
    record = get_remote_file('data/announcements.json')
    body = {'message':'Publish AmberaFarm announcements',
            'branch':'main', 'content':base64.b64encode(raw).decode('ascii')}
    if record:
        body['sha'] = record['sha']
    # JSON is piped via temporary file, no token embedded in shell/command args.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json',
                                     delete=False) as tmp:
        json.dump(body, tmp, ensure_ascii=False)
        name = tmp.name
    try:
        result = run_gh('api', '--method', 'PUT', f'repos/{REPO}/contents/data/announcements.json', '--input', name)
        return json.loads(result)
    finally:
        from pathlib import Path
        Path(name).unlink(missing_ok=True)


def create_release(version, notes):
    """Publish tag from main only after code/version.json uploaded by administrator."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('バージョンは 0.7.0 の形式で入力してください')
    if not notes.strip() or len(notes) > 3500:
        raise ValueError('配布内容（3500文字以内）を入力してください')
    current = remote_version()
    if current != version:
        raise ValueError(f'GitHub main のversion.jsonは {current} です。先にコードをアップロードしてください。')
    run_gh('release', 'create', 'v' + version, '--repo', REPO, '--target', 'main',
           '--title', 'AmberaFarm v' + version, '--notes', notes.strip(), '--latest')


class NoticeAdminTab:
    def __init__(self, parent):
        self.parent = parent
        self.feed = load_draft()
        self.index = None
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        ttk.Label(parent, text='お知らせ管理 — 保存してからGitHubへ公開',
                  font=('Meiryo', 13, 'bold')).grid(row=0, column=0, sticky='w', pady=(3, 8))
        ttk.Label(parent, text='公開した文章は、ゲームのEXE更新なしでプレイヤーへ届きます。GitHub CLIの認証が必要。',
                  foreground='#555555').grid(row=1, column=0, sticky='w')
        body = ttk.Panedwindow(parent, orient='horizontal')
        body.grid(row=2, column=0, sticky='nsew', pady=(9, 0))
        left = ttk.Frame(body); right = ttk.Frame(body, padding=(10, 0))
        body.add(left, weight=1); body.add(right, weight=3)
        self.list = tk.Listbox(left, font=('Meiryo', 10), exportselection=False)
        self.list.pack(fill='both', expand=True)
        self.list.bind('<<ListboxSelect>>', self.choose)
        row = ttk.Frame(left); row.pack(fill='x', pady=8)
        ttk.Button(row, text='追加', command=self.add).pack(side='left', padx=3)
        ttk.Button(row, text='削除', command=self.delete).pack(side='left', padx=3)
        self.id_v = tk.StringVar(); self.title_v = tk.StringVar()
        self.category_v = tk.StringVar(value='news'); self.date_v = tk.StringVar()
        self.published_v = tk.BooleanVar(value=True); self.pinned_v = tk.BooleanVar()
        self.url_v = tk.StringVar(value=RELEASES_URL)
        def field(name, var):
            ttk.Label(right, text=name).pack(anchor='w', pady=(5, 1))
            ttk.Entry(right, textvariable=var).pack(fill='x')
        field('お知らせID（英数字、公開後は変更しない）', self.id_v)
        field('タイトル', self.title_v)
        ttk.Label(right, text='種類').pack(anchor='w', pady=(5, 1))
        ttk.Combobox(right, textvariable=self.category_v, values=list(TYPES), state='readonly').pack(fill='x')
        field('公開日（表示用）', self.date_v)
        field('配布リンク（公式GitHub Releasesのみ）', self.url_v)
        flags = ttk.Frame(right); flags.pack(fill='x', pady=6)
        ttk.Checkbutton(flags, text='公開する', variable=self.published_v).pack(side='left')
        ttk.Checkbutton(flags, text='重要なお知らせ（上部固定）', variable=self.pinned_v).pack(side='left', padx=15)
        ttk.Label(right, text='本文（1800文字以内）').pack(anchor='w')
        self.body = tk.Text(right, height=10, wrap='word', font=('Meiryo', 10))
        self.body.pack(fill='both', expand=True)
        footer = ttk.Frame(parent); footer.grid(row=3, column=0, sticky='ew', pady=10)
        ttk.Button(footer, text='編集中の内容を反映', command=self.apply).pack(side='left', padx=3)
        ttk.Button(footer, text='下書き保存', command=self.save).pack(side='left', padx=3)
        ttk.Button(footer, text='GitHubへ公開', command=self.publish).pack(side='right', padx=3)
        ttk.Button(footer, text='GitHubから読み込む', command=self.import_remote).pack(side='right', padx=3)
        self.refresh()
        if self.feed['notices']:
            self.list.selection_set(0); self.choose()

    def refresh(self):
        self.list.delete(0, 'end')
        for n in self.feed['notices']:
            flag = '公開' if n['published'] else '下書き'
            self.list.insert('end', f'[{flag}] {n["title"]}')

    def choose(self, event=None):
        selected = self.list.curselection()
        if not selected: return
        self.index = selected[0]
        n = self.feed['notices'][self.index]
        for var, key in ((self.id_v,'id'), (self.title_v,'title'),
                         (self.category_v,'category'), (self.date_v,'published_at'), (self.url_v,'url'),
                         (self.published_v,'published'), (self.pinned_v,'pinned')):
            var.set(n[key])
        self.body.delete('1.0', 'end'); self.body.insert('1.0', n['body'])

    def apply(self):
        if self.index is None: return True
        try:
            n = {'id':self.id_v.get().strip(), 'title':self.title_v.get().strip(),
                 'category':self.category_v.get(), 'published_at':self.date_v.get().strip(),
                 'url':self.url_v.get().strip(), 'pinned':bool(self.pinned_v.get()),
                 'published':bool(self.published_v.get()), 'body':self.body.get('1.0','end-1c').strip()}
            next_items = list(self.feed['notices']); next_items[self.index] = n
            self.feed = validate_feed({'schema':1, 'notices':next_items})
            self.refresh(); self.list.selection_set(self.index)
            return True
        except (TypeError, ValueError) as exc:
            messagebox.showerror('入力エラー', str(exc)); return False

    def add(self):
        if not self.apply(): return
        new_id = 'notice_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        existing = {n['id'] for n in self.feed['notices']}
        while new_id in existing: new_id += '_1'
        self.feed['notices'].insert(0, {'id':new_id, 'title':'新しいお知らせ', 'body':'本文を入力してください。',
              'category':'news','pinned':False,'published':False,
              'published_at':datetime.now().strftime('%Y-%m-%d'), 'url':RELEASES_URL})
        self.refresh(); self.list.selection_set(0); self.choose()

    def delete(self):
        if self.index is None:return
        if not messagebox.askyesno('削除確認', 'このお知らせを削除しますか？'):return
        self.feed['notices'].pop(self.index);self.index=None;self.refresh()
        if self.feed['notices']:self.list.selection_set(0);self.choose()

    def save(self):
        if not self.apply(): return False
        try:save_feed(draft_path(), self.feed)
        except (OSError, ValueError) as exc:
            messagebox.showerror('保存エラー', str(exc));return False
        messagebox.showinfo('保存', '下書きをローカルへ保存しました。プレイヤーにはまだ公開されません。')
        return True

    def publish(self):
        if not self.apply():return
        if not messagebox.askyesno('GitHubへ公開',
                    '公開済みチェックのあるお知らせが、公開リポジトリのデータを置き換えます。\nGitHubへ送信しますか？'):
            return
        try:
            save_feed(draft_path(), self.feed)
            publish_announcements(self.feed)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror('公開失敗', str(exc));return
        messagebox.showinfo('公開', 'GitHubに公開しました。プレイヤーは次回起動時や「再読み込み」で取得します。')

    def import_remote(self):
        if not messagebox.askyesno('確認','今編集中の内容を破棄してGitHub上の公開情報で置き換えますか？'):
            return
        try:
            self.feed = fetch_public();save_feed(draft_path(), self.feed)
        except Exception as exc:
            messagebox.showerror('読み込み失敗', str(exc));return
        self.index=None;self.refresh()
        if self.feed['notices']:self.list.selection_set(0);self.choose()


class DistributionTab:
    def __init__(self, parent):
        self.parent = parent
        ttk.Label(parent, text='ゲーム配布・アップデート管理', font=('Meiryo',13,'bold')).pack(anchor='w', pady=6)
        ttk.Label(parent, text='配布ページからZIPを公開。新しいリリースはGitHub ActionsがEXEを生成します。',
                  wraplength=840).pack(anchor='w', pady=5)
        header = ttk.Frame(parent);header.pack(fill='x',pady=8)
        ttk.Button(header,text='配布ページを開く', command=lambda:webbrowser.open(RELEASES_URL)).pack(side='left', padx=5)
        ttk.Button(header,text='ビルド結果を見る', command=lambda:webbrowser.open(f'https://github.com/{REPO}/actions')).pack(side='left', padx=5)
        ttk.Button(header,text='GitHubログイン状態確認',command=self.check_auth).pack(side='left',padx=5)
        ttk.Separator(parent).pack(fill='x', pady=8)
        self.version = tk.StringVar(value=current_version())
        ttk.Label(parent, text='新しいリリースのバージョン（GitHub main の version.json と同じにする）').pack(anchor='w', pady=2)
        ttk.Entry(parent,textvariable=self.version,width=15).pack(anchor='w')
        ttk.Label(parent,text='リリースノート').pack(anchor='w',pady=(12,3))
        self.notes=tk.Text(parent,height=10,font=('Meiryo',10),wrap='word')
        self.notes.pack(fill='both',expand=True)
        self.notes.insert('1.0','新機能：ゲーム内のお知らせ掲示板、管理画面からの通知公開、配布管理。')
        ttk.Label(parent, text='重要: 配信するソースの全ファイルを、先にGitHub mainへアップロードしてください。',
                  foreground='#a33822').pack(anchor='w',pady=7)
        ttk.Button(parent,text='バージョンを公開してEXEビルドを開始',command=self.release).pack(anchor='w',pady=7)
        ttk.Label(parent,text='管理者PCでGitHub CLI (gh) のインストールと gh auth login が必要です。\n'
                  'プレイヤー配布用EXEにGitHub認証情報は含まれません。',
                  foreground='#555555').pack(anchor='w',pady=8)

    def check_auth(self):
        try:check_gh_auth()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror('未接続',str(exc));return
        messagebox.showinfo('GitHub','GitHub CLIで認証済みです。')

    def release(self):
        version=self.version.get().strip();notes=self.notes.get('1.0','end-1c').strip()
        if not messagebox.askyesno('配布を確定', f'GitHubのmainブランチから v{version} を公開しますか？\n'
                       'タグ作成後にActionsがEXEと更新ファイルをビルドします。\n\n'
                       'ソースコードはすべてGitHubへアップロード済みですか？'):
            return
        try:create_release(version,notes)
        except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired) as exc:
            messagebox.showerror('リリース失敗',str(exc));return
        messagebox.showinfo('公開操作完了',f'v{version} のリリース作成を実行しました。\nActionsが成功したら配布ZIPを確認してください。')
        webbrowser.open(f'https://github.com/{REPO}/actions')
