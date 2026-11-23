# SPDX-License-Identifier: GPL-3.0-or-later
"""tokens, brand empty states, skeleton, vault ritual + ingot meter, polish (scroll glide, tray state)."""
import re
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QScrollArea, QWidget

from aegis_desktop.ui import brand, moments, skeleton, theme, tokens
from aegis_desktop.ui.anim import MOTION
from test_gui import setup_vault, win  # noqa: F401

UI = Path(__file__).resolve().parent.parent / "aegis_desktop" / "ui"


# ------------------------------------------------------------------------------------------- N5 tokens ---
def test_tokens_are_sane():
    assert list(tokens.SPACE.values()) == sorted(tokens.SPACE.values())
    assert all(v % 2 == 0 for v in tokens.SPACE.values())
    assert len(tokens.PAGE) == 4 and len(tokens.DIALOG) == 4
    assert tokens.TYPE["caption"] < tokens.TYPE["small"] < tokens.TYPE["body"] < tokens.TYPE["h1"] < tokens.TYPE["hero"]


def test_stylesheet_font_sizes_stay_on_the_scale(qapp):
    used = {float(x) for x in re.findall(r"font-size:\s*([0-9.]+)pt", theme.stylesheet("dark"))}
    assert used <= set(tokens.TYPE.values()), used - set(tokens.TYPE.values())


def test_pages_and_dialogs_use_the_margin_tokens():
    for f in ("pages.py", "settings_page.py", "calendar_view.py"):
        src = (UI / f).read_text(encoding="utf-8")
        assert "(24, 20, 24, 20)" not in src, f
    for f in ("dialogs.py", "backup_ui.py"):
        assert "(22, 20, 22, 18)" not in (UI / f).read_text(encoding="utf-8"), f


def test_every_page_has_the_same_outer_margins(win):
    setup_vault(win)
    seen = {}
    for key, page in win.pages.items():
        m = page.layout().contentsMargins() if page.layout() else None
        if m is not None:
            seen[key] = (m.left(), m.top(), m.right(), m.bottom())
    pad = {k: v for k, v in seen.items() if v != (0, 0, 0, 0)}
    assert pad and set(pad.values()) == {tokens.PAGE}, pad


# ------------------------------------------------------------------------------------- N6 empty states ---
@pytest.mark.parametrize("icon", ["tasks", "check", "calendar", "notes", "trash", "habits", "goals", "focus", "reports", "sparkle"])
def test_brand_empty_art_draws_for_every_page_glyph(qapp, icon):
    pal = theme.THEMES["noir"]["pal"]
    pm = QPixmap(220, 200)
    pm.fill(QColor(pal["bg"]))
    p = QPainter(pm)
    assert brand.paint_empty_art(p, 110, 100, pal, icon)
    p.end()
    img = pm.toImage()
    lit = sum(1 for x in range(0, 220, 2) for y in range(0, 200, 2) if img.pixelColor(x, y) != QColor(pal["bg"]))
    assert lit > 300                                          # something real was drawn


def test_empty_art_unknown_icon_falls_back(qapp):
    pal = theme.THEMES["noir"]["pal"]
    pm = QPixmap(200, 200)
    p = QPainter(pm)
    assert brand.paint_empty_art(p, 100, 100, pal, "no-such-icon") is False
    p.end()


def test_empty_art_on_light_theme(qapp):
    pal = theme.THEMES["aegis-light"]["pal"]
    pm = QPixmap(220, 200)
    pm.fill(QColor(pal["bg"]))
    p = QPainter(pm)
    assert brand.paint_empty_art(p, 110, 100, pal, "tasks")
    p.end()


# --------------------------------------------------------------------------------------- N7 skeleton ---
def test_skeleton_layout_fits_any_size():
    for w, h in ((400, 300), (1000, 700), (1900, 1100), (50, 50)):
        for r, _k in skeleton.layout_blocks(w, h):
            assert r.width() > 0 and r.height() > 0


def test_skeleton_covers_reports_then_dissolves(win):
    setup_vault(win)
    win.show_page("today"); QTest.qWait(200)
    win.show_page("reports")
    sk = win.pages["reports"]._skeleton
    assert sk is not None and sk.isVisible()
    assert not win.pages["reports"].grab().isNull()
    QTest.qWait(1000)
    assert win.pages["reports"]._skeleton is None            # gone, and the real page is underneath
    assert win.pages["reports"].area.data is not None


def test_skeleton_skipped_with_reduced_motion(win):
    setup_vault(win)
    old = MOTION[0]
    try:
        MOTION[0] = False
        win.show_page("today"); QTest.qWait(50)
        win.show_page("reports"); QTest.qWait(50)
        assert getattr(win.pages["reports"], "_skeleton", None) is None
    finally:
        MOTION[0] = old


