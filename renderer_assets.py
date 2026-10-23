"""Phase 3 asset loading: magenta-key matting once per plate, game-size Surfaces.

Semantics copied from `.superpowers/brainstorm/compositor.py` (`matte_from_key` ->
premultiply -> `smoothscale` -> un-premultiply with the alpha clamp). The DEAD
`load_clean` there is NOT reproduced: every sprite goes through the matte step.
Plates and strips are read with Pillow so no source PNG dimension is ever
hardcoded -- widths/heights come from the decoded array.
"""
import math
import os
import sys

import numpy as np
import pygame
from PIL import Image

# matte constants (compositor.py)
KEY_FEATHER_LO = 36.0     # L1 at/below this -> fully transparent (pure key)
KEY_FEATHER_HI = 150.0    # L1 at/above this -> fully opaque; between -> ramp
DESPILL_MARGIN = 90.0     # how far past KEY_FEATHER_HI despill weight stays > 0
EXT_RADIUS = 3            # radius of opaque-colour extension into the feather band

# Phase 2 published tint (multiply + additive grey lift), keyed by theme index
TINT = {0: (1.0, 30), 1: (0.8221, 60), 2: (0.25, 30), 3: (0.644, 60)}

BG_PLATES = ("bg_daytime", "bg_sunset", "bg_night", "bg_twilight")
# v3 plates (regenerated 2026-10-23 with the lawn pinned to the game floor): the
# rule is no longer "land the plate's ground line on ground_y = H - 180". It is now
# "the plate's unbroken lawn band must COVER ground_y with margin, and the plate
# keeps its native aspect", because the old hillside plates aligned perfectly yet
# read as floating. Measured horizons (biggest horizontal luminance break, canvas
# row -> screen row at the runtime plate-to-screen scale and offset 0): daytime 737
# -> 742, sunset 659 -> 664, night 765 -> 771, twilight 733 -> 738. All sit 129..236
# px ABOVE the floor, so offset 0 leaves every theme standing on plain lawn and needs
# no gap band at all (`_paint_bg_gap` returns early when its offset is 0). Re-measure
# this table if the plates are ever re-rolled again -- a horizon that lands BELOW 900
# would put structures on hills instead of grass.
BG_OFFSET = {0: 0, 1: 0, 2: 0, 3: 0}

SPRITE_TARGETS = {
    "cat_idle": (54, 54),
    "cat_tail": (53, 46),      # same scale as cat_idle (canvas 1008x864 -> 53x46)
    "mouse_large": (80, 66),
    "sling_fork": (200, 130),
    "supercat": (300, 260),
    "debris_wood": (18, 18),
    "debris_stone": (18, 18),
}

# Art nothing blits today, kept OUT of SPRITE_TARGETS so startup never pays its
# matte: handed out blank at the exact game size and matted on demand by
# `LazySprite.materialize()` (particles stayed procedural -- Phase 2 ruling).
LAZY_SPRITES = {"dust_puff": (48, 48)}

MOUSE_SIZES = {"mouse_small": (44, 36), "mouse_medium": (58, 48), "mouse_large": (80, 66)}
MOUSE_KEYS_BY_RADIUS = {22: "mouse_small", 29: "mouse_medium", 40: "mouse_large"}
MOUSE_KEYS_BY_SIZE = ("mouse_small", "mouse_medium", "mouse_large")
FORK_LARGE = (300, 195)       # 1.5x the 200x130 game slot, aspect preserved
TAIL_STEPS = 12               # wag table indexed by sin(frame * 0.1)
MOUSE_PLATE = "mouse_large"   # mouse_small/medium are byte-identical copies

# _MATTED INTENTIONALLY keeps every full-res matted canvas alive for the whole
# process lifetime (~18 MB of un-scaled canvases): matting a plate costs tens of
# ms, so it is never redone and there is no eviction to trade off. These Surfaces
# are NOT display-converted -- only the game-size copies load_assets hands out
# ever go through _finish, which is also why they cannot be blitted fast.
_MATTED = {}                  # name -> un-converted SRCALPHA Surface at canvas size
_STRIPS = {}                  # (material, height, theme_idx) -> RAW (pre-_finish) crop
                              # tinted full-width crop; each Renderer converts its own
                              # display copy (Renderer.strip_display) once, so the
                              # first Renderer to run cannot fix the pixel format.


