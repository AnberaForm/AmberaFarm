# -*- coding: utf-8 -*-
"""Ambera Town 2.0: one source of truth for paths, districts and interactions.

The 24 farm plots and lake stay at their historical coordinates so existing saves
and multiplayer plot indices remain compatible across upgrades.
"""
from dataclasses import dataclass
from collections import deque
import math
import random

TILE = 32
WORLD_W, WORLD_H = 56, 36

@dataclass(frozen=True)
class Building:
    key: str
    label: str
    tile_x: int
    tile_y: int
    tile_w: int
    tile_h: int
    door_x: float
    door_y: float

    def bounds(self):
        return (self.tile_x*TILE, self.tile_y*TILE, self.tile_w*TILE, self.tile_h*TILE)

    def door(self):
        return (self.door_x*TILE, self.door_y*TILE)

# Distinct neighborhoods: farmhouse + greenhouse in the west, a north shopping
# avenue, a central village square, arena to the east and lakeside to the south.
BUILDINGS = (
    Building('home', 'わたしの家', 4, 2, 9, 6, 8.5, 8.6),
    Building('greenhouse', '温室', 15, 2, 7, 6, 18.5, 8.6),
    Building('shop', 'たね屋', 26, 2, 8, 6, 30, 8.6),
    Building('general_store', '道具・雑貨屋', 36, 2, 8, 6, 40, 8.6),
    Building('workshop', '衣装工房', 46, 2, 8, 6, 50, 8.6),
    Building('hall', 'アンベラ集会所', 45, 15, 9, 7, 49.5, 22.6),
    Building('cafe', 'カフェ', 27, 22, 7, 4, 30.5, 26.6),
    Building('shipping', '出荷所', 36, 24, 8, 5, 40, 29.6),
    Building('fish_market', '魚市場', 23, 29, 7, 4, 26.5, 33.6),
)
BUILDING_BY_ID = {b.key: b for b in BUILDINGS}

INTERACTION_POINTS = {
    **{b.key: b.door() for b in BUILDINGS},
    'missions': (26.5*TILE, 17.5*TILE),
    'fishing': (15*TILE, 29.5*TILE),
    'fisherman': (18.3*TILE, 27.9*TILE),
}


TRAVEL_STOPS = {
    'home': ('住宅街', (14.5*TILE, 9.5*TILE)),
    'plaza': ('こもれび広場', (31.5*TILE, 12.5*TILE)),
    'arena': ('集会所通り', (43.5*TILE, 23.5*TILE)),
    'lake': ('湖畔の桟橋', (17.5*TILE, 30.5*TILE)),
}

def nearest_travel_stop(x,y,radius=60):
    found=[(math.dist((x,y),point),ident) for ident,(_,point) in TRAVEL_STOPS.items()
           if math.dist((x,y),point)<=radius]
    return min(found)[1] if found else None

# A walkable tiled path network connects every doorstep, the existing farm,
# the plaza, pier and southern shoreline. Named in world tile coordinates.
def path_at(x, y):
    if 7 <= x <= 52 and y in (9, 10):
        return True  # northern shopping avenue
    if 22 <= x <= 35 and 13 <= y <= 21:
        return True  # central square
    if x in (23, 24) and 10 <= y <= 33:
        return True  # village north-south axis
    if x in (35, 36) and 10 <= y <= 31:
        return True  # eastern shopping access
    if 34 <= x <= 52 and y in (22, 23):
        return True  # arena avenue
    if 14 <= x <= 43 and y in (30, 31):
        return True  # lakeside promenade
    if 21 <= x <= 35 and y in (26, 27):
        return True  # cafe and southern area
    if 6 <= x <= 22 and y in (21, 22):
        return True  # farmland southern access
    if x in (20, 21) and 10 <= y <= 23:
        return True  # farmland eastern access
    if 13 <= x <= 22 and y in (28, 29):
        return True  # accessible fishing pier
    if x in (48, 49, 50) and 10 <= y <= 23:
        return True  # arena approach
    for b in BUILDINGS:
        if abs(x + .5 - b.door_x) < 1.35 and b.tile_y + b.tile_h <= y < b.tile_y + b.tile_h + 2:
            return True
    return False


def plaza_at(tx, ty):
    return 22 <= tx <= 34 and 13 <= ty <= 21


