# SPDX-License-Identifier: GPL-3.0-or-later
"""Premium, custom-painted building blocks shared by the Habits and Goals pages.

Everything here reads the live palette at paint time (``_fpal``), scales radii with the active theme (``rr``) and only
repaints while animating, so it stays cheap and follows all 29 colour themes.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import time

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QTextCharFormat,
                         QTextLayout, QTextOption)
from PyQt6.QtWidgets import QPlainTextEdit, QSizePolicy, QTextEdit, QToolTip, QWidget

from ..core import jalali
from . import icons, micro
from .anim import MOTION, STRIPE_PERIOD, Ticker, mark_progress, marker_color, span_x, stripe_phase, stripe_watch, sweep_rect
from .charts import CHART
from .fx_widgets import _Anim, _fpal
from .theme import AL_R, rr


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def alpha(c: QColor | str, a: float) -> QColor:
    q = QColor(c)
    q.setAlphaF(max(0.0, min(1.0, a)))
    return q


def on_color(c: QColor | str) -> QColor:
    """Readable ink (black/white) for a fill colour."""
    q = QColor(c)
    lum = 0.2126 * q.redF() + 0.7152 * q.greenF() + 0.0722 * q.blueF()
    return QColor("#101114") if lum > 0.55 else QColor("#ffffff")


def accent_for(key: str, pal: dict) -> QColor:
    """A stable per-item colour picked from the active theme's chart palette (falls back to the accent)."""
    lively = [c for c in CHART if QColor(c).hsvSaturation() > 60]     # a grey habit / goal would read as "disabled"
    if not lively:
        return QColor(pal["accent"])
    return QColor(lively[sum(ord(ch) for ch in key) % len(lively)])


def tone_color(tone: str | QColor, pal: dict) -> QColor:
    if isinstance(tone, QColor):
        return tone
    if tone.startswith("#"):
        return QColor(tone)
    if tone == "info":                                     # secondary brand colour, lifted on dark grounds
        c = QColor(pal["accent2"])
        return c.lighter(135) if QColor(pal["bg"]).lightness() < 128 else c
    return QColor({"success": pal["ok"], "danger": pal["danger"], "warn": pal["warn"], "muted": pal["muted"],
                   "accent": pal["acc_text"]}.get(tone, pal["muted"]))


def _font(w: QWidget, delta: float = 0.0, bold: bool = False) -> QFont:
    f = QFont(w.font())
    f.setPointSizeF(max(7.0, f.pointSizeF() + delta))
    f.setBold(bold)
    return f


def draw_num(p: QPainter, rect: QRectF, align, text: str, zero_scale: float = 1.45) -> None:
    """drawText for big numbers: the Persian zero (۰) is a tiny dot in most fonts, so enlarge just that glyph."""
    zs = [i for i, ch in enumerate(text) if ch in "۰٠"]
    if not zs:
        p.drawText(rect, align, text)
        return
    font = p.font()
    lay = QTextLayout(text, font)
    opt = QTextOption(align & Qt.AlignmentFlag.AlignHorizontal_Mask)
    opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
    lay.setTextOption(opt)
    big = QFont(font)
    big.setPointSizeF(font.pointSizeF() * zero_scale)
    big.setBold(font.bold())            # same weight as its neighbours: a bold enlarged dot reads as a ring
    fmt = QTextCharFormat()
    fmt.setFont(big)
    rs = []
    for i in zs:
        r = QTextLayout.FormatRange()
        r.start, r.length, r.format = i, 1, fmt
        rs.append(r)
    lay.setFormats(rs)
    lay.beginLayout()
    line = lay.createLine()
    line.setLineWidth(rect.width())
    lay.endLayout()
    # centre on the base font's line box so bigger zeros grow evenly instead of pushing the digits around
    fm = QFontMetrics(font)
    y = rect.top() + (rect.height() - fm.height()) / 2 - (line.ascent() - fm.ascent())
    if align & Qt.AlignmentFlag.AlignTop:
        y = rect.top()
    lay.draw(p, QPointF(rect.left(), y))


