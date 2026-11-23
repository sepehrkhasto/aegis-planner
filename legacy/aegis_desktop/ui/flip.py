# SPDX-License-Identifier: GPL-3.0-or-later
"""FLIP list motion: rows glide to their new place, new rows fade in and removed rows fade out.

Item views rebuild their rows in one go, so a completed / deleted / added task would simply *jump*. Here we
(F)irst take a picture of the visible rows, let the view update, (L)ast take a second picture, and then play the
(I)nversion for a moment on a transparent overlay: every row slides from its old y to its new y. The view itself is
never touched - after ~0.3 s the overlay disappears and the real, identical rows are underneath.
"""
from __future__ import annotations

from collections import Counter

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRect, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractItemView, QWidget

from .anim import MOTION
from .fx_widgets import _fpal

UR = Qt.ItemDataRole.UserRole
MAX_ROWS = 80                                                     # only what is on screen; huge lists just snap
SUSPEND = [False]                                                 # True while the whole window restyles (a theme switch): nothing moved


def _items(view: QAbstractItemView) -> dict[str, QRect]:
    """{row id: full-width rect} of the rows visible in the viewport, in order."""
    vp = view.viewport()
    m = view.model()
    out: dict[str, QRect] = {}
    if m is None or m.rowCount() == 0:
        return out
    first = view.indexAt(QPoint(5, 1))
    r0 = first.row() if first.isValid() else 0
    for r in range(max(0, r0), min(m.rowCount(), r0 + MAX_ROWS)):
        idx = m.index(r, 0)
        rect = view.visualRect(idx)
        if rect.top() > vp.height():
            break
        rid = idx.data(UR)
        if rid is None or rect.height() <= 0:
            continue
        out[str(rid)] = QRect(0, rect.top(), vp.width(), rect.height())
    return out


def capture(view: QAbstractItemView) -> dict | None:
    """Step F: call right before the view's rows change. Returns None when animating makes no sense."""
    if not MOTION[0] or SUSPEND[0] or not view.isVisible() or view.viewport().width() < 50:
        return None
    finish(view)
    items = _items(view)
    if not items:
        return None
    return {"pm": view.viewport().grab(), "items": items}


def finish(view: QAbstractItemView) -> None:
    ov = getattr(view, "_flip", None)
    view._flip = None
    if ov is not None:
        try:
            ov.an.stop()
            ov.hide()
            ov.deleteLater()
        except RuntimeError:
            pass


def _background(pm, items: dict[str, QRect], pal: dict) -> QColor:
    """The colour rows sit on: the most common pixel at the row starts (falls back to the theme's panel colour)."""
    img = pm.toImage()
    dpr = max(1.0, pm.devicePixelRatio())
    seen: Counter = Counter()
    for r in list(items.values())[:12]:
        x, y = int(2 * dpr), int(min(img.height() - 1, (r.center().y()) * dpr))
        if 0 <= y < img.height() and x < img.width():
            seen[img.pixelColor(x, y).name(QColor.NameFormat.HexArgb)] += 1
    if seen:
        c = QColor(seen.most_common(1)[0][0])
        if c.alpha() >= 250:
            return c
    return QColor(pal["panel"])


class _Overlay(QWidget):
    def __init__(self, view: QAbstractItemView, before: dict, after: dict, spring: bool = False):
        super().__init__(view.viewport())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(view.viewport().rect())
        self.b_pm, self.b_items = before["pm"], before["items"]
        self.a_pm, self.a_items = after["pm"], after["items"]
        self.bg = _background(self.a_pm, self.a_items, _fpal(view))
        self.t = 0.0
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.base = 420 if spring else 300
        self.new_order = sorted((rid for rid in self.a_items if rid not in self.b_items), key=lambda r: self.a_items[r].top())
        self.stag = min(len(self.new_order), 12) * 30                  # new rows enter one after another, 30 ms apart
        self.an.setDuration(self.base + self.stag)
        if spring:                                                     # cards overshoot a hair and settle (kanban)
            oc = QEasingCurve(QEasingCurve.Type.OutBack)
            oc.setOvershoot(1.05)
            self.an.setEasingCurve(oc)
        else:
            self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.valueChanged.connect(self._tick)
        self._view = view
        self.an.finished.connect(self._end)
        view.viewport().installEventFilter(_Guard(view, self))

    def _end(self) -> None:
        finish(self._view)

    def _tick(self, v) -> None:
        self.t = float(v)
        self.update()

    @staticmethod
    def _strip(p: QPainter, pm, rect: QRect, y: float, opacity: float) -> None:
        dpr = pm.devicePixelRatio()
        p.setOpacity(max(0.0, min(1.0, opacity)))
        p.drawPixmap(QRectF(0, y, rect.width(), rect.height()), pm,
                     QRectF(rect.x() * dpr, rect.y() * dpr, rect.width() * dpr, rect.height() * dpr))

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        t = self.t
        for rid, rect in self.b_items.items():                         # leaving rows dissolve where they stood
            if rid not in self.a_items:
                self._strip(p, self.b_pm, rect, rect.top() - 6 * t, 1.0 - min(1.0, t * 1.6))
        for rid, rect in self.a_items.items():
            old = self.b_items.get(rid)
            if old is not None:                                        # rows glide from where they were
                self._strip(p, self.a_pm, rect, old.top() + (rect.top() - old.top()) * t, 1.0)
            else:                                                      # new rows rise 8 px into place, staggered by 30 ms
                i = min(self.new_order.index(rid), 12)
                k = max(0.0, min(1.0, (t * (self.base + self.stag) - i * 30) / self.base))
                k = 1 - (1 - k) ** 3
                self._strip(p, self.a_pm, rect, rect.top() + 8 * (1.0 - k), k)
        p.end()


