# -*- coding: utf-8 -*-
"""Single authoritative layout for drawing, collision and interactions.
No third-party modules. All positions in world pixel coordinates.
"""
from dataclasses import dataclass
import math

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
    door_x: float  # in world tile coordinates, not sprite origin
    door_y: float
    def bounds(self):
        return (self.tile_x*TILE,self.tile_y*TILE,self.tile_w*TILE,self.tile_h*TILE)
    def door(self):
        return (self.door_x*TILE, self.door_y*TILE)

BUILDINGS = (
    Building('home','自宅',5,2,8,6,9.0,8.65),
    Building('shop','たね屋',37,7,7,6,40.5,13.65),
    Building('shipping','出荷所',37,22,7,5,40.5,27.7),
    Building('fish_market','魚市場',24,26,6,3,26.4,29.65),
    Building('general_store','雑貨屋',28,2,7,5,31.5,7.65),
    Building('hall','集会所',46,18,8,6,50.0,24.7),
)
BUILDING_BY_ID = {b.key:b for b in BUILDINGS}

# Sufficient distance from a wall for the avatar to approach the door.  All are
# outside the impenetrable building rectangles, unlike the previous display.
INTERACTION_POINTS = {
    **{b.key:b.door() for b in BUILDINGS},
    'missions':(26.5*TILE,17.5*TILE),
    'fishing':(15*TILE,29.5*TILE),
    'fisherman':(18.3*TILE,27.9*TILE),
}

# Fence segments have gaps at the southern entrance and the east entrance.
def fence_at(tx,ty):
    if 6<=tx<=19 and ty in (10,20):
        return not (ty==20 and 11<=tx<=13)
    if tx in (6,19) and 10<=ty<=20:
        return not (tx==19 and 13<=ty<=15)
    return False

# The pier is accessible through the east side of the lake.
def water_at(tx,ty):
    return 3<=tx<=13 and 26<=ty<=32

# Map trees deterministically and place away from roads, structures and key areas.
def make_trees():
    import random
    rng=random.Random(1937)
    trees=set()
    for _ in range(165):
        x,y=rng.randrange(2,WORLD_W-2),rng.randrange(2,WORLD_H-2)
        if 5<=x<=45 and 8<=y<=30: continue
        if 2<=x<=16 and 25<=y<=33:continue
        if any(b.tile_x-2<=x<=b.tile_x+b.tile_w+2 and
               b.tile_y-2<=y<=b.tile_y+b.tile_h+2 for b in BUILDINGS):continue
        trees.add((x,y))
    for x in (3,4,7,13,46,48,50,53):
        for y in (4,9,18,24,32):
            if 5<=x<=45 and 8<=y<=30:continue
            if 2<=x<=16 and 25<=y<=33:continue
            if any(b.tile_x-2<=x<=b.tile_x+b.tile_w+2 and
                   b.tile_y-2<=y<=b.tile_y+b.tile_h+2 for b in BUILDINGS):continue
            trees.add((x,y))
    return trees

TREE_POSITIONS = frozenset(make_trees())

def obstacle_tile(tx,ty):
    if tx<1 or ty<1 or tx>=WORLD_W-1 or ty>=WORLD_H-1:return True
    if (tx,ty) in TREE_POSITIONS:return True
    if water_at(tx,ty) or fence_at(tx,ty):return True
    if any(b.tile_x<=tx<b.tile_x+b.tile_w and b.tile_y<=ty<b.tile_y+b.tile_h for b in BUILDINGS):return True
    if (tx,ty)==(26,16):return True   # solid notice board
    return False

def blocked(x,y):
    return obstacle_tile(math.floor(x/TILE), math.floor(y/TILE))

def can_stand(x,y,radius=7):
    return all(not blocked(x+ox,y+oy) for ox in (-radius,radius) for oy in (-radius,radius))

def plot_world(index):
    return ((8+(index%6)*2+.5)*TILE,(12+(index//6)*2+.5)*TILE)

def interaction_near(x,y,kind,radius=72):
    p=INTERACTION_POINTS[kind]
    return math.dist((x,y),p)<=radius

def test_reachability():
    """Floodfill walkable tile centers from player start. Door and field locations reachable."""
    from collections import deque
    start=(10,11)
    assert not obstacle_tile(*start), 'Start is obstructed'
    seen={start};queue=deque([start])
    while queue:
        x,y=queue.popleft()
        for candidate in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if candidate not in seen and not obstacle_tile(*candidate):
                seen.add(candidate);queue.append(candidate)
    targets={key:point for key,point in INTERACTION_POINTS.items()}
    targets.update({f'plot{i}':plot_world(i) for i in range(24)})
    unreachable=[]
    for key,(px,py) in targets.items():
        # Players must be able to get close enough, not necessarily occupy a plot.
        if not any(math.dist(((x+.5)*TILE,(y+.5)*TILE),(px,py))<50 for x,y in seen):
            unreachable.append(key)
    return unreachable
