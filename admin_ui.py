"""Shared presentation helpers for the administrator desktop app only."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

BG = '#f2f5f1'
INK = '#20362e'
GREEN = '#32664e'
MUTED = '#64766d'


def theme(root):
    root.configure(bg=BG)
    root.option_add('*Font', ('Meiryo', 10))
    root.option_add('*Listbox.background', '#ffffff')
    root.option_add('*Listbox.foreground', INK)
    root.option_add('*Listbox.selectBackground', '#d8e9dd')
    root.option_add('*Listbox.selectForeground', INK)
    root.option_add('*Listbox.relief', 'flat')
    root.option_add('*Text.background', '#ffffff')
    root.option_add('*Text.foreground', INK)
    root.option_add('*Text.relief', 'flat')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Meiryo', 10), background=BG, foreground=INK)
    style.configure('TFrame', background=BG)
    style.configure('TLabel', background=BG)
    style.configure('Title.TLabel', font=('Meiryo', 21, 'bold'))
    style.configure('Section.TLabel', font=('Meiryo', 12, 'bold'))
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('TButton', padding=(12, 8), borderwidth=0)
    style.map('TButton', background=[('active', '#dbe8df')])
    style.configure('Primary.TButton', background=GREEN, foreground='white')
    style.map('Primary.TButton', background=[('active', '#244e3b'), ('disabled', '#a9b9ae')], foreground=[('disabled', '#ffffff')])
    style.configure('Nav.TButton', anchor='w', padding=(16, 13))
    style.configure('Active.Nav.TButton', background=GREEN, foreground='white')
    style.map('Active.Nav.TButton', background=[('active', '#244e3b')], foreground=[('active', 'white')])
    style.configure('TEntry', padding=7, fieldbackground='white')
    style.configure('TCombobox', padding=6, fieldbackground='white')
    style.configure('TLabelframe', padding=12, bordercolor='#d1ddd3')
    style.configure('TLabelframe.Label', font=('Meiryo', 11, 'bold'))
    style.configure('Treeview', rowheight=34, fieldbackground='white', background='white', borderwidth=0)
    style.configure('Treeview.Heading', padding=8, font=('Meiryo', 10, 'bold'))


def heading(parent, title, subtitle):
    ttk.Label(parent, text=title, style='Title.TLabel').pack(anchor='w', pady=(0, 5))
    label = ttk.Label(parent, text=subtitle, style='Muted.TLabel', wraplength=760)
    label.pack(anchor='w', pady=(0, 16))
    label.bind('<Configure>', lambda e: label.configure(wraplength=max(200, e.width)))


def field(parent, label, variable, values=None):
    ttk.Label(parent, text=label).pack(anchor='w', pady=(9, 4))
    entry = (ttk.Combobox(parent, textvariable=variable, values=values, state='readonly')
             if values else ttk.Entry(parent, textvariable=variable))
    entry.pack(fill='x')
    return entry


def text_area(parent, height=8):
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True, pady=4)
    text = tk.Text(frame, height=height, wrap='word', font=('Meiryo', 10), padx=10, pady=10, undo=True)
    bar = ttk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y'); text.pack(fill='both', expand=True)
    return text


def list_area(parent):
    frame = ttk.Frame(parent); frame.pack(fill='both', expand=True)
    box = tk.Listbox(frame, exportselection=False, activestyle='none', font=('Meiryo', 10), height=8)
    bar = ttk.Scrollbar(frame, command=box.yview)
    box.configure(yscrollcommand=bar.set)
    bar.pack(side='right', fill='y'); box.pack(fill='both', expand=True)
    return box


class ScrollForm(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, width=550)
        bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y'); self.canvas.pack(fill='both', expand=True)
        self.content = ttk.Frame(self.canvas, padding=(8, 0, 12, 12))
        window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.content.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(window, width=e.width))
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta / 120), 'units'))


class Choice:
    """Keep stored IDs stable while presenting readable Japanese labels."""
    def __init__(self, parent, variable, labels):
        self.variable, self.labels = variable, labels
        self.display = tk.StringVar(master=parent)
        self.widget = ttk.Combobox(parent, textvariable=self.display, values=list(labels.values()), state='readonly')
        self.widget.pack(fill='x')
        variable.trace_add('write', self.sync)
        self.widget.bind('<<ComboboxSelected>>', self.selected)
        self.sync()

    def sync(self, *args):
        self.display.set(self.labels.get(self.variable.get(), self.variable.get()))

    def selected(self, event=None):
        for key, label in self.labels.items():
            if label == self.display.get():
                self.variable.set(key); break


class TaskRunner:
    """Workers never touch Tk; the UI polls results on its own event loop."""
    def __init__(self, parent, status):
        self.parent, self.status, self.busy = parent, status, False

    def run(self, label, work, done, buttons=()):
        if self.busy: return
        self.busy = True; self.status.set(label + '…')
        for button in buttons: button.state(['disabled'])
        result = queue.Queue()
        def worker():
            try: result.put((True, work()))
            except Exception as exc: result.put((False, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        def poll():
            try: ok, value = result.get_nowait()
            except queue.Empty:
                self.parent.after(80, poll); return
            self.busy = False
            for button in buttons: button.state(['!disabled'])
            if ok:
                try:
                    self.status.set(label + ' 完了')
                    done(value)
                except Exception as exc:
                    self.status.set(label + '後の保存に失敗しました')
                    messagebox.showerror('保存に失敗しました', str(exc), parent=self.parent.winfo_toplevel())
            else:
                self.status.set(label + 'に失敗しました')
                messagebox.showerror('操作に失敗しました', value, parent=self.parent.winfo_toplevel())
        self.parent.after(80, poll)
