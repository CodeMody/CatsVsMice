"""Main entry point: pygame init, game loop, state dispatch."""
import sys
import math
import pygame
import game as _game_mod
import renderer as _renderer_mod
import high_scores as _hs_mod
import audio as _audio_mod

# Constants
SCREEN_W = 1920
SCREEN_H = 1080
FPS = 60
TIMESTEP = 1.0 / FPS


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Cats vs Mice")
    clock = pygame.time.Clock()
    _audio_mod.audio_mgr.ensure_ready()

    game = _game_mod.Game()
    rend = _renderer_mod.Renderer(screen)

    running = True
    state = game.state

    # Volume slider state
    vol_value = 0.5

    # Name input buffer
    name_buf = ""

    while running:
        dt = clock.tick(FPS)
        game.frame += 1

        # --- Events (quit) — must run before any state-dispatch continue ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            if event.type == pygame.KEYDOWN and game.state == _game_mod.GameState.NAME_INPUT:
                if event.key == pygame.K_RETURN:
                    _hs_mod.add_score(name_buf, game.score)
                    game.score = 0
                    game.level = 1
                    name_buf = ""
                    game.state = _game_mod.GameState.MENU
                elif event.key == pygame.K_BACKSPACE:
                    name_buf = name_buf[:-1]
                elif event.key is not None and 32 <= event.key < 127:
                    name_buf = (name_buf + chr(event.key))[:12]
        if not running:
            break

        # --- Input ---
        mouse_pos = pygame.mouse.get_pos()
        mouse_down = pygame.mouse.get_pressed()[0]

        # Handle state-specific input
        if game.state == _game_mod.GameState.MENU:
            _handle_menu_input(game, rend, mouse_pos, mouse_down, clock)
            rend.draw_menu(game.frame)
            pygame.display.flip()
            continue

        if game.state == _game_mod.GameState.SCOREBOARD:
            _handle_scoreboard_input(game, rend, mouse_pos, mouse_down)
            scores = _hs_mod.load_scores()
            rend.draw_scoreboard(scores)
            pygame.display.flip()
            continue

        if game.state == _game_mod.GameState.LEVEL_COMPLETE:
            if mouse_down:
                # Advance (any click on the screen works)
                _advance_level(game, rend)
            rend.draw_background(game.level, game.frame)
            rend.draw_completion(game._completion_level, game._completion_bonus,
                                 game._completion_challenge)
            pygame.display.flip()
            continue

        if game.state == _game_mod.GameState.MILESTONE:
            game.milestone_frame += 1
            rend.draw_background(game.level, game.frame)
            rend.draw_milestone(game.milestone_frame)
            if game.milestone_frame > 180:
                # The milestone is an intro for game.level (already set by _advance_level),
                # so start THAT level — advancing again would skip it.
                game.start_level(game.level)
            pygame.display.flip()
            continue

        if game.state == _game_mod.GameState.GAME_OVER:
            if mouse_down and _in_rect(mouse_pos, 548, 540, 823, 108):
                # Save score then restart
                _save_and_restart(game, rend, name_buf)
            rend.draw_game_over(game.score)
            pygame.display.flip()
            continue

        if game.state == _game_mod.GameState.VICTORY:
            if mouse_down and _in_rect(mouse_pos, 548, 540, 823, 108):
                _save_and_restart(game, rend, name_buf)
            rend.draw_victory(game.score, game.frame)
            pygame.display.flip()
            continue

        if game.state == _game_mod.GameState.NAME_INPUT:
            rend.draw_background(game.level, game.frame)
            rend.draw_name_prompt(game.score, name_buf)
            pygame.display.flip()
            continue

        # --- PLAYING state ---
        if game.state == _game_mod.GameState.PLAYING:
            # Restart button (matches the rect drawn by draw_hud)
            rsx, rsy = SCREEN_W / 1920.0, SCREEN_H / 1080.0
            restart_clicked = mouse_down and _in_rect(
                mouse_pos,
                SCREEN_W - int(137 * rsx), SCREEN_H - int(90 * rsy),
                int(110 * rsx), int(54 * rsy))
            if restart_clicked:
                game.start_level(game.level)   # same layout, cats restored
                pygame.display.flip()
                continue

            # Check if cat is ready
            if game.cat is None or (game.cat.launched and not game.cat.active):
                if game.cats_remaining > 0:
                    game.prepare_cat()

            # Aiming logic
            if game.cat and not game.cat.launched:
                cat_x, cat_y = game.sling_x, game.sling_y - 27
                dist_to_cat = math.sqrt((mouse_pos[0] - cat_x)**2 + (mouse_pos[1] - cat_y)**2)
                if mouse_down and dist_to_cat < 72:
                    game.begin_drag(mouse_pos[0], mouse_pos[1])
                if game.aiming and mouse_down:
                    game.update_drag(mouse_pos[0], mouse_pos[1])
                if game.aiming and not mouse_down:
                    game.release_launch()

            # Physics
            game.update_physics()
            game.update_falling_mice()
            game.update_debris()
            game.update_particles()
            game.check_level_complete()
            game.check_game_over()

            # --- Render ---
            theme_level = game.level
            rend.draw_background(theme_level, game.frame)
            band = (game.drag_x, game.drag_y) if game.aiming else None
            rend.draw_sling(game.sling_x, game.sling_y, band)

            # Trajectory preview
            if game.aiming and game.cat:
                dx = game.sling_x - game.drag_x
                dy = game.sling_y - game.drag_y
                vx, vy = _game_mod.physics.compute_launch(dx, dy)
                if vx != 0 or vy != 0:
                    rend.draw_trajectory(game.cat.x, game.cat.y, vx, vy)

            # Draw blocks
            for blk in game.blocks:
                rend.draw_block(blk)

            # Draw mice
            theme = _renderer_mod.get_theme(game.level)
            for mouse in game.mice:
                rend.draw_mouse(mouse, theme, game.frame)

            # Draw cat
            if game.cat:
                rend.draw_cat(game.cat, theme, idle=not game.cat.launched, frame=game.frame)

            # Draw particles & debris
            rend.draw_particles(game.particles)
            rend.draw_debris(game.debris)

            # HUD
            rend.draw_hud(game.score, game.level, game.cats_remaining, game.frame)
            if game.cat and not game.cat.launched:
                rend.draw_aim_instruction(game.frame)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


