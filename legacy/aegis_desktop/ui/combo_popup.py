# SPDX-License-Identifier: GPL-3.0-or-later
"""The drop-down list of a ``Combo``: a floating glass sheet instead of Qt's plain list.

Rows are painted here (one hover pill, a tick on the chosen row, muted disabled rows), the sheet fades and settles 6 px into
place, and the keyboard works as it does everywhere else: Up/Down/Home/End/PageUp/PageDown move, Enter/Space choose, Esc closes.
It opens under the closed combo (flipping above when the screen is short) and is aligned to the combo's end edge - the right
one in this right-to-left app.
"""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from . import anim
from .fx_widgets import _fpal, _mix
from .theme import AL_R, rr


def paint_glass(p: QPainter, r: QRectF, pal: dict, rad: float) -> bool:
    """The floating-sheet look shared by every popover: soft shadow, near-opaque panel, a sheen on top, a hairline edge.
    Returns True on a dark theme."""
    dark = QColor(pal["bg"]).lightness() < 128
    for i in range(9, 0, -1):                                              # soft shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, int((5 + (9 - i) * 1.4) * (1.0 if dark else 0.6))))
        p.drawRoundedRect(r.adjusted(-i, -i + 5, i, i + 5), rad + i, rad + i)
    base = QColor(pal["panel"])
    base.setAlphaF(0.97)
    p.setBrush(base)
    p.drawRoundedRect(r, rad, rad)
    g = QLinearGradient(0, r.top(), 0, r.top() + 60)
    g.setColorAt(0, QColor(255, 255, 255, 18 if dark else 70))
    g.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(g)
    p.drawRoundedRect(r, rad, rad)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_mix(QColor(pal["line"]), QColor(pal["muted"]), 0.25), 1))
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
    return dark


