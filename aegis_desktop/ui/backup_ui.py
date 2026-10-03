# SPDX-License-Identifier: GPL-3.0-or-later
"""Encrypted automatic backups: settings building blocks, a status hero and the backup browser dialog."""
from __future__ import annotations

import math

import datetime as dt
import shutil
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractButton, QBoxLayout, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout,
                             QWidget)

from .micro import MotionDialog
from ..core import jalali
from ..core.log import friendly
from ..core.crypto import WrongPassword
from ..core.jalali import fa
from ..core.store import VaultError
from .tokens import DIALOG
from . import dialogs, icons
from .fx_widgets import _Anim, _fpal
from .paginator import Paginator
from .premium import EmptyList, alpha, mix
from .theme import AL_R, rr
from .widgets import PathLabel, button, label

UR = Qt.ItemDataRole.UserRole


# ------------------------------------------------------------- formatting ---
def human_size(n: int) -> str:
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت"):
        if n < 1024 or unit == "گیگابایت":
            return (fa(n) if unit == "بایت" else fa(f"{n:.1f}".rstrip("0").rstrip("."))) + " " + unit
        n /= 1024
    return ""


def jdatetime(t: dt.datetime, with_year: bool = True) -> str:
    return f"{jalali.label(jalali.date_to_due(t.date()), with_year)}، ساعت {fa(t.strftime('%H:%M'))}"


def rel_time(t: dt.datetime, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    s = (now - t).total_seconds()
    if s < 60:
        return "همین حالا"
    if s < 3600:
        return f"{fa(int(s // 60))} دقیقه پیش"
    if t.date() == now.date():
        return f"{fa(int(s // 3600))} ساعت پیش"
    days = (now.date() - t.date()).days
    if days == 1:
        return "دیروز، " + fa(t.strftime("%H:%M"))
    if days < 30:
        return f"{fa(days)} روز پیش"
    return jalali.label(jalali.date_to_due(t.date()), True)


def day_title(t: dt.datetime, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    days = (now.date() - t.date()).days
    if days == 0:
        return "امروز"
    if days == 1:
        return "دیروز"
    return f"{jalali.WEEKDAYS_FA[jalali.weekday_index(t.date())]} {jalali.label(jalali.date_to_due(t.date()), True)}"


# ----------------------------------------------------------------- switch ---
class Switch(QAbstractButton):
    """iOS-style toggle; accent track, white knob, keyboard + focus ring. Knob slides right→left for 'on' (RTL)."""

    def __init__(self, on: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(46, 26)
        spring = QEasingCurve(QEasingCurve.Type.OutBack)
        spring.setOvershoot(1.1)                          # a physical switch: the knob overshoots a hair and settles
        self._t = _Anim(self, 1.0 if on else 0.0, 260, spring)
        self.toggled.connect(lambda v: self._t.to(1.0 if v else 0.0))

    def set_quiet(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._t.set(1.0 if on else 0.0)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(46, 26)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tt = self._t.value
        t = max(0.0, min(1.0, tt))                        # colours never overshoot; only the knob's position does
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = mix(QColor(pal["panel2"]), QColor(pal["line"]), 0.9)
        p.setPen(QPen(mix(QColor(pal["line"]), QColor(pal["accent"]), t), 1))
        p.setBrush(mix(off, QColor(pal["accent"]), t))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        stretch = 5.0 * math.sin(math.pi * t) if 0.0 < t < 1.0 else 0.0     # the knob stretches while it travels
        x = r.right() - 3 - d - tt * (r.width() - 6 - d) - stretch / 2
        dark_bg = QColor(pal["bg"]).lightness() < 128
        knob = mix(mix(QColor(pal["panel"]), QColor(pal["text"]), 0.72) if dark_bg else QColor("#ffffff"), QColor("#ffffff"), t)
        p.setPen(QPen(alpha("#000000", 0.12), 1))
        p.setBrush(knob)
        p.drawRoundedRect(QRectF(x, r.top() + 3, d + stretch, d), d / 2, d / 2)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(pal["accent"]), 1.5))
            p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), self.height() / 2, self.height() / 2)


