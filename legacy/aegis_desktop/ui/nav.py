# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar chrome: navigation items, the command-palette hint and the collapse toggle.

The brand material of the sidebar lives here:
* ``NavIndicator`` - ONE matte-gold capsule (with a thin glowing bar on the start edge) that *glides* between items with
  a small spring instead of every item owning a background. It is the only place the sidebar spends the brand colour.
* ``SideFrame`` - grain, a gilt hairline on the inner edge and a very faint pool of light that follows the pointer; the
  nav items nearest to the pointer brighten a little (``prox``). The glow only runs while the pointer is over the bar.
* Live icons - on hover each glyph lifts, and a few have a gesture of their own (gear turns, timer swings, bin tilts).
* Smooth collapse - the bar's width is driven by ``SideFrame.p`` (0 = full, 1 = icon rail); items slide their icon to
  the centre and fade their label with a small stagger, so nothing jumps.
* Badges - the count on «امروز» pulses once when it changes (never continuously).
In compact mode every item explains itself with a tooltip. ``Reduce motion`` turns all of it into instant changes.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QAbstractButton, QFrame, QSizePolicy, QWidget

from . import icons
from .anim import MOTION
from .fx_widgets import _Anim, _fpal
from .premium import mix
from .theme import AL_R, rr

_EASE = QEasingCurve(QEasingCurve.Type.OutCubic)
_SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
_SPRING.setOvershoot(0.9)

# how each glyph "comes alive" on hover: (lift px, scale gain, rotation degrees at full hover)
_LIVE = {"settings": (1.0, 0.0, 60.0), "focus": (1.5, 0.0, 18.0), "trash": (1.0, 0.0, -14.0), "calendar": (2.0, 0.0, 0.0),
         "goals": (1.0, 0.14, 0.0), "habits": (2.0, 0.08, 0.0), "today": (1.5, 0.06, 0.0), "reports": (2.0, 0.0, 0.0)}
