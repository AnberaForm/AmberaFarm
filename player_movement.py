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


def path_is_clear(start, destination, max_step=3.0):
    """Check the full avatar capsule along a straight line, not just its end."""
    x0, y0 = map(float, start)
    x1, y1 = map(float, destination)
    if not all(map(math.isfinite, (x0, y0, x1, y1))):
        return False
    if not can_stand(x0, y0) or not can_stand(x1, y1):
        return False
    steps = max(1, math.ceil(math.hypot(x1-x0, y1-y0) / max_step))
    return all(can_stand(x0+(x1-x0)*i/steps, y0+(y1-y0)*i/steps)
               for i in range(1, steps+1))


def walkable_short_path(start, destination, max_step=3.0, max_length=None):
    """Honor the same obstacle-sliding corners used by move_character.

    Between two 12Hz packets the player may have followed a legitimate
    X-then-Y or Y-then-X path around a corner even though their direct
    displacement line clips the obstacle. Never accept a wall crossing.
    """
    if max_length is not None and math.dist(start, destination) > max_length:
        return False
    if path_is_clear(start, destination, max_step):
        return True
    x0, y0 = start
    x1, y1 = destination
    if max_length is not None and abs(x1-x0) + abs(y1-y0) > max_length:
        return False
    return (
        (path_is_clear(start, (x1, y0), max_step) and
         path_is_clear((x1, y0), destination, max_step))
        or
        (path_is_clear(start, (x0, y1), max_step) and
         path_is_clear((x0, y1), destination, max_step))
    )


def reconcile_prediction(current, sent, authoritative):
    """Correct a local prediction against the acknowledged (not latest) frame.

    Snap safely to the host if the desired correction is blocked. Never try to
    push a player a few pixels into a wall forever.
    """
    dx, dy = float(authoritative[0])-sent[0], float(authoritative[1])-sent[1]
    magnitude = math.hypot(dx, dy)
    if magnitude <= 1.5:
        return list(current)
    target = (current[0]+dx, current[1]+dy)
    if can_stand(*target) and walkable_short_path(current, target):
        blend = 1.0 if magnitude > 22 else .55
        candidate = (current[0]+dx*blend, current[1]+dy*blend)
        if can_stand(*candidate) and walkable_short_path(current, candidate):
            return list(candidate)
    return list(authoritative)


class MovementTrail:
    """Keep the *actual* client path until the host acknowledges its samples.

    A network writer is allowed to discard old packets, but not intermediate
    steps: each new packet carries every unacknowledged sample. This is what
    makes collision sliding through several turns robust under jitter.
    """

    def __init__(self, max_samples=144):
        self.max_samples = max_samples
        self.next_id = 0
        self.steps = []

    def append(self, position):
        x, y = float(position[0]), float(position[1])
        if not math.isfinite(x) or not math.isfinite(y):
            return
        if self.steps and math.dist((x, y), self.steps[-1][1:]) < 0.025:
            return
        self.next_id += 1
        self.steps.append((self.next_id, round(x, 2), round(y, 2)))
        if len(self.steps) > self.max_samples:
            self.steps = self.steps[-self.max_samples:]

    def acknowledge(self, last_step):
        if type(last_step) is int:
            self.steps = [step for step in self.steps if step[0] > last_step]

    def packet_path(self):
        return [list(step) for step in self.steps]

    def clear(self):
        # Do not rewind IDs: server rejects old/replayed movement steps.
        self.steps.clear()


def interpolate_around_obstacles(current, target, factor, snap_distance=160.0):
    """Never linearly render a remote player *through* a solid building.

    Use a walkable right-angle detour where possible. More complex paths may
    snap to the server location rather than visibly walking through walls.
    """
    start = (float(current[0]), float(current[1]))
    end = (float(target[0]), float(target[1]))
    if not all(map(math.isfinite, (*start, *end))) or not can_stand(*end):
        return list(current)
    if math.dist(start, end) >= snap_distance or not can_stand(*start):
        return list(end)
    factor = min(1.0, max(0.0, float(factor)))
    if path_is_clear(start, end):
        return [start[0]+(end[0]-start[0])*factor,
                start[1]+(end[1]-start[1])*factor]
    corners = ((end[0], start[1]), (start[0], end[1]))
    valid = [corner for corner in corners
             if path_is_clear(start, corner) and path_is_clear(corner, end)]
    if not valid:
        return list(end)
    via = min(valid, key=lambda c: math.dist(start, c) + math.dist(c, end))
    # A series of render frames must reach the bend before going toward target.
    remaining = math.dist(start, via) + math.dist(via, end)
    distance = remaining * factor
    first = math.dist(start, via)
    if distance <= first and first > 1.e-7:
        return [start[i] + (via[i]-start[i]) * distance / first for i in (0,1)]
    second = math.dist(via, end)
    if second <= 1.e-7:
        return list(end)
    t = min(1.0, (distance-first) / second)
    return [via[i] + (end[i]-via[i]) * t for i in (0,1)]
