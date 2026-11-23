# SPDX-License-Identifier: GPL-3.0-or-later
"""Branded start-up splash: painted with Qt (no image files), so it is crisp on any DPI and always matches the brand.
It always uses the signature Obsidian palette - the splash is the brand's first impression, whatever theme is saved."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QSplashScreen

from .. import __version__
from . import brand
from .themes_data import SIGNATURE, THEMES


def _pixmap(w: int = 520, h: int = 300) -> QPixmap:
    pal = THEMES[SIGNATURE]["pal"]
    dpr = 2.0
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    r = QRectF(0.5, 0.5, w - 1, h - 1)
    g = QLinearGradient(0, 0, 0, h)
    bg, ac = QColor(pal["bg"]), QColor(pal["accent"])
    g.setColorAt(0, brand._mix(bg, ac, 0.07))
    g.setColorAt(1, bg)
    p.setPen(brand.metal_pen(QPointF(0, 0), QPointF(w, h), pal, 1.2))
    p.setBrush(g)
    p.drawRoundedRect(r, 18, 18)
    rg = QRadialGradient(w / 2, 70, 230)                                    # a warm pool of light behind the mark
    rg.setColorAt(0, QColor(ac.red(), ac.green(), ac.blue(), 34))
    rg.setColorAt(1, QColor(ac.red(), ac.green(), ac.blue(), 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(rg)
    p.drawRoundedRect(r, 18, 18)
    s = 92
    brand.paint_mark(p, QRectF((w - s) / 2, 26, s, s), pal)
    p.setFont(brand.display_font(30, True, 9.0))
    p.setPen(QColor(pal["acc_text"]))
    p.drawText(QRectF(0, 124, w, 46), Qt.AlignmentFlag.AlignCenter, "AEGIS")
    p.setFont(brand.display_font(11.5, True, 6.5))
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(0, 168, w, 22), Qt.AlignmentFlag.AlignCenter, "PLANNER")
    f2 = QFont("Vazirmatn", 10)
    p.setFont(f2)
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(0, 200, w, 24), Qt.AlignmentFlag.AlignCenter, "برنامه‌ریز رمزنگاری‌شده · تمام‌آفلاین")
    p.setPen(QColor(pal["muted"]).darker(150))
    f3 = QFont("Vazirmatn", 8)
    p.setFont(f3)
    p.drawText(QRectF(0, h - 30, w, 20), Qt.AlignmentFlag.AlignCenter, f"v{__version__}")
    p.end()
    return pm


class BrandSplash(QSplashScreen):
    def __init__(self):
        brand.load_display_font()
        super().__init__(_pixmap(), Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        """A click dismisses the splash at once (it also never outlives the main window by more than a quarter second)."""
        self.hide()
        super().mousePressEvent(e)

    def finish_with(self, win) -> None:
        """Fade out shortly after the main window is up so the hand-off never flashes."""
        def fade():
            self.finish(win)
        QTimer.singleShot(250, fade)
