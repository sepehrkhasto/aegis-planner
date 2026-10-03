# SPDX-License-Identifier: GPL-3.0-or-later
"""Tactile (3D) chrome: bevelled tiles, icon tiles for the sidebar and the frosted vertical tool dock.

Port of the ThreeDIconButton / EditorToolDock design language:
  * layered soft drop shadow (contact + ambient),
  * a light edge along the top and a shade along the bottom (inside the tile),
  * pressed = the shadow disappears and the top edge turns into an inset shadow.
Everything is drawn with QPainter (no images), so it follows the active palette and the corner-radius setting.
"""
from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QGuiApplication, QIcon
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from .fx_widgets import IconToolButton, _fpal, _mix
from .theme import rr

# room a bevelled tile leaves around itself for its drop shadow (left/right, top, bottom)
PAD_X, PAD_T, PAD_B = 3.0, 2.0, 5.0


def is_dark(pal: dict) -> bool:
    return QColor(pal["bg"]).lightness() < 128


def tile_rect(rect: QRectF) -> QRectF:
    """The visible tile inside a widget rect (the remainder is drop-shadow room)."""
    return rect.adjusted(PAD_X, PAD_T, -PAD_X, -PAD_B)


def _rgba(r: int, g: int, b: int, a: float) -> QColor:
    c = QColor(r, g, b)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def paint_bevel(p: QPainter, r: QRectF, rad: float, base: QColor, dark: bool, pressed: bool = False,
                hover: float = 0.0) -> None:
    """Draw one 3D tile into ``r`` (the tile itself - shadows extend a few px outside it)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not pressed:                                                     # contact + ambient shadow, 4 soft layers
        for k, (dy, grow, a) in enumerate(((1.0, 0.0, 0.30), (2.0, 0.6, 0.20), (3.5, 1.6, 0.13), (5.0, 2.8, 0.08))):
            sh = r.adjusted(-grow, -grow, grow, grow).translated(0, dy)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(0, 0, 0, a * (1.0 if dark else 0.42)))
            p.drawRoundedRect(sh, rad + grow, rad + grow)
    body = QPainterPath()
    body.addRoundedRect(r, rad, rad)
    top = QColor(base).lighter(int(100 + (12 if dark else 3) + 6 * hover))
    bot = QColor(base).darker(106 if not pressed else 100)
    if pressed:
        top = QColor(base).darker(104)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0.0, top)
    g.setColorAt(1.0, bot)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(body)
    p.save()
    p.setClipPath(body)
    edge = 2.6
    if pressed:                                                        # inset: shadow falls from the top edge
        gi = QLinearGradient(r.topLeft(), r.bottomLeft())
        gi.setColorAt(0.0, _rgba(0, 0, 0, 0.55 if dark else 0.14))
        gi.setColorAt(0.45, _rgba(0, 0, 0, 0.0))
        p.setPen(QPen(gi, edge * 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body)
    else:
        gt = QLinearGradient(r.topLeft(), r.bottomLeft())               # light edge on the top
        gt.setColorAt(0.0, _rgba(255, 255, 255, 0.20 if dark else 0.85))
        gt.setColorAt(0.35, _rgba(255, 255, 255, 0.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(gt, edge))
        p.drawPath(body)
        gb = QLinearGradient(r.topLeft(), r.bottomLeft())               # shade along the bottom
        gb.setColorAt(0.60, _rgba(0, 0, 0, 0.0))
        gb.setColorAt(1.0, _rgba(0, 0, 0, 0.45 if dark else 0.10))
        p.setPen(QPen(gb, edge * 1.4))
        p.drawPath(body)
    p.restore()
    p.setBrush(Qt.BrushStyle.NoBrush)                                   # crisp hairline so light themes keep the outline
    p.setPen(QPen(_rgba(0, 0, 0, 0.55 if dark else 0.10), 1))
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
    p.restore()


def variant_base(pal: dict, variant: str) -> tuple[QColor, QColor]:
    """(tile colour, resting glyph colour) for a variant: soft | muted | accent."""
    if variant == "accent":
        return QColor(pal["accent"]), QColor(pal["ink"])
    if variant == "muted":
        return _mix(QColor(pal["panel2"]), QColor(pal["line"]), 0.45), QColor(pal["muted"])
    return QColor(pal["panel2"]), QColor(pal["muted"])


# ------------------------------------------------------------ icon tiles ---
def _dpr() -> float:
    try:
        return max(1.0, QGuiApplication.primaryScreen().devicePixelRatio())
    except Exception:  # noqa: BLE001
        return 2.0


@lru_cache(maxsize=256)
def _tile_pixmap(name: str, checked: bool, panel2: str, accent: str, ink: str, muted: str, bg: str, size: int, dark: bool) -> QPixmap:
    from . import icons
    dpr = _dpr()
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.scale(dpr, dpr)
    r = tile_rect(QRectF(0, 0, size, size))
    base = QColor(accent if checked else panel2)
    paint_bevel(p, r, min(rr(9), r.height() / 2.4), base, dark, False, 0.0)
    g = int(size * 0.50)
    glyph = ink if checked else muted
    p.drawPixmap(int(r.center().x() - g / 2), int(r.center().y() - g / 2), icons.pixmap(name, glyph, g))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def tile_icon(name: str, pal: dict, checked: bool, size: int = 34) -> QIcon:
    """Sidebar icon: the glyph sitting on a small 3D tile (accent-filled when its page is open)."""
    return QIcon(_tile_pixmap(name, bool(checked), pal["panel2"], pal["accent"], pal["ink"], pal["muted"], pal["bg"], size,
                              is_dark(pal)))


# -------------------------------------------------------------- tool dock ---
class ToolDock(QWidget):
    """Vertical frosted tool strip (EditorToolDock): 3D icon buttons in a translucent rounded panel."""

    picked = pyqtSignal(str)

    def __init__(self, parent=None, size: int = 40):
        super().__init__(parent)
        self.size_ = size
        self._buttons: dict[str, IconToolButton] = {}
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 8, 8, 8 + int(PAD_B))
        self._lay.setSpacing(4)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

    def add_tool(self, key: str, icon_name: str, tip: str, *, checkable: bool = False, danger: bool = False) -> IconToolButton:
        b = IconToolButton(icon_name, tip, danger=danger, size=self.size_, parent=self)
        b.setCheckable(checkable)
        b.clicked.connect(lambda _=False, k=key: self.picked.emit(k))
        self._lay.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        self._buttons[key] = b
        return b

    def add_gap(self, px: int = 8) -> None:
        self._lay.addSpacing(px)

    def button(self, key: str) -> IconToolButton:
        return self._buttons[key]

    def set_enabled_all(self, on: bool) -> None:
        for b in self._buttons.values():
            b.setEnabled(on)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        dark = is_dark(pal)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 1, -2, -PAD_B)
        rad = min(rr(16), r.width() / 2.2)
        for dy, grow, a in ((2.0, 0.0, 0.18), (4.0, 1.5, 0.10), (7.0, 3.0, 0.06)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_rgba(0, 0, 0, a * (1.0 if dark else 0.5)))
            p.drawRoundedRect(r.adjusted(-grow, -grow, grow, grow).translated(0, dy), rad + grow, rad + grow)
        panel = QColor(pal["panel"])
        panel.setAlphaF(0.86 if dark else 0.78)
        p.setBrush(panel)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawRoundedRect(r, rad, rad)
