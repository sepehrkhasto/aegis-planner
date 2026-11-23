# SPDX-License-Identifier: GPL-3.0-or-later
"""Aegis brand kit - the one place the identity is defined.

Identity: **matte noir.** Aegis is the shield, the vault is the treasure. Deep cool near-black grounds, neutral text
and a single restrained accent - brushed platinum by default (emerald / rosé variants) - spent sparingly (logo, the open
page, the primary action, focus). The scarcity of colour is what reads as expensive; nothing glossy, nothing loud.

Contents
* ``metal`` / ``metal_pen``  - the multi-stop "brushed metal" gradient (platinum / emerald / rose ... per theme) every edge and glyph uses.
* ``paint_mark``             - the monogram (metal shield rim, obsidian field, metal arch-A); also renders the app icon.
* ``Wordmark`` / ``Tagline`` - AEGIS in spaced Cormorant caps, and the ornamented «PLANNER · …» line.
* ``paint_grain``            - a barely-there film grain (~2 %) that gives dark surfaces a material, not a flat fill.
* ``EngraveLine``            - a two-tone (dark + light) divider that reads as cut into the surface.
* ``display_font``           - the display face (Cormorant Garamond, SIL OFL); Latin only, so Persian text keeps Vazirmatn.
Every painter reads the live palette, so the kit follows the active theme (gold on Obsidian, indigo on Indigo, ...).
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import (QBrush, QColor, QCursor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from PyQt6.QtWidgets import QFrame, QSizePolicy, QWidget

from . import theme
from .fx_widgets import _fpal

DISPLAY_FAMILY = "Cormorant Garamond"
_FONT_LOADED = [False]


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


# ------------------------------------------------------------------------------------------------ typography ---
def load_display_font() -> str:
    """Register the bundled Cormorant Garamond faces once; returns the family name (falls back to a serif)."""
    if _FONT_LOADED[0]:
        return DISPLAY_FAMILY
    fonts = theme.asset_path("fonts")
    ok = False
    for ttf in sorted(fonts.glob("CormorantGaramond-*.ttf")) if fonts.is_dir() else []:
        ok = QFontDatabase.addApplicationFont(str(ttf)) >= 0 or ok
    _FONT_LOADED[0] = True
    return DISPLAY_FAMILY if ok else "Georgia"


def display_font(pt: float, bold: bool = True, spacing: float = 0.0) -> QFont:
    f = QFont(load_display_font(), int(pt))
    f.setPointSizeF(pt)
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.DemiBold)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


# ------------------------------------------------------------------------------------------------- materials ---
def gilt_stops(pal: dict) -> list:
    """(position, colour) stops of the brushed-metal ramp for the palette's accent: bright shoulder -> body -> deep."""
    a, a2 = QColor(pal["accent"]), QColor(pal.get("accent2", pal["accent"]))
    white, black = QColor("#ffffff"), QColor("#000000")
    return [(0.0, _mix(a2, white, 0.16)), (0.28, a2), (0.52, a), (0.78, _mix(a, black, 0.34)), (1.0, _mix(a, black, 0.52))]


def metal(p0: QPointF, p1: QPointF, pal: dict) -> QLinearGradient:
    g = QLinearGradient(p0, p1)
    for pos, col in gilt_stops(pal):
        g.setColorAt(pos, col)
    return g


def metal_pen(p0: QPointF, p1: QPointF, pal: dict, width: float = 1.0) -> QPen:
    return QPen(QBrush(metal(p0, p1, pal)), width)


_GRAIN: dict = {}


def _grain_tile() -> QPixmap:
    if "px" not in _GRAIN:
        rnd = random.Random(7)                               # deterministic: the same film every run
        img = QImage(96, 96, QImage.Format.Format_ARGB32)
        for y in range(96):
            for x in range(96):
                v = rnd.random()
                img.setPixelColor(x, y, QColor(255, 255, 255, int(v * v * 15)) if rnd.random() < 0.5
                                  else QColor(0, 0, 0, int(v * v * 30)))
        _GRAIN["px"] = QPixmap.fromImage(img)
    return _GRAIN["px"]


