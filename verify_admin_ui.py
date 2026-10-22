"""Real Tk UI checks. Only temporary drafts, no network or publishing calls."""
import json,os,tempfile,time
from pathlib import Path
from unittest.mock import patch


def run(report_dir):
    import tkinter as tk
    import story_editor,notices_admin,mail_admin
    from PIL import ImageGrab
    report_dir=Path(report_dir).resolve();report_dir.mkdir(parents=True,exist_ok=True)
    checks=[];screens=[];errors=[]
    def check(value,name):
        if not value:raise AssertionError(name)
        checks.append(name)
        (report_dir/'admin_ui_progress.txt').write_text('\n'.join(checks),encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='ambera_admin_ui_') as folder:
        with patch.dict(os.environ,{'APPDATA':folder}),patch.object(story_editor,'USER',Path(folder)/'story_events.json'),patch('tkinter.messagebox.showinfo'),patch('tkinter.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)),patch('tkinter.messagebox.askyesno',return_value=True),patch('tkinter.messagebox.askyesnocancel',return_value=None):
            app=story_editor.StoryEditor();root=app.root
            root.report_callback_exception=lambda cls,value,tb:errors.append(str(value))
            def screen(name):
                root.update();path=report_dir/(name+'.png')
                ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(path)
                screens.append(path.name)
            try:
                root.update();screen('01-home')
                for page in ('story','notice','mail','release'):
                    app.show_page(page);root.update();check(app.pages[page].winfo_ismapped(),page+' navigation opens');screen('02-'+page)
                app.show_page('story');root.update();app.title_v.set('編集中のお話');app.load(0) if app.index is None else None
                # Switching rows retains a valid edit in the working list, before explicit disk save.
                original=app.index;app.title_v.set('切替前の未保存タイトル');app.refresh()
                if len(app.events)>1:
                    target=1 if original==0 else 0;app.list.selection_clear(0,'end');app.list.selection_set(target);app.select()
                    check(app.events[original]['title']=='切替前の未保存タイトル','Switching story retains unsaved form')
                app.duplicate();ids=[e['id'] for e in app.events];check(len(ids)==len(set(ids)),'Duplicate story has unique ID')
                check(app.save(silent=True),'Story save succeeds');saved=story_editor.USER.read_bytes()
                app.id_v.set('invalid id');check(not app.save(silent=True) and story_editor.USER.read_bytes()==saved,'Invalid story cannot overwrite saved data');errors.clear();app.load(app.index)
                app.query.set('検索に一致しない文字');check(not app.visible,'Story filter can show zero matches');app.query.set('')
                app.kind_v.set('stat');root.update();check(app.stat_panel.winfo_ismapped() and not app.flag_panel.winfo_ismapped(),'Only relevant trigger fields shown');app.kind_v.set('always')
                app.preview();root.update()
                for child in root.winfo_children():
                    if isinstance(child,tk.Toplevel):child.destroy()
                notices=app.notice_admin;notices.add();notices.title_v.set('編集したお知らせ');check(notices.save(),'Notice draft saves edited fields')
                check(any(n['title']=='編集したお知らせ' for n in notices_admin.load_draft()['notices']),'Saved notice contains latest form')
                notices.add();notices.title_v.set('切り替え前のお知らせ');notices.list.selection_clear(0,'end');notices.list.selection_set(1);notices.choose()
                check(any(n['title']=='切り替え前のお知らせ' for n in notices.feed['notices']),'Notice selection retains unsaved edit')
                mail=app.mail_admin;mail.add();mail.vars['coins'].set('125');mail.vars['title'].set('下書きプレゼント');check(mail.save(),'Mail edits save without duplicate insertion')
                check(json.loads(mail_admin.draft_path().read_text())['campaigns'][0]['coins']==125,'Mail draft stores edited rewards')
                mail.vars['coins'].set('999');check(not mail.save(),'Out of range rewards rejected');errors.clear();mail.load(0)
                mail.preview();root.update()
                for child in root.winfo_children():
                    if isinstance(child,tk.Toplevel):child.destroy()
                # Worker failure is surfaced on UI thread; no actual GitHub invocation.
                results=[];mail.task.run('テスト',lambda:42,lambda value:results.append(value))
                end=time.monotonic()+5
                while mail.task.busy and time.monotonic()<end:root.update();time.sleep(.02)
                check(results==[42] and not mail.task.busy,'Async operation completes without freezing UI')
                app.show_page('home');root.geometry('1000x650');root.update();screen('03-small-window')
                app.show_page('story');root.update();check(app.pages['story'].winfo_height()>450,'Minimum window keeps content visible')
                app.title_v.set('終了前の変更');app.close();check(root.winfo_exists(),'Cancel close preserves unsaved session')
                check(not errors,'No Tk callback errors')
            finally:root.destroy()
    report={'status':'passed','checks':checks,'screenshots':screens,'scope':'Temporary local UI; no real GitHub writes'}
    (report_dir/'admin_ui_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--report-dir',default='build_output/admin_ui_checks');args=parser.parse_args()
    print(json.dumps(run(args.report_dir),ensure_ascii=False))
