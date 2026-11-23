# SPDX-License-Identifier: GPL-3.0-or-later
"""Vault Certificate: one engraved card that says «this vault is yours» - number, birth date, non-secret id, cipher.

``paint_certificate`` is a pure painter (used by the live card and by the PNG export), so what you see is what you save.
Nothing secret is ever drawn: the id / fingerprint are public header data, not keys (the card says so, too)."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..core import certificate as cert_core
from ..core.jalali import fa
from . import brand
from .anim import MOTION
from .fx_widgets import _fpal
from .micro import MotionDialog
from .theme import AL_L, AL_R
from .widgets import button, label

W, H = 720.0, 450.0                       # design canvas; everything is drawn on it and scaled to the widget / image
RAD = 22.0


def _ui_font(pt: float, bold: bool = False, spacing: float = 0.0, light: bool = False) -> QFont:
    f = QFont("Vazirmatn")
    f.setPointSizeF(pt)
    f.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Light if light else QFont.Weight.Normal)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def _rosette(cx: float, cy: float, r0: float, k: int, amp: float, steps: int = 900) -> QPainterPath:
    """A closed guilloche-style curve: r = r0 (1 + amp cos(k t)). Layered thinly, it reads as banknote engraving."""
    path = QPainterPath()
    for i in range(steps + 1):
        t = i / steps * 2 * math.pi
        r = r0 * (1 + amp * math.cos(k * t))
        pt = QPointF(cx + r * math.cos(t), cy + r * math.sin(t))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def _facts(info: dict) -> list[tuple[str, str, bool]]:
    """(label, value, latin) rows, in reading order (right column first)."""
    d = info["days"]
    together = "امروز شروع شد" if d == 0 else f"{fa(d)} روز"
    return [
        ("تاریخ ساخت", info["created_fa"], False),
        ("همراه شما", together, False),
        ("شناسهٔ ولت", info["fingerprint"], True),
        ("نسخهٔ ذخیره‌شده", fa(info["revision"]), False),
        ("رمزنگاری", f"{info['cipher']}  ·  PBKDF2-SHA256", True),
        ("کلید بازیابی", "ساخته شده" if info["recovery"] else "ساخته نشده", False),
    ]


def paint_shell(p: QPainter, pal: dict, tilt: tuple = (0.0, 0.0), center: tuple = (W - 116.0, 92.0)) -> None:
    """The shared card body of every Aegis card (certificate, week seal): a lit matte plate with grain and a guilloche
    rosette on the far layer. Draws on the 720x450 canvas; the caller scales the painter."""
    p.save()
    tx, ty = tilt
    bg, acc, a2 = QColor(pal["bg"]), QColor(pal["accent"]), QColor(pal["accent2"])
    dark = bg.lightness() < 128
    card = QRectF(0, 0, W, H)
    body = QPainterPath()
    body.addRoundedRect(card.adjusted(1, 1, -1, -1), RAD, RAD)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, brand._mix(QColor(pal["panel"]), acc, 0.07 if dark else 0.03))
    g.setColorAt(1, brand._mix(QColor(pal["panel"]), QColor("#000000") if dark else QColor(pal["panel2"]), 0.28))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawPath(body)
    p.setClipPath(body)
    brand.paint_grain(p, card, pal, 1.0, body)
    p.translate(-tx * 5.0, -ty * 4.0)                                    # the far layer shifts against the pointer
    cx, cy = center
    for i, (r0, k, amp) in enumerate(((176, 40, 0.030), (146, 32, 0.040), (116, 24, 0.055), (88, 18, 0.075), (62, 12, 0.10))):
        c = QColor(acc if i % 2 == 0 else a2)
        c.setAlphaF(0.17 if dark else 0.24)
        p.setPen(QPen(c, 0.7))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_rosette(cx, cy, r0, k, amp))
    p.restore()


def paint_frame(p: QPainter, pal: dict) -> None:
    """Metal double border + gilt corner ticks (drawn last, over everything)."""
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(brand.metal_pen(QPointF(0, 0), QPointF(W, H), pal, 2.0))
    p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), RAD, RAD)
    inner = QColor(pal["line"])
    inner.setAlphaF(0.9)
    p.setPen(QPen(inner, 0.9))
    p.drawRoundedRect(QRectF(9, 9, W - 18, H - 18), RAD - 8, RAD - 8)
    brand.paint_crest(p, QRectF(0, 0, W, H), pal, inset=15.0, arm=11.0, alpha=170)
    p.restore()


def paint_certificate(p: QPainter, rect: QRectF, info: dict, pal: dict, tilt: tuple = (0.0, 0.0)) -> None:
    """Paint the certificate into ``rect`` (any size; drawn on a 720x450 canvas and scaled)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.translate(rect.topLeft())
    p.scale(rect.width() / W, rect.height() / H)
    tx, ty = tilt
    acc = QColor(pal["accent"])
    dark = QColor(pal["bg"]).lightness() < 128
    paint_shell(p, pal, tilt)
    # --- header: mark (near layer) + wordmark
    p.save()
    p.translate(tx * 3.0, ty * 2.5)
    brand.paint_mark(p, QRectF(W - 40 - 70, 34, 70, 70), pal)
    p.restore()
    p.setFont(brand.display_font(21, True, 5.0))
    p.setPen(QColor(pal["acc_text"]))
    p.drawText(QRectF(W - 40 - 70 - 16 - 300, 40, 300, 34), int(AL_R | Qt.AlignmentFlag.AlignVCenter), "AEGIS  PLANNER")
    p.setFont(_ui_font(11.5))
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(W - 40 - 70 - 16 - 300, 74, 300, 26), int(AL_R | Qt.AlignmentFlag.AlignVCenter),
               "گواهی ولت رمزنگاری‌شده")
    # --- serial number (start side of the header = left in this LTR-drawn layout)
    p.setFont(_ui_font(8.5, spacing=1.2))
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(40, 42, 200, 18), int(AL_L | Qt.AlignmentFlag.AlignVCenter), "\u200eVAULT  №\u200e")
    sf = _ui_font(24, light=True, spacing=3.0)
    try:
        sf.setFeature("tnum", 1)
    except Exception:                                                      # pragma: no cover - older Qt
        pass
    p.setFont(sf)
    p.setPen(QColor(pal["text"]))
    p.drawText(QRectF(40, 60, 240, 40), int(AL_L | Qt.AlignmentFlag.AlignVCenter), info["number"])
    # --- engraved rule
    ry = 128.0
    for dy, col in ((0.0, QColor(0, 0, 0, 150 if dark else 40)), (1.2, QColor(255, 255, 255, 18 if dark else 200))):
        lg = QLinearGradient(40, 0, W - 40, 0)
        clear = QColor(col)
        clear.setAlpha(0)
        lg.setColorAt(0, clear)
        lg.setColorAt(0.12, col)
        lg.setColorAt(0.88, col)
        lg.setColorAt(1, clear)
        p.fillRect(QRectF(40, ry + dy, W - 80, 1.0), lg)
    # a small diamond notch in the middle of the rule: the brand's signature nick
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(brand.metal(QPointF(W / 2 - 5, ry - 5), QPointF(W / 2 + 5, ry + 6), pal))
    p.drawPolygon(_diamond(W / 2, ry + 0.6, 5.0))
    # --- facts: two columns x three rows, labels small and muted, values large
    rows = _facts(info)
    col_w, top, row_h = 300.0, 150.0, 58.0
    for i, (lab, val, latin) in enumerate(rows):
        col, row = i % 2, i // 2                                            # column 0 = right (start side in RTL)
        x = (W - 40 - col_w) if col == 0 else 40.0
        y = top + row * row_h
        p.setFont(_ui_font(9.5))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(x, y, col_w, 18), int(AL_R | Qt.AlignmentFlag.AlignVCenter), lab)
        vf = _ui_font(13.5 if not latin else 10.8, spacing=1.2 if latin else 0.0, bold=not latin)
        p.setFont(vf)
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(x, y + 19, col_w, 26), int(AL_R | Qt.AlignmentFlag.AlignVCenter), val)
    # --- footer: seal (start side = left) and the honesty line
    fy = 340.0
    seal_c = QPointF(40 + 52, fy + 52)
    brand.paint_seal(p, seal_c, 50.0, pal, "معتبر")
    p.setFont(_ui_font(9.0))
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(140, fy + 8, W - 140 - 40, 40), int(AL_R | Qt.TextFlag.TextWordWrap),
               "این شناسه فقط برچسب است، نه کلید: از آن نمی‌شود به داده‌ها رسید. رمز و کلید بازیابی هرگز روی این کارت نیستند.")
    p.setFont(brand.display_font(9.5, False, 3.2))
    p.setPen(brand._mix(QColor(pal["muted"]), acc, 0.4))
    p.drawText(QRectF(140, fy + 62, W - 140 - 40, 22), int(AL_R | Qt.AlignmentFlag.AlignVCenter),
               "END-TO-END ENCRYPTED  ·  OFFLINE")
    paint_frame(p, pal)
    p.restore()


