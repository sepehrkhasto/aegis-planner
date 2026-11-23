# SPDX-License-Identifier: GPL-3.0-or-later
"""Sticky-note board (welcome-ui StickyNote idea) with accordion folders, plus small helpers:
AccordionSection (animated collapsible block) and VariantPicker (7 note colours).

The board paints every card itself in one pass (no per-card widgets) so hundreds of notes stay fast.
"""
from __future__ import annotations

import datetime as dt
import re

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractButton, QFrame, QMenu, QScrollArea, QVBoxLayout, QWidget)

from ..core import jalali, logic
from ..core.jalali import fa
from .anim import draw_marked, marker_color
from .premium import MARK_RE
from .theme import AL_R
from .theme import rr as _rad
from . import icons
from .theme import PALETTES

# name -> (label, accent, light bg, dark tint)
VARIANTS: dict[str, tuple[str, str, str, str]] = {
    "brand": ("فالکون", "#464c65", "#e0e4eb", "#9fadc7"),
    "green": ("سبز", "#17a565", "#d7f1e2", "#22c55e"),
    "blue": ("آبی", "#0ea5e9", "#d6ecfb", "#38bdf8"),
    "teal": ("فیروزه‌ای", "#0d9488", "#d2f0ec", "#2dd4bf"),
    "pink": ("صورتی", "#db2777", "#fbdbe8", "#f472b6"),
    "orange": ("نارنجی", "#ea580c", "#fde5cc", "#fb923c"),
    "violet": ("بنفش", "#7c3aed", "#e6dcfb", "#a78bfa"),
}
DEFAULT_VARIANT = "brand"


def variant_colors(name: str, pal: dict) -> tuple[str, str, str]:
    """(accent, light card fill, dark-mode tint) for a note colour. 'brand' follows the active theme."""
    if name == "brand":
        light = QColor(pal["soft"])
        return pal["accent"], light.name(), pal["acc_text"] if QColor(pal["bg"]).lightness() < 128 else pal["hi"]
    _l, acc, light, dtint = VARIANTS[name]
    return acc, light, dtint


def variant_of(n: dict) -> str:
    v = n.get("color")
    return v if v in VARIANTS else DEFAULT_VARIANT


def checklist_stats(text: str) -> tuple[int, int]:
    done = total = 0
    for ln in text.split("\n"):
        s = ln.strip().lower()
        if s.startswith("- [x]"):
            done += 1
            total += 1
        elif s.startswith("- [ ]"):
            total += 1
    return done, total


def short_date(iso: str | None) -> str:
    try:
        d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        j = jalali.to_jalali(d.year, d.month, d.day)
        return f"{fa(j[2])} {jalali.MONTHS_FA[j[1] - 1]}"
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ board ---
_MD_STRIP = re.compile(r"(\*\*|__|^#{1,6}\s+)")


def preview_lines(n: dict, count: int) -> list[str]:
    """The first non-empty lines of a note, markdown trimmed (checklist and ==mark== syntax is kept for the painter)."""
    out = []
    for ln in logic.note_text(n).split("\n"):
        if ln.strip():
            out.append(_MD_STRIP.sub("", ln.strip()))
        if len(out) >= count:
            break
    return out


class NotesBoard(QScrollArea):
    """Scrollable gallery. Signals carry note ids. ``mode`` is "grid" (cards with previews and drawing thumbnails) or "list"."""
    selected = pyqtSignal(str)
    opened = pyqtSignal(str)
    color_changed = pyqtSignal(str, str)
    pin_toggled = pyqtSignal(str)
    delete_req = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.canvas = _Canvas(self)
        self.setWidget(self.canvas)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def count(self) -> int:
        return len(self.canvas.notes)

    def set_notes(self, notes: list[dict], cur_id: str | None, theme: str, group: bool = True) -> None:
        self.canvas.set_notes(notes, cur_id, theme, group)

    def set_mode(self, mode: str) -> None:
        if mode in ("grid", "list") and mode != self.canvas.mode:
            self.canvas.mode = mode
            self.canvas._relayout_height()
            self.canvas.update()

    def set_current(self, nid: str | None) -> None:
        self.canvas.cur = nid
        self.canvas.update()

    def clear(self) -> None:
        self.canvas.set_notes([], None, self.canvas.theme, self.canvas.group)

    def has(self, nid: str) -> bool:
        return any(n["id"] == nid for n in self.canvas.notes)


