# SPDX-License-Identifier: GPL-3.0-or-later
"""Gold Black theme, cinematic sign-in, sounds (off by default), Focus mode, first-run tour."""
import io
import wave

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import sfx, theme
from aegis_desktop.ui.cinema import GlowMark, LockGlyph
from aegis_desktop.ui.focusmode import FocusMode, pick_tasks
from test_gui import setup_vault, win  # noqa: F401


# ---------------------------------------------------------------- theme ---
def test_new_theme_is_complete_and_applies_everywhere(win):
    g, n = theme.THEMES["coffee"], theme.THEMES["noir"]
    assert "coffee" in theme.THEME_ORDER and g["mode"] == "dark" and set(g["pal"]) == set(n["pal"])
    assert g["fa"] and g["en"] and len(g["chart"]) == len(n["chart"])
    setup_vault(win)
    win.set_pref("palette", "coffee")
    assert win.theme == "dark" and theme.PALETTES["dark"]["accent"].lower() == "#a27b5c"
    for k in win.pages:
        win.show_page(k); QTest.qWait(30)
        assert not win.pages[k].grab().isNull()


# ---------------------------------------------------------------- sounds ---
def test_sounds_off_by_default_and_wavs_are_valid(win, monkeypatch):
    assert sfx.ENABLED[0] is False and win.prefs.get("sounds", False) is False
    heard = []
    monkeypatch.setattr(sfx, "_emit", lambda d: heard.append(len(d)))
    assert sfx.play("tick") is False and heard == []
    for name, lo, hi in (("tick", 0.03, 0.2), ("open", 0.2, 1.0), ("bell", 0.5, 2.0)):
        with wave.open(io.BytesIO(sfx.build(name))) as w:
            dur = w.getnframes() / w.getframerate()
            assert lo < dur < hi and w.getnchannels() == 1 and w.getsampwidth() == 2
    with pytest.raises(KeyError):
        sfx.build("nope")
    setup_vault(win)
    win.set_pref("sounds", True)
    assert sfx.ENABLED[0] is True and heard                                  # preview tick
    heard.clear()
    from aegis_desktop.ui import micro
    micro.check_kick(win.pages["tasks"].table, "x", True)
    assert heard                                                            # completing plays the tick
    heard.clear()
    micro.check_kick(win.pages["tasks"].table, "x", False)
    assert not heard                                                        # un-ticking is silent
    win.set_pref("sounds", False)
    assert sfx.ENABLED[0] is False


def test_sound_failure_never_raises(monkeypatch):
    sfx.ENABLED[0] = True
    try:
        monkeypatch.setattr(sfx, "build", lambda n: (_ for _ in ()).throw(RuntimeError("no device")))
        assert sfx.play("open") is False
    finally:
        sfx.ENABLED[0] = False


# ---------------------------------------------------------------- sign-in ---
def test_lock_glyph_and_glow_mark(qtbot):
    lk = LockGlyph(); qtbot.addWidget(lk); lk.show()
    for k in (0, 0.3, 1, 5, -2):
        lk.set_level(k)
        QTest.qWait(300)
        assert 0.0 <= lk.level <= 1.0 and not lk.grab().isNull()
    lk.set_level(1); QTest.qWait(320)
    assert lk.level == pytest.approx(1.0)
    gm = GlowMark(64); qtbot.addWidget(gm); gm.show(); gm.flash(); QTest.qWait(60)
    assert not gm.grab().isNull() and gm.width() > 64


def test_lock_follows_typing_and_closes_on_success(win):
    a = win.auth
    a.stack.setCurrentIndex(0)
    a.s1.edit.setText("x" * 5); QTest.qWait(320)
    assert 0.3 < a.s_lock._goal < 0.7
    a.s1.edit.setText("x" * 12); QTest.qWait(320)
    assert a.s_lock._goal == 1.0
    a.s1.edit.clear(); QTest.qWait(320)
    assert a.s_lock._goal == 0.0
    setup_vault(win)                                                         # success path runs _success()
    assert a.u_lock._goal == 1.0 and a.s_lock._goal == 1.0


# ---------------------------------------------------------------- focus mode ---
def test_pick_tasks_order():
    import datetime as dt
    T = dt.date.today()
    d = lambda n: jalali.date_to_due(T + dt.timedelta(n))
    v = {"tasks": [logic.new_task("later", due=d(9)), logic.new_task("none"), logic.new_task("late", due=d(-3)),
                   logic.new_task("t2", due=d(0), timeFrom="15:00"), logic.new_task("t1", due=d(0), timeFrom="09:00"),
                   logic.new_task("done", due=d(0), done=True), logic.new_task("ev", due=d(0), kind="event")]}
    assert [t["title"] for t in pick_tasks(v)] == ["t1", "t2", "late", "later", "none"]
    assert pick_tasks({"tasks": []}) == [] and pick_tasks({}) == []


def test_focus_mode_flow(win):
    setup_vault(win)
    win.store.vault["tasks"] = [logic.new_task("اول", due=jalali.today_jalali(), timeFrom="08:00"),
                                logic.new_task("دوم", due=jalali.today_jalali(), timeFrom="09:00")]
    win.changed()
    win.enter_focus_mode(); QTest.qWait(400)
    fm = win._focus_mode
    assert isinstance(fm, FocusMode) and fm.isVisible() and fm.geometry() == win.root.rect()
    assert fm.current()["title"] == "اول"
    assert not fm.grab().isNull()
    fm.retask(1)
    assert fm.current()["title"] == "دوم"
    fm.retask(1)
    assert fm.current()["title"] == "اول"                                     # cycles
    fm.play.clicked.emit(); QTest.qWait(30)
    assert win.pages["focus"].running and fm.play.icon == "pause"
    fm.play.clicked.emit()
    assert not win.pages["focus"].running
    fm.complete(); QTest.qWait(30)
    assert [t["done"] for t in win.store.vault["tasks"]] == [True, False] and fm.current()["title"] == "دوم"
    win.perform_undo()
    assert win.store.vault["tasks"][0]["done"] is False
    QTest.keyClick(fm, Qt.Key.Key_Escape); QTest.qWait(450)
    assert not fm.isVisible()


def test_focus_mode_empty_and_lock(win):
    setup_vault(win)
    win.store.vault["tasks"] = []
    win.changed()
    win.enter_focus_mode(); QTest.qWait(350)
    fm = win._focus_mode
    assert fm.current() is None and not fm.grab().isNull()
    fm.retask(1)                                                            # no tasks: still fine
    win.lock()
    assert not fm.isVisible() and not fm.poll.isActive()
    win.enter_focus_mode()                                                   # locked: refuses quietly
    assert not fm.isVisible()


def test_focus_command_in_palette_and_page_button(win):
    setup_vault(win)
    from aegis_desktop.ui.main_window import Palette
    p = Palette(win)
    p.q.setText("تمرکز")
    assert any(p.list.item(i).data(0x100) == ("cmd", "focus") for i in range(p.list.count()))
    win.show_page("focus"); QTest.qWait(60)
    from PyQt6.QtWidgets import QPushButton
    btn = next(b for b in win.pages["focus"].findChildren(QPushButton) if b.text() == "حالت تمرکز کامل")
    btn.click(); QTest.qWait(350)
    assert win._focus_mode.isVisible()


