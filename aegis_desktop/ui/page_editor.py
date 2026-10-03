# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared plumbing for editors that open as a full page inside the main window (task, goal, habit).

A page editor is an ordinary ``SheetDialog`` that was turned into a child widget: ``embedded=True`` removes the window chrome,
``frame()`` builds the common page (back button, caption, a centred scrolling column, footer with Save / Cancel) and the
mixin supplies the unsaved-changes bookkeeping. ``main_window.open_page_editor`` shows it and reports the result."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from . import icons
from .theme import PALETTES
from .tokens import PAGE
from .widgets import button, label


class PageEditorMixin:
    """Put before ``SheetDialog`` in the bases. The subclass provides ``_data()`` (what the form holds right now)."""

    embedded = False
    _discard = False
    _initial: dict | None = None
    UNSAVED_TEXT = "تغییرات ذخیره نشده‌اند. دور ریخته شوند؟"

    def _page_begin(self, embedded: bool) -> None:
        self.embedded, self._discard = embedded, False
        if embedded:
            self.SCRIM = self.MORPH = False                      # a page, not a modal: no veil and no grow-from-click
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setStyleSheet("")
            self._close.hide()
            self._sheet_done = True

    # ---- the page itself
    def frame(self, caption: str, max_width: int = 920):
        """Build back bar + scroll area + footer. Returns the column layout the caller fills with cards."""
        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE)
        root.setSpacing(12)
        top = QHBoxLayout()
        back = button("بازگشت", "Link", self.reject)
        theme = getattr(self.parent().window(), "theme", "dark") if self.parent() else "dark"
        pal = PALETTES.get(theme) or next(iter(PALETTES.values()))
        back.setIcon(icons.icon("arrow_right", pal["muted"], 16))
        back.setToolTip("بازگشت  Esc")
        top.addWidget(back)
        top.addStretch(1)
        top.addWidget(label(caption, "Muted"))
        root.addLayout(top)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
        host = QWidget()
        host.setObjectName("DlgBody")
        host.setStyleSheet("QWidget#DlgBody { background: transparent; }")
        outer = QHBoxLayout(host)
        outer.setContentsMargins(0, 0, 8, 0)
        outer.addStretch(1)
        col = QWidget()
        col.setObjectName("DlgBody")
        col.setMaximumWidth(max_width)
        col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(14)
        sc.setWidget(host)
        root.addWidget(sc, 1)
        self._page_root = root
        return cl

    def footer(self, err) -> None:
        """Error line, hint and Save / Cancel; Ctrl+Enter saves."""
        root = self._page_root
        root.addWidget(err)
        foot = QHBoxLayout()
        foot.addWidget(label("Ctrl+Enter برای ذخیره  ·  Esc برای بازگشت", "Muted"))
        foot.addStretch(1)
        foot.addWidget(button("ذخیره", "Primary", self.accept))
        foot.addWidget(button("انصراف", slot=self.reject))
        root.addLayout(foot)
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), self, activated=self.accept)
        self._initial = self.snapshot()

    # ---- unsaved work
    def snapshot(self) -> dict:
        """What the form holds right now; never touches the edited item."""
        return self._data()

    def is_dirty(self) -> bool:
        return self.embedded and self.snapshot() != self._initial

    def reject(self) -> None:
        """Esc, the back button or leaving the page: ask before typed work is thrown away."""
        if self.embedded and not self._discard and self.is_dirty():
            from .dialogs import ask
            if not ask(self, "ذخیره نشده", self.UNSAVED_TEXT, True, "دور بریز"):
                return
        super().reject()

    def paintEvent(self, e) -> None:  # noqa: N802
        if not self.embedded:
            super().paintEvent(e)                                 # the floating sheet paints its own card; the page has none