def _asset_path(name):
    base = os.path.join(os.path.dirname(__file__), "assets", "generated", name)
    if getattr(sys, "frozen", False):
        base = os.path.join(sys._MEIPASS, "assets", "generated", name)
    return base


def _path(name):
    """Loader-internal names are bare asset keys; `_asset_path` takes a file."""
    return _asset_path(name if name.endswith(".png") else name + ".png")


def detect_key(arr):
    """Modal colour of the plate's 2 px border ring -- its actual key backdrop."""
    parts = [arr[0:2, :, :].reshape(-1, 3), arr[-2:, :, :].reshape(-1, 3),
             arr[:, 0:2, :].reshape(-1, 3), arr[:, -2:, :].reshape(-1, 3)]
    ring = np.concatenate(parts).astype(np.uint8)
    vals, counts = np.unique(ring, axis=0, return_counts=True)
    return vals[np.argmax(counts)].astype(np.float32)


def box_mean(arr, r):
    """Mean over (2r+1)^2 windows, edge-replicated, same shape as input."""
    h, w = arr.shape
    p = np.pad(arr.astype(np.float64), ((r, r), (r, r)), mode="edge")
    c = np.pad(np.cumsum(np.cumsum(p, axis=0), axis=1), ((1, 0), (1, 0)))
    y0 = np.arange(h)
    y1 = y0 + 2 * r + 1
    x0 = np.arange(w)
    x1 = x0 + 2 * r + 1
    s = c[y1][:, x1] - c[y0][:, x1] - c[y1][:, x0] + c[y0][:, x0]
    return s / float((2 * r + 1) ** 2)


def rgba_to_surface(rgb, alpha):
    """(H,W,3) uint8 + (H,W) uint8 -> un-converted SRCALPHA pygame Surface."""
    surf = pygame.Surface((rgb.shape[1], rgb.shape[0]), pygame.SRCALPHA)
    p3 = pygame.surfarray.pixels3d(surf)
    pa = pygame.surfarray.pixels_alpha(surf)
    p3[:] = np.ascontiguousarray(rgb.transpose(1, 0, 2))
    pa[:] = np.ascontiguousarray(alpha.T)
    del p3, pa
    return surf


def matte_from_key(name):
    """RGB magenta-keyed plate -> (rgb uint8 (H,W,3), alpha uint8 (H,W))."""
    arr = np.asarray(Image.open(_path(name)).convert("RGB"), dtype=np.float32)
    key = detect_key(arr)
    d = np.abs(arr - key[None, None, :]).sum(axis=2)

    t = np.clip((d - KEY_FEATHER_LO) / (KEY_FEATHER_HI - KEY_FEATHER_LO), 0.0, 1.0)
    alpha = (t * 255.0).astype(np.uint8)

    rgb = arr.copy()
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    excess = np.maximum(0.0, np.minimum(R, B) - G)
    wgt = np.clip((KEY_FEATHER_HI + DESPILL_MARGIN - d) / DESPILL_MARGIN, 0.0, 1.0)
    rgb[..., 0] = np.clip(R - excess * wgt, 0.0, 255.0)
    rgb[..., 2] = np.clip(B - excess * wgt, 0.0, 255.0)

    op = (alpha == 255).astype(np.float32)
    den = box_mean(op, EXT_RADIUS)
    blend = np.where((alpha > 0) & (alpha < 255), (255 - alpha) / 255.0 * 0.9, 0.0)
    for i in range(3):
        nb = box_mean(rgb[..., i] * op, EXT_RADIUS) / np.maximum(den, 1e-6)
        rgb[..., i] = rgb[..., i] * (1.0 - blend) + nb * blend
    rgb = np.clip(rgb, 0.0, 255.0).astype(np.uint8)
    return rgb, alpha


def matted_surface(name):
    """Full-canvas matted Surface, built at most once per asset (module cache)."""
    surf = _MATTED.get(name)
    if surf is None:
        rgb, alpha = matte_from_key(name)
        surf = rgba_to_surface(rgb, alpha)
        _MATTED[name] = surf
    return surf


