"""Headless tests for the Phase 3 asset loader (`renderer_assets`) and its use
by `renderer.Renderer`. Same plain-assert style as tests.py: each `test_*` runs
through `run_tests()` and `python tests_assets.py` exits non-zero on failure."""
import math
import os
import re
import shutil
import struct
import sys
import tempfile

import numpy as np
import pygame
from PIL import Image

import entities
import level_generator
import renderer as renderer_mod
import renderer_assets

# Scratch frames the suite saves for eyeballing. OUTSIDE the project on purpose:
# running the tests must not leave a folder of PNGs in the repo or in the EXE.
PREVIEW_DIR = os.path.join(tempfile.gettempdir(), "cats-vs-mice-preview")


def test_asset_paths_resolve():
    """`_asset_path` finds a plate on disk, and inside a simulated frozen EXE."""
    real = renderer_assets._asset_path("cat_idle.png")
    assert os.path.exists(real), f"asset not found: {real}"

    repo = os.path.dirname(renderer_assets.__file__)
    generated = os.path.join(repo, "assets", "generated")
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(generated, os.path.join(tmp, "assets", "generated"))
        old_frozen = getattr(sys, "frozen", None)
        old_meipass = getattr(sys, "_MEIPASS", None)
        sys.frozen = True
        sys._MEIPASS = tmp
        try:
            frozen = renderer_assets._asset_path("cat_idle.png")
        finally:
            if old_frozen is None:
                del sys.frozen
            else:
                sys.frozen = old_frozen
            if old_meipass is None:
                del sys._MEIPASS
            else:
                sys._MEIPASS = old_meipass
        assert os.path.exists(frozen), f"frozen path broken: {frozen}"
        assert os.path.normcase(frozen).startswith(os.path.normcase(tmp)), (
            f"_MEIPASS ignored: {frozen} outside {tmp}")


def test_loader_returns_surfaces():
    """load_assets gives every required key, at the exact game size, with alpha."""
    width, height = 1920, 1080
    assets = renderer_assets.load_assets(width, height)
    # literals below are the AUTHORED game slots; the rendered size is slot x the
    # per-asset factor in renderer_assets.SCALE_OVERRIDES (default SPRITE_SCALE).
    game_slot = {
        "cat_idle": (54, 54),
        "cat_tail": (53, 46),
        "mouse_small": (44, 36),
        "mouse_medium": (58, 48),
        "mouse_large": (80, 66),
        "sling_fork": (200, 130),
        "supercat": (300, 260),
        "debris_wood": (18, 18),
        "debris_stone": (18, 18),
    }
    # the playtest-driven ruling: cats + mice at 1.5x, everything else back at 1x
    assert renderer_assets.CAT_SCALE == 1.5, f"CAT_SCALE {renderer_assets.CAT_SCALE}"
    assert renderer_assets.MOUSE_SCALE == 1.5, f"MOUSE_SCALE {renderer_assets.MOUSE_SCALE}"
    assert renderer_assets.SPRITE_SCALE == 1, f"SPRITE_SCALE {renderer_assets.SPRITE_SCALE}"
    for key in ("cat_idle", "cat_tail", "supercat"):
        assert renderer_assets.SCALE_OVERRIDES[key] == 1.5, f"{key} not 1.5x"
    for key in ("mouse_small", "mouse_medium", "mouse_large"):
        assert renderer_assets.SCALE_OVERRIDES[key] == 1.5, f"{key} not 1.5x"
    for key in ("sling_fork", "debris_wood", "debris_stone"):
        got = renderer_assets.SCALE_OVERRIDES.get(key, renderer_assets.SPRITE_SCALE)
        assert got == 1, f"{key} should be back at 1x, is {got}x"
    expected = {k: renderer_assets._scaled(v, k) for k, v in game_slot.items()}
    expected.update({name: (width, height) for name in renderer_assets.BG_PLATES})
    for key, size in expected.items():
        assert key in assets, f"missing asset key: {key}"
        surf = assets[key]
        assert isinstance(surf, pygame.Surface), f"{key} is not a Surface"
        assert surf.get_size() == size, f"{key} is {surf.get_size()} != {size}"

    # sprites must carry per-pixel alpha and prove the alpha clamp ran: some pixel
    # is fully opaque (255) and at least one feathered edge pixel survives.
    for key in ("cat_idle", "mouse_large", "sling_fork", "supercat", "debris_wood"):
        surf = assets[key]
        assert len(surf.get_at((0, 0))) == 4, f"{key} has no per-pixel alpha"
        alpha = pygame.surfarray.pixels_alpha(surf).copy()
        assert int(alpha.max()) == 255, f"{key} max alpha < 255 -> clamp missing"
        assert int(((alpha > 0) & (alpha < 255)).sum()) > 0, f"{key} lost its feather band"

    # tinted variants exist for all four themes at the same sizes
    for theme_idx in range(4):
        for key in ("cat_idle", "mouse_large"):
            size = expected[key]
            tinted = assets[f"{key}@{theme_idx}"]
            assert tinted.get_size() == size, f"tinted {key} resized"