# ---------------------------------------------------------- setting rows ---
class SettingRow(QWidget):
    """One settings row: the title/description block and its control(s) side by side - until there is no room, and then
    the controls drop under the text. (Two 170 px buttons beside a description made the row 414 px wide, so at the
    smallest window the whole settings page scrolled sideways.)"""

    def __init__(self):
        super().__init__()
        self.setObjectName("SRow")

    def _items(self):
        lay = self.layout()
        return [lay.itemAt(i) for i in range(lay.count())] if lay is not None else []

    def side_by_side_width(self) -> int:
        lay = self.layout()
        items = self._items()
        m = lay.contentsMargins()
        return sum(i.minimumSize().width() for i in items) + lay.spacing() * max(0, len(items) - 1) + m.left() + m.right()

    def stacked_width(self) -> int:
        lay = self.layout()
        m = lay.contentsMargins()
        return max((i.minimumSize().width() for i in self._items()), default=0) + m.left() + m.right()

    def reflow(self) -> None:
        lay = self.layout()
        if lay is None:
            return
        narrow = self.width() < self.side_by_side_width()
        want = QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        if lay.direction() != want:
            lay.setDirection(want)
            for i in self._items()[1:]:                                   # controls: start edge when stacked, centred when beside
                if i.widget() is not None:
                    i.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter if narrow else Qt.AlignmentFlag.AlignVCenter)
            lay.invalidate()

    def resizeEvent(self, e) -> None:  # noqa: N802
        self.reflow()
        super().resizeEvent(e)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.stacked_width(), super().minimumSizeHint().height())


class Section(QFrame):
    """A premium settings card: icon + title + subtitle header, then rows separated by hairlines."""

    def __init__(self, icon: str, title: str, subtitle: str = "", theme_of=None):
        super().__init__()
        self.setObjectName("Card")
        self._icon = icon
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 16, 20, 8)
        self.lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.ic = QLabel()
        self.ic.setFixedSize(36, 36)
        self.ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ic.setObjectName("SectionIcon")
        head.addWidget(self.ic, 0, Qt.AlignmentFlag.AlignTop)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        tl.addWidget(label(title, "H2"))
        if subtitle:
            tl.addWidget(label(subtitle, "Muted", True))
        head.addLayout(tl, 1)
        self.lay.addLayout(head)
        self.lay.addSpacing(10)
        self._rows = 0

    def paint_icon(self, pal: dict) -> None:
        from PyQt6.QtGui import QPixmap
        dpr = self.devicePixelRatioF() or 1.0
        pm = QPixmap(int(36 * dpr), int(36 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["soft"]))
        rad = min(18.0, rr(11))
        p.drawRoundedRect(QRectF(0, 0, 36, 36), rad, rad)
        p.drawPixmap(8, 8, icons.pixmap(self._icon, pal["acc_text"], 20))
        p.end()
        self.ic.setPixmap(pm)

    def add_row(self, title: str, desc: str = "", *controls: QWidget, stretch_control: bool = False) -> QWidget:
        line = QFrame()
        line.setObjectName("Hair")
        line.setFixedHeight(1)
        self.lay.addWidget(line)
        row = SettingRow()
        hl = QBoxLayout(QBoxLayout.Direction.LeftToRight, row)
        hl.setContentsMargins(0, 12, 0, 12)
        hl.setSpacing(16)
        tl = QVBoxLayout()
        tl.setSpacing(2)
        t = label(title, "RowTitle")
        tl.addWidget(t)
        if desc:
            tl.addWidget(label(desc, "Muted", True))
        hl.addLayout(tl, 1)
        for c in controls:
            hl.addWidget(c, 1 if stretch_control else 0, Qt.AlignmentFlag.AlignVCenter)
            if not c.accessibleName():                                  # a screen reader announces the row's title
                c.setAccessibleName(title)
                if desc:
                    c.setAccessibleDescription(desc)
        self.lay.addWidget(row)
        self._rows += 1
        return row

    def add_widget(self, w: QWidget, hair: bool = True) -> None:
        if hair:
            line = QFrame()
            line.setObjectName("Hair")
            line.setFixedHeight(1)
            self.lay.addWidget(line)
        box = QWidget()
        box.setObjectName("SRow")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 12, 0, 12)
        bl.addWidget(w)
        self.lay.addWidget(box)


