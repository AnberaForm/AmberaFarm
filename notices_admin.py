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


def admin_game_version():
    from pathlib import Path
    try:
        value=json.loads((Path(__file__).resolve().parent/'version.json').read_text(encoding='utf-8-sig'))['version']
        if isinstance(value,str) and re.fullmatch(r'\d+\.\d+\.\d+',value):return value
    except (OSError,ValueError,KeyError,TypeError):pass
    return current_version()


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
        import copy
        from admin_ui import heading, ScrollForm, field, Choice, list_area, text_area, TaskRunner
        self.parent=parent;self.feed=load_draft();self.saved=copy.deepcopy(self.feed);self.index=None
        self.baseline=None;self.loading=False
        self.status=tk.StringVar(value='ローカル下書きを読み込みました')
        self.task=TaskRunner(parent,self.status)
        heading(parent,'お知らせ','1. 編集 → 2. 下書き保存 → 3. プレビュー → 4. GitHubへ公開。下書きだけではプレイヤーに届きません。')
        footer=ttk.Frame(parent);footer.pack(side='bottom',fill='x',pady=(12,0))
        self.actions=[]
        for title,callback,style in [('GitHubへ公開',self.publish,'Primary.TButton'),('下書き保存',self.save,'TButton'),('プレビュー',self.preview,'TButton')]:
            button=ttk.Button(footer,text=title,command=callback,style=style);button.pack(side='right',padx=3);self.actions.append(button)
        ttk.Label(parent,textvariable=self.status,style='Muted.TLabel',wraplength=780).pack(side='bottom',anchor='w',pady=(8,0))
        body=ttk.Panedwindow(parent,orient='horizontal');body.pack(fill='both',expand=True)
        left=ttk.Frame(body,width=270);scroll=ScrollForm(body);body.add(left,weight=1);body.add(scroll,weight=3);right=scroll.content;self.form=right
        self.query=tk.StringVar();ttk.Entry(left,textvariable=self.query).pack(fill='x',pady=(0,6))
        ttk.Label(left,text='タイトル・種類・IDで検索',style='Muted.TLabel').pack(anchor='w',pady=(0,8))
        self.list=list_area(left);self.list.bind('<<ListboxSelect>>',self.choose)
        row=ttk.Frame(left);row.pack(fill='x',pady=8)
        for text,cb in [('追加',self.add),('削除',self.delete)]:
            button=ttk.Button(row,text=text,command=cb);button.pack(side='left',padx=3);self.actions.append(button)
        button=ttk.Button(left,text='公開情報を読み込む',command=self.import_remote);button.pack(fill='x');self.actions.append(button)
        self.id_v=tk.StringVar();self.title_v=tk.StringVar();self.category_v=tk.StringVar(value='news');self.date_v=tk.StringVar()
        self.published_v=tk.BooleanVar();self.pinned_v=tk.BooleanVar();self.url_v=tk.StringVar(value=RELEASES_URL)
        field(right,'タイトル',self.title_v)
        ttk.Label(right,text='種類').pack(anchor='w',pady=(9,4));Choice(right,self.category_v,TYPE_LABELS)
        field(right,'公開日（表示用）',self.date_v)
        flags=ttk.LabelFrame(right,text='公開する内容');flags.pack(fill='x',pady=12)
        ttk.Checkbutton(flags,text='公開対象にする（送信は「GitHubへ公開」から）',variable=self.published_v).pack(anchor='w')
        ttk.Checkbutton(flags,text='重要なお知らせとして上部に表示',variable=self.pinned_v).pack(anchor='w',pady=(7,0))
        ttk.Label(right,text='本文（1800文字まで）').pack(anchor='w',pady=(9,4));self.body=text_area(right,height=8)
        self.counter=tk.StringVar();ttk.Label(right,textvariable=self.counter,style='Muted.TLabel').pack(anchor='e')
        field(right,'配布リンク（公式GitHub Releases）',self.url_v);field(right,'お知らせID（公開後は変更しない）',self.id_v)
        self.query.trace_add('write',lambda *args:self.refresh())
        for var in (self.id_v,self.title_v,self.category_v,self.date_v,self.url_v,self.published_v,self.pinned_v):var.trace_add('write',self.changed)
        self.body.bind('<<Modified>>',self.body_changed)
        self.refresh()
        if self.feed['notices']:self.load(0)
        else:
            from admin_ui import form_enabled
            form_enabled(self.form,False);self.status.set('「追加」からお知らせを作成してください')

    def values(self):
        return tuple(v.get() for v in (self.id_v,self.title_v,self.category_v,self.date_v,self.url_v,self.published_v,self.pinned_v))+(self.body.get('1.0','end-1c'),)

    def has_changes(self):
        return self.feed!=self.saved or (self.index is not None and self.baseline is not None and self.values()!=self.baseline)

    def changed(self,*args):
        if self.loading:return
        self.counter.set(f'{len(self.body.get("1.0","end-1c"))} / 1800文字')
        self.status.set('未保存の変更があります' if self.has_changes() else '下書き保存済み / 公開は別操作です')

    def body_changed(self,event=None):
        if self.body.edit_modified():self.changed();self.body.edit_modified(False)

    def refresh(self):
        self.list.delete(0,'end');self.visible=[];query=self.query.get().strip().casefold()
        for i,n in enumerate(self.feed['notices']):
            if query and query not in (n['title']+' '+n['id']+' '+TYPE_LABELS.get(n['category'],n['category'])).casefold():continue
            self.visible.append(i);flag='公開対象' if n['published'] else '下書き'
            self.list.insert('end',f'[{flag}] {n["title"]}')
        if self.index in self.visible:self.list.selection_set(self.visible.index(self.index))

    def choose(self,event=None):
        selected=self.list.curselection()
        if not selected:return
        index=self.visible[selected[0]]
        if index==self.index:return
        if not self.apply():self.refresh();return
        self.load(index)

    def load(self,index):
        from admin_ui import form_enabled
        form_enabled(self.form,True)
        self.loading=True;self.index=index;n=self.feed['notices'][index]
        for var,key in ((self.id_v,'id'),(self.title_v,'title'),(self.category_v,'category'),(self.date_v,'published_at'),(self.url_v,'url'),(self.published_v,'published'),(self.pinned_v,'pinned')):var.set(n[key])
        self.body.delete('1.0','end');self.body.insert('1.0',n['body']);self.body.edit_modified(False)
        self.baseline=self.values();self.loading=False;self.refresh();self.changed()

    def build(self):
        return {'id':self.id_v.get().strip(),'title':self.title_v.get().strip(),'category':self.category_v.get(),
                'published_at':self.date_v.get().strip(),'url':self.url_v.get().strip(),
                'pinned':bool(self.pinned_v.get()),'published':bool(self.published_v.get()),'body':self.body.get('1.0','end-1c').strip()}

    def apply(self):
        if self.index is None:return True
        try:
            items=list(self.feed['notices']);items[self.index]=self.build()
            self.feed=validate_feed({'schema':1,'notices':items});self.baseline=self.values();self.refresh();self.changed();return True
        except (TypeError,ValueError) as exc:messagebox.showerror('入力エラー',str(exc),parent=self.parent);return False

    def add(self):
        if not self.apply():return
        ident='notice_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S');existing={n['id'] for n in self.feed['notices']}
        while ident in existing:ident+='_1'
        self.feed['notices'].insert(0,{'id':ident,'title':'新しいお知らせ','body':'本文を入力してください。','category':'news','pinned':False,'published':False,'published_at':datetime.now().strftime('%Y-%m-%d'),'url':RELEASES_URL})
        self.query.set('');self.load(0)

    def delete(self):
        if self.index is None:return
        if not messagebox.askyesno('削除の確認','選択したお知らせを下書き一覧から削除しますか？\n公開済みの内容への反映には、再度公開が必要です。',parent=self.parent):return
        index=self.index;self.feed['notices'].pop(index);self.index=None
        if self.feed['notices']:self.load(min(index,len(self.feed['notices'])-1))
        else:
            self.refresh();self.body.delete('1.0','end');self.changed()
            from admin_ui import form_enabled
            form_enabled(self.form,False)

    def save(self,silent=False):
        import copy
        if not self.apply():return False
        try:save_feed(draft_path(),self.feed)
        except (OSError,ValueError) as exc:messagebox.showerror('保存エラー',str(exc),parent=self.parent);return False
        self.saved=copy.deepcopy(self.feed);self.changed();self.status.set('下書きを保存しました。まだGitHubには公開していません。')
        return True

    def preview(self):
        from admin_ui import text_area
        if self.index is None:return
        if not self.apply():return
        n=self.feed['notices'][self.index];window=tk.Toplevel(self.parent);window.title('お知らせプレビュー');window.geometry('670x500');window.transient(self.parent.winfo_toplevel())
        panel=ttk.Frame(window,padding=22);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='公開対象' if n['published'] else '下書き / プレイヤーには届きません',style='Muted.TLabel').pack(anchor='w')
        ttk.Label(panel,text=n['title'],style='Section.TLabel',wraplength=600).pack(anchor='w',pady=14)
        ttk.Label(panel,text=TYPE_LABELS.get(n['category'],n['category'])+'  '+n['published_at']).pack(anchor='w')
        text=text_area(panel);text.insert('1.0',n['body']);text.configure(state='disabled')
        ttk.Label(panel,text=n['url'],wraplength=610,style='Muted.TLabel').pack(anchor='w',pady=10)

    def publish(self):
        import copy
        if not self.apply():return
        count=sum(n['published'] for n in self.feed['notices'])
        if not messagebox.askyesno('公開内容の確認',f'公開対象 {count}件でGitHub上のお知らせを置き換えます。\n対象外の下書きは送信しません。公開しますか？',parent=self.parent):return
        if not self.save(silent=True):return
        feed=copy.deepcopy(self.feed)
        self.task.run('GitHubへ公開',lambda:publish_announcements(feed),lambda _:messagebox.showinfo('公開しました','公開対象のお知らせを送信しました。',parent=self.parent),self.actions)

    def import_remote(self):
        import copy
        if not messagebox.askyesno('公開情報を読み込む','ローカルの下書きをGitHub上の公開情報で置き換えます。\n未公開のお知らせも一覧からなくなります。続けますか？',parent=self.parent):return
        def done(feed):
            self.feed=feed;save_feed(draft_path(),feed);self.saved=copy.deepcopy(feed);self.index=None;self.query.set('');self.refresh()
            if feed['notices']:self.load(0)
            else:
                from admin_ui import form_enabled
                form_enabled(self.form,False)
            self.status.set('公開情報を読み込みました')
        self.task.run('公開情報を読み込み',fetch_public,done,self.actions)


