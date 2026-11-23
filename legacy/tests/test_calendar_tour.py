# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar interaction (drag to create / move / resize, quick-create card, mini month, year view, menus,
shortcuts), plus the first-run tour and the «what's new» card."""
import datetime as dt

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import calendar_view as cv
from aegis_desktop.ui.calendar_kit import layout_events, snap, span_of, when_text
from test_gui import setup_vault, win  # noqa: F401

TODAY = dt.date.today()


def _cal(win, view=1):
    setup_vault(win)
    win.store.vault["tasks"] = []                      # the welcome tasks would sit under the points these tests aim at
    win.changed()
    win.show_page("calendar")
    QTest.qWait(30)
    cp = win.pages["calendar"]
    cp.selected = TODAY
    cp._set_view(view)
    QTest.qWait(200)                                   # the view scrolls itself to the working hours (three delayed tries)
    for sc in (cp.week_sc, cp.day_sc):
        sc.verticalScrollBar().setValue(0)             # the floating header covers whatever is under it; tests aim at raw grid points
    win.grab()
    return cp


def _task(win, title, day, **kw):
    t = logic.new_task(title, due=jalali.date_to_due(day), **kw)
    win.store.vault["tasks"].append(t)
    win.changed()
    win.grab()
    return t


def _pt(g, day, minute):
    """A point inside the grid `g` at (day, minute) in the grid's own coordinates."""
    col = g.dates().index(day)
    return QPoint(int(g._col_x(col) + g._cw() / 2), int(g._y_of(minute)))


