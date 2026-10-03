# SPDX-License-Identifier: GPL-3.0-or-later
"""Inline SVG icon set (24x24, stroke style). Rendered through QtSvg and cached per (name, color, size).

The 'tasks' icon is the checked-box glyph supplied by the user.
"""
from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_S = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'

ICONS: dict[str, str] = {
    "shield": f'<g {_S}><path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.2 7.5 9.5 4.4-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m8.8 12.2 2.3 2.3 4.2-4.6"/></g>',
    "backup": f'<g {_S}><path d="M12 3v11M7.5 9.5 12 14l4.5-4.5"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/></g>',
    "palette": f'<g {_S}><path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.4 0 2-1 1.5-2.2-.5-1.2.3-2.3 1.6-2.3H17a3.5 3.5 0 0 0 3.5-3.5C20.5 7.2 16.7 3.5 12 3.5z"/><circle cx="8" cy="11" r=".7"/><circle cx="11" cy="7.7" r=".7"/><circle cx="15.3" cy="8.5" r=".7"/></g>',
    "bell": f'<g {_S}><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2H4.5z"/><path d="M10 21h4"/></g>',
    "database": f'<g {_S}><ellipse cx="12" cy="6" rx="7.5" ry="2.8"/><path d="M4.5 6v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6"/></g>',
    "info": f'<g {_S}><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.1"/></g>',
    "today": f'<g {_S}><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/></g>',
    # user-supplied check-in-box glyph (filled paths)
    "tasks": '<path fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" d="m20.215 2.387-8.258 10.547-2.704-3.092a1 1 0 1 0-1.506 1.316l3.103 3.548a1.5 1.5 0 0 0 2.31-.063L21.79 3.62a1 1 0 1 0-1.575-1.233zM20 11a1 1 0 0 0-1 1v6.077c0 .459-.021.57-.082.684a.364.364 0 0 1-.157.157c-.113.06-.225.082-.684.082H5.923c-.459 0-.57-.022-.684-.082a.363.363 0 0 1-.157-.157c-.06-.113-.082-.225-.082-.684V5.5a.5.5 0 0 1 .5-.5l8.5.004a1 1 0 1 0 0-2L5.5 3A2.5 2.5 0 0 0 3 5.5v12.577c0 .76.082 1.185.319 1.627.224.419.558.753.977.977.442.237.866.319 1.627.319h12.154c.76 0 1.185-.082 1.627-.319.42-.224.754-.558.978-.977.236-.442.318-.866.318-1.627V12a1 1 0 0 0-1-1z"/>',
    "calendar": f'<g {_S}><rect x="3.5" y="5" width="17" height="15.5" rx="3"/><path d="M8 3v4M16 3v4M3.5 10h17"/><circle cx="8.5" cy="14.5" r=".6"/><circle cx="12" cy="14.5" r=".6"/><circle cx="15.5" cy="14.5" r=".6"/></g>',
    "kanban": f'<g {_S}><rect x="3.5" y="4" width="5" height="16" rx="1.6"/><rect x="10" y="4" width="5" height="10" rx="1.6"/><rect x="16.5" y="4" width="4" height="13" rx="1.6"/></g>',
    "notes": f'<g {_S}><path d="M6 3.5h9l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-11.5A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 6 3.5z"/><path d="M14.5 3.5V8H19M8 12.5h8M8 16h5"/></g>',
    "habits": f'<g {_S}><path d="M12 3c.5 3-2.5 4.5-2.5 7.5 0 1 .4 1.7 1 2.2C9.3 12.5 7 12 7 14.5A5 5 0 0 0 12 20a5 5 0 0 0 5-5c0-3.5-3.5-4.5-5-12z"/></g>',
    "goals": f'<g {_S}><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r=".8"/></g>',
    "focus": f'<g {_S}><circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.5 1.5M9.5 3h5"/></g>',
    "reports": f'<g {_S}><path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/></g>',
    "trash": f'<g {_S}><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 12.3a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4L17.5 7M10 11v6M14 11v6"/></g>',
    "settings": f'<g {_S}><circle cx="12" cy="12" r="3"/><path d="M19.4 14.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></g>',
    "search": f'<g {_S}><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4-4"/></g>',
    "plus": f'<g {_S}><path d="M12 5v14M5 12h14"/></g>',
    "tick": '<g fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5.5 12.5 4.2 4.2L18.5 7.5"/></g>',
    "check": f'<g {_S}><path d="m5 12.5 4.5 4.5L19 7.5"/></g>',
    "close": f'<g {_S}><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></g>',
    "lock": f'<g {_S}><rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/></g>',
    "logout": f'<g {_S}><path d="M9.5 4H7a2.5 2.5 0 0 0-2.5 2.5v11A2.5 2.5 0 0 0 7 20h2.5"/><path d="m15 8 4 4-4 4M19 12H9.5"/></g>',
    "sun": f'<g {_S}><circle cx="12" cy="12" r="3.8"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/></g>',
    "moon": f'<g {_S}><path d="M20 14.2A8 8 0 1 1 9.8 4 6.5 6.5 0 0 0 20 14.2z"/></g>',
    "chevron": f'<g {_S}><path d="m6.5 9.5 5.5 5.5 5.5-5.5"/></g>',
    "pin": f'<g {_S}><path d="M9 4h6l-1 6 3 3H7l3-3-1-6zM12 13v7"/></g>',
    "trend": f'<g {_S}><path d="m3.5 16 5.5-5.5 3.5 3.5 7-7.5M15 6.5h5.5V12"/></g>',
    "home": f'<g {_S}><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/></g>',
    "play": '<path fill="currentColor" d="M8.5 5.2v13.6a.8.8 0 0 0 1.2.7l11-6.8a.8.8 0 0 0 0-1.4l-11-6.8a.8.8 0 0 0-1.2.7z"/>',
    "pause": '<g fill="currentColor"><rect x="6.5" y="5" width="4" height="14" rx="1.3"/><rect x="13.5" y="5" width="4" height="14" rx="1.3"/></g>',
    "reset": f'<g {_S}><path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 4v4.5h4.5"/></g>',
    "skip": f'<g {_S}><path d="M6 5.5v13l9-6.5z"/><path d="M18.5 5.5v13"/></g>',
    "inbox": f'<g {_S}><path d="M4 13.5 6.5 5h11l2.5 8.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18z"/><path d="M4 13.5h4.5l1 2h5l1-2H20"/></g>',
    "dots": '<g fill="currentColor"><circle cx="12" cy="5.5" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="12" cy="18.5" r="1.7"/></g>',
    "edit": f'<g {_S}><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/></g>',
    "chevron_up": f'<g {_S}><path d="m6.5 14.5 5.5-5.5 5.5 5.5"/></g>',
    "trophy": f'<g {_S}><path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5v1.5A3 3 0 0 0 8 10.5M16 6h3v1.5a3 3 0 0 1-3 3M12 13v4M8.5 20h7M10 17h4"/></g>',
    "flag": f'<g {_S}><path d="M5.5 21V4M5.5 4.5h11l-2 4 2 4h-11"/></g>',
    "sparkle": f'<g {_S}><path d="M12 3.5 13.9 9l5.6 1.9-5.6 1.9L12 18.5l-1.9-5.7L4.5 10.9 10.1 9z"/><path d="M19 3v3M20.5 4.5h-3"/></g>',
    "bold": f'<g {_S}><path d="M7 4.5h6a3.6 3.6 0 0 1 0 7.2H7zM7 11.7h7.2a3.9 3.9 0 0 1 0 7.8H7z"/></g>',
    "italic": f'<g {_S}><path d="M10 4.5h8M6 19.5h8M14.5 4.5 9.5 19.5"/></g>',
    "underline": f'<g {_S}><path d="M7 4.5v7a5 5 0 0 0 10 0v-7M5 20h14"/></g>',
    "highlight": f'<g {_S}><path d="m14.5 4.5 5 5-8 8H6.5v-5z"/><path d="m12 7 5 5"/><path d="M4 21h9"/></g>',
    "heading": f'<g {_S}><path d="M6 4.5v15M18 4.5v15M6 12h12"/></g>',
    "checklist": f'<g {_S}><path d="m3.8 6.6 1.6 1.6 2.9-3.2M3.8 14.6l1.6 1.6 2.9-3.2M11.5 7h9M11.5 15h9M11.5 19.5h5"/></g>',
    "save": f'<g {_S}><path d="M5.5 4h10.4L20 8.1V18.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13A1.5 1.5 0 0 1 5.5 4z"/><path d="M8 4v4.5h6.5V4M7.5 20v-6h9v6"/></g>',
    "alert": f'<g {_S}><path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17v.1"/></g>',
    "bookmark": f'<g {_S}><path d="M7 3.5h10a1 1 0 0 1 1 1V20l-6-4-6 4V4.5a1 1 0 0 1 1-1z"/></g>',
    "export": f'<g {_S}><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4.5 14v4.5A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5V14"/></g>',
    "link": f'<g {_S}><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></g>',
    "print": f'<g {_S}><path d="M7 9V4h10v5"/><path d="M7 17H5V9h14v8h-2"/><path d="M7 14h10v6H7z"/></g>',
}


