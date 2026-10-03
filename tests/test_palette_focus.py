# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression: the palette must survive being reaped while one of its own handlers (Enter on the search field) is still
running a nested event loop (the chosen command opens a dialog that stays up longer than MotionDialog.REAP_MS).
Before the fix QLineEdit.keyPressEvent returned into a freed widget -> segfault."""
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from aegis_desktop.ui import micro
from aegis_desktop.ui.main_window import UR, Palette
from test_gui import setup_vault, win  # noqa: F401


def _select(p, data):
    for i in range(p.list.count()):
        if tuple(p.list.item(i).data(UR)) == data:
            p.list.setCurrentRow(i)
            return
    raise AssertionError(f"no row {data}")


def test_enter_in_palette_survives_reap_during_nested_loop(win, monkeypatch):
    setup_vault(win)
    monkeypatch.setattr(micro.MotionDialog, "REAP_MS", 30)
    calls = []

    def slow_command(key):
        calls.append(key)
        QTest.qWait(300)                      # QTest.qWait also flushes DeferredDelete, like a real nested exec() would

    monkeypatch.setattr(win, "run_command", slow_command)
    p = Palette(win)
    p.show()
    p.q.setText("certificate")
    _select(p, ("cmd", "certificate"))
    QTest.keyClick(p.q, Qt.Key.Key_Return)   # used to crash here, after the handler returned into the deleted QLineEdit
    assert calls == ["certificate"]
    QTest.qWait(150)                          # the held reap now goes through
    from PyQt6 import sip
    QTest.qWait(100)
    assert sip.isdeleted(p)                   # ... and the dialog is freed after all (nothing leaks)


def test_palette_reap_is_held_only_while_handler_runs(win):
    setup_vault(win)
    p = Palette(win)
    p.hold_reap()
    assert p._reap_hold == 1
    p.release_reap()
    p.release_reap()
    assert p._reap_hold == 0
