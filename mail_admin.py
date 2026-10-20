# -*- coding: utf-8 -*-
"""Administrator-only public campaign editor. GitHub CLI's authenticated session
is the publishing authority; local UI code/password grants NO GitHub privileges.
"""
from __future__ import annotations
import base64,json,tkinter as tk
from tkinter import ttk,messagebox
import tempfile,os
from farm_mailbox import validate
from notices_admin import get_remote_file,run_gh
from notices import REPO

class MailAdminTab:
    def __init__(self,parent):
        self.parent=parent
        self.items=[]
        self.frame=ttk.Frame(parent);self.frame.pack(fill='both',expand=True)
        ttk.Label(self.frame,text='全員配布メール管理',font=('Meiryo',17,'bold')).pack(anchor='w',pady=15)
        ttk.Label(self.frame,text='GitHubに公開したアイテム配布は全プレイヤーに届きます。個別宛ではありません。').pack(anchor='w')
        ttk.Label(self.frame,text='配布IDを変えなければ、一度受け取った人は重複受取できません。').pack(anchor='w')
        self.list=tk.Listbox(self.frame,height=8);self.list.pack(fill='x',pady=10)
        self.list.bind('<<ListboxSelect>>',self.choose)
        self.vars={k:tk.StringVar() for k in ('id','title','coins','item','count')}
        self.vars['coins'].set('0');self.vars['item'].set('tea');self.vars['count'].set('1')
        for key,label in (('id','配布ID（英数字）'),('title','件名'),('coins','配布コイン（0〜250）'),('item','回復アイテム'),('count','個数（0〜3）')):
            row=ttk.Frame(self.frame);row.pack(fill='x',pady=5)
            ttk.Label(row,text=label,width=27).pack(side='left')
            if key=='item':
                ttk.Combobox(row,textvariable=self.vars[key],values=['tea','riceball','lunch'],state='readonly').pack(side='left',fill='x',expand=True)
            else:
                ttk.Entry(row,textvariable=self.vars[key]).pack(side='left',fill='x',expand=True)
        btn=ttk.Frame(self.frame);btn.pack(fill='x',pady=17)
        for label,cb in [('新規追加',self.add),('選択削除',self.remove),('GitHubから取得',self.reload),('GitHubへ公開',self.publish)]:
            ttk.Button(btn,text=label,command=cb).pack(side='left',padx=5)

    def refresh(self):
        self.list.delete(0,'end')
        for m in self.items:self.list.insert('end',m['id']+'  '+m['title'])
    def choose(self,event=None):
        if not self.list.curselection():return
        m=self.items[self.list.curselection()[0]]
        for k in self.vars:self.vars[k].set(str(m[k]))
    def build(self):
        return dict(id=self.vars['id'].get().strip(),title=self.vars['title'].get().strip(),
                    coins=int(self.vars['coins'].get()),item=self.vars['item'].get(),count=int(self.vars['count'].get()))
    def add(self):
        try:
            mail=self.build();validate({'schema':1,'campaigns':self.items+[mail]})
            self.items.append(mail);self.refresh()
        except (TypeError,ValueError) as exc:messagebox.showerror('入力エラー',str(exc))
    def remove(self):
        if not self.list.curselection():return
        self.items.pop(self.list.curselection()[0]);self.refresh()
    def reload(self):
        try:
            item=get_remote_file('data/mail_campaigns.json')
            if item:
                raw=base64.b64decode(item['content'])
                self.items=validate(json.loads(raw.decode('utf-8-sig')))['campaigns']
            self.refresh()
            messagebox.showinfo('取得完了',str(len(self.items))+'件の配布設定を取得')
        except (ValueError,OSError,RuntimeError) as exc:messagebox.showerror('読込エラー',str(exc))
    def publish(self):
        try:
            feed=validate({'schema':1,'campaigns':self.items})
            remote=get_remote_file('data/mail_campaigns.json')
            body={'message':'Publish Ambera Farm mail campaigns','branch':'main',
                  'content':base64.b64encode((json.dumps(feed,ensure_ascii=False,indent=2)+'\n').encode('utf-8')).decode('ascii')}
            if remote:body['sha']=remote['sha']
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json',delete=False) as fp:
                json.dump(body,fp,ensure_ascii=False);file=fp.name
            try:run_gh('api','--method','PUT',f'repos/{REPO}/contents/data/mail_campaigns.json','--input',file)
            finally:os.unlink(file)
            messagebox.showinfo('公開成功','配布メールをGitHubに公開しました。')
        except (ValueError,OSError,RuntimeError) as exc:messagebox.showerror('公開失敗',str(exc))
