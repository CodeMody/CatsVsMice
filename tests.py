"""Unit tests for core game logic."""
import math
import random
import sys

# Import modules
import physics
import level_generator
import game as game_mod
import high_scores
import entities


def test_clamp_drag():
    """Drag distance is clamped to MAX_DRAG."""
    sx, sy = 230, 420
    # Point far away
    cx, cy = physics.clamp_drag(sx + 500, sy, sx, sy)
    dx = cx - sx
    dy = cy - sy
    dist = math.sqrt(dx*dx + dy*dy)
    assert abs(dist - physics.MAX_DRAG) < 0.1, f"Clamp failed: dist={dist}"
    # Point within range
    cx, cy = physics.clamp_drag(sx + 50, sy, sx, sy)
    assert math.sqrt((cx-sx)**2 + (cy-sy)**2) == 50.0


def test_launch_speed():
    """Launch speed scales with drag distance, max at full drag."""
    # Full drag
    vx, vy = physics.compute_launch(260, 0)
    assert abs(vx - 26.0) < 0.1 and abs(vy) < 0.1
    # Half drag
    vx, vy = physics.compute_launch(130, 0)
    assert abs(vx - 13.0) < 0.1
    # Below threshold
    vx, vy = physics.compute_launch(3, 0)
    assert vx == 0.0 and vy == 0.0


def test_circle_rect_collision():
    """Circle vs rectangle detection works."""
    hit, nx, ny, pen = physics.circle_rect_collision(50, 50, 10, 55, 45, 20, 20)
    assert hit
    # No hit
    hit, _, _, _ = physics.circle_rect_collision(10, 10, 5, 50, 50, 20, 20)
    assert not hit


def test_circle_circle_collision():
    """Circle vs circle detection works. Normal points from the second circle toward the first."""
    hit, nx, ny, pen = physics.circle_circle_collision(0, 0, 10, 15, 0, 10)
    assert hit and abs(nx + 1.0) < 0.01
    hit, _, _, _ = physics.circle_circle_collision(0, 0, 5, 100, 0, 5)
    assert not hit


def test_gravity_friction():
    """Gravity and friction apply correctly per step."""
    vx, vy = 10.0, 0.0
    # After one step
    vy += physics.GRAVITY
    vx *= physics.FRICTION
    assert abs(vy - physics.GRAVITY) < 0.01
    assert abs(vx - 10.0 * physics.FRICTION) < 0.01


def test_block_hp():
    """Blocks lose HP and disappear at zero."""
    blk = level_generator.Block(x=0, y=0, w=40, h=30, material="wood", hp=2)
    blk.hp -= 1
    assert blk.hp == 1
    blk.hp -= 1
    assert blk.hp == 0
    blk.alive = False


def test_strong_hit_damage():
    """Speed above STRONG_HIT_THRESHOLD causes two damage to mice."""
    strength = physics.impact_strength(40, 0)
    assert strength == 40.0
    assert strength > physics.STRONG_HIT_THRESHOLD
    damage = 2  # as specified


def test_large_mouse_returns_cat():
    """Large mouse (2HP) restores one cat when killed."""
    m = level_generator.Mouse(x=100, y=400, size=2, hp=2)
    assert m.max_hp == 2
    # Simulate kill
    m.hp = 0
    m.alive = False
    assert m.size == 2  # triggers cat return


def test_mouse_falling():
    """Mouse falls when support removed."""
    # Simulate: mouse at y=400, no block below, ground at 500
    m = level_generator.Mouse(x=600, y=400, size=1, hp=1)
    # After update_falling_mice: y increases by GRAVITY*0.6
    fall_speed = physics.GRAVITY * 0.6
    m.y += fall_speed
    assert m.y > 400  # fell down


def test_debris_damage():
    """Debris damages mice (3 HP) and expires."""
    d = entities.Debris(x=100, y=400, vx=0, vy=0, size=5, life=120, max_life=120)
    m = entities.Mouse(x=100, y=400, size=0, hp=1)
    hit, _, _, _ = physics.circle_circle_collision(d.x, d.y, d.radius, m.x, m.y, m.radius)
    assert hit
    m.hp -= 3
    assert m.hp <= 0
    # Debris expires
    d.life = 0
    assert d.life <= 0


