# SPDX-License-Identifier: GPL-3.0-or-later
"""Tasks table chrome: animated row hover, soft status badges and round edit / delete / more buttons.

  * ``TaskTableModel``   - the rows, computed lazily per visible cell (5000 tasks refresh in a few ms: nothing is
                           built for rows that are never painted).
  * ``HoverTable``       - QTableView that tracks the hovered row + hovered action button and animates both.
  * ``TaskCellDelegate`` - paints one cell: row-hover wash (with a thin accent bar at the start edge), the check
                           circle, priority / status pills and the round action buttons of the last column.

Column layout of the tasks table (logical order, column 0 sits on the right in RTL):
0 check · 1 title · 2 category · 3 priority · 4 status · 5 due · 6 tags · 7 actions
"""
from __future__ import annotations

import bisect
import datetime as dt

from PyQt6.QtCore import QAbstractTableModel, QEasingCurve, QEvent, QModelIndex, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QLineEdit, QStyle, QStyledItemDelegate, QTableView, QToolTip

from ..core import jalali, logic
from ..core.jalali import fa
from . import icons
from .theme import AL_R
from .fx_widgets import _Anim, _fpal, color_hex, paint_badge
from . import micro
from .premium import CheckCellDelegate, _paint_empty, alpha, is_checked, mix, paint_check

UR = Qt.ItemDataRole.UserRole
TONE = Qt.ItemDataRole.UserRole + 5
PR_TONE = {"high": "danger", "normal": "info", "low": "muted"}

COL_CHECK, COL_TITLE, COL_CAT, COL_PRIO, COL_STATUS, COL_DUE, COL_TAGS, COL_ACT = range(8)
BAND = 30                                                    # height of a group header band (grouped mode)
BTN_D, BTN_GAP = 28, 6                                       # diameter / gap of the round buttons
ACTIONS = (("edit", "edit", "ویرایش"), ("trash", "delete", "حذف"), ("dots", "more", "گزینه‌ها"))

STATUS_LABEL = {"todo": "انجام‌نشده", "doing": "در حال انجام", "done": "انجام‌شده", "late": "عقب‌افتاده"}
STATUS_TONE = {"todo": "muted", "doing": "info", "done": "success", "late": "danger"}


def task_status(x: dict, today: dt.date | None = None) -> str:
    """todo | doing | done | late - what the status pill of a task shows."""
    st = logic.kanban_status(x)
    if st == "done" or x.get("done"):
        return "done"
    d = logic.task_date(x)
    if d is not None and d < (today or dt.date.today()):
        return "late"
    return st


GROUPS = ("late", "today", "week", "later", "none")
GROUP_LABEL = {"late": "عقب‌افتاده", "past": "گذشته", "today": "امروز", "week": "این هفته", "later": "بعداً", "none": "بدون موعد"}


def group_of(x: dict, today: dt.date, open_only: bool = True) -> str:
    """Which section a task belongs to. Tasks arrive sorted by due date, so each section is one contiguous run."""
    d = logic.task_date(x)
    if d is None:
        return "none"
    if d < today:
        return "late" if open_only else "past"
    if d == today:
        return "today"
    return "week" if (d - today).days <= 7 else "later"


def button_rects(cell: QRectF) -> list[QRectF]:
    """The three round buttons of an action cell, first (edit) on the right - the reading start in RTL."""
    total = 3 * BTN_D + 2 * BTN_GAP
    right = cell.center().x() + total / 2
    y = cell.center().y() - BTN_D / 2
    return [QRectF(right - (i + 1) * BTN_D - i * BTN_GAP, y, BTN_D, BTN_D) for i in range(3)]


