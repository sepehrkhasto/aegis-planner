# SPDX-License-Identifier: GPL-3.0-or-later
"""Time of day as a pill with a small picker: ``TimeField`` shows «۰۹:۳۰» and opens ``TimeGrid`` (hours, then minutes).
It speaks the part of the QTimeEdit API the forms use (``time``, ``setTime``, ``timeChanged``)."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, QTime, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ..core import jalali
from . import icons
from .theme import PALETTES
from .theme import rr as _rad

CW, CH, PAD, HEAD = 44, 34, 10, 26


def _pal(w: QWidget) -> dict:
    return PALETTES.get(getattr(w.window(), "theme", "dark")) or next(iter(PALETTES.values()))


class TimeGrid(QWidget):
    """24 hours in a 6x4 grid, then the minutes in steps of five (6x2). Picking a minute finishes."""

    picked = pyqtSignal(QTime)
    changed = pyqtSignal(QTime)

    def __init__(self, value: QTime, parent=None):
        super().__init__(parent)
        self.h, self.m = value.hour(), value.minute()
        self.hover: tuple[str, int] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(PAD * 2 + CW * 6, PAD + HEAD + CH * 4 + 8 + HEAD + CH * 2 + PAD)

    def set_time(self, t: QTime) -> None:
        self.h, self.m = t.hour(), t.minute()
        self.update()

    def _cells(self) -> list[tuple[QRectF, tuple[str, int]]]:
        rtl = self.isRightToLeft()
        out = []

        def x(col: int) -> float:
            return self.width() - PAD - (col + 1) * CW if rtl else PAD + col * CW

        top = PAD + HEAD
        for i in range(24):
            r, c = divmod(i, 6)
            out.append((QRectF(x(c) + 2, top + r * CH + 2, CW - 4, CH - 4), ("h", i)))
        top2 = top + CH * 4 + 8 + HEAD
        for i in range(12):
            r, c = divmod(i, 6)
            out.append((QRectF(x(c) + 2, top2 + r * CH + 2, CW - 4, CH - 4), ("m", i * 5)))
        return out

    def _at(self, pos):
        for r, k in self._cells():
            if r.contains(pos):
                return k
        return None

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        k = self._at(e.position())
        if k != self.hover:
            self.hover = k
            self.setCursor(Qt.CursorShape.PointingHandCursor if k else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        k = self._at(e.position())
        if k is None:
            return
        if k[0] == "h":
            self.h = k[1]
            self.changed.emit(QTime(self.h, self.m))
            self.update()
        else:
            self.m = k[1]
            self.changed.emit(QTime(self.h, self.m))
            self.picked.emit(QTime(self.h, self.m))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k == Qt.Key.Key_Up:
            self.h = (self.h - 1) % 24
        elif k == Qt.Key.Key_Down:
            self.h = (self.h + 1) % 24
        elif k == Qt.Key.Key_Left:
            self.m = (self.m + (5 if self.isRightToLeft() else -5)) % 60
        elif k == Qt.Key.Key_Right:
            self.m = (self.m + (-5 if self.isRightToLeft() else 5)) % 60
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.picked.emit(QTime(self.h, self.m))
            return
        else:
            super().keyPressEvent(e)
            return
        self.changed.emit(QTime(self.h, self.m))
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _pal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        p.setFont(f)
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(PAD, PAD, self.width() - 2 * PAD, HEAD), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading), "ساعت")
        p.drawText(QRectF(PAD, PAD + HEAD + CH * 4 + 8, self.width() - 2 * PAD, HEAD),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading), "دقیقه")
        bold = QFont(f)
        bold.setBold(True)
        for r, (kind, v) in self._cells():
            sel = (kind == "h" and v == self.h) or (kind == "m" and v == self.m)
            if sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent"]))
                p.drawRoundedRect(r, _rad(9), _rad(9))
                p.setPen(QColor(pal["ink"]))
                p.setFont(bold)
            else:
                if self.hover == (kind, v):
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(pal["soft"]))
                    p.drawRoundedRect(r, _rad(9), _rad(9))
                p.setPen(QColor(pal["text"]))
                p.setFont(f)
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), jalali.fa(f"{v:02d}"))
        p.end()


class TimeField(QAbstractButton):
    """«۰۹:۳۰» pill. Click opens the grid; the wheel and ↑/↓ nudge the time (five minutes / an hour with Shift)."""

    timeChanged = pyqtSignal(QTime)

    def __init__(self, t: QTime | None = None, parent=None):
        super().__init__(parent)
        self._t = t or QTime(0, 0)
        self.pop = None
        self.grid: TimeGrid | None = None
        self.setFixedHeight(38)
        self.setMinimumWidth(110)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.open_popover)
        self._sync_name()

    # QTimeEdit-compatible surface
    def time(self) -> QTime:
        return self._t

    def setTime(self, t: QTime) -> None:  # noqa: N802
        if t != self._t:
            self._t = t
            self._sync_name()
            self.update()
            self.timeChanged.emit(t)

    def setDisplayFormat(self, _fmt: str) -> None:  # noqa: N802
        """Kept for callers written against QTimeEdit; the field always shows HH:mm."""

    def text_now(self) -> str:
        return jalali.fa(self._t.toString("HH:mm"))

    def _sync_name(self) -> None:
        self.setAccessibleName("ساعت " + self.text_now())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(max(110, self.fontMetrics().horizontalAdvance(self.text_now()) + 64), 38)

    def nudge(self, minutes: int) -> None:
        total = (self._t.hour() * 60 + self._t.minute() + minutes) % (24 * 60)
        self.setTime(QTime(total // 60, total % 60))

    def wheelEvent(self, e) -> None:  # noqa: N802
        if self.isEnabled():
            step = 60 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 5
            self.nudge(step if e.angleDelta().y() > 0 else -step)
            e.accept()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        step = 60 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 5
        if e.key() == Qt.Key.Key_Up:
            self.nudge(step)
        elif e.key() == Qt.Key.Key_Down:
            self.nudge(-step)
        else:
            super().keyPressEvent(e)

    def open_popover(self) -> None:
        from .notes_page import Popover
        if self.grid is None:
            self.grid = TimeGrid(self._t)
            self.grid.changed.connect(self.setTime)
            self.grid.picked.connect(lambda t: (self.setTime(t), self.pop.hide()))
            self.pop = Popover(self.grid, self)
        self.grid.set_time(self._t)
        self.pop.show_under(self)
        self.grid.setFocus()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _pal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isEnabled()
        hot = on and (self.underMouse() or self.hasFocus() or (self.pop is not None and self.pop.isVisible()))
        p.setBrush(QColor(pal["panel2"]) if hot else QColor(pal["panel"]))
        p.setPen(QPen(QColor(pal["accent"] if self.hasFocus() else pal["line"]), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        rtl = self.isRightToLeft()
        gx = r.right() - 28 if rtl else r.left() + 12
        p.drawPixmap(int(gx), int(r.center().y() - 8), icons.pixmap("focus", pal["acc_text"] if on else pal["muted"], 16))
        p.setPen(QColor(pal["text"] if on else pal["muted"]))
        tr = QRectF(r.left() + 12, r.top(), r.width() - 44, r.height()) if rtl else QRectF(r.left() + 34, r.top(), r.width() - 46, r.height())
        p.drawText(tr, int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)), self.text_now())
        p.end()

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(e)

    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        self.update()
