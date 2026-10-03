# SPDX-License-Identifier: GPL-3.0-or-later
"""The editor sheet: how the task / goal / habit editors are presented.

A frameless, softly shadowed card that floats over the dimmed window (no operating-system title bar), with a close button, a
large borderless title field and a sticky footer. It is still a ``QDialog`` (modal, ``exec()``, Esc to cancel, Ctrl+Enter to save),
so everything that opens an editor keeps working; only the way it is dressed changes."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import QAbstractButton, QLineEdit

from .fx_widgets import _fpal
from .micro import MotionDialog
from .theme import rr
from .tokens import TYPE

SHADOW = 22                       # transparent margin around the card that holds its shadow


class _Close(QAbstractButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip("بستن  (Esc)")
        self.setAccessibleName("بستن")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hot = self.underMouse() or self.hasFocus()
        if hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["panel2"]))
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(pal["text"] if hot else pal["muted"]), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = QRectF(self.rect()).center()
        d = 5.0
        p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))


class SheetDialog(MotionDialog):
    """Base of the editor dialogs. Build the layout as usual, then call ``finish_sheet(width)`` at the end of ``__init__``."""

    SHEET_RADIUS = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("QDialog { background: transparent; } QDialog > QWidget { background: transparent; }")
        self._close = _Close(self)
        self._close.clicked.connect(self.reject)
        self._sheet_done = False

    def finish_sheet(self, width: int) -> None:
        lay = self.layout()
        if lay is not None and not self._sheet_done:
            m = lay.contentsMargins()
            lay.setContentsMargins(m.left() + SHADOW, m.top() + SHADOW + 4, m.right() + SHADOW, m.bottom() + SHADOW)
        self._sheet_done = True
        self.setMinimumWidth(width + 2 * SHADOW)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.accept)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.accept)
        self._place_close()

    def style_title(self, edit: QLineEdit) -> None:
        """The title field of an editor: large, borderless, with one hairline that turns to the accent colour on focus."""
        edit.setObjectName("SheetTitle")
        edit.setFrame(False)                 # no halo overlay (micro._FocusRing skips frameless fields): the hairline is the focus cue
        f = QFont(edit.font())
        f.setPointSizeF(TYPE["h3"] + 1.5)
        f.setWeight(QFont.Weight.DemiBold)
        edit.setFont(f)
        edit.setMinimumHeight(46)

    def _place_close(self) -> None:
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = SHADOW + 16 if rtl else self.width() - SHADOW - 16 - self._close.width()
        self._close.move(x, SHADOW + 16)
        self._close.raise_()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if not getattr(self, "embedded", False):
            self._place_close()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if getattr(self, "embedded", False):                    # the page editor is an ordinary child of the window
            return
        pal = _fpal(self)
        self.setStyleSheet(
            "QDialog { background: transparent; } QDialog > QWidget { background: transparent; }"
            f"QLineEdit#SheetTitle {{ background: transparent; border: none; border-bottom: 1px solid {pal['line']};"
            " border-radius: 0; padding: 4px 2px; }"
            f"QLineEdit#SheetTitle:focus {{ border-bottom: 1px solid {pal['accent2']}; }}")
        self._place_close()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        """Drag the sheet by any empty spot (there is no title bar to grab)."""
        if getattr(self, "embedded", False):
            return super().mousePressEvent(e)
        from PyQt6.QtWidgets import QLabel
        under = self.childAt(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and (under is None or isinstance(under, QLabel) or under.objectName() in ("Hair",)):
            h = self.windowHandle()
            if h is not None:
                try:
                    h.startSystemMove()
                except Exception:  # noqa: BLE001
                    pass
        super().mousePressEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        return super().sizeHint()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        rad = max(10.0, rr(self.SHEET_RADIUS))
        dark = QColor(pal["bg"]).lightness() < 128
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(9, 0, -1):                                    # a soft shadow: stacked, widening, fainter rounded rects
            grow = i * 2.2
            a = (9 if dark else 6) * (10 - i) / 9.0
            p.setBrush(QColor(0, 0, 0, int(a * 2.2)))
            p.drawRoundedRect(card.adjusted(-grow, -grow + 6, grow, grow + 6), rad + grow, rad + grow)
        p.setBrush(QColor(pal["panel"]))
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        top = QColor(pal["accent2"])                                  # the brand's engraved notch along the top edge, start side
        top.setAlpha(150)
        p.setPen(QPen(top, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x0 = card.right() - rad - 6 if rtl else card.left() + rad + 6
        x1 = x0 - 56 if rtl else x0 + 56
        p.drawLine(QPointF(x0, card.top() + 0.8), QPointF(x1, card.top() + 0.8))
