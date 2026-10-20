# -*- coding: utf-8 -*-
"""Room-scoped cooperative delivery board.

Authoritative donations deduct only the donating player's own inventory.
The board is transient per room; balances/items stay with each player's save.
"""
from __future__ import annotations
from farm_core import CROP_BY_ID
from fishing_core import FISH_BY_ID

ORDERS = (
    ('sprouts', 'みんなの朝市', 'crop', 'kaiware', 3, 40),
    ('radish', '村の食卓', 'crop', 'radish', 3, 65),
    ('lake', '湖畔の食堂', 'fish', 'medaka', 2, 55),
)


def new_board():
    return [{'id': ident, 'title': title, 'kind': kind, 'item': item,
             'target': target, 'count': 0, 'reward': reward,
             'contributors': {}, 'paid': False}
            for ident,title,kind,item,target,reward in ORDERS]


def view(board):
    return [{k: entry[k] for k in ('id','title','kind','item','target','count','reward','paid')}
            for entry in board]


def contribute(board, order_id, player_id, profile, players, amount=1):
    """Donate 1/3 units. Return a short player-facing status. Runs under room lock."""
    entry = next((e for e in board if e['id']==order_id), None)
    if entry is None or entry['paid']:
        return 'この共同依頼は終了しています'
    if type(amount) is not int or amount not in (1, 3):
        return '納品数が不正です'
    catalog = CROP_BY_ID if entry['kind']=='crop' else FISH_BY_ID
    if entry['item'] not in catalog:
        return '依頼データが不正です'
    inventory = profile['warehouse'] if entry['kind']=='crop' else profile['fish_inventory']
    usable = min(amount, entry['target']-entry['count'])
    if inventory.get(entry['item'], 0) < usable:
        return '納品する品物が足りません'
    inventory[entry['item']] -= usable
    entry['count'] += usable
    entry['contributors'][player_id] = entry['contributors'].get(player_id, 0) + usable
    if entry['count'] >= entry['target']:
        entry['paid'] = True
        # Only participants receive the completion reward, once each.
        # Disconnecting participants cannot cause unrelated players to be paid.
        for pid in entry['contributors']:
            if pid in players:
                players[pid]['profile']['coins'] += entry['reward']
        return f'共同依頼「{entry["title"]}」達成！ 参加者に{entry["reward"]}G'
    return f'共同納品 +{usable}個（{entry["count"]}/{entry["target"]}）'
