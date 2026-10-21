# -*- coding: utf-8 -*-
"""Shared scene rules for room-authoritative interiors and neighboring town."""
import math
from interior_world import ROOMS, STATIONS, SPAWN, walkable
from world_map import INTERACTION_POINTS, nearest_travel_stop

OUTDOOR = 'outdoor'
NEIGHBOR = 'neighbor'
AREAS = (OUTDOOR, NEIGHBOR) + tuple('room:' + r for r in ROOMS)
DIRECTIONS = ('down', 'left', 'right', 'up')


def can_enter(player, target):
    if target == OUTDOOR:
        return player.get('area', OUTDOOR) in AREAS
    if player.get('area', OUTDOOR) != OUTDOOR:
        return False
    if target == NEIGHBOR:
        return nearest_travel_stop(player['x'], player['y'], 100) is not None
    if target in AREAS and target.startswith('room:'):
        return math.dist((player['x'], player['y']), INTERACTION_POINTS[target[5:]]) <= 100
    return False


def at_facility(player, facility, radius=100):
    area = player.get('area', OUTDOOR)
    if area == OUTDOOR:
        return math.dist((player['x'], player['y']), INTERACTION_POINTS[facility]) <= radius
    if area == 'room:' + facility or facility == 'general_store' and area == 'room:cafe':
        stations = STATIONS[area[5:]]
        return any(math.dist((player.get('scene_x', SPAWN[0]), player.get('scene_y', SPAWN[1])),
                             (s.x, s.y)) <= max(100, radius) for s in stations)
    return False


def area_view(player):
    return {'area': player.get('area', OUTDOOR),
            'pos': [player.get('scene_x', SPAWN[0]), player.get('scene_y', SPAWN[1])],
            'seq': player.get('scene_seq', -1),
            'revision': player.get('scene_revision', 0)}


def valid_scene_point(x, y):
    return (type(x) in (int, float) and type(y) in (int, float)
            and math.isfinite(x) and math.isfinite(y) and walkable(x, y))
