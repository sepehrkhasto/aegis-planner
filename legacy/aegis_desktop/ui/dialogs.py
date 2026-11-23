# SPDX-License-Identifier: GPL-3.0-or-later
"""Modal dialogs: task/goal/habit editors, password & recovery flows, import."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from .tokens import DIALOG
from .micro import MotionDialog
from .sheet import SheetDialog
from .page_editor import PageEditorMixin
from .motion_widgets import JellyRadio
from .fx_widgets import Combo, AnimCheck, ColorSwatches, StrengthMeter
from PyQt6.QtWidgets import (QCheckBox, QDialog, QLabel, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit, QRadioButton,
                             QVBoxLayout, QWidget, QScrollArea, QFrame)
from PyQt6.QtCore import QTime

from ..core import crypto, logic
from ..core.jalali import fa
from ..core.store import uid
from .more import MoreSection, refit
from .premium import add_head
from .widgets import FaSpinBox, JalaliDateEdit, PasswordEdit, button, label


def _copy_secret(text: str, seconds: int = 60) -> None:
    """Put a secret on the clipboard and take it off again after a minute, if nothing else has replaced it."""
    cb = QGuiApplication.clipboard()
    cb.setText(text)

    def wipe():
        c = QGuiApplication.clipboard()
        if c.text() == text:
            c.clear()
    QTimer.singleShot(seconds * 1000, wipe)


class _Err(QLabel):
    """The line under a form that explains what is wrong: it takes no room until there is something to say."""

    def __init__(self):
        super().__init__("")
        self.setObjectName("Danger")
        self.setWordWrap(True)
        self.hide()

    def setText(self, t: str) -> None:  # noqa: N802
        super().setText(t)
        self.setVisible(bool(t))


def _buttons(dlg: QDialog, ok_text: str = "ذخیره", cancel_text: str = "انصراف") -> QDialogButtonBox:
    bb = QDialogButtonBox()
    ok = bb.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
    ok.setObjectName("Primary")
    bb.addButton(cancel_text, QDialogButtonBox.ButtonRole.RejectRole)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class _Msg(MotionDialog):
    """Themed replacement for QMessageBox: icon badge, title, wrapped text, primary + optional cancel."""

    def __init__(self, parent, title: str, text: str, icon: str, tone: str, yes: str, cancel: str | None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setMaximumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(14)
        body = label(text, "", True)
        lay.addWidget(body)
        row = QHBoxLayout()
        ok = button(yes, "Primary" if tone != "danger" else "", self.accept)
        if tone == "danger":
            ok.setObjectName("Danger")
        row.addWidget(ok)
        if cancel:
            row.addWidget(button(cancel, "", self.reject))
        row.addStretch(1)
        lay.addLayout(row)
        ok.setDefault(True)
        ok.setFocus()
        add_head(self, icon, title, "", tone)


def ask(parent, title: str, text: str, danger: bool = False, yes: str = "تأیید") -> bool:
    return _Msg(parent, title, text, "trash" if danger else "info", "danger" if danger else "accent", yes, "انصراف").exec() == 1


def info(parent, title: str, text: str) -> None:
    _Msg(parent, title, text, "info", "accent", "باشه", None).exec()


def warn(parent, title: str, text: str) -> None:
    _Msg(parent, title, text, "info", "warn", "باشه", None).exec()


# ------------------------------------------------------------------ task ---
class _NoForm:
    """Stands in for a QFormLayout while the page editor places the widgets itself: every call is accepted and ignored."""

    def __getattr__(self, _name):
        return lambda *a, **k: None


class TaskDialog(PageEditorMixin, SheetDialog):
    def __init__(self, parent, vault: dict, task: dict | None = None, default_due: dict | None = None,
                 defaults: dict | None = None, embedded: bool = False):
        """``defaults`` pre-fills a NEW task (title, timeFrom, timeTo, dueEnd, cat...): the calendar hands over what a drag drew.
        ``embedded`` makes it a full page that lives inside the main window (the app's editor) instead of a floating sheet."""
        super().__init__(parent)
        self._page_begin(embedded)
        self.UNSAVED_TEXT = "تغییرات این تسک ذخیره نشده‌اند. دور ریخته شوند؟"
        self.vault, self.task = vault, task
        self.setWindowTitle("ویرایش تسک" if task else "تسک جدید")
        t = task or dict(defaults or {})
        form = _NoForm() if embedded else QFormLayout()          # the page lays the same widgets out itself (see _compose_page)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.title = QLineEdit(t.get("title", ""))
        self.title.setPlaceholderText("عنوان…")
        self.notes = QPlainTextEdit(t.get("notes", ""))
        self.notes.setFixedHeight(64)
        self.cat = Combo()
        for k, lab in logic.CATEGORIES:
            self.cat.addItem(lab, k)
        self.cat.setCurrentIndex(max(0, self.cat.findData(t.get("cat", "personal"))))
        self.pr = JellyRadio([lab for _k, lab in logic.PRIORITIES], [k for k, _l in logic.PRIORITIES])
        self.theme = getattr(parent.window(), "theme", "dark") if parent else "dark"
        self.pr.theme = self.theme
        self.pr.set_value(t.get("pr", "normal"))
        self.due = JalaliDateEdit(True, t.get("due") if task else default_due)
        self.due_end = JalaliDateEdit(True, t.get("dueEnd"))
        self.due_end.enabled_cb.setText("تا تاریخ")
        from .timepick import TimeField
        self.t_from, self.t_to = TimeField(), TimeField()
        for w, v in ((self.t_from, t.get("timeFrom")), (self.t_to, t.get("timeTo"))):
            w.setDisplayFormat("HH:mm")
            w.setTime(QTime.fromString(v, "HH:mm") if v else QTime(0, 0))
        self.use_time = AnimCheck("ساعت مشخص")
        self.use_time.setChecked(bool(t.get("timeFrom")))
        trow = QHBoxLayout()
        trow.setSpacing(10)
        trow.addWidget(self.use_time)
        trow.addWidget(label("از"))
        trow.addWidget(self.t_from)
        trow.addWidget(label("تا"))
        trow.addWidget(self.t_to)
        trow.addStretch(1)
        self.use_time.toggled.connect(lambda on: (self.t_from.setEnabled(on), self.t_to.setEnabled(on)))
        self.t_from.setEnabled(self.use_time.isChecked())
        self.t_to.setEnabled(self.use_time.isChecked())
        self.rep = Combo()
        for k, lab in logic.REPEATS:
            self.rep.addItem(lab, k)
        self.rep.setCurrentIndex(max(0, self.rep.findData(t.get("rep", "none"))))
        self.tags = QLineEdit("، ".join(t.get("tags") or []))
        self.tags.setPlaceholderText("برچسب‌ها با ویرگول جدا شوند")
        self.goal = Combo()
        self.goal.addItem("— بدون هدف —", "")
        for g in vault.get("goals", []):
            self.goal.addItem(g["title"], g["id"])
        self.goal.setCurrentIndex(max(0, self.goal.findData(t.get("goalId", ""))))
        self.color = ColorSwatches(t.get("color") or "c0")
        self.link = QLineEdit(t.get("link", ""))
        self.link.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.subs = QListWidget()
        self.subs.setFixedHeight(92)
        for s in t.get("subs") or []:
            self._add_sub(str(s.get("text", "")), bool(s.get("done", False)))
        self.sub_in = QLineEdit()
        self.sub_in.setPlaceholderText("زیرتسک جدید + Enter")
        self.sub_in.returnPressed.connect(self._sub_enter)
        rm = button("حذف", slot=self._rm_sub)
        rm.setToolTip("حذف زیرتسک انتخابی")
        subrow = QHBoxLayout()
        subrow.setContentsMargins(0, 0, 0, 0)
        subrow.addWidget(self.sub_in, 1)
        subrow.addWidget(rm)
        self.title.setPlaceholderText("عنوان تسک…")

        # what everyone fills: title, when, category, priority - the rest waits behind «گزینه‌های بیشتر»
        pr_row = QHBoxLayout()
        pr_row.setContentsMargins(0, 0, 0, 0)
        pr_row.setSpacing(10)
        pr_row.addWidget(self.cat)
        pr_row.addWidget(label("اولویت", "Muted"))
        pr_row.addWidget(self.pr)
        pr_row.addStretch(1)
        self.style_title(self.title)
        form.addRow(self.title)
        form.addRow("موعد", self.due)
        form.addRow("ساعت", trow)
        form.addRow("دسته", pr_row)
        if embedded:
            self._compose_page(form, trow, pr_row, subrow)
            return
        self.more = MoreSection("گزینه‌های بیشتر")
        self.more.add_row("توضیحات", self.notes)
        self.more.add_row("", self.due_end)
        self.more.add_row("تکرار", self.rep)
        self.more.add_row("برچسب", self.tags)
        self.more.add_row("هدف", self.goal)
        self.more.add_row("رنگ", self.color)
        self.more.add_row("پیوند", self.link)
        self.more.add_row("زیرتسک‌ها", self.subs)
        self.more.add_row("", subrow)
        for sig in (self.notes.textChanged, self.due_end.enabled_cb.toggled, self.rep.currentIndexChanged, self.tags.textChanged,
                    self.goal.currentIndexChanged, self.color.changed, self.link.textChanged,
                    self.subs.model().rowsInserted, self.subs.model().rowsRemoved):
            sig.connect(lambda *_: self._sync_more())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(12)
        body = self._body = QWidget()
        body.setObjectName("DlgBody")
        body.setStyleSheet("QWidget#DlgBody { background: transparent; }")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 10, 0)
        bl.setSpacing(14)
        bl.addLayout(form)
        bl.addWidget(self.more)
        bl.addStretch(1)
        sc = self._sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")
        sc.setWidget(body)
        lay.addWidget(sc, 1)
        self.err = _Err()
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self, "ذخیره"))
        self.title.setFocus()
        add_head(self, "check", "ویرایش تسک" if task else "تسک جدید", "فقط عنوان لازم است؛ بقیه اختیاری است.")
        self._sync_more()
        self.more.set_open(bool(task) and self.more.head.count > 0, animate=False)   # editing a task that already has extras: show them
        self._fit_scroll()
        self.more.toggled.connect(self._more_toggled)
        self.finish_sheet(600)

    # ---- «more» plumbing
    def _more_names(self) -> list[str]:
        n = []
        if self.notes.toPlainText().strip():
            n.append("توضیحات")
        if self.due_end.value():
            n.append("تا تاریخ")
        if self.rep.currentData() != "none":
            n.append("تکرار")
        tags = [x for x in self.tags.text().replace("،", ",").split(",") if x.strip()]
        if tags:
            n.append("برچسب" if len(tags) == 1 else f"{fa(len(tags))} برچسب")
        if self.goal.currentData():
            n.append("هدف")
        if self.color.value != "c0":
            n.append("رنگ")
        if self.link.text().strip():
            n.append("پیوند")
        if self.subs.count():
            n.append("زیرتسک" if self.subs.count() == 1 else f"{fa(self.subs.count())} زیرتسک")
        return n

    def _sync_more(self) -> None:
        self.more.set_state(self._more_names())

    def _fit_scroll(self) -> None:
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry().height() if scr else 900
        # header ≈ 90, buttons/error ≈ 110, window chrome ≈ 40 - never let the dialog exceed the screen
        self._body.adjustSize()
        self._sc.setMinimumHeight(max(220, min(self._body.sizeHint().height() + 4, int(avail * 0.94) - 260)))

    def _more_toggled(self, _on: bool) -> None:
        self._fit_scroll()
        refit(self)

    def _add_sub(self, text: str, done: bool = False) -> None:
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        self.subs.addItem(it)

    def _sub_enter(self) -> None:
        if self.sub_in.text().strip():
            self._add_sub(self.sub_in.text().strip())
            self.sub_in.clear()

    def _rm_sub(self) -> None:
        for it in self.subs.selectedItems():
            self.subs.takeItem(self.subs.row(it))

    def accept(self) -> None:  # noqa: D401
        if not self.title.text().strip():
            self.err.setText("عنوان را وارد کن.")
            return
        if self.rep.currentData() != "none" and not self.due.value():
            self.due.set_value(None)
            self.due.enabled_cb.setChecked(True)   # recurring tasks need a start date
        super().accept()

    def _compose_page(self, form, trow, pr_row, subrow) -> None:
        """The full-page layout: a big title, two cards side by side (when / what), the sub-tasks, the notes - all visible at
        once, and a footer that stays in view. Cards stack under each other in a narrow window."""
        from PyQt6.QtWidgets import QBoxLayout
        from .widgets import card
        self.notes.setMinimumHeight(120)
        self.notes.setMaximumHeight(16777215)
        self.subs.setMinimumHeight(120)
        self.subs.setMaximumHeight(200)
        self.more = None
        cl = self.frame("ویرایش تسک" if self.task else "تسک جدید")
        self.style_title(self.title)
        self.title.setMinimumHeight(56)
        tf = self.title.font()
        tf.setPointSizeF(tf.pointSizeF() + 3)
        self.title.setFont(tf)
        cl.addWidget(self.title)
        self._cards = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._cards.setSpacing(14)
        when_f, when = card()
        when.addWidget(label("زمان‌بندی", "H2"))
        wf = QFormLayout()
        wf.setVerticalSpacing(10)
        wf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        wf.addRow("موعد", self.due)
        wf.addRow("", self.due_end)
        wf.addRow("ساعت", trow)
        wf.addRow("تکرار", self.rep)
        when.addLayout(wf)
        what_f, what = card()
        what.addWidget(label("دسته‌بندی", "H2"))
        kf = QFormLayout()
        kf.setVerticalSpacing(10)
        kf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        kf.addRow("دسته", pr_row)
        kf.addRow("هدف", self.goal)
        kf.addRow("برچسب", self.tags)
        kf.addRow("رنگ", self.color)
        what.addLayout(kf)
        self._cards.addWidget(when_f, 1)
        self._cards.addWidget(what_f, 1)
        cl.addLayout(self._cards)
        sub_f, sub = card()
        sub.addWidget(label("زیرتسک‌ها", "H2"))
        sub.addWidget(self.subs)
        sub.addLayout(subrow)
        cl.addWidget(sub_f)
        note_f, note = card()
        note.addWidget(label("توضیحات و پیوند", "H2"))
        note.addWidget(self.notes)
        lf = QFormLayout()
        lf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        lf.addRow("پیوند", self.link)
        note.addLayout(lf)
        cl.addWidget(note_f)
        cl.addStretch(1)
        self.err = _Err()
        self.footer(self.err)
        self._sync_more = lambda: None

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        cards = getattr(self, "_cards", None)
        if cards is not None:
            from PyQt6.QtWidgets import QBoxLayout
            d = QBoxLayout.Direction.TopToBottom if self.width() < 900 else QBoxLayout.Direction.LeftToRight
            if cards.direction() != d:
                cards.setDirection(d)

    def _data(self) -> dict:
        subs = [{"text": self.subs.item(i).text(),
                 "done": self.subs.item(i).checkState() == Qt.CheckState.Checked}
                for i in range(self.subs.count())]
        tags = [x.strip() for x in self.tags.text().replace("،", ",").split(",") if x.strip()]
        return dict(title=self.title.text().strip(), notes=self.notes.toPlainText().strip(),
                    cat=self.cat.currentData(), pr=self.pr.value(), due=self.due.value(),
                    dueEnd=self.due_end.value() if self.due.value() else None,
                    timeFrom=self.t_from.time().toString("HH:mm") if self.use_time.isChecked() else "",
                    timeTo=self.t_to.time().toString("HH:mm") if self.use_time.isChecked() else "",
                    rep=self.rep.currentData(), tags=tags, goalId=self.goal.currentData(),
                    link=self.link.text().strip(), subs=subs, color=self.color.value)

    def result_task(self) -> dict:
        subs = [{"text": self.subs.item(i).text(),
                 "done": self.subs.item(i).checkState() == Qt.CheckState.Checked}
                for i in range(self.subs.count())]
        tags = [x.strip() for x in self.tags.text().replace("،", ",").split(",") if x.strip()]
        data = dict(title=self.title.text().strip(), notes=self.notes.toPlainText().strip(),
                    cat=self.cat.currentData(), pr=self.pr.value(), due=self.due.value(),
                    dueEnd=self.due_end.value() if self.due.value() else None,
                    timeFrom=self.t_from.time().toString("HH:mm") if self.use_time.isChecked() else "",
                    timeTo=self.t_to.time().toString("HH:mm") if self.use_time.isChecked() else "",
                    rep=self.rep.currentData(), tags=tags, goalId=self.goal.currentData(),
                    link=self.link.text().strip(), subs=subs, color=self.color.value)
        if self.task:
            self.task.update(data)
            return self.task
        return logic.new_task(**data)


