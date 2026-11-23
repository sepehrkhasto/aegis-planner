# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar theme control: a quiet capsule of one dot per theme; a ring glides to the active one."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .fx_widgets import _Anim, _fpal
from .premium import alpha


def paint_swatch(p: QPainter, c: QPointF, r: float, pal: dict) -> None:
    """A theme's identity: its page colour with the accent as a diagonal half."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(pal["bg"]))
    p.drawEllipse(c, r, r)
    half = QPainterPath()
    half.moveTo(c.x() + r, c.y() - r)
    half.lineTo(c.x() + r, c.y() + r)
    half.lineTo(c.x() - r, c.y() + r)
    half.closeSubpath()
    disc = QPainterPath()
    disc.addEllipse(c, r, r)
    p.setBrush(QColor(pal["accent"]))
    p.drawPath(disc.intersected(half))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(alpha(pal["text"], 0.28), 1))
    p.drawEllipse(c, r, r)


class ThemeDots(QWidget):
    picked = pyqtSignal(str)
    DOT, GAP, PAD = 15, 9, 11

    def __init__(self, themes: dict, order: list[str], current: str, parent=None):
        super().__init__(parent)
        self.themes, self.order = themes, list(order)
        self.cur = current if current in self.order else self.order[0]        # a theme without a dot (contrast, mint...) lights no dot
        self._own = current in self.order
        self._hover = -1
        n = len(self.order)
        if n > 4:                                                   # more themes: tighter dots so the row still fits
            self.DOT, self.GAP, self.PAD = 14, 6, 9
        self.setFixedSize(2 * self.PAD + n * self.DOT + (n - 1) * self.GAP, 37)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName("تم برنامه")
        self._x = _Anim(self, float(self.order.index(self.cur)), 320, QEasingCurve(QEasingCurve.Type.OutBack))

    def _center(self, i: float) -> QPointF:
        return QPointF(self.PAD + self.DOT / 2 + i * (self.DOT + self.GAP), self.height() / 2)

    def _index_at(self, x: float) -> int:
        i = int((x - self.PAD + self.GAP / 2) // (self.DOT + self.GAP))
        n = len(self.order)
        return n - 1 - i if 0 <= i < n else -1                     # dot 0 sits at the right edge (RTL)

    def set_current(self, key: str) -> None:
        self._own = key in self.order                               # no dot for it: the ring stays away instead of pointing at another theme
        if key not in self.order:
            key = self.order[0]
        if key in self.themes and key != self.cur:
            self.cur = key
            self._x.to(float(self.order.index(key)))
        self.update()

    def name_of(self, i: int) -> str:
        t = self.themes[self.order[i]]
        return f"{t['fa']} — {t['en']}"

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = self._index_at(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()
            if i >= 0:
                QToolTip.showText(e.globalPosition().toPoint(), self.name_of(i), self)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        i = self._index_at(e.position().x())
        if e.button() == Qt.MouseButton.LeftButton and i >= 0:
            self.picked.emit(self.order[i])

    def keyPressEvent(self, e) -> None:  # noqa: N802
        d = {Qt.Key.Key_Right: -1, Qt.Key.Key_Left: 1}.get(e.key())      # RTL: the first theme is at the right
        if d is None:
            return super().keyPressEvent(e)
        self.picked.emit(self.order[(self.order.index(self.cur) + d) % len(self.order)])

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(alpha(pal["line"], 1.0), 1))
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        # RTL: dot 0 sits at the right edge
        for i, k in enumerate(self.order):
            c = self._center(len(self.order) - 1 - i)
            rad = self.DOT / 2 + (1.2 if i == self._hover else 0.0)
            paint_swatch(p, c, rad, self.themes[k]["pal"])
        if self._own:
            ci = len(self.order) - 1 - self._x.value
            ring = self._center(ci)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["acc_text"]), 1.6))
            p.drawEllipse(ring, self.DOT / 2 + 3.2, self.DOT / 2 + 3.2)
        if self.hasFocus():
            p.setPen(QPen(QColor(pal["accent"]), 1.2, Qt.PenStyle.DotLine))
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), r.height() / 2, r.height() / 2)
