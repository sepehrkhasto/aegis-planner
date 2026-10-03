# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility safety net: every button-like control gets a spoken name (its text, else its tooltip, else its role)."""
from __future__ import annotations

from PyQt6.QtWidgets import QAbstractButton, QWidget

_ROLE = {"EyeToggle": "نمایش یا پنهان کردن رمز", "PinButton": "سنجاق", "BellToggle": "یادآوری", "Switch": "کلید"}


def ensure_names(root: QWidget) -> int:
    """Name every unnamed button under ``root``. Returns how many were named."""
    n = 0
    for b in root.findChildren(QAbstractButton):
        if b.accessibleName() or b.text().strip() or b.objectName().startswith("qt_"):
            continue
        b.setAccessibleName(b.toolTip().strip() or _ROLE.get(type(b).__name__, "دکمه"))
        n += 1
    return n