def clean_scale(img, size):
    """premultiply -> smoothscale -> un-premultiply, alpha clamped to 255 where
    the SOURCE pixel was fully opaque (smoothscale tops out at 253 otherwise)."""
    img = img.copy()
    src_a = pygame.surfarray.pixels_alpha(img).copy()
    rgb = pygame.surfarray.pixels3d(img).copy()
    a = src_a.astype(np.float32) / 255.0
    rgb = (rgb.astype(np.float32) * a[:, :, None]).astype(np.uint8)
    pygame.surfarray.pixels3d(img)[:] = rgb

    scaled = pygame.transform.smoothscale(img, size)
    sa = pygame.surfarray.pixels_alpha(scaled).copy()
    sr = pygame.surfarray.pixels3d(scaled).copy()
    sw, sh = src_a.shape
    tw, th = size
    sx = np.minimum(((np.arange(tw) + 0.5) * sw / max(tw, 1)).astype(np.int64), sw - 1)
    sy = np.minimum(((np.arange(th) + 0.5) * sh / max(th, 1)).astype(np.int64), sh - 1)
    src_here = src_a[np.ix_(sx, sy)]
    solid = (src_here == 255) & (sa < 255)
    sa = np.where(solid, np.uint8(255), sa)
    pygame.surfarray.pixels_alpha(scaled)[:] = sa
    a = np.maximum(sa.astype(np.float32) / 255.0, 1e-3)
    sr = (sr.astype(np.float32) / a[:, :, None]).astype(np.uint8)
    pygame.surfarray.pixels3d(scaled)[:] = sr
    return scaled


class LazySprite(pygame.Surface):
    """Game-size Surface whose art is built the first time `.materialize()` runs.

    Keys in `LAZY_SPRITES` go through this instead of SPRITE_TARGETS, so a plate
    nothing blits never pays its ~50 ms matte at startup. It IS a pygame.Surface
    (subclass) and is blank/fully transparent until materialized -- anything that
    ever wants to draw it must call `assets[key].materialize()` first, which
    fills this same surface in place and returns it for the caller to `_finish`.
    No tinted `key@idx` variants are made for lazy keys while nothing reads them.
    """
    def __init__(self, size, source):
        super().__init__(size, pygame.SRCALPHA)
        self.source = source
        self.built = False

    def materialize(self):
        """Pay the matte once and paint it into THIS surface (identity kept)."""
        if not self.built:
            art = clean_scale(matted_surface(self.source), self.get_size())
            self.blit(art, (0, 0))   # dest starts fully transparent -> source passes through
            self.built = True
        return self


def tint_surface(src, mult, lift):
    """Multiply + additive grey lift on the RGB channels; alpha untouched."""
    out = src.copy()
    px = pygame.surfarray.pixels3d(out)
    arr = px.astype(np.float32) * float(mult) + float(lift)
    px[:] = np.clip(arr, 0.0, 255.0).astype(np.uint8)
    del px
    return out


def opaque_anchor(surf):
    """(x, y) of the lowest fully-opaque row's centroid -- the trunk base."""
    alpha = pygame.surfarray.pixels_alpha(surf)
    solid = alpha == 255
    ys, xs = np.nonzero(solid.T)            # (row, col) in numpy order
    if not len(ys):
        return surf.get_width() // 2, surf.get_height() - 1
    ymax = ys.max()
    band = xs[ys >= max(0, ymax - 2)]
    return int(round(float(band.mean()))), int(ymax)


