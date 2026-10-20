# -*- coding: utf-8 -*-
"""Persistent household chest and rest mechanics; all rules are testable headless.

Online actions must be executed by the room server under its existing lock,
never by trusting client-submitted balances.
"""
from __future__ import annotations
import time
from farm_core import CROP_BY_ID
from fishing_core import FISH_BY_ID

STORAGE_CATEGORIES = ('seeds', 'warehouse', 'fish_inventory', 'consumables')
STORAGE_IDS = {
    'seeds': tuple(CROP_BY_ID),
    'warehouse': tuple(CROP_BY_ID),
    'fish_inventory': tuple(FISH_BY_ID),
    'consumables': ('tea', 'riceball', 'lunch'),
}
STORAGE_NAMES = {'seeds':'種', 'warehouse':'収穫物', 'fish_inventory':'魚', 'consumables':'食べ物'}

def init_town(state):
    if 'home_chest' not in state:
        state['home_chest'] = {category:{k:0 for k in keys} for category,keys in STORAGE_IDS.items()}
    return state


def validate_town(state):
    init_town(state)
    chest=state['home_chest']
    if not isinstance(chest, dict) or set(chest) != set(STORAGE_CATEGORIES):
        raise ValueError('自宅収納データが不正です')
    cleaned={}
    for category, keys in STORAGE_IDS.items():
        entries=chest.get(category)
        if not isinstance(entries, dict) or any(k not in keys for k in entries):
            raise ValueError('自宅収納のアイテムが不正です')
        if any(type(entries.get(k,0)) is not int or not 0 <= entries.get(k,0) <= 10000000 for k in keys):
            raise ValueError('自宅収納の個数が不正です')
        cleaned[category]={k: entries.get(k,0) for k in keys}
    state['home_chest']=cleaned
    return state


def move_chest(state, category, item_id, count, withdraw=False):
    """Atomic inventory/chest transfer, returning False without a partial move."""
    init_town(state)
    if (category not in STORAGE_IDS or item_id not in STORAGE_IDS[category]
            or type(count) is not int or count <= 0 or count > 9999
            or type(withdraw) is not bool):
        return False
    inventory=state.get(category)
    stored=state['home_chest'].get(category)
    if not isinstance(inventory,dict) or not isinstance(stored,dict):return False
    source, target=(stored, inventory) if withdraw else (inventory, stored)
    available=source.get(item_id)
    target_count=target.get(item_id)
    if (type(available) is not int or type(target_count) is not int or
            available < count or target_count < 0 or target_count+count > 10000000):
        return False
    source[item_id]=available-count
    target[item_id]=target_count+count
    return True


def rest_in_bed(state, now=None):
    """Rest at home replenishes farming stamina. No cost or cooldown."""
    before=state.get('stamina')
    if type(before) is not int or not 0 <= before <= 5:
        return False
    state['stamina']=5
    state['stamina_updated_at']=time.time() if now is None else float(now)
    return before < 5