# ------------------------------------------------------------------ chips ---
class Chips(QWidget):
    """A row of small tinted pills (icon + text). Painted from the right edge (RTL)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[str, str | QColor, str | None]] = []
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_items(self, items) -> None:
        self.items = list(items)
        self.update()

    def _widths(self, fm: QFontMetrics) -> list[int]:
        return [fm.horizontalAdvance(t) + 20 + (16 if ic else 0) for t, _c, ic in self.items]

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(_font(self, -1, True))
        return QSize(sum(self._widths(fm)) + 6 * max(0, len(self.items) - 1), 26)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = _font(self, -1, True)
        p.setFont(f)
        fm = QFontMetrics(f)
        x = float(self.width())
        for (text, tone, ic), w in zip(self.items, self._widths(fm)):
            base = tone_color(tone, pal)
            col = mix(base, QColor(pal["text"]), 0.28)      # keeps pastel accents readable as text
            r = QRectF(x - w, 1, w, 24)
            x -= w + 6
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(base, 0.17))
            p.drawRoundedRect(r, min(rr(12), 12), min(rr(12), 12))
            tr = r.adjusted(10, 0, -10, 0)
            if ic:
                p.drawPixmap(int(tr.right() - 13), int(r.center().y() - 6.5), icons.pixmap(ic, col.name(), 13))
                tr.setRight(tr.right() - 16)
            p.setPen(col)
            p.drawText(tr, AL_R | Qt.AlignmentFlag.AlignVCenter, text)


_DIG = "۰۱۲۳۴۵۶۷۸۹0123456789٠١٢٣٤٥٦٧٨٩"


def _digits(t: str) -> bool:
    return bool(t) and all(c in _DIG for c in t)


def draw_roll(p: QPainter, rect: QRectF, old: str, new: str, t: float) -> None:
    """Odometer: only the digits that changed roll (up when the number grew, down when it fell), the last digit first;
    unchanged digits stay put. Numbers are right-aligned like ``draw_num``; ``old`` and ``new`` have the same length."""
    fm = QFontMetrics(p.font())
    advs = [fm.horizontalAdvance(c) for c in new]
    x = rect.right() - sum(advs)
    to_i = lambda s: int("".join(str(_DIG.index(c) % 10) for c in s))          # noqa: E731
    up = to_i(new) >= to_i(old)
    n = len(new)
    p.save()
    p.setClipRect(rect)
    for i, (o, c) in enumerate(zip(old, new)):
        cell = QRectF(x, rect.top(), advs[i], rect.height())
        if o == c:
            draw_num(p, cell, Qt.AlignmentFlag.AlignCenter, c)
        else:
            k = max(0.0, min(1.0, (t - (n - 1 - i) * 0.09) / 0.7))
            e = 1 - (1 - k) ** 3
            off = rect.height() * 0.8 * (-1 if up else 1)
            p.setOpacity(1 - e)
            draw_num(p, cell.translated(0, off * e), Qt.AlignmentFlag.AlignCenter, o)
            p.setOpacity(e)
            draw_num(p, cell.translated(0, -off * (1 - e)), Qt.AlignmentFlag.AlignCenter, c)
            p.setOpacity(1.0)
        x += advs[i]
    p.restore()


# -------------------------------------------------------------------- KPI ---
def paint_tile_spark(p: QPainter, rect: QRectF, values: list[float], color: QColor, pal: dict) -> None:
    """A tiny trend line for a KPI tile: soft glow, a hairline on top, a matte wash below and a dot on the latest value.
    The series is oldest -> newest, so it runs right-to-left like the rest of the (RTL) interface."""
    n = len(values)
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = [QPointF(rect.right() - rect.width() * i / (n - 1),          # oldest at the right, newest at the left (RTL, like the area chart)
                   rect.bottom() - 3 - (rect.height() - 8) * ((v - lo) / span if hi != lo else 0.0))
           for i, v in enumerate(values)]
    path = QPainterPath(pts[0])
    for i in range(1, n):
        a, b = pts[i - 1], pts[i]
        dx = (b.x() - a.x()) / 2.5
        path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
    p.save()
    fill = QPainterPath(path)
    fill.lineTo(pts[-1].x(), rect.bottom())
    fill.lineTo(pts[0].x(), rect.bottom())
    fill.closeSubpath()
    g = QLinearGradient(0, rect.top(), 0, rect.bottom())
    g.setColorAt(0, alpha(color, 0.22))
    g.setColorAt(1, alpha(color, 0.0))
    p.fillPath(fill, g)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(alpha(color, 0.20), 4, cap=Qt.PenCapStyle.RoundCap))
    p.drawPath(path)
    p.setPen(QPen(color, 1.5, cap=Qt.PenCapStyle.RoundCap))
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(alpha(color, 0.25))
    p.drawEllipse(pts[-1], 4.5, 4.5)
    p.setBrush(color)
    p.drawEllipse(pts[-1], 2.2, 2.2)
    p.restore()


class KpiTile(QWidget):
    """Summary tile: tinted icon, big value, caption and an optional thin progress bar."""

    def __init__(self, icon: str, tone: str = "accent", parent=None):
        super().__init__(parent)
        self.icon, self.tone = icon, tone
        self.value, self.caption, self.progress, self.delta = "—", "", None, None
        self.spark: list[float] | None = None
        self._p = _Anim(self, 0, 700, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._tick = Ticker(self, 900)                 # the number counts up to its value
        self._replayed = 0.0
        self.setFixedHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        from .brand import HoverLight
        self._hl = HoverLight(self)
        self._roll = _Anim(self, 1.0, 460, QEasingCurve(QEasingCurve.Type.OutCubic))   # odometer roll on a value change
        self._roll_from = ""
        self._pg = _Anim(self, 1.0, 800, QEasingCurve(QEasingCurve.Type.InOutQuad))      # glint along a bar that just grew
        self._hold_until, self._pending = 0.0, None
        self._pulse = _Anim(self, 1.0, 620, QEasingCurve(QEasingCurve.Type.OutCubic))  # a ring leaves the glyph when a light lands

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hl.enter()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hl.leave()
        super().leaveEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._hl.stop()
        super().hideEvent(e)

    def hold(self, ms: int) -> None:
        """Keep the shown number for ``ms`` (a light is on its way); the newest ``set`` is applied when it lands."""
        self._hold_until = time.monotonic() + ms / 1000.0
        QTimer.singleShot(ms + 20, self.release)

    def release(self) -> None:
        self._hold_until = 0.0
        if self._pending is not None:
            args, kw = self._pending
            self._pending = None
            self.set(*args, **kw)

    def land(self) -> None:
        """A light arrived: release the held number (it rolls now) and send a ring out from the glyph."""
        self.release()
        if MOTION[0]:
            self._pulse.set(0.0)
            self._pulse.to(1.0)

    def anchor(self) -> QPoint:
        return QPoint(int(self.width() - 14 - 15), 14 + 15)          # the centre of the glyph tile

    def set(self, value: str, caption: str, progress: float | None = None, delta: tuple[str, str] | None = None,
            spark: list | None = None) -> None:
        if time.monotonic() < self._hold_until:
            self._pending = ((value, caption, progress, delta), {"spark": spark})
            return
        old_value = self.value
        self.value, self.caption = value, caption
        self.progress, self.delta = progress, delta
        self.spark = [float(x) for x in spark] if spark and len(spark) >= 3 else None
        if (self.isVisible() and MOTION[0] and time.monotonic() - self._replayed > 1.4 and value != old_value
                and _digits(value) and _digits(old_value) and len(value) == len(old_value)):
            self._tick.set_text(value, animate=False)          # a settled number rolls digit by digit instead of counting
            self._roll_from = old_value
            self._roll.set(0.0)
            self._roll.to(1.0)
        else:
            self._tick.set_text(value, animate=self.isVisible() or self._tick.parts is None)
        if progress is not None:
            newp = max(0.0, min(1.0, progress))
            if MOTION[0] and self.isVisible() and self.progress is not None and newp > self._p.value + 0.004:
                self._pg.set(0.0)
                self._pg.to(1.0)
            self._p.to(newp)
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        # count up again when the page is opened (but not when it flickers back within a few seconds)
        now = time.monotonic()
        if now - self._replayed > 4.0:
            self._replayed = now
            self._tick.replay()
            self._p.set(0.0)
            if self.progress is not None:
                self._p.to(max(0.0, min(1.0, self.progress)))
        super().showEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        """Neutral surface; colour is spent only where it carries meaning (the glyph, and a warning number)."""
        pal = _fpal(self)
        col = tone_color(self.tone, pal)
        if self.tone == "accent":                          # the brand colour belongs to actions, not to statistics
            col = QColor(pal["text"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = rr(12)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(r, rad, rad)
        if QColor(pal["bg"]).lightness() < 128:
            from .brand import paint_depth
            paint_depth(p, QRectF(self.rect()), rad, pal)
        ib = QRectF(r.right() - 14 - 30, r.top() + 14, 30, 30)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(ib, min(rr(8), 10), min(rr(8), 10))
        p.drawPixmap(int(ib.center().x() - 8), int(ib.center().y() - 8), icons.pixmap(self.icon, col.name(), 16))
        p.setPen(QColor(pal["muted"]))
        p.setFont(_font(self, -0.5))
        p.drawText(QRectF(r.left() + 14, ib.top(), ib.left() - r.left() - 24, ib.height()),
                   AL_R | Qt.AlignmentFlag.AlignVCenter, self.caption)
        warn = self.tone == "danger" and self._tick.shown() not in ("۰", "0", "—", "")
        zero = self._tick.shown() in ("۰", "0")                # the Persian zero is a bold ring: quiet it so it reads "nothing"
        p.setPen(QColor(pal["danger"]) if warn else QColor(pal["muted"] if zero else pal["text"]))
        nf = _font(self, 8, not zero)
        nf.setFeature(QFont.Tag("tnum"), 1)                 # tabular figures: the count-up never jitters sideways
        p.setFont(nf)
        nr = QRectF(r.left() + 14, ib.bottom() + 4, r.width() - 28, 34)
        if self._roll.value < 1.0 and self._roll_from:
            draw_roll(p, nr, self._roll_from, self._tick.shown(), self._roll.value)
        else:
            draw_num(p, nr, AL_R | Qt.AlignmentFlag.AlignVCenter, self._tick.shown())
        if self.delta:
            text, tone = self.delta
            dc = tone_color(tone, pal)
            f = _font(self, -1.5, True)
            p.setFont(f)
            w = QFontMetrics(f).horizontalAdvance(text) + 16
            box = QRectF(r.left() + 14, ib.bottom() + 12, w, 22)
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.setBrush(QColor(pal["panel2"]))
            p.drawRoundedRect(box, min(rr(11), 11), min(rr(11), 11))
            p.setPen(mix(dc, QColor(pal["text"]), 0.35) if tone != "muted" else QColor(pal["muted"]))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        if self.spark and not self.delta:
            paint_tile_spark(p, QRectF(r.left() + 14, ib.bottom() + 6, min(96.0, r.width() * 0.36), 28), self.spark, mix(QColor(pal["text"]), col, 0.5) if self.tone != "accent" else QColor(pal["accent2"]), pal)
        if self.progress is not None:
            bar = QRectF(r.left() + 14, r.bottom() - 12, r.width() - 28, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["panel2"]))
            p.drawRoundedRect(bar, 1.5, 1.5)
            w = bar.width() * self._p.value
            if w > 1:
                p.setBrush(col)
                p.drawRoundedRect(QRectF(bar.right() - w, bar.top(), w, 3), 1.5, 1.5)
                if 0.0 < self._pg.value < 1.0:                                   # a glint runs along the new length
                    gx = bar.right() - w * self._pg.value
                    gb = QLinearGradient(gx + 18, 0, gx - 18, 0)
                    gb.setColorAt(0, QColor(255, 255, 255, 0))
                    gb.setColorAt(0.5, QColor(255, 255, 255, 190))
                    gb.setColorAt(1, QColor(255, 255, 255, 0))
                    p.save()
                    p.setClipRect(QRectF(bar.right() - w, bar.top() - 1, w, 5))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(gb))
                    p.drawRoundedRect(QRectF(bar.right() - w, bar.top(), w, 3), 1.5, 1.5)
                    p.restore()
        if self._pulse.value < 1.0:                        # the landing ring
            k = self._pulse.value
            ring = alpha(tone_color("success", pal) if self.tone != "danger" else col, 0.7 * (1 - k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(ring, 2.0 * (1 - k) + 0.6))
            gr = ib.adjusted(-k * 12, -k * 12, k * 12, k * 12)
            p.drawRoundedRect(gr, min(rr(8), 10) + k * 10, min(rr(8), 10) + k * 10)
        self._hl.paint(p, r, rad, pal)


# ------------------------------------------------------------------- rings ---
class HabitRing(QWidget):
    """Round 'log today' button: outer arc = weekly goal progress, inner disc fills when today is logged."""
    clicked = pyqtSignal()

    def __init__(self, color: QColor, frac: float, done: bool, prev: tuple[float, float] | None = None, parent=None):
        super().__init__(parent)
        self.color = color
        self._f = _Anim(self, prev[0] if prev else 0.0, 650, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._d = _Anim(self, prev[1] if prev else (1.0 if done else 0.0), 320, QEasingCurve(QEasingCurve.Type.OutBack))
        self._h = _Anim(self, 0, 140)
        self._down = False
        self.done = done
        self._f.to(frac)
        self._d.to(1.0 if done else 0.0)
        self.setFixedSize(68, 68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip("لغو ثبت امروز" if done else "ثبت امروز")
        self.setAccessibleName(self.toolTip())

    @property
    def state(self) -> tuple[float, float]:
        return (self._f.value, self._d.value)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._down = True
            self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        was, self._down = self._down, False
        self.update()
        if was and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        d = max(0.0, min(1.0, self._d.value))
        hov = self._h.value
        ring = QRectF(c.x() - 30, c.y() - 30, 60, 60)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(mix(QColor(pal["line"]), QColor(pal["muted"]), 0.15), 4, cap=Qt.PenCapStyle.RoundCap))
        p.drawEllipse(ring)
        f = max(0.0, min(1.0, self._f.value))
        if f > 0.004:
            p.setPen(QPen(self.color, 4, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, int(-f * 360 * 16))
        # RTL-friendly: arc runs clockwise from 12 o'clock
        rad = 21.0 * (0.94 if self._down else 1.0) + 1.5 * hov
        fill = mix(QColor(pal["panel2"]), self.color, d)
        p.setPen(QPen(mix(QColor(pal["line"]), self.color, max(d, 0.55 * hov)), 1.4))
        p.setBrush(fill)
        p.drawEllipse(c, rad, rad)
        ink = on_color(self.color)
        col = mix(QColor(pal["muted"]), ink, d)
        s = 20
        pm = icons.pixmap("check", col.name(), s)
        p.drawPixmap(int(c.x() - s / 2), int(c.y() - s / 2), pm)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["accent"]), 2))
            p.drawEllipse(QRectF(1.5, 1.5, self.width() - 3, self.height() - 3))


class GoalRing(QWidget):
    """Large progress ring with the percentage in the middle."""

    def __init__(self, frac: float, color: QColor, prev: float | None = None, parent=None):
        super().__init__(parent)
        self.color = color
        self._f = _Anim(self, prev if prev is not None else 0.0, 900, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._f.to(frac)
        self.target = frac
        self._glow = _Anim(self, 1.0 if (prev or 0.0) >= 0.999 else 0.0, 1500, QEasingCurve(QEasingCurve.Type.OutCubic))
        if frac >= 0.999 and (prev or 0.0) < 0.999:                  # the ring just closed: it flashes brand metal once
            self._f.a.finished.connect(lambda: self._glow.to(1.0))
        self.setFixedSize(92, 92)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(8, 8, self.width() - 16, self.height() - 16)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(alpha(self.color, 0.16), 8, cap=Qt.PenCapStyle.RoundCap))
        p.drawEllipse(r)
        f = max(0.0, min(1.0, self._f.value))
        full = self.target >= 0.999 and f >= 0.999
        g = self._glow.value if full else 0.0
        ring_col = mix(self.color, QColor(pal["accent2"]), min(1.0, g * 1.4)) if full else self.color
        if g > 0.0:                                                    # gold halo: bright at first, then a calm afterglow
            for w, a in ((16, 0.10), (11, 0.16)):
                p.setPen(QPen(alpha(QColor(pal["accent2"]), a * (1.0 - 0.55 * g) * min(1.0, g * 4)), w))
                p.drawEllipse(r)
        if f > 0.004:
            p.setPen(QPen(ring_col, 8, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, int(-f * 360 * 16))
        p.setPen(QColor(pal["text"]))
        p.setFont(_font(self, 4, True))
        draw_num(p, QRectF(0, 0, self.width(), self.height() - 8), Qt.AlignmentFlag.AlignCenter,
                 jalali.fa(round(self.target * 100)) + "٪")
        p.setPen(QColor(pal["muted"]))
        p.setFont(_font(self, -2.5))
        p.drawText(QRectF(0, self.height() / 2 + 10, self.width(), 16), Qt.AlignmentFlag.AlignCenter, "پیشرفت")

    @property
    def value(self) -> float:
        return self._f.value


class HabitHeatmap(QWidget):
    """GitHub-style year-at-a-glance for ALL habits: one square per day (newest week on the start side); the deeper the
    colour, the larger the share of habits done that day."""
    CELL, GAP, MAX_CELL, YEAR = 13, 3, 18, 52

    def __init__(self, habits: list[dict], parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.today = dt.date.today()
        n = max(1, len(habits))
        self.counts: dict[dt.date, int] = {}
        for h in habits:
            for k in (h.get("log") or {}):
                try:
                    d = dt.date.fromisoformat(k)
                except ValueError:
                    continue
                self.counts[d] = self.counts.get(d, 0) + 1
        self.n = n
        self.cell = self.CELL
        self.setFixedHeight(7 * (self.cell + self.GAP) + 44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._rects: list[tuple[QRectF, dt.date]] = []

    def _cell_for(self, width: int) -> int:
        """13 px squares until a full year fits; on a wide card the squares grow (up to MAX_CELL) so the year fills it."""
        return max(self.CELL, min(self.MAX_CELL, (max(width, 1) - 28) // self.YEAR - self.GAP))

    def resizeEvent(self, e) -> None:  # noqa: N802
        c = self._cell_for(self.width())
        if c != self.cell:
            self.cell = c
            self.setFixedHeight(7 * (c + self.GAP) + 44)
        super().resizeEvent(e)

    @property
    def weeks(self) -> int:
        """As many weeks as the card is wide (a full year at most)."""
        return max(8, min(self.YEAR, (self.width() - 28) // (self.cell + self.GAP)))

    def _origin(self) -> dt.date:
        """First day of the grid: a Saturday, WEEKS-1 weeks before this week's Saturday."""
        sat = self.today - dt.timedelta(days=jalali.weekday_index(self.today))
        return sat - dt.timedelta(weeks=self.weeks - 1)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = self.cell + self.GAP
        right = self.width() - 14
        top = 30
        self._rects = []
        o = self._origin()
        base = QColor(pal["panel2"])
        p.setPen(QColor(pal["muted"]))
        p.setFont(_font(self, -1))
        p.drawText(QRectF(14, 4, self.width() - 28, 20), AL_R | Qt.AlignmentFlag.AlignVCenter,
                   f"{jalali.fa(sum(c for d, c in self.counts.items() if d >= o))} ثبت در {jalali.fa(self.weeks)} هفته‌ی اخیر")
        for w in range(self.weeks):
            for dow in range(7):
                d = o + dt.timedelta(weeks=w, days=dow)
                if d > self.today:
                    continue
                r = QRectF(right - (w + 1) * step + self.GAP, top + dow * step, self.cell, self.cell)
                c = self.counts.get(d, 0)
                t = min(1.0, c / self.n) if c else 0.0
                col = mix(base, QColor(pal["ok"]), 0.30 + 0.70 * t) if c else mix(base, QColor(pal["line"]), 0.5)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                rad = max(3.0, self.cell * 0.22)
                p.drawRoundedRect(r, rad, rad)
                if d == self.today:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(pal["text"]), 1.2))
                    p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), rad + 1, rad + 1)
                self._rects.append((r, d))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        for r, d in self._rects:
            if r.contains(e.position()):
                j = jalali.to_jalali(d.year, d.month, d.day)
                QToolTip.showText(e.globalPosition().toPoint(),
                                  f"{jalali.fa(j[2])} {jalali.MONTHS_FA[j[1] - 1]}: {jalali.fa(self.counts.get(d, 0))} عادت", self)
                return
        QToolTip.hideText()


