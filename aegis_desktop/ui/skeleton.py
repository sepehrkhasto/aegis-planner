# SPDX-License-Identifier: GPL-3.0-or-later
"""Loading skeleton: matte placeholder blocks with one slow shimmer sweeping across them.

Used for data-heavy pages (Reports): the skeleton is painted *before* the page computes its numbers, stays for at least a
beat so it never flashes, then dissolves into the real content. Timer runs only while it is on screen; nothing is drawn
with reduced motion (the page simply appears)."""
from __future__ import annotations

import time

from PyQt6.QtCore import QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from .anim import MOTION
from .fx_widgets import _fpal
from .theme import rr

MIN_MS = 520            # shown at least this long (the page crossfade uncovers it first), so it reads as a deliberate reveal
SWEEP_MS = 1300


def layout_blocks(w: float, h: float, pad: float = 24.0) -> list[tuple[QRectF, str]]:
    """Placeholder geometry for a dashboard page: a title, a row of four KPI tiles, then a two-column grid of cards."""
    out: list[tuple[QRectF, str]] = []
    x0, x1 = pad, w - pad
    gap, top = 12.0, pad + 64
    out.append((QRectF(max(x0, x1 - 190), pad, min(190.0, x1 - x0), 22), "title"))
    out.append((QRectF(max(x0, x1 - 330), pad + 32, min(330.0, x1 - x0), 12), "line"))
    x1 = max(x1, x0 + 120)                                # never negative on a tiny host
    tw = (x1 - x0 - 3 * gap) / 4
    for i in range(4):
        out.append((QRectF(x1 - (i + 1) * tw - i * gap, top, tw, 104), "tile"))
    y = top + 104 + gap
    big = (x1 - x0 - gap) * 0.62
    rows = max(1, int((h - y - pad + gap) // (230 + gap)))
    for r in range(min(rows, 3)):
        yy = y + r * (230 + gap)
        out.append((QRectF(x1 - big, yy, big, 230), "card"))
        out.append((QRectF(x0, yy, x1 - x0 - big - gap, 230), "card"))
    return out


class Skeleton(QWidget):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.t0 = time.monotonic()
        self.phase = 0.0
        self.k = 1.0
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._step)
        self._fade = None
        self.setGeometry(host.rect())
        host.installEventFilter(self)

    def eventFilter(self, o, e):  # noqa: N802
        from PyQt6.QtCore import QEvent
        if e.type() == QEvent.Type.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False

    def start(self) -> None:
        self.show()
        self.raise_()
        self._timer.start()
        self.repaint()                                  # on screen NOW, before the page starts computing

    def _step(self) -> None:
        self.phase = ((time.monotonic() - self.t0) * 1000.0 / SWEEP_MS) % 1.0
        self.update()

    def finish(self) -> None:
        """Dissolve once the minimum time has passed."""
        left = MIN_MS - (time.monotonic() - self.t0) * 1000.0
        QTimer.singleShot(max(0, int(left)), self._dissolve)

    def _dissolve(self) -> None:
        if self._fade is not None:
            return
        self._fade = QVariantAnimation(self)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setDuration(220)
        self._fade.valueChanged.connect(self._set_k)
        self._fade.finished.connect(self._done)
        self._fade.start()

    def _set_k(self, v) -> None:
        self.k = float(v)
        self.update()

    def _done(self) -> None:
        self._timer.stop()
        self.hide()
        host = self.parentWidget()
        if host is not None and getattr(host, "_skeleton", None) is self:
            host._skeleton = None
        self.deleteLater()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.k)
        p.fillRect(self.rect(), QColor(pal["bg"]))
        rad = min(rr(12), 14)
        dark = QColor(pal["bg"]).lightness() < 128
        for r, kind in layout_blocks(self.width(), self.height()):
            if kind in ("title", "line"):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["panel2"]))
                p.drawRoundedRect(r, 6, 6)
                continue
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.setBrush(QColor(pal["panel"]))
            p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), rad, rad)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["panel2"]))
            if kind == "tile":
                p.drawRoundedRect(QRectF(r.right() - 44, r.top() + 14, 30, 30), 9, 9)
                p.drawRoundedRect(QRectF(r.right() - 70, r.bottom() - 42, 56, 22), 6, 6)
            else:
                p.drawRoundedRect(QRectF(r.right() - 150, r.top() + 18, 130, 14), 6, 6)
                p.drawRoundedRect(QRectF(r.right() - 230, r.top() + 40, 210, 10), 5, 5)
                for i in range(6):                        # a ghost of the chart: bars of varied height
                    hh = 30 + (i * 37) % 90
                    p.drawRoundedRect(QRectF(r.right() - 40 - i * 34, r.bottom() - 24 - hh, 20, hh), 4, 4)
        # the shimmer: one soft diagonal band travelling from the start side to the end side
        w = self.width()
        cx = w * (1.15 - 1.3 * self.phase)
        g = QLinearGradient(cx - w * .18, 0, cx + w * .18, self.height() * .25)
        hi = QColor(255, 255, 255, 16 if dark else 60)
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, hi)
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), g)


def cover(page: QWidget) -> Skeleton | None:
    """Put a skeleton over ``page`` right now (None with reduced motion or if the page is not on screen)."""
    if not MOTION[0] or not page.isVisible():
        return None
    old = getattr(page, "_skeleton", None)
    if old is not None:
        try:
            old.deleteLater()
        except RuntimeError:
            pass
    sk = Skeleton(page)
    page._skeleton = sk
    sk.start()
    QApplication.processEvents()
    return sk
