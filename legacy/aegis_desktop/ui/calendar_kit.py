# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar building blocks: time maths, the overlap layout, the quick-create popover and the mini month.

Everything here is independent of the page so it can be tested alone:

* ``mins`` / ``hm`` / ``snap`` / ``span_of`` - «HH:MM» <-> minutes, 15-minute snapping, and the (start, end) a task occupies
  on a day grid (bad or out-of-range times simply mean «no time»).
* ``layout_events`` - Google-style side-by-side layout: events that overlap share the width of their cluster, everything else
  keeps the full column.
* ``QuickCreate`` - the small glass card that appears where a drag ended: a title, when, «Enter to save».
* ``MiniMonth`` - a compact Jalali month (dots for busy days, the shown week banded, wheel to change month) used as the
  navigator beside the calendar and, one per month, in the year view.
"""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QEasingCurve, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from . import anim
from ..core import jalali
from ..core.jalali import fa
from .combo_popup import paint_glass
from .fx_widgets import _fpal, _mix
from .premium import alpha
from .theme import rr
from .widgets import button

STEP = 15                      # minutes: what a drag snaps to
MIN_SPAN = 15                  # the shortest event a drag can make


# ------------------------------------------------------------------------------------------------ time maths ---
def mins(s) -> int | None:
    """«HH:MM» -> minutes since midnight; None for anything that is not a real clock time."""
    try:
        h, m = str(s or "").split(":")
        h, m = int(h), int(m)
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def hm(m: int) -> str:
    m = max(0, min(24 * 60, int(m)))
    return f"{m // 60:02d}:{m % 60:02d}"


def hm_end(m: int) -> str:
    """The clock text stored for the end of a block: a block that runs to the bottom of the day ends at 23:59,
    because «24:00» is not a time the rest of the app (or an ICS file) understands."""
    return hm(min(int(m), 24 * 60 - 1))


def snap(m: float, step: int = STEP) -> int:
    return int(round(m / step) * step)


def span_of(t: dict) -> tuple[int, int] | None:
    """(start, end) in minutes on a day grid, or None when the task has no usable start time.
    A missing / earlier end (or an overnight «23:00 -> 01:00») gives one hour, and the end never passes midnight."""
    a = mins(t.get("timeFrom"))
    if a is None:
        return None
    b = mins(t.get("timeTo"))
    if b is None or b <= a:
        b = a + 60
    return a, max(min(b, 24 * 60), min(a + 30, 24 * 60))


def range_text(a: int, b: int) -> str:
    return f"{fa(hm(a))} – {fa(hm(b))}"


def layout_events(events: list[tuple[int, int, dict]]) -> list[tuple[int, int, dict, int, int]]:
    """[(start, end, task)] -> [(start, end, task, lane, lanes)]: ``lanes`` is how many columns the event's overlap cluster
    needs, so a lone event is full width and three that overlap each get a third."""
    out: list[tuple[int, int, dict, int, int]] = []
    cluster: list[tuple[int, int, dict, int]] = []
    ends: list[int] = []
    horizon = -1

    def flush() -> None:
        n = max(1, len(ends))
        out.extend((a, b, t, li, n) for a, b, t, li in cluster)
        cluster.clear()
        ends.clear()

    for a, b, t in sorted(events, key=lambda z: (z[0], -z[1])):
        if a >= horizon and cluster:
            flush()
        for li, end in enumerate(ends):
            if end <= a:
                ends[li] = b
                break
        else:
            ends.append(b)
            li = len(ends) - 1
        cluster.append((a, b, t, li))
        horizon = max(horizon, b) if cluster[:-1] else b
    flush()
    return out


def when_text(d: dt.date, a: int | None = None, b: int | None = None, end: dt.date | None = None) -> str:
    """«چهارشنبه ۸ مهر · ۱۰:۳۰ – ۱۱:۳۰» (or a day range)."""
    j = jalali.date_to_due(d)
    s = f"{jalali.WEEKDAYS_FA[jalali.weekday_index(d)]} {fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]}"
    if end is not None and end != d:
        je = jalali.date_to_due(end)
        s = f"{fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} تا {fa(je['jd'])} {jalali.MONTHS_FA[je['jm'] - 1]}"
    if a is not None and b is not None:
        s += "  —  " + range_text(a, b)
    return s


# ------------------------------------------------------------------------------------------- quick create ---
class _Cross(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._h = False
        self.setToolTip("بستن  Esc")

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._h:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(pal["text"], 0.09))
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QPen(QColor(pal["text"] if self._h else pal["muted"]), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = QPointF(self.width() / 2, self.height() / 2)
        p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))


class QuickCreate(QWidget):
    """A small floating card placed where a drag ended: type a title, Enter saves, «جزئیات…» opens the full form."""
    saved = pyqtSignal(str)
    detail = pyqtSignal(str)
    closed = pyqtSignal()
    SH, W, H = 22, 352, 178

    def __init__(self, host: QWidget, when: str):
        super().__init__(host.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._pal = _fpal(host)
        self._done = False
        self.k = 1.0 if not anim.MOTION[0] else 0.0
        self.resize(self.W + 2 * self.SH, self.H + 2 * self.SH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self.SH + 18, self.SH + 14, self.SH + 14, self.SH + 14)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.when = QLabel(when)
        self.when.setObjectName("Muted")
        top.addWidget(self.when, 1)
        x = _Cross()
        x.clicked.connect(self.close)
        top.addWidget(x)
        lay.addLayout(top)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("عنوان تسک…")
        self.edit.setMinimumHeight(40)
        self.edit.returnPressed.connect(self._save)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.b_save = button("ذخیره", "Primary", self._save)
        self.b_more = button("جزئیات بیشتر…", "Link", self._more)
        row.addWidget(self.b_save)
        row.addWidget(self.b_more)
        row.addStretch(1)
        hint = QLabel("Enter ذخیره  ·  Esc لغو")
        hint.setObjectName("Muted")
        row.addWidget(hint)
        lay.addLayout(row)
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(self._tick)

    # ---- placement
    def popup_at(self, anchor: QRect) -> None:
        """Beside ``anchor`` (global rect): on the side with more room, its top near the anchor's, always on screen."""
        scr = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        av = scr.availableGeometry()
        w, h = self.W, self.H
        left_room = anchor.left() - av.left()
        x = anchor.left() - w - 8 if left_room >= w + 16 else anchor.right() + 8
        if x + w > av.right() - 8:
            x = max(av.left() + 8, min(anchor.left() + 12, av.right() - w - 8))
        y = max(av.top() + 8, min(anchor.top() - 12, av.bottom() - h - 8))
        self.move(x - self.SH, y - self.SH)
        self.show()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.edit.setFocus()
        if self.k < 1.0:
            self._an.setStartValue(0.0)
            self._an.setEndValue(1.0)
            self._an.start()

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    # ---- actions
    def _title(self) -> str:
        return " ".join(self.edit.text().split())

    def _save(self) -> None:
        t = self._title()
        if not t:
            self.edit.setPlaceholderText("یک عنوان بنویس…")
            self.edit.setFocus()
            return
        self._done = True
        self.saved.emit(t)
        self.close()

    def _more(self) -> None:
        self._done = True
        self.detail.emit(self._title())
        self.close()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not QRect(self.SH, self.SH, self.W, self.H).contains(e.position().toPoint()):
            self.close()                                                    # a click on the shadow is a click outside
        else:
            super().mousePressEvent(e)

    def closeEvent(self, e) -> None:  # noqa: N802
        self._an.stop()
        super().closeEvent(e)
        self.closed.emit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.k)
        p.translate(0, (1.0 - self.k) * -6)
        paint_glass(p, QRectF(self.SH, self.SH, self.W, self.H), self._pal, min(rr(14), 16))


