# SPDX-License-Identifier: GPL-3.0-or-later
"""Progressive disclosure for forms: the few fields everyone fills stay on top, the rest waits behind «گزینه‌های بیشتر».

``MoreSection`` is a quiet header row (hairline, label, a count of the options that are already set, a chevron that turns)
with a body that opens below it. While closed, the header names what is set («توضیحات · تکرار · ۲ برچسب») so nothing is
hidden by surprise. ``refit(dialog)`` lets a dialog grow or shrink to the new content and stay on screen.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QFormLayout, QSizePolicy, QVBoxLayout, QWidget

from ..core.jalali import fa
from .fx_widgets import _Anim, _fpal
from .micro import reveal
from .premium import alpha


class _Head(QWidget):
    H = 38
    clicked = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title, self.count, self.summary = title, 0, ""
        self.open = False
        self._turn = _Anim(self, 0.0, 200)
        self._hov = _Anim(self, 0.0, 140)
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAccessibleName(title)

    def set_open(self, on: bool, animate: bool = True) -> None:
        self.open = on
        if animate:
            self._turn.to(1.0 if on else 0.0)
        else:
            self._turn.set(1.0 if on else 0.0)
        self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hov.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hov.to(0.0)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, self.H)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rtl = self.isRightToLeft()
        h = self._hov.value
        w = self.width()
        cy = self.height() / 2.0
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawLine(QPointF(0, 0.5), QPointF(w, 0.5))
        ink = QColor(pal["text"]) if (self.open or self.hasFocus()) else QColor(pal["muted"])
        if h > 0.01 and not self.open:
            ink = QColor(int(ink.red() + (QColor(pal["text"]).red() - ink.red()) * h),
                         int(ink.green() + (QColor(pal["text"]).green() - ink.green()) * h),
                         int(ink.blue() + (QColor(pal["text"]).blue() - ink.blue()) * h))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(self.title)
        x = w - 2.0 if rtl else 2.0
        r = QRectF(x - tw, 0, tw, self.height()) if rtl else QRectF(x, 0, tw, self.height())
        p.setPen(ink)
        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignLeft, self.title)
        edge = r.left() if rtl else r.right()
        if self.count:                                                   # how many of the hidden options are set
            txt = fa(self.count)
            bw = max(18.0, QFontMetrics(self.font()).horizontalAdvance(txt) + 10)
            br = QRectF(edge - 8 - bw, cy - 9, bw, 18) if rtl else QRectF(edge + 8, cy - 9, bw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["accent"]))
            p.drawRoundedRect(br, 9, 9)
            bf = QFont(self.font())
            bf.setPointSizeF(max(7.5, bf.pointSizeF() - 1.5))
            bf.setBold(True)
            p.setFont(bf)
            p.setPen(QColor(pal["ink"]))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, txt)
            edge = br.left() if rtl else br.right()
        chev_w = 34.0
        if self.summary and not self.open:                                # closed: name what is inside
            sf = QFont(self.font())
            sf.setPointSizeF(max(8.0, sf.pointSizeF() - 1))
            p.setFont(sf)
            room = int(max(0.0, (edge - chev_w - 12) if rtl else (w - chev_w - edge - 12)) - 8)
            if room > 40:
                txt = QFontMetrics(sf).elidedText(self.summary, Qt.TextElideMode.ElideLeft if rtl else Qt.TextElideMode.ElideRight, room)
                sw = QFontMetrics(sf).horizontalAdvance(txt)
                sr = QRectF(edge - 10 - sw, 0, sw, self.height()) if rtl else QRectF(edge + 10, 0, sw, self.height())
                p.setPen(alpha(pal["muted"], 0.9))
                p.drawText(sr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignLeft, txt)
        c = QPointF(14.0, cy) if rtl else QPointF(w - 14.0, cy)          # the chevron sits on the end side and turns over when open
        t = self._turn.value
        sign = 1 - 2 * t                                                  # 1 (points down) -> -1 (points up)
        p.setPen(QPen(ink, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline([QPointF(c.x() - 4.5, c.y() - 2.2 * sign), QPointF(c.x(), c.y() + 2.2 * sign), QPointF(c.x() + 4.5, c.y() - 2.2 * sign)])
        if self.hasFocus():
            p.setPen(QPen(QColor(pal["accent2"]), 1.2, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 3, -1, -1), 6, 6)


class MoreSection(QWidget):
    """Header + a body that opens under it. Put the fields into ``self.form`` (a QFormLayout)."""
    toggled = pyqtSignal(bool)

    def __init__(self, title: str = "گزینه‌های بیشتر", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.head = _Head(title, self)
        self.head.clicked.connect(lambda: self.set_open(not self.body.isVisibleTo(self)))
        lay.addWidget(self.head)
        self.body = QWidget(self)
        self.body.setObjectName("MoreBody")
        self.body.setStyleSheet("QWidget#MoreBody { background: transparent; }")
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(0, 4, 0, 0)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.body.hide()
        lay.addWidget(self.body)

    # ---- state
    def is_open(self) -> bool:
        return self.body.isVisibleTo(self)

    def set_open(self, on: bool, animate: bool = True) -> None:
        if on == self.is_open():
            return
        self.body.setVisible(on)
        self.head.set_open(on, animate)
        if on and animate:
            reveal(self.body, 10, 240)
        self.toggled.emit(on)

    def set_state(self, names: list[str]) -> None:
        """``names`` = the hidden options that hold a value right now (shown as a count + a short list while closed)."""
        self.head.count = len(names)
        self.head.summary = " · ".join(names)
        self.head.update()

    def add_row(self, label, widget) -> None:
        self.form.addRow(label, widget)


def refit(dlg: QWidget) -> None:
    """Resize a dialog to its content after a section opened or closed, keeping it centred on where it was and on screen."""
    old = dlg.geometry()
    lay = dlg.layout()
    if lay is not None:
        lay.invalidate()
        lay.activate()
    scr = dlg.screen().availableGeometry() if dlg.screen() else None
    want = max(dlg.sizeHint().height(), dlg.minimumSizeHint().height())
    if scr is not None:
        want = min(want, scr.height() - 30)
    dlg.resize(dlg.width(), want)
    if scr is not None:
        y = old.center().y() - want // 2
        y = max(scr.top() + 12, min(y, scr.bottom() - want - 12))
        dlg.move(old.x(), y)