_LIVE_DEFAULT = (1.5, 0.0, 0.0)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class NavIndicator(QWidget):
    """The gilt capsule behind the open page's item. Lives in the sidebar, under the items (which paint no fill)."""

    def __init__(self, side: QWidget):
        super().__init__(side)
        self.side, self.target = side, None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._an = QVariantAnimation(self)
        self._an.setDuration(320)
        self._an.setEasingCurve(_SPRING)
        self._an.valueChanged.connect(self._step)
        self._from = self._to = QRectF()
        self.hide()
        side.installEventFilter(self)

    def _goal(self) -> QRectF | None:
        b = self.target
        if b is None or not b.isVisibleTo(self.side):
            return None
        return QRectF(QPointF(b.mapTo(self.side, b._pill().topLeft().toPoint())), b._pill().size())

    def _step(self, v) -> None:
        k = float(v)
        a, b = self._from, self._to
        self.setGeometry(QRectF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k,
                                a.width() + (b.width() - a.width()) * k, a.height() + (b.height() - a.height()) * k).toRect())

    def glide_to(self, btn, animate: bool = True) -> None:
        self.target = btn
        self.sync(animate)

    def sync(self, animate: bool = False) -> None:
        g = self._goal()
        if g is None:
            self.hide()
            return
        moving = self.isVisible() and self.geometry().isValid() and self.geometry().size().isValid()
        if animate and moving and MOTION[0] and self.side.isVisible():
            self._from, self._to = QRectF(self.geometry()), g
            if self._from.toRect() != g.toRect():
                self._an.stop()
                self._an.setStartValue(0.0)
                self._an.setEndValue(1.0)
                self._an.start()
        else:
            self._an.stop()
            self.setGeometry(g.toRect())
        self.show()
        self.lower()                                             # under the items, above the sidebar's own paint

    def eventFilter(self, o, e) -> bool:  # noqa: N802
        if o is getattr(self, "side", None) and e.type() in (e.Type.Resize, e.Type.Show, e.Type.LayoutRequest):
            QTimer.singleShot(0, self._resync)
        return False

    def _resync(self) -> None:
        if not self._an.state() == QVariantAnimation.State.Running:
            self.sync(False)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        dark = QColor(pal["bg"]).lightness() < 128
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = min(rr(8), 10.0)
        acc = QColor(pal["accent"])
        fill = QColor(acc.red(), acc.green(), acc.blue(), 34 if dark else 30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, rad, rad)
        edge = QColor(acc.red(), acc.green(), acc.blue(), 70 if dark else 80)
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        bar = QRectF(r.right() - 7, r.center().y() - 8, 3, 16)         # the slim glowing bar on the start edge
        for w, a in ((9, 26), (5, 46)):
            glow = QColor(acc.red(), acc.green(), acc.blue(), a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(bar.adjusted(-(w - 3) / 2, -(w - 3) / 2, (w - 3) / 2, (w - 3) / 2), w / 2, w / 2)
        p.setBrush(QColor(pal["accent2"]))
        p.drawRoundedRect(bar, 1.5, 1.5)


class SideFrame(QFrame):
    """The sidebar surface: grain, a gilt hairline on the inner edge, and a faint light that follows the pointer.
    ``p`` is the collapse progress (0 full width .. 1 icon rail) that the items read while the bar animates."""

    resized = pyqtSignal()

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.resized.emit()

    def __init__(self, *a):
        super().__init__(*a)
        self.p = 0.0
        self._gx = self._gy = 0.0
        self._ga = 0.0
        self._inside = False
        self._poll = QTimer(self, interval=32)
        self._poll.timeout.connect(self._follow)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._inside = True
        if MOTION[0]:
            self._poll.start()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._inside = False
        super().leaveEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._poll.stop()
        self._ga = 0.0
        super().hideEvent(e)

    def _items(self):
        return [b for b in self.findChildren(NavButton)]

    def _follow(self) -> None:
        loc = QPointF(self.mapFromGlobal(QCursor.pos()))
        inside = self._inside and QRectF(self.rect()).contains(loc)
        if self._ga < 0.02:                                       # (re)appear where the pointer is, not from far away
            self._gx, self._gy = loc.x(), loc.y()
        else:
            self._gx += (loc.x() - self._gx) * 0.32
            self._gy += (loc.y() - self._gy) * 0.32
        self._ga += ((1.0 if inside else 0.0) - self._ga) * 0.22
        for b in self._items():
            c = b.mapTo(self, b.rect().center()).y()
            b.set_prox(_clamp(1 - abs(c - self._gy) / 84.0) * self._ga)
        self.update()
        if not inside and self._ga < 0.015:
            self._ga = 0.0
            self._poll.stop()
            for b in self._items():
                b.set_prox(0.0)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        from PyQt6.QtGui import QLinearGradient
        from . import brand
        pal = _fpal(self)
        if QColor(pal["bg"]).lightness() > 128:
            if self._ga > 0.01:
                self._paint_glow(pal, 14)
            return
        p = QPainter(self)
        brand.paint_grain(p, QRectF(self.rect()), pal, 1.0)
        h = float(self.height())
        g = QLinearGradient(0, 0, 0, h)
        c = QColor(pal["accent"])
        for pos, a in ((0.0, 0), (0.18, 0), (0.42, 110), (0.62, 40), (1.0, 0)):
            g.setColorAt(pos, QColor(c.red(), c.green(), c.blue(), a))
        p.fillRect(QRectF(0, 0, 1, h), g)                         # the border sits on the left (content) side in RTL
        p.end()
        if self._ga > 0.01:
            self._paint_glow(pal, 20)

    def _paint_glow(self, pal: dict, peak: int) -> None:
        p = QPainter(self)
        acc = QColor(pal["accent2"])
        g = QRadialGradient(QPointF(self._gx, self._gy), 130)
        g.setColorAt(0, QColor(acc.red(), acc.green(), acc.blue(), int(peak * self._ga)))
        g.setColorAt(1, QColor(acc.red(), acc.green(), acc.blue(), 0))
        p.fillRect(self.rect(), g)


class _SideButton(QAbstractButton):
    """Shared hover / press / keyboard-focus plumbing."""

    H = 38
    H_TIGHT = 32                                                   # short windows: see MainWindow._fit_side

    def __init__(self, parent=None):
        super().__init__(parent)
        self.compact = False
        self.shortcut = ""
        self.idx = 0                                               # position in the list: staggers the collapse
        self.prox = 0.0                                            # 0..1, how close the pointer is (SideFrame)
        self._h = _Anim(self, 0.0, 150, _EASE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)               # focus ring for keyboard users only
        self.setFixedHeight(self.H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_tight(self, on: bool) -> None:
        self.setFixedHeight(self.H_TIGHT if on else self.H)
        self.updateGeometry()

    def set_prox(self, v: float) -> None:
        if abs(v - self.prox) > 0.02 or (v == 0.0 and self.prox != 0.0):
            self.prox = v
            self.update()

    def cp(self) -> float:
        """This item's own collapse progress: the bar's ``p`` with a small per-item lag (top items go first)."""
        side = self.parentWidget()
        p = getattr(side, "p", None)
        if p is None:
            return 1.0 if self.compact else 0.0
        return _clamp((p - self.idx * 0.02) / 0.78)

    def set_compact(self, on: bool) -> None:
        self.compact = on
        self.setToolTip(f"{self.text()}  {self.shortcut}" if on and self.shortcut else self.text() if on else self._tip())
        self.update()

    def _tip(self) -> str:
        return self.shortcut

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0.0)
        super().leaveEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):      # Space works already; Enter should too
            self.click()
            return
        super().keyPressEvent(e)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, self.minimumHeight() or self.H)

    def _pill(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 1, -8, -1)

    def _focus_ring(self, p: QPainter, r: QRectF, pal: dict, rad: float) -> None:
        if self.hasFocus():
            p.setPen(QPen(QColor(pal["accent2"]), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)


class NavButton(_SideButton):
    """One page link. ``key`` is also the icon name. Paints no fill for the open page - the NavIndicator does."""

    def __init__(self, key: str, text: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setText(text)
        self.setCheckable(True)
        self.setAccessibleName(text)
        self.badge, self.badge_warn = 0, False
        self._pulse = _Anim(self, 0.0, 460, QEasingCurve(QEasingCurve.Type.Linear))
        self._on = _Anim(self, 0.0, 220, _EASE)
        self.toggled.connect(lambda on: self._on.to(1.0 if on else 0.0))

    def land(self) -> None:
        """A light landed on this item (a task was completed elsewhere): one small pulse of the count chip."""
        if MOTION[0] and self.isVisible():
            self._pulse.set(0.0)
            self._pulse.to(1.0)

    def anchor(self):
        from PyQt6.QtCore import QPoint
        return QPoint(int(self.width() - 22), int(self.height() / 2))

    def set_badge(self, n: int, warn: bool = False) -> None:
        """Count chip on the item. Changing (not the first set) gives it one small pulse."""
        changed = n != self.badge
        first = self.badge == 0 and not getattr(self, "_badge_seen", False)
        self.badge, self.badge_warn, self._badge_seen = n, warn, True
        if changed and not first and n > 0 and MOTION[0] and self.isVisible():
            self._pulse.set(0.0)
            self._pulse.to(1.0)
        self.setAccessibleDescription(f"{n} مورد" if n else "")
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = self._pill()
        rad = min(rr(8), 10.0)
        on, h, c = self._on.value, self._h.value, self.cp()
        text_c, muted = QColor(pal["text"]), QColor(pal["muted"])
        a = 0.7 * h * (1 - 0.6 * on)                                # hover wash; the open page has the capsule instead
        if a > 0.01:
            bg = QColor(pal["panel2"])
            bg.setAlphaF(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, rad, rad)
        ink = mix(muted, text_c, max(h, 0.55 * self.prox))
        if on > 0.01:
            ink = mix(ink, QColor(pal["acc_text"]), on)
        g = 18
        ix_full = r.right() - 16 - g
        ix_rail = r.center().x() - g / 2
        ix = ix_full + (ix_rail - ix_full) * c
        life, gain, deg = _LIVE.get(self.key, _LIVE_DEFAULT)
        ease = h * h * (3 - 2 * h)
        p.save()
        p.translate(ix + g / 2, r.center().y())
        if MOTION[0]:
            p.translate(0, -life * ease)
            if deg:
                p.rotate(deg * ease)
            if gain:
                s = 1 + gain * ease
                p.scale(s, s)
        p.drawPixmap(int(-g / 2), int(-g / 2), icons.pixmap(self.key, ink.name(), g))
        p.restore()
        la = 1.0 - _clamp(c * 1.7)                                  # the label fades out first when collapsing
        if la > 0.02:
            f = QFont(self.font())
            f.setPointSizeF(10.5)
            f.setWeight(QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal)
            p.setFont(f)
            tc = QColor(ink)
            tc.setAlphaF(la)
            p.setPen(tc)
            left = r.left() + 10 + (28 if self.badge else 0)
            tr = QRectF(left, r.top(), ix - left - 12, r.height())
            p.drawText(tr, AL_R | Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(f).elidedText(self.text(), Qt.TextElideMode.ElideRight, int(tr.width())))
        if self.badge:
            self._paint_badge(p, pal, r, ix, c, la)
        self._focus_ring(p, r, pal, rad)

    def _paint_badge(self, p: QPainter, pal: dict, r: QRectF, ix: float, c: float, la: float) -> None:
        from ..core.jalali import fa
        s = 1.0 + 0.32 * math.sin(math.pi * self._pulse.value) if self._pulse.value < 1.0 else 1.0
        warn = self.badge_warn
        col = QColor(pal["danger"] if warn else pal["accent"])
        if c > 0.5:                                                  # icon rail: just a dot on the glyph's corner
            p.setPen(QPen(QColor(pal["panel"]), 1.5))
            p.setBrush(col)
            d = 8 * s
            p.drawEllipse(QRectF(ix - 3, r.center().y() - 15, d, d))
            return
        txt = fa(self.badge if self.badge < 100 else 99)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setWeight(QFont.Weight.DemiBold)
        w = max(20.0, QFontMetrics(f).horizontalAdvance(txt) + 12) * s
        box = QRectF(r.left() + 8, r.center().y() - 8 * s, w, 16 * s)
        fill = QColor(col.red(), col.green(), col.blue(), int(38 * la))
        edge = QColor(col.red(), col.green(), col.blue(), int(90 * la))
        p.setPen(QPen(edge, 1))
        p.setBrush(fill)
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        p.setFont(f)
        tc = mix(col, QColor(pal["text"]), 0.55 if not warn else 0.25)
        tc.setAlphaF(la)
        p.setPen(tc)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, txt)


class CommandHint(_SideButton):
    """«جست‌وجو و فرمان‌ها   Ctrl K» - makes the command palette discoverable; a click opens it."""
    H_TIGHT = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("جست‌وجو و فرمان‌ها")
        self.setAccessibleName("جست‌وجو و فرمان‌ها (Ctrl+K)")
        self.setToolTip("پرش سریع  Ctrl+K")

    def _tip(self) -> str:
        return "Ctrl+K"

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._pill().adjusted(0, 2, 0, -2)
        rad = min(rr(8), 10.0)
        h, c = self._h.value, self.cp()
        p.setPen(QPen(mix(QColor(pal["line"]), QColor(pal["muted"]), 0.35 * h), 1))
        p.setBrush(mix(QColor(pal["bg"]), QColor(pal["panel2"]), 0.5 + 0.5 * h))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        ink = mix(QColor(pal["muted"]), QColor(pal["text"]), h)
        g = 16
        ix_full = r.right() - 12 - g
        ix = ix_full + (r.center().x() - g / 2 - ix_full) * c
        p.drawPixmap(int(ix), int(r.center().y() - g / 2), icons.pixmap("search", ink.name(), g))
        la = 1.0 - _clamp(c * 3.2)                                   # the hint's text and keycaps go quickly
        if la > 0.02:
            p.setOpacity(la)
            f = QFont(self.font())
            f.setPointSizeF(9.5)
            p.setFont(f)
            p.setPen(ink)
            p.drawText(QRectF(r.left() + 8, r.top(), ix - r.left() - 16, r.height()),
                       AL_R | Qt.AlignmentFlag.AlignVCenter, self.text())
            kf = QFont(self.font())
            kf.setPointSizeF(8.0)
            kf.setWeight(QFont.Weight.DemiBold)
            p.setFont(kf)
            fm = QFontMetrics(kf)
            x = r.left() + 8
            for key in ("K", "Ctrl"):                                # keycaps at the end (left) edge
                w = fm.horizontalAdvance(key) + 10
                cap = QRectF(x, r.center().y() - 9, w, 18)
                p.setPen(QPen(QColor(pal["line"]), 1))
                p.setBrush(QColor(pal["panel"]))
                p.drawRoundedRect(cap, 4, 4)
                p.setPen(QColor(pal["muted"]))
                p.drawText(cap, Qt.AlignmentFlag.AlignCenter, key)
                x += w + 4
            p.setOpacity(1.0)
        self._focus_ring(p, r, pal, rad)


class SideToggle(QAbstractButton):
    """Collapse / expand the sidebar (a small panel glyph)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = _Anim(self, 0.0, 150, _EASE)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip("جمع/باز کردن منو")
        self.setAccessibleName("جمع/باز کردن منو")

    def enterEvent(self, e) -> None:  # noqa: N802
        self._h.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._h.to(0.0)
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._h.value
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if h > 0.01 or self.hasFocus():
            bg = QColor(pal["panel2"])
            bg.setAlphaF(max(h, 0.6 if self.hasFocus() else 0.0))
            p.setPen(QPen(QColor(pal["accent2"]), 1.2) if self.hasFocus() else Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 7, 7)
        ink = mix(QColor(pal["muted"]), QColor(pal["text"]), h)
        g = QRectF(0, 0, 16, 13)
        g.moveCenter(r.center())
        p.setPen(QPen(ink, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(g, 3, 3)
        x = g.right() - 5.5                                            # the sidebar lives on the right (RTL)
        p.drawLine(QPointF(x, g.top() + 1), QPointF(x, g.bottom() - 1))