class ComboPopup(QWidget):
    ROW, PAD, SHADOW, MAX_ROWS, MIN_W = 38, 6, 22, 9, 150
    picked = pyqtSignal(int)

    def __init__(self, combo):
        super().__init__(combo.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.combo = combo
        self.setLayoutDirection(combo.layoutDirection())
        self.items = [(i, combo.itemText(i), combo.itemIcon(i), bool(combo.model().flags(combo.model().index(i, 0))
                                                                     & Qt.ItemFlag.ItemIsEnabled))
                      for i in range(combo.count())]
        self.cur = combo.currentIndex()
        self.hot = self.cur if self.cur >= 0 else self._step(-1, 1)
        self.off = 0.0                                           # scroll offset in px
        self.k = 1.0 if not anim.MOTION[0] else 0.0                  # 0 -> 1 while it opens
        self._pal = _fpal(combo)
        self._font = QFont(combo.font())
        self._wheel_acc = 0.0
        fm = QFontMetrics(self._font)
        text_w = max([fm.horizontalAdvance(t) for _i, t, _ic, _e in self.items] + [40])
        self.pw = max(combo.width(), self.MIN_W, text_w + 2 * (self.PAD + 14) + 34 + 8)
        n = max(1, min(len(self.items), self.MAX_ROWS))
        self.ph = n * self.ROW + 2 * self.PAD
        self.resize(self.pw + 2 * self.SHADOW, self.ph + 2 * self.SHADOW)
        self.place()
        self._an = QVariantAnimation(self)
        self._an.setDuration(150)
        self._an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._an.valueChanged.connect(self._tick)
        self._scroll_to(self.hot)

    # ----------------------------------------------------------------------------------------- geometry ---
    def place(self) -> None:
        c = self.combo
        base = c.mapToGlobal(QPoint(0, c.height()))
        rtl = c.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = base.x() + c.width() - self.pw if rtl else base.x()
        y = base.y() + 4
        scr = QGuiApplication.screenAt(c.mapToGlobal(QPoint(c.width() // 2, c.height() // 2))) or QGuiApplication.primaryScreen()
        av = scr.availableGeometry()
        x = max(av.left() + 4, min(x, av.right() - self.pw - 4))
        self._above = y + self.ph > av.bottom() - 4 and base.y() - c.height() - self.ph - 8 > av.top()
        if self._above:
            y = base.y() - c.height() - self.ph - 4
        self.move(x - self.SHADOW, y - self.SHADOW)

    def _panel(self) -> QRectF:
        return QRectF(self.SHADOW, self.SHADOW, self.pw, self.ph)

    def _visible_rows(self) -> int:
        return max(1, min(len(self.items), self.MAX_ROWS))

    def _max_off(self) -> float:
        return max(0.0, len(self.items) * self.ROW - self._visible_rows() * self.ROW)

    def _row_rect(self, i: int) -> QRectF:
        p = self._panel()
        return QRectF(p.left() + self.PAD, p.top() + self.PAD + i * self.ROW - self.off, p.width() - 2 * self.PAD, self.ROW)

    def _row_at(self, pt: QPointF) -> int:
        p = self._panel()
        if not (p.left() + self.PAD <= pt.x() <= p.right() - self.PAD and p.top() + self.PAD <= pt.y() <= p.bottom() - self.PAD):
            return -1
        i = int((pt.y() - p.top() - self.PAD + self.off) // self.ROW)
        return i if 0 <= i < len(self.items) else -1

    # ------------------------------------------------------------------------------------------ motion ---
    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.setFocus()
        if self.k < 1.0:
            self._an.setStartValue(0.0)
            self._an.setEndValue(1.0)
            self._an.start()

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def closeEvent(self, e) -> None:  # noqa: N802
        self._an.stop()
        try:
            self.combo._popup_closed()
        except RuntimeError:
            pass
        super().closeEvent(e)

    # ------------------------------------------------------------------------------------- navigation ---
    def _step(self, start: int, d: int) -> int:
        """The next enabled row from ``start`` in direction ``d`` (stays put at the ends)."""
        i = start + d
        while 0 <= i < len(self.items):
            if self.items[i][3]:
                return i
            i += d
        return start if 0 <= start < len(self.items) else -1

    def _scroll_to(self, i: int) -> None:
        if i < 0:
            return
        top, bot = i * self.ROW, (i + 1) * self.ROW
        if top < self.off:
            self.off = float(top)
        elif bot > self.off + self._visible_rows() * self.ROW:
            self.off = float(bot - self._visible_rows() * self.ROW)
        self.off = max(0.0, min(self.off, self._max_off()))

    def _choose(self, i: int) -> None:
        if not (0 <= i < len(self.items)) or not self.items[i][3]:
            return
        self.picked.emit(i)
        self.close()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.close()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._choose(self.hot)
        elif k == Qt.Key.Key_Down:
            self.hot = self._step(self.hot, 1)
        elif k == Qt.Key.Key_Up:
            self.hot = self._step(self.hot, -1)
        elif k == Qt.Key.Key_Home:
            self.hot = self._step(-1, 1)
        elif k == Qt.Key.Key_End:
            self.hot = self._step(len(self.items), -1)
        elif k == Qt.Key.Key_PageDown:
            self.hot = self._step(min(len(self.items) - 1, self.hot + self.MAX_ROWS - 1) - 1, 1)
        elif k == Qt.Key.Key_PageUp:
            self.hot = self._step(max(0, self.hot - self.MAX_ROWS + 1) + 1, -1)
        else:
            t = e.text().casefold()
            if t.strip():                                                         # type a letter: jump to the next row that starts with it
                for j in list(range(self.hot + 1, len(self.items))) + list(range(0, self.hot + 1)):
                    if self.items[j][3] and self.items[j][1].casefold().startswith(t):
                        self.hot = j
                        break
            else:
                super().keyPressEvent(e)
                return
        self._scroll_to(self.hot)
        self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = self._row_at(e.position())
        if i >= 0 and self.items[i][3] and i != self.hot:
            self.hot = i
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._row_at(e.position())
        if i < 0 and not self._panel().contains(e.position()):
            self.close()
            return
        e.accept()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        i = self._row_at(e.position())
        if i >= 0:
            self._choose(i)

    def wheelEvent(self, e) -> None:  # noqa: N802
        if self._max_off() <= 0:
            return
        self.off = max(0.0, min(self._max_off(), self.off - e.angleDelta().y() / 120.0 * self.ROW * 1.5))
        i = self._row_at(e.position())
        if i >= 0 and self.items[i][3]:
            self.hot = i
        self.update()

    # ---------------------------------------------------------------------------------------------- paint ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = self.k
        p.setOpacity(k)
        p.translate(0, (1.0 - k) * (6 if self._above else -6))
        r = self._panel()
        rad = min(rr(14), 16)
        dark = paint_glass(p, r, pal, rad)
        # rows (clipped to the sheet so a scrolled list never spills)
        clip = QPainterPath()
        clip.addRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)
        p.setClipPath(clip)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        for i, (idx, text, icon, enabled) in enumerate(self.items):
            rr_ = self._row_rect(i)
            if rr_.bottom() < r.top() or rr_.top() > r.bottom():
                continue
            chosen = idx == self.cur
            hot = i == self.hot and enabled
            if hot:
                pill = _mix(QColor(pal["panel"]), QColor(pal["text"]), 0.09 if dark else 0.06)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(pill)
                p.drawRoundedRect(rr_, min(rr(9), 11), min(rr(9), 11))
            if chosen:                                                           # a slim accent mark at the start edge
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["accent2"]))
                mx = rr_.right() - 3 if rtl else rr_.left()
                p.drawRoundedRect(QRectF(mx, rr_.center().y() - 8, 3, 16), 1.5, 1.5)
            inner = rr_.adjusted(14, 0, -14, 0)
            tick_w = 22
            tx = inner.adjusted(tick_w, 0, 0, 0) if rtl else inner.adjusted(0, 0, -tick_w, 0)
            if not icon.isNull():
                px = icon.pixmap(QSize(16, 16))
                ix = tx.right() - 16 if rtl else tx.left()
                p.drawPixmap(int(ix), int(rr_.center().y() - 8), px)
                tx = tx.adjusted(0, 0, -24, 0) if rtl else tx.adjusted(24, 0, 0, 0)
            f = QFont(self._font)
            f.setWeight(QFont.Weight.DemiBold if chosen else QFont.Weight.Normal)
            p.setFont(f)
            col = QColor(pal["text"] if enabled else pal["muted"])
            if enabled and not chosen and not hot:
                col = _mix(QColor(pal["text"]), QColor(pal["muted"]), 0.18)
            p.setPen(col)
            shown = QFontMetrics(f).elidedText(text, Qt.TextElideMode.ElideRight, int(tx.width()))
            p.drawText(tx, AL_R | Qt.AlignmentFlag.AlignVCenter, shown)
            if chosen:                                                           # the tick sits at the end edge
                cx = inner.left() + 8 if rtl else inner.right() - 8
                cy = rr_.center().y()
                p.setPen(QPen(QColor(pal["accent2"]), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
                p.drawPolyline([QPointF(cx - 5, cy + 0.5), QPointF(cx - 1.5, cy + 4), QPointF(cx + 5, cy - 3.5)])
        p.setClipping(False)
        if self._max_off() > 0:                                                  # a hairline scroll thumb on the end edge
            track = r.adjusted(0, self.PAD, 0, -self.PAD)
            th = max(24.0, track.height() * self._visible_rows() * self.ROW / (len(self.items) * self.ROW))
            ty = track.top() + (track.height() - th) * (self.off / self._max_off())
            tx0 = r.left() + 3 if rtl else r.right() - 5
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_mix(QColor(pal["muted"]), QColor(pal["panel"]), 0.5))
            p.drawRoundedRect(QRectF(tx0, ty, 2.5, th), 1.25, 1.25)
