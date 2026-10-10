"""Data models: Cat, Mouse, Block, Particle, Debris."""
import math
from typing import List


class Cat:
    def __init__(self, x=0.0, y=0.0, vx=0.0, vy=0.0):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.radius = 27.0
        self.active = False
        self.first_hit = False
        self.life_after_hit = 0
        self.launched = False


class Mouse:
    def __init__(self, x=0.0, y=0.0, size=1, hp=1):
        self.x = x
        self.y = y
        self.size = size  # 0=small, 1=medium, 2=large
        self.hp = hp
        self.max_hp = hp
        self.alive = True
        self.falling = False
        self.support_y = 900.0  # where it rests
        self.breath_phase = 0.0
        self.tail_phase = 0.0

    @property
    def radius(self):
        return [22, 29, 40][self.size]


class Block:
    def __init__(self, x=0.0, y=0.0, w=40, h=30, material="wood", hp=2):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.material = material  # "wood" or "stone"
        self.hp = hp
        self.max_hp = hp
        self.alive = True


class Particle:
    def __init__(self, x=0.0, y=0.0, vx=0.0, vy=0.0, life=30,
                 color=(255,255,255), size=3, max_life=None):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = max_life if max_life is not None else life
        self.color = color
        self.size = size


class Debris:
    def __init__(self, x=0.0, y=0.0, vx=0.0, vy=0.0, size=5,
                 life=120, color=(150,150,150), max_life=None):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.size = size
        self.life = life
        self.max_life = max_life if max_life is not None else life
        self.color = color
        self.radius = size