# ------------------------------------------------------------- week strip ---
class WeekStrip(QWidget):
    """Seven day capsules for the current Persian week (Sat → Fri, right to left). Click to toggle a day."""
    dayClicked = pyqtSignal(object)

    def __init__(self, log: dict, color: QColor, parent=None):
        super().__init__(parent)
        self.log, self.color = log or {}, color
        self.setFixedSize(280, 60)
        self.setMouseTracking(True)
        self._hover = -1

    def _days(self) -> list[dt.date]:
        today = dt.date.today()
        sat = today - dt.timedelta(days=jalali.weekday_index(today))
        return [sat + dt.timedelta(days=i) for i in range(7)]

    def _center(self, i: int) -> QPointF:
        cw = self.width() / 7
        return QPointF(self.width() - (i + 0.5) * cw, 39)

    def _hit(self, pt: QPointF) -> int:
        for i in range(7):
            c = self._center(i)
            if abs(pt.x() - c.x()) <= self.width() / 14 and pt.y() > 18:
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = self._hit(e.position())
        days = self._days()
        i = i if 0 <= i < 7 and days[i] <= dt.date.today() else -1
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._hit(e.position())
        days = self._days()
        if 0 <= i < 7 and days[i] <= dt.date.today() and e.button() == Qt.MouseButton.LeftButton:
            self.dayClicked.emit(days[i])

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        today = dt.date.today()
        ink = on_color(self.color)
        for i, d in enumerate(self._days()):
            c = self._center(i)
            on = d.isoformat() in self.log
            future = d > today
            is_today = d == today
            p.setFont(_font(self, -1.5, is_today))
            p.setPen(QColor(pal["acc_text"] if is_today else pal["muted"]))
            p.drawText(QRectF(c.x() - 20, 0, 40, 18), Qt.AlignmentFlag.AlignCenter, jalali.WEEKDAYS_SHORT[i])
            rad = 14.0 + (1.2 if i == self._hover else 0)
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self.color)
                p.drawEllipse(c, rad, rad)
                p.drawPixmap(int(c.x() - 7.5), int(c.y() - 7.5), icons.pixmap("check", ink.name(), 15))
            else:
                pen = QPen(QColor(pal["accent"]) if is_today else mix(QColor(pal["line"]), QColor(pal["muted"]), 0.2),
                           1.6 if is_today else 1.2)
                if future:
                    pen = QPen(alpha(pal["line"], 0.8), 1.1, Qt.PenStyle.DotLine)
                if i == self._hover:
                    pen = QPen(self.color, 1.6)
                p.setPen(pen)
                p.setBrush(QColor(pal["panel2"]) if not future else Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, rad - 0.6, rad - 0.6)
            if is_today:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent"]))
                p.drawEllipse(QPointF(c.x(), 57), 1.8, 1.8)


# ---------------------------------------------------------- segmented bar ---
def _rgb_dist(a: QColor, b: QColor) -> float:
    return ((a.red() - b.red()) ** 2 + (a.green() - b.green()) ** 2 + (a.blue() - b.blue()) ** 2) ** 0.5


def distinct_color(pal: dict, taken: list[QColor], prefer=("accent2", "ok", "warn", "accent", "danger"), gap: float = 95.0) -> QColor:
    """First palette colour that is clearly different from every colour already used in the same bar."""
    best, best_d = QColor(pal[prefer[0]]), -1.0
    for key in prefer:
        c = QColor(pal[key])
        d = min((_rgb_dist(c, t) for t in taken), default=999.0)
        if d >= gap:
            return c
        if d > best_d:
            best, best_d = c, d
    return best


