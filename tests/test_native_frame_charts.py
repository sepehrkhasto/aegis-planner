# SPDX-License-Identifier: GPL-3.0-or-later
"""native frame, focus watch face, branded charts + KPI sparklines, command palette v2."""
import datetime as dt

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtTest import QTest

from aegis_desktop.core import logic
from aegis_desktop.ui import charts, theme, winchrome
from aegis_desktop.ui.main_window import Palette
from test_gui import setup_vault, win  # noqa: F401


# ------------------------------------------------------------------------------------------------ M1 frame ---
def test_frame_attrs_follow_palette():
    pal = theme.PALETTES["dark"]
    attrs = dict(winchrome.frame_attrs(pal, True))
    assert attrs[winchrome.ATTR_DARK] == 1
    c = QColor(pal["bg"])
    assert attrs[winchrome.ATTR_CAPTION] == (c.red() | c.green() << 8 | c.blue() << 16)
    assert winchrome.ATTR_BORDER in attrs and attrs[winchrome.ATTR_CORNER] == winchrome.CORNER_ROUND
    assert dict(winchrome.frame_attrs(theme.PALETTES["light"], False))[winchrome.ATTR_DARK] == 0


def test_apply_to_calls_dwm_and_survives_failures():
    calls = []

    class Dwm:
        def DwmSetWindowAttribute(self, hwnd, attr, ref, size):  # noqa: N802
            calls.append(attr)

    assert winchrome.apply_to(Dwm(), 1, theme.PALETTES["dark"], True) == 5 and len(calls) == 5

    class Bad:
        def DwmSetWindowAttribute(self, hwnd, attr, ref, size):  # noqa: N802
            if attr == winchrome.ATTR_CAPTION:
                raise OSError("old windows")

    assert winchrome.apply_to(Bad(), 1, theme.PALETTES["dark"], True) == 4      # one unsupported attribute fails alone


# ------------------------------------------------------------------------------------------- M2 watch face ---
def test_focus_dial_paints_all_states(win):
    setup_vault(win)
    win.show_page("focus"); QTest.qWait(120)
    d = win.pages["focus"].dial
    for mode in ("work", "break"):
        for running in (False, True):
            d.set_state("24:59", 0.63, mode, running, 5, "تمرکز"); QTest.qWait(30)
            assert not d.grab().isNull()
    d.set_state("00:00", 1.0, "work", True, 0, ""); QTest.qWait(30)
    assert not d.grab().isNull()


def test_focus_dial_time_is_latin_and_stable_width(win):
    setup_vault(win)
    win.show_page("focus"); QTest.qWait(120)
    d = win.pages["focus"].dial
    d.set_state("11:11", 0.2, "work", False, 0, "x"); QTest.qWait(30)
    a = d.grab().toImage()
    d.set_state("00:00", 0.2, "work", False, 0, "x"); QTest.qWait(30)
    b = d.grab().toImage()
    assert a != b


