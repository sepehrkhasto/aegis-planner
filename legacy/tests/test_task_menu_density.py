# SPDX-License-Identifier: GPL-3.0-or-later
"""rich task menu actions, Space quick look, row density, note snippets in the palette."""
import datetime as dt

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui.main_window import Palette
from aegis_desktop.ui.peek import TaskPeek, describe
from aegis_desktop.ui.task_table import COL_TITLE, TaskCellDelegate
from test_gui import setup_vault, win  # noqa: F401

T = dt.date.today()


def _page(win, *tasks):
    setup_vault(win)
    win.store.vault["tasks"] = list(tasks)
    win.changed()
    win.show_page("tasks"); QTest.qWait(80)
    return win.pages["tasks"]


def _get(win, tid):
    return next(t for t in win.store.vault["tasks"] if t["id"] == tid)


def test_quick_due_priority_and_undo(win):
    a, b = logic.new_task("a"), logic.new_task("b", due=jalali.today_jalali(), timeFrom="10:00", dueEnd=jalali.date_to_due(T + dt.timedelta(3)))
    pg = _page(win, a, b)
    pg._set_due([a["id"], b["id"]], 1)
    tom = jalali.date_to_due(T + dt.timedelta(1))
    assert _get(win, a["id"])["due"] == tom and _get(win, b["id"])["due"] == tom
    assert jalali.due_to_date(_get(win, b["id"])["dueEnd"]) == T + dt.timedelta(3)      # still valid: kept
    win.perform_undo()
    assert _get(win, a["id"])["due"] is None and _get(win, b["id"])["timeFrom"] == "10:00"
    pg._set_due([b["id"]], 7)
    assert _get(win, b["id"])["dueEnd"] is not None and jalali.due_to_date(_get(win, b["id"])["dueEnd"]) >= jalali.due_to_date(_get(win, b["id"])["due"]) or _get(win, b["id"])["dueEnd"] is None
    pg._set_due([b["id"]], None)
    x = _get(win, b["id"])
    assert x["due"] is None and x["dueEnd"] is None and x["timeFrom"] == ""
    pg._set_pr([a["id"]], "high")
    assert _get(win, a["id"])["pr"] == "high"
    win.perform_undo()
    assert _get(win, a["id"])["pr"] == "normal"


def test_copy_titles(win):
    from PyQt6.QtWidgets import QApplication
    a, b = logic.new_task("اولی"), logic.new_task("دومی")
    pg = _page(win, a, b)
    pg._copy_titles([a["id"], b["id"], "ghost"])
    assert QApplication.clipboard().text() == "اولی\nدومی"


def test_space_opens_quick_look_and_closes(win):
    x = logic.new_task("مرور", due=jalali.today_jalali(), notes="یادداشت " * 60, subs=[{"text": "s", "done": True}, {"text": "t"}], tags=["درس"])
    pg = _page(win, x)
    tbl = pg.table
    tbl.resize(1100, 500); QTest.qWait(30)
    tbl.setFocus(); tbl.setCurrentCell(0, COL_TITLE)
    QTest.keyClick(tbl, Qt.Key.Key_Space)
    pk = pg._peek_w
    assert isinstance(pk, TaskPeek) and pk.isVisible() and not pk.grab().isNull()
    labs = dict(pk.rows)
    assert labs["مراحل"] == "۱ از ۲" and labs["برچسب‌ها"] == "#درس" and labs["یادداشت"].endswith("…")
    QTest.keyClick(pk, Qt.Key.Key_Escape); QTest.qWait(30)
    try:
        gone = not pk.isVisible()
    except RuntimeError:                                                  # closed and deleted
        gone = True
    assert gone


def test_describe_hostile_task():
    assert describe({}) == [] or all(isinstance(a, str) for a, _ in describe({}))
    describe({"subs": [None, 3, {"done": True}], "tags": None, "notes": None, "due": {"jy": 1, "jm": 40, "jd": 1}})


def test_density_changes_row_height_and_persists(win):
    pg = _page(win, *[logic.new_task(f"t{i}") for i in range(5)])
    tbl = pg.table
    assert tbl.rowHeight(0) - tbl.model().band(0) == 46
    win.set_pref("density", "compact")
    assert TaskCellDelegate.ROW_H == 36 and tbl.rowHeight(0) - tbl.model().band(0) == 36 and win.prefs["density"] == "compact"
    assert not tbl.grab().isNull()
    win.set_pref("density", "garbage")                                  # unknown value = comfortable
    assert tbl.rowHeight(0) - tbl.model().band(0) == 46
    win.set_pref("density", "comfortable")


def test_palette_note_snippet(win):
    setup_vault(win)
    n = logic.new_note("عنوان یادداشت", "این یک متن طولانی است که کلمهٔ گنجینه در وسط آن قرار دارد و ادامه هم دارد", "")
    win.store.vault["notes"].append(n)
    p = Palette(win)
    p.q.setText("گنجینه")
    lines = [p.list.item(i).text() for i in range(p.list.count()) if p.list.item(i).data(0x100)[0] == "note"]
    assert lines and lines[0].startswith("عنوان یادداشت — ") and "گنجینه" in lines[0]
    p.q.setText("عنوان")
    lines = [p.list.item(i).text() for i in range(p.list.count()) if p.list.item(i).data(0x100)[0] == "note"]
    assert lines == ["عنوان یادداشت"]