class _Guard(QObject):
    """Ends the effect at once if the view is resized or hidden mid-flight (the overlay would be stale)."""

    def __init__(self, view, ov):
        super().__init__(ov)
        self.view = view

    def eventFilter(self, o, e) -> bool:  # noqa: N802
        if e.type() in (QEvent.Type.Resize, QEvent.Type.Hide):
            finish(self.view)
        return False


def play(view: QAbstractItemView, before: dict | None, spring: bool = False) -> None:
    """Step L + I: call right after the rows changed."""
    if before is None or not MOTION[0] or SUSPEND[0] or not view.isVisible():
        return
    view.viewport().repaint()                                          # make sure the grab shows the new rows
    after = {"pm": view.viewport().grab(), "items": _items(view)}
    b, a = before["items"], after["items"]
    if not a and not b:
        return
    if list(a) == list(b) and all(a[k].top() == b[k].top() for k in a):
        return                                                         # nothing moved
    ov = _Overlay(view, before, after, spring)
    view._flip = ov
    ov.show()
    ov.raise_()
    ov.an.start()


def gate(page: QWidget, sig) -> bool:
    """Animate only real data changes: not when a filter changed (that is a new list) and not while the page is
    still making its own entrance."""
    import time
    ok = getattr(page, "_flip_sig", None) == sig and time.monotonic() - getattr(page, "_flip_shown", 0.0) > 0.7
    page._flip_sig = sig
    return ok


class _XFade(QWidget):
    def __init__(self, host: QWidget, pm, ms: int):
        super().__init__(host)
        self.pm, self.k = pm, 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(host.rect())
        self.an = QVariantAnimation(self)
        self.an.setStartValue(1.0)
        self.an.setEndValue(0.0)
        self.an.setDuration(ms)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self._end)

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def _end(self) -> None:
        self.hide()
        self.deleteLater()

    def paintEvent(self, _e) -> None:  # noqa: N802
        """The page we left recedes: it fades, shrinks a hair (1 -> 0.985) and drifts toward the end side (left in RTL),
        so the new page reads as arriving from the start side rather than just appearing."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        q = 1.0 - self.k
        p.setOpacity(self.k)
        c = self.rect().center()
        p.translate(c.x() - 14 * q, c.y())
        s = 1.0 - 0.015 * q
        p.scale(s, s)
        p.translate(-c.x(), -c.y())
        p.drawPixmap(self.rect(), self.pm)


class _Melt(QWidget):
    """A picture of the window as it was, fading away over the restyled one - a theme switch reads as one soft change."""

    def __init__(self, host: QWidget, pm, ms: int):
        super().__init__(host)
        self.pm, self.k = pm, 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(host.rect())
        self.an = QVariantAnimation(self)
        self.an.setStartValue(1.0)
        self.an.setEndValue(0.0)
        self.an.setDuration(ms)
        self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self._end)

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def _end(self) -> None:
        self.hide()
        self.deleteLater()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setOpacity(self.k)
        p.drawPixmap(self.rect(), self.pm)


def melt(host: QWidget, pm, ms: int = 220) -> None:
    old = getattr(host, "_melt", None)
    if old is not None:
        try:
            old.an.stop()
            old.hide()
            old.deleteLater()
        except RuntimeError:
            pass
    x = host._melt = _Melt(host, pm, ms)
    x.show()
    x.raise_()
    x.an.start()


def crossfade(host: QWidget, pm, ms: int = 190) -> None:
    """The page we just left melts away over the new one (a picture of it, faded out and thrown away)."""
    old = getattr(host, "_xfade", None)
    if old is not None:
        try:
            old.an.stop()
            old.hide()
            old.deleteLater()
        except RuntimeError:
            pass
    x = host._xfade = _XFade(host, pm, ms)
    x.show()
    x.raise_()
    x.an.start()


class _Slide(QWidget):
    """Old view drifts out and fades while the new one drifts in from the other side (a short, subtle glide)."""

    def __init__(self, host: QWidget, old, new, s: int, ms: int = 300):
        super().__init__(host)
        self.old, self.new, self.dir, self.k = old, new, 1 if s > 0 else -1, 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(host.rect())
        self.bg = _fpal(host)["bg"]
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(ms)
        self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self._end)

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def _end(self) -> None:
        self.hide()
        self.deleteLater()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.bg))
        dx = self.width() * 0.07
        k = self.k
        p.setOpacity(1.0 - min(1.0, k * 1.5))
        p.drawPixmap(QRectF(self.dir * dx * k, 0, self.width(), self.height()), self.old, QRectF(self.old.rect()))
        p.setOpacity(min(1.0, k * 1.4))
        p.drawPixmap(QRectF(-self.dir * dx * (1 - k), 0, self.width(), self.height()), self.new, QRectF(self.new.rect()))


def slide(host: QWidget, old, new, s: int) -> None:
    prev = getattr(host, "_slide", None)
    if prev is not None:
        try:
            prev.an.stop()
            prev.hide()
            prev.deleteLater()
        except RuntimeError:
            pass
    x = host._slide = _Slide(host, old, new, s)
    x.show()
    x.raise_()
    x.an.start()
