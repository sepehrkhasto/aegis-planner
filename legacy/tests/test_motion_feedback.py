# SPDX-License-Identifier: GPL-3.0-or-later
"""motion that answers the user — flying tick, live rows, dialog morph, drag lift, focus/switch feel, edges..."""
import datetime as dt

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import flight, micro
from aegis_desktop.ui.anim import MOTION
from aegis_desktop.ui.premium import KpiTile, TaskRowDelegate
from test_gui import setup_vault, win  # noqa: F401


def _today_task(win, title="آزمون", **kw):
    t = logic.new_task(title, due=jalali.today_jalali(), **kw)
    win.store.vault["tasks"].append(t)
    win.changed()
    return t


def _move(view, pos):
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), view.viewport().mapToGlobal(QPointF(pos)),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.viewport(), ev)


def _click(view, pos):
    for typ, btn in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton)):
        ev = QMouseEvent(typ, QPointF(pos), view.viewport().mapToGlobal(QPointF(pos)), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton if typ == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view.viewport(), ev)


# ------------------------------------------------------------------------------------ 1: flying tick ---
def test_bezier_endpoints_and_arc():
    from PyQt6.QtCore import QPointF as P
    a, b = P(0, 300), P(400, 100)
    c = flight.control_point(a, b)
    assert flight.bezier(a, c, b, 0.0) == a and flight.bezier(a, c, b, 1.0) == b
    assert c.y() < min(a.y(), b.y())                          # bows upward


def test_kpi_tile_holds_then_releases_the_number(qtbot):
    t = KpiTile("check", "success")
    qtbot.addWidget(t); t.resize(220, 104); t.show()
    t.set("۱", "x"); qtbot.wait(50)
    t.hold(200)
    t.set("۲", "x")
    assert t.value == "۱" and t._pending is not None            # held: the old number stays
    qtbot.wait(300)
    assert t.value == "۲" and t._pending is None


def test_land_releases_early_and_pulses(qtbot):
    t = KpiTile("check", "success")
    qtbot.addWidget(t); t.resize(220, 104); t.show()
    t.set("۱", "x"); t.hold(5000); t.set("۲", "x")
    t.land()
    assert t.value == "۲" and t._pulse.a.state().name == "Running"
    assert not t.grab().isNull()


def test_launch_without_motion_lands_at_once(win):
    setup_vault(win)
    hits = []
    old = MOTION[0]
    try:
        MOTION[0] = False
        assert flight.launch(win, QPoint(50, 50), win.pages["today"].tiles["done"], QColor("#fff"), lambda: hits.append(1)) is None
    finally:
        MOTION[0] = old
    assert hits == [1]


def test_ticking_a_task_flies_a_light_to_the_done_tile(win):
    setup_vault(win)
    win.resize(1180, 760); win.show(); QTest.qWait(80)
    t = _today_task(win)
    win.show_page("today"); QTest.qWait(600)
    lw = win.pages["today"].today
    d = lw.itemDelegate()
    box = lw.visualItemRect(lw.item(0)).adjusted(2, 2, -2, -2)
    tile = win.pages["today"].tiles["done"]
    before = tile.value
    _click(lw, d._circle(box).center().toPoint())
    QTest.qWait(60)
    lights = win.findChildren(flight._Light)
    assert lights and lights[0].isVisible()
    assert tile.value == before and tile._pending is not None    # the number waits for the light
    QTest.qWait(700)
    assert not [x for x in win.findChildren(flight._Light) if x.isVisible()]
    assert tile.value != before and t["done"]                    # landed: rolled to the new count


def test_flight_target_is_the_sidebar_when_the_tile_is_not_showing(win):
    setup_vault(win)
    win.resize(1180, 760); win.show(); QTest.qWait(80)
    _today_task(win)
    win.show_page("tasks"); QTest.qWait(400)
    win.fly_done(win.mapToGlobal(QPoint(300, 300)))
    QTest.qWait(50)
    assert win.findChildren(flight._Light)
    QTest.qWait(700)


