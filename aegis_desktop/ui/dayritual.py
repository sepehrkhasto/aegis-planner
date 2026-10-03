# SPDX-License-Identifier: GPL-3.0-or-later
"""The day-start ritual: the first time the vault opens each day, a calm card says good morning and what today holds.
Once per day, never during a first run, Esc / Enter / a click closes it, and it can be switched off in Settings."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPolygonF
from PyQt6.QtWidgets import QWidget

from ..core import jalali, logic
from ..core.jalali import fa
from . import brand
from .ambient import greeting
from .anim import MOTION
from .fx_widgets import _fpal
from .theme import AL_R

PREF_ON, PREF_DATE = "day_ritual", "day_ritual_date"


def day_facts(vault: dict, today: dt.date) -> dict:
    """What today holds: how many tasks, the first one to face, what is overdue, how many habits wait."""
    todays = [x for x in logic.tasks_on(vault, today) if not x.get("done")]
    timed = [x for x in todays if x.get("timeFrom")]
    if timed:
        first = timed[0]
    else:
        rank = {"high": 0, "normal": 1, "low": 2}
        first = min(todays, key=lambda x: (rank.get(x.get("pr") or "normal", 1), x.get("title", ""))) if todays else None
    habits = [h for h in vault.get("habits", []) if not (h.get("log") or {}).get(today.isoformat())]
    return {"count": len(todays), "first": (first or {}).get("title") or "", "first_time": (first or {}).get("timeFrom") or "",
            "overdue": sum(1 for x in vault.get("tasks", []) if logic.is_overdue(x, today)), "habits": len(habits)}


def day_lines(f: dict) -> list[str]:
    out = [f"امروز {fa(f['count'])} کار پیش رو داری." if f["count"] else "امروز کاری نداری؛ روزِ آزاد است."]
    if f["first"]:
        t = f["first"] if len(f["first"]) <= 34 else f["first"][:33] + "…"
        out.append(f"اول از همه: «{t}»" + (f" — ساعت {fa(f['first_time'])}" if f["first_time"] else ""))
    if f["overdue"]:
        out.append(f"{fa(f['overdue'])} کار عقب‌افتاده منتظر است.")
    if f["habits"]:
        out.append(f"{fa(f['habits'])} عادت برای امروز مانده.")
    return out[:4]


def should_show(prefs: dict, today: dt.date) -> bool:
    return bool(prefs.get(PREF_ON, True)) and prefs.get(PREF_DATE) != today.isoformat()


class DayStart(QWidget):
    W, PAD = 500.0, 30.0

    def __init__(self, host: QWidget, facts: dict, today: dt.date, on_close=None):
        super().__init__(host)
        self.host, self.facts, self.today, self.on_close = host, facts, today, on_close
        self.lines = day_lines(facts)
        self.k, self._closing, self._hover = 0.0, False, False
        self.setGeometry(host.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("شروع روز")
        self.setAccessibleDescription(" ".join(self.lines))
        self.an = QVariantAnimation(self)
        self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self._done)
        host.installEventFilter(self)

    # ---------------------------------------------------------------- life ---
    def eventFilter(self, o, e):  # noqa: N802
        host = getattr(self, "host", None)
        if host is not None and o is host and e.type() == e.Type.Resize:
            self.setGeometry(host.rect())
        return False

    def open(self) -> None:
        self.show()
        self.raise_()
        self.setFocus()
        if MOTION[0]:
            self.an.stop()
            self.an.setStartValue(0.0)
            self.an.setEndValue(1.0)
            self.an.setDuration(380)
            self.an.start()
        else:
            self.k = 1.0
            self.update()

    def close_ritual(self) -> None:
        if self._closing:
            return
        self._closing = True
        if MOTION[0] and self.isVisible():
            self.an.stop()
            self.an.setStartValue(self.k)
            self.an.setEndValue(0.0)
            self.an.setDuration(200)
            self.an.start()
        else:
            self._done()

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def _done(self) -> None:
        if self._closing or self.k <= 0.0:
            self.hide()
            self.host.removeEventFilter(self)
            cb, self.on_close = self.on_close, None
            self.deleteLater()
            if cb:
                cb()

    # ------------------------------------------------------------- input ---
    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.close_ritual()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.close_ritual()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._button().contains(e.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)
            self.update()

    # ----------------------------------------------------------- painting ---
    def _card(self) -> QRectF:
        h = 250.0 + 27.0 * len(self.lines)
        return QRectF((self.width() - self.W) / 2, (self.height() - h) / 2 - 10, self.W, h)

    def _button(self) -> QRectF:
        c = self._card()
        return QRectF(c.center().x() - 78, c.bottom() - 62, 156, 38)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self.host)
        k = max(0.0, min(1.0, self.k))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bg = QColor(pal["bg"])
        bg.setAlphaF(0.90 * k)
        p.fillRect(self.rect(), bg)
        c = self._card()
        rise = (1.0 - k) * 16
        p.setOpacity(k)
        p.translate(0, rise)
        dark = QColor(pal["bg"]).lightness() < 128
        acc = QColor(pal["accent"])
        for dy, grow, a in ((6.0, 0.0, 0.22), (16.0, 8.0, 0.12), (30.0, 16.0, 0.06)):        # a soft floor shadow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(255 * a * (1.0 if dark else 0.5))))
            p.drawRoundedRect(c.adjusted(-grow, -grow, grow, grow).translated(0, dy), 22 + grow, 22 + grow)
        g = QLinearGradient(c.topLeft(), c.bottomLeft())
        g.setColorAt(0, brand._mix(QColor(pal["panel"]), acc, 0.08 if dark else 0.03))
        g.setColorAt(1, QColor(pal["panel"]))
        p.setBrush(g)
        p.setPen(brand.metal_pen(c.topLeft(), c.bottomRight(), pal, 1.6))
        p.drawRoundedRect(c, 22, 22)
        brand.paint_crest(p, c, pal, inset=12.0, arm=9.0, alpha=140)
        cx = c.center().x()
        brand.paint_mark(p, QRectF(cx - 27, c.top() + 26, 54, 54), pal)
        gf = QFont("Vazirmatn")
        gf.setPointSizeF(21)
        gf.setWeight(QFont.Weight.Bold)
        p.setFont(gf)
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(c.left(), c.top() + 88, c.width(), 38), int(Qt.AlignmentFlag.AlignCenter), greeting())
        j = jalali.date_to_due(self.today)
        p.setFont(self._f(10.5))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(c.left(), c.top() + 126, c.width(), 22), int(Qt.AlignmentFlag.AlignCenter),
                   f"{jalali.WEEKDAYS_FA[jalali.weekday_index(self.today)]} {fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} {fa(j['jy'])}")
        from .letterhead import rule
        rule(p, c.left() + 60, c.right() - 60, c.top() + 160, pal)
        y = c.top() + 176
        p.setFont(self._f(11))
        for ln in self.lines:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(brand.metal(QPointF(c.right() - self.PAD - 8, y), QPointF(c.right() - self.PAD, y + 8), pal))
            p.drawPolygon(QPolygonF([QPointF(c.right() - self.PAD - 3, y + 4), QPointF(c.right() - self.PAD, y + 8),
                                     QPointF(c.right() - self.PAD - 3, y + 12), QPointF(c.right() - self.PAD - 6, y + 8)]))
            p.setPen(QColor(pal["text"]))
            p.drawText(QRectF(c.left() + self.PAD, y - 3, c.width() - 2 * self.PAD - 18, 22),
                       int(AL_R | Qt.AlignmentFlag.AlignVCenter), ln)
            y += 27
        b = self._button()
        fill = brand.metal(QPointF(b.left(), b.top()), QPointF(b.right(), b.bottom()), pal)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(b.adjusted(-2, -2, 2, 2) if self._hover else b, 19, 19)
        p.setFont(self._f(11, True))
        from .premium import on_color
        p.setPen(on_color(QColor(pal["accent2"])))
        p.drawText(b, int(Qt.AlignmentFlag.AlignCenter), "شروع روز")
        p.setFont(self._f(8.5))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(c.left(), c.bottom() - 20, c.width(), 16), int(Qt.AlignmentFlag.AlignCenter), "Esc برای بستن")

    @staticmethod
    def _f(pt: float, bold: bool = False) -> QFont:
        f = QFont("Vazirmatn")
        f.setPointSizeF(pt)
        f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        return f
