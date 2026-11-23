# SPDX-License-Identifier: GPL-3.0-or-later
"""The sign-in scene: a breathing golden-white halo behind the Aegis mark and a padlock that closes as you type.

* ``GlowMark``  - BrandMark with a slow "breathing" radial glow (only animates while visible, static when motion is off).
* ``LockGlyph`` - a small padlock: shackle open when the field is empty, easing shut as the password grows; a gentle
                  glow appears once it is closed (long enough). ``set_level(0..1)`` drives it.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .anim import MOTION
from .fx_widgets import _fpal
from .parallax import Follower
from .premium import BrandMark, mix
from .theme import rr


class GlowMark(QWidget):
    PAD = 46

    def __init__(self, size: int = 64, parent=None):
        super().__init__(parent)
        self.size_ = size
        self.setFixedSize(size + 2 * self.PAD, size + 2 * self.PAD)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mark = BrandMark(size)
        lay.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignCenter)
        self.follow = Follower(self)                          # the mark and its halo sit at different depths
        self._lay = lay
        self.t = 0.5
        self.boost = 0.0                                       # extra flash (e.g. on success), 0..1
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(3200)
        self.an.setLoopCount(-1)
        self.an.valueChanged.connect(self._tick)
        self._flash = QVariantAnimation(self)
        self._flash.setStartValue(1.0)
        self._flash.setEndValue(0.0)
        self._flash.setDuration(900)
        self._flash.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._flash.valueChanged.connect(self._fl)

    def _tick(self, v) -> None:
        self.t = 0.5 - 0.5 * math.cos(float(v) * 2 * math.pi)
        if self.follow.step():
            dx, dy = int(round(self.follow.x * 6)), int(round(self.follow.y * 5))
            self._lay.setContentsMargins(max(0, dx) * 2, max(0, dy) * 2, max(0, -dx) * 2, max(0, -dy) * 2)   # the mark itself moves
        self.update()

    def _fl(self, v) -> None:
        self.boost = float(v)
        self.update()

    def flash(self) -> None:
        """A one-off bright pulse (successful unlock)."""
        if MOTION[0]:
            self._flash.stop()
            self._flash.start()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if MOTION[0]:
            self.an.start()

    def hideEvent(self, e) -> None:  # noqa: N802
        self.an.stop()
        super().hideEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        c = QPointF(self.width() / 2 - self.follow.x * 9, self.height() / 2 - self.follow.y * 7)      # the halo drifts the other way
        base = QColor(pal["accent"])
        a = 0.26 + 0.20 * self.t + 0.5 * self.boost
        rad = self.size_ * (0.95 + 0.20 * self.t + 0.5 * self.boost)
        g = QRadialGradient(c, rad)
        for pos, k in ((0.0, a), (0.45, a * 0.42), (1.0, 0.0)):
            col = QColor(base)
            col.setAlphaF(max(0.0, min(1.0, k)))
            g.setColorAt(pos, col)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, rad, rad)


class LockGlyph(QWidget):
    """Padlock whose shackle closes with ``level`` (0 = wide open, 1 = shut)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 40)
        self.level, self._goal = 0.0, 0.0
        self.an = QVariantAnimation(self)
        self.an.setDuration(260)
        self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.valueChanged.connect(self._set)

    def _set(self, v) -> None:
        self.level = float(v)
        self.update()

    def set_level(self, k: float) -> None:
        k = max(0.0, min(1.0, k))
        if abs(k - self._goal) < 1e-3:
            return
        self._goal = k
        if not MOTION[0] or not self.isVisible():
            self.level = k
            self.update()
            return
        self.an.stop()
        self.an.setStartValue(self.level)
        self.an.setEndValue(k)
        self.an.start()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        k = self.level
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(4, h * 0.46, w - 8, h * 0.50)
        tone = mix(QColor(pal["muted"]), QColor(pal["accent"]), k)
        # shackle: left leg fixed on the body; the right leg lifts and the arc swings up/left as it opens
        lift = (1.0 - k) * 9.0
        sw = w * 0.5 - 6
        left_x, right_x = w / 2 - sw / 2, w / 2 + sw / 2
        top = body.top()
        arc_top = 2 + (1.0 - k) * -1.0
        path = QPainterPath()
        path.moveTo(left_x, top)
        path.lineTo(left_x, arc_top + sw / 2 - lift * 0.2)
        path.arcTo(QRectF(left_x, arc_top - lift * 0.2, sw, sw), 180, -180)
        path.lineTo(right_x, top - lift)
        pen = QPen(tone, 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if k > 0.98:                                            # closed: a soft ring of light
            g = QColor(pal["accent"])
            g.setAlphaF(0.18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(body.center(), w * 0.62, w * 0.62)
        p.setPen(QPen(mix(QColor(pal["line"]), tone, 0.6), 1.2))
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(body, rr(7), rr(7))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tone)
        p.drawEllipse(body.center() - QPointF(0, 1.5), 2.6, 2.6)
        p.drawRoundedRect(QRectF(body.center().x() - 1.1, body.center().y(), 2.2, 5.5), 1, 1)