# ---------------------------------------------------------------------------------------------- mini month ---
class MiniMonth(QWidget):
    """A compact Jalali month. Days that hold tasks get a dot, today a ring, the picked day a filled disc and the picked
    week a soft band. ``compact`` (year view) drops the arrows: the title opens that month instead."""
    picked = pyqtSignal(object)                 # date
    moved = pyqtSignal(int, int)                # jy, jm the navigator now shows
    title_clicked = pyqtSignal(int, int)        # compact: jy, jm

    HEAD, WEEK, ROW = 32, 20, 27

    def __init__(self, count, jy: int, jm: int, selected: dt.date | None = None, compact: bool = False, parent=None):
        """``count(date) -> int`` says how many tasks a day holds (0 = no dot)."""
        super().__init__(parent)
        self.count, self.jy, self.jm, self.selected, self.compact = count, jy, jm, selected or dt.date.today(), compact
        self._hover: dt.date | None = None
        self._cells: list[tuple[QRectF, dt.date]] = []
        self._arrows: dict[str, QRectF] = {}
        self._title_r = QRectF()
        self.setMouseTracking(True)
        self.setFixedHeight(self.height_for())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("مینی‌تقویم")

    @classmethod
    def height_for(cls) -> int:
        return cls.HEAD + cls.WEEK + 6 * cls.ROW + 4

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(240, self.height_for())

    def show_month(self, jy: int, jm: int) -> None:
        if (jy, jm) != (self.jy, self.jm):
            self.jy, self.jm = jy, jm
            self.moved.emit(jy, jm)
            self.update()

    def set_selected(self, d: dt.date) -> None:
        self.selected = d
        self.update()

    def shows(self, d: dt.date) -> bool:
        """Is ``d`` one of the 42 days on the grid right now (its own month plus the grey edges)?"""
        first = dt.date(*jalali.to_gregorian(self.jy, self.jm, 1))
        start = first - dt.timedelta(days=jalali.weekday_index(first))
        return 0 <= (d - start).days < 42

    def _step(self, s: int) -> None:
        jm, jy = self.jm + s, self.jy
        if jm > 12:
            jm, jy = 1, jy + 1
        if jm < 1:
            jm, jy = 12, jy - 1
        self.show_month(jy, jm)

    # ---- input
    def _date_at(self, pos) -> dt.date | None:
        for r, d in self._cells:
            if r.contains(pos):
                return d
        return None

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        d = self._date_at(e.position())
        if d != self._hover:
            self._hover = d
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        for k, r in self._arrows.items():
            if r.contains(pos):
                self._step(-1 if k == "prev" else 1)
                return
        if self.compact and self._title_r.contains(pos):
            self.title_clicked.emit(self.jy, self.jm)
            return
        d = self._date_at(pos)
        if d is not None:
            self.picked.emit(d)

    def wheelEvent(self, e) -> None:  # noqa: N802
        if self.compact:
            e.ignore()
            return
        self._step(-1 if e.angleDelta().y() > 0 else 1)

    # ---- paint
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W = float(self.width())
        rtl = self.isRightToLeft()
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        title = f"{jalali.MONTHS_FA[self.jm - 1]} {fa(self.jy)}"
        tw = QFontMetrics(f).horizontalAdvance(title)
        self._title_r = QRectF(W - 4 - tw if rtl else 4, 0, tw, self.HEAD)
        p.setPen(QColor(pal["text"]))
        p.drawText(self._title_r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignLeft, title)
        self._arrows = {}
        if not self.compact:
            spots = (("next", 14.0), ("prev", 42.0)) if rtl else (("prev", W - 42.0), ("next", W - 14.0))
            for k, cx in spots:
                r = QRectF(cx - 13, 3, 26, self.HEAD - 6)
                self._arrows[k] = r
                p.setPen(QPen(QColor(pal["muted"]), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                c = r.center()
                tip = 1 if (k == "prev") == rtl else -1                     # RTL: «previous» points right, «next» points left
                p.drawPolyline([QPointF(c.x() - 2.5 * tip, c.y() - 4.5), QPointF(c.x() + 2.5 * tip, c.y()),
                                QPointF(c.x() - 2.5 * tip, c.y() + 4.5)])
        cw = W / 7.0
        wf = QFont(self.font())
        wf.setPointSizeF(max(7.5, wf.pointSizeF() - 1.5))
        p.setFont(wf)
        for c, s in enumerate(jalali.WEEKDAYS_SHORT):
            p.setPen(QColor(pal["danger"]) if c == 6 else QColor(pal["muted"]))
            x = W - (c + 1) * cw if rtl else c * cw
            p.drawText(QRectF(x, self.HEAD, cw, self.WEEK), Qt.AlignmentFlag.AlignCenter, s)
        first = dt.date(*jalali.to_gregorian(self.jy, self.jm, 1))
        start = first - dt.timedelta(days=jalali.weekday_index(first))
        today = dt.date.today()
        wk0 = self.selected - dt.timedelta(days=jalali.weekday_index(self.selected))
        self._cells = []
        f2 = QFont(self.font())
        f2.setPointSizeF(max(8.0, f2.pointSizeF() - 0.5))
        top0 = self.HEAD + self.WEEK
        if not self.compact:                                                    # the picked week as one soft band
            row = (wk0 - start).days // 7
            if 0 <= row < 6:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["text"], 0.05))
                p.drawRoundedRect(QRectF(2, top0 + row * self.ROW + 1.5, W - 4, self.ROW - 3), 9, 9)
        for i in range(42):
            r_, c = divmod(i, 7)
            d = start + dt.timedelta(days=i)
            x = W - (c + 1) * cw if rtl else c * cw
            cell = QRectF(x, top0 + r_ * self.ROW, cw, self.ROW)
            self._cells.append((cell, d))
            j = jalali.date_to_due(d)
            inm = j["jm"] == self.jm
            if not inm and self.compact:
                continue                                                        # year view: only the month's own days
            disc = QRectF(0, 0, 22, 22)
            disc.moveCenter(QPointF(cell.center().x(), cell.center().y() - 1))
            is_sel = d == self.selected
            if d == today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent"]))
                p.drawEllipse(disc)
                ink = QColor(pal["ink"])
            elif is_sel:
                p.setPen(QPen(QColor(pal["accent2"]), 1.4))
                p.setBrush(alpha(pal["accent2"], 0.14))
                p.drawEllipse(disc)
                ink = QColor(pal["text"])
            elif d == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["text"], 0.08))
                p.drawEllipse(disc)
                ink = QColor(pal["text"])
            else:
                ink = QColor(pal["text"]) if inm else _mix(QColor(pal["muted"]), QColor(pal["panel"]), 0.35)
                if inm and jalali.weekday_index(d) == 6:
                    ink = QColor(pal["danger"])
            p.setFont(f2)
            p.setPen(ink)
            p.drawText(disc, Qt.AlignmentFlag.AlignCenter, fa(j["jd"]))
            n = self.count(d) if inm else 0
            if n:                                                               # a dot per busy day (up to three for busier ones)
                dots = 1 if n < 3 else 2 if n < 6 else 3
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(ink.red(), ink.green(), ink.blue(), 200) if d == today else QColor(pal["accent2"]))
                for k in range(dots):
                    p.drawEllipse(QPointF(cell.center().x() + (k - (dots - 1) / 2) * 5, cell.bottom() - 2.5), 1.5, 1.5)
