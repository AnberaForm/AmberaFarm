# -*- coding: utf-8 -*-
"""Offline-safe farmer progress, daily requests, titles and public profiles.

The public profile is deliberately a small allowlist.  Inventory, wallet and
other private save fields must not be broadcast to other players.
"""
from __future__ import annotations
from datetime import datetime
import copy
import math

STAT_KEYS = ('planted', 'harvested', 'fish_caught', 'shipped', 'fish_sold')
TITLE_LABELS = {
    'farmer': '駆け出し牧場主',
    'sprout': '芽吹きの農家',
    'harvester': '収穫の達人',
    'angler': '伝説を目指す釣り師',
    'kabuball': 'カブボール初勝利',
    'champion': 'カブボール王者',
}
DAILY_QUESTS = (
    ('planted', 2, 30, 28, '種を2回植えよう'),
    ('harvested', 2, 50, 36, '作物を2つ収穫しよう'),
    ('fish_caught', 1, 40, 30, '魚を1匹釣り上げよう'),
)

def clean_bio(s):
    return ''.join(c for c in str(s) if c.isprintable() and c not in '\r\n\t')[:90]

def init_profile(s, day=None):
    s.setdefault('farm_xp', 0)
    s.setdefault('farm_level', 1)
    s.setdefault('farm_stat_seen', {k: max(0,int(s.get('stats',{}).get(k,0))) for k in STAT_KEYS})
    s.setdefault('daily_board', {})
    s.setdefault('profile_bio', '')
    s.setdefault('profile_title', 'farmer')
    s.setdefault('goal_effect', 0)
    s.setdefault('profile_cache', {})
    s.setdefault('arena_record', {'wins':0,'losses':0,'draws':0,'goals':0,'conceded':0,'rating':1000,'best_streak':0,'streak':0,'recent':[]})
    if not isinstance(s.get('daily_board'),dict):s['daily_board']={}
    if not isinstance(s.get('profile_cache'),dict):s['profile_cache']={}
    ensure_board(s,day)
    return s

def validate_profile(s):
    init_profile(s)
    for key in ('farm_xp', 'farm_level'):
        if type(s[key]) is not int or not 0 <= s[key] <= 100000000:
            raise ValueError('農場レベル情報が不正です')
    if not isinstance(s['farm_stat_seen'],dict) or any(type(s['farm_stat_seen'].get(k)) is not int or s['farm_stat_seen'][k]<0 for k in STAT_KEYS):
        raise ValueError('経験値の記録が不正です')
    if not isinstance(s['profile_bio'],str) or len(s['profile_bio'])>90:
        raise ValueError('自己紹介文が不正です')
    if type(s['goal_effect']) is not int or s['goal_effect'] not in (0,1,2):raise ValueError('ゴール演出が不正です')
    if s['profile_title'] not in TITLE_LABELS or s['profile_title'] not in unlocked_titles(s):
        s['profile_title']='farmer'
    rec=s['arena_record']
    if not isinstance(rec,dict):raise ValueError('戦績が不正です')
    for k in ('wins','losses','draws','goals','conceded','best_streak','streak'):
        if type(rec.get(k)) is not int or not 0 <= rec[k]<=100000000:raise ValueError('戦績が不正です')
    if type(rec.get('rating')) is not int or not 0 <= rec['rating'] <= 1000000:raise ValueError('レートが不正です')
    if not isinstance(rec.get('recent'),list) or len(rec['recent'])>12:
        raise ValueError('試合履歴が不正です')
    if not isinstance(s['profile_cache'],dict) or len(s['profile_cache'])>120:
        raise ValueError('プロフィール履歴が不正です')
    return s

def unlocked_titles(s):
    rec=s.get('arena_record',{})
    stats=s.get('stats',{})
    a=['farmer']
    if s.get('farm_level',1)>=3:a.append('sprout')
    if stats.get('harvested',0)>=30:a.append('harvester')
    if stats.get('fish_caught',0)>=15:a.append('angler')
    if rec.get('wins',0)>=1:a.append('kabuball')
    if rec.get('wins',0)>=15:a.append('champion')
    return a

