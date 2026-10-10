"""Game state machine, level progression, scoring, orchestration."""
import math
import random
from typing import List
from entities import Cat, Mouse, Block, Particle, Debris
import physics
import level_generator
import renderer
import high_scores

# --- Game State ---
class GameState:
    MENU = "menu"
    SCOREBOARD = "scoreboard"
    PLAYING = "playing"
    LEVEL_COMPLETE = "level_complete"
    MILESTONE = "milestone"
    GAME_OVER = "game_over"
    VICTORY = "victory"
    NAME_INPUT = "name_input"


class Game:
    def __init__(self):
        self.state = GameState.MENU
        self.level = 1
        self.score = 0
        self.cats_remaining = 5
        self.max_cats = 5

        # Active entities
        self.blocks: List[Block] = []
        self.mice: List[Mouse] = []
        self.particles: List[Particle] = []
        self.debris: List[Debris] = []
        self.cat: Cat = None

        # Slingshot
        self.sling_x = 315.0
        self.sling_y = 756.0

        # Aiming
        self.aiming = False
        self.drag_x = 0.0
        self.drag_y = 0.0
        self.launch_vx = 0.0
        self.launch_vy = 0.0

        # Frame counter for animations
        self.frame = 0

        # Level complete bonus tracking
        self.bonus_awarded = False

        # Milestone animation
        self.milestone_frame = 0

        # Name input state
        self.name_input = ""

    def start_level(self, level_num):
        self.level = level_num
        self.cats_remaining = self.max_cats
        self.bonus_awarded = False
        self.blocks, self.mice = level_generator.generate_level(level_num)
        self.particles = []
        self.debris = []
        self.cat = None
        self.aiming = False
        self.state = GameState.PLAYING

    def prepare_cat(self):
        """Position cat on slingshot for aiming."""
        if self.cats_remaining <= 0:
            return
        self.cat = Cat(x=self.sling_x, y=self.sling_y - 27, vx=0, vy=0)
        self.aiming = False

    def begin_drag(self, mx, my):
        """Start aiming."""
        self.aiming = True
        self.drag_x = mx
        self.drag_y = my

    def update_drag(self, mx, my):
        """Update the rubber-band handle. The cat itself stays anchored on the sling."""
        cx, cy = physics.clamp_drag(mx, my, self.sling_x, self.sling_y)
        self.drag_x = cx
        self.drag_y = cy
        # Do NOT move self.cat here: the drag point only encodes pull direction/power.

    def release_launch(self):
        """Release the cat and compute launch velocity."""
        if self.cat:
            # Launch from the pouch so every pull direction gives a clean arc.
            self.cat.x = self.sling_x
            self.cat.y = self.sling_y - 27
            dx = self.sling_x - self.drag_x
            dy = self.sling_y - self.drag_y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 5:
                self.aiming = False
                return
            vx, vy = physics.compute_launch(dx, dy)
            self.cat.vx = vx
            self.cat.vy = vy
            self.cat.launched = True
            self.cat.active = True
            self.cat.first_hit = False
            self.cat.life_after_hit = 0
            self.cats_remaining -= 1
            self.aiming = False
            # Audio
            try:
                import audio
                audio.audio_mgr.play("meow")
            except Exception:
                pass

    def update_physics(self):
        """One fixed-timestep physics update."""
        if self.cat and self.cat.launched and self.cat.active:
            cat = self.cat
            # Gravity
            cat.vy += physics.GRAVITY
            # Friction
            cat.vx *= physics.FRICTION
            # Move
            cat.x += cat.vx
            cat.y += cat.vy

            # Ground collision
            if cat.y + cat.radius >= physics.GROUND_Y:
                cat.y = physics.GROUND_Y - cat.radius
                cat.vx, cat.vy = physics.ground_bounce(cat.vx, cat.vy)
                if not cat.first_hit:
                    cat.first_hit = True
                    cat.life_after_hit = physics.STOP_TIME
                self._spawn_impact_particles(cat.x, cat.y + cat.radius, (100, 80, 40))

            # Field bounds
            if cat.x < physics.FIELD_LEFT or cat.x > physics.FIELD_RIGHT:
                cat.active = False
                return

            # Block collisions
            for blk in self.blocks:
                if not blk.alive:
                    continue
                hit, nx, ny, pen = physics.circle_rect_collision(
                    cat.x, cat.y, cat.radius, blk.x, blk.y, blk.w, blk.h)
                if hit:
                    # Separate
                    cat.x += nx * pen
                    cat.y += ny * pen
                    # Damage
                    strength = physics.impact_strength(cat.vx, cat.vy)
                    damage = max(1, int(strength / 8))
                    blk.hp -= damage
                    # Bounce
                    cat.vx, cat.vy = physics.resolve_bounce(
                        cat.vx, cat.vy, nx, ny, physics.BOUNCE_DAMP)
                    if not cat.first_hit:
                        cat.first_hit = True
                        cat.life_after_hit = physics.STOP_TIME
                    # Particles
                    self._spawn_impact_particles(cat.x, cat.y,
                        (180, 100, 50) if blk.material == "wood" else (150, 150, 160))
                    # Sound
                    try:
                        import audio
                        if blk.hp <= 0:
                            audio.audio_mgr.play("crunch" if blk.material == "stone" else "thud")
                        else:
                            audio.audio_mgr.play("thud")
                    except Exception:
                        pass
                    if blk.hp <= 0:
                        blk.alive = False
                        self._spawn_destruction_particles(blk)
                        if blk.material == "stone":
                            self._spawn_stone_debris(blk)

            # Mouse collisions
            for mouse in self.mice:
                if not mouse.alive:
                    continue
                hit, nx, ny, pen = physics.circle_circle_collision(
                    cat.x, cat.y, cat.radius, mouse.x, mouse.y, mouse.radius)
                if hit:
                    cat.x += nx * pen
                    cat.y += ny * pen
                    strength = physics.impact_strength(cat.vx, cat.vy)
                    damage = 2 if strength > physics.STRONG_HIT_THRESHOLD else 1
                    mouse.hp -= damage
                    cat.vx, cat.vy = physics.resolve_bounce(
                        cat.vx, cat.vy, nx, ny, physics.BOUNCE_DAMP)
                    if not cat.first_hit:
                        cat.first_hit = True
                        cat.life_after_hit = physics.STOP_TIME
                    self._spawn_impact_particles(mouse.x, mouse.y, (255, 200, 100))
                    if mouse.hp <= 0:
                        mouse.alive = False
                        if mouse.size == 2:
                            self.cats_remaining = min(self.cats_remaining + 1, self.max_cats)
                        self._spawn_destruction_particles_mouse(mouse)
                        try:
                            import audio
                            audio.audio_mgr.play("squeak")
                        except Exception:
                            pass
                    else:
                        try:
                            import audio
                            audio.audio_mgr.play("ouch")
                        except Exception:
                            pass

            # Stop condition
            speed = math.sqrt(cat.vx * cat.vx + cat.vy * cat.vy)
            if cat.first_hit:
                cat.life_after_hit -= 1
                if cat.life_after_hit <= 0:
                    cat.active = False
            if speed < physics.STOP_SPEED and cat.y + cat.radius >= physics.GROUND_Y - 1:
                cat.active = False

    def update_falling_mice(self):
        """Check support and apply falling gravity."""
        for mouse in self.mice:
            if not mouse.alive:
                continue
            # Check support
            supported = False
            r = mouse.radius
            # Check if on ground
            if mouse.y + r >= physics.GROUND_Y - 1:
                mouse.y = physics.GROUND_Y - r
                supported = True
            else:
                # Check blocks below
                for blk in self.blocks:
                    if not blk.alive:
                        continue
                    if (mouse.x - r < blk.x + blk.w and
                        mouse.x + r > blk.x and
                        mouse.y + r >= blk.y - 2 and
                        mouse.y + r <= blk.y + 5):
                        mouse.y = blk.y - r
                        supported = True
                        break
            if not supported:
                mouse.falling = True
                mouse.y += physics.GRAVITY * 0.6

    def update_debris(self):
        """Update debris: fall, bounce, damage mice, expire."""
        for d in self.debris:
            d.vy += physics.GRAVITY * 0.5
            d.vx *= 0.98
            d.x += d.vx
            d.y += d.vy
            # Ground bounce
            if d.y + d.radius >= physics.GROUND_Y:
                d.y = physics.GROUND_Y - d.radius
                d.vy = -d.vy * 0.3
                d.vx *= 0.7
            # Damage mice
            for mouse in self.mice:
                if not mouse.alive:
                    continue
                hit, _, _, _ = physics.circle_circle_collision(
                    d.x, d.y, d.radius, mouse.x, mouse.y, mouse.radius)
                if hit:
                    mouse.hp -= 3
                    if mouse.hp <= 0:
                        mouse.alive = False
                        if mouse.size == 2:
                            self.cats_remaining = min(self.cats_remaining + 1, self.max_cats)
            d.life -= 1
        self.debris = [d for d in self.debris if d.life > 0]

    def update_particles(self):
        """Update particles: gravity, expire."""
        for p in self.particles:
            p.vy += physics.GRAVITY * 0.3
            p.x += p.vx
            p.y += p.vy
            p.life -= 1
        self.particles = [p for p in self.particles if p.life > 0]

    def check_level_complete(self):
        """Check if all mice are eliminated."""
        if self.bonus_awarded:
            return
        if all(not m.alive for m in self.mice):
            self.bonus_awarded = True
            bonus = 1000 + 500 * self.cats_remaining
            is_challenge = (self.level % 5 == 0)
            if is_challenge:
                bonus += 2000
            self.score += bonus
            self.state = GameState.LEVEL_COMPLETE
            self._completion_level = self.level
            self._completion_bonus = bonus
            self._completion_challenge = is_challenge

    def check_game_over(self):
        """Check if cats exhausted and mice alive."""
        if self.cats_remaining <= 0 and self.cat is not None and not self.cat.active:
            alive_mice = [m for m in self.mice if m.alive]
            if alive_mice:
                self.state = GameState.GAME_OVER

    def _spawn_impact_particles(self, x, y, color):
        for _ in range(6):
            angle = random.random() * 2 * math.pi
            speed = 2 + random.random() * 4
            self.particles.append(Particle(
                x=x, y=y,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed,
                life=20, max_life=20,
                color=color, size=5))

    def _spawn_destruction_particles(self, blk):
        cx = blk.x + blk.w / 2
        cy = blk.y + blk.h / 2
        col = (180, 100, 50) if blk.material == "wood" else (150, 150, 160)
        for _ in range(10):
            angle = random.random() * 2 * math.pi
            speed = 3 + random.random() * 5
            self.particles.append(Particle(
                x=cx, y=cy,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed,
                life=35, max_life=35,
                color=col, size=7))

    def _spawn_stone_debris(self, blk):
        cx = blk.x + blk.w / 2
        cy = blk.y + blk.h / 2
        for _ in range(4):
            angle = random.random() * 2 * math.pi
            speed = 2 + random.random() * 3
            self.debris.append(Debris(
                x=cx, y=cy,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed - 3,
                size=11, life=120, max_life=120,
                color=(140, 140, 150)))

    def _spawn_destruction_particles_mouse(self, mouse):
        cx, cy = mouse.x, mouse.y
        for _ in range(8):
            angle = random.random() * 2 * math.pi
            speed = 2 + random.random() * 4
            self.particles.append(Particle(
                x=cx, y=cy,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed,
                life=25, max_life=25,
                color=(255, 200, 100), size=5))