# SPDX-License-Identifier: GPL-3.0-or-later
"""The «now» band on the Today page: the one task that deserves attention, a start-focus button and the day's progress."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..core import jalali, logic
from ..core.jalali import fa
from .theme import PALETTES
from .widgets import button, label


def _pal(w: QWidget) -> dict:
    return PALETTES.get(getattr(w.window(), "theme", "dark")) or next(iter(PALETTES.values()))


def pick_now(vault: dict) -> dict | None:
    """The open task to do right now: today's first (timed ones by clock), then the oldest overdue. Never a future task."""
    import datetime as dt
    from .focusmode import pick_tasks
    today = dt.date.today()
    for x in pick_tasks(vault):
        d = logic.task_date(x)
        if d is not None and d <= today:
            return x
    return None


class DayBar(QWidget):
    """Thin rounded progress track with a caption above it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frac = 0.0
        self.text = ""
        self.setFixedWidth(190)
        self.setFixedHeight(42)

    def set_progress(self, done: int, total: int) -> None:
        self.frac = (done / total) if total else 0.0
        self.text = f"{fa(done)} از {fa(total)} امروز انجام شد" if total else "امروز برنامه‌ای نیست"
        self.setAccessibleName(self.text)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(190, 42)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _pal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(0, 0, self.width(), 22), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading), self.text)
        r = QRectF(0, 28, self.width(), 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(r, 3, 3)
        if self.frac > 0:
            w = max(6.0, r.width() * self.frac)
            fr = QRectF(r.right() - w, r.top(), w, r.height()) if self.isRightToLeft() else QRectF(r.left(), r.top(), w, r.height())
            p.setBrush(QColor(pal["accent"]))
            p.drawRoundedRect(fr, 3, 3)
        p.end()


class NowBand(QFrame):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("Card")
        self.tid: str | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 16, 14)
        lay.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.cap = label("الان", "Muted")
        self.title = label("", "H2")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)     # long titles elide, never widen the band
        self.meta = label("", "Muted")
        for w in (self.cap, self.title, self.meta):
            col.addWidget(w)
        lay.addLayout(col, 1)
        self.bar = DayBar()
        lay.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.b_done = button("انجام شد", slot=self._done)
        self.b_start = button("شروع تمرکز", "Primary", self._start)
        self.b_add = button("＋ یک کار اضافه کن", "Primary", lambda: ctx.new_task(jalali.today_jalali()))
        for b in (self.b_done, self.b_start, self.b_add):
            b.setFixedHeight(38)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        self._full = ""

    def set_state(self, vault: dict, done: int, total: int) -> None:
        x = pick_now(vault)
        self.tid = x["id"] if x else None
        self.bar.set_progress(done, total)
        self.b_done.setVisible(x is not None)
        self.b_start.setVisible(x is not None)
        self.b_add.setVisible(x is None)
        if x is None:
            self._full = "همه‌چیز انجام شده" if total and done >= total else "کاری برای همین حالا نیست"
            self.meta.setText("یک کار تازه اضافه کن یا از تقویم برنامه‌ریزی کن." if not total else "امروز را با آرامش ببند.")
            self.cap.setText("الان")
        else:
            self._full = x.get("title", "")
            bits = []
            if x.get("timeFrom"):
                bits.append("ساعت " + fa(x["timeFrom"]) + (f"–{fa(x['timeTo'])}" if x.get("timeTo") else ""))
            d = logic.task_date(x)
            import datetime as dt
            if d is not None and d < dt.date.today():
                bits.append("عقب‌افتاده")
            bits.append(logic.CAT_LABEL.get(x.get("cat"), ""))
            self.meta.setText("  ·  ".join(b for b in bits if b))
            self.cap.setText("کار بعدی برای تمرکز")
        self._elide()

    def _elide(self) -> None:
        w = max(120, self.title.width())
        self.title.setText(self.title.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, w))
        self.title.setToolTip(self._full)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._elide()

    def _done(self) -> None:
        x = next((t for t in self.ctx.store.vault["tasks"] if t["id"] == self.tid), None)
        if x:
            logic.set_done(self.ctx.store.vault, x, True)
            self.ctx.changed()

    def _start(self) -> None:
        if self.tid:
            self.ctx.enter_focus_mode(self.tid, start=True)
