# SPDX-License-Identifier: GPL-3.0-or-later
"""Animated, custom-painted widgets (ports of the chosen Uiverse.io designs).

Performance rules: no widget repaints while idle. Animations run only during
hover / click / focus transitions (QVariantAnimation), except the loader and the
search glow, which start their timer only while visible/focused.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QBrush, QLinearGradient, QPolygonF, QColor, QFont, QPainter, QPainterPath, QPen)
from PyQt6.QtWidgets import QAbstractButton, QComboBox, QHBoxLayout, QLineEdit, QSizePolicy, QToolTip, QWidget

CURVE_BACK = QEasingCurve(QEasingCurve.Type.OutBack)

from .theme import AL_L, AL_R
from .theme import rr as _rad
CURVE_SMOOTH = QEasingCurve(QEasingCurve.Type.InOutCubic)


def _fpal(w) -> dict:
    from .theme import PALETTES
    x = w
    while x is not None:
        t = getattr(x, "theme", None)
        if isinstance(t, str) and t in PALETTES:
            return PALETTES[t]
        x = x.parentWidget()
    return PALETTES["dark"]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(int(_lerp(c1.red(), c2.red(), t)), int(_lerp(c1.green(), c2.green(), t)),
                  int(_lerp(c1.blue(), c2.blue(), t)), int(_lerp(c1.alpha(), c2.alpha(), t)))


class _Anim:
    """Tiny helper: animate a float attribute on a widget and repaint."""

    def __init__(self, w: QWidget, value: float = 0.0, ms: int = 250, curve=CURVE_SMOOTH):
        self.w, self.value = w, float(value)
        self.a = QVariantAnimation(w)
        self.a.setDuration(ms)
        self.a.setEasingCurve(curve)
        self.a.valueChanged.connect(self._tick)

    def _tick(self, v) -> None:
        self.value = float(v)
        self.w.update()

    def to(self, target: float, ms: int | None = None) -> None:
        self.a.stop()
        if ms is not None:
            self.a.setDuration(ms)
        self.a.setStartValue(self.value)
        self.a.setEndValue(float(target))
        self.a.start()

    def set(self, v: float) -> None:
        self.a.stop()
        self.value = float(v)
        self.w.update()


# ----------------------------------------------------------------- pills ---
# ----------------------------------------------------------------- search ---
class _FocusEdit(QLineEdit):
    focused = pyqtSignal(bool)

    def focusInEvent(self, e) -> None:  # noqa: N802
        super().focusInEvent(e)
        self.focused.emit(True)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        super().focusOutEvent(e)
        self.focused.emit(False)


class GlowSearch(QWidget):
    """Search field: quiet 1px frame at rest, lifted frame on hover, accent focus ring (no perpetual motion)."""
    textChanged = pyqtSignal(str)

    def __init__(self, placeholder: str = "جست‌وجو…", parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit = _FocusEdit(self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrame(False)
        self.edit.setClearButtonEnabled(True)
        self.edit.setStyleSheet("QLineEdit{border:none;background:transparent;font-size:14px;padding:0;}")
        self.edit.setTextMargins(34, 0, 34, 0)                   # room for the glass (start) and the clear button (end)
        self.edit.textChanged.connect(self.textChanged)
        self.edit.focused.connect(self._on_focus)
        self.edit.setAccessibleName(placeholder.rstrip("…"))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hover, self._focus = _Anim(self, 0.0, 160), _Anim(self, 0.0, 200)
        self.edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFocusProxy(self.edit)

    # QLineEdit-like API
    def text(self) -> str:
        return self.edit.text()

    def setText(self, s: str) -> None:  # noqa: N802
        self.edit.setText(s)

    def clear(self) -> None:
        self.edit.clear()

    def setPlaceholderText(self, s: str) -> None:  # noqa: N802
        self.edit.setPlaceholderText(s)

    def setFocus(self, *a) -> None:  # noqa: N802
        self.edit.setFocus(*a)

    def _on_focus(self, on: bool) -> None:
        self._focus.to(1.0 if on else 0.0)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover.to(1.0)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover.to(0.0)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self.edit.setGeometry(2, 2, self.width() - 4, self.height() - 4)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fp = _fpal(self)
        f, h = self._focus.value, self._hover.value
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        rad = _rad(10)
        acc = QColor(fp["accent2"])
        if f > 0.01:                                             # soft focus halo just outside the frame
            halo = QColor(acc)
            halo.setAlphaF(0.22 * f)
            p.setPen(QPen(halo, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), rad + 1, rad + 1)
        line = QColor(fp["line"])
        edge = _mix(_mix(line, QColor(fp["muted"]), 0.45 * h), acc, f)
        p.setPen(QPen(edge, 1))
        p.setBrush(QColor(fp["panel"]))
        p.drawRoundedRect(r, rad, rad)
        icon = _mix(QColor(fp["muted"]), QColor(fp["text"]), max(f, 0.5 * h))
        p.setPen(QPen(icon, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cy, x = self.height() / 2, self.width() - 20
        p.drawEllipse(QPointF(x, cy - 1), 5.5, 5.5)
        p.drawLine(QPointF(x - 4.2, cy + 3.2), QPointF(x - 8, cy + 7))


# ----------------------------------------------------------------- loader ---
class BounceLoader(QWidget):
    """Three bouncing balls. Timer only runs while visible."""

    def __init__(self, color: str = "#ffffff", parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(90, 44)
        self._t = 0.0
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._step)

    def _step(self) -> None:
        self._t += 0.016
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._timer.start()

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(3):
            ph = (self._t / 0.5 - i * 0.2) % 2
            k = ph if ph < 1 else 2 - ph          # 0..1..0 alternate
            y = 30 - 22 * (1 - (1 - k) ** 2)
            x = 15 + i * 30
            sc = 0.6 + 0.4 * (1 - k)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(60 * sc)))
            p.drawEllipse(QPointF(x, 40), 8 * sc, 2.2 * sc)
            p.setBrush(self.color)
            p.drawEllipse(QPointF(x, y), 7, 7)


# ------------------------------------------------------------ color picker ---
TASK_COLORS = ["#e11d48", "#f472b6", "#fb923c", "#facc15", "#84cc16",
               "#10b981", "#0ea5e9", "#3b82f6", "#8b5cf6", "#a78bfa"]


class ColorSwatches(QWidget):
    """Ten swatches with dock-style hover magnification. Value = 'c0'..'c9'."""
    changed = pyqtSignal(str)

    def __init__(self, value: str = "c0", parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFixedHeight(46)
        self.setMinimumWidth(10 * 30)
        self.value = value if value in self.keys() else "c0"
        self._mx = -1000.0
        self._hi = _Anim(self, 0, 160)

    @staticmethod
    def keys() -> list[str]:
        return [f"c{i}" for i in range(len(TASK_COLORS))]

    def set_value(self, v: str) -> None:
        self.value = v if v in self.keys() else "c0"
        self.update()

    def _layout(self):
        n, base, gap = len(TASK_COLORS), 24.0, 6.0
        total = n * base + (n - 1) * gap
        x = (self.width() - total) / 2
        out = []
        for i in range(n):
            cx = x + base / 2 + i * (base + gap)
            d = abs(cx - self._mx)
            s = 1 + 0.55 * max(0.0, 1 - d / 60) ** 1.5 if self._mx > -500 else 1
            out.append((cx, base * s, s))
        return out

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self._mx = e.position().x()
        self.update()
        i = self._hit(e.position().x())
        if i is not None:
            QToolTip.showText(e.globalPosition().toPoint(), TASK_COLORS[i].upper(), self)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._mx = -1000
        self.update()

    def _hit(self, x: float):
        best, bi = 1e9, None
        for i, (cx, d, _s) in enumerate(self._layout()):
            if abs(cx - x) < d / 2 and abs(cx - x) < best:
                best, bi = abs(cx - x), i
        return bi

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._hit(e.position().x())
        if i is not None:
            self.value = f"c{i}"
            self.update()
            self.changed.emit(self.value)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base_y = self.height() - 8
        for i, (cx, d, s) in enumerate(self._layout()):
            r = QRectF(cx - d / 2, base_y - d - (s - 1) * 4, d, d)
            sel = self.value == f"c{i}"
            p.setPen(QPen(QColor(_fpal(self)["text"]), 2.2 if sel else 1.2))
            p.setBrush(QColor(TASK_COLORS[i]))
            p.drawRoundedRect(r, _rad(5), _rad(5))
            if sel:
                p.setPen(QPen(QColor("white"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                c = r.center()
                p.drawLine(QPointF(c.x() - 4, c.y()), QPointF(c.x() - 1, c.y() + 3.5))
                p.drawLine(QPointF(c.x() - 1, c.y() + 3.5), QPointF(c.x() + 5, c.y() - 3.5))


def color_hex(key: str | None) -> str | None:
    try:
        return TASK_COLORS[int((key or "")[1:])] if (key or "c0") != "c0" and key else None
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------- checkboxes ---
class AnimCheck(QAbstractButton):
    """Stroke-draw checkbox. If strike=True the label gets a sliding strike-through + burst dots."""

    def __init__(self, text: str = "", strike: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.strike = strike
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._t = _Anim(self, 0, 450)
        self._burst = _Anim(self, 0, 600, QEasingCurve(QEasingCurve.Type.OutCubic))
        self.toggled.connect(self._on)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _on(self, on: bool) -> None:
        self._t.to(1 if on else 0)
        if on:
            self._burst.set(0)
            self._burst.to(1)

    def setChecked(self, on: bool) -> None:  # noqa: N802
        was = self.blockSignals(True)
        super().setChecked(on)
        self.blockSignals(was)
        self._t.set(1 if on else 0)
        self._burst.set(1 if on else 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        w = 26 + (self.fontMetrics().horizontalAdvance(self.text()) + 10 if self.text() else 0)
        return QSize(w, 26)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        t = self._t.value
        S = 20.0
        x = self.width() - S - 3 if rtl else 3
        box = QRectF(x, (self.height() - S) / 2, S, S)
        fp = _fpal(self)
        accent = QColor(fp["accent"])
        idle = _mix(QColor(fp["line"]), QColor(fp["muted"]), 0.55)
        p.setPen(QPen(_mix(idle, accent, min(1, t * 1.5)), 2))
        tint = QColor(accent)
        tint.setAlpha(34)
        p.setBrush(_mix(QColor(0, 0, 0, 0), tint, t))
        p.drawRoundedRect(box.adjusted(1, 1, -1, -1), _rad(5), _rad(5))
        if t > 0.02:
            p.setPen(QPen(accent, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            c = box.center()
            pts = [QPointF(c.x() - 4.5, c.y() + 0.5), QPointF(c.x() - 1.2, c.y() + 4), QPointF(c.x() + 5, c.y() - 4)]
            f1 = min(1, t / 0.45)
            f2 = max(0, min(1, (t - 0.45) / 0.55))
            p.drawLine(pts[0], QPointF(_lerp(pts[0].x(), pts[1].x(), f1), _lerp(pts[0].y(), pts[1].y(), f1)))
            if f2 > 0:
                p.drawLine(pts[1], QPointF(_lerp(pts[1].x(), pts[2].x(), f2), _lerp(pts[1].y(), pts[2].y(), f2)))
        # burst dots
        b = self._burst.value
        if 0 < b < 0.98:
            c = box.center()
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(8):
                a = i * math.pi / 4
                rad = 11 + 7 * b
                p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), int(220 * (1 - b))))
                p.drawEllipse(QPointF(c.x() + math.cos(a) * rad, c.y() + math.sin(a) * rad), 1.8 * (1 - b) + .4, 1.8 * (1 - b) + .4)
        if self.text():
            tx = QRectF(4, 0, self.width() - S - 12, self.height()) if rtl else QRectF(S + 10, 0, self.width() - S - 10, self.height())
            col = _mix(QColor(fp["text"]), QColor(fp["muted"]), t)
            p.setPen(col)
            al = (AL_R if rtl else AL_L) | Qt.AlignmentFlag.AlignVCenter
            p.drawText(tx, al, self.text())
            if self.strike and t > 0:
                tw = self.fontMetrics().horizontalAdvance(self.text())
                y = self.height() / 2
                if rtl:
                    xr = tx.right()
                    p.drawLine(QPointF(xr, y), QPointF(xr - tw * t, y))
                else:
                    p.drawLine(QPointF(tx.left(), y), QPointF(tx.left() + tw * t, y))


# --------------------------------------------------------- small toggles ---
class _IconToggle(QAbstractButton):
    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        self._t = _Anim(self, 0, 350, CURVE_BACK)
        self._h = _Anim(self, 0, 150)
        self._pop = _Anim(self, 0, 500, QEasingCurve(QEasingCurve.Type.OutCubic))
        self.toggled.connect(self._on)

    def _on(self, on: bool) -> None:
        self._t.to(1 if on else 0)
        if on:
            self._pop.set(0)
            self._pop.to(1)

    def setChecked(self, on: bool) -> None:  # noqa: N802
        was = self.blockSignals(True)
        super().setChecked(on)
        self.blockSignals(was)
        self._t.set(1 if on else 0)
        self._pop.set(1 if on else 0)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0)

    def _ticks(self, p: QPainter, color: QColor, n: int, r0: float, r1: float) -> None:
        b = self._pop.value
        if not 0 < b < 0.98:
            return
        c = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), int(255 * (1 - b))), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(n):
            a = i * 2 * math.pi / n
            ra, rb = r0 + (r1 - r0) * b, r0 + (r1 - r0) * b + 3 * (1 - b)
            p.drawLine(QPointF(c.x() + math.cos(a) * ra, c.y() + math.sin(a) * ra),
                       QPointF(c.x() + math.cos(a) * rb, c.y() + math.sin(a) * rb))


class PinButton(_IconToggle):
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._t.value
        h = self._h.value
        if h > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            hc = QColor(_fpal(self)["accent"])
            hc.setAlpha(int(45 * h))
            p.setBrush(hc)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), _rad(8), _rad(8))
        col = _mix(QColor(_fpal(self)["muted"]), QColor(_fpal(self)["acc_text"]), t)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(35 * (1 - t) - 10 * t)
        pen = QPen(col, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(_mix(QColor(0, 0, 0, 0), col, t))
        head = QPainterPath()
        head.addRoundedRect(QRectF(-4.5, -9, 9, 10), 2, 2)
        p.drawPath(head)
        p.drawLine(QPointF(-7, 1), QPointF(7, 1))
        p.drawLine(QPointF(0, 1), QPointF(0, 9))


class StarRating(QWidget):
    """5 stars; hover previews, click sets, click same star clears."""
    changed = pyqtSignal(int)

    def __init__(self, value: int = 0, parent=None):
        super().__init__(parent)
        self.value, self._hover = value, 0
        self.setMouseTracking(True)
        self.setFixedSize(5 * 26, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pop = _Anim(self, 0, 350, CURVE_BACK)
        self._last = 0

    def set_value(self, v: int) -> None:
        self.value = int(v or 0)
        self.update()

    def _idx(self, x: float) -> int:
        i = int(x // 26) + 1
        return max(1, min(5, i))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        self._hover = self._idx(e.position().x())
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = 0
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._idx(e.position().x())
        self.value = 0 if i == self.value else i
        self._last = i
        self._pop.set(0)
        self._pop.to(1)
        self.changed.emit(self.value)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shown = self._hover or self.value
        for i in range(5):
            cx, cy = 13 + i * 26, 14
            on = i < shown
            k = 1.0
            if self._pop.value < 1 and i + 1 <= self._last and self.value:
                k = 1 + 0.35 * math.sin(self._pop.value * math.pi)
            path = QPainterPath()
            for j in range(10):
                a = -math.pi / 2 + j * math.pi / 5
                r = (10 if j % 2 == 0 else 4.4) * k
                pt = QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r)
                path.moveTo(pt) if j == 0 else path.lineTo(pt)
            path.closeSubpath()
            p.setPen(QPen(QColor("#ffc73a") if on else QColor(_fpal(self)["muted"]), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(QColor("#ffc73a") if on else Qt.BrushStyle.NoBrush)
            p.drawPath(path)


# ---------------------------------------------------------------- lock btn ---
# ---------------------------------------------------------- icon tool button ---
class IconToolButton(QAbstractButton):
    """Square 3D icon button (bevelled tile: layered shadow, light top edge, inset when pressed). Used for chrome
    actions (lock, sign-out...), timer controls and the editor tool dock. Keyboard focusable (Tab).
    variant: soft | muted | accent. A checkable button shows its checked state as the accent variant."""

    def __init__(self, icon_name: str, tip: str = "", danger: bool = False, size: int = 38, parent=None,
                 variant: str = "soft"):
        super().__init__(parent)
        self.icon_name, self.danger, self.variant = icon_name, danger, variant
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(size, size + 3)          # +3: room for the tile's drop shadow
        self._h = _Anim(self, 0, 140)
        self._down = False

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0)
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._down = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    def setIconName(self, name: str) -> None:  # noqa: N802
        self.icon_name = name
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from . import icons
        from .tactile import is_dark, paint_bevel, tile_rect, variant_base
        from .theme import rr
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._h.value
        on = self.isEnabled()
        var = "accent" if (self.isCheckable() and self.isChecked()) else self.variant
        base, glyph = variant_base(pal, var)
        pressed = self._down and on
        r = tile_rect(QRectF(self.rect()))
        if pressed:
            r = r.translated(0, 1)
        paint_bevel(p, r, min(rr(9), r.height() / 2.2), base, is_dark(pal), pressed, t if on else 0.0)
        if var != "accent":
            tone = QColor(pal["danger"] if self.danger else pal["text"])
            glyph = _mix(glyph, tone, t)
        if not on:
            p.setOpacity(0.4)
        s = max(14, int(min(self.width(), self.height() - 3) * 0.46))
        p.drawPixmap(int(r.center().x() - s / 2), int(r.center().y() - s / 2), icons.pixmap(self.icon_name, glyph.name(), s))
        p.setOpacity(1.0)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["accent"]), 2))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), min(rr(9), r.height() / 2.2) + 1, min(rr(9), r.height() / 2.2) + 1)


# ---------------------------------------------------------------- hamburger ---
class Hamburger(QAbstractButton):
    """Hamburger -> X (600ms)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, 36)
        self._t = _Anim(self, 0, 600, QEasingCurve(QEasingCurve.Type.InOutCubic))
        self.toggled.connect(lambda on: self._t.to(1 if on else 0))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._t.value
        p.setPen(QPen(self.palette().text().color(), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = QPointF(self.width() / 2, self.height() / 2)
        w = 9.0
        # top and bottom rotate into the X, middle fades and shrinks
        for sgn in (-1, 1):
            p.save()
            p.translate(c.x(), c.y() + sgn * 6 * (1 - t))
            p.rotate(-sgn * 45 * t)
            p.drawLine(QPointF(-w, 0), QPointF(w, 0))
            p.restore()
        mid = max(0.0, 1 - t * 2.2)
        if mid > 0:
            q = QColor(p.pen().color())
            q.setAlphaF(mid)
            p.setPen(QPen(q, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(c.x() - w * mid, c.y()), QPointF(c.x() + w * mid, c.y()))


def hbox(*ws: QWidget, spacing: int = 8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in ws:
        h.addWidget(w)
    return h


# ------------------------------------------------- shadcn-style patterns ---
class EyeToggle(QAbstractButton):
    """Show/hide password icon (checked == visible)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = _Anim(self, 0, 150)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().text().color()
        c = QColor(base)
        c.setAlphaF(0.55 + 0.45 * self._h.value)
        p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.translate(self.width() / 2, self.height() / 2)
        eye = QPainterPath()
        eye.moveTo(-8, 0)
        eye.quadTo(0, -8, 8, 0)
        eye.quadTo(0, 8, -8, 0)
        p.drawPath(eye)
        p.drawEllipse(QPointF(0, 0), 2.4, 2.4)
        if not self.isChecked():
            p.drawLine(QPointF(-7, 7), QPointF(7, -7))


class Badge(QWidget):
    """Small rounded status pill (success/warning/info/danger/muted/primary)."""
    TONES = {"success": ("#5f8f86", 0.18), "warning": ("#9a8460", 0.18), "info": ("#6a7c9f", 0.18),
             "danger": ("#af6a65", 0.18), "muted": ("#7b808c", 0.16), "primary": ("#6a7c9f", 0.18)}

    def __init__(self, text: str = "", tone: str = "muted", parent=None):
        super().__init__(parent)
        self.text_, self.tone = text, tone
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self.text_) + 20, 22)

    def paintEvent(self, _e) -> None:  # noqa: N802
        paint_badge(QPainter(self), QRectF(self.rect()), self.text_, self.tone, self.font(), _fpal(self))


def _info_tone(pal: dict) -> str:
    """Neutral-blue "information" colour: the secondary brand colour, lifted on dark surfaces so it stays legible."""
    c = QColor(pal["accent2"])
    if QColor(pal["bg"]).lightness() < 128:
        c = QColor(int(c.red() + (255 - c.red()) * .28), int(c.green() + (255 - c.green()) * .28), int(c.blue() + (255 - c.blue()) * .28))
    return c.name()


def paint_badge(p: QPainter, r: QRectF, text: str, tone: str, font: QFont, pal: dict | None = None,
                dot: bool = False) -> None:
    if pal:
        col = {"success": pal["ok"], "warning": pal["warn"], "info": _info_tone(pal), "danger": pal["danger"],
               "muted": pal["muted"], "primary": pal["acc_text"]}.get(tone, pal["muted"])
        a = 0.16
    else:
        col, a = Badge.TONES.get(tone, Badge.TONES["muted"])
    c = QColor(col)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont(font)
    f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
    f.setBold(True)
    p.setFont(f)
    w = p.fontMetrics().horizontalAdvance(text) + 18 + (12 if dot else 0)
    box = QRectF(0, 0, min(w, r.width()), 21)
    box.moveCenter(r.center())
    p.setPen(Qt.PenStyle.NoPen)
    fill = QColor(c)
    fill.setAlphaF(a)
    p.setBrush(fill)
    p.drawRoundedRect(box, _rad(10.5), _rad(10.5))
    text_box = box
    if dot:                                                   # status dot at the start (right) edge
        p.setBrush(c)
        p.drawEllipse(QPointF(box.right() - 10, box.center().y()), 3.0, 3.0)
        text_box = box.adjusted(6, 0, -14, 0)
    p.setPen(c)
    p.drawText(text_box, Qt.AlignmentFlag.AlignCenter, text)


class StrengthMeter(QWidget):
    """Segmented strength bar + requirement checklist (shadcn password-strength pattern)."""
    REQS = [("حداقل ۱۰ کاراکتر", lambda s: len(s) >= 10), ("حداقل یک عدد", lambda s: any(c.isdigit() for c in s)),
            ("یک حرف کوچک", lambda s: any(c.islower() for c in s)), ("یک حرف بزرگ", lambda s: any(c.isupper() for c in s)),
            ("یک نماد ویژه", lambda s: any(not c.isalnum() and not c.isspace() for c in s))]
    COLORS = ["#7b808c", "#af6a65", "#b08a68", "#b39d78", "#8db8a8", "#5f8f86"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pw = ""
        self.setMinimumHeight(42 + 22 * self._rows() + 6)             # the checklist runs in two columns: it took half the dialog
        self._score = _Anim(self, 0, 520, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._glint = _Anim(self, 1.0, 900, QEasingCurve(QEasingCurve.Type.InOutQuad))

    COLS = 2

    def _rows(self) -> int:
        return -(-len(self.REQS) // self.COLS)

    def set_password(self, s: str) -> None:
        self.pw = s
        n = sum(1 for _t, f in self.REQS if f(s))
        if n == len(self.REQS) and float(self._score.a.endValue() or 0) < len(self.REQS) - 0.5:
            self._glint.set(0.0)                           # the ingot is complete: one glint runs along it
            self._glint.to(1.0)
        self._score.to(n)

    def _ingot(self, p: QPainter, pal: dict, col: QColor, score: int) -> None:
        """The bar is a metal ingot that fills as the password gets stronger: a brushed-metal ramp in the current hue,
        engraved notches at the five steps, and a glint sweeping along it when it is full."""
        from .brand import gilt_stops
        col = _mix(col, QColor(pal["muted"]), 0.28)         # matte: the state hue, but never a neon
        w, h, y = self.width(), 8.0, 3.0
        track = QRectF(0, y, w, h)
        rad = min(_rad(4), h / 2)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        fill = max(0.0, min(1.0, self._score.value / len(self.REQS)))
        if fill > 0.001:
            fw = max(h, w * fill)
            r = QRectF(w - fw, y, fw, h)                   # RTL: it fills from the right, like the text reads
            hue = {"accent": col.name(), "accent2": _mix(col, QColor("#ffffff"), 0.35).name(),
                   "bg": pal["bg"]}
            g = QLinearGradient(r.left(), r.top(), r.left(), r.bottom())
            for pos, c in gilt_stops(hue):
                g.setColorAt(pos, c)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, rad, rad)
            if self._glint.value > 0.0 and self._glint.value < 1.0:
                gx = w - w * self._glint.value * 1.3 + w * 0.15
                gg = QLinearGradient(gx - 26, 0, gx + 26, 0)
                gg.setColorAt(0, QColor(255, 255, 255, 0))
                gg.setColorAt(0.5, QColor(255, 255, 255, 170))
                gg.setColorAt(1, QColor(255, 255, 255, 0))
                p.save()
                p.setClipRect(r)
                p.setBrush(QBrush(gg))
                p.drawRoundedRect(r, rad, rad)
                p.restore()
        nb = QColor(pal["bg"])
        nb.setAlpha(190)
        p.setPen(QPen(nb, 1.4))
        for i in range(1, len(self.REQS)):                 # the engraved notches
            x = w * i / len(self.REQS)
            p.drawLine(QPointF(x, y + 0.5), QPointF(x, y + h - 0.5))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = _fpal(self)
        met = [f(self.pw) for _t, f in self.REQS]
        score = sum(met)
        mixc = lambda a, b: _mix(QColor(pal[a]), QColor(pal[b]), 0.5)   # noqa: E731
        col = (QColor(pal["muted"]), QColor(pal["danger"]), mixc("danger", "warn"), QColor(pal["warn"]),
               mixc("warn", "ok"), QColor(pal["ok"]))[score]
        self._ingot(p, pal, col, score)
        w = self.width()
        txt = "رمز را وارد کن" if score == 0 else ("امنیت ضعیف" if score <= 2 else "امنیت متوسط" if score <= 4 else "امنیت قوی")
        p.setPen(QColor(pal["text"]))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 14, w, 22), AL_R | Qt.AlignmentFlag.AlignVCenter, txt)
        f.setBold(False)
        f.setPointSizeF(max(8, f.pointSizeF() - 1))
        p.setFont(f)
        muted = QColor(pal["muted"])
        p.setPen(muted)
        p.drawText(QRectF(0, 14, w, 22), AL_L | Qt.AlignmentFlag.AlignVCenter, f"{score}/5")
        cw = w / self.COLS
        for i, ((t, _f), ok) in enumerate(zip(self.REQS, met)):
            row, col = divmod(i, self.COLS)
            y = 42 + row * 22
            x0 = w - col * cw                                     # RTL: the first requirement sits at the right
            c = QColor(pal["ok"]) if ok else QColor(muted)
            p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x = x0 - 9
            if ok:
                p.drawLine(QPointF(x - 4, y + 11), QPointF(x - 1.5, y + 14))
                p.drawLine(QPointF(x - 1.5, y + 14), QPointF(x + 4, y + 8))
            else:
                p.drawLine(QPointF(x - 3, y + 8), QPointF(x + 3, y + 14))
                p.drawLine(QPointF(x + 3, y + 8), QPointF(x - 3, y + 14))
            p.setPen(QColor(pal["text"]) if ok else muted)
            p.drawText(QRectF(x0 - cw + 4, y, cw - 26, 22), AL_R | Qt.AlignmentFlag.AlignVCenter, t)


class GhostIconButton(QAbstractButton):
    """Ghost icon button with tooltip (bold/italic/... toolbar). kind: bold|italic|underline|list|heading|save|image."""

    def __init__(self, kind: str, tip: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setToolTip(tip)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = _Anim(self, 0, 120)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fg = self.palette().text().color()
        if self._h.value > 0.01:
            bg = QColor(fg)
            bg.setAlphaF(0.10 * self._h.value)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), _rad(7), _rad(7))
        p.setPen(QPen(fg, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.translate(self.width() / 2, self.height() / 2)
        k = self.kind
        if k in ("bold", "italic", "underline", "heading"):
            f = QFont("Vazirmatn", 12)
            f.setBold(k in ("bold", "heading"))
            f.setItalic(k == "italic")
            f.setUnderline(k == "underline")
            p.setFont(f)
            p.drawText(QRectF(-12, -12, 24, 24), Qt.AlignmentFlag.AlignCenter, "H" if k == "heading" else {"bold": "B", "italic": "I", "underline": "U"}[k])
        elif k == "list":
            for y in (-5, 0, 5):
                p.drawPoint(QPointF(-7, y))
                p.drawLine(QPointF(-3, y), QPointF(7, y))
        elif k == "save":
            body = QPainterPath()
            body.addRoundedRect(QRectF(-7, -7, 14, 14), 2, 2)
            p.drawPath(body)
            p.drawRect(QRectF(-3.5, -7, 7, 4))
            p.drawRect(QRectF(-4, 1, 8, 6))
        else:  # image
            p.drawRoundedRect(QRectF(-8, -6.5, 16, 13), 2, 2)
            p.drawEllipse(QPointF(-3, -2), 1.5, 1.5)
            p.drawLine(QPointF(-8, 5), QPointF(-2, 0))
            p.drawLine(QPointF(-2, 0), QPointF(3, 4))
            p.drawLine(QPointF(3, 4), QPointF(5, 2.5))


# ------------------------------------------------------------------ combo ---
class Combo(QComboBox):
    """QComboBox whose closed state is painted here: one chevron on the END side (left in RTL), text on the start
    side, and the same frame / hover / focus language as the other fields. (Qt's style-sheet combo draws two arrows
    under a right-to-left layout.) The drop-down is a floating glass sheet (``combo_popup.ComboPopup``), not Qt's list.

    ``set_default(i)`` marks the "no filter" row: while another row is chosen the field wears a small accent dot and an
    accent hairline, so an active filter is visible at a glance."""

    PAD, ARROW = 12, 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hov = _Anim(self, 0.0, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pop = None
        self._pop_closed_t = 0.0
        self._default: int | None = None

    # ---- the drop-down
    def showPopup(self) -> None:  # noqa: N802
        import time
        if self._pop is not None or self.count() == 0 or time.monotonic() - self._pop_closed_t < 0.2:
            return                                    # a click that just closed the sheet must not reopen it
        from .combo_popup import ComboPopup
        self._pop = ComboPopup(self)
        self._pop.picked.connect(self._picked)
        self._pop.show()
        self.update()

    def hidePopup(self) -> None:  # noqa: N802
        if self._pop is not None:
            try:
                self._pop.close()
            except RuntimeError:
                pass

    def _picked(self, i: int) -> None:
        if i != self.currentIndex():
            self.setCurrentIndex(i)
        self.activated.emit(i)
        self.textActivated.emit(self.itemText(i))

    def _popup_closed(self) -> None:
        import time
        self._pop = None
        self._pop_closed_t = time.monotonic()
        self.update()

    def wheelEvent(self, e) -> None:  # noqa: N802
        e.ignore()                                    # scrolling a page over a field must not change it

    def set_default(self, index: int | None) -> None:
        self._default = index
        self.update()

    def is_filtering(self) -> bool:
        return self._default is not None and self.currentIndex() != self._default

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hov.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hov.to(0.0)
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        w = max([fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())] + [40])
        return QSize(w + 2 * self.PAD + self.ARROW + 6, max(36, fm.height() + 16))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(min(self.sizeHint().width(), 90), self.sizeHint().height())

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = _rad(8)
        h = self._hov.value if self.isEnabled() else 0.0
        focus = self.hasFocus() or self._pop is not None
        flt = self.is_filtering() and self.isEnabled()
        edge = QColor(pal["accent2"]) if focus else _mix(QColor(pal["line"]), QColor(pal["accent2"] if flt else pal["muted"]),
                                                       0.55 if flt else 0.45 * h)
        p.setPen(QPen(edge, 1))
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(r, rad, rad)
        ink = QColor(pal["text"] if self.isEnabled() else pal["muted"])
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        arrow = QRectF(r.left() + 6, r.top(), self.ARROW, r.height()) if rtl else \
            QRectF(r.right() - 6 - self.ARROW, r.top(), self.ARROW, r.height())
        text = r.adjusted(self.PAD + self.ARROW, 0, -self.PAD, 0) if rtl else r.adjusted(self.PAD, 0, -self.PAD - self.ARROW, 0)
        if flt:                                                              # an active filter: a small accent dot before the text
            dx = r.right() - self.PAD + 1 if rtl else r.left() + self.PAD - 1
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["accent2"]))
            p.drawEllipse(QPointF(dx - 3 if rtl else dx + 3, r.center().y()), 2.6, 2.6)
            text = text.adjusted(0, 0, -10, 0) if rtl else text.adjusted(10, 0, 0, 0)
        p.setPen(ink)
        p.setFont(self.font())
        al = (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignAbsolute
        p.drawText(text, al | Qt.AlignmentFlag.AlignVCenter,
                   self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, int(text.width())))
        c = arrow.center()
        chev = _mix(QColor(pal["muted"]), QColor(pal["text"]), max(h, 1.0 if focus else 0.0))
        p.setPen(QPen(chev, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        up = -1 if self._pop is not None else 1
        p.drawPolyline(QPolygonF([QPointF(c.x() - 4, c.y() - 2 * up), QPointF(c.x(), c.y() + 2 * up),
                                  QPointF(c.x() + 4, c.y() - 2 * up)]))
