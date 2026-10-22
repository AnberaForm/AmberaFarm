# -*- coding: utf-8 -*-
"""Local Tkinter admin tool. Edits only story JSON in the user's own profile.
Password-gated local editing only; no remote administrator privilege.
"""
import json
import os
import shutil
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk,messagebox
from story_engine import load_story
from farm_core import state_path
from story_admin_auth import validate_admin
from notices_admin import NoticeAdminTab, DistributionTab
from mail_admin import MailAdminTab

BASE=Path(__file__).resolve().parent
DEFAULT=BASE/'data'/'story_events.json'
USER=state_path().parent/'story_events.json'
NPCS={'nagi':'ナギ（釣り人）','guide':'ミオ（村の案内人）','merchant':'種屋の店主'}
STATS={'planted':'植えた数','harvested':'収穫した数','fish_caught':'魚を釣った数','bought':'購入した種の数'}

def story_path():return USER if USER.exists() else DEFAULT

def validate_event(obj):
    if not isinstance(obj,dict):raise ValueError('イベント形式が不正')
    event_id=obj.get('id')
    if not isinstance(event_id,str) or not event_id or len(event_id)>120 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in event_id):
        raise ValueError('イベントIDは英数字と _ - のみ、120文字以内にしてください')
    if not isinstance(obj.get('npc'),str) or obj['npc'] not in NPCS:raise ValueError('NPCを選択してください')
    if not isinstance(obj.get('title'),str) or not obj['title'].strip() or len(obj['title'])>80:raise ValueError('タイトルは80文字以内')
    if not isinstance(obj.get('speaker'),str) or len(obj['speaker'])>80:raise ValueError('話者名は80文字以内')
    lines=obj.get('lines')
    if not isinstance(lines,list) or not 1<=len(lines)<=25 or any(not isinstance(line,str) or not 1<=len(line)<=450 for line in lines):
        raise ValueError('台詞は1〜25行、1行450文字以内')
    trig=obj.get('trigger')
    if not isinstance(trig,dict) or trig.get('kind') not in ('always','stat','flag'):raise ValueError('条件を選択してください')
    if trig['kind']=='stat' and (trig.get('name') not in STATS or type(trig.get('at_least'))!=int or not 1<=trig['at_least']<=100000):
        raise ValueError('統計条件の種類・回数を確認してください')
    if trig['kind']=='flag' and not (isinstance(trig.get('id'),str) and trig['id']):raise ValueError('先行イベントIDを入れてください')
    return obj

