# -*- coding: utf-8 -*-
"""Independent world maps, entrances and foot-level collision geometry.

All positions in this module are map coordinates, never dialog coordinates.
The outdoor farm position stays untouched while visiting another map.
"""
from dataclasses import dataclass
import math
from interior_world import ROOMS, STATIONS, Station

OUTDOOR = 'outdoor'
NEIGHBOR = 'neighbor'
NEIGHBOR_STORE = 'neighbor:shop'


@dataclass(frozen=True)
class SceneMap:
    name: str
    asset: str
    size: tuple
    floor: tuple
    obstacles: tuple = ()
    spawn: tuple = (637., 519.)
    exit: tuple = (600, 654, 80, 50)


ROOM_NAMES = {'home': '自宅', 'shop': 'たね屋', 'shipping': '出荷所',
              'fish_market': '魚市場', 'general_store': '道具・雑貨屋',
              'hall': 'アンベラ集会所', 'greenhouse': '温室',
              'workshop': '衣装工房', 'cafe': 'カフェ'}
ROOM_OBSTACLES = {
    'home': ((340, 95, 150, 200), (764, 150, 125, 100),
             (545, 120, 165, 135), (970, 297, 140, 110)),
    'shop': ((370, 210, 325, 115),),
    'shipping': ((445, 170, 345, 130),),
    'fish_market': ((360, 185, 340, 130),),
    'general_store': ((450, 210, 350, 115),),
    'hall': ((345, 165, 190, 120), (735, 170, 200, 135)),
    'greenhouse': ((450, 210, 100, 70), (110, 180, 125, 310),
                   (1040, 180, 130, 310)),
    'workshop': ((410, 210, 180, 80),),
    'cafe': ((320, 215, 190, 70), (760, 215, 100, 70),
             (105, 365, 90, 90), (1055, 365, 90, 90)),
}
MAPS = {'room:' + key: SceneMap(name, key, (1280, 768), (96, 288, 1088, 416),
                               ROOM_OBSTACLES[key]) for key, name in ROOM_NAMES.items()}
# The neighboring town is a larger outdoor world with its own camera, bounds,
# shop doorway and return gate. It never uses the farm's coordinates/collisions.
MAPS[NEIGHBOR] = SceneMap('みずほ町', 'mizuho', (1600, 1024), (80, 260, 1440, 700),
                         ((330, 80, 620, 202), (1070, 100, 370, 210),
                          (960, 520, 570, 330), (120, 515, 390, 300)),
                         (760., 855.), (700, 898, 145, 62))
MAPS[NEIGHBOR_STORE] = SceneMap('みずほ町のたね屋', 'shop', (1280, 768),
                               (96, 288, 1088, 416), ROOM_OBSTACLES['shop'])
AREAS = (OUTDOOR,) + tuple(MAPS)
NEIGHBOR_DOOR = (637., 304.)
NEIGHBOR_SHOP_STATIONS = (Station('みずほ町の種を買う', 430, 302, 'neighbor_catalog'),)


def contains(rect, x, y, margin=0):
    left, top, width, height = rect
    return left-margin <= x <= left+width+margin and top-margin <= y <= top+height+margin


def can_stand(area, x, y, radius=9):
    if (area not in MAPS or type(x) not in (int, float) or type(y) not in (int, float)
            or not math.isfinite(x) or not math.isfinite(y)):
        return False
    spec = MAPS[area]
    left, top, width, height = spec.floor
    if not (left+radius <= x <= left+width-radius and top+radius <= y <= top+height-radius):
        return False
    return not any(contains(rect, x, y, radius) for rect in spec.obstacles)


def path_clear(area, start, end):
    if not can_stand(area, *start) or not can_stand(area, *end):
        return False
    distance = math.dist(start, end)
    for index in range(1, max(1, math.ceil(distance/5))+1):
        t = index/max(1, math.ceil(distance/5))
        if not can_stand(area, start[0]+(end[0]-start[0])*t, start[1]+(end[1]-start[1])*t):
            return False
    return True


def move(area, point, dx, dy):
    if not all(type(n) in (int, float) and math.isfinite(n) for n in (*point, dx, dy)):
        return tuple(point)
    if math.hypot(dx, dy) > 128:
        return tuple(point)
    steps = max(1, math.ceil(max(abs(dx), abs(dy))/5))
    x, y = point
    for _ in range(steps):
        if can_stand(area, x+dx/steps, y): x += dx/steps
        if can_stand(area, x, y+dy/steps): y += dy/steps
    return x, y


def spawn(area, source=None):
    if area == NEIGHBOR and source == NEIGHBOR_STORE:
        return (637., 350.)
    return MAPS[area].spawn if area in MAPS else (637., 519.)


def exit_target(area):
    return NEIGHBOR if area == NEIGHBOR_STORE else OUTDOOR


def at_exit(area, position):
    return area in MAPS and contains(MAPS[area].exit, *position)


def stations(area):
    if area == NEIGHBOR_STORE:
        return NEIGHBOR_SHOP_STATIONS
    return STATIONS.get(area[5:], ()) if area.startswith('room:') else ()


def nearby(area, position, radius=90):
    candidates = stations(area)
    closest = min(candidates, key=lambda item: math.dist(position, (item.x, item.y)), default=None)
    return closest if closest and math.dist(position, (closest.x, closest.y)) <= radius else None


def camera(area, position, viewport):
    width, height = MAPS[area].size
    return (max(0., min(max(0, width-viewport[0]), position[0]-viewport[0]/2)),
            max(0., min(max(0, height-viewport[1]), position[1]-viewport[1]*.56)))