def _handle_menu_input(game, rend, mouse_pos, mouse_down, clock):
    """Handle menu clicks. Uses a simple debounce via clock delay."""
    if not mouse_down:
        return
    sx, sy = SCREEN_W / 1920.0, SCREEN_H / 1080.0
    bw, bh = int(274 * sx), int(72 * sy)
    # Must match renderer.Renderer._menu_buttons, which draws buttons at x=795.
    bx = int(795 * sx)

    def btn(y0):
        return (bx, int(y0 * sy) - int(18 * sy), bw, bh)

    # "Play" button area
    if _in_rect(mouse_pos, *btn(450)):
        game.state = _game_mod.GameState.PLAYING
        game.start_level(1)
        return
    # Scoreboard
    if _in_rect(mouse_pos, *btn(558)):
        game.state = _game_mod.GameState.SCOREBOARD
        return
    # Volume: drag a slider, value is read/written through the audio manager
    if _in_rect(mouse_pos, *btn(666)):
        v = (mouse_pos[0] - bx) / bw
        try:
            _audio_mod.audio_mgr.set_volume(v)
        except Exception:
            pass
        return
    # Quit
    if _in_rect(mouse_pos, *btn(774)):
        pygame.quit()
        import sys
        sys.exit()


def _handle_scoreboard_input(game, rend, mouse_pos, mouse_down):
    sx, sy = SCREEN_W / 1920.0, SCREEN_H / 1080.0
    bw, bh = int(274 * sx), int(72 * sy)
    bx = SCREEN_W // 2 - bw // 2
    if mouse_down and _in_rect(mouse_pos, bx, int(780 * sy), bw, bh):
        game.state = _game_mod.GameState.MENU


def _advance_level(game, rend):
    """Advance to next level or trigger milestone/victory."""
    next_level = game.level + 1
    if next_level > 50:
        game.state = _game_mod.GameState.VICTORY
        return
    if next_level % 10 == 0:
        game.state = _game_mod.GameState.MILESTONE
        game.milestone_frame = 0
        game.level = next_level
        return
    game.start_level(next_level)


def _save_and_restart(game, rend, name_buf):
    """Ask for a name if this run makes the top-5, otherwise return to the menu."""
    if game.score > 0 and _hs_mod.qualifies("Player", game.score):
        game.state = _game_mod.GameState.NAME_INPUT
        return
    if game.score > 0:
        try:
            _hs_mod.add_score("Player", game.score)
        except Exception:
            pass
    game.score = 0
    game.level = 1
    game.state = _game_mod.GameState.MENU


def _in_rect(pos, rx, ry, rw, rh):
    return rx <= pos[0] <= rx + rw and ry <= pos[1] <= ry + rh


if __name__ == "__main__":
    main()