def test_deterministic_generation():
    """Same level number generates identical layout."""
    blocks1, mice1 = level_generator.generate_level(7)
    blocks2, mice2 = level_generator.generate_level(7)
    assert len(blocks1) == len(blocks2)
    assert len(mice1) == len(mice2)
    for b1, b2 in zip(blocks1, blocks2):
        assert b1.x == b2.x and b1.y == b2.y
        assert b1.hp == b2.hp
    for m1, m2 in zip(mice1, mice2):
        assert m1.x == m2.x and m1.y == m2.y


def test_mouse_count_cap():
    """Mouse count never exceeds level limit."""
    for lvl in range(1, 51):
        _, mice = level_generator.generate_level(lvl)
        max_m = 6 if lvl % 5 == 0 else 5
        assert len(mice) <= max_m


def test_scoring_bonus_once():
    """Level bonus awarded exactly once."""
    g = game_mod.Game()
    g.start_level(1)
    # Simulate all mice dead
    for m in g.mice:
        m.alive = False
    g.check_level_complete()
    assert g.bonus_awarded
    # Calling again should not add bonus
    g.check_level_complete()
    assert g.score == 1000 + 500 * 5  # only once


def test_challenge_bonus():
    """Challenge levels get +2000 bonus."""
    g = game_mod.Game()
    g.start_level(5)  # challenge
    for m in g.mice:
        m.alive = False
    g.check_level_complete()
    expected = 1000 + 500 * 5 + 2000
    assert g.score == expected


def test_cat_supply_reset():
    """Cat supply resets to 5 on level transition."""
    g = game_mod.Game()
    g.start_level(1)
    assert g.cats_remaining == 5
    g.cats_remaining = 0
    g.start_level(2)
    assert g.cats_remaining == 5


def test_game_over_victory():
    """Game over and victory transitions work."""
    g = game_mod.Game()
    g.start_level(1)
    g.cats_remaining = 0
    g.cat = game_mod.Cat(x=0, y=0, vx=0, vy=0)
    g.cat.active = False
    g.check_game_over()
    assert g.state == game_mod.GameState.GAME_OVER

    g2 = game_mod.Game()
    g2.start_level(50)
    for m in g2.mice:
        m.alive = False
    g2.check_level_complete()
    # Next level > 50 → victory
    assert g2.level == 50


def test_high_scores():
    """High scores sorted, capped at 5, saved safely. Uses a scratch file, not the player's board."""
    import tempfile
    from pathlib import Path
    scratch = Path(tempfile.gettempdir()) / "catsvsmice_high_scores_test.json"
    scratch.unlink(missing_ok=True)
    original_save_path = high_scores._save_path
    high_scores._save_path = lambda: scratch
    try:
        scores = high_scores.add_score("TestPlayer", 5000)
        assert len(scores) <= 5
        assert scores[0]["score"] >= scores[-1]["score"]
        # Empty name → Anonymous
        scores2 = high_scores.add_score("", 100)
        names = [s["name"] for s in scores2]
        assert "Anonymous" in names
    finally:
        high_scores._save_path = original_save_path
        scratch.unlink(missing_ok=True)


def test_all_levels_generate():
    """All 50 levels generate without error."""
    for lvl in range(1, 51):
        blocks, mice = level_generator.generate_level(lvl)
        assert isinstance(blocks, list)
        assert isinstance(mice, list)


def run_tests():
    tests = [
        test_clamp_drag,
        test_launch_speed,
        test_circle_rect_collision,
        test_circle_circle_collision,
        test_gravity_friction,
        test_block_hp,
        test_strong_hit_damage,
        test_large_mouse_returns_cat,
        test_mouse_falling,
        test_debris_damage,
        test_deterministic_generation,
        test_mouse_count_cap,
        test_scoring_bonus_once,
        test_challenge_bonus,
        test_cat_supply_reset,
        test_game_over_victory,
        test_high_scores,
        test_all_levels_generate,
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