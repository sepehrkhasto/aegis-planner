# SPDX-License-Identifier: GPL-3.0-or-later
"""More animated widgets: HoldButton (hold-to-delete wave fill), BellToggle (ringing bell),
JellyRadio (jelly chip selector) and RubberSegment (stretchy segmented control).
All repaint only while animating."""
from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractButton, QWidget

from .theme import AL_R
from .theme import rr as _rad
from . import icons
from .fx_widgets import _Anim, _mix
from .theme import PALETTES


def _pal(w: QWidget) -> dict:
    x = w
    while x is not None:
        t = getattr(x, "theme", None)
        if isinstance(t, str) and t in PALETTES:
            return PALETTES[t]
        x = x.parentWidget()
    return PALETTES["dark"]


# ------------------------------------------------------------- HoldButton ---
class HoldButton(QAbstractButton):
    """Press and hold; a wavy fill sweeps across, and `held` fires when it completes."""
    held = pyqtSignal()
    tapped = pyqtSignal()

    def __init__(self, text: str = "نگه‌دار تا حذف شود", done: str = "حذف شد", icon: str = "trash",
                 fill: str | None = None, hold_ms: int = 1200):
        super().__init__()
        self.setText(text)
        self.done_text, self.icon_name, self._fill, self.hold_ms = done, icon, fill, hold_ms
        self.p = 0.0
        self.done = False
        self._t = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setMinimumWidth(190)
        self.a = QVariantAnimation(self)
        self.a.valueChanged.connect(self._val)
        self.a.finished.connect(self._fin)
        self._start_ms = 0
        self._reset = QTimer(self, singleShot=True, interval=1200)
        self._reset.timeout.connect(self._back)
        self._holding = False

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(210, 40)

    def _val(self, v) -> None:
        self.p = float(v)
        self.update()

    def _fin(self) -> None:
        if self._holding and self.p >= 1.0:
            self._holding = False
            self.done = True
            self.held.emit()
            self._reset.start()

    def _back(self) -> None:
        self.done = False
        self._anim_to(0.0, 200, QEasingCurve.Type.OutCubic)

    def _anim_to(self, to: float, ms: int, curve) -> None:
        self.a.stop()
        self.a.setEasingCurve(curve)
        self.a.setDuration(ms)
        self.a.setStartValue(self.p)
        self.a.setEndValue(to)
        self.a.start()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or self.done or not self.isEnabled():
            return
        self._holding = True
        self._anim_to(1.0, int(self.hold_ms * (1 - self.p)) + 1, QEasingCurve.Type.Linear)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._cancel()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._cancel()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return) and not e.isAutoRepeat() and not self.done:
            self._holding = True
            self._anim_to(1.0, int(self.hold_ms * (1 - self.p)) + 1, QEasingCurve.Type.Linear)

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return) and not e.isAutoRepeat():
            self._cancel()

    def _cancel(self) -> None:
        if self._holding:
            self._holding = False
            self._anim_to(0.0, 200, QEasingCurve.Type.OutCubic)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _pal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = min(_rad(12), r.height() / 2)
        clip = QPainterPath()
        clip.addRoundedRect(r, rad, rad)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel2"]))
        p.drawPath(clip)
        text = self.done_text if self.done else self.text()
        font = QFont(self.font())
        font.setBold(True)
        p.setFont(font)
        icon_col = pal["danger"] if "danger" in pal else "#ef4444"

        def draw(col: str) -> None:
            p.setPen(QColor(col))
            tr = QRectF(r.left() + 10, r.top(), r.width() - 48, r.height())
            p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | AL_R, text)
            p.drawPixmap(int(r.right() - 32), int(r.center().y() - 9), icons.pixmap(self.icon_name, col, 18))

        if self.p <= 0.001:
            draw(icon_col)
        if self.p > 0.001:
            # fill sweeps from the right edge (RTL) with a wavy crest
            edge = r.right() - (r.width() + 12) * self.p + 6
            path = QPainterPath()
            path.moveTo(r.right() + 2, r.top() - 1)
            path.lineTo(edge, r.top() - 1)
            amp, n = 4.0, 8
            for i in range(n + 1):
                y = r.top() + r.height() * i / n
                path.lineTo(edge + amp * math.sin(self.p * 14 + i * 1.3), y)
            path.lineTo(r.right() + 2, r.bottom() + 1)
            path.closeSubpath()
            p.save()
            p.setClipPath(clip.subtracted(path))
            draw(icon_col)
            p.restore()
            p.save()
            p.setClipPath(path.intersected(clip))
            fillc = QColor(self._fill) if self._fill else QColor(pal["danger"])
            p.fillRect(r, fillc)
            draw("#000000" if fillc.lightness() > 150 else "#ffffff")
            p.restore()


