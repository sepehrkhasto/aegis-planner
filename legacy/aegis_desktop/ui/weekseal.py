# SPDX-License-Identifier: GPL-3.0-or-later
"""«مهر هفته»: the last seven days as one engraved card you can keep or send - big seal, a handful of numbers, seven bars.
Aggregates only (counts, minutes, a title) - no task text ever reaches the picture."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout

from ..core import jalali, logic
from ..core.jalali import fa
from . import brand
from .certificate import CertificateCard, H, W, _ui_font, paint_frame, paint_shell
from .letterhead import rule
from .micro import MotionDialog
from .theme import AL_R
from .widgets import button, label


def _range_fa(a: dt.date, b: dt.date) -> str:
    ja, jb = jalali.date_to_due(a), jalali.date_to_due(b)
    if ja["jm"] == jb["jm"]:
        return f"{fa(ja['jd'])} تا {fa(jb['jd'])} {jalali.MONTHS_FA[jb['jm'] - 1]} {fa(jb['jy'])}"
    return f"{fa(ja['jd'])} {jalali.MONTHS_FA[ja['jm'] - 1]} تا {fa(jb['jd'])} {jalali.MONTHS_FA[jb['jm'] - 1]} {fa(jb['jy'])}"


def stat_rows(d: dict) -> list[tuple[str, str]]:
    """(label, value) rows, in reading order."""
    rows = [("کار انجام‌شده", fa(d["done"]))]
    if d["delta_pct"] is None:
        rows.append(("نسبت به هفتهٔ قبل", "—"))
    else:
        sign = "‎+" if d["delta_pct"] > 0 else ("‎−" if d["delta_pct"] < 0 else "")
        rows.append(("نسبت به هفتهٔ قبل", f"{sign}{fa(abs(d['delta_pct']))}٪"))
    rows.append(("تمرکز", f"{fa(d['focus_minutes'])} دقیقه" if d["focus_minutes"] else "—"))
    rows.append(("پیاپی", f"{fa(d['streak'])} روز" if d["streak"] else "—"))
    if d["best_day"] is not None:
        rows.append(("پرکارترین روز", jalali.WEEKDAYS_FA[jalali.weekday_index(d["best_day"])]))
    return rows


def paint_week_seal(p: QPainter, rect: QRectF, d: dict, pal: dict, tilt: tuple = (0.0, 0.0)) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.translate(rect.topLeft())
    p.scale(rect.width() / W, rect.height() / H)
    tx, ty = tilt
    acc = QColor(pal["accent"])
    dark = QColor(pal["bg"]).lightness() < 128
    paint_shell(p, pal, tilt, center=(170.0, 200.0))
    # the seal, large, on the start-opposite side (left), lit from behind
    sc = QPointF(172, 214)
    glow = QRadialGradient(sc, 150)
    glow.setColorAt(0, QColor(acc.red(), acc.green(), acc.blue(), 46 if dark else 30))
    glow.setColorAt(1, QColor(acc.red(), acc.green(), acc.blue(), 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(sc, 150, 150)
    p.save()
    p.translate(tx * 4.0, ty * 3.0)
    brand.paint_seal(p, sc, 108.0, pal, "مهر هفته")
    p.restore()
    p.setFont(_ui_font(9.5, spacing=0.4))
    p.setPen(QColor(pal["muted"]))
    p.drawText(QRectF(56, 332, 232, 20), int(Qt.AlignmentFlag.AlignCenter), _range_fa(d["since"], d["until"]))
    # header (right): title + wordmark
    p.setFont(brand.display_font(15, True, 4.0))
    p.setPen(QColor(pal["acc_text"]))
    p.drawText(QRectF(340, 34, W - 340 - 40, 26), int(AL_R | Qt.AlignmentFlag.AlignVCenter), "AEGIS  PLANNER")
    tf = _ui_font(21, bold=True)
    p.setFont(tf)
    p.setPen(QColor(pal["text"]))
    p.drawText(QRectF(340, 62, W - 340 - 40, 38), int(AL_R | Qt.AlignmentFlag.AlignVCenter), d["title"])
    rule(p, 340, W - 40, 112, pal)
    y = 128.0
    for lab, val in stat_rows(d):
        p.setFont(_ui_font(9.5))
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(W - 40 - 150, y + 4, 150, 22), int(AL_R | Qt.AlignmentFlag.AlignVCenter), lab)     # label at the start edge
        p.setFont(_ui_font(14, bold=True))
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(340, y, W - 40 - 150 - 14 - 340, 30), int(AL_R | Qt.AlignmentFlag.AlignVCenter), val)   # value just after it
        y += 34
    # seven bars: the shape of the week (oldest at the right, like the rest of the app's time axis)
    bx1, bx0, base, bh = W - 40.0, 340.0, 388.0, 44.0
    bars = d["done_by_day"]
    mx = max(bars + [1])
    step = (bx1 - bx0) / 7
    bw = 18.0
    for i, n in enumerate(bars):
        cx = bx1 - step * (i + 0.5)
        h = max(2.0, bh * n / mx) if n else 2.0
        p.setPen(Qt.PenStyle.NoPen)
        if n:
            p.setBrush(brand.metal(QPointF(cx, base - h), QPointF(cx, base), pal))
        else:
            c = QColor(pal["line"])
            p.setBrush(c)
        p.drawRoundedRect(QRectF(cx - bw / 2, base - h, bw, h), 3, 3)
    p.setFont(brand.display_font(8.5, False, 2.4))
    p.setPen(brand._mix(QColor(pal["muted"]), acc, 0.4))
    p.drawText(QRectF(340, 406, W - 380, 18), int(AL_R | Qt.AlignmentFlag.AlignVCenter), "SEALED  ·  OFFLINE")
    paint_frame(p, pal)
    p.restore()


def render_week_image(d: dict, pal: dict, width: int = 1440) -> QImage:
    """Same soft-shadowed PNG as the certificate, with the week seal inside."""
    pad = 36
    scale = width / W
    img = QImage(int(width + pad * scale), int(width * H / W + pad * scale), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    m = pad * scale / 2
    sh = QRadialGradient(img.width() / 2, img.height() / 2 + m * 0.5, width * 0.62)
    sh.setColorAt(0, QColor(0, 0, 0, 90))
    sh.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), sh)
    paint_week_seal(p, QRectF(m, m, width, width * H / W), d, pal)
    p.end()
    return img


class WeekSealCard(CertificateCard):
    """Same live card (hover light, parallax) painting the week seal instead of the certificate."""

    def __init__(self, data: dict, parent=None):
        super().__init__({"number": "", "created_fa": "", "fingerprint": ""}, parent)
        self.data = data
        self.setAccessibleName("مهر هفته")
        self.setAccessibleDescription(f"{data['title']}؛ {fa(data['done'])} کار انجام‌شده")

    def paintEvent(self, _e) -> None:  # noqa: N802
        from .fx_widgets import _fpal
        pal = _fpal(self)
        p = QPainter(self)
        r = QRectF(self.rect())
        paint_week_seal(p, r, self.data, pal, (self.follow.x, self.follow.y))
        from .certificate import RAD
        self.hl.paint(p, r.adjusted(1, 1, -1, -1), RAD * r.width() / W, pal)


class WeekSealDialog(MotionDialog):
    def __init__(self, win, data: dict | None = None):
        super().__init__(win)
        self.win = win
        self.data = data or logic.week_summary(win.store.vault)
        self.setWindowTitle("مهر هفته")
        self.setProperty("theme", win.theme)
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(12)
        self.card = WeekSealCard(self.data)
        lay.addWidget(self.card, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.note = label("فقط عدد و خلاصه؛ هیچ متنی از تسک‌هایت در تصویر نیست.", "Muted", True)
        row.addWidget(self.note, 1)
        self.b_copy = button("کپی تصویر", slot=self.copy_image)
        self.b_save = button("ذخیرهٔ تصویر…", "Primary", self.save_image)
        row.addWidget(self.b_copy)
        row.addWidget(self.b_save)
        lay.addLayout(row)

    def _image(self) -> QImage:
        from .theme import PALETTES
        return render_week_image(self.data, PALETTES[self.win.theme])

    def copy_image(self) -> None:
        QApplication.clipboard().setImage(self._image())
        self.note.setText("تصویر کپی شد.")

    def save_image(self, path: str | None = None) -> str | None:
        from PyQt6.QtWidgets import QFileDialog
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "ذخیرهٔ مهر هفته", f"aegis-week-{self.data['until'].isoformat()}.png", "PNG (*.png)")
        if not path:
            return None
        if not path.lower().endswith(".png"):
            path += ".png"
        ok = self._image().save(path, "PNG")
        self.note.setText("تصویر ذخیره شد." if ok else "ذخیره نشد؛ مسیر را بررسی کن.")
        return path if ok else None