class SegmentedProgress(QWidget):
    """Multi-colour progress bar with marching diagonal stripes (goals, habits).

    ``segments`` = [(count, color, label), ...] laid out from the start edge (right in RTL); whatever is left of
    ``total`` stays as the empty track. The stripes only move while ``animated`` and the widget is on screen -
    every bar shares one clock (``anim.stripe_watch``) that pauses when the app is not the active window.
    """

    BAR_H = 8
    LEGEND_H = 18

    def __init__(self, segments, total: float, animated: bool = True, legend: bool = True,
                 rest_label: str = "باقی‌مانده", unit: str = "", parent=None):
        super().__init__(parent)
        self.segments = [(float(n), QColor(c), str(t)) for n, c, t in segments if n > 0]
        self.total = max(float(total), sum(n for n, _c, _t in self.segments), 1e-9)
        self.animated, self.legend, self.rest_label = animated, legend, rest_label
        self.unit = (" " + unit) if unit else ""
        self._a = _Anim(self, 0.0, 900, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._g = _Anim(self, 1.0, 900, QEasingCurve(QEasingCurve.Type.InOutQuad))   # one glint after the fill lands
        self._a.a.finished.connect(self._glint)
        self._a.to(1.0)
        self.setFixedHeight(self.BAR_H + (self.LEGEND_H + 8 if legend else 0))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        rest = self.total - sum(n for n, _c, _t in self.segments)
        parts = [f"{t} {jalali.fa(round(n))}{self.unit}" for n, _c, t in self.segments]
        if rest > 0.5:
            parts.append(f"{rest_label} {jalali.fa(round(rest))}{self.unit}")
        self.setToolTip("  ·  ".join(parts))
        self.setAccessibleName("پیشرفت: " + "، ".join(parts))

    def _glint(self) -> None:
        if MOTION[0] and self.filled > 0.003 and self.isVisible():
            self._g.set(0.0)
            self._g.to(1.0)

    @property
    def filled(self) -> float:
        """Fraction of the bar covered by segments (0..1)."""
        return sum(n for n, _c, _t in self.segments) / self.total

    def showEvent(self, e) -> None:  # noqa: N802
        if self.animated and self.filled < 0.999:
            stripe_watch(self, True)
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        stripe_watch(self, False)
        super().hideEvent(e)

    def _rest(self) -> float:
        return max(0.0, self.total - sum(n for n, _c, _t in self.segments))

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        dark = QColor(pal["bg"]).lightness() < 128
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = float(self.width()), float(self.BAR_H)
        bar = QRectF(0, 0, W, H)
        clip = QPainterPath()
        clip.addRoundedRect(bar, H / 2, H / 2)
        track = mix(QColor(pal["panel2"]), QColor(pal["line"]), 0.65)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawPath(clip)
        p.save()
        p.setClipPath(clip)
        # inner shadow of the empty track
        sh = QLinearGradient(0, 0, 0, H)
        sh.setColorAt(0, QColor(0, 0, 0, 46 if dark else 26))
        sh.setColorAt(0.5, QColor(0, 0, 0, 0))
        p.setBrush(sh)
        p.drawRect(bar)
        k = self._a.value
        phase = stripe_phase() if self.animated and MOTION[0] else 0.0
        x = W
        edges: list[float] = []
        for n, color, _t in self.segments:
            w = W * n / self.total * k
            if w < 0.5:
                continue
            r = QRectF(x - w, 0, w, H)
            g = QLinearGradient(0, 0, 0, H)
            g.setColorAt(0, mix(color, QColor("#ffffff"), 0.08))
            g.setColorAt(1, color)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRect(r)
            p.save()                                                        # diagonal stripes, marching toward the far end
            p.setClipRect(r, Qt.ClipOperation.IntersectClip)
            p.setPen(QPen(QColor(255, 255, 255, 26 if dark else 38), 4.0, cap=Qt.PenCapStyle.FlatCap))
            step = STRIPE_PERIOD
            sx = math.floor((r.left() - H * 2) / step) * step - phase        # anchored to the bar, not to the segment
            while sx < r.right() + H:
                p.drawLine(QPointF(sx, H + 1), QPointF(sx + H + 2, -1))
                sx += step
            p.restore()
            edges.append(r.left())
            x -= w
        p.setPen(QPen(QColor(pal["panel"]), 2.0))                           # thin separators between the colours
        for ex in edges[:-1] if self._rest() <= 0.5 else edges:
            if 1 < ex < W - 1:
                p.drawLine(QPointF(ex, 0), QPointF(ex, H))
        p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        if 0.0 < self._g.value < 1.0 and self.filled > 0.003:               # the glint runs along what is filled
            g = self._g.value
            fw = W * self.filled * self._a.value
            cx = W - fw * g
            band = QLinearGradient(cx + 26, 0, cx - 26, 0)
            band.setColorAt(0, QColor(255, 255, 255, 0))
            band.setColorAt(0.5, QColor(255, 255, 255, 120 if dark else 150))
            band.setColorAt(1, QColor(255, 255, 255, 0))
            p.save()
            p.setClipPath(clip)
            p.setClipRect(QRectF(W - fw, 0, fw, H), Qt.ClipOperation.IntersectClip)
            p.fillRect(bar, band)
            if self.filled >= 0.999:                                          # complete: the whole bar breathes light once
                p.fillRect(bar, QColor(255, 255, 255, int(70 * math.sin(math.pi * g))))
            p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(alpha(pal["line"], 0.55), 1))
        p.drawPath(clip)
        if self.legend:
            self._paint_legend(p, pal)

    def _paint_legend(self, p: QPainter, pal: dict) -> None:
        f = _font(self, -1.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        items = [(c, f"{t} {jalali.fa(round(n))}{self.unit}") for n, c, t in self.segments]
        if self._rest() > 0.5:
            items.append((mix(QColor(pal["panel2"]), QColor(pal["line"]), 0.65), f"{self.rest_label} {jalali.fa(round(self._rest()))}{self.unit}"))
        x = float(self.width())
        y = self.BAR_H + 8
        for c, txt in items:
            tw = fm.horizontalAdvance(txt)
            if x - (tw + 22) < 0:
                break
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(x - 4, y + self.LEGEND_H / 2), 3.6, 3.6)
            p.setPen(QColor(pal["muted"]))
            p.drawText(QRectF(x - 12 - tw - 2, y, tw + 4, self.LEGEND_H), int(AL_R | Qt.AlignmentFlag.AlignVCenter), txt)
            x -= tw + 26


# ================================================================= cards ===
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QVBoxLayout  # noqa: E402

from ..core import logic  # noqa: E402
from .fx_widgets import AnimCheck, IconToolButton  # noqa: E402
from .theme import PALETTES  # noqa: E402
from .widgets import CardFrame, Heatmap, button, label  # noqa: E402


def _menu(parent: QWidget, anchor: QWidget, pal: dict, entries) -> None:
    m = pmenu(parent, pal, entries)
    m.exec(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))