def prong_tips(surf):
    """Left/right tip points: topmost fully-opaque pixel of each half."""
    alpha = pygame.surfarray.pixels_alpha(surf)
    w, h = surf.get_size()
    tips = []
    for off, hi in ((0, w // 2), (w // 2, w)):
        solid = (alpha[off:hi] == 255).T          # (H, W-of-off)
        ys, xs = np.nonzero(solid)
        if not len(ys):
            tips.append(None)
            continue
        ymin = ys.min()
        band = xs[ys <= ymin + 2]
        tips.append((int(off + float(band.mean())), int(ymin)))
    while len(tips) < 2:
        tips.append(None)
    return tips[0], tips[1]


def tail_pivot(surf):
    """Fattest point of the art -- where an attached tail must stay pinned."""
    alpha = pygame.surfarray.pixels_alpha(surf)
    grid = box_mean(alpha.T.astype(np.float64), 6)      # (H,W)
    row, col = np.unravel_index(int(np.argmax(grid)), grid.shape)
    return int(col), int(row)


def _finish(surf):
    """Display-ready copy when a display exists; the raw Surface when headless."""
    if pygame.display.get_surface() is not None:
        return surf.convert_alpha()
    return surf


# Size knobs (user request 2026-10-23, second pass after playtesting the 2x build):
# everything is back at its AUTHORED game slot except cats and mice, which stay at
# 1.5x. `supercat` counts as a cat so it follows CAT_SCALE; the sling fork, blocks,
# debris and the lazy particle plate are back at 1x. Physics footprints in entities.py
# / physics.py / level_generator.py are untouched either way, so a 1.5x cat/mouse
# picture still sits inside a smaller hitbox than the art shows.
SPRITE_SCALE = 1        # default factor: sling fork, blocks, debris, particles
CAT_SCALE = 1.5         # cat_idle + cat_tail + supercat milestone cat
MOUSE_SCALE = 1.5       # all three mouse sizes (one plate, scaled per slot)

# Where draw_cat pins the tail's base, as fractions of the rendered body half-size
# (r * CAT_SCALE), x right / y down. The vertical fraction is deliberately ABOVE
# the lower-right corner: with 0.71/0.71 the playtest showed the tail sitting under
# the belly, so it is raised to mid-rump height where the stroke reads attached.
TAIL_ANCHOR = (0.71, 0.46)

# Per-asset factors; any name absent from here renders at SPRITE_SCALE.
SCALE_OVERRIDES = {
    "cat_idle": CAT_SCALE, "cat_tail": CAT_SCALE, "supercat": CAT_SCALE,
    "mouse_small": MOUSE_SCALE, "mouse_medium": MOUSE_SCALE, "mouse_large": MOUSE_SCALE,
}


def _scaled(size, name=None):
    """Authored slot -> rendered slot, honouring the scale table in ONE place."""
    f = SCALE_OVERRIDES.get(name, SPRITE_SCALE)
    return (max(1, int(round(size[0] * f))), max(1, int(round(size[1] * f))))


def load_assets(width, height):
    """Every asset a Renderer needs, as Surfaces at their exact game sizes.

    Base keys are untinted; `name@<theme_index>` carries Phase 2's multiply+lift.
    Sizes go through `_scaled(name)`, so the scale tables above are the only size knobs.
    """
    assets = {}
    raw = {}
    for name, size in SPRITE_TARGETS.items():
        raw[name] = clean_scale(matted_surface(name), _scaled(size, name))
        assets[name] = _finish(raw[name])
    # kept as a key so callers can find it, but blank until something materializes
    for name, size in LAZY_SPRITES.items():
        assets[name] = LazySprite(_scaled(size, name), name)
    # one mouse plate serves three sizes
    for key, size in MOUSE_SIZES.items():
        if key == MOUSE_PLATE:
            continue
        raw[key] = clean_scale(matted_surface(MOUSE_PLATE), _scaled(size, key))
        assets[key] = _finish(raw[key])

    # fork at 1.5x the game-size slot (300x195), straight from the plate so no
    # 1024 px source is ever smoothscaled per frame; geometry measured once.
    # FORK_LARGE already carries Phase 3's 1.5x decision, so it takes the plain
    # SPRITE_SCALE factor (back to 1x after the playtest-driven 2x pass).
    fork_big = clean_scale(matted_surface("sling_fork"), _scaled(FORK_LARGE))
    assets["sling_fork_big"] = _finish(fork_big)
    assets["sling_fork_pin"] = opaque_anchor(fork_big)
    assets["sling_fork_tips"] = prong_tips(fork_big)

    for idx in range(4):
        mult, lift = TINT[idx]
        for name in list(SPRITE_TARGETS) + ["mouse_small", "mouse_medium"]:
            assets[f"{name}@{idx}"] = _finish(tint_surface(raw[name], mult, lift))
        assets[f"sling_fork_big@{idx}"] = _finish(
            tint_surface(fork_big, mult, lift))
        assets[f"cat_tail_rot@{idx}"] = _tail_table(tint_surface(raw["cat_tail"], mult, lift))

    for i, name in enumerate(BG_PLATES):
        plate = _plate_surface(name)
        assets[name] = _finish(pygame.transform.smoothscale(plate, (width, height)))

    cat_idle = raw["cat_idle"]
    raw["cat_idle_big"] = pygame.transform.smoothscale(cat_idle, (108, 108))
    assets["cat_idle_big"] = _finish(raw["cat_idle_big"])
    return assets


def tail_pivot(surf):
    """Attach point of an already-oriented plate -- one END of the tail stroke,
    nudged inward along it, so `_tail_table` can pin it to the cat while it wags."""
    ends = stroke_ends(surf)
    if ends is None:
        return 0, 0
    e1, e2 = ends
    # the base is the end from which the stroke runs up and to the right
    def score(a, b):
        return (1 if b[0] - a[0] > 0 else 0) + (1 if b[1] - a[1] < 0 else 0)
    base, other = (e1, e2) if score(e1, e2) >= score(e2, e1) else (e2, e1)
    vx, vy = other[0] - base[0], other[1] - base[1]
    span = max(1.0, math.hypot(vx, vy))
    inset = min(8.0, span * 0.2)
    px = int(round(base[0] + vx / span * inset))
    py = int(round(base[1] + vy / span * inset))
    al = pygame.surfarray.array_alpha(surf).transpose(1, 0)      # [y][x]
    h, w = al.shape
    px = min(max(px, 0), w - 1)
    py = min(max(py, 0), h - 1)
    if al[py, px] < 200:                     # nudge left the art; pin on the end itself
        return int(base[0]), int(base[1])
    return px, py


def stroke_ends(surf):
    """The two tips of the tail stroke, by two farthest-pixel sweeps over the core."""
    al = pygame.surfarray.array_alpha(surf).transpose(1, 0)      # [y][x]
    ys, xs = np.nonzero(al >= 200)
    if len(xs) == 0:
        return None
    i0 = int(np.argmin(ys * al.shape[1] + xs))                   # any core pixel
    def farthest(i, cand_y, cand_x):
        d2 = (cand_x - xs[i]) ** 2 + (cand_y - ys[i]) ** 2
        return int(np.argmax(d2))
    a = farthest(i0, ys, xs)
    b = farthest(a, ys, xs)
    return (int(xs[a]), int(ys[a])), (int(xs[b]), int(ys[b]))


def tail_orientation(surf):
    """Which symmetry of the plate lets its base sweep the right way round.

    A rear-facing tail is pinned at one END of its stroke (`stroke_ends`) and must
    run UP and to the RIGHT of that point once `draw_cat` puts it at the body's
    lower-right; otherwise it would be buried behind the cat. Rotations are tried
    before mirrors so the art keeps its own curve whenever a rotation will do.
    """
    ends = stroke_ends(surf)
    if ends is None:
        return "none"
    (x1, y1), (x2, y2) = ends
    for mode, sx, sy in (("none", 1.0, 1.0), ("rot180", -1.0, -1.0),
                         ("flip_x", -1.0, 1.0), ("flip_y", 1.0, -1.0)):
        ax, ay = x1 * sx, y1 * sy
        bx, by = x2 * sx, y2 * sy
        ok = (bx - ax > 0 and by - ay <= 0) or (ax - bx > 0 and ay - by <= 0)
        if ok:
            return mode
    return "none"


def _tail_table(surf):
    """12 pre-rotated copies of the tail, each drawn into a square canvas whose
    centre IS the tail's base, so `blit(...).center = attach point` keeps the
    tail pinned while it wags. The plate is first put through `tail_orientation`
    (a rotation where possible) so the stroke runs up and away from the cat."""
    mode = tail_orientation(surf)
    if mode == "rot180":
        surf = pygame.transform.rotate(surf, 180)
    elif mode == "flip_x":
        surf = pygame.transform.flip(surf, True, False)
    elif mode == "flip_y":
        surf = pygame.transform.flip(surf, False, True)
    pivot = tail_pivot(surf)
    w, h = surf.get_size()
    side = int(math.ceil((w * w + h * h) ** 0.5)) + 2
    table = []
    for i in range(TAIL_STEPS):
        deg = -18.0 + 36.0 * i / (TAIL_STEPS - 1)
        canvas = pygame.Surface((side, side), pygame.SRCALPHA)
        canvas.blit(surf, (side // 2 - pivot[0], side // 2 - pivot[1]))
        rot = pygame.transform.rotate(canvas, deg)
        rw, rh = rot.get_size()
        pad = pygame.Surface((rw + 2, rh + 2), pygame.SRCALPHA)
        pad.blit(rot, (1, 1))
        table.append(_finish(pad))
    return table


def _plate_surface(name):
    """Backdrop plate as an opaque Surface at its own canvas size (no matting)."""
    arr = np.asarray(Image.open(_path(name)).convert("RGB"), dtype=np.uint8)
    surf = pygame.Surface((arr.shape[1], arr.shape[0]), pygame.SRCALPHA)
    p3 = pygame.surfarray.pixels3d(surf)
    p3[:] = np.ascontiguousarray(arr.transpose(1, 0, 2))
    del p3
    pa = pygame.surfarray.pixels_alpha(surf)
    pa[:] = 255
    del pa
    return surf


def strip_crop(material, height, theme_idx=0):
    """Full-width centred crop of a strip at `height`, tinted for `theme_idx`.

    The cached value is the RAW, pre-`_finish` crop: `_STRIPS` must never hold
    display-format pixels, because pygame picks the blit path from the source's
    format and the first Renderer to run would otherwise hand every later one an
    already-converted (or un-converted) surface. Each Renderer converts its own
    display copy once (`Renderer.strip_display`), which is where `_finish` runs.
    """
    key = (material, height, theme_idx)
    cached = _STRIPS.get(key)
    if cached is not None:
        return cached
    name = f"{material}_strip.png"
    arr = np.asarray(Image.open(_path(name)).convert("RGB"), dtype=np.uint8)
    sw, sh = arr.shape[1], arr.shape[0]
    y0 = max(0, min(sh - 1, sh // 2 - height // 2))
    h = min(height, sh - y0)
    crop = arr[y0:y0 + h, :, :]
    surf = rgba_to_surface(crop, np.full(crop.shape[:2], 255, dtype=np.uint8))
    if h != height:
        surf = pygame.transform.smoothscale(surf, (sw, height))
    mult, lift = TINT[theme_idx]
    out = tint_surface(surf, mult, lift)   # RAW on purpose -- see the docstring
    _STRIPS[key] = out
    return out


def strip_slice(crop, width, height, x_off=0):
    """Slice (or repeat the slice) of `crop` so the block gets exactly (width, height)."""
    cw, ch = crop.get_size()
    if width <= cw:
        x = int(x_off) % max(cw - width, 1)
        return crop.subsurface((x, 0, width, height))
    out = pygame.Surface((width, height), pygame.SRCALPHA)
    x = 0
    while x < width:
        tw = min(width - x, cw)
        out.blit(crop.subsurface((0, 0, tw, height)), (x, 0))
        x += tw
    return out


def strip_tile(material, width, height, theme_idx=0, x_off=0):
    """Slice (or repeat the slice) so the block gets exactly (width, height).

    ALIASING, documented rather than copied (the doc and the code match): for a
    block no wider than the source strip the returned Surface is a `subsurface`
    VIEW of the shared full-width crop -- it shares that crop's pixels, allocates
    nothing per block per frame, and must never be written into (no set_at, no
    surfarray assignment, no set_alpha on the tile itself). Renderer.draw_block
    only blits, so aliasing is safe there. Only the wide branch (a block wider
    than the strip) returns a fresh Surface, which callers may mutate freely.
    The view is raw unless the caller passed a converted strip; Renderer.draw_block
    slices its own `_finish`ed copy in `Renderer.strip_display`.
    """
    return strip_slice(strip_crop(material, height, theme_idx), width, height, x_off)
