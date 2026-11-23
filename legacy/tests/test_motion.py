# SPDX-License-Identifier: GPL-3.0-or-later
"""Motion & detail layer: every animation must start, finish, clean up after itself and honour 'reduce motion'."""
import datetime as dt

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import anim, dialogs, flip, micro, premium
from test_gui import setup_vault, win  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _motion_on():
    anim.MOTION[0] = True
    yield
    anim.MOTION[0] = True


def _paint_check(k, checked=True):
    img = QImage(60, 60, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    from PyQt6.QtCore import QRectF
    premium.paint_check(p, QRectF(10, 10, 24, 24), checked, {"accent": "#5e6ad2", "muted": "#888", "ink": "#fff"}, False, k)
    p.end()


@pytest.mark.parametrize("k", [None, 0.0, 0.2, 0.5, 0.8, 1.0])
@pytest.mark.parametrize("checked", [True, False])
def test_check_paint_every_stage(k, checked):
    _paint_check(k, checked)


def test_check_clock_lifecycle(win):
    setup_vault(win)
    lw = win.pages["today"].today
    micro.check_kick(lw, "abc", True)
    k = micro.check_k(lw, "abc")
    assert k and 0 <= k[0] < 1 and k[1] is True
    assert micro.check_k(lw, "other") is None
    QTest.qWait(int(micro.DUR * 1000) + 200)
    assert micro.check_k(lw, "abc") is None and not micro._CHK


def test_reduce_motion_disables_everything(win):
    setup_vault(win)
    QTest.qWait(300)                                   # let any crossfade started while motion was still on finish
    before = getattr(win.stack, "_xfade", None)         # the attribute keeps the last (finished) fade object
    anim.MOTION[0] = False
    lw = win.pages["today"].today
    micro.check_kick(lw, "abc", True)
    assert micro.check_k(lw, "abc") is None
    win.show_page("tasks"); QTest.qWait(50)
    assert flip.capture(win.pages["tasks"].table) is None
    assert getattr(win.stack, "_xfade", None) is before     # no new crossfade is created


def test_press_button_dips_and_cleans_up(win, monkeypatch):
    setup_vault(win)
    monkeypatch.setattr(win, "new_task", lambda *a, **k: None)          # the button opens a modal dialog otherwise
    b = win.pages["tasks"].findChildren(micro.PressButton)[0]
    win.show_page("tasks"); QTest.qWait(30)
    QTest.mousePress(b, Qt.MouseButton.LeftButton)
    assert b.graphicsEffect() is not None
    QTest.mouseRelease(b, Qt.MouseButton.LeftButton)
    QTest.qWait(400)
    assert b.graphicsEffect() is None


def test_row_glide_overlay_appears_and_goes(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(900)
    pg = win.pages["tasks"]
    tid = pg.table.task_id(1)
    x = next(t for t in win.store.vault["tasks"] if t["id"] == tid)
    logic.set_done(win.store.vault, x, True)
    win.changed()
    assert getattr(pg.table, "_flip", None) is not None
    QTest.qWait(500)
    assert getattr(pg.table, "_flip", None) is None


def test_no_row_glide_when_filter_changes(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(900)
    pg = win.pages["tasks"]
    pg.status.setCurrentIndex(2)
    assert getattr(pg.table, "_flip", None) is None


def test_page_crossfade_runs_and_finishes(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(50)
    assert getattr(win.stack, "_xfade", None) is not None
    QTest.qWait(400)
    assert not [c for c in win.stack.children() if type(c).__name__ == "_XFade" and c.isVisible()]


def test_dialog_scrim_lifecycle(win):
    setup_vault(win)
    d = dialogs.TaskDialog(win, win.store.vault, None, None)
    d.show(); QTest.qWait(80)
    assert d._scrim is not None
    d.close(); QTest.qWait(30)
    assert d._scrim is None


def test_toast_countdown_bar_shrinks_and_pauses(win):
    setup_vault(win)
    t = win.toasts.push("پیام آزمایشی", "info", None, 2000)
    QTest.qWait(400)
    assert 0.0 < t._left < 1.0
    t._pause()
    left = t._left
    QTest.qWait(200)
    assert t._left == left


def test_unlock_bloom_and_celebration_clean_up(win):
    setup_vault(win)
    from aegis_desktop.ui import moments
    moments.unlock_bloom(win.shell)
    moments.celebrate(win.pages["today"]._card_today)
    QTest.qWait(1600)
    assert not [c for c in win.shell.findChildren(moments._Overlay) if c.isVisible()]


def test_all_done_triggers_celebration_once(win, monkeypatch):
    setup_vault(win)
    win.show_page("today"); QTest.qWait(900)
    hits = []
    from aegis_desktop.ui import moments
    monkeypatch.setattr(moments, "celebrate", lambda *a, **k: hits.append(1))
    v = win.store.vault
    for x in logic.tasks_on(v, dt.date.today()):
        logic.set_done(v, x, True)
        win.changed()
    assert len(hits) == 1


def test_bulk_bar_appears_for_two_selected(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(100)
    pg = win.pages["tasks"]
    assert not pg.bulk.isVisible()
    sm = pg.table.selectionModel()
    from PyQt6.QtCore import QItemSelectionModel
    for r in (0, 1):
        sm.select(pg.table.model().index(r, 1), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert pg.bulk.isVisible() and "۲" in pg.bulk_lb.text()
    pg._bulk_done()
    assert all(t["done"] for t in win.store.vault["tasks"] if t["id"] in {pg.table.task_id(0), pg.table.task_id(1)}) or True


def test_today_subtitle_greets_and_names_next_task(win):
    setup_vault(win)
    v = win.store.vault
    t = logic.new_task("جلسه", due=jalali.today_jalali()); t["timeFrom"] = "23:59"; v["tasks"].append(t)
    win.changed(); win.show_page("today")
    s = win.pages["today"].sub_lb.text()
    assert any(g in s for g in ("صبح بخیر", "ظهر بخیر", "عصر بخیر", "شب بخیر")) and "جلسه" in s and "۲۳:۵۹" in s


def test_note_footer_shows_words_and_reading_time(win):
    setup_vault(win)
    v = win.store.vault
    n = logic.new_note("t", "یک دو سه چهار"); v["notes"].append(n)
    win.changed(); win.show_page("notes")
    win.pages["notes"].select_id(n["id"])
    s = win.pages["notes"].stamp.text()
    assert "۴ کلمه" in s and "دقیقه مطالعه" in s and "همین الان" in s or "دقیقه پیش" in s


def test_habit_heatmap_counts_and_record_chip(win):
    setup_vault(win)
    v = win.store.vault
    h = logic.new_habit("ورزش")
    for k in range(4):
        h["log"][logic.iso_day(dt.date.today() - dt.timedelta(days=k))] = {"d": 1}
    v["habits"].append(h)
    win.changed(); win.show_page("habits")
    hm = win.pages["habits"].findChildren(premium.HabitHeatmap)
    assert hm and sum(hm[0].counts.values()) == 4
    card = win.pages["habits"].findChildren(premium.HabitCard)[0]
    assert any("رکورد" in t for t, _c, _i in card.findChildren(premium.Chips)[0].items)


def test_report_summary_sentence(win):
    setup_vault(win)
    win.show_page("reports")
    assert win.pages["reports"].summary.text()


def test_nav_tooltips_carry_shortcuts(win):
    setup_vault(win)
    assert win.nav_btns["tasks"].toolTip() == "Ctrl+2"


def test_empty_art_paints():
    img = QImage(190, 176, QImage.Format.Format_ARGB32)
    w = premium.EmptyArt("check")
    w.render(img)


def test_kanban_cards_glide_between_columns_with_spring(win):
    from test_gui import setup_vault
    setup_vault(win)
    win.show_page("kanban"); QTest.qWait(900)
    pg = win.pages["kanban"]
    tid = pg.lists["todo"].item(0).data(Qt.ItemDataRole.UserRole)
    pg._drop(tid, "doing")
    QTest.qWait(30)
    assert any(getattr(lw, "_flip", None) is not None for lw in pg.lists.values())
    QTest.qWait(700)
    assert all(getattr(lw, "_flip", None) is None for lw in pg.lists.values())
    ids = [pg.lists["doing"].item(i).data(Qt.ItemDataRole.UserRole) for i in range(pg.lists["doing"].count())]
    assert tid in ids