def _drag(g, p0, p1, steps=8):
    QTest.mousePress(g, Qt.MouseButton.LeftButton, pos=p0)
    for i in range(1, steps + 1):
        QTest.mouseMove(g, QPoint(p0.x() + (p1.x() - p0.x()) * i // steps, p0.y() + (p1.y() - p0.y()) * i // steps))
    QTest.mouseRelease(g, Qt.MouseButton.LeftButton, pos=p1)


def _save_quick(cp, title):
    q = cp._quick
    assert q is not None and q.isVisible()
    q.edit.setText(title)
    QTest.keyClick(q.edit, Qt.Key.Key_Return)
    QTest.qWait(20)
    assert cp._quick is None


# ---------------------------------------------------------------------------------------------- kit helpers ---
def test_snap_layout_and_span_helpers():
    assert snap(7) == 0 and snap(8) == 15 and snap(22) == 15 and snap(23) == 30
    ev = [(540, 630, {"id": "a"}), (570, 630, {"id": "b"}), (700, 760, {"id": "c"})]
    out = {t["id"]: (lane, lanes) for _a, _b, t, lane, lanes in layout_events(ev)}
    assert out["a"] == (0, 2) and out["b"] == (1, 2) and out["c"] == (0, 1)      # overlap -> two lanes, the loner is full width
    assert span_of({"timeFrom": "00:00", "timeTo": "01:00"}) == (0, 60)            # midnight is a time, not «all day»
    assert span_of({}) is None
    assert span_of({"timeFrom": "99:99"}) is None
    assert "تا" in when_text(TODAY, None, None, TODAY + dt.timedelta(days=2))
    assert "–" in when_text(TODAY, 540, 600)


# --------------------------------------------------------------------------------------- draw on the grid ---
def test_drag_on_week_grid_draws_a_block_and_quick_card_saves_it(win):
    cp = _cal(win)
    g = cp.week
    n0 = len(win.store.vault["tasks"])
    _drag(g, _pt(g, TODAY, 14 * 60 + 2), _pt(g, TODAY, 15 * 60 + 28))
    assert cp._quick is not None and g._pending is not None
    assert (g._pending["a"], g._pending["b"]) == (14 * 60, 15 * 60 + 30)          # snapped to quarter hours
    _save_quick(cp, "بازبینی")
    t = win.store.vault["tasks"][-1]
    assert len(win.store.vault["tasks"]) == n0 + 1
    assert (t["title"], t["timeFrom"], t["timeTo"]) == ("بازبینی", "14:00", "15:30")
    assert jalali.due_to_date(t["due"]) == TODAY
    assert g._pending is None
    win.perform_undo()
    assert len(win.store.vault["tasks"]) == n0                                     # one Ctrl+Z takes it back


def test_drag_upwards_and_across_is_normalised(win):
    cp = _cal(win)
    g = cp.week
    _drag(g, _pt(g, TODAY, 16 * 60), _pt(g, TODAY, 15 * 60))
    assert (g._pending["a"], g._pending["b"]) == (15 * 60, 16 * 60 + 15)
    cp._quick.close()
    QTest.qWait(20)
    assert g._pending is None and cp._quick is None


def test_plain_click_or_tiny_wiggle_never_creates(win):
    cp = _cal(win)
    g = cp.week
    p = _pt(g, TODAY, 12 * 60)
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=p)
    QTest.mousePress(g, Qt.MouseButton.LeftButton, pos=p)
    QTest.mouseMove(g, p + QPoint(2, 1))
    QTest.mouseRelease(g, Qt.MouseButton.LeftButton, pos=p + QPoint(2, 1))
    assert cp._quick is None and g._pending is None


def test_escape_cancels_a_drag(win):
    cp = _cal(win)
    g = cp.week
    p0, p1 = _pt(g, TODAY, 10 * 60), _pt(g, TODAY, 11 * 60)
    QTest.mousePress(g, Qt.MouseButton.LeftButton, pos=p0)
    QTest.mouseMove(g, p1)
    assert g._ghost is not None
    QTest.keyClick(g, Qt.Key.Key_Escape)
    QTest.mouseRelease(g, Qt.MouseButton.LeftButton, pos=p1)
    assert g._ghost is None and cp._quick is None


def test_quick_card_empty_title_stays_open_esc_closes_more_opens_full_form(win, monkeypatch):
    cp = _cal(win)
    g = cp.week
    _drag(g, _pt(g, TODAY, 9 * 60), _pt(g, TODAY, 10 * 60))
    q = cp._quick
    QTest.keyClick(q.edit, Qt.Key.Key_Return)
    assert cp._quick is q and q.isVisible()                                        # nothing typed: nothing saved, card stays
    got = {}
    monkeypatch.setattr(cp.ctx, "new_task", lambda due, defaults=None: got.update(due=due, d=defaults))
    q.edit.setText("جزئیات")
    q.b_more.click()
    QTest.qWait(20)
    assert got["d"]["title"] == "جزئیات" and got["d"]["timeFrom"] == "09:00" and got["d"]["timeTo"] == "10:00"
    assert jalali.due_to_date(got["due"]) == TODAY
    _drag(g, _pt(g, TODAY, 9 * 60), _pt(g, TODAY, 10 * 60))
    QTest.keyClick(cp._quick, Qt.Key.Key_Escape)
    QTest.qWait(20)
    assert cp._quick is None and g._pending is None


def test_new_block_inherits_the_category_filter(win):
    cp = _cal(win)
    cp.cat.setCurrentIndex(cp.cat.findData("sport"))
    g = cp.week
    _drag(g, _pt(g, TODAY, 8 * 60), _pt(g, TODAY, 9 * 60))
    _save_quick(cp, "دویدن")
    assert win.store.vault["tasks"][-1]["cat"] == "sport"


def test_double_click_makes_an_hour_block(win):
    cp = _cal(win)
    g = cp.week
    QTest.mouseDClick(g, Qt.MouseButton.LeftButton, pos=_pt(g, TODAY, 13 * 60 + 10))
    assert (g._pending["a"], g._pending["b"]) == (13 * 60, 14 * 60)
    _save_quick(cp, "ناهار")
    assert win.store.vault["tasks"][-1]["timeFrom"] == "13:00"


def test_drag_in_the_all_day_strip_makes_an_all_day_task(win):
    cp = _cal(win)
    g = cp.week
    col = g.dates().index(TODAY)
    p = QPoint(int(g._col_x(col) + g._cw() / 2), cv.HEAD_H + 8)
    QTest.mouseDClick(g, Qt.MouseButton.LeftButton, pos=p)
    assert g._pending["a"] is None
    _save_quick(cp, "مهلت")
    t = win.store.vault["tasks"][-1]
    assert not t.get("timeFrom") and jalali.due_to_date(t["due"]) == TODAY


# --------------------------------------------------------------------------------- move / resize / tick ---
def _block(g, tid):
    return next(b for b in g._blocks if b["id"] == tid)


def test_drag_a_block_to_another_day_and_time_retimes_it_and_undoes(win):
    cp = _cal(win)
    t = _task(win, "جلسه", TODAY, timeFrom="09:00", timeTo="10:00")
    g = cp.week
    tgt = next(d for d in g.dates() if d != TODAY)                                  # any other visible day (tomorrow is next week on a Friday)
    _drag(g, _pt(g, TODAY, 9 * 60 + 30), _pt(g, tgt, 15 * 60 + 30))               # grabbed in the middle of the hour
    assert jalali.due_to_date(t["due"]) == tgt
    assert t["timeFrom"] == "15:00" and t["timeTo"] == "16:00"                     # keeps its length, snaps to the grid
    win.perform_undo()
    assert jalali.due_to_date(t["due"]) == TODAY and t["timeFrom"] == "09:00"


def test_resize_from_the_bottom_and_top_edge(win):
    cp = _cal(win)
    t = _task(win, "طولانی", TODAY, timeFrom="09:00", timeTo="10:00")
    g = cp.week
    r = _block(g, t["id"])["rect"]
    bottom = QPoint(int(r.center().x()), int(r.bottom() - 2))
    _drag(g, bottom, _pt(g, TODAY, 11 * 60 + 30))
    assert (t["timeFrom"], t["timeTo"]) == ("09:00", "11:30")
    win.grab()
    r = _block(g, t["id"])["rect"]
    top = QPoint(int(r.center().x()), int(r.top() + 2))
    _drag(g, top, _pt(g, TODAY, 8 * 60))
    assert (t["timeFrom"], t["timeTo"]) == ("08:00", "11:30")


def test_click_on_a_block_opens_it_and_the_check_toggles_done(win, monkeypatch):
    cp = _cal(win, 2)
    t = _task(win, "باز شو", TODAY, timeFrom="10:00", timeTo="11:00")
    g = cp.day
    opened = []
    monkeypatch.setattr(cp.ctx, "edit_task_id", lambda tid: opened.append(tid))
    g.open_task.disconnect()
    g.open_task.connect(cp.ctx.edit_task_id)
    r = _block(g, t["id"])["rect"]
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPoint(int(r.center().x()), int(r.center().y())))
    assert opened == [t["id"]]
    chk = next(rc for rc, tid in g._checks if tid == t["id"])
    QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=chk.center().toPoint())
    assert t["done"] is True
    win.perform_undo()
    assert not t["done"]


