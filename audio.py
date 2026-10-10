"""Optional procedural audio. Never crashes the game."""
import math
import struct
import array
from pathlib import Path
from typing import List

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

_audio_enabled = True
_volume = 0.5  # 0.0 - 1.0

# Pre-generated background music: a real file in the project, loaded as-is.
MUSIC_FILE = Path("assets") / "ambient_loop.wav"


def generate_sound(channels: List[float], sample_rate=22050) -> bytes:
    """Convert channel data to WAV bytes."""
    samples = []
    for ch in channels:
        val = int(max(-1.0, min(1.0, ch)) * 32767)
        samples.append(val)
    raw = struct.pack(f"<{len(samples)}h", *samples)
    # WAV header
    data_size = len(raw)
    header = b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
    header += b"fmt " + struct.pack("<I", 16)
    header += struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", data_size)
    return header + raw


def _meow(duration=0.15):
    """Short playful meow."""
    sr = 22050
    n = int(sr * duration)
    ch = []
    for i in range(n):
        t = i / sr
        freq = 800 + 400 * math.sin(t * 20)
        env = math.sin(math.pi * t / duration)
        ch.append(env * 0.3 * math.sin(2 * math.pi * freq * t))
    return ch


def _thud():
    """Block impact thud."""
    sr = 22050
    n = int(sr * 0.08)
    ch = []
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 30)
        ch.append(env * 0.4 * math.sin(2 * math.pi * 150 * t))
    return ch


def _crunch():
    """Stone destruction."""
    sr = 22050
    n = int(sr * 0.12)
    ch = []
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 20)
        freq = 200 + 300 * (1 - t / 0.12)
        ch.append(env * 0.35 * math.sin(2 * math.pi * freq * t))
    return ch


def _squeak():
    """Mouse squeak."""
    sr = 22050
    n = int(sr * 0.1)
    ch = []
    for i in range(n):
        t = i / sr
        env = math.sin(math.pi * t / 0.1)
        freq = 2000 + 1000 * math.sin(t * 40)
        ch.append(env * 0.25 * math.sin(2 * math.pi * freq * t))
    return ch


def _whoosh():
    """Projectile whoosh."""
    sr = 22050
    n = int(sr * 0.1)
    ch = []
    for i in range(n):
        t = i / sr
        env = math.sin(math.pi * t / 0.1)
        ch.append(env * 0.15 * math.sin(2 * math.pi * 600 * t))
    return ch


def _ouch():
    """Short 'ouch' yelp when a mouse is hit."""
    sr = 22050
    n = int(sr * 0.18)
    ch = []
    for i in range(n):
        t = i / sr
        prog = t / 0.18
        freq = 620 - 260 * prog
        env = math.sin(math.pi * min(1.0, prog * 1.4)) * math.exp(-t * 8)
        v = env * 0.35 * math.sin(2 * math.pi * freq * t)
        v += 0.15 * env * math.sin(2 * math.pi * (freq * 2.7) * t)
        ch.append(v)
    return ch


def _find_music():
    """First audio file in assets/, preferring ambient_loop.wav."""
    assets = Path(__file__).resolve().parent / "assets"
    if not assets.is_dir():
        return None
    preferred = assets / MUSIC_FILE.name
    if preferred.exists():
        return preferred
    for ext in (".ogg", ".wav"):
        found = sorted(assets.glob(f"*{ext}"))
        if found:
            return found[0]
    return None


class AudioManager:
    def __init__(self):
        self.sounds = {}
        self.music_channel = None

    def ensure_ready(self):
        """(Re)build sounds; call this AFTER pygame.init(), otherwise the mixer isn't up yet."""
        if not _PYGAME_AVAILABLE or self.sounds:
            return
        try:
            import pygame
            self.sounds["meow"] = pygame.mixer.Sound(generate_sound(_meow()))
            self.sounds["thud"] = pygame.mixer.Sound(generate_sound(_thud()))
            self.sounds["crunch"] = pygame.mixer.Sound(generate_sound(_crunch()))
            self.sounds["squeak"] = pygame.mixer.Sound(generate_sound(_squeak()))
            self.sounds["whoosh"] = pygame.mixer.Sound(generate_sound(_whoosh()))
            self.sounds["ouch"] = pygame.mixer.Sound(generate_sound(_ouch()))
        except Exception:
            self.sounds = {}
            return
        try:
            music_path = _find_music()
            if music_path is None:
                raise FileNotFoundError("no music file in assets/")
            m = pygame.mixer.Sound(str(music_path))
            self.sounds["music"] = m
            m.set_volume(_volume * 0.25)
            m.play(loops=-1)
        except Exception:
            self.sounds.pop("music", None)

    def play(self, name):
        if not _PYGAME_AVAILABLE or not self.sounds:
            return
        try:
            if name in self.sounds and name != "music":
                self.sounds[name].set_volume(_volume * 0.6)
                self.sounds[name].play()
        except Exception:
            pass

    def set_volume(self, v):
        global _volume
        _volume = max(0.0, min(1.0, v))
        if self.sounds.get("music"):
            try:
                self.sounds["music"].set_volume(_volume * 0.25)
            except Exception:
                pass

    def get_volume(self):
        """Current master volume, so the menu can read the real value back."""
        return _volume


# Singleton
audio_mgr = AudioManager()