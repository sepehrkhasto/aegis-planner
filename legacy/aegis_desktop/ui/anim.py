# SPDX-License-Identifier: GPL-3.0-or-later
"""Motion primitives shared by the whole UI (all painted with QPainter, no timers run while idle):

  * ``Ticker``        - number ticker: a value counts up/down to its new number (KPI tiles).
  * ``mark_progress`` / ``span_x`` / ``draw_marked`` - the animated marker-pen highlight (notes, search matches).
  * ``LinkButton``    - text link whose underline grows from the start edge on hover and leaves through the far edge.
  * ``ScrambleLabel`` - a label whose letters shuffle and settle one by one (brand, page titles).
  * ``Spinner`` / ``set_loading`` - spinner glyph and a "loading" state for push buttons.
  * ``stagger_in`` / ``finish_stagger`` - cards slide in from the start side one after another when a page opens.
  * ``stripe_watch`` / ``stripe_phase`` - one shared clock that marches the diagonal stripes of progress bars.
"""
from __future__ import annotations

import math
import random
import re
import time
import weakref

from PyQt6.QtCore import (QEasingCurve, QPoint, QPointF, QVariantAnimation, QRectF, QSize, QSizeF,
                          Qt, QTimer)
from PyQt6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QTextLayout, QTextLine,
                         QTextOption)
from PyQt6.QtWidgets import QFrame, QGraphicsEffect, QLabel, QPushButton, QStyle, QWidget

from ..core.jalali import fa
from .fx_widgets import _Anim, _fpal

_BACK = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_IN_OUT = QEasingCurve(QEasingCurve.Type.InOutCubic)
_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)


def _alpha(c: QColor | str, a: float) -> QColor:
    q = QColor(c)
    q.setAlphaF(max(0.0, min(1.0, a)))
    return q


# ============================================================ number ticker ===
def parse_number(text: str):
    """'۱۲٪' -> ('', 12.0, '٪', 0); None when the text holds no number (e.g. '—')."""
    t = text.translate(_BACK)                       # 1:1 character mapping, so indices carry over
    m = _NUM.search(t)
    if not m:
        return None
    s = m.group(0)
    return text[:m.start()], float(s), text[m.end():], (len(s.split(".")[1]) if "." in s else 0)


class Ticker:
    """Number ticker for a widget that paints ``shown()``: the digits count towards the new value."""

    def __init__(self, widget: QWidget, ms: int = 900):
        self.w = widget
        self.anim = _Anim(widget, 0.0, ms, _IN_OUT)
        self.parts: tuple[str, float, str, int] | None = None
        self.text = "—"

    def set_text(self, text: str, animate: bool = True) -> None:
        old = self.parts
        parsed = parse_number(text)
        self.text, self.parts = text, parsed
        if parsed is None:
            self.anim.a.stop()
            self.w.update()
            return
        val = parsed[1]
        if not animate:
            self.anim.set(val)
        elif old is None:                                   # first number: count up from zero
            self.anim.set(0.0)
            self.anim.to(val)
        elif old[1] != val:                                 # changed: continue from what is on screen
            self.anim.to(val)

    def replay(self) -> None:
        """Count up from zero again (used when the page is shown)."""
        if self.parts is not None:
            self.anim.set(0.0)
            self.anim.to(self.parts[1])

    def shown(self) -> str:
        if self.parts is None:
            return self.text
        pre, _val, suf, dec = self.parts
        v = self.anim.value
        return pre + fa(f"{v:.{dec}f}" if dec else str(int(round(v)))) + suf


# ============================================================ marker pen ====
def marker_color(pal: dict) -> QColor:
    """The highlighter ink for a palette: its warm 'warn' hue, strong enough to read on dark and light pages."""
    dark = QColor(pal["bg"]).lightness() < 128
    return _alpha(pal["warn"], 0.32 if dark else 0.42)