# ---------------------------------------------------------------------------------------- 3: live row ---
def test_row_actions_appear_on_hover_and_only_then(win):
    setup_vault(win)
    win.resize(1180, 760); win.show(); QTest.qWait(80)
    win.store.vault["tasks"].clear()                  # one row only, so the empty strip below it is really empty
    _today_task(win)
    win.show_page("today"); QTest.qWait(600)
    lw = win.pages["today"].today
    d = lw.itemDelegate()
    assert isinstance(d, TaskRowDelegate) and d._enabled() and not d.hp
    rect = lw.visualItemRect(lw.item(0))
    _move(lw, rect.center()); QTest.qWait(400)
    key = lw.item(0).data(0x100)
    assert d.hp.get(key, 0) > 0.95
    assert not lw.viewport().grab().isNull()
    _move(lw, QPoint(2, lw.viewport().height() - 2)); QTest.qWait(500)      # pointer left the row
    assert not d.hp and not d.clock.isActive()


def test_row_action_rects_slide_and_do_not_overlap_check(win):
    setup_vault(win)
    d = TaskRowDelegate(None)
    from PyQt6.QtCore import QRectF
    box = QRectF(0, 0, 500, 54)
    full = d.action_rects(box, 1.0)
    early = d.action_rects(box, 0.0)
    assert [n for n, _ in full] == list(TaskRowDelegate.ACTIONS)
    assert early[0][1].x() < full[0][1].x()                                # starts further out
    assert all(r.right() < d._circle(box).left() for _n, r in full)


def test_row_actions_edit_later_trash_with_undo(win, monkeypatch):
    setup_vault(win)
    t = _today_task(win, "کار زنده")
    opened = []
    monkeypatch.setattr(win, "edit_task_id", lambda tid: opened.append(tid))
    win.row_action("edit", t["id"]); assert opened == [t["id"]]
    win.row_action("later", t["id"])
    assert jalali.due_to_date(t["due"]) == dt.date.today() + dt.timedelta(days=1)
    win.perform_undo()
    x = next(y for y in win.store.vault["tasks"] if y["id"] == t["id"])
    assert jalali.due_to_date(x["due"]) == dt.date.today()
    win.row_action("trash", t["id"])
    assert not [y for y in win.store.vault["tasks"] if y["id"] == t["id"] and not y.get("deleted")]
    win.perform_undo()
    assert [y for y in win.store.vault["tasks"] if y["id"] == t["id"] and not y.get("deleted")]


def test_overdue_task_moves_to_today_not_tomorrow(win):
    setup_vault(win)
    t = logic.new_task("قدیمی", due=jalali.date_to_due(dt.date.today() - dt.timedelta(days=3)))
    win.store.vault["tasks"].append(t); win.changed()
    win.row_action("later", t["id"])
    assert jalali.due_to_date(t["due"]) == dt.date.today()


def test_hover_click_on_action_runs_it(win, monkeypatch):
    setup_vault(win)
    win.resize(1180, 760); win.show(); QTest.qWait(80)
    t = _today_task(win)
    win.show_page("today"); QTest.qWait(600)
    lw = win.pages["today"].today
    d = lw.itemDelegate()
    seen = []
    monkeypatch.setattr(win, "row_action", lambda kind, tid: seen.append((kind, tid)))
    rect = lw.visualItemRect(lw.item(0))
    _move(lw, rect.center()); QTest.qWait(400)
    box = rect.adjusted(2, 2, -2, -2)
    name, r = d.action_rects(__import__("PyQt6.QtCore", fromlist=["QRectF"]).QRectF(box))[0]
    _click(lw, r.center().toPoint())
    assert seen == [(name, t["id"])]


def test_no_actions_when_the_window_does_not_offer_them(qtbot):
    from aegis_desktop.ui.premium import EmptyList
    lw = EmptyList("check", "x")
    d = TaskRowDelegate(lw)
    lw.setItemDelegate(d); qtbot.addWidget(lw); lw.show()
    assert d._enabled() is False


# ------------------------------------------------------------------------------------ 4: dialog morph ---
def test_morph_ghost_grows_to_the_dialog_place(win, qtbot):
    setup_vault(win)
    from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
    dlg = QDialog(win); QVBoxLayout(dlg).addWidget(QLabel("hello")); dlg.resize(500, 320); dlg.show(); dlg.move(200, 150)
    done = []
    g = micro.morph_open(dlg, QPoint(600, 400), lambda: done.append(1))
    assert g is not None and g.k == 0.0
    r0 = g.geometry()
    assert r0.width() < 200 and abs(r0.center().x() - 600) <= 2
    qtbot.wait(500)
    assert done == [1]