def paint_grain(p: QPainter, rect: QRectF, pal: dict, strength: float = 1.0, clip: QPainterPath | None = None) -> None:
    """Film grain over a dark surface. Skipped on light themes (it would look like dirt) and when the rect is tiny."""
    if QColor(pal["bg"]).lightness() > 128 or rect.width() < 24 or rect.height() < 24 or strength <= 0:
        return
    p.save()
    if clip is not None:
        p.setClipPath(clip)
    p.setOpacity(min(1.0, strength))
    p.setBrushOrigin(rect.topLeft())
    p.fillRect(rect, QBrush(_grain_tile()))
    p.restore()


# ------------------------------------------------------------------------------------------------- monogram ---
def _shield(s: float, ox: float = 0.0, oy: float = 0.0) -> QPainterPath:
    sh = QPainterPath()
    sh.moveTo(ox + s * .5, oy + s * .15)
    sh.lineTo(ox + s * .80, oy + s * .27)
    sh.lineTo(ox + s * .80, oy + s * .52)
    sh.cubicTo(ox + s * .80, oy + s * .71, ox + s * .66, oy + s * .81, ox + s * .5, oy + s * .88)
    sh.cubicTo(ox + s * .34, oy + s * .81, ox + s * .20, oy + s * .71, ox + s * .20, oy + s * .52)
    sh.lineTo(ox + s * .20, oy + s * .27)
    sh.closeSubpath()
    return sh


def paint_mark(p: QPainter, rect: QRectF, pal: dict) -> None:
    """The Aegis monogram in ``rect``: obsidian tile with an engraved double rim, a gilt shield whose field is
    obsidian again, and a gilt arch-A. Works at 16 px (icon) and 512 px (installer art) from the same geometry."""
    if QColor(pal["bg"]).lightness() > 128:                  # the monogram is always obsidian & gold, even on a day theme
        pal = theme.THEMES[theme.SIGNATURE]["pal"]
    s = min(rect.width(), rect.height())
    p.save()
    p.translate(rect.topLeft())
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    a, bg = QColor(pal["accent"]), QColor(pal["bg"])
    rad = s * 0.27
    tile = QRectF(0.5, 0.5, s - 1, s - 1)
    field = QLinearGradient(0, 0, 0, s)
    field.setColorAt(0, _mix(bg, a, 0.16))
    field.setColorAt(0.55, _mix(bg, a, 0.05))
    field.setColorAt(1, _mix(bg, QColor("#000000"), 0.35))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(field)
    p.drawRoundedRect(tile, rad, rad)
    rim_w = max(1.0, s * 0.028)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(metal_pen(QPointF(0, 0), QPointF(s, s), pal, rim_w))
    p.drawRoundedRect(tile.adjusted(rim_w / 2, rim_w / 2, -rim_w / 2, -rim_w / 2), rad - rim_w / 2, rad - rim_w / 2)
    if s >= 40:                                              # the engraved inner hairline (too fine below ~40 px)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawRoundedRect(tile.adjusted(rim_w + 1.5, rim_w + 1.5, -rim_w - 1.5, -rim_w - 1.5), rad * .8, rad * .8)
    outer = _shield(s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(metal(QPointF(s * .2, s * .15), QPointF(s * .8, s * .88), pal))
    p.drawPath(outer)
    inset = QTransform().translate(s * .5, s * .52).scale(0.80, 0.80).translate(-s * .5, -s * .52).map(outer)
    inner = QLinearGradient(0, s * .2, 0, s * .85)
    inner.setColorAt(0, _mix(bg, a, 0.10))
    inner.setColorAt(1, _mix(bg, QColor("#000000"), 0.45))
    p.setBrush(inner)
    p.drawPath(inset)
    arch = QPolygonF([QPointF(s * .5, s * .335), QPointF(s * .655, s * .685), QPointF(s * .57, s * .685),
                      QPointF(s * .5, s * .53), QPointF(s * .43, s * .685), QPointF(s * .345, s * .685)])
    bar = QPolygonF([QPointF(s * .5, s * .585), QPointF(s * .535, s * .685), QPointF(s * .465, s * .685)])
    p.setBrush(metal(QPointF(s * .35, s * .33), QPointF(s * .65, s * .69), pal))
    p.drawPolygon(arch)
    p.drawPolygon(bar)
    if s >= 28:                                              # a soft specular edge on the shield's upper-left shoulder
        hi = QPainterPath()
        hi.moveTo(s * .5, s * .15)
        hi.lineTo(s * .20, s * .27)
        hi.lineTo(s * .20, s * .40)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), max(1.0, s * .026)))
        p.save()
        p.setClipPath(outer)                                  # only the half of the stroke that lies on the rim
        p.drawPath(hi)
        p.restore()
    p.restore()


