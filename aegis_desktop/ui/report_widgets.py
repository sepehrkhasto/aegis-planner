# SPDX-License-Identifier: GPL-3.0-or-later
"""Report widgets: the animated progress-ring card and the Jalali activity calendar (custom painted, palette-aware)."""
from __future__ import annotations

import datetime as dt
from typing import Callable

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from ..core import jalali
from ..core.jalali import fa
from .fx_widgets import _Anim, _fpal
from .premium import alpha, draw_num, mix
from .theme import AL_L, AL_R, rr

_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)


def _font(w: QWidget, delta: float = 0.0, bold: bool = False):
    f = w.font()
    f.setPointSizeF(max(7.0, f.pointSizeF() + delta))
    f.setBold(bold)
    return f


# =================================================================== ring ===
class ProgressRingCard(QWidget):
    """A gradient progress ring with a breakdown underneath. Click a row to focus the ring on that stage
    (click it again to go back to the overall value). stages: [(label, value 0-100, colour | None)]."""

    stage_clicked = pyqtSignal(int)
    ROW_H = 30
    RING = 148

    def __init__(self, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.stages: list[tuple[str, float, QColor | None]] = []
        self.overall = 0.0
        self.caption = ""
        self.empty_text = "داده‌ای در این بازه نیست"
        self._active: int | None = None
        self._hover = -1
        self._sig = None
        self._rects: list[QRectF] = []
        self._ring = _Anim(self, 0.0, 900, _OUT)
        self._bars = _Anim(self, 1.0, 700, _OUT)
        self.setMouseTracking(True)
        self.setMinimumHeight(self.RING + 60)

    # -- data
    def set_data(self, stages, overall: float, caption: str, theme: str, empty_text: str | None = None) -> None:
        self.theme = theme
        if empty_text:
            self.empty_text = empty_text
        stages = [(str(l), max(0.0, min(100.0, float(v))), c) for l, v, c in stages]
        sig = (tuple((l, round(v)) for l, v, _c in stages), round(overall), caption)
        changed = sig != self._sig
        self._sig = sig
        self.stages, self.overall, self.caption = stages, max(0.0, min(100.0, float(overall))), caption
        if self._active is not None and self._active >= len(stages):
            self._active = None
        self.setMinimumHeight(self.RING + 52 + max(1, len(stages)) * self.ROW_H)
        self.setAccessibleName(f"{caption} {fa(round(self.overall))}٪")
        if changed:
            self._ring.set(0.0 if not self._ring.value else self._ring.value)
            self._ring.to(self._target())
            self._bars.set(0.0)
            self._bars.to(1.0)
        else:
            self.update()

    def _target(self) -> float:
        return self.stages[self._active][1] if self._active is not None else self.overall

    # -- interaction
    def _hit(self, pos: QPointF) -> int:
        for i, r in enumerate(self._rects):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = self._hit(e.position())
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            i = self._hit(e.position())
            if i >= 0:
                self._active = None if self._active == i else i
                self._ring.to(self._target())
                self.stage_clicked.emit(i)
                self.update()

    # -- painting
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        d = min(self.RING, w - 40)
        ring = QRectF((w - d) / 2, 12, d, d).adjusted(8, 8, -8, -8)
        stroke = 9.0
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(alpha(pal["line"], 0.9), stroke))
        p.drawEllipse(ring)
        v = max(0.0, min(100.0, self._ring.value))
        if v > 0.3:
            g = QLinearGradient(ring.topLeft(), ring.topRight())
            g.setColorAt(0.0, QColor(pal["accent"]))
            g.setColorAt(1.0, QColor(pal["accent2"]))
            p.setPen(QPen(g, stroke, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, int(-v / 100 * 360 * 16))
        p.setPen(QColor(pal["text"]))
        big = _font(self, 9, True)
        p.setFont(big)
        draw_num(p, QRectF(ring.left(), ring.center().y() - 26, ring.width(), 40), Qt.AlignmentFlag.AlignCenter,
                 fa(round(v)) + "٪")
        p.setPen(QColor(pal["muted"]))
        p.setFont(_font(self, -2))
        cap = self.caption if self._active is None else self.stages[self._active][0]
        p.drawText(QRectF(ring.left() + 8, ring.center().y() + 14, ring.width() - 16, 18), Qt.AlignmentFlag.AlignCenter,
                   p.fontMetrics().elidedText(cap, Qt.TextElideMode.ElideRight, int(ring.width() - 16)))
        # ---- breakdown
        self._rects = []
        y = ring.bottom() + 8 + stroke / 2 + 10
        if not self.stages:
            p.setPen(QColor(pal["muted"]))
            p.setFont(_font(self, 0))
            p.drawText(QRectF(12, y, w - 24, self.ROW_H), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return
        from .charts import CHART
        rad = min(rr(8), 12)
        prog = self._bars.value
        f_lab, f_pct = _font(self, -1), _font(self, -1.5, True)
        for i, (lab, val, col) in enumerate(self.stages):
            row = QRectF(8, y, w - 16, self.ROW_H - 4)
            self._rects.append(row)
            if i == self._active or i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["soft"]) if i == self._active else alpha(pal["soft"], 0.55))
                p.drawRoundedRect(row, rad, rad)
            colr = QColor(col) if col is not None else QColor(CHART[i % len(CHART)] if CHART else pal["accent"])
            lab_w = min(112.0, row.width() * 0.38)
            lab_r = QRectF(row.right() - 8 - lab_w, row.top(), lab_w, row.height())
            p.setFont(f_lab)
            p.setPen(QColor(pal["text"]))
            p.drawText(lab_r, AL_R | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(lab, Qt.TextElideMode.ElideRight, int(lab_w)))
            pct_r = QRectF(row.left() + 8, row.top(), 38, row.height())
            p.setFont(f_pct)
            p.setPen(QColor(pal["muted"]))
            draw_num(p, pct_r, AL_L | Qt.AlignmentFlag.AlignVCenter, fa(round(val)) + "٪", 1.4)
            bar = QRectF(pct_r.right() + 6, row.center().y() - 3, lab_r.left() - pct_r.right() - 14, 6)
            if bar.width() > 8:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["line"], 0.9))
                p.drawRoundedRect(bar, 3, 3)
                fw = bar.width() * val / 100 * prog
                if fw > 0.5:
                    p.setBrush(colr)
                    p.drawRoundedRect(QRectF(bar.right() - max(fw, 6.0), bar.top(), max(fw, 6.0), bar.height()), 3, 3)   # fills from the right
            y += self.ROW_H