class HabitCard(CardFrame):
    def __init__(self, page, h: dict, prev, opened: bool):
        super().__init__(lively=True)
        self.setObjectName("Card")
        self.hid = h["id"]
        pal = PALETTES[page.ctx.theme]
        color = accent_for(h["id"], pal)
        today = dt.date.today()
        st = logic.habit_stats(h)
        log = h.get("log") or {}
        done = logic.iso_day(today) in log
        goal = st["goal"]
        unit = "روز" if st["daily"] else "هفته"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 14, 14)
        outer.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.ring = HabitRing(color, min(1.0, st["week"] / goal), done, prev)
        self.ring.clicked.connect(lambda: page._tick(h, today))
        row.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        info = QVBoxLayout()
        info.setSpacing(7)
        info.addStretch(1)
        info.addWidget(label(h["name"], "H2"))
        chips = Chips()
        items = [(f"{jalali.fa(st['streak'])} {unit} رگه", "warn" if st["streak"] else "muted", "habits"),
                 (f"{jalali.fa(st['week'])}/{jalali.fa(goal)} این هفته", "success" if st["metWeek"] else color, "goals"),
                 ("رکورد شخصی!" if st["streak"] >= 3 and st["streak"] >= st["best"] else f"بهترین {jalali.fa(st['best'])}",
                  "warn" if st["streak"] >= 3 and st["streak"] >= st["best"] else "muted", "trophy")]
        chips.set_items(items)
        info.addWidget(chips)
        info.addStretch(1)
        row.addLayout(info, 1)
        self.strip = WeekStrip(log, color)
        self.strip.dayClicked.connect(lambda d: page._tick(h, d))
        row.addWidget(self.strip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.more = IconToolButton("dots", "گزینه‌ها", size=34)
        self.more.clicked.connect(lambda: _menu(self, self.more, PALETTES[page.ctx.theme], [
            ("edit", "ویرایش", lambda: page._edit(h), False), ("trash", "حذف", lambda: page._delete(h), True)]))
        self.exp = IconToolButton("chevron_up" if opened else "chevron", "سابقه‌ی یک سال", size=34)
        row.addWidget(self.exp, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(row)
        recent = max(0, st["month"] - st["week"])
        outer.addWidget(SegmentedProgress(
            [(st["week"], color, "این هفته"), (recent, distinct_color(pal, [color]), "هفته‌های قبل")], 30,
            animated=not st["metWeek"], rest_label="بدون ثبت", unit="روز"))
        self.heat_box = QWidget()
        hb = QVBoxLayout(self.heat_box)
        hb.setContentsMargins(0, 4, 0, 0)
        hb.setSpacing(6)
        hb.addWidget(label(f"سابقه‌ی یک سال اخیر  ·  {jalali.fa(len(log))} ثبت", "Muted"))
        hm = Heatmap(52, page.ctx.theme)
        hm.set_data(log, page.ctx.theme)
        hm.dayClicked.connect(lambda d: page._tick(h, d))
        hb.addWidget(hm)
        self.heat_box.setVisible(opened)
        outer.addWidget(self.heat_box)
        self.exp.clicked.connect(lambda: self._toggle(page))

    def _toggle(self, page) -> None:
        on = not self.heat_box.isVisible()
        self.heat_box.setVisible(on)
        self.exp.icon_name = "chevron_up" if on else "chevron"
        self.exp.update()
        (page._open.add if on else page._open.discard)(self.hid)


class GoalCard(CardFrame):
    SHOW = 4

    def __init__(self, page, g: dict, prev, expanded: bool):
        super().__init__(lively=True)
        self.setObjectName("Card")
        self.gid = g["id"]
        v = page.v
        pal = PALETTES[page.ctx.theme]
        by_goal = getattr(page, "by_goal", None)
        linked = by_goal.get(g["id"], []) if by_goal is not None else [x for x in v["tasks"] if x.get("goalId") == g["id"]]
        ms = g.get("ms") or []
        total = len(ms) + len(linked)
        done_n = sum(1 for m in ms if m.get("done")) + sum(1 for x in linked if x.get("done"))
        pct = round(done_n / total * 100) if total else None
        dl = logic.goal_days_left(g)
        complete = pct == 100
        color = QColor(pal["ok"]) if complete else QColor(pal["danger"]) if (dl is not None and dl < 0) else accent_for(g["id"], pal)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 14, 16)
        outer.setSpacing(12)
        row = QHBoxLayout()
        row.setSpacing(18)
        self.ring = GoalRing((pct or 0) / 100, color, prev)
        row.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(8)
        info.addWidget(label(g["title"], "H2", True))
        chips = Chips()
        items = [(dict(logic.GOAL_HORIZONS).get(g.get("horizon"), ""), "accent", "flag")]
        if complete:
            items.append(("تکمیل‌شده", "success", "trophy"))
        if dl is not None:
            rel = (f"{jalali.fa(dl)} روز مانده" if dl > 0 else "امروز" if dl == 0 else f"{jalali.fa(-dl)} روز عقب‌افتاده")
            tone = "danger" if dl < 0 else "warn" if dl <= 7 and not complete else "muted"
            items.append((rel, tone, "calendar"))
            items.append((jalali.label(g["deadline"], True), "muted", None))
        if ms:
            items.append((f"{jalali.fa(sum(1 for m in ms if m.get('done')))}/{jalali.fa(len(ms))} مرحله", "muted", "check"))
        if linked:
            items.append((f"{jalali.fa(sum(1 for x in linked if x.get('done')))}/{jalali.fa(len(linked))} تسک", "muted", "link"))
        chips.set_items(items)
        info.addWidget(chips)
        if g.get("desc"):
            info.addWidget(label(g["desc"], "Muted", True))
        row.addLayout(info, 1)
        more = IconToolButton("dots", "گزینه‌ها", size=34)
        more.clicked.connect(lambda: _menu(self, more, PALETTES[page.ctx.theme], [
            ("edit", "ویرایش", lambda: page._edit(g), False), ("trash", "حذف", lambda: page._delete(g), True)]))
        row.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(row)
        if total:
            m_done = sum(1 for m in ms if m.get("done"))
            t_done = sum(1 for x in linked if x.get("done"))
            today = dt.date.today()
            open_t = [x for x in linked if not x.get("done")]
            t_late = sum(1 for x in open_t if (logic.task_date(x) or dt.date.max) < today)
            t_doing = sum(1 for x in open_t if logic.kanban_status(x) == "doing" and (logic.task_date(x) or dt.date.max) >= today)
            c_ms = QColor(color)
            c_td = distinct_color(pal, [c_ms])
            c_dg = distinct_color(pal, [c_ms, c_td], ("warn", "accent", "accent2"))
            c_lt = distinct_color(pal, [c_ms, c_td, c_dg], ("danger", "warn"), gap=60)
            segs = [(m_done, c_ms, "مراحل"), (t_done, c_td, "تسک انجام‌شده"),
                    (t_doing, c_dg, "در حال انجام"), (t_late, c_lt, "عقب‌افتاده")]
            outer.addWidget(SegmentedProgress(segs, total, animated=not complete))
        else:
            outer.addWidget(label("برای دیدن پیشرفت، مرحله یا تسک وابسته اضافه کن.", "Muted"))
        shown = ms if expanded else ms[: self.SHOW]
        for m in shown:
            cb = AnimCheck(m["text"], strike=True)
            cb.setChecked(bool(m.get("done")))
            cb.toggled.connect(lambda on, m=m: page._ms(m, on))
            outer.addWidget(cb)
        if len(ms) > self.SHOW:
            more_b = button("نمایش کمتر" if expanded else f"نمایش همه‌ی مراحل ({jalali.fa(len(ms))})", "Link",
                            lambda: page._expand(g["id"]))
            more_b.setCursor(Qt.CursorShape.PointingHandCursor)
            outer.addWidget(more_b, 0, Qt.AlignmentFlag.AlignRight)


# ============================================================ empty states ===
def draw_empty_art(p: QPainter, cx: float, cy: float, pal: dict, icon: str, tilt: tuple = (0.0, 0.0)) -> None:
    """Empty-state illustration: the brand's line-art shield with the page's glyph; icons without a glyph get a soft disc."""
    from .brand import paint_empty_art
    if paint_empty_art(p, cx, cy, pal, icon, tilt=tilt):
        return
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i, rad in enumerate((46, 62, 80)):
        p.setPen(QPen(alpha(pal["line"], 0.9 - 0.28 * i), 1.0, Qt.PenStyle.DashLine if i == 1 else Qt.PenStyle.SolidLine))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
    p.setPen(Qt.PenStyle.NoPen)
    for ang, rad, sz, a in ((28, 62, 3.2, 0.9), (160, 80, 2.4, 0.6), (250, 46, 2.6, 0.8), (330, 80, 3.0, 0.5)):
        x, y = cx + rad * math.cos(math.radians(ang)), cy - rad * math.sin(math.radians(ang))
        p.setBrush(alpha(pal["accent2"], a * 0.8))
        p.drawEllipse(QPointF(x, y), sz, sz)
    p.setBrush(QColor(pal["soft"]))
    p.setPen(QPen(alpha(pal["accent2"], 0.35), 1))
    p.drawEllipse(QPointF(cx, cy), 34, 34)
    p.drawPixmap(int(cx - 16), int(cy - 16), icons.pixmap(icon, pal["acc_text"], 32))
    p.restore()


class EmptyArt(QWidget):
    """The empty-state illustration. While it is on screen the layers drift a few pixels with the pointer (a 33 ms poll that
    repaints only when the eased offset moved, and stops when hidden or with reduced motion)."""

    def __init__(self, icon: str, parent=None):
        super().__init__(parent)
        from .parallax import Follower
        self.icon = icon
        self.setFixedSize(190, 176)
        self.follow = Follower(self)
        self._poll = QTimer(self, interval=50)
        self._poll.timeout.connect(self._step)
        self._t0 = time.monotonic()
        self._idle = (0.0, 0.0)

    def _step(self) -> None:
        """Very slow idle breathing (one cycle ~16 s) on top of the pointer drift, so an empty page is quietly alive."""
        ph = (time.monotonic() - self._t0) * (2 * math.pi / 16.0)
        idle = (round(0.35 * math.sin(ph), 3), round(0.25 * math.cos(ph * 0.8), 3))
        moved = self.follow.step()
        if moved or idle != self._idle:
            self._idle = idle
            self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        if MOTION[0]:
            self._poll.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._poll.stop()
        super().hideEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_empty_art(p, self.width() / 2, self.height() / 2, _fpal(self), self.icon,
                       (self.follow.x + self._idle[0], self.follow.y + self._idle[1]))


def _paint_empty(view: QWidget, icon: str, title: str, sub: str) -> None:
    pal = _fpal(view)
    p = QPainter(view.viewport())
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(view.viewport().rect())
    cx, cy = r.center().x(), r.center().y() - 18
    if r.height() >= 250:
        draw_empty_art(p, cx, cy - 30, pal, icon)
    else:                                                   # a short view has no room for the orbits: just the disc
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["soft"]))
        p.drawEllipse(QPointF(cx, cy - 22), 34, 34)
        p.drawPixmap(int(cx - 16), int(cy - 22 - 16), icons.pixmap(icon, pal["acc_text"], 32))
    p.setPen(QColor(pal["text"]))
    p.setFont(_font(view, 1.5, True))
    p.drawText(QRectF(r.left(), cy + 30, r.width(), 28), Qt.AlignmentFlag.AlignCenter, title)
    p.setPen(QColor(pal["muted"]))
    p.setFont(_font(view, -0.5))
    p.drawText(QRectF(r.left() + 20, cy + 58, r.width() - 40, 44), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
               | Qt.TextFlag.TextWordWrap, sub)


from PyQt6.QtWidgets import QListWidget, QTableWidget  # noqa: E402


class EmptyList(QListWidget):
    """QListWidget that paints a friendly illustration + message when it has no items."""

    def __init__(self, icon: str, title: str, sub: str = "", parent=None):
        super().__init__(parent)
        self.empty = (icon, title, sub)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if self.count() == 0 and getattr(self, "overlay", None) is None:
            _paint_empty(self, *self.empty)


class EmptyTable(QTableWidget):
    def __init__(self, rows: int, cols: int, icon: str, title: str, sub: str = "", parent=None):
        super().__init__(rows, cols, parent)
        self.empty = (icon, title, sub)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        if self.rowCount() == 0:
            _paint_empty(self, *self.empty)


