# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window: sidebar navigation, autosave, auto-lock, reminders, palette."""
from __future__ import annotations

import datetime as dt
import json
import re
import time

from PyQt6.QtCore import QByteArray, QEasingCurve, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QGuiApplication, QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QSizePolicy, QSpacerItem, QStackedWidget, QStyle,
                             QStyledItemDelegate, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import micro
from .micro import MotionDialog
from .undo import UndoRecord
from .. import __version__
from ..core import logic
from ..core.log import friendly, log as _log
from ..core.crypto import WrongPassword
from ..core import jalali
from ..core.jalali import fa
from .anim import MOTION
from ..core.store import VaultError, VaultStore, _atomic_write
from .anim import ScrambleLabel, draw_marked, finish_stagger, mark_progress, marker_color, stagger_in
from . import anim
from .theme import AL_R
from .theme import rr as _rad
from . import dialogs, flip, moments, theme
from .auth import AuthScreen, busy, run_blocking
from .landing import WarmTooltips
from .pages import (CalendarPage, FocusPage, GoalsPage, HabitsPage, KanbanPage, NotesPage, ReportsPage,
                    TasksPage, TodayPage, TrashPage)
from .settings_page import SettingsPage

UR = Qt.ItemDataRole.UserRole


from . import icons
from .toast import ToastHost
from .fx_widgets import IconToolButton
from .lazypages import LazyPages
from .voice import VOICE
from .nav import CommandHint, NavButton, NavIndicator, SideFrame, SideToggle
from .theme_dots import ThemeDots


class ActivityFilter(QObject):
    """Records the last user input so the idle auto-lock knows when to fire."""

    def __init__(self, win):
        super().__init__(win)            # dies with the window: an app-wide filter must never outlive its owner
        self.win = win

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                         QEvent.Type.Wheel):
            self.win.last_activity = time.monotonic()
            if ev.type() == QEvent.Type.MouseButtonPress:
                micro.note_click(ev.globalPosition().toPoint())
        return False


class _PaletteDelegate(QStyledItemDelegate):
    """Command-palette rows: section headers, icon + title, shortcut hint on the far side."""

    def sizeHint(self, opt, idx):  # noqa: N802
        return QSize(opt.rect.width(), 26 if idx.data(UR)[0] == "hdr" else 36)

    def paint(self, p, opt, idx):  # noqa: N802
        kind = idx.data(UR)[0]
        pal = theme.PALETTES[self.parent().property("theme") or "dark"]
        r = QRectF(opt.rect)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if kind == "hdr":
            f = QFont(opt.font)
            f.setPointSizeF(max(8.0, f.pointSizeF() - 1.5))
            p.setFont(f)
            p.setPen(QColor(pal["muted"]))
            p.drawText(r.adjusted(14, 4, -14, 0), AL_R | Qt.AlignmentFlag.AlignVCenter, idx.data(Qt.ItemDataRole.DisplayRole))
            p.restore()
            return
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        if sel:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["soft"]))
            p.drawRoundedRect(r.adjusted(6, 2, -6, -2), _rad(8), _rad(8))
        ic = idx.data(Qt.ItemDataRole.UserRole + 2)
        if ic:
            p.drawPixmap(int(r.right() - 34), int(r.center().y() - 9), icons.pixmap(ic, pal["acc_text"] if sel else pal["muted"], 18))
        p.setPen(QColor(pal["text"]))
        p.setFont(opt.font)
        tr = r.adjusted(90, 0, -44, 0)
        dlg = self.parent().window() if self.parent() is not None else None
        needle = getattr(dlg, "_needle", "") if kind != "hdr" else ""
        k = mark_progress(getattr(dlg, "_mark_t0", 0.0) + 0.045 * idx.row(), time.monotonic()) if needle else 0.0
        draw_marked(p, tr, idx.data(Qt.ItemDataRole.DisplayRole), needle, k, marker_color(pal), QColor(pal["text"]), opt.font)
        sc = idx.data(Qt.ItemDataRole.UserRole + 1)
        if sc:
            f = QFont(opt.font)
            f.setPointSizeF(max(8.0, f.pointSizeF() - 1.5))
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(sc) + 14
            box = QRectF(r.left() + 16, r.center().y() - 10, w, 20)
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.setBrush(QColor(pal["panel2"]))
            p.drawRoundedRect(box, _rad(5), _rad(5))
            p.setPen(QColor(pal["muted"]))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, sc)
        p.restore()


class _PalettePreview(QWidget):
    """Footer of the palette: a small preview of what Enter will do with the selected row."""

    def __init__(self, pal_key: str, parent=None):
        super().__init__(parent)
        self.pal_key = pal_key
        self.title, self.meta, self.icon, self.hint = "", "", None, ""
        self.setFixedHeight(64)

    def set_info(self, title: str, meta: str, icon: str | None, hint: str = "") -> None:
        self.title, self.meta, self.icon, self.hint = title, meta, icon, hint
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = theme.PALETTES[self.pal_key]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel2"]))
        p.drawRoundedRect(r, _rad(10), _rad(10))
        if not self.title:
            return
        ib = QRectF(r.right() - 12 - 38, r.center().y() - 19, 38, 38)
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(ib, min(_rad(9), 11), min(_rad(9), 11))
        if self.icon:
            p.drawPixmap(int(ib.center().x() - 9), int(ib.center().y() - 9), icons.pixmap(self.icon, pal["acc_text"], 18))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        left = r.left() + (150 if self.hint else 14)
        fm = p.fontMetrics()
        title = fm.elidedText(self.title, Qt.TextElideMode.ElideRight, int(ib.left() - left - 14))
        p.drawText(QRectF(left, r.top() + 9, ib.left() - left - 14, 22), AL_R | Qt.AlignmentFlag.AlignVCenter, title)
        f2 = QFont(self.font())
        f2.setPointSizeF(max(8.0, f2.pointSizeF() - 1.5))
        p.setFont(f2)
        p.setPen(QColor(pal["muted"]))
        meta = p.fontMetrics().elidedText(self.meta, Qt.TextElideMode.ElideRight, int(ib.left() - left - 14))
        p.drawText(QRectF(left, r.top() + 31, ib.left() - left - 14, 20), AL_R | Qt.AlignmentFlag.AlignVCenter, meta)
        if self.hint:                                            # what Enter does, as a small key-cap on the far side
            w = p.fontMetrics().horizontalAdvance(self.hint) + 30
            box = QRectF(r.left() + 12, r.center().y() - 12, min(w, 132), 24)
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.setBrush(QColor(pal["panel"]))
            p.drawRoundedRect(box, _rad(6), _rad(6))
            p.setPen(QColor(pal["muted"]))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "↵  " + self.hint)