def render_mark(size: int, pal: dict | None = None, dpr: float = 1.0) -> QPixmap:
    """The monogram as a pixmap (icon.png, splash, installer art)."""
    pal = pal or theme.THEMES[theme.SIGNATURE]["pal"]
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_mark(p, QRectF(0, 0, size, size), pal)
    p.end()
    return pm


# --------------------------------------------------------------------------------------------- lockup widgets ---
class Wordmark(QWidget):
    """AEGIS in spaced display caps with a gilt fill. ``pt`` is the cap size; it sizes itself to the text."""

    def __init__(self, text: str = "AEGIS", pt: float = 22, spacing: float = 6.0, parent=None):
        super().__init__(parent)
        self._text, self._font = text, display_font(pt, True, spacing)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font)
        self.setFixedSize(fm.horizontalAdvance(text) + 8, fm.height() + 4)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        path = QPainterPath()
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font)
        path.addText(4, 2 + fm.ascent(), self._font, self._text)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(metal(QPointF(0, 0), QPointF(0, self.height()), pal))
        p.drawPath(path)


class Tagline(QWidget):
    """──── ◆ ────  then PLANNER (spaced caps) over the Persian descriptor - the ornamented sub-title of the hero."""

    def __init__(self, latin: str = "PLANNER", fa: str = "برنامه‌ریز شخصی رمزنگاری‌شده", parent=None):
        super().__init__(parent)
        self.latin, self.fa = latin, fa
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(66)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, cx = self.width(), self.width() / 2
        y = 8.0
        run = min(120.0, w / 2 - 20)
        for sgn in (-1, 1):                                            # the rules fade out away from the diamond
            g = QLinearGradient(cx + sgn * 12, y, cx + sgn * (12 + run), y)
            g.setColorAt(0, QColor(pal["accent"]))
            tail = QColor(pal["accent"])
            tail.setAlpha(0)
            g.setColorAt(1, tail)
            p.setPen(QPen(QBrush(g), 1))
            p.drawLine(QPointF(cx + sgn * 12, y), QPointF(cx + sgn * (12 + run), y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["accent2"]))
        p.drawPolygon(QPolygonF([QPointF(cx, y - 4), QPointF(cx + 4, y), QPointF(cx, y + 4), QPointF(cx - 4, y)]))
        p.setFont(display_font(13, True, 7.0))
        p.setPen(QColor(pal["acc_text"]))
        p.drawText(QRectF(0, 18, w, 22), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.latin)
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(0, 42, w, 20), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, self.fa)


