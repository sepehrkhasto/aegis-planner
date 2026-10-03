# SPDX-License-Identifier: GPL-3.0-or-later
"""Command palette: Persian quick-add parser, quick-add row, theme switching, undo of a quick-added task."""
import datetime as dt

import pytest

from aegis_desktop.core import jalali
from aegis_desktop.core.nlp import parse_quick
from aegis_desktop.ui.main_window import Palette
from test_gui import setup_vault, win  # noqa: F401

T = dt.date(2026, 9, 30)                                             # a Wednesday


def _due(d):
    return jalali.date_to_due(d)


@pytest.mark.parametrize("text,title,date,tm,cmd", [
    ("تسک بساز فردا ساعت ۱۰", "", T + dt.timedelta(1), "10:00", True),
    ("فردا ساعت ۱۰ جلسه با استاد تسک بساز", "جلسه با استاد", T + dt.timedelta(1), "10:00", True),
    ("تسک بساز خرید نان", "خرید نان", None, "", True),
    ("جلسه سه‌شنبه ۱۶:30", "جلسه", T + dt.timedelta(6), "16:30", False),
    ("جلسه چهارشنبه", "جلسه", T + dt.timedelta(7), "", False),           # today is Wednesday -> next week
    ("۳ روز دیگر مطالعه", "مطالعه", T + dt.timedelta(3), "", False),
    ("ساعت 8 عصر ورزش", "ورزش", T, "20:00", False),
    ("خرید ۲ کیلو سیب", "خرید 2 کیلو سیب", None, "", False),             # a bare number is title text
    ("new task call mom tomorrow 9am", "call mom", T + dt.timedelta(1), "09:00", True),
    ("تسک بساز پس‌فردا", "", T + dt.timedelta(2), "", True),
    ("بساز امتحان ۱۴۰۵/۷/۲۰", "امتحان", jalali._jymd_to_date(1405, 7, 20), "", True),
    ("تسک بساز ۱۵ مهر تحویل پروژه", "تحویل پروژه", jalali._jymd_to_date(1405, 7, 15), "", True),
    ("ساعت ۱۲ ظهر ناهار", "ناهار", T, "12:00", False),
    ("۱۲ شب خواب", "خواب", T, "23:59", False),                               # midnight: end of that day, never noon
])
def test_parse(text, title, date, tm, cmd):
    q = parse_quick(text, T)
    assert q.title == title and q.time_from == tm and q.is_command == cmd
    assert q.due == (_due(date) if date else None)


def test_parse_hostile():
    for s in ["", "   ", "تسک", "ساعت", "۹۹:۹۹", "۳۰ اسفند", "x" * 5000, "‌‏", "ساعت ۲۵"]:
        q = parse_quick(s, T)
        assert isinstance(q.title, str)
    assert parse_quick("۳۰ اسفند جشن", dt.date(2026, 9, 30)).title in ("جشن", "۳۰ اسفند جشن", "30 اسفند جشن")


def _rows(p):
    return [(p.list.item(i).data(0x100)[0], p.list.item(i).text()) for i in range(p.list.count())]


def test_palette_quick_add_and_undo(win):
    setup_vault(win)
    n = len(win.store.vault["tasks"])
    p = Palette(win)
    p.q.setText("تسک بساز فردا ساعت ۱۰ جلسه")
    rows = _rows(p)
    assert rows[1][0] == "create" and "جلسه" in rows[1][1] and p.list.currentRow() == 1
    p._go()
    ts = win.store.vault["tasks"]
    assert len(ts) == n + 1
    t = ts[-1]
    assert t["title"] == "جلسه" and t["timeFrom"] == "10:00"
    assert jalali.due_to_date(t["due"]) == dt.date.today() + dt.timedelta(1)
    win.perform_undo()
    assert len(win.store.vault["tasks"]) == n


def test_palette_plain_search_has_no_create_row(win):
    setup_vault(win)
    p = Palette(win)
    p.q.setText("گزارش")
    assert all(k != "create" for k, _ in _rows(p))


def test_palette_theme_switch(win):
    setup_vault(win)
    p = Palette(win)
    p.q.setText("نیمه‌شب")
    assert ("cmd", "تم: نیمه‌شب") in _rows(p)
    for i in range(p.list.count()):
        if p.list.item(i).data(0x100) == ("cmd", "theme:midnight"):
            p.list.setCurrentRow(i)
    p._go()
    assert win.prefs["palette"] == "midnight" and win.theme == "dark"
    p2 = Palette(win)
    p2.q.setText("theme")
    assert all(k != "theme:midnight" for _, k in [(0, p2.list.item(i).data(0x100)[1]) for i in range(p2.list.count())])


def test_palette_lock_command(win):
    setup_vault(win)
    p = Palette(win)
    p.q.setText("قفل")
    for i in range(p.list.count()):
        if p.list.item(i).data(0x100) == ("cmd", "lock"):
            p.list.setCurrentRow(i)
    p._go()
    assert not win.store.is_unlocked
