# SPDX-License-Identifier: GPL-3.0-or-later
"""Focus mode: the whole window dims away and only the timer and ONE task remain.

The overlay reads its state from ``FocusPage`` (time left, mode, running) and drives it back (play / pause), so the
pomodoro logic stays in one place. The task is the most relevant open one (today's first, then overdue, then the
rest); click the task title to swap to the next one, click the circle to complete it. Esc (or the ×) leaves.
"""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from ..core import logic
from ..core.jalali import fa
from .anim import MOTION
from .fx_widgets import IconToolButton, _fpal
from .premium import RoundButton, mix


def pick_tasks(vault: dict) -> list[dict]:
    """Open tasks in the order they deserve attention (today+timed, today, overdue, upcoming, undated)."""
    today = dt.date.today()

    def key(x):
        d = logic.task_date(x)
        if d == today:
            return (0, str(x.get("timeFrom") or "99:99"), {"high": 0, "normal": 1, "low": 2}.get(x.get("pr"), 1))
        if d is not None and d < today:
            return (1, d.toordinal(), 0)
        if d is not None:
            return (2, d.toordinal(), 0)
        return (3, 0, 0)
    return sorted((x for x in vault.get("tasks", []) if not x.get("done") and not x.get("archived")
                   and not logic.is_event(x)), key=key)