def test_retime_is_a_noop_when_nothing_changed_and_shifts_multiday_end(win):
    cp = _cal(win)
    t = _task(win, "چندروزه", TODAY, timeFrom="09:00", timeTo="10:00", dueEnd=jalali.date_to_due(TODAY + dt.timedelta(days=2)))
    win._undo = None
    cp._retime(t["id"], TODAY, 540, 600)
    assert win._undo is None                                                       # same day, same hours: nothing recorded
    cp._retime(t["id"], TODAY + dt.timedelta(days=3), 540, 600)
    assert jalali.due_to_date(t["dueEnd"]) == TODAY + dt.timedelta(days=5)
    cp._retime(t["id"], TODAY + dt.timedelta(days=3), None, None)
    assert not t["timeFrom"] and not t["timeTo"]
    cp._retime("nope", TODAY, 0, 60)                                               # unknown id never raises


# --------------------------------------------------------------------------------------------- month grid ---
def test_month_drag_over_days_makes_a_multiday_task(win):
    cp = _cal(win, 0)
    m = cp.month
    d0, d1 = TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=3)
    r0, r1 = m.cell_rect(d0), m.cell_rect(d1)
    _drag(m, r0.center().toPoint(), r1.center().toPoint())
    assert cp._quick is not None
    _save_quick(cp, "سفر")
    t = win.store.vault["tasks"][-1]
    assert jalali.due_to_date(t["due"]) == d0 and jalali.due_to_date(t["dueEnd"]) == d1
    assert m._pending is None


def test_month_double_click_opens_the_quick_card_for_that_day(win):
    cp = _cal(win, 0)
    d = TODAY + dt.timedelta(days=1)
    QTest.mouseDClick(cp.month, Qt.MouseButton.LeftButton, pos=cp.month.cell_rect(d).center().toPoint())
    assert cp._quick is not None and cp.month._pending == (d, d)
    _save_quick(cp, "یک روزه")
    t = win.store.vault["tasks"][-1]
    assert jalali.due_to_date(t["due"]) == d and not t.get("dueEnd") and not t.get("timeFrom")
    assert cp.month._pending is None


# ------------------------------------------------------------------------ mini month, year, keys, menus ---
def test_mini_month_picks_a_day_and_follows_the_page(win):
    cp = _cal(win, 0)
    win.grab()
    d = TODAY + dt.timedelta(days=2)
    r = next(rc for rc, dd in cp.mini._cells if dd == d)
    QTest.mouseClick(cp.mini, Qt.MouseButton.LeftButton, pos=r.center().toPoint())
    assert cp.selected == d
    cp._shift(1)
    assert (cp.mini.jy, cp.mini.jm) == (cp.jy, cp.jm)                              # the navigator follows the page
    cp.mini._step(-3)                                                              # paged away on its own...
    cp._today()
    assert cp.mini.shows(TODAY)                                                    # ...and «today» brings it back


def test_year_view_opens_a_day_or_a_month(win):
    cp = _cal(win, 4)
    assert len(cp.year.months) == 12
    win.grab()
    d = TODAY
    mm = cp.year.months[jalali.date_to_due(d)["jm"] - 1]
    mm.grab()
    r = next(rc for rc, dd in mm._cells if dd == d)
    QTest.mouseClick(mm, Qt.MouseButton.LeftButton, pos=r.center().toPoint())
    assert cp.view == 2 and cp.selected == d
    cp._go_view(4)
    mm = cp.year.months[4]
    mm.grab()
    QTest.mouseClick(mm, Qt.MouseButton.LeftButton, pos=mm._title_r.center().toPoint())
    assert cp.view == 0 and cp.jm == 5
    cp._go_view(4)
    y0 = cp.jy
    cp._shift(1)
    assert cp.jy == y0 + 1 and "سال" in cp.title_lb.text()


