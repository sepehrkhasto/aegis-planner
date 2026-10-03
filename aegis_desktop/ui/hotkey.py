# SPDX-License-Identifier: GPL-3.0-or-later
"""Global quick-add hotkey (Windows): Ctrl+Alt+Space from anywhere opens a small glass box that captures a task.

RegisterHotKey is a documented user32 call and needs no admin rights and no hook DLL. WM_HOTKEY arrives as a native
event on the thread that registered; ``HotkeyFilter`` receives it through Qt. Everywhere else this module does
nothing (``available()`` is False). Everything that touches ctypes takes an injectable ``user32`` so it is unit-tested
on Linux; the real behaviour can only be confirmed on Windows."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QAbstractNativeEventFilter

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
VK_SPACE = 0x20
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xA361
DEFAULT_LABEL = "Ctrl+Alt+Space"
# Tried in order: another program (launchers, clipboard tools) may already own the first one.
COMBOS = ((MOD_CONTROL | MOD_ALT, VK_SPACE, "Ctrl+Alt+Space"),
          (MOD_CONTROL | MOD_SHIFT, VK_SPACE, "Ctrl+Shift+Space"),
          (MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_SPACE, "Ctrl+Alt+Shift+Space"))


def available() -> bool:
    return sys.platform.startswith("win")


def _user32():
    import ctypes
    return ctypes.windll.user32


def msg_is_hotkey(message, hotkey_id: int = HOTKEY_ID) -> bool:
    """True if ``message`` (a pointer to a Win32 MSG) is our WM_HOTKEY. Never raises."""
    try:
        import ctypes
        from ctypes import wintypes

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                        ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT)]
        m = MSG.from_address(int(message))
        return m.message == WM_HOTKEY and int(m.wParam) == hotkey_id
    except Exception:  # noqa: BLE001
        return False


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, callback, hotkey_id: int = HOTKEY_ID, matcher=msg_is_hotkey):
        super().__init__()
        self.callback, self.id, self.matcher = callback, hotkey_id, matcher

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG") and self.matcher(message, self.id):
            try:
                self.callback()
            except Exception:  # noqa: BLE001 - a hotkey must never take the app down
                pass
            return True, 0
        return False, 0


class GlobalHotkey:
    """Owns the registration. ``enable()`` -> bool (False if unavailable or every combination is already taken).

    The first combination is the preferred one; when Windows refuses it (someone else registered it) the next is tried, and
    ``label`` says which one is live so the UI never promises a shortcut that does not work."""

    def __init__(self, app, callback, user32=None, mods: int = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk: int = VK_SPACE,
                 combos=COMBOS):
        self.app, self.callback, self.mods, self.vk = app, callback, mods, vk
        self.combos = [(mods, vk, DEFAULT_LABEL)] + [c for c in combos[1:]]
        self._u32 = user32
        self.filter: HotkeyFilter | None = None
        self.active = False
        self.label = DEFAULT_LABEL
        self.fell_back = False

    def enable(self) -> bool:
        if self.active:
            return True
        u32 = self._u32 or (_user32() if available() else None)
        if u32 is None:
            return False
        ok = False
        for i, (mods, vk, label) in enumerate(self.combos):
            try:
                ok = bool(u32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk))
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                self.label, self.fell_back = label, i > 0
                break
        if not ok:
            return False
        self.filter = HotkeyFilter(self.callback)
        self.app.installNativeEventFilter(self.filter)
        self._u32 = u32
        self.active = True
        return True

    def disable(self) -> None:
        if not self.active:
            return
        try:
            self._u32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:  # noqa: BLE001
            pass
        if self.filter is not None:
            self.app.removeNativeEventFilter(self.filter)
        self.filter, self.active = None, False
