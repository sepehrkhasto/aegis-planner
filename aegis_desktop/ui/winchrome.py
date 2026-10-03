# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows title-bar theming: dark/light caption + caption colour that matches the app (Windows 10 20H1+/11).

Everything is best-effort and silently skipped elsewhere, so the app never depends on it."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget

_STATE: dict = {"pal": None, "dark": True, "filter": None}


def _cref(hex_: str) -> int:
    c = QColor(hex_)
    return c.red() | (c.green() << 8) | (c.blue() << 16)


# DWM window attributes (dwmapi.h): dark caption, corner style, border / caption / text colours (Windows 11)
ATTR_DARK, ATTR_CORNER, ATTR_BORDER, ATTR_CAPTION, ATTR_TEXT = 20, 33, 34, 35, 36
CORNER_ROUND = 2


def frame_attrs(pal: dict, dark: bool) -> list[tuple[int, int]]:
    """(attribute, value) pairs that make the native frame part of the theme: caption and border take the page colours
    so the title bar melts into the app instead of sitting on it as a grey strip."""
    return [(ATTR_DARK, 1 if dark else 0), (ATTR_CORNER, CORNER_ROUND), (ATTR_CAPTION, _cref(pal["bg"])),
            (ATTR_TEXT, _cref(pal["text"])), (ATTR_BORDER, _cref(pal["line"]))]


def apply_to(dwm, hwnd, pal: dict, dark: bool) -> int:
    """Push the frame attributes through ``dwm`` (ctypes.windll.dwmapi or a test double); returns how many calls were made.
    Each attribute is independent: an unsupported one (older Windows) fails alone."""
    import ctypes
    n = 0
    for attr, val in frame_attrs(pal, dark):
        try:
            v = ctypes.c_int(val)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def apply(w: QWidget) -> None:
    pal = _STATE["pal"]
    if not sys.platform.startswith("win") or not pal:
        return
    try:
        import ctypes
        from ctypes import wintypes
        apply_to(ctypes.windll.dwmapi, wintypes.HWND(int(w.winId())), pal, _STATE["dark"])
    except Exception:  # noqa: BLE001
        pass


class _Filter(QObject):
    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            if obj.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog):
                apply(obj)
        return False


def set_theme(app, pal: dict, dark: bool) -> None:
    """Remember the active palette and restyle every open window's title bar."""
    _STATE["pal"], _STATE["dark"] = dict(pal), dark
    if not sys.platform.startswith("win"):
        return
    if _STATE["filter"] is None:
        _STATE["filter"] = _Filter(app)
        app.installEventFilter(_STATE["filter"])
    for w in app.topLevelWidgets():
        if w.isVisible():
            apply(w)
