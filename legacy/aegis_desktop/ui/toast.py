# SPDX-License-Identifier: GPL-3.0-or-later
"""In-app glass toasts: iOS-style banners (coloured app tile, title, short text, dismiss X) that slide in over the
window, stack, pause while hovered and fade out on their own. Painted with QPainter, so they follow the palette."""
from __future__ import annotations

import time

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from . import icons
from .anim import MOTION
from .fx_widgets import _Anim, _fpal
from .premium import alpha, mix
from .theme import AL_L, AL_R, rr

# kind -> (icon, tile colour top, tile colour bottom, default title)
KINDS: dict[str, tuple[str, str, str, str]] = {
    "reminder": ("calendar", "#ff6259", "#e5372f", "یادآوری"),
    "alert": ("alert", "#ffc93a", "#f59e0b", "هشدار"),
    "info": ("info", "#4cc3f5", "#0e9be0", "اعلان"),
    "focus": ("focus", "#ff9a4d", "#f0641c", "تمرکز"),
    "success": ("check", "#3ddc84", "#16a34a", "انجام شد"),
}

W = 348                                  # card width
PX, PT, PB = 16, 8, 24                   # room around the card for its drop shadow
_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)
_IN = QEasingCurve(QEasingCurve.Type.InOutCubic)
_POP = QEasingCurve(QEasingCurve.Type.OutBack)              # scale-in with a small spring overshoot
_POP.setOvershoot(1.7)