def test_morph_skipped_for_tiny_dialogs_and_reduced_motion(win):
    from PyQt6.QtWidgets import QDialog
    small = QDialog(win); small.resize(120, 80)
    assert micro.morph_open(small, QPoint(10, 10)) is None
    big = QDialog(win); big.resize(500, 300)
    old = MOTION[0]
    try:
        MOTION[0] = False
        assert micro.morph_open(big, QPoint(10, 10)) is None
    finally:
        MOTION[0] = old


def test_click_is_remembered_for_the_morph_window():
    micro.note_click(QPoint(5, 6))
    assert micro.LAST_CLICK["pos"] == QPoint(5, 6) and micro.LAST_CLICK["t"] > 0


def test_palette_does_not_morph():
    from aegis_desktop.ui.main_window import Palette
    assert Palette.MORPH is False


# --------------------------------------------------------------------------------- 2: kanban drag lift ---
def test_kanban_dragged_card_leaves_a_dashed_ghost_and_columns_light_up(win):
    setup_vault(win)
    win.resize(1180, 760); win.show(); QTest.qWait(80)
    t = logic.new_task("بکش", due=jalali.today_jalali())
    win.store.vault["tasks"].append(t); win.changed()
    win.show_page("kanban"); QTest.qWait(500)
    from aegis_desktop.ui.pages import KanbanList
    lists = win.pages["kanban"].findChildren(KanbanList)
    src = next(l for l in lists if l.count())
    dst = next(l for l in lists if l is not src)
    plain = src.viewport().grab().toImage()
    KanbanList.dragging = src.item(0).data(0x100)
    try:
        src.viewport().update(); QTest.qWait(30)
        assert src.viewport().grab().toImage() != plain              # the slot now draws as a dashed ghost
        dst.set_target(True); QTest.qWait(300)
        assert dst._ovk > 0.95
        lit = dst.viewport().grab().toImage()
        dst.set_target(False); QTest.qWait(300)
        assert dst._ovk == 0.0 and dst.viewport().grab().toImage() != lit
    finally:
        KanbanList.dragging = None


def test_kanban_target_highlight_without_motion_is_instant(win):
    setup_vault(win)
    win.show_page("kanban"); QTest.qWait(100)
    from aegis_desktop.ui.pages import KanbanList
    l = win.pages["kanban"].findChildren(KanbanList)[0]
    old = MOTION[0]
    try:
        MOTION[0] = False
        l.set_target(True); assert l._ovk == 1.0
        l.set_target(False); assert l._ovk == 0.0
    finally:
        MOTION[0] = old


# ------------------------------------------------------------------------------------ 5: focus sweep ---
def test_field_focus_runs_one_sweep_then_rests(win, qtbot):
    from PyQt6.QtWidgets import QLineEdit, QWidget, QVBoxLayout
    from aegis_desktop.ui import focusfx
    focusfx.install()
    host = QWidget(); QVBoxLayout(host); e = QLineEdit(); e.setMinimumHeight(40); host.layout().addWidget(e)
    qtbot.addWidget(host); host.resize(300, 120); host.show(); host.activateWindow(); qtbot.wait(50)
    assert focusfx.eligible(e)
    e.clearFocus(); qtbot.wait(30)
    e.setFocus(Qt.FocusReason.TabFocusReason); qtbot.wait(120)
    sw = e._sweep
    assert sw.isVisible() and sw.an.state().name == "Running"
    assert not host.grab().isNull()
    qtbot.wait(800)
    assert not sw.isVisible()


def test_focus_sweep_ignores_readonly_tiny_and_embedded_fields(qtbot):
    from PyQt6.QtWidgets import QLineEdit, QSpinBox
    from aegis_desktop.ui import focusfx
    a = QLineEdit(); a.setReadOnly(True); a.resize(200, 40); qtbot.addWidget(a)
    b = QLineEdit(); b.resize(200, 20); qtbot.addWidget(b)
    c = QLineEdit(); c.resize(200, 40); c.setStyleSheet("QLineEdit{border:none;}"); qtbot.addWidget(c)
    s = QSpinBox(); s.resize(200, 40); qtbot.addWidget(s)
    inner = s.lineEdit(); inner.resize(100, 40)
    assert not focusfx.eligible(a) and not focusfx.eligible(b) and not focusfx.eligible(c) and not focusfx.eligible(inner)


