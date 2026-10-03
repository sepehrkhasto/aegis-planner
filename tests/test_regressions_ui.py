# SPDX-License-Identifier: GPL-3.0-or-later
"""Regressions: Today ticks, wide habit heatmap, busy global shortcut."""
import datetime as dt

from PyQt6.QtCore import QEvent, QPointF, QRect, Qt
from PyQt6.QtGui import QImage, QMouseEvent, QPainter
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyleOptionViewItem

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import hotkey, premium
from aegis_desktop.ui.premium import HabitHeatmap, TaskRowDelegate, is_checked
from test_gui import setup_vault, win  # noqa: F401

UR = Qt.ItemDataRole.UserRole


# ---------------------------------------------------------------------------------- Today: done ticks ---
def test_is_checked_reads_both_the_int_and_the_enum():
    assert is_checked(2) and is_checked(Qt.CheckState.Checked)
    assert not is_checked(0) and not is_checked(Qt.CheckState.Unchecked) and not is_checked(None)
    assert not is_checked(Qt.CheckState.PartiallyChecked)


def test_a_list_widget_hands_back_an_int_which_is_not_equal_to_the_enum(qapp):
    """The trap behind the bug: QListWidget's own model returns 2, and ``2 == Qt.CheckState.Checked`` is False."""
    lw = QListWidget()
    it = QListWidgetItem("x")
    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
    it.setCheckState(Qt.CheckState.Checked)
    lw.addItem(it)
    v = lw.model().index(0, 0).data(Qt.ItemDataRole.CheckStateRole)
    assert v != Qt.CheckState.Checked and is_checked(v)


def _list(qtbot, done_flags):
    lw = QListWidget()
    qtbot.addWidget(lw)
    lw.resize(520, 300)
    d = TaskRowDelegate(lw)
    lw.setItemDelegate(d)
    for i, done in enumerate(done_flags):
        it = QListWidgetItem(f"task {i}")
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        it.setData(UR, f"id{i}")
        lw.addItem(it)
    lw.show()
    return lw, d


def _paint_row(lw, d, row, monkeypatch):
    seen = []
    monkeypatch.setattr(premium, "paint_check", lambda p, r, checked, *a, **k: seen.append(bool(checked)))
    img = QImage(520, 80, QImage.Format.Format_ARGB32)
    img.fill(0)
    opt = QStyleOptionViewItem()
    opt.widget, opt.rect, opt.font = lw, QRect(0, 0, 520, TaskRowDelegate.H), lw.font()
    p = QPainter(img)
    d.paint(p, opt, lw.model().index(row, 0))
    p.end()
    return seen


def test_today_row_paints_a_done_task_as_done(qtbot, monkeypatch):
    lw, d = _list(qtbot, [True, False])
    assert _paint_row(lw, d, 0, monkeypatch) == [True]
    assert _paint_row(lw, d, 1, monkeypatch) == [False]


def _release(lw, d, row):
    opt = QStyleOptionViewItem()
    opt.widget, opt.rect = lw, QRect(0, 0, 520, TaskRowDelegate.H)
    box = opt.rect.adjusted(2, 2, -2, -2)
    c = d._circle(__import__("PyQt6.QtCore", fromlist=["QRectF"]).QRectF(box)).center()
    ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(c), QPointF(c), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    return d.editorEvent(ev, lw.model(), opt, lw.model().index(row, 0))


def test_clicking_the_circle_of_a_done_task_unchecks_it(qtbot):
    lw, d = _list(qtbot, [True, False])
    assert _release(lw, d, 0) is True
    assert lw.item(0).checkState() == Qt.CheckState.Unchecked            # before the fix it stayed checked forever
    assert _release(lw, d, 1) is True
    assert lw.item(1).checkState() == Qt.CheckState.Checked
    assert _release(lw, d, 1) is True
    assert lw.item(1).checkState() == Qt.CheckState.Unchecked            # and back again


def test_today_page_shows_completed_tasks_ticked_and_the_counts_agree(win, monkeypatch):
    setup_vault(win)
    j = jalali.today_jalali()
    a, b = logic.new_task("done one", due=j), logic.new_task("open one", due=j)
    a["done"], a["doneAt"] = True, dt.datetime.now().isoformat()
    win.store.vault["tasks"] = [a, b]
    win.changed()
    win.show_page("today")
    pg = win.pages["today"]
    lw = pg.today
    rows = {lw.item(i).text(): i for i in range(lw.count())}
    assert lw.item(rows["done one"]).checkState() == Qt.CheckState.Checked
    d = lw.itemDelegate()
    assert _paint_row(lw, d, rows["done one"], monkeypatch) == [True]
    assert _paint_row(lw, d, rows["open one"], monkeypatch) == [False]
    # un-tick through the delegate: the task in the vault goes back to open
    _release(lw, d, rows["done one"])
    assert not next(t for t in win.store.vault["tasks"] if t["title"] == "done one")["done"]


