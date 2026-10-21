# -*- coding: utf-8 -*-
"""Small neighboring town, shops and deterministic purchases, no Pygame requirement."""
from farm_core import CROP_BY_ID, buy_seeds

TOWN_NAME='みずほ町'
# Different town inventory. Keeps existing item/crop IDs rather than inventing
# unrecognized items that would break V2 save migration.
TOWN_STOCK=('ichigo','kyuri','corn','komugi','kabotya','suika')

def shop_rows(state):
    return [(key,CROP_BY_ID[key].name,CROP_BY_ID[key].buy_price,state['seeds'][key]) for key in TOWN_STOCK]

def town_buy(state,key,count):
    if key not in TOWN_STOCK or type(count) is not int or count not in (1,5,10):
        return False
    return buy_seeds(state,key,count)