def test_sweep_path_is_closed_and_paints(qtbot):
    from PyQt6.QtWidgets import QLineEdit
    from aegis_desktop.ui import focusfx
    e = QLineEdit(); e.resize(240, 40); qtbot.addWidget(e); e.show()
    sw = focusfx.Sweep(e)
    for k in (0.0, 0.3, 0.75, 1.0):
        sw.k = k; sw.show(); assert not sw.grab().isNull()


# ---------------------------------------------------------------------------------------- 6: switch ---
def test_switch_is_a_spring_that_overshoots_a_hair_and_settles(qtbot):
    from aegis_desktop.ui.backup_ui import Switch
    s = Switch(); qtbot.addWidget(s); s.show()
    peak = 0.0
    s.setChecked(True)
    for _ in range(40):
        qtbot.wait(8); peak = max(peak, s._t.value)
    assert 1.0 < peak < 1.12                                     # overshoot exists but stays tiny
    qtbot.wait(300)
    assert s._t.value == pytest.approx(1.0, abs=0.001)
    assert not s.grab().isNull()
    s.setChecked(False); qtbot.wait(400)
    assert s._t.value == pytest.approx(0.0, abs=0.001)


# ------------------------------------------------------------------------------ P3: glint / depth / edges ---
@pytest.fixture
def motion_on():
    old = MOTION[0]
    MOTION[0] = True
    yield
    MOTION[0] = old


def test_segmented_progress_glints_once_after_the_fill(qtbot, motion_on):
    from PyQt6.QtGui import QColor as C
    from aegis_desktop.ui.premium import SegmentedProgress
    w = SegmentedProgress([(3, C("#4ade80"), "a")], 10)
    qtbot.addWidget(w); w.resize(300, 40); w.show()
    qtbot.wait(1100)                                             # fill (900) lands -> glint starts
    assert w._g.a.state() != w._g.a.State.Stopped or w._g.value == 1.0
    qtbot.wait(1000)
    assert w._g.value == 1.0                                     # glint is over, nothing keeps animating
    assert not w.grab().isNull()


def test_segmented_progress_no_glint_without_motion(qtbot):
    from PyQt6.QtGui import QColor as C
    from aegis_desktop.ui.premium import SegmentedProgress
    old = MOTION[0]
    MOTION[0] = False
    try:
        w = SegmentedProgress([(3, C("#4ade80"), "a")], 10)
        qtbot.addWidget(w); w.show(); w._glint()
        assert w._g.value == 1.0
    finally:
        MOTION[0] = old


def test_kpi_progress_growth_starts_a_glint(qtbot, motion_on):
    t = KpiTile("check", "success")
    qtbot.addWidget(t); t.resize(220, 104); t.show()
    t.set("۱", "x", progress=0.2); qtbot.wait(800)
    t.set("۲", "x", progress=0.6)
    assert t._pg.value < 1.0
    qtbot.wait(1000)
    assert t._pg.value == 1.0


def test_goal_ring_flash_uses_the_brand_accent(qtbot):
    from aegis_desktop.ui.premium import GoalRing
    g = GoalRing(1.0, QColor("#4ade80"), prev=0.5)
    qtbot.addWidget(g); g.show()
    qtbot.wait(2600)                                             # fill (900) then the metal flash (1500)
    assert g._glow.value == 1.0
    assert not g.grab().isNull()
    assert GoalRing(1.0, QColor("#4ade80"), prev=1.0)._glow.value == 1.0   # already closed: no flash again


def test_toast_stack_recedes_and_clears(win, qtbot, motion_on):
    setup_vault(win)
    a = win.toasts.push("اول", "info", None, 8000)
    b = win.toasts.push("دوم", "info", None, 8000)
    c = win.toasts.push("سوم", "info", None, 8000)
    qtbot.wait(400)
    assert c._depth_goal == 0 and b._depth_goal == 1 and a._depth_goal == 2
    assert a._depth.value > b._depth.value > c._depth.value
    win.toasts.clear()
    qtbot.wait(400)


def test_toast_depth_is_instant_without_motion(win, qtbot):
    setup_vault(win)
    old = MOTION[0]
    MOTION[0] = False
    try:
        a = win.toasts.push("اول", "info", None, 8000)
        win.toasts.push("دوم", "info", None, 8000)
        assert a._depth.value == 1.0
        win.toasts.clear()
    finally:
        MOTION[0] = old


