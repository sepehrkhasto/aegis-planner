# SPDX-License-Identifier: GPL-3.0-or-later
"""Empty states that tell you what to do next: illustration, one line of explanation and ONE clear action button.

``EmptyOverlay`` is a real widget laid over a view's viewport (so the button is a real, focusable button). The page
calls ``show_for(empty, title, sub, btn, slot)`` after every refresh; it hides itself as soon as there is content.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from .premium import EmptyArt
from .widgets import button, label


class EmptyOverlay(QWidget):
    def __init__(self, host: QWidget, icon: str):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._slot = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 12, 24, 12)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.art = EmptyArt(icon)
        lay.addWidget(self.art, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label("", "H2")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        self.sub = label("", "Muted", True)
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.sub)
        self.btn: QPushButton = button("", "Primary", self._fire)
        self.btn.setProperty("cta", True)
        lay.addSpacing(4)
        lay.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)
        self._track = _Resize(self)
        host.installEventFilter(self._track)
        self.hide()

    def _fire(self) -> None:
        if self._slot:
            self._slot()

    def fit(self) -> None:
        self.setGeometry(self.host.rect())
        self.art.setVisible(self.height() >= 330)                 # a short view has no room for the illustration

    def show_for(self, empty: bool, title: str = "", sub: str = "", btn: str = "", slot=None) -> None:
        """Show (with this text/action) when ``empty``; hide otherwise."""
        if not empty:
            self.hide()
            self._accent()
            return
        self.title.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.btn.setText(btn)
        self.btn.setVisible(bool(btn))
        self._slot = slot
        self.fit()
        self.show()
        self.raise_()
        self._accent()

    def _accent(self) -> None:
        from .widgets import one_accent
        w = self.parentWidget()
        while w is not None and not hasattr(w, "ctx"):
            w = w.parentWidget()
        if w is not None:
            one_accent(w)


class _Resize(QObject):
    def __init__(self, ov: EmptyOverlay):
        super().__init__(ov)
        self.ov = ov

    def eventFilter(self, o, e) -> bool:  # noqa: N802
        if e.type() == QEvent.Type.Resize:
            self.ov.fit()
        return False