def mark_progress(t0: float, now: float, ms: int = 650) -> float:
    """0..1 sweep progress of a marker stroke that started at ``t0`` (eased, no overshoot)."""
    k = (now - t0) * 1000.0 / ms
    if k <= 0:
        return 0.0
    if k >= 1:
        return 1.0
    return 1 - (1 - k) ** 3


def span_x(line: QTextLine, lo: int, hi: int) -> tuple[float, float]:
    """Horizontal extent [left, right] of characters lo..hi inside one laid-out text line (bidi safe)."""
    a = line.cursorToX(lo)[0]
    b = line.cursorToX(hi)[0]
    return (min(a, b), max(a, b))


def sweep_rect(x0: float, x1: float, top: float, height: float, k: float, rtl: bool, pad: float = 2.0) -> QRectF:
    """The part of a highlighted span that is inked at progress ``k`` (starts on the reading-start side)."""
    w = (x1 - x0 + 2 * pad) * k
    left = x0 - pad
    right = x1 + pad
    return QRectF(right - w, top, w, height) if rtl else QRectF(left, top, w, height)


def draw_marked(p: QPainter, rect: QRectF, text: str, needle: str, k: float, mark: QColor, fg: QColor,
                font: QFont, rtl: bool = True) -> None:
    """Draw one line of text (start-aligned, elided) with every occurrence of ``needle`` under a marker stroke
    that has been swept ``k`` of the way."""
    fm = QFontMetrics(font)
    text = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()))
    lay = QTextLayout(text, font)
    opt = QTextOption()
    opt.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
    opt.setWrapMode(QTextOption.WrapMode.NoWrap)
    lay.setTextOption(opt)
    lay.beginLayout()
    ln = lay.createLine()
    ln.setLineWidth(max(1.0, rect.width()))
    ln.setPosition(QPointF(0, 0))
    lay.endLayout()
    nat = ln.naturalTextWidth()
    ox = rect.right() - nat if rtl else rect.left()
    oy = rect.top() + (rect.height() - ln.height()) / 2
    if needle and k > 0:
        from ..core.logic import fold
        low, nl = fold(text), fold(needle)
        i = low.find(nl)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mark)
        while i >= 0:
            x0, x1 = span_x(ln, i, i + len(nl))
            r = sweep_rect(ox + x0, ox + x1, oy + 1, ln.height() - 2, k, rtl)
            p.drawRoundedRect(r, 3, 3)
            i = low.find(nl, i + len(nl))
        p.restore()
    p.setPen(fg)
    lay.draw(p, QPointF(ox, oy))


