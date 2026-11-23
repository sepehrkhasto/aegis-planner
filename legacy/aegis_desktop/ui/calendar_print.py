# SPDX-License-Identifier: GPL-3.0-or-later
"""Printing for the calendar: a day, a week or a month as a restrained black-and-white A4 sheet.

Unlike the Reports PDF (numbers only) this printout DOES contain task titles. Everything is painted with QPainter on any
QPagedPaintDevice, so «ذخیره PDF» (QPdfWriter) and «چاپ…» (QPrinter) share one renderer:

* day   - portrait: an hourly schedule, a «بدون ساعت» checklist with empty boxes, and a ruled notes area;
* week  - landscape: seven ruled columns (Saturday at the right);
* month - landscape: a Jalali month grid; a crowded cell says «+N بیشتر» and «فهرست کامل ماه» follows on the next page(s).

The page is white, the ink near-black, lines hairline and the only filled shapes are the small mark, priority dots and today's
date - friendly to laser printers and to the ink budget."""
from __future__ import annotations

import dataclasses
import datetime as dt
import math

from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from ..core import jalali, logic
from ..core.jalali import fa
from . import brand, letterhead
from .calendar_kit import hm, layout_events, mins, range_text, span_of
from .theme import AL_L, AL_R

MODES = ("day", "week", "month")
RES = 144                                   # dpi of the PDF writer; the painter is scaled so 1 unit = 1 point
PORTRAIT, LANDSCAPE = (595.0, 842.0), (842.0, 595.0)
M = 30.0                                    # side margin
HEAD_BOTTOM = 68.0                          # the header band ends here
FOOT_H = 34.0
INK, MUTED, GRID, HAIR, SHADE = "#15171c", "#666b75", "#9ea3ad", "#d3d6dc", "#eff0f3"
KIND = {"day": "تقویم روزانه", "week": "تقویم هفتگی", "month": "تقویم ماهانه"}
NO_TITLE = "(بدون عنوان)"
MAX_TITLE = 300                             # a pasted essay must not stall the wrap loop
MAX_LANES = 3                               # more simultaneous events than this go to the checklist instead of thin slivers


# ------------------------------------------------------------------------------------------------ dates & titles ---
def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=jalali.weekday_index(d))


def _jd(d: dt.date) -> dict:
    return jalali.date_to_due(d)


def _dm(d: dt.date) -> str:
    j = _jd(d)
    return f"{fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]}"


def _dmy(d: dt.date) -> str:
    return f"{_dm(d)} {fa(_jd(d)['jy'])}"


def range_dates(mode: str, anchor: dt.date) -> list[dt.date]:
    """The days a printout of ``mode`` around ``anchor`` covers (a month: its real Jalali length)."""
    if mode == "day":
        return [anchor]
    if mode == "week":
        s = week_start(anchor)
        return [s + dt.timedelta(days=i) for i in range(7)]
    j = _jd(anchor)
    first = dt.date(*jalali.to_gregorian(j["jy"], j["jm"], 1))
    return [first + dt.timedelta(days=i) for i in range(jalali.month_length(j["jy"], j["jm"]))]


def range_title(mode: str, anchor: dt.date) -> str:
    """«مهر ۱۴۰۵» / «هفته ۸ تا ۱۴ مهر ۱۴۰۵» / «چهارشنبه ۱۰ مهر ۱۴۰۵»."""
    j = _jd(anchor)
    if mode == "month":
        return f"{jalali.MONTHS_FA[j['jm'] - 1]} {fa(j['jy'])}"
    if mode == "day":
        return f"{jalali.WEEKDAYS_FA[jalali.weekday_index(anchor)]} {_dmy(anchor)}"
    a = week_start(anchor)
    b = a + dt.timedelta(days=6)
    ja, jb = _jd(a), _jd(b)
    if (ja["jy"], ja["jm"]) == (jb["jy"], jb["jm"]):
        return f"هفته {fa(ja['jd'])} تا {fa(jb['jd'])} {jalali.MONTHS_FA[jb['jm'] - 1]} {fa(jb['jy'])}"
    if ja["jy"] == jb["jy"]:
        return f"هفته {_dm(a)} تا {_dm(b)} {fa(jb['jy'])}"
    return f"هفته {_dmy(a)} تا {_dmy(b)}"


