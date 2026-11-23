# SPDX-License-Identifier: GPL-3.0-or-later
"""Ambient light: the room's light follows the clock. A very quiet wash from the top corner - cool at night, rosy at dawn,
neutral at noon, amber in the evening - so the app feels lit rather than painted.

Deliberately faint (alpha 2-5 %): you should never *see* a colour, only feel that the evening is warmer than the morning.
It is one translucent widget that repaints only when the tone changes (every few minutes), and it can be switched off."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QEvent, QPointF, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

from .fx_widgets import _fpal

# (minute of day, rgb, alpha) - the day as a ring; the first stop repeats at 24:00
STOPS = [(0, (108, 132, 255), 0.050), (330, (255, 168, 140), 0.046), (480, (196, 218, 255), 0.030),
         (720, (255, 255, 255), 0.022), (990, (255, 224, 168), 0.034), (1110, (255, 168, 90), 0.052),
         (1260, (150, 128, 255), 0.048), (1440, (108, 132, 255), 0.050)]
GREETING = ((5, "صبح بخیر"), (12, "ظهر بخیر"), (17, "عصر بخیر"), (21, "شب بخیر"))


def tone_at(minute: float) -> tuple[QColor, float]:
    """Colour and strength of the light at ``minute`` of the day (0-1440), blended between the surrounding stops."""
    m = max(0.0, min(1440.0, float(minute)))
    for (m0, c0, a0), (m1, c1, a1) in zip(STOPS, STOPS[1:]):
        if m0 <= m <= m1:
            t = 0.0 if m1 == m0 else (m - m0) / (m1 - m0)
            rgb = [round(x + (y - x) * t) for x, y in zip(c0, c1)]
            return QColor(*rgb), a0 + (a1 - a0) * t
    return QColor(*STOPS[0][1]), STOPS[0][2]


def minute_of(now: dt.datetime) -> float:
    return now.hour * 60 + now.minute + now.second / 60.0


def greeting(now: dt.datetime | None = None) -> str:
    h = (now or dt.datetime.now()).hour
    out = GREETING[-1][1]                        # before 05:00 it is still night
    for start, text in GREETING:
        if h >= start:
            out = text
    return out


class AmbientLight(QWidget):
    """A click-through wash over ``host``. ``set_now`` recomputes the tone; a 4-minute timer keeps it current."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.tone, self.strength = tone_at(minute_of(dt.datetime.now()))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self._t = QTimer(self, interval=4 * 60 * 1000)
        self._t.timeout.connect(lambda: self.set_now(dt.datetime.now()))
        self.hide()

    def eventFilter(self, o, e):  # noqa: N802
        host = getattr(self, "host", None)                  # None while Python tears the window down
        if host is not None and o is host and e.type() == QEvent.Type.Resize:
            self.setGeometry(host.rect())
        return False

    def set_now(self, now: dt.datetime) -> None:
        self.tone, self.strength = tone_at(minute_of(now))
        self.update()

    def enable(self, on: bool) -> None:
        if on:
            self.set_now(dt.datetime.now())
            self.setGeometry(self.host.rect())
            self.show()
            self.raise_()
            self._t.start()
        else:
            self._t.stop()
            self.hide()

    def paintEvent(self, _e) -> None:  # noqa: N802
        if self.strength <= 0.001:
            return
        pal = _fpal(self.host)
        dark = QColor(pal["bg"]).lightness() < 128
        a = self.strength * (1.0 if dark else 0.7)                       # on paper the same tint would read as a stain
        w, h = self.width(), self.height()
        # start side (right in RTL): the light comes in from the top corner and dies out before the middle of the page
        c = QPointF(w * (0.92 if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else 0.08), -h * 0.12)
        rad = max(w, h) * 0.85
        g = QRadialGradient(c, rad)
        col = QColor(self.tone)
        col.setAlphaF(min(1.0, a))
        g.setColorAt(0.0, col)
        col2 = QColor(col)
        col2.setAlphaF(col.alphaF() * 0.35)
        g.setColorAt(0.5, col2)
        col3 = QColor(col)
        col3.setAlpha(0)
        g.setColorAt(1.0, col3)
        p = QPainter(self)
        p.fillRect(self.rect(), g)
