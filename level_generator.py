"""Deterministic procedural level generation for 50 levels."""
import random
import math
from typing import List, Tuple
from entities import Block, Mouse


def generate_level(level_number: int) -> Tuple[List[Block], List[Mouse]]:
    """Generate blocks and mice for a given level (1-50). Deterministic."""
    rng = random.Random(level_number * 7919 + 31)  # prime seed

    tier = (level_number - 1) // 10
    sublevel = (level_number - 1) % 10
    is_challenge = (level_number % 5 == 0)

    # Base HP
    base_hp = 2 + 2 * tier + sublevel // 3
    if is_challenge:
        base_hp += 3

    # Number of structures
    num_structures = 1 + min(3, tier + sublevel // 4)
    if is_challenge:
        num_structures += 1

    # Primary material
    primary_material = "wood" if tier == 0 else "stone"

    blocks: List[Block] = []
    mice: List[Mouse] = []

    # Distribute structures across x > 500
    playfield_left = 713
    playfield_right = 1700   # was 1350: flush to the screen edge made the far column un-hittable
    structure_width = 165  # approximate width of one structure
    spacing = (playfield_right - playfield_left - structure_width) / max(1, num_structures - 1)

    for si in range(num_structures):
        sx = playfield_left + si * spacing if num_structures > 1 else 960
        # Clamp
        sx = int(sx)
        sx = max(713, min(sx, playfield_right - structure_width))

        # Column height (number of stacked blocks)
        col_blocks = 2 + tier  # 2-6 blocks tall
        if is_challenge:
            col_blocks = min(col_blocks + 1, 7)

        col_w = rng.randint(48, 67)
        col_h = 54
        beam_h = 36

        # Left column
        for row in range(col_blocks):
            by = 900 - (row + 1) * col_h
            mat = primary_material
            hp = base_hp
            # Occasional wood in upper tiers
            if tier >= 1 and row >= col_blocks - 1 and rng.random() < 0.3:
                mat = "wood"
                hp = max(2, hp - 2)
            blocks.append(Block(x=sx, y=by, w=col_w, h=col_h,
                                material=mat, hp=hp))

        # Right column
        rx = sx + structure_width - col_w
        for row in range(col_blocks):
            by = 900 - (row + 1) * col_h
            mat = primary_material
            hp = base_hp
            if tier >= 1 and row >= col_blocks - 1 and rng.random() < 0.3:
                mat = "wood"
                hp = max(2, hp - 2)
            blocks.append(Block(x=rx, y=by, w=col_w, h=col_h,
                                material=mat, hp=hp))

        # Horizontal beam on top
        beam_y = 900 - col_blocks * col_h - beam_h
        beam_x = sx + col_w
        beam_w = structure_width - 2 * col_w
        if beam_w > 10:
            blocks.append(Block(x=beam_x, y=beam_y, w=beam_w, h=beam_h,
                                material=primary_material, hp=base_hp))

        # Mice on this structure
        top_y = 900 - col_blocks * col_h - beam_h
        num_mice_on_struct = 1 + (1 if is_challenge and rng.random() < 0.5 else 0)
        num_mice_on_struct = min(num_mice_on_struct, 2)

        for mi in range(num_mice_on_struct):
            # Pick a surface to place mouse on
            surfaces = []
            # Top of columns
            surfaces.append((sx + col_w // 2, 900 - col_blocks * col_h))
            surfaces.append((rx + col_w // 2, 900 - col_blocks * col_h))
            # Beam top
            if beam_w > 10:
                surfaces.append((beam_x + beam_w // 2, top_y))

            if surfaces:
                mx, my = surfaces[rng.randrange(len(surfaces))]
                size, hp = _pick_mouse_size(rng, is_challenge)
                radius = [22, 29, 40][size]
                if not _surface_clear(mx, my - radius, radius, blocks):
                    # Retry other surfaces that can actually hold this mouse.
                    cands = [s for s in surfaces
                             if _surface_clear(s[0], s[1] - radius, radius, blocks)]
                    if not cands:
                        continue
                    mx, my = cands[rng.randrange(len(cands))]
                mice.append(Mouse(x=float(mx), y=float(my - radius),
                                  size=size, hp=hp))

    # Additional ground mice on later/challenge levels
    if is_challenge or tier >= 2:
        extra = 1 if is_challenge else (1 if rng.random() < 0.4 else 0)
        for _ in range(extra):
            size, hp = _pick_mouse_size(rng, is_challenge)
            radius = [22, 29, 40][size]
            gx = _pick_free_ground_x(rng, blocks, mice, size)
            if gx is None:
                continue
            mice.append(Mouse(x=float(gx), y=900.0 - radius,
                              size=size, hp=hp))

    # Cap mice: 5 normal, 6 challenge
    max_mice = 6 if is_challenge else 5
    if len(mice) > max_mice:
        # Prefer keeping larger mice
        mice.sort(key=lambda m: m.size, reverse=True)
        mice = mice[:max_mice]

    return blocks, mice


def _surface_clear(cx, cy, radius, blocks):
    """True if a mouse circle at (cx, cy) does not intersect any block."""
    for b in blocks:
        nx = max(b.x, min(cx, b.x + b.w))
        ny = max(b.y, min(cy, b.y + b.h))
        if (nx - cx) ** 2 + (ny - cy) ** 2 < radius * radius:
            return False
    return True


def _pick_free_ground_x(rng, blocks, mice, size):
    """Pick a ground x where a mouse of the given size does not overlap any block."""
    radius = [22, 29, 40][size]
    # Blocks that occupy the ground band would swallow the mouse.
    blocked = [(b.x - radius, b.x + b.w + radius) for b in blocks
               if b.y + b.h > 900.0 - 2 * radius]
    taken = [(m.x - radius - 2, m.x + radius + 2) for m in mice
             if m.y + radius > 900.0]
    lo, hi = 823 + radius, 1646 - radius
    for _ in range(40):
        gx = rng.randint(lo, hi)
        if all(gx < b0 or gx > b1 for b0, b1 in blocked + taken):
            return gx
    return None


def _pick_mouse_size(rng, challenge=False):
    """Pick mouse size. Returns (size, hp)."""
    r = rng.random()
    if challenge:
        # Slightly more large mice on challenge
        if r < 0.35:
            return 0, 1
        elif r < 0.65:
            return 1, 1
        else:
            return 2, 2
    else:
        if r < 0.4:
            return 0, 1
        elif r < 0.8:
            return 1, 1
        else:
            return 2, 2