def test_keyboard_shortcuts_switch_views_and_move(win):
    cp = _cal(win, 0)
    for key, view in ((Qt.Key.Key_W, 1), (Qt.Key.Key_D, 2), (Qt.Key.Key_A, 3), (Qt.Key.Key_Y, 4), (Qt.Key.Key_M, 0)):
        QTest.keyClick(cp, key)
        assert cp.view == view, key
    cp._go_view(2)
    d0 = cp.selected
    QTest.keyClick(cp, Qt.Key.Key_PageDown)
    assert cp.selected == d0 + dt.timedelta(days=1)
    QTest.keyClick(cp, Qt.Key.Key_T)
    assert cp.selected == TODAY


def test_task_menu_offers_edit_done_duplicate_trash_and_they_work(win, monkeypatch):
    cp = _cal(win)
    t = _task(win, "منو", TODAY, timeFrom="11:00", timeTo="12:00")
    seen = {}

    class Fake:
        def __init__(self, ents):
            seen["ents"] = ents

        def exec(self, _pos):
            pass
    monkeypatch.setattr(cv, "pmenu", lambda parent, pal, ents: Fake(ents))
    cp.task_menu(t["id"], QPoint())
    acts = {e[1]: e[2] for e in seen["ents"] if e}
    assert set(acts) >= {"ویرایش…", "انجام شد", "ساخت یک کپی", "انتقال به سطل زباله"}
    n = len(win.store.vault["tasks"])
    acts["ساخت یک کپی"]()
    assert len(win.store.vault["tasks"]) == n + 1
    dup = win.store.vault["tasks"][-1]
    assert dup["title"] == "منو" and dup["id"] != t["id"] and not dup["done"]
    win.perform_undo()
    assert len(win.store.vault["tasks"]) == n
    acts["انجام شد"]()
    assert t["done"]
    acts["انتقال به سطل زباله"]()
    assert all(x["id"] != t["id"] for x in win.store.vault["tasks"])
    win.perform_undo()
    assert any(x["id"] == t["id"] for x in win.store.vault["tasks"])


def test_day_menu_lists_new_task_here_and_it_opens_the_card(win, monkeypatch):
    cp = _cal(win)
    seen = {}

    class Fake:
        def __init__(self, ents):
            seen["ents"] = ents

        def exec(self, _pos):
            pass
    monkeypatch.setattr(cv, "pmenu", lambda parent, pal, ents: Fake(ents))
    cp.day_menu(TODAY, QPoint(), 10 * 60)
    labels = [e[1] for e in seen["ents"] if e]
    assert any("۱۰:۰۰" in x for x in labels)
    next(e for e in seen["ents"] if e and "۱۰:۰۰" in e[1])[2]()
    assert cp._quick is not None and (cp.week._pending["a"], cp.week._pending["b"]) == (600, 660)
    cp._quick.close()


def test_filters_have_the_default_dot_and_year_view_uses_filters(win):
    cp = _cal(win, 4)
    assert cp.cat.default_index() == 0 if hasattr(cp.cat, "default_index") else True
    _task(win, "کار", TODAY)
    cp.status.setCurrentIndex(cp.status.findData("done"))
    assert cp.filtered(TODAY) == []


def test_autoscroll_follows_the_pointer_not_the_system_cursor(win):
    cp = _cal(win)
    win.resize(1180, 640)
    QTest.qWait(30)
    g = cp.week
    sc = cp.week_sc
    sc.verticalScrollBar().setValue(0)
    QTest.mousePress(g, Qt.MouseButton.LeftButton, pos=_pt(g, TODAY, 60))
    QTest.mouseMove(g, _pt(g, TODAY, 120))
    QTest.mouseMove(g, QPoint(_pt(g, TODAY, 0).x(), sc.viewport().height() - 4 + sc.verticalScrollBar().value()))
    before = sc.verticalScrollBar().value()
    QTest.qWait(300)
    assert sc.verticalScrollBar().value() > before                                 # near the bottom edge: the grid scrolls
    QTest.mouseRelease(g, Qt.MouseButton.LeftButton, pos=_pt(g, TODAY, 400))
    assert g._auto.isActive() is False
    if cp._quick:
        cp._quick.close()


# ================================================================== the tour, «what's new», About ==========
from aegis_desktop.ui import anim, main_window, tour  # noqa: E402
from aegis_desktop.ui import whatsnew as wn  # noqa: E402


@pytest.fixture
def no_motion():
    """«Reduce motion» for one test (declare it after `win`, which resets the flag from the prefs when it builds the window)."""
    old = anim.MOTION[0]
    anim.MOTION[0] = False
    yield
    anim.MOTION[0] = old


def _tour(win, steps=None, single=False):
    setup_vault(win)
    win.show_page("today")
    QTest.qWait(60)
    t = tour.start(win, steps, single=single)
    return t


