# -*- coding: utf-8 -*-
"""Frame-independent pixel avatar movement with collision sliding and rescue."""
import math
from world_map import can_stand

HOME_SPAWN = (336.0, 368.0)


def safe_destination(start=HOME_SPAWN):
    if can_stand(*start):
        return list(start)
    # This is a defensive fallback for future map edits.
    for r in range(1, 50):
        for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
            point = ((10 + dx + .5) * 32, (11 + dy + .5) * 32)
            if can_stand(*point):
                return list(point)
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
