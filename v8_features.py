# -*- coding: utf-8 -*-
"""Ambera Farm v8 gameplay additions. Pure Python; zero pygame dependency.

Virtual currency only. These features deliberately do not claim global accounts,
a secure redemption backend, or Internet matchmaking.
"""
from __future__ import annotations
from datetime import datetime
import math
import re
import time
import uuid
from farm_core import PLOT_COUNT, CROP_BY_ID, plant, harvest, progress_for, time_short

MAX_STAMINA = 5
STAMINA_REGEN_SECONDS = 100  # 5 in-game minutes; works while offline
ITEMS = {'tea': ('お茶', 22, 1), 'riceball': ('おにぎり', 65, 3), 'lunch': ('特製弁当', 110, 5)}
EVENT_GOODS = {'autumn_hat': ('紅葉の帽子', 5), 'autumn_coat': ('収穫祭の上着', 9),
               'winter_cap': ('星の帽子', 5), 'winter_coat': ('冬祭りの上着', 9)}
OUTFIT_COLORS = ((57,79,134),(167,79,83),(73,125,93),(188,143,59),(113,79,148),(70,140,151),(234,173,109))


def init_v8(state):
    """In-place, idempotent migration for old v2 saves."""
    state.setdefault('stamina', 5)
    state.setdefault('stamina_updated_at', time.time())
    state.setdefault('plot_preparation', [0] * PLOT_COUNT)
    state.setdefault('consumables', {k: 0 for k in ITEMS})
    state.setdefault('outfits', [{'name':'いつもの服','shirt':0,'hat':0}])
    state.setdefault('outfit_index', 0)
    state.setdefault('outfit_draft', {'shirt':0,'hat':0})
    state.setdefault('friends', [])
    if 'player_uid' not in state:state['player_uid']=uuid.uuid4().hex
    state.setdefault('friend_ids', [])
    state.setdefault('local_chat', [])
    state.setdefault('player_name', '牧場主')
    state.setdefault('mail_claimed', [])
    state.setdefault('event_tokens', 0)
    state.setdefault('event_claimed', [])
    state.setdefault('event_earned_on', '')
    state.setdefault('event_daily_count', 0)
    return state


