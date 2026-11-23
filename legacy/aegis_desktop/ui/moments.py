# SPDX-License-Identifier: GPL-3.0-or-later
"""The big, rare moments: opening the vault, finishing the day. Each plays once, lasts about a second and never blocks."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from .anim import MOTION
from .fx_widgets import _fpal
from .theme import rr



class _Overlay(QWidget):
    """Base: a click-through child that fills its parent, runs one 0→1 animation and removes itself."""

    def __init__(self, host: QWidget, ms: int, curve=QEasingCurve.Type.OutCubic):
        super().__init__(host)
        self.host, self.k = host, 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(host.rect())
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(ms)
        self.an.setEasingCurve(curve)
        self.an.valueChanged.connect(self._tick)
        self.an.finished.connect(self._end)

    def _tick(self, v) -> None:
        self.k = float(v)
        self.update()

    def _end(self) -> None:
        self.hide()
        self.deleteLater()

    def run(self) -> None:
        self.show()
        self.raise_()
        self.an.start()


class _Iris(_Overlay):
    """The screen opens from the centre like an iris: a dark veil with a growing clear circle and a soft glowing rim."""

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self.host)
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        diag = (w * w + h * h) ** 0.5 / 2
        rad = diag * 1.05 * self.k
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        veil = QPainterPath()
        veil.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addEllipse(c, rad, rad)
        veil = veil.subtracted(hole)
        p.fillPath(veil, QColor(pal["bg"]))
        if 4 < rad < diag:
            acc = QColor(pal["accent2"])
            g = QRadialGradient(c, rad + 34)
            edge = max(0.0, (rad - 34) / (rad + 34))
            a0 = QColor(acc)
            a0.setAlpha(0)
            a1 = QColor(acc)
            a1.setAlphaF(0.30 * (1.0 - self.k))
            g.setColorAt(0.0, a0)
            g.setColorAt(edge, a0)
            g.setColorAt(min(1.0, (rad) / (rad + 34)), a1)
            g.setColorAt(1.0, a0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, rad + 34, rad + 34)


class _Doors(_Overlay):
    """The vault doors: the Aegis shield split down the middle, each half carried by a door.

    ``opening``: the shield sits whole for a beat (a glint crosses it), then the halves part sideways and the app is
    revealed behind them. Closing plays the same thing backwards over ``backdrop`` (a picture of the screen being
    locked), then the veil melts away to reveal the sign-in screen that is already underneath."""

    HOLD = 0.18

    def __init__(self, host: QWidget, ms: int, opening: bool, backdrop=None, hold: float | None = None, caption: str = ""):
        super().__init__(host, ms, QEasingCurve.Type.Linear)
        self.opening, self.backdrop = opening, backdrop
        self.hold = self.HOLD if hold is None else hold          # the shield sits whole this long (fraction of the run)
        self.caption = caption                                     # engraved line under the shield (the creation ritual)
        self._mark = None

    def _openness(self) -> float:
        """0 = doors shut, 1 = fully apart."""
        k = self.k
        ease = QEasingCurve(QEasingCurve.Type.InOutCubic)
        if self.opening:
            return ease.valueForProgress(max(0.0, min(1.0, (k - self.hold) / (1 - self.hold))))
        return 1.0 - ease.valueForProgress(max(0.0, min(1.0, k / 0.55)))

    def _mark_pm(self, size: int):
        if self._mark is None or self._mark.width() != int(size * 2):
            from . import brand
            self._mark = brand.render_mark(size, _fpal(self.host), 2.0)
        return self._mark

    def _seal_sweep(self) -> float:
        """How much of the seal ring is drawn (0..1): locking draws it as the doors meet, unlocking unwinds it."""
        if self.opening:
            return 1.0 - max(0.0, min(1.0, self.k / (self.hold + 0.28)))
        return max(0.0, min(1.0, (self.k - 0.34) / 0.26))

    def _seal_click(self) -> float:
        return (self.k - 0.60) / 0.22 if not self.opening else -1.0

    def paintEvent(self, _e) -> None:  # noqa: N802
        from . import brand
        pal = _fpal(self.host)
        w, h = self.width(), self.height()
        e, half = self._openness(), self.width() / 2
        off = half * e
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.opening:
            fade = 1.0 - max(0.0, min(1.0, (self.k - 0.8) / 0.2))          # the veil melts away at the very end
            p.setOpacity(fade)
            if self.backdrop is not None and e > 0.001:
                p.drawPixmap(0, 0, self.backdrop)
        bg = QColor(pal["bg"])
        acc = QColor(pal["accent"])
        size = int(max(120, min(220, min(w, h) * 0.28)))
        mark = self._mark_pm(size)
        cx, cy = w / 2, h / 2
        for side in (-1, 1):
            rect = QRectF(-off, 0, half + 1, h) if side < 0 else QRectF(half + off - 1, 0, half + 1, h)
            g = QLinearGradient(rect.left(), 0, rect.right(), 0)
            near, far = (QColor(bg.red() + 9, bg.green() + 8, bg.blue() + 4), bg)
            g.setColorAt(0, far if side < 0 else near)
            g.setColorAt(1, near if side < 0 else far)
            p.fillRect(rect, g)
            p.save()
            p.setClipRect(rect)
            p.setOpacity(p.opacity() * (1.0 - 0.85 * e))
            p.drawPixmap(QPointF(cx - size / 2 - (off if side < 0 else -off), cy - size / 2 - 0), mark,
                         QRectF(0, 0, mark.width(), mark.height()))
            p.restore()
        if e < 0.995:                                                       # the lit seam between the doors
            for wd, al in ((18, 26), (8, 60), (2, 230)):
                col = QColor(acc.red(), acc.green(), acc.blue(), int(al * (1 - e)))
                p.fillRect(QRectF(cx - wd / 2, 0, wd, h), col)
            if self.opening or e > 0.01:
                edge = QColor(acc.red(), acc.green(), acc.blue(), int(110 * (1 - e)))
                p.fillRect(QRectF(-off + half - 1, 0, 1, h), edge)
                p.fillRect(QRectF(half + off, 0, 1, h), edge)
        sweep = self._seal_sweep()                                            # «مُهر شدن»: a ring closes around the mark (opens again on unlock)
        if sweep > 0.002:
            rad = size * 0.64
            ring = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
            pen = QPen(QColor(acc.red(), acc.green(), acc.blue(), 70), 5.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(ring, 90 * 16, int(-360 * 16 * sweep))                  # soft under-glow
            pen = QPen(QColor(pal["accent2"]), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, int(-360 * 16 * sweep))
            import math
            a = math.radians(90 - 360 * sweep)                                # the bright head of the stroke
            hx, hy = cx + rad * math.cos(a), cy - rad * math.sin(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(hx, hy), 2.6, 2.6)
            if sweep >= 0.999:                                                # the click: one thin ring of light leaves the seal
                kk = self._seal_click()
                if 0 < kk < 1:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(acc.red(), acc.green(), acc.blue(), int(150 * (1 - kk))), 1.4))
                    p.drawEllipse(QPointF(cx, cy), rad * (1 + 0.35 * kk), rad * (1 + 0.35 * kk))
        gk = self.k / (self.hold + 0.12) if self.opening else (self.k - 0.5) / 0.3
        if 0.0 < gk < 1.0 and e < 0.35:                                       # one glint crosses the whole shield
            x = -60 + (w + 120) * gk if self.opening else w + 60 - (w + 120) * gk
            g = QLinearGradient(x - 60, 0, x + 60, 0)
            hi = QColor(pal["accent2"])
            g.setColorAt(0, QColor(hi.red(), hi.green(), hi.blue(), 0))
            g.setColorAt(0.5, QColor(hi.red(), hi.green(), hi.blue(), int(58 * (1 - e) * brand_sin(gk))))
            g.setColorAt(1, QColor(hi.red(), hi.green(), hi.blue(), 0))
            p.fillRect(QRectF(0, 0, w, h), g)
        if self.caption and self.opening:                                     # «your vault is sealed»: fades in, then out as the doors part
            a = max(0.0, min(1.0, (self.k - 0.10) / 0.16)) * (1.0 - max(0.0, min(1.0, (e - 0.02) / 0.25)))
            if a > 0.01:
                p.setOpacity(a)
                p.setPen(QColor(pal["accent2"]))
                p.setFont(brand.display_font(20, True, 3.0))
                p.drawText(QRectF(0, cy + size / 2 + 18, w, 34), Qt.AlignmentFlag.AlignCenter, "AEGIS")
                p.setPen(QColor(pal["text"]))
                f = QFont(self.font())
                f.setPointSizeF(f.pointSizeF() + 1.5)
                p.setFont(f)
                p.drawText(QRectF(0, cy + size / 2 + 54, w, 26), Qt.AlignmentFlag.AlignCenter, self.caption)
                p.setOpacity(1.0)


def brand_sin(t: float) -> float:
    import math
    return math.sin(math.pi * max(0.0, min(1.0, t)))


def unlock_bloom(host: QWidget) -> None:
    """The vault opens: the two halves of the shield part and the app appears behind them (~1.1 s, never blocks)."""
    if not MOTION[0] or host.width() < 100:
        return
    _Doors(host, 1100, True).run()


def vault_born(host: QWidget, caption: str) -> None:
    """First run, right after the vault is created: the shield stays whole for a long beat with an engraved line, then
    the doors part (~2.4 s). The ritual that says «this is yours now»."""
    if not MOTION[0] or host.width() < 100:
        return
    _Doors(host, 2400, True, hold=0.45, caption=caption).run()


def lock_close(host: QWidget, backdrop) -> None:
    """The vault closes over ``backdrop`` (a QPixmap of what was on screen); ``host`` already shows the sign-in page."""
    if not MOTION[0] or host.width() < 100 or backdrop is None or backdrop.isNull():
        return
    _Doors(host, 1000, False, backdrop).run()


class _Seal(_Overlay):
    """«امروز مهر شد»: a gilt seal is stamped onto the page (slams in, a ring of light spreads, a glint crosses it),
    rests for a moment and dissolves. Rare - only the moment the last task of today is finished."""

    R = 66.0

    def __init__(self, host: QWidget):
        super().__init__(host, 2600, QEasingCurve.Type.Linear)

    def paintEvent(self, _e) -> None:  # noqa: N802
        from . import brand
        pal = _fpal(self.host)
        k = self.k
        c = QPointF(self.width() / 2, min(self.height() * 0.42, 240.0))
        slam = max(0.0, min(1.0, k / 0.13))
        e = QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress(slam)
        scale = 1.9 - 0.9 * e
        rot = -16.0 + 8.0 * e
        alpha = min(1.0, slam * 1.6) * (1.0 - max(0.0, min(1.0, (k - 0.72) / 0.28)))
        if alpha <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        acc = QColor(pal["accent2"])
        if 0.10 < k < 0.55:                                                  # the impact: a ring of light spreads out
            t = (k - 0.10) / 0.45
            ring = QColor(acc.red(), acc.green(), acc.blue(), int(150 * (1 - t) ** 2))
            p.setPen(QPen(ring, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, self.R * (1.0 + 1.6 * t), self.R * (1.0 + 1.6 * t))
        p.setOpacity(alpha)
        p.translate(c)
        p.rotate(rot)
        p.scale(scale, scale)
        p.translate(-c)
        for i in range(3, 0, -1):                                            # a soft floor shadow under the seal
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 22))
            p.drawEllipse(c + QPointF(0, 6), self.R + i * 4, self.R + i * 4)
        brand.paint_seal(p, c, self.R, pal)
        gk = (k - 0.16) / 0.3
        if 0.0 < gk < 1.0:
            clip = QPainterPath()
            clip.addEllipse(c, self.R, self.R)
            p.setClipPath(clip)
            x = c.x() - self.R * 1.4 + self.R * 2.8 * gk
            g = QLinearGradient(x - 26, 0, x + 26, 0)
            g.setColorAt(0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, int(120 * brand_sin(gk))))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(c.x() - self.R, c.y() - self.R, self.R * 2, self.R * 2), g)


def seal_day(page: QWidget) -> None:
    """Stamp the day seal over ``page`` (once per finished day; the caller decides when)."""
    if not MOTION[0] or not page.isVisible() or page.width() < 240:
        return
    try:
        from . import sfx
        sfx.play("seal")
    except Exception:
        pass
    _Seal(page).run()


class _Glow(_Overlay):
    """A gold rim that breathes once around a card: 'everything done'."""

    def __init__(self, host: QWidget, color: str):
        super().__init__(host, 1300, QEasingCurve.Type.OutCubic)
        self.color = QColor(color)

    def paintEvent(self, _e) -> None:  # noqa: N802
        a = (1.0 - self.k) ** 1.5
        if a < 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = rr(12)
        for width, al in ((10.0, 0.10), (5.0, 0.20), (1.6, 0.85)):
            c = QColor(self.color)
            c.setAlphaF(al * a)
            p.setPen(QPen(c, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(width / 2, width / 2, -width / 2, -width / 2), rad, rad)


def celebrate(card: QWidget, color: str | None = None) -> None:
    """A quiet glow in the theme's accent around ``card`` (no confetti - luxury is restraint)."""
    if not MOTION[0] or not card.isVisible():
        return
    _Glow(card, color or _fpal(card)["accent2"]).run()