def test_strip_crop_widths():
    """Strips crop from their ACTUAL height; slicing gives exactly (w, h)."""
    for mat in ("wood", "stone"):
        for w in (31, 48, 55, 67, 69):
            h = 36 if w in (31, 69) else 54
            tile = renderer_assets.strip_tile(mat, w, h)
            assert isinstance(tile, pygame.Surface), f"{mat} tile not a Surface"
            assert tile.get_size() == (w, h), f"{mat} tile {tile.get_size()} != {(w, h)}"
    # wider than the source strip -> repeated slice, still exact
    wide = renderer_assets.strip_tile("wood", 2100, 54)
    assert wide.get_size() == (2100, 54), f"tiling failed: {wide.get_size()}"

    src = open(renderer_assets.__file__, encoding="utf-8").read()
    for dims in ("224", "1072", "1024x224", "1920x1072"):
        assert dims not in src, f"hardcoded source dimension {dims} in loader"


def test_headless_frame():
    """A real Renderer can draw every PLAYING-state call headless and save a frame."""
    pygame.init()  # matches main.py line 18; without it pygame.font raises "font not initialized"
    screen = pygame.display.set_mode((1920, 1080))
    rend = renderer_mod.Renderer(screen)
    blocks, mice = level_generator.generate_level(1)
    theme = renderer_mod.get_theme(1)
    frame = 37

    cat = entities.Cat(x=315.0, y=729.0)
    particles = [entities.Particle(x=600.0, y=820.0, life=20, max_life=30,
                                   color=(160, 100, 50), size=4)]
    debris = [entities.Debris(x=700.0, y=840.0, size=14, life=60, max_life=120,
                              color=(160, 100, 50)),
              entities.Debris(x=760.0, y=860.0, size=12, life=30, max_life=120,
                              color=(130, 130, 140))]

    rend.draw_background(1, frame)
    rend.draw_sling(315, 756, drag=(250.0, 800.0))
    rend.draw_trajectory(315, 756, -9.0, -7.0)
    rend.draw_particles(particles)
    rend.draw_debris(debris)
    rend.draw_cat(cat, theme, idle=True, frame=frame)
    for mouse in mice:
        rend.draw_mouse(mouse, theme, frame=frame)
    for block in blocks:
        rend.draw_block(block)
    rend.draw_hud(1234, 1, 2, frame)

    os.makedirs(PREVIEW_DIR, exist_ok=True)
    assert os.path.isdir(PREVIEW_DIR), f"no preview dir: {PREVIEW_DIR}"
    out = os.path.join(PREVIEW_DIR, "frame_playing.png")
    pygame.image.save(screen, out)
    assert os.path.exists(out), f"frame not saved: {out}"
    saved = pygame.image.load(out)
    assert saved.get_size() == (1920, 1080), f"saved frame is {saved.get_size()}"


def test_milestone_and_menu_paths():
    """Milestone + menu paths still work on the asset-backed renderer."""
    pygame.init()  # matches main.py line 18; without it pygame.font raises "font not initialized"
    screen = pygame.display.set_mode((1920, 1080))
    rend = renderer_mod.Renderer(screen)
    rend.draw_milestone(90)
    rend.draw_menu(1)
    rend.draw_scoreboard([])
    rend.draw_completion(3, 5000, False)
    rend.draw_victory(99999, 120)
    assert os.path.isabs(__file__)