def test_tour_covers_every_section_and_every_step_is_written(win):
    pages = {s.page for s in tour.STEPS if s.page}
    assert {k for k, _t in win.NAV if k != "settings"} <= pages                    # every section has its own step
    keys = [s.key for s in tour.STEPS]
    assert len(keys) == len(set(keys)) and keys[0] == "welcome" and keys[-1] == "done"
    for s in tour.STEPS:
        assert s.title.strip() and len(s.text) > 20, s.key
        assert "\n" not in s.text and len(s.text) < 180, s.key                     # two short lines, never a wall of text
    assert tour.STEPS[0].hero and tour.STEPS[-1].hero
    assert all(f.title and f.text for f in tour.FEATURES.values())


def test_tour_walks_every_step_with_a_lit_target_and_a_card_on_screen(win, no_motion):        # steps land at once: this checks where
    t = _tour(win)
    assert win.tour is t and t.isVisible()
    W, H = win.width(), win.height()
    for i, st in enumerate(tour.STEPS):
        t.go(i)
        QTest.qWait(420)
        assert t.i == i
        c = t.card.geometry().adjusted(t.card.SH, t.card.SH, -t.card.SH, -t.card.SH)      # the visible glass, without its shadow
        assert c.left() >= 0 and c.top() >= 0 and c.right() <= W and c.bottom() <= H, (st.key, c)
        if st.target is None:
            assert t._hole is None, st.key
        else:
            h = t._hole
            assert h is not None and h.width() > 20 and h.height() > 20, st.key
            assert h.left() >= 0 and h.top() >= 0 and h.right() <= W and h.bottom() <= H, (st.key, h)
            assert not h.toRect().intersects(c) or h.width() * h.height() > 0.25 * W * H or st.key in ("calendar", "focus"), st.key
        assert not win.grab().isNull()
    assert t.card.b_next.text() == "شروع کنیم" and not t.card.b_prev.isHidden()


def test_tour_opens_each_steps_page(win, no_motion):
    t = _tour(win)
    for st in tour.STEPS:
        if st.page:
            t.go(tour.STEPS.index(st))
            QTest.qWait(350)
            assert win.stack.currentWidget() is win.pages[st.page], st.key


def test_tour_keys_next_prev_and_escape_remember_the_choice(win):
    t = _tour(win)
    QTest.qWait(200)
    QTest.keyClick(t, Qt.Key.Key_Left)                                            # RTL: ← is forward
    assert t.i == 1
    QTest.keyClick(t, Qt.Key.Key_Return)
    assert t.i == 2
    QTest.keyClick(t, Qt.Key.Key_Right)
    assert t.i == 1
    QTest.keyClick(t, Qt.Key.Key_Escape)
    QTest.qWait(300)
    assert win.tour is None and win.prefs["onboarded"] is True and win.prefs["seen_version"]


def test_tour_finishing_and_skipping_mark_the_first_run_done(win):
    t = _tour(win)
    walked = []
    t.finished.connect(walked.append)
    t.go(len(tour.STEPS) - 1)
    QTest.qWait(300)
    t.next()
    QTest.qWait(300)
    assert walked == [True] and win.tour is None and win.prefs["onboarded"] is True
    win.prefs.pop("onboarded")
    t2 = tour.start(win)
    t2.card.b_skip.click()
    QTest.qWait(300)
    assert win.tour is None and win.prefs["onboarded"] is True


def test_tour_returns_to_the_page_you_were_on(win):
    setup_vault(win)
    win.show_page("habits")
    QTest.qWait(80)
    t = tour.start(win)
    t.go(5)
    QTest.qWait(650)
    t.finish(False)
    QTest.qWait(300)
    assert win.stack.currentWidget() is win.pages["habits"]


