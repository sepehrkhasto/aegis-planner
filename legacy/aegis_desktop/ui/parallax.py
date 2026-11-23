# SPDX-License-Identifier: GPL-3.0-or-later
"""Pointer parallax: things that sit at different depths shift a few pixels against each other as the pointer moves.

``tilt(widget)`` is the pointer position relative to the window's centre, -1..1 on both axes. ``Follower`` eases toward it so
motion never snaps. Everything using it repaints only when the eased value actually changed, and only while visible."""
from __future__ import annotations

from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QWidget

from .anim import MOTION


def tilt(w: QWidget) -> tuple[float, float]:
    win = w.window()
    if win is None or not win.isVisible() or win.width() < 10 or win.height() < 10:
        return 0.0, 0.0
    c = win.mapFromGlobal(QCursor.pos())
    nx = (c.x() - win.width() / 2) / (win.width() / 2)
    ny = (c.y() - win.height() / 2) / (win.height() / 2)
    return max(-1.0, min(1.0, nx)), max(-1.0, min(1.0, ny))


class Follower:
    """Eases (x, y) toward the pointer tilt of ``widget``; ``step()`` returns True when the eased value moved."""

    def __init__(self, widget: QWidget, ease: float = 0.16):
        self.w, self.ease = widget, ease
        self.x = self.y = 0.0

    def step(self) -> bool:
        if not MOTION[0]:
            moved = self.x != 0.0 or self.y != 0.0
            self.x = self.y = 0.0
            return moved
        tx, ty = tilt(self.w)
        nx, ny = self.x + (tx - self.x) * self.ease, self.y + (ty - self.y) * self.ease
        moved = abs(nx - self.x) > 0.004 or abs(ny - self.y) > 0.004
        if moved:
            self.x, self.y = nx, ny
        return moved