# ------------------------------------------------------------ status hero ---
class BackupHero(QWidget):
    """Big status banner: health state, last backup, count/size, next run."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state, self.title, self.lines = "ok", "", []
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, state: str, title: str, lines: list[str]) -> None:
        self.state, self.title, self.lines = state, title, lines
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        col = QColor({"ok": pal["ok"], "warn": pal["warn"], "off": pal["muted"], "error": pal["danger"]}[self.state])
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = rr(14)
        p.setPen(QPen(mix(QColor(pal["line"]), col, 0.35), 1))
        p.setBrush(mix(QColor(pal["panel"]), col, 0.07))
        p.drawRoundedRect(r, rad, rad)
        # shield medallion
        c = QRectF(r.right() - 24 - 64, r.center().y() - 32, 64, 64)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(col, 0.10))
        p.drawEllipse(c.adjusted(-6, -6, 6, 6))
        p.setBrush(alpha(col, 0.18))
        p.drawEllipse(c)
        ic = {"ok": "shield", "warn": "backup", "off": "backup", "error": "info"}[self.state]
        p.drawPixmap(int(c.center().x() - 15), int(c.center().y() - 15), icons.pixmap(ic, col.name(), 30))
        tx = QRectF(r.left() + 20, r.top(), c.left() - r.left() - 44, r.height())
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 3.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        n = len(self.lines)
        top = r.center().y() - (26 + 20 * n) / 2
        p.drawText(QRectF(tx.left(), top, tx.width(), 26), AL_R | Qt.AlignmentFlag.AlignVCenter, self.title)
        f2 = QFont(self.font())
        p.setFont(f2)
        for i, ln in enumerate(self.lines):
            p.setPen(QColor(pal["muted"] if i else pal["text"]))
            p.drawText(QRectF(tx.left(), top + 28 + 20 * i, tx.width(), 20), AL_R | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(ln, Qt.TextElideMode.ElideRight, int(tx.width())))


# --------------------------------------------------------- browser dialog ---
class _RowDelegate(QStyledItemDelegate):
    H = 62

    def sizeHint(self, opt, idx):  # noqa: N802
        return QSize(200, self.H if idx.data(UR + 1) != "head" else 34)

    def paint(self, p, opt, idx):  # noqa: D401
        pal = _fpal(opt.widget)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(opt.rect)
        if idx.data(UR + 1) == "head":
            f = QFont(opt.font)
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() - 1)
            p.setFont(f)
            p.setPen(QColor(pal["muted"]))
            p.drawText(r.adjusted(8, 8, -8, 0), AL_R | Qt.AlignmentFlag.AlignVCenter, idx.data(Qt.ItemDataRole.DisplayRole))
            p.restore()
            return
        m = idx.data(UR)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        hov = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        box = r.adjusted(3, 2, -3, -2)
        if sel or hov:
            p.setPen(QPen(QColor(pal["accent"]), 1.2) if sel else Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["soft"]) if sel else alpha(pal["accent"], 0.06))
            p.drawRoundedRect(box, rr(10), rr(10))
        ok = m["valid"]
        col = QColor(pal["ok"] if ok else pal["danger"])
        ic = QRectF(box.right() - 12 - 36, box.center().y() - 18, 36, 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(col, 0.15))
        p.drawRoundedRect(ic, min(rr(10), 18), min(rr(10), 18))
        p.drawPixmap(int(ic.center().x() - 9), int(ic.center().y() - 9), icons.pixmap("shield" if ok else "info", col.name(), 18))
        tx = QRectF(box.left() + 12, box.top() + 9, ic.left() - box.left() - 24, 22)
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        title = fa(m["when"].strftime("%H:%M")) + "  —  " + m["label"]
        p.drawText(tx, AL_R | Qt.AlignmentFlag.AlignVCenter, title)
        f2 = QFont(opt.font)
        f2.setPointSizeF(f2.pointSizeF() - 1)
        p.setFont(f2)
        p.setPen(QColor(pal["muted"]))
        sub = f"{rel_time(m['when'])}  —  {human_size(m['size'])}" + ("" if ok else "  —  فایل خراب")
        p.drawText(QRectF(tx.left(), tx.bottom() + 1, tx.width(), 20), AL_R | Qt.AlignmentFlag.AlignVCenter, sub)
        if m["pinned"]:
            p.drawPixmap(int(box.left() + 12), int(box.center().y() - 8), icons.pixmap("pin", pal["acc_text"], 16))
        p.restore()


class _Stat(QWidget):
    def __init__(self, icon: str, name: str):
        super().__init__()
        self.icon, self.name, self.value = icon, name, "—"
        self.setFixedHeight(64)

    def set(self, v: str) -> None:
        self.value = v
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(r, rr(10), rr(10))
        p.drawPixmap(int(r.right() - 26), int(r.top() + 11), icons.pixmap(self.icon, pal["muted"], 15))
        p.setPen(QColor(pal["muted"]))
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() - 1)
        p.setFont(f)
        p.drawText(QRectF(r.left() + 10, r.top() + 8, r.width() - 40, 20), AL_R | Qt.AlignmentFlag.AlignVCenter, self.name)
        f.setPointSizeF(f.pointSizeF() + 5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        p.drawText(QRectF(r.left() + 10, r.top() + 28, r.width() - 20, 28), AL_R | Qt.AlignmentFlag.AlignVCenter, self.value)


class BackupBrowser(MotionDialog):
    """Browse, verify, pin, export, delete and restore encrypted backups."""
    restored = pyqtSignal()
    PAGE = 8                                                 # backups per page

    def __init__(self, win):
        super().__init__(win)
        self.win, self.store = win, win.store
        self.theme = win.theme
        self._page, self._metas = 1, []
        self.setWindowTitle("پشتیبان‌ها")
        self.resize(900, 600)
        self.setMinimumSize(760, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(*DIALOG)
        root.setSpacing(14)
        head = QHBoxLayout()
        hl = QVBoxLayout()
        hl.setSpacing(2)
        hl.addWidget(label("پشتیبان‌های رمزنگاری‌شده", "H1"))
        self.sub = label("", "Muted")
        hl.addWidget(self.sub)
        head.addLayout(hl, 1)
        head.addWidget(button("باز کردن پوشه", slot=self._open_folder))
        head.addWidget(button("＋ پشتیبان‌گیری الان", "Primary", self._backup_now))
        root.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = EmptyList("backup", "هنوز پشتیبانی نیست", "با «پشتیبان‌گیری الان» اولین نسخه‌ی رمزنگاری‌شده را بگیر.")
        self.list.setObjectName("BackupList")
        self.list.setItemDelegate(_RowDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list.setMinimumWidth(360)
        self.pager = Paginator()
        self.pager.pageChanged.connect(self._goto)
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self.list, 1)
        left.addWidget(self.pager)
        body.addLayout(left, 5)
        det = QFrame()
        det.setObjectName("Card")
        dl = QVBoxLayout(det)
        dl.setContentsMargins(18, 16, 18, 16)
        dl.setSpacing(10)
        self.d_title = label("", "H2", True)
        self.d_when = label("", "Muted", True)
        self.d_health = label("", "", True)
        dl.addWidget(self.d_title)
        dl.addWidget(self.d_when)
        dl.addWidget(self.d_health)
        grid = QHBoxLayout()
        grid.setSpacing(8)
        self.s_tasks, self.s_notes, self.s_habits, self.s_goals = (_Stat("tasks", "تسک"), _Stat("notes", "یادداشت"),
                                                                   _Stat("habits", "عادت"), _Stat("goals", "هدف"))
        for s in (self.s_tasks, self.s_notes, self.s_habits, self.s_goals):
            grid.addWidget(s, 1)
        dl.addLayout(grid)
        self.d_file = PathLabel()
        dl.addWidget(self.d_file)
        dl.addStretch(1)
        self.b_restore = button("بازگردانی این نسخه…", "Primary", self._restore)
        dl.addWidget(self.b_restore)
        row = QHBoxLayout()
        self.b_pin = button("سنجاق کن", slot=self._pin)
        self.b_save = button("ذخیره‌ی یک کپی…", slot=self._save_copy)
        self.b_del = button("حذف", "Danger", self._delete)
        for b in (self.b_pin, self.b_save, self.b_del):
            row.addWidget(b, 1)
        dl.addLayout(row)
        body.addWidget(det, 4)
        self.det = det
        root.addLayout(body, 1)
        foot = label("هر پشتیبان کپی دقیق فایل رمزنگاری‌شده‌ی ولت است (AES‑256‑GCM). پشتیبان‌های سنجاق‌شده هرگز خودکار حذف نمی‌شوند.",
                     "Muted", True)
        root.addWidget(foot)
        self._load()

    # ---- data
    def _load(self, select: Path | None = None) -> None:
        files = self.store.list_backups()
        metas = []
        for p in files:
            try:
                metas.append(self.store.backup_meta(p))
            except OSError:
                pass
        total = sum(m["size"] for m in metas)
        pinned = sum(1 for m in metas if m["pinned"])
        self.sub.setText(f"{fa(len(metas))} پشتیبان  —  {human_size(total)}  —  نگه‌داری {fa(self.store.keep_backups)} نسخه"
                         + (f"  —  {fa(pinned)} سنجاق‌شده" if pinned else "") if metas else "هنوز پشتیبانی وجود ندارد.")
        self._metas = metas
        if select is not None:                                # jump to the page that holds the wanted backup
            for i, m in enumerate(metas):
                if m["path"] == select:
                    self._page = i // self.PAGE + 1
                    break
        self._fill(select)

    def _goto(self, page: int) -> None:
        self._page = page
        self._fill()

    def _fill(self, select: Path | None = None) -> None:
        metas = self._metas
        self.pager.set_state(self._page, len(metas), self.PAGE)
        self._page = self.pager.page
        self.det.setVisible(bool(metas))                       # nothing to inspect: the empty state gets the whole dialog
        self.list.clear()
        last_day, first_row = None, None
        for m in metas[(self._page - 1) * self.PAGE: self._page * self.PAGE]:
            dtt = day_title(m["when"])
            if dtt != last_day:
                h = QListWidgetItem(dtt)
                h.setData(UR + 1, "head")
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(h)
                last_day = dtt
            it = QListWidgetItem("")
            it.setData(UR, m)
            self.list.addItem(it)
            if first_row is None or (select is not None and m["path"] == select):
                first_row = self.list.count() - 1
        if first_row is not None:
            self.list.setCurrentRow(first_row)
        self._show()

    def _cur(self) -> dict | None:
        it = self.list.currentItem()
        return it.data(UR) if it and it.data(UR + 1) != "head" else None

    def _show(self) -> None:
        m = self._cur()
        for b in (self.b_restore, self.b_pin, self.b_save, self.b_del):
            b.setEnabled(m is not None)
        pal = _fpal(self.win)
        if not m:
            self.d_title.setText("پشتیبانی انتخاب نشده")
            for w in (self.d_when, self.d_health, self.d_file):
                w.setText("")
            for s in (self.s_tasks, self.s_notes, self.s_habits, self.s_goals):
                s.set("—")
            return
        self.d_title.setText(f"{day_title(m['when'])}، ساعت {fa(m['when'].strftime('%H:%M'))}")
        self.d_when.setText(f"{m['label']}  —  {human_size(m['size'])}  —  {rel_time(m['when'])}"
                            + (f"  —  نسخه‌ی {fa(m['revision'])}" if m["revision"] is not None else ""))
        self.d_file.setText(str(m["path"]))
        self.b_pin.setText("برداشتن سنجاق" if m["pinned"] else "سنجاق کن")
        self.b_del.setEnabled(not m["pinned"])
        try:
            v = self.store.open_backup(m["path"])
            self.d_health.setText("✓  سالم — اصالت داده با AES‑GCM تأیید شد")
            self.d_health.setStyleSheet(f"color: {pal['ok']}; font-weight: 500;")
            self.s_tasks.set(fa(len(v.get("tasks", []))))
            self.s_notes.set(fa(len(v.get("notes", []))))
            self.s_habits.set(fa(len(v.get("habits", []))))
            self.s_goals.set(fa(len(v.get("goals", []))))
        except WrongPassword:
            self.d_health.setText("🔒  با کلید فعلی باز نمی‌شود — برای بازگردانی، رمزی که آن زمان داشتی لازم است")
            self.d_health.setStyleSheet(f"color: {pal['warn']}; font-weight: 500;")
            for s in (self.s_tasks, self.s_notes, self.s_habits, self.s_goals):
                s.set("؟")
        except (VaultError, OSError, ValueError):
            self.d_health.setText("✕  فایل آسیب دیده است و قابل بازگردانی نیست")
            self.d_health.setStyleSheet(f"color: {pal['danger']}; font-weight: 500;")
            self.b_restore.setEnabled(False)
            for s in (self.s_tasks, self.s_notes, self.s_habits, self.s_goals):
                s.set("—")

    # ---- actions
    def _backup_now(self) -> None:
        dst = self.win.backup_now("manual")
        if dst:
            self._load(dst)
        else:
            dialogs.warn(self, "پشتیبان‌گیری", "پشتیبان گرفته نشد. " + (self.store.backup_error or ""))

    def _open_folder(self) -> None:
        from .settings_page import open_folder
        try:
            self.store.backup_dir.mkdir(parents=True, exist_ok=True)
            open_folder(self.store.backup_dir)
        except OSError as e:
            dialogs.warn(self, "پوشه‌ی پشتیبان", f"پوشه باز نشد: {friendly(e)}")

    def _restore(self) -> None:
        m = self._cur()
        if not m:
            return
        if not dialogs.ask(self, "بازگردانی پشتیبان",
                           f"همه‌ی داده‌های فعلی با نسخه‌ی «{day_title(m['when'])}، ساعت {fa(m['when'].strftime('%H:%M'))}» جایگزین می‌شود.\n\n"
                           "نگران نباش: قبل از بازگردانی، از وضعیت فعلی هم یک پشتیبان گرفته می‌شود تا در صورت نیاز برگردی.",
                           True, "بازگردانی"):
            return
        self.win._flush_notes()
        try:
            try:
                self.store.restore_backup(m["path"])
            except WrongPassword:
                pw, ok = QInputDialog.getText(self, "رمز پشتیبان", "این پشتیبان با رمز دیگری ساخته شده. رمز آن زمان را وارد کن:",
                                              QLineEdit.EchoMode.Password)
                if not ok or not pw:
                    return
                from .auth import run_blocking
                run_blocking(lambda: self.store.restore_backup(m["path"], pw))
        except WrongPassword:
            dialogs.warn(self, "بازگردانی", "رمز درست نیست. چیزی تغییر نکرد.")
            return
        except (VaultError, OSError) as e:
            dialogs.warn(self, "بازگردانی", friendly(e))
            return
        self.win.vault_replaced()
        self.restored.emit()
        self.win.status_lb.setText("پشتیبان بازگردانی شد")
        dialogs.info(self, "بازگردانی", "نسخه‌ی انتخابی بازگردانی شد. وضعیت قبلی هم با عنوان «پیش از بازگردانی» در فهرست هست.")
        self._load()

    def _pin(self) -> None:
        m = self._cur()
        if not m:
            return
        try:
            dst = self.store.set_pinned(m["path"], not m["pinned"])
        except OSError as e:
            dialogs.warn(self, "سنجاق", friendly(e))
            return
        self._load(dst)

    def _save_copy(self) -> None:
        m = self._cur()
        if not m:
            return
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره‌ی کپی پشتیبان", m["path"].name, "Aegis vault (*.aegis)")
        if path:
            try:
                shutil.copy2(m["path"], path)
                self.win.status_lb.setText("کپی پشتیبان ذخیره شد")
            except OSError as e:
                dialogs.warn(self, "ذخیره", friendly(e))

    def _delete(self) -> None:
        m = self._cur()
        if not m or m["pinned"]:
            return
        if dialogs.ask(self, "حذف پشتیبان", "این پشتیبان برای همیشه حذف شود؟", True, "حذف"):
            try:
                m["path"].unlink()
            except OSError as e:
                dialogs.warn(self, "حذف", friendly(e))
            self._load()