def validate_v8(raw):
    """Reject malformed extensions, retain unknown prior v2 fields elsewhere."""
    s = init_v8(raw)
    if type(s['stamina']) is not int or not 0 <= s['stamina'] <= MAX_STAMINA:
        raise ValueError('スタミナが不正です')
    if (isinstance(s['stamina_updated_at'],bool) or not isinstance(s['stamina_updated_at'],(int,float))
            or not math.isfinite(s['stamina_updated_at']) or s['stamina_updated_at']<0):
        raise ValueError('スタミナ回復の時刻が不正です')
    if (not isinstance(s['plot_preparation'],list) or len(s['plot_preparation']) != PLOT_COUNT
            or any(type(x) is not int or x not in (0,1,2) for x in s['plot_preparation'])):
        raise ValueError('畑の準備データが不正です')
    if not isinstance(s['consumables'],dict) or any(type(s['consumables'].get(k,0)) is not int or s['consumables'].get(k,0)<0 for k in ITEMS):
        raise ValueError('回復アイテムが不正です')
    s['consumables']={k:s['consumables'].get(k,0) for k in ITEMS}
    if not isinstance(s['outfits'],list) or len(s['outfits'])>20:
        raise ValueError('衣装データが不正です')
    for outfit in s['outfits']:
        if (not isinstance(outfit,dict) or not isinstance(outfit.get('name'),str) or len(outfit['name'])>20
                or any(type(outfit.get(k)) is not int or not 0<=outfit[k]<len(OUTFIT_COLORS) for k in ('shirt','hat'))):
            raise ValueError('衣装データが不正です')
    if not s['outfits']:s['outfits']=[{'name':'いつもの服','shirt':0,'hat':0}]
    if type(s['outfit_index']) is not int or not 0<=s['outfit_index']<len(s['outfits']):s['outfit_index']=0
    draft=s['outfit_draft']
    if not isinstance(draft,dict) or any(type(draft.get(k)) is not int or not 0<=draft[k]<len(OUTFIT_COLORS) for k in ('shirt','hat')):
        s['outfit_draft']={'shirt':0,'hat':0}
    if not isinstance(s['player_uid'],str) or not re.fullmatch(r'[0-9a-f]{32}',s['player_uid']):
        raise ValueError('プレイヤー識別情報が不正です')
    if (not isinstance(s['friend_ids'],list) or len(s['friend_ids'])>100 or
            any(not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{32}',x) for x in s['friend_ids'])):
        raise ValueError('フレンドIDが不正です')
    if not isinstance(s['friends'],list) or len(s['friends'])>100 or any(not isinstance(x,str) or len(x)>32 for x in s['friends']):
        raise ValueError('フレンドデータが不正です')
    if not isinstance(s['local_chat'],list):raise ValueError('ローカルチャットが不正です')
    s['local_chat']=[m for m in s['local_chat'][-40:] if isinstance(m,dict) and isinstance(m.get('text'),str) and len(m['text'])<=160]
    if not isinstance(s['player_name'],str) or len(s['player_name'])>18:s['player_name']='牧場主'
    for field in ('mail_claimed','event_claimed'):
        if not isinstance(s[field],list) or len(s[field])>1000 or any(not isinstance(x,str) or len(x)>80 for x in s[field]):
            raise ValueError(field + 'のデータが不正です')
    for field in ('event_tokens','event_daily_count'):
        if type(s[field]) is not int or s[field]<0:raise ValueError(field + 'が不正です')
    if not isinstance(s['event_earned_on'],str) or len(s['event_earned_on'])>12:raise ValueError('イベント日付が不正です')
    return s


def restore_stamina(state,now=None):
    """Offline-safe passive regen, every 100 actual seconds / 5 in-game minutes."""
    init_v8(state)
    now=time.time() if now is None else float(now)
    last=state['stamina_updated_at']
    if state['stamina']>=MAX_STAMINA:
        state['stamina_updated_at']=now
        return 0
    elapsed=max(0.,now-last)
    gained=int(elapsed//STAMINA_REGEN_SECONDS)
    if gained:
        before=state['stamina']
        state['stamina']=min(MAX_STAMINA,before+gained)
        state['stamina_updated_at']=now if state['stamina']==MAX_STAMINA else last+gained*STAMINA_REGEN_SECONDS
        return state['stamina']-before
    return 0


def field_phase(state,index):
    """Existing planted plots are already in the growing stage."""
    init_v8(state)
    if state['plots'][index] is not None:
        return 'ready' if progress_for(state['plots'][index])[2] else 'growing'
    return ('till','water','seed')[state['plot_preparation'][index]]


def field_action(state,index,crop_id,now=None):
    """One E/click advances one stage; exactly one heart for each step.

    Returns an action code, never deducts stamina on failed attempts.
    """
    init_v8(state)
    restore_stamina(state,now)
    if type(index) is not int or not 0<=index<PLOT_COUNT or crop_id not in CROP_BY_ID:
        return 'invalid'
    plot=state['plots'][index]
    if plot is not None and not progress_for(plot,now)[2]:return 'growing'
    if state['stamina']<1:return 'tired'
    if plot is not None:
        if harvest(state,index,now) is None:return 'growing'
        state['plot_preparation'][index]=0
        state['stamina']-=1
        earn_event_token(state,now)
        return 'harvest'
    phase=state['plot_preparation'][index]
    if phase==0:
        state['plot_preparation'][index]=1
        state['stamina']-=1
        return 'till'
    if phase==1:
        state['plot_preparation'][index]=2
        state['stamina']-=1
        return 'water'
    if phase==2:
        if state['seeds'][crop_id]<1:return 'seeds'
        if not plant(state,index,crop_id,now):return 'invalid'
        state['plot_preparation'][index]=0
        state['stamina']-=1
        return 'plant'
    return 'invalid'


def buy_consumable(state,item_id,quantity=1):
    init_v8(state)
    if item_id not in ITEMS or type(quantity) is not int or not 1<=quantity<=10:return False
    price=ITEMS[item_id][1]*quantity
    if state['coins']<price:return False
    state['coins']-=price
    state['consumables'][item_id]+=quantity
    return True


def use_consumable(state,item_id):
    init_v8(state)
    restore_stamina(state)
    if item_id not in ITEMS or state['consumables'][item_id]<1 or state['stamina']>=MAX_STAMINA:return False
    state['consumables'][item_id]-=1
    state['stamina']=min(MAX_STAMINA,state['stamina']+ITEMS[item_id][2])
    return True


def new_outfit(state):
    init_v8(state)
    if len(state['outfits'])>=20:return False
    selected={k:state['outfit_draft'][k] for k in ('shirt','hat')}
    state['outfits'].append(dict(name=f'マイ衣装 {len(state["outfits"])}',**selected))
    state['outfit_index']=len(state['outfits'])-1
    return True


def time_of_day(state,now=None):
    from farm_core import clock_at
    _,h,m=clock_at(state,now)
    if 5<=h<10:return '朝'
    if 10<=h<17:return '昼'
    if 17<=h<20:return '夕方'
    return '夜'


def active_event(now=None):
    date=datetime.fromtimestamp(time.time() if now is None else now)
    if date.month==10:
        return {'id':f'harvest_{date.year}', 'name':'秋の収穫祭',
                'description':'農業の収穫で「紅葉メダル」を集めて限定衣装と交換！',
                'ends':f'{date.year}-10-31'}
    if date.month in (12,1):
        return {'id':f'winter_{date.year if date.month==12 else date.year-1}',
                'name':'冬の星明かり祭', 'description':'農業の収穫で星メダルを集めよう！',
                'ends':f'{date.year}-12-31' if date.month==12 else f'{date.year}-01-31'}
    return None


def earn_event_token(state,now=None):
    init_v8(state)
    if active_event(now) is None:return False
    day=datetime.fromtimestamp(time.time() if now is None else now).strftime('%Y-%m-%d')
    if state['event_earned_on'] != day:
        state['event_earned_on']=day
        state['event_daily_count']=0
    if state['event_daily_count']>=20:return False
    state['event_tokens']+=1
    state['event_daily_count']+=1
    return True


def exchange_event(state,good_id,now=None):
    init_v8(state)
    event=active_event(now)
    if not event or good_id not in EVENT_GOODS or len(state['outfits'])>=20:return False
    if (good_id.startswith('autumn_') and not event['id'].startswith('harvest_')) or (
            good_id.startswith('winter_') and not event['id'].startswith('winter_')):return False
    award=event['id']+':'+good_id
    price=EVENT_GOODS[good_id][1]
    if award in state['event_claimed'] or state['event_tokens']<price:return False
    state['event_tokens']-=price
    state['event_claimed'].append(award)
    if good_id=='autumn_hat':state['outfits'].append({'name':'紅葉の帽子','shirt':0,'hat':3})
    if good_id=='autumn_coat':state['outfits'].append({'name':'収穫祭の上着','shirt':3,'hat':0})
    if good_id=='winter_cap':state['outfits'].append({'name':'星の帽子','shirt':0,'hat':5})
    if good_id=='winter_coat':state['outfits'].append({'name':'冬祭りの上着','shirt':5,'hat':0})
    return True


def add_friend(state,name):
    init_v8(state)
    name=''.join(c for c in str(name) if c.isprintable() and c not in '\n\r\t').strip()[:18]
    if not name or name==state['player_name'] or name in state['friends'] or len(state['friends'])>=100:return False
    state['friends'].append(name)
    return True


def receive_public_mail(state,mail):
    """Claim a public campaign ONCE locally; this is not private/signed mail.
    Call only with trusted prepackaged or HTTPS-fetched validated campaigns.
    """
    init_v8(state)
    if not isinstance(mail,dict) or not isinstance(mail.get('id'),str) or len(mail['id'])>80:return False
    if mail['id'] in state['mail_claimed']:return False
    if not isinstance(mail.get('coins'),int) or not 0<=mail['coins']<=250:return False
    item=mail.get('item','tea')
    if item not in ITEMS:return False
    count=mail.get('count',1)
    if type(count) is not int or not 0<=count<=3:return False
    state['coins']+=mail['coins']
    state['consumables'][item]+=count
    state['mail_claimed'].append(mail['id'])
    return True


def duel_practice(kind, choice, target):
    """Three no-stakes solo practice minigames; no pseudo-online opponents."""
    if kind=='guess':return int(choice)==int(target)
    if kind=='timing':return abs(float(choice)-float(target))<=.14
    if kind=='reaction':return float(choice)<=float(target)
    return False