# ============================================================ activity cal ===
class ActivityCalendar(QWidget):
    """One Jalali month: days with finished tasks / ticked habits are filled (stronger = more activity),
    today has a ring. ``provider(since, until) -> {date: count}`` is asked for the visible month."""

    def __init__(self, provider: Callable[[dt.date, dt.date], dict], theme: str = "dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.provider = provider
        j = jalali.today_jalali()
        self.jy, self.jm = j["jy"], j["jm"]
        self._data: dict[dt.date, int] = {}
        self._cells: list[tuple[QRectF, dt.date]] = []
        self._nav: dict[str, QRectF] = {}
        self._hover_nav = ""
        self.setMouseTracking(True)
        self.setMinimumHeight(250)
        self.reload()

    def reload(self) -> None:
        first = dt.date(*jalali.to_gregorian(self.jy, self.jm, 1))
        last = dt.date(*jalali.to_gregorian(self.jy, self.jm, jalali.month_length(self.jy, self.jm)))
        self._data = self.provider(first, last)
        self.update()

    def set_theme(self, theme: str) -> None:
        self.theme = theme
        self.update()

    def _shift(self, step: int) -> None:
        m = self.jm - 1 + step
        self.jy, self.jm = self.jy + m // 12, m % 12 + 1
        self.reload()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pos = e.position()
        nav = next((k for k, r in self._nav.items() if r.contains(pos)), "")
        if nav != self._hover_nav:
            self._hover_nav = nav
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor if nav else Qt.CursorShape.ArrowCursor)
        tip = ""
        for r, d in self._cells:
            if r.contains(pos):
                n = self._data.get(d, 0)
                j = jalali.date_to_due(d)
                tip = f"{fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} — " + (f"{fa(n)} فعالیت" if n else "بدون فعالیت")
                break
        self.setToolTip(tip)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover_nav = ""
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position()
            if self._nav.get("prev") and self._nav["prev"].contains(pos):
                self._shift(-1)
            elif self._nav.get("next") and self._nav["next"].contains(pos):
                self._shift(1)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 6.0
        # ---- header: prev (right) / title / next (left)
        p.setPen(QColor(pal["text"]))
        p.setFont(_font(self, 1, True))
        p.drawText(QRectF(0, 0, w, 28), Qt.AlignmentFlag.AlignCenter, f"{jalali.MONTHS_FA[self.jm - 1]} {fa(self.jy)}")
        self._nav = {"prev": QRectF(w - pad - 28, 0, 28, 28), "next": QRectF(pad, 0, 28, 28)}
        for key, r in self._nav.items():
            hov = self._hover_nav == key
            if hov:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["soft"], 0.9))
                p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 7, 7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["text"] if hov else pal["muted"]), 1.8, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            c, s = r.center(), 4.0
            sign = 1 if key == "prev" else -1            # RTL: "previous" points to the right
            p.drawPolyline([QPointF(c.x() - sign * s / 2, c.y() - s), QPointF(c.x() + sign * s / 2, c.y()), QPointF(c.x() - sign * s / 2, c.y() + s)])
        # ---- weekday header
        cw = (w - 2 * pad) / 7
        top = 34.0
        p.setFont(_font(self, -2))
        p.setPen(QColor(pal["muted"]))
        for i, name in enumerate(jalali.WEEKDAYS_SHORT):
            p.drawText(QRectF(w - pad - (i + 1) * cw, top, cw, 18), Qt.AlignmentFlag.AlignCenter, name)
        # ---- day grid
        first = dt.date(*jalali.to_gregorian(self.jy, self.jm, 1))
        lead = jalali.weekday_index(first)
        n_days = jalali.month_length(self.jy, self.jm)
        rows = (lead + n_days + 6) // 7
        foot = 26.0
        rh = max(20.0, min(cw, (h - top - 22 - foot) / rows))
        today = dt.date.today()
        self._cells = []
        f_day = _font(self, -1.5, True)
        active_days = total = 0
        peak = max(self._data.values(), default=1)
        for dn in range(1, n_days + 1):
            idx = lead + dn - 1
            col, row = idx % 7, idx // 7
            cell = QRectF(w - pad - (col + 1) * cw, top + 22 + row * rh, cw, rh)
            d = first + dt.timedelta(days=dn - 1)
            self._cells.append((cell, d))
            n = self._data.get(d, 0)
            dia = min(cw, rh) - 5
            circ = QRectF(cell.center().x() - dia / 2, cell.center().y() - dia / 2, dia, dia)
            txt = QColor(pal["muted"])
            if n:
                active_days += 1
                total += n
                strength = 0.38 + 0.62 * min(1.0, n / max(3, peak))
                fill = mix(QColor(pal["bg"]), QColor(pal["ok"]), strength)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawEllipse(circ)
                txt = QColor("#ffffff") if fill.lightness() < 150 else QColor("#101114")
            if d == today:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(pal["warn"]), 2))
                p.drawEllipse(circ.adjusted(-1, -1, 1, 1))
                if not n:
                    txt = QColor(pal["warn"])
            elif d > today and not n:
                txt = alpha(pal["muted"], 0.55)
            p.setFont(f_day)
            p.setPen(txt)
            draw_num(p, cell, Qt.AlignmentFlag.AlignCenter, fa(dn), 1.5)
        # ---- footer
        p.setFont(_font(self, -1.5))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(pad, h - foot, w - 2 * pad, foot), Qt.AlignmentFlag.AlignCenter,
                   f"{fa(active_days)} روز فعال  ·  {fa(total)} فعالیت")


