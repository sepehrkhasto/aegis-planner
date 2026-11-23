# SPDX-License-Identifier: GPL-3.0-or-later
"""Micro-interactions: small, fast details that make the app feel alive without ever getting in the way.

  * ``PressButton``        - a button dips to 97 % under the finger and springs back.
  * ``install_focus_fade`` - text fields bloom a soft accent halo when they get the keyboard focus.
  * ``check_kick``/``check_k`` - a shared clock for the "task completed" moment (circle fill, drawn tick, burst ring,
                              title strike sweeping across); views only repaint while an animation is really running.

Every effect honours the "reduce motion" preference (``anim.MOTION``) and only paints - geometry is never touched.
"""
from __future__ import annotations

import time
import weakref

from PyQt6.QtCore import QEasingCurve, QEvent, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractSpinBox, QComboBox, QFrame, QGraphicsEffect, QLineEdit, QPlainTextEdit, QPushButton,
                             QTextEdit, QWidget)

from .anim import MOTION
from .fx_widgets import _fpal
from .theme import rr

# ================================================================== press ===
_DOWN = 0.98


class _Scale(QGraphicsEffect):
    """Paints the widget scaled about its centre (only while a press is in progress)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.s = 1.0

    def boundingRectFor(self, r: QRectF) -> QRectF:  # noqa: N802
        return r.adjusted(-4, -4, 4, 4)                      # room for the tiny overshoot on release

    def draw(self, p: QPainter) -> None:
        pm, off = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        size = pm.deviceIndependentSize()
        c = QRectF(off.x(), off.y(), size.width(), size.height()).center()
        p.save()
        p.translate(c)
        p.scale(self.s, self.s)
        p.translate(-c)
        p.drawPixmap(off, pm)
        p.restore()


def _press_to(w: QWidget, target: float, ms: int, curve: QEasingCurve, remove_at_end: bool) -> None:
    st = getattr(w, "_press_fx", None)
    if not MOTION[0]:
        return
    if st is None:
        if w.graphicsEffect() is not None:                     # a stagger / another effect owns the widget
            return
        eff = _Scale(w)
        w.setGraphicsEffect(eff)
        an = QVariantAnimation(w)
        st = w._press_fx = {"eff": eff, "an": an}

        def tick(v, st=st) -> None:
            try:
                st["eff"].s = float(v)
                st["eff"].update()
            except RuntimeError:
                pass
        an.valueChanged.connect(tick)
    eff, an = st["eff"], st["an"]
    try:
        an.stop()
        try:
            an.finished.disconnect()
        except TypeError:
            pass
        an.setStartValue(eff.s)
        an.setEndValue(target)
        an.setDuration(ms)
        an.setEasingCurve(curve)
        if remove_at_end:
            an.finished.connect(lambda w=w: _press_clear(w))
        an.start()
    except RuntimeError:
        w._press_fx = None


def _press_clear(w: QWidget) -> None:
    try:
        st = getattr(w, "_press_fx", None)
        w._press_fx = None
        if st is not None:
            st["an"].stop()
            if w.graphicsEffect() is st["eff"]:
                w.setGraphicsEffect(None)
    except RuntimeError:
        pass


_OUT = QEasingCurve(QEasingCurve.Type.OutCubic)
_SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
_SPRING.setOvershoot(2.2)


class PressButton(QPushButton):
    """QPushButton that gives a physical press: 96.5 % on the way down, a small spring on the way up, a soft ripple
    from the point of contact, and - on the primary (gold) action - one gilt glint across it when the pointer arrives."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._rip = QVariantAnimation(self)
        self._rip.setDuration(520)
        self._rip.setStartValue(0.0)
        self._rip.setEndValue(1.0)
        self._rip.setEasingCurve(_OUT)
        self._rip.valueChanged.connect(lambda _v: self.update())
        self._rip_at = QRectF().center()
        self._glint = None

    def enterEvent(self, e) -> None:  # noqa: N802
        if self.objectName() == "Primary" and self.isEnabled():
            if self._glint is None:
                from .brand import GlintPass
                self._glint = GlintPass(self)
            self._glint.start()
        super().enterEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        rip = self._rip.state() == QVariantAnimation.State.Running
        gl = self._glint is not None and self._glint.running
        if not (rip or gl):
            return
        from . import theme
        pal = _fpal(self)
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = float(theme.RADIUS[0])
        if gl:
            self._glint.paint(p, r, rad, pal, 0.75)
        if rip:
            from PyQt6.QtGui import QPainterPath
            k = float(self._rip.currentValue())
            col = QColor("#ffffff") if self.objectName() == "Primary" else QColor(pal["text"])
            col.setAlpha(int((70 if self.objectName() == "Primary" else 30) * (1 - k)))
            clip = QPainterPath()
            clip.addRoundedRect(r, rad, rad)
            p.setClipPath(clip)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            rad_px = max(r.width(), r.height()) * 0.95 * k
            p.drawEllipse(self._rip_at, rad_px, rad_px)
        p.end()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            _press_to(self, _DOWN, 80, _OUT, False)
            if MOTION[0]:
                self._rip_at = e.position()
                self._rip.stop()
                self._rip.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if getattr(self, "_press_fx", None) is not None:
            _press_to(self, 1.0, 240, _SPRING, True)
        super().mouseReleaseEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        _press_clear(self)
        self._rip.stop()
        if self._glint is not None:
            self._glint.stop()
        super().hideEvent(e)


