# SPDX-License-Identifier: GPL-3.0-or-later
"""Custom-painted analytics charts (ideas from the shadcn/recharts patterns): glow area, grouped bars,
donut (gradient / hatched slices + centre total), radial bars, radar. Each animates once on show/data change
and draws a hover tooltip. No timers run while idle."""
from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen)
from PyQt6.QtWidgets import QWidget

from ..core.jalali import fa
from .theme import AL_L, AL_R
from .theme import rr as _rad
from .theme import PALETTES

CHART = ["#6a7c9f", "#9fadc7", "#61667d", "#799db1", "#4a5d80", "#99b6b2"]   # Falcon monochrome blue-gray


def _motion() -> bool:
    from .anim import MOTION
    return bool(MOTION[0])


class ChartBase(QWidget):
    def _hover_in(self, n: int) -> None:
        """New data can be shorter than the point the mouse was on: forget a hover that no longer exists."""
        if self._hover is not None and not (0 <= self._hover < n):
            self._hover = None

    def __init__(self, theme: str = "dark"):
        super().__init__()
        self.theme = theme
        self.p = 1.0
        self._hover = None
        self.setMouseTracking(True)
        self.setMinimumHeight(180)
        self._a = QVariantAnimation(self)
        self._a.setDuration(900)
        self._a.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self._a.valueChanged.connect(self._tick)
        self._tt = QVariantAnimation(self)                  # tooltip fade-in
        self._tt.setDuration(140)
        self._tt.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self._tt.valueChanged.connect(self._tt_tick)
        self._tt_p, self._tt_key = 1.0, None

    def _tt_tick(self, v) -> None:
        self._tt_p = float(v)
        self.update()

    def _tick(self, v) -> None:
        self.p = float(v)
        self.update()

    def animate(self) -> None:
        self._a.stop()
        self._a.setStartValue(0.0)
        self._a.setEndValue(1.0)
        self._a.start()

    @property
    def pal(self) -> dict:
        return PALETTES[self.theme]

    def set_theme(self, t: str) -> None:
        self.theme = t
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self._tt_key = None
        self._tt.stop()
        self.update()

    def _tooltip(self, p: QPainter, anchor: QPointF, title: str, rows: list[tuple[QColor, str, str]]) -> None:
        """Glass tooltip: translucent panel, a soft sheen on its top edge, a hairline border, a short fade-in whenever the
        hovered item changes."""
        key = (title, tuple(r[1:] for r in rows))
        if key != self._tt_key:
            self._tt_key = key
            self._tt.stop()
            if _motion():
                self._tt.setStartValue(0.0)
                self._tt.setEndValue(1.0)
                self._tt.start()
            else:
                self._tt_p = 1.0
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        p.setFont(f)
        fm = p.fontMetrics()
        w = max([fm.horizontalAdvance(title)] + [fm.horizontalAdvance(a) + fm.horizontalAdvance(b) + 44 for _c, a, b in rows]) + 24
        h = 26 + 20 * len(rows) + 6
        x = min(max(6, anchor.x() - w / 2), self.width() - w - 6)
        y = max(6, anchor.y() - h - 12)
        k = self._tt_p
        p.save()
        p.setOpacity(k)
        y += (1.0 - k) * 5                                     # rises into place
        r = QRectF(x, y, w, h)
        rad = min(_rad(9), 12)
        for i, al in ((3, 0.05), (2, 0.07), (1, 0.09)):        # ambient shadow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(255 * al)))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), rad + i, rad + i)
        base = QColor(self.pal["panel2"])
        base.setAlphaF(0.88)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(r, rad, rad)
        sheen = QLinearGradient(0, r.top(), 0, r.bottom())
        sheen.setColorAt(0, QColor(255, 255, 255, 22))
        sheen.setColorAt(0.35, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(self.pal["line"]), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        p.setPen(QColor(self.pal["text"]))
        p.drawText(QRectF(x, y + 4, w, 20), Qt.AlignmentFlag.AlignCenter, title)
        p.setPen(QPen(QColor(self.pal["line"]), 1))
        p.drawLine(QPointF(x + 8, y + 26), QPointF(x + w - 8, y + 26))
        yy = y + 30
        for c, a, b in rows:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x + w - 20, yy + 5, 9, 9), 2, 2)
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(x + 10, yy, w - 36, 20), AL_R | Qt.AlignmentFlag.AlignVCenter, a)
            bf = QFont(f)
            bf.setBold(True)
            p.setFont(bf)
            p.setPen(QColor(self.pal["text"]))
            p.drawText(QRectF(x + 10, yy, w - 36, 20), AL_L | Qt.AlignmentFlag.AlignVCenter, b)
            p.setFont(f)
            yy += 20
        p.restore()

    def _grid(self, p: QPainter, plot: QRectF, vmax: float, steps: int = 4) -> None:
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        for i in range(steps + 1):
            y = plot.bottom() - plot.height() * i / steps
            p.setPen(QPen(QColor(self.pal["line"]), 1, Qt.PenStyle.DashLine if i else Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(plot.right() + 4, y - 8, 30, 16), AL_L | Qt.AlignmentFlag.AlignVCenter,
                       fa(int(round(vmax * i / steps))))


def _nice_step(v: float, steps: int = 4) -> float:
    """Smallest 'round' integer step so that ``steps`` grid lines reach ``v`` (labels stay evenly spaced integers)."""
    for k in range(0, 9):
        for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8):
            s = m * 10 ** k
            if s == int(s) and s * steps >= v:
                return s
    return math.ceil(v / steps)


