
# Cats vs Mice

A physics-based projectile game built with **Python 3.12** and **pygame**, inspired by the classic slingshot-launch genre. Launch cats from a slingshot to knock out mice hidden inside destructible structures. The game features 50 procedurally generated levels, milestones, challenge levels, high-score leaderboards, and procedural audio — graphics are pre-baked PNG assets generated with ComfyUI (`moss-image-sft`, one seed for the whole set) and shipped from `assets/generated/` inside the build, while audio needs no files beyond a single optional background music file. Runs from source on any platform pygame supports; the checked-in spec builds a standalone **Windows** EXE (see [Building for Linux](#linux-build)).

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
13. [Building for Linux](#linux-build)
14. [Installation & Running](#installation--running)
15. [Controls](#controls)

---

## Overview

**Cats vs Mice** is a single-screen slingshot physics game. You drag a cat back on a slingshot, aim using a trajectory preview, and release to launch it. The cat obeys gravity and friction, bounces off ground and structures, and destroys blocks and mice on impact. Clear every mouse in a level with a limited supply of cats to advance.

- **Resolution:** 1920 × 1080 (UI scales to the actual display surface)
- **Frame rate:** 60 FPS fixed timestep
- **Levels:** 50 (deterministic procedural generation)
- **Dependencies:** `pygame` and `Pillow` (`renderer_assets.py` decodes the PNG plates with Pillow; PyInstaller picks it up automatically), plus the Python standard library

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

```
main.py ──► game.py ──► entities.py, physics.py, level_generator.py, high_scores.py
   │           │
   │           └──────► renderer.py ──► renderer_assets.py   (leaf: pygame + numpy + Pillow)
   │                        │
   │                        └──► physics.py  (trajectory_preview, imported inside draw_trajectory)
   ├──► renderer.py
   ├──► audio.py        (standalone: stdlib only)
   └──► high_scores.py

tests.py ───────► physics, level_generator, game, high_scores, entities
tests_assets.py ─► entities, level_generator, renderer, renderer_assets
tools/make_icon.py ► renderer_assets  (build-time only, not bundled in the EXE)
```

`renderer_assets.py` imports nothing from this project, so it is the seam everything else
can be tested through: plates are decoded once, matted, cached, and handed out as Surfaces.

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
`Renderer` is asset-first: it blits pre-baked PNG plates from `assets/generated/` (loaded and cached once by `renderer_assets.py`, which also downscales every sprite to its game size at load time) and paints only the procedural parts on top. Four theme palettes (`THEMES`) cycle by level via `get_theme()`: Daytime, Sunset, Night, Twilight — the matching full-screen background plate cycles with them every 5 levels. Provides drawing routines for backgrounds (blitted plate plus three drifting cloud sprites and twinkling stars; sun/moon, hills, trees and grass are baked into the plate), slingshot, cat, mice, blocks, particles, debris, trajectory, HUD, menu (blitted `bg_menu` plate), scoreboard, completion, game-over, victory, and the milestone "SuperCat" animation.

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

Graphics are pre-baked PNG assets in `assets/generated/` — generated with ComfyUI (`moss-image-sft`, one seed for the whole set) — not pygame primitives. Sprites are keyed on a flat magenta backdrop and matted at load time (despill + feather, with an alpha clamp); each theme applies a multiply tint (×1.0 / ×0.8221 / ×0.25 / ×0.644) plus an additive grey lift; background plates are 1920×1072 full-bleed art blitted at their native aspect (the per-theme vertical offsets are now all zero) so each plate's unbroken lawn band covers the game floor at `H - 180` with margin; the main menu has its own plate, `bg_menu.png` — a dusk sky generated from the prompt document `.superpowers/brainstorm/regen-prompts-v4-menu-plate.md`, loaded once at display size and cached process-wide, so a second Renderer gets the same Surface instead of re-decoding it. It is never tinted: `draw_menu` blits it full-screen and paints the amber title and grey button rects straight onto it (no scrim, and the plate was rolled so both UI bands hold no foreground art); the flat navy fill survives only as the fallback when the asset is missing. All three mouse sizes come from the single `mouse_large.png` plate scaled to each slot (`mouse_small.png` / `mouse_medium.png` were byte-identical copies and are gone); `cat_tail.png` is a separate sprite driven by a load-time rotation table whose twelve wag frames are pinned at the tail stroke's base end (that end and the plate's symmetry are chosen at load time, so a re-rolled plate stays attached however its art is oriented), anchored at mid-rump height via the `TAIL_ANCHOR` knob in `renderer_assets.py`; `cloud.png` is cropped to its cloud body (key residue reaches every canvas edge, so an alpha > 0 crop would cut nothing) and matted at load time, then blitted as three drifting clouds whose slot keeps the plate's aspect — the drift/row values are the ones the old procedural circles used, so the motion is unchanged; no contact shadow is drawn under sprites. Particles, trajectory, HUD and the menu's widgets stay procedural. Four themes cycle every 5 levels: Daytime → Sunset → Night → Twilight. Night/Twilight add twinkling stars. UI scales to the real display surface.

---

## Testing

Run the test suite to validate core logic:

```powershell
python tests.py         # physics, collisions, level generation, scoring, high scores
python tests_assets.py  # asset loader: matting, sizes, caching, strips, clouds, icon, menu plate
```

The runner reports `PASS`/`FAIL` per test and exits `0` on success (`tests.py`: 18 tests, `tests_assets.py`: 22). Both run headless via pygame's `dummy` SDL driver, so no window is needed. `tests_assets.py` saves one eyeball frame to a scratch folder **outside** the repo (`<temp>/cats-vs-mice-preview/frame_playing.png`) — running the tests leaves no artifacts in the project.

The runner reports `PASS`/`FAIL` per test and exits `0` on success.

> **Note:** In a one-file build, `high_scores.json` is written into PyInstaller's temporary extraction folder and does not persist between runs. The leaderboard works normally when running the game from source (`python main.py`).

---
## Building a Standalone Executable

The game is compiled into a single-file Windows executable using **PyInstaller**, driven by the checked-in spec file `CatsVsMice.spec`.

### Build artifacts

| Path | Description |
|------|-------------|
| `CatsVsMice.spec` | PyInstaller build specification: entry point `main.py`, bundles the whole `assets/` folder as a data directory (`datas=[('assets', 'assets')]` — recursive, so every PNG under `assets/generated/` ships automatically and no per-file entries are needed), embeds `assets/generated/icon.ico` as the EXE's Windows icon (`icon=`), UPX-compressed, windowed (no console), single-file output that unpacks into PyInstaller's temporary `_MEIPASS` folder at launch |
| `tools/make_icon.py` | Build-time tool, not shipped in the EXE: crops `cat_idle.png` to its face — anchored on the measured green-eye band, ear tips to chin — composites it on the daytime plate's own sky gradient with rounded corners, and packs 16/32/48/256 PNG-compressed frames into `assets/generated/icon.ico`. Re-run it after re-rolling `cat_idle.png`: `python tools/make_icon.py` |
| `renderer_assets.py` | Asset loader/cache imported transitively (`main.py` → `renderer.py` → `renderer_assets.py`): reads the PNGs from `assets/generated/`, mattes and downscales them once per process, and resolves paths through `sys._MEIPASS` when running frozen |
| `assets/generated/` | The 15 pre-baked PNG plates/sprites generated with ComfyUI (`moss-image-sft`, one seed for the whole set), including the menu backdrop `bg_menu.png`, plus `icon.ico` built by `tools/make_icon.py`; bundled as data by the spec and shipped inside the single-file EXE. All three mouse sizes scale from the one `mouse_large.png` plate |
| `build/` | Intermediate compilation artifacts produced by PyInstaller (safe to delete; regenerated on each build) |
| `dist/CatsVsMice.exe` | The final standalone game — pygame and all project modules are bundled inside; no Python installation needed to run it |

### Rebuilding

Or from scratch (equivalent to the spec):

```powershell
pip install pyinstaller               # build-time only; the game itself needs pygame + Pillow
python tools/make_icon.py             # regenerate assets/generated/icon.ico if cat_idle.png was re-rolled
pyinstaller CatsVsMice.spec --noconfirm
```

### Running the compiled game

Double-click `dist\CatsVsMice.exe` or run it from a terminal:

```powershell
.\dist\CatsVsMice.exe
```

## Building for Linux

<a id="linux-build"></a>

The game is pure Python plus pygame, so it runs on Linux unchanged:

```bash
pip install pygame          # Pillow is needed too -- renderer_assets.py decodes PNGs with it
python3 main.py
```

To compile a standalone Linux binary, use the same spec file (it carries no Windows-only
paths; `assets/` and `icon=` resolve the same way):

```bash
python3 -m pip install pyinstaller pillow pygame
python3 tools/make_icon.py            # optional: rebuild assets/generated/icon.ico
pyinstaller CatsVsMice.spec --noconfirm
./dist/CatsVsMice                     # PyInstaller names the output after the entry point, not ".exe"
```

Three caveats worth knowing before shipping it to someone else's machine:

- **glibc:** PyInstaller bundles CPython and SDL but links against the *build host's* libc,
  so a binary built on a very new distro can fail on an older one with a `GLIBC_2.xx not found`
  error. Build on the same distro family the player uses — building on their machine is safest.
- **System libs:** pygame needs SDL2 present (`libsdl2-dev` on Debian/Ubuntu); PyInstaller does
  not install it for you.
- **The icon:** `assets/generated/icon.ico` is a Windows icon format. On Linux it is a data
  file only — window/taskbar icons come from the desktop environment, not the binary.

## Installation & Running

Requires **Python 3.12**, **pygame** and **Pillow** (`pip install pygame Pillow`). A virtual environment (`.venv`) is configured in the project; start it with `python main.py`. On Linux, see [Building for Linux](#linux-build).

---

## Controls

**Mouse:**
- **Menu:** click Play / Scoreboard / Volume (drag slider) / Quit.
- **Playing:** click near the cat to grab it, drag to aim, release to launch. Click the in-level "Restart" button to restart the current level.
- **Level complete / milestones / game over / victory / scoreboard:** click to continue or return.

**Keyboard:**
- `Esc` — quit.
- In name-input: type your name, `Backspace` to edit, `Enter` to confirm.

