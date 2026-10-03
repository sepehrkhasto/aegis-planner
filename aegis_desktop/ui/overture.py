# SPDX-License-Identifier: GPL-3.0-or-later
"""«Overture»: the cinematic opening shown every time the app starts, before the password form. About twenty seconds.

One widget, one painter, one clock. A timeline ``t`` (seconds) decides what is on screen, in four shots and a finale:

     0 - 3.2   ignite   a point of light, an anamorphic streak, a bezel that draws itself, dust that converges
     3.2 - 8   emblem   the mark turns in 3D over a mirror floor, god-rays, the wordmark letter by letter
     8 - 14    product  five glass panels float in perspective and play their own little stories
    14 - 17.4  lock     a metal padlock closes, three promises
    17.4 -     finale   emblem, wordmark and the «ورود» button with a light running around it

Every cut is hidden by a light sweep; letterbox bars, film grain, vignette, dust and bokeh run through all of it.
On top of that: a slow camera dolly with mouse parallax, depth of field with a rack focus between the glass panels, light
that runs along their edges, a lens flare when the emblem glints, physical sparks, a pre-mixed soundtrack (ui/sfx.py) whose
beat the dial moves to, the colours of the active theme, a different dust and camera drift on every launch, 120 fps on fast
screens and an automatic quality drop on slow ones, and an iris out of the film when «ورود» is pressed.
It is skippable at any moment (a clear button, Enter, Space, Esc). With «reduce motion» only the final frame is shown.
It never touches the vault: it is pure decoration, so it is safe to show before unlocking.
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QCursor, QFont, QFontMetricsF, QGuiApplication, QImage, QKeyEvent,
                         QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform)
from PyQt6.QtWidgets import QPushButton, QWidget

from ..core import jalali
from ..core.jalali import fa
from . import sfx, theme
from .themes_data import _mix
from .brand import display_font, metal, paint_mark

SHOTS = (("ignite", 0.0, 3.2), ("emblem", 3.2, 8.0), ("product", 8.0, 14.0), ("lock", 14.0, 17.4))
CUTS = (3.2, 8.0, 14.0, 17.4)
T_CTA = 17.4
T_TOTAL = 20.0

SKIP_CSS = """QPushButton{background:rgba(255,255,255,0.16);color:#ffffff;border:1px solid rgba(255,255,255,0.55);
border-radius:18px;padding:7px 22px;font-weight:700;font-size:13px;}
QPushButton:hover{background:rgba(255,255,255,0.32);border-color:#ffffff;}
QPushButton:pressed{background:rgba(255,255,255,0.45);}"""

LEAVE_S = 0.55
SLOGAN = "برنامه‌ات، فقط مال خودت"
TASKS = ("پیش‌نویس گزارش هفتگی", "جلسه با استاد", "ورزش صبحگاهی", "مرور درس شبکه")
SIDEBAR = ("امروز", "تسک‌ها", "تقویم", "کانبان", "یادداشت‌ها", "عادت‌ها", "گزارش‌ها")


def clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def seg(t: float, a: float, b: float) -> float:
    return clamp((t - a) / (b - a))


def ease_out(x: float) -> float:
    return 1 - (1 - x) ** 3


def ease_in(x: float) -> float:
    return x * x * x


def ease_io(x: float) -> float:
    return x * x * (3 - 2 * x)


def ease_back(x: float) -> float:
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def shot_at(t: float) -> tuple[str, float, float]:
    for name, a, b in SHOTS:
        if a <= t < b:
            return name, a, b
    return ("end", T_CTA, T_TOTAL + 999.0)


class Overture(QWidget):
    entered = pyqtSignal()

    def __init__(self, parent=None, speed: float = 1.0, seed: int | None = None):
        super().__init__(parent)
        self.speed = speed
        self.seed = random.randrange(1 << 30) if seed is None else seed          # a different dust and camera drift each launch
        self.sound = False                                                        # set from the «overture_sound» preference
        self.quality = 2                                                          # 2 full · 1 no depth of field/extrusion · 0 bare
        self._ema = 0.016
        self._slow = 0
        self._last = 0.0
        self._mx = self._my = 0.0
        self._pal: dict | None = None
        self._pal_key = ""
        self._leaving = False
        self._leave_clock = QElapsedTimer()
        self.t = 0.0
        self._fixed: float | None = None
        self._clock = QElapsedTimer()
        self._base = 0.0
        self._timer = QTimer(self, interval=16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._bg: QPixmap | None = None
        self._bg_key = (0, 0)
        self._marks: dict[int, tuple[QPixmap, QPixmap, QPixmap]] = {}
        self._grain = self._make_grain()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)
        from .widgets import button
        self.skip_btn = QPushButton("رد کردن  ·  Esc", self)
        self.skip_btn.setStyleSheet(SKIP_CSS)
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.setMinimumHeight(36)
        self.skip_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_btn.clicked.connect(self._enter)
        self.go_btn = button("ورود به برنامه", "Primary", self._enter)
        self.go_btn.setParent(self)
        self.go_btn.setMinimumHeight(48)
        self.go_btn.setMinimumWidth(240)
        self.go_btn.hide()
        self._done = False

    @property
    def pal(self) -> dict:
        key = theme.THEME[0]
        if self._pal is None or key != self._pal_key:
            self._pal, self._pal_key = self._film_pal(key), key
            self._bg = None
            self._marks = {}
        return self._pal

    @staticmethod
    def _film_pal(key: str) -> dict:
        """The film is always a night scene wearing the active theme's colours: a dark theme is used as it is, a day theme
        is turned into a dark base tinted with its accent."""
        t = theme.THEMES.get(key) or theme.THEMES[theme.SIGNATURE]
        pal = dict(t["pal"])
        if t["mode"] == "light":
            a = pal["accent"]
            bg = _mix("#050506", a, 0.09)
            pal.update(bg=bg, panel=_mix(bg, a, 0.10), panel2=_mix(bg, a, 0.18), line=_mix(bg, a, 0.28), edge=_mix(bg, a, 0.34),
                       soft=_mix(bg, a, 0.22), text="#f4f4f6", muted=_mix("#f4f4f6", bg, 0.42), accent=_mix(a, "#ffffff", 0.30),
                       accent2=_mix(pal["accent2"], "#ffffff", 0.40), hi=_mix(a, "#ffffff", 0.58), ink="#0a0a0c",
                       acc_text=_mix(a, "#ffffff", 0.55), danger="#ef6b73", warn="#e5a94a", ok="#5fcf9c")
        return pal

    @staticmethod
    def _make_grain() -> QPixmap:
        rnd = random.Random(7)
        raw = bytes(rnd.randrange(256) for _ in range(128 * 128))
        img = QImage(raw, 128, 128, 128, QImage.Format.Format_Grayscale8).copy()
        return QPixmap.fromImage(img)

    # ------------------------------------------------------------ clock ---
    def start(self) -> None:
        from . import anim
        self._done = False
        if not anim.MOTION[0]:
            self.set_time(T_CTA + 3.0)
            return
        self._fixed = None
        self._base = 0.0
        self._leaving = False
        self._clock.start()
        self._timer.setInterval(self._frame_ms())
        self._timer.start()
        self.setFocus()
        if self.sound:
            sfx.play_film()

    def _frame_ms(self) -> int:
        scr = self.screen() or QGuiApplication.primaryScreen()
        rate = scr.refreshRate() if scr else 60.0
        rate = rate if 20.0 <= rate <= 400.0 else 60.0
        return max(8, int(1000.0 / min(rate, 120.0)))                              # up to 120 fps on a fast screen

    def stop(self) -> None:
        self._timer.stop()
        sfx.stop_film()

    def set_time(self, t: float) -> None:
        """Freeze the film at ``t`` seconds (reduce-motion shows the last frame; tests render single frames)."""
        self._timer.stop()
        self._fixed = t
        self.t = t
        self._sync_buttons()
        self.update()

    def _tick(self) -> None:
        now = self._clock.elapsed() / 1000.0
        dt = now - self._last
        self._last = now
        if 0 < dt < 0.5:                                                           # slow machine: drop effects, never frames
            self._ema += (dt - self._ema) * 0.1
            budget = self._timer.interval() / 1000.0
            self._slow = self._slow + 1 if self._ema > max(0.026, budget * 1.7) else 0
            if self._slow > 30 and self.quality > 0:
                self.quality -= 1
                self._slow, self._ema = 0, 0.016
        if self._fixed is None:
            self.t = self._base + now * self.speed
            pos = self.mapFromGlobal(QCursor.pos())
            tx = (pos.x() / max(1, self.width()) - 0.5) * 2 if self.rect().contains(pos) else 0.0
            ty = (pos.y() / max(1, self.height()) - 0.5) * 2 if self.rect().contains(pos) else 0.0
            self._mx += (max(-1.0, min(1.0, tx)) - self._mx) * 0.06
            self._my += (max(-1.0, min(1.0, ty)) - self._my) * 0.06
        if self._leaving and self._leave_clock.elapsed() / 1000.0 >= LEAVE_S:
            self._timer.stop()
            self._leaving = False
            self.entered.emit()
            return
        self._sync_buttons()
        self.update()

    def _enter(self) -> None:
        if self._done:
            return
        self._done = True
        sfx.stop_film()
        if self._fixed is None and self._timer.isActive():                       # animated: iris out of the film, then hand over
            self._leaving = True
            self._leave_clock.start()
            return
        self._timer.stop()
        self.entered.emit()

    def _sync_buttons(self) -> None:
        show = self.t >= T_CTA + 0.9
        show = show and not self._leaving
        if show != self.go_btn.isVisible():
            self.go_btn.setVisible(show)
            if show:
                self.go_btn.setFocus()
        self.skip_btn.setVisible(self.t < T_CTA + 0.9 and not self._leaving)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if self._fixed is None and not self._timer.isActive() and not self._done:
            self._clock.start()
            self._timer.start()

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        sfx.stop_film()
        super().hideEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self._enter()
            return
        super().keyPressEvent(e)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.skip_btn.adjustSize()
        self.skip_btn.move(24, max(10, int(self.height() * 0.0375) - self.skip_btn.height() // 2 + 4))
        self.go_btn.adjustSize()
        self.go_btn.move(int((self.width() - self.go_btn.width()) / 2), int(self.height() * 0.76))

    # --------------------------------------------------------- helpers ---
    @property
    def _f(self) -> float:
        return max(0.35, min(2.2, min(self.width() / 1280.0, self.height() / 800.0)))

    def _cy(self, t: float) -> float:
        return self.height() * (0.40 - 0.08 * ease_io(seg(t, T_CTA, T_CTA + 0.8)))

    def C(self, name: str, a: float = 1.0) -> QColor:
        c = QColor(self.pal[name])
        c.setAlphaF(clamp(a))
        return c

    def _chip(self, key: str, a: float = 1.0) -> QColor:
        p = self.pal
        c = QColor({"c1": p["accent2"], "c2": p["ok"], "c3": p["warn"], "c4": p["hi"], "c5": p["danger"]}[key])
        c.setAlphaF(clamp(a))
        return c

    @staticmethod
    def _dp(p: QPainter, path) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    @staticmethod
    def _glow(p: QPainter, cx: float, cy: float, r: float, col: QColor, a: float) -> None:
        if a <= 0.004 or r <= 0:
            return
        g = QRadialGradient(cx, cy, r)
        c0, c1 = QColor(col), QColor(col)
        c0.setAlphaF(clamp(a))
        c1.setAlphaF(0)
        g.setColorAt(0, c0)
        g.setColorAt(1, c1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r, r)

    # --------------------------------------------------------- painting ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        t = self.t
        name, a, _b = shot_at(t)
        s = t - a
        zoom, dx, dy, roll = self._camera(t)
        self._paint_bg(p, t, dx, dy)
        p.save()
        c = QPointF(self.width() / 2, self.height() * 0.45)
        p.translate(c.x() + dx, c.y() + dy)
        p.rotate(roll)
        p.scale(zoom, zoom)
        p.translate(-c.x(), -c.y())
        self._paint_rays(p, t)
        self._paint_rings(p, t)
        {"ignite": self._shot_ignite, "emblem": self._shot_emblem, "product": self._shot_product,
         "lock": self._shot_lock, "end": self._shot_finale}[name](p, t, s)
        if self.quality >= 1:
            self._paint_bokeh(p, t)
        p.restore()
        if self._leaving:
            self._paint_leave(p)
        self._paint_cut(p, t)
        if self.quality >= 1:
            self._paint_grain(p, t)
        self._paint_letterbox(p, t)

    # ---- camera: a slow dolly-in over the whole film, a seeded hand-held drift, parallax from the mouse
    def _camera(self, t: float) -> tuple[float, float, float, float]:
        f = self._f
        sd = (self.seed % 628) / 100.0
        zoom = 1.0 + 0.05 * clamp(t / T_CTA) + 0.004 * math.sin(t * 0.6 + sd)
        dx = (math.sin(t * 0.31 + sd) * 7 - self._mx * 16) * f
        dy = (math.cos(t * 0.23 + sd * 1.7) * 5 - self._my * 10) * f
        roll = 0.35 * math.sin(t * 0.17 + sd) * (1 if (self.seed >> 3) & 1 else -1)
        return zoom, dx, dy, roll

    def _paint_leave(self, p: QPainter) -> None:
        """«ورود»: the emblem's light floods the frame and the film dissolves into the login background."""
        k = clamp(self._leave_clock.elapsed() / 1000.0 / LEAVE_S)
        cx, cy = self.width() / 2, self._cy(self.t)
        self._glow(p, cx, cy, max(self.width(), self.height()) * (0.2 + 1.3 * ease_in(k)), QColor(255, 246, 226), 0.9 * ease_in(k))
        p.fillRect(self.rect(), self.C("bg", clamp((k - 0.45) / 0.55)))

    # ---- background: black glass, warm key light, dust in depth
    def _paint_bg(self, p: QPainter, t: float, dx: float = 0.0, dy: float = 0.0) -> None:
        w, h = self.width(), self.height()
        if self._bg is None or self._bg_key != (w, h):
            pm = QPixmap(w, h)
            q = QPainter(pm)
            q.fillRect(0, 0, w, h, self.C("bg"))
            g = QRadialGradient(w / 2, h * 0.40, max(w, h) * 0.7)
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 235))
            q.fillRect(0, 0, w, h, g)
            q.end()
            self._bg, self._bg_key = pm, (w, h)
        p.drawPixmap(0, 0, self._bg)
        k = 0.10 + 0.04 * math.sin(t * 0.8)
        self._glow(p, w / 2, h * 0.40, max(w, h) * 0.55, self.C("accent"), k)
        p.setPen(Qt.PenStyle.NoPen)
        sd = self.seed % 1000
        for i in range(64 if self.quality >= 1 else 22):                         # dust, three depths, a new field every launch
            depth = 0.35 + (i % 3) * 0.3
            seed = ((i + sd) * 7919) % 1000 / 1000.0
            x = (((i + sd) * 977) % 1000) / 1000.0 * w + math.sin(t * 0.25 * depth + i) * 22 * depth + dx * depth * 1.6
            y = (1.0 - ((seed + t * 0.014 * depth) % 1.0)) * h + dy * depth * 1.6
            a = (0.08 + 0.22 * (0.5 + 0.5 * math.sin(t * 1.1 + i * 1.7))) * depth
            p.setBrush(self.C("hi" if i % 4 else "accent2", a))
            r = (0.7 + (i % 4) * 0.45) * depth * self._f
            p.drawEllipse(QPointF(x, y), r, r)

    def _paint_bokeh(self, p: QPainter, t: float) -> None:
        w, h = self.width(), self.height()
        for i in range(7):
            x = (((i * 331) % 1000) / 1000.0 * w + math.sin(t * 0.18 + i * 2.1) * 60) % w
            y = (1.0 - ((i * 0.17 + t * 0.012) % 1.0)) * h
            r = (46 + (i % 3) * 30) * self._f
            self._glow(p, x, y, r, self.C("hi"), 0.05 + 0.03 * math.sin(t + i))

    # ---- light rays behind the emblem
    def _paint_rays(self, p: QPainter, t: float) -> None:
        a = seg(t, 3.4, 4.6) * (1 - seg(t, 7.3, 8.1)) if t < 9 else (seg(t, 14.3, 15.3) * 0.7 if t >= 14.0 else 0.0)
        if a <= 0.01:
            return
        cx, cy = self.width() / 2, self._cy(t)
        R = max(self.width(), self.height()) * 0.8
        p.save()
        p.translate(cx, cy)
        p.rotate(t * 2.4)
        g = QRadialGradient(0, 0, R)
        g.setColorAt(0, self.C("hi", 0.2 * a))
        g.setColorAt(0.6, self.C("accent2", 0.05 * a))
        g.setColorAt(1, self.C("accent2", 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        for i in range(14 if self.quality >= 1 else 8):
            ang = i * (360.0 / (14 if self.quality >= 1 else 8))
            path = QPainterPath()
            path.moveTo(0, 0)
            half = 3.2 + 1.8 * math.sin(i * 1.7)
            path.lineTo(R * math.cos(math.radians(ang - half)), R * math.sin(math.radians(ang - half)))
            path.lineTo(R * math.cos(math.radians(ang + half)), R * math.sin(math.radians(ang + half)))
            path.closeSubpath()
            p.drawPath(path)
        p.restore()

    # ---- the bezel: rings and ticks, drawn like a watch dial
    def _paint_rings(self, p: QPainter, t: float) -> None:
        if t < 8.4:
            a = 1 - seg(t, 7.3, 8.2)
        elif t >= 14.0:
            a = seg(t, 14.2, 15.0) * 0.8
        else:
            a = 0.0
        if a <= 0.01:
            return
        rp = ease_io(seg(t, 1.0, 2.8)) if t < 8.4 else 1.0
        cx, cy = self.width() / 2, self._cy(t)
        H = self.height() * (1 + 0.012 * self._beat(t))                              # the dial breathes on the soundtrack's beat
        for r_k, wd, dash, spin in ((0.245, 1.6, False, 6.0), (0.215, 1.0, False, -9.0), (0.31, 1.0, True, 2.5)):
            R = H * r_k
            pen = QPen(self.C("hi", 0.7 * a), wd * self._f)
            if dash:
                pen.setStyle(Qt.PenStyle.CustomDashLine)
                pen.setDashPattern([2, 9])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            start = int((90 + t * spin) * 16)
            p.drawArc(QRectF(cx - R, cy - R, 2 * R, 2 * R), start, int(-360 * 16 * rp))
        R = H * 0.228
        p.save()
        p.translate(cx, cy)
        p.rotate(-t * 4)
        for i in range(72):
            if i / 72.0 > rp:
                break
            major = i % 6 == 0
            ln = (H * 0.016) if major else (H * 0.008)
            p.setPen(QPen(self.C("hi" if major else "accent2", (0.85 if major else 0.5) * a), (1.6 if major else 1.0) * self._f))
            ang = math.radians(i * 5)
            p.drawLine(QPointF(math.cos(ang) * R, math.sin(ang) * R), QPointF(math.cos(ang) * (R + ln), math.sin(ang) * (R + ln)))
        p.restore()

    @staticmethod
    def _beat(t: float) -> float:
        """1 on a beat of the soundtrack, decaying to 0 (the pulse starts with the emblem)."""
        if t < 3.2 or t > T_CTA + 2.5:
            return 0.0
        return math.exp(-((t - 3.2) % sfx.BEAT) * 7.0)

    # ---- transitions and film dressing
    def _paint_cut(self, p: QPainter, t: float) -> None:
        for c in CUTS:
            d = t - c
            if -0.14 < d < 0.42:
                k = (d + 0.14) / 0.56
                w = self.width()
                x = w * (1.55 * k - 0.27)
                a = math.sin(math.pi * k)
                g = QLinearGradient(x - 150 * self._f, 0, x + 150 * self._f, 0)
                g.setColorAt(0, QColor(255, 255, 255, 0))
                g.setColorAt(0.5, self.C("hi", 0.32 * a))
                g.setColorAt(1, QColor(255, 255, 255, 0))
                p.fillRect(self.rect(), g)
                return

    def _paint_grain(self, p: QPainter, t: float) -> None:
        p.save()
        p.setOpacity(0.10)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Overlay)
        ox, oy = int(t * 997) % 128, int(t * 577) % 128
        for x in range(-ox, self.width(), 128):
            for y in range(-oy, self.height(), 128):
                p.drawPixmap(x, y, self._grain)
        p.restore()

    def _paint_letterbox(self, p: QPainter, t: float) -> None:
        bar = self.height() * 0.075 * (1 - ease_io(seg(t, T_CTA + 0.2, T_CTA + 1.0))) * ease_out(seg(t, 0.0, 0.8))
        if bar > 0.5:
            p.fillRect(QRectF(0, 0, self.width(), bar), QColor(0, 0, 0))
            p.fillRect(QRectF(0, self.height() - bar, self.width(), bar), QColor(0, 0, 0))
        if t < T_CTA:
            p.fillRect(QRectF(0, self.height() - 2, self.width() * clamp(t / T_CTA), 2), self.C("hi", 0.8))

    # ---- shot 1: ignite
    def _shot_ignite(self, p: QPainter, t: float, s: float) -> None:
        w, h = self.width(), self.height()
        cx, cy = w / 2, self._cy(t)
        f = self._f
        k = ease_out(seg(s, 0.2, 1.0))
        self._glow(p, cx, cy, (8 + 150 * k) * f, QColor(255, 244, 214), 0.95 * k * (1 - 0.5 * seg(s, 2.0, 3.0)))
        st = ease_out(seg(s, 0.5, 1.6))
        fade = 1 - seg(s, 2.2, 3.0)
        if st > 0 and fade > 0:
            ln = w * 0.48 * st
            g = QLinearGradient(cx - ln, 0, cx + ln, 0)
            g.setColorAt(0, self.C("hi", 0))
            g.setColorAt(0.5, QColor(255, 246, 224, int(255 * fade)))
            g.setColorAt(1, self.C("hi", 0))
            p.fillRect(QRectF(cx - ln, cy - 1.3 * f, 2 * ln, 2.6 * f), g)
            g2 = QLinearGradient(cx - ln, 0, cx + ln, 0)
            g2.setColorAt(0, self.C("accent2", 0))
            g2.setColorAt(0.5, self.C("accent2", 0.35 * fade))
            g2.setColorAt(1, self.C("accent2", 0))
            p.fillRect(QRectF(cx - ln, cy - 9 * f, 2 * ln, 18 * f), g2)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(70):                                                    # dust falls into the light
            ang = (i * 2.399963) % math.tau
            r0 = (0.25 + 0.75 * (((i * 53) % 100) / 100.0)) * h * 0.55
            kk = ease_in(seg(s, 1.5 + (i % 10) * 0.04, 3.0))
            if kk >= 1 or kk <= 0:
                continue
            rr = r0 * (1 - kk)
            p.setBrush(self.C("hi", 0.85 * (1 - kk * 0.4)))
            p.drawEllipse(QPointF(cx + math.cos(ang + kk * 2.0) * rr, cy + math.sin(ang + kk * 2.0) * rr * 0.62),
                          (1.0 + (i % 3) * 0.6) * f, (1.0 + (i % 3) * 0.6) * f)
        fl = seg(s, 2.85, 3.2)
        if fl > 0:
            self._glow(p, cx, cy, max(w, h) * (0.3 + 0.6 * fl), QColor(255, 246, 226), 0.9 * fl)

    # ---- the emblem (cached) with a 3D turn and a mirror floor
    def _mark_pms(self, size: int) -> tuple[QPixmap, QPixmap, QPixmap]:
        got = self._marks.get(size)
        if got is None:
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_mark(q, QRectF(0, 0, size, size), self.pal)
            q.end()
            refl = QPixmap(pm)
            q = QPainter(refl)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            g = QLinearGradient(0, 0, 0, size)
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 110))
            q.fillRect(0, 0, size, size, g)
            q.end()
            dark = QPixmap(pm)                                                  # the side of the metal, for the extrusion
            q = QPainter(dark)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            q.fillRect(0, 0, size, size, QColor(0, 0, 0, 150))
            q.end()
            got = (pm, refl, dark)
            self._marks = {size: got}
        return got

    def _emblem(self, p: QPainter, cx: float, cy: float, size: float, yaw: float, alpha: float, glint: float = -1.0,
                scale: float = 1.0, mirror: float = 1.0) -> None:
        sz = max(48, int(size))
        pm, refl, dark = self._mark_pms(sz)
        depth = sz * 0.07 * abs(math.sin(math.radians(yaw)))
        slices = int(depth / 1.6) if self.quality >= 1 else 0
        for flip in ((1, -1) if mirror > 0.02 else (1,)):
            if flip == 1:                                                       # real thickness: slices of darker metal behind the face
                for k in range(slices, 0, -1):
                    p.save()
                    tr = QTransform()
                    tr.translate(cx - math.copysign(k * depth / max(1, slices), yaw) * scale, cy)
                    tr.rotate(yaw, Qt.Axis.YAxis, 1100.0)
                    tr.scale(scale, scale)
                    tr.translate(-sz / 2, -sz / 2)
                    p.setWorldTransform(tr, True)
                    p.setOpacity(clamp(alpha))
                    p.drawPixmap(0, 0, dark)
                    p.restore()
            p.save()
            tr = QTransform()
            tr.translate(cx, cy if flip == 1 else cy + sz * 0.5 * scale + sz * 0.5 * scale + 6)
            tr.rotate(yaw, Qt.Axis.YAxis, 1100.0)
            tr.scale(scale, scale * flip)
            tr.translate(-sz / 2, -sz / 2)
            p.setWorldTransform(tr, True)
            p.setOpacity(clamp(alpha) * (1.0 if flip == 1 else clamp(mirror)))
            if flip == 1:
                img = pm
                if 0.0 <= glint <= 1.0:
                    img = QPixmap(pm)
                    q = QPainter(img)
                    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                    gx = -sz * 0.4 + sz * 1.8 * glint
                    g = QLinearGradient(gx - sz * 0.18, 0, gx + sz * 0.18, 0)
                    g.setColorAt(0, QColor(255, 255, 255, 0))
                    g.setColorAt(0.5, QColor(255, 255, 255, 170))
                    g.setColorAt(1, QColor(255, 255, 255, 0))
                    q.fillRect(0, 0, sz, sz, g)
                    q.end()
                p.drawPixmap(0, 0, img)
            else:
                p.drawPixmap(0, 0, refl)
            p.restore()

    def _flare(self, p: QPainter, x: float, y: float, k: float, cx: float, cy: float) -> None:
        """Anamorphic lens flare at the glint (x, y): a horizontal streak, a soft core and ghosts mirrored through the centre."""
        if k <= 0.01:
            return
        f = self._f
        w = self.width()
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        ln = w * 0.32 * k
        g = QLinearGradient(x - ln, 0, x + ln, 0)
        g.setColorAt(0, self.C("accent2", 0))
        g.setColorAt(0.5, QColor(255, 244, 220, int(210 * k)))
        g.setColorAt(1, self.C("accent2", 0))
        p.fillRect(QRectF(x - ln, y - 1.3 * f, 2 * ln, 2.6 * f), g)
        self._glow(p, x, y, 34 * f * (0.6 + k), QColor(255, 246, 226), 0.8 * k)
        for i, (m, r, a) in enumerate(((0.55, 26, 0.16), (1.0, 14, 0.2), (1.45, 40, 0.1), (1.9, 20, 0.12))):
            gx, gy = cx + (cx - x) * m * 0.8, cy + (cy - y) * m * 0.8
            col = self.C("accent2" if i % 2 else "hi")
            self._glow(p, gx, gy, r * f, col, a * k)
            p.setPen(QPen(self.C("hi", 0.25 * k), 1.0 * f))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(gx, gy), r * 0.55 * f, r * 0.55 * f)
        p.restore()

    def _sparks(self, p: QPainter, t: float, t0: float, x0: float, y0: float, n: int, speed: float, life: float, up: float = 0.0) -> None:
        """A burst with real ballistics: x = x0 + vx·τ, y = y0 + vy·τ + ½gτ² (gravity down), fading, drawn as short motion trails.
        Deterministic in t (no state), so scrubbing or skipping can never leave particles behind."""
        tau = t - t0
        if tau <= 0 or tau >= life or self.quality < 1:
            return
        f = self._f
        g = 900.0 * f
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for i in range(n):
            r1 = ((i * 2654435761 + self.seed) % 1000) / 1000.0
            r2 = ((i * 40503 + self.seed * 7) % 1000) / 1000.0
            ang = r1 * math.tau
            v = speed * f * (0.35 + 0.65 * r2)
            vx, vy = math.cos(ang) * v, math.sin(ang) * v - up * f
            x, y = x0 + vx * tau, y0 + vy * tau + 0.5 * g * tau * tau
            a = (1 - tau / life) ** 1.5
            tx, ty = x - vx * 0.035, y - (vy + g * tau) * 0.035
            col = self.C("hi" if i % 3 else "accent2", a)
            p.setPen(QPen(col, (1.2 + 1.2 * r2) * f, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(tx, ty), QPointF(x, y))
        p.restore()

    def _wordmark(self, p: QPainter, cx: float, y: float, px: float, s: float, t0: float, text: str = "AEGIS", gap_k: float = 0.34) -> None:
        f = display_font(max(24.0, px), True, 0)
        fm = QFontMetricsF(f)
        gap = px * gap_k
        advs = [fm.horizontalAdvance(c) for c in text]
        total = sum(advs) + gap * (len(text) - 1)
        grad = metal(QPointF(cx - total / 2, y), QPointF(cx + total / 2, y + px * 1.2), self.pal)
        p.save()
        p.setFont(f)
        p.setPen(QPen(QBrush(grad), 1))
        x = cx - total / 2
        for i, ch in enumerate(text):
            k = seg(s, t0 + 0.13 * i, t0 + 0.13 * i + 0.7)
            if k > 0:
                p.setOpacity(ease_out(k))
                p.drawText(QPointF(x, y + px * 0.92 + (1 - ease_out(k)) * px * 0.28), ch)
            x += advs[i] + gap
        p.restore()
        line_k = ease_out(seg(s, t0 + 0.9, t0 + 1.9))
        if line_k > 0:
            ly = y + px * 0.55
            ln = (total * 0.45) * line_k
            for sign in (-1, 1):
                x0 = cx + sign * (total / 2 + px * 0.5)
                g = QLinearGradient(x0, 0, x0 + sign * ln, 0)
                g.setColorAt(0, self.C("hi", 0.8))
                g.setColorAt(1, self.C("hi", 0))
                p.fillRect(QRectF(min(x0, x0 + sign * ln), ly, ln, 1.2 * self._f), g)

    def _tagline(self, p: QPainter, cx: float, y: float, s: float, t0: float) -> None:
        k = ease_out(seg(s, t0, t0 + 0.9))
        if k <= 0:
            return
        f = self._f
        fn = QFont("Inter")
        fn.setPixelSize(max(10, int(13 * f)))
        fn.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 7 * f)
        p.setFont(fn)
        p.setPen(self.C("hi", 0.9 * k))
        p.drawText(QRectF(0, y, self.width(), 24 * f), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "PLANNER")
        fp = QFont(self.font())
        fp.setPixelSize(max(11, int(15 * f)))
        p.setFont(fp)
        p.setPen(self.C("muted", k * clamp((s - t0 - 0.3) / 0.6)))
        p.drawText(QRectF(0, y + 28 * f, self.width(), 26 * f), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   "برنامه‌ریز شخصی رمزنگاری‌شده")

    # ---- shot 2: emblem
    def _shot_emblem(self, p: QPainter, t: float, s: float) -> None:
        w, h = self.width(), self.height()
        cx, cy = w / 2, self._cy(t)
        f = self._f
        fl = (1 - seg(s, 0.0, 0.35)) ** 2
        if fl > 0:
            self._glow(p, cx, cy, max(w, h) * 0.55, QColor(255, 246, 226), 0.6 * fl)
        size = h * 0.25
        spin = ease_out(seg(s, 0.0, 1.9))
        yaw = -88 * (1 - spin) + math.sin(s * 0.9) * 5 * seg(s, 1.9, 2.6)
        out = seg(s, 4.3, 4.8)
        scale = (0.78 + 0.22 * ease_out(seg(s, 0, 1.4))) * (1 + 0.12 * out)
        self._glow(p, cx, cy, size * 1.5, self.C("accent"), 0.5 * seg(s, 0.2, 1.4) * (1 - out))
        gl = seg(s, 1.7, 2.7) if 1.7 < s < 2.7 else -1.0
        self._emblem(p, cx, cy, size, yaw, ease_out(seg(s, 0, 0.8)) * (1 - out), glint=gl, scale=scale, mirror=1 - seg(s, 1.2, 1.9))
        if gl >= 0:
            self._flare(p, cx - size * 0.4 + size * 1.8 * gl - size * 0.5 + size * 0.0, cy - size * 0.18, math.sin(math.pi * gl) ** 1.5, cx, cy)
        p.save()
        p.setOpacity(1 - out)
        self._wordmark(p, cx, cy + size * 0.62 + 18 * f, h * 0.085, s, 1.5)
        self._tagline(p, cx, cy + size * 0.62 + h * 0.085 * 1.5 + 18 * f, s, 3.1)
        p.restore()

    # ---- shot 3: five glass panels in perspective
    def _card_face(self, p: QPainter, w: float, h: float, draw, t: float, idx: int, light: float) -> None:
        body = QPainterPath()
        body.addRoundedRect(QRectF(0, 0, w, h), 18, 18)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, self.C("panel2", 0.98))
        g.setColorAt(1, self.C("panel", 0.98))
        p.fillPath(body, QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.2))
        self._dp(p, body)
        cg = QConicalGradient(QPointF(w / 2, h / 2), (t * 38 + idx * 71) % 360)       # a light that runs around the glass edge
        cg.setColorAt(0.0, QColor(255, 255, 255, int(235 * light)))
        cg.setColorAt(0.10, self.C("hi", 0.55 * light))
        cg.setColorAt(0.26, QColor(255, 255, 255, 0))
        cg.setColorAt(0.62, QColor(255, 255, 255, 0))
        cg.setColorAt(0.74, self.C("accent2", 0.35 * light))
        cg.setColorAt(0.80, QColor(255, 255, 255, 0))
        cg.setColorAt(1.0, QColor(255, 255, 255, int(235 * light)))
        p.setPen(QPen(QBrush(cg), 1.9))
        self._dp(p, body)
        p.save()
        p.setClipPath(body)
        top = QLinearGradient(0, 0, 0, h * 0.35)                                       # the sheen of glass catching the key light
        top.setColorAt(0, QColor(255, 255, 255, int(26 * light)))
        top.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, h * 0.35), top)
        sh = ((t * 0.22 + idx * 0.31) % 1.8 - 0.4)
        gx = w * sh
        sg = QLinearGradient(gx - 70, 0, gx + 70, 0)
        sg.setColorAt(0, QColor(255, 255, 255, 0))
        sg.setColorAt(0.5, QColor(255, 255, 255, 22))
        sg.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(0, 0, w, h), sg)
        draw(p, w, h)
        p.restore()

    def _card(self, p: QPainter, cx: float, cy: float, w: float, h: float, rx: float, ry: float, sc: float, alpha: float,
              draw, t: float, idx: int, blur: float = 0.0) -> None:
        """One floating glass panel. ``blur`` (0..1) is the depth of field: a blurred panel is painted small and scaled up
        with smoothing - one cheap pass instead of a real blur filter."""
        if alpha <= 0.01:
            return
        f = self._f
        S = sc * f
        p.save()
        shadow = QRadialGradient(cx, cy + h * S * 0.62, w * S * 0.75)
        shadow.setColorAt(0, QColor(0, 0, 0, int(150 * alpha)))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(cx - w * S, cy + h * S * 0.2, 2 * w * S, h * S * 0.9), shadow)
        tr = QTransform()
        tr.translate(cx, cy)
        tr.rotate(rx, Qt.Axis.XAxis, 1200.0)
        tr.rotate(ry, Qt.Axis.YAxis, 1200.0)
        tr.scale(S, S)
        tr.translate(-w / 2, -h / 2)
        p.setWorldTransform(tr, True)
        sharp = 1.0 - blur
        p.setOpacity(clamp(alpha) * (0.62 + 0.38 * sharp))
        if blur > 0.12 and self.quality >= 2:
            res = max(0.22, 1.0 - 0.8 * blur) * min(1.0, S * 1.1)
            pw, ph = max(8, int(w * res)), max(8, int(h * res))
            pm = QPixmap(pw, ph)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            q.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            q.scale(pw / w, ph / h)
            self._card_face(q, w, h, draw, t, idx, 0.3 + 0.7 * sharp)
            q.end()
            p.drawPixmap(QRectF(0, 0, w, h), pm, QRectF(0, 0, pw, ph))
        else:
            self._card_face(p, w, h, draw, t, idx, 0.3 + 0.7 * sharp)
        p.restore()

    def _txt(self, p: QPainter, r: QRectF, text: str, px: float, col: QColor, bold: bool = False, align=None) -> None:
        f = QFont(self.font())
        f.setPixelSize(max(6, int(px)))
        f.setBold(bold)
        p.setFont(f)
        p.setPen(col)
        p.drawText(r, align or (Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute), text)

    def _c_dash(self, p: QPainter, w: float, h: float, s: float) -> None:
        for i, col in enumerate(("danger", "warn", "ok")):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.C(col, 0.9))
            p.drawEllipse(QPointF(18 + i * 16, 16), 4.5, 4.5)
        side = QRectF(w - 112, 34, 100, h - 46)
        p.setBrush(self.C("panel", 0.9))
        p.drawRoundedRect(side, 10, 10)
        for i, name in enumerate(SIDEBAR):
            on = i == (int(s * 0.7) % len(SIDEBAR))
            r = QRectF(side.left() + 6, side.top() + 8 + i * 30, side.width() - 12, 24)
            if on:
                p.setBrush(self.C("accent", 0.28))
                p.drawRoundedRect(r, 7, 7)
            self._txt(p, r.adjusted(0, 0, -8, 0), name, 11.5, self.C("acc_text" if on else "muted"))
        j = jalali.today_jalali()
        self._txt(p, QRectF(0, 34, w - 124, 34), f"{fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]}", 20, self.C("text"), True)
        stats = (("امروز", 5, " تسک"), ("عادت‌ها", 86, "٪"), ("تمرکز", 120, " دقیقه"))
        tw = (w - 124 - 28) / 3
        for i, (lab, val, unit) in enumerate(stats):
            k = ease_out(seg(s, 0.4 + i * 0.15, 1.6 + i * 0.15))
            r = QRectF(12 + i * (tw + 8), 76, tw, 62)
            p.setBrush(self.C("panel", 0.9))
            p.setPen(QPen(self.C("line", 0.8), 1))
            p.drawRoundedRect(r, 10, 10)
            self._txt(p, r.adjusted(0, 6, -10, 0), lab, 10.5, self.C("muted"), False, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
            self._txt(p, r.adjusted(0, 0, -10, -6), f"{fa(int(val * k))}{unit}", 19, self.C("text"), True, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
        chart = QRectF(12, 148, (w - 124) * 0.58, h - 160)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(14):
            k = ease_out(seg(s, 0.9 + i * 0.05, 1.9 + i * 0.05))
            bh = (0.25 + 0.6 * abs(math.sin(i * 1.3 + 0.4))) * (chart.height() - 10) * k
            bw = chart.width() / 14
            p.setBrush(self.C("hi" if i % 4 == 0 else "accent2", 0.9))
            p.drawRoundedRect(QRectF(chart.left() + i * bw + 2, chart.bottom() - bh, bw * 0.62, bh), 2.5, 2.5)
        lst = QRectF(chart.right() + 12, 148, (w - 124) - chart.width() - 12 - 4, h - 160)
        for i in range(4):
            k = ease_out(seg(s, 1.0 + i * 0.2, 1.8 + i * 0.2))
            y = lst.top() + i * (lst.height() / 4.2)
            p.setBrush(self.C("line", 0.9 * k))
            p.drawRoundedRect(QRectF(lst.right() - (lst.width() - 22) * (0.6 + 0.35 * ((i * 37) % 10) / 10) * k, y + 4, (lst.width() - 22) * (0.6 + 0.35 * ((i * 37) % 10) / 10) * k, 7), 3.5, 3.5)
            p.setBrush(self._chip(f"c{i % 5 + 1}", 0.95 * k))
            p.drawEllipse(QPointF(lst.left() + 8, y + 7.5), 4.5, 4.5)

    def _c_calendar(self, p: QPainter, w: float, h: float, s: float) -> None:
        j = jalali.today_jalali()
        jy, jm = j["jy"], j["jm"]
        self._txt(p, QRectF(0, 10, w - 16, 28), f"{jalali.MONTHS_FA[jm - 1]} {fa(jy)}", 16, self.C("text"), True)
        first = jalali.weekday_index(jalali._jymd_to_date(jy, jm, 1))
        days = jalali.month_length(jy, jm)
        rows = math.ceil((first + days) / 7)
        cw, ch = (w - 24) / 7, (h - 56) / rows
        hop = (int(s * 1.6) % days) + 1
        for d in range(1, days + 1):
            pos = first + d - 1
            r_, c_ = divmod(pos, 7)
            k = ease_back(seg(s, 0.2 + pos * 0.015, 0.6 + pos * 0.015))
            if k <= 0:
                continue
            cell = QRectF(w - 12 - (c_ + 1) * cw + 2, 44 + r_ * ch + 2, cw - 4, ch - 4)
            c0 = cell.center()
            half = (cw - 4) / 2 * clamp(k)
            on = d == hop
            if on:
                p.setBrush(self.C("accent", 0.4))
                p.setPen(QPen(self.C("hi", 0.9), 1.2))
            else:
                p.setBrush(self.C("panel", 0.9))
                p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(c0.x() - half, c0.y() - half * (ch / cw), half * 2, half * 2 * (ch / cw)), 6, 6)
            self._txt(p, cell, fa(d), 10, self.C("acc_text" if on or d == j["jd"] else "muted", clamp(k)), False, Qt.AlignmentFlag.AlignCenter)
            if d in (3, 9, 15, 21):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._chip(f"c{d % 5 + 1}", clamp(k)))
                p.drawEllipse(QPointF(c0.x(), cell.bottom() - 4), 2.4, 2.4)

    def _c_tasks(self, p: QPainter, w: float, h: float, s: float) -> None:
        done = sum(1 for i in range(len(TASKS)) if s > 1.2 + i * 0.8 + 0.4)
        self._txt(p, QRectF(0, 10, w - 16, 28), "امروز", 16, self.C("text"), True)
        self._txt(p, QRectF(16, 10, 100, 28), f"{fa(done)} از {fa(len(TASKS))}", 11.5, self.C("muted"), False, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.C("line", 0.9))
        p.drawRoundedRect(QRectF(16, 44, w - 32, 6), 3, 3)
        prog = sum(ease_out(seg(s, 1.2 + i * 0.8, 1.2 + i * 0.8 + 0.4)) for i in range(len(TASKS))) / len(TASKS)
        p.setBrush(self.C("ok"))
        p.drawRoundedRect(QRectF(w - 16 - (w - 32) * prog, 44, (w - 32) * prog, 6), 3, 3)
        fm = QFontMetricsF(self.font())
        for i, title in enumerate(TASKS):
            k = ease_out(seg(s, 0.3 + i * 0.15, 0.9 + i * 0.15))
            if k <= 0:
                continue
            y = 60 + i * 41
            r = QRectF(12, y + (1 - k) * 12, w - 24, 34)
            p.setBrush(self.C("panel", 0.9 * k))
            p.setPen(QPen(self.C("line", 0.8 * k), 1))
            p.drawRoundedRect(r, 9, 9)
            tk = ease_out(seg(s, 1.2 + i * 0.8, 1.2 + i * 0.8 + 0.4))
            box = QRectF(r.right() - 30, r.center().y() - 9, 18, 18)
            p.setPen(QPen(self.C("ok" if tk > 0.3 else "muted", k), 1.6))
            p.setBrush(self.C("ok", clamp(tk * 1.5)) if tk > 0 else Qt.BrushStyle.NoBrush)
            p.drawEllipse(box)
            if tk > 0.3:
                kk = seg(tk, 0.3, 1.0)
                pa = QPainterPath()
                pa.moveTo(box.left() + 4.5, box.center().y() + 0.5)
                pa.lineTo(box.left() + 8, box.center().y() + 4)
                pa.lineTo(box.left() + 13.5, box.center().y() - 3.8)
                sp = QPainterPath()
                for q in range(int(16 * kk) + 1):
                    pt = pa.pointAtPercent(q / 16)
                    sp.moveTo(pt) if q == 0 else sp.lineTo(pt)
                p.setPen(QPen(self.C("ink"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                self._dp(p, sp)
            fp = QFont(self.font())
            fp.setPixelSize(12)
            fm = QFontMetricsF(fp)
            self._txt(p, r.adjusted(34, 0, -38, 0), title, 12, self.C("text" if tk < 0.5 else "muted", k))
            if tk > 0:
                tw = fm.horizontalAdvance(title)
                p.setPen(QPen(self.C("muted", 0.9), 1.3))
                p.drawLine(QPointF(r.right() - 38, r.center().y()), QPointF(r.right() - 38 - tw * tk, r.center().y()))

    def _c_habits(self, p: QPainter, w: float, h: float, s: float) -> None:
        self._txt(p, QRectF(0, 10, w - 16, 28), "عادت‌ها", 16, self.C("text"), True)
        d = min(w, h) * 0.5
        ring = QRectF((w - d) / 2, 46, d, d)
        k = ease_out(seg(s, 0.5, 3.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.C("line"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring.adjusted(6, 6, -6, -6), 0, 360 * 16)
        p.setPen(QPen(self.C("ok"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring.adjusted(6, 6, -6, -6), 90 * 16, int(-360 * 16 * 0.86 * k))
        self._txt(p, ring, f"{fa(int(86 * k))}٪", d * 0.26, self.C("text"), True, Qt.AlignmentFlag.AlignCenter)
        for i in range(7):
            kk = ease_back(seg(s, 1.0 + i * 0.28, 1.5 + i * 0.28))
            cx = w - 24 - i * ((w - 48) / 6.0)
            half = 9 * clamp(0.4 + 0.6 * kk)
            on = i not in (2, 5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._chip("c4", 0.95) if on else self.C("line", 0.9))
            if kk > 0:
                p.drawRoundedRect(QRectF(cx - half, h - 44 - half, half * 2, half * 2), 5, 5)
        self._txt(p, QRectF(0, h - 30, w - 16, 24), f"{fa(int(12 * ease_out(seg(s, 1.0, 3.6))))} روز پیاپی", 11.5, self.C("hi"))

    def _c_focus(self, p: QPainter, w: float, h: float, s: float) -> None:
        self._txt(p, QRectF(0, 10, w - 16, 26), "تمرکز", 15, self.C("text"), True)
        d = h * 0.62
        ring = QRectF(w - d - 20, 46, d, d)
        remain = max(0, 25 * 60 - int(s * 38))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.C("line"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring.adjusted(5, 5, -5, -5), 0, 360 * 16)
        p.setPen(QPen(self.C("hi"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring.adjusted(5, 5, -5, -5), 90 * 16, int(-360 * 16 * remain / 1500.0))
        self._txt(p, ring, fa(f"{remain // 60:02d}:{remain % 60:02d}"), d * 0.2, self.C("text"), True, Qt.AlignmentFlag.AlignCenter)
        self._txt(p, QRectF(16, 56, w - d - 44, 28), "جلسه‌ی ۲۵ دقیقه‌ای", 11, self.C("muted"), False, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)

    _FOCUS = ((0.0, 0.0), (2.0, 0.0), (2.7, 1.0), (3.5, 1.0), (4.2, 2.0), (4.9, 2.0), (5.4, 3.0), (6.1, 3.0))

    def _focus_at(self, s: float) -> float:
        """Which panel the lens is focused on, as a continuous index: the rack focus glides from one to the next."""
        pts = self._FOCUS
        if s <= pts[0][0]:
            return pts[0][1]
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if s <= t1:
                return v0 + (v1 - v0) * ease_io(seg(s, t0, t1))
        return pts[-1][1]

    def _slogan(self, p: QPainter, s: float) -> None:
        """The headline: revealed by a wipe with a bright front (Persian joins its letters, so it is never split into glyphs)."""
        k = ease_out(seg(s, 0.15, 1.7))
        fade = 1 - seg(s, 5.0, 5.7)
        if k <= 0.001 or fade <= 0.001:
            return
        h, w = self.height(), self.width()
        f = QFont(self.font())
        f.setPixelSize(max(18, int(h * 0.062)))
        f.setBold(True)
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(SLOGAN) + 8
        x1 = w / 2 + tw / 2
        x0 = x1 - tw * k
        y = h * 0.115
        r = QRectF(w / 2 - tw / 2, y, tw, fm.height() * 1.3)
        p.save()
        p.setClipRect(QRectF(x0, y - 20, x1 - x0 + 2, fm.height() * 2))
        p.setOpacity(fade)
        p.setFont(f)
        p.setPen(QPen(QBrush(metal(QPointF(r.left(), y), QPointF(r.right(), y + fm.height()), self.pal)), 1))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, SLOGAN)
        p.restore()
        if k < 0.995:                                                                  # the light at the wipe's edge, with a trail
            g = QLinearGradient(x0, 0, x0 + 90 * self._f, 0)
            g.setColorAt(0, QColor(255, 246, 226, int(120 * fade)))
            g.setColorAt(1, QColor(255, 246, 226, 0))
            p.fillRect(QRectF(x0, y, 90 * self._f, fm.height() * 1.25), g)
            self._glow(p, x0, y + fm.height() * 0.6, 40 * self._f, QColor(255, 246, 226), 0.6 * fade)

    def _shot_product(self, p: QPainter, t: float, s: float) -> None:
        w, h = self.width(), self.height()
        f = self._f
        cx0, cy0 = w / 2, h / 2 + 18 * f
        yaw = -15 + 26 * ease_io(seg(s, 0.0, 6.0))
        out = seg(s, 5.4, 6.0)
        self._slogan(p, s)
        cards = (
            (0, 560, 350, self._c_dash, (0, -10), 0.7 * yaw, 6.0, 1.22, 0.0, 0.0),
            (1, 300, 270, self._c_calendar, (-440, -78), 20 + 0.35 * yaw, 4.0, 0.98, 0.35, -90),
            (2, 300, 250, self._c_tasks, (440, -62), -20 + 0.35 * yaw, 4.0, 0.98, 0.65, 90),
            (3, 250, 250, self._c_habits, (-330, 196), 14 + 0.3 * yaw, -4.0, 0.9, 1.0, -70),
            (4, 270, 175, self._c_focus, (350, 208), -14 + 0.3 * yaw, -4.0, 0.9, 1.3, 70))
        fcs = self._focus_at(s)
        order = sorted(cards, key=lambda c: c[7])
        tasks_pos = None
        for idx, cw, ch, fn, (ox, oy), ry, rx, sc, t0, fly in order:
            k = ease_out(seg(s, t0, t0 + 1.1))
            bob = math.sin(t * 1.25 + idx * 1.3) * 5 * f
            par = -yaw * (2.2 + idx * 0.4) * f * (0.0 if idx == 0 else 1.0)
            cx = cx0 + ox * f + fly * (1 - k) * f + par
            cy = cy0 + oy * f + bob + (1 - k) * 30 * f
            focus = clamp(1.0 - abs(fcs - idx))
            blur = 0.85 * (1.0 - focus) ** 0.8 * (0.65 if idx == 0 else 1.0) * k
            scl = sc * (0.7 + 0.3 * k) * (1 + 0.05 * out) * (1 + 0.045 * focus)
            ry_ = ry + (1 - k) * (-30 if fly < 0 else 30 if fly > 0 else 0)
            self._card(p, cx, cy, cw, ch, rx, ry_, scl, k * (1 - out),
                       lambda pp, ww, hh, fn=fn: fn(pp, ww, hh, max(0.0, s - t0)), t, idx, blur)
            if idx == 2:
                tasks_pos = (cx, cy, scl * f, ry_, cw, ch, t0)
        if tasks_pos:                                                                   # a small burst each time a task is ticked
            cx, cy, S, ry_, cw, ch, t0 = tasks_pos
            cs = math.cos(math.radians(ry_))
            for i in range(len(TASKS)):
                self._sparks(p, t, 8.0 + t0 + 1.2 + i * 0.8 + 0.3, cx + (cw / 2 - 21) * S * cs, cy + (77 + 41 * i - ch / 2) * S,
                             14, 190, 0.8, 60)

    # ---- shot 4: the lock
    def _shot_lock(self, p: QPainter, t: float, s: float) -> None:
        w, h = self.width(), self.height()
        cx, cy = w / 2, self._cy(t)
        f = self._f
        a = ease_out(seg(s, 0.0, 0.6))
        sz = h * 0.16
        close = ease_back(seg(s, 0.5, 1.7))
        lift = (1 - clamp(close)) * sz * 0.5
        sway = math.sin(s * 1.6) * 14
        self._glow(p, cx, cy, sz * 2.4, self.C("accent"), 0.5 * a)
        p.save()
        tr = QTransform()
        tr.translate(cx, cy)
        tr.rotate(sway, Qt.Axis.YAxis, 1000.0)
        p.setWorldTransform(tr, True)
        p.setOpacity(a)
        body = QRectF(-sz * 0.5, -sz * 0.12, sz, sz * 0.82)
        shackle = QPainterPath()
        shackle.moveTo(-sz * 0.3, -sz * 0.12)
        shackle.lineTo(-sz * 0.3, -sz * 0.36 - lift)
        shackle.arcTo(QRectF(-sz * 0.3, -sz * 0.66 - lift, sz * 0.6, sz * 0.6), 180, -180)
        shackle.lineTo(sz * 0.3, -sz * 0.12)
        p.setPen(QPen(QBrush(metal(QPointF(-sz, -sz), QPointF(sz, sz), self.pal)), max(7.0, sz * 0.1), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        self._dp(p, shackle)
        path = QPainterPath()
        path.addRoundedRect(body, sz * 0.13, sz * 0.13)
        p.fillPath(path, QBrush(metal(body.topLeft(), body.bottomRight(), self.pal)))
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.2))
        self._dp(p, path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.C("bg"))
        p.drawEllipse(QPointF(0, body.center().y() - sz * 0.04), sz * 0.075, sz * 0.075)
        p.drawRoundedRect(QRectF(-sz * 0.022, body.center().y(), sz * 0.044, sz * 0.2), 2, 2)
        p.restore()
        self._sparks(p, t, sfx.FILM_CLUNK, cx, cy + sz * 0.1, 46, 520, 1.15, 160)
        pulse = seg(s, 1.6, 2.8)
        if 0 < pulse < 1:
            p.setPen(QPen(self.C("hi", (1 - pulse) * 0.8), 2 * f))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = sz * (0.7 + 1.8 * pulse)
            p.drawEllipse(QPointF(cx, cy + sz * 0.2), r, r)
        chips = (("AES-256", "رمزنگاری"), ("OFFLINE", "کاملاً آفلاین"), ("NO ACCOUNT", "بدون حساب"), ("YOUR KEY", "کلید دست توست"))
        fn = QFont("Inter")
        fn.setPixelSize(max(10, int(12 * f)))
        fn.setBold(True)
        fn.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.2 * f)
        fp = QFont(self.font())
        fp.setPixelSize(max(10, int(13 * f)))
        gap = 16 * f
        wd = 150 * f
        x = cx - (wd * 4 + gap * 3) / 2
        y = cy + sz * 1.05
        for i, (en, fa_t) in enumerate(chips):
            k = ease_out(seg(s, 1.5 + i * 0.22, 2.2 + i * 0.22))
            r = QRectF(x + i * (wd + gap), y + (1 - k) * 16, wd, 58 * f)
            pp = QPainterPath()
            pp.addRoundedRect(r, 14 * f, 14 * f)
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, self.C("panel2", 0.95 * k))
            g.setColorAt(1, self.C("panel", 0.95 * k))
            p.fillPath(pp, QBrush(g))
            p.setPen(QPen(self.C("hi", 0.5 * k), 1))
            self._dp(p, pp)
            p.setFont(fn)
            p.setPen(self.C("hi", k))
            p.drawText(r.adjusted(0, 8 * f, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, en)
            p.setFont(fp)
            p.setPen(self.C("muted", k))
            p.drawText(r.adjusted(0, 0, 0, -8 * f), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, fa_t)

    # ---- finale
    def _shot_finale(self, p: QPainter, t: float, s: float) -> None:
        w, h = self.width(), self.height()
        cx, cy = w / 2, self._cy(t)
        f = self._f
        fl = (1 - seg(s, 0.0, 0.35)) ** 2
        if fl > 0:
            self._glow(p, cx, cy, max(w, h) * 0.55, QColor(255, 246, 226), 0.55 * fl)
        size = h * 0.2
        pulse = 0.5 + 0.5 * math.sin(t * 1.7)
        self._glow(p, cx, cy, size * (1.5 + 0.1 * pulse), self.C("accent"), 0.5)
        yaw = math.sin(t * 0.8) * 9
        glint = ((t * 0.28) % 1.0) * 1.6 - 0.3
        self._emblem(p, cx, cy, size, yaw, ease_out(seg(s, 0, 0.7)), glint=clamp(glint) if 0 < glint < 1 else -1.0, scale=1.0, mirror=0.0)
        self._wordmark(p, cx, cy + size * 0.6 + 14 * f, h * 0.068, s, 0.2)
        self._tagline(p, cx, cy + size * 0.6 + h * 0.068 * 1.5 + 14 * f, s, 1.2)
        if self.go_btn.isVisible() or s > 0.8:
            by = self.go_btn.geometry()
            k = ease_out(seg(s, 0.9, 1.8))
            self._glow(p, by.center().x(), by.center().y(), by.width() * (0.75 + 0.1 * pulse), self.C("accent"), 0.5 * k)
            g = QConicalGradient(QPointF(by.center()), -(t * 140) % 360)
            g.setColorAt(0.0, QColor(255, 246, 226, int(255 * k)))
            g.setColorAt(0.18, self.C("hi", 0.0))
            g.setColorAt(1.0, self.C("hi", 0.0))
            p.setPen(QPen(QBrush(g), 2.4 * f))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(by).adjusted(-3, -3, 3, 3), 11 * f, 11 * f)
            fh = QFont("Inter")
            fh.setPixelSize(max(10, int(12 * f)))
            p.setFont(fh)
            p.setPen(self.C("muted", 0.8 * k))
            p.drawText(QRectF(0, by.bottom() + 14 * f, w, 22 * f), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "ENTER")
