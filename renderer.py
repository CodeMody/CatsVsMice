"""All rendering: backgrounds, themes, entities, particles, UI."""
import math
import random
import pygame
from typing import List, Tuple

import renderer_assets
from renderer_assets import BG_PLATES, BG_OFFSET, MOUSE_KEYS_BY_RADIUS

# Theme palettes
THEMES = {
    0: {  # Daytime
        "sky_top": (135, 200, 255), "sky_bot": (200, 235, 255),
        "hill1": (80, 160, 80), "hill2": (60, 140, 60),
        "grass": (70, 180, 70), "sun": (255, 230, 50),
        "cloud": (255, 255, 255), "tree": (40, 120, 40),
        "mouse_body": (180, 180, 180), "mouse_ear": (220, 180, 180),
    },
    1: {  # Sunset
        "sky_top": (255, 120, 60), "sky_bot": (255, 200, 100),
        "hill1": (100, 80, 50), "hill2": (80, 60, 40),
        "grass": (90, 110, 50), "sun": (255, 100, 30),
        "cloud": (255, 200, 150), "tree": (60, 80, 30),
        "mouse_body": (200, 160, 140), "mouse_ear": (230, 180, 160),
    },
    2: {  # Night
        "sky_top": (15, 15, 50), "sky_bot": (30, 30, 80),
        "hill1": (30, 50, 40), "hill2": (20, 40, 30),
        "grass": (30, 60, 30), "sun": (200, 200, 220),
        "cloud": (60, 60, 90), "tree": (20, 40, 20),
        "mouse_body": (140, 140, 150), "mouse_ear": (180, 160, 170),
    },
    3: {  # Twilight
        "sky_top": (80, 40, 120), "sky_bot": (200, 100, 150),
        "hill1": (60, 40, 60), "hill2": (50, 30, 50),
        "grass": (50, 70, 40), "sun": (220, 180, 200),
        "cloud": (180, 120, 160), "tree": (40, 50, 30),
        "mouse_body": (170, 150, 160), "mouse_ear": (210, 180, 190),
    },
}


