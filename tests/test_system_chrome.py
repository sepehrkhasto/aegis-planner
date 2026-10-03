# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared page chrome (header, rule, column heads) and the keyboard/accessibility contract of the new controls."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from test_gui import win, setup_vault  # noqa: F401
from aegis_desktop.ui import system
from aegis_desktop.ui.notes_ui import Segmented


def test_every_page_opens_with_the_same_header(win):
    setup_vault(win)
    for key in ("today", "tasks", "kanban", "notes", "habits", "goals", "focus", "reports", "trash", "settings"):
        win.show_page(key)
        QApplication.processEvents()
        pg = win.pages[key]
        assert pg.findChildren(system.EngravedRule), key
        assert pg.findChild(system.EngravedRule).height() == 9


def test_kanban_column_heads_show_counts(win):
    setup_vault(win)
    win.show_page("kanban")
    pg = win.pages["kanban"]
    assert all(isinstance(h, system.ColHead) for h in pg.heads.values())
    assert sum(h.n for h in pg.heads.values()) == len([t for t in win.store.vault["tasks"] if not t.get("archived") and t.get("kind") != "event"])
    assert "(" in pg.heads["todo"].accessibleName()


def test_segmented_is_keyboard_operable(qtbot):
    sw = Segmented([("grid", "grid", "نمای کارت"), ("list", "rows", "نمای فهرست")])
    qtbot.addWidget(sw)
    sw.show()
    got = []
    sw.changed.connect(got.append)
    assert sw.focusPolicy() == Qt.FocusPolicy.TabFocus and "نمای کارت" in sw.accessibleName()
    QTest.keyClick(sw, Qt.Key.Key_Right)
    QTest.keyClick(sw, Qt.Key.Key_Left)
    assert got == ["list", "grid"]


def test_toolbar_builds_a_row(qtbot):
    from PyQt6.QtWidgets import QPushButton, QWidget
    host = QWidget()
    qtbot.addWidget(host)
    a, b = QPushButton("a"), QPushButton("b")
    row = system.toolbar(a, "stretch", b, stretch_first=True)
    host.setLayout(row)
    assert row.count() == 3