# ------------------------------------------------------------------- N8 ingot meter + vault ritual ---
def test_strength_ingot_fills_and_glints(qtbot):
    from aegis_desktop.ui.fx_widgets import StrengthMeter
    m = StrengthMeter()
    qtbot.addWidget(m); m.resize(320, 200); m.show()
    empty = m.grab().toImage()
    m.set_password("Abcdefghij1!")
    qtbot.wait(100)
    assert m._glint.a.state().name == "Running"               # full: the glint runs
    qtbot.wait(1200)
    assert m._score.value == pytest.approx(5.0, abs=0.01)
    assert m.grab().toImage() != empty
    m.set_password("")
    qtbot.wait(700)
    assert m._score.value == pytest.approx(0.0, abs=0.01)


def test_vault_born_doors_carry_a_caption_and_hold_longer(win, qtbot):
    from aegis_desktop.ui.voice import VOICE
    assert VOICE["vault_born"]
    d = moments._Doors(win.shell, 1000, True, hold=0.45, caption=VOICE["vault_born"])
    assert d.hold == 0.45 and d.caption
    d.k = 0.3
    assert d._openness() == 0.0                                # still shut during the long hold
    d.k = 1.0
    assert d._openness() == pytest.approx(1.0)
    d.k = 0.35
    pm = QPixmap(win.shell.size()); d.resize(win.shell.size()); d.render(pm)
    assert not pm.isNull()
    d.deleteLater()


def test_creation_flag_selects_the_ritual(win, monkeypatch):
    calls = []
    monkeypatch.setattr(moments, "vault_born", lambda host, cap: calls.append("born"))
    monkeypatch.setattr(moments, "unlock_bloom", lambda host: calls.append("bloom"))
    setup_vault(win)
    assert calls == ["born"] and win.auth.created_now is False       # first run: the long ritual, once
    win.lock(); QTest.qWait(50)
    from test_gui import PW
    win.auth.u1.edit.setText(PW); win.auth._unlock()
    QTest.qWait(300)
    assert win.store.is_unlocked and calls == ["born", "bloom"]      # every later unlock: the short doors


# --------------------------------------------------------------------------------------- N9 polish ---
def test_tray_icon_states(qapp):
    a, b = brand.tray_icon(True), brand.tray_icon(False)
    pa, pb = a.pixmap(32, 32).toImage(), b.pixmap(32, 32).toImage()
    assert not pa.isNull() and not pb.isNull() and pa != pb


def test_window_tray_follows_lock(win):
    setup_vault(win)
    assert win._tray_locked is False
    win.lock(); QTest.qWait(50)
    assert win._tray_locked is True


def _wheel(w, dy):
    ev = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(w.viewport(), ev)


def test_wheel_glides_instead_of_jumping(qtbot):
    from aegis_desktop.ui import scrollfx
    sa = QScrollArea(); inner = QWidget(); inner.setFixedSize(300, 4000)
    sa.setWidget(inner); sa.resize(320, 300); qtbot.addWidget(sa); sa.show()
    scrollfx.attach(sa)
    _wheel(sa, -120)
    assert sa.verticalScrollBar().value() < 84                   # not there yet: it is gliding
    qtbot.waitUntil(lambda: sa.verticalScrollBar().value() == 84, timeout=1500)
    _wheel(sa, -120); _wheel(sa, -120)                           # two quick notches accumulate into one motion
    qtbot.waitUntil(lambda: sa.verticalScrollBar().value() == 84 * 3, timeout=1500)
    for _ in range(3):
        _wheel(sa, 120)
    qtbot.waitUntil(lambda: sa.verticalScrollBar().value() == 0, timeout=1500)
    _wheel(sa, 120)                                               # at the top: nothing happens, no error
    assert sa.verticalScrollBar().value() == 0


def test_wheel_native_when_motion_reduced(qtbot):
    from aegis_desktop.ui import scrollfx
    old = MOTION[0]
    try:
        MOTION[0] = False
        sa = QScrollArea(); inner = QWidget(); inner.setFixedSize(300, 4000)
        sa.setWidget(inner); sa.resize(320, 300); qtbot.addWidget(sa); sa.show()
        scrollfx.attach(sa)
        _wheel(sa, -120)
        assert sa.verticalScrollBar().value() > 0                  # Qt's own immediate step
    finally:
        MOTION[0] = old


def test_selection_colour_comes_from_the_theme(qapp):
    qss = theme.stylesheet("dark")
    assert "selection-background-color: rgba(" in qss


# ------------------------------------------------------------------------------- O10 global hotkey ---
class _FakeUser32:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def RegisterHotKey(self, hwnd, hid, mods, vk):  # noqa: N802
        self.calls.append(("reg", hid, mods, vk))
        return 1 if self.ok else 0

    def UnregisterHotKey(self, hwnd, hid):  # noqa: N802
        self.calls.append(("unreg", hid))
        return 1


def test_hotkey_registers_ctrl_alt_space_and_unregisters(qapp):
    from aegis_desktop.ui import hotkey
    u = _FakeUser32()
    hk = hotkey.GlobalHotkey(qapp, lambda: None, user32=u)
    assert hk.enable() and hk.active and hk.enable()                       # idempotent
    kind, hid, mods, vk = u.calls[0]
    assert (kind, hid, vk) == ("reg", hotkey.HOTKEY_ID, hotkey.VK_SPACE)
    assert mods & hotkey.MOD_CONTROL and mods & hotkey.MOD_ALT and mods & hotkey.MOD_NOREPEAT
    assert len(u.calls) == 1
    hk.disable()
    assert not hk.active and u.calls[-1] == ("unreg", hotkey.HOTKEY_ID)
    hk.disable()                                                            # twice is harmless


