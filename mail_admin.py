# -*- coding: utf-8 -*-
"""Administrator-only campaign editor; authenticated GitHub CLI publishes."""
from __future__ import annotations
import base64,copy,json,tkinter as tk
from tkinter import ttk,messagebox
from datetime import datetime,timezone
from pathlib import Path
import tempfile,os
from farm_mailbox import validate
from farm_core import state_path
from notices_admin import get_remote_file,run_gh
from notices import REPO
from admin_ui import heading,field,Choice,list_area,TaskRunner

ITEM_LABELS={'tea':'お茶','riceball':'おにぎり','lunch':'お弁当'}

def draft_path():return state_path().parent/'mail_campaigns_draft.json'

def save_draft(feed):
    feed=validate(feed);path=draft_path();path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='mail_draft_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as fp:json.dump(feed,fp,ensure_ascii=False,indent=2)
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def publish_campaigns(feed):
    feed=validate(feed);remote=get_remote_file('data/mail_campaigns.json')
    body={'message':'Publish Ambera Farm mail campaigns','branch':'main',
          'content':base64.b64encode((json.dumps(feed,ensure_ascii=False,indent=2)+'\n').encode('utf-8')).decode('ascii')}
    if remote:body['sha']=remote['sha']
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.json',delete=False) as fp:
        json.dump(body,fp,ensure_ascii=False);name=fp.name
    try:return run_gh('api','--method','PUT',f'repos/{REPO}/contents/data/mail_campaigns.json','--input',name)
    finally:os.unlink(name)