# ================================================================== focus ===
class FocusDial(QWidget):
    """Big circular timer: progress arc, time, mode label and 4 session dots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode, self.text, self.frac, self.running = "work", "25:00", 0.0, False
        self.sessions, self.label = 0, "زمان کار"
        self._f = _Anim(self, 0.0, 950, QEasingCurve(QEasingCurve.Type.Linear))
        self._pulse = _Anim(self, 0.0, 1600, QEasingCurve(QEasingCurve.Type.InOutSine))
        self._pulse.a.setLoopCount(-1)
        self._beat = _Anim(self, 1.0, 900, QEasingCurve(QEasingCurve.Type.OutCubic))   # the last ten seconds: one soft ring per second
        self._done = _Anim(self, 1.0, 1300, QEasingCurve(QEasingCurve.Type.OutCubic))  # the finish: one ring of light, once
        self.left = -1
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def finish(self) -> None:
        """A single ring of light spreads out from the dial when a session ends (skipped with reduced motion)."""
        if MOTION[0]:
            self._done.a.stop()
            self._done.set(0.0)
            self._done.to(1.0, 1300)
        self.update()

    def _beat_tick(self, left: int) -> None:
        if not (self.running and 0 < left <= 10 and MOTION[0]) or left == self.left:
            return
        self._beat.a.stop()
        self._beat.set(0.0)
        self._beat.to(1.0, 900)

    def set_state(self, text: str, frac: float, mode: str, running: bool, sessions: int, label: str, left: int = -1) -> None:
        self._beat_tick(left)
        self.left = left
        if frac < self._f.value - 0.05 or mode != self.mode:
            self._f.set(frac)
        else:
            self._f.to(frac, 950 if running else 300)
        self.text, self.frac, self.mode, self.running, self.sessions, self.label = text, frac, mode, running, sessions, label
        if running and self._pulse.a.state() != self._pulse.a.State.Running:
            self._pulse.a.setStartValue(0.0)
            self._pulse.a.setEndValue(1.0)
            self._pulse.a.start()
        elif not running:
            self._pulse.a.stop()
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        """A watch face for deep focus: a bezel of 60 ticks that light up as the time passes, a thin arc, big display
        numerals in fixed cells (they never jitter), and a very quiet breathing ring while it runs."""
        import math
        from PyQt6.QtGui import QFontMetrics, QRadialGradient
        pal = _fpal(self)
        work = self.mode == "work"
        col = QColor(pal["accent"] if work else pal["ok"])
        hi = QColor(pal["accent2"] if work else pal["ok"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        side = min(self.width(), self.height()) - 16
        c = QPointF(self.width() / 2, self.height() / 2)
        R = side / 2 - 26
        f = max(0.0, min(1.0, self._f.value))
        k = 0.5 + 0.5 * math_sin(self._pulse.a.currentValue() or 0.0) if self.running else 0.0
        vr = min(self.width(), self.height()) / 2                          # a pool of light in the dark: depth, not a flat page
        vg = QRadialGradient(c, vr)
        vg.setColorAt(0, alpha(col, 0.09 + 0.03 * k))
        vg.setColorAt(1, alpha(col, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(vg)
        p.drawEllipse(c, vr, vr)
        if self.running:                                                   # one slow breathing ring, nothing more
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(alpha(col, 0.05 + 0.10 * k), 1.2))
            p.drawEllipse(c, R + 30 + 5 * k, R + 30 + 5 * k)
        hot = self.running and 0 < self.left <= 10
        if hot and self._beat.value < 1.0:                                 # last ten seconds: a ring leaves the bezel each second
            b = self._beat.value
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(alpha(hi, 0.42 * (1 - b)), 1.6))
            p.drawEllipse(c, R + 24 + 16 * b, R + 24 + 16 * b)
        if self._done.value < 1.0:                                         # the finish: brand-metal ring, once
            d = self._done.value
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(alpha(hi, 0.85 * (1 - d)), 2.4 * (1 - d) + 0.6))
            p.drawEllipse(c, R + 10 + 46 * d, R + 10 + 46 * d)
        lit = int(f * 60 + 1e-6)
        for i in range(60):                                                # the bezel
            ang = math.radians(90 - i * 6)
            major = i % 5 == 0
            r0, r1 = R + 12, R + (24 if major else 19)
            on = i < lit or (i == 0 and f > 0)
            colr = alpha(hi if major else col, 0.95 if major else 0.6) if on else mix(QColor(pal["line"]), QColor(pal["bg"]), 0.0)
            p.setPen(QPen(colr, 2.0 if major else 1.2, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(c.x() + r0 * math.cos(ang), c.y() - r0 * math.sin(ang)),
                       QPointF(c.x() + r1 * math.cos(ang), c.y() - r1 * math.sin(ang)))
        ring = QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(mix(QColor(pal["panel2"]), QColor(pal["line"]), 0.6), 3))
        p.drawEllipse(ring)
        if f > 0.003:
            p.setPen(QPen(alpha(col, 0.16), 10, cap=Qt.PenCapStyle.RoundCap))           # soft glow under the arc
            p.drawArc(ring, 90 * 16, int(-f * 360 * 16))
            p.setPen(QPen(col, 3, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, int(-f * 360 * 16))
            ang = math.radians(90 - f * 360)
            hp = QPointF(c.x() + R * math.cos(ang), c.y() - R * math.sin(ang))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(hi, 0.22))
            p.drawEllipse(hp, 8, 8)
            p.setBrush(hi)
            p.drawEllipse(hp, 3.4, 3.4)
        p.setPen(QColor(pal["muted"]))
        p.setFont(_font(self, 0.5, False))
        p.drawText(QRectF(c.x() - R, c.y() - R * 0.62, 2 * R, 26), Qt.AlignmentFlag.AlignCenter, self.label)
        df = QFont(self.font())                                            # numerals: the UI face, light and tabular (Cormorant's "1" reads as "I")
        df.setPointSizeF(max(34.0, R / 2.7))
        df.setWeight(QFont.Weight.Light)
        df.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        try:
            df.setFeature("tnum", 1)
        except Exception:                                                  # pragma: no cover - older Qt
            pass
        p.setFont(df)
        fm = QFontMetrics(df)
        cell = max(fm.horizontalAdvance(ch) for ch in "0123456789")
        widths = [cell if ch.isdigit() else int(fm.horizontalAdvance(ch) * 0.9) for ch in self.text]
        x = c.x() - sum(widths) / 2
        base = c.y() + fm.ascent() * 0.30
        p.setPen(QColor(pal["text"]))
        for ch, w in zip(self.text, widths):
            p.drawText(QRectF(x, base - fm.ascent(), w, fm.height()), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, ch)
            x += w
        done = self.sessions % 4 if self.sessions % 4 or not self.sessions else 4
        for i in range(4):                                                 # four diamonds: the sessions of a cycle
            x0 = c.x() + (i - 1.5) * 22
            y0 = c.y() + R * 0.62
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col if i < done else mix(QColor(pal["line"]), QColor(pal["muted"]), 0.2))
            p.drawPolygon(QPolygonF([QPointF(x0, y0 - 5), QPointF(x0 + 4.5, y0), QPointF(x0, y0 + 5), QPointF(x0 - 4.5, y0)]))


def math_sin(t: float) -> float:
    import math
    return math.sin(t * 2 * math.pi)


class RoundButton(QWidget):
    """Big filled circular button (play/pause)."""
    clicked = pyqtSignal()

    def __init__(self, icon: str, size: int = 68, parent=None):
        super().__init__(parent)
        self.icon = icon
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._h = _Anim(self, 0.0, 150)
        self._down = False
        self.setAccessibleName("شروع / مکث")

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._down = True
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        was, self._down = self._down, False
        self.update()
        if was and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        acc = QColor(pal["accent"])
        base = mix(acc, QColor(pal["accent2"]), self._h.value)
        rad = self.width() / 2 - 3 - (1.5 if self._down else 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(acc, 0.18 * self._h.value))
        p.drawEllipse(c, rad + 3, rad + 3)
        p.setBrush(base)
        p.drawEllipse(c, rad, rad)
        s = int(self.width() * 0.42)
        p.drawPixmap(int(c.x() - s / 2 + (2 if self.icon == "play" else 0)), int(c.y() - s / 2),
                     icons.pixmap(self.icon, on_color(base).name(), s))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["text"]), 1.6))
            p.drawEllipse(c, rad + 3, rad + 3)


# ============================================================ task rows =====
from PyQt6.QtCore import QEvent  # noqa: E402
from PyQt6.QtWidgets import QStyle, QStyledItemDelegate  # noqa: E402



def is_checked(v) -> bool:
    """Whether a CheckStateRole value means "checked". A QListWidget's built-in model hands back the plain int ``2``, while a
    Python model returns the ``Qt.CheckState`` enum; ``2 == Qt.CheckState.Checked`` is False in PyQt6, so compare by value."""
    return int(getattr(v, "value", v) or 0) == Qt.CheckState.Checked.value


def paint_check(p: QPainter, r: QRectF, checked: bool, pal: dict, hover: bool = False, k: float | None = None) -> None:
    """Round check control used by task rows and the tasks table.

    ``k`` (0..1) is the progress of a running transition to ``checked``: the disc springs open, the tick is drawn
    stroke by stroke and a faint ring rushes outwards. ``None`` = at rest."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    acc = QColor(pal["accent"])
    if k is None:
        fill = tick = 1.0 if checked else 0.0
    elif checked:
        fill, tick = micro.ease("back", k / 0.55), micro.ease("out", (k - 0.18) / 0.55)
    else:
        fill = tick = 1.0 - micro.ease("out", k / 0.5)
    if fill < 0.999:                                                     # the empty ring, fading out as the disc grows
        edge = mix(QColor(pal["muted"]), acc, 0.6 if hover else 0.0)
        edge.setAlphaF(max(0.0, 1.0 - fill))
        p.setPen(QPen(edge, 1.6))
        p.setBrush(alpha(acc, 0.10) if hover and not checked else Qt.BrushStyle.NoBrush)
        p.drawEllipse(r.adjusted(0.8, 0.8, -0.8, -0.8))
    if fill > 0.01:
        d = r.width() * fill
        disc = QRectF(0, 0, d, d)
        disc.moveCenter(r.center())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(acc)
        p.drawEllipse(disc)
    if tick > 0.01:
        w, h, x0, y0 = r.width(), r.height(), r.left(), r.top()
        a, b, c = QPointF(x0 + w * 0.27, y0 + h * 0.53), QPointF(x0 + w * 0.43, y0 + h * 0.69), QPointF(x0 + w * 0.74, y0 + h * 0.34)
        l1, l2 = math.hypot(b.x() - a.x(), b.y() - a.y()), math.hypot(c.x() - b.x(), c.y() - b.y())
        cut = tick * (l1 + l2)
        path = QPainterPath(a)
        if cut <= l1:
            path.lineTo(a + (b - a) * (cut / l1))
        else:
            path.lineTo(b)
            path.lineTo(b + (c - b) * min(1.0, (cut - l1) / l2))
        pen = QPen(on_color(acc), max(1.6, w * 0.11))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    if k is not None and checked and k < 0.85:                           # the burst ring
        t = micro.ease("out", k / 0.85)
        ring = QRectF(0, 0, r.width() * (1.0 + 0.7 * t), r.height() * (1.0 + 0.7 * t))
        ring.moveCenter(r.center())
        p.setPen(QPen(alpha(acc, 0.55 * (1.0 - t)), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(ring)
    p.restore()


def _fly_from(view, local_center) -> None:
    """A task was completed at ``local_center`` (viewport coordinates): let the main window fly a light to its counter."""
    try:
        win = view.window()
        if hasattr(win, "fly_done"):
            win.fly_done(view.viewport().mapToGlobal(local_center.toPoint() if hasattr(local_center, "toPoint") else local_center))
    except RuntimeError:
        pass


class TaskRowDelegate(QStyledItemDelegate):
    """Today-page rows: round check, title (struck when done), meta line, priority/overdue accents.
    Roles: DisplayRole=title, UserRole=id, +1=meta text, +2=priority, +3=overdue, +6=colour hex. CheckStateRole = done.

    Live row: under the pointer a slim accent bar grows on the start edge and three quiet actions (edit, move, trash) slide
    in from the end side. They exist only when the window offers ``row_action(kind, task_id)``; the clock runs only while a
    row is easing in or out."""
    H = 58
    ACT = 26
    GAP = 4
    ACTIONS = ("edit", "later", "trash")

    def __init__(self, view=None):
        super().__init__(view)
        self.view = view
        self.hp: dict[str, float] = {}            # task id -> hover progress 0..1
        self.hover_key: str | None = None
        self.mouse = QPointF(-1, -1)
        self.clock = QTimer(self, interval=16)
        self.clock.timeout.connect(self._tick)
        self._vp = view.viewport() if view is not None else None
        if view is not None:
            self._vp.installEventFilter(self)
            view.setMouseTracking(True)

    # ----------------------------------------------------------------------------------------- hover clock ---
    def _enabled(self) -> bool:
        try:
            return self.view is not None and hasattr(self.view.window(), "row_action") and bool(MOTION[0] or True)
        except RuntimeError:
            return False

    def eventFilter(self, obj, ev):  # noqa: N802
        if self._vp is None or obj is not self._vp:
            return False
        t = ev.type()
        if t not in (QEvent.Type.MouseMove, QEvent.Type.Leave):
            return False
        try:
            return self._hover_event(ev, t)
        except RuntimeError:                                  # the view is being destroyed
            self.clock.stop()
            return False

    def _hover_event(self, ev, t) -> bool:
        if t == QEvent.Type.MouseMove:
            self.mouse = QPointF(ev.position())
            i = self.view.indexAt(ev.position().toPoint())
            key = i.data(Qt.ItemDataRole.UserRole) if i.isValid() else None
            if key != self.hover_key:
                self.hover_key = key
                self._kick()
            else:
                self.view.viewport().update()
        elif t == QEvent.Type.Leave and self.hover_key is not None:
            self.hover_key = None
            self.mouse = QPointF(-1, -1)
            self._kick()
        return False

    def _kick(self) -> None:
        if not MOTION[0]:
            self.hp = {self.hover_key: 1.0} if self.hover_key else {}
            self.view.viewport().update()
            return
        if not self.clock.isActive():
            self.clock.start()

    def _tick(self) -> None:
        moving = False
        for k in set(self.hp) | ({self.hover_key} if self.hover_key else set()):
            cur = self.hp.get(k, 0.0)
            goal = 1.0 if k == self.hover_key else 0.0
            nxt = cur + (goal - cur) * 0.32
            if abs(goal - nxt) < 0.02:
                nxt = goal
            else:
                moving = True
            if nxt == 0.0:
                self.hp.pop(k, None)
            else:
                self.hp[k] = nxt
        try:
            self.view.viewport().update()
        except RuntimeError:
            self.clock.stop()
            return
        if not moving:
            self.clock.stop()

    def reset(self) -> None:
        """The list was rebuilt: forget hover state (row ids may no longer exist)."""
        self.hp.clear()
        self.hover_key = None
        self.clock.stop()

    # ----------------------------------------------------------------------------------------------- geometry ---
    def sizeHint(self, opt, idx):  # noqa: N802
        return QSize(120, self.H)

    def _circle(self, rect: QRectF) -> QRectF:
        return QRectF(rect.right() - 14 - 24, rect.center().y() - 12, 24, 24)

    def action_rects(self, box: QRectF, k: float = 1.0) -> list[tuple[str, QRectF]]:
        """Where the three actions sit (end side = left in RTL); ``k`` slides them in from further out."""
        out = []
        x = box.left() + 10 - (1.0 - k) * 18
        for name in self.ACTIONS:
            out.append((name, QRectF(x, box.center().y() - self.ACT / 2, self.ACT, self.ACT)))
            x += self.ACT + self.GAP
        return out

    def _tip(self, name: str, idx) -> str:
        if name == "later":
            return "به امروز" if idx.data(Qt.ItemDataRole.UserRole + 3) else "به فردا"
        return {"edit": "ویرایش", "trash": "حذف (قابل واگرد)"}.get(name, "")

    def helpEvent(self, ev, view, opt, idx):  # noqa: N802
        if self._enabled() and idx.isValid():
            box = QRectF(opt.rect).adjusted(2, 2, -2, -2)
            for name, r in self.action_rects(box):
                if r.contains(QPointF(ev.pos())) and self.hp.get(idx.data(Qt.ItemDataRole.UserRole), 0.0) > 0.5:
                    QToolTip.showText(ev.globalPos(), self._tip(name, idx), view)
                    return True
        return super().helpEvent(ev, view, opt, idx)

    # -------------------------------------------------------------------------------------------------- paint ---
    def paint(self, p, opt, idx):  # noqa: D401
        pal = _fpal(opt.widget)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(opt.rect).adjusted(2, 2, -2, -2)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        hov = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        key = idx.data(Qt.ItemDataRole.UserRole)
        hk = self.hp.get(key, 0.0)
        live = self._enabled()
        if sel or hov:
            p.setPen(QPen(QColor(pal["accent"]), 1) if sel else Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["soft"]) if sel else QColor(pal["panel2"]))
            p.drawRoundedRect(box, rr(10), rr(10))
        done = is_checked(idx.data(Qt.ItemDataRole.CheckStateRole))
        pr = idx.data(Qt.ItemDataRole.UserRole + 2)
        ck = micro.check_k(opt.widget, key)
        c = self._circle(box)
        paint_check(p, c, done, pal, hov, ck[0] if ck else None)
        hexc = idx.data(Qt.ItemDataRole.UserRole + 6)
        stripe = hexc or ({"high": pal["danger"]}.get(pr))
        if stripe and not done:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(stripe))
            p.drawRoundedRect(QRectF(box.right() - 3, box.top() + 12, 3, box.height() - 24), 1.5, 1.5)
        elif hk > 0.01 and live and not done:                            # the accent bar grows from the middle of the edge
            full = box.height() - 24
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(pal["accent2"], 0.9))
            p.drawRoundedRect(QRectF(box.right() - 3, box.center().y() - full * hk / 2, 3, full * hk), 1.5, 1.5)
        left_pad = (self.ACT * 3 + self.GAP * 2 + 22) if live else 0
        tx = QRectF(box.left() + 12 + left_pad, box.top() + 7, c.left() - box.left() - 26 - left_pad, 24)
        f = QFont(opt.font)
        f.setBold(not done)
        f.setStrikeOut(done and ck is None)
        p.setFont(f)
        overdue = bool(idx.data(Qt.ItemDataRole.UserRole + 3))
        s = micro.sweep(*ck) if ck else (1.0 if done else 0.0)
        p.setPen(mix(QColor(pal["text"]), QColor(pal["muted"]), s))
        shown = p.fontMetrics().elidedText(idx.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideRight, int(tx.width()))
        p.drawText(tx, AL_R | Qt.AlignmentFlag.AlignVCenter, shown)
        if ck and s > 0.01:                                              # the strike sweeps in from the start edge
            tw = p.fontMetrics().horizontalAdvance(shown)
            fm = p.fontMetrics()
            y = tx.center().y() - fm.height() / 2 + fm.ascent() - fm.strikeOutPos()
            p.setPen(QPen(mix(QColor(pal["text"]), QColor(pal["muted"]), 0.6), fm.lineWidth()))
            p.drawLine(QPointF(tx.right(), y), QPointF(tx.right() - tw * s, y))
        meta = idx.data(Qt.ItemDataRole.UserRole + 1)
        if meta:
            f2 = QFont(opt.font)
            f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.5))
            p.setFont(f2)
            p.setPen(QColor(pal["danger"] if overdue and not done else pal["muted"]))
            p.drawText(QRectF(tx.left(), tx.bottom() - 1, tx.width(), 20), AL_R | Qt.AlignmentFlag.AlignVCenter, meta)
        if live and hk > 0.01:                                           # the actions slide in and fade up
            p.setOpacity(hk)
            for name, r in self.action_rects(box, hk):
                under = r.contains(self.mouse) and hk > 0.6
                p.setPen(Qt.PenStyle.NoPen)
                if under:
                    p.setBrush(alpha(pal["danger"], 0.16) if name == "trash" else QColor(pal["soft"]))
                    p.drawRoundedRect(r, min(rr(7), 9), min(rr(7), 9))
                ic = {"edit": "edit", "later": "calendar", "trash": "trash"}[name]
                colr = pal["danger"] if (name == "trash" and under) else (pal["text"] if under else pal["muted"])
                p.drawPixmap(int(r.center().x() - 8), int(r.center().y() - 8), icons.pixmap(ic, colr, 16))
        p.restore()

    def editorEvent(self, ev, model, opt, idx):  # noqa: N802
        if ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            box = QRectF(opt.rect).adjusted(2, 2, -2, -2)
            key = idx.data(Qt.ItemDataRole.UserRole)
            if self._enabled() and self.hp.get(key, 0.0) > 0.5:
                for name, r in self.action_rects(box):
                    if r.contains(ev.position()):
                        try:
                            self.view.window().row_action(name, key)
                        except RuntimeError:
                            pass
                        return True
            hit = self._circle(box).adjusted(-8, -8, 8, 8)
            if hit.contains(ev.position()):
                cur = is_checked(idx.data(Qt.ItemDataRole.CheckStateRole))
                micro.check_kick(opt.widget, key, not cur)
                if not cur:
                    _fly_from(opt.widget, self._circle(box).center())
                model.setData(idx, Qt.CheckState.Unchecked if cur else Qt.CheckState.Checked,
                              Qt.ItemDataRole.CheckStateRole)
                return True
        return False