def level_from_xp(xp):
    # Quadratic progression; v8 saves start at level 1 without retroactively awarding XP.
    level=1
    while level < 50 and xp >= 50*(level*(level+1)):
        level+=1
    return level

def refresh_progress(s):
    init_profile(s)
    delta=0
    weights={'planted':8,'harvested':14,'fish_caught':12,'shipped':5,'fish_sold':5}
    for k in STAT_KEYS:
        current=max(0,int(s['stats'].get(k,0)))
        previous=max(0,int(s['farm_stat_seen'].get(k,0)))
        if current>previous:delta+=min(current-previous,10000)*weights[k]
        s['farm_stat_seen'][k]=current
    s['farm_xp']=min(100000000,s['farm_xp']+delta)
    s['farm_level']=level_from_xp(s['farm_xp'])
    return delta

def ensure_board(s, day=None):
    today=day or datetime.now().date().isoformat()
    board=s.get('daily_board',{})
    if board.get('day') != today:
        s['daily_board']={'day':today,
          'baseline':{k:max(0,int(s.get('stats',{}).get(k,0))) for k in STAT_KEYS},
          'claimed':[]}
    return s['daily_board']

def board_rows(s,day=None):
    init_profile(s,day)
    rows=[]
    for k,target,coins,xp,label in DAILY_QUESTS:
        progress=max(0,int(s['stats'].get(k,0))-int(s['daily_board']['baseline'].get(k,0)))
        rows.append({'id':k, 'name':label, 'progress':min(target,progress),'target':target,
                     'coins':coins, 'xp':xp, 'claimed':k in s['daily_board']['claimed']})
    return rows

def claim_daily(s,key,day=None):
    for entry in board_rows(s,day):
        if entry['id']==key and entry['progress']>=entry['target'] and not entry['claimed']:
            s['daily_board']['claimed'].append(key)
            s['coins']+=entry['coins']
            s['farm_xp']+=entry['xp']
            s['farm_level']=level_from_xp(s['farm_xp'])
            return True
    return False

def apply_arena_result(s,scored,conceded,opponent,match_id):
    """Apply exactly once to a player's match history; G never changes."""
    init_profile(s)
    rec=s['arena_record']
    if any(x.get('id')==match_id for x in rec['recent']):return False
    scored=int(scored);conceded=int(conceded)
    outcome='win' if scored>conceded else ('loss' if scored<conceded else 'draw')
    if outcome=='win':
        rec['wins']+=1;rec['streak']+=1;rec['best_streak']=max(rec['best_streak'],rec['streak'])
        rec['rating']+=15
    elif outcome=='loss':
        rec['losses']+=1;rec['streak']=0;rec['rating']=max(0,rec['rating']-12)
    else:rec['draws']+=1;rec['streak']=0
    rec['goals']+=scored;rec['conceded']+=conceded
    rec['recent']=(rec['recent']+[{'id':match_id,'against':str(opponent)[:18], 'score':f'{scored}-{conceded}', 'outcome':outcome}])[-12:]
    return True

def public_profile(s):
    if 'player_uid' not in s:
        from v8_features import init_v8
        init_v8(s)
    init_profile(s)
    rec=s['arena_record']
    return {'uid':s['player_uid'],'name':s['player_name'],
        'bio':clean_bio(s.get('profile_bio','')), 'title':s.get('profile_title','farmer'),
        'farm_level':s['farm_level'], 'arena_record':{k:rec[k] for k in ('wins','losses','draws','rating','best_streak')}}

def cache_public_profiles(state,players):
    init_profile(state)
    friends=set(state.get('friend_ids',[]))
    for p in players:
        if not isinstance(p,dict):continue
        info=p.get('public_profile')
        if isinstance(info,dict) and info.get('uid') in friends and info['uid']!=state.get('player_uid'):
            state['profile_cache'][info['uid']]=copy.deepcopy(info)
    # Bound saved cache
    if len(state['profile_cache'])>100:
        for uid in list(state['profile_cache'])[:-100]:state['profile_cache'].pop(uid,None)
