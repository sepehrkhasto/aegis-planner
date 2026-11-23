# SPDX-License-Identifier: GPL-3.0-or-later
"""Taking one note out of the app: a PDF (A4, letterhead, drawings in vector), a PNG (one tall image) or Markdown
(the text plus every sketch / flowchart saved as a PNG beside it).

One layout routine serves both the paged PDF and the continuous PNG; everything is painted with QPainter on the
ink-on-paper palette so the output prints well."""
from __future__ import annotations

import datetime as dt
import html
import os
import re

from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument, QTextOption)
from PyQt6.QtWidgets import QFileDialog

from ..core import logic
from ..core.jalali import fa
from . import letterhead
from .letterhead import FOOT_H, HEAD_H, MARGIN, PAGE_H, PAGE_W
from .note_blocks import FlowCanvas, InkCanvas, W_UNITS, PRINT_PAL

BODY_PT = 11.0
MAX_PAGES = 200
_B = re.compile(r"\*\*(.+?)\*\*")
_I = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_U = re.compile(r"__(.+?)__")
_M = re.compile(r"==(.+?)==")


def md_html(line: str) -> str:
    """One line of the note's light markup as a small HTML fragment (headings, check boxes, bold, italic, underline, mark)."""
    s = html.escape(line)
    size = None
    m = re.match(r"^(#{1,3})\s+(.*)$", s)
    if m:
        size, s = {1: 160, 2: 135, 3: 118}[len(m.group(1))], m.group(2)
        s = f"<b>{s}</b>"
    s = re.sub(r"^(\s*)- \[( |x|X)\]\s?", lambda k: k.group(1) + ("☑ " if k.group(2) != " " else "☐ "), s)
    s = re.sub(r"^(\s*)[-*]\s+", lambda k: k.group(1) + "• ", s)
    s = _B.sub(r"<b>\1</b>", s)
    s = _U.sub(r"<u>\1</u>", s)
    s = _M.sub(r'<span style="background-color:#ffe98a">\1</span>', s)
    s = _I.sub(r"<i>\1</i>", s)
    s = s or "&nbsp;"
    return f'<p style="margin:0 0 2px 0;{f"font-size:{size}%;" if size else ""}">{s}</p>'


class _Sheet:
    """Cursor over a stack of pages (``page_h`` set) or one endless page (``page_h`` None)."""

    def __init__(self, p: QPainter, pal: dict, width: float, page_h: float | None, top: float, bottom: float, newpage=None):
        self.p, self.pal, self.w = p, pal, width
        self.page_h, self.top, self.bottom = page_h, top, bottom
        self.y = top
        self.page = 1
        self.newpage = newpage

    def room(self) -> float:
        return float("inf") if self.page_h is None else self.page_h - self.bottom - self.y

    def need(self, h: float) -> None:
        if self.page_h is not None and h > self.room() and self.y > self.top + 1 and self.page < MAX_PAGES:
            self.break_page()

    def break_page(self) -> None:
        if self.newpage:
            self.newpage()
        self.page += 1
        self.y = 40.0

    def text(self, txt: str, x0: float, width: float) -> None:
        p = self.p
        for para in txt.split("\n"):
            doc = QTextDocument()
            f = QFont(p.font())
            f.setPointSizeF(BODY_PT * letterhead.UNIT[0] * 1.0)
            doc.setDefaultFont(f)
            op = QTextOption()
            op.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
            op.setAlignment(Qt.AlignmentFlag.AlignRight)
            op.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(op)
            doc.setDocumentMargin(0)
            doc.setDefaultStyleSheet(f"body{{color:{self.pal['text']};}}")
            doc.setHtml(f"<body>{md_html(para)}</body>")
            doc.setTextWidth(width)
            h = doc.size().height()
            if h > self.page_h - self.top - self.bottom if self.page_h else False:      # one gigantic paragraph: slice it
                done = 0.0
                while done < h:
                    self.need(40)
                    avail = max(30.0, self.room())
                    p.save()
                    p.translate(x0, self.y - done)
                    p.setClipRect(QRectF(0, done, width, avail))
                    doc.drawContents(p)
                    p.restore()
                    done += avail
                    self.y += avail
                    if done < h:
                        self.break_page()
                continue
            self.need(h)
            p.save()
            p.translate(x0, self.y)
            doc.drawContents(p)
            p.restore()
            self.y += h + 2


def _flow_height(fc: FlowCanvas, width: float) -> float:
    b = fc.bounds().adjusted(-16, -16, 16, 16)
    return b.height() * min(1.0, width / b.width())


