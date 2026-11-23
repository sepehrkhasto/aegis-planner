# SPDX-License-Identifier: GPL-3.0-or-later
"""The main application pages. Each page reads/writes ``ctx.store.vault`` and
calls ``ctx.changed()`` after a mutation (marks dirty, schedules autosave and
refreshes the other pages)."""
from __future__ import annotations

import datetime as dt
import math
import time

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate
from PyQt6.QtGui import QColor, QFont, QPen
from PyQt6.QtGui import QPainter, QPixmap
from .fx_widgets import Combo, IconToolButton, _fpal, GlowSearch, color_hex
from PyQt6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QScrollArea,
                             QVBoxLayout, QWidget)

from ..core import jalali, logic
from ..core.jalali import fa
from .voice import VOICE
from . import dialogs, flip, micro, moments
from .motion_widgets import HoldButton, JellyRadio
from .empty import EmptyOverlay
from .premium import (accent_for, pmenu, TaskRowDelegate, EmptyList, FocusDial, GoalCard, EmptyArt, HabitCard, HabitHeatmap, KpiTile, RoundButton)
from .calendar_view import CalendarPage  # noqa: F401  (re-exported)
from .paginator import Paginator
from .task_table import (COL_ACT, COL_CAT, COL_CHECK, COL_DUE, COL_PRIO, COL_STATUS, COL_TAGS, COL_TITLE, HoverTable, TaskCellDelegate)
from . import icons
from .anim import MOTION
from .tokens import PAGE
from .system import BAR_H, ChipCombo, ChipToggle, ChoiceTabs, ColHead, page_head, toolbar
from .theme import AL_R, PALETTES
from .theme import rr as _rad
from .widgets import button, card, label, one_accent

UR = Qt.ItemDataRole.UserRole


class Page(QWidget):
    title = ""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    @property
    def v(self) -> dict:
        return self.ctx.store.vault

    def refresh(self) -> None:  # override
        pass

    def one_accent(self) -> None:
        one_accent(self)

    def showEvent(self, e) -> None:  # noqa: N802
        self._flip_shown = time.monotonic()               # list motion waits until the page's own entrance is over
        super().showEvent(e)
        QTimer.singleShot(60, self.one_accent)             # children only count as visible once the page is shown

    def header(self, text, *right: QWidget, sub=None):
        """The page's opening block: title, optional subtitle, actions and the engraved rule (see ``system.page_head``)."""
        return page_head(text, sub, *right)


def _tipped(b, tip: str):
    b.setToolTip(tip)
    return b


def _wrap(lw: QListWidget) -> None:
    lw.setWordWrap(True)
    lw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    lw.setTextElideMode(Qt.TextElideMode.ElideNone)


def _task_line(x: dict) -> str:
    s = x.get("title", "")
    if x.get("timeFrom"):
        s = f"{fa(x['timeFrom'])}  {s}"
    return s


def _color(theme: str, key: str) -> QColor:
    return QColor(PALETTES[theme][key])


# ============================================================== TODAY ======
class TodayPage(Page):
    title = "امروز"

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(14)
        self.date_lb = label("", "H1")
        self.sub_lb = label("", "Muted")
        lay.addLayout(page_head(self.date_lb, self.sub_lb))
        add_row = QHBoxLayout()
        self.quick = QLineEdit()
        self.quick.setPlaceholderText("چه کاری برای امروز داری؟  (Enter برای افزودن)")
        self.quick.returnPressed.connect(self._quick_add)
        add_row.addWidget(self.quick, 1)
        add_row.addWidget(button("تسک با جزئیات…", slot=lambda: ctx.new_task(jalali.today_jalali())))
        lay.addLayout(add_row)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.tiles = {}
        for key, cap, ic, tone in (("today", "برای امروز", "today", "accent"), ("overdue", "عقب‌افتاده", "calendar", "danger"),
                                   ("open", "تسک باز", "tasks", "muted"), ("done", "انجام‌شده امروز", "check", "success")):
            t = KpiTile(ic, tone)
            t.caption = cap
            stats.addWidget(t, 1)
            self.tiles[key] = t
        lay.addLayout(stats)
        from .today_band import NowBand
        self.band = NowBand(ctx)
        lay.addWidget(self.band)

        cols = QHBoxLayout()
        cols.setSpacing(14)
        f1, l1 = card()
        self._card_over = f1
        l1.addWidget(label("عقب‌افتاده‌ها", "H2"))
        self.overdue = EmptyList("check", "هیچ کار عقب‌افتاده‌ای نیست", "عالی! همه‌چیز سر موعد است.")
        l1.addWidget(self.overdue)
        f2, l2 = card()
        l2.addWidget(label("امروز", "H2"))
        self.today = EmptyList("calendar", "امروز چیزی برنامه‌ریزی نشده", "از نوار بالا یک کار سریع اضافه کن.")
        l2.addWidget(self.today)
        self.today_empty = EmptyOverlay(self.today.viewport(), "calendar")
        self.today.overlay = self.today_empty
        cols.addWidget(f1, 1)
        cols.addWidget(f2, 1)
        self._card_today = f2
        self._was_all_done = None
        lay.addLayout(cols, 1)
        for lw in (self.overdue, self.today):
            _wrap(lw)
            lw.setItemDelegate(TaskRowDelegate(lw))
            lw.setFrameShape(QFrame.Shape.NoFrame)
            lw.setStyleSheet("QListWidget { background: transparent; border: none; }")
            lw.setMouseTracking(True)
            lw.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
            lw.itemChanged.connect(self._toggled)
            lw.itemDoubleClicked.connect(lambda it: ctx.edit_task_id(it.data(UR)))
        self._busy = False

    def _quick_add(self) -> None:
        t = self.quick.text().strip()
        if not t:
            return
        self.v["tasks"].append(logic.new_task(t, due=jalali.today_jalali()))
        self.quick.clear()
        self.ctx.changed()

    def _toggled(self, it: QListWidgetItem) -> None:
        if self._busy:
            return
        x = next((t for t in self.v["tasks"] if t["id"] == it.data(UR)), None)
        if x:
            logic.set_done(self.v, x, it.checkState() == Qt.CheckState.Checked)
            self.ctx.changed()

    def _fill(self, lw: QListWidget, tasks: list[dict]) -> None:
        lw.clear()
        today = dt.date.today()
        for x in tasks:
            it = QListWidgetItem(x.get("title", ""))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if x.get("done") else Qt.CheckState.Unchecked)
            it.setData(UR, x["id"])
            parts = []
            if x.get("timeFrom"):
                parts.append(fa(x["timeFrom"]) + (f"–{fa(x['timeTo'])}" if x.get("timeTo") else ""))
            d = logic.task_date(x)
            if d and d < today:
                parts.append(jalali.label(x.get("due")))
            parts.append(logic.CAT_LABEL.get(x.get("cat"), ""))
            it.setData(UR + 1, "  ·  ".join(t for t in parts if t))
            it.setData(UR + 2, x.get("pr"))
            it.setData(UR + 3, bool(d and d < today))
            it.setData(UR + 6, color_hex(x.get("color")))
            lw.addItem(it)

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        self._busy = True
        today = dt.date.today()
        j = jalali.today_jalali()
        self.date_lb.setText(f"{jalali.WEEKDAYS_FA[jalali.weekday_index(today)]}، {fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} {fa(j['jy'])}")
        tasks = self.v["tasks"]
        over = [x for x in tasks if logic.is_overdue(x, today) and not logic.is_event(x)]
        todays = [x for x in logic.tasks_on(self.v, today)]
        moving = flip.gate(self, ())
        b1, b2 = (flip.capture(self.overdue), flip.capture(self.today)) if moving else (None, None)
        self._fill(self.overdue, sorted(over, key=lambda x: logic.task_date(x)))
        self._fill(self.today, todays)
        flip.play(self.overdue, b1)
        flip.play(self.today, b2)
        self.today_empty.show_for(not todays, "امروز چیزی برنامه‌ریزی نشده", "یک کار برای امروز اضافه کن.",
                                  "＋ تسک برای امروز", lambda: self.ctx.new_task(jalali.today_jalali()))
        done_today = sum(1 for x in tasks if x.get("done") and x.get("doneAt") and
                         self._is_today(x["doneAt"]))
        left = sum(1 for x in todays if not x.get("done"))
        n_today = len(todays)
        self.tiles["today"].set(fa(left), "برای امروز", ((n_today - left) / n_today) if n_today else None)
        self.tiles["overdue"].set(fa(len(over)), "عقب‌افتاده")
        dm = logic.daily_metrics(self.v, 14)
        self.tiles["open"].set(fa(sum(1 for x in tasks if not x.get("done") and not x.get("archived"))), "تسک باز", spark=dm["created"])
        self.tiles["done"].set(fa(done_today), "انجام‌شده امروز", spark=dm["done"])
        all_done = bool(todays) and not left
        if all_done and self._was_all_done is False and moving:      # the moment the last open task gets ticked
            moments.celebrate(self._card_today)
            moments.seal_day(self)
        self._was_all_done = all_done
        self._card_over.setVisible(bool(over))                       # nothing overdue: the empty card gives its room to today
        self.band.set_state(self.v, n_today - left, n_today)
        hour = dt.datetime.now().hour
        hi = "صبح بخیر" if 5 <= hour < 12 else "ظهر بخیر" if 12 <= hour < 16 else "عصر بخیر" if 16 <= hour < 20 else "شب بخیر"
        nxt = self._next_timed(todays)
        body = (VOICE["day_done"] if todays and not left else
                (f"{fa(left)} کار برای امروز مانده" if left else "امروز چیزی برنامه‌ریزی نشده."))
        self.sub_lb.setText(f"{hi}  ·  {body}" + (f"  ·  کار بعدی: «{nxt['title'][:28]}» ساعت {fa(nxt['timeFrom'])}" if nxt else ""))
        self._busy = False

    @staticmethod
    def _next_timed(todays: list[dict]) -> dict | None:
        """The next not-yet-done task of today that has a start time in the future."""
        now = dt.datetime.now().strftime("%H:%M")
        c = [x for x in todays if not x.get("done") and x.get("timeFrom") and str(x["timeFrom"]) >= now]
        return min(c, key=lambda x: str(x["timeFrom"])) if c else None

    @staticmethod
    def _is_today(iso: str) -> bool:
        try:
            return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().date() == dt.date.today()
        except ValueError:
            return False


