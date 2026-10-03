# SPDX-License-Identifier: GPL-3.0-or-later
"""Task grouping (today / this week / later, sticky headers) and inline title editing - model, view and page level."""
import datetime as dt

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLineEdit

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import task_table as tt
from aegis_desktop.ui.task_table import BAND, COL_ACT, COL_TITLE, TaskTableModel, group_of
from test_gui import setup_vault, win  # noqa: F401

TODAY = dt.date.today()


def _ed(tbl):
    eds = [e for e in tbl.findChildren(QLineEdit) if e.isVisible()]
    return eds[-1] if eds else None


def _t(title, days=None, **kw):
    due = jalali.date_to_due(TODAY + dt.timedelta(days)) if days is not None else None
    return logic.new_task(title, due=due, **kw)


def _model(rows, grouped=True, open_only=True):
    m = TaskTableModel()
    from PyQt6.QtGui import QColor, QFont
    m.set_rows(sorted(rows, key=logic.filter_tasks.__globals__["task_date"] and (lambda x: (logic.task_date(x) is None, logic.task_date(x) or dt.date.max))),
               {k: QColor("#888") for k in ("muted", "danger", "text")}, QFont(), grouped, open_only)
    return m


def test_group_of_boundaries():
    assert group_of(_t("a", -1), TODAY) == "late"
    assert group_of(_t("a", -1), TODAY, open_only=False) == "past"
    assert group_of(_t("a", 0), TODAY) == "today"
    assert group_of(_t("a", 1), TODAY) == "week"
    assert group_of(_t("a", 7), TODAY) == "week"
    assert group_of(_t("a", 8), TODAY) == "later"
    assert group_of(_t("a"), TODAY) == "none"
    assert group_of({"due": {"jy": 1, "jm": 99, "jd": 99}}, TODAY) == "none"          # corrupt due never crashes


def test_model_groups_are_contiguous_and_rows_stay_one_to_one():
    rows = [_t("n"), _t("l1", 30), _t("t", 0), _t("w", 3), _t("o", -2), _t("t2", 0)]
    m = _model(rows)
    assert m.rowCount() == 6
    assert m.gkeys == ["late", "today", "week", "later", "none"]
    assert m.gcount == [1, 2, 1, 1, 1] and m.starts == [0, 1, 3, 4, 5]
    assert [m.band(r) for r in range(6)] == [BAND] * 1 + [BAND, 0, BAND, BAND, BAND]
    assert [m.group_at(r) for r in range(6)] == [0, 1, 1, 2, 3, 4]
    assert m.data(m.index(2, COL_TITLE), Qt.ItemDataRole.UserRole) == m.rows[2]["id"]


def test_ungrouped_and_empty_model():
    m = _model([_t("a", 0), _t("b", 20)], grouped=False)
    assert m.starts == [] and m.band(0) == 0 and m.group_at(1) == -1
    e = _model([])
    assert e.rowCount() == 0 and e.band(0) == 0


def test_page_groups_bands_heights_and_toggle(win):
    setup_vault(win)
    v = win.store.vault
    v["tasks"] += [_t("امروزی", 0), _t("هفته‌ای", 4), _t("دور", 40), _t("بی‌موعد"), _t("دیروز", -1)]
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]
    pg.group.setChecked(True); pg.refresh()
    tbl, m = pg.table, pg.table.model()
    assert m.starts and len(m.starts) == len(m.gkeys)
    base = tbl.verticalHeader().defaultSectionSize()
    for r in range(m.rowCount()):
        assert tbl.rowHeight(r) == base + (BAND if r in m.starts else 0)
    pg.group.setChecked(False)
    assert not m.starts and all(tbl.rowHeight(r) == base for r in range(m.rowCount()))
    assert win.prefs["group_tasks"] is False


def test_task_id_selection_and_actions_hit_the_right_row_with_bands(win):
    setup_vault(win)
    win.store.vault["tasks"] += [_t("aa", 0), _t("bb", 3), _t("cc", 50)]
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]
    pg.group.setChecked(True); pg.refresh()
    tbl = pg.table
    tbl.resize(1100, 500); QTest.qWait(30)
    from PyQt6.QtCore import QPointF
    for r in tbl.model().starts:
        cell = tbl.visualRect(tbl.model().index(r, COL_ACT))
        assert cell.height() == tbl.verticalHeader().defaultSectionSize() + BAND
        # a point inside the shifted button row resolves to a real button, one in the band to none
        row, b = tbl.button_at(QPointF(cell.center().x(), cell.top() + BAND + 23))
        assert row == r and b in (0, 1, 2)
        assert tbl.button_at(QPointF(cell.center().x(), cell.top() + 5))[1] == -1
    r1 = tbl.model().starts[1]
    tbl.setFocus(); tbl.setCurrentCell(r1, COL_TITLE); tbl.selectRow(r1)
    from PyQt6.QtCore import QItemSelectionModel as S
    tbl.selectionModel().select(tbl.model().index(r1, 0), S.SelectionFlag.ClearAndSelect | S.SelectionFlag.Rows)
    assert tbl.selected_rows() == [r1] and tbl.task_id(r1) == tbl.model().rows[r1]["id"]