# ------------------------------------------------------------------ goal ---
class GoalDialog(PageEditorMixin, SheetDialog):
    def __init__(self, parent, goal: dict | None = None, embedded: bool = False):
        super().__init__(parent)
        self._page_begin(embedded)
        self.UNSAVED_TEXT = "تغییرات این هدف ذخیره نشده‌اند. دور ریخته شوند؟"
        self.goal = goal
        g = goal or {}
        self.setWindowTitle("ویرایش هدف" if goal else "هدف جدید")
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.title = QLineEdit(g.get("title", ""))
        self.desc = QPlainTextEdit(g.get("desc", ""))
        self.desc.setFixedHeight(70)
        self.hz = Combo()
        for k, lab in logic.GOAL_HORIZONS:
            self.hz.addItem(lab, k)
        self.hz.setCurrentIndex(max(0, self.hz.findData(g.get("horizon", "year"))))
        self.deadline = JalaliDateEdit(True, g.get("deadline"))
        self.ms = QListWidget()
        self.ms.setFixedHeight(104)
        for m in g.get("ms") or []:
            self._add(m["text"], m.get("done", False), m.get("id"))
        self.ms_in = QLineEdit()
        self.ms_in.setPlaceholderText("مرحله‌ی جدید + Enter")
        self.ms_in.returnPressed.connect(self._enter)
        rm = button("حذف", slot=lambda: [self.ms.takeItem(self.ms.row(i)) for i in self.ms.selectedItems()])
        rm.setToolTip("حذف مرحله‌ی انتخابی")
        msrow = QHBoxLayout()
        msrow.setContentsMargins(0, 0, 0, 0)
        msrow.addWidget(self.ms_in, 1)
        msrow.addWidget(rm)
        self.title.setPlaceholderText("عنوان هدف…")
        self.desc.setFixedHeight(72)
        self.style_title(self.title)
        if embedded:
            self._compose_page(msrow)
            return
        form.addRow(self.title)
        form.addRow("افق", self.hz)
        form.addRow("سررسید", self.deadline)
        form.addRow("مراحل", self.ms)
        form.addRow("", msrow)
        self.more = MoreSection("گزینه‌های بیشتر")                 # the description is optional: it waits behind «more»
        self.more.add_row("توضیح", self.desc)
        self.desc.textChanged.connect(lambda: self.more.set_state(["توضیح"] if self.desc.toPlainText().strip() else []))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(14)
        lay.addLayout(form)
        lay.addWidget(self.more)
        self.err = _Err()
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self))
        add_head(self, "trophy", "ویرایش هدف" if goal else "هدف جدید", "یک عنوان و چند مرحله‌ی روشن کافی است.")
        self.desc.textChanged.emit()
        self.more.set_open(bool(goal) and self.more.head.count > 0, animate=False)
        self.more.toggled.connect(lambda _on: refit(self))
        self.finish_sheet(540)

    def _compose_page(self, msrow) -> None:
        from PyQt6.QtWidgets import QBoxLayout
        from .widgets import card
        self.more = None
        self.desc.setMinimumHeight(120)
        self.desc.setMaximumHeight(16777215)
        self.ms.setMinimumHeight(150)
        self.ms.setMaximumHeight(16777215)
        cl = self.frame("ویرایش هدف" if self.goal else "هدف جدید")
        self.title.setMinimumHeight(56)
        tf = self.title.font()
        tf.setPointSizeF(tf.pointSizeF() + 3)
        self.title.setFont(tf)
        cl.addWidget(self.title)
        self._cards = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._cards.setSpacing(14)
        a_f, a = card()
        a.addWidget(label("زمان", "H2"))
        af = QFormLayout()
        af.setVerticalSpacing(10)
        af.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        af.addRow("افق", self.hz)
        af.addRow("سررسید", self.deadline)
        a.addLayout(af)
        a.addStretch(1)
        m_f, m = card()
        m.addWidget(label("مرحله‌ها", "H2"))
        m.addWidget(self.ms)
        m.addLayout(msrow)
        self._cards.addWidget(a_f, 1)
        self._cards.addWidget(m_f, 1)
        cl.addLayout(self._cards)
        d_f, d = card()
        d.addWidget(label("توضیح", "H2"))
        d.addWidget(self.desc)
        cl.addWidget(d_f)
        cl.addStretch(1)
        self.err = _Err()
        self.footer(self.err)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        cards = getattr(self, "_cards", None)
        if cards is not None:
            from PyQt6.QtWidgets import QBoxLayout
            d = QBoxLayout.Direction.TopToBottom if self.width() < 900 else QBoxLayout.Direction.LeftToRight
            if cards.direction() != d:
                cards.setDirection(d)

    def _data(self) -> dict:
        ms = [{"id": self.ms.item(i).data(Qt.ItemDataRole.UserRole), "text": self.ms.item(i).text(),
               "done": self.ms.item(i).checkState() == Qt.CheckState.Checked} for i in range(self.ms.count())]
        return dict(title=self.title.text().strip(), desc=self.desc.toPlainText().strip(),
                    horizon=self.hz.currentData(), deadline=self.deadline.value(), ms=ms)

    def _add(self, text, done=False, mid=None) -> None:
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        it.setData(Qt.ItemDataRole.UserRole, mid or uid("m"))
        self.ms.addItem(it)

    def _enter(self) -> None:
        if self.ms_in.text().strip():
            self._add(self.ms_in.text().strip())
            self.ms_in.clear()

    def accept(self) -> None:
        if not self.title.text().strip():
            self.err.setText("عنوان را وارد کن.")
            return
        super().accept()

    def result_goal(self) -> dict:
        data = self._data()
        if self.goal:
            self.goal.update(data)
            return self.goal
        return logic.new_goal(**data)