# ---------------------------------------------------------------------------------- Habits: wide heatmap ---
def _hm(width):
    h = HabitHeatmap([{"log": {}}])
    h.resize(width, h.height())
    h.show()                                                             # a hidden widget gets no resizeEvent
    return h


def test_heatmap_keeps_13px_squares_until_a_year_fits_then_grows(qtbot):
    narrow, mid, wide = _hm(520), _hm(900), _hm(1600)
    for h in (narrow, mid, wide):
        qtbot.addWidget(h)
    assert narrow.cell == 13 and narrow.weeks < 52
    assert mid.cell == 13 and mid.weeks == 52                            # 52 x 16 = 832 fits, no growth needed
    assert wide.cell > 13 and wide.weeks == 52


def test_heatmap_fills_a_wide_card_within_one_square(qtbot):
    for w in (1000, 1300, 1600, 1900):
        h = _hm(w)
        qtbot.addWidget(h)
        used = h.weeks * (h.cell + h.GAP)
        assert h.cell <= h.MAX_CELL
        if h.cell < h.MAX_CELL:
            assert (w - 28) - used < (h.cell + h.GAP) + 52, (w, h.cell, used)     # the strip left blank is under a square + rounding
        assert h.height() == 7 * (h.cell + h.GAP) + 44                   # the card grows with the squares


def test_heatmap_shrinks_back_when_the_window_narrows(qtbot):
    h = _hm(1600)
    qtbot.addWidget(h)
    big = h.height()
    h.resize(700, h.height())
    h.grab()
    assert h.cell == 13 and h.height() < big


# ---------------------------------------------------------------------------------- busy global shortcut ---
class _U32:
    def __init__(self, busy=()):
        self.busy, self.calls = set(busy), []

    def RegisterHotKey(self, hwnd, hid, mods, vk):  # noqa: N802
        self.calls.append(("reg", mods & ~hotkey.MOD_NOREPEAT, vk))
        return 0 if (mods & ~hotkey.MOD_NOREPEAT, vk) in self.busy else 1

    def UnregisterHotKey(self, hwnd, hid):  # noqa: N802
        self.calls.append(("unreg",))
        return 1


CA = (hotkey.MOD_CONTROL | hotkey.MOD_ALT, hotkey.VK_SPACE)
CS = (hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, hotkey.VK_SPACE)
CAS = (hotkey.MOD_CONTROL | hotkey.MOD_ALT | hotkey.MOD_SHIFT, hotkey.VK_SPACE)


def test_free_shortcut_is_used_as_before(qapp):
    u = _U32()
    hk = hotkey.GlobalHotkey(qapp, lambda: None, user32=u)
    assert hk.enable() and hk.label == "Ctrl+Alt+Space" and not hk.fell_back and len(u.calls) == 1
    hk.disable()


def test_busy_first_shortcut_falls_back_to_the_next(qapp):
    u = _U32(busy={CA})
    hk = hotkey.GlobalHotkey(qapp, lambda: None, user32=u)
    assert hk.enable() and hk.active and hk.fell_back and hk.label == "Ctrl+Shift+Space"
    assert [c[1:] for c in u.calls] == [CA, CS]
    hk.disable()
    assert u.calls[-1] == ("unreg",) and not hk.active


def test_two_busy_shortcuts_reach_the_third_and_all_busy_reports_false(qapp):
    hk = hotkey.GlobalHotkey(qapp, lambda: None, user32=_U32(busy={CA, CS}))
    assert hk.enable() and hk.label == "Ctrl+Alt+Shift+Space"
    hk.disable()
    none = hotkey.GlobalHotkey(qapp, lambda: None, user32=_U32(busy={CA, CS, CAS}))
    assert none.enable() is False and not none.active and none.filter is None


def test_settings_row_promises_the_shortcut_that_is_live(win):
    setup_vault(win)
    sp = win.pages["settings"]
    win.hotkey_label = "Ctrl+Shift+Space"
    assert "Ctrl+Shift+Space" in sp._hotkey_text() and "Ctrl+Alt+Space" not in sp._hotkey_text()
    sp.sync_hotkey_text()                                                # no switch row off Windows: must not raise