# ============================================================ link button ===
class LinkButton(QPushButton):
    """Text link. The underline enters from the start edge (right, in RTL) on hover/focus and leaves through the
    far edge when the pointer goes away ("comes in, goes out")."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Link")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self._head = _Anim(self, 0.0, 260, _OUT)          # the underline's leading edge
        self._tail = _Anim(self, 0.0, 260, _OUT)          # its trailing edge (catches up when leaving)
        self._on = False

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 12, fm.height() + 12)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _enter(self) -> None:
        if self._on:
            return
        self._on = True
        if self._tail.value > 0.5:                        # re-entered while still leaving: start a fresh stroke
            self._head.set(0.0)
        self._tail.set(0.0)
        self._head.to(1.0)

    def _leave(self) -> None:
        if not self._on:
            return
        self._on = False
        self._head.to(1.0)
        self._tail.a.finished.connect(self._reset_once)
        self._tail.to(1.0)

    def _reset_once(self) -> None:
        try:
            self._tail.a.finished.disconnect(self._reset_once)
        except TypeError:
            pass
        if not self._on:
            self._head.set(0.0)
            self._tail.set(0.0)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._enter()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        if not self.hasFocus():
            self._leave()
        super().leaveEvent(e)

    def focusInEvent(self, e) -> None:  # noqa: N802
        self._enter()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._leave()
        super().focusOutEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(pal["acc_text"])
        if not self.isEnabled():
            col = QColor(pal["muted"])
        elif self.isDown():
            col = QColor(pal["accent"])
        p.setPen(col)
        p.setFont(self.font())
        r = QRectF(self.rect())
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self.text())
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance(self.text())
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x0 = r.center().x() - tw / 2
        a, b = min(self._tail.value, self._head.value), self._head.value
        if b - a > 0.002:
            y = r.center().y() + fm.height() / 2 + 1.5
            p.setPen(QPen(col, 1.6, cap=Qt.PenCapStyle.RoundCap))
            if rtl:                                        # the stroke starts at the right edge of the text
                p.drawLine(QPointF(x0 + tw * (1 - b), y), QPointF(x0 + tw * (1 - a), y))
            else:
                p.drawLine(QPointF(x0 + tw * a, y), QPointF(x0 + tw * b, y))


# ============================================================ scramble ======
_FA = "ابپتثجچحخدذرزسشصضطظعغفقکگلمنوهی"
_FA_DIG = "۰۱۲۳۴۵۶۷۸۹"


def _random_like(ch: str) -> str:
    if ch in _FA_DIG:
        return random.choice(_FA_DIG)
    if ch.isdigit():
        return random.choice("0123456789")
    if "؀" <= ch <= "ۿ":
        return random.choice(_FA)
    if ch.isalpha():
        pool = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return random.choice(pool) if ch.isupper() else random.choice(pool).lower()
    return ch


class ScrambleLabel(QLabel):
    """QLabel whose text shuffles and then settles one character at a time (``replay``). The layout never jitters:
    the real text stays in the label, only the painting is swapped while the animation runs."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._k = 1.0
        self._run = False
        self._t0 = 0.0
        self._ms = 700
        self._timer = QTimer(self, interval=32)
        self._timer.timeout.connect(self._step)
        self._shown = ""
        self._seed = 0

    def replay(self, ms: int = 700, delay_ms: int = 0) -> None:
        if self.wordWrap() or not self.text().strip():
            return
        self._ms = ms
        self._t0 = time.monotonic() + delay_ms / 1000.0
        self._run = True
        self._timer.start()
        self._step()

    def _step(self) -> None:
        k = (time.monotonic() - self._t0) * 1000.0 / self._ms
        if k >= 1.0:
            self._run = False
            self._timer.stop()
            self.update()
            return
        self._k = max(0.0, k)
        txt = self.text()
        n = len(txt)
        settled = int(n * (1 - (1 - self._k) ** 2))            # eased: many letters settle early
        self._shown = "".join(c if i < settled or c.isspace() else _random_like(c) for i, c in enumerate(txt))
        self.update()

    def hideEvent(self, e) -> None:  # noqa: N802
        self._run = False
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        if not self._run or time.monotonic() < self._t0:
            if self._run:                                       # waiting out the delay: draw nothing yet
                return
            super().paintEvent(e)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.font())
        p.setPen(self.palette().windowText().color())
        p.setOpacity(0.55 + 0.45 * self._k)
        al = QStyle.visualAlignment(self.layoutDirection(), self.alignment())
        p.drawText(self.contentsRect(), int(al), self._shown or self.text())