def _block_height(b: dict, width: float) -> float:
    if b.get("t") == "ink":
        return InkCanvas(b).h * width / W_UNITS
    if b.get("t") == "flow":
        fc = FlowCanvas(b)
        return 0.0 if fc.is_empty() else _flow_height(fc, width)
    return 0.0


def draw_block(p: QPainter, b: dict, rect: QRectF, pal: dict) -> float:
    """Paint one drawing block into ``rect`` (width decides the scale); returns the height used."""
    if b.get("t") == "ink":
        c = InkCanvas(b)
        if c.is_empty():
            return 0.0
        return c.render(p, rect, pal)
    if b.get("t") == "flow":
        c = FlowCanvas(b)
        return c.render(p, rect, pal)
    return 0.0


def _layout(sh: _Sheet, note: dict, x0: float, width: float) -> None:
    p, pal = sh.p, sh.pal
    title = (note.get("title") or "").strip() or "بدون عنوان"
    f = QFont(p.font())
    f.setBold(True)
    f.setPointSizeF(19 * letterhead.UNIT[0])
    p.setFont(f)
    p.setPen(QColor(pal["text"]))
    fm_h = p.fontMetrics().height() * 1.6
    sh.need(fm_h)
    p.drawText(QRectF(x0, sh.y, width, fm_h), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), title)
    sh.y += fm_h + 2
    meta = []
    if note.get("folder"):
        meta.append(f"پوشه: {note['folder']}")
    for k, lab in (("createdAt", "ساخته‌شده"), ("updatedAt", "ویرایش")):
        v = note.get(k)
        if v:
            try:
                d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone()
                from ..core import jalali
                j = jalali.to_jalali(d.year, d.month, d.day)
                meta.append(f"{lab}: {fa(j[0])}/{fa(j[1])}/{fa(j[2])}")
            except Exception:  # noqa: BLE001
                pass
    if meta:
        f.setBold(False)
        f.setPointSizeF(9 * letterhead.UNIT[0])
        p.setFont(f)
        p.setPen(QColor(pal["muted"]))
        h = p.fontMetrics().height() * 1.5
        p.drawText(QRectF(x0, sh.y, width, h), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "   ·   ".join(meta))
        sh.y += h + 10
    p.setFont(QFont(p.font().family()))
    first = logic.note_text(note)
    if first.strip():
        sh.text(first, x0, width)
        sh.y += 8
    for b in note.get("blocks") or ():
        if not isinstance(b, dict):
            continue
        if b.get("t") == "text":
            if str(b.get("text") or "").strip():
                sh.text(str(b["text"]), x0, width)
                sh.y += 8
        elif b.get("t") in ("ink", "flow"):
            h = _block_height(b, width)
            if h <= 0:
                continue
            if sh.page_h is not None:
                maxh = sh.page_h - sh.top - sh.bottom
                w = width
                if h > maxh:                                  # taller than a page: shrink to fit
                    w = width * maxh / h
                    h = maxh
                sh.need(h)
                draw_block(p, b, QRectF(x0 + (width - w) / 2, sh.y, w, h), pal)
            else:
                draw_block(p, b, QRectF(x0, sh.y, width, h), pal)
            sh.y += h + 14


def _pdf_pass(target, note: dict, pal: dict, total: int) -> int:
    w = QPdfWriter(target)
    w.setResolution(144)
    w.setTitle((note.get("title") or "یادداشت") + " — Aegis Planner")
    w.setCreator("Aegis Planner")
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                                QPageLayout.Unit.Millimeter))
    p = QPainter(w)
    if not p.isActive():
        return 0
    dpi = float(w.logicalDpiX() or 144)
    sc = min(w.width() / PAGE_W, w.height() / PAGE_H)
    p.translate((w.width() - PAGE_W * sc) / 2, (w.height() - PAGE_H * sc) / 2)
    p.scale(sc, sc)
    p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    letterhead.UNIT[0] = 72.0 / dpi
    pages = 1
    try:
        letterhead.paint_letterhead(p, pal, "یادداشت", "")
        sh = _Sheet(p, pal, PAGE_W - 2 * MARGIN, PAGE_H, HEAD_H + 8, FOOT_H + 14, None)

        def newpage():
            nonlocal pages
            letterhead.paint_footer(p, pal, pages, total or pages, fa)
            w.newPage()
            pages += 1
        sh.newpage = newpage
        _layout(sh, note, MARGIN, PAGE_W - 2 * MARGIN)
        letterhead.paint_footer(p, pal, pages, total or pages, fa)
    finally:
        letterhead.UNIT[0] = 1.0
        if p.isActive():
            p.end()
    return pages


