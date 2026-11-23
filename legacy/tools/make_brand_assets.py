# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate every raster brand asset from the vector painters in ``ui/brand.py`` (run: python tools/make_brand_assets.py).

Writes assets/icon.png, assets/logo.png, assets/icon.ico (16-256 px) and the Inno Setup wizard / small images in
packaging/installer_assets. The app itself paints the mark live; these files are for the OS (taskbar, installer, tray).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPointF, QRectF, Qt                       # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402

from aegis_desktop.ui import brand                                  # noqa: E402
from aegis_desktop.ui.themes_data import SIGNATURE, THEMES                     # noqa: E402

PAL = THEMES[SIGNATURE]["pal"]


def wizard(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    g = QLinearGradient(0, 0, 0, h)
    bg, ac = QColor(PAL["bg"]), QColor(PAL["accent"])
    g.setColorAt(0, brand._mix(bg, ac, 0.08))
    g.setColorAt(1, bg)
    p.fillRect(0, 0, w, h, g)
    rg = QRadialGradient(w / 2, h * 0.30, w * 0.9)
    rg.setColorAt(0, QColor(ac.red(), ac.green(), ac.blue(), 40))
    rg.setColorAt(1, QColor(ac.red(), ac.green(), ac.blue(), 0))
    p.fillRect(0, 0, w, h, rg)
    s = w * 0.56
    brand.paint_mark(p, QRectF((w - s) / 2, h * 0.16, s, s), PAL)
    p.setFont(brand.display_font(w * 0.105 * 0.75, True, w * 0.03))
    p.setPen(QColor(PAL["acc_text"]))
    p.drawText(QRectF(0, h * 0.16 + s + h * 0.03, w, h * 0.08), Qt.AlignmentFlag.AlignCenter, "AEGIS")
    p.setFont(brand.display_font(w * 0.06 * 0.75, True, w * 0.02))
    p.setPen(QColor(PAL["muted"]))
    p.drawText(QRectF(0, h * 0.16 + s + h * 0.10, w, h * 0.05), Qt.AlignmentFlag.AlignCenter, "PLANNER")
    ry = h * 0.16 + s + h * 0.20                                       # the engraved rule with the diamond nick, then the promise
    from aegis_desktop.ui import letterhead
    letterhead.rule(p, w * 0.14, w * 0.86, ry, PAL)
    p.setFont(brand.display_font(w * 0.052 * 0.75, False, w * 0.014))
    p.setPen(brand._mix(QColor(PAL["muted"]), ac, 0.4))
    p.drawText(QRectF(0, ry + h * 0.02, w, h * 0.05), Qt.AlignmentFlag.AlignCenter, "OFFLINE")
    p.drawText(QRectF(0, ry + h * 0.065, w, h * 0.05), Qt.AlignmentFlag.AlignCenter, "ENCRYPTED")
    p.setPen(brand.metal_pen(QPointF(0, 0), QPointF(0, h), PAL, max(1.0, w / 120)))
    p.drawLine(QPointF(w - 0.5, 0), QPointF(w - 0.5, h))
    p.end()
    return img


def file_icon(px: int) -> QImage:
    """The .aegis document icon: a dark page with a folded corner, the shield on it and an engraved rule below."""
    from PyQt6.QtGui import QPainterPath, QPen
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    m, fold = px * 0.12, px * 0.24
    x0, y0, x1, y1 = m, px * 0.06, px - m, px - px * 0.06
    page = QPainterPath()
    page.moveTo(x0, y0)
    page.lineTo(x1 - fold, y0)
    page.lineTo(x1, y0 + fold)
    page.lineTo(x1, y1)
    page.lineTo(x0, y1)
    page.closeSubpath()
    g = QLinearGradient(0, y0, 0, y1)
    bg, ac = QColor(PAL["bg"]), QColor(PAL["accent"])
    g.setColorAt(0, brand._mix(bg, ac, 0.10))
    g.setColorAt(1, bg)
    p.setBrush(g)
    p.setPen(brand.metal_pen(QPointF(x0, y0), QPointF(x1, y1), PAL, max(1.0, px / 40)))
    p.drawPath(page)
    corner = QPainterPath()
    corner.moveTo(x1 - fold, y0)
    corner.lineTo(x1 - fold, y0 + fold)
    corner.lineTo(x1, y0 + fold)
    p.setBrush(brand._mix(bg, ac, 0.22))
    p.drawPath(corner)
    s = (x1 - x0) * 0.62
    brand.paint_mark(p, QRectF((px - s) / 2, y0 + fold + (y1 - y0 - fold - s) * 0.30, s, s), PAL)
    if px >= 48:                                                                       # the engraved rule only where it can be seen
        p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 150), max(1.0, px / 96)))
        ry = y1 - (y1 - y0) * 0.10
        p.drawLine(QPointF(x0 + (x1 - x0) * 0.22, ry), QPointF(x1 - (x1 - x0) * 0.22, ry))
    p.end()
    return img


def small(px: int) -> QImage:
    img = QImage(px, px, QImage.Format.Format_RGB32)
    img.fill(QColor(PAL["bg"]))
    p = QPainter(img)
    brand.paint_mark(p, QRectF(px * 0.06, px * 0.06, px * 0.88, px * 0.88), PAL)
    p.end()
    return img


def main() -> None:
    _app = QGuiApplication.instance() or QGuiApplication([])
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from aegis_desktop.ui import theme
    theme.load_font(app)
    assets, inst = ROOT / "aegis_desktop" / "assets", ROOT / "packaging" / "installer_assets"
    for name in ("icon.png", "logo.png"):
        brand.render_mark(512).save(str(assets / name))
    from PIL import Image
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    frames = []
    for sz in (16, 24, 32, 48, 64, 128, 256):                           # small sizes re-rendered, not down-sampled
        frames.append(Image.open(_tmp(brand.render_mark(sz, dpr=1.0), sz)).convert("RGBA"))
    frames[-1].save(assets / "icon.ico", sizes=sizes, append_images=frames[:-1])
    ff = [Image.open(_tmp(file_icon(sz), sz)).convert("RGBA") for sz in (16, 24, 32, 48, 64, 128, 256)]
    ff[-1].save(assets / "aegis_file.ico", sizes=sizes, append_images=ff[:-1])
    for w, h in ((164, 314), (246, 471), (328, 628)):
        wizard(w, h).save(str(inst / f"wiz_{w}.bmp"), "BMP")
    for px in (55, 83, 110):
        small(px).save(str(inst / f"small_{px}.bmp"), "BMP")
    print("brand assets written")


def _tmp(pm, sz) -> str:
    f = ROOT / f".tmp_icon_{sz}.png"
    pm.save(str(f))
    return str(f)


if __name__ == "__main__":
    main()
    for f in ROOT.glob(".tmp_icon_*.png"):
        f.unlink()