def test_hotkey_taken_by_another_app_reports_false(qapp):
    from aegis_desktop.ui import hotkey
    hk = hotkey.GlobalHotkey(qapp, lambda: None, user32=_FakeUser32(ok=False))
    assert hk.enable() is False and not hk.active and hk.filter is None


def test_hotkey_unavailable_off_windows(qapp):
    import sys
    from aegis_desktop.ui import hotkey
    if not sys.platform.startswith("win"):
        assert hotkey.available() is False
        assert hotkey.GlobalHotkey(qapp, lambda: None).enable() is False


def test_hotkey_filter_only_reacts_to_our_message(qapp):
    from aegis_desktop.ui import hotkey
    hits = []
    f = hotkey.HotkeyFilter(lambda: hits.append(1), matcher=lambda m, i: m == "ours")
    assert f.nativeEventFilter(b"windows_generic_MSG", "ours") == (True, 0) and hits == [1]
    assert f.nativeEventFilter(b"windows_generic_MSG", "other") == (False, 0) and hits == [1]
    assert f.nativeEventFilter(b"xcb_generic_event_t", "ours") == (False, 0)


def test_hotkey_callback_errors_never_escape(qapp):
    from aegis_desktop.ui import hotkey

    def boom():
        raise RuntimeError("x")
    f = hotkey.HotkeyFilter(boom, matcher=lambda m, i: True)
    assert f.nativeEventFilter(b"windows_generic_MSG", 1) == (True, 0)


def test_msg_is_hotkey_parses_a_win32_msg(qapp):
    import ctypes
    from ctypes import wintypes
    from aegis_desktop.ui import hotkey

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT)]
    m = MSG(None, hotkey.WM_HOTKEY, hotkey.HOTKEY_ID, 0, 0, wintypes.POINT(0, 0))
    assert hotkey.msg_is_hotkey(ctypes.addressof(m))
    m.wParam = 5
    assert not hotkey.msg_is_hotkey(ctypes.addressof(m))
    m.message, m.wParam = 0x0100, hotkey.HOTKEY_ID
    assert not hotkey.msg_is_hotkey(ctypes.addressof(m))
    assert not hotkey.msg_is_hotkey("garbage")


def test_quick_add_creates_a_parsed_task_and_closes(win, qtbot):
    setup_vault(win)
    n = len(win.store.vault["tasks"])
    win.show_quick_add()
    box = win._quick_add_box
    assert box.isVisible() and box.q.isEnabled()
    box.q.setText("تسک بساز فردا ساعت ۱۰ جلسه با استاد")
    assert "جلسه با استاد" in box.hint and "فردا" in box.hint
    assert box.submit() is True
    t = win.store.vault["tasks"][-1]
    assert len(win.store.vault["tasks"]) == n + 1 and t["timeFrom"] == "10:00" and "جلسه" in t["title"]
    qtbot.waitUntil(lambda: not box.isVisible(), timeout=2000)
    win.perform_undo()
    assert len(win.store.vault["tasks"]) == n


def test_quick_add_plain_text_becomes_the_title(win):
    setup_vault(win)
    win.show_quick_add()
    box = win._quick_add_box
    box.q.setText("خرید نان")
    box.submit()
    assert win.store.vault["tasks"][-1]["title"] == "خرید نان"


def test_quick_add_ignores_empty_input_and_escape_closes(win, qtbot):
    setup_vault(win)
    n = len(win.store.vault["tasks"])
    win.show_quick_add()
    box = win._quick_add_box
    assert box.submit() is False
    box.q.setText("   "); assert box.submit() is False
    assert len(win.store.vault["tasks"]) == n
    qtbot.keyClick(box, Qt.Key.Key_Escape)
    assert not box.isVisible()


def test_quick_add_when_locked_creates_nothing(win):
    setup_vault(win)
    win.lock(); QTest.qWait(50)
    win.show_quick_add()
    box = win._quick_add_box
    assert box.locked and not box.q.isEnabled()
    assert box.submit() is False
    box.reject()


def test_quick_add_second_call_reuses_the_open_box(win):
    setup_vault(win)
    win.show_quick_add()
    a = win._quick_add_box
    win.show_quick_add()
    assert win._quick_add_box is a
    a.reject()


def test_hotkey_pref_wires_enable_and_disable(win, monkeypatch):
    from aegis_desktop.ui import hotkey
    monkeypatch.setattr(hotkey, "available", lambda: True)
    u = _FakeUser32()
    win._hotkey = hotkey.GlobalHotkey(QApplication.instance(), win.show_quick_add, user32=u)
    win.set_pref("global_hotkey", True)
    assert win._hotkey.active
    win.set_pref("global_hotkey", False)
    assert not win._hotkey.active and u.calls[-1][0] == "unreg"