# ----------------------------------------------------------------- habit ---
class HabitDialog(PageEditorMixin, SheetDialog):
    def __init__(self, parent, habit: dict | None = None, embedded: bool = False):
        super().__init__(parent)
        self._page_begin(embedded)
        self.UNSAVED_TEXT = "تغییرات این عادت ذخیره نشده‌اند. دور ریخته شوند؟"
        self.habit = habit
        self.setWindowTitle("ویرایش عادت" if habit else "عادت جدید")
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name = QLineEdit((habit or {}).get("name", ""))
        self.per = FaSpinBox()
        self.per.setRange(1, 7)
        self.per.setValue(logic.habit_goal(habit or {}))
        self.per.setSuffix(" روز در هفته")
        self.style_title(self.name)
        if embedded:
            self._compose_page()
            return
        form.addRow(self.name)
        form.addRow("هدف", self.per)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(12)
        lay.addLayout(form)
        self.err = _Err()
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self))
        add_head(self, "habits", "ویرایش عادت" if habit else "عادت جدید", "هر هفته چند روز می‌خواهی انجامش بدهی؟")
        self.finish_sheet(460)

    def accept(self) -> None:
        if not self.name.text().strip():
            self.err.setText("نام عادت را وارد کن.")
            return
        super().accept()

    def _compose_page(self) -> None:
        from .widgets import card
        self.more = None
        cl = self.frame("ویرایش عادت" if self.habit else "عادت جدید", 720)
        self.name.setMinimumHeight(56)
        tf = self.name.font()
        tf.setPointSizeF(tf.pointSizeF() + 3)
        self.name.setFont(tf)
        self.name.setPlaceholderText("نام عادت…")
        cl.addWidget(self.name)
        f, c = card()
        c.addWidget(label("هدف هفتگی", "H2"))
        c.addWidget(label("هر هفته چند روز می‌خواهی انجامش بدهی؟ رگه و نقشهٔ حرارتی بر اساس همین هدف حساب می‌شوند.", "Muted", True))
        row = QHBoxLayout()
        row.addWidget(self.per)
        row.addStretch(1)
        c.addLayout(row)
        cl.addWidget(f)
        cl.addStretch(1)
        self.err = _Err()
        self.footer(self.err)

    def _data(self) -> dict:
        return dict(name=self.name.text().strip(), perWeek=self.per.value())

    def result_habit(self) -> dict:
        if self.habit:
            self.habit.update(name=self.name.text().strip(), perWeek=self.per.value())
            return self.habit
        return logic.new_habit(self.name.text().strip(), self.per.value())


