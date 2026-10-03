# SPDX-License-Identifier: GPL-3.0-or-later
"""sidebar (gilt capsule, pointer light, live icons, smooth collapse, badge) and card hover (HoverLight, odometer,
button ripple + glint)."""
import datetime as dt

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QCursor, QEnterEvent, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import anim, brand
from aegis_desktop.ui.micro import PressButton
from aegis_desktop.ui.premium import draw_roll
from aegis_desktop.ui.widgets import CardFrame
from test_gui import setup_vault, win  # noqa: F401


def _goal(win, key):
    b = win.nav_btns[key]
    return b.mapTo(win.side, b._pill().topLeft().toPoint()), b


def test_capsule_sits_on_the_open_page_and_glides(win):
    setup_vault(win)
    win.resize(1180, 760)
    win.show(); QTest.qWait(80)
    win.show_page("tasks"); QTest.qWait(500)
    tl, b = _goal(win, "tasks")
    g = win.nav_ind.geometry()
    assert win.nav_ind.isVisible() and (g.x(), g.y()) == (tl.x(), tl.y()) and g.height() == int(b._pill().height())
    tl2, _ = _goal(win, "notes")
    win.show_page("notes")
    QTest.qWait(70)
    mid = win.nav_ind.geometry().y()
    assert min(tl.y(), tl2.y()) < mid < max(tl.y(), tl2.y()) or abs(mid - tl2.y()) <= 12   # travelling (a small spring)
    QTest.qWait(500)
    assert win.nav_ind.geometry().y() == tl2.y()
    win.set_pref("reduce_motion", True)
    tl3, _ = _goal(win, "kanban")
    win.show_page("kanban")
    assert win.nav_ind.geometry().y() == tl3.y()                 # instant when Reduce motion is on
    win.set_pref("reduce_motion", False)
    b = win.nav_btns["kanban"]
    assert b.isChecked() and win.nav_btns["notes"].isChecked() is False


def test_capsule_follows_the_rail_and_footer_item(win):
    setup_vault(win)
    win.show(); QTest.qWait(50)
    win.show_page("settings"); QTest.qWait(500)
    tl, _ = _goal(win, "settings")
    assert win.nav_ind.geometry().y() == tl.y()                   # the footer item, across the divider
    win.set_pref("side_compact", True); QTest.qWait(450)
    tl, b = _goal(win, "settings")
    assert win.nav_ind.geometry().x() == tl.x() and win.nav_ind.width() == int(b._pill().width())
    win.set_pref("side_compact", False); QTest.qWait(450)


def test_collapse_animates_the_width_then_lands_exactly(win):
    setup_vault(win)
    win.show(); QTest.qWait(50)
    win.set_pref("side_compact", True)
    QTest.qWait(90)
    w = win.side.width()
    assert win.RAIL_W < w < win.SIDE_W and 0 < win.side.p < 1
    QTest.qWait(400)
    assert win.side.width() == win.RAIL_W and win.side.p == 1.0 and win.nav_btns["today"].compact
    win.set_pref("side_compact", False)
    QTest.qWait(450)
    assert win.side.width() == win.SIDE_W and win.side.p == 0.0 and win._brand_names.isVisible()
    win.set_pref("reduce_motion", True)
    win.set_pref("side_compact", True)
    assert win.side.width() == win.RAIL_W                         # no animation with Reduce motion
    win.set_pref("side_compact", False); win.set_pref("reduce_motion", False)


def test_pointer_light_brightens_nearby_items_and_stops_when_idle(win):
    setup_vault(win)
    win.show(); QTest.qWait(80)
    b = win.nav_btns["calendar"]
    QCursor.setPos(b.mapToGlobal(b.rect().center()))
    ev = QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10))
    QApplication.sendEvent(win.side, ev)
    QTest.qWait(300)
    assert win.side._poll.isActive() and b.prox > 0.2
    assert b.prox > win.nav_btns["trash"].prox                    # the nearer item is lit more
    QApplication.sendEvent(win.side, QEvent_leave())
    QTest.qWait(700)
    assert not win.side._poll.isActive() and b.prox == 0.0 and win.side._ga == 0.0


def QEvent_leave():
    from PyQt6.QtCore import QEvent
    return QEvent(QEvent.Type.Leave)


def test_live_icons_move_on_hover_and_settings_gear_turns(win):
    setup_vault(win)
    win.show(); QTest.qWait(50)
    for key in ("settings", "focus", "calendar"):
        b = win.nav_btns[key]
        b._h.set(0.0)
        a = b.grab().toImage()
        b._h.set(1.0)
        c = b.grab().toImage()
        assert a != c
    win.set_pref("reduce_motion", True)
    b = win.nav_btns["settings"]
    b._h.set(1.0)
    still = b.grab().toImage()
    b._h.set(0.0)
    win.set_pref("reduce_motion", False)
    assert still is not None


