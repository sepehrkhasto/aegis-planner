# SPDX-License-Identifier: GPL-3.0-or-later
"""Pagination control: «قبلی  ۱  ۲  ۳ … ۹  بعدی» (RTL: «قبلی» sits at the right / start edge).

Painted with QPainter like the rest of the app: the accent pill glides from the old page to the new one, hover
lifts a number, arrows / PageUp / PageDown / Home / End work once the control has focus. The whole widget hides
itself when everything fits on one page.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..core.jalali import fa
from .fx_widgets import _Anim, _fpal
from .premium import _font, alpha, mix
from .theme import AL_L, rr


def page_count(total: int, size: int) -> int:
    return max(1, math.ceil(max(0, total) / max(1, size)))


def page_items(cur: int, pages: int) -> list[int | None]:
    """Page numbers to show; ``None`` is an ellipsis. Never more than 7 entries: 1 … 4 5 6 … 10."""
    if pages <= 7:
        return list(range(1, pages + 1))
    lo, hi = max(2, cur - 1), min(pages - 1, cur + 1)
    if cur <= 3:
        lo, hi = 2, 4
    elif cur >= pages - 2:
        lo, hi = pages - 3, pages - 1
    out: list[int | None] = [1]
    if lo > 2:
        out.append(None)
    out.extend(range(lo, hi + 1))
    if hi < pages - 1:
        out.append(None)
    out.append(pages)
    return out


class Paginator(QWidget):
    pageChanged = pyqtSignal(int)                            # 1-based page number

    H, BTN, GAP = 40, 34, 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.page, self.pages, self.total, self.size = 1, 1, 0, 1
        self._hover: tuple[str, int] | None = None
        self._press: tuple[str, int] | None = None
        self._from: QRectF | None = None                     # where the accent pill glides from
        self._t = _Anim(self, 1.0, 300, QEasingCurve(QEasingCurve.Type.OutBack))
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAccessibleName("صفحه‌بندی")
        self.setVisible(False)

    # ------------------------------------------------------------ state ---
    def set_state(self, page: int, total: int, size: int) -> None:
        """Show ``page`` of a list with ``total`` rows, ``size`` rows per page (clamps ``page``)."""
        self.total, self.size = int(total), max(1, int(size))
        self.pages = page_count(self.total, self.size)
        new = max(1, min(int(page), self.pages))
        if new != self.page:
            self._from = self._active_rect()
            self.page = new
            self._t.set(0.0)
            self._t.to(1.0)
        self.setVisible(self.pages > 1)
        self.update()

    def go(self, page: int) -> None:
        page = max(1, min(int(page), self.pages))
        if page != self.page:
            self.set_state(page, self.total, self.size)
            self.pageChanged.emit(self.page)

    def range_text(self) -> str:
        lo = (self.page - 1) * self.size + 1
        hi = min(self.total, self.page * self.size)
        return f"{fa(lo)}–{fa(hi)} از {fa(self.total)}"

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(420, self.H)

    # ----------------------------------------------------------- layout ---
    def _cells(self) -> list[tuple[str, int, QRectF]]:
        """[(kind, value, rect)] from the right edge: prev, page numbers / ellipses, next."""
        fm = QFontMetrics(_font(self, 0, True))
        pw = fm.horizontalAdvance("قبلی") + 44
        nw = fm.horizontalAdvance("بعدی") + 44
        y = (self.height() - self.BTN) / 2
        x = float(self.width())
        out: list[tuple[str, int, QRectF]] = []
        x -= pw
        out.append(("prev", 0, QRectF(x, y, pw, self.BTN)))
        for it in page_items(self.page, self.pages):
            x -= self.GAP
            if it is None:
                x -= 22
                out.append(("gap", 0, QRectF(x, y, 22, self.BTN)))
            else:
                w = max(self.BTN, fm.horizontalAdvance(fa(it)) + 20)
                x -= w
                out.append(("page", it, QRectF(x, y, w, self.BTN)))
        x -= self.GAP + nw
        out.append(("next", 0, QRectF(x, y, nw, self.BTN)))
        return out

    def _active_rect(self) -> QRectF | None:
        for kind, v, r in self._cells():
            if kind == "page" and v == self.page:
                return r
        return None

    def _hit(self, pos: QPointF) -> tuple[str, int] | None:
        for kind, v, r in self._cells():
            if kind in ("prev", "next", "page") and r.contains(pos):
                if kind == "prev" and self.page <= 1 or kind == "next" and self.page >= self.pages:
                    return None
                return kind, v
        return None

    # ------------------------------------------------------------ input ---
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._hit(e.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = self._hit(e.position())
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        hit, self._press = self._press, None
        if hit and e.button() == Qt.MouseButton.LeftButton and self._hit(e.position()) == hit:
            kind, v = hit
            self.go(self.page - 1 if kind == "prev" else self.page + 1 if kind == "next" else v)
        self.update()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_PageUp):        # RTL: the right arrow goes back
            self.go(self.page - 1)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_PageDown):
            self.go(self.page + 1)
        elif k == Qt.Key.Key_Home:
            self.go(1)
        elif k == Qt.Key.Key_End:
            self.go(self.pages)
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------ paint ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        dark = QColor(pal["bg"]).lightness() < 128
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        f = _font(self, 0, True)
        p.setFont(f)
        cells = self._cells()
        rad = min(rr(11), 15.0)
        line, muted, text = QColor(pal["line"]), QColor(pal["muted"]), QColor(pal["text"])
        for kind, v, r in cells:                              # neutral buttons and hover
            if kind == "gap":
                p.setPen(muted)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, "…")
                continue
            off = kind == "prev" and self.page <= 1 or kind == "next" and self.page >= self.pages
            hov = self._hover == (kind, v) and not off
            down = self._press == (kind, v) and hov
            rr_ = r.adjusted(0, 1, 0, 0) if down else r
            if kind in ("prev", "next"):
                p.setOpacity(0.42 if off else 1.0)
                p.setPen(QPen(mix(line, QColor(pal["accent"]), 0.6 if hov else 0.0), 1))
                p.setBrush(alpha(pal["accent"], 0.10) if hov else QColor(pal["panel"]))
                p.drawRoundedRect(rr_, rad, rad)
                ink = QColor(pal["acc_text"]) if hov else text
                p.setPen(ink)
                label = "قبلی" if kind == "prev" else "بعدی"
                if kind == "prev":                            # arrow at the right, text next to it
                    self._chevron(p, QPointF(rr_.right() - 16, rr_.center().y()), +1, ink)
                    p.drawText(rr_.adjusted(8, 0, -30, 0), Qt.AlignmentFlag.AlignCenter, label)
                else:
                    self._chevron(p, QPointF(rr_.left() + 16, rr_.center().y()), -1, ink)
                    p.drawText(rr_.adjusted(30, 0, -8, 0), Qt.AlignmentFlag.AlignCenter, label)
                p.setOpacity(1.0)
            elif hov and v != self.page:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["accent"], 0.12))
                p.drawRoundedRect(rr_, rad, rad)
        act = self._active_rect()                             # the gliding accent pill
        if act is not None:
            t = max(0.0, min(1.12, self._t.value))
            a = act
            if self._from is not None and t != 1.0:                          # spring past the target and settle
                tw = min(1.0, t)
                a = QRectF(self._from.x() + (act.x() - self._from.x()) * t, act.y(),
                           self._from.width() + (act.width() - self._from.width()) * tw, act.height())
            if not dark:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 22))
                p.drawRoundedRect(a.translated(0, 2), rad, rad)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["accent"]))
            p.drawRoundedRect(a, rad, rad)
            p.setPen(QPen(QColor(255, 255, 255, 46 if dark else 70), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(a.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        for kind, v, r in cells:                              # numbers on top of the pill
            if kind == "page":
                p.setPen(mix(text, QColor(pal["ink"]), max(0.0, min(1.0, self._t.value))) if v == self.page else text)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, fa(v))
        if cells:                                             # "۹–۱۶ از ۲۳" at the far end when there is room
            left = cells[-1][2].left()
            if left > 150:
                p.setPen(muted)
                p.setFont(_font(self, -1))
                p.drawText(QRectF(0, 0, left - 12, self.height()), Qt.AlignmentFlag.AlignVCenter | AL_L, self.range_text())

    @staticmethod
    def _chevron(p: QPainter, c: QPointF, d: int, color: QColor) -> None:
        """Small chevron; d=+1 points right, d=-1 points left."""
        path = QPainterPath()
        path.moveTo(c.x() - 2.5 * d, c.y() - 4.5)
        path.lineTo(c.x() + 2.5 * d, c.y())
        path.lineTo(c.x() - 2.5 * d, c.y() + 4.5)
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 1.8, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        p.restore()
