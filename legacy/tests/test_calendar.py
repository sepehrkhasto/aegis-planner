# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar: every view, Jalali month edges, multi-day tasks, drag-move, filters, hostile data and speed."""
import datetime as dt
import time

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest

from aegis_desktop.core import jalali, logic
from test_gui import setup_vault, win  # noqa: F401


def _cal(win):
    setup_vault(win)
    win.show_page("calendar")
    QTest.qWait(30)
    return win.pages["calendar"]


def _mid_morning(monkeypatch):
    """Working-hours scrolling depends on the clock (just after midnight the right answer IS the top): pin it to 10:00."""
    import types
    from aegis_desktop.ui import calendar_view

    class _Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime.combine(dt.date.today(), dt.time(10, 0))
    fake = types.SimpleNamespace(**{k: getattr(dt, k) for k in dir(dt) if not k.startswith("__")})
    fake.datetime = _Clock
    monkeypatch.setattr(calendar_view, "dt", fake)


def _task(v, title, day, **kw):
    t = logic.new_task(title, due=jalali.date_to_due(day), **kw)
    v["tasks"].append(t)
    return t


@pytest.mark.parametrize("view", [0, 1, 2, 3, 4])
def test_every_view_renders_at_many_sizes(win, view):
    cp = _cal(win)
    v = win.store.vault
    for i in range(8):
        _task(v, f"کار {i}", dt.date.today() + dt.timedelta(days=i - 2), timeFrom="09:30" if i % 2 else "")
    win.changed()
    cp._set_view(view)
    for w, h in ((1280, 800), (900, 640), (1920, 1080), (760, 560)):
        win.resize(w, h); QTest.qWait(20)
        assert not win.grab().isNull()


@pytest.mark.parametrize("key", ["ivory", "aegis-light", "midnight", "ocean", "sage-linen"])
def test_calendar_paints_in_every_theme(win, key):
    cp = _cal(win)
    win.set_pref("palette", key); QTest.qWait(20)
    for view in range(5):
        cp._set_view(view)
        assert not win.grab().isNull()


def test_month_navigation_roundtrip_and_clamps_day(win):
    cp = _cal(win)
    cp.selected = dt.date(*jalali.to_gregorian(1403, 6, 31))          # 31 Shahrivar
    cp.refresh()
    cp._shift(1)                                                        # Mehr has 30 days → day clamps, never crashes
    assert (cp.jy, cp.jm) == (1403, 7)
    assert jalali.date_to_due(cp.selected)["jd"] == 30
    start = (cp.jy, cp.jm)
    for _ in range(30):
        cp._shift(1)
    for _ in range(30):
        cp._shift(-1)
    assert (cp.jy, cp.jm) == start


@pytest.mark.parametrize("jy", [1403, 1404, 1408])
def test_esfand_and_nowruz_boundaries(win, jy):
    cp = _cal(win)
    n = jalali.month_length(jy, 12)
    assert n == (30 if jalali.is_leap(jy) else 29)
    cp.selected = dt.date(*jalali.to_gregorian(jy, 12, n))
    cp.refresh()
    cp._shift(1)
    assert (cp.jy, cp.jm) == (jy + 1, 1)
    cp._shift(-1)
    assert (cp.jy, cp.jm) == (jy, 12)
    cp._set_view(1)
    for _ in range(3):
        cp._shift(1)
    assert not win.grab().isNull()


def test_week_and_day_and_agenda_shift_sizes(win):
    cp = _cal(win)
    d0 = cp.selected
    cp._set_view(1); cp._shift(1); assert cp.selected == d0 + dt.timedelta(days=7)
    cp._set_view(2); cp._shift(-1); assert cp.selected == d0 + dt.timedelta(days=6)
    cp._set_view(3); cp._shift(1); assert cp.selected == d0 + dt.timedelta(days=36)


def test_multiday_task_appears_on_every_day_and_moves_together(win):
    cp = _cal(win)
    v = win.store.vault
    d0 = dt.date.today() + dt.timedelta(days=3)
    t = _task(v, "سفر", d0)
    t["dueEnd"] = jalali.date_to_due(d0 + dt.timedelta(days=2))
    win.changed()
    for i in range(3):
        assert any(x["id"] == t["id"] for x in cp.filtered(d0 + dt.timedelta(days=i)))
    assert not any(x["id"] == t["id"] for x in cp.filtered(d0 + dt.timedelta(days=3)))
    cp._move(t["id"], d0 + dt.timedelta(days=5))
    assert jalali.due_to_date(t["due"]) == d0 + dt.timedelta(days=5)
    assert jalali.due_to_date(t["dueEnd"]) == d0 + dt.timedelta(days=7)


def test_move_to_same_day_or_unknown_task_is_a_noop(win):
    cp = _cal(win)
    t = _task(win.store.vault, "x", dt.date.today())
    before = dict(t["due"])
    cp._move(t["id"], dt.date.today())
    cp._move("nope", dt.date.today() + dt.timedelta(days=1))
    assert t["due"] == before


def test_filters_status_and_category(win):
    cp = _cal(win)
    v = win.store.vault
    a = _task(v, "a", dt.date.today(), cat="work")
    b = _task(v, "b", dt.date.today(), cat="study"); b["done"] = True
    win.changed()
    ids = lambda: {x["id"] for x in cp.filtered(dt.date.today())}  # noqa: E731
    assert {a["id"], b["id"]} <= ids()
    cp.status.setCurrentIndex(cp.status.findData("open")); assert b["id"] not in ids() and a["id"] in ids()
    cp.status.setCurrentIndex(cp.status.findData("done")); assert ids() == {x["id"] for x in cp.filtered(dt.date.today()) if x.get("done")} and b["id"] in ids()
    cp.status.setCurrentIndex(0)
    cp.cat.setCurrentIndex(cp.cat.findData("study")); assert ids() == {b["id"]}


