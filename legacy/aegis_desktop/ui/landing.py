# SPDX-License-Identifier: GPL-3.0-or-later
"""Brand surfaces: ParticleText hero, BorderGlow card, and the WarmTooltip manager.

Performance: ParticleText and BorderGlow run a timer only while there is something to animate
(gathering, pointer near, settling) and only while the widget is visible.
"""
from __future__ import annotations

import math
import re

import numpy as np
from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QCursor, QLinearGradient, QFont, QFontMetrics, QImage, QPainter, QPen, QPolygonF,
                         QRadialGradient)
from PyQt6.QtWidgets import QApplication, QFrame, QWidget

from .theme import AL_R
from .theme import rr as _rad
from .theme import PALETTES



def _theme_of(w: QWidget) -> str:
    x = w
    while x is not None:
        t = getattr(x, "theme", None)
        if isinstance(t, str) and t in PALETTES:
            return t
        x = x.parentWidget()
    return "dark"


# ------------------------------------------------------------ ParticleText ---
class ParticleText(QWidget):
    """Text made of particles that gather from a scatter, then repel from the pointer."""

    def __init__(self, text: str = "AEGIS", particle: float = 2.5, density: int = 4, scatter: float = 190,
                 gather_ms: int = 1600, stagger_ms: int = 420, repel: float = 42, radius: float = 120):
        super().__init__()
        self.text, self.psize, self.density = text, particle, density
        self.scatter, self.gather, self.stagger, self.repel, self.radius = scatter, gather_ms, stagger_ms, repel, radius
        self.setMouseTracking(True)
        self.setMinimumHeight(170)
        self.theme = None  # inherit
        self.n = 0
        self.home = self.pos_ = self.vel = np.zeros((0, 2))
        self.delay = self.hl = np.zeros(0)
        self.t = 0.0
        self.ptr = np.array([-9999.0, -9999.0])
        self._built_for = (0, 0)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self._step)

    # geometry ---------------------------------------------------------------
    def _build(self) -> None:
        w, h = max(80, self.width()), max(80, self.height())
        self._built_for = (w, h)
        img = QImage(w, h, QImage.Format.Format_Grayscale8)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        from .brand import display_font
        f = display_font(20)                                   # Cormorant Garamond Bold: the brand's display caps
        size = int(min(h * 0.86, w * 0.9 / max(1, len(self.text)) * 1.5))
        f.setPixelSize(max(20, size))
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 118)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()
        stride = img.bytesPerLine()
        arr = np.frombuffer(img.constBits().asstring(stride * h), dtype=np.uint8).reshape(h, stride)[:, :w]
        step = max(2, self.density)
        ys, xs = np.nonzero(arr[::step, ::step] > 128)
        pts = np.stack([xs * step + step / 2, ys * step + step / 2], axis=1).astype(float)
        rng = np.random.default_rng(7)
        self.n = len(pts)
        self.home = pts
        ang = rng.uniform(0, 2 * math.pi, self.n)
        rad = rng.uniform(0.3, 1.0, self.n) * self.scatter
        self.pos_ = pts + np.stack([np.cos(ang) * rad, np.sin(ang) * rad], axis=1)
        self.vel = np.zeros((self.n, 2))
        self.delay = rng.uniform(0, self.stagger / 1000, self.n)
        self.hl = np.zeros(self.n)
        self.t = 0.0
        self.timer.start()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.isVisible() and (self.width(), self.height()) != self._built_for:
            self._build()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if (self.width(), self.height()) != self._built_for or self.n == 0:
            self._build()
        else:
            self.timer.start()

    def hideEvent(self, e) -> None:  # noqa: N802
        self.timer.stop()
        super().hideEvent(e)

    def replay(self) -> None:
        self._build()

    # interaction ---------------------------------------------------------------
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self.ptr = np.array([e.position().x(), e.position().y()])
        if not self.timer.isActive():
            self.timer.start()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.ptr = np.array([-9999.0, -9999.0])
        if not self.timer.isActive():
            self.timer.start()

    # simulation ----------------------------------------------------------------
    def _step(self) -> None:
        if self.n == 0:
            self.timer.stop()
            return
        dt = 0.016
        self.t += dt
        live = (self.t > self.delay)[:, None]
        k = 9.0 if self.t * 1000 < self.gather else 14.0
        acc = (self.home - self.pos_) * k * live
        d = self.pos_ - self.ptr
        dist = np.sqrt((d ** 2).sum(axis=1)) + 1e-6
        near = dist < self.radius
        if near.any():
            push = ((1 - dist / self.radius) * near * self.repel * 24)[:, None]
            acc += d / dist[:, None] * push
        self.vel = (self.vel + acc * dt) * 0.86
        self.pos_ += self.vel * dt * 6
        tgt = (dist < self.radius * 0.7).astype(float)
        self.hl += (tgt - self.hl) * 0.15
        self.update()
        settled = (self.t * 1000 > self.gather + self.stagger and float(np.abs(self.vel).max()) < 0.4
                   and float(np.abs(self.home - self.pos_).max()) < 0.6 and float(self.hl.max()) < 0.02)
        if settled and not near.any():
            self.pos_[:] = self.home
            self.timer.stop()
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        if self.n == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = PALETTES[self.theme or _theme_of(self)]
        base = QColor(pal["text"])
        a2 = QColor(pal["accent2"])                          # the letters are gilded: text tinted toward the accent
        base = QColor((base.red() + a2.red() * 2) // 3, (base.green() + a2.green() * 2) // 3, (base.blue() + a2.blue() * 2) // 3)
        hi = QColor(pal["hi"])
        fade = np.clip((self.t - self.delay) / 0.5, 0.15, 1.0)
        for mask_hi in (False, True):
            sel = (self.hl > 0.35) if mask_hi else (self.hl <= 0.35)
            idx = np.nonzero(sel)[0]
            if idx.size == 0:
                continue
            c = QColor(hi if mask_hi else base)
            pen = QPen(c, self.psize * (1.35 if mask_hi else 1.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            # bucket alpha in 3 levels to keep drawPoints batched
            for lo, up, a in ((0, 0.5, 90), (0.5, 0.95, 190), (0.95, 2, 255)):
                sub = idx[(fade[idx] >= lo) & (fade[idx] < up)]
                if sub.size == 0:
                    continue
                c.setAlpha(a)
                pen.setColor(c)
                p.setPen(pen)
                pts = self.pos_[sub]
                p.drawPoints(QPolygonF([QPointF(x, y) for x, y in pts]))


# --------------------------------------------------------------- BorderGlow ---
class BorderGlow(QFrame):
    """Card whose border lights up in a brand gradient near the pointer (polled only while visible)."""
    COLORS = ("#9fadc7", "#6a7f8b", "#99b6b2")

    def __init__(self, radius: int = 22, sensitivity: int = 60):
        super().__init__()
        self.setObjectName("GlowCard")
        self.radius, self.sens = radius, sensitivity
        self._cur = QPointF(-999, -999)
        self._k = 0.0
        self._poll = QTimer(self, interval=30)
        self._poll.timeout.connect(self._check)
        self.setContentsMargins(0, 0, 0, 0)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._poll.start()

    def hideEvent(self, e) -> None:  # noqa: N802
        self._poll.stop()
        super().hideEvent(e)

    def _check(self) -> None:
        loc = QPointF(self.mapFromGlobal(QCursor.pos()))
        r = QRectF(self.rect())
        inside = r.adjusted(-self.sens, -self.sens, self.sens, self.sens).contains(loc)
        # proximity to the nearest edge
        dx = min(loc.x() - r.left(), r.right() - loc.x())
        dy = min(loc.y() - r.top(), r.bottom() - loc.y())
        edge = min(abs(dx), abs(dy)) if r.contains(loc) else 0
        target = 0.0
        if inside:
            target = 0.35 + 0.65 * max(0.0, 1 - edge / (self.sens * 3))
        nk = self._k + (target - self._k) * 0.2
        if abs(nk - self._k) < 0.003 and loc == self._cur:
            return
        if abs(nk) < 0.01 and target == 0:
            nk = 0.0
            if self._k == 0.0:
                return
        self._k, self._cur = nk, loc
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES[_theme_of(self)]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(r, min(self.radius, _rad(self.radius * 0.9)), min(self.radius, _rad(self.radius * 0.9)))
        from . import brand
        from PyQt6.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addRoundedRect(r, min(self.radius, _rad(self.radius * 0.9)), min(self.radius, _rad(self.radius * 0.9)))
        brand.paint_grain(p, r, pal, 1.0, clip)
        brand.paint_crest(p, QRectF(self.rect()), pal, inset=12, arm=11, alpha=120)
        if self._k > 0.01:
            g = QRadialGradient(self._cur, 150)
            for i, col in enumerate((pal["hi"], pal["acc_text"], pal["accent"])):
                c = QColor(col)
                c.setAlphaF(min(1.0, self._k))
                g.setColorAt(i * 0.38, c)
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            for w, a in ((9, 0.16), (2.4, 1.0)):
                p.setOpacity(a)
                pen = QPen()
                pen.setBrush(g)
                pen.setWidthF(w)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r, min(self.radius, _rad(self.radius * 0.9)), min(self.radius, _rad(self.radius * 0.9)))
            p.setOpacity(1)


# ------------------------------------------------------------- WarmTooltip ---
_KEY = r"(?:Ctrl|Shift|Alt|⌘)(?:\+[\w/\[\],.\-]+)+"
_KBD = re.compile(r"^(.*?)(?:\s{2,}|\s*\()(" + _KEY + r")\)?\s*$")
_BARE = re.compile(r"^\(?(" + _KEY + r")\)?$")


class _Bubble(QWidget):
    """Every tooltip in the app: a small glass card (translucent surface, hairline border, soft shadow) with the
    keyboard shortcut as a key-cap on the far side. Text and key-cap come from ``"label  Ctrl+N"``."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text, self.kbd, self.dark = "", "", True

    @staticmethod
    def split(text: str) -> tuple[str, str]:
        text = text.strip()
        b = _BARE.match(text)
        if b:
            return "", b.group(1)
        m = _KBD.match(text)
        return (m.group(1).strip(), m.group(2)) if m else (text, "")

    def set(self, text: str, dark: bool) -> None:
        self.text, self.kbd = self.split(text)
        self.dark = dark
        fm = QFontMetrics(self.font())
        w = (fm.horizontalAdvance(self.text) + 24) if self.text else 12
        if self.kbd:
            w += fm.horizontalAdvance(self.kbd) + (18 if self.text else 12)
        self.resize(w + 12, fm.height() + 22)                    # room for the shadow
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from .theme import PALETTES
        pal = PALETTES["dark" if self.dark else "light"]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(6, 3, self.width() - 12, self.height() - 12)
        rad = min(_rad(8), 9)
        p.setPen(Qt.PenStyle.NoPen)
        for grow, a in ((3, 14), (2, 22), (1, 30)):              # soft shadow
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(body.adjusted(-grow, -grow + 3, grow, grow + 3), rad + grow, rad + grow)
        surf = QColor(pal["panel2"])
        surf.setAlpha(238)
        p.setBrush(surf)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawRoundedRect(body, rad, rad)
        hi = QLinearGradient(body.topLeft(), body.bottomLeft())    # faint top sheen = the "glass"
        hi.setColorAt(0, QColor(255, 255, 255, 26 if self.dark else 70))
        hi.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hi)
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        fm = p.fontMetrics()
        left = body.left() + 8
        if self.kbd:
            kw = fm.horizontalAdvance(self.kbd) + 12
            kr = QRectF(left if self.text else body.center().x() - kw / 2, body.center().y() - 9, kw, 18)
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.setBrush(QColor(pal["panel"]))
            p.drawRoundedRect(kr, _rad(5), _rad(5))
            p.setPen(QColor(pal["muted"]))
            p.drawText(kr, Qt.AlignmentFlag.AlignCenter, self.kbd)
            left = kr.right() + 8
        if self.text:
            p.setPen(QColor(pal["text"]))
            p.drawText(QRectF(left, body.top(), body.right() - 10 - left, body.height()),
                       AL_R | Qt.AlignmentFlag.AlignVCenter, self.text)


class WarmTooltips(QObject):
    """Replaces Qt tooltips: pops in after a delay when cold, glides between neighbours when warm."""
    DELAY, WARM = 400, 300

    def __init__(self, app: QApplication, owner: QObject | None = None):
        super().__init__(owner or app)   # owned by the main window: removed from the app's filters when it closes
        self.bubble = _Bubble()
        self.destroyed.connect(self.bubble.deleteLater)
        self.pending: tuple[QWidget, str] | None = None
        self.open_timer = QTimer(self, singleShot=True, interval=self.DELAY)
        self.open_timer.timeout.connect(self._open)
        self.close_timer = QTimer(self, singleShot=True, interval=90)
        self.close_timer.timeout.connect(self._close)
        self.warm_until = 0.0
        self.glide = QPropertyAnimation(self.bubble, b"pos", self)
        self.glide.setDuration(260)
        self.glide.setEasingCurve(QEasingCurve.Type.OutBack)
        self.fade = QPropertyAnimation(self.bubble, b"windowOpacity", self)
        self.fade.setDuration(140)
        self.current: QWidget | None = None
        self.dark = True
        app.installEventFilter(self)

    def set_theme(self, theme: str) -> None:
        self.dark = theme == "dark"

    def eventFilter(self, obj, e) -> bool:  # noqa: N802
        t = e.type()
        if t == QEvent.Type.ToolTip and isinstance(obj, QWidget) and obj.toolTip():
            self.pending = (obj, obj.toolTip())
            self.close_timer.stop()
            import time
            if time.monotonic() < self.warm_until or self.bubble.isVisible():
                self._open()
            else:
                self.open_timer.start()
            return True   # suppress the native tooltip
        if t in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel):
            if isinstance(obj, QWidget) and (obj is self.current or obj is (self.pending and self.pending[0])):
                self.open_timer.stop()
                self.close_timer.start()
        return False

    def _target(self, w: QWidget, text: str) -> tuple[int, int]:
        self.bubble.set(text, self.dark)
        c = w.mapToGlobal(w.rect().center())
        top = w.mapToGlobal(w.rect().topLeft()).y()
        x = c.x() - self.bubble.width() // 2
        y = top - self.bubble.height() + 4
        if y < 4:
            y = w.mapToGlobal(w.rect().bottomLeft()).y() + 6
        return x, y

    def _open(self) -> None:
        if not self.pending:
            return
        import time
        w, text = self.pending
        try:
            x, y = self._target(w, text)
        except RuntimeError:
            return
        self.current = w
        if self.bubble.isVisible():
            self.glide.stop()
            self.glide.setStartValue(self.bubble.pos())
            self.glide.setEndValue(self.bubble.pos().__class__(x, y))
            self.glide.start()
        else:
            self.bubble.move(x, y - 4)
            self.bubble.setWindowOpacity(0.0)
            self.bubble.show()
            self.glide.stop()
            self.glide.setStartValue(self.bubble.pos())
            self.glide.setEndValue(self.bubble.pos().__class__(x, y))
            self.glide.setDuration(160)
            self.glide.start()
            self.fade.stop()
            self.fade.setStartValue(0.0)
            self.fade.setEndValue(1.0)
            self.fade.start()
        self.warm_until = time.monotonic() + 999

    def _close(self) -> None:
        import time
        self.bubble.hide()
        self.current = None
        self.pending = None
        self.warm_until = time.monotonic() + self.WARM / 1000
        self.glide.setDuration(260)
