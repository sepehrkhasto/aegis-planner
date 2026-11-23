# SPDX-License-Identifier: GPL-3.0-or-later
"""Auto theme by sunset: a day theme while the sun is up, a night theme after it goes down.

The sun's times come from the standard solar-declination formula (good to a few minutes) for a fixed place - Tehran, where
the planner's users mostly are - so nothing is looked up, no location is requested and nothing leaves the computer.
``SunWatcher`` checks every few minutes and asks the window to switch only when the phase really changes."""
from __future__ import annotations

import datetime as dt
import math

from PyQt6.QtCore import QObject, QTimer

LAT, LON = 35.70, 51.42                      # Tehran
DAY_DEFAULT, NIGHT_DEFAULT = "ivory", "noir"


def sun_times(day: dt.date, lat: float = LAT, lon: float = LON, utc_offset_h: float = 3.5) -> tuple[float, float] | None:
    """(sunrise, sunset) as local hours of the day (0-24), or None when the sun never rises or sets that day."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365.0 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))        # equation of time, minutes
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    phi = math.radians(lat)
    c = (math.cos(math.radians(90.833)) - math.sin(phi) * math.sin(decl)) / (math.cos(phi) * math.cos(decl))
    if c <= -1 or c >= 1:
        return None
    ha = math.degrees(math.acos(c))
    noon = (720 - 4 * lon - eqt) / 60.0 + utc_offset_h
    return noon - ha / 15.0, noon + ha / 15.0


def is_daylight(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now().astimezone()
    off = now.utcoffset()
    h = (off.total_seconds() / 3600.0) if off is not None else 3.5
    t = sun_times(now.date(), utc_offset_h=h)
    if t is None:
        return True
    hour = now.hour + now.minute / 60.0
    return t[0] <= hour < t[1]


class SunWatcher(QObject):
    """Calls ``on_change(is_day)`` when the sun rises or sets (and once when switched on)."""

    def __init__(self, on_change, parent=None, minutes: int = 5):
        super().__init__(parent)
        self._cb = on_change
        self._last: bool | None = None
        self._timer = QTimer(self, interval=minutes * 60_000)
        self._timer.timeout.connect(self.check)

    def enable(self, on: bool) -> None:
        if on:
            self._last = None
            self._timer.start()
            self.check()
        else:
            self._timer.stop()

    def check(self) -> None:
        day = is_daylight()
        if day != self._last:
            self._last = day
            self._cb(day)