def save_events(events,path=USER):
    ids=set()
    for event in events:
        validate_event(event)
        if event['id'] in ids:raise ValueError(f'IDが重複しています: {event["id"]}')
        ids.add(event['id'])
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():shutil.copy2(path,path.with_suffix('.backup.json'))
    fd,name=tempfile.mkstemp(prefix='story_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as fp:json.dump(events,fp,ensure_ascii=False,indent=2)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

class StoryEditor:
    def __init__(self):
        from admin_ui import theme, heading, field, Choice, ScrollForm, list_area, text_area
        import copy
        self.root=tk.Tk(); self.root.title('アンベラ牧場｜管理者ツール')
        width=max(1000,min(1240,self.root.winfo_screenwidth()-40))
        height=max(650,min(840,self.root.winfo_screenheight()-120))
        self.root.geometry(f'{width}x{height}+10+10'); self.root.minsize(1000,650); theme(self.root)
        self.events=load_story(story_path()); self.saved_events=copy.deepcopy(self.events)
        self.index=None; self.loading=False; self.form_baseline=None
        self.status=tk.StringVar(value='準備できました')
        sidebar=ttk.Frame(self.root,padding=(18,24),width=210); sidebar.pack(side='left',fill='y'); sidebar.pack_propagate(False)
        ttk.Label(sidebar,text='AMBERA FARM',font=('Meiryo',12,'bold')).pack(anchor='w')
        ttk.Label(sidebar,text='管理者ツール',style='Muted.TLabel').pack(anchor='w',pady=(2,25))
        workspace=ttk.Frame(self.root); workspace.pack(side='left',fill='both',expand=True)
        ttk.Label(workspace,textvariable=self.status,style='Muted.TLabel',padding=(22,10)).pack(side='bottom',fill='x')
        self.pages={}; self.nav={}
        for key,title in [('home','ホーム'),('story','ストーリー'),('notice','お知らせ'),('mail','アイテム配布'),('release','ゲーム配布・更新')]:
            panel=ttk.Frame(workspace,padding=(22,22)); self.pages[key]=panel
            btn=ttk.Button(sidebar,text=title,style='Nav.TButton',command=lambda k=key:self.show_page(k))
            btn.pack(fill='x',pady=3); self.nav[key]=btn
        ttk.Label(sidebar,text='ローカル保存と公開を\n分けて管理できます。',style='Muted.TLabel').pack(side='bottom',anchor='w')
        self.notice_admin=NoticeAdminTab(self.pages['notice'])
        self.mail_admin=MailAdminTab(self.pages['mail'])
        self.distribution_admin=DistributionTab(self.pages['release'])
        main=self.pages['story']
        heading(main,'ストーリー','左からお話を選び、右で編集します。保存した内容は、このPCのゲームで再開時に反映されます。')
        footer=ttk.Frame(main); footer.pack(side='bottom',fill='x',pady=(12,0))
        ttk.Button(footer,text='変更を保存  Ctrl+S',style='Primary.TButton',command=self.save).pack(side='right')
        ttk.Button(footer,text='会話プレビュー',command=self.preview).pack(side='right',padx=8)
        self.story_status=tk.StringVar(value='保存済み')
        ttk.Label(footer,textvariable=self.story_status,style='Muted.TLabel').pack(side='left')
        body=ttk.Panedwindow(main,orient='horizontal'); body.pack(fill='both',expand=True)
        left=ttk.Frame(body,width=280); scroll=ScrollForm(body); body.add(left,weight=1); body.add(scroll,weight=3)
        right=scroll.content;self.form=right
        self.query=tk.StringVar(); ttk.Entry(left,textvariable=self.query).pack(fill='x',pady=(0,8))
        ttk.Label(left,text='タイトル・NPC・IDで絞り込み',style='Muted.TLabel').pack(anchor='w',pady=(0,8))
        self.list=list_area(left); self.list.bind('<<ListboxSelect>>',self.select)
        tools=ttk.Frame(left); tools.pack(fill='x',pady=8)
        for caption,func in [('追加',self.add),('複製',self.duplicate),('削除',self.remove)]:
            ttk.Button(tools,text=caption,command=func,width=5).pack(side='left',padx=2)
        order=ttk.Frame(left); order.pack(fill='x')
        ttk.Button(order,text='上へ',command=lambda:self.shift(-1)).pack(side='left',padx=2)
        ttk.Button(order,text='下へ',command=lambda:self.shift(1)).pack(side='left',padx=2)
        self.id_v=tk.StringVar();self.title_v=tk.StringVar();self.speaker_v=tk.StringVar()
        self.npc_v=tk.StringVar(value='nagi');self.kind_v=tk.StringVar(value='always')
        self.stat_v=tk.StringVar(value='planted');self.count_v=tk.StringVar(value='1');self.flag_v=tk.StringVar()
        field(right,'タイトル',self.title_v);field(right,'話者名',self.speaker_v)
        ttk.Label(right,text='登場人物').pack(anchor='w',pady=(9,4)); Choice(right,self.npc_v,NPCS)
        ttk.Label(right,text='発生条件').pack(anchor='w',pady=(9,4))
        Choice(right,self.kind_v,{'always':'いつでも発生','stat':'行動の回数で発生','flag':'先行イベント後に発生'})
        self.stat_panel=ttk.Frame(right); self.flag_panel=ttk.Frame(right)
        ttk.Label(self.stat_panel,text='対象の行動').pack(anchor='w',pady=(8,4)); Choice(self.stat_panel,self.stat_v,STATS)
        field(self.stat_panel,'必要な回数',self.count_v);field(self.flag_panel,'先行イベントID',self.flag_v)
        self.condition_anchor=ttk.Frame(right);self.condition_anchor.pack(fill='x')
        field(right,'イベントID（半角英数字・ _ ・ - ）',self.id_v)
        ttk.Label(right,text='台詞  /  1行につき1ページ、最大25ページ').pack(anchor='w',pady=(12,4))
        self.lines=text_area(right,height=8)
        self.lines.bind('<<Modified>>',self.text_changed)
        for var in (self.id_v,self.title_v,self.speaker_v,self.npc_v,self.kind_v,self.stat_v,self.count_v,self.flag_v):
            var.trace_add('write',self.mark_dirty)
        self.kind_v.trace_add('write',self.condition_changed)
        self.query.trace_add('write',self.filter_changed)
        self.refresh()
        if self.events:self.load(0)
        else:
            from admin_ui import form_enabled
            form_enabled(self.form,False);self.story_status.set('「追加」からお話を作成してください')
        self.condition_changed();self.build_home()
        self.root.bind('<Control-s>',self.shortcut_save)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.show_page('home')

    def show_page(self,key):
        for name,page in self.pages.items():
            page.pack_forget(); self.nav[name].configure(style='Active.Nav.TButton' if name==key else 'Nav.TButton')
        self.current_page=key
        if key=='home':self.home_summary.set(self.summary())
        self.pages[key].pack(fill='both',expand=True)

    def summary(self):
        notices=self.notice_admin.feed['notices']; published=sum(n['published'] for n in notices)
        return f'ストーリー {len(self.events)}件   /   お知らせ {published}件公開対象・{len(notices)-published}件下書き   /   配布メール {len(self.mail_admin.items)}件'

    def build_home(self):
        from admin_ui import heading
        import webbrowser
        from notices import RELEASES_URL
        home=self.pages['home'];heading(home,'管理ホーム','作成・確認・公開の作業を、ここから始められます。')
        self.home_summary=tk.StringVar(value=self.summary())
        ttk.Label(home,textvariable=self.home_summary,style='Section.TLabel',wraplength=800).pack(anchor='w',pady=(0,22))
        for title,description,key in [('ストーリーを編集','このPCのお話を編集。会話のプレビューで確認して保存します。','story'),
                ('お知らせを届ける','下書きを保存し、公開対象を確認してGitHubへ公開します。','notice'),
                ('アイテムを配布','配布内容を編集し、全プレイヤー向けのメールを公開します。','mail'),
                ('ゲームを配布・更新','Setupの配布ページ、ビルド結果、新しいリリースを管理します。','release')]:
            card=ttk.LabelFrame(home,text=title,padding=8);card.pack(fill='x',pady=5)
            ttk.Button(card,text='開く →',command=lambda k=key:self.show_page(k)).pack(side='right',padx=8)
            ttk.Label(card,text=description,wraplength=650).pack(anchor='w',pady=5)
        self.home_download=ttk.Button(home,text='公開中のダウンロードページ',command=lambda:webbrowser.open(RELEASES_URL))
        self.home_download.pack(anchor='w',pady=6)

    def form_values(self):
        return tuple(v.get() for v in (self.id_v,self.title_v,self.speaker_v,self.npc_v,self.kind_v,self.stat_v,self.count_v,self.flag_v))+(self.lines.get('1.0','end-1c'),)

    def text_changed(self,event=None):
        if self.lines.edit_modified():self.mark_dirty();self.lines.edit_modified(False)

    def mark_dirty(self,*args):
        if self.loading:return
        dirty=self.has_changes()
        self.story_status.set('未保存の変更があります' if dirty else '保存済み')

    def has_changes(self):
        return self.events!=self.saved_events or (self.index is not None and self.form_baseline is not None and self.form_values()!=self.form_baseline)

    def condition_changed(self,*args):
        self.stat_panel.pack_forget();self.flag_panel.pack_forget()
        panel={'stat':self.stat_panel,'flag':self.flag_panel}.get(self.kind_v.get())
        if panel:panel.pack(fill='x',before=self.condition_anchor,pady=4)

    def refresh(self):
        query=self.query.get().strip().casefold();self.visible=[];self.list.delete(0,'end')
        for i,event in enumerate(self.events):
            label=f'{event["title"]}  /  {NPCS.get(event.get("npc"),event.get("npc"))}  /  {event["id"]}'
            if query and query not in label.casefold():continue
            self.visible.append(i);self.list.insert('end',label)
        if self.index in self.visible:self.list.selection_set(self.visible.index(self.index))

    def filter_changed(self,*args):
        self.refresh()

    def select(self,event=None):
        choice=self.list.curselection()
        if not choice:return
        index=self.visible[choice[0]]
        if index==self.index:return
        if self.index is not None and not self.apply():self.refresh();return
        self.load(index)

    def load(self,index):
        from admin_ui import form_enabled
        form_enabled(self.form,True)
        self.loading=True;self.index=index;e=self.events[index]
        for v,k in ((self.id_v,'id'),(self.title_v,'title'),(self.speaker_v,'speaker'),(self.npc_v,'npc')):v.set(e.get(k,''))
        t=e.get('trigger',{'kind':'always'})
        self.kind_v.set(t.get('kind','always'));self.stat_v.set(t.get('name','planted'))
        self.count_v.set(str(t.get('at_least',1)));self.flag_v.set(t.get('id',''))
        self.lines.delete('1.0','end');self.lines.insert('1.0','\n'.join(e['lines']));self.lines.edit_modified(False)
        self.form_baseline=self.form_values();self.loading=False;self.refresh();self.mark_dirty()

    def build(self):
        kind=self.kind_v.get()
        if kind=='stat':trigger={'kind':'stat','name':self.stat_v.get(),'at_least':int(self.count_v.get())}
        elif kind=='flag':trigger={'kind':'flag','id':self.flag_v.get().strip()}
        else:trigger={'kind':'always'}
        return validate_event({'id':self.id_v.get().strip(),'title':self.title_v.get().strip(),
            'speaker':self.speaker_v.get().strip(),'npc':self.npc_v.get(),
            'trigger':trigger,'lines':self.lines.get('1.0','end-1c').splitlines()})

    def apply(self):
        if self.index is None:return True
        try:
            event=self.build()
            if any(e['id']==event['id'] for i,e in enumerate(self.events) if i!=self.index):raise ValueError('イベントIDが既に使われています')
            self.events[self.index]=event;self.form_baseline=self.form_values();self.refresh();self.mark_dirty();return True
        except (ValueError,TypeError) as ex:messagebox.showerror('入力エラー',str(ex),parent=self.root);return False

    def add(self):
        if not self.apply():return
        ident='new_event';existing={e['id'] for e in self.events};n=1
        while f'{ident}_{n}' in existing:n+=1
        self.events.append({'id':f'{ident}_{n}','title':'新しいお話','speaker':'村人','npc':'guide',
            'trigger':{'kind':'always'},'lines':['ここに台詞を入力']})
        self.query.set('');self.load(len(self.events)-1)

    def duplicate(self):
        import copy
        if self.index is None or not self.apply():return
        event=copy.deepcopy(self.events[self.index]);original=event['id'][:105];n=1;existing={e['id'] for e in self.events}
        while f'{original}_copy{n}' in existing:n+=1
        event['id']=f'{original}_copy{n}';event['title']=event['title'][:76]+'（複製）'
        self.events.insert(self.index+1,event);self.query.set('');self.load(self.index+1)

    def remove(self):
        if self.index is None:return
        if not messagebox.askyesno('削除の確認',f'「{self.events[self.index]["title"]}」を削除しますか？',parent=self.root):return
        index=self.index;self.events.pop(index);self.index=None
        if self.events:self.load(min(index,len(self.events)-1))
        else:
            self.refresh();self.lines.delete('1.0','end');self.mark_dirty()
            from admin_ui import form_enabled
            form_enabled(self.form,False)

    def shift(self,delta):
        if self.index is None or not self.apply():return
        j=self.index+delta
        if not 0<=j<len(self.events):return
        self.events[self.index],self.events[j]=self.events[j],self.events[self.index];self.load(j)

    def save(self,silent=False):
        import copy
        if not self.apply():return False
        try:save_events(self.events,USER)
        except (OSError,ValueError) as ex:messagebox.showerror('保存に失敗',str(ex),parent=self.root);return False
        self.saved_events=copy.deepcopy(self.events);self.mark_dirty();self.status.set('ストーリーを保存しました。ゲームを再開すると反映されます。')
        if not silent:messagebox.showinfo('保存しました',f'{len(self.events)}件のお話を保存しました。',parent=self.root)
        return True

    def preview(self):
        if self.index is None:return
        try:event=self.build()
        except (ValueError,TypeError) as exc:messagebox.showerror('プレビューできません',str(exc),parent=self.root);return
        window=tk.Toplevel(self.root);window.title('会話プレビュー');window.geometry('640x370');window.transient(self.root)
        panel=ttk.Frame(window,padding=24);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text=event['title'],style='Section.TLabel').pack(anchor='w',pady=8)
        ttk.Label(panel,text=event['speaker'],foreground='#32664e').pack(anchor='w',pady=8)
        page=tk.IntVar(master=window,value=0);body=tk.StringVar(master=window);counter=tk.StringVar(master=window)
        ttk.Label(panel,textvariable=body,wraplength=570,font=('Meiryo',12)).pack(fill='both',expand=True,pady=15)
        controls=ttk.Frame(panel);controls.pack(fill='x')
        def show(delta=0):
            page.set(max(0,min(len(event['lines'])-1,page.get()+delta)));body.set(event['lines'][page.get()]);counter.set(f'{page.get()+1} / {len(event["lines"])} ページ')
        ttk.Button(controls,text='前へ',command=lambda:show(-1)).pack(side='left')
        ttk.Label(controls,textvariable=counter).pack(side='left',padx=20)
        ttk.Button(controls,text='次へ',command=lambda:show(1)).pack(side='left');show()

    def shortcut_save(self,event=None):
        if self.current_page=='story':self.save()
        elif self.current_page=='notice':self.notice_admin.save()
        elif self.current_page=='mail':self.mail_admin.save()
        elif self.current_page=='release':self.distribution_admin.save()
        return 'break'

    def close(self):
        if any(task.busy for task in (self.notice_admin.task,self.mail_admin.task,self.distribution_admin.task)):
            messagebox.showinfo('処理中','公開・読み込み処理の完了後に閉じてください。',parent=self.root);return
        if self.has_changes() or self.notice_admin.has_changes() or self.mail_admin.has_changes() or self.distribution_admin.has_changes():
            answer=messagebox.askyesnocancel('未保存の変更','変更をローカルに保存して終了しますか？\n「いいえ」は変更を破棄します。GitHubには公開しません。',parent=self.root)
            if answer is None:return
            if answer and not (self.save(silent=True) and self.notice_admin.save(silent=True) and self.mail_admin.save(silent=True) and self.distribution_admin.save(silent=True)):return
        self.root.destroy()

