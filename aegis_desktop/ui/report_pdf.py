# SPDX-License-Identifier: GPL-3.0-or-later
"""«خروجی PDF» for the Reports page: an aggregate, shareable summary on the Aegis letterhead.

It contains only numbers and category names - never a task title, note or journal line - so it is safe to hand to someone."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from ..core import jalali, logic
from ..core.jalali import fa
from . import brand, letterhead
from .theme import AL_L, AL_R
from .letterhead import FOOT_H, HEAD_H, MARGIN, PAGE_H, PAGE_W

RES = 144                                          # dpi of the writer; the painter is scaled so 1 unit = 1 point
BODY_BOTTOM = PAGE_H - FOOT_H - 16


def _ui(pt: float, bold: bool = False) -> QFont:
    return letterhead._ui(pt, bold)


def _fa_date(d: dt.date) -> str:
    j = jalali.date_to_due(d)
    return f"{fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} {fa(j['jy'])}"


class _Sheet:
    """A tiny flow layout over QPdfWriter pages: ``y`` is the cursor; ``need(h)`` starts a new page when h does not fit."""

    def __init__(self, w: QPdfWriter, p: QPainter, pal: dict, title: str, subtitle: str, number: str, total: int = 0):
        self.w, self.p, self.pal, self.title, self.subtitle, self.number = w, p, pal, title, subtitle, number
        self.page, self.total = 1, total
        self._head()

    def _head(self) -> None:
        letterhead.paint_letterhead(self.p, self.pal, self.title, self.subtitle, self.number)
        self.y = HEAD_H + 8

    def need(self, h: float) -> None:
        if self.y + h > BODY_BOTTOM:
            self.new_page()

    def foot(self) -> None:
        letterhead.paint_footer(self.p, self.pal, self.page, max(self.total, self.page), fa)

    def new_page(self) -> None:
        self.foot()
        self.w.newPage()
        self.page += 1
        self._head()

    def h2(self, text: str, sub: str = "") -> None:
        self.need(40)
        self.p.setFont(_ui(11.5, True))
        self.p.setPen(QColor(self.pal["text"]))
        self.p.drawText(QRectF(MARGIN, self.y, PAGE_W - 2 * MARGIN, 20), int(AL_R | Qt.AlignmentFlag.AlignVCenter), text)
        self.y += 20
        if sub:
            self.p.setFont(_ui(8.5))
            self.p.setPen(QColor(self.pal["muted"]))
            self.p.drawText(QRectF(MARGIN, self.y, PAGE_W - 2 * MARGIN, 14), int(AL_R | Qt.AlignmentFlag.AlignVCenter), sub)
            self.y += 16
        self.y += 4


def _kpis(s: _Sheet, r: dict) -> None:
    items = [("انجام‌شده", r["total_done"], "ok"), ("باز", r["open"], "accent"), ("عقب‌افتاده", r["overdue"], "danger"),
             ("پومودورو", r["pomodoros"], "warn")]
    s.need(74)
    gap, w = 10.0, (PAGE_W - 2 * MARGIN - 30.0) / 4
    p = s.p
    for i, (cap, val, tone) in enumerate(items):
        x = PAGE_W - MARGIN - (i + 1) * w - i * gap
        box = QRectF(x, s.y, w, 62)
        p.setPen(QPen(QColor(s.pal["line"]), 0.8))
        p.setBrush(QColor(s.pal["panel"]))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(s.pal[tone]))
        p.drawRoundedRect(QRectF(box.right() - 3, box.top() + 12, 3, box.height() - 24), 1.5, 1.5)   # a slim tone edge on the start side
        vf = _ui(22, True)
        p.setFont(vf)
        p.setPen(QColor(s.pal["text"]))
        p.drawText(QRectF(box.left(), box.top() + 8, box.width() - 12, 30), int(AL_R | Qt.AlignmentFlag.AlignVCenter), fa(val))
        p.setFont(_ui(8.5))
        p.setPen(QColor(s.pal["muted"]))
        p.drawText(QRectF(box.left(), box.top() + 38, box.width() - 12, 16), int(AL_R | Qt.AlignmentFlag.AlignVCenter), cap)
    s.y += 62 + 16


def _bars(s: _Sheet, series: list[tuple[str, int]]) -> None:
    h = 96.0
    s.need(h + 34)
    p = s.p
    x0, x1 = MARGIN, PAGE_W - MARGIN
    gut = 26.0                                                       # a gutter for the scale label: it used to sit on the newest bar
    top = s.y
    mx = max([n for _d, n in series] + [1])
    n = max(1, len(series))
    step = (x1 - (x0 + gut)) / n
    bw = max(1.5, min(14.0, step * 0.62))
    p.setPen(QPen(QColor(s.pal["line"]), 0.6, Qt.PenStyle.DotLine))
    for k in range(4):
        y = top + h * k / 3
        p.drawLine(QPointF(x0 + gut, y), QPointF(x1, y))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(brand.metal(QPointF(0, top), QPointF(0, top + h), s.pal))
    for i, (_d, v) in enumerate(series):                             # newest on the LEFT would fight RTL: oldest at the right
        cx = x1 - step * (i + 0.5)
        bh = (h - 2) * v / mx
        if v:
            p.drawRoundedRect(QRectF(cx - bw / 2, top + h - bh, bw, bh), min(2.0, bw / 2), min(2.0, bw / 2))
        else:
            p.setBrush(QColor(s.pal["line"]))
            p.drawRect(QRectF(cx - bw / 2, top + h - 1.2, bw, 1.2))
            p.setBrush(brand.metal(QPointF(0, top), QPointF(0, top + h), s.pal))
    p.setFont(_ui(7.5))
    p.setPen(QColor(s.pal["muted"]))
    p.drawText(QRectF(x0, top - 5, gut - 6, 12), int(AL_R | Qt.AlignmentFlag.AlignTop), fa(mx))
    if series:
        p.drawText(QRectF(x1 - 120, top + h + 3, 120, 12), int(AL_R | Qt.AlignmentFlag.AlignTop),
                   _fa_date(dt.date.fromisoformat(series[0][0])))
        p.drawText(QRectF(x0, top + h + 3, 120, 12), int(AL_L | Qt.AlignmentFlag.AlignTop),
                   _fa_date(dt.date.fromisoformat(series[-1][0])))
    s.y += h + 24


def _hbars(s: _Sheet, rows: list[tuple[str, float, str]], unit: str = "٪") -> None:
    p = s.p
    lab_w, right = 96.0, PAGE_W - MARGIN
    for lab, val, tone in rows:
        s.need(24)
        p.setFont(_ui(9))
        p.setPen(QColor(s.pal["text"]))
        p.drawText(QRectF(right - lab_w, s.y, lab_w, 16), int(AL_R | Qt.AlignmentFlag.AlignVCenter), lab)
        track = QRectF(MARGIN + 46, s.y + 4, right - lab_w - 8 - MARGIN - 46, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(s.pal["panel2"]))
        p.drawRoundedRect(track, 4, 4)
        f = max(0.0, min(1.0, val / 100.0))
        if f > 0:
            fw = max(6.0, track.width() * f)
            p.setBrush(brand.metal(QPointF(track.right() - fw, 0), QPointF(track.right(), 0), s.pal) if tone == "accent" else QColor(s.pal[tone]))
            p.drawRoundedRect(QRectF(track.right() - fw, track.top(), fw, track.height()), 4, 4)
        p.setFont(_ui(8.5))
        p.setPen(QColor(s.pal["muted"]))
        p.drawText(QRectF(MARGIN, s.y, 42, 16), int(AL_L | Qt.AlignmentFlag.AlignVCenter), fa(round(val)) + unit)
        s.y += 22
    s.y += 6


def _bullets(s: _Sheet, lines: list[str]) -> None:
    p = s.p
    for t in lines:
        s.need(20)
        p.setFont(_ui(9.5))
        p.setPen(QColor(s.pal["text"]))
        p.drawText(QRectF(MARGIN, s.y, PAGE_W - 2 * MARGIN - 12, 18), int(AL_R | Qt.AlignmentFlag.AlignVCenter), t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(s.pal["accent"]))
        p.drawEllipse(QPointF(PAGE_W - MARGIN - 3, s.y + 9), 2.2, 2.2)
        s.y += 19
    s.y += 6


def report_lines(v: dict, days: int, today: dt.date) -> list[str]:
    r = logic.report_summary(v, days, today)
    wd = logic.weekday_done(v, days)
    out = [f"در این بازه {fa(r['total_done'])} تسک انجام شد؛ میانگین {fa(round(r['total_done'] / days, 1)).replace('.', '٫')} در روز."]
    if sum(wd):
        out.append(f"پرکارترین روز هفته: {jalali.WEEKDAYS_FA[wd.index(max(wd))]} ({fa(max(wd))} تسک).")
    if r["overdue"]:
        out.append(f"{fa(r['overdue'])} تسک عقب‌افتاده منتظر رسیدگی است.")
    po = logic.priority_open(v)
    if po["high"]:
        out.append(f"{fa(po['high'])} تسک باز با اولویت زیاد وجود دارد.")
    return out


def _render(dev, vault: dict, days: int, pal: dict, number: str, today: dt.date, total: int) -> int:
    w = QPdfWriter(dev)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    w.setResolution(RES)
    w.setTitle("گزارش Aegis Planner")
    w.setCreator("Aegis Planner")
    p = QPainter(w)
    if not p.isActive():
        return 0
    p.scale(w.width() / PAGE_W, w.height() / PAGE_H)              # the whole A4 sheet == 595 x 842 units
    letterhead.UNIT[0] = 72.0 / RES                                # ...and a font of N pt is N units tall, whatever the writer's dpi
    try:
        return _draw(w, p, vault, days, pal, number, today, total)
    finally:
        letterhead.UNIT[0] = 1.0
        if p.isActive():
            p.end()                                                    # never let the writer die under an active painter (segfault)


def _draw(w, p: QPainter, vault: dict, days: int, pal: dict, number: str, today: dt.date, total: int) -> int:
    since = today - dt.timedelta(days=days - 1)
    sub = f"{fa(days)} روز اخیر  ·  {_fa_date(since)} تا {_fa_date(today)}"
    s = _Sheet(w, p, pal, "گزارش عملکرد", sub, number, total)
    r = logic.report_summary(vault, days, today)
    _kpis(s, r)
    s.h2("روند انجام تسک‌ها", "انجام‌شده در هر روز (قدیمی‌ترین در سمت راست)")
    _bars(s, r["series"])
    sc = logic.scores(vault, days, today)
    s.h2("امتیاز عملکرد", "تکمیل، وقت‌شناسی، پایبندی به عادت‌ها و پیشرفت هدف‌ها")
    _hbars(s, [("تکمیل", sc["completion"], "accent"), ("وقت‌شناسی", sc["punctual"], "ok"), ("عادت‌ها", sc["habit"], "warn"),
               ("هدف‌ها", sc["goal"], "accent")])
    cats = sorted(r["by_cat"].items(), key=lambda kv: -kv[1])
    if cats:
        s.h2("تسک‌های انجام‌شده به تفکیک دسته")
        top = max(n for _c, n in cats)
        _hbars(s, [(logic.CAT_LABEL.get(c, c), n / top * 100, "accent") for c, n in cats[:8]], unit="")
    gp = logic.goal_progress_map(vault)
    goals = [gp[g["id"]] for g in vault.get("goals", []) if gp.get(g["id"]) is not None]
    if goals:                                                            # goal titles are the user's own words: only their progress is shown
        s.h2("پیشرفت هدف‌ها", f"{fa(len(goals))} هدف در جریان")
        _hbars(s, [("میانگین همهٔ هدف‌ها", sum(goals) / len(goals), "accent")])
    s.h2("نکته‌ها")
    _bullets(s, report_lines(vault, days, today))
    s.foot()
    return s.page


def build_report_pdf(path: str, vault: dict, days: int = 30, theme_pal: dict | None = None, number: str = "",
                     today: dt.date | None = None) -> int:
    """Write the PDF; returns the number of pages. ``theme_pal`` colours the metal, the page itself stays white.
    Two passes: a dry run into memory counts the pages so every footer can say «صفحه ۱ از ۲»."""
    from PyQt6.QtCore import QBuffer, QIODevice
    today = today or dt.date.today()
    pal = letterhead.paper_palette(theme_pal)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    total = _render(buf, vault, days, pal, number, today, 0)
    buf.close()
    if not total:
        return 0
    return _render(path, vault, days, pal, number, today, total)