def _nice_max(v: float, steps: int = 4) -> float:
    """Top of the value axis: ``steps`` equal integer steps (0 3 6 9 12, never 0 2 5 8 10)."""
    return _nice_step(max(1.0, v), steps) * steps


# ------------------------------------------------------------------- area ---
class AreaChart(ChartBase):
    """Smooth glow area. data = [(label, value)]"""

    def __init__(self, theme="dark", color=None, name="انجام‌شده", color2=None, name2="ایجادشده"):
        super().__init__(theme)
        self.data: list[tuple[str, int]] = []
        self.data2: list[int] | None = None                 # optional second series (same length), drawn behind
        self._c1, self._c2 = color, color2                  # None = follow the theme's chart palette live
        self.name, self.name2 = name, name2

    @property
    def color(self) -> QColor:
        return QColor(self._c1 or CHART[0])

    @property
    def color2(self) -> QColor:
        return QColor(self._c2 or CHART[3])

    def set_data(self, data, theme=None, second=None) -> None:
        self.data = list(data)
        self.data2 = list(second) if second is not None and len(second) == len(self.data) else None
        if theme:
            self.theme = theme
        self.animate()

    def _pts(self, plot, vmax, values=None):
        vals = values if values is not None else [v for _l, v in self.data]
        n = len(vals)
        return [QPointF(plot.right() - plot.width() * (i / max(1, n - 1)),
                        plot.bottom() - plot.height() * (v / vmax) * self.p) for i, v in enumerate(vals)]

    @staticmethod
    def _smooth(pts) -> QPainterPath:
        path = QPainterPath(pts[0])
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            dx = (b.x() - a.x()) / 2.5
            path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        return path

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.data:
            return
        plot = self._plot()
        i = round((plot.right() - e.position().x()) / max(1, plot.width()) * (len(self.data) - 1))
        i = max(0, min(len(self.data) - 1, i))
        if i != self._hover:
            self._hover = i
            self.update()

    def _plot(self) -> QRectF:
        return QRectF(8, 14, self.width() - 46, self.height() - 40)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self._plot()
        if not self.data:
            return
        self._hover_in(len(self.data) if self.data2 is None else min(len(self.data), len(self.data2)))
        vmax = _nice_max(max([v for _l, v in self.data] + (self.data2 or [0])) or 1)
        self._grid(p, plot, vmax)
        pts = self._pts(plot, vmax)
        if self.data2 is not None:                          # the second series sits behind: soft dashed edge + wash
            pts2 = self._pts(plot, vmax, self.data2)
            path2 = self._smooth(pts2)
            f2 = QPainterPath(path2)
            f2.lineTo(pts2[-1].x(), plot.bottom())
            f2.lineTo(pts2[0].x(), plot.bottom())
            f2.closeSubpath()
            g2 = QLinearGradient(0, plot.top(), 0, plot.bottom())
            a1, a2 = QColor(self.color2), QColor(self.color2)
            a1.setAlphaF(0.24)
            a2.setAlphaF(0.0)
            g2.setColorAt(0, a1)
            g2.setColorAt(1, a2)
            p.fillPath(f2, QBrush(g2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self.color2, 1.6, Qt.PenStyle.DashLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path2)
        path = self._smooth(pts)
        p.save()
        p.setClipRect(plot.adjusted(-8, -12, 8, 1))                  # the glow never bleeds below the zero line
        fill = QPainterPath(path)
        fill.lineTo(pts[-1].x(), plot.bottom())
        fill.lineTo(pts[0].x(), plot.bottom())
        fill.closeSubpath()
        g = QLinearGradient(0, plot.top(), 0, plot.bottom())
        c1, c2 = QColor(self.color), QColor(self.color)
        c1.setAlphaF(0.38)
        c2.setAlphaF(0.0)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.fillPath(fill, QBrush(g))
        glow = QColor(self.color)
        glow.setAlphaF(0.22)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(glow, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setPen(QPen(self.color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.restore()
        # x labels (sparse)
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.setPen(QColor(self.pal["muted"]))
        step = max(1, len(self.data) // 6)
        for i in range(0, len(self.data), step):
            p.drawText(QRectF(pts[i].x() - 30, plot.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignCenter, self.data[i][0])
        show_dots = len(self.data) <= 16
        if self._hover is not None:                          # crosshair: a hairline that fades away from the point
            hp = pts[self._hover]
            cg = QLinearGradient(0, plot.top(), 0, plot.bottom())
            cl = QColor(self.color)
            cg.setColorAt(0, QColor(cl.red(), cl.green(), cl.blue(), 0))
            cg.setColorAt(max(0.0, min(1.0, (hp.y() - plot.top()) / max(1, plot.height()))), QColor(cl.red(), cl.green(), cl.blue(), 150))
            cg.setColorAt(1, QColor(cl.red(), cl.green(), cl.blue(), 0))
            p.setPen(QPen(QBrush(cg), 1))
            p.drawLine(QPointF(hp.x(), plot.top()), QPointF(hp.x(), plot.bottom()))
            hl = QColor(self.pal["line"])
            hl.setAlphaF(0.7)
            p.setPen(QPen(hl, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(plot.left(), hp.y()), QPointF(plot.right(), hp.y()))
        for i, pt in enumerate(pts):
            if show_dots or i == self._hover:
                if i == self._hover:
                    halo = QColor(self.color)
                    halo.setAlphaF(0.22)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(halo)
                    p.drawEllipse(pt, 11, 11)
                p.setPen(QPen(QColor(self.pal["panel"]), 2))
                p.setBrush(self.color)
                p.drawEllipse(pt, 6 if i == self._hover else 3.5, 6 if i == self._hover else 3.5)
        if self._hover is not None:
            pt = pts[self._hover]
            l, v = self.data[self._hover]
            rows = [(self.color, self.name, fa(v))]
            if self.data2 is not None:
                rows.append((self.color2, self.name2, fa(self.data2[self._hover])))
            self._tooltip(p, pt, l, rows)


# ------------------------------------------------------------ grouped bars ---
class GroupedBars(ChartBase):
    """data = [(label, a, b)]; series = [(name, color), (name, color)]"""

    def __init__(self, theme="dark", series=(("ایجادشده", CHART[3]), ("انجام‌شده", CHART[1]))):
        super().__init__(theme)
        self.series = [(n, QColor(c)) for n, c in series]
        self.data: list[tuple] = []

    def set_data(self, data, theme=None) -> None:
        self.data = list(data)
        if theme:
            self.theme = theme
        self.animate()

    def _plot(self) -> QRectF:
        return QRectF(8, 14, self.width() - 46, self.height() - 40)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.data:
            return
        plot = self._plot()
        gw = plot.width() / len(self.data)
        i = int((plot.right() - e.position().x()) // gw)
        i = i if 0 <= i < len(self.data) else None
        if i != self._hover:
            self._hover = i
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.data:
            return
        self._hover_in(len(self.data))
        plot = self._plot()
        vmax = _nice_max(max(max(r[1:]) for r in self.data) or 1)
        self._grid(p, plot, vmax)
        n = len(self.data)
        gw = plot.width() / n
        bw = min(22.0, gw * 0.32)
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        for i, row in enumerate(self.data):
            cx = plot.right() - gw * (i + 0.5)
            if i == self._hover:
                hv = QColor(self.pal["text"])
                hv.setAlphaF(0.05)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(hv)
                p.drawRoundedRect(QRectF(cx - gw / 2 + 2, plot.top(), gw - 4, plot.height()), _rad(6), _rad(6))
            for k in range(len(self.series)):
                val = row[1 + k]
                h = plot.height() * val / vmax * self.p
                x = cx + (0.05 if k else -1.05) * bw - (0 if k else 0)
                r = QRectF(x - (bw if k == 0 else 0) + (bw if k == 0 else 0) * 0, plot.bottom() - h, bw, h)
                r.moveLeft(cx - bw - 1 if k == 0 else cx + 1)
                path = QPainterPath()
                rr = min(5.0, bw / 2, max(0.0, h))
                path.addRoundedRect(r.adjusted(0, 0, 0, rr), rr, rr)
                p.setClipRect(QRectF(r.left() - 1, plot.top(), r.width() + 2, plot.height()))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self.series[k][1])
                p.drawPath(path)
                p.setClipping(False)
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(cx - gw / 2, plot.bottom() + 4, gw, 16), Qt.AlignmentFlag.AlignCenter, str(row[0]))
        if self._hover is not None:
            row = self.data[self._hover]
            cx = plot.right() - gw * (self._hover + 0.5)
            self._tooltip(p, QPointF(cx, plot.top() + 30), str(row[0]),
                          [(self.series[k][1], self.series[k][0], fa(row[1 + k])) for k in range(len(self.series))])


# ---------------------------------------------------------- horizontal bars ---
class HorizontalBars(ChartBase):
    """Two-series horizontal bars with rounded ends and a legend on top. data = [(label, a, b)]; the bars grow from the
    right edge (start side in RTL). Hover a row for both values."""

    def __init__(self, theme="dark", series=(("این دوره", CHART[0]), ("دوره‌ی قبل", CHART[3]))):
        super().__init__(theme)
        self.series = [(n, QColor(c)) for n, c in series]
        self.data: list[tuple] = []
        self.setMinimumHeight(240)

    def set_data(self, data, theme=None) -> None:
        self.data = list(data)
        if theme:
            self.theme = theme
        self.animate()

    def _geo(self):
        top, bottom = 34.0, 22.0
        label_w = 64.0
        plot = QRectF(46.0, top, self.width() - 46.0 - label_w - 8.0, self.height() - top - bottom)
        return plot, label_w

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.data:
            return
        plot, _lw = self._geo()
        rh = plot.height() / len(self.data)
        i = int((e.position().y() - plot.top()) // rh)
        i = i if 0 <= i < len(self.data) else None
        if i != self._hover:
            self._hover = i
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.data:
            return
        self._hover_in(len(self.data))
        plot, label_w = self._geo()
        vmax = _nice_max(max(max(r[1:]) for r in self.data) or 1)
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        # legend (top, start side) with circular markers
        x = self.width() - 8.0
        for name, col in self.series:
            w = p.fontMetrics().horizontalAdvance(name)
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(x - w - 2, 4, w + 2, 18), AL_R | Qt.AlignmentFlag.AlignVCenter, name)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(x - w - 12, 13), 4.5, 4.5)
            x -= w + 30
        # vertical grid + value ticks along the bottom
        for i in range(5):
            gx = plot.right() - plot.width() * i / 4
            p.setPen(QPen(QColor(self.pal["line"]), 1, Qt.PenStyle.DashLine if i else Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(gx, plot.top()), QPointF(gx, plot.bottom()))
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(gx - 20, plot.bottom() + 3, 40, 16), Qt.AlignmentFlag.AlignCenter, fa(int(round(vmax * i / 4))))
        n, k = len(self.data), len(self.series)
        rh = plot.height() / n
        bh = min(11.0, rh * 0.30)
        for i, row in enumerate(self.data):
            cy = plot.top() + rh * (i + 0.5)
            if i == self._hover:
                hv = QColor(self.pal["text"])
                hv.setAlphaF(0.05)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(hv)
                p.drawRoundedRect(QRectF(0, cy - rh / 2 + 1, self.width(), rh - 2), _rad(6), _rad(6))
            p.setPen(QColor(self.pal["text"]))
            p.drawText(QRectF(self.width() - label_w - 4, cy - rh / 2, label_w, rh), AL_R | Qt.AlignmentFlag.AlignVCenter, str(row[0]))
            for s_i in range(k):
                val = row[1 + s_i]
                w = plot.width() * val / vmax * self.p
                y = cy - bh - 1 if s_i == 0 else cy + 1
                r = QRectF(plot.right() - w, y, w, bh)
                rad = min(bh / 2, max(0.0, w / 2))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self.series[s_i][1])
                p.drawRoundedRect(r, rad, rad)
                if w > rad:                                  # flat start against the axis, round only the far end
                    p.drawRect(QRectF(r.right() - rad, r.top(), rad, r.height()))
        if self._hover is not None:
            row = self.data[self._hover]
            cy = plot.top() + rh * (self._hover + 0.5)
            self._tooltip(p, QPointF(plot.center().x(), cy - 4), str(row[0]),
                          [(self.series[s][1], self.series[s][0], fa(row[1 + s])) for s in range(k)])


# ------------------------------------------------------------------ donut ---
class Donut(ChartBase):
    """items = [(name, value, color, hatched)]; centre = (big, small)."""

    def __init__(self, theme="dark"):
        super().__init__(theme)
        self.items: list[tuple] = []
        self.centre = ("", "")
        self.setMinimumHeight(220)

    def set_data(self, items, centre=("", ""), theme=None) -> None:
        self.items, self.centre = list(items), centre
        if theme:
            self.theme = theme
        self.animate()

    def _geom(self):
        legend_h = 22 * ((len(self.items) + 1) // 2) + 4
        size = min(self.width() - 20, self.height() - legend_h - 10, 190)        # a calm ring, not a poster
        c = QPointF(self.width() / 2, 8 + (self.height() - legend_h - 10) / 2)
        return c, size / 2, legend_h

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not self.items:
            return
        c, R, _ = self._geom()
        d = e.position() - c
        dist = math.hypot(d.x(), d.y())
        hit = None
        if R * 0.72 <= dist <= R + 4:
            ang = (math.degrees(math.atan2(-d.y(), d.x())) - 90) % 360
            ang = (360 - ang) % 360
            tot = sum(v for _n, v, *_ in self.items) or 1
            acc = 0.0
            for i, (_n, v, *_r) in enumerate(self.items):
                acc += v / tot * 360
                if ang <= acc:
                    hit = i
                    break
        if hit != self._hover:
            self._hover = hit
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, R, lh = self._geom()
        tot = sum(v for _n, v, *_ in self.items)
        if R <= 10:
            return
        thick = max(10.0, R * 0.2)
        rect = QRectF(c.x() - R + thick / 2, c.y() - R + thick / 2, 2 * R - thick, 2 * R - thick)
        p.setPen(QPen(QColor(self.pal["line"]), thick))                         # quiet track under the segments
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        if tot > 0:
            gap = 4.0 if len([1 for it in self.items if it[1] > 0]) > 1 else 0
            start = 90.0
            for i, (n, v, col, hatched) in enumerate(self.items):
                if v <= 0:
                    continue
                span = v / tot * 360 * self.p
                sweep = max(0.5, span - gap)
                w = thick + (5 if i == self._hover else 0)
                base = QColor(col)
                pen = QPen(base, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
                if hatched:
                    b = QBrush(base, Qt.BrushStyle.BDiagPattern)
                    fillc = QColor(base)
                    fillc.setAlphaF(0.3)
                    p.setPen(QPen(fillc, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                    p.drawArc(rect, int((start - gap / 2) * 16), int(-sweep * 16))
                    pen = QPen(b, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
                p.setPen(pen)
                p.drawArc(rect, int((start - gap / 2) * 16), int(-sweep * 16))
                start -= span
        big, small = self.centre
        p.setPen(QColor(self.pal["text"]))
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(c.x() - R * 0.5, c.y() - 26, R, 30), Qt.AlignmentFlag.AlignCenter, big)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 10))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(self.pal["muted"]))
        p.drawText(QRectF(c.x() - R * 0.5, c.y() + 4, R, 20), Qt.AlignmentFlag.AlignCenter, small)
        # legend
        f.setPointSizeF(max(8.0, self.font().pointSizeF() - 0.5))
        p.setFont(f)
        y0 = self.height() - lh
        colw = self.width() / 2
        for i, (n, v, col, hatched) in enumerate(self.items):
            r_, c_ = divmod(i, 2)
            x = self.width() - (c_ + 1) * colw + 8
            y = y0 + r_ * 22
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(col), Qt.BrushStyle.BDiagPattern if hatched else Qt.BrushStyle.SolidPattern))
            p.drawRoundedRect(QRectF(x + colw - 26, y + 5, 10, 10), 3, 3)
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(x, y, colw - 32, 20), AL_R | Qt.AlignmentFlag.AlignVCenter, f"{n}  {fa(v)}")
        if self._hover is not None and self._hover < len(self.items):
            n, v, col, _h = self.items[self._hover]
            pct = round(v / tot * 100) if tot else 0
            self._tooltip(p, QPointF(c.x(), c.y() - R * 0.2), n, [(QColor(col), "تعداد", f"{fa(v)} ({fa(pct)}٪)")])


# ----------------------------------------------------------- radial bars ---
class RadialBars(ChartBase):
    """items = [(name, 0..100, color)]"""

    def __init__(self, theme="dark"):
        super().__init__(theme)
        self.items: list[tuple] = []
        self.setMinimumHeight(240)

    def set_data(self, items, theme=None) -> None:
        self.items = list(items)
        if theme:
            self.theme = theme
        self.animate()

    def _geom(self):
        lh = 22 * ((len(self.items) + 1) // 2) + 4
        size = min(self.width() - 20, self.height() - lh - 10)
        return QPointF(self.width() / 2, 8 + size / 2), size / 2, lh

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        c, R, _ = self._geom()
        d = e.position() - c
        dist = math.hypot(d.x(), d.y())
        n = len(self.items)
        band = (R - R * 0.28) / max(1, n)
        hit = None
        for i in range(n):
            r_out = R - i * band
            if r_out - band <= dist <= r_out:
                hit = i
        if hit != self._hover:
            self._hover = hit
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, R, lh = self._geom()
        n = len(self.items)
        if R <= 10 or not n:
            return
        band = (R - R * 0.28) / n
        bar = band * 0.7
        f = QFont(self.font())
        for i, (name, val, col) in enumerate(self.items):
            r = R - i * band - band / 2
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            track = QColor(self.pal["line"])
            track.setAlphaF(0.55)
            p.setPen(QPen(track, bar, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 90 * 16, -270 * 16)
            sweep = 270 * max(0, min(100, val)) / 100 * self.p
            g = QColor(col)
            if i == self._hover:
                g = g.lighter(115)
            p.setPen(QPen(g, bar, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            if sweep > 0.5:
                p.drawArc(rect, 90 * 16, int(-sweep * 16))
        f.setPointSizeF(max(8.0, f.pointSizeF() - 0.5))
        p.setFont(f)
        y0 = self.height() - lh
        colw = self.width() / 2
        for i, (name, val, col) in enumerate(self.items):
            r_, c_ = divmod(i, 2)
            x = self.width() - (c_ + 1) * colw + 8
            y = y0 + r_ * 22
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x + colw - 26, y + 5, 10, 10), 3, 3)
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(x, y, colw - 32, 20), AL_R | Qt.AlignmentFlag.AlignVCenter, f"{name}  {fa(val)}٪")
        if self._hover is not None and self._hover < n:
            name, val, col = self.items[self._hover]
            self._tooltip(p, QPointF(c.x(), c.y() - R * 0.1), name, [(QColor(col), "امتیاز", f"{fa(val)}/{fa(100)}")])


# ------------------------------------------------------------------ radar ---
class Radar(ChartBase):
    """axes = [label], values = [number]"""

    def __init__(self, theme="dark", color=CHART[3], name="انجام‌شده"):
        super().__init__(theme)
        self.axes: list[str] = []
        self.values: list[float] = []
        self.color, self.name = QColor(color), name
        self.setMinimumHeight(240)

    def set_data(self, axes, values, theme=None) -> None:
        self.axes = list(axes)
        self.values = (list(values) + [0.0] * len(self.axes))[:len(self.axes)]      # one value per axis, always
        if theme:
            self.theme = theme
        self.animate()

    def _geom(self):
        R = min(self.width(), self.height()) / 2 - 34
        return QPointF(self.width() / 2, self.height() / 2), max(20, R)

    def _pt(self, c, R, i, frac) -> QPointF:
        n = len(self.axes)
        a = -math.pi / 2 - i * 2 * math.pi / n      # clockwise flipped for RTL (Saturday at top, going left)
        return QPointF(c.x() + math.cos(a) * R * frac, c.y() + math.sin(a) * R * frac)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        c, R = self._geom()
        hit = None
        for i in range(len(self.axes)):
            pt = self._pt(c, R, i, (self.values[i] / (max(self.values) or 1)))
            if math.hypot(pt.x() - e.position().x(), pt.y() - e.position().y()) < 14:
                hit = i
        if hit != self._hover:
            self._hover = hit
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.axes)
        if n < 3:
            return
        self._hover_in(min(len(self.axes), len(self.values)))
        c, R = self._geom()
        vmax = max(self.values) or 1
        for ring in (0.25, 0.5, 0.75, 1.0):
            poly = QPainterPath(self._pt(c, R, 0, ring))
            for i in range(1, n):
                poly.lineTo(self._pt(c, R, i, ring))
            poly.closeSubpath()
            p.setPen(QPen(QColor(self.pal["line"]), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(poly)
        for i in range(n):
            p.setPen(QPen(QColor(self.pal["line"]), 1))
            p.drawLine(c, self._pt(c, R, i, 1))
        poly = QPainterPath()
        pts = [self._pt(c, R, i, self.values[i] / vmax * self.p) for i in range(n)]
        poly.moveTo(pts[0])
        for pt in pts[1:]:
            poly.lineTo(pt)
        poly.closeSubpath()
        from PyQt6.QtGui import QRadialGradient
        g = QRadialGradient(c, R)
        c1, c2 = QColor(self.color), QColor(self.color)
        c1.setAlphaF(0.08)
        c2.setAlphaF(0.5)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        glow = QColor(self.color)
        glow.setAlphaF(0.2)
        p.setPen(QPen(glow, 6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(poly)
        p.setPen(QPen(self.color, 2))
        p.setBrush(QBrush(g))
        p.drawPath(poly)
        f = QFont(self.font())
        p.setFont(f)
        for i, pt in enumerate(pts):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.color)
            p.drawEllipse(pt, 5 if i == self._hover else 3.6, 5 if i == self._hover else 3.6)
            lp = self._pt(c, R + 20, i, 1)
            p.setPen(QColor(self.pal["muted"]))
            p.drawText(QRectF(lp.x() - 34, lp.y() - 10, 68, 20), Qt.AlignmentFlag.AlignCenter, self.axes[i])
        if self._hover is not None:
            self._tooltip(p, pts[self._hover], self.axes[self._hover], [(self.color, self.name, fa(int(self.values[self._hover])))])