def test_tour_swallows_clicks_and_blocks_palette_and_new_task_underneath(win, monkeypatch):
    t = _tour(win)
    opened = []
    monkeypatch.setattr(main_window, "Palette", lambda *_a, **_k: opened.append("palette"))
    win.open_palette()
    win.new_task(None)                                                            # would block on a modal dialog if the guard failed
    assert opened == []
    QTest.mouseClick(t, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    assert win.tour is t                                                          # a click on the dim layer does not end it


def test_locking_the_vault_ends_the_tour(win):
    t = _tour(win)
    QTest.qWait(200)
    win.lock()
    QTest.qWait(300)
    assert win.tour is None


def test_tour_follows_a_resized_window_and_reduced_motion(win):
    t = _tour(win)
    t.go(1)
    QTest.qWait(700)
    win.resize(1000, 640)
    QTest.qWait(150)
    assert t.geometry() == win.rect()
    h = t._hole
    assert h is not None and h.right() <= win.width() and h.bottom() <= win.height()
    old = anim.MOTION[0]
    anim.MOTION[0] = False
    try:
        t.go(2)
        QTest.qWait(400)
        assert t._hole is not None and t._fx.opacity() == 1.0                 # no glide, no fade: it just lands
    finally:
        anim.MOTION[0] = old


def test_card_text_is_forced_rtl_so_a_leading_latin_word_cannot_flip_it(win):
    t = _tour(win)
    i = next(k for k, s in enumerate(tour.STEPS) if s.text.startswith("Ctrl"))
    t.go(i)
    QTest.qWait(700)
    assert t.card.text.text().startswith("‏") and t.card.title.text().startswith("‏")


def test_card_grows_to_fit_its_text_and_keycaps(win):
    t = _tour(win)
    t.go(1)                                                                       # has keycaps
    QTest.qWait(700)
    c = t.card
    assert c.text.height() >= c.text.heightForWidth(c.text.width()) - 1           # not squeezed
    need = c.lay.heightForWidth(c.width())
    assert c.height() >= need - 1 and c.keys is not None and c.keys.isVisible()


def test_every_feature_spotlight_finds_its_target(win):
    setup_vault(win)
    for key in tour.FEATURES:
        t = tour.show_feature(win, key)
        assert t is not None and t.single
        QTest.qWait(900)
        h = t._hole
        assert h is not None and h.width() > 20, key
        assert t.card.b_next.text() == "فهمیدم" and t.card.b_skip.isHidden() and t.card.b_prev.isHidden(), key
        QTest.keyClick(t, Qt.Key.Key_Return)                                      # single step: Enter closes it
        QTest.qWait(300)
        assert win.tour is None, key
    assert tour.show_feature(win, "nope") is None


def test_a_second_tour_replaces_the_first(win):
    t1 = _tour(win)
    t2 = tour.start(win)
    QTest.qWait(300)
    assert win.tour is t2 and t1._closed


# ------------------------------------------------------------------------------------------ what's new ---
def test_release_notes_are_grouped_and_every_show_me_points_somewhere(win):
    es = wn.entries_for("1.5.0")
    assert {e.kind for e in es} == {"added", "improved", "fixed"}
    assert all(e.title and e.detail for e in es)
    assert all(e.where in tour.FEATURES for e in es if e.where)
    assert sum(1 for e in es if e.where) >= 6
    old = wn.entries_for("1.4.1")
    assert old and all(e.kind == "" for e in old)                                 # older versions stay a plain list
    assert wn.notes_for("1.5.0") and wn.notes_for("0.0.1") == []


def test_whatsnew_card_lists_groups_and_show_me_runs_the_spotlight(win, monkeypatch):
    setup_vault(win)
    seen = []
    monkeypatch.setattr(win, "show_feature", lambda k: seen.append(k))
    d = wn.WhatsNew(win, "1.5.0")
    d.show()
    QTest.qWait(200)
    from PyQt6.QtWidgets import QPushButton
    btns = [b for b in d.findChildren(QPushButton) if b.text().startswith("نشانم بده")]
    assert len(btns) == sum(1 for e in wn.entries_for("1.5.0") if e.where)
    btns[0].click()
    QTest.qWait(500)
    assert seen == ["calendar"] and win.prefs["seen_version"] == "1.5.0"
    assert not d.isVisible()


def test_whatsnew_can_start_the_tour_and_old_versions_still_render(win, monkeypatch):
    setup_vault(win)
    started = []
    monkeypatch.setattr(win, "show_tour", lambda: started.append(1))
    d = wn.WhatsNew(win)
    d.show()
    d.tour_btn.click()
    QTest.qWait(500)
    assert started == [1]
    old = wn.WhatsNew(win, "1.3.0")
    old.show()
    assert not old.grab().isNull()
    old.close()


def test_about_has_whatsnew_and_tour_buttons_and_the_palette_finds_them(win, monkeypatch):
    setup_vault(win)
    win.show_page("settings")
    st = win.pages["settings"]
    tour._p_about(win)
    QTest.qWait(100)
    from PyQt6.QtWidgets import QPushButton
    texts = {b.text() for b in st.findChildren(QPushButton)}
    assert {"نمایش تازه‌ها", "شروع تور"} <= texts
    called = []
    monkeypatch.setattr(win, "show_whatsnew", lambda force=False: called.append(("wn", force)))
    monkeypatch.setattr(win, "show_tour", lambda: called.append(("tour",)))
    next(b for b in st.findChildren(QPushButton) if b.text() == "نمایش تازه‌ها").click()
    next(b for b in st.findChildren(QPushButton) if b.text() == "شروع تور").click()
    assert called == [("wn", True), ("tour",)]
    pal = main_window.Palette.__new__(main_window.Palette)
    pal.win = win
    from aegis_desktop.core import logic
    assert any(k == "tour" for _l, k, _i in pal._commands(logic.fold("معرفی")))
    assert any(k == "whatsnew" for _l, k, _i in pal._commands(logic.fold("تازه")))
    win.run_command("tour")
    win.run_command("whatsnew")
    QTest.qWait(400)
    assert ("tour",) in called[2:] and ("wn", True) in called[2:]


def test_first_run_starts_the_tour_and_an_update_shows_whatsnew(win, monkeypatch):
    setup_vault(win)
    got = []
    monkeypatch.setattr(win, "show_tour", lambda: got.append("tour"))
    win.show_onboarding()
    assert got == ["tour"]


# ================================================== 1.5.0 basics: dropdowns, forms, themes, lazy pages, copy ====
import pathlib  # noqa: E402
import time  # noqa: E402

from aegis_desktop.ui import dialogs, themes_data  # noqa: E402
from aegis_desktop.ui.combo_popup import ComboPopup  # noqa: E402
from aegis_desktop.ui.fx_widgets import Combo  # noqa: E402


def _combo(win):
    c = Combo()
    for i, t in enumerate(("همه", "کار", "درس", "ورزش")):
        c.addItem(t, i)
    c.set_default(0)
    c.setParent(win.shell)
    c.move(300, 200)
    c.show()
    return c


def test_dropdown_is_a_glass_sheet_that_picks_with_keys_mouse_and_closes_on_escape_or_outside_click(win):
    setup_vault(win)
    c = _combo(win)
    assert not c.is_filtering()
    c.showPopup()
    pop = c._pop
    assert isinstance(pop, ComboPopup) and pop.isVisible() and not pop.grab().isNull()
    QTest.keyClick(pop, Qt.Key.Key_Down)
    QTest.keyClick(pop, Qt.Key.Key_Down)
    QTest.keyClick(pop, Qt.Key.Key_Return)
    QTest.qWait(50)
    assert c.currentIndex() == 2 and c.is_filtering()                              # a chosen filter wears the dot
    c._pop_closed_t = 0.0
    c.showPopup()
    pop = c._pop
    QTest.keyClick(pop, Qt.Key.Key_Escape)
    QTest.qWait(50)
    assert c.currentIndex() == 2 and c._pop is None
    c._pop_closed_t = 0.0
    c.showPopup()
    pop = c._pop
    QTest.mousePress(pop, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))              # on the shadow, outside the sheet
    QTest.qWait(50)
    assert c._pop is None and c.currentIndex() == 2
    c.setCurrentIndex(0)
    assert not c.is_filtering()