class CheckCellDelegate(QStyledItemDelegate):
    """Round check for a table's checkbox column."""

    def paint(self, p, opt, idx):  # noqa: D401
        pal = _fpal(opt.widget)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        if sel:
            p.fillRect(opt.rect, QColor(pal["soft"]))
        r = QRectF(0, 0, 22, 22)
        r.moveCenter(QRectF(opt.rect).center())
        ck = micro.check_k(opt.widget, idx.data(Qt.ItemDataRole.UserRole))
        paint_check(p, r, is_checked(idx.data(Qt.ItemDataRole.CheckStateRole)), pal,
                    bool(opt.state & QStyle.StateFlag.State_MouseOver), ck[0] if ck else None)

    def sizeHint(self, opt, idx):  # noqa: N802
        return QSize(44, 42)

    def editorEvent(self, ev, model, opt, idx):  # noqa: N802
        if ev.type() == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            cur = is_checked(idx.data(Qt.ItemDataRole.CheckStateRole))
            micro.check_kick(opt.widget, idx.data(Qt.ItemDataRole.UserRole), not cur)
            if not cur:
                _fly_from(opt.widget, QRectF(opt.rect).center())
            model.setData(idx, Qt.CheckState.Unchecked if cur else Qt.CheckState.Checked,
                          Qt.ItemDataRole.CheckStateRole)
            return True
        return False