def test_theme_lookup_unchanged():
    """THEMES / get_theme / lerp_color stay exactly as they were."""
    for level in (1, 6, 11, 16):
        idx = ((level - 1) // 5) % 4
        theme = renderer_mod.get_theme(level)
        assert theme is renderer_mod.THEMES[idx], f"get_theme({level}) changed"
        for key in ("sky_top", "grass", "mouse_body", "sun"):
            assert isinstance(theme[key], tuple) and len(theme[key]) == 3
    assert len(renderer_mod.THEMES) == 4
    assert renderer_mod.lerp_color((0, 0, 0), (100, 200, 300), 0.5) == (50, 100, 150)


def test_box_mean_is_a_window_mean():
    """`box_mean` must be a true mean over (2r+1)^2 windows, edge-replicated."""
    arr = np.array([[(x * 7 + y * 3) % 256 for x in range(40)] for y in range(24)],
                   dtype=np.float64)
    r = 3
    got = renderer_assets.box_mean(arr, r)
    h, w = arr.shape
    want = np.empty_like(got)
    for y in range(h):
        for x in range(w):
            total = 0.0
            for dy in range(-r, r + 1):
                yy = min(max(y + dy, 0), h - 1)
                for dx in range(-r, r + 1):
                    xx = min(max(x + dx, 0), w - 1)
                    total += arr[yy, xx]
            want[y, x] = total / float((2 * r + 1) ** 2)
    assert got.shape == arr.shape, f"box_mean changed shape: {got.shape}"
    diff = float(np.abs(got - want).max())
    assert diff < 1e-9, f"box_mean is not a window mean: max diff {diff:.3f}"
    # a mean of values <= 255 can never exceed 255
    assert float(got.max()) <= 255.0 + 1e-9, "box_mean overshoots its input range"


def test_tail_pivot_pins_the_base():
    """The attach point must sit ON the tail art, at an END of its stroke, with the
    rest of the stroke running up and to the right of it -- that is what keeps the
    tail pinned to the cat's rear once `draw_cat` puts it at the body's lower-right."""
    slot = renderer_assets.clean_scale(
        renderer_assets.matted_surface("cat_tail"),
        renderer_assets._scaled((53, 46), "cat_tail"))
    al = pygame.surfarray.array_alpha(slot).transpose(1, 0)      # [y][x]
    core = al >= 200
    assert core.any(), "tail plate has no opaque core"
    px, py = renderer_assets.tail_pivot(slot)
    assert 0 <= px < al.shape[1] and 0 <= py < al.shape[0], f"pivot {px, py} off the canvas"
    assert bool(core[py, px]), (
        f"pivot {px, py} is not on the art: alpha {int(al[py, px])}")

    ys, xs = np.nonzero(core)
    far = np.hypot(xs - px, ys - py) >= np.max(np.hypot(xs - px, ys - py)) * 0.6
    vx = float(xs[far].mean()) - px
    vy = float(ys[far].mean()) - py
    assert vx > 0, f"tail runs left of its attach point: dx {vx:.1f}"
    assert vy <= 0, f"tail hangs below its attach point: dy {vy:.1f}"
    # an end of the stroke, not its middle
    cxm, cym = float(xs.mean()), float(ys.mean())
    spread = np.hypot(xs - cxm, ys - cym)
    at_pivot = float(np.hypot(px - cxm, py - cym))
    assert at_pivot >= 0.6 * float(spread.max()), (
        f"attach point is mid-stroke: {at_pivot:.1f} from the core centroid vs "
        f"{float(spread.max()):.1f} furthest")


def test_tail_clears_the_body():
    """On screen the wagged tail must be attached to the body's lower-right, poke OUT
    to the right of it, and stay above the ground line."""
    assets = renderer_assets.load_assets(1920, 1080)
    idx = 0
    table = assets[f"cat_tail_rot@{idx}"]
    assert table, "no tail table for theme 0"
    r_phys = 27                      # entities.Cat physics radius
    scale = renderer_assets.CAT_SCALE
    cx, cy = 960, 700                # probe cat, mid-air like draw_cat's anchor maths
    ax = cx + int(r_phys * scale * renderer_assets.TAIL_ANCHOR[0])
    ay = cy + int(r_phys * scale * renderer_assets.TAIL_ANCHOR[1])
    half = int(r_phys * scale)
    body_left, body_right = cx - half, cx + half
    body_top, body_bottom = cy - half, cy + half
    ground = 1080 - 180              # renderer.GROUND_Y
    opaque = 0
    furthest_right = -10 ** 9
    closest = 10 ** 9
    below_body = 0
    for step in range(len(table)):
        surf = table[step]
        rect = surf.get_rect(center=(ax, ay))
        alpha = pygame.surfarray.array_alpha(surf).transpose(1, 0)      # [y][x]
        ys, xs = np.where(alpha >= 200)
        if not len(xs):
            continue
        sx = xs + rect.left
        sy = ys + rect.top
        opaque += len(xs)
        furthest_right = max(furthest_right, int(sx.max()))
        # distance from each tail pixel to the body's bounding box (0 when inside it)
        dx = np.maximum(np.maximum(body_left - sx, sx - body_right), 0)
        dy = np.maximum(np.maximum(body_top - sy, sy - body_bottom), 0)
        closest = min(closest, int(np.min(np.hypot(dx, dy))))
        below_body += int((sy > body_bottom + 6).sum())
    assert opaque > 0, "tail table is empty"
    assert furthest_right > body_right, (
        f"tail never pokes out past the body edge x={body_right}: furthest x "
        f"{furthest_right}")
    assert closest <= 4, f"tail floats off the body: nearest gap {closest} px"
    assert below_body < opaque * 0.35, (
        f"most of the tail hangs below the body (below_body {below_body} of {opaque})")


def test_cloud_asset_is_cropped_to_its_cloud():
    """`cloud.png` is a 512x512 plate whose key residue reaches every edge, so the
    loader must crop to the cloud itself and scale it preserving the blob's aspect."""
    assets = renderer_assets.load_assets(1920, 1080)
    surf = assets.get("cloud")
    assert surf is not None, "loader hands out no 'cloud' asset"
    want = renderer_assets._scaled(renderer_assets.CLOUD_SLOT, "cloud")
    assert surf.get_size() == want, f"cloud slot {surf.get_size()} != {want}"
    al = pygame.surfarray.array_alpha(surf).transpose(1, 0)      # [y][x]
    ys, xs = np.nonzero(al >= 200)
    assert len(xs) > 0, "cloud asset has no opaque body"
    # tightly cropped: the body must reach all four edges of the slot
    assert xs.min() == 0 and xs.max() == surf.get_width() - 1, \
        f"cloud not cropped horizontally: x {xs.min()}..{xs.max()} of {surf.get_width()}"
    assert ys.min() == 0 and ys.max() == surf.get_height() - 1, \
        f"cloud not cropped vertically: y {ys.min()}..{ys.max()} of {surf.get_height()}"
    aspect = surf.get_width() / float(surf.get_height())
    assert abs(aspect - 1.75) < 0.12, f"cloud aspect {aspect:.2f} distorts the plate's blob"


def test_cloud_tinted_variants_exist_for_every_theme():
    """Clouds get Phase 2's tint like every other sprite: same silhouette, four tints."""
    assets = renderer_assets.load_assets(1920, 1080)
    base = assets["cloud"]
    al = pygame.surfarray.array_alpha(base).transpose(1, 0)
    for idx in range(4):
        tinted = assets.get(f"cloud@{idx}")
        assert tinted is not None, f"no tinted cloud for theme {idx}"
        assert tinted.get_size() == base.get_size(), f"theme {idx} cloud resized"
        assert np.array_equal(pygame.surfarray.array_alpha(tinted).transpose(1, 0), al), \
            f"theme {idx} tint changed the cloud silhouette"
    day = pygame.surfarray.array3d(assets["cloud@0"]).transpose(1, 0, 2)
    night = pygame.surfarray.array3d(assets["cloud@2"]).transpose(1, 0, 2)
    solid = al >= 200
    assert int(day[solid].sum()) > int(night[solid].sum()), \
        "night cloud is not darker than the daytime one"


def test_cloud_positions_drift_and_wrap():
    """Cloud centres come from a shared helper: steady drift, and they wrap through
    the off-screen margins instead of popping at the screen edge."""
    W, H = 1920, 1080
    slot = renderer_assets._scaled(renderer_assets.CLOUD_SLOT, "cloud")
    half = slot[0] // 2
    p0 = renderer_assets.cloud_positions(W, H, 0)
    p40 = renderer_assets.cloud_positions(W, H, 40)
    assert len(p0) == 3, f"expected three clouds, got {len(p0)}"
    for (x0, y0), (x1, y1) in zip(p0, p40):
        assert abs((x1 - x0) - renderer_assets.CLOUD_SPEED * 40) <= 1.0, \
            f"cloud moved {x1 - x0:.1f} px over 40 frames, speed is " \
            f"{renderer_assets.CLOUD_SPEED}"
        assert y0 == y1, "cloud rows moved vertically"
    rows = [y for _, y in p0]
    assert sorted(rows) == rows and len(set(rows)) == 3, f"cloud rows not stacked: {rows}"
    xs = [x for x, _ in renderer_assets.cloud_positions(W, H, 7000)]
    assert min(xs) >= -half and max(xs) <= W + half, \
        f"clouds leave the wrap band: x {min(xs)}..{max(xs)} against {-half}..{W + half}"


def test_background_blits_the_cloud_plate():
    """draw_background must blit the cloud sprite over the plate, not draw circles:
    every cloud region has to match a plate+sprite blend pixel for pixel."""
    assets = renderer_assets.load_assets(1920, 1080)
    surf = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    rend = renderer_mod.Renderer(surf)
    frame = None
    slot = renderer_assets._scaled(renderer_assets.CLOUD_SLOT, "cloud")
    half = slot[0] // 2
    for f in range(0, 400):
        pos = renderer_assets.cloud_positions(1920, 1080, f)
        if all(half <= x <= 1920 - half for x, _ in pos):
            frame = f
            break
    assert frame is not None, "no frame puts all three clouds fully on screen"

    rend.draw_background(1, frame_count=frame)
    got = pygame.surfarray.array3d(surf).transpose(1, 0, 2)          # [y][x][3]
    plate = pygame.surfarray.array3d(assets["bg_daytime"]).transpose(1, 0, 2)
    cloud = assets["cloud@0"]
    c_rgb = pygame.surfarray.array3d(cloud).transpose(1, 0, 2)
    c_al = pygame.surfarray.array_alpha(cloud).transpose(1, 0) / 255.0

    checked = 0
    for cx, cy in renderer_assets.cloud_positions(1920, 1080, frame):
        left = int(cx - slot[0] // 2)
        top = int(cy - slot[1] // 2)
        want = plate[top:top + slot[1], left:left + slot[0]] * (1.0 - c_al[:, :, None]) \
            + c_rgb * c_al[:, :, None]
        region = got[top:top + slot[1], left:left + slot[0]]
        assert region.shape == want.shape, f"cloud region {region.shape} != sprite {want.shape}"
        diff = float(np.abs(region.astype(np.int32) - np.round(want)).mean())
        assert diff < 4.0, f"cloud at ({cx},{cy}) is not the plate sprite: mean L1 {diff:.1f}"
        checked += 1
    assert checked == 3, f"only {checked} clouds checked"


def _ico_frames(path):
    """Decode an ICO container ourselves: header + 16-byte directory entries + payloads.

    `tools/make_icon.py` writes PNG-compressed frames, so each payload is a whole PNG;
    decoding here keeps the test independent of Pillow's ICO reader.
    """
    from io import BytesIO
    from PIL import Image
    data = open(path, "rb").read()
    reserved, rtype, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and rtype == 1, f"not an ICO container: reserved={reserved} type={rtype}"
    frames = {}
    for i in range(count):
        ent = data[6 + i * 16: 6 + i * 16 + 16]
        w, h = struct.unpack("<BB", ent[:2])
        bpp = struct.unpack("<H", ent[6:8])[0]
        size, off = struct.unpack("<II", ent[8:16])
        side = w or 256, h or 256
        assert side[0] == side[1], f"icon frame {side} is not square"
        assert bpp == 32, f"icon frame {side} has {bpp} bpp, needs 32 for rounded corners"
        payload = data[off: off + size]
        assert payload[:8] == b"\x89PNG\r\n\x1a\n", f"icon frame {side} is not a PNG payload"
        img = Image.open(BytesIO(payload)).convert("RGBA")
        assert img.size == side, f"icon frame declares {side} but decodes to {img.size}"
        frames[side] = img
    return frames


def test_icon_asset_ships_the_sizes_windows_needs():
    """`assets/generated/icon.ico` must carry 16/32/48/256 at 32 bpp."""
    path = renderer_assets._asset_path("icon.ico")
    assert os.path.exists(path), f"no icon asset at {path}"
    frames = _ico_frames(path)
    assert set(frames) == {(16, 16), (32, 32), (48, 48), (256, 256)}, \
        f"icon sizes {sorted(frames)} != 16/32/48/256"


def test_icon_crop_is_the_face_not_the_whole_body():
    """The crop is a square around the face: it contains both eyes and stops above
    the paws, so the tile reads as a cat FACE rather than a smudged whole cat."""
    import tools.make_icon as make_icon
    crop = make_icon.face_crop()
    al = pygame.surfarray.array_alpha(crop).transpose(1, 0)          # [y][x]
    rgb = pygame.surfarray.array3d(crop).transpose(1, 0, 2).astype(np.int32)
    solid = al >= 240
    assert crop.get_width() == crop.get_height(), f"face crop {crop.get_size()} is not square"

    green = (rgb[..., 1] > rgb[..., 0] + 30) & (rgb[..., 1] > rgb[..., 2] + 20) & solid
    cols = np.nonzero(green.any(axis=0))[0]
    assert len(cols) > 0, "the crop holds no green eyes -- it is not the face"
    span = cols.max() - cols.min() + 1
    assert span > crop.get_width() * 0.25, f"eyes fill only {span}/{crop.get_width()} of the tile"

    ys, xs = np.nonzero(solid)
    body = renderer_assets.matted_surface("cat_idle")
    bal = pygame.surfarray.pixels_alpha(body).transpose(1, 0)
    bsolid = bal >= 240
    bys, bxs = np.nonzero(bsolid)
    body_h = bys.max() - bys.min() + 1
    # the crop must be a fraction of the body and must stop short of the paw band
    assert crop.get_width() < bxs.max() - bxs.min() + 1, "crop is as wide as the whole cat"
    assert ys.max() <= bys.max() - int(0.10 * body_h), \
        f"crop reaches y {ys.max()}, inside the paw band (body bottom {bys.max()})"


def test_icon_tile_is_a_rounded_tile_on_daytime_sky():
    """Backdrop comes from the daytime plate's own sky; corners are transparent so
    Explorer shows a rounded tile, and the face covers most of it."""
    import tools.make_icon as make_icon
    tile = make_icon.tile_master(256)
    arr = np.asarray(tile)                                    # [y][x][4]
    assert arr.shape[:2] == (256, 256), f"tile {arr.shape[:2]} != 256x256"
    assert arr[0, 0, 3] == 0 and arr[0, -1, 3] == 0 and arr[-1, 0, 3] == 0 and arr[-1, -1, 3] == 0, \
        "tile corners are not transparent"
    assert arr[128, 0, 3] == 255 and arr[0, 128, 3] == 255, "tile edge midpoints are cut away"

    plate = renderer_assets._plate_surface("bg_daytime")
    pa = pygame.surfarray.array3d(plate).transpose(1, 0, 2)    # [y][x][3]
    sky_top = pa[4, pa.shape[1] // 2]
    sky_low = pa[int(pa.shape[0] * 0.30), pa.shape[1] // 2]
    # the face crop is inset, so the outer margin is pure sky: check both ends of the
    # gradient against the plate's own sampled rows
    band = arr[:12, :, :3]
    assert int(np.abs(band.astype(np.int32) - sky_top[None, None, :]).mean()) < 30, \
        f"tile top {tuple(band.mean(axis=(0, 1)))} is not the plate's sky ({tuple(sky_top)})"
    low = arr[-12:, :, :3]
    assert int(np.abs(low.astype(np.int32) - sky_low[None, None, :]).mean()) < 30, \
        f"tile bottom {tuple(low.mean(axis=(0, 1)))} is not the plate's sky ({tuple(sky_low)})"

    # fur is identified by colour, not alpha: the sky margin is fully opaque too
    grad = np.round(sky_top[None, :] * (1.0 - np.linspace(0.0, 1.0, 256)[:, None])
                   + sky_low[None, :] * np.linspace(0.0, 1.0, 256)[:, None])
    away = np.abs(arr[..., :3].astype(np.int32) - grad[:, None, :]).mean(axis=2)
    fur = (arr[..., 3] >= 240) & (away > 30)
    assert int(fur.sum()) > 256 * 256 * 0.45, f"face covers only {int(fur.sum())} of 65536 px"
    crop = make_icon.face_crop()
    side_face = int(round(256 * make_icon.FACE_FILL))
    scaled = renderer_assets.clean_scale(crop, (side_face, side_face))
    src = pygame.surfarray.array3d(scaled).transpose(1, 0, 2).astype(np.int32)
    sa = pygame.surfarray.array_alpha(scaled).transpose(1, 0)
    tile_mean = arr[..., :3][fur].astype(np.int32).mean(axis=0)
    crop_mean = src[sa == 255].mean(axis=0)
    drift = float(np.abs(tile_mean - crop_mean).max())
    assert drift < 12, f"tile fur colour drifts from the plate: max channel diff {drift:.1f}"


def test_shipped_icon_matches_the_tool_output():
    """The committed .ico must be what `tools/make_icon.py` produces, frame for frame."""
    import tools.make_icon as make_icon
    path = renderer_assets._asset_path("icon.ico")
    frames = _ico_frames(path)
    sizes = sorted(frames)
    master = make_icon.tile_master(max(sizes)[0])
    for side, img in frames.items():
        want = np.asarray(master.resize(side, Image.LANCZOS))
        got = np.asarray(img)
        assert got.shape == want.shape, f"{side} frame shape {got.shape} != {want.shape}"
        diff = float(np.abs(got.astype(np.int32) - want.astype(np.int32)).mean())
        assert diff == 0.0, f"{side} frame differs from the tool output by mean L1 {diff}"


def test_spec_points_at_the_icon_asset():
    """PyInstaller must embed the icon, otherwise the EXE shows pygame's default."""
    spec = open(os.path.join(os.path.dirname(renderer_assets.__file__), "CatsVsMice.spec"),
                encoding="utf-8").read()
    m = re.search(r"icon\s*=\s*['\"]([^'\"]+)['\"]", spec)
    assert m, "CatsVsMice.spec has no icon= field"
    target = os.path.normpath(os.path.join(os.path.dirname(renderer_assets.__file__), m.group(1)))
    assert os.path.exists(target), f"spec icon points at a missing file: {target}"


def test_menu_plate_loaded_once_at_display_size():
    """`load_assets` hands out the menu plate at the display size, like the theme plates."""
    width, height = 1920, 1080
    assets = renderer_assets.load_assets(width, height)
    key = renderer_assets.MENU_PLATE
    assert key in assets, f"missing asset key: {key}"
    surf = assets[key]
    assert isinstance(surf, pygame.Surface), f"{key} is not a Surface"
    assert surf.get_size() == (width, height), f"{key} is {surf.get_size()} != {(width, height)}"
    assert len(surf.get_at((0, 0))) == 4, f"{key} has no per-pixel alpha"
    # one plate, cached: asking twice gives the SAME Surface, so no second read/scale
    again = renderer_assets.load_assets(width, height)
    assert again[key] is surf, f"{key} rebuilt on every load_assets call"


def test_menu_blits_the_plate_not_a_flat_fill():
    """draw_menu paints the menu plate over the whole screen; the UI bands still draw."""
    pygame.init()
    screen = pygame.display.set_mode((1920, 1080))
    rend = renderer_mod.Renderer(screen)
    screen.fill((7, 13, 23))          # sentinel nothing in the plate matches
    rend.draw_menu(1)
    got = pygame.surfarray.array3d(screen).transpose(1, 0, 2)      # [y][x][3]
    plate = pygame.surfarray.array3d(rend.assets[renderer_assets.MENU_PLATE]).transpose(1, 0, 2)

    # regions the UI does NOT paint over: left of the title/buttons and right of them
    for y0, y1, x0, x1 in ((300, 1079, 0, 700), (300, 1079, 1200, 1919)):
        a, b = got[y0:y1, x0:x1], plate[y0:y1, x0:x1]
        drift = float(np.abs(a.astype(np.int32) - b.astype(np.int32)).mean())
        assert drift < 8, f"menu region y{y0}..{y1} x{x0}..{x1} differs from the plate by L1 {drift:.1f}"
    flat = int((np.abs(got.astype(np.int32) - np.array([30, 30, 50])).max(axis=2) == 0).sum())
    assert flat < 1000, f"{flat} px still the old flat menu fill -- plate not blitted"

    # the button rects are drawn ON TOP of the plate, so they must differ from it
    band = got[432:828, 795:1069]
    plate_band = plate[432:828, 795:1069]
    assert float(np.abs(band.astype(np.int32) - plate_band.astype(np.int32)).mean()) > 10, \
        "button column was not painted over the plate"


def test_dead_asset_files_are_gone_and_mouse_sizes_still_resolve():
    """The duplicate mouse plates and the never-blitted dust plate are not shipped;
    the three mouse sizes still come out of the one plate."""
    generated = os.path.join(os.path.dirname(renderer_assets.__file__), "assets", "generated")
    for gone in ("mouse_small.png", "mouse_medium.png", "dust_puff.png"):
        path = os.path.join(generated, gone)
        assert not os.path.exists(path), f"dead asset still on disk: {path}"
    assert renderer_assets.LAZY_SPRITES == {}, "LAZY_SPRITES still holds a plate nothing blits"

    assets = renderer_assets.load_assets(1920, 1080)
    assert "dust_puff" not in assets, "loader still hands out dust_puff"
    want = {"mouse_small": (66, 54), "mouse_medium": (87, 72), "mouse_large": (120, 99)}
    for key, size in want.items():
        surf = assets[key]
        assert isinstance(surf, pygame.Surface), f"{key} is not a Surface"
        assert surf.get_size() == size, f"{key} is {surf.get_size()} != {size}"


def test_frame_artifacts_stay_out_of_the_repo():
    """The suite's saved frame goes somewhere OUTSIDE the project, so running tests
    leaves no scratch folder behind."""
    repo = os.path.dirname(os.path.abspath(renderer_assets.__file__))
    target = os.path.abspath(PREVIEW_DIR)
    assert not os.path.normcase(target).startswith(os.path.normcase(repo)), \
        f"preview dir {target} lives inside the project ({repo})"


def run_tests():
    tests = [
        test_asset_paths_resolve,
        test_loader_returns_surfaces,
        test_box_mean_is_a_window_mean,
        test_tail_pivot_pins_the_base,
        test_tail_clears_the_body,
        test_strip_crop_widths,
        test_headless_frame,
        test_milestone_and_menu_paths,
        test_theme_lookup_unchanged,
        test_cloud_asset_is_cropped_to_its_cloud,
        test_cloud_tinted_variants_exist_for_every_theme,
        test_cloud_positions_drift_and_wrap,
        test_background_blits_the_cloud_plate,
        test_icon_asset_ships_the_sizes_windows_needs,
        test_icon_crop_is_the_face_not_the_whole_body,
        test_icon_tile_is_a_rounded_tile_on_daytime_sky,
        test_shipped_icon_matches_the_tool_output,
        test_spec_points_at_the_icon_asset,
        test_menu_plate_loaded_once_at_display_size,
        test_menu_blits_the_plate_not_a_flat_fill,
        test_dead_asset_files_are_gone_and_mouse_sizes_still_resolve,
        test_frame_artifacts_stay_out_of_the_repo,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS: {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL: {t.__name__} - {e}")
    print(f"\nResults: {passed} passed, {failed} failed, {len(tests)} total")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