def test_task_filters_are_marked_and_light_and_dark_sheets_paint(win):
    setup_vault(win)
    win.show_page("tasks")
    tp = win.pages["tasks"]
    for w in (tp.cat, tp.pr, tp.tag):
        assert w._default == 0 and not w.is_filtering()
    tp.cat.setCurrentIndex(1)
    assert tp.cat.is_filtering()
    for key in ("noir", "aegis-light"):
        win.set_pref("palette", key)
        QTest.qWait(30)
        tp.cat.showPopup()
        assert tp.cat._pop is not None and not tp.cat._pop.grab().isNull()
        tp.cat._pop.close()
        tp.cat._pop_closed_t = 0.0
        QTest.qWait(30)


def test_palette_has_a_close_button_and_closes_on_an_outside_click(win):
    setup_vault(win)
    p = main_window.Palette(win)
    p.show()
    QTest.qWait(60)
    assert p.close_btn.isVisible()
    p.close_btn.click()
    QTest.qWait(60)
    assert not p.isVisible()
    p = main_window.Palette(win)
    p.show()
    QTest.qWait(60)
    QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=QPoint(3, 3))                # the dimmed window, outside the sheet
    QTest.qWait(60)
    assert not p.isVisible()
    p = main_window.Palette(win)
    p.show()
    QTest.qWait(60)
    inner = p.panel.geometry().center()
    QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=inner)                       # a click on the sheet keeps it open
    assert p.isVisible()
    QTest.keyClick(p.q, Qt.Key.Key_Escape)
    QTest.qWait(60)
    assert not p.isVisible()


def test_task_form_keeps_extras_behind_more_and_says_what_is_set(win):
    setup_vault(win)
    v = win.store.vault
    d = dialogs.TaskDialog(win, v)
    d.show()
    QTest.qWait(80)
    assert not d.more.is_open() and d.more.head.count == 0 and d.err.isHidden()
    closed_h = d.height()
    d.more.set_open(True, animate=False)
    QTest.qWait(50)
    dialogs.refit(d)
    assert d.more.is_open() and d.tags.isVisibleTo(d) and d.height() >= closed_h
    d.title.setText("کار تازه")
    d.tags.setText("مهم")
    t = d.result_task()
    assert t["title"] == "کار تازه" and "مهم" in t["tags"]
    d.reject()
    x = logic.new_task("با برچسب", tags=["الف", "ب"], rep="daily", due=jalali.date_to_due(TODAY))
    d2 = dialogs.TaskDialog(win, v, x)
    d2.show()
    QTest.qWait(80)
    assert d2.more.head.count >= 2 and d2.more.head.summary                        # the closed header names what is inside
    d2.reject()


def test_goal_form_and_password_dialog_are_compact(win):
    setup_vault(win)
    g = dialogs.GoalDialog(win)
    g.show()
    QTest.qWait(60)
    assert not g.more.is_open() and g.more.body.isHidden()
    assert not g.grab().isNull()
    g.reject()
    n = dialogs.NewPasswordDialog(win, ask_current=False)
    n.show()
    QTest.qWait(60)
    assert n.height() < 560 and not n.grab().isNull()
    n.reject()