# ================================================================== focus ===
class _FocusRing(QWidget):
    """Transparent overlay inside a text field: an accent halo that fades in on focus and out on blur."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.host, self.k = host, 0.0
        self.an = QVariantAnimation(self)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self._done)
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.hide()

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def _done(self) -> None:
        if self.k <= 0.001:
            self.hide()

    def go(self, on: bool) -> None:
        self.setGeometry(self.host.rect())
        self.raise_()
        self.show()
        self.an.stop()
        if not MOTION[0]:
            self.k = 1.0 if on else 0.0
            self.setVisible(on)
            self.update()
            return
        self.an.setDuration(170 if on else 230)
        self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.setStartValue(self.k)
        self.an.setEndValue(1.0 if on else 0.0)
        self.an.start()

    def eventFilter(self, o, e) -> bool:  # noqa: N802
        host = getattr(self, "host", None)
        if host is not None and o is host and e.type() == QEvent.Type.Resize:
            self.setGeometry(host.rect())
        return False

    def paintEvent(self, _e) -> None:  # noqa: N802
        if self.k <= 0.004:
            return
        pal = _fpal(self.host)
        acc = QColor(pal["accent2"])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = rr(8)
        halo = QColor(acc)
        halo.setAlphaF(0.20 * self.k)
        p.setPen(QPen(halo, 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), max(0.0, rad - 1), max(0.0, rad - 1))
        edge = QColor(acc)
        edge.setAlphaF(min(1.0, self.k))
        p.setPen(QPen(edge, 1.0))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)


def _eligible(w) -> bool:
    if not isinstance(w, (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit)):
        return False
    if w.objectName().startswith("qt_"):                       # the line edit inside a spin box / combo
        return False
    par = w.parentWidget()
    if isinstance(par, (QAbstractSpinBox, QComboBox)) or getattr(par, "paints_focus", False):
        return False
    try:
        if isinstance(w, QLineEdit):
            return w.hasFrame()
        if isinstance(w, QAbstractSpinBox):
            return w.hasFrame()
        return w.frameShape() != QFrame.Shape.NoFrame
    except RuntimeError:
        return False


def _ring(w: QWidget) -> _FocusRing:
    ring = getattr(w, "_focus_ring", None)
    if ring is None:
        ring = w._focus_ring = _FocusRing(w)
    return ring


def _focus_changed(old, new) -> None:
    for w, on in ((old, False), (new, True)):
        if w is None:
            continue
        try:
            if _eligible(w) and (on or getattr(w, "_focus_ring", None) is not None):
                _ring(w).go(on)
        except RuntimeError:                                   # widget deleted between the signal and now
            pass


_installed = [False]


def install_focus_fade(app=None) -> None:
    """Connect once: the fade is driven by QApplication.focusChanged, so idle widgets cost nothing."""
    if _installed[0]:
        return
    app = app or QGuiApplication.instance()
    if app is not None:
        app.focusChanged.connect(_focus_changed)
        _installed[0] = True


# ================================================== task-completed moment ===
DUR = 0.46                                                        # seconds
_CHK: dict[tuple[int, str], tuple[float, bool, "weakref.ref"]] = {}
_clock: dict = {"timer": None}


def _tick() -> None:
    now = time.monotonic()
    views: dict[int, object] = {}
    for key, (t0, _on, ref) in list(_CHK.items()):
        v = ref()
        if v is None or now - t0 > DUR + 0.05:
            _CHK.pop(key, None)
            if v is not None:
                views[id(v)] = v                                # one last repaint at rest
            continue
        views[id(v)] = v
    for v in views.values():
        try:
            v.viewport().update()
        except RuntimeError:
            pass
    if not _CHK and _clock["timer"] is not None:
        _clock["timer"].stop()


def check_kick(view, key, on: bool) -> None:
    """A task was just (un)completed in ``view``: run the transition for ``key`` (the task id)."""
    if on:
        from . import sfx
        sfx.play("tick")
    if not MOTION[0] or view is None or key is None:
        return
    _CHK[(id(view), str(key))] = (time.monotonic(), bool(on), weakref.ref(view))
    if _clock["timer"] is None:
        t = QTimer()
        t.setInterval(16)
        t.timeout.connect(_tick)
        _clock["timer"] = t
    if not _clock["timer"].isActive():
        _clock["timer"].start()


def check_k(view, key) -> tuple[float, bool] | None:
    """(progress 0..1, target state) of a running transition, or None when the row is at rest."""
    if not _CHK or key is None:
        return None
    rec = _CHK.get((id(view), str(key)))
    if rec is None:
        return None
    k = (time.monotonic() - rec[0]) / DUR
    return (min(1.0, max(0.0, k)), rec[1]) if k < 1.0 else None


def ease(name: str, t: float) -> float:
    return _EASE[name].valueForProgress(max(0.0, min(1.0, t)))


_BACK = QEasingCurve(QEasingCurve.Type.OutBack)
_BACK.setOvershoot(1.9)
_EASE = {"back": _BACK, "out": QEasingCurve(QEasingCurve.Type.OutCubic)}


def sweep(k: float, on: bool) -> float:
    """How much of a title is struck through (0..1) at progress ``k`` of a transition to ``on``."""
    s = ease("out", (k - 0.12) / 0.62)
    return s if on else 1.0 - ease("out", k / 0.5)


# ============================================================== dialogs ===
class _Scrim(QWidget):
    """A dimming veil over the window behind a modal dialog; fades in with the dialog."""

    def __init__(self, win: QWidget):
        super().__init__(win)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(win.rect())
        self.k = 0.0
        self.an = QVariantAnimation(self)
        self.an.valueChanged.connect(self._tick)

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def go(self, to: float, ms: int) -> None:
        self.an.stop()
        self.an.setStartValue(self.k)
        self.an.setEndValue(to)
        self.an.setDuration(ms)
        self.an.start()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, int(105 * self.k)))


from PyQt6.QtWidgets import QDialog  # noqa: E402

LAST_CLICK: dict = {"t": 0.0, "pos": None}       # where and when the pointer last pressed (set by the app-wide input filter)
MORPH_WINDOW_S = 0.7                              # a dialog that opens this soon after a click grows out of that click


def note_click(global_pos) -> None:
    LAST_CLICK["t"], LAST_CLICK["pos"] = time.monotonic(), global_pos


class _Morph(QWidget):
    """A picture of the dialog that grows from the click point to the dialog's place, then hands over to the real thing."""

    def __init__(self, pm, start: "QRectF", end: "QRectF", on_done):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.pm, self.a, self.b, self.on_done, self.k = pm, start, end, on_done, 0.0
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(240)
        self.an.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self.an.valueChanged.connect(self._step)
        self.an.finished.connect(self._done)
        self._step(0.0)

    def _rect(self, k: float) -> "QRectF":
        a, b = self.a, self.b
        return QRectF(a.x() + (b.x() - a.x()) * k, a.y() + (b.y() - a.y()) * k,
                      a.width() + (b.width() - a.width()) * k, a.height() + (b.height() - a.height()) * k)

    def _step(self, v) -> None:
        self.k = float(v)
        r = self._rect(self.k)
        self.setGeometry(int(r.x()), int(r.y()), max(8, int(r.width())), max(8, int(r.height())))
        self.update()

    def go(self) -> None:
        self.show()
        self.an.start()

    def _done(self) -> None:
        try:
            if self.on_done:
                self.on_done()
        finally:
            self.hide()
            self.deleteLater()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setOpacity(min(1.0, 0.35 + self.k * 0.9))
        p.drawPixmap(self.rect(), self.pm)


