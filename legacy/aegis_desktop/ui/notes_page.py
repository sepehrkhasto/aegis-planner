# SPDX-License-Identifier: GPL-3.0-or-later
"""The notes page: a gallery of every note, and a full-width editor that opens when you pick one.

Gallery   a header with search and a grid / list switch, folder chips, then cards that preview the text and show a small
          picture of the first sketch or flowchart (``notes_board.NotesBoard``).
Editor    one page that holds, top to bottom, the first paragraph block (``self.body``, the editor every shortcut and test
          talks to) followed by any number of further blocks: more text, hand-drawn sketches and flowcharts
          (``note_blocks``). Everything is saved with the note, inside the encrypted vault: the first text in
          ``note["body"]`` as before, the rest in ``note["blocks"]``.

``self.cur`` is the open note (or None). The gallery stays the home view: locking, deleting the open note and Esc all return
to it."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QEvent, QRectF, QSize, QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (QHBoxLayout, QCompleter, QFrame, QLineEdit, QMenu, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ..core import jalali, logic
from ..core.jalali import fa
from ..core.store import uid
from . import dialogs, flip, icons
from .anim import MOTION
from .empty import EmptyOverlay
from .fx_widgets import Combo, GlowSearch, PinButton, _fpal
from .motion_widgets import HoldButton
from .note_blocks import BlockFrame
from .notes_board import (DEFAULT_VARIANT, NotesBoard, PaperFrame, VariantPicker, checklist_stats, variant_colors, variant_of)
from .notes_ui import FlatIconButton, FormatBar, Pill, Segmented
from .pages import Page, _neg
from .premium import NoteEditor, style_menu
from .theme import PALETTES
from .theme import rr as _rad
from .system import BAR_H, ChipToggle, page_head, toolbar
from .tokens import PAGE
from .widgets import button, label

MAX_TAIL_BLOCKS = 120


class GrowEditor(NoteEditor):
    """A note editor that is exactly as tall as its text (the page scrolls, not the editor), never shorter than ``min_h``."""

    def __init__(self, parent=None, min_h: int = 56):
        super().__init__(parent)
        self.min_h = min_h
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().documentLayout().documentSizeChanged.connect(lambda _s: self._grow())

    def set_min_h(self, h: int) -> None:
        self.min_h = max(40, int(h))
        self._grow()

    def _grow(self) -> None:
        doc = self.document()
        lh = QFontMetricsF(self.font()).lineSpacing()
        h = int(doc.size().height() * lh + 2 * doc.documentMargin() + 8)
        if self.height() != max(self.min_h, h) or self.minimumHeight() != max(self.min_h, h):
            self.setFixedHeight(max(self.min_h, h))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._grow()

    def wheelEvent(self, e) -> None:  # noqa: N802
        e.ignore()                                              # the page scrolls

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, self.min_h)


class Popover(QFrame):
    """A rounded popup card that owns ``content`` for good (it is shown and hidden, never deleted)."""

    def __init__(self, content: QWidget, owner: QWidget):
        super().__init__(owner, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._owner = owner
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(content)
        self.content = content

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self._owner)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor(pal["panel"]))
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawRoundedRect(r, _rad(12), _rad(12))
        p.end()

    def show_under(self, anchor: QWidget) -> None:
        self.content.show()
        self.adjustSize()
        g = anchor.mapToGlobal(anchor.rect().bottomRight())
        x = g.x() - self.width() + 1                    # right-aligned under the button (the page is RTL)
        scr = anchor.screen().availableGeometry() if anchor.screen() else None
        if scr is not None:
            x = max(scr.left() + 6, min(x, scr.right() - self.width() - 6))
        self.move(x, g.y() + 6)
        self.show()


class FolderEdit(QLineEdit):
    """Free-text folder name with the existing folders offered as completions (combo-like API: setEditText / currentText /
    addItems / clear / editTextChanged)."""
    editTextChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStringListModel(self)
        comp = QCompleter(self._model, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.setCompleter(comp)
        self.textChanged.connect(self.editTextChanged)

    def setEditText(self, t: str) -> None:  # noqa: N802
        self.setText(t)

    def currentText(self) -> str:  # noqa: N802
        return self.text()

    def addItems(self, items) -> None:  # noqa: N802
        self._model.setStringList([str(i) for i in items])

    def clear(self) -> None:
        self._model.setStringList([])


class _TextBlock(QWidget):
    """More writing between two drawings."""

    def __init__(self, text: str = "", block_id: str = "", parent=None):
        super().__init__(parent)
        self.kind = "text"
        self.block_id = block_id or uid("b")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.editor = GrowEditor(min_h=48)
        self.editor.setPlaceholderText("ادامه‌ی یادداشت…")
        self.editor.setPlainText(text)
        lay.addWidget(self.editor, 1)
        self.btn_del = FlatIconButton("close", "حذف این بخش", 26, danger=True)
        lay.addWidget(self.btn_del, 0, Qt.AlignmentFlag.AlignTop)

    def data(self) -> dict:
        return {"t": "text", "id": self.block_id, "text": self.editor.toPlainText()}


class NotesPage(Page):
    title = "یادداشت‌ها"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.cur: dict | None = None
        self._loading = False
        self._tail: list[QWidget] = []                       # the blocks after the first text, in order
        self._removed: list[tuple[int, QWidget]] = []
        self._pops: dict[int, QWidget] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(*PAGE)
        root.setSpacing(0)
        self.views = QStackedWidget()
        root.addWidget(self.views)
        self.views.addWidget(self._build_gallery())
        self.views.addWidget(self._build_editor())
        self._q_timer = QTimer(self, singleShot=True, interval=120)
        self._q_timer.timeout.connect(self._fill_list)
        self.q.textChanged.connect(lambda _=0: self._q_timer.start())
        self.folder.currentIndexChanged.connect(lambda _=0: self._folder_changed())
        self.group_chk.toggled.connect(lambda _=0: self._fill_list())
        self.mode_sw.changed.connect(self._set_mode)
        self.board.selected.connect(self.select_id)
        self.board.color_changed.connect(self._set_color_for)
        self.board.pin_toggled.connect(self._toggle_pin_for)
        self.board.delete_req.connect(lambda i: (self.select_id(i), self._delete()))
        self.title_in.textEdited.connect(self._edited)
        self.body.textChanged.connect(self._edited)
        self.pin.toggled.connect(self._edited)
        self.folder_in.editTextChanged.connect(self._edited)
        self.variant.changed.connect(self._variant_changed)
        self._save_timer = QTimer(self, singleShot=True, interval=500)
        self._save_timer.timeout.connect(self._do_commit)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.flush)
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._esc)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._set_enabled(False)

    # ------------------------------------------------------------------ build ---
    def _build_gallery(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.count_lb = label("", "Muted")
        self.q = GlowSearch()
        self.q.setFixedHeight(BAR_H)
        self.q.setMinimumWidth(200)
        self.mode_sw = Segmented([("grid", "grid", "نمای کارت"), ("list", "rows", "نمای فهرست")])
        lay.addLayout(page_head("یادداشت‌ها", self.count_lb, button("＋  یادداشت جدید", "Primary", self._new)))
        self.folder = Combo()                                  # the source of truth for the folder filter; the chips mirror it
        self.folder.hide()
        self.chips_box = QHBoxLayout()
        self.chips_box.setSpacing(8)
        self.chips_box.setContentsMargins(0, 0, 0, 0)
        chips_host = QWidget()
        chips_host.setLayout(self.chips_box)
        chips_host.setFixedHeight(36)
        self.group_chk = ChipToggle("گروه‌بندی بر اساس پوشه")
        self.group_chk.setChecked(True)
        lay.addLayout(toolbar(self.q, self.mode_sw, self.group_chk, stretch_first=True))
        lay.addWidget(chips_host)
        self.board = NotesBoard()
        self.list = self.board                                  # .count() kept for API/tests
        self.empty = EmptyOverlay(self.board.viewport(), "notes")
        lay.addWidget(self.board, 1)
        return w

    def _build_editor(self) -> QWidget:
        host = QWidget()
        outer = QHBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        page = QWidget()
        page.setMaximumWidth(980)
        outer.addWidget(page, 100)
        outer.addStretch(1)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.back_btn = Pill("همه‌ی یادداشت‌ها", icon_name="arrow_right")
        self.back_btn.setCheckable(False)
        self.back_btn.clicked.connect(self._back)
        bar.addWidget(self.back_btn)
        bar.addStretch(1)
        self.saved_lb = label("", "Muted")
        bar.addWidget(self.saved_lb)
        bar.addSpacing(6)
        self.pin = PinButton(30)
        self.pin.setToolTip("سنجاق")
        bar.addWidget(self.pin)
        self.variant = VariantPicker()
        self.btn_color = FlatIconButton("palette", "رنگ یادداشت", 34)
        self.btn_color.clicked.connect(lambda: self._popup(self.btn_color, self.variant))
        bar.addWidget(self.btn_color)
        self.stats = label("", "Muted")
        self.stats.setWordWrap(True)
        self.stats.setMinimumWidth(240)
        self.stats.setContentsMargins(14, 10, 14, 10)
        self.btn_info = FlatIconButton("info", "آمار و جزئیات", 34)
        self.btn_info.clicked.connect(lambda: self._popup(self.btn_info, self.stats))
        bar.addWidget(self.btn_info)
        self.btn_export = FlatIconButton("export", "خروجی گرفتن از این یادداشت", 34)
        self.btn_export.clicked.connect(self._export_menu)
        bar.addWidget(self.btn_export)
        lay.addLayout(bar)
        self.title_in = QLineEdit()
        self.title_in.setPlaceholderText("عنوان")
        f = self.title_in.font()
        f.setPointSizeF(f.pointSizeF() + 8)
        f.setBold(True)
        self.title_in.setFont(f)
        self.title_in.setFrame(False)
        self.title_in.setStyleSheet("QLineEdit{background:transparent;border:none;padding:4px 2px;}")
        lay.addWidget(self.title_in)
        meta = QHBoxLayout()
        meta.setSpacing(10)
        self.folder_in = FolderEdit()
        self.folder_in.setPlaceholderText("پوشه")
        self.folder_in.setFixedWidth(190)
        meta.addWidget(self.folder_in)
        self.stamp = label("", "Muted")
        meta.addWidget(self.stamp, 1)
        lay.addLayout(meta)
        self.dock = FormatBar(size=34)
        for key, icon, tip, fn in (("bold", "bold", "پررنگ (**)", lambda: self._wrap("**", "**")),
                                   ("italic", "italic", "مورب (*)", lambda: self._wrap("*", "*")),
                                   ("underline", "underline", "زیرخط (__)", lambda: self._wrap("__", "__")),
                                   ("mark", "highlight", "هایلایت (==)", lambda: self._wrap("==", "==")),
                                   ("heading", "heading", "عنوان (#)", lambda: self._prefix("# ")),
                                   ("list", "checklist", "چک‌لیست (- [ ])", lambda: self._prefix("- [ ] "))):
            self.dock.add_tool(key, icon, tip)
            self.dock.button(key).clicked.connect(fn)
        self.dock.add_sep()
        for key, icon, tip, kind in (("text", "text", "بخش نوشتاری تازه", "text"), ("ink", "pen", "طراحی دستی — با قلم نوری یا ماوس", "ink"),
                                     ("flow", "flow", "فلوچارت", "flow")):
            self.dock.add_tool(key, icon, tip)
            self.dock.button(key).clicked.connect(lambda _=False, k=kind: self.add_block(k))
        self.dock.add_stretch()
        self.dock.add_tool("save", "save", "ذخیره  Ctrl+S")
        self.dock.button("save").clicked.connect(self.flush)
        lay.addWidget(self.dock)
        self.body = GrowEditor(min_h=180)
        self.body.setPlaceholderText("متن یادداشت…  (برای چک‌لیست: - [ ])")
        self.column = QWidget()
        self.col_lay = QVBoxLayout(self.column)
        self.col_lay.setContentsMargins(26, 20, 26, 22)
        self.col_lay.setSpacing(14)
        self.col_lay.addWidget(self.body)
        self.add_row = QHBoxLayout()
        self.add_row.setSpacing(8)
        self.add_row.addStretch(1)
        for kind, text, icon in (("text", "＋ متن", ""), ("ink", "طراحی دستی", "pen"), ("flow", "فلوچارت", "flow")):
            pill = Pill(text, icon_name=icon)
            pill.setCheckable(False)
            pill.clicked.connect(lambda _=False, k=kind: self.add_block(k))
            self.add_row.addWidget(pill)
        self.add_row.addStretch(1)
        self.add_host = QWidget()
        self.add_host.setLayout(self.add_row)
        self.col_lay.addWidget(self.add_host)
        self.col_lay.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setProperty("edges", True)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.scroll.viewport().setStyleSheet("background:transparent;")
        self.column.setStyleSheet("background:transparent;")
        self.scroll.setWidget(self.column)
        self.scroll.viewport().installEventFilter(self)
        self.paper = PaperFrame(self.scroll)
        lay.addWidget(self.paper, 1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        _d = HoldButton("نگه‌دار تا حذف شود", "به سطل رفت")
        _d.held.connect(lambda: self._delete(False))
        foot.addWidget(_d)
        lay.addLayout(foot)
        self.body.cursorPositionChanged.connect(lambda: self._follow_caret(self.body))
        return host

    def _popup(self, anchor: QWidget, content: QWidget) -> None:
        """Show ``content`` in a small card under ``anchor``. The card is created once and kept, so the content widget is
        never destroyed with a menu (a QWidgetAction deletes its widget when the menu goes)."""
        pop = self._pops.get(id(content))
        if pop is None:
            pop = self._pops[id(content)] = Popover(content, self)
        pop.show_under(anchor)

    # ------------------------------------------------------------------ state ---
    def _set_enabled(self, on: bool) -> None:
        for w in (self.title_in, self.body, self.folder_in, self.pin, self.variant, self.btn_color, self.btn_info,
                  self.btn_export, self.add_host):
            w.setEnabled(on)
        for b in self._tail:
            b.setEnabled(on)
        self.dock.set_enabled_all(on)
        self.body.setPlaceholderText("متن یادداشت…  (برای چک‌لیست: - [ ])" if on else "")

    def unbind(self) -> None:
        """No note is open: the editor must not look (or act) like it is."""
        self.cur = None
        self._save_timer.stop()
        self._loading = True
        try:
            self.title_in.clear()
            self.body.clear()
            self.folder_in.setEditText("")
            self.pin.setChecked(False)
            self._clear_tail()
        finally:
            self._loading = False
        self._set_enabled(False)
        self._show_gallery(animate=False)

    def _clear_tail(self) -> None:
        for b in self._tail:
            self.col_lay.removeWidget(b)
            b.hide()
            b.deleteLater()
        self._tail = []
        self._removed.clear()

    def _tint(self) -> None:
        name = variant_of(self.cur) if self.cur else DEFAULT_VARIANT
        pal = PALETTES[self.ctx.theme]
        acc, light, dtint = variant_colors(name, pal)
        dark = self.ctx.theme == "dark"
        col = QColor_(dtint if dark else acc)
        if not self.cur:
            fill, edge = QColor_(pal["panel"]), QColor_(pal["line"])
        else:
            pb = QColor_(pal["panel"])
            if dark:
                fill = QColor_(int(pb.red() * .94 + col.red() * .06), int(pb.green() * .94 + col.green() * .06),
                               int(pb.blue() * .94 + col.blue() * .06))
            else:
                fill = QColor_(light).lighter(106)
            ln = QColor_(pal["line"])
            edge = QColor_((col.red() + ln.red() * 2) // 3, (col.green() + ln.green() * 2) // 3, (col.blue() + ln.blue() * 2) // 3)
        self.body.setStyleSheet("QPlainTextEdit{background:transparent;border:none;padding:0 2px;}")
        self.body.set_paper(None, None, 0)
        for b in self._tail:
            if isinstance(b, _TextBlock):
                b.editor.setStyleSheet("QPlainTextEdit{background:transparent;border:none;padding:0 2px;}")
                b.editor.set_paper(None, None, 0)
        self.paper.set_look(QColor_(0, 0, 0, 40), _rad(8), fill, edge)
        self.variant.set_value(name)
        self.variant.theme = self.ctx.theme
        self.variant.update()
        self.column.update()
        for b in self._tail:
            b.update()
            for c in b.findChildren(QWidget):
                c.update()

    def _show_editor(self, animate: bool = True) -> None:
        if self.views.currentIndex() == 1:
            return
        pm = self.views.grab() if animate and MOTION[0] and self.isVisible() else None
        self.views.setCurrentIndex(1)
        if pm is not None:
            flip.crossfade(self.views, pm, 170)
        QTimer.singleShot(0, self._resize_body)

    def _show_gallery(self, animate: bool = True) -> None:
        if self.views.currentIndex() == 0:
            return
        pm = self.views.grab() if animate and MOTION[0] and self.isVisible() else None
        self.views.setCurrentIndex(0)
        if pm is not None:
            flip.crossfade(self.views, pm, 170)

    def _back(self) -> None:
        self._commit()
        self._show_gallery()
        self._fill_list()

    def _esc(self) -> None:
        if self.views.currentIndex() == 1:
            self._back()

    # ------------------------------------------------------------------ gallery ---
    def _set_mode(self, mode: str) -> None:
        self.board.set_mode(mode)
        try:
            self.ctx.set_pref("notes_view", mode)
        except AttributeError:
            pass

    def _folder_changed(self) -> None:
        self._sync_chips()
        self._fill_list()

    def _rebuild_chips(self) -> None:
        while self.chips_box.count():
            it = self.chips_box.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        notes = self.v["notes"]
        items = [("", "همه", len(notes))] + [(f, f, sum(1 for n in notes if n.get("folder") == f)) for f in logic.note_folders(self.v)]
        self._chips = {}
        for key, text, cnt in items[:14]:
            pill = Pill(text, count=cnt)
            pill.setChecked(key == (self.folder.currentData() or ""))
            pill.clicked.connect(lambda _=False, k=key: self._pick_folder(k))
            self.chips_box.addWidget(pill)
            self._chips[key] = pill
        self.chips_box.addStretch(1)

    def _sync_chips(self) -> None:
        cur = self.folder.currentData() or ""
        for key, pill in getattr(self, "_chips", {}).items():
            pill.setChecked(key == cur)

    def _pick_folder(self, key: str) -> None:
        self.folder.setCurrentIndex(max(0, self.folder.findData(key)))

    def _fill_list(self, keep: str | None = None) -> None:
        if not self.ctx.store.is_unlocked:
            return
        cur_id = keep or (self.cur["id"] if self.cur else None)
        folder = self.folder.currentData() or ""
        q = logic.fold(self.q.text().strip())
        notes = [n for n in self.v["notes"]
                 if (not folder or n.get("folder") == folder)
                 and (not q or q in logic.fold(n.get("title", "") + " " + logic.note_full_text(n)))]
        notes.sort(key=lambda n: (not n.get("pinned"), _neg(n.get("updatedAt") or n.get("createdAt") or "")))
        self.board.set_notes(notes, cur_id, self.ctx.theme, self.group_chk.isChecked())
        total = len(self.v["notes"])
        pinned = sum(1 for n in self.v["notes"] if n.get("pinned"))
        self.count_lb.setText(f"{fa(total)} یادداشت" + (f"  ·  {fa(pinned)} سنجاق‌شده" if pinned else "") if total else "هنوز چیزی ننوشته‌ای")
        if notes:
            self.empty.show_for(False)
        elif q or folder:
            self.empty.show_for(True, "یادداشتی پیدا نشد", "جستجو یا پوشه را عوض کن.", "پاک کردن جستجو",
                                lambda: (self.q.setText(""), self.folder.setCurrentIndex(0)))
        else:
            self.empty.show_for(True, "هنوز یادداشتی نداری", "هر فکر، فهرست، طرح یا فلوچارتی را اینجا بنویس.",
                                "＋ یادداشت جدید", self._new)

    # ------------------------------------------------------------------ note ---
    def _new(self) -> None:
        self._commit()
        n = logic.new_note("", "", self.folder.currentData() or "")
        self.v["notes"].append(n)
        self.ctx.changed()
        self.select_id(n["id"])
        self.title_in.setFocus()

    def select_id(self, nid: str, show: bool = True) -> None:
        if self.cur and self.cur["id"] == nid:
            if show:
                self._show_editor()
            return
        self._commit()
        n = next((x for x in self.v["notes"] if x["id"] == nid), None)
        if not n:
            return
        self.cur = n
        self._loading = True
        self._set_enabled(True)
        self.title_in.setText(n.get("title", ""))
        self.body.setPlainText(logic.note_text(n))
        self.pin.setChecked(bool(n.get("pinned")))
        self.folder_in.setEditText(n.get("folder", ""))
        self._load_tail(n)
        self._loading = False
        self._stamp()
        self._tint()
        self._update_stats()
        self.board.set_current(nid)
        self.saved_lb.setText("")
        if show:
            self._show_editor()
        self._resize_body()

    def _load_tail(self, n: dict) -> None:
        self._clear_tail()
        for b in (n.get("blocks") or [])[:MAX_TAIL_BLOCKS]:
            if not isinstance(b, dict):
                continue
            w = self._make_block(b.get("t"), b)
            if w is not None:
                self._tail.append(w)
        self._relayout_tail()

    def _make_block(self, kind: str, data: dict | None = None) -> QWidget | None:
        data = data or {}
        if kind == "text":
            w = _TextBlock(str(data.get("text") or ""), data.get("id", ""))
            w.editor.textChanged.connect(self._edited)
            w.editor.cursorPositionChanged.connect(lambda ed=w.editor: self._follow_caret(ed))
            w.btn_del.clicked.connect(lambda _=False, b=w: self._remove_block(b))
            return w
        if kind in ("ink", "flow"):
            w = BlockFrame(kind, {**data, "id": data.get("id") or uid("b")})
            w.changed.connect(self._edited)
            w.delete_req.connect(self._remove_block)
            w.move_req.connect(self._move_block)
            return w
        return None

    def _relayout_tail(self) -> None:
        """(Re)seat the tail blocks in order, between the body and the add-row."""
        for b in self._tail:
            self.col_lay.removeWidget(b)
        for i, b in enumerate(self._tail):
            self.col_lay.insertWidget(1 + i, b)
            b.setEnabled(self.cur is not None)
            b.show()
        self.add_host.setVisible(True)
        self._resize_body()

    def add_block(self, kind: str) -> None:
        if not self.cur or len(self._tail) >= MAX_TAIL_BLOCKS:
            return
        w = self._make_block(kind)
        if w is None:
            return
        pos = len(self._tail)                                   # after the focused block, else at the end
        fw = self.focusWidget()
        for i, b in enumerate(self._tail):
            if fw is not None and (b is fw or b.isAncestorOf(fw)):
                pos = i + 1
                break
        self._tail.insert(pos, w)
        if kind != "text" and pos == len(self._tail) - 1:         # something to type into after a drawing
            self._tail.append(self._make_block("text"))
        self._relayout_tail()
        self._tint()
        self._edited()
        if kind == "text":
            w.editor.setFocus()
        QTimer.singleShot(30, lambda: self.scroll.ensureWidgetVisible(w, 20, 60))

    def _remove_block(self, w: QWidget) -> None:
        if w not in self._tail:
            return
        idx = self._tail.index(w)
        self._tail.remove(w)
        self.col_lay.removeWidget(w)
        w.hide()
        self._removed.append((idx, w))
        del self._removed[:-6]
        self._relayout_tail()
        self._edited()
        t = getattr(self.ctx, "toasts", None)
        if t is not None:
            t.push("بخش حذف شد", "info", "", 7000, action=("برگردان", lambda b=w: self._restore_block(b)))

    def _restore_block(self, w: QWidget) -> None:
        for i, (idx, b) in enumerate(self._removed):
            if b is w:
                del self._removed[i]
                self._tail.insert(min(idx, len(self._tail)), w)
                self._relayout_tail()
                self._edited()
                return

    def _move_block(self, w: QWidget, d: int) -> None:
        if w not in self._tail:
            return
        i = self._tail.index(w)
        j = max(0, min(len(self._tail) - 1, i + d))
        if i != j:
            self._tail[i], self._tail[j] = self._tail[j], self._tail[i]
            self._relayout_tail()
            self._edited()

    # ------------------------------------------------------------------ layout ---
    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self.scroll.viewport() and ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._resize_body)
        return super().eventFilter(obj, ev)

    def _resize_body(self) -> None:
        """With nothing after it the first paragraph fills the page; with blocks it is just as tall as its text."""
        vh = self.scroll.viewport().height()
        if self._tail:
            self.body.set_min_h(120)
        else:
            self.body.set_min_h(max(180, vh - 40 - 26 - 22 - 14))

    def _follow_caret(self, ed: QWidget) -> None:
        if self._loading or not ed.hasFocus():
            return
        r = ed.cursorRect()
        pt = ed.mapTo(self.column, r.bottomLeft())
        self.scroll.ensureVisible(pt.x(), pt.y(), 20, 56)

    # ------------------------------------------------------------------ text ---
    def _all_text(self) -> str:
        parts = [self.body.toPlainText()]
        parts += [b.editor.toPlainText() for b in self._tail if isinstance(b, _TextBlock)]
        return "\n".join(parts)

    @staticmethod
    def _ago(iso: str | None) -> str:
        try:
            d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
            s = (dt.datetime.now().astimezone() - d).total_seconds()
        except Exception:  # noqa: BLE001
            return ""
        if s < 60:
            return "همین الان"
        if s < 3600:
            return f"{fa(int(s // 60))} دقیقه پیش"
        if s < 86400:
            return f"{fa(int(s // 3600))} ساعت پیش"
        return NotesPage._fmt(iso)

    def _stamp(self) -> None:
        """Under the title: how long ago it was edited, word count and an honest reading time."""
        if not self.cur:
            self.stamp.setText("")
            return
        words = len(self._all_text().split())
        mins = max(1, -(-words // 180))
        self.stamp.setText(f"آخرین ویرایش {self._ago(self.cur.get('updatedAt'))}  ·  {fa(words)} کلمه  ·  حدود {fa(mins)} دقیقه مطالعه")

    def _update_stats(self) -> None:
        self._stamp()
        if not self.cur:
            self.stats.setText("")
            return
        txt = self._all_text()
        d, t = checklist_stats(txt)
        words = len(txt.split())
        s = f"کلمات: {fa(words)}   نویسه‌ها: {fa(len(txt))}"
        if t:
            s += f"\nچک‌لیست: {fa(d)} از {fa(t)} انجام شده"
        inks = sum(1 for b in self._tail if isinstance(b, BlockFrame) and b.kind == "ink")
        flows = sum(1 for b in self._tail if isinstance(b, BlockFrame) and b.kind == "flow")
        if inks or flows:
            s += f"\nطراحی دستی: {fa(inks)}   فلوچارت: {fa(flows)}"
        s += f"\nساخته‌شده: {self._fmt(self.cur.get('createdAt'))}\nویرایش: {self._fmt(self.cur.get('updatedAt'))}"
        self.stats.setText(s)

    @staticmethod
    def _fmt(iso: str | None) -> str:
        try:
            d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
            j = jalali.to_jalali(d.year, d.month, d.day)
            return f"{fa(j[2])} {jalali.MONTHS_FA[j[1] - 1]} {fa(j[0])} — {fa(d.strftime('%H:%M'))}"
        except Exception:  # noqa: BLE001
            return ""

    def _edited(self, *_a) -> None:
        if self._loading or not self.cur:
            return
        self.saved_lb.setText("در حال ذخیره…")
        self._save_timer.start()
        self._update_stats()

    def _variant_changed(self, name: str) -> None:
        if self._loading or not self.cur:
            return
        self.cur["color"] = name
        self._tint()
        self._save_timer.start()

    def _set_color_for(self, nid: str, name: str) -> None:
        n = next((x for x in self.v["notes"] if x["id"] == nid), None)
        if not n:
            return
        n["color"] = name
        n["updatedAt"] = logic.now_iso()
        self.ctx.store.dirty = True
        self.ctx.schedule_save()
        if self.cur and self.cur["id"] == nid:
            self._tint()
        self._fill_list(keep=nid)

    def _toggle_pin_for(self, nid: str) -> None:
        n = next((x for x in self.v["notes"] if x["id"] == nid), None)
        if not n:
            return
        self._commit()
        n["pinned"] = not n.get("pinned")
        self.ctx.store.dirty = True
        self.ctx.schedule_save()
        if self.cur and self.cur["id"] == nid:
            self._loading = True
            self.pin.setChecked(n["pinned"])
            self._loading = False
        self._fill_list(keep=nid)

    def _commit(self) -> None:
        """Write any pending edit now (no-op when nothing is pending)."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._do_commit()

    def _focus_editor(self) -> GrowEditor:
        fw = self.focusWidget()
        for b in self._tail:
            if isinstance(b, _TextBlock) and (fw is b.editor):
                return b.editor
        return self.body

    def _wrap(self, a: str, b: str) -> None:
        ed = self._focus_editor()
        c = ed.textCursor()
        sel = c.selectedText()
        c.insertText(f"{a}{sel}{b}")
        if not sel:
            c.movePosition(c.MoveOperation.Left, c.MoveMode.MoveAnchor, len(b))
            ed.setTextCursor(c)
        ed.setFocus()

    def _prefix(self, p: str) -> None:
        ed = self._focus_editor()
        c = ed.textCursor()
        c.movePosition(c.MoveOperation.StartOfLine)
        c.insertText(p)
        ed.setFocus()

    def _collect_blocks(self) -> list[dict]:
        out = [b.data() for b in self._tail]
        while out and out[-1]["t"] == "text" and not out[-1]["text"].strip():     # the spare line after the last drawing
            out.pop()
        return out

    def _do_commit(self) -> None:
        if not self.cur:
            return
        n = self.cur
        n["title"] = self.title_in.text().strip()
        n["pinned"] = self.pin.isChecked()
        n["folder"] = self.folder_in.currentText().strip()
        logic.set_note_body(n, self.body.toPlainText())
        blocks = self._collect_blocks()
        if blocks:
            n["blocks"] = blocks
        else:
            n.pop("blocks", None)
        self.ctx.store.dirty = True
        self.ctx.schedule_save()
        self._fill_list(keep=n["id"])
        self._update_stats()
        self.saved_lb.setText("ذخیره شد ✓")

    def flush(self) -> None:
        self._commit()

    def _delete(self, confirm: bool = True) -> None:
        if not self.cur:
            return
        if not confirm or dialogs.ask(self, "حذف یادداشت", "یادداشت به سطل زباله منتقل شود؟", True, "حذف"):
            self._commit()                      # the trash copy must carry the last keystrokes (hold-to-delete skips the dialog)
            n = self.cur
            self.ctx.store.trash_put("note", n)
            self.v["notes"] = [x for x in self.v["notes"] if x["id"] != n["id"]]
            self.unbind()
            self.ctx.changed("یادداشت به سطل زباله رفت")

    def _export_one(self) -> None:
        if self.cur:
            self.flush()
            self.ctx.export_notes_md([self.cur], self.cur.get("title") or "note")

    def _export_menu(self) -> None:
        if not self.cur:
            return
        self.flush()
        pal = PALETTES[self.ctx.theme]
        m = style_menu(QMenu(self))
        m.aboutToHide.connect(m.deleteLater)
        m.addAction(icons.icon("export", pal["muted"], 16), "ذخیره به‌صورت PDF…", lambda: self._export("pdf"))
        m.addAction(icons.icon("image", pal["muted"], 16), "ذخیره به‌صورت تصویر (PNG)…", lambda: self._export("png"))
        m.addAction(icons.icon("notes", pal["muted"], 16), "ذخیره به‌صورت Markdown (با تصاویر)…", lambda: self._export("md"))
        m.exec(self.btn_export.mapToGlobal(self.btn_export.rect().bottomLeft()))

    def _export(self, kind: str, path: str | None = None) -> str | None:
        from . import note_export
        if not self.cur:
            return None
        self.flush()
        return note_export.export_note(self, self.cur, kind, path)

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        self._commit()
        cur_f = self.folder.currentData()
        self.folder.blockSignals(True)
        self.folder.clear()
        self.folder.addItem("همه‌ی پوشه‌ها", "")
        folders = logic.note_folders(self.v)
        for f in folders:
            self.folder.addItem(f, f)
        self.folder.setCurrentIndex(max(0, self.folder.findData(cur_f)))
        self.folder.blockSignals(False)
        self._rebuild_chips()
        self.folder_in.addItems(folders)
        mode = self.ctx.prefs.get("notes_view", "grid") if hasattr(self.ctx, "prefs") else "grid"
        self.mode_sw.set_current(mode if mode in ("grid", "list") else "grid")
        self.board.set_mode(self.mode_sw.cur)
        if self.cur is not None:
            live = next((x for x in self.v["notes"] if x["id"] == self.cur["id"]), None)
            if live is not self.cur:                     # deleted, or the vault was swapped (restore / import): rebind
                self.cur = None
                if live is None:
                    self._set_enabled(False)
                    self.title_in.clear()
                    self.body.clear()
                    self._clear_tail()
                    self._show_gallery(animate=False)
                else:
                    self.select_id(live["id"], show=self.views.currentIndex() == 1)
        self._fill_list()
        self._tint()


class QColor_:                                   # (tiny alias so the tint code above reads like the rest of the notes code)
    def __new__(cls, *a):
        from PyQt6.QtGui import QColor
        return QColor(*a)
