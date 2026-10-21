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

# v9.1 backpack layout: placement is local UI metadata only. Inventory quantities
# always come from the authoritative farm state (the room host when online).
BACKPACK_SLOTS = GRID_SLOTS
TOTAL_SLOTS = BACKPACK_SLOTS + HOTBAR_SLOTS


def owned_entries(state):
    """Return every owned item; do not truncate to the backpack's 36 slots."""
    entries = []
    for crop in CROPS:
        quantity = int(state.get('seeds', {}).get(crop.id, 0))
        if quantity > 0:
            entries.append(('seed', crop.id, crop.name+'の種', quantity))
    for crop in CROPS:
        quantity = int(state.get('warehouse', {}).get(crop.id, 0))
        if quantity > 0:
            entries.append(('crop', crop.id, crop.name, quantity))
    for fish in FISH:
        quantity = int(state.get('fish_inventory', {}).get(fish.id, 0))
        if quantity > 0:
            entries.append(('fish', fish.id, fish.name, quantity))
    for ident, (name, _, _) in ITEMS.items():
        quantity = int(state.get('consumables', {}).get(ident, 0))
        if quantity > 0:
            entries.append(('item', ident, name, quantity))
    quantity = int(state.get('event_tokens', 0))
    if quantity > 0:
        entries.append(('token', 'event_tokens', '季節イベントメダル', quantity))
    return entries


def item_key(entry):
    return f'{entry[0]}:{entry[1]}'


def _empty_layout():
    return [None] * TOTAL_SLOTS


def reconcile_layout(layout, state):
    """Reconcile a player-chosen layout with trusted item counts.

    The layout is NEVER an inventory: fabricated slot counts/keys are discarded.
    Existing split stacks preserve their placement when stock grows or shrinks.
    """
    catalog = {item_key(e): e for e in owned_entries(state)}
    remaining = {key: entry[3] for key, entry in catalog.items()}
    result = _empty_layout()
    if not isinstance(layout, list):
        layout = []
    # Prioritize pinned hotbar stacks when consumables/seeds are spent.
    order = list(range(BACKPACK_SLOTS, TOTAL_SLOTS)) + list(range(BACKPACK_SLOTS))
    for index in order:
        value = layout[index] if index < len(layout) else None
        if not isinstance(value, dict):
            continue
        key, quantity = value.get('key'), value.get('qty')
        if key not in catalog or type(quantity) is not int or quantity < 1:
            continue
        taken = min(quantity, remaining[key])
        if taken > 0:
            result[index] = {'key': key, 'qty': taken}
            remaining[key] -= taken
    # First load defaults: the starting seed goes in hotbar slot 1.
    fresh = not any(isinstance(x, dict) for x in layout[:TOTAL_SLOTS])
    for entry in catalog.values():
        key = item_key(entry)
        amount = remaining[key]
        if not amount:
            continue
        current_slot = next((i for i, s in enumerate(result) if s is not None and s['key'] == key), None)
        if current_slot is not None:
            result[current_slot]['qty'] += amount
            continue
        if entry[0] == 'seed' and fresh:
            candidates = list(range(BACKPACK_SLOTS, TOTAL_SLOTS)) + list(range(BACKPACK_SLOTS))
        else:
            candidates = list(range(BACKPACK_SLOTS)) + list(range(BACKPACK_SLOTS, TOTAL_SLOTS))
        dest = next((i for i in candidates if result[i] is None), None)
        if dest is not None:
            result[dest] = {'key': key, 'qty': amount}
        # If all 45 slots are occupied, leave excess *visible through owned_entries*
        # without dropping it from the real inventory state.
    return result


def entry_at(layout, state, index):
    """Display entry compatible with the existing icon renderer."""
    if not (0 <= index < TOTAL_SLOTS):
        return None
    slot = reconcile_layout(layout, state)[index]
    if slot is None:
        return None
    entry = next((e for e in owned_entries(state) if item_key(e) == slot['key']), None)
    return (entry[0], entry[1], entry[2], slot['qty']) if entry else None


def move_or_swap(layout, source, target):
    """Drag/drop: swap different items, move onto an empty slot, merge same items."""
    if not (0 <= source < TOTAL_SLOTS and 0 <= target < TOTAL_SLOTS):
        return layout, False
    if source == target or layout[source] is None:
        return layout, False
    updated = [dict(s) if s else None for s in layout]
    left, right = updated[source], updated[target]
    if right is not None and right['key'] == left['key']:
        right['qty'] += left['qty']
        updated[source] = None
    else:
        updated[source], updated[target] = right, left
    return updated, True


def quick_transfer(layout, source):
    """Shift-click moves an entire stack between bag and hotbar."""
    if not (0 <= source < TOTAL_SLOTS) or layout[source] is None:
        return layout, False
    destinations = (range(BACKPACK_SLOTS, TOTAL_SLOTS) if source < BACKPACK_SLOTS
                    else range(BACKPACK_SLOTS))
    # Prefer an empty slot to preserve a deliberately split stack.
    destination = next((i for i in destinations if layout[i] is None), None)
    if destination is None:
        destination = next((i for i in destinations if layout[i]['key'] == layout[source]['key']), None)
    return move_or_swap(layout, source, destination) if destination is not None else (layout, False)


def split_stack(layout, source):
    """Right-click divides a stack into two; items remain unchanged in total."""
    if not (0 <= source < TOTAL_SLOTS) or layout[source] is None or layout[source]['qty'] < 2:
        return layout, False
    section = (list(range(BACKPACK_SLOTS)) if source < BACKPACK_SLOTS
               else list(range(BACKPACK_SLOTS, TOTAL_SLOTS)))
    destination = next((i for i in section if layout[i] is None), None)
    if destination is None:
        destination = next((i for i, slot in enumerate(layout) if slot is None), None)
    if destination is None:
        return layout, False
    updated = [dict(s) if s else None for s in layout]
    amount = updated[source]['qty'] // 2
    updated[source]['qty'] -= amount
    updated[destination] = {'key': updated[source]['key'], 'qty': amount}
    return updated, True


def sort_backpack(layout):
    """Sort and merge only the 36 backpack slots; preserve hotbar exactly."""
    ranked = {'seed': 0, 'crop': 1, 'fish': 2, 'item': 3, 'token': 4}
    totals = {}
    for slot in layout[:BACKPACK_SLOTS]:
        if slot:
            totals[slot['key']] = totals.get(slot['key'], 0) + slot['qty']
    keys = sorted(totals, key=lambda key: (ranked.get(key.partition(':')[0], 9), key))
    updated = [{'key': key, 'qty': totals[key]} for key in keys]
    updated.extend([None] * (BACKPACK_SLOTS-len(updated)))
    updated.extend(dict(s) if s else None for s in layout[BACKPACK_SLOTS:TOTAL_SLOTS])
    return updated
