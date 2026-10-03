# SPDX-License-Identifier: GPL-3.0-or-later
"""The Aegis letterhead: the same mark, wordmark and engraved rule on anything that leaves the app as a document.

Painters only (points on an A4-like page), so a PDF, a PNG card or a printout carry the identical header and footer.
``paper_palette`` gives the ink-on-paper version of the brand: white page, near-black ink, the theme's metal deepened
enough to stay readable on white."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPolygonF

from . import brand
from .theme import AL_L, AL_R

UNIT = [1.0]                                     # point-size factor: 1.0 on screen, 72/dpi while painting into a QPdfWriter
PAGE_W, PAGE_H = 595.0, 842.0                   # A4 in points
MARGIN = 44.0
HEAD_H = 104.0                                   # the letterhead band; body starts below it
FOOT_H = 40.0


def paper_palette(accent_pal: dict | None = None) -> dict:
    """Ink-on-paper palette. ``accent_pal`` is the live theme palette (its accent colours the metal); None -> platinum."""
    src = accent_pal or {}
    acc = QColor(src.get("accent", "#b9c0cc"))
    acc2 = QColor(src.get("accent2", "#d6dbe4"))
    ink = QColor("#15171c")
    deep = brand._mix(acc, QColor("#000000"), 0.42)                # readable on white
    return {"bg": "#ffffff", "panel": "#f5f6f8", "panel2": "#eceef2", "line": "#d9dce2", "text": ink.name(), "muted": "#666b75",
            "accent": deep.name(), "accent2": brand._mix(acc2, QColor("#000000"), 0.30).name(), "acc_text": ink.name(),
            "soft": "#eef0f4", "ok": "#1f7a4d", "warn": "#9a6a00", "danger": "#b3372f"}


def _ui(pt: float, bold: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont("Vazirmatn")
    f.setPointSizeF(pt * UNIT[0])
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing * UNIT[0])
    return f


def _disp(pt: float, bold: bool = True, spacing: float = 0.0) -> QFont:
    return brand.display_font(pt * UNIT[0], bold, spacing * UNIT[0])


def rule(p: QPainter, x0: float, x1: float, y: float, pal: dict, notch: bool = True) -> None:
    """The engraved rule: a fine dark hairline, a lighter one under it, fading at both ends, and the diamond nick."""
    for dy, col in ((0.0, QColor(0, 0, 0, 70)), (0.9, QColor(255, 255, 255, 230))):
        g = QLinearGradient(x0, 0, x1, 0)
        clear = QColor(col)
        clear.setAlpha(0)
        g.setColorAt(0, clear)
        g.setColorAt(0.1, col)
        g.setColorAt(0.9, col)
        g.setColorAt(1, clear)
        p.fillRect(QRectF(x0, y + dy, x1 - x0, 0.8), g)
    if notch:
        cx, r = (x0 + x1) / 2, 3.6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brand.metal(QPointF(cx - r, y - r), QPointF(cx + r, y + r), pal))
        p.drawPolygon(QPolygonF([QPointF(cx, y - r), QPointF(cx + r * 0.8, y + 0.4), QPointF(cx, y + r + 0.8), QPointF(cx - r * 0.8, y + 0.4)]))


def paint_letterhead(p: QPainter, pal: dict, title: str, subtitle: str = "", number: str = "") -> None:
    """Header band: mark + wordmark on the start side (right), the document title under it, the vault number on the end side."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    top = 34.0
    s = 46.0
    brand.paint_mark(p, QRectF(PAGE_W - MARGIN - s, top, s, s), pal)
    p.setFont(_disp(15, True, 3.6))
    p.setPen(QColor(pal["text"]))
    p.drawText(QRectF(MARGIN + 120, top - 2, PAGE_W - 2 * MARGIN - s - 12 - 120, 24),
               int(AL_R | Qt.AlignmentFlag.AlignVCenter), "AEGIS  PLANNER")
    p.setFont(_ui(10.5, True))
    p.setPen(QColor(pal["text"]))
    p.drawText(QRectF(MARGIN + 120, top + 22, PAGE_W - 2 * MARGIN - s - 12 - 120, 20),
               int(AL_R | Qt.AlignmentFlag.AlignVCenter), title)
    if subtitle:
        p.setFont(_ui(8.5))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(MARGIN + 120, top + 40, PAGE_W - 2 * MARGIN - s - 12 - 120, 16),
                   int(AL_R | Qt.AlignmentFlag.AlignVCenter), subtitle)
    if number:
        p.setFont(_ui(7.5, spacing=1.0))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(MARGIN, top + 2, 140, 14), int(AL_L | Qt.AlignmentFlag.AlignVCenter), "\u200eVAULT  №\u200e")
        nf = _ui(13, spacing=2.0)
        try:
            nf.setFeature("tnum", 1)
        except Exception:                                                  # pragma: no cover
            pass
        p.setFont(nf)
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(MARGIN, top + 16, 160, 22), int(AL_L | Qt.AlignmentFlag.AlignVCenter), number)
    rule(p, MARGIN, PAGE_W - MARGIN, HEAD_H - 6, pal)
    p.restore()


def paint_footer(p: QPainter, pal: dict, page: int, pages: int, fa=str) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    y = PAGE_H - FOOT_H
    rule(p, MARGIN, PAGE_W - MARGIN, y, pal, notch=False)
    p.setFont(_disp(7.5, False, 2.4))
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(MARGIN, y + 8, 260, 16), int(AL_L | Qt.AlignmentFlag.AlignVCenter), "OFFLINE  ·  END-TO-END ENCRYPTED")
    p.setFont(_ui(8))
    p.drawText(QRectF(PAGE_W - MARGIN - 200, y + 8, 200, 16), int(AL_R | Qt.AlignmentFlag.AlignVCenter),
               f"صفحه {fa(page)} از {fa(pages)}")
    m = 14.0
    brand.paint_mark(p, QRectF((PAGE_W - m) / 2, y + 8, m, m), pal)
    p.restore()
