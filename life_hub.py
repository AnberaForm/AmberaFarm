# -*- coding: utf-8 -*-
"""Version 9.1 farmer conveniences and cosmetics; pure Python for CI and saves.

The in-game daily reward is NOT a secure economy; online actions must be applied
by the room host. It cannot be purchased or redeemed for money.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from farm_core import CROP_BY_ID

DECOR = {
    'plant': ('鉢植え', {'kaiware': 3}, '収穫したカイワレで作る鉢植え'),
    'rug': ('牧場ラグ', {'radish': 2, 'potato': 1}, '柔らかい色の敷物'),
    'table': ('木のテーブル', {'tomato': 2, 'kyuri': 2}, '温もりのあるテーブル'),
    'lamp': ('星のランプ', {'corn': 2, 'ichigo': 2}, 'あたたかな星明かり'),
}
EMOTES = {'wave': '手を振る', 'cheer': 'やった！', 'heart': 'ありがとう', 'help': '手伝って！'}


def init_life(s):
    s.setdefault('login_reward', {'last': '', 'streak': 0})
    s.setdefault('favorite_crop', 'kaiware')
    s.setdefault('home_decor', ['plant'])
    s.setdefault('home_decor_selected', 'plant')
    s.setdefault('quick_quest_visible', True)
    s.setdefault('hud_inventory_visible', True)
    return s


def validate_life(s):
    init_life(s)
    log = s['login_reward']
    if not isinstance(log, dict) or not isinstance(log.get('last'), str) or len(log['last']) > 10:
        raise ValueError('ログインボーナスの記録が不正です')
    if type(log.get('streak')) is not int or not 0 <= log['streak'] <= 7:
        raise ValueError('ログイン日数が不正です')
    if log['last']:
        try: date.fromisoformat(log['last'])
        except ValueError as exc: raise ValueError('ログイン日付が不正です') from exc
    if s['favorite_crop'] not in CROP_BY_ID:
        raise ValueError('お気に入り作物が不正です')
    decor = s['home_decor']
    if (not isinstance(decor, list) or len(decor) > len(DECOR)
            or len(set(decor)) != len(decor) or any(k not in DECOR for k in decor)):
        raise ValueError('家具のデータが不正です')
    if s['home_decor_selected'] not in decor:
        s['home_decor_selected'] = decor[0] if decor else ''
    for name in ('quick_quest_visible', 'hud_inventory_visible'):
        if type(s[name]) is not bool:
            raise ValueError('表示設定が不正です')
    return s


def login_reward_view(s, now=None):
    init_life(s)
    today = (now or datetime.now()).date()
    last = s['login_reward']['last']
    claimed = last == today.isoformat()
    previous = False
    if last:
        try: previous = date.fromisoformat(last) == today - timedelta(days=1)
        except ValueError: pass
    next_streak = s['login_reward']['streak'] % 7 + 1 if previous else 1
    if claimed: next_streak = s['login_reward']['streak']
    prizes = (10, 15, 20, 25, 30, 40, 75)
    return {'day': next_streak, 'coins': prizes[next_streak - 1],
            'seed': 2 if next_streak == 7 else 0, 'claimed': claimed}


def claim_login_reward(s, now=None):
    view = login_reward_view(s, now)
    if view['claimed']: return False
    s['coins'] += view['coins']
    if view['seed']: s['seeds']['kaiware'] += view['seed']
    s['login_reward'] = {'last': (now or datetime.now()).date().isoformat(),
                         'streak': view['day']}
    return True


def craft_decor(s, key):
    init_life(s)
    if key not in DECOR or key in s['home_decor']: return False
    needs = DECOR[key][1]
    if any(int(s['warehouse'].get(item, 0)) < qty for item, qty in needs.items()): return False
    for item, qty in needs.items(): s['warehouse'][item] -= qty
    s['home_decor'].append(key)
    s['home_decor_selected'] = key
    return True


def set_decor(s, key):
    init_life(s)
    if key not in s['home_decor']: return False
    s['home_decor_selected'] = key
    return True


def claim_all_mail(s, mails):
    """Uses existing idempotent reward handling; returns number of newly claimed mails."""
    from v8_features import receive_public_mail
    count = 0
    for mail in mails[:100]:
        if receive_public_mail(s, mail): count += 1
    return count


def unread_mail_count(s, mails):
    claimed = set(s.get('mail_claimed', []))
    return sum(1 for m in mails if m.get('id') not in claimed)