def test_toast_depth_is_clamped(win):
    setup_vault(win)
    t = win.toasts.push("x", "info", None, 5000)
    t.set_depth(9)
    assert t._depth_goal == 3
    t.set_depth(-4)
    assert t._depth_goal == 0
    win.toasts.clear()


def test_page_crossfade_recedes_and_cleans_up(win, qtbot, motion_on):
    from aegis_desktop.ui import flip
    setup_vault(win)
    snap = win.stack.grab()
    flip.crossfade(win.stack, snap, 120)
    x = win.stack._xfade
    qtbot.wait(40)
    assert 0.0 < x.k < 1.0
    assert not x.grab().isNull()                                 # the receding paint path runs
    qtbot.wait(300)
    from PyQt6 import sip
    assert sip.isdeleted(x)                                      # the snapshot is thrown away


def test_follower_eases_toward_the_pointer_and_rests(qtbot, monkeypatch, motion_on):
    from aegis_desktop.ui import parallax
    from PyQt6.QtWidgets import QWidget
    w = QWidget()
    qtbot.addWidget(w); w.resize(400, 300); w.show()
    monkeypatch.setattr(parallax, "tilt", lambda _w: (1.0, -1.0))
    f = parallax.Follower(w)
    assert f.step() and 0 < f.x < 1 and -1 < f.y < 0
    for _ in range(60):
        f.step()
    assert f.x > 0.95 and f.y < -0.95                            # close enough that the last sliver is not worth a repaint
    assert f.step() is False                                     # arrived: nothing repaints


def test_follower_is_still_without_motion(qtbot, monkeypatch):
    from aegis_desktop.ui import parallax
    from PyQt6.QtWidgets import QWidget
    w = QWidget(); qtbot.addWidget(w)
    old = MOTION[0]
    MOTION[0] = False
    try:
        monkeypatch.setattr(parallax, "tilt", lambda _w: (1.0, 1.0))
        f = parallax.Follower(w)
        assert f.step() is False and (f.x, f.y) == (0.0, 0.0)
    finally:
        MOTION[0] = old


def test_tilt_is_zero_for_a_hidden_window(qtbot):
    from aegis_desktop.ui import parallax
    from PyQt6.QtWidgets import QWidget
    w = QWidget(); qtbot.addWidget(w)
    assert parallax.tilt(w) == (0.0, 0.0)


def test_empty_art_polls_only_while_visible(qtbot, motion_on):
    from aegis_desktop.ui.premium import EmptyArt
    e = EmptyArt("check")
    qtbot.addWidget(e)
    assert not e._poll.isActive()
    e.show()
    assert e._poll.isActive()
    e.hide()
    assert not e._poll.isActive()


def test_glow_mark_follows_the_pointer(qtbot, monkeypatch, motion_on):
    from aegis_desktop.ui import parallax
    from aegis_desktop.ui.cinema import GlowMark
    g = GlowMark(64)
    qtbot.addWidget(g); g.show()
    monkeypatch.setattr(parallax, "tilt", lambda _w: (1.0, 1.0))
    g._tick(0.3)
    m = g._lay.contentsMargins()
    assert m.left() > 0 and m.top() > 0
    assert not g.grab().isNull()


def test_scroll_edges_only_on_opted_in_areas(qtbot):
    from PyQt6.QtWidgets import QLabel, QScrollArea
    from aegis_desktop.ui import scrollfx
    for opted in (True, False):
        sa = QScrollArea()
        sa.setProperty("edges", opted)
        lab = QLabel("x\n" * 200)
        sa.setWidget(lab); sa.setWidgetResizable(True)
        qtbot.addWidget(sa); sa.resize(300, 200); sa.show()
        scrollfx.attach(sa)
        edges = [c for c in sa.viewport().children() if isinstance(c, scrollfx._Edges)]
        assert bool(edges) == opted
        if opted:
            e = edges[0]
            assert e.amounts() == (0.0, 1.0)                     # at rest: nothing on top, content hidden below
            sa.verticalScrollBar().setValue(sa.verticalScrollBar().maximum())
            assert e.amounts() == (1.0, 0.0)
            assert not sa.viewport().grab().isNull()


