# SPDX-License-Identifier: GPL-3.0-or-later
"""A small Jalali calendar in a popover instead of three drop-downs: ``MiniCalendar`` (the month grid) and ``DateButton``
(the pill that shows the chosen day and opens it)."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ..core import jalali
from . import icons
from .theme import PALETTES
from .theme import rr as _rad

CELL = 36
HEAD = 44
WEEK = 26
FOOT = 40
PAD = 10


def _theme(w: QWidget) -> str:
    return getattr(w.window(), "theme", "dark")


def _pal(w: QWidget) -> dict:
    return PALETTES.get(_theme(w)) or next(iter(PALETTES.values()))


class MiniCalendar(QWidget):
    """One month at a time, Saturday first (right-hand column in RTL), Fridays red. Click or Enter picks a day."""

    picked = pyqtSignal(dict)

    def __init__(self, value: dict | None = None, parent=None):
        super().__init__(parent)
        today = jalali.today_jalali()
        v = value or today
        self.sel = dict(value) if value else None
        self.cur = int(v["jy"]), int(v["jm"])
        self.focus_d = int(v["jd"])
        self.hover: tuple[str, int] | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(PAD * 2 + CELL * 7, HEAD + WEEK + CELL * 6 + FOOT + PAD)
        self._hits: list[tuple[QRectF, tuple[str, int]]] = []

    # ---- model
    def set_value(self, value: dict | None) -> None:
        self.sel = dict(value) if value else None
        v = value or jalali.today_jalali()
        self.cur = int(v["jy"]), int(v["jm"])
        self.focus_d = int(v["jd"])
        self.update()

    def shift_month(self, n: int) -> None:
        y, m = self.cur
        k = y * 12 + (m - 1) + n
        self.cur = (k // 12, k % 12 + 1)
        self.focus_d = min(self.focus_d, jalali.month_length(*self.cur))
        self.update()

    def _pick(self, d: int) -> None:
        self.sel = {"jy": self.cur[0], "jm": self.cur[1], "jd": d}
        self.focus_d = d
        self.update()
        self.picked.emit(dict(self.sel))

    def _first_col(self) -> int:
        d = jalali.due_to_date({"jy": self.cur[0], "jm": self.cur[1], "jd": 1})
        return jalali.weekday_index(d) if d else 0

    # ---- geometry
    def _col_x(self, c: int) -> float:
        return self.width() - PAD - (c + 1) * CELL if self.isRightToLeft() else PAD + c * CELL

    def _layout(self) -> None:
        self._hits = []
        w = self.width()
        rtl = self.isRightToLeft()
        prev_x = w - PAD - 32 if rtl else PAD
        next_x = PAD if rtl else w - PAD - 32
        self._hits.append((QRectF(prev_x, 6, 32, 32), ("prev", 0)))
        self._hits.append((QRectF(next_x, 6, 32, 32), ("next", 0)))
        first = self._first_col()
        n = jalali.month_length(*self.cur)
        for d in range(1, n + 1):
            row, col = divmod(first + d - 1, 7)
            self._hits.append((QRectF(self._col_x(col) + 2, HEAD + WEEK + row * CELL + 2, CELL - 4, CELL - 4), ("day", d)))
        self._hits.append((QRectF(PAD, HEAD + WEEK + CELL * 6 + 4, self.width() - 2 * PAD, FOOT - 8), ("today", 0)))

    def _at(self, pos) -> tuple[str, int] | None:
        self._layout()
        for r, k in self._hits:
            if r.contains(pos):
                return k
        return None

    # ---- events
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._at(e.position())
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        k = self._at(e.position())
        if k is None:
            return
        kind, d = k
        if kind == "prev":
            self.shift_month(-1)
        elif kind == "next":
            self.shift_month(1)
        elif kind == "today":
            t = jalali.today_jalali()
            self.cur = (t["jy"], t["jm"])
            self._pick(t["jd"])
        else:
            self._pick(d)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        n = jalali.month_length(*self.cur)
        step = {Qt.Key.Key_Left: 1 if self.isRightToLeft() else -1, Qt.Key.Key_Right: -1 if self.isRightToLeft() else 1,
                Qt.Key.Key_Up: -7, Qt.Key.Key_Down: 7}.get(e.key())
        if step is not None:
            nd = self.focus_d + step
            if nd < 1:
                self.shift_month(-1)
                nd = jalali.month_length(*self.cur) + nd
            elif nd > n:
                nd -= n
                self.shift_month(1)
            self.focus_d = max(1, min(nd, jalali.month_length(*self.cur)))
            self.update()
        elif e.key() == Qt.Key.Key_PageUp:
            self.shift_month(-1)
        elif e.key() == Qt.Key.Key_PageDown:
            self.shift_month(1)
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._pick(self.focus_d)
        else:
            super().keyPressEvent(e)

    # ---- paint
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _pal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._layout()
        f = QFont(self.font())
        f.setPointSizeF(max(9.0, f.pointSizeF()))
        # header: month + year centred, arrows at the ends
        hf = QFont(f)
        hf.setBold(True)
        p.setFont(hf)
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(0, 0, self.width(), HEAD), int(Qt.AlignmentFlag.AlignCenter),
                   f"{jalali.MONTHS_FA[self.cur[1] - 1]} {jalali.fa(self.cur[0])}")
        rtl = self.isRightToLeft()
        for r, (kind, _d) in self._hits:
            if kind in ("prev", "next"):
                hot = self.hover == (kind, 0)
                if hot:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(pal["soft"]))
                    p.drawRoundedRect(r, 10, 10)
                pm = icons.pixmap("chevron", pal["text"] if hot else pal["muted"], 16)
                from PyQt6.QtGui import QTransform
                ang = 90 if (kind == "prev") != rtl else -90          # the chevron points down by default
                pm = pm.transformed(QTransform().rotate(ang), Qt.TransformationMode.SmoothTransformation)
                p.drawPixmap(int(r.center().x() - pm.width() / pm.devicePixelRatio() / 2),
                             int(r.center().y() - pm.height() / pm.devicePixelRatio() / 2), pm)
        # weekday letters
        p.setFont(f)
        for c in range(7):
            p.setPen(QColor(pal["danger"] if c == 6 else pal["muted"]))
            p.drawText(QRectF(self._col_x(c), HEAD, CELL, WEEK), int(Qt.AlignmentFlag.AlignCenter), jalali.WEEKDAYS_SHORT[c])
        today = jalali.today_jalali()
        first = self._first_col()
        for r, (kind, d) in self._hits:
            if kind != "day":
                continue
            col = (first + d - 1) % 7
            is_sel = bool(self.sel) and (self.sel["jy"], self.sel["jm"], self.sel["jd"]) == (*self.cur, d)
            is_today = (today["jy"], today["jm"], today["jd"]) == (*self.cur, d)
            hov = self.hover == ("day", d)
            if is_sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent"]))
                p.drawRoundedRect(r, _rad(9), _rad(9))
                p.setPen(QColor(pal["ink"]))
            else:
                if hov:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(pal["soft"]))
                    p.drawRoundedRect(r, _rad(9), _rad(9))
                if is_today:
                    p.setPen(QPen(QColor(pal["accent"]), 1.4))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), _rad(9), _rad(9))
                p.setPen(QColor(pal["danger"] if col == 6 else pal["text"]))
            if self.hasFocus() and d == self.focus_d:
                p.save()
                p.setPen(QPen(QColor(pal["hi"]), 1, Qt.PenStyle.DotLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), _rad(10), _rad(10))
                p.restore()
                p.setPen(QColor(pal["ink"] if is_sel else pal["text"]))
            p.setFont(hf if is_sel else f)
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), jalali.fa(d))
        # footer: "today"
        tr = next(r for r, (k, _d) in self._hits if k == "today")
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawLine(QPointF(PAD, tr.top() - 2), QPointF(self.width() - PAD, tr.top() - 2))
        if self.hover == ("today", 0):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["soft"]))
            p.drawRoundedRect(tr, 10, 10)
        p.setFont(f)
        p.setPen(QColor(pal["acc_text"]))
        p.drawText(tr, int(Qt.AlignmentFlag.AlignCenter), f"امروز  ·  {jalali.label(today, True)}")
        p.end()


class DateButton(QAbstractButton):
    """The pill: «۱۰ مهر ۱۴۰۵» + a calendar glyph. Click opens the popover; ``changed`` fires when a day is picked."""

    changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value: dict | None = None
        self.cal: MiniCalendar | None = None
        self.pop = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self.open_popover)

    def set_value(self, v: dict | None) -> None:
        self.value = dict(v) if v else None
        if self.cal is not None:
            self.cal.set_value(self.value)
        self.setAccessibleName("تاریخ: " + (jalali.label(self.value, True) or "انتخاب نشده"))
        self.update()

    def text_now(self) -> str:
        return jalali.label(self.value, True) or "انتخاب تاریخ"

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(max(150, self.fontMetrics().horizontalAdvance(self.text_now()) + 70), 38)

    def open_popover(self) -> None:
        from .notes_page import Popover
        if self.cal is None:
            self.cal = MiniCalendar(self.value)
            self.cal.picked.connect(self._picked)
            self.pop = Popover(self.cal, self)
        self.cal.set_value(self.value)
        self.pop.show_under(self)
        self.cal.setFocus()

    def _picked(self, v: dict) -> None:
        self.set_value(v)
        self.changed.emit(dict(v))
        if self.pop is not None:
            self.pop.hide()

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
        p.drawPixmap(int(gx), int(r.center().y() - 8), icons.pixmap("calendar", pal["muted"] if not on else pal["acc_text"], 16))
        p.setPen(QColor(pal["text"] if on and self.value else pal["muted"]))
        tr = QRectF(r.left() + 12, r.top(), r.width() - 44, r.height()) if rtl else QRectF(r.left() + 34, r.top(), r.width() - 46, r.height())
        p.drawText(tr, int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)), self.text_now())
        p.end()

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(e)