# -------------------------------------------------------------- BellToggle ---
class BellToggle(QAbstractButton):
    """Notify toggle: the bell rings when switched on, colours invert, label crossfades."""

    def __init__(self, off_label: str = "یادآوری خاموش", on_label: str = "یادآوری روشن"):
        super().__init__()
        self.setCheckable(True)
        self.off_label, self.on_label = off_label, on_label
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)
        self.setMinimumWidth(190)
        self.mix = _Anim(self, 0.0, 200)
        self.ring = QVariantAnimation(self)
        self.ring.setStartValue(0.0)
        self.ring.setEndValue(1.0)
        self.ring.setDuration(820)
        self.ring.valueChanged.connect(lambda _v: self.update())
        self.toggled.connect(self._on)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(210, 42)

    def _on(self, on: bool) -> None:
        self.mix.to(1.0 if on else 0.0)
        if on:
            self.ring.stop()
            self.ring.start()

    def set_state(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self.mix.set(1.0 if on else 0.0)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _pal(self)
        m = self.mix.value
        off_bg, on_bg = QColor(pal["panel2"]), QColor(pal["accent2"])
        off_fg, on_fg = QColor(pal["text"]), QColor(pal["ink"])
        bg, fg = _mix(off_bg, on_bg, m), _mix(off_fg, on_fg, m)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, _rad(14), _rad(14))
        # bell (rotates about its top centre)
        t = self.ring.currentValue() if self.ring.state() == QVariantAnimation.State.Running else 1.0
        ang = 17 * math.sin(2 * math.pi * 5 * t) * (1 - t) if t < 1 else 0
        c = QPointF(r.right() - 26, r.center().y() - 8)
        p.save()
        p.translate(c)
        p.rotate(ang)
        p.drawPixmap(-10, 0, icons.pixmap("bell", fg.name(), 20))
        p.restore()
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        tr = QRectF(r.left() + 10, r.top(), r.width() - 52, r.height())
        c1, c2 = QColor(fg), QColor(fg)
        c1.setAlphaF(1 - m)
        c2.setAlphaF(m)
        p.setPen(c1)
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | AL_R, self.off_label)
        p.setPen(c2)
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | AL_R, self.on_label)


# --------------------------------------------------- selector base (thumb) ---
def gooey_path(left: float, right: float, top: float, bottom: float, base_w: float, rad: float) -> QPainterPath:
    """Metaball-style thumb: while it travels, its two ends stay round and are joined by a pinched neck, like the
    gooey SVG filter (blur + threshold) - but built from real curves, so it costs nothing and stays crisp."""
    h = bottom - top
    if right - left <= base_w + 1.0:
        path = QPainterPath()
        path.addRoundedRect(QRectF(left, top, right - left, h), rad, rad)
        return path
    a, b = QPainterPath(), QPainterPath()
    a.addRoundedRect(QRectF(left, top, base_w, h), rad, rad)
    b.addRoundedRect(QRectF(right - base_w, top, base_w, h), rad, rad)
    x0, x1 = left + base_w * 0.5, right - base_w * 0.5
    pinch = min(h * 0.32, (right - left - base_w) * 0.14)         # deeper neck the further it stretches
    span = x1 - x0
    neck = QPainterPath()
    neck.moveTo(x0, top)
    neck.cubicTo(x0 + span * 0.38, top + pinch, x1 - span * 0.38, top + pinch, x1, top)
    neck.lineTo(x1, bottom)
    neck.cubicTo(x1 - span * 0.38, bottom - pinch, x0 + span * 0.38, bottom - pinch, x0, bottom)
    neck.closeSubpath()
    return a.united(b).united(neck)


