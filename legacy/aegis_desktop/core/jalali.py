# SPDX-License-Identifier: GPL-3.0-or-later
"""Jalali <-> Gregorian conversion (port of jalaali-js, MIT) + display helpers."""
from __future__ import annotations

from functools import lru_cache as _lru

import datetime as _dt

_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]

MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
# Week starts on Saturday (index 0). Python weekday(): Mon=0 ... Sun=6
WEEKDAYS_FA = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
WEEKDAYS_SHORT = ["ش", "ی", "د", "س", "چ", "پ", "ج"]

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n) -> str:
    return str(n).translate(_FA_DIGITS)


def _div(a: int, b: int) -> int:
    return int(a / b) if (a >= 0) == (b >= 0) else -int(-a / b)


def _mod(a: int, b: int) -> int:
    return a - _div(a, b) * b


def _jal_cal(jy: int) -> dict:
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    if jy < jp or jy >= _BREAKS[bl - 1]:
        raise ValueError(f"Invalid Jalali year {jy}")
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(_mod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(_mod(n, 33) + 3, 4)
    if _mod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = _mod(_mod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return {"leap": leap, "gy": gy, "march": march}


def is_leap(jy: int) -> bool:
    return _jal_cal(jy)["leap"] == 0


def month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_leap(jy) else 29


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + \
        _div(153 * _mod(gm + 9, 12) + 2, 5) + gd - 34840408
    d = d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752
    return d


def _d2g(jdn: int) -> tuple[int, int, int]:
    j = 4 * jdn + 139361631
    j = j + _div(_div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = _div(_mod(j, 1461), 4) * 5 + 308
    gd = _div(_mod(i, 153), 5) + 1
    gm = _mod(_div(i, 153), 12) + 1
    gy = _div(j, 1461) - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _j2d(jy: int, jm: int, jd: int) -> int:
    r = _jal_cal(jy)
    return _g2d(r["gy"], 3, r["march"]) + (jm - 1) * 31 - _div(jm, 7) * (jm - 7) + jd - 1


def _d2j(jdn: int) -> tuple[int, int, int]:
    gy = _d2g(jdn)[0]
    jy = gy - 621
    r = _jal_cal(jy)
    jdn1f = _g2d(gy, 3, r["march"])
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), _mod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if r["leap"] == 1:
            k += 1
    return jy, 7 + _div(k, 30), _mod(k, 30) + 1


def to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    return _d2j(_g2d(gy, gm, gd))


def to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    return _d2g(_j2d(jy, jm, jd))


# ---- vault due-date helpers: {"jy":..,"jm":..,"jd":..} <-> datetime.date ----
@_lru(maxsize=16384)
def _jymd_to_date(jy: int, jm: int, jd: int) -> _dt.date | None:
    """None for a day that does not exist (31 Mehr, 30 Esfand of a common year...) - never a silent roll-over."""
    try:
        if not (1 <= jm <= 12 and 1 <= jd <= month_length(jy, jm)):
            return None
    except ValueError:                                            # year outside the supported table
        return None
    try:
        gy, gm, gd = to_gregorian(jy, jm, jd)
        return _dt.date(gy, gm, gd)
    except (ValueError, OverflowError):
        return None


@_lru(maxsize=16384)
def _date_to_jymd(ordinal: int) -> tuple[int, int, int]:
    d = _dt.date.fromordinal(ordinal)
    return to_jalali(d.year, d.month, d.day)


def due_to_date(due: dict | None) -> _dt.date | None:
    """Pure + memoised: calendars and reports call this thousands of times per repaint."""
    if not due:
        return None
    try:
        return _jymd_to_date(int(due["jy"]), int(due["jm"]), int(due["jd"]))
    except (KeyError, ValueError, TypeError):
        return None


def date_to_due(d: _dt.date) -> dict:
    jy, jm, jd = _date_to_jymd(d.toordinal())
    return {"jy": jy, "jm": jm, "jd": jd}


def today_jalali() -> dict:
    return date_to_due(_dt.date.today())


def label(due: dict | None, with_year: bool = False) -> str:
    if not due:
        return ""
    try:
        s = f"{fa(due['jd'])} {MONTHS_FA[int(due['jm']) - 1]}" if 1 <= int(due["jm"]) <= 12 else ""
    except (KeyError, TypeError, ValueError):
        return ""
    if not s:
        return ""
    if with_year:
        s += f" {fa(due['jy'])}"
    return s


def weekday_index(d: _dt.date) -> int:
    """0 = Saturday ... 6 = Friday."""
    return (d.weekday() + 2) % 7