# --------------------------------------------------------------------------------------------- M3 charts ---
def _move(w, x, y):
    pt = QPointF(x, y)
    w.window().windowHandle()
    ev = QMouseEvent(QEvent.Type.MouseMove, pt, w.mapToGlobal(pt), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    from PyQt6.QtWidgets import QApplication
    QApplication.sendEvent(w, ev)


def test_area_chart_follows_theme_colours_live(qtbot):
    a = charts.AreaChart("dark")
    old = list(charts.CHART)
    try:
        charts.CHART[0], charts.CHART[3] = "#112233", "#445566"
        assert a.color.name() == "#112233" and a.color2.name() == "#445566"
    finally:
        charts.CHART[:] = old
    fixed = charts.AreaChart("dark", color="#ff0000")
    assert fixed.color.name() == "#ff0000"


def test_area_hover_crosshair_and_glass_tooltip(qtbot):
    a = charts.AreaChart("dark")
    qtbot.addWidget(a); a.resize(560, 260); a.show()
    a.set_data([(str(i), (i * 7) % 9) for i in range(20)], second=[(i * 5) % 8 for i in range(20)])
    qtbot.wait(1000)
    base = a.grab().toImage()
    _move(a, 260, 120); qtbot.wait(300)
    assert a._hover is not None
    assert a._tt_p > 0.95 and a._tt_key is not None
    assert a.grab().toImage() != base                       # crosshair + tooltip drawn
    a.leaveEvent(None)
    assert a._hover is None and a._tt_key is None


def test_tooltip_key_changes_restart_fade(qtbot):
    a = charts.AreaChart("dark")
    qtbot.addWidget(a); a.resize(560, 260); a.show()
    a.set_data([(str(i), i) for i in range(10)])
    qtbot.wait(1000)
    _move(a, 100, 100); qtbot.wait(250)
    k1 = a._tt_key
    _move(a, 400, 100); qtbot.wait(20)
    assert a._tt_key != k1


def test_kpi_sparkline_draws_and_needs_three_points(win):
    setup_vault(win)
    win.show_page("today"); QTest.qWait(1300)
    t = win.pages["today"].tiles["done"]
    t.set("۳", "انجام‌شده امروز", spark=[0, 1, 2, 1, 4, 2, 3]); QTest.qWait(50)
    assert t.spark and len(t.spark) == 7
    with_spark = t.grab().toImage()
    t.set("۳", "انجام‌شده امروز", spark=[1, 2]); QTest.qWait(1200)
    assert t.spark is None
    assert t.grab().toImage() != with_spark
    t.set("۳", "x", spark=[2, 2, 2, 2]); QTest.qWait(50)
    assert not t.grab().isNull()                           # a flat series must not divide by zero


def test_today_tiles_get_sparks_from_vault(win):
    setup_vault(win)
    v = win.store.vault
    for i in range(6):
        t = logic.new_task(f"t{i}")
        t["done"], t["doneAt"] = True, (dt.datetime.now() - dt.timedelta(days=i)).isoformat()
        v["tasks"].append(t)
    win.changed(); win.show_page("today"); QTest.qWait(400)
    tl = win.pages["today"].tiles
    assert tl["done"].spark and tl["open"].spark and tl["overdue"].spark is None


# --------------------------------------------------------------------------------------------- M4 palette ---
def _kinds(p):
    return [(p.list.item(i).data(0x100)[0], p.list.item(i).text()) for i in range(p.list.count())]


def test_palette_is_frameless_glass(win):
    setup_vault(win)
    p = Palette(win)
    assert p.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert p.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    p.show(); QTest.qWait(300)
    assert not p.grab().isNull()
    p.close()


def test_palette_preview_follows_selection(win):
    setup_vault(win)
    win.store.vault["tasks"].append(logic.new_task("جلسهٔ ویژه", pr="high"))
    p = Palette(win)
    p.q.setText("ویژه")
    assert p.preview.title == "جلسهٔ ویژه" and "زیاد" in p.preview.meta and p.preview.hint == "ویرایش"
    p.q.setText("")
    assert p.preview.title and p.preview.hint == "باز کردن"          # a page row
    p.q.setText("zzzz-nothing")
    assert p.preview.title == ""


def test_palette_recent_section_and_pruning(win, monkeypatch):
    setup_vault(win)
    opened = []
    monkeypatch.setattr(win, "edit_task_id", lambda tid: opened.append(tid))
    t = logic.new_task("کار موقت")
    win.store.vault["tasks"].append(t)
    p = Palette(win)
    assert not any(k == "hdr" and txt == "اخیراً" for k, txt in _kinds(p))          # nothing yet
    p.q.setText("موقت"); p._go()
    assert opened == [t["id"]]
    p2 = Palette(win)
    rows = _kinds(p2)
    assert rows[0] == ("hdr", "اخیراً") and rows[1] == ("task", "کار موقت")
    assert p2.list.currentRow() == 1                                              # Enter runs the newest recent item
    win.store.vault["tasks"].remove(t)                                            # a deleted task disappears from recents
    assert not any(k == "task" for k, _ in _kinds(Palette(win)))


def test_palette_recent_is_capped_and_deduped(win):
    setup_vault(win)
    p = Palette(win)
    for key in ("today", "tasks", "calendar", "kanban", "notes", "habits", "today"):
        p._remember("page", key, key, key)
    rec = win.prefs["palette_recent"]
    assert len(rec) == Palette.RECENT_MAX and rec[0][1] == "today" and [r[1] for r in rec].count("today") == 1


def test_palette_survives_garbage_recent(win):
    setup_vault(win)
    win.prefs["palette_recent"] = ["x", [1], None, ["page", "nope", "a", "b"], ["zzz", "k", "l", "i"]]
    assert not any(k == "hdr" and t == "اخیراً" for k, t in _kinds(Palette(win)))


def test_palette_rise_animation_respects_reduce_motion(win, qtbot):
    setup_vault(win)
    from aegis_desktop.ui.anim import MOTION
    old = MOTION[0]
    try:
        MOTION[0] = False
        p = Palette(win); qtbot.addWidget(p); p.show()
        assert getattr(p, "_rise", None) is None
        MOTION[0] = True
        p2 = Palette(win); qtbot.addWidget(p2); p2.show()
        assert p2._rise is not None
    finally:
        MOTION[0] = old