def test_day_list_toggle_updates_task_and_survives_rebuild(win):
    cp = _cal(win)
    n = cp.day_list.count()
    assert n >= 1
    it = cp.day_list.item(0)
    tid = it.data(Qt.ItemDataRole.UserRole)
    it.setCheckState(Qt.CheckState.Checked)
    x = next(t for t in win.store.vault["tasks"] if t["id"] == tid)
    assert x["done"]
    assert cp.day_list.count() == n                                     # still listed, now ticked


def test_month_click_selects_and_drag_moves(win):
    cp = _cal(win)
    v = win.store.vault
    t = _task(v, "dragme", dt.date.today())
    win.changed(); cp._set_view(0); QTest.qWait(30)
    win.grab()                                                          # paint once so cell/chip rects exist
    m = cp.month
    tgt_rect, tgt_day = next((r, d) for r, d in m._cells if d == dt.date.today() + dt.timedelta(days=2))
    chip = next(r for r, tid in m._chips if tid == t["id"])
    QTest.mousePress(m, Qt.MouseButton.LeftButton, pos=chip.center().toPoint())
    QTest.mouseMove(m, tgt_rect.center().toPoint())
    QTest.mouseRelease(m, Qt.MouseButton.LeftButton, pos=tgt_rect.center().toPoint())
    assert jalali.due_to_date(t["due"]) == tgt_day
    QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=tgt_rect.center().toPoint() + QPointF(0, 0).toPoint())
    assert cp.selected == tgt_day


def test_hostile_tasks_never_crash_any_view(win):
    cp = _cal(win)
    v = win.store.vault
    v["tasks"] += [
        {"id": "b1", "title": "no due"},
        {"id": "b2", "title": "end before start", "due": jalali.date_to_due(dt.date.today()),
         "dueEnd": jalali.date_to_due(dt.date.today() - dt.timedelta(days=9))},
        {"id": "b3", "title": "huge span", "due": jalali.date_to_due(dt.date.today()),
         "dueEnd": jalali.date_to_due(dt.date.today() + dt.timedelta(days=9000))},
        {"id": "b4", "title": "bad time", "due": jalali.date_to_due(dt.date.today()), "timeFrom": "99:99", "timeTo": "zz"},
        {"id": "b5", "title": "overnight", "due": jalali.date_to_due(dt.date.today()), "timeFrom": "23:00", "timeTo": "01:00"},
        {"id": "b6", "title": "x" * 500, "due": jalali.date_to_due(dt.date.today())},
    ]
    win.changed()
    for view in range(4):
        cp._set_view(view)
        assert not win.grab().isNull()


def test_empty_vault_all_views(win):
    cp = _cal(win)
    win.store.vault["tasks"].clear(); win.changed()
    for view in range(4):
        cp._set_view(view)
        assert not win.grab().isNull()
    assert cp.day_list.count() == 0


def test_speed_with_4000_tasks(win):
    cp = _cal(win)
    v = win.store.vault
    for i in range(4000):
        _task(v, f"t{i}", dt.date.today() + dt.timedelta(days=i % 60 - 20), timeFrom=("%02d:00" % (i % 24)) if i % 3 else "")
    win.changed()
    for view, budget in ((0, 0.35), (1, 0.35), (2, 0.35), (3, 0.35)):
        cp._set_view(view)
        t0 = time.perf_counter()
        for _ in range(3):
            cp.refresh(); cp.grab()
        avg = (time.perf_counter() - t0) / 3
        assert avg < budget, f"view {view}: {avg:.3f}s"


def test_calendar_page_does_not_leak_timers_when_hidden(win):
    cp = _cal(win)
    assert cp._tick.isActive()
    win.show_page("today"); QTest.qWait(30)
    assert not cp._tick.isActive()


def test_week_and_day_open_scrolled_to_the_working_hours(win, monkeypatch):
    _mid_morning(monkeypatch)
    cp = _cal(win)
    cp._set_view(2)
    QTest.qWait(300)
    assert cp.day_sc.verticalScrollBar().value() > 0
    cp._set_view(1)
    QTest.qWait(300)
    assert cp.week_sc.verticalScrollBar().value() > 0


def test_header_stays_pinned_and_clickable_while_scrolled(win, monkeypatch):
    _mid_morning(monkeypatch)
    cp = _cal(win)
    v = win.store.vault
    t = _task(v, "تمام‌روز", dt.date.today())
    win.changed(); cp._set_view(2); QTest.qWait(300)
    sb = cp.day_sc.verticalScrollBar()
    assert sb.value() > 0
    win.grab()
    g = cp.day
    assert g._sticky and all(r.top() >= sb.value() for r, _ in g._sticky)          # drawn at the top of the viewport
    r, tid = g._sticky[0]
    assert g._hit(r.center()) == tid
    assert g._hit(QPointF(50, sb.value() + 5)) is None                             # nothing behind the header is hit


def test_slide_transition_runs_and_cleans_up(win):
    cp = _cal(win)
    cp._set_view(0)
    cp._shift(1)
    assert getattr(cp.stack, "_slide", None) is not None
    QTest.qWait(500)
    assert not [c for c in cp.stack.children() if type(c).__name__ == "_Slide" and c.isVisible()]
    from aegis_desktop.ui import anim
    anim.MOTION[0] = False
    try:
        cp._shift(-1)
        assert cp.stack.children().count(cp.stack._slide) == 0 or not cp.stack._slide.isVisible()
    finally:
        anim.MOTION[0] = True
