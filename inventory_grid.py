# -*- coding: utf-8 -*-
"""Minecraft-inspired 9x4 inventory view-model. No Pygame required."""
from farm_core import CROPS
from fishing_core import FISH
from v8_features import ITEMS

GRID_COLUMNS = 9
GRID_ROWS = 4
GRID_SLOTS = GRID_COLUMNS * GRID_ROWS
HOTBAR_SLOTS = 9


def slots(state):
    owned = []
    for crop in CROPS:
        n = int(state['seeds'].get(crop.id, 0))
        if n > 0:
            owned.append(('seed', crop.id, crop.name + 'の種', n))
    for crop in CROPS:
        n = int(state['warehouse'].get(crop.id, 0))
        if n > 0:
            owned.append(('crop', crop.id, crop.name, n))
    for fish in FISH:
        n = int(state['fish_inventory'].get(fish.id, 0))
        if n > 0:
            owned.append(('fish', fish.id, fish.name, n))
    for ident, (name, _, _) in ITEMS.items():
        n = int(state['consumables'].get(ident, 0))
        if n > 0:
            owned.append(('item', ident, name, n))
    tokens=int(state.get('event_tokens',0))
    if tokens>0:
        owned.append(('token','event_tokens','季節イベントメダル',tokens))
    return owned[:GRID_SLOTS] + [None] * max(0, GRID_SLOTS - len(owned))


def hotbar(offset=0):
    """12 seed types, paged 1-9 / 10-12 to keep number-key behavior useful."""
    return list(CROPS[offset:offset+HOTBAR_SLOTS])


def hotbar_offset(offset, direction):
    from farm_core import CROPS
    last = max(0, len(CROPS) - HOTBAR_SLOTS)
    return last if direction > 0 else 0