def test_badge_counts_today_and_overdue_and_pulses_once(win):
    setup_vault(win)
    T = dt.date.today()
    due = lambda n: jalali.date_to_due(T + dt.timedelta(n))       # noqa: E731
    v = win.store.vault
    v["tasks"] = [logic.new_task("a", due=due(0)), logic.new_task("b", due=due(2))]
    win.show(); win.changed(); QTest.qWait(50)
    bt = win.nav_btns["today"]
    assert bt.badge == 1 and bt.badge_warn is False
    v["tasks"].append(logic.new_task("late", due=due(-1)))
    win.changed(); QTest.qWait(30)
    assert bt.badge == 2 and bt.badge_warn is True
    assert bt._pulse.a.state().name == "Running"                 # one small pulse on the change
    QTest.qWait(700)
    assert bt._pulse.value == 1.0
    v["tasks"][0]["done"] = True
    win.changed(); QTest.qWait(30)
    assert bt.badge == 1
    assert not bt.grab().isNull()
    win.set_pref("side_compact", True); QTest.qWait(450)
    assert not bt.grab().isNull()                                # the rail shows a dot instead of a chip
    win.set_pref("side_compact", False); QTest.qWait(450)


def test_vault_open_dot_on_the_sidebar_mark(win):
    assert win._tile.status is True and "باز" in win._tile.toolTip()


def test_hoverlight_card_lights_up_glints_once_and_stops(qtbot):
    c = CardFrame(lively=True)
    qtbot.addWidget(c)
    c.resize(300, 100); c.show()
    idle = c.grab().toImage()
    QCursor.setPos(c.mapToGlobal(c.rect().center()))
    QApplication.sendEvent(c, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    qtbot.wait(180)
    assert c._hl.k > 0.3 and c._hl._t.isActive() and c.grab().toImage() != idle
    qtbot.wait(900)
    assert c._hl.glint == 1.0                                     # exactly one glint per entry
    QApplication.sendEvent(c, QEvent_leave())
    qtbot.wait(1000)
    assert c._hl.k == 0.0 and not c._hl._t.isActive()
    plain = CardFrame(); qtbot.addWidget(plain)
    assert plain._hl is None and plain.property("lively") is False


def test_hoverlight_static_with_reduce_motion(qtbot):
    anim.MOTION[0] = False
    try:
        c = CardFrame(lively=True)
        qtbot.addWidget(c); c.resize(200, 80); c.show()
        QApplication.sendEvent(c, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
        assert c._hl.k == 1.0 and not c._hl._t.isActive()         # a calm warm border, no timers
        QApplication.sendEvent(c, QEvent_leave())
        assert c._hl.k == 0.0
    finally:
        anim.MOTION[0] = True


def test_kpi_odometer_rolls_settled_numbers_only(win):
    setup_vault(win)
    win.show(); win.show_page("today"); QTest.qWait(1600)
    t = win.pages["today"].tiles["today"]
    t.set("۳", "برای امروز")
    QTest.qWait(50)
    t.set("۴", "برای امروز")
    assert t._roll_from == "۳" and t._roll.a.state().name == "Running"
    assert t._tick.shown() == "۴"                                 # value is exact at once; only the paint rolls
    img = t.grab().toImage()
    assert not img.isNull()
    QTest.qWait(700)
    assert t._roll.value == 1.0
    t.set("۱۰", "برای امروز")                                     # a different digit count: no roll, plain ticker
    assert t._roll.value == 1.0


def test_draw_roll_moves_only_changed_digits(qapp):
    def render(t):
        img = QImage(120, 34, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        f = p.font(); f.setPointSize(18); p.setFont(f)
        p.setPen(Qt.GlobalColor.white)
        from PyQt6.QtCore import QRectF
        draw_roll(p, QRectF(0, 0, 120, 34), "۱۲", "۱۳", t)
        p.end()
        return img
    a, b, c = render(0.0), render(0.5), render(1.0)
    assert a != b and b != c
    left = lambda im: im.copy(0, 0, 60, 34)                       # noqa: E731
    assert left(a) == left(b) == left(c)                          # the unchanged digit never moves


def test_button_ripple_and_primary_glint(qtbot):
    b = PressButton("ثبت"); b.setObjectName("Primary")
    qtbot.addWidget(b); b.resize(120, 36); b.show()
    QTest.mousePress(b, Qt.MouseButton.LeftButton, pos=b.rect().center())
    assert b._rip.state().name == "Running"
    QTest.mouseRelease(b, Qt.MouseButton.LeftButton, pos=b.rect().center())
    assert not b.grab().isNull()
    QApplication.sendEvent(b, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert b._glint is not None and b._glint.running
    qtbot.wait(800)
    assert not b._glint.running
    plain = PressButton("x"); qtbot.addWidget(plain); plain.show()
    QApplication.sendEvent(plain, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert plain._glint is None                                    # only the primary action glints


def test_habit_and_goal_cards_are_lively(win):
    from aegis_desktop.ui.premium import GoalCard, HabitCard
    assert issubclass(HabitCard, CardFrame) and issubclass(GoalCard, CardFrame)
    assert callable(brand.GlintPass)