def login_and_open():
    """Require the supplied local administrator code and password before editing."""
    root = tk.Tk()
    root.title('アンベラ牧場｜管理者ログイン')
    root.geometry('480x380')
    from admin_ui import theme
    theme(root)
    root.resizable(False, False)
    code = tk.StringVar()
    password = tk.StringVar()
    attempts = [0]
    ttk.Label(root, text='アンベラ牧場 管理画面', font=('Meiryo', 16, 'bold')).pack(pady=(22, 13))
    ttk.Label(root, text='コード').pack(anchor='w', padx=54)
    code_field = ttk.Entry(root, textvariable=code, width=35)
    code_field.pack(padx=54, fill='x', pady=4)
    ttk.Label(root, text='パスワード').pack(anchor='w', padx=54, pady=(8, 0))
    pass_field = ttk.Entry(root, textvariable=password, show='*', width=35)
    pass_field.pack(padx=54, fill='x', pady=4)
    status = ttk.Label(root, text='ローカル編集用の簡易認証です。', foreground='#666666')
    status.pack(pady=8)

    def submit(event=None):
        if validate_admin(code.get(), password.get()):
            root.destroy()
            editor = StoryEditor()
            editor.root.mainloop()
            return
        attempts[0] += 1
        password.set('')
        status.configure(text=f'認証失敗（{attempts[0]}回）', foreground='#c03d31')
        if attempts[0] >= 5:
            messagebox.showwarning('認証失敗', '試行回数が多いため、この画面を終了します。')
            root.destroy()

    ttk.Button(root, text='ログイン', command=submit).pack(pady=3)
    root.bind('<Return>', submit)
    code_field.focus_set()
    root.mainloop()


if __name__ == '__main__':
    import sys
    if '--admin-smoke-test' in sys.argv:
        target=sys.argv[sys.argv.index('--report-dir')+1] if '--report-dir' in sys.argv else 'build_output/admin_ui_checks'
        try:
            from verify_admin_ui import run
            run(target)
        except BaseException:
            import traceback
            folder=Path(target);folder.mkdir(parents=True,exist_ok=True)
            (folder/'admin_ui_failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            sys.exit(1)
    else:
        login_and_open()

