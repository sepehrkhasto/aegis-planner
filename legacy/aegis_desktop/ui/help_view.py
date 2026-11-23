# SPDX-License-Identifier: GPL-3.0-or-later
"""The Help section of Settings: searchable FAQ (accordion), feature cards and the privacy policy."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget)

from . import icons
from .help_content import FAQ, FEATURES, PRIVACY
from .system import ChoiceTabs
from .theme import PALETTES
from .widgets import label


def _norm(s: str) -> str:
    """Search folding: Arabic/Persian letter variants, ZWNJ and digits compare equal."""
    s = s.replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("‑", "-").lower()
    for i, d in enumerate("۰۱۲۳۴۵۶۷۸۹"):
        s = s.replace(d, str(i))
    for i, d in enumerate("٠١٢٣٤٥٦٧٨٩"):
        s = s.replace(d, str(i))
    return s


def _theme(w: QWidget) -> str:
    return getattr(w.window(), "theme", "dark")


def _pal(w: QWidget) -> dict:
    return PALETTES.get(_theme(w)) or next(iter(PALETTES.values()))


class FaqItem(QFrame):
    """One question: the whole header is the button; the answer opens under it."""

    def __init__(self, q: str, a: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.q, self.a = q, a
        self.key = _norm(q + " " + a)
        self.open = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.title = label(q, "RowTitle", True)
        head.addWidget(self.title, 1)
        self.chev = QLabel()
        self.chev.setFixedSize(18, 18)
        head.addWidget(self.chev, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)
        self.body = label(a, "Muted", True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.hide()
        lay.addWidget(self.body)
        self.setAccessibleName(q)
        self._sync()

    def _sync(self) -> None:
        pal = _pal(self)
        self.chev.setPixmap(icons.pixmap("chevron_up" if self.open else "chevron", pal["muted"], 16))
        self.title.setStyleSheet("" if not self.open else f"color: {pal['acc_text']};")

    def set_open(self, on: bool) -> None:
        self.open = on
        self.body.setVisible(on)
        self._sync()
        self.updateGeometry()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.set_open(not self.open)
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.set_open(not self.open)
            return
        super().keyPressEvent(e)

    def changeEvent(self, e) -> None:  # noqa: N802
        if e.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self._sync()
        super().changeEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._sync()                                          # built before it had a window: the theme is known only now


class _FaqTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجو در پرسش‌ها…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(38)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.items: list[FaqItem] = []
        self.heads: dict[str, QLabel] = {}
        cat = None
        for c, q, a in FAQ:
            if c != cat:
                cat = c
                h = label(c, "Muted")
                h.setContentsMargins(4, 10, 4, 0)
                self.heads[c] = h
                lay.addWidget(h)
            it = FaqItem(q, a)
            it.cat = c                                       # type: ignore[attr-defined]
            self.items.append(it)
            lay.addWidget(it)
        self.empty = label("پرسشی پیدا نشد. عبارت دیگری را امتحان کن.", "Muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setContentsMargins(0, 24, 0, 24)
        self.empty.hide()
        lay.addWidget(self.empty)
        lay.addStretch(1)

    def _filter(self, text: str) -> None:
        words = _norm(text).split()
        shown: set[str] = set()
        n = 0
        for it in self.items:
            ok = all(w in it.key for w in words)
            it.setVisible(ok)
            if ok:
                n += 1
                shown.add(it.cat)                           # type: ignore[attr-defined]
                if words:
                    it.set_open(True)
        if not words:
            for it in self.items:
                it.set_open(False)
        for c, h in self.heads.items():
            h.setVisible(c in shown)
        self.empty.setVisible(n == 0)


class _FeatureCard(QFrame):
    def __init__(self, title: str, desc: str, icon: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._icon = icon
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        self.ic = QLabel()
        self.ic.setFixedSize(36, 36)
        self.ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.ic, 0, Qt.AlignmentFlag.AlignTop)
        tl = QVBoxLayout()
        tl.setSpacing(3)
        tl.addWidget(label(title, "RowTitle"))
        tl.addWidget(label(desc, "Muted", True))
        lay.addLayout(tl, 1)
        self.paint_icon()

    def paint_icon(self) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QColor, QPixmap
        pal = _pal(self)
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(int(36 * dpr), int(36 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["soft"]))
        p.drawRoundedRect(QRectF(0, 0, 36, 36), 11, 11)
        p.drawPixmap(8, 8, icons.pixmap(self._icon, pal["acc_text"], 20))
        p.end()
        self.ic.setPixmap(pm)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.paint_icon()


class _FeaturesTab(QWidget):
    COLS = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10)
        self.cards = [_FeatureCard(t, d, i) for t, d, i in FEATURES]
        for n, c in enumerate(self.cards):
            g.addWidget(c, n // self.COLS, n % self.COLS)
        g.setRowStretch(len(self.cards) // self.COLS + 1, 1)


class _PrivacyTab(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(6)
        lay.addWidget(label("سیاست حریم خصوصی", "H2"))
        for n, (h, b) in enumerate(PRIVACY):
            if n:
                line = QFrame()
                line.setObjectName("Hair")
                line.setFixedHeight(1)
                lay.addSpacing(12)
                lay.addWidget(line)
                lay.addSpacing(12)
            else:
                lay.addSpacing(8)
            lay.addWidget(label(h, "RowTitle"))
            body = label(b, "Muted", True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeading)
            lay.addWidget(body)


class HelpView(QWidget):
    """Three tabs under one pill switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.tabs = ChoiceTabs()
        for t, k in (("سوالات متداول", "faq"), ("امکانات", "features"), ("حریم خصوصی", "privacy")):
            self.tabs.addItem(t, k)
        row = QHBoxLayout()
        row.addWidget(self.tabs)
        row.addStretch(1)
        lay.addLayout(row)
        self.faq, self.features, self.privacy = _FaqTab(), _FeaturesTab(), _PrivacyTab()
        self.pages = (self.faq, self.features, self.privacy)
        for w in self.pages:                                 # not a QStackedWidget: that is as tall as its tallest page
            lay.addWidget(w)
        lay.addStretch(1)
        self.tabs.currentIndexChanged.connect(self._tab)
        self._tab(0)

    def _tab(self, i: int) -> None:
        for k, w in enumerate(self.pages):
            w.setVisible(k == i)
