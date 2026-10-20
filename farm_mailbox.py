# -*- coding: utf-8 -*-
"""Public, one-time per-save gift campaigns published via owner-controlled GitHub.

Not private mail. No user account guarantee, no cash value, and rewards are small.
"""
from __future__ import annotations
import json,os,re,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
from farm_core import state_path
from notices import REPO
from v8_features import ITEMS
MAIL_URL=f'https://raw.githubusercontent.com/{REPO}/main/data/mail_campaigns.json'
MAX_BYTES=16000

def validate(obj):
    if not isinstance(obj,dict) or obj.get('schema')!=1 or not isinstance(obj.get('campaigns'),list) or len(obj['campaigns'])>40:
        raise ValueError('配布データ形式が不正です')
    clean=[];ids=set()
    for m in obj['campaigns']:
        if (not isinstance(m,dict) or not isinstance(m.get('id'),str) or
                not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',m['id']) or m['id'] in ids or
                not isinstance(m.get('title'),str) or not 1<=len(m['title'])<=60 or
                type(m.get('coins')) is not int or not 0<=m['coins']<=250 or
                m.get('item') not in ITEMS or type(m.get('count')) is not int or not 0<=m['count']<=3):
            raise ValueError('配布メールの入力に問題があります')
        ids.add(m['id']);clean.append({k:m[k] for k in ('id','title','coins','item','count')})
    return {'schema':1,'campaigns':clean}

def cache_file():return state_path().parent/'mail_campaigns_cache.json'
def bundled_file():return Path(__file__).resolve().parent/'data'/'mail_campaigns.json'
def load():
    for p in (cache_file(),bundled_file()):
        try:return validate(json.loads(p.read_text(encoding='utf-8-sig')))['campaigns']
        except (OSError,ValueError,UnicodeError):pass
    return []
def fetch(timeout=6):
    request=Request(MAIL_URL,headers={'User-Agent':'AmberaFarm-Mail/8','Cache-Control':'no-cache'})
    with urlopen(request,timeout=timeout) as response:
        if response.geturl().split('?')[0]!=MAIL_URL:raise ValueError('公開先が変更されました')
        payload=response.read(MAX_BYTES+1)
    if len(payload)>MAX_BYTES:raise ValueError('配布データが大きすぎます')
    clean=validate(json.loads(payload.decode('utf-8-sig')))
    out=cache_file();out.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=out.parent,prefix='.mail_',suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as fp:json.dump(clean,fp,ensure_ascii=False,indent=2)
        os.replace(name,out)
    finally:
        if os.path.exists(name):os.unlink(name)
    return clean['campaigns']