# ============================================================== TASKS ======
class TasksPage(Page):
    title = "تسک‌ها"

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(12)
        self.sub = label("", "Muted")
        lay.addLayout(self.header("تسک‌ها", _tipped(button("＋ تسک جدید", "Primary", lambda: ctx.new_task(None)), "تسک جدید  Ctrl+N"), sub=self.sub))
        self.q = GlowSearch()
        self.q.setFixedHeight(BAR_H)
        self.q.setMinimumWidth(170)
        self.status = ChoiceTabs()
        for k, t in (("open", "باز"), ("done", "انجام‌شده"), ("all", "همه")):
            self.status.addItem(t, k)
        self.cat = ChipCombo("دسته")
        self.cat.addItem("همه‌ی دسته‌ها", "all")
        for k, t in logic.CATEGORIES:
            self.cat.addItem(t, k)
        self.pr = ChipCombo("اولویت")
        self.pr.addItem("همه‌ی اولویت‌ها", "all")
        for k, t in logic.PRIORITIES:
            self.pr.addItem(t, k)
        self.tag = ChipCombo("برچسب")
        self.group = ChipToggle("گروه‌بندی")                      # today / this week / later sections
        self.group.setChecked(bool(ctx.prefs.get("group_tasks", True)))
        self.group.setToolTip("گروه‌بندی بر اساس موعد")
        self.group.toggled.connect(lambda on: (ctx.set_pref("group_tasks", bool(on)), self.refresh()))
        lay.addLayout(toolbar(self.q, self.status, self.cat, self.pr, self.tag, self.group, stretch_first=True))
        self.table = HoverTable(0, 8, "tasks", "تسکی پیدا نشد", "فیلترها را تغییر بده یا یک تسک تازه بساز.")
        self.empty = EmptyOverlay(self.table.viewport(), "tasks")
        self.table.overlay = self.empty                                # the table then skips its own painted empty state
        self.table.setHorizontalHeaderLabels(["", "عنوان", "دسته", "اولویت", "وضعیت", "موعد", "برچسب", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegate(TaskCellDelegate(self.table))
        self.table.actionRequested.connect(self._row_action)
        self.table.resized.connect(self._fit_columns)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading)
        hh.setHighlightSections(False)
        hh.setFixedHeight(38)
        self.apply_density(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, wpx in ((COL_CHECK, 52), (COL_CAT, 112), (COL_PRIO, 100), (COL_STATUS, 124), (COL_DUE, 130),
                       (COL_TAGS, 150), (COL_ACT, 128)):                          # roomy fixed columns → no huge dead gap
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, wpx)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(self._dbl)
        self.table.previewRequested.connect(self._peek)
        self.table.model().checkToggled.connect(self._check)
        self.table.model().titleEdited.connect(lambda tid, t: QTimer.singleShot(0, lambda: self._rename(tid, t)))
        self.bulk = QFrame()
        self.bulk.setObjectName("Card")
        bl = QHBoxLayout(self.bulk)
        bl.setContentsMargins(14, 8, 10, 8)
        self.bulk_lb = label("", "")
        bl.addWidget(self.bulk_lb)
        bl.addStretch(1)
        bl.addWidget(button("انجام شد", "Primary", lambda: self._bulk_done()))
        bl.addWidget(button("سطل زباله", "Danger", lambda: self._delete_selected()))
        bl.addWidget(button("لغو انتخاب", "Link", lambda: self.table.clearSelection()))
        self.bulk.hide()
        lay.addWidget(self.bulk)
        lay.addWidget(self.table, 1)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._sync_bulk())
        self.count = self.sub                                   # the count lives in the header now
        for w in (self.status, self.cat, self.pr, self.tag):
            w.currentIndexChanged.connect(lambda _=0: self.refresh())
        self._q_timer = QTimer(self, singleShot=True, interval=140)      # type freely: one refresh after a pause
        self._q_timer.timeout.connect(self.refresh)
        self.q.textChanged.connect(lambda _=0: self._q_timer.start())
        self.table.deleteRequested.connect(self._delete_selected)     # Enter/Delete only while the table has focus
        self._busy = False

    def apply_density(self, refresh: bool = True) -> None:
        """Comfortable (46 px) or compact (36 px) rows - for people with a lot of tasks."""
        TaskCellDelegate.ROW_H = 36 if self.ctx.prefs.get("density") == "compact" else 46
        self.table.verticalHeader().setDefaultSectionSize(TaskCellDelegate.ROW_H)
        if refresh:
            self.refresh()

    def _peek(self, row: int) -> None:
        from .peek import TaskPeek
        tid = self.table.task_id(row)
        x = next((t for t in self.v["tasks"] if t["id"] == tid), None)
        if x is None:
            return
        old = getattr(self, "_peek_w", None)
        if old is not None:
            try:
                old.close()
            except RuntimeError:
                pass
        rect = self.table.visualRect(self.table.model().index(row, COL_TITLE))
        w = self._peek_w = TaskPeek(self, x)
        anchor = self.table.viewport().mapToGlobal(rect.center())
        w.show_at(QPoint(anchor.x() - w.width() // 2, anchor.y() + 18))

    def _dbl(self, idx) -> None:
        """Double-click on the title renames in place; anywhere else opens the full editor."""
        if idx.column() == COL_TITLE:
            self.table.edit_title(idx.row())
        else:
            self.ctx.edit_task_id(self.table.task_id(idx.row()))

    def _rename(self, tid: str, text: str) -> None:
        text = " ".join(text.split())
        x = next((t for t in self.v["tasks"] if t["id"] == tid), None)
        if not x or not text or text == x.get("title"):
            return                                                  # empty / unchanged: keep the old title
        rec = self.ctx.snapshot([tid])
        x["title"] = text[:300]
        self.ctx.changed("عنوان عوض شد", undo=rec)

    def _ids(self) -> list[str]:
        return [self.table.task_id(r) for r in self.table.selected_rows()]

    def _sync_bulk(self) -> None:
        """A slim action bar appears once two or more rows are selected."""
        n = len(self.table.selected_rows())
        self.bulk_lb.setText(f"{fa(n)} تسک انتخاب شده")
        was = self.bulk.isVisible()
        self.bulk.setVisible(n >= 2)
        if n >= 2 and not was:
            micro.reveal(self.bulk)
        self.one_accent()

    def _bulk_done(self) -> None:
        ids = set(self._ids())
        rec = self.ctx.snapshot(ids)
        for x in [t for t in self.v["tasks"] if t["id"] in ids]:
            logic.set_done(self.v, x, True)
        self.ctx.changed(f"{fa(len(ids))} تسک انجام شد", undo=rec)

    def _clear_filters(self) -> None:
        for w in (self.status, self.cat, self.pr, self.tag):
            w.blockSignals(True)
            w.setCurrentIndex(0)
            w.blockSignals(False)
        self.q.setText("")
        self.refresh()

    def _sync_empty(self, rows) -> None:
        """Nothing to show: say why and offer the one action that fixes it."""
        if rows:
            self.empty.show_for(False)
            return
        narrowed = bool(self.q.text().strip()) or any(w.currentIndex() > 0 for w in (self.cat, self.pr, self.tag))
        status = self.status.currentData()
        if not self.v["tasks"]:
            self.empty.show_for(True, "هنوز تسکی نداری", "اولین تسکت را بساز — با Ctrl+N هم از هر جا می‌شود.",
                                "＋ اولین تسک را بساز", lambda: self.ctx.new_task(None))
        elif narrowed:
            self.empty.show_for(True, "چیزی با این فیلترها پیدا نشد", "جستجو یا فیلترها را عوض کن.",
                                "پاک کردن فیلترها", self._clear_filters)
        elif status == "open":                                     # tasks exist, none open: that is good news, say so
            self.empty.show_for(True, "همه‌ی کارها انجام شده", "چیزی باز نمانده. تسک تازه‌ای بساز یا انجام‌شده‌ها را مرور کن.",
                                "＋ تسک جدید", lambda: self.ctx.new_task(None))
        else:                                                      # "done" but nothing finished yet
            self.empty.show_for(True, "هنوز چیزی انجام نشده", "تسکی که تیک بزنی اینجا جمع می‌شود.",
                                "نشان‌دادن تسک‌های باز", self._clear_filters)

    def _fit_columns(self) -> None:
        """Narrow windows drop the least important columns first so the title always keeps room to breathe."""
        w = self.table.viewport().width() or self.width() - 48
        self.table.setColumnHidden(COL_TAGS, w < 1010)
        self.table.setColumnHidden(COL_CAT, w < 800)

    def _row_action(self, row: int, kind: str) -> None:
        tid = self.table.task_id(row)
        if tid is None:
            return
        if kind == "edit":
            self.ctx.edit_task_id(tid)
        elif kind == "delete":
            x = next((t for t in self.v["tasks"] if t["id"] == tid), None)
            if x:
                rec = self.ctx.snapshot([tid])
                logic.remove_task(self.ctx.store, x)
                self.ctx.changed("۱ تسک به سطل زباله رفت", undo=rec)
        else:
            rect = self.table.visualRect(self.table.model().index(row, COL_ACT))
            self._open_menu([tid], self.table.viewport().mapToGlobal(rect.bottomRight()))

    def _check(self, tid: str, on: bool) -> None:
        x = next((t for t in self.v["tasks"] if t["id"] == tid), None)
        if x:
            logic.set_done(self.v, x, on)
            self.ctx.changed()

    def _delete_selected(self) -> None:
        ids = self._ids()
        if not ids:
            return
        rec = self.ctx.snapshot(ids)
        for x in [t for t in self.v["tasks"] if t["id"] in ids]:
            logic.remove_task(self.ctx.store, x)
        self.ctx.changed(f"{fa(len(ids))} تسک به سطل زباله رفت", undo=rec)

    def _menu(self, pos) -> None:
        ids = self._ids()
        if not ids:
            return
        self._open_menu(ids, self.table.viewport().mapToGlobal(pos))

    def _open_menu(self, ids: list[str], global_pos) -> None:
        def trash() -> None:
            rec = self.ctx.snapshot(ids)
            for x in [t for t in self.v["tasks"] if t["id"] in ids]:
                logic.remove_task(self.ctx.store, x)
            self.ctx.changed(f"{fa(len(ids))} تسک به سطل زباله رفت", undo=rec)

        n = len(ids)
        m = pmenu(self, PALETTES[self.ctx.theme], [
            ("edit", "ویرایش", lambda: self.ctx.edit_task_id(ids[0]), False),
            None,
            ("calendar", "موعد: امروز", lambda: self._set_due(ids, 0), False),
            ("calendar", "موعد: فردا", lambda: self._set_due(ids, 1), False),
            ("calendar", "موعد: هفتهٔ بعد", lambda: self._set_due(ids, 7), False),
            ("calendar", "بدون موعد", lambda: self._set_due(ids, None), False),
            None,
            ("flag", "اولویت: زیاد", lambda: self._set_pr(ids, "high"), False),
            ("flag", "اولویت: معمولی", lambda: self._set_pr(ids, "normal"), False),
            ("flag", "اولویت: کم", lambda: self._set_pr(ids, "low"), False),
            None,
            ("kanban", "انتقال به «در حال انجام»", lambda: self._set_status(ids, "doing"), False),
            ("link", "کپی عنوان" if n == 1 else f"کپی عنوان {fa(n)} تسک", lambda: self._copy_titles(ids), False),
            None,
            ("trash", "انتقال به سطل زباله", trash, True)])
        m.exec(global_pos)

    def _set_due(self, ids, offset) -> None:
        rec = self.ctx.snapshot(ids)
        due = jalali.date_to_due(dt.date.today() + dt.timedelta(days=offset)) if offset is not None else None
        for x in self.v["tasks"]:
            if x["id"] in ids:
                x["due"] = dict(due) if due else None
                if not due:
                    x["dueEnd"] = None
                    x["timeFrom"] = x["timeTo"] = ""
                elif x.get("dueEnd") and jalali.due_to_date(x["dueEnd"]) and jalali.due_to_date(x["dueEnd"]) < jalali.due_to_date(due):
                    x["dueEnd"] = None                                   # a range can't end before its new start
        self.ctx.changed("موعد عوض شد", undo=rec)

    def _set_pr(self, ids, pr: str) -> None:
        rec = self.ctx.snapshot(ids)
        for x in self.v["tasks"]:
            if x["id"] in ids:
                x["pr"] = pr
        self.ctx.changed("اولویت عوض شد", undo=rec)

    def _copy_titles(self, ids) -> None:
        by = {t["id"]: t.get("title", "") for t in self.v["tasks"]}
        QApplication.clipboard().setText("\n".join(by[i] for i in ids if i in by))
        self.ctx.status_lb.setText("کپی شد")

    def _set_status(self, ids, st) -> None:
        rec = self.ctx.snapshot(ids)
        for x in self.v["tasks"]:
            if x["id"] in ids:
                logic.set_status(x, st)
        self.ctx.changed("وضعیت تسک عوض شد", undo=rec)

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        self._busy = True
        self.table.reset_hover()
        cur_tag = self.tag.currentData()
        self.tag.blockSignals(True)
        self.tag.clear()
        self.tag.addItem("همه‌ی برچسب‌ها", "")
        for t in logic.all_tags(self.v):
            self.tag.addItem("#" + t, t)
        self.tag.setCurrentIndex(max(0, self.tag.findData(cur_tag)))
        self.tag.blockSignals(False)
        self.tag.updateGeometry()
        rows = logic.filter_tasks(self.v, status=self.status.currentData(), cat=self.cat.currentData(),
                                  pr=self.pr.currentData(), q=self.q.text(), tag=self.tag.currentData() or "")
        # model/view: a reset is O(1); cells are derived lazily for the rows actually painted
        colors = {k: _color(self.ctx.theme, k) for k in ("muted", "danger", "text")}
        sig = (self.status.currentData(), self.cat.currentData(), self.pr.currentData(), self.q.text(), self.tag.currentData())
        before = flip.capture(self.table) if flip.gate(self, sig) else None
        self.table.model().set_rows(rows, colors, self.table.font(), grouped=self.group.isChecked(),
                                    open_only=self.status.currentData() == "open")
        flip.play(self.table, before)
        self._sync_empty(rows)
        late = sum(1 for x in rows if logic.is_overdue(x))
        self.count.setText(f"{fa(len(rows))} مورد" + (f"  ·  {fa(late)} عقب‌افتاده" if late else ""))
        self._busy = False


# ============================================================ CALENDAR =====
# ============================================================= KANBAN ======
class KanbanCardDelegate(QStyledItemDelegate):
    """Paints each kanban item as a card: priority stripe, title, due-date row and category chip.
    Roles: DisplayRole=title, UR+1=due text, UR+2=priority, UR+3=overdue?, UR+4=category label, UR+6=colour hex."""
    H = 74

    def sizeHint(self, opt, idx):  # noqa: N802, D401
        return QSize(120, self.H)

    def paint(self, p, opt, idx):  # noqa: D401
        pal = _fpal(opt.widget) if opt.widget is not None else PALETTES["dark"]
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        r = QRectF(opt.rect).adjusted(2, 2, -2, -2)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        hov = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        rad = min(_rad(9), 14)
        if KanbanList.dragging is not None and KanbanList.dragging == idx.data(UR):
            # the card in your hand has left its slot: only a dashed outline of where it was remains
            p.setPen(QPen(QColor(pal["accent2"]).lighter(100), 1.2, Qt.PenStyle.DashLine))
            ghost = QColor(pal["accent2"])
            ghost.setAlphaF(0.06)
            p.setBrush(ghost)
            p.drawRoundedRect(r, rad, rad)
            p.restore()
            return
        p.setPen(QPen(QColor(pal["accent2"] if sel else pal["muted"] if hov else pal["line"]), 1.4 if sel else 1))
        p.setBrush(QColor(pal["soft"] if sel else pal["panel2"]))
        p.drawRoundedRect(r, rad, rad)
        pr = idx.data(UR + 2)
        stripe = {"high": pal["danger"], "low": pal["muted"]}.get(pr, pal["accent2"])
        hexc = idx.data(UR + 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(hexc or stripe))
        p.drawRoundedRect(QRectF(r.right() - 4, r.top() + 10, 3, r.height() - 20), 1.5, 1.5)
        inner = r.adjusted(12, 8, -16, -8)
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        fm = p.fontMetrics()
        title = fm.elidedText(idx.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideRight, int(inner.width()))
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), 22), AL_R | Qt.AlignmentFlag.AlignVCenter, title)
        f2 = QFont(opt.font)
        f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.5))
        p.setFont(f2)
        y = inner.bottom() - 20
        due, over = idx.data(UR + 1), bool(idx.data(UR + 3))
        if due:
            col = pal["danger"] if over else pal["muted"]
            p.setPen(QColor(col))
            p.drawPixmap(int(inner.right() - 14), int(y + 3), icons.pixmap("calendar", col, 14))
            p.drawText(QRectF(inner.left(), y, inner.width() - 20, 20), AL_R | Qt.AlignmentFlag.AlignVCenter, due)
        cat = idx.data(UR + 4)
        if cat:
            tw = p.fontMetrics().horizontalAdvance(cat) + 16
            box = QRectF(inner.left(), y + 1, tw, 18)
            p.setPen(QPen(QColor(pal["line"]), 1))                     # quiet category tag
            p.setBrush(QColor(pal["panel"]))
            p.drawRoundedRect(box, _rad(9), _rad(9))
            p.setPen(QColor(pal["muted"]))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, cat)
        p.restore()