class Palette(MotionDialog):
    MORPH = False                                       # it has its own rise-in
    SCRIM = False                                       # it covers the window and dims it itself, so a click outside can close it
    """Ctrl+K command palette: grouped pages / tasks / notes with icons and shortcut hints.

    The dialog is as big as the window (transparent, dimmed); the glass sheet is a child panel in the upper middle. A click on
    the dim area, the × button and Esc all close it."""
    SHORTCUTS = {"today": "Ctrl+1", "tasks": "Ctrl+2", "calendar": "Ctrl+3", "kanban": "Ctrl+4", "notes": "Ctrl+5",
                 "habits": "Ctrl+6", "goals": "Ctrl+7", "focus": "Ctrl+8", "reports": "Ctrl+9"}
    PANEL_W, PANEL_MIN_H, SHADOW = 690, 500, 26

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("پرش سریع")
        self.setObjectName("Palette")
        self.setProperty("theme", win.theme)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)     # a floating glass sheet, not a window with a title bar
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("#Palette, #PalettePanel { background: transparent; }")
        self.setGeometry(self._cover())
        self.panel = QWidget(self)
        self.panel.setObjectName("PalettePanel")
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(26, 24, 26, 28)                              # room for the shadow
        lay.setSpacing(6)
        self.q = QLineEdit()
        self.q.setPlaceholderText("جستجو یا دستور… مثلاً «تسک بساز فردا ساعت ۱۰ جلسه»")
        self.q.addAction(icons.icon("search", theme.PALETTES[win.theme]["muted"], 18), QLineEdit.ActionPosition.TrailingPosition)
        self.close_btn = IconToolButton("close", "بستن (Esc)", size=34, parent=self.panel)
        self.close_btn.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.q, 1)
        top.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.list = QListWidget()
        self.list.setItemDelegate(_PaletteDelegate(self.list))
        self.list.setProperty("theme", win.theme)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; }")     # the glass shows through
        self.list.viewport().setAutoFillBackground(False)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.preview = _PalettePreview(win.theme)
        lay.addLayout(top)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.preview)
        self._place()
        self.list.currentItemChanged.connect(lambda *_: self._show_preview())
        self._needle, self._mark_t0 = "", 0.0
        self._mark_timer = QTimer(self, interval=16)             # repaints only while a highlight stroke is sweeping
        self._mark_timer.timeout.connect(self._mark_tick)
        self.q.textChanged.connect(self._fill)
        self.q.returnPressed.connect(self._go)
        self.q.installEventFilter(self)
        self.list.itemActivated.connect(lambda _i: self._go())
        self._fill("")
        self.q.setFocus()

    def _cover(self) -> QRect:
        """The whole client area of the main window, in screen coordinates (the dialog dims it and catches outside clicks)."""
        w = self.win
        return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())

    def _panel_rect(self) -> QRect:
        W, H = self.width(), self.height()
        pw = min(self.PANEL_W, max(360, W - 32))
        ph = max(self.PANEL_MIN_H, min(H - 60, 640))
        ph = min(ph, max(320, H - 24))
        return QRect((W - pw) // 2, max(10, int(H * 0.09) - 24), pw, ph)

    def _place(self) -> None:
        self.panel.setGeometry(self._panel_rect())

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "panel"):
            self._place()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        """A click on the dimmed window (outside the glass sheet) closes the palette, like every good palette."""
        inner = self.panel.geometry().adjusted(self.SHADOW - 4, self.SHADOW - 6, -(self.SHADOW - 4), -self.SHADOW)
        if not inner.contains(e.position().toPoint()):
            self.reject()
            return
        super().mousePressEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        """The dim veil over the window, then the glass: soft shadow, translucent panel, a sheen on the top edge and a hairline
        that catches the light."""
        pal = theme.PALETTES[self.win.theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = QColor(pal["bg"]).lightness() < 128
        p.fillRect(self.rect(), QColor(0, 0, 0, 120 if dark else 70))
        r = QRectF(self.panel.geometry()).adjusted(22, 20, -22, -24)
        rad = min(_rad(16), 20)
        for i in range(9, 0, -1):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 7 + (9 - i)))
            p.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), rad + i, rad + i)
        base = QColor(pal["panel"])
        base.setAlphaF(0.94)
        p.setBrush(base)
        p.drawRoundedRect(r, rad, rad)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(255, 255, 255, 20 if QColor(pal["bg"]).lightness() < 128 else 60))
        g.setColorAt(0.25, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        edge = QLinearGradient(0, r.top(), 0, r.bottom())
        e1 = QColor(pal["line"]).lighter(150)
        edge.setColorAt(0, e1)
        edge.setColorAt(1, QColor(pal["line"]))
        p.setPen(QPen(QBrush(edge), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if MOTION[0] and not getattr(self, "_rise", None):               # the sheet rises 12 px into place while the fade runs
            end = self.panel.pos()
            an = QVariantAnimation(self)
            an.setStartValue(end.y() + 12)
            an.setEndValue(end.y())
            an.setDuration(200)
            an.setEasingCurve(QEasingCurve.Type.OutCubic)
            an.valueChanged.connect(lambda y: (self.panel.move(end.x(), int(y)), self.update()))
            an.start()
            self._rise = an

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            QTimer.singleShot(0, self._maybe_dismiss)
        return super().event(ev)

    def _maybe_dismiss(self) -> None:
        if self.isVisible() and QApplication.platformName() != "offscreen" and QApplication.activeWindow() is not self:
            self.reject()                                                   # click outside = close, like every good palette

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.q and ev.type() == QEvent.Type.KeyPress and ev.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if ev.key() == Qt.Key.Key_Down else -1
            r = self.list.currentRow() + step
            while 0 <= r < self.list.count() and self.list.item(r).data(UR)[0] == "hdr":
                r += step
            if 0 <= r < self.list.count():
                self.list.setCurrentRow(r)
            return True
        return False

    def _mark_tick(self) -> None:
        self.list.viewport().update()
        if time.monotonic() - self._mark_t0 > 1.6:
            self._mark_timer.stop()

    def _fill(self, text: str) -> None:
        q = logic.fold(text.strip())
        self._needle = q
        self._mark_t0 = time.monotonic()
        if q:
            self._mark_timer.start()
        self.list.clear()
        v = self.win.store.vault
        self._quick = None
        if q:
            from ..core.nlp import parse_quick
            qt = parse_quick(text)
            if qt.is_command or qt.time_from or qt.due:
                self._quick = qt
                self._add("ساخت سریع", ("hdr", ""))
                self._add(self._quick_label(qt), ("create", ""), icon="plus", sc="Enter")
        if not q:
            self._add_recent()
        acts = self._commands(q)
        if acts:
            self._add("دستورها", ("hdr", ""))
            for label, key, icon in acts:
                self._add(label, ("cmd", key), icon=icon)
        pages = [(k, self.win.pages.title(k)) for k in self.win.pages if not q or q in logic.fold(self.win.pages.title(k))]
        if pages:
            self._add("صفحه‌ها", ("hdr", ""))
            for key, ptitle in pages:
                self._add(ptitle, ("page", key), icon=key, sc=self.SHORTCUTS.get(key))
        if q:
            ts = [x for x in v["tasks"] if q in logic.fold(x.get("title", ""))][:15]
            if ts:
                self._add("تسک‌ها", ("hdr", ""))
                for x in ts:
                    self._add(x["title"], ("task", x["id"]), icon="tasks")
            ns = [x for x in v["notes"] if q in logic.fold(x.get("title", "") + " " + logic.note_full_text(x))][:15]
            if ns:
                self._add("یادداشت‌ها", ("hdr", ""))
                for x in ns:
                    self._add(self._note_line(x, q), ("note", x["id"]), icon="notes")
        for i in range(self.list.count()):
            if self.list.item(i).data(UR)[0] != "hdr":
                self.list.setCurrentRow(i)
                break
        self._show_preview()

    RECENT_MAX = 5

    def _add_recent(self) -> None:
        """The last things opened from here (pages, tasks, notes, commands), newest first; stale entries are dropped."""
        v = self.win.store.vault
        tasks = {x["id"]: x for x in v["tasks"]}
        notes = {x["id"]: x for x in v["notes"]}
        rows = []
        for ent in self.win.recent:
            try:
                kind, key, label, icon = ent
            except (TypeError, ValueError):
                continue
            if kind == "task":
                if key not in tasks:
                    continue
                label = tasks[key].get("title") or label
            elif kind == "note":
                if key not in notes:
                    continue
                label = notes[key].get("title") or "بدون عنوان"
            elif kind == "page":
                if key not in self.win.pages:
                    continue
                label = self.win.pages.title(key)
            elif kind != "cmd":
                continue
            rows.append((label, (kind, key), icon))
        if rows:
            self._add("اخیراً", ("hdr", ""))
            for label, data, icon in rows[: self.RECENT_MAX]:
                self._add(label, data, icon=icon, sc=self.SHORTCUTS.get(data[1]) if data[0] == "page" else None)

    def _remember(self, kind: str, key: str, label: str, icon: str) -> None:
        if kind not in ("page", "task", "note", "cmd"):
            return
        ent = [kind, key, label, icon]
        old = [e for e in self.win.recent if not (isinstance(e, list) and e[:2] == ent[:2])]
        self.win.recent = ([ent] + old)[: self.RECENT_MAX]
        self.win.set_pref("palette_recent", [e for e in self.win.recent if e[0] in ("page", "cmd")])

    def _show_preview(self) -> None:
        it = self.list.currentItem()
        if it is None or it.data(UR)[0] == "hdr":
            self.preview.set_info("", "", None)
            return
        kind, key = it.data(UR)
        icon = it.data(Qt.ItemDataRole.UserRole + 2)
        v = self.win.store.vault
        title, meta, hint = it.text(), "", "اجرا"
        if kind == "task":
            x = next((t for t in v["tasks"] if t["id"] == key), None)
            if x:
                bits = []
                if x.get("done"):
                    bits.append("انجام‌شده")
                if x.get("due"):
                    bits.append(jalali.label(x["due"]))
                if x.get("timeFrom"):
                    bits.append(fa(x["timeFrom"]))
                bits.append(logic.PR_LABEL.get(x.get("pr"), ""))
                bits.append(logic.CAT_LABEL.get(x.get("cat"), ""))
                subs = x.get("subs") or []
                if subs:
                    bits.append(f"{fa(sum(1 for s in subs if s.get('done')))}/{fa(len(subs))} زیرکار")
                title, meta, hint = x.get("title", ""), " · ".join(b for b in bits if b), "ویرایش"
        elif kind == "note":
            x = next((n for n in v["notes"] if n["id"] == key), None)
            if x:
                body = " ".join(logic.note_text(x).split())
                title, meta, hint = x.get("title") or "بدون عنوان", body[:120] or "یادداشت خالی", "باز کردن"
        elif kind == "page":
            title, meta, hint = (self.win.pages.title(key) if key in self.win.pages else title), "رفتن به این صفحه", "باز کردن"
        elif kind == "create":
            meta, hint = "با همین عبارت یک تسک تازه ساخته می‌شود", "ساختن"
        elif kind == "cmd":
            meta = "اجرای فرمان"
        self.preview.set_info(title, meta, icon, hint)

    @staticmethod
    def _note_line(x: dict, q: str) -> str:
        """Title, plus a short «…snippet…» of the body when the match is there (so you can tell notes apart)."""
        title = x.get("title") or "بدون عنوان"
        if q in logic.fold(x.get("title", "")):
            return title
        body = " ".join(logic.note_text(x).split())
        i = logic.fold(body).find(q)
        if i < 0:
            return title
        a, b = max(0, i - 18), min(len(body), i + len(q) + 28)
        return f"{title} — {'…' if a else ''}{body[a:b]}{'…' if b < len(body) else ''}"

    @staticmethod
    def _quick_label(qt) -> str:
        from ..core import jalali
        bits = [qt.title or "تسک جدید"]
        if qt.due:
            d = jalali.due_to_date(qt.due)
            delta = (d - dt.date.today()).days if d else None
            bits.append({0: "امروز", 1: "فردا", 2: "پس‌فردا"}.get(delta) or jalali.label(qt.due))
        if qt.time_from:
            bits.append(fa(qt.time_from))
        return "ساخت تسک: " + " · ".join(bits)

    def _commands(self, q: str) -> list[tuple[str, str, str]]:
        """Theme switches, lock, reduce-motion... matched by Persian/English words (q is already folded)."""
        out = []
        if not q:
            return out
        cur = self.win.prefs.get("palette", theme.DEFAULT_THEME)
        for key in theme.THEME_ORDER:
            t = theme.THEMES[key]
            hay = logic.fold(f"تم {t['fa']} {t['en']} theme {key}")
            if q in hay and key != cur:
                out.append((f"تم: {t['fa']}", "theme:" + key, "palette"))
        for label, key, icon, words in (("حالت تمرکز کامل", "focus", "focus", "تمرکز focus حالت"),
                                        ("قفل برنامه", "lock", "lock", "قفل lock"),
                                        ("پشتیبان‌گیری الان", "backup", "backup", "پشتیبان backup"),
                                        ("گواهی ولت", "certificate", "lock", "گواهی ولت certificate شناسه شماره"),
                                        ("مهر هفته", "weekseal", "trophy", "مهر هفته week seal خلاصه مرور هفتگی"),
                                        ("شروع روز", "dayritual", "sun", "شروع روز صبح بخیر day start"),
                                        ("معرفی برنامه (تور)", "tour", "sparkle", "معرفی تور آموزش راهنما شروع tour intro help"),
                                        ("تازه‌های این نسخه", "whatsnew", "sparkle", "تازه‌ها تغییرات نسخه چه چیزی جدید whats new changelog"),):
            if q in logic.fold(words + " " + label):
                out.append((label, key, icon))
        return out

    def _add(self, text, data, icon=None, sc=None) -> None:
        it = QListWidgetItem(text)
        it.setData(UR, data)
        if icon:
            it.setData(Qt.ItemDataRole.UserRole + 2, icon)
        if sc:
            it.setData(Qt.ItemDataRole.UserRole + 1, sc)
        if data[0] == "hdr":
            it.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(it)

    def _go(self) -> None:
        it = self.list.currentItem()
        if not it or it.data(UR)[0] == "hdr":
            return
        kind, key = it.data(UR)
        self._remember(kind, key, it.text(), it.data(Qt.ItemDataRole.UserRole + 2) or "")
        self.accept()
        self.hold_reap()                                    # the action may open a dialog whose loop outlives the reap timer
        try:
            if kind == "create":
                self.win.quick_add(self._quick)
            elif kind == "cmd":
                self.win.run_command(key)
            elif kind == "page":
                self.win.show_page(key)
            elif kind == "task":
                self.win.edit_task_id(key)
            elif kind == "note":
                self.win.show_page("notes")
                self.win.pages["notes"].select_id(key)
        finally:
            self.release_reap()


def default_size(avail=None) -> tuple[int, int]:
    """The first-run window size: 1180x760, but never taller/wider than the usable screen (a 1080p laptop at 150% is only
    1280x720 logical pixels, and a window hanging under the taskbar hides the bottom of every page). Floors at the minimum."""
    if avail is None:
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry() if scr is not None else None
    if avail is None:
        return 1180, 760
    return max(900, min(1180, avail.width() - 48)), max(600, min(760, avail.height() - 48))


class MainWindow(QMainWindow):
    _save_done = pyqtSignal(object)            # background save finished (None = ok, else the error); emitted from the worker
    _update_result = pyqtSignal(object, bool)  # (Release | None, user_asked) from the update-check thread

    BIG_VAULT = 3000                           # items; above this autosave encrypts and writes off the UI thread

    NAV = [("today", "امروز"), ("tasks", "تسک‌ها"), ("calendar", "تقویم"), ("kanban", "کانبان"),
           ("notes", "یادداشت‌ها"), ("habits", "عادت‌ها"), ("goals", "هدف‌ها"), ("focus", "تمرکز"),
           ("reports", "گزارش‌ها"), ("trash", "سطل زباله"), ("settings", "تنظیمات")]

    def __init__(self, store: VaultStore, app: QApplication, prefs_path):
        super().__init__()
        self.store, self.app, self.prefs_path = store, app, prefs_path
        self.prefs = self._load_prefs()
        self.recent: list = [e for e in self.prefs.get("palette_recent", []) if isinstance(e, list) and e[:1] and e[0] in ("page", "cmd")]
        self.theme = theme.set_theme(self.prefs.get("palette", theme.DEFAULT_THEME))
        anim.MOTION[0] = not self.prefs.get("reduce_motion", False)
        from . import sfx
        sfx.ENABLED[0] = bool(self.prefs.get("sounds", False))
        self.last_activity = time.monotonic()
        self._notified: set[str] = set()
        self.setWindowTitle("Aegis Planner")
        self.setWindowIcon(QIcon(str(theme.asset_path("icon.png"))))
        self.resize(*default_size())
        self._restore_geometry()
        self.setMinimumSize(900, 600)

        self.root = QStackedWidget()
        self.setCentralWidget(self.root)
        self.tips = WarmTooltips(app, owner=self)
        from .micro import install_focus_fade
        install_focus_fade(app)
        self.auth = AuthScreen(store)
        self.auth.unlocked.connect(self._on_unlocked)
        self.root.addWidget(self.auth)
        from .overture import Overture
        self.overture = Overture()
        self.overture.entered.connect(self._overture_done)
        self.root.addWidget(self.overture)

        self.shell = QWidget()
        sh = QHBoxLayout(self.shell)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)
        self.side = SideFrame()
        self.side.setObjectName("Sidebar")
        self.side.setFixedWidth(self.SIDE_W)
        self._side_tight, self._side_need = False, 0
        self.side.resized.connect(self._fit_side)
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(0, 0, 0, 8)
        sl.setSpacing(0)
        brand = self._brand = QBoxLayout(QBoxLayout.Direction.LeftToRight)      # visually right-to-left in RTL
        brand.setContentsMargins(14, 14, 10, 10)
        brand.setSpacing(10)
        from .premium import BrandMark
        tile = self._tile = BrandMark(30)
        tile.status = True
        tile.setToolTip("ولت باز است")
        self._brand_names = names_w = QWidget()
        names_w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        names_w.setStyleSheet("background: transparent;")
        names = QVBoxLayout(names_w)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(2)
        b = ScrambleLabel("Aegis Planner")
        self._brand_lb = b
        b.setObjectName("Brand")
        sub = QLabel("آفلاین · رمزنگاری‌شده")
        sub.setObjectName("BrandSub")
        names.addWidget(b)
        names.addWidget(sub)
        self.side_toggle = SideToggle()
        self.side_toggle.clicked.connect(lambda: self.set_pref("side_compact", not self.prefs.get("side_compact", False)))
        brand.addWidget(tile)
        brand.addWidget(names_w, 1)
        brand.addWidget(self.side_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        sl.addLayout(brand)
        self.cmd_hint = CommandHint()
        self.cmd_hint.clicked.connect(self.open_palette)
        sl.addWidget(self.cmd_hint)
        sl.addSpacing(6)
        self._grp_lb = grp = QLabel("فضای کار")
        grp.setObjectName("GroupLabel")
        sl.addWidget(grp)
        self.stack = QStackedWidget()
        self.pages = LazyPages(self, {                        # a page is built when it is first opened (see lazypages.py)
            "today": TodayPage, "tasks": TasksPage, "calendar": CalendarPage, "kanban": KanbanPage, "notes": NotesPage,
            "habits": HabitsPage, "goals": GoalsPage, "focus": FocusPage, "reports": ReportsPage, "trash": TrashPage,
            "settings": SettingsPage}, on_build=self._page_built)
        self.nav_btns: dict[str, NavButton] = {}
        self.nav_ind = NavIndicator(self.side)              # the gilt capsule that glides to the open page's item
        for i, (key, text) in enumerate(self.NAV):
            btn = NavButton(key, text)
            btn.idx = i
            btn.toggled.connect(lambda on, b=btn: self.nav_ind.glide_to(b) if on else None)
            btn.shortcut = f"Ctrl+{i + 1}" if i < 9 else ""
            btn.setToolTip(btn.shortcut)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            if key != "settings":
                sl.addWidget(btn)
            self.nav_btns[key] = btn
        sl.addStretch(1)
        from .brand import EngraveLine
        sl.addWidget(EngraveLine())
        sl.addSpacing(6)
        sl.addWidget(self.nav_btns["settings"])        # settings sits in the footer group
        sl.addSpacing(6)
        self._tools = tools = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        tools.setContentsMargins(14, 0, 14, 0)
        tools.setSpacing(8)
        self.theme_dots = ThemeDots(theme.THEMES, theme.THEME_DOTS, self.prefs.get("palette", theme.DEFAULT_THEME))
        self.theme_dots.picked.connect(lambda k: self.set_pref("palette", k))
        self.lock_btn = IconToolButton("lock", "قفل ولت (Ctrl+L)", size=34)
        self.lock_btn.clicked.connect(self.lock)
        self.out_btn = IconToolButton("logout", "خروج از برنامه", danger=True, size=34)
        self.out_btn.clicked.connect(self._quit)
        self._tools_gap = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        tools.addWidget(self.theme_dots)
        tools.addItem(self._tools_gap)
        tools.addWidget(self.lock_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        tools.addWidget(self.out_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        sl.addLayout(tools)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 8, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.stack, 1)
        sh.addWidget(self.side)          # RTL: first item sits on the right, like the web app
        sh.addWidget(content, 1)
        self._apply_side_compact(bool(self.prefs.get("side_compact", False)))
        self.root.addWidget(self.shell)
        from .ambient import AmbientLight
        self.ambient = AmbientLight(self.stack)          # the room's light follows the clock (Settings can switch it off)
        self.ambient.enable(bool(self.prefs.get("ambient", True)))
        from .sunphase import SunWatcher
        self.sun = SunWatcher(self._sun_changed, self)
        self.sun.enable(bool(self.prefs.get("auto_theme", False)))

        self.toasts = ToastHost(self)
        self.statusBar().setSizeGripEnabled(False)
        self.status_lb = QLabel("")
        self.status_lb.setObjectName("StatusText")
        self.statusBar().addWidget(self.status_lb, 1)
        chip = QWidget()
        cl2 = QHBoxLayout(chip)
        cl2.setContentsMargins(12, 0, 12, 0)
        cl2.setSpacing(6)
        self._sec_icon = QLabel()
        self._sec_icon.setFixedSize(15, 15)
        sec_txt = QLabel("رمزنگاری AES‑256 · فقط روی همین دستگاه")
        sec_txt.setObjectName("StatusText")
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("StatusText")
        cl2.addWidget(self._sec_icon)
        cl2.addWidget(sec_txt)
        cl2.addWidget(ver)
        self.statusBar().addPermanentWidget(chip)

        # timers
        self.save_timer = QTimer(self, singleShot=True, interval=1200)
        self.save_timer.timeout.connect(self._autosave)
        self._save_done.connect(self._on_save_done)
        self._update_result.connect(self._on_update_result)
        self.idle_timer = QTimer(self, interval=10_000)
        self.idle_timer.timeout.connect(self._idle_check)
        self.remind_timer = QTimer(self, interval=30_000)
        self.remind_timer.timeout.connect(self._reminders)
        self.midnight_timer = QTimer(self, interval=60_000)
        self.midnight_timer.timeout.connect(self._day_rollover)
        self.backup_timer = QTimer(self, interval=5 * 60_000)
        self.backup_timer.timeout.connect(self.auto_backup)
        self._apply_backup_prefs()
        self._today = dt.date.today()

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip("Aegis Planner")
            self.tray.show()
        self._tray_state(locked=True)
        from . import focusfx
        focusfx.install(app)
        self._hotkey = None
        self._apply_hotkey()

        self._undo = None
        self._undo_toast = None
        self.tour = None                                   # the running spotlight tour (ui/tour.py), if any
        self._filter = ActivityFilter(self)
        app.installEventFilter(self._filter)
        for seq, fn in (("Ctrl+Z", self.perform_undo), ("Ctrl+L", self.lock), ("Ctrl+N", lambda: self.new_task(None)), ("Ctrl+K", self.open_palette), ("Ctrl+Shift+F", self.enter_focus_mode)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        for i, (key, _t) in enumerate(self.NAV[:9]):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda k=key: self.show_page(k))
        self.apply_theme()
        self.go_locked()
        if self.prefs.get("overture", True) and QGuiApplication.platformName() != "offscreen":
            self.show_overture()

    def _sun_changed(self, is_day: bool) -> None:
        """Sunrise / sunset: switch to the day or night theme (each half remembers the theme chosen for it)."""
        from .sunphase import DAY_DEFAULT, NIGHT_DEFAULT
        key = self.prefs.get("auto_theme_day", DAY_DEFAULT) if is_day else self.prefs.get("auto_theme_night", NIGHT_DEFAULT)
        if key in theme.THEMES and self.prefs.get("palette") != key:
            self.set_pref("palette", key)

    # ------------------------------------------------------------ overture ---
    def show_overture(self) -> None:
        """The cinematic opening: shown on launch (pref «overture»), before the password form."""
        from . import sfx
        self.overture.sound = bool(self.prefs.get("overture_sound", True))
        if self.overture.sound:
            sfx.prepare_film()                                                       # synthesised off the UI thread; plays when ready
        self.root.setCurrentWidget(self.overture)
        self.overture.start()

    def _overture_done(self) -> None:
        self.overture.stop()
        self.root.setCurrentWidget(self.auth)
        self.auth.show_appropriate(skip_welcome=True)
        anim.stagger_in(self.auth)                                                   # the form settles in where the dashboard panel was

    # ------------------------------------------------------------ prefs ---
    # key -> (min, max, default); values outside the range (hand-edited or damaged file) fall back to the default
    _NUM_PREFS = {"font_pt": (8, 16, 10), "autolock_min": (0, 240, 15), "backup_keep": (3, 500, 30),
                  "backup_every_h": (1, 168, 6), "remind_min": (0, 120, 10)}

    def _load_prefs(self) -> dict:
        try:
            prefs = json.loads(self.prefs_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(prefs, dict):
            return {}
        if prefs.get("palette") not in theme.THEMES:              # pre-brand-kit prefs: 29 palettes + a dark/light switch
            prefs["palette"] = "aegis-light" if prefs.get("theme") == "light" else theme.DEFAULT_THEME
        prefs.pop("theme", None)
        rec = prefs.get("palette_recent")
        if isinstance(rec, list) and any(not (isinstance(e, list) and e[:1] and e[0] in ("page", "cmd")) for e in rec):
            prefs["palette_recent"] = [e for e in rec if isinstance(e, list) and e[:1] and e[0] in ("page", "cmd")]
            try:
                _atomic_write(self.prefs_path, json.dumps(prefs, ensure_ascii=False, indent=1))
            except OSError:
                pass
        if prefs.get("brand_theme_v") != 2:                       # migrate prefs that still name a retired theme
            if prefs.get("palette") in ("aegis", "goldblack"):
                prefs["palette"] = theme.DEFAULT_THEME            # saved with the next pref, so a later choice is respected
            prefs["brand_theme_v"] = 2
        for k, (lo, hi, default) in self._NUM_PREFS.items():
            if k in prefs:
                v = prefs[k]
                prefs[k] = v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else default
        return prefs

    def set_pref(self, key: str, val) -> None:
        if self.prefs.get(key) == val:
            return
        self.prefs[key] = val
        try:
            _atomic_write(self.prefs_path, json.dumps(self.prefs, ensure_ascii=False, indent=1))
        except OSError as exc:
            _log.warning("prefs not saved: %s", type(exc).__name__)
        if key == "global_hotkey":
            self._apply_hotkey()
        if key == "side_compact":
            self._apply_side_compact(bool(val), animate=True)
        if key in ("font_pt", "palette"):
            self.apply_theme()
        if key == "reduce_motion":
            anim.MOTION[0] = not val
        if key == "auto_theme" and hasattr(self, "sun"):
            self.sun.enable(bool(val))
        if key == "palette" and val in theme.THEMES and self.prefs.get("auto_theme", False):
            slot = "auto_theme_day" if theme.THEMES[val]["mode"] == "light" else "auto_theme_night"
            if self.prefs.get(slot) != val:                       # choosing a theme by hand while auto is on re-teaches that half of the day
                self.set_pref(slot, val)
        if key == "ambient" and hasattr(self, "ambient"):
            self.ambient.enable(bool(val))
        if key == "density":
            tp = self.pages.peek("tasks")
            if tp is not None:
                tp.apply_density()
        if key == "sounds":
            from . import sfx
            sfx.ENABLED[0] = bool(val)
            if val:
                sfx.play("tick")                      # a little preview when switched on
        if key.startswith("backup_"):
            self._apply_backup_prefs()

    def apply_theme(self) -> None:
        # a theme switch restyles the whole window: freeze paints, skip list animations (nothing moves), and let a picture
        # of the old look melt away over the new one so the change reads as one soft step instead of a flicker
        shell = getattr(self, "shell", None)
        snap = None
        if shell is not None and shell.isVisible() and anim.MOTION[0] and self.store.is_unlocked \
                and shell.width() > 40 and QApplication.platformName() != "offscreen":
            snap = shell.grab()
        flip.SUSPEND[0] = True
        if shell is not None:
            shell.setUpdatesEnabled(False)
        try:
            self._apply_theme_now()
        finally:
            flip.SUSPEND[0] = False
            if shell is not None:
                shell.setUpdatesEnabled(True)
        if snap is not None:
            flip.melt(shell, snap)

    def _apply_theme_now(self) -> None:
        self.theme = theme.set_theme(self.prefs.get("palette", theme.DEFAULT_THEME))
        from . import charts
        charts.CHART[:] = theme.chart_colors(self.theme)
        self._paint_nav_icons()
        if hasattr(self, "_tile"):
            self._tile.update()
        if hasattr(self, "_sec_icon"):
            self._sec_icon.setPixmap(icons.pixmap("shield", theme.PALETTES[self.theme]["ok"], 15))
        if hasattr(self, "tips"):
            self.tips.set_theme(self.theme)
        if hasattr(self, "theme_dots"):
            self.theme_dots.set_current(self.prefs.get("palette", theme.DEFAULT_THEME))
        f = self.app.font()
        pt = int(self.prefs.get("font_pt", 10))
        if f.pointSize() != pt:                                   # a font change re-lays-out every widget: only when it really changed
            f.setPointSize(pt)
            self.app.setFont(f)
        theme.apply_palette(self.app, self.theme)
        theme.install_stylesheet(self.app, theme.stylesheet(self.theme))
        if self.store.is_unlocked:
            self.refresh_all()
        for w in self.findChildren(QWidget):   # painted widgets read PALETTES at paint time
            if w.isVisible():
                w.update()

    # ---------------------------------------------------------- lock state ---
    def _apply_hotkey(self) -> None:
        """Ctrl+Alt+Space from anywhere -> quick-add box (Windows; a preference, on by default)."""
        from . import hotkey
        want = bool(self.prefs.get("global_hotkey", True)) and hotkey.available()
        if want and self._hotkey is None:
            self._hotkey = hotkey.GlobalHotkey(QApplication.instance(), self.show_quick_add)
        if self._hotkey is not None:
            if want:
                if not self._hotkey.enable():
                    self.status_lb.setText("میانبر سراسری فعال نشد؛ Ctrl+Alt+Space و دو ترکیب جایگزین را برنامه‌ی دیگری گرفته است")
                elif self._hotkey.fell_back:
                    self.status_lb.setText(f"Ctrl+Alt+Space دست برنامه‌ی دیگری است؛ افزودن سریع روی {self._hotkey.label} فعال شد")
                self.hotkey_label = self._hotkey.label
                sp = self.pages.get("settings") if hasattr(self, "pages") else None
                if sp is not None and hasattr(sp, "sync_hotkey_text"):
                    sp.sync_hotkey_text()
            else:
                self._hotkey.disable()

    def show_quick_add(self) -> None:
        """Open the quick-add box (from the hotkey or the tray); works while the window is hidden or minimised."""
        from .quickadd import QuickAdd
        old = getattr(self, "_quick_add_box", None)
        if old is not None and old.isVisible():
            old.activateWindow()
            old.q.setFocus()
            return
        box = QuickAdd(self)
        self._quick_add_box = box
        box.popup()

    def _tray_state(self, locked: bool) -> None:
        """The tray icon mirrors the vault: a dimmed shield with a padlock when locked, the shield with a green pip when open."""
        self._tray_locked = locked
        if self.tray is not None:
            from .brand import tray_icon
            self.tray.setIcon(tray_icon(locked))
            self.tray.setToolTip("Aegis Planner — قفل" if locked else "Aegis Planner — باز")

    def go_locked(self) -> None:
        if self.tour is not None:
            self.tour.finish(False)
        self._tray_state(True)
        for t in (self.idle_timer, self.remind_timer, self.midnight_timer):
            t.stop()
        self.root.setCurrentWidget(self.auth)
        self.auth.show_appropriate()
        self.setWindowTitle("Aegis Planner — قفل")

    def show_whatsnew(self, force: bool = False) -> None:
        """What changed in this version (once after an update; ``force`` = the person asked, e.g. from Settings → About)."""
        from .whatsnew import WhatsNew, entries_for
        if not self.store.is_unlocked:                  # the 900 ms timer may fire after an instant lock
            return
        if entries_for(__version__):
            WhatsNew(self).exec()
        elif not force:
            self.set_pref("seen_version", __version__)

    def show_onboarding(self) -> None:
        """The first-run spotlight tour."""
        self.show_tour()

    def show_tour(self) -> None:
        """Start (or restart) the spotlight tour: first run, Settings → About, Ctrl+K «معرفی»."""
        if not self.store.is_unlocked:
            return
        from . import tour
        tour.start(self)

    def show_feature(self, key: str) -> None:
        """«نشانم بده» in the what's-new card: open the page and put a spotlight on the new thing."""
        if not self.store.is_unlocked:
            return
        from . import tour
        tour.show_feature(self, key)

    def _page_built(self, _key: str, page: QWidget) -> None:
        """A page built lazily after unlock still gets what ``_on_unlocked`` gives the rest: quiet scrollbars, wheel glide,
        and accessible names on icon-only buttons."""
        self.stack.addWidget(page)
        from . import scrollfx
        from .a11y import ensure_names
        scrollfx.attach(page)
        ensure_names(page)

    def _on_unlocked(self) -> None:
        from . import scrollfx
        scrollfx.attach(self.shell)
        from .a11y import ensure_names
        ensure_names(self.shell)
        if QGuiApplication.platformName() != "offscreen":               # never in headless tests
            if not self.prefs.get("onboarded"):
                QTimer.singleShot(900, self.show_onboarding)            # first run: the tour (it also marks the version seen)
            elif self.prefs.get("seen_version") != __version__:
                QTimer.singleShot(900, self.show_whatsnew)              # after an update: what changed, once
            elif not getattr(self.auth, "created_now", False):
                QTimer.singleShot(2100, self._maybe_day_start)          # the daily good-morning card, after the vault has opened
                QTimer.singleShot(4200, self.offer_week_seal)
                QTimer.singleShot(6500, self.maybe_check_updates)
        self.last_activity = time.monotonic()
        self._notified.clear()
        if logic.archive_old_tasks(self.store.vault):
            self.schedule_save()                 # persist the move, or it would be redone (and lost on a crash) every unlock
        if logic.extend_series(self.store.vault):
            self.schedule_save()
        fp = self.pages.peek("focus")
        if fp is not None:
            fp.apply_pending()
        self._tray_state(False)
        self.root.setCurrentWidget(self.shell)
        self.refresh_all()
        self.show_page("today")
        self._brand_lb.replay(900)
        self.enter_page("today")
        if getattr(self.auth, "created_now", False):
            self.auth.created_now = False
            moments.vault_born(self.shell, VOICE["vault_born"])
        else:
            moments.unlock_bloom(self.shell)
        fw = QApplication.focusWidget()
        if fw is not None:
            fw.clearFocus()          # no stray focus ring on the first nav button
        for t in (self.idle_timer, self.remind_timer, self.midnight_timer, self.backup_timer):
            t.start()
        self.setWindowTitle("Aegis Planner")
        self._reminders()
        if self.store.backup_error:
            self.status_lb.setText("⚠ پشتیبان خودکار انجام نشد: پوشه‌ی پشتیبان در دسترس نیست")

    def _paint_nav_icons(self) -> None:
        """Nav items paint their own glyphs from the live palette; a repaint is all a theme change needs."""
        for b in getattr(self, "nav_btns", {}).values():
            b.update()

    SIDE_W, RAIL_W = 224, 64

    def _fit_side(self) -> None:
        """The full sidebar needs ~620 px of height; a 1366x768 laptop at 125% gives the window ~550. The window has an explicit
        minimum size, so Qt does not stop the layout from squashing children - and the brand block (the first thing a person
        sees) was the one that got crushed. Below what it needs the sidebar goes *tight*: 32 px items, no «فضای کار» label,
        a slimmer brand block. It returns to the full look as soon as the height allows (the need is measured while full)."""
        lay = self.side.layout()
        if lay is None:
            return
        h = self.side.height()
        if not self._side_tight:
            self._side_need = lay.minimumSize().height()
            if h and h < self._side_need:
                self._set_side_tight(True)
        elif h >= self._side_need:
            self._set_side_tight(False)

    def _set_side_tight(self, on: bool) -> None:
        self._side_tight = on
        for b in [*self.nav_btns.values(), self.cmd_hint]:
            b.set_tight(on)
        self._grp_lb.setVisible(not on and not self.prefs.get("side_compact", False))
        m = self._brand.contentsMargins()
        self._brand.setContentsMargins(m.left(), 8 if on else 14, m.right(), 4 if on else 10)
        self.side.layout().invalidate()
        self.nav_ind.sync(False)

    def _apply_side_compact(self, on: bool, animate: bool = False) -> None:
        """Full sidebar <-> icon rail. Everything stays reachable; labels move into tooltips."""
        an = getattr(self, "_side_an", None)
        if an is not None:
            an.stop()
        start, target = self.side.p, (1.0 if on else 0.0)
        if animate and anim.MOTION[0] and self.isVisible() and abs(start - target) > 0.001:
            if on:                                       # collapsing: the wide-only widgets go first
                for w in (self._brand_names, self._grp_lb, self.theme_dots):
                    w.setVisible(False)
            an = self._side_an = QVariantAnimation(self)
            an.setDuration(260)
            an.setEasingCurve(QEasingCurve.Type.InOutCubic)
            an.setStartValue(start)
            an.setEndValue(target)

            def step(v) -> None:
                self.side.p = float(v)
                self.side.setFixedWidth(round(self.SIDE_W + (self.RAIL_W - self.SIDE_W) * float(v)))
                self.nav_ind.sync(False)
                self.side.update()
            an.valueChanged.connect(step)
            an.finished.connect(lambda: self._apply_side_compact(on))
            an.start()
            return
        self.side.p = target
        self.side.setFixedWidth(self.RAIL_W if on else self.SIDE_W)
        for w in (self._brand_names, self._grp_lb, self.theme_dots):
            w.setVisible(not on)
        for b in [*self.nav_btns.values(), self.cmd_hint]:
            b.set_compact(on)
        self._tools.setDirection(QBoxLayout.Direction.TopToBottom if on else QBoxLayout.Direction.LeftToRight)
        self._tools.setContentsMargins(15 if on else 14, 0, 15 if on else 14, 0)
        self._tools_gap.changeSize(0, 0, QSizePolicy.Policy.Fixed if on else QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Minimum)
        self._tools.invalidate()
        self._brand.setDirection(QBoxLayout.Direction.TopToBottom if on else QBoxLayout.Direction.LeftToRight)
        self._brand.setContentsMargins(17 if on else 14, 14, 17 if on else 10, 10)
        self._brand.setAlignment(self._tile, Qt.AlignmentFlag.AlignHCenter if on else Qt.AlignmentFlag.AlignVCenter)
        self._brand.setAlignment(self.side_toggle, Qt.AlignmentFlag.AlignHCenter if on else Qt.AlignmentFlag.AlignVCenter)
        self.side_toggle.setToolTip("باز کردن منو" if on else "جمع کردن منو")
        if self._side_tight:                                 # the compact pass above reset the brand margins / group label
            self._set_side_tight(True)
        self.nav_ind.sync(False)

    def _quit(self) -> None:
        self.close()

    def _close_dialogs(self) -> None:
        self._close_editor(discard=True)                      # the page editor goes without its unsaved-work question
        for d in self.findChildren(QDialog):
            if d.isVisible():
                getattr(d, "force_close", d.reject)()

    def lock(self, auto: bool = False) -> None:
        if not self.store.is_unlocked:
            return
        self._flush_notes()
        try:
            self._save_now()
        except (VaultError, OSError) as e:
            if auto:
                self.status_lb.setText(f"⚠ قفل خودکار انجام نشد چون ذخیره نشد ({friendly(e)})")
                self.save_timer.start(5000)
            else:
                dialogs.warn(self, "ذخیره‌سازی", f"ذخیره نشد: {friendly(e)}\nقفل انجام نشد تا داده‌ات از دست نرود.")
            return
        self._close_dialogs()
        self._drop_undo()
        self.toasts.clear()                           # toasts carry task titles: none may linger over the lock screen
        self.recent = [e for e in self.recent if e[0] in ("page", "cmd")]
        fm = getattr(self, "_focus_mode", None)
        if fm is not None:
            fm.poll.stop()
            fm.hide()
        self._close_editor(discard=True)
        self._exit_backup()
        self.backup_timer.stop()
        self.store.lock()
        for _k, p in self.pages.built():   # drop decrypted content from widgets (pages never opened hold none)
            if hasattr(p, "unbind"):
                p.unbind()
        snap = self.shell.grab() if self.isVisible() and anim.MOTION[0] else None      # what the doors will close over
        self._clear_widgets()
        self.go_locked()
        if snap is not None:
            from . import sfx
            sfx.play("close")
            moments.lock_close(self.root, snap)

    def _flush_notes(self) -> None:
        """Save the note being typed - only if the notes page has ever been opened."""
        n = self.pages.peek("notes")
        if n is not None:
            n.flush()

    def _clear_widgets(self) -> None:
        n = self.pages.peek("notes")
        if n is not None:
            n._loading = True
            n.title_in.clear(); n.body.clear(); n.list.clear(); n.q.clear()
            n._loading = False
        for key in ("today", "tasks", "kanban", "trash", "calendar"):
            p = self.pages.peek(key)
            if p is None:
                continue
            for name in ("overdue", "today", "table", "day_list", "list"):
                w = getattr(p, name, None)
                if w is not None:
                    (w.setRowCount(0) if hasattr(w, "setRowCount") else w.clear())
        kb = self.pages.peek("kanban")
        if kb is not None:
            for lw in kb.lists.values():
                lw.clear()
        for _key, page in self.pages.built():
            for t in page.findChildren(QTimer):
                if t.isSingleShot() and t.isActive():
                    t.stop()

    def _idle_check(self) -> None:
        if busy():
            return
        mins = int(self.prefs.get("autolock_min", 15))
        if mins and time.monotonic() - self.last_activity > mins * 60:
            self.lock(auto=True)

    # ----------------------------------------------------------- persist ---
    def schedule_save(self) -> None:
        self.store.dirty = True
        self.save_timer.start()

    def _autosave(self) -> None:
        """Timer-driven save: never raise into Qt; retry shortly if the disk hiccuped
        (antivirus lock, full disk, USB drive removed...)."""
        if busy():                              # an import / re-key owns the vault right now
            self.save_timer.start()
            return
        try:
            self._save_now(background=True)
        except (VaultError, OSError) as e:
            self.status_lb.setText(f"⚠ ذخیره نشد ({friendly(e)}) — دوباره تلاش می‌کنم")
            self.save_timer.start(5000)
        except Exception as e:  # noqa: BLE001
            _log.warning("autosave failed: %s", type(e).__name__)
            self.status_lb.setText("⚠ ذخیره نشد — دوباره تلاش می‌کنم")
            self.save_timer.start(5000)

    # ------------------------------------------------------- auto backup ---
    BACKUP_EVERY = [(1, "هر ساعت"), (3, "هر ۳ ساعت"), (6, "هر ۶ ساعت"), (12, "هر ۱۲ ساعت"), (24, "روزانه"), (168, "هفتگی")]

    def _apply_backup_prefs(self) -> None:
        p = self.prefs
        self.store.keep_backups = int(p.get("backup_keep", 30))
        self.store.set_backup_dir(p.get("backup_dir") or None)
        on = bool(p.get("backup_auto", True))
        self.store.unlock_backup_s = int(p.get("backup_every_h", 6)) * 3600 if on else 0

    def backup_now(self, reason: str = "manual", min_age_s: float = 0, quiet: bool = False):
        """Save pending edits, then copy the encrypted vault into the backup folder. Never raises."""
        if not self.store.is_unlocked:
            return None
        try:
            self._flush_notes()
            self._save_now()
            dst = self.store.snapshot(reason, min_age_s=min_age_s)
        except (VaultError, OSError) as e:
            self.store.backup_error = friendly(e)
            self.status_lb.setText(f"⚠ پشتیبان‌گیری ناموفق بود: {friendly(e)}")
            return None
        self.store.backup_error = None
        if dst and not quiet:
            self.status_lb.setText("پشتیبان رمزنگاری‌شده گرفته شد · " + fa(dt.datetime.now().strftime("%H:%M")))
        sp = self.pages.peek("settings")
        if dst and sp is not None:
            sp.refresh_backup()
        return dst

    def auto_backup(self) -> None:
        if busy():
            return
        if self.prefs.get("backup_auto", True):
            self.backup_now("auto", min_age_s=int(self.prefs.get("backup_every_h", 6)) * 3600 - 60)

    def _exit_backup(self) -> None:
        if self.prefs.get("backup_auto", True) and self.prefs.get("backup_on_exit", True):
            self.backup_now("exit", min_age_s=15 * 60, quiet=True)

    def _vault_items(self) -> int:
        v = self.store.vault or {}
        return sum(len(v.get(k, ())) for k in ("tasks", "notes", "journal", "habits", "archive", "trash"))

    def _on_save_done(self, err) -> None:
        if err is None:
            self.status_lb.setText(VOICE["saved"] + " " + fa(dt.datetime.now().strftime("%H:%M:%S")))
        elif self.store.is_unlocked:
            _log.warning("background save failed: %s", type(err).__name__)
            self.status_lb.setText(f"⚠ ذخیره نشد ({friendly(err) if isinstance(err, (VaultError, OSError)) else 'خطای نامشخص'}) — دوباره تلاش می‌کنم")
            self.save_timer.start(5000)
        elif self.store.dirty:
            self.save_timer.start(5000)

    def _save_now(self, background: bool = False) -> None:
        if not background:
            self.store.wait_idle()                        # a background write in flight (or one that failed) must be settled first
        if self.store.is_unlocked and self.store.dirty:
            if background and self._vault_items() >= self.BIG_VAULT:
                if not self.store.save_async(self._save_done.emit):
                    self.save_timer.start(1000)           # the previous write is still going: try again shortly
                return
            self.store.save()
            self.status_lb.setText(VOICE["saved"] + " " + fa(dt.datetime.now().strftime("%H:%M:%S")))

    def changed(self, msg: str | None = None, undo=None) -> None:
        """A page mutated the vault: autosave and refresh every page. ``undo`` (an UndoRecord taken BEFORE the action)
        adds a «واگرد» button to the toast for ten seconds."""
        self._drop_undo()
        self.schedule_save()
        self.refresh_all()
        if msg:
            self.status_lb.setText(msg)
            if undo is not None and self.isVisible():
                self._undo = undo
                self._undo_toast = self.toasts.push(msg, "info", "انجام شد", 10000, action=("واگرد", self.perform_undo))

    def vault_replaced(self) -> None:
        """Restore, merge or replace swapped the vault contents: the pending undo no longer applies and every page
        must rebind to the new objects."""
        self._drop_undo()
        self.refresh_all()

    def snapshot(self, ids) -> UndoRecord:
        return UndoRecord(self.store.vault, ids)

    def _drop_undo(self) -> None:
        """Any other change makes the pending undo unsafe: withdraw it (and its toast)."""
        t, self._undo, self._undo_toast = self._undo, None, None
        if t is not None:
            try:
                self._undo_toast_close(t)
            except RuntimeError:
                pass

    def _undo_toast_close(self, _rec) -> None:
        for t in list(self.toasts._toasts):
            if t.action and t.action[1] == self.perform_undo:
                t.close_toast()

    def perform_undo(self) -> None:
        rec = self._undo
        if rec is None or not self.store.is_unlocked:
            return
        self._undo = None
        rec.apply(self.store.vault)
        self.changed("بازگردانی شد")

    def row_action(self, kind: str, tid: str) -> None:
        """Hover actions of a task row (edit / move to today-or-tomorrow / trash); every change is undoable."""
        if not self.store.is_unlocked:
            return
        x = next((t for t in self.store.vault["tasks"] if t["id"] == tid), None)
        if x is None:
            return
        if kind == "edit":
            self.edit_task_id(tid)
        elif kind == "later":
            over = logic.is_overdue(x, dt.date.today())
            rec = self.snapshot([tid])
            x["due"] = jalali.date_to_due(dt.date.today() + dt.timedelta(days=0 if over else 1))
            if x.get("dueEnd"):
                x["dueEnd"] = None
            self.changed("به امروز منتقل شد" if over else "به فردا منتقل شد", undo=rec)
        elif kind == "trash":
            rec = self.snapshot([tid])
            logic.remove_task(self.store, x)
            self.changed("تسک به سطل زباله رفت", undo=rec)

    def fly_done(self, start_global) -> None:
        """A task was just ticked at ``start_global``: a light flies to the counter that is about to change."""
        if not anim.MOTION[0] or not self.isVisible() or not self.store.is_unlocked:
            return
        from . import flight
        today = self.pages["today"]
        on_today = self.stack.currentWidget() is today and today.isVisible()
        tgt = today.tiles["done"] if on_today else self.nav_btns.get("today")
        if tgt is None or not tgt.isVisible():
            return
        if on_today:
            tgt.hold(flight.MS)
        acc = QColor(theme.PALETTES[self.theme]["accent2"])
        flight.launch(self, start_global, tgt, acc, on_land=tgt.land, anchor=tgt.anchor())

    def _update_badges(self) -> None:
        """«امروز» carries the count of open tasks due today or late (red when something is overdue)."""
        v = self.store.vault
        today = dt.date.today()
        late = due = 0
        for x in v.get("tasks", []):
            if x.get("done") or logic.is_event(x) or x.get("deleted"):
                continue
            d = logic.task_date(x)
            if d is None:
                continue
            if d < today:
                late += 1
            elif d == today:
                due += 1
        self.nav_btns["today"].set_badge(late + due, warn=late > 0)

    def refresh_all(self) -> None:
        if not self.store.is_unlocked:
            return
        self._update_badges()
        # Only the visible page is rebuilt now; the rest refresh when they are opened (show_page). With thousands of
        # tasks this keeps every edit instant instead of re-filling all eleven pages.
        cur = self.stack.currentWidget()
        for key, p in self.pages.built():
            if p is not cur and self.stack.count() > 1:
                continue
            if key == "notes" and p._save_timer.isActive():
                continue
            p.refresh()
            p.one_accent()

    def _restore_geometry(self) -> None:
        """Reopen where the user left the window (only if that spot still exists on a connected screen)."""
        import base64
        raw = self.prefs.get("win_geom")
        if not isinstance(raw, str):
            return
        try:
            self.restoreGeometry(QByteArray(base64.b64decode(raw)))
        except (ValueError, TypeError):
            return
        if not any(s.availableGeometry().intersects(self.frameGeometry()) for s in QGuiApplication.screens()):
            self.resize(*default_size())
            self.move(QGuiApplication.primaryScreen().availableGeometry().center() - self.rect().center())

    def closeEvent(self, e) -> None:  # noqa: N802
        import base64
        try:
            if self.store.is_unlocked:
                self._flush_notes()
                self._save_now()
                self._exit_backup()
        except (VaultError, OSError) as exc:
            if not dialogs.ask(self, "ذخیره‌سازی", f"ذخیره‌ی نهایی ناموفق بود: {friendly(exc)}\n\nاگر الان ببندی، تغییرات ذخیره‌نشده از بین می‌رود.",
                               True, "بستن بدون ذخیره"):
                e.ignore()
                self.save_timer.start(5000)
                return
        if getattr(self, "_hotkey", None) is not None:
            self._hotkey.disable()
        try:
            self.set_pref("win_geom", base64.b64encode(bytes(self.saveGeometry())).decode("ascii"))
        except Exception:  # noqa: BLE001 - cosmetic; never block closing
            pass
        super().closeEvent(e)

    # ------------------------------------------------------- navigation ---
    def show_page(self, key: str) -> None:
        if not self.store.is_unlocked:
            return
        if not self._close_editor():                                  # unsaved edits and the user chose to stay
            return
        self._flush_notes()
        prev = self.stack.currentWidget()
        changed = prev is not self.pages[key]
        snap = prev.grab() if changed and prev is not None and prev.isVisible() and anim.MOTION[0] else None
        if changed and prev is not None:
            finish_stagger(prev)                      # an unfinished entrance snaps to rest before we leave the page
        self.stack.setCurrentWidget(self.pages[key])
        for k, b in self.nav_btns.items():
            b.setChecked(k == key)
        self._paint_nav_icons()
        sk = None
        if changed and getattr(self.pages[key], "skeleton", False):         # data-heavy page: placeholders first, then the numbers
            from . import skeleton
            sk = skeleton.cover(self.pages[key])
        self.pages[key].refresh()
        if sk is not None:
            sk.finish()
        self.pages[key].one_accent()
        from .a11y import ensure_names
        ensure_names(self.pages[key])
        if snap is not None:
            flip.crossfade(self.stack, snap)
        if changed:                                   # the page title shuffles into place
            for lb in self.pages[key].findChildren(ScrambleLabel):
                if lb.objectName() == "H1":
                    lb.replay(560)
                    break
            self.enter_page(key)

    def enter_page(self, key: str) -> None:
        """Cards of the page slide in one after another (after the layout has settled)."""
        page = self.pages[key]
        QTimer.singleShot(0, lambda: stagger_in(page) if self.stack.currentWidget() is page else None)

    def open_palette(self) -> None:
        if self.store.is_unlocked and self.tour is None:
            Palette(self).exec()

    # ------------------------------------------------- shared actions ---
    def new_task(self, due: dict | None, defaults: dict | None = None) -> None:
        if not self.store.is_unlocked or self.tour is not None:
            return
        self._open_editor(None, due, defaults)

    # ---- editors (task, goal, habit) are full pages inside the window, not floating dialogs
    _editor = None
    _editor_prev = None

    def open_page_editor(self, d, on_save) -> None:
        """Show an embedded editor over the current page. ``on_save(dialog)`` runs after Save; Cancel just returns."""
        if self._editor is not None:                                   # one editor at a time: a second request keeps the first
            d.deleteLater()
            return
        prev = self.stack.currentWidget()
        self._editor, self._editor_prev = d, prev
        snap = prev.grab() if prev is not None and prev.isVisible() and anim.MOTION[0] else None
        d.finished.connect(lambda r, d=d: self._editor_finished(d, r, on_save))
        self.stack.addWidget(d)
        self.stack.setCurrentWidget(d)
        from .a11y import ensure_names
        ensure_names(d)
        if snap is not None:
            flip.crossfade(self.stack, snap)
        (getattr(d, "title", None) or getattr(d, "name", None)).setFocus()

    def _open_editor(self, task: dict | None, due: dict | None = None, defaults: dict | None = None) -> None:
        if self._editor is not None:
            return
        d = dialogs.TaskDialog(self, self.store.vault, task, due, defaults, embedded=True)
        is_new = task is None

        def saved(dlg) -> None:
            t = dlg.result_task()
            if is_new:
                self.store.vault["tasks"].append(t)
                if t.get("rep") not in (None, "none") and t.get("due"):
                    logic.materialize_series(self.store.vault, t)
                self.changed("تسک اضافه شد")
            else:
                self.changed("تسک ذخیره شد")
        self.open_page_editor(d, saved)

    def edit_goal(self, goal: dict | None = None) -> None:
        if not self.store.is_unlocked:
            return
        d = dialogs.GoalDialog(self, goal, embedded=True)

        def saved(dlg) -> None:
            g = dlg.result_goal()
            if goal is None:
                self.store.vault["goals"].append(g)
            self.changed()
        self.open_page_editor(d, saved)

    def edit_habit(self, habit: dict | None = None) -> None:
        if not self.store.is_unlocked:
            return
        d = dialogs.HabitDialog(self, habit, embedded=True)

        def saved(dlg) -> None:
            h = dlg.result_habit()
            if habit is None:
                self.store.vault["habits"].append(h)
            self.changed()
        self.open_page_editor(d, saved)

    def _editor_finished(self, d, result: int, on_save) -> None:
        self._editor = None
        prev, self._editor_prev = self._editor_prev, None
        snap = d.grab() if d.isVisible() and anim.MOTION[0] else None
        if prev is not None:
            self.stack.setCurrentWidget(prev)
        self.stack.removeWidget(d)
        d.hide()
        d.deleteLater()
        if snap is not None:
            flip.crossfade(self.stack, snap)
        if result == 1:
            on_save(d)                                                 # the widget lives until the event loop runs again

    def _close_editor(self, discard: bool = False) -> bool:
        """Leave the editor (it may ask about unsaved edits). Returns True when it is gone."""
        d = self._editor
        if d is not None:
            d._discard = discard
            d.reject()
        return self._editor is None

    def enter_focus_mode(self, task_id: str | None = None, start: bool = False) -> None:
        """Dim the whole window down to the timer and one task (a given one, and the timer running, when asked)."""
        if not self.store.is_unlocked:
            return
        from .focusmode import FocusMode
        if getattr(self, "_focus_mode", None) is None:
            self._focus_mode = FocusMode(self, self.root)
        fm = self._focus_mode
        if task_id:
            fm.task_id = task_id                                   # enter() keeps it while it is still open
        fm.enter()
        if start and not fm.page.running:
            fm._toggle()

    def quick_add(self, qt) -> None:
        """Palette quick-add: the task is created straight away (undoable); a toast offers «واگرد»."""
        if not self.store.is_unlocked or qt is None:
            return
        kw = {"due": qt.due}
        if qt.time_from:
            kw["timeFrom"] = qt.time_from
        t = logic.new_task(qt.title or "تسک جدید", **kw)
        rec = self.snapshot([t["id"]])                                   # taken before: undo = "this id never existed"
        self.store.vault["tasks"].append(t)
        self.changed("تسک ساخته شد: " + t["title"], undo=rec)

    def run_command(self, key: str) -> None:
        if key.startswith("theme:"):
            self.set_pref("palette", key[6:])
        elif key == "focus":
            self.enter_focus_mode()
        elif key == "lock":
            self.lock()
        elif key == "backup" and hasattr(self, "backup_now"):
            self.backup_now()
        elif key == "certificate":
            self.show_certificate()
        elif key == "weekseal":
            self.show_week_seal()
        elif key == "dayritual":
            self.show_day_start(force=True)
        elif key == "tour":
            QTimer.singleShot(80, self.show_tour)
        elif key == "whatsnew":
            QTimer.singleShot(80, lambda: self.show_whatsnew(force=True))

    def show_certificate(self) -> None:
        """The vault's certificate card (number, birth date, non-secret id). Needs an unlocked vault."""
        if not self.store.is_unlocked:
            return
        from .certificate import CertificateDialog
        CertificateDialog(self).exec()

    def edit_task_id(self, tid: str) -> None:
        x = next((t for t in self.store.vault["tasks"] if t["id"] == tid), None)
        if not x:
            return
        self._open_editor(x)

    def notify(self, msg: str, beep: bool = False, kind: str = "info", title: str | None = None) -> None:
        """Status line + a glass toast inside the window; the system tray balloon only when the window is not the
        one in front (so the same message is never shown twice)."""
        self.status_lb.setText(msg)
        on_screen = self.isVisible() and not self.isMinimized()
        if on_screen:
            self.toasts.push(msg, kind, title)
        if self.tray and not (on_screen and self.isActiveWindow()):
            self.tray.showMessage(title or "Aegis Planner", msg, QSystemTrayIcon.MessageIcon.Information, 6000)
        if beep:
            from . import sfx
            if not sfx.play("bell"):
                QApplication.beep()

    def archive_old(self) -> None:
        n = logic.archive_old_tasks(self.store.vault)
        self.changed(f"{fa(n)} تسک بایگانی شد" if n else "چیزی برای بایگانی نبود")

    # ---- backup / export
    def export_vault(self) -> None:
        name = f"aegis-vault-{dt.date.today().isoformat()}.aegis"
        path, _ = QFileDialog.getSaveFileName(self, "خروجی ولت رمزنگاری‌شده", name, "Aegis vault (*.aegis)")
        if not path:
            return
        try:
            self._flush_notes()
            self.store.export_bundle(path)
        except (VaultError, OSError) as e:
            dialogs.warn(self, "خروجی ولت", friendly(e))
            return
        sp = self.pages.peek("settings")
        if sp is not None:
            sp.refresh()
        dialogs.info(self, "خروجی ولت", f"پشتیبان رمزنگاری‌شده ذخیره شد:\n{path}\n\nفقط با رمز اصلی همین ولت باز می‌شود.")

    def import_vault(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "وارد کردن ولت", "", "Aegis vault (*.aegis *.json);;All files (*)")
        if not path:
            return
        try:
            bundle = VaultStore.read_bundle(path)
        except VaultError as e:
            dialogs.warn(self, "وارد کردن", friendly(e))
            return
        d = dialogs.ImportDialog(self, path, can_merge=True)
        if not d.exec():
            return
        self._flush_notes()
        try:
            if d.mode() == "merge":
                added = run_blocking(lambda: self.store.import_merge(bundle, d.pw.text()))
                total = sum(added.values())
                self.vault_replaced()
                dialogs.info(self, "ادغام", f"{fa(total)} مورد جدید اضافه شد.")
            else:
                run_blocking(lambda: self.store.import_replace(bundle, d.pw.text()))
                self.vault_replaced()
                dialogs.info(self, "وارد کردن", "ولت جایگزین شد. از این پس رمز اصلی، رمز همین فایل است.")
        except WrongPassword:
            dialogs.warn(self, "وارد کردن", "رمز درست نیست یا فایل آسیب دیده است. چیزی تغییر نکرد.")
        except (VaultError, OSError) as e:
            dialogs.warn(self, "وارد کردن", friendly(e))

    def export_notes_md(self, notes, base: str) -> None:
        notes = notes if notes is not None else self.store.vault["notes"]
        if not notes:
            dialogs.info(self, "خروجی", "یادداشتی برای خروجی نیست.")
            return
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", base).strip()[:60] or "notes"
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره‌ی Markdown", f"{safe}-{dt.date.today().isoformat()}.md", "Markdown (*.md)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(logic.notes_to_markdown(notes))
            except OSError as exc:
                dialogs.warn(self, "خروجی", f"ذخیره نشد: {friendly(exc)}")
                return
            self.status_lb.setText("خروجی Markdown ذخیره شد")

    def export_ics(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "خروجی تقویم", "aegis-tasks.ics", "iCalendar (*.ics)")
        if path:
            try:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(logic.export_ics(self.store.vault))
            except OSError as exc:
                dialogs.warn(self, "خروجی", f"ذخیره نشد: {friendly(exc)}")
                return
            self.status_lb.setText("فایل تقویم ذخیره شد")

    def show_week_seal(self) -> None:
        """The last seven days as one shareable card."""
        if not self.store.is_unlocked:
            return
        from .weekseal import WeekSealDialog
        WeekSealDialog(self).exec()

    def show_day_start(self, force: bool = False):
        """The once-a-day good-morning card. ``force`` (the palette command) shows it again without touching the daily mark."""
        if not self.store.is_unlocked:
            return None
        from . import dayritual
        today = dt.date.today()
        if not force:
            if not dayritual.should_show(self.prefs, today):
                return None
            self.set_pref(dayritual.PREF_DATE, today.isoformat())
        old = getattr(self, "_day_start", None)
        if old is not None:
            try:
                old.close_ritual()
            except RuntimeError:
                pass
        card = self._day_start = dayritual.DayStart(self.shell, dayritual.day_facts(self.store.vault, today), today)
        card.open()
        return card

    def _maybe_day_start(self) -> None:
        if not self.store.is_unlocked or QApplication.activeModalWidget() is not None:
            return
        self.show_day_start()

    def maybe_check_updates(self) -> None:
        """Daily background check; runs only when the user switched it on."""
        if not self.prefs.get("update_check", False):
            return
        today = dt.date.today().isoformat()
        if self.prefs.get("last_update_check") == today:
            return
        self.check_updates(False)

    def check_updates(self, user_asked: bool = True) -> None:
        """Ask GitHub for the latest release on a worker thread; the answer arrives through ``_update_result``."""
        import threading
        from ..core import updates

        def work() -> None:
            self._update_result.emit(updates.fetch_latest(), user_asked)
        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _on_update_result(self, rel, user_asked: bool) -> None:
        from ..core import updates
        if rel is not None:
            self.set_pref("last_update_check", dt.date.today().isoformat())
        if rel is not None and updates.is_newer(rel.version):
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices
            self.toasts.push(f"نسخهٔ {fa(rel.version)} منتشر شده است.", "info", "به‌روزرسانی", 12000,
                             action=("صفحهٔ دانلود", lambda: QDesktopServices.openUrl(QUrl(rel.url))))
        elif user_asked:
            if rel is None:
                self.toasts.push("بررسی انجام نشد؛ اتصال اینترنت یا آدرس مخزن را بررسی کن.", "warn", "به‌روزرسانی", 6000)
            else:
                self.toasts.push("نسخهٔ فعلی آخرین نسخه است.", "success", "به‌روزرسانی", 4000)

    def offer_week_seal(self, force: bool = False) -> bool:
        """On the first unlock of each week (Saturday-based), if last week had any work, offer the seal in a toast - once."""
        from ..core import jalali as _j
        today = dt.date.today()
        week = (today - dt.timedelta(days=_j.weekday_index(today))).isoformat()
        if not self.store.is_unlocked or (not force and self.prefs.get("week_seal_offered") == week):
            return False
        if not logic.week_summary(self.store.vault, today)["done"] and not force:
            return False
        self.set_pref("week_seal_offered", week)
        self.toasts.push("مهر هفتهٔ گذشته آماده است.", "success", "مرور هفته", 9000, action=("ببین", self.show_week_seal))
        return True

    def export_report_pdf(self, days: int = 30, path: str | None = None) -> str | None:
        """Reports -> PDF on the Aegis letterhead: numbers and category names only, no task text."""
        if not self.store.is_unlocked:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "خروجی PDF", f"aegis-report-{dt.date.today().isoformat()}.pdf", "PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        from ..core import certificate as _cert
        from .report_pdf import build_report_pdf
        try:
            n = build_report_pdf(path, self.store.vault, days, theme.PALETTES[self.theme], _cert.identity(self.store)["number"])
        except OSError:
            n = 0
        if n:
            self.notify("گزارش PDF ذخیره شد.", kind="success", title="خروجی")
            return path
        self.notify("گزارش ذخیره نشد؛ مسیر را بررسی کن.", kind="alert", title="خروجی")
        return None

    # ---------------------------------------------------- reminders ------
    def _reminders(self) -> None:
        if busy() or not self.store.is_unlocked:
            return
        lead = int(self.prefs.get("remind_min", 10))
        if not lead:
            return
        now = dt.datetime.now()
        for x in logic.tasks_on(self.store.vault, now.date()):
            tf = x.get("timeFrom")
            if x.get("done") or not tf or x["id"] in self._notified or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", tf):
                continue
            at = dt.datetime.combine(now.date(), dt.time(int(tf[:2]), int(tf[3:])))
            mins = (at - now).total_seconds() / 60
            if -1 <= mins <= lead:
                self._notified.add(x["id"])
                self.notify(f"«{x.get('title') or 'بدون عنوان'}» ساعت {fa(tf)}", beep=True, kind="reminder", title="یادآوری تسک")

    def _day_rollover(self) -> None:
        if not busy() and dt.date.today() != self._today:
            self._today = dt.date.today()
            self._notified.clear()
            if self.store.is_unlocked and logic.extend_series(self.store.vault):
                self._drop_undo()                 # a pending undo would delete the occurrences just created
                self.schedule_save()
            self.refresh_all()
