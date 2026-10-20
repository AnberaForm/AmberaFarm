# -*- coding: utf-8 -*-
"""Frame-independent pixel avatar movement with collision sliding and rescue."""
import math
from world_map import can_stand

HOME_SPAWN = (336.0, 368.0)


def safe_destination(start=HOME_SPAWN):
    """Keep the player's saved neighborhood during a map redesign.

    If a former shop is now a wall, find the nearest walkable tile instead of
    teleporting every returning farmer to the beginning of the game.
    """
    if can_stand(*start):
        return list(start)
    center_x=max(1,min(54,int(float(start[0])//32)))
    center_y=max(1,min(34,int(float(start[1])//32)))
    for radius in range(0, 56):
        for dx in range(-radius,radius+1):
            for dy in (-radius,radius):
                target=((center_x+dx+.5)*32,(center_y+dy+.5)*32)
                if can_stand(*target):return list(target)
        for dy in range(-radius+1,radius):
            for dx in (-radius,radius):
                target=((center_x+dx+.5)*32,(center_y+dy+.5)*32)
                if can_stand(*target):return list(target)
    raise RuntimeError('No safe spawn tile')


def move_character(pos, direction, dt, speed=205):
    """Sweep in steps no larger than 4 px, sliding along non-passable edges.

    Returns a fresh [x,y]. Never teleports through narrow walls on slow frames.
    """
    x, y = map(float, pos)
    dx, dy = map(float, direction)
    length = math.hypot(dx, dy)
    if length == 0:
        return [x, y]
    dx /= length
    dy /= length
    remaining = min(max(0.0, float(dt)), .12) * speed
    steps = max(1, math.ceil(remaining / 3.5))
    step_x, step_y = dx * remaining / steps, dy * remaining / steps
    for _ in range(steps):
        if can_stand(x + step_x, y + step_y):
            x += step_x
            y += step_y
        else:
            if can_stand(x + step_x, y):
                x += step_x
            if can_stand(x, y + step_y):
                y += step_y
    return [x, y]
