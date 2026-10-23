"""Headless tests for the Phase 3 asset loader (`renderer_assets`) and its use
by `renderer.Renderer`. Same plain-assert style as tests.py: each `test_*` runs
through `run_tests()` and `python tests_assets.py` exits non-zero on failure."""
import math
import os
import shutil
import sys
import tempfile

import pygame

import entities
import level_generator
import renderer as renderer_mod
import renderer_assets

PREVIEW_DIR = os.path.join(".superpowers", "brainstorm", "preview")


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
    expected = {
        "cat_idle": (54, 54),
        "cat_tail": (53, 46),
        "mouse_small": (44, 36),
        "mouse_medium": (58, 48),
        "mouse_large": (80, 66),
        "sling_fork": (200, 130),
        "supercat": (300, 260),
        "debris_wood": (18, 18),
        "debris_stone": (18, 18),
        "dust_puff": (48, 48),
        "bg_daytime": (width, height),
        "bg_sunset": (width, height),
        "bg_night": (width, height),
        "bg_twilight": (width, height),
    }
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
        for key, size in (("cat_idle", (54, 54)), ("mouse_large", (80, 66))):
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


def run_tests():
    tests = [
        test_asset_paths_resolve,
        test_loader_returns_surfaces,
        test_strip_crop_widths,
        test_headless_frame,
        test_milestone_and_menu_paths,
        test_theme_lookup_unchanged,
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
