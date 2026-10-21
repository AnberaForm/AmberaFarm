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
    Fish('medaka', 'メダカ', '普通', 1, 10, 26, (215, 181, 116)),
    Fish('funa', 'フナ', '普通', 1, 17, 24, (162, 172, 137)),
    Fish('ayu', 'アユ', '普通', 2, 30, 19, (140, 178, 174)),
    Fish('koi', 'コイ', '珍しい', 3, 55, 12, (223, 157, 92)),
    Fish('unagi', 'ウナギ', '珍しい', 3, 65, 9, (131, 112, 90)),
    Fish('masu', 'マス', '希少', 4, 95, 6, (181, 153, 168)),
    Fish('king_salmon', 'キングサーモン', '希少', 5, 160, 3, (227, 129, 96)),
    Fish('gold_koi', '黄金のコイ', '伝説', 5, 280, 1, (249, 199, 65)),
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
    remaining: float = 28.
    elapsed: float = 0.
    result: str = ''  # 'caught' or 'escaped'
    seed: int | None = None
    bobber_velocity: float = 0.
    struggling: bool = False

    def __post_init__(self):
        if self.fish_id not in FISH_BY_ID:
            raise ValueError('不明な魚です')
        self.seed = random.randrange(2**31) if self.seed is None else int(self.seed)
        self._rng = random.Random(self.seed)
        self._turn_in = self._rng.uniform(.6, 1.25)
        self._surge_in = self._rng.uniform(1.7, 2.7)
        self._surge_left = 0.
        self._accumulator = 0.

    @property
    def tolerance(self):
        return .142 - (FISH_BY_ID[self.fish_id].difficulty-1)*.018

    def view(self):
        fields = ('fish_id', 'fish_y', 'fish_direction', 'bobber_y', 'progress',
                  'tension', 'remaining', 'elapsed', 'result', 'struggling')
        return {k: getattr(self, k) for k in fields}

    @classmethod
    def from_view(cls, view):
        round_ = cls(view['fish_id'], seed=0)
        for key in round_.view():
            if key in view:
                setattr(round_, key, view[key])
        return round_

    def step(self, dt, direction=0, reeling=False):
        """Advance by seconds, no real-time clock dependency. Direction -1/up or +1/down."""
        if self.result:
            return self.result
        try:
            dt = float(dt)
        except (TypeError, ValueError, OverflowError):
            return self.result
        if not math.isfinite(dt) or dt <= 0:
            return self.result
        # Fixed physics steps make difficulty independent of monitor FPS.
        self._accumulator += min(dt, .12)
        while self._accumulator >= 1/120 and not self.result:
            self._accumulator -= 1/120
            self._step(1/120, direction, reeling)
        return self.result

    def _step(self, dt, direction, reeling):
        fish = FISH_BY_ID[self.fish_id]
        difficulty = fish.difficulty
        self.remaining = max(0., self.remaining - dt)
        self.elapsed += dt
        self._turn_in -= dt
        if self._turn_in <= 0:
            self.fish_direction = self._rng.choice((-1, 1))
            self._turn_in += self._rng.uniform(.45, 1.3) / (1 + .08*difficulty)
        self._surge_in -= dt
        if self._surge_in <= 0:
            self._surge_left = self._rng.uniform(.32, .50) + .045*difficulty
            self._surge_in += self._rng.uniform(2., 3.3)
        self._surge_left = max(0., self._surge_left-dt)
        self.struggling = self._surge_left > 0
        speed = .225 + difficulty * .056
        dart = (1.7 if self.struggling else 1.) + .22*abs(math.sin(self.elapsed*(1.9+difficulty*.31)))
        self.fish_y += speed * dart * dt * self.fish_direction
        if self.fish_y >= .96:
            self.fish_y = .96
            self.fish_direction = -1
        elif self.fish_y <= .04:
            self.fish_y = .04
            self.fish_direction = 1
        desired = (1 if direction > 0 else -1 if direction < 0 else 0) * .94
        self.bobber_velocity += (desired-self.bobber_velocity)*(1-math.exp(-12*dt))
        self.bobber_y = max(.025, min(.975, self.bobber_y+self.bobber_velocity*dt))
        locked = abs(self.fish_y - self.bobber_y) <= self.tolerance
        if reeling:
            if locked:
                self.progress = min(100., self.progress + dt*(22-1.9*difficulty)*(0.28 if self.struggling else 1))
                self.tension = min(100., self.tension+dt*((40+5*difficulty) if self.struggling else 2+difficulty))
            else:
                self.progress = max(0., self.progress-dt*(6+1.7*difficulty))
                self.tension = min(100., self.tension+dt*(39+difficulty*7))
        else:
            self.tension = max(0., self.tension-dt*24)
            self.progress = max(0., self.progress-dt*(1.2 if locked else 4.5))
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