class _ThumbRow(QWidget):
    """Row of labelled slots with an animated thumb; subclasses set look via attributes."""
    changed = pyqtSignal(int)
    JELLY = False

    def __init__(self, items: list[str], radius: int = 10, pad: int = 4, height: int = 34, chips: bool = False):
        super().__init__()
        self.items, self.idx, self.radius, self.pad, self.chips = list(items), 0, radius, pad, chips
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(False)
        self._lead = _Anim(self, 0.0, 240, QEasingCurve(QEasingCurve.Type.OutBack) if self.JELLY else QEasingCurve(QEasingCurve.Type.OutCubic))
        self._trail = _Anim(self, 0.0, 380 if not self.JELLY else 300, QEasingCurve(QEasingCurve.Type.OutBack) if self.JELLY else QEasingCurve(QEasingCurve.Type.OutCubic))
        self._drag = False
        self._placed = False
        self.setFixedWidth(self._total_w())
        self.theme_override: str | None = None

    def _slot_w(self, t: str) -> int:
        return self.fontMetrics().horizontalAdvance(t) + (34 if not self.chips else 30)

    def _total_w(self) -> int:
        gap = 8 if self.chips else 0
        return sum(self._slot_w(t) for t in self.items) + gap * (len(self.items) - 1) + 2 * self.pad

    def set_items(self, items: list[str]) -> None:
        self.items = list(items)
        self.setFixedWidth(self._total_w())
        self.update()

    def _rects(self) -> list[QRectF]:
        gap = 8 if self.chips else 0
        x = self.width() - self.pad
        out = []
        for t in self.items:
            w = self._slot_w(t)
            out.append(QRectF(x - w, self.pad, w, self.height() - 2 * self.pad))
            x -= w + gap
        return out

    def set_index(self, i: int, animate: bool = True) -> None:
        i = max(0, min(len(self.items) - 1, i))
        self.idx = i
        rs = self._rects()
        if not rs:
            return
        r = rs[i]
        if animate and self._placed:
            # right edge (in RTL the leading edge depends on direction; both edges just chase with different timing)
            going_left = r.center().x() < (self._lead.value + self._trail.value) / 2
            (self._lead if going_left else self._trail).to(r.left() if going_left else r.right())
            (self._trail if going_left else self._lead).to(r.right() if going_left else r.left())
            # lead = left edge value, trail = right edge value (kept consistent below)
        else:
            self._lead.set(r.left())
            self._trail.set(r.right())
            self._placed = True
        self.update()

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._placed = False
        self.set_index(self.idx, animate=False)
        super().resizeEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        if not self._placed:
            self.set_index(self.idx, animate=False)
        super().showEvent(e)

    def _hit(self, x: float) -> int:
        for i, r in enumerate(self._rects()):
            if r.left() - 4 <= x <= r.right() + 4:
                return i
        return -1

    def _pick(self, x: float) -> None:
        i = self._hit(x)
        if i >= 0 and i != self.idx:
            self.set_index(i)
            self.changed.emit(i)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._drag = True
        self._pick(e.position().x())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag:
            self._pick(e.position().x())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = False


class RubberSegment(_ThumbRow):
    """Segmented control whose thumb stretches and snaps like rubber."""

    def __init__(self, items: list[str]):
        super().__init__(items, radius=9, pad=3, height=34)
        self.theme = "dark"

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES[self.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(QRectF(self.rect()), self.radius + 3, self.radius + 3)
        l, r = sorted((self._lead.value, self._trail.value))
        stretch = max(0.0, abs((r - l)) - self._rects()[self.idx].width()) if self._rects() else 0
        squash = min(3.0, stretch / 12)
        base = self._rects()[self.idx].width() if self._rects() else r - l
        top, bot = self.pad + squash / 2, self.height() - self.pad - squash / 2
        p.setBrush(QColor(pal["panel"]))
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawPath(gooey_path(l, r, top, bot, base, self.radius))
        for i, rc in enumerate(self._rects()):
            p.setPen(QColor(pal["text"]) if i == self.idx else QColor(pal["muted"]))
            p.drawText(rc, Qt.AlignmentFlag.AlignCenter, self.items[i])


class JellyRadio(_ThumbRow):
    """Chip selector; the active blob wobbles (overshoots) into place."""
    JELLY = True

    def __init__(self, items: list[str], values: list[str] | None = None):
        super().__init__(items, radius=14, pad=2, height=36, chips=True)
        self.values = list(values or items)
        self.theme = "dark"

    def value(self) -> str:
        return self.values[self.idx]

    def set_value(self, v: str) -> None:
        if v in self.values:
            self.set_index(self.values.index(v), animate=self._placed)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES[self.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rs = self._rects()
        p.setPen(Qt.PenStyle.NoPen)
        for rc in rs:
            p.setBrush(QColor(pal["panel2"]))
            p.drawRoundedRect(rc, self.radius, self.radius)
        l, r = sorted((self._lead.value, self._trail.value))
        base = rs[self.idx].width() if rs else 0
        swell = min(3.0, max(0.0, (r - l - base)) / 10)
        p.setBrush(QColor(pal["text"]))                   # monochrome selected chip: bright pill, ink label
        p.drawPath(gooey_path(l, r, self.pad - swell, self.height() - self.pad + swell, base, self.radius))
        for i, rc in enumerate(rs):                        # label on the bright pill takes the page colour
            p.setPen(QColor(pal["bg"]) if i == self.idx else QColor(pal["muted"]))
            p.drawText(rc, Qt.AlignmentFlag.AlignCenter, self.items[i])