class TaskTableModel(QAbstractTableModel):
    """Rows = task dicts (already filtered and sorted). Cell values are derived on demand and memoised per row."""

    checkToggled = pyqtSignal(str, bool)                     # task id, done
    titleEdited = pyqtSignal(str, str)                       # task id, new title (inline edit)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []
        self.heads = [""] * 8
        self._memo: dict[int, tuple] = {}
        self._icons: dict[str, QIcon] = {}
        self.today = dt.date.today()
        self.colors = {"muted": QColor("#888"), "danger": QColor("#e55"), "text": QColor("#eee")}
        self.strike = QFont()
        self.strike.setStrikeOut(True)
        self.starts: list[int] = []                          # first row of every group (grouped mode), else []
        self.gkeys: list[str] = []
        self.gcount: list[int] = []

    def set_rows(self, rows: list[dict], colors: dict[str, QColor], font: QFont, grouped: bool = False,
                 open_only: bool = True) -> None:
        self.beginResetModel()
        self.rows, self.colors, self._memo = rows, colors, {}
        self.starts, self.gkeys, self.gcount = [], [], []
        if grouped:
            today, last = dt.date.today(), None
            for i, x in enumerate(rows):
                g = group_of(x, today, open_only)
                if g != last:
                    self.starts.append(i)
                    self.gkeys.append(g)
                    self.gcount.append(0)
                    last = g
                self.gcount[-1] += 1
        self.today = dt.date.today()
        self.strike = QFont(font)
        self.strike.setStrikeOut(True)
        self.endResetModel()

    # --- Qt model API
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 8

    def headerData(self, section, orient, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orient == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole and 0 <= section < 8:
            return self.heads[section]
        return None

    def flags(self, idx):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if idx.column() == COL_TITLE:
            return f | Qt.ItemFlag.ItemIsEditable
        return f | Qt.ItemFlag.ItemIsUserCheckable if idx.column() == COL_CHECK else f

    def band(self, r: int) -> int:
        """Extra height on top of row ``r`` that carries its group header (0 for all other rows)."""
        if not self.starts:
            return 0
        i = bisect.bisect_left(self.starts, r)
        return BAND if i < len(self.starts) and self.starts[i] == r else 0

    def group_at(self, r: int) -> int:
        """Index of the group row ``r`` belongs to (-1 when not grouped)."""
        return bisect.bisect_right(self.starts, r) - 1 if self.starts else -1

    def group_title(self, g: int) -> tuple[str, str]:
        """(section name, how many tasks in it)."""
        return GROUP_LABEL[self.gkeys[g]], fa(self.gcount[g])

    def _row(self, r: int) -> tuple:
        m = self._memo.get(r)
        if m is None:
            x = self.rows[r]
            title = x.get("title") or ""
            subs = x.get("subs")
            if subs:
                title += f"   [{fa(sum(1 for s in subs if s.get('done')))}/{fa(len(subs))}]"
            if x.get("rep") not in (None, "none"):
                title += "  ↻"
            due = logic.task_date(x)
            due_txt = jalali.label(x.get("due")) + (f"  {fa(x['timeFrom'])}" if x.get("timeFrom") else "")
            due_col = "danger" if due and not x.get("done") and due < self.today else "text" if due == self.today else None
            st = task_status(x, self.today)
            m = self._memo[r] = (title, logic.CAT_LABEL.get(x.get("cat"), ""), logic.PR_LABEL.get(x.get("pr"), ""),
                                 PR_TONE.get(x.get("pr"), "muted"), "" if st == "todo" else STATUS_LABEL[st], STATUS_TONE[st],      # a plain open task needs no badge
                                 due_txt, due_col,
                                 " ".join("#" + t for t in x.get("tags") or []), bool(x.get("done")), color_hex(x.get("color")))
        return m

    def data(self, idx, role=Qt.ItemDataRole.DisplayRole):
        r, c = idx.row(), idx.column()
        if not (0 <= r < len(self.rows)):
            return None
        if role == UR:
            return self.rows[r]["id"]
        if role == Qt.ItemDataRole.EditRole:
            return self.rows[r].get("title", "") if c == COL_TITLE else None
        (title, cat, pr, pr_tone, st, st_tone, due, due_col, tags, done, hexc) = self._row(r)
        if role == Qt.ItemDataRole.DisplayRole:
            return {COL_TITLE: title, COL_CAT: cat, COL_PRIO: pr, COL_STATUS: st, COL_DUE: due, COL_TAGS: tags}.get(c, "")
        if role == Qt.ItemDataRole.CheckStateRole and c == COL_CHECK:
            return Qt.CheckState.Checked if done else Qt.CheckState.Unchecked
        if role == TONE:
            return pr_tone if c == COL_PRIO else st_tone if c == COL_STATUS else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if c == COL_TITLE and done:
                return self.colors["muted"]
            if c == COL_DUE and due_col:
                return self.colors[due_col]
            return None
        if role == Qt.ItemDataRole.FontRole and c == COL_TITLE and done:
            return self.strike
        if role == Qt.ItemDataRole.DecorationRole and c == COL_TITLE and hexc:
            ic = self._icons.get(hexc)
            if ic is None:
                pm = QPixmap(12, 12)
                pm.fill(QColor(hexc))
                ic = self._icons[hexc] = QIcon(pm)
            return ic
        return None

    def setData(self, idx, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role == Qt.ItemDataRole.EditRole and idx.column() == COL_TITLE and 0 <= idx.row() < len(self.rows):
            self.titleEdited.emit(self.rows[idx.row()]["id"], str(value))
            return True
        if role != Qt.ItemDataRole.CheckStateRole or idx.column() != COL_CHECK or not (0 <= idx.row() < len(self.rows)):
            return False
        on = (value.value if hasattr(value, "value") else int(value)) == Qt.CheckState.Checked.value
        self.checkToggled.emit(self.rows[idx.row()]["id"], on)
        return True


class _ItemRef:
    """QTableWidgetItem-like read handle on one cell (keeps call sites and tests readable)."""

    def __init__(self, view: "HoverTable", r: int, c: int):
        self._m, self._r, self._c = view.model(), r, c

    def _i(self):
        return self._m.index(self._r, self._c)

    def row(self) -> int:
        return self._r

    def column(self) -> int:
        return self._c

    def text(self) -> str:
        return self._i().data() or ""

    def data(self, role=Qt.ItemDataRole.DisplayRole):
        return self._i().data(role)

    def flags(self):
        return self._m.flags(self._i())

    def checkState(self):  # noqa: N802
        return self._i().data(Qt.ItemDataRole.CheckStateRole)

    def setCheckState(self, state) -> None:  # noqa: N802
        self._m.setData(self._i(), state, Qt.ItemDataRole.CheckStateRole)


class HoverTable(QTableView):
    """Row hover + round action buttons. Emits ``actionRequested(row, "edit" | "delete" | "more")``."""

    actionRequested = pyqtSignal(int, str)
    deleteRequested = pyqtSignal()                           # Delete with the table focused (selected rows)
    previewRequested = pyqtSignal(int)                       # Space on the current row: quick look
    resized = pyqtSignal()
    HOVER_A = 0.085                                          # strength of the row wash

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Keyboard twins of the hover-only buttons, scoped to the table's own focus: Enter edits the current row,
        Delete trashes the selection. (A window-wide shortcut would also fire while typing in the search box.)"""
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentRow() >= 0:
            self.actionRequested.emit(self.currentRow(), "edit")
            e.accept()
            return
        if k == Qt.Key.Key_Space and e.modifiers() == Qt.KeyboardModifier.NoModifier and self.currentRow() >= 0 \
                and self.state() != QAbstractItemView.State.EditingState:
            self.previewRequested.emit(self.currentRow())
            e.accept()
            return
        if k == Qt.Key.Key_F2 and self.currentRow() >= 0:
            self.edit_title(self.currentRow())
            e.accept()
            return
        if k == Qt.Key.Key_Delete and e.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.deleteRequested.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def __init__(self, _rows: int, _cols: int, icon: str, title: str, sub: str = "", parent=None):
        super().__init__(parent)
        self.empty = (icon, title, sub)
        self.setModel(TaskTableModel(self))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.hover_row, self._prev_row = -1, -1
        self.hover_btn, self._prev_btn, self._hover_btn_row = -1, -1, -1
        self._row_t = _Anim(self.viewport(), 1.0, 170, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._btn_t = _Anim(self.viewport(), 1.0, 140, QEasingCurve(QEasingCurve.Type.OutCubic))
        self._press: tuple[int, int] | None = None
        self.model().modelReset.connect(self._apply_bands)

    def edit_title(self, row: int) -> None:
        """Inline title editing (F2 / double-click on the title): Enter saves, Esc cancels."""
        if 0 <= row < self.rowCount():
            idx = self.model().index(row, COL_TITLE)
            self.setCurrentIndex(idx)
            self.scrollTo(idx)
            self.edit(idx)

    def _apply_bands(self) -> None:
        """Group headers live in the top BAND px of the first row of each group (rows stay 1:1 with tasks)."""
        m = self.model()
        base = self.verticalHeader().defaultSectionSize()
        for r in getattr(self, "_banded", ()):                      # a reset keeps old section sizes: undo them first
            if r < m.rowCount():
                self.setRowHeight(r, base)
        for r in m.starts:
            self.setRowHeight(r, base + BAND)
        self._banded = list(m.starts)

    # ---------------------------------------------------- QTableWidget-like helpers ---
    def rowCount(self) -> int:  # noqa: N802
        return self.model().rowCount()

    def columnCount(self) -> int:  # noqa: N802
        return self.model().columnCount()

    def item(self, r: int, c: int) -> _ItemRef | None:
        return _ItemRef(self, r, c) if 0 <= r < self.rowCount() and 0 <= c < self.columnCount() else None

    def selectedItems(self) -> list[_ItemRef]:  # noqa: N802
        return [_ItemRef(self, i.row(), i.column()) for i in self.selectionModel().selectedIndexes()]

    def setCurrentCell(self, r: int, c: int) -> None:  # noqa: N802
        self.setCurrentIndex(self.model().index(r, c))

    def currentRow(self) -> int:  # noqa: N802
        return self.currentIndex().row()

    def clear(self) -> None:
        """Drop every task (and every memoised cell text) - called when the vault locks."""
        m = self.model()
        m.beginResetModel()
        m.rows, m._memo = [], {}
        for name in ("starts", "gkeys", "gcount"):          # grouped mode: no header bands over a locked, empty table
            if hasattr(m, name):
                setattr(m, name, type(getattr(m, name))())
        self._banded = []
        m.endResetModel()
        self.reset_hover()

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedIndexes()})

    def setHorizontalHeaderLabels(self, labels) -> None:  # noqa: N802
        self.model().heads = list(labels) + [""] * (8 - len(labels))
        self.model().headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 7)

    def task_id(self, row: int) -> str | None:
        m = self.model()
        return m.rows[row]["id"] if 0 <= row < len(m.rows) else None

    def _paint_groups(self) -> None:
        """Group headers (in each first row's band) plus one sticky header that stays pinned while its group scrolls."""
        m = self.model()
        if not m.starts:
            return
        pal = _fpal(self)
        vp = self.viewport()
        p = QPainter(vp)
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1.0))
        f.setBold(True)
        p.setFont(f)
        top_row = self.rowAt(0)
        if top_row < 0:
            top_row = 0
        g0 = m.group_at(top_row)
        n = len(m.starts)
        for g in range(max(0, g0), n):
            r = m.starts[g]
            y = self.rowViewportPosition(r)
            if y > vp.height():
                break
            if g == g0 and y < 0:                                       # sticky: pinned to the top, pushed up by the next
                ny = self.rowViewportPosition(m.starts[g + 1]) if g + 1 < n else 10 ** 6
                y = min(0, ny - BAND)
                p.fillRect(0, y, vp.width(), BAND, QColor(pal["panel"]))
                p.fillRect(0, y + BAND - 1, vp.width(), 1, QColor(pal["line"]))
            self._paint_header(p, QRectF(0, y, vp.width(), BAND), m.gkeys[g], m.group_title(g), pal)
        p.end()

    @staticmethod
    def _paint_header(p: QPainter, r: QRectF, key: str, title: tuple[str, str], pal: dict) -> None:
        tone = {"late": pal["danger"], "today": pal["acc_text"]}.get(key, pal["muted"])
        name, count = title
        area = r.adjusted(18, 6, -18, 0)
        p.setPen(QColor(tone))
        p.drawText(area, AL_R | Qt.AlignmentFlag.AlignVCenter, name)
        nw = p.fontMetrics().horizontalAdvance(name)
        f = QFont(p.font())
        f.setBold(False)
        p.setFont(f)                                                 # the count is quieter than the name
        p.setPen(QColor(pal["muted"]))
        p.drawText(area.adjusted(0, 0, -(nw + 10), 0), AL_R | Qt.AlignmentFlag.AlignVCenter, count)
        f.setBold(True)
        p.setFont(f)

    def _quiet_selection(self) -> None:
        """The style paints a selected row with the palette's Highlight (brand colour) *before* our delegate runs;
        that would peek out of a group's header band. Make it the theme's soft surface instead."""
        soft = QColor(_fpal(self)["soft"])
        pal = self.palette()
        if pal.color(QPalette.ColorRole.Highlight) != soft:
            pal.setColor(QPalette.ColorRole.Highlight, soft)
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(_fpal(self)["text"]))
            self.setPalette(pal)

    def paintEvent(self, e) -> None:  # noqa: N802
        self._quiet_selection()
        super().paintEvent(e)
        self._paint_groups()
        if self.rowCount() == 0 and getattr(self, "overlay", None) is None:
            _paint_empty(self, *self.empty)

    # ------------------------------------------------------------ state ---
    def row_hover(self, row: int) -> float:
        """0..1 - how strongly the wash of this row shows right now (fades in for the new row, out for the old)."""
        if row == self.hover_row:
            return self._row_t.value if self._prev_row != row else 1.0
        if row == self._prev_row:
            return 1.0 - self._row_t.value
        return 0.0

    def btn_hover(self, row: int, b: int) -> float:
        if row == self._hover_btn_row and b == self.hover_btn:
            return self._btn_t.value
        if row == self._hover_btn_row and b == self._prev_btn:
            return 1.0 - self._btn_t.value
        return 0.0

    def reset_hover(self) -> None:
        self.hover_row = self._prev_row = -1
        self.hover_btn = self._prev_btn = self._hover_btn_row = -1
        self.viewport().update()

    def _set_row(self, row: int) -> None:
        if row != self.hover_row:
            self._prev_row, self.hover_row = self.hover_row, row
            self._row_t.set(0.0)
            self._row_t.to(1.0)

    def _set_btn(self, row: int, b: int) -> None:
        if (row, b) != (self._hover_btn_row, self.hover_btn):
            self._prev_btn = self.hover_btn if row == self._hover_btn_row else -1
            self.hover_btn, self._hover_btn_row = b, row
            self._btn_t.set(0.0)
            self._btn_t.to(1.0)

    def button_at(self, pos) -> tuple[int, int]:
        """(row, button index) under a viewport point, or (row, -1) / (-1, -1)."""
        row = self.rowAt(int(pos.y()))
        if row < 0:
            return -1, -1
        if self.columnAt(int(pos.x())) != COL_ACT or self.isColumnHidden(COL_ACT):
            return row, -1
        cell = QRectF(self.visualRect(self.model().index(row, COL_ACT)))
        cell.setTop(cell.top() + self.model().band(row))
        for i, r in enumerate(button_rects(cell)):
            if r.adjusted(-2, -2, 2, 2).contains(QPointF(pos)):
                return row, i
        return row, -1

    # ----------------------------------------------------------- events ---
    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.resized.emit()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        row, b = self.button_at(e.position())
        self._set_row(row)
        self._set_btn(row, b)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if b >= 0 else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._set_row(-1)
        self._set_btn(-1, -1)
        self.viewport().unsetCursor()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            row, b = self.button_at(e.position())
            if b >= 0:                                       # a press on a round button never changes the selection
                self._press = (row, b)
                self.viewport().update()
                e.accept()
                return
        self._press = None
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._press is not None and e.button() == Qt.MouseButton.LeftButton:
            row, b = self.button_at(e.position())
            hit, self._press = self._press, None
            self.viewport().update()
            if (row, b) == hit:
                self.actionRequested.emit(row, ACTIONS[b][1])
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        if self.button_at(e.position())[1] >= 0:             # a fast second click on a button is not "edit row"
            self.mousePressEvent(e)
            return
        super().mouseDoubleClickEvent(e)

    def viewportEvent(self, e) -> bool:  # noqa: N802
        if e.type() == QEvent.Type.ToolTip:
            _row, b = self.button_at(e.pos())
            if b >= 0:
                QToolTip.showText(e.globalPos(), ACTIONS[b][2], self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(e)


class _TitleEdit(QLineEdit):
    """Inline title editor. Handles Enter / Esc itself and *accepts* the key, so it can never leak to the table
    (where Enter means "open the full editor")."""

    def __init__(self, parent, delegate):
        super().__init__(parent)
        self._d = delegate
        self._done = False

    def _finish(self, commit: bool) -> None:
        if self._done:
            return
        self._done = True
        if commit:
            self._d.commitData.emit(self)
        self._d.closeEditor.emit(self, QStyledItemDelegate.EndEditHint.NoHint)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish(True)
            e.accept()
        elif e.key() == Qt.Key.Key_Escape:
            self._finish(False)
            e.accept()
        else:
            super().keyPressEvent(e)


class TaskCellDelegate(CheckCellDelegate):
    """One delegate for every column of the tasks table (see the module docstring for the column map)."""

    ROW_H = 46

    def sizeHint(self, opt, idx):  # noqa: N802
        return QSize(60, self.ROW_H) if idx.column() == COL_CHECK else super(CheckCellDelegate, self).sizeHint(opt, idx)

    def editorEvent(self, ev, model, opt, idx):  # noqa: N802
        if idx.column() == COL_CHECK:
            return super().editorEvent(ev, model, opt, idx)
        return False                                         # only the first column toggles the check state

    # ------------------------------------------------------------ paint ---
    def _wash(self, p: QPainter, opt, idx, pal: dict) -> None:
        tbl = opt.widget
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        if sel:
            p.fillRect(opt.rect, QColor(pal["soft"]))
        t = tbl.row_hover(idx.row()) if isinstance(tbl, HoverTable) else 0.0
        if t > 0.004:
            p.fillRect(opt.rect, alpha(pal["accent"], HoverTable.HOVER_A * t * (0.6 if sel else 1.0)))
            if idx.column() == COL_CHECK:                    # slim accent bar on the start edge (right in RTL)
                p.fillRect(QRectF(opt.rect.right() - 2.5, opt.rect.top() + 9, 3, opt.rect.height() - 18), alpha(pal["accent"], 0.9 * t))

    def _shift(self, opt, idx):
        """Grouped mode: the top BAND px of a group's first row belong to its header - content is painted below."""
        m = idx.model()
        b = m.band(idx.row()) if hasattr(m, "band") else 0
        if b:
            opt = type(opt)(opt)
            opt.rect = opt.rect.adjusted(0, b, 0, 0)
        return opt

    def createEditor(self, parent, opt, idx):  # noqa: N802
        if idx.column() != COL_TITLE:
            return None
        ed = _TitleEdit(parent, self)
        ed.setFrame(False)
        ed.setTextMargins(6, 0, 6, 0)
        ed.setMaxLength(300)
        return ed

    def setEditorData(self, ed, idx) -> None:  # noqa: N802
        ed.setText(idx.data(Qt.ItemDataRole.EditRole) or "")
        ed.selectAll()

    def setModelData(self, ed, model, idx) -> None:  # noqa: N802
        model.setData(idx, ed.text(), Qt.ItemDataRole.EditRole)

    def updateEditorGeometry(self, ed, opt, idx) -> None:  # noqa: N802
        ed.setGeometry(self._shift(opt, idx).rect.adjusted(2, 5, -2, -5))

    def paint(self, p, opt, idx):  # noqa: D401
        col = idx.column()
        opt = self._shift(opt, idx)
        pal = _fpal(opt.widget)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._wash(p, opt, idx, pal)
        if col == COL_CHECK:
            r = QRectF(0, 0, 22, 22)
            r.moveCenter(QRectF(opt.rect).center())
            ck = micro.check_k(opt.widget, idx.data(UR))
            paint_check(p, r, is_checked(idx.data(Qt.ItemDataRole.CheckStateRole)), pal,
                        bool(opt.state & QStyle.StateFlag.State_MouseOver), ck[0] if ck else None)
        elif col in (COL_PRIO, COL_STATUS) and idx.data() and idx.data(Qt.ItemDataRole.UserRole + 5):
            paint_badge(p, QRectF(opt.rect), idx.data(), idx.data(Qt.ItemDataRole.UserRole + 5), opt.font, pal,
                        dot=(col == COL_STATUS))
        elif col == COL_ACT:
            self._paint_buttons(p, opt, idx, pal)
        else:
            p.restore()
            p.save()
            o = type(opt)(opt)
            o.state &= ~QStyle.StateFlag.State_Selected      # the wash is already painted; keep default text painting
            o.state &= ~QStyle.StateFlag.State_HasFocus
            super(CheckCellDelegate, self).paint(p, o, idx)
            if col == COL_TITLE:
                self._paint_sweep(p, o, idx, pal)
        p.restore()

    def initStyleOption(self, option, index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        if index.column() == COL_TITLE and micro._CHK:
            ck = micro.check_k(option.widget, index.data(UR))
            if ck:                                           # mid-transition: the strike is drawn by _paint_sweep
                s = micro.sweep(*ck)
                f = QFont(option.font)
                f.setStrikeOut(False)
                option.font = f
                pal = _fpal(option.widget)
                option.palette.setColor(QPalette.ColorRole.Text, mix(QColor(pal["text"]), QColor(pal["muted"]), s))

    def _paint_sweep(self, p: QPainter, opt, idx, pal: dict) -> None:
        ck = micro.check_k(opt.widget, idx.data(UR)) if micro._CHK else None
        if not ck:
            return
        s = micro.sweep(*ck)
        if s <= 0.01:
            return
        o = type(opt)(opt)
        self.initStyleOption(o, idx)
        rect = QRectF(opt.widget.style().subElementRect(QStyle.SubElement.SE_ItemViewItemText, o, opt.widget))
        fm = QFontMetrics(o.font)
        tw = min(fm.horizontalAdvance(idx.data() or ""), rect.width() - 6)
        y = rect.center().y() - fm.height() / 2 + fm.ascent() - fm.strikeOutPos()
        p.setPen(QPen(mix(QColor(pal["text"]), QColor(pal["muted"]), 0.6), fm.lineWidth()))
        p.drawLine(QPointF(rect.right() - 3, y), QPointF(rect.right() - 3 - tw * s, y))

    def _paint_buttons(self, p: QPainter, opt, idx, pal: dict) -> None:
        tbl = opt.widget
        row = idx.row()
        hovered_row = isinstance(tbl, HoverTable) and tbl.row_hover(row)
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        reveal = 1.0 if sel else float(hovered_row or 0.0)
        pressed = getattr(tbl, "_press", None)
        for i, r in enumerate(button_rects(QRectF(opt.rect))):
            kind = ACTIONS[i][1]
            base = 0.45 + 0.55 * reveal if kind == "more" else reveal        # calm rows: only ⋮ stays, dimmed
            if base <= 0.01:
                continue
            h = tbl.btn_hover(row, i) if isinstance(tbl, HoverTable) else 0.0
            down = pressed == (row, i)
            danger = kind == "delete"
            tone = QColor(pal["danger"] if danger else pal["accent"])
            rr_ = r.adjusted(1, 1, -1, -1) if down else r
            p.setOpacity(base)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 40 if QColor(pal["bg"]).lightness() < 128 else 16))      # tiny drop shadow
            p.drawEllipse(rr_.translated(0, 1.2))
            fill = mix(QColor(pal["panel2"]), tone, 0.20 * h)
            p.setBrush(fill)
            p.setPen(QPen(mix(QColor(pal["line"]), tone, 0.75 * h), 1))
            p.drawEllipse(rr_)
            ic = mix(QColor(pal["muted"]), QColor(pal["danger"] if danger else pal["acc_text"]), h)
            pm = icons.pixmap(ACTIONS[i][0], ic.name(), 15)
            s = 15
            p.drawPixmap(int(rr_.center().x() - s / 2), int(rr_.center().y() - s / 2), pm)
        p.setOpacity(1.0)
