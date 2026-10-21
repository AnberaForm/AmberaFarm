# -*- coding: utf-8 -*-
"""Custom backpack/hotbar layout: visual position only, no duplicate items."""
import copy

from farm_core import new_state
from v8_features import init_v8
from inventory_grid import (
    owned_entries, reconcile_layout, entry_at, move_or_swap, quick_transfer,
    split_stack, sort_backpack, BACKPACK_SLOTS, TOTAL_SLOTS,
)


def make_state():
    return init_v8(new_state())


def assert_counts_match(layout, state):
    expected = {f'{kind}:{key}': count for kind, key, _, count in owned_entries(state)}
    actual = {}
    for slot in layout:
        if slot:
            actual[slot['key']] = actual.get(slot['key'], 0) + slot['qty']
    assert actual == expected
    assert len(layout) == TOTAL_SLOTS


def test_default_starter_seed_is_visible_in_first_hotbar_slot():
    state = make_state()
    layout = reconcile_layout([], state)
    assert entry_at(layout, state, BACKPACK_SLOTS) == ('seed','kaiware','カイワレ大根の種',4)
    assert all(slot is None for slot in layout[:BACKPACK_SLOTS])
    assert_counts_match(layout, state)


def test_drag_and_drop_move_and_swap_without_changing_stocks():
    state = make_state()
    state['warehouse']['tomato'] = 7
    state['seeds']['radish'] = 3
    original = copy.deepcopy(state)
    layout = reconcile_layout([], state)
    seed_slot = next(i for i, s in enumerate(layout) if s and s['key'] == 'seed:kaiware')
    crop_slot = next(i for i, s in enumerate(layout) if s and s['key'] == 'crop:tomato')
    layout, ok = move_or_swap(layout, seed_slot, crop_slot)
    assert ok
    assert layout[seed_slot]['key'] == 'crop:tomato'
    assert layout[crop_slot]['key'] == 'seed:kaiware'
    layout, ok = move_or_swap(layout, crop_slot, BACKPACK_SLOTS+4)
    assert ok
    assert layout[BACKPACK_SLOTS+4]['key'] == 'seed:kaiware'
    assert_counts_match(layout, state)
    assert state == original


def test_quick_transfer_between_bag_and_hotbar():
    state = make_state()
    layout = reconcile_layout([], state)
    state['seeds']['radish'] = 6
    layout = reconcile_layout(layout, state)
    source = next(i for i, s in enumerate(layout) if s and s['key'] == 'seed:radish')
    assert source < BACKPACK_SLOTS
    layout, ok = quick_transfer(layout, source)
    assert ok
    target = next(i for i, s in enumerate(layout) if s and s['key'] == 'seed:radish')
    assert target >= BACKPACK_SLOTS
    layout, ok = quick_transfer(layout, target)
    assert ok
    assert_counts_match(layout, state)


def test_split_then_merge_and_sort_preserves_hotbar():
    state = make_state()
    state['warehouse']['corn'] = 11
    state['warehouse']['tomato'] = 2
    layout = reconcile_layout([], state)
    corn = next(i for i, s in enumerate(layout) if s and s['key'] == 'crop:corn')
    layout, ok = split_stack(layout, corn)
    assert ok
    assert_counts_match(layout, state)
    corn_slots = [i for i, s in enumerate(layout) if s and s['key'] == 'crop:corn']
    assert len(corn_slots) == 2
    assert sorted(layout[i]['qty'] for i in corn_slots) == [5,6]
    hotbar_copy = copy.deepcopy(layout[BACKPACK_SLOTS:])
    sorted_layout = sort_backpack(layout)
    assert sorted_layout[BACKPACK_SLOTS:] == hotbar_copy
    assert_counts_match(sorted_layout, state)
    assert len([s for s in sorted_layout if s and s['key']=='crop:corn'])==1


def test_spent_and_restocked_items_reconcile_without_phantom_copies():
    state = make_state()
    state['seeds']['kaiware'] = 17
    layout = reconcile_layout([], state)
    layout, ok = split_stack(layout, BACKPACK_SLOTS)
    assert ok
    assert_counts_match(layout, state)
    state['seeds']['kaiware'] = 1
    layout = reconcile_layout(layout, state)
    assert_counts_match(layout, state)
    assert layout[BACKPACK_SLOTS] == {'key':'seed:kaiware','qty':1}
    state['seeds']['kaiware'] = 23
    layout = reconcile_layout(layout, state)
    assert_counts_match(layout, state)
    assert layout[BACKPACK_SLOTS]['qty'] == 23
    state['seeds']['kaiware'] = 0
    layout = reconcile_layout(layout, state)
    assert_counts_match(layout, state)
    assert layout[BACKPACK_SLOTS] is None


def test_saved_layout_roundtrip_and_new_item_preserve_existing_positions():
    import json
    state = make_state()
    state['fish_inventory']['medaka'] = 2
    layout = reconcile_layout([], state)
    fish_idx = next(i for i,s in enumerate(layout) if s and s['key']=='fish:medaka')
    layout,ok = move_or_swap(layout, fish_idx, BACKPACK_SLOTS+7)
    assert ok
    serialized=json.dumps(layout,ensure_ascii=False)
    restored=reconcile_layout(json.loads(serialized),state)
    assert restored == layout
    state['warehouse']['tomato']=4
    updated=reconcile_layout(restored,state)
    assert updated[BACKPACK_SLOTS+7]['key']=='fish:medaka'
    assert_counts_match(updated,state)


def test_corrupt_saved_layout_does_not_create_items():
    state = make_state()
    malicious=[{'key':'seed:kaiware','qty':10000000} for _ in range(TOTAL_SLOTS)]
    malicious[0]={'key':'crop:gold_coin','qty':9876}
    restored=reconcile_layout(malicious,state)
    assert_counts_match(restored,state)
    assert sum(s['qty'] for s in restored if s) == 4
    assert reconcile_layout(['invalid'],state) == reconcile_layout([],state)


def test_no_duplicate_on_online_state_replacement():
    state = make_state()
    layout = reconcile_layout([],state)
    incoming = copy.deepcopy(state)
    incoming['seeds']['kaiware'] = 0
    incoming['fish_inventory']['koi'] = 5
    layout = reconcile_layout(layout,incoming)
    assert_counts_match(layout,incoming)
    incoming['seeds']['kaiware'] = 2
    incoming['fish_inventory']['koi'] = 2
    layout = reconcile_layout(layout,incoming)
    assert_counts_match(layout,incoming)
