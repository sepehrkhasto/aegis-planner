# SPDX-License-Identifier: GPL-3.0-or-later
"""QA sweep of the real window (offscreen): every page x every theme x several sizes, damaged / empty / huge vaults,
every dialog, keyboard paths, performance budgets, widget leaks and Qt warnings.

One window is shared by the whole module (creating a vault costs a real 600k-iteration key derivation).
"""
import datetime as dt
import gc
import random
import time

import pytest
from PyQt6.QtCore import QRect, Qt, qInstallMessageHandler
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFrame, QWidget

from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import VaultStore, empty_vault, normalize
from aegis_desktop.ui import dialogs, main_window as mw_mod, theme
from aegis_desktop.ui.main_window import MainWindow
from aegis_desktop.ui.premium import KpiTile

from test_fuzz import _vault

PW = "correct horse battery 42"
_qt_msgs: list[str] = []


@pytest.fixture(scope="module")
def mw(qapp, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(dialogs, "info", lambda *a, **k: None)
    mp.setattr(dialogs, "warn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("warn: %s" % (a[2:],))))
    prev = qInstallMessageHandler(lambda _mode, _ctx, msg: _qt_msgs.append(msg))
    qapp.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.load_font(qapp)
    d = tmp_path_factory.mktemp("qa")
    w = MainWindow(VaultStore(d / "data"), qapp, d / "data" / "prefs.json")
    w.resize(1280, 800)
    w.show()
    w.auth.s1.edit.setText(PW); w.auth.s2.edit.setText(PW); w.auth._create()
    assert w.store.is_unlocked
    yield w
    w.store.dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()
    qInstallMessageHandler(prev)
    mp.undo()


def _settle(ms: int = 0) -> None:
    QApplication.processEvents()
    if ms:
        QTest.qWait(ms)


def _visible_cards(page: QWidget) -> list[QWidget]:
    out = []
    for c in page.findChildren(QWidget):
        if (isinstance(c, KpiTile) or (isinstance(c, QFrame) and c.objectName() == "Card")) and c.isVisibleTo(page):
            out.append(c)
    return out


def _layout_problems(win: MainWindow, key: str) -> list[str]:
    """Sibling cards that overlap, or a card that sticks out of the window sideways."""
    page = win.pages[key]
    probs = []
    cards = _visible_cards(page)
    by_parent: dict[int, list[QWidget]] = {}
    for c in cards:
        by_parent.setdefault(id(c.parentWidget()), []).append(c)
    for sibs in by_parent.values():
        for i, a in enumerate(sibs):
            for b in sibs[i + 1:]:
                inter = a.geometry().intersected(b.geometry())
                if inter.width() > 2 and inter.height() > 2:
                    probs.append(f"{key}: {type(a).__name__} overlaps {type(b).__name__} {inter}")
    wr = QRect(0, 0, win.width(), win.height())
    for c in cards:
        top_left = c.mapTo(win, c.rect().topLeft())
        r = QRect(top_left, c.size())
        if r.left() < -2 or r.right() > wr.right() + 2:
            probs.append(f"{key}: {type(c).__name__} outside the window horizontally {r} (window {wr.width()})")
    return probs


def _all_pages(win: MainWindow, wait: int = 0) -> list[str]:
    probs = []
    for key in win.pages:
        win.show_page(key)
        _settle(wait)
        assert not win.grab().isNull()
        probs += _layout_problems(win, key)
    return probs


# -------------------------------------------------------------------------------------------------------- render ---
@pytest.mark.parametrize("size", [(900, 600), (1280, 800), (1920, 1080)])
def test_every_page_in_every_theme_and_size(mw, size):
    mw.resize(*size)
    _settle(50)
    probs = []
    for th in theme.THEME_ORDER:
        mw.set_pref("palette", th)
        probs += [f"[{th} {size}] {p}" for p in _all_pages(mw)]
    mw.set_pref("palette", theme.DEFAULT_THEME)
    mw.resize(1280, 800)
    assert not probs, "\n".join(probs[:20])


def test_compact_sidebar_rail(mw):
    mw.set_pref("side_compact", True)
    try:
        _settle(420)
        assert mw.side.width() == mw.RAIL_W and not mw._brand_names.isVisible()
        assert all(b.toolTip() for b in mw.nav_btns.values())                     # labels live in tooltips now
        probs = _all_pages(mw)
        assert not probs, "\n".join(probs[:10])
    finally:
        mw.set_pref("side_compact", False)
    _settle(420)
    assert mw.side.width() == mw.SIDE_W and mw._brand_names.isVisible()


@pytest.mark.parametrize("seed", range(10))
def test_damaged_vaults_render_everywhere_and_open_in_dialogs(mw, seed, monkeypatch):
    mw.store.vault = normalize(_vault(seed))
    mw.refresh_all()
    _all_pages(mw)
    v = mw.store.vault
    for t in v["tasks"][:4]:                                   # the edit dialogs read every field of the entity
        d = dialogs.TaskDialog(mw, v, t); d.show(); _settle(); d.result_task(); d.reject(); d.deleteLater()
    for g in v["goals"]:
        d = dialogs.GoalDialog(mw, g); d.show(); _settle(); d.result_goal(); d.reject(); d.deleteLater()
    for h in v["habits"]:
        d = dialogs.HabitDialog(mw, h); d.show(); _settle(); d.reject(); d.deleteLater()


def test_empty_vault_everywhere(mw):
    mw.store.vault = normalize(empty_vault())
    mw.refresh_all()
    probs = _all_pages(mw)
    assert not probs, "\n".join(probs)


# ------------------------------------------------------------------------------------------------------- dialogs ---
def test_every_dialog_opens_fits_and_closes(mw, tmp_path):
    from aegis_desktop.ui.backup_ui import BackupBrowser
    mw.store.vault = normalize(_vault(3)); mw.refresh_all()
    screen = QApplication.primaryScreen().availableGeometry()
    made = [dialogs.TaskDialog(mw, mw.store.vault), dialogs.GoalDialog(mw), dialogs.HabitDialog(mw),
            dialogs.NewPasswordDialog(mw, ask_current=True, verify=lambda p: p == PW),
            dialogs.RecoveryUnlockDialog(mw), dialogs.ImportDialog(mw, str(tmp_path / "x.aegis"), True),
            BackupBrowser(mw), mw_mod.Palette(mw)]
    for d in made:
        d.show(); _settle(30)
        assert not d.grab().isNull()
        assert d.height() <= max(screen.height(), 600) + 40, (type(d).__name__, d.height())
        d.reject(); _settle()
        assert not d.isVisible(), type(d).__name__
        d.deleteLater()


def test_validation_messages_instead_of_silent_failures(mw):
    d = dialogs.TaskDialog(mw, mw.store.vault); d.show()
    d.accept()
    assert d.isVisible() and d.err.text()                                  # empty title: explained, not closed
    d.reject(); d.deleteLater()
    p = dialogs.NewPasswordDialog(mw); p.show()
    p.p1.edit.setText("short"); p.p2.edit.setText("short"); p.accept()
    assert p.isVisible() and "۱۰" in p.err.text()
    p.p1.edit.setText(PW); p.p2.edit.setText(PW + "x"); p.accept()
    assert p.isVisible() and "یکسان" in p.err.text()
    p.reject(); p.deleteLater()


def test_recovery_key_dialog_cannot_be_dismissed_unacknowledged(mw):
    d = dialogs.RecoveryKeyDialog(mw, "AEGIS-ABCDE-FGHIJ"); d.show(); _settle()
    d.reject(); _settle()
    assert d.isVisible()                                                   # Esc does nothing until acknowledged
    d.ack.setChecked(True); d.reject(); _settle()
    assert not d.isVisible()
    d.deleteLater()


# ------------------------------------------------------------------------------------------------------ keyboard ---
def test_global_shortcuts_are_wired(mw, monkeypatch):
    from PyQt6.QtGui import QShortcut
    calls = []
    monkeypatch.setattr(mw_mod.Palette, "exec", lambda self: calls.append("palette") or 0)
    monkeypatch.setattr(mw, "new_task", lambda *a, **k: calls.append("task"))
    sc = {s.key().toString(): s for s in mw.findChildren(QShortcut) if s.parent() is mw}
    for k in ("Ctrl+K", "Ctrl+N", "Ctrl+L", "Ctrl+1", "Ctrl+9"):
        assert k in sc, k
    sc["Ctrl+K"].activated.emit(); sc["Ctrl+N"].activated.emit()
    assert calls == ["palette", "task"]
    sc["Ctrl+2"].activated.emit(); assert mw.stack.currentWidget() is mw.pages["tasks"]
    sc["Ctrl+9"].activated.emit(); assert mw.stack.currentWidget() is mw.pages["reports"]


def test_sidebar_is_keyboard_operable(mw):
    mw.show_page("today")
    b = mw.nav_btns["tasks"]
    b.setFocus(Qt.FocusReason.TabFocusReason); _settle()
    QTest.keyClick(b, Qt.Key.Key_Return)
    assert mw.stack.currentWidget() is mw.pages["tasks"]
    QTest.keyClick(mw.nav_btns["notes"], Qt.Key.Key_Space)
    assert mw.stack.currentWidget() is mw.pages["notes"]
    assert all(x.focusPolicy() & Qt.FocusPolicy.TabFocus for x in mw.nav_btns.values())


def test_delete_in_search_box_never_trashes_selected_tasks(mw):
    mw.store.vault = normalize(empty_vault())
    mw.store.vault["tasks"] = [logic.new_task(f"t{i}") for i in range(3)]
    mw.refresh_all(); mw.show_page("tasks")
    p = mw.pages["tasks"]
    p.table.selectRow(0)
    p.q.edit.setFocus(); p.q.edit.setText("abc"); p.q.edit.setCursorPosition(0)
    _settle()
    QTest.keyClick(p.q.edit, Qt.Key.Key_Delete)
    assert len(mw.store.vault["tasks"]) == 3 and p.q.edit.text() == "bc"
    p.q.edit.clear(); _settle(350)                                         # debounced search refresh
    from PyQt6.QtCore import QItemSelectionModel as SM
    p.table.setFocus()
    p.table.selectionModel().select(p.table.model().index(0, 1), SM.SelectionFlag.ClearAndSelect | SM.SelectionFlag.Rows)
    _settle()
    assert len(p._ids()) == 1
    QTest.keyClick(p.table, Qt.Key.Key_Delete)                             # with the table focused it does delete
    _settle()
    assert len(mw.store.vault["tasks"]) == 2 and len(mw.store.vault["trash"]) == 1


def test_enter_edits_the_current_row(mw, monkeypatch):
    opened = []
    monkeypatch.setattr(mw, "edit_task_id", lambda tid: opened.append(tid))
    mw.store.vault = normalize(empty_vault())
    mw.store.vault["tasks"] = [logic.new_task("یک")]
    mw.refresh_all(); mw.show_page("tasks")
    p = mw.pages["tasks"]
    p.q.edit.clear(); _settle(350)
    p.table.setFocus(); p.table.setCurrentCell(0, 1); _settle()
    QTest.keyClick(p.table, Qt.Key.Key_Return)
    assert opened == [mw.store.vault["tasks"][0]["id"]]


# --------------------------------------------------------------------------------------------------- performance ---
def _big_vault(n_tasks: int) -> dict:
    r = random.Random(7)
    today = dt.date.today()
    v = empty_vault()
    v["tasks"] = [logic.new_task(f"تسک شمارهٔ {i}", cat=r.choice(["work", "study", "personal"]), pr=r.choice(["high", "normal", "low"]),
                                 tags=[r.choice(["کار", "پروژه"])], done=r.random() < 0.4,
                                 doneAt=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=r.randint(0, 50))).isoformat().replace("+00:00", "Z"),
                                 due=jalali.date_to_due(today + dt.timedelta(days=r.randint(-60, 60))) if r.random() < 0.8 else None)
                  for i in range(n_tasks)]
    v["notes"] = [logic.new_note(f"یادداشت {i}", "متن " * 150, folder=r.choice(["", "کار"])) for i in range(n_tasks // 5)]
    v["habits"] = [logic.new_habit(f"عادت {i}", 5) for i in range(30)]
    for h in v["habits"]:
        for k in range(90):
            if r.random() < 0.6:
                h["log"][(today - dt.timedelta(days=k)).isoformat()] = {"d": 1}
    v["goals"] = [logic.new_goal(f"هدف {i}", ms=[{"text": "م", "done": k % 2 == 0} for k in range(5)]) for i in range(25)]
    return normalize(v)


def test_performance_budget_with_a_big_vault(mw):
    mw.store.vault = _big_vault(4000)
    mw.refresh_all()
    t = time.perf_counter(); mw.store.save(); save_ms = (time.perf_counter() - t) * 1000
    slow = {}
    for key in mw.pages:
        _settle()
        t = time.perf_counter(); mw.show_page(key); _settle(); ms = (time.perf_counter() - t) * 1000
        if ms > 900:                                                        # generous: shared CI machines are slow
            slow[key] = round(ms)
    assert save_ms < 1500 and not slow, (save_ms, slow)
    mw.show_page("tasks")
    p = mw.pages["tasks"]
    p.q.edit.clear(); _settle(350)
    lat = []
    for ch in "شمارهٔ ۱۲":
        t = time.perf_counter(); p.q.edit.setText(p.q.edit.text() + ch); _settle(); lat.append((time.perf_counter() - t) * 1000)
    assert max(lat) < 80, lat                                              # typing never waits for the table
    _settle(400)
    assert p.table.rowCount() > 0                                          # Persian digits found ASCII ones
    p.q.edit.clear(); _settle(300)


def test_no_widget_leak_when_switching_pages(mw):
    mw.store.vault = _big_vault(300); mw.refresh_all()
    keys = list(mw.pages)
    for k in keys * 2:
        mw.show_page(k); _settle()
    _settle(1200); gc.collect()
    before = len(QApplication.allWidgets())
    for i in range(120):
        mw.show_page(keys[i % len(keys)]); _settle()
    _settle(1500); gc.collect(); _settle()
    after = len(QApplication.allWidgets())
    assert after - before <= 8, (before, after)


# warnings that point at a real bug in our code (painting on a dead device, broken layouts, bad connections...);
# platform chatter (window geometry negotiation on Windows, offscreen plugin notes) is not a failure
QT_BUGS = ("QPainter::", "QLayout", "QObject::connect", "QObject::setParent", "recursive repaint", "QWidget::repaint",
           "Cannot create children", "QBackingStore", "QPropertyAnimation", "QVariantAnimation", "QAbstractAnimation")


def test_no_qt_warnings_were_emitted(mw):
    bad = sorted({m for m in _qt_msgs if any(b in m for b in QT_BUGS)})
    assert not bad, "\n".join(bad[:20])