class MailAdminTab:
    def __init__(self,parent):
        self.parent=parent;self.items=[];self.index=None;self.baseline=None;self.loading=False
        self.status=tk.StringVar(value='下書きはこのPCに保存します。公開は別操作です。');self.task=TaskRunner(parent,self.status)
        error=None
        if draft_path().exists():
            try:self.items=validate(json.loads(draft_path().read_text(encoding='utf-8-sig')))['campaigns']
            except (ValueError,OSError,TypeError) as exc:error=str(exc)
        self.saved=copy.deepcopy(self.items)
        heading(parent,'アイテム配布','全プレイヤー向けの配布メールを編集します。同じ配布IDは一度だけ受け取れます。')
        footer=ttk.Frame(parent);footer.pack(side='bottom',fill='x',pady=(12,0));self.actions=[]
        for title,cb,style in [('GitHubへ公開',self.publish,'Primary.TButton'),('下書き保存',self.save,'TButton'),('受け取り内容を確認',self.preview,'TButton')]:
            btn=ttk.Button(footer,text=title,command=cb,style=style);btn.pack(side='right',padx=3);self.actions.append(btn)
        ttk.Label(parent,textvariable=self.status,style='Muted.TLabel',wraplength=780).pack(side='bottom',anchor='w',pady=(8,0))
        body=ttk.Panedwindow(parent,orient='horizontal');body.pack(fill='both',expand=True)
        left=ttk.Frame(body,width=280);right=ttk.Frame(body,padding=(18,0));self.form=right;body.add(left,weight=1);body.add(right,weight=2)
        self.query=tk.StringVar();ttk.Entry(left,textvariable=self.query).pack(fill='x',pady=(0,6))
        ttk.Label(left,text='件名・配布IDで検索',style='Muted.TLabel').pack(anchor='w',pady=(0,8))
        self.list=list_area(left);self.list.bind('<<ListboxSelect>>',self.choose)
        row=ttk.Frame(left);row.pack(fill='x',pady=8)
        for title,cb in [('新規追加',self.add),('削除',self.remove)]:
            btn=ttk.Button(row,text=title,command=cb);btn.pack(side='left',padx=3);self.actions.append(btn)
        btn=ttk.Button(left,text='公開情報を読み込む',command=self.reload);btn.pack(fill='x');self.actions.append(btn)
        self.vars={k:tk.StringVar() for k in ('id','title','coins','item','count')}
        self.vars['coins'].set('0');self.vars['item'].set('tea');self.vars['count'].set('1')
        field(right,'件名',self.vars['title']);field(right,'コイン（0〜250G）',self.vars['coins'])
        ttk.Label(right,text='回復アイテム').pack(anchor='w',pady=(9,4));Choice(right,self.vars['item'],ITEM_LABELS)
        field(right,'個数（0〜3個 / 配らない場合は0）',self.vars['count']);field(right,'配布ID（公開後は変更しない）',self.vars['id'])
        ttk.Label(right,text='配布対象：全プレイヤー\n個別のユーザー宛てには送信されません。\n\n公開前に「受け取り内容を確認」で内容を確認できます。',style='Muted.TLabel',wraplength=470).pack(anchor='w',pady=20)
        for var in self.vars.values():var.trace_add('write',self.changed)
        self.query.trace_add('write',lambda *args:self.refresh());self.refresh()
        if self.items:self.load(0)
        else:
            from admin_ui import form_enabled
            form_enabled(self.form,False);self.status.set('「新規追加」から配布メールを作成してください')
        if error:self.status.set('下書きを読み込めません。保存前にバックアップを確認してください。')

    def values(self):return tuple(v.get() for v in self.vars.values())
    def has_changes(self):return self.items!=self.saved or (self.index is not None and self.baseline is not None and self.values()!=self.baseline)
    def changed(self,*args):
        if not self.loading:self.status.set('未保存の変更があります' if self.has_changes() else '下書き保存済み / 公開は別操作です')
    def refresh(self):
        self.list.delete(0,'end');self.visible=[];query=self.query.get().strip().casefold()
        for i,m in enumerate(self.items):
            if query and query not in (m['id']+' '+m['title']).casefold():continue
            self.visible.append(i);self.list.insert('end',m['title']+'  /  '+m['id'])
        if self.index in self.visible:self.list.selection_set(self.visible.index(self.index))
    def choose(self,event=None):
        if not self.list.curselection():return
        index=self.visible[self.list.curselection()[0]]
        if index==self.index:return
        if not self.apply():self.refresh();return
        self.load(index)
    def load(self,index):
        from admin_ui import form_enabled
        form_enabled(self.form,True)
        self.loading=True;self.index=index
        for key,var in self.vars.items():var.set(str(self.items[index][key]))
        self.baseline=self.values();self.loading=False;self.refresh();self.changed()
    def build(self):
        return dict(id=self.vars['id'].get().strip(),title=self.vars['title'].get().strip(),coins=int(self.vars['coins'].get()),item=self.vars['item'].get(),count=int(self.vars['count'].get()))
    def apply(self):
        if self.index is None:return True
        try:
            items=list(self.items);items[self.index]=self.build();self.items=validate({'schema':1,'campaigns':items})['campaigns'];self.baseline=self.values();self.refresh();self.changed();return True
        except (TypeError,ValueError) as exc:messagebox.showerror('入力エラー',str(exc),parent=self.parent);return False
    def add(self):
        if not self.apply():return
        ident='gift_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S');existing={m['id'] for m in self.items}
        while ident in existing:ident+='_1'
        item=dict(id=ident,title='新しいプレゼント',coins=0,item='tea',count=1)
        try:validate({'schema':1,'campaigns':self.items+[item]})
        except ValueError as exc:messagebox.showerror('追加できません',str(exc),parent=self.parent);return
        self.items.append(item);self.query.set('');self.load(len(self.items)-1)
    def remove(self):
        if self.index is None:return
        if not messagebox.askyesno('削除の確認','選択した配布メールを下書きから削除しますか？\n公開情報の変更には再度公開が必要です。',parent=self.parent):return
        index=self.index;self.items.pop(index);self.index=None
        if self.items:self.load(min(index,len(self.items)-1))
        else:
            self.refresh();self.changed()
            from admin_ui import form_enabled
            form_enabled(self.form,False)
    def save(self,silent=False):
        if not self.apply():return False
        try:save_draft({'schema':1,'campaigns':self.items})
        except (OSError,ValueError) as exc:messagebox.showerror('保存できません',str(exc),parent=self.parent);return False
        self.saved=copy.deepcopy(self.items);self.changed();self.status.set('下書きを保存しました。まだGitHubには公開していません。');return True
    def reload(self):
        if not messagebox.askyesno('公開情報を読み込む','このPCの下書きを公開中の配布メールで置き換えます。続けますか？',parent=self.parent):return
        def work():
            record=get_remote_file('data/mail_campaigns.json')
            return validate(json.loads(base64.b64decode(record['content']).decode('utf-8-sig'))) if record else {'schema':1,'campaigns':[]}
        def done(feed):
            save_draft(feed);self.items=feed['campaigns'];self.saved=copy.deepcopy(self.items);self.index=None;self.query.set('');self.refresh()
            if self.items:self.load(0)
            else:
                from admin_ui import form_enabled
                form_enabled(self.form,False)
            self.status.set(f'公開情報を{len(self.items)}件読み込みました')
        self.task.run('公開情報を読み込み',work,done,self.actions)
    def preview(self):
        if self.index is None or not self.apply():return
        m=self.items[self.index];window=tk.Toplevel(self.parent);window.title('配布メールプレビュー');window.geometry('540x310');window.transient(self.parent.winfo_toplevel())
        panel=ttk.Frame(window,padding=24);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text=m['title'],style='Section.TLabel',wraplength=480).pack(anchor='w',pady=12)
        ttk.Label(panel,text=f'コイン：{m["coins"]}G\nアイテム：{ITEM_LABELS.get(m["item"],m["item"])} × {m["count"]}個',font=('Meiryo',14)).pack(anchor='w',pady=16)
        ttk.Label(panel,text='全プレイヤー対象 / このIDにつき1回のみ受取',style='Muted.TLabel').pack(anchor='w')
    def publish(self):
        if not self.apply():return
        if not messagebox.askyesno('公開内容の確認',f'全プレイヤー向け配布 {len(self.items)}件で公開情報を置き換えます。\n内容を確認しましたか？',parent=self.parent):return
        if not self.save(silent=True):return
        feed=copy.deepcopy({'schema':1,'campaigns':self.items})
        self.task.run('配布メールを公開',lambda:publish_campaigns(feed),lambda _:messagebox.showinfo('公開しました','配布メールをGitHubへ公開しました。',parent=self.parent),self.actions)
