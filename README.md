
# Cats vs Mice

A physics-based projectile game built with **Python 3.12** and **pygame**, inspired by the classic slingshot-launch genre. Launch cats from a slingshot to knock out mice hidden inside destructible structures. The game features 50 procedurally generated levels, milestones, challenge levels, high-score leaderboards, and procedural audio — all without any external asset dependencies beyond a single optional background music file.

---

## Table of Contents

1. [Overview](#overview)
2. [Gameplay](#gameplay)
3. [Architecture / Project Structure](#architecture--project-structure)
4. [Module Documentation](#module-documentation)
5. [Physics Model](#physics-model)
6. [Level Generation](#level-generation)
7. [Scoring & Progression](#scoring--progression)
8. [High Scores](#high-scores)
9. [Audio System](#audio-system)
10. [Rendering & Themes](#rendering--themes)
11. [Testing](#testing)
12. [Building a Standalone EXE](#StandaloneExe)
13. [Installation & Running](#installation--running)
14. [Controls](#controls)

---

## Overview

**Cats vs Mice** is a single-screen slingshot physics game. You drag a cat back on a slingshot, aim using a trajectory preview, and release to launch it. The cat obeys gravity and friction, bounces off ground and structures, and destroys blocks and mice on impact. Clear every mouse in a level with a limited supply of cats to advance.

- **Resolution:** 1920 × 1080 (UI scales to the actual display surface)
- **Frame rate:** 60 FPS fixed timestep
- **Levels:** 50 (deterministic procedural generation)
- **Dependencies:** `pygame` (plus the Python standard library only)

---

## Gameplay

- **Goal:** Eliminate every mouse in a level.
- **Resources:** You start each level with **5 cats**. A strong hit on a large mouse (size 2) returns one cat.
- **Aiming:** Click and drag near the cat to pull the slingshot band; release to fire. A dotted trajectory preview shows the predicted arc.
- **Win:** Clear all 50 levels → **VICTORY**.
- **Lose:** Run out of cats while mice remain → **GAME OVER**.

### Game States (`game.GameState`)

| State | Meaning |
|-------|---------|
| `MENU` | Title screen; click Play / Scoreboard / Volume / Quit |
| `PLAYING` | Active level: aiming + physics simulation |
| `LEVEL_COMPLETE` | All mice cleared; shows bonus, click to continue |
| `MILESTONE` | Flown-in "SuperCat" animation on levels 10/20/30/40 |
| `GAME_OVER` | Cats exhausted with mice alive |
| `VICTORY` | Completed level 50 |
| `NAME_INPUT` | Enter your name if the score qualifies for top-5 |
| `SCOREBOARD` | Displays top-5 high scores |

---

## Architecture / Project Structure

**Dependency graph (imports):**

---

## Module Documentation

### `main.py` — Entry point
Sets up the pygame window (1920×1080, 60 FPS), instantiates `Game` and `Renderer`, and runs the main loop. Each frame it:
1. Handles quit events and name-input keyboard events.
2. Dispatches input/rendering per game state (menu, scoreboard, level-complete, milestone, game-over, victory, name-input).
3. In `PLAYING`: handles restart button, cat preparation, aiming/drag/release logic, physics step, and full scene rendering.

Helper functions: `_handle_menu_input`, `_handle_scoreboard_input`, `_advance_level`, `_save_and_restart`, `_in_rect`.

### `game.py` — Game orchestration
Defines `GameState` and the `Game` class. Key responsibilities:
- `start_level(n)` — resets cats/score state and generates the level layout.
- `prepare_cat` / `begin_drag` / `update_drag` / `release_launch` — aiming & launch control.
- `update_physics()` — one fixed-timestep step: gravity, friction, ground/field bounds, block & mouse collisions, damage, bouncing, particles, stop conditions.
- `update_falling_mice()` — mice lose support when blocks beneath them are destroyed and fall.
- `update_debris()` / `update_particles()` — cosmetic/secondary physics.
- `check_level_complete()` / `check_game_over()` — progression transitions.

### `entities.py` — Data models
Plain-Python entity classes (no pygame dependency):
- **`Cat`** — position, velocity, radius 27, `launched`/`active`/`first_hit`/`life_after_hit` flags.
- **`Mouse`** — `size` (0 small / 1 medium / 2 large), `hp`, radius derived from size `[22, 29, 40]`, animation phases.
- **`Block`** — AABB with `material` (`wood`/`stone`), `hp`, `alive`.
- **`Particle`** / **`Debris`** — short-lived visual/secondary entities.

### `physics.py` — Physics engine
Standalone constants and pure functions (fully testable):
- Constants: `GRAVITY`, `FRICTION`, `MAX_DRAG`, `MAX_SPEED`, `CAT_RADIUS`, `BOUNCE_DAMP`, `GROUND_DAMP`, `GROUND_Y`, field bounds, `STOP_SPEED`, `STOP_TIME`, etc.
- `clamp_drag` — clamps drag point to `MAX_DRAG` from slingshot.
- `compute_launch` — converts drag offset to launch velocity (speed scales with pull distance, capped at `MAX_SPEED`).
- `trajectory_preview` — simulates the arc for the aim preview.
- `circle_rect_collision` / `circle_circle_collision` — return `(hit, nx, ny, penetration)`.
- `resolve_bounce` / `ground_bounce` — velocity reflection with damping.
- `impact_strength` — velocity magnitude used for damage.

### `level_generator.py` — Procedural levels
`generate_level(level_number)` is **deterministic**: seeded with `random.Random(level_number * 7919 + 31)`. Builds 1–5 tower structures (columns + top beam) in the playfield `x ∈ [713, 1700]`, scales block HP and structure count by tier, and places mice on surfaces. Challenge levels (multiples of 5) add extra structures/mice and a bonus. Mouse counts are capped at 5 (6 on challenge levels).
Helpers: `_surface_clear`, `_pick_free_ground_x`, `_pick_mouse_size`.

### `renderer.py` — Rendering
`Renderer` draws everything with pygame primitives (no sprite assets). Four theme palettes (`THEMES`) cycle by level via `get_theme()`: Daytime, Sunset, Night, Twilight. Provides drawing routines for backgrounds (animated sky, sun/moon, hills, trees, grass, clouds, stars), slingshot, cat, mice, blocks, particles, debris, trajectory, HUD, menu, scoreboard, completion, game-over, victory, and the milestone "SuperCat" animation.

### `audio.py` — Procedural audio
Generates all sound effects at runtime as WAV bytes (`generate_sound`) — no audio asset files required. Provides `meow`, `thud`, `crunch`, `squeak`, `whoosh`, `ouch`. Background music is loaded from `assets/ambient_loop.wav` if present. `AudioManager` singleton exposes `ensure_ready()` (must be called after `pygame.init()`), `play(name)`, `set_volume(v)`, `get_volume()`. All audio failures are swallowed so audio never crashes the game.

### `high_scores.py` — Leaderboard
Stores top-5 scores in `high_scores.json` next to the module. Handles missing/corrupt files gracefully. API: `load_scores`, `save_scores`, `add_score(name, score)` (blank name → `"Anonymous"`), `qualifies(name, score)`.

### `tests.py` — Unit tests
Self-contained test runner covering physics, collisions, level generation determinism/caps, scoring bonuses, cat supply, game-over/victory transitions, and high-score persistence. Exits non-zero on failure.

---

## Physics Model

Fixed-timestep (per frame at 60 Hz) integration:
- **Gravity:** `vy += GRAVITY` (0.72)
- **Friction/air drag:** `vx *= FRICTION` (0.99)
- **Launch:** speed scales with pull distance up to `MAX_SPEED` (46.8); drag clamped to `MAX_DRAG` (468).
- **Ground bounce:** `vx *= GROUND_H_MULT`, `vy = -vy * GROUND_DAMP`.
- **Surface bounce:** velocity reflected across collision normal, scaled by `BOUNCE_DAMP` (0.42).
- **Damage:** block damage `= max(1, int(strength / 8))`; mouse damage `2` if `strength > STRONG_HIT_THRESHOLD` else `1`.
- **Stop condition:** cat becomes inactive after `STOP_TIME` (60 frames) past first collision, or when speed < `STOP_SPEED` on the ground.

---

## Level Generation

- **50 levels**, organized into tiers of 10 (`tier = (level-1)//10`).
- Difficulty scales block HP, structure count, and column height with tier/sublevel.
- Primary material is `wood` in tier 0, `stone` in higher tiers (with occasional wood caps).
- Challenge levels (multiples of 5) get extra structures, more/larger mice, and a scoring bonus.
- Generation is fully deterministic per level number (verified by tests).

---

## Scoring & Progression

- **Level clear bonus:** `1000 + 500 * cats_remaining` (awarded exactly once per level).
- **Challenge bonus:** `+2000` on challenge levels.
- **Milestones:** flying "SuperCat" intro on levels 10/20/30/40.
- **Victory:** completing level 50.
- On game-over/victory, the score is submitted; if it qualifies for top-5, the player enters their name.

---

## High Scores

Persisted to `high_scores.json` (top-5, sorted descending). Blank names become `"Anonymous"`. Corrupt/missing files are treated as empty.

---

## Audio System

All SFX are procedurally synthesized (sine/envelope math → WAV bytes) and loaded into `pygame.mixer.Sound` objects. Background music uses `assets/ambient_loop.wav` when available. Master volume is adjustable from the menu (0.0–1.0). Audio is fully optional — the game runs if pygame mixer is unavailable.

---

## Rendering & Themes

No external image assets — all graphics are drawn with pygame primitives. Four themes cycle every 5 levels: Daytime → Sunset → Night → Twilight. Night/Twilight add twinkling stars. UI scales to the real display surface.

---

## Testing

Run the test suite to validate core logic:

The runner reports `PASS`/`FAIL` per test and exits `0` on success.

> **Note:** In a one-file build, `high_scores.json` is written into PyInstaller's temporary extraction folder and does not persist between runs. The leaderboard works normally when running the game from source (`python main.py`).

---
## Building a Standalone Executable

The game is compiled into a single-file Windows executable using **PyInstaller**, driven by the checked-in spec file `CatsVsMice.spec`.

### Build artifacts

| Path | Description |
|------|-------------|
| `CatsVsMice.spec` | PyInstaller build specification: entry point `main.py`, bundles `assets/` as a data directory, UPX-compressed, windowed (no console), single-file output |
| `build/` | Intermediate compilation artifacts produced by PyInstaller (safe to delete; regenerated on each build) |
| `dist/CatsVsMice.exe` | The final standalone game — pygame and all project modules are bundled inside; no Python installation needed to run it |

### Rebuilding

Or from scratch (equivalent to the spec):

### Running the compiled game

Double-click `dist\CatsVsMice.exe` or run it from a terminal:powershell .\dist\CatsVsMice.exe

## Installation & Running

Requires **Python 3.12** and **pygame**. A virtual environment (`.venv`) is configured in the project.

---

## Controls

**Mouse:**
- **Menu:** click Play / Scoreboard / Volume (drag slider) / Quit.
- **Playing:** click near the cat to grab it, drag to aim, release to launch. Click the in-level "Restart" button to restart the current level.
- **Level complete / milestones / game over / victory / scoreboard:** click to continue or return.

**Keyboard:**
- `Esc` — quit.
- In name-input: type your name, `Backspace` to edit, `Enter` to confirm.

---

*Generated project documentation — see individual module docstrings for detailed API references.*
