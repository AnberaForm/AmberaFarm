# -*- coding: utf-8 -*-
"""Shared scene rules for room-authoritative interiors and neighboring town."""
import math
from interior_world import STATIONS, SPAWN
from scene_maps import (OUTDOOR, NEIGHBOR, NEIGHBOR_STORE, AREAS, NEIGHBOR_DOOR,
                        can_stand, stations)
from world_map import INTERACTION_POINTS, nearest_travel_stop

DIRECTIONS = ('down', 'left', 'right', 'up')


def can_enter(player, target):
    if target == OUTDOOR:
        return player.get('area', OUTDOOR) in AREAS
    area = player.get('area', OUTDOOR)
    if target == NEIGHBOR_STORE:
        return area == NEIGHBOR and math.dist((player['scene_x'], player['scene_y']), NEIGHBOR_DOOR) <= 92
    if target == NEIGHBOR and area == NEIGHBOR_STORE:
        return True
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
        points = stations(area)
        return any(math.dist((player.get('scene_x', SPAWN[0]), player.get('scene_y', SPAWN[1])),
                             (s.x, s.y)) <= max(100, radius) for s in points)
    return False


def area_view(player):
    return {'area': player.get('area', OUTDOOR),
            'pos': [player.get('scene_x', SPAWN[0]), player.get('scene_y', SPAWN[1])],
            'seq': player.get('scene_seq', -1),
            'revision': player.get('scene_revision', 0)}


def valid_scene_point(x, y, area='room:hall'):
    return can_stand(area, x, y)