class DistributionTab:
    def __init__(self,parent):
        from admin_ui import heading, field, text_area, TaskRunner
        self.parent=parent;self.status=tk.StringVar(value='GitHub接続は「認証を確認」から確認できます')
        self.task=TaskRunner(parent,self.status)
        heading(parent,'ゲーム配布・更新','配布中のSetupとビルド状況を確認し、新しいバージョンを公開します。')
        links=ttk.LabelFrame(parent,text='公開中のファイル・ビルド');links.pack(fill='x',pady=(0,14))
        ttk.Button(links,text='Setupの配布ページ',command=lambda:webbrowser.open(RELEASES_URL)).pack(side='left',padx=5)
        ttk.Button(links,text='ビルド結果',command=lambda:webbrowser.open(f'https://github.com/{REPO}/actions')).pack(side='left',padx=5)
        self.auth_button=ttk.Button(links,text='認証を確認',command=self.check_auth);self.auth_button.pack(side='left',padx=5)
        footer=ttk.Frame(parent);footer.pack(side='bottom',fill='x',pady=(12,0))
        self.release_button=ttk.Button(footer,text='確認してリリースを公開',style='Primary.TButton',command=self.release);self.release_button.pack(side='right')
        ttk.Button(footer,text='下書き保存',command=self.save).pack(side='right',padx=8)
        ttk.Label(parent,textvariable=self.status,wraplength=780,style='Muted.TLabel').pack(side='bottom',anchor='w',pady=8)
        steps=ttk.LabelFrame(parent,text='新しいバージョンを公開する手順');steps.pack(fill='x',pady=6)
        ttk.Label(steps,text='1. 更新するソースをGitHubのmainへ反映\n2. version.jsonと同じバージョン・変更内容を入力\n3. 公開後にビルド成功とSetupの追加を確認',justify='left').pack(anchor='w')
        self.version=tk.StringVar(value=admin_game_version());field(parent,'公開するバージョン（例：9.6.1）',self.version)
        ttk.Label(parent,text='変更内容 / リリースノート（3500文字まで）').pack(anchor='w',pady=(12,4));self.notes=text_area(parent,height=8)
        ttk.Label(parent,text='GitHub CLIでの認証が必要です。ソースのアップロードはこの画面では行いません。',wraplength=780,style='Muted.TLabel').pack(anchor='w',pady=8)
        self.saved=(self.version.get(),'')
        try:
            record=json.loads(self.draft_file().read_text(encoding='utf-8'))
            if not isinstance(record,dict) or not isinstance(record.get('version'),str) or not isinstance(record.get('notes'),str):raise ValueError('下書き形式が不正です')
            self.version.set(record['version']);self.notes.insert('1.0',record['notes']);self.saved=(record['version'],record['notes'])
        except FileNotFoundError:pass
        except (OSError,ValueError):self.status.set('配布管理の下書きを読み込めませんでした。')

    def draft_file(self):
        from farm_core import state_path
        return state_path().parent/'release_draft.json'

    def has_changes(self):
        return (self.version.get(),self.notes.get('1.0','end-1c'))!=self.saved

    def save(self,silent=False):
        import os
        path=self.draft_file();payload={'version':self.version.get(),'notes':self.notes.get('1.0','end-1c')}
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='release_',suffix='.tmp',dir=path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as fp:json.dump(payload,fp,ensure_ascii=False)
                os.replace(name,path)
            finally:
                from pathlib import Path
                Path(name).unlink(missing_ok=True)
        except OSError as exc:messagebox.showerror('下書き保存に失敗',str(exc),parent=self.parent);return False
        self.saved=(payload['version'],payload['notes']);self.status.set('配布管理の下書きを保存しました。リリースは公開していません。');return True

    def check_auth(self):
        self.task.run('GitHub認証を確認',check_gh_auth,lambda _:self.status.set('GitHub認証済み / 公開操作を使用できます'),(self.auth_button,self.release_button))

    def release(self):
        version=self.version.get().strip();notes=self.notes.get('1.0','end-1c').strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+',version) or not notes or len(notes)>3500:
            messagebox.showerror('入力を確認','バージョンと変更内容（1〜3500文字）を入力してください。',parent=self.parent);return
        if not messagebox.askyesno('リリースを公開',f'mainから v{version} を公開します。\nビルド成功後にSetupが追加されます。\n\nソースの反映と変更内容を確認しましたか？',parent=self.parent):return
        if not self.save(silent=True):return
        self.task.run('リリースを公開',lambda:create_release(version,notes),lambda _:self.status.set(f'v{version}を作成しました。「ビルド結果」で完了を確認してください。'),(self.auth_button,self.release_button))