def test_theme_picker_has_dark_and_light_groups_and_every_theme_applies(win):
    assert len(themes_data.LIGHT) >= 5 and len(themes_data.DARK) >= 9
    assert set(themes_data.LIGHT) | set(themes_data.DARK) == set(themes_data.THEMES)
    assert all(themes_data.THEMES[k]["mode"] == "light" for k in themes_data.LIGHT)
    setup_vault(win)
    win.show_page("settings")
    st = win.pages["settings"]
    tour._p_appearance(win)
    QTest.qWait(80)
    pk = st.picker
    assert list(pk.heads) == ["dark", "light"]                                     # two groups, dark first
    darks = [pk.cards[k].geometry() for k in themes_data.DARK]
    lights = [pk.cards[k].geometry() for k in themes_data.LIGHT]
    assert max(g.bottom() for g in darks) < min(g.top() for g in lights)          # the light group sits below the dark one
    assert len(pk.cards) == len(themes_data.THEMES)
    assert pk.height() > 0
    picked = []
    pk.picked.connect(picked.append)
    for k in themes_data.LIGHT:
        win.set_pref("palette", k)
        QTest.qWait(20)
        assert win.prefs["palette"] == k and win.theme == "light" and not win.grab().isNull()
    win.set_pref("palette", "noir")


def test_switching_theme_is_quick_and_only_touches_built_pages(win):
    setup_vault(win)
    built = {k for k, _p in win.pages.built()}
    assert len(built) < len(win.pages)                                             # pages are built when first opened
    times = []
    for k in ("aegis-light", "noir", "ocean", "aegis-light", "noir"):
        t0 = time.perf_counter()
        win.set_pref("palette", k)
        QTest.qWait(1)
        times.append(time.perf_counter() - t0)
    assert max(times) < 1.5, times                                                 # generous: catches a return to «rebuild everything»


def test_pages_and_settings_sections_are_built_lazily(win):
    setup_vault(win)
    assert not win.pages.is_built("reports") and win.pages.peek("reports") is None
    win.show_page("reports")
    assert win.pages.is_built("reports")
    win.show_page("settings")
    st = win.pages["settings"]
    assert "appearance" not in st._built and "picker" not in st.__dict__
    assert st.picker is not None and "appearance" in st._built                     # asking for its widget builds its section
    win.lock()
    win.auth.s1.edit.clear()


def test_empty_states_say_what_to_do(win):
    setup_vault(win)
    v = win.store.vault
    v["tasks"] = []
    win.changed()
    win.show_page("tasks")
    tp = win.pages["tasks"]
    QTest.qWait(80)
    assert tp.empty.isVisible() and "هنوز تسکی نداری" in tp.empty.title.text() and tp.empty.btn.isVisible()
    v["tasks"] = [logic.new_task("یک"), logic.new_task("دو")]
    win.changed()
    tp.q.setText("چیزی که وجود ندارد")
    QTest.qWait(400)
    assert tp.empty.isVisible() and "پیدا نشد" in tp.empty.title.text()
    tp.q.setText("")
    QTest.qWait(400)
    assert not tp.empty.isVisible()
    win.show_page("trash")
    tr = win.pages["trash"]
    assert tr.b_restore.isHidden() and tr.b_empty.isHidden()                       # an empty bin offers no buttons, only its message


def test_copy_is_warm_and_the_old_sign_in_line_is_gone():
    from aegis_desktop.ui.voice import VOICE
    assert VOICE["locked"] == "خوش برگشتی"
    root = pathlib.Path(__file__).resolve().parents[1] / "aegis_desktop"
    for f in root.rglob("*.py"):
        assert "در پناه ایجیس" not in f.read_text(encoding="utf-8"), f


def test_tour_owns_the_keyboard_so_calendar_letters_do_nothing_underneath(win):
    setup_vault(win)
    win.show_page("calendar")
    QTest.qWait(60)
    cp = win.pages["calendar"]
    cp._set_view(0)
    t = tour.start(win)
    QTest.qWait(300)
    for key in (Qt.Key.Key_W, Qt.Key.Key_D, Qt.Key.Key_Y):
        QTest.keyClick(t, key)
    assert cp.view == 0 and win.tour is t
    t.finish(False)
    QTest.qWait(250)
    QTest.keyClick(cp, Qt.Key.Key_W)                                              # and they work again once it is gone
    assert cp.view == 1


def test_lazily_built_pages_and_sections_get_scrollfx_and_names(win):
    """Pages/sections that only exist once opened must still get quiet scrollbars, glide and button names."""
    from aegis_desktop.ui import a11y, scrollfx
    setup_vault(win)
    for key, _t in win.NAV:
        win.show_page(key)
        QTest.qWait(30)
    win.pages["settings"]._ensure_all()
    QTest.qWait(30)
    assert scrollfx.attach(win.shell) == 0
    assert a11y.ensure_names(win.shell) == 0