# -------------------------------------------------------------- passwords ---
class NewPasswordDialog(MotionDialog):
    """Ask for a new master password twice, validating strength."""

    def __init__(self, parent, title: str = "رمز اصلی جدید", ask_current: bool = False, verify=None):
        super().__init__(parent)
        self.verify = verify
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(12)
        lay.addWidget(label("این رمز را جایی امن بنویس. هیچ نسخه‌ای از آن جای دیگری نیست و بدون آن (و بدون کلید بازیابی) داده‌ها برنمی‌گردند.", "Muted", True))
        self.cur = PasswordEdit("رمز فعلی") if ask_current else None
        if self.cur:
            lay.addWidget(self.cur)
        self.p1, self.p2 = PasswordEdit("رمز جدید (حداقل ۱۰ کاراکتر)"), PasswordEdit("تکرار رمز جدید")
        lay.addWidget(self.p1)
        self.meter = StrengthMeter()
        self.p1.textChanged.connect(self.meter.set_password)
        lay.addWidget(self.meter)
        lay.addWidget(self.p2)
        self.err = _Err()
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self, "تغییر رمز" if ask_current else "تأیید"))
        add_head(self, "lock", title, "رمزی قوی و منحصربه‌فرد انتخاب کن.")

    def accept(self) -> None:
        if self.cur and self.verify and not self.verify(self.cur.text()):
            self.err.setText("رمز فعلی درست نیست.")
            return
        probs = crypto.password_problems(self.p1.text())
        if probs:
            self.err.setText(" ".join(probs))
            return
        if self.p1.text() != self.p2.text():
            self.err.setText("دو رمز یکسان نیستند.")
            return
        super().accept()

    def password(self) -> str:
        return self.p1.text()