def morph_open(dlg: QWidget, origin_global, on_done=None) -> "_Morph | None":
    """Grow a picture of ``dlg`` from ``origin_global`` to where it sits. Returns the ghost, or None when it is not worth it."""
    if not MOTION[0] or dlg.width() < 260 or dlg.height() < 160:
        return None
    pm = dlg.grab()
    if pm.isNull():
        return None
    end = QRectF(dlg.geometry())
    s = 0.16
    w, h = max(24.0, end.width() * s), max(18.0, end.height() * s)
    start = QRectF(origin_global.x() - w / 2, origin_global.y() - h / 2, w, h)
    ghost = _Morph(pm, start, end, on_done)
    ghost.go()
    return ghost


class MotionDialog(QDialog):
    """QDialog that eases in (fade) over a softly dimmed window; opened right after a click it grows out of that click."""
    MORPH = True
    SCRIM = True                                        # False: the dialog dims the window itself (the command palette)
    REAP_MS = 10_000                                    # a finished dialog is freed this long after it closed

    def done(self, r: int) -> None:
        """Dialogs are made for one use and parented to a long-lived window, so without this every one that was ever opened
        (a whole widget tree, often with a snapshot of the window) would stay in memory until the program exits. The delay
        is generous: callers read the answer straight after ``exec()`` returns."""
        super().done(r)
        QTimer.singleShot(self.REAP_MS, self._reap)

    _reap_hold = 0

    def hold_reap(self) -> None:
        """Call around code that runs on this dialog's own call stack (a signal handler such as returnPressed) and may spin a
        nested event loop: the dialog must not be freed under the Qt frames that are still below that code (use-after-free)."""
        self._reap_hold += 1

    def release_reap(self) -> None:
        self._reap_hold = max(0, self._reap_hold - 1)

    def _reap(self) -> None:
        try:
            if self._reap_hold:                         # still inside one of its own handlers: try again a little later
                QTimer.singleShot(self.REAP_MS, self._reap)
                return
            if not self.isVisible():
                self.deleteLater()
        except RuntimeError:                            # already gone with its parent
            pass

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        from . import scrollfx
        scrollfx.attach(self)
        from .a11y import ensure_names
        ensure_names(self)
        if not MOTION[0] or getattr(self, "_mo_on", False):
            return
        self._mo_on = True
        if QGuiApplication.platformName() != "offscreen":            # the headless test platform has no window opacity
            self.setWindowOpacity(0.0)
            origin = LAST_CLICK["pos"] if time.monotonic() - LAST_CLICK["t"] < MORPH_WINDOW_S else None
            self._mo_ghost = morph_open(self, origin, lambda: self.setWindowOpacity(1.0)) if (origin is not None and self.MORPH) else None
            an = QVariantAnimation(self)
            an.setStartValue(0.0)
            an.setEndValue(1.0)
            an.setDuration(170 if self._mo_ghost is None else 240)
            an.setEasingCurve(QEasingCurve.Type.OutCubic)
            if self._mo_ghost is None:
                an.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
            an.start()
            self._mo_an = an
        par = self.parentWidget()
        if self.SCRIM and par is not None and par.window().isVisible():
            self._scrim = _Scrim(par.window())
            self._scrim.show()
            self._scrim.raise_()
            self._scrim.go(1.0, 200)

    def _drop_scrim(self) -> None:
        s = getattr(self, "_scrim", None)
        self._scrim = None
        self._mo_on = False
        if s is not None:
            try:
                s.hide()
                s.deleteLater()
            except RuntimeError:
                pass

    def hideEvent(self, e) -> None:  # noqa: N802
        self._drop_scrim()
        super().hideEvent(e)


def reveal(w: QWidget, dist: int = 18, ms: int = 300) -> None:
    """A widget that just appeared slides in from the start side while fading (paint-only, layout untouched)."""
    if not MOTION[0] or w.graphicsEffect() is not None:
        return
    from .anim import _SlideFade
    eff = _SlideFade(w, dist)
    w.setGraphicsEffect(eff)
    an = QVariantAnimation(w)
    an.setStartValue(0.0)
    an.setEndValue(1.0)
    an.setDuration(ms)
    spring = QEasingCurve(QEasingCurve.Type.OutBack)

    def step(t) -> None:
        try:
            eff.set(dist * (1.0 - spring.valueForProgress(float(t))), min(1.0, float(t) * 2.2))
        except RuntimeError:
            pass

    def done() -> None:
        try:
            if w.graphicsEffect() is eff:
                w.setGraphicsEffect(None)
            an.deleteLater()
        except RuntimeError:
            pass
    an.valueChanged.connect(step)
    an.finished.connect(done)
    an.start()