class EngraveLine(QFrame):
    """A divider cut into the surface: a dark hairline with a faint light one beneath. Fades out at both ends."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EngraveLine")
        self.setFixedHeight(2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        dark_ui = QColor(pal["bg"]).lightness() < 128
        p = QPainter(self)
        m, w = 14.0, float(self.width())
        for y, base in ((0.5, QColor(0, 0, 0, 150) if dark_ui else QColor(0, 0, 0, 34)),
                        (1.5, QColor(255, 255, 255, 16) if dark_ui else QColor(255, 255, 255, 190))):
            g = QLinearGradient(m, y, w - m, y)
            clear = QColor(base)
            clear.setAlpha(0)
            g.setColorAt(0, clear)
            g.setColorAt(0.18, base)
            g.setColorAt(0.82, base)
            g.setColorAt(1, clear)
            p.fillRect(QRectF(m, y - 0.5, w - 2 * m, 1), QBrush(g))


def paint_depth(p: QPainter, rect: QRectF, rad: float, pal: dict, crest: bool = False) -> None:
    """A dark card as an object, not a fill: grain, a soft floor shadow, the "cut edge" just inside the border (light
    above, dark below) and a lit top edge that fades toward the corners. ``rad`` is the card's corner radius."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = rect.adjusted(1, 1, -1, -1)
    clip = QPainterPath()
    clip.addRoundedRect(body, rad - 1, rad - 1)
    paint_grain(p, body, pal, 1.0, clip)
    floor = QLinearGradient(0, body.bottom() - 16, 0, body.bottom())
    floor.setColorAt(0, QColor(0, 0, 0, 0))
    floor.setColorAt(1, QColor(0, 0, 0, 46))
    p.save()
    p.setClipPath(clip)
    p.fillRect(QRectF(body.left(), body.bottom() - 16, body.width(), 16), floor)
    p.restore()
    tint = QColor(pal["accent2"])
    cut = QLinearGradient(0, body.top(), 0, body.bottom())
    cut.setColorAt(0, QColor(tint.red(), tint.green(), tint.blue(), 34))
    cut.setColorAt(0.35, QColor(255, 255, 255, 6))
    cut.setColorAt(1, QColor(0, 0, 0, 70))
    p.setPen(QPen(cut, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), rad - 1.5, rad - 1.5)
    r = rad + 2
    g = QLinearGradient(rect.left() + r, 0, rect.right() - r, 0)
    for pos, a in ((0.0, 0), (0.2, 34), (0.5, 60), (0.8, 34), (1.0, 0)):
        g.setColorAt(pos, QColor(tint.red(), tint.green(), tint.blue(), a))
    p.fillRect(QRectF(rect.left() + r, rect.top() + 1, rect.width() - 2 * r, 1), QBrush(g))
    if crest:
        paint_crest(p, rect, pal)
    p.restore()


def paint_crest(p: QPainter, r: QRectF, pal: dict, inset: float = 7.0, arm: float = 9.0, alpha: int = 150) -> None:
    """Four gilt corner ticks - the mark of a hero card (login, Today's summary)."""
    col = QColor(pal["accent"])
    col.setAlpha(alpha)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    x0, y0, x1, y1 = r.left() + inset, r.top() + inset, r.right() - inset, r.bottom() - inset
    for x, y, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
    p.restore()


