# SPDX-License-Identifier: GPL-3.0-or-later
"""Undo & action toasts: delete / bulk done / status can be taken back; unrelated edits invalidate it safely."""

from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtTest import QTest

from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import empty_vault
from aegis_desktop.ui.undo import UndoRecord
from test_gui import setup_vault, win  # noqa: F401


def _mk(v, n=3):
    out = []
    for i in range(n):
        t = logic.new_task(f"t{i}", due=jalali.today_jalali())
        v["tasks"].append(t)
        out.append(t)
    return out


def test_record_restores_deleted_and_modified_and_drops_new():
    v = empty_vault()
    a, b, c = _mk(v)
    rec = UndoRecord(v, [a["id"], b["id"]])
    v["tasks"].remove(a)
    v["trash"].append({"kind": "task", "item": a, "at": logic.now_iso()})
    b["done"] = True
    v["tasks"].append(logic.new_task("spawned"))
    rec.apply(v)
    assert {t["title"] for t in v["tasks"]} == {"t0", "t1", "t2"}
    assert not next(t for t in v["tasks"] if t["id"] == b["id"])["done"]
    assert not v["trash"]


def test_delete_then_undo_button_restores_task_and_trash(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(50)
    pg = win.pages["tasks"]
    v = win.store.vault
    n, trash = len(v["tasks"]), len(v["trash"])
    tid = pg.table.task_id(0)
    pg._row_action(0, "delete")
    assert len(v["tasks"]) == n - 1 and len(v["trash"]) == trash + 1
    assert win._undo is not None
    toast = win._undo_toast
    assert toast is not None and toast.action[0] == "واگرد"
    win.perform_undo()
    assert len(v["tasks"]) == n and len(v["trash"]) == trash
    assert any(t["id"] == tid for t in v["tasks"])
    assert win._undo is None


def test_toast_pill_click_runs_undo(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(50)
    pg = win.pages["tasks"]
    n = len(win.store.vault["tasks"])
    pg._row_action(0, "delete")
    QTest.qWait(500)
    t = win._undo_toast
    QTest.mouseClick(t, Qt.MouseButton.LeftButton, pos=t._act_rect().center().toPoint())
    assert len(win.store.vault["tasks"]) == n


def test_any_other_change_withdraws_the_undo(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(50)
    pg = win.pages["tasks"]
    n = len(win.store.vault["tasks"])
    pg._row_action(0, "delete")
    win.changed("something else")
    assert win._undo is None
    win.perform_undo()                                                  # nothing happens, nothing breaks
    assert len(win.store.vault["tasks"]) == n - 1


def test_bulk_done_undo(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(50)
    pg = win.pages["tasks"]
    sm = pg.table.selectionModel()
    for r in (0, 1):
        sm.select(pg.table.model().index(r, 1), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    ids = pg._ids()
    pg._bulk_done()
    v = win.store.vault
    assert all(t["done"] for t in v["tasks"] if t["id"] in ids)
    win.perform_undo()
    assert not any(t["done"] for t in v["tasks"] if t["id"] in ids)


def test_undo_survives_save_and_reopen(win):
    setup_vault(win)
    win.show_page("tasks"); QTest.qWait(50)
    pg = win.pages["tasks"]
    tid = pg.table.task_id(0)
    pg._row_action(0, "delete")
    win.perform_undo()
    win.store.save()
    from aegis_desktop.core.store import VaultStore
    s2 = VaultStore(win.store.dir); s2.unlock("correct horse battery 42")
    assert any(t["id"] == tid for t in s2.vault["tasks"])