def default_name(mode: str, anchor: dt.date) -> str:
    j = _jd(anchor)
    return f"aegis-calendar-{mode}-{j['jy']}-{j['jm']:02d}" + (f"-{j['jd']:02d}" if mode != "month" else "") + ".pdf"


# ------------------------------------------------------------------------------------------------ task items ---
@dataclasses.dataclass
class _It:
    x: dict
    title: str
    a: int | None            # start minute, None = no (usable) time
    rng: str                 # «۱۲ تا ۱۵ مهر» for a multi-day task, else ""
    pr: str
    done: bool
    first: bool              # False on the 2nd..nth day of a multi-day task

    @property
    def time(self) -> str:
        return fa(hm(self.a)) if self.a is not None else ""

    @property
    def span_text(self) -> str:
        s = span_of(self.x)
        if s is None:
            return ""
        return range_text(*s) if mins(self.x.get("timeTo")) is not None else self.time


def _clean(t) -> str:
    s = " ".join(str(t or "").split())
    return (s[:MAX_TITLE] + "…") if len(s) > MAX_TITLE else (s or NO_TITLE)


def _item(x: dict, day: dt.date) -> _It:
    d0 = jalali.due_to_date(x.get("due")) or day
    d1 = jalali.due_to_date(x.get("dueEnd")) or d0
    if d1 < d0:
        d1 = d0
    rng = ""
    if d1 > d0:
        j0, j1 = _jd(d0), _jd(d1)
        rng = (f"{fa(j0['jd'])} تا {_dm(d1)}" if (j0["jy"], j0["jm"]) == (j1["jy"], j1["jm"]) else f"{_dm(d0)} تا {_dm(d1)}")
    pr = x.get("pr") if x.get("pr") in ("high", "low") else "normal"
    return _It(x, _clean(x.get("title")), mins(x.get("timeFrom")), rng, pr, bool(x.get("done")), day == d0)


def _index(tasks: list[dict]) -> dict[dt.date, list[dict]]:
    """date -> tasks covering it (same span rule as the calendar, but tolerant of odd field types; ordering is done later)."""
    idx: dict[dt.date, list[dict]] = {}
    for x in tasks:
        if not isinstance(x, dict):
            continue
        d0 = jalali.due_to_date(x.get("due"))
        if not d0:
            continue
        d1 = jalali.due_to_date(x.get("dueEnd")) or d0
        for i in range((min((d1 - d0).days, logic.MAX_SPAN_DAYS) if d1 >= d0 else 0) + 1):
            idx.setdefault(d0 + dt.timedelta(days=i), []).append(x)
    return idx


def _day_items(idx: dict, d: dt.date) -> list[_It]:
    its = [_item(x, d) for x in idx.get(d, ()) if isinstance(x, dict)]
    rank = {"high": 0, "normal": 1, "low": 2}
    its.sort(key=lambda i: (i.a is None, i.a or 0, rank[i.pr], i.title))
    return its


# ------------------------------------------------------------------------------------------------ small painters ---
def _f(pt: float, bold: bool = False, strike: bool = False) -> QFont:
    f = letterhead._ui(pt, bold)
    f.setStrikeOut(strike)
    return f


def _fm(p: QPainter, f: QFont) -> QFontMetricsF:
    return QFontMetricsF(f, p.device())


def _text(p: QPainter, r: QRectF, s: str, f: QFont, col: str = INK, al=AL_R) -> None:
    p.setFont(f)
    p.setPen(QColor(col))
    p.drawText(r, int(al | Qt.AlignmentFlag.AlignVCenter), s)


def _elide(p: QPainter, s: str, f: QFont, w: float) -> str:
    return _fm(p, f).elidedText(s, Qt.TextElideMode.ElideRight, max(1.0, w))