def district_at(x, y):
    """Named location for HUD; x/y measured in world pixels."""
    tx, ty = int(x // TILE), int(y // TILE)
    if 6 <= tx <= 20 and 10 <= ty <= 22:
        return 'わたしの牧場'
    if 2 <= tx <= 17 and 25 <= ty <= 34:
        return 'さざなみ湖'
    if tx >= 44 and 13 <= ty <= 25:
        return 'アンベラ・アリーナ通り'
    if 22 <= tx <= 36 and 12 <= ty <= 24:
        return 'こもれび広場'
    if 22 <= tx and ty <= 12:
        return 'お買いもの通り'
    if 21 <= tx and ty >= 26:
        return 'みなと小道'
    if ty <= 12:
        return '木漏れ日の住宅街'
    return 'アンベラの小道'


def fence_at(tx,ty):
    if 6 <= tx <= 19 and ty in (10,20):
        return not (ty == 20 and 11 <= tx <= 13)
    if tx in (6,19) and 10 <= ty <= 20:
        return not (tx == 19 and 13 <= ty <= 15)
    return False


def water_at(tx,ty):
    return 3 <= tx <= 13 and 26 <= ty <= 32


def _protected(tx, ty):
    if any(abs(tx+0.5-p[0]/TILE)<=1 and abs(ty+0.5-p[1]/TILE)<=1
           for _,p in TRAVEL_STOPS.values()):return True
    if 2 <= tx <= 17 and 25 <= ty <= 34:return True
    if 4 <= tx <= 21 and 9 <= ty <= 23:return True
    if path_at(tx,ty) or plaza_at(tx,ty):return True
    if (tx - 26)**2 + (ty - 16)**2 < 20:return True
    return any(b.tile_x - 2 <= tx <= b.tile_x + b.tile_w + 1 and
               b.tile_y - 2 <= ty <= b.tile_y + b.tile_h + 2 for b in BUILDINGS)


def make_trees():
    rng=random.Random(1937)
    positions=set()
    for _ in range(220):
        x,y=rng.randrange(2,WORLD_W-2),rng.randrange(2,WORLD_H-2)
        if not _protected(x,y):positions.add((x,y))
    return positions

TREE_POSITIONS=frozenset(make_trees())


def flower_at(tx,ty):
    """Decorative flowers, drawn in the cached ground layer; never block movement."""
    if water_at(tx,ty) or path_at(tx,ty) or plaza_at(tx,ty):return False
    if any(b.tile_x - 1 <= tx < b.tile_x + b.tile_w + 1 and
           b.tile_y - 1 <= ty < b.tile_y + b.tile_h + 2 for b in BUILDINGS):return False
    if (tx,ty) in TREE_POSITIONS or fence_at(tx,ty):return False
    return (tx*37+ty*29+tx*ty*3)%19 == 0


def obstacle_tile(tx,ty):
    if tx < 1 or ty < 1 or tx >= WORLD_W-1 or ty >= WORLD_H-1:return True
    if (tx,ty) in TREE_POSITIONS or water_at(tx,ty) or fence_at(tx,ty):return True
    if any(b.tile_x <= tx < b.tile_x+b.tile_w and b.tile_y <= ty < b.tile_y+b.tile_h for b in BUILDINGS):return True
    if (tx,ty)==(26,16):return True
    return False


def blocked(x,y):
    return obstacle_tile(math.floor(x/TILE),math.floor(y/TILE))


def can_stand(x,y,radius=7):
    return all(not blocked(x+dx,y+dy) for dx in (-radius,radius) for dy in (-radius,radius))


def plot_world(index):
    return ((8+(index%6)*2+.5)*TILE,(12+(index//6)*2+.5)*TILE)


def interaction_near(x,y,kind,radius=72):
    return math.dist((x,y),INTERACTION_POINTS[kind])<=radius


def test_reachability():
    start=(10,11)
    assert not obstacle_tile(*start), 'Starting position must remain unobstructed'
    seen={start};q=deque([start])
    while q:
        x,y=q.popleft()
        for pt in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if pt not in seen and not obstacle_tile(*pt):
                seen.add(pt);q.append(pt)
    targets={**INTERACTION_POINTS, **{f'plot{i}':plot_world(i) for i in range(24)},
             **{f'carriage_{k}':point for k,(_,point) in TRAVEL_STOPS.items()}}
    return [key for key,(px,py) in targets.items()
            if not any(math.dist(((x+.5)*TILE,(y+.5)*TILE),(px,py))<50 for x,y in seen)]
