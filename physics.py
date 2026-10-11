"""Projectile physics, collision detection, and resolution."""
import math
from typing import List, Tuple

# --- Constants (per-frame at 60 Hz fixed timestep) ---
GRAVITY = 0.72
FRICTION = 0.99
MAX_DRAG = 468.0
MAX_SPEED = 46.8
CAT_RADIUS = 27.0
BOUNCE_DAMP = 0.42
GROUND_DAMP = 0.34
GROUND_H_MULT = 0.9
STRONG_HIT_THRESHOLD = 32.4
GROUND_Y = 900.0
FIELD_LEFT = 0.0
FIELD_RIGHT = 1920.0
STOP_SPEED = 0.54
STOP_TIME = 60  # frames after first collision before disappearing


def clamp_drag(px, py, sx, sy):
    """Clamp drag point to MAX_DRAG from slingshot. Returns (cx, cy)."""
    dx = px - sx
    dy = py - sy
    dist = math.sqrt(dx * dx + dy * dy)
    if dist < 1:
        return sx, sy
    if dist > MAX_DRAG:
        scale = MAX_DRAG / dist
        return sx + dx * scale, sy + dy * scale
    return px, py


def compute_launch(dx, dy):
    """Compute launch velocity from drag offset (slingshot - drag_point)."""
    dist = math.sqrt(dx * dx + dy * dy)
    if dist < 5:
        return 0.0, 0.0
    speed = min(MAX_SPEED, (dist / MAX_DRAG) * MAX_SPEED)
    nx = dx / dist
    ny = dy / dist
    return nx * speed, ny * speed


def trajectory_preview(sx, sy, vx, vy, steps=60):
    """Simulate trajectory for preview. Returns list of (x,y) points."""
    pts = []
    x, y = sx, sy
    for _ in range(steps):
        x += vx
        y += vy
        vy += GRAVITY
        vx *= FRICTION
        if y > GROUND_Y:
            y = GROUND_Y
            vy = -vy * GROUND_DAMP
            vx *= GROUND_H_MULT
        if x < FIELD_LEFT or x > FIELD_RIGHT:
            break
        pts.append((x, y))
    return pts


def circle_rect_collision(cx, cy, r, rx, ry, rw, rh):
    """Circle vs AABB. Returns (hit, normal_x, normal_y, penetration)."""
    # Find closest point on rect to circle center
    closest_x = max(rx, min(cx, rx + rw))
    closest_y = max(ry, min(cy, ry + rh))
    dx = cx - closest_x
    dy = cy - closest_y
    dist_sq = dx * dx + dy * dy
    if dist_sq < r * r:
        dist = math.sqrt(dist_sq) if dist_sq > 0 else 0.001
        # Normal points from rect to circle
        nx = dx / dist if dist > 0.001 else 0.0
        ny = dy / dist if dist > 0.001 else -1.0
        pen = r - dist
        return True, nx, ny, pen
    return False, 0, 0, 0


def circle_circle_collision(cx, cy, r1, mx, my, r2):
    """Circle vs circle. Returns (hit, nx, ny, pen)."""
    dx = cx - mx
    dy = cy - my
    dist_sq = dx * dx + dy * dy
    min_dist = r1 + r2
    if dist_sq < min_dist * min_dist:
        dist = math.sqrt(dist_sq) if dist_sq > 0.001 else 0.001
        nx = dx / dist
        ny = dy / dist
        pen = min_dist - dist
        return True, nx, ny, pen
    return False, 0, 0, 0


def resolve_bounce(vx, vy, nx, ny, damp):
    """Reflect velocity across normal and apply damping."""
    dot = vx * nx + vy * ny
    # Only reflect if moving toward surface; if already moving away, keep direction.
    if dot < 0:
        vx = vx - 2 * dot * nx
        vy = vy - 2 * dot * ny
    return vx * damp, vy * damp


def ground_bounce(vx, vy):
    """Bounce off ground."""
    return vx * GROUND_H_MULT, -vy * GROUND_DAMP


def impact_strength(vx, vy):
    """Magnitude of velocity = impact strength."""
    return math.sqrt(vx * vx + vy * vy)