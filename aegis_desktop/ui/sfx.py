# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional, very quiet interface sounds - OFF by default (Settings → «صدای ظریف»).

Five sounds, synthesised in memory (no asset files): a soft *tick* for completing a task, a two-note rising chime
when the vault opens (the brand's signature) and its mirror when it closes, a low thud with a bright ring for the day
seal, and a three-note bell at the end of a pomodoro. Playback uses ``winsound`` on Windows (stdlib,
async, nothing extra to ship); other platforms are silent. ``ENABLED`` is switched by the ``sounds`` preference.
"""
from __future__ import annotations

import io
import math
import struct
import sys
import wave

ENABLED = [False]
RATE = 22050
GAIN = 0.22                                    # everything is deliberately quiet
_cache: dict[str, bytes] = {}


def _tone(freq: float, ms: int, decay: float, gain: float = 1.0, attack_ms: int = 4) -> list[float]:
    n = int(RATE * ms / 1000)
    out = []
    for i in range(n):
        t = i / RATE
        env = min(1.0, i / max(1, RATE * attack_ms / 1000)) * math.exp(-t * decay)
        s = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t * decay * 1.6)
        out.append(gain * env * s)
    return out


def _mix(parts: list[tuple[int, list[float]]]) -> list[float]:
    """[(start_ms, samples)] -> one buffer."""
    end = max(int(RATE * st / 1000) + len(s) for st, s in parts)
    buf = [0.0] * end
    for st, s in parts:
        o = int(RATE * st / 1000)
        for i, v in enumerate(s):
            buf[o + i] += v
    return buf


def _wav(samples: list[float]) -> bytes:
    peak = max(1e-9, max(abs(x) for x in samples))
    pcm = struct.pack("<%dh" % len(samples), *[int(max(-1.0, min(1.0, x / peak * GAIN)) * 32767) for x in samples])
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return bio.getvalue()


def build(name: str) -> bytes:
    """WAV bytes of a named sound (cached). Unknown names raise KeyError."""
    if name not in _cache:
        if name == "tick":
            s = _mix([(0, _tone(1250, 70, 70)), (0, _tone(2500, 30, 160, 0.3))])
        elif name == "open":
            s = _mix([(0, _tone(523.25, 260, 9)), (110, _tone(783.99, 420, 6))])           # C5 -> G5
        elif name == "close":
            s = _mix([(0, _tone(783.99, 260, 9)), (110, _tone(523.25, 460, 6))])           # G5 -> C5: the vault shuts
        elif name == "seal":
            s = _mix([(0, _tone(196.0, 240, 12, 1.1)), (60, _tone(659.25, 620, 5, 0.7)), (200, _tone(987.77, 700, 5, 0.5))])
        elif name == "bell":
            s = _mix([(0, _tone(659.25, 500, 5)), (170, _tone(830.61, 500, 5)), (340, _tone(987.77, 800, 4))])
        else:
            raise KeyError(name)
        _cache[name] = _wav(s)
    return _cache[name]


def _emit(data: bytes) -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:                                    # a missing sound device must never break the app
        pass


def play(name: str) -> bool:
    """Play a sound if sounds are enabled. Returns True when it was handed to the player."""
    if not ENABLED[0]:
        return False
    try:
        _emit(build(name))
    except Exception:
        return False
    return True


# ------------------------------------------------------------------------------------------- the film's soundtrack ---
# One pre-mixed 20-second track for the opening film (ui/overture.py): a low pad that swells shot by shot, a soft pulse
# on the beat the film's dial moves to, a whoosh into every cut, small ticks when the demo ticks tasks, a metal clunk when
# the padlock closes and a three-note bloom at the end. It is ONE buffer because ``winsound`` plays a single sound at a
# time, so separate effects would cut each other off. It is synthesised once, in a background thread, and cached.
BPM = 75
BEAT = 60.0 / BPM
FILM_SECONDS = 20.8
FILM_GAIN = 0.34
_film: dict = {"wav": None, "busy": False}
FILM_CUTS = (3.2, 8.0, 14.0, 17.4)
FILM_TICKS = tuple(8.0 + 0.65 + 1.2 + i * 0.8 + 0.3 for i in range(4))
FILM_CLUNK = 15.75


def _env(i: int, n: int, a: float, r: float) -> float:
    """Attack/release envelope over n samples (a and r are fractions)."""
    x = i / n
    if x < a:
        return x / a
    if x > 1 - r:
        return max(0.0, (1 - x) / r)
    return 1.0


def build_film() -> bytes:
    import random
    rnd = random.Random(11)
    n = int(RATE * FILM_SECONDS)
    buf = [0.0] * n
    tau = 2 * math.pi

    def add(t0: float, samples: list[float]) -> None:
        o = int(RATE * t0)
        for i, v in enumerate(samples):
            if 0 <= o + i < n:
                buf[o + i] += v

    def pad(t0: float, dur: float, freqs: tuple, gain: float, swell: float = 0.5) -> None:
        m = int(RATE * dur)
        ph = [0.0] * len(freqs)
        inc = [tau * f / RATE for f in freqs]
        out = []
        for i in range(m):
            e = _env(i, m, swell, 0.35)
            v = 0.0
            for k in range(len(freqs)):
                ph[k] += inc[k] * (1 + 0.0015 * math.sin(i / RATE * 0.9 + k))
                v += math.sin(ph[k])
            out.append(gain * e * e * v / len(freqs))
        add(t0, out)

    pad(0.0, 3.4, (65.41, 98.0, 130.81), 0.8, 0.85)                                  # C2 G2 C3: the dark before the light
    pad(3.0, 5.2, (65.41, 98.0, 130.81, 196.0, 261.63), 0.9, 0.25)                    # the emblem
    pad(7.8, 6.4, (55.0, 110.0, 164.81, 220.0, 329.63), 0.8, 0.15)                    # product: Am
    pad(13.8, 4.0, (65.41, 98.0, 155.56, 196.0), 0.7, 0.25)                           # the lock: Cm
    pad(17.2, 3.6, (65.41, 98.0, 130.81, 164.81, 196.0, 329.63), 1.0, 0.1)            # finale: C major, open

    m = int(RATE * 3.2)                                                               # the rise into the first light
    ph, out = 0.0, []
    for i in range(m):
        x = i / m
        ph += tau * (70 + 900 * x ** 3) / RATE
        out.append(0.55 * x ** 2.2 * math.sin(ph))
    add(0.0, out)

    def boom(t0: float, gain: float) -> None:
        m = int(RATE * 1.5)
        out, ph = [], 0.0
        for i in range(m):
            tt = i / RATE
            ph += tau * (46 + 70 * math.exp(-tt * 9)) / RATE
            out.append(gain * (math.sin(ph) * math.exp(-tt * 2.6) + 0.18 * (rnd.random() * 2 - 1) * math.exp(-tt * 22)))
        add(t0, out)

    def whoosh(end: float, dur: float = 0.62, gain: float = 0.5) -> None:
        m = int(RATE * dur)
        y, out = 0.0, []
        for i in range(m):
            x = i / m
            a = 0.015 + 0.55 * x ** 2
            y += a * ((rnd.random() * 2 - 1) - y)
            out.append(gain * math.sin(math.pi * x) ** 1.5 * y)
        add(end - dur + 0.12, out)

    def chime(t0: float, f: float, gain: float, ms: int = 1400) -> None:
        add(t0, _tone(f, ms, 3.2, gain, 6))

    boom(3.2, 0.9)
    for c in FILM_CUTS[1:]:
        whoosh(c)
        boom(c, 0.28)
    whoosh(3.2, 0.9, 0.35)
    t = 3.2
    while t < 17.4:                                                                   # the pulse the dial moves to
        add(t, [0.34 * math.sin(tau * (52 + 60 * math.exp(-i / RATE * 28)) * i / RATE) * math.exp(-i / RATE * 9) for i in range(int(RATE * 0.28))])
        if t > 8.0:
            add(t + BEAT / 2, [0.05 * (rnd.random() * 2 - 1) * math.exp(-i / RATE * 90) for i in range(int(RATE * 0.05))])
        t += BEAT
    chime(4.9, 1046.5, 0.22)
    chime(5.05, 1568.0, 0.16)
    for k, tt in enumerate(FILM_TICKS):
        add(tt, _tone(1500 + 120 * k, 60, 90, 0.42))
    add(FILM_CLUNK, [0.8 * math.sin(tau * 150 * i / RATE) * math.exp(-i / RATE * 20) + 0.4 * (rnd.random() * 2 - 1) * math.exp(-i / RATE * 140)
                     for i in range(int(RATE * 0.35))])
    add(FILM_CLUNK + 0.02, _tone(3100, 90, 70, 0.3))
    chime(FILM_CLUNK + 0.2, 1318.5, 0.18, 1800)
    for k, f in enumerate((523.25, 783.99, 1046.5, 1318.5)):                          # the bloom of the finale
        chime(17.4 + 0.12 * k, f, 0.24, 2600)
    peak = max(1e-9, max(abs(x) for x in buf))
    pcm = struct.pack("<%dh" % n, *[int(max(-1.0, min(1.0, x / peak * FILM_GAIN)) * 32767) for x in buf])
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return bio.getvalue()


def prepare_film() -> None:
    """Start building the soundtrack in the background (idempotent). Windows only: elsewhere nothing could play it."""
    if sys.platform != "win32" or _film["wav"] is not None or _film["busy"]:
        return
    import threading
    _film["busy"] = True

    def work() -> None:
        try:
            _film["wav"] = build_film()
        except Exception:
            _film["wav"] = b""
        finally:
            _film["busy"] = False
    threading.Thread(target=work, daemon=True, name="aegis-film-audio").start()


def play_film() -> bool:
    if sys.platform != "win32" or not _film["wav"]:
        return False
    _emit(_film["wav"])
    return True


def stop_film() -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