# ============================================================ spark table ===
def paint_spark(p: QPainter, rect: QRectF, kind: str, values: list[float], color: QColor, pal: dict, k: float,
                neg: QColor | None = None, slices: list[QColor] | None = None) -> None:
    """Draw one inline chart into ``rect``. kind: area | line | bars | pie. ``k`` (0..1) reveals it from the start
    edge (right, in RTL). Oldest value sits on the right, like the big charts."""
    if not values:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    n = len(values)
    if kind == "pie":
        tot = float(sum(max(0.0, v) for v in values)) or 1.0
        d = min(rect.width(), rect.height())
        box = QRectF(rect.center().x() - d / 2, rect.center().y() - d / 2, d, d).adjusted(1, 1, -1, -1)
        ang = 90.0
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(values):
            span = 360.0 * max(0.0, v) / tot * k
            if span <= 0:
                continue
            p.setBrush(slices[i % len(slices)] if slices else color)
            p.drawPie(box, int(-ang * 16), int(-span * 16))
            ang += span
        p.restore()
        return
    lo, hi = min(0.0, min(values)), max(values)
    if kind == "bars":
        hi = max(hi, 0.0)                                        # all-negative bars still hang from a zero line inside the box
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad = 2.0
    inner = rect.adjusted(pad, pad, -pad, -pad)

    def xy(i: int, v: float) -> QPointF:
        x = inner.right() - inner.width() * (i / max(1, n - 1))
        return QPointF(x, inner.bottom() - inner.height() * (v - lo) / (hi - lo))

    p.setClipRect(QRectF(inner.right() - (inner.width() + 2 * pad) * k, rect.top(), (inner.width() + 2 * pad) * k + pad, rect.height()))
    if kind == "bars":
        slot = inner.width() / n
        bw = max(1.5, min(9.0, slot * 0.62))
        zero_y = inner.bottom() - inner.height() * (0 - lo) / (hi - lo)
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(values):
            cx = inner.right() - slot * (i + 0.5)
            y = xy(i, v).y()
            top, bot = (y, zero_y) if v >= 0 else (zero_y, y)
            if abs(bot - top) < 1.0:
                bot = top + 1.0
            p.setBrush(neg if (v < 0 and neg is not None) else color)
            p.drawRoundedRect(QRectF(cx - bw / 2, top, bw, bot - top), min(2.0, bw / 2), min(2.0, bw / 2))
    else:
        pts = [xy(i, v) for i, v in enumerate(values)]
        path = QPainterPath(pts[0])
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            dx = (b.x() - a.x()) / 2.4
            path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        if kind == "area":
            fill = QPainterPath(path)
            fill.lineTo(pts[-1].x(), inner.bottom())
            fill.lineTo(pts[0].x(), inner.bottom())
            fill.closeSubpath()
            g = QLinearGradient(0, inner.top(), 0, inner.bottom())
            g.setColorAt(0, alpha(color, 0.55))
            g.setColorAt(1, alpha(color, 0.06))
            p.fillPath(fill, g)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 1.8, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        if k >= 1.0:
            p.setPen(QPen(QColor(pal["panel"]), 1.5))
            p.setBrush(color)
            p.drawEllipse(pts[0], 2.6, 2.6)               # the latest value
    p.restore()