# ============================================================ spinners ======
class Spinner(QWidget):
    """Small loading glyph. kind = 'arc' (rotating arc) | 'ring' (expanding, fading ping)."""

    def __init__(self, size: int = 16, kind: str = "arc", color: QColor | str | None = None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._color = QColor(color) if color is not None else None
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._t = 0.0
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._step)

    def _step(self) -> None:
        self._t = time.monotonic()
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        col = self._color or QColor(_fpal(self)["text"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = float(self.width())
        w = max(1.6, s / 8)
        r = QRectF(w, w, s - 2 * w, s - 2 * w)
        if self.kind == "ring":
            k = (self._t * 1.1) % 1.0
            for j in (0.0, 0.5):
                kk = (k + j) % 1.0
                rr_ = r.center()
                rad = (s / 2 - w / 2) * (0.25 + 0.75 * kk)
                p.setPen(QPen(_alpha(col, 0.9 * (1 - kk)), w * 0.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(rr_, rad, rad)
            return
        p.setPen(QPen(_alpha(col, 0.22), w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        p.setPen(QPen(col, w, cap=Qt.PenCapStyle.RoundCap))
        start = -int(((self._t * 1.3) % 1.0) * 360 * 16)
        p.drawArc(r, start, -int(100 * 16 + 80 * 16 * (0.5 + 0.5 * math.sin(self._t * 3.0))))


def set_loading(btn: QPushButton, on: bool, text: str | None = None) -> None:
    """Put a push button into (or out of) a loading state: disabled, optional caption, spinner on the start side."""
    sp: Spinner | None = getattr(btn, "_ld_spinner", None)
    if on:
        if sp is not None:
            return
        btn._ld_text = btn.text()
        if text:
            btn.setText(text)
        btn.setEnabled(False)
        sp = Spinner(16, "arc", QColor(_fpal(btn)["muted"]), btn)
        rtl = btn.layoutDirection() == Qt.LayoutDirection.RightToLeft
        sp.move(btn.width() - 14 - 16 if rtl else 14, (btn.height() - 16) // 2)
        sp.show()
        btn._ld_spinner = sp
    elif sp is not None:
        sp.hide()
        sp.setParent(None)
        sp.deleteLater()
        btn._ld_spinner = None
        btn.setText(getattr(btn, "_ld_text", btn.text()))
        btn.setEnabled(True)


# ============================================================ staggered entrance ===
def _entrance_targets(page: QWidget, max_items: int = 14) -> list[QWidget]:
    """The visible top-level cards / KPI tiles of a page, in reading order (top to bottom, right to left)."""
    from .premium import KpiTile
    view = QRectF(page.rect())
    found: list[tuple[QWidget, QRectF]] = []
    for w in page.findChildren(QWidget):
        if not (isinstance(w, KpiTile) or (isinstance(w, QFrame) and w.objectName() == "Card")):
            continue
        if not w.isVisibleTo(page):
            continue
        r = QRectF(QPointF(w.mapTo(page, QPoint(0, 0))), QSizeF(w.size()))
        if r.width() > 60 and r.height() > 30 and r.intersects(view):
            found.append((w, r))
    have = {id(w) for w, _r in found}
    top: list[tuple[QWidget, QRectF]] = []
    for w, r in found:                                   # a card inside another card moves with its parent
        p = w.parentWidget()
        nested = False
        while p is not None and p is not page:
            if id(p) in have:
                nested = True
                break
            p = p.parentWidget()
        if not nested:
            top.append((w, r))
    top.sort(key=lambda t: (round(t[1].top() / 24), -t[1].right()))
    return [w for w, _r in top[:max_items]]


class _SlideFade(QGraphicsEffect):
    """Entrance effect that only changes how a widget is PAINTED (horizontal offset + opacity).

    The widget's geometry is never touched, so the layout stays the single source of truth: a resize, a late layout
    pass or a scrollbar appearing mid-animation cannot leave a card in a stale spot (the old pos()-animation did)."""

    def __init__(self, parent: QWidget, dist: float):
        super().__init__(parent)
        self.dist = float(dist)
        self.dx, self.op = float(dist), 0.0

    def set(self, dx: float, op: float) -> None:
        self.dx, self.op = dx, max(0.0, min(1.0, op))
        self.update()

    def boundingRectFor(self, r: QRectF) -> QRectF:  # noqa: N802
        return r.adjusted(-self.dist * 0.25, 0, self.dist, 0)      # room for the start offset and the overshoot

    def draw(self, p: QPainter) -> None:
        if self.op <= 0.003:
            return
        pm, off = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        p.save()
        p.setOpacity(self.op)
        p.drawPixmap(QPointF(off) + QPointF(self.dx, 0), pm)
        p.restore()


def _clear(st: dict) -> None:
    st["dead"] = True
    try:
        st["anim"].stop()
        if st["w"].graphicsEffect() is st["eff"]:
            st["w"].setGraphicsEffect(None)
        st["anim"].deleteLater()                         # a finished entrance leaves nothing behind on the (long-lived) card
    except RuntimeError:                                 # the widget was deleted meanwhile
        pass


def finish_stagger(page: QWidget) -> None:
    """End an unfinished entrance at once (page switched away / re-entered): every card shows at rest."""
    for st in getattr(page, "_stagger", []):
        _clear(st)
    page._stagger = []


def _stepper(st: dict, spring: QEasingCurve, fade: QEasingCurve):
    eff = st["eff"]

    def step(t) -> None:
        t = float(t)
        try:
            eff.set(eff.dist * (1.0 - spring.valueForProgress(t)), fade.valueForProgress(min(1.0, t / 0.62)))
        except RuntimeError:
            pass
    return step


def _finisher(page: QWidget, st: dict):
    def done() -> None:
        _clear(st)
        try:
            lst = getattr(page, "_stagger", [])
            if st in lst:
                lst.remove(st)
        except RuntimeError:
            pass
    return done


def _starter(st: dict):
    def start() -> None:
        if not st.get("dead"):
            try:
                st["anim"].start()
            except RuntimeError:
                pass
    return start


def stagger_in(page: QWidget, step_ms: int = 70, dist: int = 46, ms: int = 620) -> None:
    """Cards slide in from the right (the start side) one after another with a springy overshoot while fading in."""
    finish_stagger(page)
    if not MOTION[0]:
        return
    spring = QEasingCurve(QEasingCurve.Type.OutBack)
    spring.setOvershoot(1.25)
    fade = QEasingCurve(QEasingCurve.Type.OutCubic)
    state: list[dict] = []
    for i, w in enumerate(_entrance_targets(page)):
        eff = _SlideFade(w, dist)
        w.setGraphicsEffect(eff)
        an = QVariantAnimation(w)
        an.setStartValue(0.0)
        an.setEndValue(1.0)
        an.setDuration(ms)
        st = {"w": w, "eff": eff, "anim": an}
        an.valueChanged.connect(_stepper(st, spring, fade))
        an.finished.connect(_finisher(page, st))
        state.append(st)
        QTimer.singleShot(i * step_ms, _starter(st))
    page._stagger = state


MOTION = [True]          # global switch (user preference "reduce motion" turns it off)


# ------------------------------------------------------------- stripe clock ---
STRIPE_PERIOD = 14.0                     # px between two diagonal stripes
_STRIPE_W: "weakref.WeakSet[QWidget]" = weakref.WeakSet()
_stripe = {"timer": None, "phase": 0.0}


def stripe_phase() -> float:
    """Current stripe offset in px (0 ≤ x < STRIPE_PERIOD); one shared clock drives every animated bar."""
    return _stripe["phase"]


def stripe_tick() -> None:
    _stripe["phase"] = (time.monotonic() * 26.0) % STRIPE_PERIOD
    live = [w for w in list(_STRIPE_W) if w.isVisible()]
    if QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
        return                                            # nobody is looking: no repaints, no CPU
    for w in live:
        w.update()


def stripe_watch(w: QWidget, on: bool) -> None:
    """Register / unregister a widget for the shared ~30 fps stripe clock (starts and stops itself)."""
    if on and MOTION[0]:
        _STRIPE_W.add(w)
        if _stripe["timer"] is None:
            t = QTimer()
            t.setInterval(33)
            t.timeout.connect(stripe_tick)
            _stripe["timer"] = t
        if not _stripe["timer"].isActive():
            _stripe["timer"].start()
    else:
        _STRIPE_W.discard(w)
        if not _STRIPE_W and _stripe["timer"] is not None:
            try:
                _stripe["timer"].stop()
            except RuntimeError:                         # interpreter / QApplication shutting down
                _stripe["timer"] = None

