# SPDX-License-Identifier: GPL-3.0-or-later
"""empty states with a real action, glass tooltips with key-caps, wake-on-scroll scrollbars."""

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractScrollArea

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import scrollfx
from aegis_desktop.ui.landing import _Bubble
from test_gui import setup_vault, win  # noqa: F401


def _blank(win):
    setup_vault(win)
    v = win.store.vault
    v["tasks"].clear(); v["notes"].clear()
    win.refresh_all()


def test_tasks_empty_state_first_run_and_filtered(win, monkeypatch):
    _blank(win)
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]
    pg.refresh()
    assert pg.empty.isVisible() and pg.empty.btn.text().endswith("اولین تسک را بساز")
    called = []
    monkeypatch.setattr(win, "new_task", lambda due: called.append(due))
    pg.empty.btn.click()
    assert called == [None]
    win.store.vault["tasks"].append(logic.new_task("alpha"))
    pg.q.setText("zzz-no-match"); pg.refresh()
    assert pg.empty.isVisible() and pg.empty.btn.text() == "پاک کردن فیلترها"
    pg.empty.btn.click()
    assert pg.q.text() == "" and not pg.empty.isVisible() and pg.table.rowCount() == 1


def test_today_and_notes_empty_actions(win, monkeypatch):
    _blank(win)
    tp = win.pages["today"]
    tp.refresh()
    assert tp.today_empty.isVisibleTo(tp) or tp.today_empty.btn.isVisibleTo(tp.today_empty)
    got = []
    monkeypatch.setattr(win, "new_task", lambda due: got.append(due))
    tp.today_empty.btn.click()
    assert got == [jalali.today_jalali()]
    win.store.vault["tasks"].append(logic.new_task("x", due=jalali.today_jalali()))
    tp.refresh()
    assert not tp.today_empty.isVisible()
    win.show_page("notes"); QTest.qWait(60)
    npg = win.pages["notes"]
    npg._fill_list()
    assert npg.empty.isVisible() and "یادداشت جدید" in npg.empty.btn.text()
    npg.empty.btn.click()
    assert len(win.store.vault["notes"]) == 1
    npg._fill_list()
    assert not npg.empty.isVisible()


def test_bubble_splits_shortcut_forms():
    s = _Bubble.split
    assert s("تسک جدید  Ctrl+N") == ("تسک جدید", "Ctrl+N")
    assert s("تسک‌ها (Ctrl+2)") == ("تسک‌ها", "Ctrl+2")
    assert s("Ctrl+K") == ("", "Ctrl+K")
    assert s("Ctrl+Shift+P") == ("", "Ctrl+Shift+P")
    assert s("سنجاق") == ("سنجاق", "")
    assert s("") == ("", "")
    assert s("Ctrl+ چیزی") == ("Ctrl+ چیزی", "")                              # not a shortcut


def test_bubble_paints_all_forms_both_modes():
    b = _Bubble()
    for dark in (True, False):
        for t in ("سنجاق", "تسک جدید  Ctrl+N", "Ctrl+K", "", "x" * 200):
            b.set(t, dark)
            assert b.width() > 10 and not b.grab().isNull()


def test_scrollbar_wakes_only_while_scrolling(win):
    setup_vault(win)
    win.store.vault["tasks"] += [logic.new_task(f"t{i}") for i in range(200)]
    win.show_page("tasks"); QTest.qWait(80)
    tbl = win.pages["tasks"].table
    bar = tbl.verticalScrollBar()
    assert scrollfx.attach(win.shell) == 0                                    # already hooked by unlock; idempotent
    assert bool(bar.property("active")) is False
    bar.setValue(50)
    assert bar.property("active") is True
    QTest.qWait(scrollfx.HOLD_MS + 250)
    assert bar.property("active") is False


def test_all_scrollbars_hooked_including_dialogs(win):
    setup_vault(win)
    areas = win.shell.findChildren(QAbstractScrollArea)
    assert areas and all(a.verticalScrollBar().property("_wake") for a in areas)


def test_one_accent_per_page(win):
    from PyQt6.QtWidgets import QAbstractItemView, QPushButton

    def prim(pg):
        out = []
        for b in pg.findChildren(QPushButton):
            if b.objectName() != "Primary" or not b.isVisibleTo(pg):
                continue
            p = b.parentWidget()
            while p is not None and p is not pg and not isinstance(p, QAbstractItemView):
                p = p.parentWidget()
            if b.property("cta") or not isinstance(p, QAbstractItemView):     # CTAs live inside a viewport on purpose
                out.append(b.text())
        return out
    setup_vault(win)
    for state in ("starter", "blank"):
        if state == "blank":
            v = win.store.vault
            for k in ("tasks", "notes", "habits", "goals"):
                v[k].clear()
            win.refresh_all()
        for k in win.pages:
            win.show_page(k); QTest.qWait(160)
            assert len(prim(win.pages[k])) <= 1, (state, k, prim(win.pages[k]))
    # bulk selection must not add a second accent on the tasks page
    win.store.vault["tasks"] += [logic.new_task(f"b{i}") for i in range(3)]
    win.show_page("tasks"); win.refresh_all(); QTest.qWait(40)
    tbl = win.pages["tasks"].table
    tbl.selectAll()
    QTest.qWait(30)
    assert len(prim(win.pages["tasks"])) == 1