class SparkTable(QWidget):
    """Compact 'trends at a glance' table: label, an inline chart (area / diverging bars / line / bars / pie) and the
    period's total. rows: dict(label, kind, values, total_text, color_key, neg?, slices?, names?)."""

    ROW_H = 50
    HEAD_H = 32

    def __init__(self, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.rows: list[dict] = []
        self.heads = ("مقیاس", "روند", "جمع دوره")
        self._reveal = _Anim(self, 0.0, 950, _OUT)
        self._hover = -1
        self._hx = -1.0
        self.setMouseTracking(True)
        self.setMinimumHeight(self.HEAD_H + self.ROW_H)

    def set_data(self, rows: list[dict], theme: str) -> None:
        self.theme = theme
        self.rows = rows
        self.setMinimumHeight(self.HEAD_H + self.ROW_H * max(1, len(rows)) + 4)
        self._reveal.set(0.0)
        self._reveal.to(1.0)

    # geometry ---------------------------------------------------------------
    def _cols(self):
        w = float(self.width())
        label = QRectF(w - 12 - min(150.0, w * 0.36), 0, min(150.0, w * 0.36), 1)
        total = QRectF(12, 0, min(80.0, w * 0.2), 1)
        spark = QRectF(total.right() + 10, 0, label.left() - total.right() - 20, 1)
        return label, spark, total

    def _row_rect(self, i: int) -> QRectF:
        return QRectF(0, self.HEAD_H + i * self.ROW_H, self.width(), self.ROW_H)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = int((e.position().y() - self.HEAD_H) // self.ROW_H)
        i = i if 0 <= i < len(self.rows) else -1
        self._hx = e.position().x()
        if i != self._hover:
            self._hover = i
            self.update()
        tip = ""
        if i >= 0:
            _lab, spark, _tot = self._cols()
            r = self.rows[i]
            vals, names = r.get("values", []), r.get("names") or []
            if spark.left() <= self._hx <= spark.right() and vals:
                if r["kind"] == "pie":
                    tip = "  ·  ".join(f"{nm}: {fa(int(v))}" for nm, v in zip(names, vals))
                else:
                    j = int(round((spark.right() - self._hx) / max(1.0, spark.width()) * (len(vals) - 1)))
                    j = max(0, min(len(vals) - 1, j))
                    nm = names[j] if j < len(names) else fa(j + 1)
                    tip = f"{nm}: {fa(int(vals[j]))}"
        self.setToolTip(tip)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lab, spark, tot = self._cols()
        p.setFont(_font(self, -1.5, True))
        p.setPen(QColor(pal["muted"]))
        for txt, r, al in ((self.heads[0], lab, AL_R), (self.heads[1], spark, Qt.AlignmentFlag.AlignCenter), (self.heads[2], tot, AL_L)):
            p.drawText(QRectF(r.left(), 0, r.width(), self.HEAD_H), al | Qt.AlignmentFlag.AlignVCenter, txt)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawLine(QPointF(0, self.HEAD_H - 0.5), QPointF(self.width(), self.HEAD_H - 0.5))
        from .charts import CHART
        for i, r in enumerate(self.rows):
            row = self._row_rect(i)
            if i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["soft"], 0.45))
                p.drawRect(row.adjusted(0, 0, 0, -1))
            if i:
                p.setPen(QPen(alpha(pal["line"], 0.7), 1))
                p.drawLine(QPointF(0, row.top() + 0.5), QPointF(self.width(), row.top() + 0.5))
            col = QColor(pal.get(r.get("color", "accent"), pal["accent"]))
            p.setFont(_font(self, -0.5))
            p.setPen(QColor(pal["text"]))
            p.drawText(QRectF(lab.left(), row.top(), lab.width(), row.height()), AL_R | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(r["label"], Qt.TextElideMode.ElideRight, int(lab.width())))
            p.setFont(_font(self, 0.5, True))
            p.setPen(QColor(pal["text"]))
            draw_num(p, QRectF(tot.left(), row.top(), tot.width(), row.height()), AL_L | Qt.AlignmentFlag.AlignVCenter,
                     r.get("total_text", ""), 1.5)
            box = QRectF(spark.left(), row.top() + 8, spark.width(), row.height() - 16)
            if r["kind"] == "pie":
                box = QRectF(spark.center().x() - 17, row.top() + 8, 34, row.height() - 16)
            paint_spark(p, box, r["kind"], r.get("values", []), col, pal, self._reveal.value,
                        neg=QColor(pal["danger"]) if r.get("neg") else None,
                        slices=[QColor(c) for c in (r.get("slices") or CHART)])
