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
        self.root=tk.Tk();self.root.title('アンベラ牧場｜ストーリー管理画面');self.root.geometry('1080x710');self.root.minsize(850,570)
        self.events=load_story(story_path())
        main=ttk.Frame(self.root,padding=12);main.pack(fill='both',expand=True)
        ttk.Label(main,text='ストーリー管理 — 追加 / 編集 / 並べ替え',font=('Meiryo',15,'bold')).pack(anchor='w',pady=(0,10))
        ttk.Label(main,text='保存先：%APPDATA%\\AmberaFarm\\story_events.json（ゲーム更新で上書きされません）').pack(anchor='w')
        body=ttk.Panedwindow(main,orient='horizontal');body.pack(fill='both',expand=True,pady=12)
        left=ttk.Frame(body);right=ttk.Frame(body,padding=(13,0));body.add(left,weight=1);body.add(right,weight=3)
        self.list=tk.Listbox(left,font=('Meiryo',10));self.list.pack(fill='both',expand=True)
        self.list.bind('<<ListboxSelect>>',self.select)
        lf=ttk.Frame(left);lf.pack(fill='x',pady=9)
        for caption,func in [('追加',self.add),('削除',self.remove),('↑',lambda:self.shift(-1)),('↓',lambda:self.shift(1))]:
            ttk.Button(lf,text=caption,command=func).pack(side='left',padx=2)
        self.id_v=tk.StringVar();self.title_v=tk.StringVar();self.speaker_v=tk.StringVar()
        self.npc_v=tk.StringVar(value='nagi');self.kind_v=tk.StringVar(value='always')
        self.stat_v=tk.StringVar(value='planted');self.count_v=tk.StringVar(value='1');self.flag_v=tk.StringVar()
        def labeled(label,var):
            ttk.Label(right,text=label).pack(anchor='w',pady=(7,2));entry=ttk.Entry(right,textvariable=var);entry.pack(fill='x');return entry
        labeled('イベントID（半角英数字）',self.id_v)
        labeled('タイトル',self.title_v)
        labeled('話者',self.speaker_v)
        ttk.Label(right,text='登場NPC').pack(anchor='w',pady=(8,2))
        ttk.Combobox(right,textvariable=self.npc_v,values=list(NPCS),state='readonly').pack(fill='x')
        ttk.Label(right,text='発生条件').pack(anchor='w',pady=(8,2))
        ttk.Combobox(right,textvariable=self.kind_v,values=['always','stat','flag'],state='readonly').pack(fill='x')
        condition=ttk.Frame(right);condition.pack(fill='x',pady=4)
        ttk.Label(condition,text='統計').grid(row=0,column=0);ttk.Combobox(condition,textvariable=self.stat_v,values=list(STATS),width=14).grid(row=0,column=1,padx=6)
        ttk.Label(condition,text='必要回数').grid(row=0,column=2);ttk.Entry(condition,textvariable=self.count_v,width=5).grid(row=0,column=3,padx=6)
        ttk.Label(condition,text='先行ID').grid(row=0,column=4);ttk.Entry(condition,textvariable=self.flag_v,width=16).grid(row=0,column=5,padx=6)
        ttk.Label(right,text='台詞（1行ごとに1ページ）').pack(anchor='w',pady=(8,2))
        self.lines=tk.Text(right,height=9,wrap='word',font=('Meiryo',10));self.lines.pack(fill='both',expand=True)
        footer=ttk.Frame(main);footer.pack(fill='x')
        ttk.Button(footer,text='この内容を一覧に反映',command=self.apply).pack(side='left',padx=4)
        ttk.Button(footer,text='すべて保存',command=self.save).pack(side='left',padx=4)
        ttk.Label(footer,text='保存後、ゲームのタイトルに戻ると再読み込みされます。').pack(side='right')
        self.index=None;self.refresh();self.list.selection_set(0);self.select()
        self.root.protocol('WM_DELETE_WINDOW',self.root.destroy)

    def refresh(self):
        self.list.delete(0,'end')
        for event in self.events:self.list.insert('end',f'{event.get("npc","nagi")}: {event["id"]} / {event.get("title","")}')

    def select(self,event=None):
        choice=self.list.curselection()
        if not choice:return
        self.index=choice[0];e=self.events[self.index]
        for v,k in ((self.id_v,'id'),(self.title_v,'title'),(self.speaker_v,'speaker'),(self.npc_v,'npc')):v.set(e.get(k,'nagi' if k=='npc' else ''))
        t=e.get('trigger',{'kind':'always'})
        self.kind_v.set(t.get('kind','always'));self.stat_v.set(t.get('name','planted'))
        self.count_v.set(str(t.get('at_least',1)));self.flag_v.set(t.get('id',''))
        self.lines.delete('1.0','end');self.lines.insert('1.0','\n'.join(e['lines']))

    def build(self):
        kind=self.kind_v.get()
        if kind=='stat':trigger={'kind':'stat','name':self.stat_v.get(),'at_least':int(self.count_v.get())}
        elif kind=='flag':trigger={'kind':'flag','id':self.flag_v.get().strip()}
        else:trigger={'kind':'always'}
        return validate_event({'id':self.id_v.get().strip(),'title':self.title_v.get().strip(),
            'speaker':self.speaker_v.get().strip(),'npc':self.npc_v.get(),
            'trigger':trigger,'lines':self.lines.get('1.0','end-1c').splitlines()})

    def apply(self):
        try:
            event=self.build()
            if any(e['id']==event['id'] for i,e in enumerate(self.events) if i!=self.index):raise ValueError('イベントIDが既に使われています')
            self.events[self.index]=event;self.refresh();self.list.selection_set(self.index)
            return True
        except (ValueError,TypeError) as ex:messagebox.showerror('入力エラー',str(ex));return False

    def add(self):
        # Do not discard the old form; apply first.
        if self.index is not None and not self.apply():return
        self.events.append({'id':'new_event_'+str(len(self.events)+1),'title':'新しいお話','speaker':'村人','npc':'guide',
            'trigger':{'kind':'always'},'lines':['ここに台詞を入力']})
        self.refresh();self.list.selection_clear(0,'end');self.list.selection_set('end');self.select()

    def remove(self):
        if self.index is None:return
        if not messagebox.askyesno('確認','このイベントを削除しますか？'):return
        self.events.pop(self.index);self.index=None;self.refresh()
        if self.events:self.list.selection_set(min(len(self.events)-1,0));self.select()

    def shift(self,delta):
        if self.index is None:return
        j=self.index+delta
        if not 0<=j<len(self.events):return
        self.events[self.index],self.events[j]=self.events[j],self.events[self.index]
        self.index=j;self.refresh();self.list.selection_set(j)

    def save(self):
        if self.index is not None and not self.apply():return
        try:save_events(self.events)
        except (OSError,ValueError) as ex:messagebox.showerror('保存に失敗',str(ex));return
        messagebox.showinfo('保存しました',f'{len(self.events)}件のイベントを保存しました。\nゲームのタイトル画面から再開すると反映されます。')

def login_and_open():
    """Require the supplied local administrator code and password before editing."""
    root = tk.Tk()
    root.title('Ambera Farm - Story Admin Login')
    root.geometry('430x310')
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
    login_and_open()

