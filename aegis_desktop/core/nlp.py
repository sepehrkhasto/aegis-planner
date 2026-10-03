# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiny Persian/English quick-add parser for the command palette: «تسک بساز فردا ساعت ۱۰ جلسه با استاد».

Pure and offline. ``parse_quick(text, today)`` -> ``QuickTask(title, due, time_from, is_command)``.
Understands: امروز / فردا / پس‌فردا / weekday names / «۳ روز دیگر» / «هفته بعد» / «۱۵ مهر» / «۱۴۰۵/۷/۱۵»,
times «ساعت ۱۰», «ساعت ۱۰:۳۰», «۱۰ عصر», «22:15», and command words (تسک بساز / اضافه کن / new task / add).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from . import jalali

_DIG = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_FIX = str.maketrans({"ي": "ی", "ك": "ک", "‌": " ", "\u200f": " ", "\u200e": " "})

_CMD = [r"تسک\s+(?:جدید\s+)?بساز", r"تسک\s+جدید", r"یک\s+تسک\s+بساز", r"بساز", r"اضافه\s+کن", r"اضافه", r"ایجاد\s+کن",
        r"new\s+task", r"add\s+task", r"add", r"create", r"todo", r"تسک"]
_MONTHS = {m.replace("‌", " "): i + 1 for i, m in enumerate(jalali.MONTHS_FA)}
_WD = {"شنبه": 0, "یکشنبه": 1, "یک شنبه": 1, "دوشنبه": 2, "دو شنبه": 2, "سه شنبه": 3, "چهارشنبه": 4,
       "چهار شنبه": 4, "پنجشنبه": 5, "پنج شنبه": 5, "جمعه": 6}
_PM = ("عصر", "شب", "بعد از ظهر", "بعدازظهر", "pm")
_AM = ("صبح", "am")


@dataclass
class QuickTask:
    title: str
    due: dict | None
    time_from: str
    is_command: bool


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_DIG).translate(_FIX)).strip()


def _cut(s: str, m: re.Match) -> str:
    return (s[:m.start()] + " " + s[m.end():])


_STOP = ("برای", "در", "تا", "واسه", "ساعت", "روز")


def _cutd(s: str, m: re.Match) -> str:
    """Cut a date / time token, and with it the one linking word directly in front of it («برای فردا», «تا ۱۰:۳۰»);
    the same words elsewhere in the title («جلسه در دانشگاه») stay."""
    left = s[:m.start()].rstrip()
    for w in _STOP:
        if left == w or left.endswith(" " + w):
            left = left[:len(left) - len(w)].rstrip()
            break
    return left + " " + s[m.end():]


def _time(s: str):
    """-> (HH:MM | "", rest)."""
    for m in re.finditer(r"(ساعت\s*)?(?<![\d/:])([01]?\d|2[0-3])(?::([0-5]\d))?\s*(صبح|عصر|شب|بعد ?از ?ظهر|ظهر|am|pm)?(?![\w/:])", s, re.I):
        has_word, h, mi, ap = m.group(1), int(m.group(2)), m.group(3), (m.group(4) or "").lower()
        if not (has_word or mi or ap):
            continue                                                  # a bare number is part of the title
        if ap == "شب" and h < 6:
            pass                                                      # «۱ شب» is 01:00, not 13:00
        elif ap and any(ap.replace(" ", "").startswith(x.replace(" ", "")) for x in _PM) and h < 12:
            h += 12
        elif ap == "ظهر" and h < 11:
            h += 12
        elif ap and ap.startswith(_AM) and h == 12:
            h = 0
        elif ap == "شب" and h == 12 and not mi:
            return "23:59", _cutd(s, m)                               # «۱۲ شب» without minutes: end of the day
        elif ap == "شب" and h == 12:
            h = 0
        return f"{h:02d}:{int(mi or 0):02d}", _cutd(s, m)
    return "", s


def _date(s: str, today: dt.date):
    """-> (date | None, rest)."""
    m = re.search(r"(?<!\d)(\d{4})/(\d{1,2})/(\d{1,2})(?!\d)", s)
    if m:
        d = jalali._jymd_to_date(int(m[1]), int(m[2]), int(m[3]))
        if d:
            return d, _cutd(s, m)
    for pat, off in ((r"پس ?فردا", 2), (r"فردا", 1), (r"امروز", 0), (r"دیروز", -1), (r"today", 0), (r"tomorrow", 1)):
        m = re.search(pat, s, re.I)
        if m:
            return today + dt.timedelta(days=off), _cutd(s, m)
    m = re.search(r"(?<!\d)(\d{1,3}) ?روز (?:دیگه|دیگر|بعد|آینده)", s)
    if m:
        return today + dt.timedelta(days=int(m[1])), _cutd(s, m)
    m = re.search(r"هفته (?:بعد|آینده|دیگه)", s)
    if m:
        return today + dt.timedelta(days=7), _cutd(s, m)
    jy, jm, jd = jalali.to_jalali(today.year, today.month, today.day)
    m = re.search(r"(?<!\d)(\d{1,2}) ?(" + "|".join(sorted(map(re.escape, _MONTHS), key=len, reverse=True)) + r")(?!\S)", s)
    if m:
        dd, mm = int(m[1]), _MONTHS[m[2]]
        ym = re.match(r"\s*(1[34]\d\d)(?!\d)", s[m.end():])         # «۱۵ مهر ۱۴۰۶»: an explicit year wins
        if ym:
            d = jalali._jymd_to_date(int(ym[1]), mm, dd)
            if d:
                return d, _cutd(s[:m.end()] + s[m.end() + ym.end():], m)
        d = jalali._jymd_to_date(jy, mm, dd)
        if d and d < today:
            d = jalali._jymd_to_date(jy + 1, mm, dd)
        if d:
            return d, _cutd(s, m)
    cur = jalali.weekday_index(today)
    for name in sorted(_WD, key=len, reverse=True):
        m = re.search(r"(?<!\S)" + name + r"(?!\S)", s)
        if m:
            return today + dt.timedelta(days=(_WD[name] - cur) % 7 or 7), _cutd(s, m)
    return None, s


def parse_quick(text: str, today: dt.date | None = None) -> QuickTask:
    today = today or dt.date.today()
    s = _norm(text)
    is_cmd = False
    for c in _CMD[:-1]:                                              # the bare word «تسک» is only stripped at the start
        m = re.search(r"(?<!\S)" + c + r"(?!\S)", s, re.I)
        if m:
            is_cmd = True
            s = _cut(s, m)
            break
    else:
        m = re.match(r"تسک(?!\S)", s)
        if m:
            is_cmd, s = True, s[m.end():]
    tm, s = _time(s)
    d, s = _date(s, today)
    title = re.sub(r"\s+", " ", s).strip(" -–:،,")
    if tm and not d:
        d = today
    return QuickTask(title, jalali.date_to_due(d) if d else None, tm, is_cmd)