class KanbanList(QListWidget):
    dropped = pyqtSignal(str, str)   # task id, column
    dragging: str | None = None      # id of the card being carried (its slot draws as a dashed ghost)

    def __init__(self, col: str):
        super().__init__()
        self.col = col
        self._ovk = 0.0                                   # how strongly this column is lit as a drop target
        self._ov = QVariantAnimation(self)
        self._ov.setDuration(150)
        self._ov.valueChanged.connect(self._ov_step)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setItemDelegate(KanbanCardDelegate(self))
        _wrap(self)

    def startDrag(self, actions):  # noqa: N802
        """The card you carry is lifted: tilted a few degrees with a deep soft shadow underneath."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QCursor, QDrag, QPainter as _P
        it = self.currentItem()
        if it is None:
            return super().startDrag(actions)
        rect = self.visualItemRect(it)
        card = self.viewport().grab(rect)
        dpr, pad = card.devicePixelRatio(), 18
        out = QPixmap(int((rect.width() + 2 * pad) * dpr), int((rect.height() + 2 * pad) * dpr))
        out.setDevicePixelRatio(dpr)
        out.fill(Qt.GlobalColor.transparent)
        q = _P(out)
        q.setRenderHint(_P.RenderHint.Antialiasing)
        q.translate(pad + rect.width() / 2, pad + rect.height() / 2)
        q.rotate(-3.0)
        q.translate(-rect.width() / 2, -rect.height() / 2)
        q.setPen(Qt.PenStyle.NoPen)
        for grow, dy, a in ((0, 6, 60), (4, 10, 34), (9, 15, 18)):
            q.setBrush(QColor(0, 0, 0, a))
            q.drawRoundedRect(QRectF(-grow, dy - grow, rect.width() + 2 * grow, rect.height() + 2 * grow), 12 + grow, 12 + grow)
        q.setOpacity(0.96)
        q.drawPixmap(0, 0, card)
        q.end()
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(self.selectedItems()))
        drag.setPixmap(out)
        hot = self.viewport().mapFromGlobal(QCursor.pos()) - rect.topLeft()
        drag.setHotSpot(QPoint(hot.x() + pad, hot.y() + pad))
        KanbanList.dragging = it.data(UR)
        self.viewport().update()
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            KanbanList.dragging = None
            self.viewport().update()
            self.set_target(False)

    # ---- the column under the card lights up as a drop target
    def _ov_step(self, v) -> None:
        self._ovk = float(v)
        self.viewport().update()

    def set_target(self, on: bool) -> None:
        goal = 1.0 if on else 0.0
        if goal == self._ovk or (self._ov.state() == QVariantAnimation.State.Running and self._ov.endValue() == goal):
            return
        if not MOTION[0]:
            self._ovk = goal
            self.viewport().update()
            return
        self._ov.stop()
        self._ov.setStartValue(self._ovk)
        self._ov.setEndValue(goal)
        self._ov.start()

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        if self._ovk > 0.01:
            pal = _fpal(self)
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.viewport().rect()).adjusted(2, 2, -2, -2)
            fill = QColor(pal["accent2"])
            fill.setAlphaF(0.05 * self._ovk)
            edge = QColor(pal["accent2"])
            edge.setAlphaF(0.55 * self._ovk)
            p.setBrush(fill)
            p.setPen(QPen(edge, 1.4, Qt.PenStyle.DashLine))
            p.drawRoundedRect(r, min(_rad(10), 14), min(_rad(10), 14))

    def dragEnterEvent(self, e):  # noqa: N802
        if isinstance(e.source(), KanbanList):
            e.acceptProposedAction()
            self.set_target(e.source() is not self)

    def dragLeaveEvent(self, e):  # noqa: N802
        self.set_target(False)
        super().dragLeaveEvent(e)

    def dragMoveEvent(self, e):  # noqa: N802
        e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        self.set_target(False)
        src = e.source()
        if isinstance(src, KanbanList) and src.currentItem():
            self.dropped.emit(src.currentItem().data(UR), self.col)
        e.setDropAction(Qt.DropAction.IgnoreAction)   # the page rebuilds the columns itself
        e.accept()


class KanbanPage(Page):
    title = "کانبان"

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(12)
        lay.addLayout(self.header("تخته‌ی کانبان", _tipped(button("＋ تسک جدید", "Primary", lambda: ctx.new_task(None)), "تسک جدید  Ctrl+N"),
                                  sub=label("کارت را بکش و در ستون دیگر رها کن؛ یا روی آن راست‌کلیک کن.", "Muted")))
        cols = QHBoxLayout()
        cols.setSpacing(12)
        self.lists: dict[str, KanbanList] = {}
        self.heads: dict[str, QLabel] = {}
        for k, name in logic.KANBAN_COLS:
            f, l = card(margins=(10, 10, 10, 10), spacing=6)
            h = ColHead(name, {"todo": "muted", "doing": "accent", "done": "ok"}.get(k, "muted"))
            lw = KanbanList(k)
            lw.dropped.connect(self._drop)
            lw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            lw.customContextMenuRequested.connect(lambda pos, lw=lw: self._menu(lw, pos))
            lw.itemDoubleClicked.connect(lambda it: ctx.edit_task_id(it.data(UR)))
            l.addWidget(h)
            l.addWidget(lw, 1)
            cols.addWidget(f, 1)
            self.lists[k], self.heads[k] = lw, h
        lay.addLayout(cols, 1)

    def _drop(self, tid: str, col: str) -> None:
        x = next((t for t in self.v["tasks"] if t["id"] == tid), None)
        if x and logic.kanban_status(x) != col:
            if col == "done":
                logic.set_done(self.v, x, True)          # same as ticking it: a recurring task gets its next occurrence
            else:
                logic.set_status(x, col)
            self.ctx.changed()

    def _menu(self, lw: KanbanList, pos) -> None:
        it = lw.itemAt(pos)
        if not it:
            return
        ents = [("kanban", f"انتقال به «{name}»", lambda k=k, i=it.data(UR): self._drop(i, k), False)
                for k, name in logic.KANBAN_COLS if k != lw.col]
        ents += [None, ("edit", "ویرایش", lambda: self.ctx.edit_task_id(it.data(UR)), False)]
        m = pmenu(self, PALETTES[self.ctx.theme], ents)
        m.exec(lw.viewport().mapToGlobal(pos))

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        moving = flip.gate(self, ())
        before = {k: flip.capture(lw) for k, lw in self.lists.items()} if moving else {}
        self._fill()
        for k, lw in self.lists.items():
            flip.play(lw, before.get(k), spring=True)

    def _fill(self) -> None:
        by = {k: [] for k, _ in logic.KANBAN_COLS}
        for x in self.v["tasks"]:
            if not x.get("archived") and not logic.is_event(x):
                by[logic.kanban_status(x)].append(x)
        for k, name in logic.KANBAN_COLS:
            lw = self.lists[k]
            lw.clear()
            items = sorted(by[k], key=lambda x: (logic.task_date(x) or dt.date.max, x.get("title", "")))
            if k == "done":
                items = items[-60:]
            today = dt.date.today()
            for x in items:
                due = jalali.label(x.get("due"))
                d = logic.task_date(x)
                it = QListWidgetItem(x.get("title", ""))
                it.setData(UR, x["id"])
                it.setData(UR + 1, due + (f"  {fa(x['timeFrom'])}" if due and x.get("timeFrom") else ""))
                it.setData(UR + 2, x.get("pr"))
                it.setData(UR + 3, bool(d and d < today and k != "done"))
                it.setData(UR + 4, logic.CAT_LABEL.get(x.get("cat"), ""))
                it.setData(UR + 6, color_hex(x.get("color")))
                lw.addItem(it)
            self.heads[k].set(name, len(by[k]))


# ============================================================== NOTES ======
def _neg(s: str) -> str:
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def _empty_state(page, icon: str, title: str, sub: str, btn: str, slot) -> QWidget:
    w = QWidget()
    l = QVBoxLayout(w)
    l.setContentsMargins(0, 48, 0, 48)
    l.setSpacing(10)
    l.addWidget(EmptyArt(icon), 0, Qt.AlignmentFlag.AlignHCenter)
    t = label(title, "H2")
    t.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.addWidget(t)
    m = label(sub, "Muted", True)
    m.setAlignment(Qt.AlignmentFlag.AlignCenter)
    l.addWidget(m)
    l.addSpacing(6)
    cta = button(btn, "Primary", slot)
    cta.setProperty("cta", True)
    l.addWidget(cta, 0, Qt.AlignmentFlag.AlignHCenter)
    return w


def _page_head(title: str, sub, *right: QWidget):
    return page_head(title, sub, *right)


def _scroll_area() -> tuple[QScrollArea, QVBoxLayout]:
    sc = QScrollArea()
    sc.setProperty("edges", True)
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.Shape.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget()
    box = QVBoxLayout(inner)
    box.setContentsMargins(0, 0, 6, 0)
    box.setSpacing(12)
    box.addStretch(1)
    sc.setWidget(inner)
    return sc, box


def _clear(box: QVBoxLayout) -> None:
    while box.count() > 1:
        w = box.takeAt(0).widget()
        if w:
            w.hide()
            w.deleteLater()


class HabitsPage(Page):
    title = "عادت‌ها"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._open: set[str] = set()
        self._prev: dict[str, tuple] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(14)
        self.sub = label("", "Muted")
        lay.addLayout(_page_head("عادت‌ها", self.sub, button("＋ عادت جدید", "Primary", self._new)))
        kr = QHBoxLayout()
        kr.setSpacing(12)
        self.k_today = KpiTile("check", "success")
        self.k_streak = KpiTile("habits", "warn")
        self.k_rate = KpiTile("trend", "accent")
        self.k_total = KpiTile("reports", "muted")
        for k in (self.k_today, self.k_streak, self.k_rate, self.k_total):
            kr.addWidget(k, 1)
        lay.addLayout(kr)
        self.scroll, self.box = _scroll_area()
        lay.addWidget(self.scroll, 1)

    def _new(self) -> None:
        self.ctx.edit_habit(None)

    def _edit(self, h) -> None:
        self.ctx.edit_habit(h)

    def _delete(self, h) -> None:
        if dialogs.ask(self, "حذف عادت", f"«{h['name']}» به سطل زباله برود؟", True, "حذف"):
            self.ctx.store.trash_put("habit", h)
            self.v["habits"] = [x for x in self.v["habits"] if x["id"] != h["id"]]
            self.ctx.changed()

    def _tick(self, h, day: dt.date) -> None:
        logic.habit_toggle(h, day)
        self.ctx.changed()

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        for i in range(self.box.count() - 1):
            w = self.box.itemAt(i).widget()
            if isinstance(w, HabitCard):
                self._prev[w.hid] = w.ring.state
        _clear(self.box)
        habits = self.v["habits"]
        today = dt.date.today()
        tk = logic.iso_day(today)
        stats = [logic.habit_stats(h) for h in habits]
        done_n = sum(1 for h in habits if tk in (h.get("log") or {}))
        n = len(habits)
        self.sub.setText(f"{fa(done_n)} از {fa(n)} عادت امروز انجام شد" if n else "عادت‌های کوچک، نتیجه‌های بزرگ.")
        self.k_today.set(f"{fa(done_n)}/{fa(n)}", "انجام‌شده‌ی امروز", done_n / n if n else 0)
        best = max(stats, key=lambda s: s["streak"], default=None)
        if best and best["streak"]:
            self.k_streak.set(f"{fa(best['streak'])} {'روز' if best['daily'] else 'هفته'}", "بلندترین رگه‌ی فعال")
        else:
            self.k_streak.set("—", "بلندترین رگه‌ی فعال")
        goal_sum = sum(s["goal"] for s in stats)
        rate = sum(min(s["week"], s["goal"]) for s in stats) / goal_sum if goal_sum else 0
        self.k_rate.set(fa(round(rate * 100)) + "٪", "تحقق هدف این هفته", rate)
        self.k_total.set(fa(sum(len(h.get("log") or {}) for h in habits)), "مجموع ثبت‌ها")
        if not habits:
            self.box.insertWidget(0, _empty_state(self, "habits", "هنوز عادتی نداری",
                                                  "با یک عادت کوچک شروع کن؛ هر روز فقط یک تیک.", "＋ اولین عادت", self._new))
            return
        hm = QFrame()
        hm.setObjectName("Card")
        hl = QVBoxLayout(hm)
        hl.setContentsMargins(6, 6, 6, 6)
        hl.addWidget(HabitHeatmap(habits))
        self.box.insertWidget(0, hm)
        for i, h in enumerate(habits):
            self.box.insertWidget(i + 1, HabitCard(self, h, self._prev.get(h["id"]), h["id"] in self._open))


# =============================================================== GOALS =====
class GoalsPage(Page):
    title = "هدف‌ها"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._prev: dict[str, float] = {}
        self._exp: set[str] = set()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(14)
        self.sub = label("", "Muted")
        lay.addLayout(_page_head("هدف‌ها و نقشه‌ی راه", self.sub, button("＋ هدف جدید", "Primary", self._new)))
        kr = QHBoxLayout()
        kr.setSpacing(12)
        self.k_active = KpiTile("goals", "accent")
        self.k_avg = KpiTile("trend", "success")
        self.k_soon = KpiTile("calendar", "warn")
        self.k_done = KpiTile("trophy", "success")
        for k in (self.k_active, self.k_avg, self.k_soon, self.k_done):
            kr.addWidget(k, 1)
        lay.addLayout(kr)
        from .system import ChoiceTabs
        self.filter = ChoiceTabs()
        for k, t in [("all", "همه")] + list(logic.GOAL_HORIZONS):
            self.filter.addItem(t, k)
        self.filter.currentIndexChanged.connect(lambda _=0: self.refresh())
        fr = QHBoxLayout()
        fr.addWidget(self.filter)
        fr.addStretch(1)
        lay.addLayout(fr)
        self.scroll, self.box = _scroll_area()
        lay.addWidget(self.scroll, 1)

    def _new(self) -> None:
        self.ctx.edit_goal(None)

    def _edit(self, g) -> None:
        self.ctx.edit_goal(g)

    def _delete(self, g) -> None:
        if dialogs.ask(self, "حذف هدف", f"«{g['title']}» به سطل زباله برود؟ (تسک‌های وابسته حذف نمی‌شوند)", True, "حذف"):
            self.ctx.store.trash_put("goal", g)
            self.v["goals"] = [x for x in self.v["goals"] if x["id"] != g["id"]]
            self.ctx.changed()

    def _ms(self, m, on) -> None:
        m["done"] = bool(on)
        self.ctx.changed()

    def _expand(self, gid: str) -> None:
        self._exp ^= {gid}
        self.refresh()

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        for i in range(self.box.count() - 1):
            w = self.box.itemAt(i).widget()
            if isinstance(w, GoalCard):
                self._prev[w.gid] = w.ring.value
        _clear(self.box)
        self.filter.theme = self.ctx.theme
        allg = self.v["goals"]
        self.by_goal: dict[str, list] = {}
        for t in self.v["tasks"]:
            if t.get("goalId"):
                self.by_goal.setdefault(t["goalId"], []).append(t)
        prog = logic.goal_progress_map(self.v)
        act = [g for g in allg if prog[g["id"]] != 100]
        vals = [p for p in prog.values() if p is not None]
        soon = [g for g in act if (logic.goal_days_left(g) is not None and 0 <= logic.goal_days_left(g) <= 14)]
        self.sub.setText(f"{fa(len(act))} هدف در جریان" if allg else "هدف بزرگ را به قدم‌های کوچک بشکن.")
        self.k_active.set(fa(len(act)), "هدف در جریان")
        avg = round(sum(vals) / len(vals)) if vals else 0
        self.k_avg.set(fa(avg) + "٪", "میانگین پیشرفت", avg / 100 if vals else 0)
        self.k_soon.set(fa(len(soon)), "سررسید تا ۱۴ روز آینده")
        self.k_done.set(fa(len(allg) - len(act)), "هدف تکمیل‌شده")
        flt = self.filter.value()
        goals = [g for g in allg if flt == "all" or g.get("horizon") == flt]
        goals.sort(key=lambda g: (prog[g["id"]] == 100, logic.jalali.due_to_date(g.get("deadline")) or dt.date.max))
        if not goals:
            self.box.insertWidget(0, _empty_state(self, "goals", "هدفی ثبت نشده" if not allg else "هدفی در این بازه نیست",
                                                  "یک هدف بزرگ را به چند مرحله‌ی کوچک بشکن و پیشرفتش را ببین.",
                                                  "＋ هدف جدید", self._new))
            return
        for i, g in enumerate(goals):
            self.box.insertWidget(i, GoalCard(self, g, self._prev.get(g["id"]), g["id"] in self._exp))


# ============================================================== FOCUS ======
class FocusPage(Page):
    title = "تمرکز"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.mode, self.running = "work", False
        self.left = self._dur("work")
        self._deadline = 0.0          # monotonic end time of the running phase (immune to timer drift and sleep)
        self._pending = 0             # sessions finished while the vault was locked; logged on the next unlock
        self.theme = ctx.theme
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(14)
        self.sub = label("", "Muted")
        lay.addLayout(_page_head("تمرکز", self.sub))
        mid = QHBoxLayout()
        mid.addStretch(1)
        f, l = card(margins=(28, 24, 28, 24), spacing=16)
        f.setMaximumWidth(560)
        f.setMinimumWidth(440)
        self.seg = JellyRadio(["زمان کار", "استراحت"], ["work", "break"])
        self.seg.theme = ctx.theme
        self.seg.changed.connect(self._seg_changed)
        l.addWidget(self.seg, 0, Qt.AlignmentFlag.AlignHCenter)
        self.dial = FocusDial()
        l.addWidget(self.dial, 1)
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addStretch(1)
        self.b_skip = IconToolButton("skip", "رد شدن", size=46)
        self.b_skip.clicked.connect(self._skip)
        self.b_reset = IconToolButton("reset", "بازنشانی", size=46)
        self.b_reset.clicked.connect(self._reset)
        self.start = RoundButton("play", 72)
        self.start.clicked.connect(self._toggle)
        row.addWidget(self.b_reset)
        row.addWidget(self.start)
        row.addWidget(self.b_skip)
        row.addStretch(1)
        l.addLayout(row)
        l.addWidget(_tipped(button("حالت تمرکز کامل", "Link", lambda: ctx.enter_focus_mode()), "کل صفحه را کم‌نور می‌کند  Ctrl+Shift+F"),
                    0, Qt.AlignmentFlag.AlignHCenter)
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.k_sessions = KpiTile("focus", "accent")
        self.k_minutes = KpiTile("trend", "success")
        stats.addWidget(self.k_sessions)
        stats.addWidget(self.k_minutes)
        l.addLayout(stats)
        mid.addWidget(f, 3)
        mid.addStretch(1)
        lay.addLayout(mid, 1)
        self.timer = QTimer(self, interval=250)
        self.timer.timeout.connect(self._tick)
        self._paint()

    def _dur(self, mode: str) -> int:
        s = (self.v.get("settings") if self.ctx.store.vault else {}) or {}
        default = 25 if mode == "work" else 5
        try:
            mins = int(s.get("pomoWork" if mode == "work" else "pomoBreak", default))
        except (TypeError, ValueError):
            mins = default
        return max(1, min(180, mins)) * 60

    def _sessions(self) -> int:
        log = (self.v.get("settings", {}).get("pomoLog") or {}) if self.ctx.store.vault else {}
        return int(log.get(logic.iso_day(dt.date.today()), 0))

    def _seg_changed(self, _i: int) -> None:
        m = self.seg.value()
        if m != self.mode:
            self.mode = m
            self._reset()

    def _toggle(self) -> None:
        self.running = not self.running
        if self.running:
            self._deadline = time.monotonic() + self.left
            self.timer.start()
        else:
            self.left = max(0, math.ceil(self._deadline - time.monotonic()))     # freeze what is left
            self.timer.stop()
        self._paint()

    def _reset(self) -> None:
        self.timer.stop()
        self.running = False
        self.left = self._dur(self.mode)
        self._paint()

    def _skip(self) -> None:
        self._switch()

    def _switch(self) -> None:
        self.mode = "break" if self.mode == "work" else "work"
        self.seg.set_value(self.mode)
        self._reset()

    def _tick(self) -> None:
        left = math.ceil(self._deadline - time.monotonic())
        if left > 0:
            if left != self.left:          # the timer runs at 4 Hz; only repaint when the displayed second changes
                self.left = left
                self._paint()
            return
        finished_work = self.mode == "work"
        self.dial.finish()
        if finished_work:
            if self.ctx.store.is_unlocked:
                logic.pomo_add(self.v)
                self.ctx.changed()
            else:                          # auto-lock can fire mid-session: never touch a vault that is closed
                self._pending += 1
        self.ctx.notify("پایان زمان " + ("کار — استراحت کن " if finished_work else "استراحت — برگرد سر کار "), beep=True,
                        kind="focus", title="تمرکز")
        self._switch()

    def apply_pending(self) -> None:
        """Log sessions that finished while the app was locked (called right after unlock)."""
        n, self._pending = self._pending, 0
        if n and self.ctx.store.is_unlocked:
            for _ in range(n):
                logic.pomo_add(self.v)
            self.ctx.store.dirty = True
            self.ctx.schedule_save()

    def _paint(self) -> None:
        m, s = divmod(max(self.left, 0), 60)
        total = max(1, self._dur(self.mode))
        n = self._sessions()
        self.dial.set_state(f"{m:02d}:{s:02d}", (total - self.left) / total, self.mode, self.running, n,
                            ("در حال تمرکز…" if self.running else "آماده‌ای؟") if self.mode == "work"
                            else ("استراحت کن…" if self.running else "استراحت کوتاه"), self.left)
        self.start.icon = "pause" if self.running else "play"
        self.start.update()
        self.theme = self.ctx.theme
        self.seg.theme = self.ctx.theme

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        if not self.running:
            self.left = self._dur(self.mode)   # pick up changed durations while idle
        n = self._sessions()
        w = self._dur("work") // 60
        self.sub.setText("هر ۴ جلسه یک استراحت بلندتر بگیر." if not n else f"امروز {fa(n)} جلسه‌ی تمرکز داشتی.")
        self.k_sessions.set(fa(n), "جلسه‌ی تمرکز امروز", min(1.0, n / 4))
        self.k_minutes.set(fa(n * w), "دقیقه تمرکز امروز")
        self._paint()


# ============================================================= REPORTS =====
class ReportsPage(Page):
    title = "گزارش‌ها"
    skeleton = True            # many charts computed at once: show placeholders while they are built

    def __init__(self, ctx):
        super().__init__(ctx)
        from PyQt6.QtWidgets import QScrollArea
        from . import charts
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setProperty("edges", True)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(sc)
        body = QWidget()
        sc.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(14)
        self.days = Combo()
        for d in (7, 30, 90):
            self.days.addItem(f"{fa(d)} روز اخیر", d)
        self.days.setCurrentIndex(1)
        self.days.currentIndexChanged.connect(lambda _=0: self.refresh())
        self.seal = button("مهر هفته", slot=lambda: ctx.show_week_seal())
        self.seal.setToolTip("خلاصهٔ ۷ روز اخیر روی یک کارت قابل ذخیره و ارسال")
        self.pdf = button("خروجی PDF", slot=lambda: ctx.export_report_pdf(self.days.currentData()))
        self.pdf.setToolTip("گزارش خلاصهٔ این بازه روی سربرگ Aegis؛ فقط عدد و نام دسته، بدون متن تسک‌ها")
        self.summary = label("", "Muted", True)             # one plain sentence: how this period compares with the last
        lay.addLayout(self.header("گزارش‌ها و تحلیل", self.seal, self.pdf, self.days, sub=self.summary))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.tiles = {}
        for k, cap, ic, tone in (("total_done", "انجام‌شده", "check", "success"), ("open", "باز", "tasks", "accent"),
                                 ("overdue", "عقب‌افتاده", "calendar", "danger"), ("pomodoros", "پومودورو", "focus", "warn")):
            t = KpiTile(ic, tone)
            t.caption = cap
            row.addWidget(t, 1)
            self.tiles[k] = t
        lay.addLayout(row)

        def panel(title, sub, widget, minh=230):
            f, l = card()
            l.addWidget(label(title, "H2"))
            l.addWidget(label(sub, "Muted", True))
            widget.setMinimumHeight(minh)
            l.addWidget(widget, 1)
            return f

        self.area = charts.AreaChart(ctx.theme)
        self.bars = charts.GroupedBars(ctx.theme)
        self.cat_donut = charts.Donut(ctx.theme)
        self.pr_donut = charts.Donut(ctx.theme)
        self.radial = charts.RadialBars(ctx.theme)
        self.radar = charts.Radar(ctx.theme)
        g = QGridLayout()
        g.setSpacing(12)
        g.addWidget(panel("روند انجام تسک‌ها", "انجام‌شده در هر روز بازه‌ی انتخابی؛ خط‌چین = ایجادشده", self.area), 0, 0, 1, 2)
        g.addWidget(panel("سهم دسته‌ها", "تسک‌های انجام‌شده به تفکیک دسته", self.cat_donut, 260), 0, 2)
        g.addWidget(panel("جریان هفتگی", "ایجادشده در برابر انجام‌شده در ۸ هفته‌ی اخیر", self.bars), 1, 0, 1, 2)
        g.addWidget(panel("الگوی روزهای هفته", "کدام روزها بیشتر کار انجام می‌دهی", self.radar, 260), 1, 2)
        g.addWidget(panel("امتیاز عملکرد", "تکمیل، وقت‌شناسی، پایبندی به عادت‌ها و پیشرفت هدف‌ها", self.radial, 280), 2, 0)
        g.addWidget(panel("اولویت تسک‌های باز", "خط‌خطی = اولویت زیاد", self.pr_donut, 280), 2, 1)
        f, l = card()
        l.addWidget(label("نکته‌های تحلیلی", "H2"))
        self.insights = label("", "", True)
        self.insights.setTextFormat(Qt.TextFormat.RichText)
        l.addWidget(self.insights)
        l.addStretch(1)
        g.addWidget(f, 2, 2)
        from .report_widgets import ActivityCalendar, ProgressRingCard
        self.ring_cat = ProgressRingCard(ctx.theme)
        self.ring_goal = ProgressRingCard(ctx.theme)
        self.activity = ActivityCalendar(lambda a, b: logic.activity_days(self.v, a, b) if self.v else {}, ctx.theme)
        g.addWidget(panel("تکمیل به تفکیک دسته", "درصد تسک‌های سررسیدشده‌ی بازه که انجام شده‌اند؛ روی هر دسته بزن", self.ring_cat, 330), 3, 0)
        g.addWidget(panel("پیشرفت هدف‌ها", "هدف‌های در جریان؛ ردیف را بزن تا حلقه روی همان هدف برود", self.ring_goal, 330), 3, 1)
        g.addWidget(panel("تقویم فعالیت", "روزهای انجام تسک یا تیک عادت (پررنگ‌تر = فعالیت بیشتر)", self.activity, 330), 3, 2)
        from .report_widgets import SparkTable
        self.hbars = charts.HorizontalBars(ctx.theme)
        self.spark = SparkTable(ctx.theme)
        g.addWidget(panel("مقایسه با دوره‌ی قبل", "تسک‌های انجام‌شده در هر روز هفته؛ دوره‌ی جاری در برابر دوره‌ی قبلی هم‌طول", self.hbars, 330), 4, 0, 1, 2)
        g.addWidget(panel("روندها در یک نگاه", "نمودارهای کوچک دوره‌ی انتخابی؛ نشانگر را روی هر کدام ببر", self.spark, 300), 4, 2)
        for c in range(3):
            g.setColumnStretch(c, 1)
        lay.addLayout(g)
        lay.addStretch(1)
        self.charts = (self.area, self.bars, self.cat_donut, self.pr_donut, self.radial, self.radar, self.hbars)

    @staticmethod
    def _delta(cur: int, prev: int):
        if prev == 0 and cur == 0:
            return None
        pct = 100 if prev == 0 else round((cur - prev) / prev * 100)
        if pct == 0:
            return ("بدون تغییر نسبت به دوره‌ی قبل", "muted")
        return (f"{fa(abs(pct))}٪ {'رشد' if pct > 0 else 'کاهش'} نسبت به دوره‌ی قبل", "success" if pct > 0 else "danger")

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        from .charts import CHART
        days = self.days.currentData()
        r = logic.report_summary(self.v, days)
        prev = logic.report_summary(self.v, days, dt.date.today() - dt.timedelta(days=days))
        th = self.ctx.theme
        cur, old = r["total_done"], prev["total_done"]
        if not cur and not old:
            msg = "هنوز تسکی در این بازه انجام نشده."
        elif not old:
            msg = f"در این بازه {fa(cur)} تسک انجام دادی؛ بازه‌ی قبلی چیزی ثبت نشده بود."
        elif cur == old:
            msg = f"به اندازه‌ی بازه‌ی قبل تسک انجام دادی ({fa(cur)})."
        else:
            pct = round(abs(cur - old) / old * 100)
            msg = f"این بازه {fa(pct)}٪ {'بیشتر' if cur > old else 'کمتر'} از بازه‌ی قبل تسک انجام دادی ({fa(cur)} در برابر {fa(old)})."
        self.summary.setText(msg)
        for k, t in self.tiles.items():
            t.set(fa(r[k]), t.caption, None, self._delta(r[k], prev[k]) if k == "total_done" else None)
        for c in self.charts:
            c.set_theme(th)
        from ..core import jalali as _j
        ser = []
        for iso, n in r["series"]:
            d = dt.date.fromisoformat(iso)
            j = _j.date_to_due(d)
            ser.append((f"{fa(j['jd'])} {_j.MONTHS_FA[j['jm'] - 1]}", n))
        dm = logic.daily_metrics(self.v, days)
        self.area.set_data(ser, th, second=dm["created"])
        self.bars.set_data([(fa(l.split()[0]) + " " + l.split()[1], a, b) for l, a, b in logic.weekly_flow(self.v, 8)], th)
        cats = sorted(r["by_cat"].items(), key=lambda kv: -kv[1])
        self.cat_donut.set_data([(logic.CAT_LABEL.get(k, k), n, CHART[i % len(CHART)], False) for i, (k, n) in enumerate(cats)],
                                (fa(r["total_done"]), "انجام‌شده"), th)
        po = logic.priority_open(self.v)
        self.pr_donut.set_data([("زیاد", po["high"], PALETTES[th]["danger"], True), ("معمولی", po["normal"], CHART[0], False),
                                ("کم", po["low"], PALETTES[th]["muted"], False)], (fa(sum(po.values())), "باز"), th)
        sc = logic.scores(self.v, days)
        self.radial.set_data([("تکمیل", sc["completion"], CHART[0]), ("وقت‌شناسی", sc["punctual"], CHART[1]),
                              ("عادت‌ها", sc["habit"], CHART[2]), ("هدف‌ها", sc["goal"], CHART[3])], th)
        wd = logic.weekday_done(self.v, days)
        self.radar.set_data(_j.WEEKDAYS_FA, wd, th)
        cp = logic.category_progress(self.v, days)
        done_all, total_all = sum(d for _c, d, _t in cp), sum(t for _c, _d, t in cp)
        self.ring_cat.set_data([(logic.CAT_LABEL.get(c, c), d / t * 100, CHART[i % len(CHART)]) for i, (c, d, t) in enumerate(cp)],
                               done_all / total_all * 100 if total_all else 0, "تکمیل‌شده", th)
        gp = logic.goal_progress_map(self.v)
        goals = [(g["title"] or "بدون عنوان", gp[g["id"]], accent_for(g["id"], PALETTES[th])) for g in self.v["goals"] if gp.get(g["id"]) is not None]
        goals.sort(key=lambda t: -t[1])
        self.ring_goal.set_data(goals[:6], sum(v for _l, v, _c in goals) / len(goals) if goals else 0, "میانگین پیشرفت", th,
                                "هنوز هدفی با مرحله یا تسک پیوندی نداری")
        self.activity.set_theme(th)
        self.activity.reload()
        cur, prv = logic.weekday_compare(self.v, days)
        self.hbars.set_data([(_j.WEEKDAYS_FA[i], cur[i], prv[i]) for i in range(7)], th)
        names = [n for n, _v in ser]
        net = [d - c for d, c in zip(dm["done"], dm["created"])]
        tot_net = sum(net)
        sign = "\u200e+" if tot_net > 0 else ("\u200e−" if tot_net < 0 else "")
        po = logic.priority_open(self.v)
        self.spark.set_data([
            dict(label="تسک‌های انجام‌شده", kind="area", values=dm["done"], total_text=fa(sum(dm["done"])), color="accent", names=names),
            dict(label="انجام − ایجاد", kind="bars", values=net, total_text=sign + fa(abs(tot_net)), color="accent2",
                 neg=True, names=names),
            dict(label="تیک عادت‌ها", kind="line", values=dm["habits"], total_text=fa(sum(dm["habits"])), color="ok", names=names),
            dict(label="پومودورو", kind="bars", values=dm["pomo"], total_text=fa(sum(dm["pomo"])), color="warn", names=names),
            dict(label="اولویت تسک‌های باز", kind="pie", values=[po["high"], po["normal"], po["low"]], total_text=fa(sum(po.values())),
                 names=["زیاد", "معمولی", "کم"], slices=[PALETTES[th]["danger"], PALETTES[th]["accent"], PALETTES[th]["muted"]]),
        ], th)
        tips = []
        if sum(wd):
            tips.append(f"پرکارترین روز: <b>{_j.WEEKDAYS_FA[wd.index(max(wd))]}</b> ({fa(max(wd))} تسک)")
        tips.append(f"میانگین: <b>{fa(round(r['total_done'] / days, 1)).replace('.', '٫')}</b> تسک در روز")
        if r["overdue"]:
            tips.append(f"<b>{fa(r['overdue'])}</b> تسک عقب‌افتاده منتظر رسیدگی است")
        if sc["punctual"]:
            tips.append(f"وقت‌شناسی: <b>{fa(sc['punctual'])}٪</b> تسک‌ها تا موعد انجام شده‌اند")
        if po["high"]:
            tips.append(f"<b>{fa(po['high'])}</b> تسک باز با اولویت زیاد داری")
        self.insights.setText("<br><br>".join("• " + t for t in tips) or "هنوز داده‌ی کافی نیست.")


# =============================================================== TRASH =====
class TrashDelegate(QStyledItemDelegate):
    H = 60
    ICON = {"task": "tasks", "note": "notes", "habit": "habits", "goal": "goals"}

    def sizeHint(self, opt, idx):  # noqa: N802, D401
        return QSize(120, self.H)

    def paint(self, p, opt, idx):  # noqa: D401
        from .backup_ui import rel_time
        pal = _fpal(opt.widget)
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        hov = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        box = QRectF(opt.rect).adjusted(3, 2, -3, -2)
        p.setPen(QPen(QColor(pal["accent2"]), 1.2) if sel else QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["soft"]) if sel else QColor(pal["panel2"]) if hov else QColor(pal["panel"]))
        p.drawRoundedRect(box, _rad(10), _rad(10))
        tile = QRectF(box.right() - 12 - 36, box.center().y() - 18, 36, 36)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["soft"]) if not sel else QColor(pal["panel"]))
        p.drawRoundedRect(tile, min(_rad(10), 18), min(_rad(10), 18))
        p.drawPixmap(int(tile.center().x() - 9), int(tile.center().y() - 9),
                     icons.pixmap(self.ICON.get(idx.data(UR + 1), "trash"), pal["acc_text"], 18))
        tx = QRectF(box.left() + 14, box.top() + 9, tile.left() - box.left() - 28, 22)
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        p.drawText(tx, AL_R | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(idx.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideRight, int(tx.width())))
        f2 = QFont(opt.font)
        f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.5))
        p.setFont(f2)
        p.setPen(QColor(pal["muted"]))
        sub = idx.data(UR + 2) or ""
        try:
            when = dt.datetime.fromisoformat((idx.data(UR + 3) or "").replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            left = max(0, 30 - (dt.datetime.now() - when).days)
            sub += f"  ·  حذف‌شده {rel_time(when)}  ·  {fa(left)} روز تا پاک‌شدن"
        except ValueError:
            pass
        p.drawText(QRectF(tx.left(), tx.bottom() + 1, tx.width(), 20), AL_R | Qt.AlignmentFlag.AlignVCenter, sub)
        p.restore()


class TrashPage(Page):
    title = "سطل زباله"
    KINDS = {"task": "تسک", "note": "یادداشت", "habit": "عادت", "goal": "هدف"}
    PAGE = 8                                                 # rows per page (newest first)

    def __init__(self, ctx):
        super().__init__(ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*PAGE)
        lay.setSpacing(12)
        self.b_empty = button("خالی‌کردن", "Danger", self._empty)
        lay.addLayout(self.header("سطل زباله", self.b_empty,
                                  sub=label("موارد حذف‌شده تا ۳۰ روز نگه‌داری می‌شوند و بعد برای همیشه پاک می‌شوند.", "Muted")))
        self.list = EmptyList("trash", "سطل زباله خالی است", "چیزی که حذف کنی تا ۳۰ روز اینجا می‌ماند و می‌شود برش گرداند.")
        self.list.setItemDelegate(TrashDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        lay.addWidget(self.list, 1)
        self._page = 1
        self.pager = Paginator()
        self.pager.pageChanged.connect(self._goto)
        lay.addWidget(self.pager)
        row = QHBoxLayout()
        self.b_restore = button("بازگردانی", "Primary", self._restore)
        row.addWidget(self.b_restore)
        hb = self.hb = HoldButton("نگه‌دار تا برای همیشه حذف شود", "حذف شد")
        hb.held.connect(lambda: self._purge(False))
        row.addWidget(hb)
        row.addStretch(1)
        lay.addLayout(row)

    def _entry(self):
        it = self.list.currentItem()
        return self.v["trash"][it.data(UR)] if it else None

    def _restore(self) -> None:
        e = self._entry()
        if e:
            if logic.restore_from_trash(self.v, e):
                self.ctx.changed("بازگردانی شد")
            else:
                self.ctx.notify("این مورد قابل بازگردانی نیست.", kind="alert", title="سطل زباله")

    def _purge(self, confirm: bool = True) -> None:
        e = self._entry()
        if e and (not confirm or dialogs.ask(self, "حذف همیشگی", "این مورد برای همیشه حذف شود؟", True, "حذف همیشگی")):
            self.v["trash"] = [t for t in self.v["trash"] if t is not e]
            self.ctx.changed()

    def _empty(self) -> None:
        if self.v["trash"] and dialogs.ask(self, "خالی‌کردن", "همه‌ی موارد سطل زباله برای همیشه حذف شوند؟", True, "خالی کن"):
            self.v["trash"] = []
            self.ctx.changed()

    def _goto(self, page: int) -> None:
        self._page = page
        self._fill()

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        self._fill()

    def _fill(self) -> None:
        cur = self.list.currentItem().data(UR) if self.list.currentItem() else None
        tr = self.v["trash"]
        order = list(range(len(tr) - 1, -1, -1))              # newest first
        self.pager.set_state(self._page, len(order), self.PAGE)
        self._page = self.pager.page
        self.list.clear()
        for i in order[(self._page - 1) * self.PAGE: self._page * self.PAGE]:
            t = tr[i]
            item = t.get("item") or {}
            name = item.get("title") or item.get("name") or "بدون عنوان"
            it = QListWidgetItem(name)
            it.setData(UR, i)
            it.setData(UR + 1, t.get("kind"))
            it.setData(UR + 2, self.KINDS.get(t.get("kind"), t.get("kind") or ""))
            it.setData(UR + 3, t.get("at"))
            self.list.addItem(it)
            if i == cur:
                self.list.setCurrentItem(it)
        if self.list.count() and not self.list.currentItem():
            self.list.setCurrentRow(0)
        has = self.list.count() > 0
        for w in (self.b_restore, self.hb):
            w.setEnabled(has)
        for w in (self.b_restore, self.hb, self.b_empty):        # an empty bin offers no actions - just its message
            w.setVisible(has)


from .notes_page import NotesPage  # noqa: E402,F401  (re-exported; imported last to avoid a cycle)
