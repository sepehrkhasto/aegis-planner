# SPDX-License-Identifier: GPL-3.0-or-later
"""The tick that travels: when a task is completed, a small light leaves the row and flies to the counter that just
changed (the «done today» tile, or the Today entry in the sidebar when that tile is not on screen). The counter holds its
number until the light lands, then rolls — cause and effect in one gesture (~0.42 s, never blocks input).

Paint-only overlay; a timer runs only while a light is in the air. Nothing happens with reduced motion."""
from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

from .anim import MOTION

MS = 420
TRAIL = 9


def bezier(a: QPointF, c: QPointF, b: QPointF, t: float) -> QPointF:
    u = 1.0 - t
    return QPointF(u * u * a.x() + 2 * u * t * c.x() + t * t * b.x(), u * u * a.y() + 2 * u * t * c.y() + t * t * b.y())


def control_point(a: QPointF, b: QPointF) -> QPointF:
    """The arc bows upward (toward the top of the window), more for longer flights."""
    mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
    d = math.hypot(b.x() - a.x(), b.y() - a.y())
    return QPointF(mid.x(), mid.y() - min(140.0, 30.0 + d * 0.22))


class _Light(QWidget):
    def __init__(self, host: QWidget, a: QPointF, b: QPointF, color: QColor, on_land):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(host.rect())
        self.a, self.b, self.c = a, b, control_point(a, b)
        self.color, self.on_land = QColor(color), on_land
        self.t = 0.0
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(MS)
        self.an.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutCubic))
        self.an.valueChanged.connect(self._step)
        self.an.finished.connect(self._land)
        self.landed = False

    def go(self) -> None:
        self.show()
        self.raise_()
        self.an.start()

    def _step(self, v) -> None:
        self.t = float(v)
        self.update()

    def _land(self) -> None:
        if self.landed:
            return
        self.landed = True
        try:
            if self.on_land:
                self.on_land()
        finally:
            self.hide()
            self.deleteLater()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(TRAIL, -1, -1):                       # a short comet tail, fading and narrowing
            tt = max(0.0, self.t - i * 0.028)
            pt = bezier(self.a, self.c, self.b, tt)
            k = 1.0 - i / (TRAIL + 1)
            col = QColor(self.color)
            col.setAlphaF(0.55 * k * k)
            p.setBrush(col)
            r = 2.0 + 3.2 * k
            p.drawEllipse(pt, r, r)
        head = bezier(self.a, self.c, self.b, self.t)
        g = QRadialGradient(head, 15)
        glow = QColor(self.color)
        glow.setAlphaF(0.55)
        g.setColorAt(0, glow)
        glow.setAlphaF(0.0)
        g.setColorAt(1, glow)
        p.setBrush(g)
        p.drawEllipse(head, 15, 15)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawEllipse(head, 3.2, 3.2)


def launch(host: QWidget, start_global: QPoint, target: QWidget, color: QColor, on_land=None, anchor: QPoint | None = None) -> _Light | None:
    """Fly a light from ``start_global`` to ``target`` (its ``anchor`` in target coordinates, default its centre).
    Returns the overlay, or None when motion is reduced / the target is not visible (``on_land`` is then called at once)."""
    if not MOTION[0] or host is None or target is None or not target.isVisible():
        if on_land:
            on_land()
        return None
    a = QPointF(host.mapFromGlobal(start_global))
    tp = anchor if anchor is not None else target.rect().center()
    b = QPointF(host.mapFromGlobal(target.mapToGlobal(tp)))
    light = _Light(host, a, b, color, on_land)
    light.go()
    return light