def _diamond(x: float, y: float, r: float):
    from PyQt6.QtGui import QPolygonF
    return QPolygonF([QPointF(x, y - r), QPointF(x + r * 0.8, y), QPointF(x, y + r), QPointF(x - r * 0.8, y)])


def render_image(info: dict, pal: dict, width: int = 1440) -> QImage:
    """The shareable PNG: the same painter, on a transparent-cornered image with a little breathing room."""
    pad = 36
    scale = width / W
    img = QImage(int(width + 2 * pad * scale / 2), int(width * H / W + 2 * pad * scale / 2), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    m = pad * scale / 2
    sh = QRadialGradient(img.width() / 2, img.height() / 2 + m * 0.5, width * 0.62)
    sh.setColorAt(0, QColor(0, 0, 0, 90))
    sh.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), sh)
    paint_certificate(p, QRectF(m, m, width, width * H / W), info, pal)
    p.end()
    return img


class CertificateCard(QWidget):
    """The live card: pointer light + border spotlight + one glint on entry (the shared hover language), and a slow parallax
    of the engraving against the shield. It repaints only while the pointer is on it or the eased tilt moved."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        from .parallax import Follower
        self.info = info
        self.setMinimumSize(520, int(520 * H / W))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAccessibleName("گواهی ولت")
        self.setAccessibleDescription(f"شمارهٔ {info['number']}، ساخته‌شده در {info['created_fa']}")
        self.hl = brand.HoverLight(self)
        self.follow = Follower(self, 0.12)
        self._poll = QTimer(self, interval=33)
        self._poll.timeout.connect(self._step)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return int(w * H / W)

    def sizeHint(self):  # noqa: N802
        from PyQt6.QtCore import QSize
        return QSize(720, 450)

    def _step(self) -> None:
        if self.follow.step():
            self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        if MOTION[0]:
            self._poll.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._poll.stop()
        self.hl.stop()
        super().hideEvent(e)

    def enterEvent(self, e) -> None:  # noqa: N802
        self.hl.enter()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.hl.leave()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        r = QRectF(self.rect())
        paint_certificate(p, r, self.info, pal, (self.follow.x, self.follow.y))
        self.hl.paint(p, r.adjusted(1, 1, -1, -1), RAD * r.width() / W, pal)


class CertificateDialog(MotionDialog):
    def __init__(self, win, info: dict | None = None):
        super().__init__(win)
        self.win = win
        self.info = info or cert_core.identity(win.store)
        self.setWindowTitle("گواهی ولت")
        self.setProperty("theme", win.theme)
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(12)
        self.card = CertificateCard(self.info)
        lay.addWidget(self.card, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.note = label("", "Muted", True)
        row.addWidget(self.note, 1)
        self.b_copy = button("کپی شناسه", slot=self.copy_id)
        self.b_save = button("ذخیرهٔ تصویر…", "Primary", self.save_image)
        row.addWidget(self.b_copy)
        row.addWidget(self.b_save)
        lay.addLayout(row)

    def copy_id(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.info["fingerprint"].replace(" · ", ""))
        self.note.setText("شناسه کپی شد.")

    def save_image(self, path: str | None = None) -> str | None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "ذخیرهٔ گواهی", f"aegis-vault-{self.info['number']}.png", "PNG (*.png)")
        if not path:
            return None
        if not path.lower().endswith(".png"):
            path += ".png"
        from .theme import PALETTES
        img = render_image(self.info, PALETTES[self.win.theme] if self.win.theme in PALETTES else _fpal(self))
        ok = img.save(path, "PNG")
        self.note.setText("تصویر ذخیره شد." if ok else "ذخیره نشد؛ مسیر را بررسی کن.")
        return path if ok else None