def _wrap(p: QPainter, text: str, f: QFont, width: float, max_lines: int) -> list[str]:
    """Greedy word wrap (long words are cut), at most ``max_lines`` lines, the last one ending in «…» when text was dropped."""
    fm = _fm(p, f)
    width = max(8.0, width)
    lines: list[str] = []
    cur = ""
    for w in text.split(" "):
        trial = f"{cur} {w}" if cur else w
        if fm.horizontalAdvance(trial) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        while len(w) > 1 and fm.horizontalAdvance(w) > width:
            lo, hi = 1, len(w) - 1                                   # longest prefix that fits
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fm.horizontalAdvance(w[:mid]) <= width:
                    lo = mid
                else:
                    hi = mid - 1
            lines.append(w[:lo])
            w = w[lo:]
        cur = w
        if len(lines) > max_lines:
            break
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and fm.horizontalAdvance(last + "…") > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines or [""]


def _dot(p: QPainter, c: QPointF, pr: str, done: bool, r: float = 2.5, cont: bool = False) -> None:
    """Priority mark that survives a b/w printer: high = solid, normal = ring, low = small grey ring. A dash = «continues from yesterday»."""
    p.save()
    col = QColor(MUTED if done else INK)
    if cont:
        p.setPen(QPen(col, 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
    elif pr == "high":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(c, r, r)
    elif pr == "low":
        p.setPen(QPen(QColor(GRID), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r * 0.7, r * 0.7)
    else:
        p.setPen(QPen(col, 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r * 0.85, r * 0.85)
    p.restore()


def _box(p: QPainter, r: QRectF, done: bool) -> None:
    """An empty square for a pen tick (with a tick when the task is done)."""
    p.save()
    p.setPen(QPen(QColor(INK), 0.8))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(r)
    if done:
        p.setPen(QPen(QColor(MUTED), 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(r.left() + r.width() * 0.2, r.center().y()), QPointF(r.left() + r.width() * 0.42, r.bottom() - r.height() * 0.22),
                        QPointF(r.right() - r.width() * 0.15, r.top() + r.height() * 0.2)])
    p.restore()


def _line(p: QPainter, x0: float, y0: float, x1: float, y1: float, col: str = HAIR, w: float = 0.5, dash: bool = False) -> None:
    pen = QPen(QColor(col), w)
    if dash:
        pen.setStyle(Qt.PenStyle.DotLine)
    p.setPen(pen)
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))


def _more(n: int) -> str:
    """«+N بیشتر» with the plus kept in front of the number (an isolate stops the RTL line from flipping it)."""
    return f"\u2066+{fa(n)}\u2069 بیشتر"


def _fit(needs: list[int], rows: int, reserve: int = 1) -> int:
    """How many items (``needs[i]`` rows each) fit in ``rows``; unless all of them do, ``reserve`` rows stay free for «+N بیشتر»."""
    used = 0
    for k, n in enumerate(needs):
        more = k < len(needs) - 1
        if used + n + (reserve if more else 0) > rows:
            return k
        used += n
    return len(needs)


# ------------------------------------------------------------------------------------------------ page chrome ---
class _Pager:
    """The sheet: header (mark, wordmark, range title), footer (print date, legend, page x of y) and page turning."""

    def __init__(self, dev, p: QPainter, size: tuple[float, float], pal: dict, kind: str, title: str, sub: str, today: dt.date, total: int):
        self.dev, self.p, (self.W, self.H), self.pal = dev, p, size, pal
        self.kind, self.title, self.sub, self.today, self.total, self.page = kind, title, sub, today, total, 1
        self.top, self.bottom = HEAD_BOTTOM + 8, self.H - FOOT_H - 6
        self.header()

    def header(self) -> None:
        p, W = self.p, self.W
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        s, top = 30.0, 20.0
        brand.paint_mark(p, QRectF(W - M - s, top, s, s), self.pal)
        wm = QRectF(M + 200, top - 1, W - 2 * M - s - 9 - 200, 17)
        _text(p, wm, "Aegis Planner", letterhead._disp(12.5, True, 1.2), INK)
        _text(p, QRectF(wm.left(), top + 15, wm.width(), 14), self.kind, _f(8.5), MUTED)
        mid = QRectF(M + 150, top - 1, W - 2 * M - 300, 22)
        f = _f(17, True)
        while _fm(p, f).horizontalAdvance(self.title) > mid.width() and f.pointSizeF() > 9:
            f.setPointSizeF(f.pointSizeF() - 0.5)
        _text(p, mid, self.title, f, INK, Qt.AlignmentFlag.AlignHCenter)
        if self.sub:
            _text(p, QRectF(mid.left(), top + 22, mid.width(), 14), self.sub, _f(8.5), MUTED, Qt.AlignmentFlag.AlignHCenter)
        _line(p, M, HEAD_BOTTOM, W - M, HEAD_BOTTOM, INK, 0.8)
        p.restore()

    def footer(self) -> None:
        p, W = self.p, self.W
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.H - FOOT_H
        _line(p, M, y, W - M, y, HAIR, 0.6)
        r = QRectF(0, y + 7, 0, 14)
        _text(p, QRectF(W - M - 140, y + 7, 140, 14), f"صفحه {fa(self.page)} از {fa(max(self.total, self.page))}", _f(8), MUTED)
        _text(p, QRectF(M, y + 7, 220, 14), f"تاریخ چاپ: {_dmy(self.today)}", _f(8), MUTED, AL_L)
        # legend, centred: solid = high, ring = normal, small ring = low, dash = continues
        items = (("زیاد", "high", False), ("معمولی", "normal", False), ("کم", "low", False), ("ادامه", "normal", True))
        f = _f(7.5)
        fm = _fm(p, f)
        widths = [fm.horizontalAdvance(t) + 14 for t, _p, _c in items]
        x = (W + sum(widths)) / 2
        for (t, pr, cont), w in zip(items, widths):
            _dot(p, QPointF(x - 3, r.top() + 7), pr, False, 2.4, cont)
            _text(p, QRectF(x - w, r.top(), w - 9, 14), t, f, MUTED)
            x -= w + 8
        p.restore()

    def next_page(self, kind: str | None = None) -> None:
        self.footer()
        self.dev.newPage()
        self.page += 1
        if kind:
            self.kind = kind
        self.header()


# ------------------------------------------------------------------------------------------------ month ---
def _month(pg: _Pager, idx: dict, today: dt.date, anchor: dt.date) -> bool:
    """Draw the grid; True when some cell had more tasks than lines (the caller then appends the full list)."""
    p, W = pg.p, pg.W
    days = range_dates("month", anchor)
    lead = jalali.weekday_index(days[0])
    rows = math.ceil((lead + len(days)) / 7)
    x1, top, hdr = W - M, pg.top, 17.0
    cw = (x1 - M) / 7
    ch = (pg.bottom - top - hdr) / rows
    gy = top + hdr
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRectF(M, gy, cw, rows * ch), QColor(SHADE))                                        # Friday = the leftmost column
    for c in range(7):
        _text(p, QRectF(x1 - (c + 1) * cw, top, cw, hdr), jalali.WEEKDAYS_FA[c], _f(8.5, True), MUTED if c == 6 else INK, Qt.AlignmentFlag.AlignHCenter)
    for r in range(rows + 1):
        _line(p, M, gy + r * ch, x1, gy + r * ch, INK if r in (0, rows) else GRID, 0.8 if r in (0, rows) else 0.5)
    for c in range(8):
        _line(p, M + c * cw, gy, M + c * cw, gy + rows * ch, INK if c in (0, 7) else GRID, 0.8 if c in (0, 7) else 0.5)
    lh = 11.0
    cap = max(1, int((ch - 18) / lh))
    f_item, f_more = _f(7.5), _f(7, True)
    overflow = False
    for k in range(rows * 7):
        r, c = divmod(k, 7)
        x, y = x1 - (c + 1) * cw, gy + r * ch
        n = k - lead
        inside = 0 <= n < len(days)
        d = days[n] if inside else (days[0] + dt.timedelta(days=n))
        jd = _jd(d)
        num = QRectF(x + cw - 24, y + 2.5, 20, 12)
        if d == today:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(INK))
            p.drawEllipse(QPointF(x + cw - 14, y + 8.5), 7.6, 7.6)
            _text(p, num, fa(jd["jd"]), _f(8.5, True), "#ffffff", Qt.AlignmentFlag.AlignHCenter)
        else:
            _text(p, num, fa(jd["jd"]), _f(8.5, inside), INK if inside else "#b4b8c0", Qt.AlignmentFlag.AlignHCenter)
        if not inside:
            continue
        its = _day_items(idx, d)
        shown = its if len(its) <= cap else its[:cap - 1]
        for i, it in enumerate(shown):
            ly = y + 17 + i * lh
            _dot(p, QPointF(x + cw - 6, ly + lh / 2), it.pr, it.done, 2.1, not it.first)
            s = (f"{it.time} " if it.time and it.first else "") + it.title
            f = QFont(f_item)
            f.setStrikeOut(it.done)
            tw = cw - 15
            _text(p, QRectF(x + 3, ly, tw, lh), _elide(p, s, f, tw), f, MUTED if it.done else INK)
        if len(its) > len(shown):
            overflow = True
            _text(p, QRectF(x + 3, y + 17 + len(shown) * lh, cw - 15, lh), _more(len(its) - len(shown)), f_more, INK)
    p.restore()
    return overflow