# ================================================================ dialogs ===
class _Badge(QWidget):
    def __init__(self, icon: str, tone: str = "accent", parent=None):
        super().__init__(parent)
        self.icon, self.tone = icon, tone
        self.setFixedSize(46, 46)

    def paintEvent(self, e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(pal.get(self.tone, pal["accent"]))
        bg = QColor(col)
        bg.setAlphaF(0.16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), rr(14), rr(14))
        p.drawPixmap(11, 11, icons.pixmap(self.icon, pal["acc_text"] if self.tone == "accent" else col.name(), 24))


def dialog_head(icon: str, title: str, sub: str = "", tone: str = "accent") -> QWidget:
    """Premium dialog header: soft icon badge + title + one-line subtitle + hairline."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(12)
    h = QHBoxLayout()
    h.setSpacing(14)
    h.addWidget(_Badge(icon, tone))
    col = QVBoxLayout()
    col.setSpacing(2)
    t = label(title, "H2")
    col.addWidget(t)
    if sub:
        col.addWidget(label(sub, "Muted", True))
    h.addLayout(col, 1)
    v.addLayout(h)
    hair = QFrame()
    hair.setObjectName("Hair")
    hair.setFixedHeight(1)
    v.addWidget(hair)
    return w


def add_head(dlg, icon: str, title: str, sub: str = "", tone: str = "accent") -> None:
    dlg.layout().insertWidget(0, dialog_head(icon, title, sub, tone))




MARK_RE = re.compile(r"==(?=\S)(.+?)(?<=\S)==")          # ==highlighted text==  (same syntax as Obsidian/Markdown-it)


class NoteEditor(QPlainTextEdit):
    """Notepad-style editor: faint ruled lines under every text line (and continuing down the empty page), a margin
    line on the start side and an animated marker pen: text written as ==this== is painted with a highlighter stroke
    that sweeps across when it appears (and again whenever a note is opened). While no note is selected (widget
    disabled) it shows a friendly illustration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rule: QColor | None = None
        self._margin: QColor | None = None
        self._margin_x = 0
        self._marks: dict[str, float] = {}               # highlighted text -> when its stroke started
        self._mark_timer = QTimer(self, singleShot=True, interval=16)
        self._mark_timer.timeout.connect(self.viewport().update)
        self._dim_timer = QTimer(self, singleShot=True, interval=0)
        self._dim_timer.timeout.connect(self._dim_delimiters)
        self.textChanged.connect(self._dim_timer.start)
        # Qt's "left" alignment is absolute, so a right-to-left page has to ask for the right edge explicitly;
        # the direction stays automatic so an English paragraph still runs left-to-right inside it.
        opt = self.document().defaultTextOption()
        opt.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
        opt.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.document().setDefaultTextOption(opt)
        self.document().setDocumentMargin(8)

    def set_paper(self, rule: QColor | None, margin: QColor | None, margin_x: int = 0) -> None:
        """rule = ruled-line colour, margin = colour of the vertical page-margin line drawn on the viewport's right
        edge (the blank strip beyond it is the widget's own padding)."""
        self._rule, self._margin, self._margin_x = rule, margin, margin_x
        self.viewport().update()

    # ------------------------------------------------------------- marker ---
    def setPlainText(self, text: str) -> None:  # noqa: N802
        self._marks.clear()                                 # every stroke sweeps again when a note is opened
        super().setPlainText(text)

    def reset_marks(self) -> None:
        self._marks.clear()
        self.viewport().update()

    def _mark_color(self) -> QColor:
        return marker_color(_fpal(self.parentWidget() or self))

    def _dim_delimiters(self) -> None:
        """Fade the '==' delimiters so the highlighted text reads cleanly."""
        sels = []
        pal = _fpal(self.parentWidget() or self)
        dim = alpha(pal["muted"], 0.55)
        text = self.toPlainText()
        if "==" in text and len(text) < 200_000:
            for m in MARK_RE.finditer(text):
                for pos in (m.start(), m.end() - 2):
                    sel = QTextEdit.ExtraSelection()
                    cur = self.textCursor()
                    cur.setPosition(pos)
                    cur.setPosition(pos + 2, cur.MoveMode.KeepAnchor)
                    sel.cursor = cur
                    fmt = QTextCharFormat()
                    fmt.setForeground(dim)
                    sel.format = fmt
                    sels.append(sel)
        self.setExtraSelections(sels)

    def _paint_marks(self) -> bool:
        """Paint marker strokes under the text. Returns True while any stroke is still sweeping."""
        vp = self.viewport()
        vh = vp.height()
        off = self.contentOffset()
        block = self.firstVisibleBlock()
        now = time.monotonic()
        color = self._mark_color()
        animating = False
        p = None
        order = 0
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(off)
            if geo.top() > vh:
                break
            text = block.text()
            if "==" in text:
                lay = block.layout()
                rtl = block.textDirection() == Qt.LayoutDirection.RightToLeft
                for m in MARK_RE.finditer(text):
                    key = m.group(0)
                    t0 = self._marks.setdefault(key, now + 0.05 * order)
                    order += 1
                    k = mark_progress(t0, now)
                    if k < 1.0:
                        animating = True
                    if k <= 0.0:
                        continue
                    if p is None:
                        p = QPainter(vp)
                        p.setRenderHint(QPainter.RenderHint.Antialiasing)
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(color)
                    for i in range(lay.lineCount()):
                        ln = lay.lineAt(i)
                        lo, hi = max(m.start(), ln.textStart()), min(m.end(), ln.textStart() + ln.textLength())
                        if lo >= hi:
                            continue
                        x0, x1 = span_x(ln, lo, hi)
                        y = geo.top() + ln.y()
                        p.drawRoundedRect(sweep_rect(geo.left() + x0, geo.left() + x1, y + 1, ln.height() - 2, k, rtl), 3, 3)
            block = block.next()
        if p is not None:
            p.end()
        return animating

    def paintEvent(self, e) -> None:  # noqa: N802
        if self.isEnabled() and "==" in self.toPlainText()[:200_000]:
            if self._paint_marks():
                self._mark_timer.start()
        super().paintEvent(e)
        if not self.isEnabled():
            _paint_empty(self, "notes", "یادداشتی انتخاب نشده", "یکی از یادداشت‌ها را باز کن یا «یادداشت جدید» را بزن.")
            return
        if self._rule is None:
            return
        p = QPainter(self.viewport())
        vw, vh = self.viewport().width(), self.viewport().height()
        off = self.contentOffset()
        pitch = max(14.0, float(self.fontMetrics().lineSpacing()))
        p.setPen(QPen(self._rule, 1))
        last = 0.0
        block = self.firstVisibleBlock()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(off)
            if geo.top() > vh:
                break
            lay = block.layout()
            for i in range(lay.lineCount()):
                ln = lay.lineAt(i)
                pitch = max(14.0, ln.height())                   # the real line pitch (font leading included)
                y = round(geo.top() + ln.y() + ln.height()) + 0.5
                if 0 <= y <= vh:
                    p.drawLine(QPointF(0, y), QPointF(vw, y))
                last = max(last, y)
            block = block.next()
        y = last + pitch if last else off.y() + pitch + 4
        while y < vh:                                        # keep ruling the blank page
            p.drawLine(QPointF(0, y), QPointF(vw, y))
            y += pitch
        if self._margin is not None:
            p.setPen(QPen(self._margin, 1))
            x = vw - self._margin_x - 0.5
            p.drawLine(QPointF(x, 0), QPointF(x, vh))


# ================================================================= brand ===
class BrandMark(QWidget):
    """The Aegis monogram (gilt shield + arch 'A' on obsidian), painted in the active theme's accent - see brand.paint_mark."""

    def __init__(self, size: int = 38, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.status = False                          # True: a small gilt "vault open" dot on the corner

    def paintEvent(self, e) -> None:  # noqa: N802
        from .brand import paint_mark
        pal = _fpal(self)
        p = QPainter(self)
        paint_mark(p, QRectF(self.rect()), pal)
        if self.status:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            s = float(self.width())
            d = max(7.0, s * 0.27)
            box = QRectF(s - d - 0.5, s - d - 0.5, d, d)
            p.setPen(QPen(QColor(pal["panel"]), max(1.5, s * 0.05)))
            p.setBrush(QColor(pal["accent2"]))
            p.drawEllipse(box)


def pmenu(parent: QWidget, pal: dict, entries) -> "QMenu":
    """Premium context menu. entries: (icon, text, slot, danger) tuples; None inserts a separator."""
    m = style_menu(QMenu(parent))
    m.aboutToHide.connect(m.deleteLater)                # one right-click, one menu: never a hidden one left on the page
    for ent in entries:
        if ent is None:
            m.addSeparator()
            continue
        icon, text, slot, danger = ent
        col = pal["danger"] if danger else pal["muted"]
        act = m.addAction(icons.icon(icon, col, 16), text)
        act.triggered.connect(lambda _=False, s=slot: s())
    return m


def style_menu(m: "QMenu") -> "QMenu":
    """Rounded, frameless popup so every menu in the app shares one premium look."""
    m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return m