# --------------------------------------------------------------------------------------- the Aegis cut ---
def _box(x: float, y: float, w: float, h: float, c: float = 2.3, big: float = 4.4) -> str:
    """A rectangle with cut (chamfered) corners instead of rounded ones. The top-right corner is cut deeper than the
    others: that single, larger cut is the family's signature notch - the same nick the shield carries."""
    r, b = x + w, y + h
    return (f"M{x + c:g} {y:g}H{r - big:g}L{r:g} {y + big:g}V{b - c:g}L{r - c:g} {b:g}H{x + c:g}"
            f"L{x:g} {b - c:g}V{y + c:g}z")


def _cut_icons() -> dict[str, str]:
    S = _S.replace('stroke-linejoin="round"', 'stroke-linejoin="miter" stroke-miterlimit="3"')     # crisp cuts, not soft corners
    return {
        "today": f'<g {S}><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v7.7l1.8 1.8h9.4l1.8-1.8V10"/><path d="M10 19.5v-5h4v5"/></g>',
        "home": f'<g {S}><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v7.7l1.8 1.8h9.4l1.8-1.8V10"/></g>',
        "calendar": f'<g {S}><path d="{_box(3.5, 5, 17, 15.5, 2.4, 4.6)}"/><path d="M8 3v4M16 3v4M3.5 10h17"/>'
                    f'<circle cx="8.5" cy="14.5" r=".6"/><circle cx="12" cy="14.5" r=".6"/><circle cx="15.5" cy="14.5" r=".6"/></g>',
        "kanban": f'<g {S}><path d="{_box(3.5, 4, 5, 16, 1.6, 2.6)}"/><path d="{_box(10, 4, 5, 10, 1.6, 2.6)}"/>'
                  f'<path d="{_box(16.5, 4, 4, 13, 1.6, 2.6)}"/></g>',
        "notes": f'<g {S}><path d="M5.5 3.5h9l4.5 4.5v11l-1.5 1.5h-12L4 19V5z"/><path d="M14.5 3.5V8H19M8 12.5h8M8 16h5"/></g>',
        "trash": f'<g {S}><path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 11.6 1.7 1.9h5.6l1.7-1.9 1-11.6M10 11v6M14 11v6"/></g>',
        "lock": f'<g {S}><path d="{_box(5, 10.5, 14, 10, 2.6, 4.4)}"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/></g>',
        "logout": f'<g {S}><path d="M9.5 4H7L4.5 6.5v11L7 20h2.5"/><path d="m15 8 4 4-4 4M19 12H9.5"/></g>',
        "backup": f'<g {S}><path d="M12 3v11M7.5 9.5 12 14l4.5-4.5"/><path d="M4 15v3l2 2h12l2-2v-3"/></g>',
        "export": f'<g {S}><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M4.5 14v3.5L7 20h10l2.5-2.5V14"/></g>',
        "inbox": f'<g {S}><path d="M4 13.5 6.5 5h11l2.5 8.5V18l-2 1.5H6L4 18z"/><path d="M4 13.5h4.5l1 2h5l1-2H20"/></g>',
        "save": f'<g {S}><path d="M5.5 4h10.4L20 8.1V18l-2 2H6l-2-2V6z"/><path d="M8 4v4.5h6.5V4M7.5 20v-6h9v6"/></g>',
        "alert": f'<g {S}><path d="M12 4 20.7 18.7 19.5 20.5H4.5L3.3 18.7z"/><path d="M12 10v4.5M12 17v.1"/></g>',
        "trophy": f'<g {S}><path d="M8 4h8v5l-1.6 2.6H9.6L8 9z"/><path d="M8 6H5v1.5A3 3 0 0 0 8 10.5M16 6h3v1.5a3 3 0 0 1-3 3M12 13v4M8.5 20h7M10 17h4"/></g>',
        "bookmark": f'<g {S}><path d="M7 3.5h8.4L18 6.1V20l-6-4-6 4V4.5a1 1 0 0 1 1-1z"/></g>',
        "pin": f'<g {S}><path d="M9 4h6l-.8 5.4L17 13H7l2.8-3.6zM12 13v7"/></g>',
        "goals": f'<g {S}><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="m12 10.6 1.4 1.4-1.4 1.4-1.4-1.4z"/></g>',
        "focus": f'<g {S}><circle cx="12" cy="13.5" r="7.5"/><path d="M12 9.5v4l2.5 1.5M9.5 3h5M17.6 6.2l1.3-1.3"/></g>',
        "reports": f'<g {S}><path d="M5 20v-9.5L6.5 9H8l1.5 1.5V20M11.5 20V4.5L13 3h1.5L16 4.5V20M18 20v-6.5l1-1h1l1 1V20M3 20h18"/></g>',
        "info": f'<g {S}><path d="M12 3.5 18.5 6l2 6.5L18 18.5 12 20.5 6 18.5 3.5 12.5 5.5 6z"/><path d="M12 11v5M12 7.8v.1"/></g>',
        "database": f'<g {S}><ellipse cx="12" cy="6" rx="7.5" ry="2.8"/><path d="M4.5 6v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6"/></g>',
        "bell": f'<g {S}><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2H4.5z"/><path d="M10 21h4"/><path d="m17.6 3.4 1.8 1.8"/></g>',
        "search": f'<g {S}><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></g>',
    }