class RecoveryKeyDialog(MotionDialog):
    """Shows the recovery key once, with copy & save-to-file."""

    def __init__(self, parent, key: str):
        super().__init__(parent)
        self.key = key
        self.setWindowTitle("کلید بازیابی")
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(12)
        lay.addWidget(label("این کلید تنها راه بازیابی است اگر رمز اصلی را فراموش کنی. آن را روی کاغذ بنویس یا در جای امنی ذخیره کن. "
                            "بعد از بستن این پنجره دیگر نمایش داده نمی‌شود.", "Muted", True))
        box = QLineEdit(key)
        box.setReadOnly(True)
        box.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = box.font()
        f.setPointSize(13)
        f.setBold(True)
        box.setFont(f)
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(button("کپی", slot=lambda: _copy_secret(key)))
        row.addWidget(button("ذخیره در فایل…", slot=self._save))
        row.addStretch(1)
        lay.addLayout(row)
        self.ack = QCheckBox("کلید را جای امنی نگه داشتم")
        lay.addWidget(self.ack)
        self.bb = _buttons(self, "بستن", "")
        self.bb.buttons()[0].setEnabled(False)
        self.ack.toggled.connect(self.bb.buttons()[0].setEnabled)
        for b in self.bb.buttons()[1:]:
            b.hide()
        lay.addWidget(self.bb)
        add_head(self, "shield", "کلید بازیابی تو", "فقط همین یک‌بار نمایش داده می‌شود.", "warn")

    def _save(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getSaveFileName(self, "ذخیره‌ی کلید بازیابی", "aegis-recovery-key.txt", "Text (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write("Aegis Planner — recovery key\n\n" + self.key + "\n\nKeep this file offline and private.\n")

    def reject(self) -> None:   # must acknowledge; Esc does nothing until checked
        if self.ack.isChecked():
            super().reject()

    def force_close(self) -> None:
        """Auto-lock: the key must not stay on screen over the lock screen, acknowledged or not."""
        super().reject()


class RecoveryUnlockDialog(MotionDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("بازیابی با کلید")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(12)
        lay.addWidget(label("کلید بازیابی و یک رمز اصلی تازه را وارد کن.", "Muted", True))
        self.key = QLineEdit()
        self.key.setPlaceholderText("AEGIS-XXXXX-XXXXX-…")
        self.key.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.p1, self.p2 = PasswordEdit("رمز اصلی جدید"), PasswordEdit("تکرار رمز جدید")
        for w in (self.key, self.p1, self.p2):
            lay.addWidget(w)
        self.err = _Err()
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self, "بازیابی"))
        add_head(self, "lock", "بازیابی با کلید", "با کلید بازیابی دوباره وارد شو.")

    def accept(self) -> None:
        probs = crypto.password_problems(self.p1.text())
        if not self.key.text().strip():
            self.err.setText("کلید بازیابی را وارد کن.")
        elif probs:
            self.err.setText(" ".join(probs))
        elif self.p1.text() != self.p2.text():
            self.err.setText("دو رمز یکسان نیستند.")
        else:
            super().accept()


class ImportDialog(MotionDialog):
    """Ask for the bundle's password and (if a vault is open) replace vs merge."""

    def __init__(self, parent, path: str, can_merge: bool):
        super().__init__(parent)
        self.setWindowTitle("وارد کردن ولت")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(12)
        lay.addWidget(label("رمز اصلیِ همین فایل پشتیبان را وارد کن (رمزی که هنگام ساخت آن پشتیبان داشتی).", wrap=True))
        self.pw = PasswordEdit("رمز اصلی فایل پشتیبان")
        lay.addWidget(self.pw)
        self.replace = QRadioButton("جایگزینی کامل ولت فعلی")
        self.merge = QRadioButton("ادغام (امن‌تر)")
        rep_note = label("رمز اصلی برنامه همان رمز این فایل می‌شود؛ پیش از آن از ولت فعلی نسخه‌ی پشتیبان گرفته می‌شود.", "Muted", True)
        mer_note = label("فقط موارد جدید (بر اساس شناسه) اضافه می‌شوند؛ چیزی حذف یا بازنویسی نمی‌شود.", "Muted", True)
        for r in (self.replace, self.merge):
            r.setStyleSheet("QRadioButton { padding: 2px 4px; font-weight: 600; }")
        self.replace.setChecked(not can_merge)
        self.merge.setChecked(can_merge)
        if can_merge:
            for r, n in ((self.merge, mer_note), (self.replace, rep_note)):
                lay.addWidget(r)
                n.setContentsMargins(0, 0, 30, 6)
                lay.addWidget(n)
        else:
            self.merge.setVisible(False)
        self.err = _Err()
        lay.addWidget(self.err)
        lay.addWidget(_buttons(self, "وارد کن"))
        import os as _os
        add_head(self, "shield", "وارد کردن ولت", _os.path.basename(path) or "فایل پشتیبان")

    def accept(self) -> None:
        if not self.pw.text():
            self.err.setText("رمز را وارد کن.")
            return
        super().accept()

    def mode(self) -> str:
        return "merge" if self.merge.isChecked() else "replace"