def test_sticky_and_group_headers_paint(win):
    setup_vault(win)
    win.store.vault["tasks"] += [_t(f"x{i}", i % 40) for i in range(80)]
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]
    pg.group.setChecked(True); pg.refresh()
    tbl = pg.table
    tbl.resize(1000, 400); QTest.qWait(30)
    for pos in (0, 300, 900, tbl.verticalScrollBar().maximum()):
        tbl.verticalScrollBar().setValue(pos)
        assert not tbl.grab().isNull()                                     # paints (sticky push-up included) without error


def test_inline_rename_f2_dblclick_and_undo(win):
    setup_vault(win)
    win.store.vault["tasks"].append(_t("قدیمی", 0, subs=[{"text": "s", "done": True}]))
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]
    tbl = pg.table
    tbl.resize(1100, 500); QTest.qWait(30)
    row = next(r for r in range(tbl.rowCount()) if tbl.model().rows[r]["title"] == "قدیمی")
    tid = tbl.task_id(row)
    tbl.setFocus(); tbl.setCurrentCell(row, COL_TITLE)
    QTest.keyClick(tbl, Qt.Key.Key_F2)
    ed = _ed(tbl)
    assert ed is not None and ed.text() == "قدیمی"                         # raw title, not the "[1/1]" decorated text
    ed.setText("  جدید   با فاصله  ")
    QTest.keyClick(ed, Qt.Key.Key_Return)
    QTest.qWait(30)
    x = next(t for t in win.store.vault["tasks"] if t["id"] == tid)
    assert x["title"] == "جدید با فاصله"
    win.perform_undo()
    assert next(t for t in win.store.vault["tasks"] if t["id"] == tid)["title"] == "قدیمی"


def test_inline_rename_escape_empty_and_same_change_nothing(win):
    setup_vault(win)
    win.store.vault["tasks"].append(_t("ثابت", 0))
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]; tbl = pg.table
    tbl.resize(1100, 500); QTest.qWait(30)
    row = next(r for r in range(tbl.rowCount()) if tbl.model().rows[r]["title"] == "ثابت")
    tid = tbl.task_id(row)
    get = lambda: next(t for t in win.store.vault["tasks"] if t["id"] == tid)["title"]
    tbl.edit_title(row)
    ed = _ed(tbl); ed.setText("عوض شد")
    QTest.keyClick(ed, Qt.Key.Key_Escape); QTest.qWait(20)
    assert get() == "ثابت"
    tbl.edit_title(row)
    ed = _ed(tbl); ed.setText("   ")
    QTest.keyClick(ed, Qt.Key.Key_Return); QTest.qWait(20)
    assert get() == "ثابت"
    tbl.edit_title(row)
    ed = _ed(tbl); ed.setText("x" * 1000)
    QTest.keyClick(ed, Qt.Key.Key_Return); QTest.qWait(20)
    assert len(get()) <= 300


def test_double_click_routing(win, monkeypatch):
    setup_vault(win)
    win.store.vault["tasks"].append(_t("dd", 0))
    win.show_page("tasks"); QTest.qWait(60)
    pg = win.pages["tasks"]; tbl = pg.table
    opened = []
    monkeypatch.setattr(win, "edit_task_id", lambda tid: opened.append(tid))
    tbl.resize(1100, 500); QTest.qWait(30)
    pg._dbl(tbl.model().index(0, tt.COL_DUE))
    assert opened == [tbl.task_id(0)]                                         # other columns: full dialog
    pg._dbl(tbl.model().index(0, COL_TITLE))
    assert _ed(tbl) is not None and len(opened) == 1          # title: inline editor


def test_5000_tasks_grouped_refresh_is_fast(win):
    import time
    setup_vault(win)
    win.store.vault["tasks"] += [_t(f"t{i}", (i * 7) % 90 - 10) for i in range(5000)]
    win.show_page("tasks"); QTest.qWait(80)
    pg = win.pages["tasks"]; pg.group.setChecked(True)
    t0 = time.perf_counter(); pg.refresh(); dt_ms = (time.perf_counter() - t0) * 1000
    assert dt_ms < 400 and pg.table.model().starts


def test_selected_row_does_not_leak_highlight_into_group_band(win):
    from PyQt6.QtCore import QItemSelectionModel as S
    from PyQt6.QtGui import QColor
    setup_vault(win)
    win.store.vault["tasks"] = [_t("a", 0), _t("b", 3)]
    win.changed(); win.show_page("tasks"); QTest.qWait(80)
    pg = win.pages["tasks"]; tbl = pg.table
    tbl.resize(1100, 400); QTest.qWait(40)
    tbl.selectionModel().select(tbl.model().index(1, 0), S.SelectionFlag.ClearAndSelect | S.SelectionFlag.Rows)
    img = tbl.viewport().grab().toImage()
    y = tbl.rowViewportPosition(1) + 6                              # inside the band of the selected row
    acc = QColor(theme_accent())
    px = img.pixelColor(400, y)
    assert abs(px.red() - acc.red()) + abs(px.green() - acc.green()) + abs(px.blue() - acc.blue()) > 90


def theme_accent():
    from aegis_desktop.ui import theme
    return theme.PALETTES["dark"]["accent"]
