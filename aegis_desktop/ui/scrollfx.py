# SPDX-License-Identifier: GPL-3.0-or-later
"""Scrollbars that wake up only while you scroll: the thumb is a barely-visible hairline at rest and brightens for
~0.8 s after every movement (wheel, drag, keys). Done with a dynamic ``active`` property that the theme QSS styles -
no global event filter: ``attach(root)`` hooks the scrollbars that exist, and is cheap to call again."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, Qt, QTimer, QVariantAnimation
from PyQt6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QScrollArea, QScrollBar, QWidget

from .anim import MOTION

HOLD_MS = 800


class _Wake:
    def __init__(self, bar: QScrollBar):
        self.bar = bar
        self.timer = QTimer(bar, singleShot=True, interval=HOLD_MS)
        self.timer.timeout.connect(self.sleep)
        bar.valueChanged.connect(self.wake)

    def _set(self, on: bool) -> None:
        self.bar.setProperty("active", on)
        st = self.bar.style()
        st.unpolish(self.bar)
        st.polish(self.bar)
        self.bar.update()

    def wake(self, _v=0) -> None:
        if not self.bar.property("active"):
            self._set(True)
        self.timer.start()

    def sleep(self) -> None:
        if self.bar.isSliderDown():                     # still dragging: stay lit
            self.timer.start()
            return
        self._set(False)


class _Glide(QObject):
    """Inertial mouse-wheel scrolling: each notch moves the target and the bar eases toward it (~200 ms), so several fast
    notches glide as one long motion instead of jumping. Precision touchpads (pixel deltas) and Ctrl+wheel keep Qt's native
    behaviour; at either end the wheel is handed on to the parent so nested areas still chain."""

    STEP = 84.0                 # px per notch (3 lines)

    def __init__(self, area: QAbstractScrollArea):
        super().__init__(area)
        self.area = area
        self.target = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(210)
        self.anim.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self.anim.valueChanged.connect(self._apply)
        area.destroyed.connect(self.anim.stop)
        area.viewport().installEventFilter(self)

    def _apply(self, v) -> None:
        try:
            self.area.verticalScrollBar().setValue(int(round(float(v))))
        except RuntimeError:                              # the view was deleted while gliding
            self.anim.stop()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() != QEvent.Type.Wheel or not MOTION[0]:
            return False
        if not ev.pixelDelta().isNull() or ev.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        dy = ev.angleDelta().y()
        bar = self.area.verticalScrollBar()
        if dy == 0 or bar.maximum() <= bar.minimum():
            return False
        running = self.anim.state() == QVariantAnimation.State.Running
        base = self.target if running else float(bar.value())
        new = max(float(bar.minimum()), min(float(bar.maximum()), base - dy / 120.0 * self.STEP))
        if new == base:                                                  # already at the end: let a parent area take it
            return False
        self.target = new
        self.anim.stop()
        self.anim.setStartValue(float(bar.value()))
        self.anim.setEndValue(new)
        self.anim.start()
        return True


class _Edges(QWidget):
    """Content dissolves into the page at the top/bottom of a scrolling page instead of being cut by a hard line: the fade is
    proportional to how much content is hidden on that side (nothing at rest, full after ~40 px of scroll)."""
    H = 26

    def __init__(self, area: QScrollArea):
        super().__init__(area.viewport())
        self.area = area
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(area.viewport().rect())
        bar = area.verticalScrollBar()
        bar.valueChanged.connect(self.update)
        bar.rangeChanged.connect(self.update)
        area.viewport().installEventFilter(self)
        self.raise_()
        self.show()

    def eventFilter(self, o, e):  # noqa: N802
        if e.type() == QEvent.Type.Resize:
            self.setGeometry(self.area.viewport().rect())
            self.raise_()
        return False

    def amounts(self) -> tuple[float, float]:
        bar = self.area.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            return 0.0, 0.0
        return min(1.0, (bar.value() - bar.minimum()) / 40.0), min(1.0, (bar.maximum() - bar.value()) / 40.0)

    def paintEvent(self, _e) -> None:  # noqa: N802
        top, bottom = self.amounts()
        if top <= 0.01 and bottom <= 0.01:
            return
        from PyQt6.QtGui import QColor, QLinearGradient, QPainter
        from .fx_widgets import _fpal
        bg = QColor(_fpal(self.area)["bg"])
        p = QPainter(self)
        for amt, y0, y1 in ((top, 0.0, float(self.H)), (bottom, float(self.height()), float(self.height() - self.H))):
            if amt <= 0.01:
                continue
            g = QLinearGradient(0, y0, 0, y1)
            c0, c1 = QColor(bg), QColor(bg)
            c0.setAlphaF(0.92 * amt)
            c1.setAlphaF(0.0)
            g.setColorAt(0, c0)
            g.setColorAt(1, c1)
            p.fillRect(0, int(min(y0, y1)), self.width(), self.H, g)


def _glidable(area: QAbstractScrollArea) -> bool:
    """Pixel-scrolling areas only: a per-item list would need different maths (and has its own feel)."""
    if isinstance(area, QAbstractItemView):
        return area.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    return True


def attach(root: QWidget) -> int:
    """Hook every scrollbar under ``root`` (once each). Returns how many were newly hooked."""
    n = 0
    areas = root.findChildren(QAbstractScrollArea)
    if isinstance(root, QAbstractScrollArea):
        areas.append(root)
    for area in areas:
        for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
            if bar is not None and not bar.property("_wake"):
                bar.setProperty("_wake", True)
                bar._wake = _Wake(bar)
                n += 1
        if isinstance(area, QScrollArea) and area.property("edges") and not area.property("_edges"):     # opt-in: page-level areas only
            area.setProperty("_edges", True)
            area._edges = _Edges(area)
        if not area.property("_glide") and _glidable(area):
            area.setProperty("_glide", True)
            area._glide = _Glide(area)
    return n