def get_theme(level):
    idx = ((level - 1) // 5) % 4
    return THEMES[idx]


def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


class Renderer:
    def __init__(self, surface: pygame.Surface):
        self.surf = surface
        self.W = surface.get_width()
        self.H = surface.get_height()
        # Phase 3: matting + scaling happen ONCE here; every draw_* only blits.
        self.assets = renderer_assets.load_assets(self.W, self.H)
        # Size knobs live in renderer_assets. Blocks/debris read SPRITE_SCALE (back
        # at 1x after playtesting the 2x build); only draw_cat reads CAT_SCALE, because
        # it sizes the body from the physics radius instead of trusting the asset.
        # draw_mouse / draw_supercat / draw_sling need no knob at all -- they blit
        # whatever size load_assets handed out, so their scale comes for free.
        self.sprite_scale = renderer_assets.SPRITE_SCALE
        self.cat_scale = renderer_assets.CAT_SCALE
        # tail anchor fractions of the body half-size, so the tail can be nudged
        # without touching draw_cat's maths again
        self.tail_anchor = renderer_assets.TAIL_ANCHOR
        self.theme_idx = 0  # set by draw_background; draw_block/draw_debris read it
        # id(theme) -> THEMES key so draw_cat/draw_mouse look a theme up in O(1)
        # instead of scanning THEMES once per entity per frame. THEMES is untouched.
        self.theme_by_id = {id(t): i for i, t in THEMES.items()}
        # Star positions are fixed, so random.Random(42) + 60 draws run ONCE here
        # rather than every frame; only themes idx >= 2 blit them.
        rng = random.Random(42)
        star_floor = max(0, int((self.H - 180) * 0.6))   # same bound as the old per-frame draw
        self.stars = [(rng.randint(0, self.W), rng.randint(0, star_floor))
                      for _ in range(60)]
        # Display-format copies of the raw shared strips (renderer_assets._STRIPS
        # stays raw), converted once per instance so pygame takes its fast blit path.
        self.strip_display = {}
        # Per-theme band that paints the screen rows a plate misses when blitted off.
        self.bg_gap = {}

    def draw_background(self, level, frame_count):
        theme = get_theme(level)
        ground_y = self.H - 180
        idx = ((level - 1) // 5) % 4
        self.theme_idx = idx
        plate = self.assets.get(BG_PLATES[idx])
        if plate is not None:
            # verification.json offset_to_900 lands the plate's grass line on ground_y
            self.surf.blit(plate, (0, BG_OFFSET[idx]))
            # A (W,H) plate blitted at an offset leaves rows outside it untouched --
            # main.py never clears the screen, so those rows keep stale/black pixels.
            # Fill them from the plate's own edge row; the scale and blit y stay put,
            # so the plate's ground line still lands on ground_y (0 px of drift).
            self._paint_bg_gap(idx, BG_OFFSET[idx], plate)
        else:
            # stand-in for a missing/corrupt plate only
            for y in range(0, ground_y, 4):
                t = y / float(ground_y)
                c = lerp_color(theme["sky_top"], theme["sky_bot"], t)
                pygame.draw.rect(self.surf, c, (0, y, self.W, 4))
            pygame.draw.rect(self.surf, theme["grass"], (0, ground_y, self.W, self.H - ground_y))

        # Stars (night/twilight only — matches get_theme's palette index)
        if idx >= 2:
            # positions come from self.stars (built once in __init__); only the
            # twinkle brightness depends on frame_count.
            for stx, sty in self.stars:
                bright = min(255, 150 + int(80 * abs(math.sin(frame_count * 0.02 + stx * 0.1))))
                star_col = (bright, bright, min(255, bright + 30))
                pygame.draw.circle(self.surf, star_col, (stx, sty), 2)

        # Sun / Moon: every plate paints its own disc (measured: daytime blob centred
        # (1722,287), sunset (1704,274), night moon (1742,97) r~27, twilight (1591,195)),
        # all within reach of the procedural disc at (W*0.785, H*0.133) -> not redrawn.
        # Hills, trees and the grass band are baked into the plate too.

        # Clouds stay procedural: no plate has a near-white cloud shape (0 px >= 245
        # lum in the sky band) and the theme cloud is 45..101 lum over that band.
        fx = self.W / 1920.0
        for ci in range(3):
            cx = (frame_count * 0.55 + ci * (self.W * 0.357)) % (self.W + int(274 * fx)) - int(137 * fx)
            cy = self.H * (0.1 + ci * 0.083)
            pygame.draw.circle(self.surf, theme["cloud"], (int(cx), int(cy)), 54)
            pygame.draw.circle(self.surf, theme["cloud"], (int(cx + 34), int(cy - 9)), 45)
            pygame.draw.circle(self.surf, theme["cloud"], (int(cx + 69), int(cy)), 50)

    def _paint_bg_gap(self, idx, off, plate):
        """Paint the screen rows a (W,H) plate misses when it is blitted at `off`.

        BG_OFFSET shifts the plate vertically, so rows above it (off > 0) or below
        it (off < 0) keep whatever was on the screen from last frame -- measured as
        a 13 px black stripe for theme 0 and 75/21/48 stale top rows for themes 1..3.
        The band is filled from the plate's OWN edge row (top row for off > 0, bottom
        row for off < 0), which keeps the plate's scale and blit y untouched, so its
        ground line still lands on ground_y. Built once per theme per Renderer, then
        it costs one blit per frame.
        """
        if off == 0:
            return
        band = self.bg_gap.get(idx)
        if band is None:
            k = abs(off)
            if off > 0:
                edge = plate.subsurface((0, 0, self.W, 1))
                pos = (0, 0)
            else:
                edge = plate.subsurface((0, self.H - 1, self.W, 1))
                pos = (0, self.H - k)
            fill = pygame.Surface((self.W, k), pygame.SRCALPHA)
            for i in range(k):
                fill.blit(edge, (0, i))
            band = (renderer_assets._finish(fill), pos)
            self.bg_gap[idx] = band
        self.surf.blit(band[0], band[1])

    def draw_sling(self, sx, sy, drag=None):
        fork = self.assets.get(f"sling_fork_big@{self.theme_idx}")
        if fork is None:
            fork = self.assets.get("sling_fork_big")
        origin = None
        if fork is not None:
            pin = self.assets["sling_fork_pin"]
            origin = (int(sx - pin[0]), int(sy + 144 - pin[1]))
            # art keeps its own shape; trunk base pinned to (sx, sy+144) = (315, 900)
            self.surf.blit(fork, origin)
        else:
            # Y-shaped slingshot (fallback when the plate is missing)
            pygame.draw.line(self.surf, (100, 60, 20), (sx, sy + 144), (sx, sy), 11)
            pygame.draw.line(self.surf, (100, 60, 20), (sx, sy), (sx - 27, sy - 54), 7)
            pygame.draw.line(self.surf, (100, 60, 20), (sx, sy), (sx + 27, sy - 54), 7)
        # Fork tips now come from the ART's own prongs (`prong_tips` measured once in
        # load_assets), so the band and its knobs line up with the drawn fork instead
        # of the old procedural (sx +/- 27, sy - 54) pair that sat elsewhere. Launch
        # geometry is untouched: game.py/main.py still launch from (sling_x, sling_y-27).
        tips = self.assets.get("sling_fork_tips")
        if origin is not None and tips is not None and tips[0] is not None and tips[1] is not None:
            anchors = ((origin[0] + tips[0][0], origin[1] + tips[0][1]),
                       (origin[0] + tips[1][0], origin[1] + tips[1][1]))
        else:
            anchors = ((sx - 27, sy - 54), (sx + 27, sy - 54))
        pygame.draw.circle(self.surf, (140, 80, 30), anchors[0], 7)
        pygame.draw.circle(self.surf, (140, 80, 30), anchors[1], 7)
        # Rubber band stretched to the pull-back handle
        if drag is not None:
            bx, by = int(drag[0]), int(drag[1])
            pygame.draw.line(self.surf, (70, 45, 25), anchors[0], (bx, by), 4)
            pygame.draw.line(self.surf, (70, 45, 25), anchors[1], (bx, by), 4)

    def draw_cat(self, cat, theme, idle=False, frame=0):
        x, y = int(cat.x), int(cat.y)
        r = int(cat.radius)
        S = self.cat_scale
        idx = self.theme_by_id.get(id(theme), self.theme_idx)
        body = self.assets.get(f"cat_idle@{idx}")
        if body is None:
            body = self.assets.get("cat_idle")
        if body is None:
            # fallback: procedural cat (unchanged from Phase 1)
            body_col = (60, 60, 60)
            pygame.draw.circle(self.surf, body_col, (x, y), r)
            pygame.draw.polygon(self.surf, body_col,
                                [(x - 14, y - r + 4), (x - 22, y - r - 14), (x - 4, y - r + 4)])
            pygame.draw.polygon(self.surf, body_col,
                                [(x + 14, y - r + 4), (x + 22, y - r - 14), (x + 4, y - r + 4)])
            pygame.draw.polygon(self.surf, (200, 150, 150),
                                [(x - 11, y - r + 5), (x - 18, y - r - 9), (x - 4, y - r + 5)])
            pygame.draw.polygon(self.surf, (200, 150, 150),
                                [(x + 11, y - r + 5), (x + 18, y - r - 9), (x + 4, y - r + 5)])
            eye_off = 7 if idle else 5
            pygame.draw.circle(self.surf, (255, 255, 255), (x - eye_off, y - 5), 7)
            pygame.draw.circle(self.surf, (255, 255, 255), (x + eye_off, y - 5), 7)
            pygame.draw.circle(self.surf, (20, 20, 20), (x - eye_off, y - 5), 4)
            pygame.draw.circle(self.surf, (20, 20, 20), (x + eye_off, y - 5), 4)
            pygame.draw.polygon(self.surf, (255, 100, 100),
                                [(x, y + 2), (x - 4, y - 2), (x + 4, y - 2)])
            for side in [-1, 1]:
                for wy in [-1, 0, 1]:
                    pygame.draw.line(self.surf, (200, 200, 200),
                                     (x + side * 9, y + wy * 2), (x + side * 25, y + wy * 2 - 2), 2)
            if idle:
                tw = math.sin(frame * 0.1) * 5
                pygame.draw.arc(self.surf, body_col,
                                (x + r - 9, y - 9, 36, 36), 3.5 + tw * 0.05, 4.5 + tw * 0.05, 4)
            return
        # Tail BEHIND the body: 12 rotations precomputed at load time, wag index
        # from sin(frame * 0.1) (same phase as the old procedural arc), anchored
        # on the body's lower-right so it stays attached while it swings.
        if idle:
            table = self.assets.get(f"cat_tail_rot@{idx}")
            if table:
                s = math.sin(frame * 0.1)
                step = int(round((s + 1.0) * (len(table) - 1) / 2.0))
                step = max(0, min(len(table) - 1, step))
                # anchor scales with the BODY, not the physics radius, so the tail
                # stays attached to the lower-right of a 2x body
                ax = x + int(r * S * self.tail_anchor[0])
                ay = y + int(r * S * self.tail_anchor[1])
                tail_rect = table[step].get_rect(center=(ax, ay))
                self.surf.blit(table[step], tail_rect.topleft)
        sprite = body
        size = (2 * r * S, 2 * r * S)
        if sprite.get_size() != size:
            sprite = pygame.transform.smoothscale(sprite, size)
        self.surf.blit(sprite, (x - size[0] // 2, y - size[1] // 2))

    def draw_mouse(self, mouse, theme, frame=0):
        if not mouse.alive:
            return
        x, y = int(mouse.x), int(mouse.y)
        r = mouse.radius
        idx = self.theme_by_id.get(id(theme), self.theme_idx)
        key = MOUSE_KEYS_BY_RADIUS.get(int(r))
        if key is None:
            key = MOUSE_KEYS_BY_SIZE[max(0, min(2, int(mouse.size)))]
        base = self.assets.get(f"{key}@{idx}")
        if base is None:
            base = self.assets.get(key)
        breath = 1.0 + 0.02 * math.sin(frame * 0.08 + mouse.breath_phase)
        if base is None:
            # fallback: procedural mouse (unchanged from Phase 1)
            body_col = theme["mouse_body"]
            ear_col = theme["mouse_ear"]
            rr = int(r * breath)
            tail_wag = math.sin(frame * 0.12 + mouse.tail_phase) * 4
            pygame.draw.arc(self.surf, ear_col,
                            (x + rr - 5, y - 5, 45, 45), 3.8 + tail_wag * 0.03, 4.8 + tail_wag * 0.03, 3)
            pygame.draw.circle(self.surf, body_col, (x, y), rr)
            pygame.draw.circle(self.surf, lerp_color(body_col, (255, 255, 255), 0.3),
                               (x, y + 4), max(1, rr - 7))
            for side in [-1, 1]:
                pygame.draw.circle(self.surf, ear_col, (x + side * (r - 4), y - r + 2), max(5, r // 3))
                pygame.draw.circle(self.surf, lerp_color(ear_col, (255, 200, 200), 0.5),
                                   (x + side * (r - 4), y - r + 2), max(4, r // 4))
            eye_sp = max(4, r // 4)
            pygame.draw.circle(self.surf, (20, 20, 20), (x - eye_sp, y - 4), max(3, r // 5))
            pygame.draw.circle(self.surf, (20, 20, 20), (x + eye_sp, y - 4), max(3, r // 5))
            pygame.draw.circle(self.surf, (255, 100, 100), (x, y + 4), max(2, r // 6))
            for side in [-1, 1]:
                for wy in [-2, 0, 2]:
                    pygame.draw.line(self.surf, (180, 180, 180),
                                     (x + side * 5, y + wy * 2), (x + side * (r + 5), y + wy * 2 - 2), 2)
            return
        # The art already carries a static tail (Phase 2 ruling), so only the
        # breathing pulse is applied -- to the ALREADY-scaled small surface.
        w, h = base.get_size()
        size = (max(1, int(round(w * breath))), max(1, int(round(h * breath))))
        sprite = base if size == (w, h) else pygame.transform.smoothscale(base, size)
        self.surf.blit(sprite, (x - size[0] // 2, y - size[1] // 2))

    def draw_block(self, block):
        if not block.alive:
            return
        x, y, w, h = int(block.x), int(block.y), int(block.w), int(block.h)
        mat = "wood" if block.material == "wood" else "stone"
        S = self.sprite_scale
        # centred crop of the strip's ACTUAL height, sliced to this block's width;
        # x_off shifts the slice so stacked blocks do not repeat the same grain.
        # `_STRIPS` caches RAW crops, so pay `_finish` once per (material, DISPLAYED
        # height, theme) for THIS Renderer and blit aliased subsurfaces of that display copy
        # every frame -- see strip_tile's docstring: a tile must never be written into.
        dw, dh = w * S, h * S
        key = (mat, dh, self.theme_idx)
        strip = self.strip_display.get(key)
        if strip is None:
            strip = renderer_assets._finish(
                renderer_assets.strip_crop(mat, dh, self.theme_idx))
            self.strip_display[key] = strip
        tile = renderer_assets.strip_slice(strip, dw, dh, x_off=x)
        # art grows about the block's BOTTOM centre, so a 2x block still plants on
        # the ground line instead of floating; its hitbox stays (w, h) at (x, y).
        self.surf.blit(tile, (x + (w - dw) // 2, y + h - dh))
        # Phase 2 verdict: NO masonry outline -- the baked joints already read as
        # grid lines once blocks tile (crop gradient 19.07 wood / 16.71 stone vs
        # 4.8..8.4 seam deltas), and an added edge doubled them.

    def draw_particles(self, particles: List):
        for p in particles:
            alpha = max(0, int(255 * p.life / p.max_life))
            c = p.color
            pygame.draw.circle(self.surf, c, (int(p.x), int(p.y)), max(2, int(p.size * p.life / p.max_life)))

    def draw_debris(self, debris_list: List):
        S = self.sprite_scale
        for d in debris_list:
            c = d.color
            key = None
            if c == (160, 100, 50):
                key = "debris_wood"
            elif c == (130, 130, 140):
                key = "debris_stone"
            sprite = self.assets.get(f"{key}@{self.theme_idx}") if key else None
            if sprite is None:
                sprite = self.assets.get(key) if key else None
            if sprite is None:
                # any other colour falls back to the procedural rect
                pygame.draw.rect(self.surf, c, (int(d.x - d.size // 2),
                                                int(d.y - d.size // 2), d.size, d.size))
                continue
            size = max(1, int(d.size)) * S
            if sprite.get_size() != (size, size):
                sprite = pygame.transform.smoothscale(sprite, (size, size))
            alpha = max(0, min(255, int(255 * d.life / d.max_life)))
            if alpha < 255:
                sprite = sprite.copy()
                sprite.set_alpha(alpha)
            self.surf.blit(sprite, (int(d.x - size // 2), int(d.y - size // 2)))

    def draw_trajectory(self, sx, sy, vx, vy):
        from physics import trajectory_preview
        pts = trajectory_preview(sx, sy, vx, vy, 50)
        for i, (px, py) in enumerate(pts):
            if i % 3 == 0:
                pygame.draw.circle(self.surf, (255, 255, 100, 180), (int(px), int(py)), 3)

    def draw_hud(self, score, level, cats_remaining, frame):
        # Score
        font = pygame.font.SysFont("Arial", 40, bold=True)
        txt = font.render(f"Score: {score}", True, (255, 255, 50))
        self.surf.blit(txt, (18, 18))
        # Level
        txt2 = font.render(f"Level {level}/50", True, (255, 255, 255))
        self.surf.blit(txt2, (18, 63))
        # Cat icons
        for ci in range(cats_remaining):
            cx = 1645 + ci * 46
            pygame.draw.circle(self.surf, (60, 60, 60), (cx, 36), 15)
            pygame.draw.polygon(self.surf, (60, 60, 60),
                                [(cx - 7, 22), (cx - 11, 11), (cx - 2, 22)])
            pygame.draw.polygon(self.surf, (60, 60, 60),
                                [(cx + 7, 22), (cx + 11, 11), (cx + 2, 22)])
        # Restart button
        btn_x, btn_y = 1783, 990
        pygame.draw.rect(self.surf, (80, 80, 80), (btn_x, btn_y, 110, 54))
        pygame.draw.rect(self.surf, (200, 200, 200), (btn_x, btn_y, 110, 54), 2)
        btn_txt = font.render("Restart", True, (255, 255, 255))
        self.surf.blit(btn_txt, (btn_x + 7, btn_y + 9))

    def draw_aim_instruction(self, frame):
        if frame % 120 < 90:
            font = pygame.font.SysFont("Arial", 29)
            txt = font.render("Drag cat to aim, release to launch!", True, (255, 255, 200))
            self.surf.blit(txt, (247, 810))

    def draw_completion(self, level, bonus, challenge):
        font = pygame.font.SysFont("Arial", 65, bold=True)
        if challenge:
            txt = font.render(f"CHALLENGE LEVEL {level} COMPLETE! +{bonus}", True, (255, 255, 0))
        else:
            txt = font.render(f"LEVEL {level} COMPLETE! +{bonus}", True, (100, 255, 100))
        self.surf.blit(txt, (548, 450))
        font2 = pygame.font.SysFont("Arial", 43)
        txt2 = font2.render("Click to continue", True, (255, 255, 255))
        self.surf.blit(txt2, (756, 576))

    def draw_game_over(self, score):
        font = pygame.font.SysFont("Arial", 76, bold=True)
        txt = font.render("GAME OVER", True, (255, 80, 80))
        self.surf.blit(txt, (686, 360))
        font2 = pygame.font.SysFont("Arial", 43)
        txt2 = font2.render(f"Final Score: {score}", True, (255, 255, 255))
        self.surf.blit(txt2, (715, 468))
        txt3 = font2.render("Click to restart", True, (255, 255, 255))
        self.surf.blit(txt3, (728, 594))

    def draw_victory(self, score, frame):
        font = pygame.font.SysFont("Arial", 86, bold=True)
        txt = font.render("VICTORY!", True, (255, 220, 50))
        self.surf.blit(txt, (686, 324))
        font2 = pygame.font.SysFont("Arial", 50)
        txt2 = font2.render(f"Final Score: {score}", True, (255, 255, 255))
        self.surf.blit(txt2, (715, 450))
        # Fireworks
        rng = random.Random(frame)   # module-level import; seeded per call as before
        for _ in range(8):
            fx = rng.randint(274, 1646)
            fy = rng.randint(180, 720)
            r = 54 + (frame % 108)
            color = (rng.randint(100, 255), rng.randint(100, 255), rng.randint(100, 255))
            for a in range(0, 360, 30):
                px = fx + int(r * math.cos(math.radians(a)))
                py = fy + int(r * math.sin(math.radians(a)))
                pygame.draw.circle(self.surf, color, (px, py), 5)
        # Happy cat
        self._draw_happy_cat(960, 810, frame)
        txt3 = font2.render("Click to play again", True, (255, 255, 255))
        self.surf.blit(txt3, (797, 612))

    def _draw_happy_cat(self, x, y, frame):
        r = 54
        pygame.draw.circle(self.surf, (50, 50, 50), (x, y), r)
        pygame.draw.polygon(self.surf, (50, 50, 50),
                            [(x - 27, y - r + 5), (x - 40, y - r - 27), (x - 9, y - r + 5)])
        pygame.draw.polygon(self.surf, (50, 50, 50),
                            [(x + 27, y - r + 5), (x + 40, y - r - 27), (x + 9, y - r + 5)])
        pygame.draw.circle(self.surf, (255, 255, 255), (x - 14, y - 9), 11)
        pygame.draw.circle(self.surf, (255, 255, 255), (x + 14, y - 9), 11)
        pygame.draw.circle(self.surf, (20, 20, 20), (x - 14, y - 9), 6)
        pygame.draw.circle(self.surf, (20, 20, 20), (x + 14, y - 9), 6)
        # Smile
        pygame.draw.arc(self.surf, (255, 255, 255), (x - 18, y, 36, 27), 3.14, 6.28, 3)

    def draw_name_prompt(self, score, name_buf):
        font = pygame.font.SysFont("Arial", 50, bold=True)
        txt = font.render(f"NEW HIGH SCORE: {score} - type your name, Enter to confirm", True, (255, 255, 100))
        self.surf.blit(txt, (411, 450))
        f2 = pygame.font.SysFont("Arial", 40)
        self.surf.blit(f2.render(f"Name: {name_buf}_", True, (255, 255, 255)), (823, 540))

    def draw_milestone(self, frame):
        """SuperCat flying across screen."""
        x = (frame * 15) % (self.W + 274) - 137
        y = self.H * 0.5 + self.H * 0.05 * math.sin(frame * 0.1)
        xi, yi = int(x), int(y)
        art = self.assets.get(f"supercat@{self.theme_idx}")
        if art is None:
            art = self.assets.get("supercat")
        if art is not None:
            # supercat.png is already loaded at exactly (300, 260) -> plain blit.
            # Cape / collar / fluff / eyes / chest emblem polygons drop: the plate
            # bakes all of them (Phase 2 ruling).
            aw, ah = art.get_size()
            self.surf.blit(art, (xi - aw // 2, yi - ah // 2))
        else:
            # fallback when the asset is missing: procedural body only
            pygame.draw.circle(self.surf, (80, 80, 80), (xi, yi), 72)
        # Star
        for i in range(5):
            a = i * 72 - 90
            px = int(x + 108 * math.cos(math.radians(a)))
            py = int(y - 36 + 108 * math.sin(math.radians(a)))
            pygame.draw.circle(self.surf, (255, 255, 0), (px, py), 7)

    def draw_menu(self, frame):
        self.surf.fill((30, 30, 50))
        font = pygame.font.SysFont("Arial", 86, bold=True)
        txt = font.render("CATS vs MICE", True, (255, 200, 50))
        text_x = (self.W - txt.get_width()) // 2
        self.surf.blit(txt, (text_x, 180))
        # Menu buttons
        self._menu_buttons(frame)

    def _menu_buttons(self, frame):
        rows = [("Click to Play", 450), ("Scoreboard", 558), ("Volume", 666), ("Quit", 774)]
        f2 = pygame.font.SysFont("Arial", 43)
        for label, y in rows:
            pygame.draw.rect(self.surf, (60, 60, 90), (795, y - 18, 274, 72))
            pygame.draw.rect(self.surf, (200, 200, 120), (795, y - 18, 274, 72), 2)
            self.surf.blit(f2.render(label, True, (255, 255, 255)), (823, y))
        # Volume slider track + handle at the currently applied value
        try:
            v = pygame.font.SysFont("Arial", 29)
            vol = __import__("audio").audio_mgr.get_volume()
        except Exception:
            vol = 0.5
        pygame.draw.rect(self.surf, (90, 90, 120), (795, 720, 274, 14))
        pygame.draw.circle(self.surf, (255, 255, 120), (int(795 + vol * 274), 727), 11)
        self.surf.blit(v.render(f"volume {int(vol * 100)}%", True, (200, 200, 200)), (803, 747))

    def draw_scoreboard(self, scores):
        self.surf.fill((30, 30, 50))
        font = pygame.font.SysFont("Arial", 65, bold=True)
        txt = font.render("SCOREBOARD", True, (255, 255, 100))
        self.surf.blit(txt, (686, 144))
        f2 = pygame.font.SysFont("Arial", 43)
        if not scores:
            msg = f2.render("No scores yet. Play to set a record!", True, (200, 200, 200))
            self.surf.blit(msg, (548, 360))
        else:
            for i, s in enumerate(scores):
                line = f2.render(f"{i+1}. {s['name']} - {s['score']}", True, (255, 255, 255))
                self.surf.blit(line, (548, 270 + i * 72))
        self.surf.blit(f2.render("Click to return", True, (200, 200, 200)), (823, 810))