def render_note_pdf(target: str, note: dict, theme_pal: dict | None = None) -> int:
    """Write ``note`` as an A4 PDF; returns the page count (0 = failed). A dry run first so every footer says «x از y»."""
    pal = letterhead.paper_palette(theme_pal)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    total = _pdf_pass(buf, note, pal, 0)
    buf.close()
    if not total:
        return 0
    return _pdf_pass(target, note, pal, total)


def render_note_image(note: dict, width: int = 1100) -> QImage:
    """The whole note as one tall picture (white page, ink colours)."""
    pal = dict(PRINT_PAL)
    pad = 44.0
    cw = width - 2 * pad
    probe = QImage(10, 10, QImage.Format.Format_ARGB32)
    height = 0.0
    for dry in (True, False):
        img = probe if dry else QImage(width, int(height + 2 * pad), QImage.Format.Format_ARGB32)
        if not dry:
            img.fill(QColor("#ffffff"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        f = QFont(p.font())
        f.setPixelSize(22)
        p.setFont(f)
        letterhead.UNIT[0] = 22 / BODY_PT / 1.333                       # BODY_PT * UNIT == ~22 px text
        try:
            sh = _Sheet(p, pal, cw, None, pad, 0, None)
            _layout(sh, note, pad, cw)
            height = sh.y - pad
        finally:
            letterhead.UNIT[0] = 1.0
            p.end()
    return img


def note_markdown(note: dict, image_dir: str | None = None, image_prefix: str = "") -> str:
    """Markdown for one note. When ``image_dir`` is given, every sketch / flowchart is written there as a PNG and linked."""
    out = []
    title = (note.get("title") or "").strip() or "بدون عنوان"
    out.append(f"# {title}")
    if note.get("folder"):
        out.append(f"*پوشه: {note['folder']}*")
    first = logic.note_text(note)
    if first.strip():
        out.append(first)
    n = 0
    for b in note.get("blocks") or ():
        if not isinstance(b, dict):
            continue
        if b.get("t") == "text":
            if str(b.get("text") or "").strip():
                out.append(str(b["text"]))
        elif b.get("t") in ("ink", "flow"):
            n += 1
            label = "طراحی دستی" if b["t"] == "ink" else "فلوچارت"
            if image_dir is None:
                out.append(f"*[{label}]*")
                continue
            h = _block_height(b, 900.0)
            if h <= 0:
                continue
            os.makedirs(image_dir, exist_ok=True)
            img = QImage(1800, int(h * 2) + 4, QImage.Format.Format_ARGB32)
            img.fill(QColor("#ffffff"))
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(2, 2)
            draw_block(p, b, QRectF(0, 0, 900, h), dict(PRINT_PAL))
            p.end()
            name = f"{'sketch' if b['t'] == 'ink' else 'flowchart'}-{n}.png"
            img.save(os.path.join(image_dir, name))
            out.append(f"![{label} {n}]({image_prefix}{name})")
    return "\n\n".join(out) + "\n"


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip()[:60] or "note"


def export_note(page, note: dict, kind: str, path: str | None = None) -> str | None:
    """Ask for a destination (unless ``path`` is given), write ``note`` as pdf / png / md, and return the written path."""
    base = _safe(note.get("title") or "note")
    ext = {"pdf": "pdf", "png": "png", "md": "md"}[kind]
    if path is None:
        filt = {"pdf": "PDF (*.pdf)", "png": "PNG (*.png)", "md": "Markdown (*.md)"}[kind]
        path, _ = QFileDialog.getSaveFileName(page, "ذخیره‌ی خروجی", f"{base}.{ext}", filt)
        if not path:
            return None
    ok = True
    if kind == "pdf":
        from .theme import PALETTES
        ok = render_note_pdf(path, note, PALETTES.get(getattr(page.ctx, "theme", ""), None)) > 0
    elif kind == "png":
        ok = render_note_image(note).save(path)
    else:
        stem = os.path.splitext(os.path.basename(path))[0]
        folder = os.path.join(os.path.dirname(path), f"{stem}_files")
        txt = note_markdown(note, folder, f"{stem}_files/")
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt)
    if ok:
        try:
            page.ctx.status_lb.setText("خروجی یادداشت ذخیره شد")
        except AttributeError:
            pass
        return path
    return None