class HoverLight:
    """The hover language of a "lively" card, shared so every card behaves the same:
    * a whisper of light on the surface that follows the pointer,
    * a border that warms toward the accent, brightest where the pointer is (spotlight border),
    * one *gilt glint* - a soft diagonal band that crosses the card once on entry (start edge -> end edge).
    The owner forwards ``enterEvent/leaveEvent/hideEvent`` to ``enter()/leave()/stop()`` and calls ``paint()`` last.
    A timer runs only while the pointer is on the card; with Reduce motion the state is a static warm border."""

    GLINT_MS = 720

    def __init__(self, w: QWidget):
        self.w = w
        self.k, self.glint = 0.0, 1.0
        self.pos = QPointF(-999, -999)
        self.inside = False
        self._t = QTimer(w, interval=30)
        self._t.timeout.connect(self._tick)

    def enter(self) -> None:
        from .anim import MOTION
        self.inside = True
        if not MOTION[0]:
            self.k, self.pos = 1.0, QPointF(self.w.rect().center())
            self.w.update()
            return
        if self.glint >= 1.0:
            self.glint = 0.0
        self._t.start()

    def leave(self) -> None:
        self.inside = False
        from .anim import MOTION
        if not MOTION[0]:
            self.k = 0.0
            self.w.update()

    def stop(self) -> None:
        self._t.stop()
        self.inside, self.k, self.glint = False, 0.0, 1.0

    def _tick(self) -> None:
        loc = QPointF(self.w.mapFromGlobal(QCursor.pos()))
        if self.k < 0.03:
            self.pos = loc
        else:
            self.pos += (loc - self.pos) * 0.35
        self.k += ((1.0 if self.inside else 0.0) - self.k) * 0.2
        if self.glint < 1.0:
            self.glint = min(1.0, self.glint + 30.0 / self.GLINT_MS)
        self.w.update()
        if not self.inside and self.k < 0.01 and self.glint >= 1.0:
            self.k = 0.0
            self._t.stop()
            self.w.update()

    def paint(self, p: QPainter, r: QRectF, rad: float, pal: dict) -> None:
        if self.k <= 0.01 and self.glint >= 1.0:
            return
        dark = QColor(pal["bg"]).lightness() < 128
        a2, acc = QColor(pal["accent2"]), QColor(pal["accent"])
        clip = QPainterPath()
        clip.addRoundedRect(r, rad, rad)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipPath(clip)
        if self.k > 0.01:
            g = QRadialGradient(self.pos, 200)
            g.setColorAt(0, QColor(a2.red(), a2.green(), a2.blue(), int((15 if dark else 20) * self.k)))
            g.setColorAt(1, QColor(a2.red(), a2.green(), a2.blue(), 0))
            p.fillRect(r, g)
        if self.glint < 1.0:
            t = 1 - (1 - self.glint) ** 3
            rtl = self.w.layoutDirection() == Qt.LayoutDirection.RightToLeft
            span = r.width() * 1.5
            cx = (r.right() + r.width() * 0.25 - span * t) if rtl else (r.left() - r.width() * 0.25 + span * t)
            fade = math.sin(math.pi * t)                            # brightest mid-crossing
            band = 80.0
            x0, x1 = cx - band / 2, cx + band / 2
            g = QLinearGradient(x0, 0, x1, 0)
            for pos, a in ((0.0, 0), (0.5, int((44 if dark else 60) * fade)), (1.0, 0)):
                g.setColorAt(pos, QColor(a2.red(), a2.green(), a2.blue(), a) if dark else QColor(255, 255, 255, a * 3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawPolygon(QPolygonF([QPointF(x0 + 26, r.top()), QPointF(x1 + 26, r.top()), QPointF(x1 - 26, r.bottom()),
                                     QPointF(x0 - 26, r.bottom())]))
        p.restore()
        if self.k > 0.01:
            edge = r.adjusted(0.5, 0.5, -0.5, -0.5)
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(acc.red(), acc.green(), acc.blue(), int(60 * self.k)), 1))
            p.drawRoundedRect(edge, rad, rad)
            g = QRadialGradient(self.pos, 150)
            g.setColorAt(0, QColor(a2.red(), a2.green(), a2.blue(), int(230 * self.k)))
            g.setColorAt(1, QColor(a2.red(), a2.green(), a2.blue(), 0))
            p.setPen(QPen(QBrush(g), 1.4))
            p.drawRoundedRect(edge, rad, rad)
            p.restore()


class GlintPass:
    """One gilt glint: a soft diagonal band that crosses a widget once (start edge -> end edge, ~0.6 s). The signature
    motion of the brand - it appears on a primary button's hover, an opening vault, a finished goal. ``paint`` after
    the widget's own drawing; nothing runs (or repaints) when it is idle or when Reduce motion is on."""

    def __init__(self, w: QWidget, ms: int = 620):
        self.w, self.t = w, 1.0
        self.an = QVariantAnimation(w)
        self.an.setDuration(ms)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.an.valueChanged.connect(self._v)
        self.an.finished.connect(self._done)

    def _v(self, v) -> None:
        self.t = float(v)
        self.w.update()

    def _done(self) -> None:
        self.t = 1.0
        self.w.update()

    @property
    def running(self) -> bool:
        return self.t < 1.0

    def start(self) -> None:
        from .anim import MOTION
        if MOTION[0] and not self.running:
            self.t = 0.0
            self.an.stop()
            self.an.start()

    def stop(self) -> None:
        self.an.stop()
        self.t = 1.0

    def paint(self, p: QPainter, r: QRectF, rad: float, pal: dict, strength: float = 1.0) -> None:
        if not self.running:
            return
        rtl = self.w.layoutDirection() == Qt.LayoutDirection.RightToLeft
        t = self.t
        span = r.width() * 1.5
        cx = (r.right() + r.width() * 0.25 - span * t) if rtl else (r.left() - r.width() * 0.25 + span * t)
        band = max(46.0, min(90.0, r.width() * 0.5))
        x0, x1 = cx - band / 2, cx + band / 2
        a = int(90 * strength * math.sin(math.pi * t))
        g = QLinearGradient(x0, 0, x1, 0)
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, a))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        clip = QPainterPath()
        clip.addRoundedRect(r, rad, rad)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipPath(clip)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        sk = min(20.0, r.height() * 0.4)
        p.drawPolygon(QPolygonF([QPointF(x0 + sk, r.top()), QPointF(x1 + sk, r.top()), QPointF(x1 - sk, r.bottom()),
                                 QPointF(x0 - sk, r.bottom())]))
        p.restore()