# ------------------------------------------------------------------------------------------------ week ---
def _week(pg: _Pager, idx: dict, today: dt.date, anchor: dt.date) -> bool:
    p, W = pg.p, pg.W
    days = range_dates("week", anchor)
    x1, top, hdr = W - M, pg.top, 36.0
    cw = (x1 - M) / 7
    body = pg.bottom - top - hdr
    f_item = _f(8)
    pitch = max(13.0, _fm(p, f_item).lineSpacing() + 1)
    rows = int(body / pitch)
    gy = top + hdr
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(QRectF(M, gy, cw, body), QColor(SHADE))
    for k in range(rows + 1):
        _line(p, M, gy + k * pitch, x1, gy + k * pitch, HAIR, 0.45)
    for c in range(8):
        _line(p, M + c * cw, top, M + c * cw, gy + body, INK if c in (0, 7) else GRID, 0.8 if c in (0, 7) else 0.5)
    _line(p, M, top, x1, top, INK, 0.8)
    _line(p, M, gy, x1, gy, INK, 0.8)
    _line(p, M, gy + body, x1, gy + body, INK, 0.8)
    overflow = False
    for c, d in enumerate(days):
        x = x1 - (c + 1) * cw
        wk = QRectF(x, top + 3, cw, 13)
        _text(p, wk, jalali.WEEKDAYS_FA[c], _f(8.5), MUTED if c == 6 else INK, Qt.AlignmentFlag.AlignHCenter)
        dm = QRectF(x, top + 17, cw, 16)
        if d == today:
            f = _f(9.5, True)
            tw = _fm(p, f).horizontalAdvance(_dm(d)) + 12
            pill = QRectF(x + (cw - tw) / 2, dm.top() + 0.5, tw, 15)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(INK))
            p.drawRoundedRect(pill, 7.5, 7.5)
            _text(p, dm, _dm(d), f, "#ffffff", Qt.AlignmentFlag.AlignHCenter)
        else:
            _text(p, dm, _dm(d), _f(9.5, True), INK, Qt.AlignmentFlag.AlignHCenter)
        its = _day_items(idx, d)
        tw = cw - 15
        lines = []
        for it in its:
            f = QFont(f_item)
            f.setStrikeOut(it.done)
            s = (f"{it.time} " if it.time and it.first else "") + it.title
            lines.append(_wrap(p, s, f, tw, 2))
        k = _fit([len(l) for l in lines], rows)
        row = 0
        for it, ls in zip(its[:k], lines[:k]):
            f = QFont(f_item)
            f.setStrikeOut(it.done)
            _dot(p, QPointF(x + cw - 6, gy + (row + 0.5) * pitch), it.pr, it.done, 2.2, not it.first)
            for ln in ls:
                _text(p, QRectF(x + 3, gy + row * pitch, tw, pitch), ln, f, MUTED if it.done else INK)
                row += 1
        if k < len(its):
            overflow = True
            _text(p, QRectF(x + 3, gy + row * pitch, tw, pitch), _more(len(its) - k), _f(7.5, True), INK)
    p.restore()
    return overflow