class _Canvas(QWidget):
    GAP, PAD, HEAD_H = 14, 6, 38
    GRID_W, GRID_H = 250, 188
    ROW_H = 68

    def __init__(self, board: NotesBoard):
        super().__init__()
        self.board = board
        self.notes: list[dict] = []
        self.cur: str | None = None
        self.theme = "dark"
        self.group = True
        self.mode = "grid"
        self.collapsed: set[str] = set()
        self._cards: list[tuple[QRectF, dict]] = []
        self._heads: list[tuple[QRectF, str]] = []
        self._hover: str | None = None
        self._thumbs: dict[tuple, QPixmap | None] = {}
        self._lift = QVariantAnimation(self)
        self._lift.setDuration(160)
        self._lift.setStartValue(0.0)
        self._lift.setEndValue(1.0)
        self._lift.valueChanged.connect(lambda _v: self.update())
        self.setMouseTracking(True)

    # data ------------------------------------------------------------------
    def set_notes(self, notes, cur_id, theme, group) -> None:
        self.notes, self.cur, self.theme, self.group = notes, cur_id, theme, group
        self._relayout_height()
        self.update()

    def _sections(self) -> list[tuple[str, str, list[dict]]]:
        if not self.group:
            return [("all", "همه", self.notes)]
        out: list[tuple[str, str, list[dict]]] = []
        pinned = [n for n in self.notes if n.get("pinned")]
        if pinned:
            out.append(("__pinned", "سنجاق‌شده", pinned))
        folders: dict[str, list[dict]] = {}
        for n in self.notes:
            if not n.get("pinned"):
                folders.setdefault(n.get("folder") or "", []).append(n)
        for f in sorted(folders, key=lambda s: (s == "", s)):
            out.append(("f:" + f, f or "بدون پوشه", folders[f]))
        return out

    def _cols(self) -> int:
        if self.mode == "list":
            return 1
        w = max(self.GRID_W, self.width()) - 2 * self.PAD
        return max(1, int((w + self.GAP) // (self.GRID_W + self.GAP)))

    def _cell_h(self) -> int:
        return self.ROW_H if self.mode == "list" else self.GRID_H

    def _gap(self) -> int:
        return 8 if self.mode == "list" else self.GAP

    def _relayout_height(self) -> None:
        cols = self._cols()
        y = self.PAD
        show_heads = self.group
        for key, _t, items in self._sections():
            if show_heads:
                y += self.HEAD_H + 6
            if key not in self.collapsed or not show_heads:
                rows = (len(items) + cols - 1) // cols
                y += rows * (self._cell_h() + self._gap())
            y += 8
        self.setMinimumHeight(y + self.PAD)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._relayout_height()
        super().resizeEvent(e)

    # interaction -------------------------------------------------------------
    def _card_at(self, pos):
        pos = QPointF(pos)                                   # contextMenuEvent hands a QPoint, mouse events a QPointF
        for r, n in self._cards:
            if r.contains(pos):
                return n
        return None

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        n = self._card_at(e.position())
        hid = n["id"] if n else None
        if hid != self._hover:
            self._hover = hid
            if hid:
                self._lift.stop()
                self._lift.start()
            self.setCursor(Qt.CursorShape.PointingHandCursor if (hid or any(r.contains(e.position()) for r, _ in self._heads))
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            return
        for r, key in self._heads:
            if r.contains(e.position()):
                self.collapsed ^= {key}
                self._relayout_height()
                self.update()
                return
        n = self._card_at(e.position())
        if n:
            self.board.selected.emit(n["id"])

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        pass                                                         # one click already opens the note

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        n = self._card_at(e.pos() if hasattr(e, "pos") else e.position())
        if not n:
            return
        from .premium import style_menu
        m = style_menu(QMenu(self))
        m.aboutToHide.connect(m.deleteLater)
        m.addAction(icons.icon("notes", PALETTES[self.theme]["muted"], 16), "باز کردن", lambda: self.board.selected.emit(n["id"]))
        cm = style_menu(m.addMenu("رنگ یادداشت"))
        pal = PALETTES[self.theme]
        for k, (lab, _a, _l, _d) in VARIANTS.items():
            a = cm.addAction(icons_color(variant_colors(k, pal)[0]), lab)
            a.triggered.connect(lambda _=False, k=k, i=n["id"]: self.board.color_changed.emit(i, k))
        m.addAction(icons.icon("pin", pal["muted"], 16), "برداشتن سنجاق" if n.get("pinned") else "سنجاق‌کردن", lambda: self.board.pin_toggled.emit(n["id"]))
        m.addSeparator()
        m.addAction(icons.icon("trash", pal["danger"], 16), "انتقال به سطل زباله", lambda: self.board.delete_req.emit(n["id"]))
        m.exec(e.globalPos())

    # thumbnails --------------------------------------------------------------
    def _thumb(self, n: dict, w: int, h: int, pal: dict) -> QPixmap | None:
        """A picture of the note's first sketch / flowchart (cached until the note changes)."""
        blocks = [b for b in (n.get("blocks") or ()) if isinstance(b, dict) and b.get("t") in ("ink", "flow")]
        if not blocks:
            return None
        key = (n["id"], n.get("updatedAt"), self.theme, w, h)
        if key in self._thumbs:
            return self._thumbs[key]
        from .note_blocks import render_block_pixmap
        pm = render_block_pixmap(blocks[0], w, h, pal)
        if len(self._thumbs) > 80:
            self._thumbs.clear()
        self._thumbs[key] = pm
        return pm

    # painting ----------------------------------------------------------------
    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = PALETTES[self.theme]
        dark = self.theme == "dark"
        W = self.width()
        cols = self._cols()
        gap = self._gap()
        cw = (W - 2 * self.PAD - (cols - 1) * gap) / cols
        ch = self._cell_h()
        self._cards, self._heads = [], []
        y = self.PAD
        vis = self.visibleRegion().boundingRect() if self.isVisible() else self.rect()
        f = QFont(self.font())
        for key, title, items in self._sections():
            collapsed = key in self.collapsed and self.group
            if self.group:
                hr = QRectF(self.PAD, y, W - 2 * self.PAD, self.HEAD_H)
                self._heads.append((hr, key))
                self._header(p, hr, title, len(items), collapsed, pal, f)
                y += self.HEAD_H + 6
            if not collapsed:
                for i, n in enumerate(items):
                    r_, c_ = divmod(i, cols)
                    x = W - self.PAD - (c_ + 1) * cw - c_ * gap
                    rect = QRectF(x, y + r_ * (ch + gap), cw, ch)
                    self._cards.append((rect, n))
                    if rect.bottom() < vis.top() - 24 or rect.top() > vis.bottom() + 24:
                        continue
                    if self.mode == "list":
                        self._row(p, rect, n, pal, dark)
                    else:
                        self._card(p, rect, n, pal, dark)
                rows = (len(items) + cols - 1) // cols
                y += rows * (ch + gap)
            y += 8

    def _header(self, p: QPainter, hr: QRectF, title: str, count: int, collapsed: bool, pal: dict, f: QFont) -> None:
        from .premium import alpha
        fb = QFont(f)
        fb.setBold(True)
        p.setFont(fb)
        p.setPen(QColor(pal["text"]))
        tw = p.fontMetrics().horizontalAdvance(title)
        tr = QRectF(hr.right() - 26 - tw, hr.top(), tw + 4, hr.height())
        p.drawText(tr, AL_R | Qt.AlignmentFlag.AlignVCenter, title)
        cx, cy = hr.right() - 11, hr.center().y()                         # chevron: down when open, start-pointing when closed
        p.setPen(QPen(QColor(pal["muted"]), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if collapsed:
            p.drawLine(QPointF(cx + 2, cy - 4.5), QPointF(cx - 2, cy))
            p.drawLine(QPointF(cx - 2, cy), QPointF(cx + 2, cy + 4.5))
        else:
            p.drawLine(QPointF(cx - 4.5, cy - 2), QPointF(cx, cy + 2))
            p.drawLine(QPointF(cx, cy + 2), QPointF(cx + 4.5, cy - 2))
        p.setFont(f)
        cs = fa(count)
        cwid = p.fontMetrics().horizontalAdvance(cs) + 14
        bx = QRectF(tr.left() - 10 - cwid, hr.center().y() - 10, cwid, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(pal["accent"], 0.13))
        p.drawRoundedRect(bx, 10, 10)
        p.setPen(QColor(pal["acc_text"]))
        p.drawText(bx, Qt.AlignmentFlag.AlignCenter, cs)
        p.setPen(QPen(alpha(pal["line"], 0.9), 1))                              # a hairline continues to the far edge
        p.drawLine(QPointF(hr.left(), cy), QPointF(bx.left() - 12, cy))

    def _palette_for(self, n: dict, pal: dict, dark: bool):
        name = variant_of(n)
        accent, light, dtint = variant_colors(name, pal)
        if dark:
            base = QColor(pal["panel"])
            tint = QColor(dtint)
            fill = QColor(int(base.red() * .93 + tint.red() * .07), int(base.green() * .93 + tint.green() * .07),
                          int(base.blue() * .93 + tint.blue() * .07))
            return fill, QColor(pal["text"]), QColor(pal["muted"]), QColor(dtint)
        return QColor(light).lighter(104), QColor("#1b2233"), QColor("#586179"), QColor(accent)

    def _card(self, p: QPainter, rect: QRectF, n: dict, pal: dict, dark: bool) -> None:
        from .premium import alpha
        fill, txt, sub, acc = self._palette_for(n, pal, dark)
        hover = n["id"] == self._hover
        sel = n["id"] == self.cur
        k = self._lift.currentValue() if (hover and self._lift.state() == QVariantAnimation.State.Running) else (1.0 if hover else 0.0)
        r = rect.translated(0, -3.0 * float(k))
        rad = _rad(14)
        p.setPen(Qt.PenStyle.NoPen)
        for grow, a in ((10, 9), (6, 12), (3, 16)):                            # soft layered shadow
            p.setBrush(QColor(0, 0, 0, int(a * (1.5 if hover else 1.0))))
            p.drawRoundedRect(r.adjusted(-grow * .3, grow * .5, grow * .3, grow * .9), rad + grow * .4, rad + grow * .4)
        p.setBrush(fill)
        p.setPen(QPen(alpha(acc, 0.9) if sel else (alpha(acc, 0.55) if hover else QColor(pal["line"])), 1.6 if sel else 1.0))
        p.drawRoundedRect(r, rad, rad)
        p.setPen(QPen(QColor(255, 255, 255, 26 if dark else 90), 1))                # lit top edge
        p.drawLine(QPointF(r.left() + rad, r.top() + 1), QPointF(r.right() - rad, r.top() + 1))
        p.setPen(Qt.PenStyle.NoPen)                                              # the note's colour: a short bar on the start edge
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(r.right() - 3.5, r.top() + 18, 3.5, 30), 1.75, 1.75)
        fb = QFont(self.font())
        fb.setBold(True)
        fb.setPointSizeF(fb.pointSizeF() + 0.8)
        p.setFont(fb)
        p.setPen(txt)
        title = n.get("title") or "بدون عنوان"
        pin_w = 22 if n.get("pinned") else 0
        tr = QRectF(r.left() + 16 + pin_w, r.top() + 14, r.width() - 36 - pin_w, 26)
        p.drawText(tr, AL_R | Qt.AlignmentFlag.AlignVCenter, p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, int(tr.width())))
        if n.get("pinned"):
            p.drawPixmap(int(r.left() + 14), int(r.top() + 19), icons.pixmap("pin", acc.name(), 15))
        thumb = self._thumb(n, int(r.width() - 28), 62, pal)
        lines = preview_lines(n, 2 if thumb else 3)
        fs = QFont(self.font())
        fs.setPointSizeF(max(8.0, fs.pointSizeF() - 0.6))
        yy = r.top() + 46
        for ln in lines:
            self._preview_line(p, QRectF(r.left() + 16, yy, r.width() - 36, 20), ln, fs, txt, sub, acc, pal)
            yy += 21
        if thumb is not None:
            tr2 = QRectF(r.left() + 14, r.bottom() - 100, r.width() - 28, 62)
            p.setPen(QPen(alpha(pal["line"], 0.9), 1))
            p.setBrush(alpha(pal["bg"], 0.55) if dark else QColor(255, 255, 255, 190))
            p.drawRoundedRect(tr2, _rad(9), _rad(9))
            p.drawPixmap(tr2.toRect().adjusted(1, 1, -1, -1), thumb)
        self._footer(p, r, n, sub, acc, pal)

    def _preview_line(self, p: QPainter, box: QRectF, ln: str, fs: QFont, txt: QColor, sub: QColor, acc: QColor, pal: dict) -> None:
        s = ln
        chk = None
        for pre, mark in (("- [x]", 1), ("- [X]", 1), ("- [ ]", 0)):
            if s.startswith(pre):
                s, chk = s[len(pre):].strip(), mark
                break
        x_right, tw = box.right(), box.width()
        if chk is not None:
            p.setPen(QPen(acc, 1.4))
            p.setBrush(acc if chk else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(x_right - 12, box.top() + 4, 12, 12), 3, 3)
            if chk:
                p.setPen(QPen(QColor("white"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(x_right - 9.2, box.top() + 10), QPointF(x_right - 6.4, box.top() + 12.8))
                p.drawLine(QPointF(x_right - 6.4, box.top() + 12.8), QPointF(x_right - 2.6, box.top() + 7))
            x_right -= 18
            tw -= 18
        ft = QFont(fs)
        ft.setStrikeOut(bool(chk))
        p.setFont(ft)
        needle = ""
        mk = MARK_RE.search(s)
        if mk:
            needle = mk.group(1)
            s = MARK_RE.sub(r"\1", s)
        draw_marked(p, QRectF(box.left(), box.top(), tw, box.height()), s, needle, 1.0, marker_color(pal),
                    QColor(sub if chk else txt), ft)

    def _footer(self, p: QPainter, r: QRectF, n: dict, sub: QColor, acc: QColor, pal: dict) -> None:
        from .premium import alpha
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.2))
        p.setFont(f)
        fm = p.fontMetrics()
        y = r.bottom() - 30
        x = r.right() - 16
        date = short_date(n.get("updatedAt") or n.get("createdAt"))
        w = fm.horizontalAdvance(date) + 4
        p.setPen(sub)
        p.drawText(QRectF(x - w, y, w, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, date)
        x -= w + 12
        inks, flows = logic.note_block_counts(n)
        for icon, cnt in (("pen", inks), ("flow", flows)):
            if cnt:
                cs = fa(cnt)
                cw = fm.horizontalAdvance(cs)
                p.drawPixmap(int(x - 14), int(y + 3), icons.pixmap(icon, sub.name(), 14))
                p.drawText(QRectF(x - 14 - cw - 3, y, cw + 2, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, cs)
                x -= 14 + cw + 14
        done, total = checklist_stats(logic.note_text(n))
        if total:
            label = f"{fa(done)}/{fa(total)}"
            pw = fm.horizontalAdvance(label) + 16
            pr = QRectF(r.left() + 14, y + 1, pw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(acc, 0.16))
            p.drawRoundedRect(pr, 9, 9)
            p.setPen(acc)
            p.drawText(pr, Qt.AlignmentFlag.AlignCenter, label)

    def _row(self, p: QPainter, rect: QRectF, n: dict, pal: dict, dark: bool) -> None:
        from .premium import alpha
        fill, txt, sub, acc = self._palette_for(n, pal, dark)
        hover = n["id"] == self._hover
        sel = n["id"] == self.cur
        rad = _rad(12)
        p.setPen(QPen(alpha(acc, 0.9) if sel else (alpha(acc, 0.5) if hover else QColor(pal["line"])), 1.4 if sel else 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(rect, rad, rad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(acc)
        p.drawRoundedRect(QRectF(rect.right() - 4, rect.top() + 14, 4, rect.height() - 28), 2, 2)
        fb = QFont(self.font())
        fb.setBold(True)
        p.setFont(fb)
        p.setPen(txt)
        left_w = 210
        title = n.get("title") or "بدون عنوان"
        pin_w = 22 if n.get("pinned") else 0
        tr = QRectF(rect.left() + left_w, rect.top() + 10, rect.width() - left_w - 28 - pin_w, 24)
        p.drawText(tr, AL_R | Qt.AlignmentFlag.AlignVCenter, p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, int(tr.width())))
        if n.get("pinned"):
            p.drawPixmap(int(rect.right() - 44), int(rect.top() + 14), icons.pixmap("pin", acc.name(), 15))
        fs = QFont(self.font())
        fs.setPointSizeF(max(8.0, fs.pointSizeF() - 0.6))
        ln = (preview_lines(n, 1) or [""])[0]
        self._preview_line(p, QRectF(rect.left() + left_w, rect.top() + 36, rect.width() - left_w - 28, 20), ln, fs, txt, sub, acc, pal)
        sub_r = QRectF(rect.left(), rect.top(), left_w - 16, rect.height())
        self._footer_row(p, sub_r, n, sub, acc)

    def _footer_row(self, p: QPainter, r: QRectF, n: dict, sub: QColor, acc: QColor) -> None:
        from .premium import alpha
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.2))
        p.setFont(f)
        fm = p.fontMetrics()
        y = r.center().y() - 10
        x = r.right()
        date = short_date(n.get("updatedAt") or n.get("createdAt"))
        w = fm.horizontalAdvance(date) + 4
        p.setPen(sub)
        p.drawText(QRectF(x - w, y, w, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, date)
        x -= w + 12
        inks, flows = logic.note_block_counts(n)
        for icon, cnt in (("pen", inks), ("flow", flows)):
            if cnt:
                cs = fa(cnt)
                cw = fm.horizontalAdvance(cs)
                p.drawPixmap(int(x - 14), int(y + 3), icons.pixmap(icon, sub.name(), 14))
                p.drawText(QRectF(x - 14 - cw - 3, y, cw + 2, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, cs)
                x -= 14 + cw + 14
        done, total = checklist_stats(logic.note_text(n))
        if total and x - 60 > r.left():
            label = f"{fa(done)}/{fa(total)}"
            pw = fm.horizontalAdvance(label) + 16
            pr = QRectF(x - pw, y + 1, pw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(acc, 0.16))
            p.drawRoundedRect(pr, 9, 9)
            p.setPen(acc)
            p.drawText(pr, Qt.AlignmentFlag.AlignCenter, label)


def icons_color(hexcol: str):
    from PyQt6.QtGui import QIcon, QPixmap
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(hexcol))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 12, 12)
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------- helpers ---
class VariantPicker(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, value: str = DEFAULT_VARIANT):
        super().__init__()
        self.value = value
        self.setFixedHeight(34)
        self.setMouseTracking(True)
        self.setMinimumWidth(7 * 30)
        self._hover = -1
        self.theme = "dark"

    def set_value(self, v: str) -> None:
        self.value = v if v in VARIANTS else DEFAULT_VARIANT
        self.update()

    def _rects(self):
        keys = list(VARIANTS)
        x = self.width() - 4
        return [(k, QRectF(x - (i + 1) * 30 + 2, 4, 26, 26)) for i, k in enumerate(keys)]

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = next((i for i, (_k, r) in enumerate(self._rects()) if r.contains(e.position())), -1)
        if h != self._hover:
            self._hover = h
            self.update()
            if h >= 0:
                self.setToolTip(VARIANTS[self._rects()[h][0]][0])

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        for k, r in self._rects():
            if r.contains(e.position()):
                self.value = k
                self.update()
                self.changed.emit(k)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, (k, r) in enumerate(self._rects()):
            acc = QColor(variant_colors(k, PALETTES[self.theme])[0])
            rr = r.adjusted(-2, -2, 2, 2) if i == self._hover else r
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(acc)
            p.drawRoundedRect(rr, _rad(8), _rad(8))
            if k == self.value:
                p.setPen(QPen(QColor("white"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                c = rr.center()
                p.drawLine(QPointF(c.x() - 4.5, c.y()), QPointF(c.x() - 1.2, c.y() + 3.5))
                p.drawLine(QPointF(c.x() - 1.2, c.y() + 3.5), QPointF(c.x() + 5, c.y() - 3.5))


class _AccHeader(QAbstractButton):
    def __init__(self, text: str):
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.theme = "dark"

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 38)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES[self.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        cx, cy = self.width() - 18, self.height() / 2
        p.setPen(QPen(QColor(pal["acc_text"] if on else pal["muted"]), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
        if not on:
            p.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 5))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["acc_text"] if on else pal["text"]))
        p.drawText(QRectF(8, 0, self.width() - 40, self.height()), AL_R | Qt.AlignmentFlag.AlignVCenter, self.text())


class AccordionSection(QFrame):
    """Bordered collapsible block (Preline/HS accordion style): +/− header, animated height."""

    def __init__(self, title: str, content: QWidget, expanded: bool = True):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(0)
        self.head = _AccHeader(title)
        self.body = content
        lay.addWidget(self.head)
        lay.addWidget(self.body)
        self._anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.finished.connect(self._done)
        self.head.toggled.connect(self._toggle)
        self.head.setChecked(expanded)
        if not expanded:
            self.body.setMaximumHeight(0)
            self.body.hide()

    def set_theme(self, t: str) -> None:
        self.head.theme = t
        self.head.update()

    def _toggle(self, on: bool) -> None:
        self._anim.stop()
        h = max(self.body.sizeHint().height(), 40)
        if on:
            self.body.show()
            self._anim.setStartValue(self.body.maximumHeight() if self.body.maximumHeight() < 16000 else 0)
            self._anim.setEndValue(h)
        else:
            self._anim.setStartValue(self.body.height())
            self._anim.setEndValue(0)
        self._anim.start()

    def _done(self) -> None:
        if self.head.isChecked():
            self.body.setMaximumHeight(16777215)
        else:
            self.body.hide()


class PaperFrame(QWidget):
    """The page the note is written on: a quiet rounded surface (hairline, lit top edge, soft shadow) around the editor column.
    ``set_look`` keeps the old signature; the colour passed is only used for a faint tint of the shadow now."""
    OFF = 0

    def __init__(self, child: QWidget, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(child)
        self.child = child
        self.shadow = QColor(0, 0, 0, 40)
        self.radius = 14
        self.fill: QColor | None = None
        self.edge: QColor | None = None

    def set_look(self, shadow: QColor, radius: int, fill: QColor | None = None, edge: QColor | None = None) -> None:
        self.shadow, self.radius, self.fill, self.edge = shadow, max(10, radius + 6), fill, edge
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from .fx_widgets import _fpal
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(self.fill or QColor(pal["panel"]))
        p.setPen(QPen(self.edge or QColor(pal["line"]), 1))
        p.drawRoundedRect(r, self.radius, self.radius)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawLine(QPointF(r.left() + self.radius, r.top() + 1), QPointF(r.right() - self.radius, r.top() + 1))