class Toast(QWidget):
    dismissed = pyqtSignal(object)
    activated = pyqtSignal(object)

    TILE, GAP, PADDING = 38, 12, 14

    def __init__(self, parent: QWidget, kind: str, title: str | None, text: str, when: str = "اکنون", action=None):
        super().__init__(parent)
        self.action = action                                    # (label, callable) → a pill button such as «واگرد»
        self._hover_act = False
        self.kind = kind if kind in KINDS else "info"
        self.title = title or KINDS[self.kind][3]
        self.text, self.when = text, when
        self._hover_x = False
        self._closing = False
        self._dead = False
        self._vis = _Anim(self, 0.0, 420, _POP)
        self._depth = _Anim(self, 0.0, 260, _OUT)              # how far back in the stack this toast sits (0 = newest)
        self._depth_goal = 0
        self._move = QPropertyAnimation(self, b"pos", self)
        self._move.setDuration(240)
        self._move.setEasingCurve(_OUT)
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self.close_toast)
        self._left = 1.0                                        # share of the display time still left (drives the thin bar)
        self._due = 0.0                                         # monotonic deadline while the countdown runs
        self._span = 6.5
        self._bar = QTimer(self)                                # repaints the bar ~30 fps, only while a countdown runs
        self._bar.setInterval(33)
        self._bar.timeout.connect(self._bar_tick)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{self.title}: {text}")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._layout_text()

    def set_depth(self, n: int) -> None:
        """Older toasts recede a little: smaller and dimmer, so a stack reads as a stack (never below 3 levels)."""
        n = max(0, min(3, int(n)))
        if n == self._depth_goal:
            return
        self._depth_goal = n
        if MOTION[0] and self.isVisible():
            self._depth.to(float(n))
        else:
            self._depth.set(float(n))

    # ---------------------------------------------------------- geometry ---
    def _fonts(self) -> tuple[QFont, QFont, QFont]:
        base = self.font()
        t, b, s = QFont(base), QFont(base), QFont(base)
        t.setPixelSize(13)
        t.setBold(True)
        b.setPixelSize(13)
        b.setBold(False)
        s.setPixelSize(11)
        s.setBold(False)
        return t, b, s

    def _text_width(self) -> int:
        return W - 2 * self.PADDING - self.TILE - self.GAP

    def _layout_text(self) -> None:
        _t, bf, _s = self._fonts()
        fm = QFontMetrics(bf)
        w = self._text_width()
        flags = int(Qt.TextFlag.TextWordWrap)
        text = self.text.strip()
        maxh = fm.lineSpacing() * 2 + 2
        if fm.boundingRect(0, 0, w, 10_000, flags, text).height() > maxh:      # longer than two lines: ellipsis
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fm.boundingRect(0, 0, w, 10_000, flags, text[:mid].rstrip() + "…").height() <= maxh:
                    lo = mid
                else:
                    hi = mid - 1
            text = text[:lo].rstrip() + "…"
        self._shown = text
        self._body_h = min(maxh, fm.boundingRect(0, 0, w, 10_000, flags, text).height())
        self._card_h = max(self.TILE, 20 + self._body_h) + 2 * self.PADDING + (34 if self.action else 0)
        self.setFixedSize(W + 2 * PX, self._card_h + PT + PB)

    def card(self) -> QRectF:
        return QRectF(PX, PT, W, self._card_h)

    def _act_rect(self) -> QRectF:
        c = self.card()
        w = QFontMetrics(self._fonts()[0]).horizontalAdvance(self.action[0]) + 30 if self.action else 0
        return QRectF(c.right() - self.PADDING - w, c.bottom() - self.PADDING - 26, w, 26)

    def _x_rect(self) -> QRectF:
        c = self.card()
        return QRectF(c.left() + 8, c.top() + 8, 22, 22)

    # -------------------------------------------------------- lifecycle ---
    def reveal(self, at: QPoint, ms: int) -> None:
        """Pop in (scale from the top edge + fade) at its slot, then start the auto-hide countdown."""
        self.move(at)
        self.show()
        self.raise_()
        self._vis.to(1.0)
        self._span = max(1500, ms) / 1000.0
        self._left = 1.0
        self._run(self._span)

    def _run(self, secs: float) -> None:
        """(Re)start the auto-hide countdown; the bar shrinks in step with the timer."""
        self._due = time.monotonic() + secs
        self._timer.start(int(secs * 1000))
        if MOTION[0]:
            self._bar.start()

    def _bar_tick(self) -> None:
        self._left = max(0.0, (self._due - time.monotonic()) / self._span)
        self.update()
        if self._left <= 0.0:
            self._bar.stop()

    def _pause(self) -> None:
        self._timer.stop()
        self._bar.stop()
        self._left = max(0.0, min(1.0, (self._due - time.monotonic()) / self._span))
        self.update()

    def slide_to(self, pos: QPoint) -> None:
        self._move.stop()
        self._move.setStartValue(self.pos())
        self._move.setEndValue(pos)
        self._move.start()

    def close_toast(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._bar.stop()
        self._vis.a.setDuration(240)
        self._vis.a.setEasingCurve(_IN)
        self._vis.a.setStartValue(min(1.0, self._vis.value))
        self._vis.a.finished.connect(self._finished)
        self._vis.to(0.0)
        self._move.stop()
        self._move.setStartValue(self.pos())
        self._move.setEndValue(self.pos() + QPoint(0, -10))
        self._move.start()

    def _finished(self) -> None:
        if self._dead:
            return
        self._dead = True
        self.hide()
        self.dismissed.emit(self)
        self.deleteLater()

    def enterEvent(self, e) -> None:  # noqa: N802
        if not self._closing:
            self._pause()                                       # hovering keeps it on screen
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover_x = False
        if not self._closing:
            self._run(max(2.2, self._left * self._span))
        self.update()
        super().leaveEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._x_rect().contains(e.position())
        a = bool(self.action) and self._act_rect().contains(e.position())
        if h != self._hover_x or a != self._hover_act:
            self._hover_x, self._hover_act = h, a
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.card().contains(e.position()):
            if self.action and self._act_rect().contains(e.position()):
                fn = self.action[1]
                self.close_toast()
                fn()
            elif self._x_rect().adjusted(-4, -4, 4, 4).contains(e.position()):
                self.close_toast()
            else:
                self.activated.emit(self)
                self.close_toast()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close_toast()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------ paint ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        dark = QColor(pal["bg"]).lightness() < 128
        v = max(0.0, min(1.0, self._vis.value))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        d = self._depth.value
        p.setOpacity(v * (1.0 - 0.16 * d))
        c = self.card()
        sc = (0.86 + 0.14 * max(0.0, min(1.06, self._vis.value))) * (1.0 - 0.035 * d)   # scale-in, origin = top edge; older = smaller
        p.translate(c.center().x(), c.top())
        p.scale(sc, sc)
        p.translate(-c.center().x(), -c.top())
        rad = min(rr(20), 22.0)
        for dy, grow, a in ((3.0, 0.0, 0.16), (8.0, 3.0, 0.10), (14.0, 6.0, 0.06)):        # soft drop shadow
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(255 * a * (1.0 if dark else 0.55))))
            p.drawRoundedRect(c.adjusted(-grow, -grow, grow, grow).translated(0, dy), rad + grow, rad + grow)
        g = QLinearGradient(c.topLeft(), c.bottomLeft())                                     # frosted glass body
        if dark:
            g.setColorAt(0, alpha(mix(QColor(pal["panel"]), QColor("#ffffff"), 0.07), 0.95))
            g.setColorAt(1, alpha(QColor(pal["panel"]), 0.95))
        else:
            g.setColorAt(0, QColor(255, 255, 255, 246))
            g.setColorAt(1, alpha(mix(QColor("#ffffff"), QColor(pal["panel"]), 0.5), 0.94))
        p.setBrush(g)
        p.setPen(QPen(alpha("#ffffff", 0.10) if dark else alpha("#ffffff", 0.9), 1))
        p.drawRoundedRect(c, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(alpha(pal["line"], 0.9 if dark else 0.55), 1))
        p.drawRoundedRect(c.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

        # app tile (start side = right in RTL)
        ic, c1, c2, _t = KINDS[self.kind]
        tile = QRectF(c.right() - self.PADDING - self.TILE, c.top() + self.PADDING, self.TILE, self.TILE)
        tg = QLinearGradient(tile.topLeft(), tile.bottomLeft())
        tg.setColorAt(0, QColor(c1))
        tg.setColorAt(1, QColor(c2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha("#000000", 0.16))
        p.drawRoundedRect(tile.translated(0, 1.5), 10.5, 10.5)
        p.setBrush(tg)
        p.drawRoundedRect(tile, 10.5, 10.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(alpha("#ffffff", 0.35), 1))
        p.drawRoundedRect(tile.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        gl = 20
        p.drawPixmap(int(tile.center().x() - gl / 2), int(tile.center().y() - gl / 2), icons.pixmap(ic, "#ffffff", gl))

        # texts
        tf, bf, sf = self._fonts()
        left = c.left() + 36                                                      # room for the X
        right = tile.left() - self.GAP
        row = QRectF(left, c.top() + self.PADDING - 1, right - left, 18)
        p.setFont(tf)
        p.setPen(QColor(pal["text"]))
        p.drawText(row, int(AL_R | Qt.AlignmentFlag.AlignVCenter), self.title)
        p.setFont(sf)
        p.setPen(alpha(pal["muted"], 0.95))
        p.drawText(row, int(AL_L | Qt.AlignmentFlag.AlignVCenter), self.when)
        p.setFont(bf)
        p.setPen(alpha(pal["text"], 0.86))
        body = QRectF(c.left() + self.PADDING, row.bottom() + 3, right - (c.left() + self.PADDING), self._body_h + 4)
        p.drawText(body, int(AL_R | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), self._shown)

        # remaining-time bar along the bottom edge (starts at the start side and shrinks toward the far side)
        if MOTION[0] and not self._closing and (self._bar.isActive() or self._left < 1.0):
            clip = QPainterPath()
            clip.addRoundedRect(c, rad, rad)
            p.save()
            p.setClipPath(clip)
            bw = (c.width() - 2 * self.PADDING) * self._left
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(QColor(KINDS[self.kind][1]), 0.75))
            p.drawRoundedRect(QRectF(c.right() - self.PADDING - bw, c.bottom() - 3.0, bw, 2.0), 1.0, 1.0)
            p.restore()

        if self.action:                                                           # action pill (e.g. «واگرد»)
            ar = self._act_rect()
            acc = QColor(pal["accent2"])
            p.setPen(QPen(alpha(acc, 0.55), 1))
            p.setBrush(alpha(acc, 0.28 if self._hover_act else 0.14))
            p.drawRoundedRect(ar, 13, 13)
            p.setFont(self._fonts()[0])
            p.setPen(QColor(pal["text"]))
            p.drawText(ar, int(Qt.AlignmentFlag.AlignCenter), self.action[0])

        # dismiss X
        xr = self._x_rect()
        if self._hover_x:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(pal["text"], 0.10))
            p.drawEllipse(xr)
        gx = 12
        p.drawPixmap(int(xr.center().x() - gx / 2), int(xr.center().y() - gx / 2),
                     icons.pixmap("close", QColor(pal["text"] if self._hover_x else pal["muted"]).name(), gx))


def _reveal_if_alive(t, ms) -> None:
    try:
        if not t._closing:
            t.reveal(t.pos(), ms)
    except RuntimeError:                                  # the toast was deleted while it waited its turn
        pass


class ToastHost(QObject):
    """Owns the visible toasts of one window: stacking, placement, limits and de-duplication."""

    MAX = 3
    GAP = 4

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.win = window
        self._toasts: list[Toast] = []                # newest first
        self._last: tuple[tuple[str, str], float] = (("", ""), 0.0)
        self._next_free = 0.0                         # when the next toast of a burst may appear (staggered pop-in)
        window.installEventFilter(self)

    def count(self) -> int:
        return len(self._toasts)

    def _top(self) -> int:
        cw = getattr(self.win, "centralWidget", None)
        w = cw() if callable(cw) else None
        return (w.geometry().top() if w is not None else 0) + 6

    def _slot_x(self, t: Toast) -> int:
        return (self.win.width() - t.width()) // 2

    def _place(self, animate: bool = True) -> None:
        y = self._top()
        for t in self._toasts:
            if t._closing:
                continue
            target = QPoint(self._slot_x(t), y - PT)
            if animate and t.isVisible():
                if t._move.endValue() != target:
                    t.slide_to(target)
            else:
                t.move(target)
            y += t.height() - PT - PB + 10

    def push(self, text: str, kind: str = "info", title: str | None = None, ms: int = 6500, action=None) -> Toast | None:
        text = (text or "").strip()
        if not text:
            return None
        now = time.monotonic()
        if self._last[0] == (kind, text) and now - self._last[1] < 2.0:
            return None                                # the same message twice in a row is noise
        self._last = ((kind, text), now)
        t = Toast(self.win, kind, title, text, action=action)
        t.dismissed.connect(self._gone)
        self._toasts.insert(0, t)
        live = [x for x in self._toasts if not x._closing]
        for old in live[self.MAX:]:
            old.close_toast()
        y = self._top()
        end = QPoint(self._slot_x(t), y - PT)
        t.move(end)
        wait = min(0.5, max(0.0, self._next_free - now))        # toasts that arrive together pop in one after another
        self._next_free = now + wait + 0.16
        if wait > 0.01:
            QTimer.singleShot(int(wait * 1000), lambda: _reveal_if_alive(t, ms))
        else:
            t.reveal(end, ms)
        # older toasts make room below the new one, and recede
        yy = y + t.height() - PT - PB + 10
        for i, o in enumerate([x for x in self._toasts[1:] if not x._closing], start=1):
            o.slide_to(QPoint(self._slot_x(o), yy - PT))
            o.set_depth(i)
            yy += o.height() - PT - PB + 10
        return t

    def _gone(self, t: Toast) -> None:
        if t in self._toasts:
            self._toasts.remove(t)
        for i, o in enumerate(x for x in self._toasts if not x._closing):
            o.set_depth(i)
        self._place()

    def clear(self) -> None:
        for t in list(self._toasts):
            t._closing = True
            for stoppable in (t._timer, t._bar, t._move, t._vis.a):         # nothing may fire into a toast that is going away
                stoppable.stop()
            t._finished()                                                      # the one normal way out: hide, tell the host, deleteLater
        self._toasts.clear()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is getattr(self, "win", None) and ev.type() == QEvent.Type.Resize and getattr(self, "_toasts", None):
            self._place(animate=False)
        return False
