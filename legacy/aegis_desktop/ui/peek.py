# SPDX-License-Identifier: GPL-3.0-or-later
"""Space-bar quick look: a small floating card with a task's details next to its row (Esc / Space / click closes it)."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..core import jalali, logic
from ..core.jalali import fa
from .fx_widgets import _fpal
from .theme import AL_R
from .theme import rr


def describe(x: dict) -> list[tuple[str, str]]:
    """(label, value) rows worth showing; empty values are skipped."""
    subs = x.get("subs") or []
    due = jalali.label(x.get("due"), with_year=True)
    if due and x.get("timeFrom"):
        due += "  " + fa(x["timeFrom"]) + (" – " + fa(x["timeTo"]) if x.get("timeTo") else "")
    rows = [("موعد", due), ("دسته", logic.CAT_LABEL.get(x.get("cat"), "")), ("اولویت", logic.PR_LABEL.get(x.get("pr"), "")),
            ("برچسب‌ها", " ".join("#" + t for t in x.get("tags") or [])),
            ("مراحل", f"{fa(sum(1 for s in subs if isinstance(s, dict) and s.get('done')))} از {fa(len(subs))}" if subs else "")]
    notes = " ".join(str(x.get("notes") or "").split())
    if notes:
        rows.append(("یادداشت", notes[:180] + ("…" if len(notes) > 180 else "")))
    return [(a, b) for a, b in rows if b]


class TaskPeek(QWidget):
    W = 340

    def __init__(self, parent: QWidget, task: dict):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.title = str(task.get("title", ""))
        self.done = bool(task.get("done"))
        self.rows = describe(task)
        fm = self.fontMetrics()
        self.line_h = fm.height() + 8
        self.resize(self.W + 24, 62 + len(self.rows) * self.line_h + 24)

    def show_at(self, global_pos: QPoint) -> None:
        self.move(global_pos)
        self.show()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        self.close()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.close()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(12, 8, self.width() - 24, self.height() - 24)
        p.setPen(Qt.PenStyle.NoPen)
        for grow, a in ((6, 10), (4, 16), (2, 26)):
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(body.adjusted(-grow, -grow + 4, grow, grow + 4), rr(12) + grow, rr(12) + grow)
        c = QColor(pal["panel2"])
        c.setAlpha(244)
        p.setBrush(c)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawRoundedRect(body, rr(12), rr(12))
        inner = body.adjusted(16, 12, -16, -10)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setStrikeOut(self.done)
        p.setFont(f)
        p.setPen(QColor(pal["muted"] if self.done else pal["text"]))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 30), AL_R | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(self.title, Qt.TextElideMode.ElideRight, int(inner.width())))
        y = inner.top() + 40
        f2 = QFont(self.font())
        p.setFont(f2)
        fm = p.fontMetrics()
        for lab, val in self.rows:
            p.setPen(QColor(pal["muted"]))
            p.drawText(QRectF(inner.left(), y, inner.width(), self.line_h), AL_R | Qt.AlignmentFlag.AlignVCenter, lab)
            lw = fm.horizontalAdvance(lab) + 14
            p.setPen(QColor(pal["text"]))
            p.drawText(QRectF(inner.left(), y, inner.width() - lw, self.line_h), AL_R | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(val, Qt.TextElideMode.ElideRight, int(inner.width() - lw)))
            y += self.line_h