def paint_seal(p: QPainter, c: QPointF, radius: float, pal: dict, caption: str = "مهر شد") -> None:
    """The day seal: a gilt double ring carrying «AEGIS · PLANNER · SEALED ·» on its rim, the shield with a check in the
    middle and a caption below it. Painted around ``c``; the caller rotates / scales / fades it."""
    R = radius
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    bg = QColor(pal["bg"])
    a = QColor(pal["accent"])
    disc = QRadialGradient(c, R)
    disc.setColorAt(0, _mix(bg, a, 0.13))
    disc.setColorAt(1, _mix(bg, QColor("#000000"), 0.3))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(disc)
    p.drawEllipse(c, R, R)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(metal_pen(QPointF(c.x() - R, c.y() - R), QPointF(c.x() + R, c.y() + R), pal, max(2.0, R * 0.05)))
    p.drawEllipse(c, R - 1.5, R - 1.5)
    p.setPen(QPen(QColor(a.red(), a.green(), a.blue(), 150), 1))
    p.drawEllipse(c, R * 0.70, R * 0.70)
    text = "AEGIS  ·  PLANNER  ·  SEALED  ·  "
    f = display_font(max(7.0, R * 0.155), True, 0.0)
    p.setFont(f)
    p.setPen(QColor(pal["acc_text"]))
    step = 360.0 / len(text)
    ring_r = R * 0.85
    for i, ch in enumerate(text):
        p.save()
        p.translate(c)
        p.rotate(-90 + i * step)
        p.translate(0, -ring_r)
        p.drawText(QRectF(-9, -9, 18, 18), Qt.AlignmentFlag.AlignCenter, ch)
        p.restore()
    s = R * 0.92
    p.save()
    p.translate(c.x() - s / 2, c.y() - s / 2 - R * 0.10)
    sh = _shield(s)
    p.setPen(metal_pen(QPointF(0, 0), QPointF(s, s), pal, max(1.6, R * 0.035)))
    p.setBrush(QColor(a.red(), a.green(), a.blue(), 26))
    p.drawPath(sh)
    p.setPen(QPen(QBrush(metal(QPointF(0, s * .3), QPointF(0, s * .8), pal)), max(2.0, R * 0.075), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    tick = QPainterPath()
    tick.moveTo(s * .36, s * .52)
    tick.lineTo(s * .47, s * .63)
    tick.lineTo(s * .66, s * .40)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(tick)
    p.restore()
    cf = QFont(p.font())
    cf.setFamily("Vazirmatn")
    cf.setPointSizeF(max(8.0, R * 0.17))
    cf.setBold(True)
    p.setFont(cf)
    p.setPen(QColor(pal["acc_text"]))
    p.drawText(QRectF(c.x() - R * 0.6, c.y() + R * 0.36, R * 1.2, R * 0.3), Qt.AlignmentFlag.AlignCenter, caption)
    p.restore()


# ------------------------------------------------------------------------------------------ empty-state art ---
def _glyph(icon: str, s: float) -> QPainterPath | None:
    """Line-art glyph for an empty page, drawn in a box of side ``s`` centred on the origin (stroke it, don't fill it)."""
    h = s / 2
    g = QPainterPath()
    if icon in ("check", "tasks", "today"):
        g.addRoundedRect(QRectF(-h * .8, -h * .8, s * .8, s * .8), s * .14, s * .14)
        g.moveTo(-h * .42, 0)
        g.lineTo(-h * .08, h * .34)
        g.lineTo(h * .5, -h * .38)
    elif icon == "calendar":
        g.addRoundedRect(QRectF(-h * .85, -h * .7, s * .85, s * .8), s * .12, s * .12)
        g.moveTo(-h * .85, -h * .3)
        g.lineTo(h * .85, -h * .3)
        for x in (-.45, .45):
            g.moveTo(h * x, -h * .95)
            g.lineTo(h * x, -h * .55)
        for x, y in ((-.42, .15), (0, .15), (.42, .15), (-.42, .55), (0, .55)):
            g.addEllipse(QPointF(h * x, h * y), s * .025, s * .025)
    elif icon == "notes":
        g.addRoundedRect(QRectF(-h * .7, -h * .9, s * .7, s * .9), s * .1, s * .1)
        for i, w in enumerate((.9, .9, .55)):
            y = -h * .45 + i * h * .45
            g.moveTo(-h * .38, y)
            g.lineTo(-h * .38 + h * w * .76, y)
    elif icon == "trash":
        g.moveTo(-h * .8, -h * .5)
        g.lineTo(h * .8, -h * .5)
        g.moveTo(-h * .3, -h * .5)
        g.lineTo(-h * .3, -h * .78)
        g.lineTo(h * .3, -h * .78)
        g.lineTo(h * .3, -h * .5)
        g.moveTo(-h * .6, -h * .5)
        g.lineTo(-h * .5, h * .85)
        g.lineTo(h * .5, h * .85)
        g.lineTo(h * .6, -h * .5)
        g.moveTo(-h * .18, -h * .15)
        g.lineTo(-h * .18, h * .5)
        g.moveTo(h * .18, -h * .15)
        g.lineTo(h * .18, h * .5)
    elif icon in ("habits", "flame"):
        g.moveTo(0, -h * .95)
        g.cubicTo(h * .15, -h * .5, h * .8, -h * .25, h * .62, h * .35)
        g.cubicTo(h * .5, h * .75, h * .2, h * .92, 0, h * .92)
        g.cubicTo(-h * .3, h * .92, -h * .62, h * .7, -h * .58, h * .3)
        g.cubicTo(-h * .55, -h * .05, -h * .3, -h * .2, -h * .18, -h * .5)
        g.cubicTo(-h * .1, -h * .3, 0, -h * .6, 0, -h * .95)
    elif icon in ("goals", "target"):
        for r in (.85, .52, .18):
            g.addEllipse(QPointF(0, 0), h * r, h * r)
    elif icon == "focus":
        g.addEllipse(QPointF(0, h * .1), h * .78, h * .78)
        g.moveTo(-h * .18, -h * .9)
        g.lineTo(h * .18, -h * .9)
        g.moveTo(0, h * .1)
        g.lineTo(0, -h * .38)
        g.moveTo(0, h * .1)
        g.lineTo(h * .3, h * .3)
    elif icon in ("reports", "trend"):
        for i, hh in enumerate((.4, .75, .55, .95)):
            x = -h * .8 + i * h * .5
            g.addRoundedRect(QRectF(x, h * .85 - h * 1.7 * hh * .9, h * .3, h * 1.7 * hh * .9), 2, 2)
    elif icon in ("backup", "archive"):                               # a shallow box with a lid and a down arrow
        g.addRoundedRect(QRectF(-h * .9, -h * .85, s * .9, h * .42), s * .06, s * .06)
        g.moveTo(-h * .75, -h * .43)
        g.lineTo(-h * .75, h * .8)
        g.lineTo(h * .75, h * .8)
        g.lineTo(h * .75, -h * .43)
        g.moveTo(0, -h * .15)
        g.lineTo(0, h * .5)
        g.moveTo(-h * .3, h * .22)
        g.lineTo(0, h * .52)
        g.lineTo(h * .3, h * .22)
    elif icon == "sparkle":
        g.moveTo(0, -h * .95)
        g.cubicTo(h * .1, -h * .3, h * .3, -h * .1, h * .95, 0)
        g.cubicTo(h * .3, h * .1, h * .1, h * .3, 0, h * .95)
        g.cubicTo(-h * .1, h * .3, -h * .3, h * .1, -h * .95, 0)
        g.cubicTo(-h * .3, -h * .1, -h * .1, -h * .3, 0, -h * .95)
    else:
        return None
    return g


def paint_empty_art(p: QPainter, cx: float, cy: float, pal: dict, icon: str, size: float = 120.0, tilt: tuple = (0.0, 0.0)) -> bool:
    """Brand illustration for an empty page: an engraved line-art shield (double contour, hairline glints), with the
    page's own glyph inside and a few faint satellites. Returns False when ``icon`` has no glyph (caller falls back)."""
    glyph = _glyph(icon, size * 0.34)
    if glyph is None:
        return False
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    a, a2, line = QColor(pal["accent"]), QColor(pal.get("accent2", pal["accent"])), QColor(pal["line"])
    s = size
    tx, ty = tilt
    oy = cy - s / 2 - s * 0.02
    p.save()
    p.translate(-tx * 3.0, -ty * 2.5)                                    # the far layer (orbits, satellites) shifts against the shield
    p.setBrush(Qt.BrushStyle.NoBrush)
    for rad, al in ((s * .62, 0.55), (s * .78, 0.28)):                   # two quiet orbits behind the shield
        oc = QColor(line)
        oc.setAlphaF(al)
        p.setPen(QPen(oc, 1.0))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
    p.setPen(Qt.PenStyle.NoPen)
    for ang, rad, sz, al in ((32, .62, 2.8, .8), (205, .78, 2.2, .5), (300, .62, 2.4, .6)):
        sc = QColor(a2)
        sc.setAlphaF(al)
        p.setBrush(sc)
        p.drawEllipse(QPointF(cx + s * rad * math.cos(math.radians(ang)), cy - s * rad * math.sin(math.radians(ang))), sz, sz)
    p.restore()
    p.save()
    p.translate(tx * 4.0, ty * 3.0)                                      # the shield: nearer
    outer = _shield(s * 1.25, cx - s * 1.25 / 2, oy - s * 0.125)
    fill = QLinearGradient(0, oy, 0, oy + s)
    fill.setColorAt(0, _mix(QColor(pal["panel2"]), a, 0.10))
    fill.setColorAt(1, _mix(QColor(pal["panel2"]), QColor("#000000"), 0.18 if QColor(pal["bg"]).lightness() < 128 else 0.0))
    p.setBrush(fill)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(outer)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(metal_pen(QPointF(cx - s * .4, oy), QPointF(cx + s * .4, oy + s), pal, 1.6))
    p.drawPath(outer)
    inset = QTransform().translate(cx, oy + s * .48).scale(0.88, 0.88).translate(-cx, -(oy + s * .48)).map(outer)
    ic = QColor(line)
    ic.setAlphaF(0.85)
    p.setPen(QPen(ic, 1.0))
    p.drawPath(inset)
    p.translate(cx + tx * 3.5, oy + s * .52 + ty * 2.5)                  # the glyph: nearest
    gc = QColor(a2)
    p.setPen(QPen(_mix(QColor(pal["text"]), gc, 0.35), max(1.6, s * 0.018), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.drawPath(glyph)
    p.restore()
    p.restore()                                                          # the outer save (render hints)
    return True


def tray_icon(locked: bool):
    """Tray icon that tells the vault's state at a glance: unlocked = the monogram with a small green pip; locked = the
    monogram dimmed and a padlock badge. Rendered at the sizes Windows asks for (16-48 px, HiDPI)."""
    from PyQt6.QtGui import QIcon
    pal = theme.THEMES[theme.SIGNATURE]["pal"]
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pm = render_mark(size, pal, 2.0)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = float(size)
        if locked:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            p.fillRect(QRectF(0, 0, s, s), QColor(0, 0, 0, 120))                     # dim what is already drawn
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            b = s * 0.44
            box = QRectF(s - b, s - b, b, b)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["bg"]))
            p.drawEllipse(box.adjusted(-s * .03, -s * .03, s * .03, s * .03))
            p.setBrush(QColor(pal["accent2"]))
            body = QRectF(box.left() + b * .2, box.top() + b * .46, b * .6, b * .40)
            p.drawRoundedRect(body, b * .08, b * .08)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["accent2"]), max(1.0, b * .10)))
            p.drawArc(QRectF(box.left() + b * .31, box.top() + b * .16, b * .38, b * .5), 0, 180 * 16)
        else:
            r = s * 0.17
            c = QPointF(s - r * 1.5, s - r * 1.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["bg"]))
            p.drawEllipse(c, r * 1.35, r * 1.35)
            p.setBrush(QColor(pal["ok"]))
            p.drawEllipse(c, r, r)
        p.end()
        icon.addPixmap(pm)
    return icon