# ------------------------------------------------------------------------------------------------ day ---
def _day(pg: _Pager, idx: dict, today: dt.date, anchor: dt.date) -> bool:
    p, W = pg.p, pg.W
    its = _day_items(idx, anchor)
    timed = [(span_of(i.x), i) for i in its if i.a is not None and span_of(i.x)]
    timed = [(s[0], s[1], i) for s, i in timed]
    lanes = layout_events([(a, b, i) for a, b, i in timed])
    side = [i for i in its if i.a is None]                                    # no-time tasks
    ev = []
    for a, b, i, lane, n in lanes:
        if lane >= MAX_LANES:
            side.append(i)                                                    # too crowded for the hour grid: keep it on the checklist
        else:
            ev.append((a, b, i, lane, min(n, MAX_LANES)))
    side.sort(key=lambda i: (i.a is None, i.a or 0))
    h0 = min([6] + [a // 60 for a, _b, _i, _l, _n in ev])
    h1 = max([23] + [math.ceil(b / 60) for _a, b, _i, _l, _n in ev])
    top, bottom = pg.top, pg.bottom
    sx0, sx1 = W - M - 340.0, W - M                                           # the schedule column (start side)
    px0, px1 = M, sx0 - 16                                                    # the side panel
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # ---- hourly schedule
    _text(p, QRectF(sx0, top, sx1 - sx0, 16), "برنامهٔ ساعتی", _f(9.5, True), INK)
    gy = top + 20
    lab_w = 36.0
    gx0, gx1 = sx0, sx1 - lab_w
    rh = (bottom - gy) / (h1 - h0)
    if jalali.weekday_index(anchor) == 6:
        p.fillRect(QRectF(gx0, gy, gx1 - gx0, bottom - gy), QColor(SHADE))
    for h in range(h0, h1 + 1):
        y = gy + (h - h0) * rh
        _line(p, gx0, y, gx1, y, GRID, 0.5)
        _text(p, QRectF(gx1 + 4, y - 7, lab_w - 4, 14), fa(f"{h % 24:02d}:00"), _f(7.5), MUTED)
        if h < h1:
            _line(p, gx0, y + rh / 2, gx1, y + rh / 2, HAIR, 0.4, True)
    _line(p, gx0, gy, gx0, bottom, INK, 0.8)
    _line(p, gx1, gy, gx1, bottom, INK, 0.8)
    _line(p, gx0, gy, gx1, gy, INK, 0.8)
    _line(p, gx0, bottom, gx1, bottom, INK, 0.8)
    inner = gx1 - gx0 - 6
    for a, b, i, lane, n in ev:
        y0 = gy + (max(a, h0 * 60) - h0 * 60) / 60 * rh
        y1 = gy + (min(b, h1 * 60) - h0 * 60) / 60 * rh
        lw = inner / n
        bx = gx1 - 3 - (lane + 1) * lw
        r = QRectF(bx + 1, y0 + 0.8, lw - 2, max(9.0, y1 - y0 - 1.6))
        p.setPen(QPen(QColor(INK), 0.8))
        p.setBrush(QColor("#ffffff" if not i.done else "#f6f6f8"))
        p.drawRoundedRect(r, 2, 2)
        _dot(p, QPointF(r.right() - 6, r.top() + 6.5), i.pr, i.done, 2.2, not i.first)
        f = _f(8, False, i.done)
        tw = r.width() - 16
        col = MUTED if i.done else INK
        if r.height() >= 27:
            _text(p, QRectF(r.left() + 3, r.top() + 1, tw, 11), i.span_text or i.time, _f(7, True), MUTED if i.done else INK)
            room = max(1, int((r.height() - 14) / 10.5))
            for k, ln in enumerate(_wrap(p, i.title, f, r.width() - 8, room)):
                _text(p, QRectF(r.left() + 3, r.top() + 12 + k * 10.5, r.width() - 8, 10.5), ln, f, col)
        else:
            s = (f"{i.time} " if i.time else "") + i.title
            _text(p, QRectF(r.left() + 3, r.top(), tw, r.height()), _elide(p, s, _f(7.5, False, i.done), tw), _f(7.5, False, i.done), col)
    # ---- the checklist + notes
    _text(p, QRectF(px0, top, px1 - px0, 16), "بدون ساعت / تمام‌روز", _f(9.5, True), INK)
    _line(p, px0, top + 18, px1, top + 18, INK, 0.8)
    unit = 10.5
    ly0 = top + 22
    list_h = (bottom - ly0) * 0.56
    rows = int(list_h / unit)
    wlines = []
    for i in side:
        f = _f(8, False, i.done)
        s = (f"{i.span_text or i.time}  " if i.time else "") + i.title
        wlines.append(_wrap(p, s, f, px1 - px0 - 36, 2))
    k = _fit([len(l) + 1 for l in wlines], rows, 2)
    row = 0
    for i, ls in zip(side[:k], wlines[:k]):
        h = len(ls) + 1
        _box(p, QRectF(px1 - 9, ly0 + row * unit + 3.5, 8, 8), i.done)
        _dot(p, QPointF(px1 - 17, ly0 + row * unit + 7.5), i.pr, i.done, 2.2, not i.first)
        for n_, ln in enumerate(ls):
            _text(p, QRectF(px0 + 4, ly0 + (row + n_) * unit, px1 - px0 - 32, unit + 1), ln, _f(8, False, i.done), MUTED if i.done else INK)
        _line(p, px0, ly0 + (row + h) * unit, px1, ly0 + (row + h) * unit, HAIR, 0.5)
        row += h
    overflow = k < len(side)
    if overflow:
        _text(p, QRectF(px0 + 4, ly0 + row * unit, px1 - px0 - 8, unit * 2), _more(len(side) - k) + "؛ فهرست کامل در صفحهٔ بعد", _f(7.5, True), INK)
    else:
        while row + 2 <= rows:                                                  # blank lines to write on
            _box(p, QRectF(px1 - 9, ly0 + row * unit + 3.5, 8, 8), False)
            _line(p, px0, ly0 + (row + 2) * unit, px1, ly0 + (row + 2) * unit, HAIR, 0.5)
            row += 2
    ny = ly0 + list_h + 14
    _text(p, QRectF(px0, ny, px1 - px0, 16), "یادداشت‌ها", _f(9.5, True), INK)
    _line(p, px0, ny + 18, px1, ny + 18, INK, 0.8)
    y = ny + 18 + 21
    while y < bottom - 4:
        _line(p, px0, y, px1, y, HAIR, 0.5)
        y += 21
    p.restore()
    return overflow


# ------------------------------------------------------------------------------------------------ the full list ---
def _full_list(pg: _Pager, idx: dict, dates: list[dt.date], kind: str) -> None:
    """Every task of the range, once, grouped by its first day in the range, in two columns over as many pages as it takes."""
    p, W = pg.p, pg.W
    seen: set[int] = set()
    groups: list[tuple[dt.date, list[_It]]] = []
    for d in dates:
        its = []
        for it in _day_items(idx, d):
            if id(it.x) not in seen:
                seen.add(id(it.x))
                its.append(it)
        if its:
            groups.append((d, its))
    if not groups:
        return
    pg.next_page(kind)
    gap = 22.0
    cw = (W - 2 * M - gap) / 2
    pitch = 11.5
    col, y = 0, pg.top

    def colx() -> float:
        return W - M - col * (cw + gap)

    def advance() -> None:
        nonlocal col, y
        col += 1
        y = pg.top
        if col > 1:
            pg.next_page(kind)
            col = 0

    for d, its in groups:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        built = []
        for it in its:
            f = _f(8, False, it.done)
            s = (f"{it.span_text or it.time}  " if it.time and it.first else "") + it.title + (f"  ·  {it.rng}" if it.rng else "")
            built.append((it, f, _wrap(p, s, f, cw - 28, 3)))
        i = 0
        first = True
        while i < len(built):
            head = 22.0 if first else 18.0
            need = head + len(built[i][2]) * pitch + 3
            if y + need > pg.bottom:
                p.restore()
                advance()
                p.save()
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                first = True                                                     # repeat the day heading on the new column
                continue
            x = colx()
            tag = f"{jalali.WEEKDAYS_FA[jalali.weekday_index(d)]} {_dm(d)}"
            if first:
                _text(p, QRectF(x - cw, y, cw, 16), tag + (" (ادامه)" if i else ""), _f(9, True), INK)
                _line(p, x - cw, y + 18, x, y + 18, INK, 0.7)
                y += 22
            it, f, ls = built[i]
            _box(p, QRectF(x - 8, y + 2.2, 7, 7), it.done)
            _dot(p, QPointF(x - 17, y + pitch / 2), it.pr, it.done, 2.1, not it.first)
            for n_, ln in enumerate(ls):
                _text(p, QRectF(x - cw, y + n_ * pitch, cw - 25, pitch), ln, f, MUTED if it.done else INK)
            y += len(ls) * pitch + 3
            first = False
            i += 1
        y += 8
        p.restore()


# ------------------------------------------------------------------------------------------------ entry points ---
def _stats(idx: dict, dates: list[dt.date]) -> str:
    seen: dict[int, bool] = {}
    for d in dates:
        for x in idx.get(d, ()):
            seen[id(x)] = bool(x.get("done"))
    if not seen:
        return "بدون تسک"
    done = sum(seen.values())
    return f"{fa(len(seen))} تسک  ·  {fa(done)} انجام‌شده"


def _render(dev, mode: str, anchor: dt.date, idx: dict, pal: dict, today: dt.date, total: int) -> int:
    size = PORTRAIT if mode == "day" else LANDSCAPE
    if isinstance(dev, QPdfWriter):
        dev.setResolution(RES)
        dev.setTitle("تقویم Aegis Planner")
        dev.setCreator("Aegis Planner")
    elif hasattr(dev, "setDocName"):
        dev.setDocName("Aegis Planner")
    orient = QPageLayout.Orientation.Portrait if mode == "day" else QPageLayout.Orientation.Landscape
    if isinstance(dev, QPdfWriter):
        dev.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), orient, QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter))
    else:
        dev.setPageOrientation(orient)                                        # a real printer keeps the person's paper and margins; the sheet is scaled to fit
    p = QPainter(dev)
    if not p.isActive():
        return 0
    dpi = float(dev.logicalDpiX() or RES)
    sc = min(dev.width() / size[0], dev.height() / size[1])
    p.translate((dev.width() - size[0] * sc) / 2, (dev.height() - size[1] * sc) / 2)
    p.scale(sc, sc)
    p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    letterhead.UNIT[0] = 72.0 / dpi                                           # a font of N pt is N units tall, whatever the dpi
    try:
        dates = range_dates(mode, anchor)
        sub = _stats(idx, dates)
        if mode == "day" and anchor == today:                                 # today's mark for the one view that has no grid cell
            sub = "امروز  ·  " + sub
        pg = _Pager(dev, p, size, pal, KIND[mode], range_title(mode, anchor), sub, today, total)
        over = {"day": _day, "week": _week, "month": _month}[mode](pg, idx, today, anchor)
        if over:
            _full_list(pg, idx, dates, {"day": "فهرست کامل روز", "week": "فهرست کامل هفته", "month": "فهرست کامل ماه"}[mode])
        pg.footer()
        return pg.page
    finally:
        letterhead.UNIT[0] = 1.0
        if p.isActive():
            p.end()                                                           # never let a device die under an active painter


def render_calendar_pdf(target, mode: str, anchor: dt.date, tasks: list[dict], theme_pal: dict | None = None,
                        today: dt.date | None = None) -> int:
    """Render a printout of ``mode`` ("day" | "week" | "month") around ``anchor``; returns the page count (0 = failed).
    ``target`` is a file path (PDF) or any QPagedPaintDevice such as a QPrinter. ``tasks`` are vault task dicts (multi-day and
    recurring instances are ordinary tasks). Two passes: a dry run into memory counts pages so every footer says «x از y»."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    today = today or dt.date.today()
    pal = letterhead.paper_palette(theme_pal)
    idx = _index(tasks)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    dry = QPdfWriter(buf)
    total = _render(dry, mode, anchor, idx, pal, today, 0)
    del dry
    buf.close()
    if not total:
        return 0
    if isinstance(target, str):
        w = QPdfWriter(target)
        try:
            return _render(w, mode, anchor, idx, pal, today, total)
        finally:
            del w
    return _render(target, mode, anchor, idx, pal, today, total)