ICONS.update(_cut_icons())

ICONS.update({
    "pen": f'<g {_S}><path d="M4 20l1-4.2L16.6 4.2a2.1 2.1 0 0 1 3 3L8 19z"/><path d="m14.6 6.2 3 3"/></g>',
    "marker": f'<g {_S}><path d="M8.2 15.8 15 9l3.2 3.2-6.8 6.8H7.6z"/><path d="m15 9 1.8-1.8a1.5 1.5 0 0 1 2.1 0l.9.9a1.5 1.5 0 0 1 0 2.1L18.2 12"/><path d="M4.5 20h4"/></g>',
    "eraser": f'<g {_S}><path d="M13 5.5 19 11.5 11.5 19H8L4.5 15.5z"/><path d="M8.5 10 15 16.5M12 19h8"/></g>',
    "undo": f'<g {_S}><path d="M9 6.5 4.5 11 9 15.5"/><path d="M5 11h8.5a5 5 0 0 1 0 10H9"/></g>',
    "redo": f'<g {_S}><path d="M15 6.5 19.5 11 15 15.5"/><path d="M19 11h-8.5a5 5 0 0 0 0 10H15"/></g>',
    "flow": f'<g {_S}><rect x="9" y="3.5" width="6" height="4.5" rx="1.3"/><rect x="3.5" y="16" width="6" height="4.5" rx="1.3"/><rect x="14.5" y="16" width="6" height="4.5" rx="1.3"/><path d="M12 8v4M12 12H6.5v4M12 12h5.5v4"/></g>',
    "arrow_right": f'<g {_S}><path d="M5 12h14M13 6l6 6-6 6"/></g>',
    "grid": f'<g {_S}><rect x="4" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.6"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.6"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.6"/></g>',
    "rows": f'<g {_S}><rect x="4" y="5" width="16" height="4.4" rx="1.4"/><rect x="4" y="14.6" width="16" height="4.4" rx="1.4"/></g>',
    "text": f'<g {_S}><path d="M5.5 6.5h13M12 6.5V19M9 19h6"/></g>',
    "tidy": f'<g {_S}><path d="M4 6h16M7 12h10M10 18h4"/></g>',
    "n_proc": f'<g {_S}><rect x="3.5" y="7" width="17" height="10" rx="2.4"/></g>',
    "n_dec": f'<g {_S}><path d="M12 3.5 21 12l-9 8.5L3 12z"/></g>',
    "n_start": f'<g {_S}><rect x="3" y="8" width="18" height="8" rx="4"/></g>',
    "n_io": f'<g {_S}><path d="M7 7h13l-3 10H4z"/></g>',
    "ink_bg": f'<g {_S}><circle cx="7" cy="7" r=".6"/><circle cx="12" cy="7" r=".6"/><circle cx="17" cy="7" r=".6"/><circle cx="7" cy="12" r=".6"/><circle cx="12" cy="12" r=".6"/><circle cx="17" cy="12" r=".6"/><circle cx="7" cy="17" r=".6"/><circle cx="12" cy="17" r=".6"/><circle cx="17" cy="17" r=".6"/></g>',
    "image": f'<g {_S}><rect x="3.5" y="5" width="17" height="14" rx="2.4"/><circle cx="9" cy="10" r="1.6"/><path d="m4 17 5-4.5 3.5 3L16 12l4 4.5"/></g>',
    "up": f'<g {_S}><path d="m6 14.5 6-6 6 6"/></g>',
    "down": f'<g {_S}><path d="m6 9.5 6 6 6-6"/></g>',
})


@lru_cache(maxsize=256)
def pixmap(name: str, color: str = "#888888", size: int = 20) -> QPixmap:
    body = ICONS[name].replace("currentColor", color)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    dpr = 2.0
    try:
        dpr = max(1.0, QGuiApplication.primaryScreen().devicePixelRatio())
    except Exception:  # noqa: BLE001
        pass
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#888888", size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))
