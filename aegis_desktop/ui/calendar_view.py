# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar page: month / week / day / agenda / year views, in the spirit of Google Calendar and Notion Calendar.

Custom-painted grids (one QPainter pass, no per-cell widgets) so navigation stays instant. Column 0 is Saturday and is drawn
on the right (RTL). What the grids let you do with the mouse:

* week / day: drag on an empty stretch of a day to draw a new task (15-minute snapping, the quick-create card opens where you
  let go); double-click an empty slot for a one-hour task; drag a task to move it (across days, and up into the all-day strip);
  drag its top / bottom edge to change its start / end; tick its circle to finish it; right-click for the task menu.
* month: drag over several days to make a multi-day task; drag a task to another day (it follows the pointer); «+N more» opens
  that day; right-click for menus.
* mini month (beside the calendar) and the year view jump to any day; the keyboard covers T M W D A Y, PageUp / PageDown and N.

Every change goes through ``ctx.changed(..., undo=...)`` so «واگرد» works for all of it.
"""
from __future__ import annotations

import copy
import datetime as dt

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QListWidget, QListWidgetItem, QScrollArea, QStackedWidget, QVBoxLayout,
                             QWidget, QFrame)

from .motion_widgets import RubberSegment
from .tokens import PAGE
from . import anim, flip, icons
from ..core import jalali, logic
from ..core.jalali import fa
from ..core.store import uid
from .calendar_kit import (MIN_SPAN, STEP, MiniMonth, QuickCreate, hm, hm_end, layout_events, range_text, snap, span_of,
                           when_text)
from .theme import AL_R
from .theme import rr as _rad
from .fx_widgets import color_hex
from .theme import PALETTES
from .widgets import button, card, label
from .premium import EmptyList, TaskRowDelegate, alpha, pmenu
from .fx_widgets import _fpal
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate

UR = Qt.ItemDataRole.UserRole
PR_KEY = {"high": "danger", "normal": "accent2", "low": "muted"}
HOUR_H = 46
HEAD_H = 30
GUTTER = 52
DRAG_PX = 5                                    # a press that moves less than this is a click


def _pal(theme: str) -> dict:
    return PALETTES[theme]


def task_color(x: dict, pal: dict) -> QColor:
    """User tag colour if set, else a priority tone taken from the active theme."""
    return QColor(color_hex(x.get("color")) or pal[PR_KEY.get(x.get("pr"), "accent")])


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=jalali.weekday_index(d))


def _chip(p: QPainter, r: QRectF, x: dict, pal: dict, font: QFont, hover: bool = False, time: bool = True) -> None:
    """A one-line task chip (month cells, all-day strip)."""
    c = task_color(x, pal)
    done = bool(x.get("done"))
    bg = QColor(c)
    bg.setAlphaF(0.10 if done else (0.30 if hover else 0.20))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(r, _rad(5), _rad(5))
    bar = QColor(c)
    bar.setAlphaF(0.45 if done else 1)
    p.setBrush(bar)
    p.drawRoundedRect(QRectF(r.right() - 3, r.top() + 2, 3, r.height() - 4), 1.5, 1.5)
    f = QFont(font)
    f.setPointSizeF(max(8.0, font.pointSizeF() - 1))
    f.setStrikeOut(done)
    p.setFont(f)
    t = QColor(pal["muted"] if done else pal["text"])
    p.setPen(t)
    s = x.get("title", "")
    if time and x.get("timeFrom"):
        s = f"{fa(x['timeFrom'])} {s}"
    tr = r.adjusted(4, 0, -8, 0)
    p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | AL_R,
               p.fontMetrics().elidedText(s, Qt.TextElideMode.ElideRight, int(tr.width())))


def _event_chip(p: QPainter, r: QRectF, x: dict, pal: dict, font: QFont, span: tuple[int, int] | None = None,
                hover: bool = False, dim: bool = False, lift: bool = False, check: bool = True) -> QRectF | None:
    """A timed task on the day grid: colour bar, a tick circle (returned so the grid can hit-test it), the title and - when the
    block is tall enough - its time range. ``dim`` = the original of something being dragged, ``lift`` = the dragged copy."""
    c = task_color(x, pal)
    done = bool(x.get("done"))
    p.save()
    p.setOpacity(0.32 if dim else 1.0)
    bg = QColor(c)
    bg.setAlphaF(0.10 if done else 0.40 if lift else 0.30 if hover else 0.20)
    p.setPen(QPen(QColor(c), 1.2) if lift else Qt.PenStyle.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(r, _rad(6), _rad(6))
    p.setPen(Qt.PenStyle.NoPen)
    bar = QColor(c)
    bar.setAlphaF(0.45 if done else 1)
    p.setBrush(bar)
    p.drawRoundedRect(QRectF(r.right() - 3, r.top() + 2, 3, r.height() - 4), 1.5, 1.5)
    chk = None
    text_right = r.right() - 9
    if check and r.width() >= 74 and r.height() >= 22:
        d = 13.0
        chk = QRectF(r.right() - 9 - d, r.top() + (5.0 if r.height() >= 30 else (r.height() - d) / 2), d, d)
        p.setPen(QPen(bar if not done else QColor(c), 1.4))
        p.setBrush(QColor(c) if done else Qt.BrushStyle.NoBrush)
        p.drawEllipse(chk)
        if done:
            p.setPen(QPen(QColor(pal["ink"]), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            cc = chk.center()
            p.drawPolyline([QPointF(cc.x() - 3, cc.y() + 0.2), QPointF(cc.x() - 0.8, cc.y() + 2.4), QPointF(cc.x() + 3.2, cc.y() - 2.2)])
        text_right = chk.left() - 6
    f = QFont(font)
    f.setPointSizeF(max(8.0, font.pointSizeF() - 1))
    f.setStrikeOut(done)
    p.setFont(f)
    two = span is not None and r.height() >= 40
    tr = QRectF(r.left() + 6, r.top() + (3 if two else 0), max(10.0, text_right - r.left() - 6), 17 if two else r.height())
    p.setPen(QColor(pal["muted"] if done else pal["text"]))
    title = x.get("title", "")
    if not two and span is not None and r.width() >= 120:
        title = f"{fa(hm(span[0]))}  {title}"
    p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | AL_R, QFontMetrics(f).elidedText(title, Qt.TextElideMode.ElideRight, int(tr.width())))
    if two:
        f2 = QFont(f)
        f2.setStrikeOut(False)
        f2.setPointSizeF(max(7.5, f.pointSizeF() - 0.5))
        p.setFont(f2)
        p.setPen(QColor(pal["muted"]))
        tr2 = QRectF(r.left() + 6, r.top() + 20, max(10.0, r.right() - 12 - r.left() - 6), 15)
        p.drawText(tr2, Qt.AlignmentFlag.AlignVCenter | AL_R, range_text(*span))
    p.restore()
    return chk


def _ghost_box(p: QPainter, r: QRectF, pal: dict, title: str, text: str) -> None:
    """The block that follows a drag that draws a new task: dashed accent outline, a soft wash, its time range."""
    c = QColor(pal["accent2"])
    p.save()
    fill = QColor(c)
    fill.setAlphaF(0.20)
    p.setBrush(fill)
    p.setPen(QPen(c, 1.3, Qt.PenStyle.DashLine))
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), _rad(6), _rad(6))
    f = QFont(p.font())
    f.setPointSizeF(max(8.0, f.pointSizeF()))
    p.setFont(f)
    p.setPen(QColor(pal["text"]))
    if r.height() >= 34:
        p.drawText(QRectF(r.left() + 8, r.top() + 3, r.width() - 16, 17), Qt.AlignmentFlag.AlignVCenter | AL_R, title)
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(r.left() + 8, r.top() + 20, r.width() - 16, 15), Qt.AlignmentFlag.AlignVCenter | AL_R, text)
    else:
        p.drawText(r.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | AL_R, text)
    p.restore()


class AgendaDelegate(QStyledItemDelegate):
    """Agenda rows: day headers with a hairline, task rows as soft cards with a colour bar and time chip."""

    def sizeHint(self, opt, idx):  # noqa: N802
        return QSize(120, 44 if idx.data(UR + 1) == "hdr" else 50)

    def paint(self, p, opt, idx):  # noqa: D401
        pal = _fpal(opt.widget)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(opt.rect)
        title = idx.data(Qt.ItemDataRole.DisplayRole) or ""
        if idx.data(UR + 1) == "hdr":
            f = QFont(opt.font)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(pal["acc_text"]))
            p.drawText(QRectF(r.left() + 6, r.top() + 12, r.width() - 12, 22), AL_R | Qt.AlignmentFlag.AlignVCenter, title)
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.drawLine(int(r.left() + 6), int(r.bottom() - 2), int(r.right() - 6), int(r.bottom() - 2))
            p.restore()
            return
        box = r.adjusted(4, 3, -4, -3)
        hov = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        p.setPen(QPen(QColor(pal["accent"]), 1) if sel else Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["soft"]) if sel else QColor(pal["panel2"] if hov else pal["panel"]))
        p.drawRoundedRect(box, _rad(10), _rad(10))
        col = QColor(idx.data(UR + 2) or pal["accent"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(box.right() - 4, box.top() + 9, 4, box.height() - 18), 2, 2)
        tm = idx.data(UR + 3) or ""
        tw = 0.0
        if tm:
            f = QFont(opt.font)
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(tm) + 20
            chip = QRectF(box.left() + 10, box.center().y() - 11, tw, 22)
            bg = QColor(col)
            bg.setAlphaF(0.18)
            p.setBrush(bg)
            p.drawRoundedRect(chip, 11, 11)
            p.setPen(QColor(pal["text"]))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, tm)
        done = bool(idx.data(UR + 4))
        f = QFont(opt.font)
        f.setStrikeOut(done)
        p.setFont(f)
        p.setPen(QColor(pal["muted"] if done else pal["text"]))
        tx = QRectF(box.left() + 18 + tw, box.top(), box.width() - 36 - tw, box.height())
        p.drawText(tx, AL_R | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, int(tx.width())))
        p.restore()


class MonthGrid(QWidget):
    selected = pyqtSignal(object)        # date
    add = pyqtSignal(object)             # date (double click)
    open_task = pyqtSignal(str)
    moved = pyqtSignal(str, object, object)      # task id, day it was dropped on, day it was grabbed on
    create_days = pyqtSignal(object, object)   # first and last day of a range dragged over empty space
    open_day = pyqtSignal(object)        # «+N more»

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMouseTracking(True)
        self.setMinimumHeight(360)
        self._cells: list[tuple[QRectF, dt.date]] = []
        self._chips: list[tuple[QRectF, str]] = []
        self._more: list[tuple[QRectF, dt.date]] = []
        self._hover: dt.date | None = None
        self._press: tuple[str, QPointF] | None = None
        self._drag_to: dt.date | None = None
        self._drag_pos: QPointF | None = None
        self._range: tuple[dt.date, QPointF] | None = None       # a press on empty space: might become a range
        self._range_to: dt.date | None = None
        self._pending: tuple[dt.date, dt.date] | None = None      # the range kept lit while the quick-create card is open

    def _cell_at(self, pos) -> dt.date | None:
        for r, d in self._cells:
            if r.contains(pos):
                return d
        return None

    def _chip_at(self, pos) -> str | None:
        for r, tid in self._chips:
            if r.contains(pos):
                return tid
        return None

    def cell_rect(self, d: dt.date) -> QRectF | None:
        return next((r for r, x in self._cells if x == d), None)

    def clear_pending(self) -> None:
        self._pending = None
        self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        d = self._cell_at(pos)
        if self._press and (pos - self._press[1]).manhattanLength() > 8:
            self._drag_to, self._drag_pos = d, pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
            return
        if self._range and (pos - self._range[1]).manhattanLength() > 8:
            self._range_to = d or self._range_to
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()
            return
        if d != self._hover:
            self._hover = d
            self.update()
        over = self._chip_at(pos) is not None or any(r.contains(pos) for r, _ in self._more)
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        for r, d in self._more:
            if r.contains(pos):
                self.open_day.emit(d)
                return
        tid = self._chip_at(pos)
        if tid:
            self._press = (tid, pos)
            return
        d = self._cell_at(pos)
        if d:
            self._range, self._range_to = (d, pos), None
            self.selected.emit(d)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._press:
            tid, p0 = self._press
            d = self._cell_at(e.position())
            if self._drag_to and d:
                self.moved.emit(tid, d, self._cell_at(p0))
            elif (e.position() - p0).manhattanLength() <= 8:
                d0 = self._cell_at(p0)
                if d0:
                    self.selected.emit(d0)
                self.open_task.emit(tid)
        elif self._range and self._range_to is not None and self._range_to != self._range[0]:
            a, b = sorted((self._range[0], self._range_to))
            self._pending = (a, b)
            self.create_days.emit(a, b)
        self._press, self._drag_to, self._drag_pos, self._range, self._range_to = None, None, None, None, None
        self.unsetCursor()
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        d = self._cell_at(e.position())
        if d and not self._chip_at(e.position()) and not any(r.contains(e.position()) for r, _d in self._more):
            self._pending = (d, d)                                          # a double click on a day: the quick card for that day
            self.create_days.emit(d, d)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        tid = self._chip_at(QPointF(e.pos()))
        if tid:
            self.page.task_menu(tid, e.globalPos())
            return
        d = self._cell_at(QPointF(e.pos()))
        if d:
            self.selected.emit(d)
            self.page.day_menu(d, e.globalPos())

    def paintEvent(self, _e) -> None:  # noqa: N802
        pg = self.page
        pal = _pal(pg.ctx.theme)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        from .theme import rr as _rr
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), _rr(12), _rr(12))
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(pal["panel"]))
        p.fillRect(QRectF(0, 0, W, HEAD_H), QColor(pal["panel2"]))
        first = dt.date(*jalali.to_gregorian(pg.jy, pg.jm, 1))
        start = first - dt.timedelta(days=jalali.weekday_index(first))
        n = jalali.month_length(pg.jy, pg.jm)
        rows = 6 if jalali.weekday_index(first) + n > 35 else 5
        cw, ch = W / 7, (H - HEAD_H) / rows
        line = QColor(pal["line"])
        # header
        p.setPen(QColor(pal["muted"]))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        p.setFont(f)
        for c in range(7):
            x = W - (c + 1) * cw
            p.setPen(QColor(pal["danger"]) if c == 6 else QColor(pal["muted"]))
            p.drawText(QRectF(x, 0, cw, HEAD_H), Qt.AlignmentFlag.AlignCenter, jalali.WEEKDAYS_FA[c])
        p.setPen(QPen(line, 1))
        p.drawLine(0, HEAD_H, W, HEAD_H)
        self._cells, self._chips, self._more = [], [], []
        today = dt.date.today()
        f2 = QFont(self.font())
        span = None                                                       # a range being dragged (or waiting for its title)
        if self._range and self._range_to is not None:
            span = tuple(sorted((self._range[0], self._range_to)))
        elif self._pending:
            span = self._pending
        for i in range(rows * 7):
            r_, c = divmod(i, 7)
            d = start + dt.timedelta(days=i)
            rect = QRectF(W - (c + 1) * cw, HEAD_H + r_ * ch, cw, ch)
            self._cells.append((rect, d))
            inmonth = jalali.to_jalali(d.year, d.month, d.day)[1] == pg.jm
            if c == 6:
                p.fillRect(rect, QColor(pal["panel2"]) if inmonth else QColor(pal["panel2"]).darker(103))
            ts = pg.filtered(d)
            if ts and inmonth:                               # workload heat: busier days carry a deeper wash
                s = QColor(pal["accent2"])
                s.setAlphaF(min(0.11, 0.025 * len(ts)))
                p.fillRect(rect, s)
            if d == self._hover and not self._press and not self._range_to:
                s = QColor(pal["text"])
                s.setAlphaF(0.035)
                p.fillRect(rect, s)
            if d == pg.selected:
                s = QColor(pal["text"])
                s.setAlphaF(0.05)
                p.fillRect(rect, s)
                p.setPen(QPen(QColor(pal["accent2"]), 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), _rr(6), _rr(6))
            if d == self._drag_to:
                s = QColor(pal["accent2"])
                s.setAlphaF(0.22)
                p.fillRect(rect, s)
            if span and span[0] <= d <= span[1]:
                s = QColor(pal["accent2"])
                s.setAlphaF(0.18)
                p.fillRect(rect, s)
            p.setPen(QPen(line, 1))
            p.drawLine(rect.bottomLeft(), rect.bottomRight())
            p.drawLine(rect.topLeft(), rect.bottomLeft())
            # day number
            jd = jalali.to_jalali(d.year, d.month, d.day)[2]
            nb = QRectF(rect.right() - 30, rect.top() + 4, 24, 22)
            if d == today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent"]))
                p.drawEllipse(nb)
                p.setPen(QColor(pal["ink"]))
            else:
                p.setPen(QColor(pal["text"]) if inmonth else QColor(pal["muted"]))
            fb = QFont(f2)
            fb.setBold(d == today or d == pg.selected)
            p.setFont(fb)
            p.drawText(nb, Qt.AlignmentFlag.AlignCenter, fa(jd))
            # hover + button
            if d == self._hover and not self._press and not self._range_to:
                pb = QRectF(rect.left() + 6, rect.top() + 5, 18, 18)
                p.setPen(QPen(QColor(pal["muted"]), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                cx, cy = pb.center().x(), pb.center().y()
                p.drawLine(QPointF(cx - 4, cy), QPointF(cx + 4, cy))
                p.drawLine(QPointF(cx, cy - 4), QPointF(cx, cy + 4))
            # chips
            y = rect.top() + 28
            room = int((rect.bottom() - y - 2) // 20)
            shown = ts if len(ts) <= room else ts[:max(0, room - 1)]
            for x in shown:
                cr = QRectF(rect.left() + 3, y, cw - 6, 18)
                _chip(p, cr, x, pal, self.font(), hover=x["id"] == (self._press[0] if self._press and self._drag_to else None))
                self._chips.append((cr, x["id"]))
                y += 20
            if len(ts) > len(shown):
                p.setPen(QColor(pal["acc_text"]))
                _mf = QFont(self.font())
                _mf.setBold(True)
                p.setFont(_mf)
                mr = QRectF(rect.left() + 4, y, cw - 10, 18)
                p.drawText(mr, Qt.AlignmentFlag.AlignVCenter | AL_R, f"{fa(len(ts) - len(shown))} مورد دیگر")
                self._more.append((mr, d))
        if self._press and self._drag_to is not None and self._drag_pos is not None:       # the dragged chip follows the pointer
            x = pg.by_id(self._press[0])
            if x:
                p.setOpacity(0.92)
                _chip(p, QRectF(self._drag_pos.x() - cw / 2 + 3, self._drag_pos.y() - 9, cw - 6, 18), x, pal, self.font(), hover=True)
                p.setOpacity(1.0)
        p.setClipping(False)
        p.setPen(QPen(line, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), _rr(12), _rr(12))


class TimeGrid(QWidget):
    """Week (7 columns) or day (1 column) time grid with an all-day strip and a now-line - and the mouse work described in
    the module docstring (draw, move, resize, tick)."""
    selected = pyqtSignal(object)
    add = pyqtSignal(object)
    open_task = pyqtSignal(str)
    create_range = pyqtSignal(object, object, object)      # date, start minute | None, end minute | None (None = all-day)
    retime = pyqtSignal(str, object, object, object, object)       # task id, date, start minute | None, end minute | None, day it was grabbed on
    toggle_done = pyqtSignal(str)

    def __init__(self, page, days: int):
        super().__init__()
        self.page, self.ndays = page, days
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._chips: list[tuple[QRectF, str]] = []
        self._blocks: list[dict] = []                          # rect, id, date, start, end of every timed block painted
        self._checks: list[tuple[QRectF, str]] = []
        self._sticky: list[tuple[QRectF, str]] = []
        self._cols: list[tuple[QRectF, dt.date]] = []
        self._allday_h = 26
        self._hover: str | None = None
        self._hover_slot: tuple[int, int] | None = None        # (column, minute) under the pointer on empty space
        self._st: dict | None = None                           # the press / drag in progress
        self._ghost: dict | None = None                        # what a drag would leave behind
        self._pending: dict | None = None                      # a drawn block kept lit while the quick-create card is open
        self._last = QPointF()                                 # the pointer in this widget's coordinates while a drag runs
        self._auto = QTimer(self, interval=30)
        self._auto.timeout.connect(self._autoscroll)

    # ------------------------------------------------------------------------------------------- geometry ---
    def dates(self) -> list[dt.date]:
        pg = self.page
        return [pg.selected] if self.ndays == 1 else [week_start(pg.selected) + dt.timedelta(days=i) for i in range(7)]

    def _top(self) -> int:
        return HEAD_H + self._allday_h

    def _cw(self) -> float:
        return max(1.0, (self.width() - GUTTER) / max(1, self.ndays if self.ndays == 1 else 7))

    def _col_at(self, x: float) -> int:
        n = len(self.dates())
        return max(0, min(n - 1, int((self.width() - GUTTER - x) // self._cw())))

    def _col_x(self, i: int) -> float:
        return self.width() - GUTTER - (i + 1) * self._cw()

    def _min_at(self, y: float) -> float:
        return (y - self._top()) / HOUR_H * 60

    def _y_of(self, m: float) -> float:
        return self._top() + m / 60 * HOUR_H

    def _sync_height(self) -> None:
        pg = self.page
        rows = max([1] + [sum(1 for x in pg.filtered(d) if span_of(x) is None) for d in self.dates()])
        self._allday_h = 8 + 22 * rows
        self.setFixedHeight(HEAD_H + self._allday_h + 24 * HOUR_H + 6)

    def _scroll(self) -> int:
        sc = self.page.week_sc if self.ndays == 7 else self.page.day_sc
        return sc.verticalScrollBar().value()

    def block_rect(self, d: dt.date, a: int | None, b: int | None) -> QRectF | None:
        """Where a block of (date, start, end) sits in this grid, or None when that day is not shown."""
        dates = self.dates()
        if d not in dates:
            return None
        x = self._col_x(dates.index(d))
        cw = self._cw()
        if a is None:
            return QRectF(x + 3, HEAD_H + 4 + self._scroll(), cw - 6, 20)
        return QRectF(x + 3, self._y_of(a) + 1, cw - 6, max(20.0, (b - a) / 60 * HOUR_H - 2))

    def pending_global_rect(self) -> QRect | None:
        g = self._pending
        if not g:
            return None
        r = self.block_rect(g["date"], g["a"], g["b"])
        if r is None:
            return None
        rr_ = r.toRect()
        return QRect(self.mapToGlobal(rr_.topLeft()), rr_.size())

    def clear_pending(self) -> None:
        self._pending = None
        self.update()

    # ----------------------------------------------------------------------------------------------- hits ---
    def _chip_zone(self, pos) -> tuple[dict, str] | None:
        for blk in reversed(self._blocks):
            r = blk["rect"]
            if r.contains(pos):
                zone = "body"
                if r.height() >= 34 and pos.y() >= r.bottom() - 6:
                    zone = "bottom"
                elif r.height() >= 46 and pos.y() <= r.top() + 5:
                    zone = "top"
                return blk, zone
        return None

    def _in_header(self, pos) -> bool:
        return pos.y() < self._scroll() + self._top()

    def _hit(self, pos):
        for r, tid in self._sticky:                                   # the floating header is on top
            if r.contains(pos):
                return tid
        if self._in_header(pos):                                       # nothing under the header can be clicked
            return None
        z = self._chip_zone(pos)
        return z[0]["id"] if z else None

    # ------------------------------------------------------------------------------------------------ mouse ---
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        st = self._st
        if st is not None:
            self._last = pos
            if st["kind"].startswith("pend_"):
                if (pos - st["origin"]).manhattanLength() < DRAG_PX or st["kind"] == "pend_check":
                    return
                st["kind"] = st["kind"][5:]
                self._auto.start()
                self.setCursor(Qt.CursorShape.SizeVerCursor if st["kind"].startswith("rs_") else
                               Qt.CursorShape.CrossCursor if st["kind"] == "create" else Qt.CursorShape.ClosedHandCursor)
            self._drag_to(pos)
            return
        h = self._hit(pos)
        zone = self._chip_zone(pos)[1] if (h and not self._in_header(pos)) else "body"
        slot = None
        if not h and not self._in_header(pos) and pos.x() < self.width() - GUTTER:
            slot = (self._col_at(pos.x()), max(0, min(24 * 60 - STEP, (int(self._min_at(pos.y())) // STEP) * STEP)))
        if h != self._hover or slot != self._hover_slot:
            self._hover, self._hover_slot = h, slot
            self.update()
        if h:
            self.setCursor(Qt.CursorShape.SizeVerCursor if zone in ("top", "bottom") else Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, e) -> None:  # noqa: N802
        if self._st is None and (self._hover or self._hover_slot):
            self._hover, self._hover_slot = None, None
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        pos = e.position()
        for r, tid in self._checks:
            if r.contains(pos) and not self._in_header(pos):
                self._st = {"kind": "pend_check", "tid": tid, "origin": pos, "rect": r}
                return
        for r, tid in self._sticky:
            if r.contains(pos):
                self._st = {"kind": "pend_allday", "tid": tid, "origin": pos, "date": self.dates()[self._col_at(pos.x())]}
                return
        dates = self.dates()
        if self._in_header(pos):                                        # weekday titles / empty all-day strip: pick the day
            col = self._col_at(pos.x())
            if pos.x() < self.width() - GUTTER:
                self.selected.emit(dates[col])
                self._st = {"kind": "pend_create_allday", "origin": pos, "col": col}
            return
        z = self._chip_zone(pos)
        if z:
            blk, zone = z
            kind = {"body": "pend_move", "top": "pend_rs_top", "bottom": "pend_rs_bottom"}[zone]
            self._st = {"kind": kind, "tid": blk["id"], "origin": pos, "date": blk["date"], "a0": blk["a"], "b0": blk["b"],
                        "grab": self._min_at(pos.y()) - blk["a"]}
            return
        if pos.x() >= self.width() - GUTTER:
            return
        col = self._col_at(pos.x())
        self.selected.emit(dates[col])
        m = self._min_at(pos.y())
        self._st = {"kind": "pend_create", "origin": pos, "col": col, "p0": max(0, min(24 * 60 - STEP, (int(m) // STEP) * STEP))}

    def _drag_to(self, pos) -> None:
        st = self._st
        dates = self.dates()
        col = self._col_at(pos.x())
        d = dates[col]
        m = self._min_at(pos.y())
        k = st["kind"]
        top_zone = self._in_header(pos)
        g = None
        if k == "create":
            p0 = st["p0"]
            cur = max(0.0, min(24 * 60.0, m))
            if cur >= p0:
                a, b = p0, -(-int(cur) // STEP) * STEP
            else:
                a, b = (int(cur) // STEP) * STEP, p0 + STEP
            b = min(24 * 60, max(b, a + STEP))
            a = min(a, b - STEP)
            g = {"kind": "create", "date": dates[st["col"]], "a": a, "b": b}
        elif k == "move":
            if top_zone:
                g = {"kind": "allday", "tid": st["tid"], "date": d, "a": None, "b": None}
            else:
                dur = st["b0"] - st["a0"]
                a = max(0, min(24 * 60 - dur, snap(m - st["grab"])))
                g = {"kind": "move", "tid": st["tid"], "date": d, "a": a, "b": a + dur}
        elif k == "allday":
            if top_zone:
                g = {"kind": "allday", "tid": st["tid"], "date": d, "a": None, "b": None}
            else:
                a = max(0, min(24 * 60 - 60, snap(m)))
                g = {"kind": "move", "tid": st["tid"], "date": d, "a": a, "b": a + 60}
        elif k == "rs_bottom":
            g = {"kind": "resize", "tid": st["tid"], "date": st["date"], "a": st["a0"], "b": max(st["a0"] + MIN_SPAN, min(24 * 60, snap(m)))}
        elif k == "rs_top":
            g = {"kind": "resize", "tid": st["tid"], "date": st["date"], "a": min(st["b0"] - MIN_SPAN, max(0, snap(m))), "b": st["b0"]}
        elif k == "create_allday":
            g = {"kind": "create", "date": dates[st["col"]], "a": None, "b": None}
        self._ghost = g
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        st, self._st = self._st, None
        self._auto.stop()
        self.unsetCursor()
        if st is None:
            return
        k = st["kind"]
        g, self._ghost = self._ghost, None
        if k == "pend_check":
            if st["rect"].contains(e.position()):
                self.toggle_done.emit(st["tid"])
        elif k in ("pend_move", "pend_rs_top", "pend_rs_bottom", "pend_allday"):
            self.open_task.emit(st["tid"])                              # a click, not a drag: open the task
        elif k in ("pend_create", "pend_create_allday"):
            pass                                                        # a click on empty space just selected the day
        elif g is not None:
            if g["kind"] == "create":
                self._pending = g
                self.create_range.emit(g["date"], g["a"], g["b"])
            else:
                self.retime.emit(st["tid"], g["date"], g["a"], g["b"], st.get("date"))
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        if self._hit(pos) or pos.x() >= self.width() - GUTTER:
            return
        col = self._col_at(pos.x())
        d = self.dates()[col]
        if self._in_header(pos):
            self._pending = {"kind": "create", "date": d, "a": None, "b": None}
            self.create_range.emit(d, None, None)
            return
        a = max(0, min(23 * 60, (int(self._min_at(pos.y())) // 30) * 30))       # a one-hour block on the half hour
        self._pending = {"kind": "create", "date": d, "a": a, "b": a + 60}
        self.create_range.emit(d, a, a + 60)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape and self._st is not None:
            self._st, self._ghost = None, None
            self._auto.stop()
            self.unsetCursor()
            self.update()
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        pos = QPointF(e.pos())
        tid = self._hit(pos)
        if tid:
            self.page.task_menu(tid, e.globalPos())
            return
        if pos.x() >= self.width() - GUTTER:
            return
        col = self._col_at(pos.x())
        d = self.dates()[col]
        self.selected.emit(d)
        minute = None if self._in_header(pos) else max(0, min(23 * 60, (int(self._min_at(pos.y())) // 30) * 30))
        self.page.day_menu(d, e.globalPos(), minute)

    def _autoscroll(self) -> None:
        """While a drag is near the top or bottom edge of the visible hours, the grid keeps scrolling. The pointer is the
        last one the drag saw (not QCursor.pos), so this behaves the same on every platform and under test."""
        st = self._st
        if st is None or st["kind"].startswith("pend_"):
            return
        sc = self.page.week_sc if self.ndays == 7 else self.page.day_sc
        vp = sc.viewport()
        y = self.mapTo(vp, self._last.toPoint()).y()
        edge = 22
        dy = 0
        if y > vp.height() - edge:
            dy = min(18, 4 + (y - (vp.height() - edge)) // 3)
        elif y < self._top() + edge and (st["kind"] in ("create",) or y >= self._top()):
            dy = -min(18, 4 + (self._top() + edge - y) // 3)
        if dy:
            bar = sc.verticalScrollBar()
            before = bar.value()
            bar.setValue(before + int(dy))
            moved = bar.value() - before                       # the pointer stays put on screen, so it slides over the grid
            if moved:
                self._last = QPointF(self._last.x(), self._last.y() + moved)
                self._drag_to(self._last)

    # ------------------------------------------------------------------------------------------------ paint ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        pg = self.page
        pal = _pal(pg.ctx.theme)
        self._sync_height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = self.width()
        p.fillRect(self.rect(), QColor(pal["panel"]))
        dates = self.dates()
        n = len(dates)
        cw = self._cw()
        line = QColor(pal["line"])
        today = dt.date.today()
        top = self._top()
        sv = self._scroll()
        self._chips, self._cols, self._sticky, self._blocks, self._checks = [], [], [], [], []
        fsmall = QFont(self.font())
        fsmall.setPointSizeF(max(8.0, fsmall.pointSizeF() - 1))
        for i, d in enumerate(dates):
            x = self._col_x(i)
            self._cols.append((QRectF(x, 0, cw, self.height()), d))
            if jalali.weekday_index(d) == 6:
                p.fillRect(QRectF(x, HEAD_H, cw, self.height() - HEAD_H), QColor(pal["panel2"]))
            if d == pg.selected and n > 1:
                s = QColor(pal["text"])
                s.setAlphaF(0.04)
                p.fillRect(QRectF(x, HEAD_H, cw, self.height() - HEAD_H), s)
            p.setPen(QPen(line, 1))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        # hover slot (a faint 15-minute cell under the pointer, so it is clear that drawing is possible)
        if self._hover_slot and not self._st:
            col, mm = self._hover_slot
            hr = QRectF(self._col_x(col) + 2, self._y_of(mm), cw - 4, HOUR_H * STEP / 60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(pal["accent2"], 0.10))
            p.drawRoundedRect(hr, 4, 4)
            if cw >= 60:
                p.setPen(QPen(alpha(pal["muted"], 0.9), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                c = hr.center()
                p.drawLine(QPointF(c.x() - 3.5, c.y()), QPointF(c.x() + 3.5, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - 3.5), QPointF(c.x(), c.y() + 3.5))
        # hour lines + labels
        p.setFont(fsmall)
        hot = None
        if self._ghost and self._ghost.get("a") is not None:
            hot = self._ghost["a"]
        elif self._hover_slot and not self._st:
            hot = self._hover_slot[1]
        for h in range(24):
            y = top + h * HOUR_H
            p.setPen(QPen(line, 1, Qt.PenStyle.DotLine if h else Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(0, y), QPointF(W - GUTTER, y))
            if hot is not None and abs(hot - h * 60) < 22:
                continue                                                # the time being pointed at replaces the hour label beside it
            p.setPen(QColor(pal["muted"]))
            p.drawText(QRectF(W - GUTTER, y - 8, GUTTER - 8, 16), AL_R | Qt.AlignmentFlag.AlignVCenter, fa(f"{h:02d}:00"))
        if hot is not None:
            f = QFont(fsmall)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(pal["acc_text"]))
            p.drawText(QRectF(W - GUTTER, self._y_of(hot) - 8, GUTTER - 8, 16), AL_R | Qt.AlignmentFlag.AlignVCenter, fa(hm(hot)))
            p.setFont(fsmall)
        # timed tasks
        allday: list[tuple[int, list[dict]]] = []
        dim = self._ghost.get("tid") if self._ghost and self._st else None
        for i, d in enumerate(dates):
            x = self._col_x(i)
            timed, untimed = [], []
            for t in pg.filtered(d):
                sp = span_of(t)
                if sp is None:
                    untimed.append(t)
                else:
                    timed.append((sp[0], sp[1], t))
            allday.append((i, untimed))
            for a, b, t, lane, lanes in layout_events(timed):
                lw = (cw - 6) / lanes
                r = QRectF(x + 3 + (lanes - 1 - lane) * lw, self._y_of(a) + 1, lw - 2, max(20.0, (b - a) / 60 * HOUR_H - 2))
                chk = _event_chip(p, r, t, pal, self.font(), (a, b), hover=t["id"] == self._hover, dim=t["id"] == dim)
                self._chips.append((r, t["id"]))
                self._blocks.append({"rect": r, "id": t["id"], "date": d, "a": a, "b": b})
                if chk is not None:
                    self._checks.append((chk.adjusted(-3, -3, 3, 3), t["id"]))
                if t["id"] == self._hover and r.height() >= 34 and not self._st:      # grab handles on the edges
                    p.setPen(QPen(alpha(pal["text"], 0.55), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    cx = r.center().x()
                    p.drawLine(QPointF(cx - 7, r.bottom() - 3), QPointF(cx + 7, r.bottom() - 3))
        # a block being drawn / moved / resized (and the one kept lit while the quick-create card is open)
        g = self._ghost or self._pending
        if g and g.get("a") is not None:
            r = self.block_rect(g["date"], g["a"], g["b"])
            if r is not None:
                if g["kind"] == "create":
                    _ghost_box(p, r, pal, "تسک جدید", range_text(g["a"], g["b"]))
                else:
                    x = pg.by_id(g.get("tid", ""))
                    if x:
                        _event_chip(p, r, x, pal, self.font(), (g["a"], g["b"]), lift=True, check=False)
        # now line
        now = dt.datetime.now()
        for i, d in enumerate(dates):
            if d == today:
                y = self._y_of(now.hour * 60 + now.minute)
                x = self._col_x(i)
                p.setPen(QPen(QColor(pal["danger"]), 1.6))
                p.drawLine(QPointF(x, y), QPointF(x + cw, y))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["danger"]))
                p.drawEllipse(QPointF(x + cw - 3, y), 4, 4)
                lab = fa(now.strftime("%H:%M"))
                lf = QFont(fsmall)
                lf.setBold(True)
                p.setFont(lf)
                lw_ = QFontMetrics(lf).horizontalAdvance(lab) + 10
                pill = QRectF(W - GUTTER + (GUTTER - 8 - lw_) / 2 + 2, y - 8, lw_, 16)
                p.drawRoundedRect(pill, 8, 8)
                p.setPen(QColor(pal["ink"] if QColor(pal["danger"]).lightness() > 150 else "#ffffff"))
                p.drawText(pill, Qt.AlignmentFlag.AlignCenter, lab)
                p.setFont(fsmall)
        # sticky header: weekday titles + the all-day strip stay put while the hours scroll under them
        p.save()
        p.translate(0, sv)
        p.fillRect(QRectF(0, 0, W, top), QColor(pal["panel"]))
        for i, d in enumerate(dates):
            x = self._col_x(i)
            if jalali.weekday_index(d) == 6:
                p.fillRect(QRectF(x, 0, cw, top), QColor(pal["panel2"]))
            elif d == pg.selected and n > 1:
                s = QColor(pal["text"])
                s.setAlphaF(0.04)
                p.fillRect(QRectF(x, HEAD_H, cw, top - HEAD_H), s)
            jd = jalali.date_to_due(d)
            p.setFont(fsmall)
            head = QRectF(x, 0, cw, HEAD_H)
            if d == today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent"]))
                p.drawRoundedRect(head.adjusted(cw / 2 - 42, 4, -(cw / 2 - 42), -4), 11, 11)
                p.setPen(QColor(pal["ink"]))
            else:
                p.setPen(QColor(pal["danger"]) if jalali.weekday_index(d) == 6 else QColor(pal["text"]))
            p.drawText(head, Qt.AlignmentFlag.AlignCenter, f"{jalali.WEEKDAYS_FA[jalali.weekday_index(d)]} {fa(jd['jd'])}")
            p.setPen(QPen(line, 1))
            p.drawLine(QPointF(x, 0), QPointF(x, top))
        p.setPen(QPen(line, 1))
        p.drawLine(0, HEAD_H, W, HEAD_H)
        p.setPen(QColor(pal["muted"]))
        p.setFont(fsmall)
        p.drawText(QRectF(W - GUTTER, HEAD_H, GUTTER - 8, self._allday_h), AL_R | Qt.AlignmentFlag.AlignVCenter, "تمام‌روز")
        for i, untimed in allday:
            x = self._col_x(i)
            ay = HEAD_H + 4
            for t in untimed:
                r = QRectF(x + 3, ay, cw - 6, 20)
                _chip(p, r, t, pal, self.font(), t["id"] == self._hover, time=False)
                self._sticky.append((r.translated(0, sv), t["id"]))
                ay += 22
        if g and g.get("a") is None and g.get("date") in dates:                 # an all-day block being drawn / dropped
            i = dates.index(g["date"])
            r = QRectF(self._col_x(i) + 3, HEAD_H + 4 + 22 * sum(1 for t in allday[i][1] if t["id"] != g.get("tid")), cw - 6, 20)
            if g["kind"] == "create":
                _ghost_box(p, r, pal, "", "تسک تمام‌روز")
            else:
                x = pg.by_id(g.get("tid", ""))
                if x:
                    p.setOpacity(0.9)
                    _chip(p, r, x, pal, self.font(), True, time=False)
                    p.setOpacity(1.0)
        p.setPen(QPen(line, 1))
        p.drawLine(0, top, W, top)
        if sv > 0:                                                    # a hairline shadow shows the header floating
            gr = QLinearGradient(0, top, 0, top + 8)
            gr.setColorAt(0, QColor(0, 0, 0, 60))
            gr.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(0, top, W - GUTTER, 8), gr)
        p.restore()


class Segmented(RubberSegment):
    """Calendar view switcher (rubber thumb)."""

    def __init__(self, items, parent=None):
        super().__init__(items)


class YearView(QScrollArea):
    """Twelve small months on one page; a day opens that day, a month title opens that month."""
    picked = pyqtSignal(object)
    month_clicked = pyqtSignal(int, int)

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("YearHost")
        host.setStyleSheet("QWidget#YearHost { background: transparent; }")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setSpacing(12)
        self.months: list[MiniMonth] = []
        for m in range(12):
            f, r = card()
            r.setContentsMargins(10, 8, 10, 6)
            mm = MiniMonth(lambda d: len(page.filtered(d)), page.jy, m + 1, page.selected, compact=True)
            mm.picked.connect(self.picked)
            mm.title_clicked.connect(self.month_clicked)
            r.addWidget(mm)
            self.months.append(mm)
            grid.addWidget(f, m // 3, m % 3)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        self.setWidget(host)

    def set_year(self, jy: int, selected: dt.date) -> None:
        for i, mm in enumerate(self.months):
            mm.jy, mm.jm, mm.selected = jy, i + 1, selected
            mm.update()
        j = jalali.date_to_due(selected)
        if j["jy"] == jy:                                          # bring the picked month into view (year is 4 rows tall)
            card_ = self.months[j["jm"] - 1].parentWidget()
            QTimer.singleShot(0, lambda: card_ is not None and self._show(card_))

    def _show(self, w) -> None:
        try:
            self.ensureWidgetVisible(w, 0, 12)
        except RuntimeError:
            pass


class CalendarPage(QWidget):
    def one_accent(self) -> None:
        from .widgets import one_accent
        one_accent(self)

    title = "تقویم"
    VIEWS = ["ماه", "هفته", "روز", "برنامه", "سال"]

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.view = 0
        self._day_idx: dict | None = None
        self._by_id: dict[str, dict] | None = None
        self._quick: QuickCreate | None = None
        self.selected = dt.date.today()
        self.jy, self.jm = jalali.today_jalali()["jy"], jalali.today_jalali()["jm"]
        self._mini_for = (self.jy, self.jm)
        self._busy = False
        root = QHBoxLayout(self)
        root.setContentsMargins(*PAGE)
        root.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(10)
        bar = QHBoxLayout()
        self.title_lb = label("", "H2")
        bar.addWidget(self.title_lb)
        bar.addStretch(1)
        from .system import StepNav
        self.nav = StepNav("امروز")
        self.nav.prev.connect(lambda: self._shift(-1))
        self.nav.today.connect(self._today)
        self.nav.next.connect(lambda: self._shift(1))
        self.nav.setToolTip("قبلی PageUp  ·  امروز T  ·  بعدی PageDown")
        self.print_btn = button("پرینت", slot=self._print_menu)
        self.print_btn.setToolTip("چاپ یا ذخیره PDF روز، هفته یا ماه  Ctrl+P")
        self.print_btn.setIcon(icons.icon("print", PALETTES[ctx.theme]["muted"], 16))
        self.print_btn.setFixedHeight(38)
        for b in (self.print_btn, self.nav):
            bar.addWidget(b)
        left.addLayout(bar)
        bar2 = QHBoxLayout()
        self.seg = Segmented(self.VIEWS)
        self.seg.changed.connect(self._set_view)
        self.seg.setToolTip("ماه M  ·  هفته W  ·  روز D  ·  برنامه A  ·  سال Y")
        bar2.addWidget(self.seg)
        bar2.addStretch(1)
        from .system import ChipCombo
        self.status = ChipCombo("وضعیت")
        for k, t in (("all", "همه"), ("open", "باز"), ("done", "انجام‌شده")):
            self.status.addItem(t, k)
        self.cat = ChipCombo("دسته")
        self.cat.addItem("همه‌ی دسته‌ها", "all")
        for k, t in logic.CATEGORIES:
            self.cat.addItem(t, k)
        for c in (self.status, self.cat):
            c.currentIndexChanged.connect(lambda _=0: self.refresh())
            bar2.addWidget(c)
        left.addLayout(bar2)
        self.stack = QStackedWidget()
        self.month = MonthGrid(self)
        self.week, self.day = TimeGrid(self, 7), TimeGrid(self, 1)
        self.week_sc, self.day_sc = QScrollArea(), QScrollArea()
        for sc, w in ((self.week_sc, self.week), (self.day_sc, self.day)):
            sc.verticalScrollBar().valueChanged.connect(lambda _v, g=w: g.update())      # keeps the header floating
            sc.setWidgetResizable(True)
            sc.setWidget(w)
            sc.setFrameShape(QScrollArea.Shape.NoFrame)
        self.agenda = EmptyList("calendar", "در ۳۰ روز آینده تسکی نیست", "برای روز دلخواه یک تسک اضافه کن.")
        self.agenda.setItemDelegate(AgendaDelegate(self.agenda))
        self.agenda.setMouseTracking(True)
        self.agenda.setFrameShape(QFrame.Shape.NoFrame)
        self.agenda.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.agenda.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.agenda.setWordWrap(True)
        self.agenda.itemDoubleClicked.connect(lambda it: it.data(UR) and ctx.edit_task_id(it.data(UR)))
        self.year = YearView(self)
        self.year.picked.connect(self._year_day)
        self.year.month_clicked.connect(self._year_month)
        for w in (self.month, self.week_sc, self.day_sc, self.agenda, self.year):
            self.stack.addWidget(w)
        left.addWidget(self.stack, 1)
        root.addLayout(left, 3)
        for g in (self.month, self.week, self.day):
            g.selected.connect(self._select)
            g.add.connect(lambda d: ctx.new_task(jalali.date_to_due(d)))
            g.open_task.connect(ctx.edit_task_id)
        self.month.moved.connect(self._move)
        self.month.create_days.connect(self._on_create_days)
        self.month.open_day.connect(self._open_day)
        for g in (self.week, self.day):
            g.create_range.connect(self._on_create_range)
            g.retime.connect(self._retime)
            g.toggle_done.connect(self._toggle_done)

        f, r = card()
        self.mini = MiniMonth(lambda d: len(self.filtered(d)), self.jy, self.jm, self.selected)
        self.mini.picked.connect(self._select)
        r.addWidget(self.mini)
        self.day_lb = label("", "H2")
        r.addWidget(self.day_lb)
        self.day_list = EmptyList("calendar", "برای این روز چیزی نیست", "با دکمه‌ی پایین یک تسک اضافه کن.")
        self.day_list.setItemDelegate(TaskRowDelegate(self.day_list))
        self.day_list.setFrameShape(QFrame.Shape.NoFrame)
        self.day_list.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.day_list.setMouseTracking(True)
        self.day_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.day_list.setWordWrap(True)
        self.day_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.day_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.day_list.itemChanged.connect(self._toggled)
        self.day_list.itemDoubleClicked.connect(lambda it: ctx.edit_task_id(it.data(UR)))
        r.addWidget(self.day_list, 1)
        r.addWidget(button("＋ تسک برای این روز", "Primary", lambda: ctx.new_task(jalali.date_to_due(self.selected))))
        f.setMinimumWidth(268)
        f.setMaximumWidth(320)
        root.addWidget(f, 1)
        self._tick = QTimer(self, interval=60_000)
        self._tick.timeout.connect(self._on_tick)
        for key, fn in (("T", self._today), ("M", lambda: self._go_view(0)), ("W", lambda: self._go_view(1)),
                        ("D", lambda: self._go_view(2)), ("A", lambda: self._go_view(3)), ("Y", lambda: self._go_view(4)),
                        ("PgUp", lambda: self._shift(-1)), ("PgDown", lambda: self._shift(1)),
                        ("N", lambda: ctx.new_task(jalali.date_to_due(self.selected))),
                        ("Ctrl+P", self._print_menu)):
            sc_ = QShortcut(QKeySequence(key), self)
            sc_.setContext(Qt.ShortcutContext.WindowShortcut)          # live while this page is the visible one; text fields keep their letters
            sc_.activated.connect(fn)

    def _on_tick(self) -> None:
        if self.view in (1, 2):
            (self.week, self.day)[self.view - 1].update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._tick.start()
        super().showEvent(e)
        QTimer.singleShot(60, self.one_accent)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._tick.stop()
        super().hideEvent(e)

    @property
    def v(self) -> dict:
        return self.ctx.store.vault

    def by_id(self, tid: str) -> dict | None:
        if self.v is None:
            return None
        if self._by_id is None:
            self._by_id = {t.get("id"): t for t in self.v.get("tasks", [])}
        return self._by_id.get(tid)

    def filtered(self, d: dt.date) -> list[dict]:
        st, cat = self.status.currentData(), self.cat.currentData()
        out = []
        if self.v is None:                                   # locked: nothing to show (a repaint can still arrive)
            return out
        if self._day_idx is None:
            self._day_idx = logic.build_day_index(self.v)
        for x in self._day_idx.get(d, ()):
            if st == "open" and x.get("done") or st == "done" and not x.get("done"):
                continue
            if cat != "all" and x.get("cat") != cat:
                continue
            out.append(x)
        return out

    # ------------------------------------------------------------ navigation
    def _go_view(self, i: int) -> None:
        if i != self.view:
            self.seg.set_index(i)
            self._set_view(i)

    def _set_view(self, i: int) -> None:
        self.view = i
        self.stack.setCurrentIndex(i)
        self.refresh()
        if i in (1, 2):
            self._scroll_to_hours()

    def _scroll_to_hours(self) -> None:
        """Open week/day at the working hours (one hour before 'now' when today is visible). The grid only gets its
        final height on its first paint, so the scroll is retried once the range exists."""
        sc = self.week_sc if self.view == 1 else self.day_sc
        grid = self.week if self.view == 1 else self.day
        hour = max(0, dt.datetime.now().hour - 1) if dt.date.today() in grid.dates() else 7

        def go() -> None:
            try:
                sc.verticalScrollBar().setValue(int(hour * HOUR_H))          # the pinned header covers the first rows
            except RuntimeError:
                pass
        for ms in (0, 60, 160):
            QTimer.singleShot(ms, go)

    def _shift(self, s: int) -> None:
        """Move by one period; the grid slides away and the new one glides in (unless motion is reduced)."""
        w = self.stack.currentWidget()
        old = w.grab() if anim.MOTION[0] and self.isVisible() and w.width() > 100 else None
        self._shift_now(s)
        if old is not None:
            flip.slide(self.stack, old, w.grab(), s)

    def _shift_now(self, s: int) -> None:
        if self.view in (0, 4):
            j = jalali.date_to_due(self.selected)
            jy, jm = j["jy"], j["jm"]
            if self.view == 0:
                jm += s
                if jm > 12:
                    jm, jy = 1, jy + 1
                if jm < 1:
                    jm, jy = 12, jy - 1
            else:
                jy += s
            jd = min(j["jd"], jalali.month_length(jy, jm))
            self.selected = dt.date(*jalali.to_gregorian(jy, jm, jd))
        else:
            self.selected += dt.timedelta(days={1: 7, 2: 1, 3: 30}[self.view] * s)
        self.refresh()

    def _today(self) -> None:
        self.selected = dt.date.today()
        self.refresh()
        if self.view in (1, 2):
            self._scroll_to_hours()

    def _select(self, d: dt.date) -> None:
        self.selected = d
        self.refresh()

    def _open_day(self, d: dt.date) -> None:
        self.selected = d
        self._go_view(2)

    def _year_day(self, d: dt.date) -> None:
        self._open_day(d)

    def _year_month(self, jy: int, jm: int) -> None:
        self.selected = dt.date(*jalali.to_gregorian(jy, jm, 1))
        self._go_view(0)

    # ------------------------------------------------------------------ edits
    def _move(self, tid: str, d: dt.date, src: dt.date | None = None) -> None:
        """``src`` is the day the block was grabbed on: a multi-day task shows a chip on every day, and dropping the
        chip of day 3 on day 3 must not move it. The whole task moves by (drop day - grab day)."""
        x = self.by_id(tid)
        old = logic.task_date(x) if x else None
        if not x or not old:
            return
        delta = d - (src or old)
        if not delta:
            return
        rec = self.ctx.snapshot([tid])
        x["due"] = jalali.date_to_due(old + delta)
        end = jalali.due_to_date(x.get("dueEnd"))
        if end:
            x["dueEnd"] = jalali.date_to_due(end + delta)
        self.ctx.changed("تسک جابه‌جا شد", undo=rec)

    def _retime(self, tid: str, d: dt.date, a, b, src: dt.date | None = None) -> None:
        """A drag on the day grid ended: new day and / or new hours (a = b = None means «all day»)."""
        x = self.by_id(tid)
        old = logic.task_date(x) if x else None
        if not x or old is None:
            return
        f, t = (hm(a), hm_end(b)) if a is not None else ("", "")
        delta = d - (src or old)
        if not delta and f == (x.get("timeFrom") or "") and t == (x.get("timeTo") or ""):
            return
        rec = self.ctx.snapshot([tid])
        if delta:
            x["due"] = jalali.date_to_due(old + delta)
            end = jalali.due_to_date(x.get("dueEnd"))
            if end:
                x["dueEnd"] = jalali.date_to_due(end + delta)
        x["timeFrom"], x["timeTo"] = f, t
        self.ctx.changed("زمان تسک عوض شد", undo=rec)

    def _toggle_done(self, tid: str) -> None:
        x = self.by_id(tid)
        if x:
            rec = self.ctx.snapshot([tid])
            logic.set_done(self.v, x, not x.get("done"))
            self.ctx.changed("تسک انجام شد" if x.get("done") else "تسک دوباره باز شد", undo=rec)

    def _toggled(self, it: QListWidgetItem) -> None:
        if self._busy:
            return
        x = self.by_id(it.data(UR))
        if x:
            logic.set_done(self.v, x, it.checkState() == Qt.CheckState.Checked)
            self.ctx.changed()

    # ------------------------------------------------------ quick create card
    def _defaults(self, title: str, a, b, end) -> dict:
        d = {"title": title}
        if a is not None:
            d.update(timeFrom=hm(a), timeTo=hm_end(b))
        cat = self.cat.currentData()
        if cat != "all":
            d["cat"] = cat                                     # drawn while filtered to a category: it belongs there
        return d

    def _open_quick(self, d: dt.date, a, b, end, anchor: QRect | None, on_close) -> None:
        if self._quick is not None:
            try:
                self._quick.close()
            except RuntimeError:
                pass
        pop = self._quick = QuickCreate(self, when_text(d, a, b, end))
        pop.saved.connect(lambda title: self._commit_new(title, d, a, b, end))
        pop.detail.connect(lambda title: self.ctx.new_task(jalali.date_to_due(d), {**self._defaults(title, a, b, end),
                                                                                    **({"dueEnd": jalali.date_to_due(end)} if end and end != d else {})}))
        pop.closed.connect(on_close)
        pop.closed.connect(lambda: setattr(self, "_quick", None))
        pop.popup_at(anchor or QRect(self.mapToGlobal(self.rect().center()), QSize(10, 10)))

    def _on_create_range(self, d: dt.date, a, b) -> None:
        grid = self.week if self.view == 1 else self.day
        self._open_quick(d, a, b, None, grid.pending_global_rect(), grid.clear_pending)

    def _on_create_days(self, d0: dt.date, d1: dt.date) -> None:
        r = self.month.cell_rect(d1)
        anchor = QRect(self.month.mapToGlobal(r.toRect().topLeft()), r.toRect().size()) if r is not None else None
        self._open_quick(d0, None, None, d1, anchor, self.month.clear_pending)

    def create_here(self, d: dt.date, minute: int | None = None) -> None:
        """«New task here» from a menu: the same card, placed at the pointer's cell."""
        a = minute
        b = None if minute is None else min(24 * 60, minute + 60)
        grid = self.week if self.view == 1 else self.day if self.view == 2 else None
        if grid is not None and d in grid.dates():
            grid._pending = {"kind": "create", "date": d, "a": a, "b": b}
            grid.update()
            self._open_quick(d, a, b, None, grid.pending_global_rect(), grid.clear_pending)
        elif self.view == 0 and self.month.cell_rect(d) is not None:
            r = self.month.cell_rect(d).toRect()
            self.month._pending = (d, d)
            self.month.update()
            self._open_quick(d, None, None, None, QRect(self.month.mapToGlobal(r.topLeft()), r.size()), self.month.clear_pending)
        else:
            self._open_quick(d, a, b, None, None, lambda: None)

    def unbind(self) -> None:
        """Vault locked: drop the open quick-create card and every cached reference to decrypted tasks."""
        q, self._quick = self._quick, None
        if q is not None:
            try:
                q.close()
            except RuntimeError:
                pass
        self._day_idx = None
        self._by_id = None

    def _commit_new(self, title: str, d: dt.date, a, b, end) -> None:
        if not self.ctx.store.is_unlocked:
            return
        kw = self._defaults("", a, b, end)
        kw.pop("title", None)
        kw["due"] = jalali.date_to_due(d)
        if end and end != d:
            kw["dueEnd"] = jalali.date_to_due(end)
        t = logic.new_task(title, **kw)
        rec = self.ctx.snapshot([t["id"]])                     # taken before: undo = «this id never existed»
        self.v["tasks"].append(t)
        self.ctx.changed("تسک ساخته شد: " + title, undo=rec)

    # ------------------------------------------------------------------ menus
    def task_menu(self, tid: str, gpos) -> None:
        x = self.by_id(tid)
        if not x:
            return
        ctx = self.ctx

        def trash() -> None:
            rec = ctx.snapshot([tid])
            logic.remove_task(ctx.store, x)
            ctx.changed("تسک به سطل زباله رفت", undo=rec)

        def duplicate() -> None:
            c = copy.deepcopy(x)
            c["id"], c["done"], c["doneAt"] = uid("t"), False, None
            c.pop("seriesId", None)
            rec = ctx.snapshot([c["id"]])
            self.v["tasks"].append(c)
            ctx.changed("یک کپی ساخته شد", undo=rec)

        m = pmenu(self, _pal(ctx.theme), [
            ("edit", "ویرایش…", lambda: ctx.edit_task_id(tid), False),
            ("check", "باز کردن دوباره" if x.get("done") else "انجام شد", lambda: self._toggle_done(tid), False),
            ("plus", "ساخت یک کپی", duplicate, False),
            None,
            ("trash", "انتقال به سطل زباله", trash, True)])
        m.exec(gpos)

    def day_menu(self, d: dt.date, gpos, minute: int | None = None) -> None:
        j = jalali.date_to_due(d)
        name = f"{fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]}"
        ents = []
        if minute is not None:
            ents.append(("plus", f"تسک جدید ساعت {fa(hm(minute))}", lambda: self.create_here(d, minute), False))
        ents.append(("plus", f"تسک تمام‌روز برای {name}", lambda: self.create_here(d, None), False))
        ents.append(("edit", "تسک جدید با جزئیات…", lambda: self.ctx.new_task(jalali.date_to_due(d)), False))
        if self.view != 2:
            ents += [None, ("calendar", f"باز کردن {name}", lambda: self._open_day(d), False)]
        pmenu(self, _pal(self.ctx.theme), ents).exec(gpos)

    # ------------------------------------------------------------------ printing
    PRINT_MODES = (("day", "چاپ روز"), ("week", "چاپ هفته"), ("month", "چاپ ماه"))

    def _print_menu(self) -> None:
        """«پرینت»: day / week / month around the selected date, each as a PDF file or on paper."""
        from PyQt6.QtWidgets import QMenu
        from .premium import style_menu
        pal = _pal(self.ctx.theme)
        m = pmenu(self, pal, [])
        for mode, text in self.PRINT_MODES:
            sub = style_menu(QMenu(text, m))
            sub.setIcon(icons.icon("print", pal["muted"], 16))
            sub.addAction(icons.icon("save", pal["muted"], 16), "ذخیره PDF…").triggered.connect(lambda _=False, k=mode: self.print_pdf(k))
            sub.addAction(icons.icon("print", pal["muted"], 16), "چاپ…").triggered.connect(lambda _=False, k=mode: self.print_paper(k))
            m.addMenu(sub)
        m.exec(self.print_btn.mapToGlobal(self.print_btn.rect().bottomLeft()))

    def _print_tasks(self, mode: str) -> list[dict]:
        """The tasks of the printed range that the page shows right now (the status and category filters apply)."""
        from . import calendar_print
        seen: dict[int, dict] = {}
        for d in calendar_print.range_dates(mode, self.selected):
            for x in self.filtered(d):
                seen.setdefault(id(x), x)
        return list(seen.values())

    def _print_render(self, target, mode: str) -> int:
        from PyQt6.QtWidgets import QApplication
        from . import calendar_print
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            return calendar_print.render_calendar_pdf(target, mode, self.selected, self._print_tasks(mode), PALETTES[self.ctx.theme])
        finally:
            QApplication.restoreOverrideCursor()

    def print_pdf(self, mode: str, path: str | None = None) -> str | None:
        """Save the printout as a PDF; returns the path (None if cancelled or it could not be written)."""
        from PyQt6.QtWidgets import QFileDialog
        from . import calendar_print
        if self.v is None:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "ذخیره PDF تقویم (شامل عنوان تسک‌ها)", calendar_print.default_name(mode, self.selected), "PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            n = self._print_render(path, mode)
        except OSError:
            n = 0
        if n:
            self.ctx.notify("PDF ذخیره شد. توجه: این خروجی عنوان تسک‌ها را دارد (برخلاف PDF گزارش‌ها)؛ با دیگران با احتیاط به اشتراک بگذار.", kind="success", title="پرینت")
            return path
        self.ctx.notify("PDF ذخیره نشد؛ مسیر را بررسی کن.", kind="alert", title="پرینت")
        return None

    def print_paper(self, mode: str, printer=None) -> bool:
        """Send the printout to a printer (the system dialog, unless a ready QPrinter is given)."""
        from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
        if self.v is None:
            return False
        if printer is None:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dlg = QPrintDialog(printer, self)
            dlg.setWindowTitle("چاپ تقویم (شامل عنوان تسک‌ها)")
            if dlg.exec() != QPrintDialog.DialogCode.Accepted:
                return False
        n = self._print_render(printer, mode)
        self.ctx.notify("برای چاپ فرستاده شد." if n else "چاپ انجام نشد؛ چاپگر را بررسی کن.", kind="success" if n else "alert", title="پرینت")
        return bool(n)

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self._busy = True
        self._day_idx = None            # vault may have changed: rebuild the per-day index lazily
        self._by_id = None
        j = jalali.date_to_due(self.selected)
        self.jy, self.jm = j["jy"], j["jm"]
        self.seg.theme = self.ctx.theme
        self.print_btn.setIcon(icons.icon("print", _pal(self.ctx.theme)["muted"], 16))
        self.seg.set_index(self.view)
        if self.view == 0:
            self.title_lb.setText(f"{jalali.MONTHS_FA[self.jm - 1]} {fa(self.jy)}")
        elif self.view == 1:
            a, b = week_start(self.selected), week_start(self.selected) + dt.timedelta(days=6)
            ja, jb = jalali.date_to_due(a), jalali.date_to_due(b)
            self.title_lb.setText(f"{fa(ja['jd'])} {jalali.MONTHS_FA[ja['jm'] - 1]} – {fa(jb['jd'])} {jalali.MONTHS_FA[jb['jm'] - 1]} {fa(jb['jy'])}")
        elif self.view == 4:
            self.title_lb.setText(f"سال {fa(self.jy)}")
        else:
            self.title_lb.setText(f"{jalali.WEEKDAYS_FA[jalali.weekday_index(self.selected)]} {fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} {fa(j['jy'])}")
        if self.view == 3:
            self._fill_agenda()
        elif self.view == 4:
            self.year.set_year(self.jy, self.selected)
        else:
            (self.month, self.week, self.day)[min(self.view, 2)].update()
        if (self.jy, self.jm) != self._mini_for or not self.mini.shows(self.selected):
            self._mini_for = (self.jy, self.jm)                 # the navigator follows the page - unless the person paged it
            self.mini.show_month(self.jy, self.jm)              # on their own and the picked day is still on its grid
        self.mini.set_selected(self.selected)
        self.day_lb.setText(f"{jalali.WEEKDAYS_FA[jalali.weekday_index(self.selected)]} {fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]}")
        self.day_list.clear()
        for x in self.filtered(self.selected):
            it = QListWidgetItem(x.get("title", ""))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if x.get("done") else Qt.CheckState.Unchecked)
            it.setData(UR, x["id"])
            meta = []
            if x.get("timeFrom"):
                meta.append(fa(x["timeFrom"]) + (f"–{fa(x['timeTo'])}" if x.get("timeTo") else ""))
            meta.append(logic.CAT_LABEL.get(x.get("cat"), ""))
            it.setData(UR + 1, "  ·  ".join(t for t in meta if t))
            it.setData(UR + 2, x.get("pr"))
            it.setData(UR + 6, color_hex(x.get("color")))
            self.day_list.addItem(it)
        self._busy = False

    def _fill_agenda(self) -> None:
        self.agenda.clear()
        for i in range(30):
            d = self.selected + dt.timedelta(days=i)
            ts = self.filtered(d)
            if not ts:
                continue
            j = jalali.date_to_due(d)
            h = QListWidgetItem(f"{jalali.WEEKDAYS_FA[jalali.weekday_index(d)]} {fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]}")
            h.setData(UR + 1, "hdr")
            h.setFlags(Qt.ItemFlag.NoItemFlags)
            self.agenda.addItem(h)
            for x in ts:
                it = QListWidgetItem(x.get("title", ""))
                it.setData(UR, x["id"])
                it.setData(UR + 2, task_color(x, _pal(self.ctx.theme)).name())
                if x.get("timeFrom"):
                    it.setData(UR + 3, fa(x["timeFrom"]) + (f"–{fa(x['timeTo'])}" if x.get("timeTo") else ""))
                it.setData(UR + 4, bool(x.get("done")))
                self.agenda.addItem(it)