class FocusMode(QWidget):
    def __init__(self, win, host: QWidget):
        super().__init__(host)
        self.win, self.host = win, host
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)
        self.i = 0
        self.task_id: str | None = None
        self._rects: dict[str, QRectF] = {}
        self.page = win.pages["focus"]
        self.play = RoundButton("play", 76, self)
        self.play.clicked.connect(self._toggle)
        self.close_b = IconToolButton("close", "خروج (Esc)", size=40, parent=self)
        self.close_b.clicked.connect(self.leave)
        self.poll = QTimer(self, interval=250)
        self.poll.timeout.connect(self.update_state)
        self.tracker = _Track(self)
        host.installEventFilter(self.tracker)
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.an = QVariantAnimation(self)
        self.an.setDuration(320)
        self.an.valueChanged.connect(lambda v: self.fx.setOpacity(float(v)))
        self.hide()

    def _toggle(self) -> None:
        self.page._toggle()
        self.update_state()

    # ------------------------------------------------------------ lifecycle ---
    def enter(self) -> None:
        self.fit()
        self.retask()
        self.update_state()
        self.show()
        self.raise_()
        self.setFocus()
        self.poll.start()
        self._fade(0.0, 1.0)

    def leave(self) -> None:
        self.poll.stop()
        if self.isVisible():
            self._fade(1.0, 0.0, then=self.hide)

    def _fade(self, a: float, b: float, then=None) -> None:
        self.an.stop()
        try:
            self.an.finished.disconnect()
        except TypeError:
            pass
        if not MOTION[0]:
            self.fx.setOpacity(b)
            if then:
                then()
            return
        self.an.setStartValue(a)
        self.an.setEndValue(b)
        if then:
            self.an.finished.connect(then)
        self.an.start()

    def fit(self) -> None:
        self.setGeometry(self.host.rect())
        w, h = self.width(), self.height()
        self.play.move(w // 2 - self.play.width() // 2, int(h * 0.70))
        self.close_b.move(w - self.close_b.width() - 24, 24)

    # ---------------------------------------------------------------- state ---
    def tasks(self) -> list[dict]:
        return pick_tasks(self.win.store.vault) if self.win.store.is_unlocked else []

    def retask(self, step: int = 0) -> None:
        ts = self.tasks()
        if not ts:
            self.task_id = None
            return
        ids = [t["id"] for t in ts]
        i = ids.index(self.task_id) if self.task_id in ids else 0
        self.task_id = ids[(i + step) % len(ids)]

    def current(self) -> dict | None:
        return next((t for t in self.tasks() if t["id"] == self.task_id), None)

    def update_state(self) -> None:
        if self.task_id and self.current() is None:
            self.retask()
        self.play.icon = "pause" if self.page.running else "play"
        self.play.update()
        self.update()

    # ---------------------------------------------------------------- paint ---
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(pal["bg"])
        bg = mix(bg, QColor("#000000"), 0.55)
        bg.setAlpha(251)
        p.fillRect(self.rect(), bg)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h * 0.34
        R = min(w, h) * 0.20
        pg = self.page
        total = max(1, pg._dur(pg.mode))
        frac = max(0.0, min(1.0, (total - pg.left) / total))
        p.setPen(QPen(QColor(pal["line"]), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - R, cy - R, 2 * R, 2 * R))
        if frac > 0:
            pen = QPen(QColor(pal["accent"] if pg.mode == "work" else pal["ok"]), 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(cx - R, cy - R, 2 * R, 2 * R), 90 * 16, int(-frac * 360 * 16))
        m, s = divmod(max(pg.left, 0), 60)
        f = QFont(self.font())
        f.setPointSizeF(max(28.0, R / 2.6))
        f.setWeight(QFont.Weight.Light)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(cx - R, cy - R * 0.55, 2 * R, R * 0.9), Qt.AlignmentFlag.AlignCenter, fa(f"{m:02d}:{s:02d}"))
        f2 = QFont(self.font())
        f2.setPointSizeF(max(9.0, f2.pointSizeF()))
        p.setFont(f2)
        p.setPen(QColor(pal["muted"]))
        state = ("در حال تمرکز" if pg.running else "آماده‌ای؟") if pg.mode == "work" else ("استراحت" if pg.running else "استراحت کوتاه")
        p.drawText(QRectF(cx - R, cy + R * 0.28, 2 * R, 28), Qt.AlignmentFlag.AlignCenter, state)
        # the one task
        self._rects.clear()
        t = self.current()
        ty = h * 0.58
        if t is not None:
            f3 = QFont(self.font())
            f3.setPointSizeF(f3.pointSizeF() + 3)
            p.setFont(f3)
            fm = p.fontMetrics()
            title = fm.elidedText(t.get("title", ""), Qt.TextElideMode.ElideRight, int(min(w * 0.7, 640)))
            tw = fm.horizontalAdvance(title)
            circ = QRectF(cx + tw / 2 + 14, ty + 3, 22, 22)                    # start edge = right in RTL
            self._rects["done"] = circ.adjusted(-8, -8, 8, 8)
            p.setPen(QPen(QColor(pal["muted"]), 1.6))
            p.drawEllipse(circ)
            p.setPen(QColor(pal["text"]))
            tr = QRectF(cx - tw / 2 - 4, ty, tw + 8, 28)
            self._rects["title"] = tr
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, title)
            p.setFont(f2)
            p.setPen(QColor(pal["muted"]))
            more = len(self.tasks()) - 1
            hint = "روی عنوان بزن تا تسک بعدی" if more > 0 else "تنها تسک باز"
            p.drawText(QRectF(cx - 200, ty + 32, 400, 22), Qt.AlignmentFlag.AlignCenter, hint)
        else:
            p.setFont(f2)
            p.setPen(QColor(pal["muted"]))
            p.drawText(QRectF(cx - 240, ty, 480, 28), Qt.AlignmentFlag.AlignCenter, "تسک بازی نداری — فقط تمرکز کن.")
        p.setPen(QColor(mix(QColor(pal["muted"]), QColor(pal["bg"]), 0.35)))
        p.drawText(QRectF(0, h - 44, w, 24), Qt.AlignmentFlag.AlignCenter, "Esc برای خروج")

    # ---------------------------------------------------------------- input ---
    def mousePressEvent(self, e) -> None:  # noqa: N802
        pt = e.position()
        if self._rects.get("done") and self._rects["done"].contains(pt):
            self.complete()
        elif self._rects.get("title") and self._rects["title"].contains(pt):
            self.retask(1)
            self.update()
        e.accept()

    def complete(self) -> None:
        t = self.current()
        if t is None:
            return
        rec = self.win.snapshot([t["id"]])
        logic.set_done(self.win.store.vault, t, True)
        from . import sfx
        sfx.play("tick")
        self.retask()
        self.win.changed("تسک انجام شد", undo=rec)
        self.update_state()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.leave()
        elif e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._toggle()
        elif e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Right, Qt.Key.Key_Left):
            self.retask(1)
            self.update()
        else:
            super().keyPressEvent(e)
        e.accept()


class _Track(QObject):
    def __init__(self, ov: FocusMode):
        super().__init__(ov)
        self.ov = ov

    def eventFilter(self, o, e) -> bool:  # noqa: N802
        if e.type() == QEvent.Type.Resize and self.ov.isVisible():
            self.ov.fit()
        return False
