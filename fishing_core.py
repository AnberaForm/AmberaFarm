# -*- coding: utf-8 -*-
"""Pure, independently testable lake fishing minigame logic."""
from __future__ import annotations
from dataclasses import dataclass
import math
import random

@dataclass(frozen=True)
class Fish:
    id: str
    name: str
    rarity: str
    difficulty: int  # 1=easy, 5=hard
    price: int         # new provisional fish market value
    weight: int        # spawn weight; not a probability
    color: tuple[int, int, int]

FISH = (
    Fish('medaka', 'メダカ', '普通', 1, 18, 26, (215, 181, 116)),
    Fish('funa', 'フナ', '普通', 1, 35, 24, (162, 172, 137)),
    Fish('ayu', 'アユ', '普通', 2, 60, 19, (140, 178, 174)),
    Fish('koi', 'コイ', '珍しい', 3, 110, 12, (223, 157, 92)),
    Fish('unagi', 'ウナギ', '珍しい', 3, 140, 9, (131, 112, 90)),
    Fish('masu', 'マス', '希少', 4, 190, 6, (181, 153, 168)),
    Fish('king_salmon', 'キングサーモン', '希少', 5, 380, 3, (227, 129, 96)),
    Fish('gold_koi', '黄金のコイ', '伝説', 5, 680, 1, (249, 199, 65)),
)
FISH_BY_ID = {f.id: f for f in FISH}

def roll_fish(rng=None):
    rng = rng or random
    return rng.choices(FISH, weights=[f.weight for f in FISH], k=1)[0]

@dataclass
class FishingRound:
    fish_id: str
    fish_y: float = .35
    fish_direction: int = 1
    bobber_y: float = .5
    progress: float = 0.
    tension: float = 0.
    remaining: float = 35.
    elapsed: float = 0.
    result: str = ''  # 'caught' or 'escaped'

    def step(self, dt, direction=0, reeling=False):
        """Advance by seconds, no real-time clock dependency. Direction -1/up or +1/down."""
        if self.result:
            return self.result
        fish = FISH_BY_ID[self.fish_id]
        dt = max(0, min(float(dt), .12))
        self.remaining = max(0., self.remaining - dt)
        self.elapsed += dt
        speed = .19 + fish.difficulty * .055
        # periodic dashes, but deterministic for replay/tests
        dart = 1.0 + .40 * abs(math.sin(self.elapsed * (1.3 + fish.difficulty * .37)))
        self.fish_y += speed * dart * dt * self.fish_direction
        if self.fish_y >= .96:
            self.fish_y = .96
            self.fish_direction = -1
        elif self.fish_y <= .04:
            self.fish_y = .04
            self.fish_direction = 1
        self.bobber_y = max(.025, min(.975, self.bobber_y + (1 if direction > 0 else -1 if direction < 0 else 0) * dt * 1.25))
        tolerance = .19 - (fish.difficulty - 1) * .019
        locked = abs(self.fish_y - self.bobber_y) <= tolerance
        if reeling:
            if locked:
                self.progress = min(100., self.progress + dt * (29 - 2 * fish.difficulty))
                self.tension = max(0., self.tension - dt * 29)
            else:
                self.progress = max(0., self.progress - dt * 1.6)
                self.tension = min(100., self.tension + dt * (25 + fish.difficulty * 7))
        else:
            self.tension = max(0., self.tension - dt * 24)
        if self.progress >= 100:
            self.result = 'caught'
        elif self.remaining <= 0 or self.tension >= 100:
            self.result = 'escaped'
        return self.result


def fish_status(state):
    return sum(state['fish_inventory'].values())


def add_catch(state, fish_id):
    if fish_id not in FISH_BY_ID:
        return False
    state['fish_inventory'][fish_id] += 1
    state['stats']['fish_caught'] += 1
    state['fish_caught_types'][fish_id] += 1
    return True


def sell_fish(state, fish_id, count=1):
    if fish_id not in FISH_BY_ID or type(count) is not int or count < 1:
        return False
    if state['fish_inventory'][fish_id] < count:
        return False
    state['fish_inventory'][fish_id] -= count
    state['coins'] += FISH_BY_ID[fish_id].price * count
    state['stats']['fish_sold'] += count
    return True
