# SPDX-License-Identifier: GPL-3.0-or-later
"""The global quick-add box: a small glass field that floats over whatever you are doing, takes one line of text
(«فردا ساعت ۱۰ جلسه با استاد»), creates the task and dissolves. Opened by the global hotkey (see hotkey.py)."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QBrush, QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout

from ..core import jalali
from ..core.jalali import fa
from ..core.nlp import parse_quick
from . import icons, theme
from .anim import MOTION
from .theme import AL_R
from .theme import rr as _rad


class QuickAdd(QDialog):
    W, H = 640, 132

    def __init__(self, win):
        super().__init__(None)
        self.win = win
        self.setObjectName("QuickAdd")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setStyleSheet("#QuickAdd { background: transparent; }")
        self.setProperty("theme", win.theme)
        self.setFixedSize(self.W, self.H)
        self.locked = not win.store.is_unlocked
        self.hint, self.done = "", 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 26, 30, 44)
        self.q = QLineEdit()
        self.q.setPlaceholderText("چه کاری؟  مثلاً «فردا ساعت ۱۰ جلسه با استاد»")
        self.q.addAction(icons.icon("plus", theme.PALETTES[win.theme]["muted"], 18), QLineEdit.ActionPosition.TrailingPosition)
        self.q.setMinimumHeight(44)
        self.q.setEnabled(not self.locked)
        if self.locked:
            self.q.setPlaceholderText("ولت قفل است؛ برای افزودن، اول برنامه را باز کن")
        self.q.textChanged.connect(self._preview)
        self.q.returnPressed.connect(self.submit)
        lay.addWidget(self.q)
        self._pop = None
        self.setAccessibleName("افزودن سریع تسک")

    # ------------------------------------------------------------------------------------------ logic ---
    def _preview(self, text: str) -> None:
        """What Enter will create, in one quiet line under the field."""
        t = text.strip()
        if not t:
            self.hint = ""
        else:
            qt = parse_quick(t)
            bits = [qt.title or "تسک جدید"]
            if qt.due:
                d = jalali.due_to_date(qt.due)
                import datetime as dt
                delta = (d - dt.date.today()).days if d else None
                bits.append({0: "امروز", 1: "فردا", 2: "پس‌فردا"}.get(delta) or jalali.label(qt.due))
            if qt.time_from:
                bits.append(fa(qt.time_from))
            self.hint = " · ".join(bits)
        self.update()

    def submit(self) -> bool:
        text = self.q.text().strip()
        if self.locked or not text:
            return False
        qt = parse_quick(text)
        if not qt.title and not qt.due and not qt.time_from:
            qt.title = text
        self.win.quick_add(qt)
        self._finish()
        return True

    def _finish(self) -> None:
        """A short confirmation (the field dims, a check draws in), then the box is gone."""
        self.q.setEnabled(False)
        if not MOTION[0]:
            self.accept()
            return
        an = QVariantAnimation(self)
        an.setStartValue(0.0)
        an.setEndValue(1.0)
        an.setDuration(260)
        an.valueChanged.connect(self._set_done)
        an.finished.connect(lambda: QTimer.singleShot(120, self.accept))
        an.start()
        self._pop = an

    def _set_done(self, v) -> None:
        self.done = float(v)
        self.update()

    # ------------------------------------------------------------------------------------------ show ---
    def popup(self) -> None:
        """Centre on the screen the cursor is on, upper third; take focus even from another app."""
        from PyQt6.QtGui import QCursor
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.center().x() - self.W // 2, g.top() + int(g.height() * 0.24))
        self.show()
        self.raise_()
        self.activateWindow()
        self.q.setFocus()

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.WindowDeactivate and self.isVisible() and self.done == 0.0:
            QTimer.singleShot(150, self._maybe_dismiss)
        return super().event(ev)

    def _maybe_dismiss(self) -> None:
        if self.isVisible() and QApplication.platformName() != "offscreen" and QApplication.activeWindow() is not self:
            self.reject()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    # ----------------------------------------------------------------------------------------- paint ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = theme.PALETTES[self.win.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(22, 18, -22, -26)
        rad = min(_rad(16), 20)
        for i in range(9, 0, -1):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 7 + (9 - i)))
            p.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), rad + i, rad + i)
        base = QColor(pal["panel"])
        base.setAlphaF(0.95)
        p.setBrush(base)
        p.drawRoundedRect(r, rad, rad)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(255, 255, 255, 20 if QColor(pal["bg"]).lightness() < 128 else 60))
        g.setColorAt(0.3, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(pal["line"]).lighter(140), 1))
        p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), rad, rad)
        f = self.font()
        f.setPointSizeF(max(8.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        p.setPen(QColor(pal["muted"]))
        if self.locked:
            line = "ولت قفل است"
        elif self.hint:
            line = "↵  " + self.hint
        else:
            line = "Enter برای افزودن  ·  Esc برای بستن"
        tr = QRectF(r.left() + 20, r.bottom() - 34, r.width() - 40, 24)
        p.drawText(tr, AL_R | Qt.AlignmentFlag.AlignVCenter, line)
        if self.done > 0:                                              # confirmation: the field dims, a check draws in
            p.setBrush(QColor(pal["panel"]).darker(105))
            p.setOpacity(min(1.0, self.done * 1.4) * 0.92)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, rad, rad)
            p.setOpacity(1.0)
            c = r.center()
            k = max(0.0, min(1.0, (self.done - 0.25) / 0.75))
            p.setPen(QPen(QColor(pal["ok"]), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            a, b, d = (c.x() - 16, c.y() + 1), (c.x() - 5, c.y() + 12), (c.x() + 17, c.y() - 11)
            from PyQt6.QtCore import QPointF
            if k < 0.4:
                t = k / 0.4
                p.drawLine(QPointF(*a), QPointF(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            else:
                t = (k - 0.4) / 0.6
                p.drawLine(QPointF(*a), QPointF(*b))
                p.drawLine(QPointF(*b), QPointF(b[0] + (d[0] - b[0]) * t, b[1] + (d[1] - b[1]) * t))