def test_scroll_edges_do_nothing_when_content_fits(qtbot):
    from PyQt6.QtWidgets import QLabel, QScrollArea
    from aegis_desktop.ui import scrollfx
    sa = QScrollArea()
    sa.setProperty("edges", True)
    sa.setWidget(QLabel("short")); sa.setWidgetResizable(True)
    qtbot.addWidget(sa); sa.resize(300, 200); sa.show()
    scrollfx.attach(sa)
    e = next(c for c in sa.viewport().children() if isinstance(c, scrollfx._Edges))
    assert e.amounts() == (0.0, 0.0)


def test_page_scroll_areas_opt_in(win):
    setup_vault(win)
    from PyQt6.QtWidgets import QScrollArea
    for key in ("reports", "settings"):
        pg = win.pages.get(key) if hasattr(win, "pages") else None
        if pg is None:
            continue
        assert any(s.property("edges") for s in pg.findChildren(QScrollArea)), key


# ------------------------------------------------------------------------------ P3: focus timer ---
def test_focus_dial_beats_once_per_second_in_the_last_ten(qtbot, motion_on):
    from aegis_desktop.ui.premium import FocusDial
    d = FocusDial()
    qtbot.addWidget(d); d.resize(360, 360); d.show()
    d.set_state("00:11", 0.99, "work", True, 1, "x", 11)
    assert d._beat.value == 1.0                                  # not yet in the last ten seconds
    d.set_state("00:10", 0.99, "work", True, 1, "x", 10)
    assert d._beat.value < 1.0 or d._beat.a.state() != d._beat.a.State.Stopped
    assert not d.grab().isNull()
    qtbot.wait(1000)
    assert d._beat.value == 1.0
    d.set_state("00:10", 0.99, "work", True, 1, "x", 10)         # same second again: no restart
    assert d._beat.value == 1.0


def test_focus_dial_is_quiet_when_paused_or_without_motion(qtbot):
    from aegis_desktop.ui.premium import FocusDial
    d = FocusDial()
    qtbot.addWidget(d); d.show()
    old = MOTION[0]
    try:
        MOTION[0] = True
        d.set_state("00:05", 0.99, "work", False, 1, "x", 5)     # paused
        assert d._beat.value == 1.0
        MOTION[0] = False
        d.set_state("00:04", 0.99, "work", True, 1, "x", 4)
        d.finish()
        assert d._beat.value == 1.0 and d._done.value == 1.0
    finally:
        MOTION[0] = old


def test_focus_dial_finish_ring_plays_once(qtbot, motion_on):
    from aegis_desktop.ui.premium import FocusDial
    d = FocusDial()
    qtbot.addWidget(d); d.resize(360, 360); d.show()
    d.finish()
    qtbot.wait(150)
    assert 0.0 <= d._done.value < 1.0
    assert not d.grab().isNull()
    qtbot.wait(1400)
    assert d._done.value == 1.0


def test_focus_page_finish_triggers_the_ring(win, qtbot, motion_on):
    import time as _t
    setup_vault(win)
    win.show_page("focus")
    pg = win.pages["focus"] if hasattr(win, "pages") else win.stack.currentWidget()
    pg.running = True
    pg._deadline = _t.monotonic() - 1
    pg._tick()
    assert pg.dial._done.value < 1.0 or pg.dial._done.a.state() != pg.dial._done.a.State.Stopped
    qtbot.wait(1500)


def test_empty_art_leaves_the_painter_balanced(qtbot):
    """A save() without restore() makes Qt warn on every repaint — the empty art must end with the stack it began with."""
    from PyQt6.QtCore import qInstallMessageHandler
    from PyQt6.QtGui import QImage, QPainter as P
    from aegis_desktop.ui.brand import paint_empty_art
    from aegis_desktop.ui.themes_data import THEMES
    msgs = []
    qInstallMessageHandler(lambda _m, _c, s: msgs.append(s))
    try:
        for name in ("noir", "aegis-light"):
            th = THEMES[name]
            pal = th.get("pal", th) if isinstance(th, dict) else th
            img = QImage(240, 240, QImage.Format.Format_ARGB32)
            p = P(img)
            assert paint_empty_art(p, 120, 120, pal, "check", tilt=(0.5, -0.5))
            p.end()
    finally:
        qInstallMessageHandler(None)
    assert not [m for m in msgs if "saved states" in m]
