# SPDX-License-Identifier: GPL-3.0-or-later
"""Small reusable widgets: Jalali date picker, heatmap, bar chart, cards."""
from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from ..core import jalali
from .theme import PALETTES


class CardFrame(QFrame):
    """The standard surface card. On dark themes it is built like a small object rather than a flat fill: a film of
    grain, a lit top edge, an inner "cut edge" (light above, dark below) and a soft floor shadow along the bottom.
    ``crest=True`` adds four gilt corner ticks (hero cards); ``lively=True`` gives it the shared hover language
    (brand.HoverLight: pointer light, spotlight border, one gilt glint)."""

    def __init__(self, *a, crest: bool = False, lively: bool = False, **k):
        super().__init__(*a, **k)
        self.setProperty("crest", crest)
        self.setProperty("lively", lively)
        self._hl = None
        if lively:
            self.set_lively(True)

    def set_lively(self, on: bool) -> None:
        from . import brand
        self.setProperty("lively", on)
        if on and self._hl is None:
            self._hl = brand.HoverLight(self)

    def enterEvent(self, e) -> None:  # noqa: N802
        if self._hl is not None:
            self._hl.enter()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        if self._hl is not None:
            self._hl.leave()
        super().leaveEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        if self._hl is not None:
            self._hl.stop()
        super().hideEvent(e)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        from .fx_widgets import _fpal
        pal = _fpal(self)
        if self.width() < 40 or self.height() < 24:
            return
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainter
        from . import brand, theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rad = theme.RADIUS[0] + 4
        if QColor(pal["bg"]).lightness() < 128:
            brand.paint_depth(p, QRectF(self.rect()), rad, pal, crest=bool(self.property("crest")))
        if self._hl is not None:
            self._hl.paint(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), rad, pal)
        p.end()


def card(layout_cls=QVBoxLayout, margins=(16, 14, 16, 14), spacing=10) -> tuple[QFrame, object]:
    f = CardFrame(lively=True)                                   # every card carries the pointer light (timer runs only while hovered)
    f.setObjectName("Card")
    lay = layout_cls(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


class PathLabel(QLabel):
    """A file path that never widens its layout. A word-wrapped QLabel cannot break "C:\\Users\\...\\AppData\\...", so its
    minimum width became the whole path and pushed the settings page into a horizontal scroll. This one elides the middle
    to fit whatever width it gets and keeps the full path in its tooltip."""

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full = ""
        self.setObjectName("Muted")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._elide()

    def text(self) -> str:
        return self._full                                    # callers (and tests) always see the whole path

    def _elide(self) -> None:
        w = max(0, self.width() - 2)
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideMiddle, w) if w > 8 else self._full
        if shown != super().text():
            super().setText(shown)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._elide()
        super().resizeEvent(e)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(40, QFontMetrics(self.font()).height() + 2)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(min(QFontMetrics(self.font()).horizontalAdvance(self._full) + 2, 420), QFontMetrics(self.font()).height() + 2)


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    if name == "H1" and not wrap:
        from .anim import ScrambleLabel          # page titles shuffle into place when the page opens
        lb: QLabel = ScrambleLabel(text)
    else:
        lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def button(text: str, kind: str = "", slot=None) -> QPushButton:
    if kind == "Link":
        from .anim import LinkButton             # text links get the animated underline
        b: QPushButton = LinkButton(text)
    else:
        from .micro import PressButton
        b = PressButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(lambda _=False: slot())
    return b


class _Stepper(QPushButton):
    """The round − / + inside a FaSpinBox; holds to repeat."""
    pressed_step = pyqtSignal()

    def __init__(self, glyph: str, owner):
        super().__init__(owner)
        self.glyph, self.owner = glyph, owner
        self.setFixedSize(26, 26)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(70)
        self.setFlat(True)
        self.clicked.connect(self.pressed_step)
        self.setAccessibleName("کاهش" if glyph == "−" else "افزایش")

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES.get(getattr(self.window(), "theme", "dark")) or next(iter(PALETTES.values()))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.owner.isEnabled() and (self.glyph == "+" and self.owner.value() < self.owner.maximum()
                                         or self.glyph == "−" and self.owner.value() > self.owner.minimum())
        if self.underMouse() and on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pal["soft"]))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QPen(QColor(pal["text"] if on else pal["line"]), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = r.center()
        p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() + 5, c.y()))
        if self.glyph == "+":
            p.drawLine(QPointF(c.x(), c.y() - 5), QPointF(c.x(), c.y() + 5))
        p.end()


class FaSpinBox(QSpinBox):
    """QSpinBox that shows Persian digits (and still accepts Latin or Persian typing)."""
    _BACK = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    STEP_W = 30

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)       # «−  ۲۵  +»: two round steppers instead of the tiny arrows
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(38)
        self._minus, self._plus = _Stepper("−", self), _Stepper("+", self)
        self._minus.pressed_step.connect(lambda: self.stepBy(-1))
        self._plus.pressed_step.connect(lambda: self.stepBy(1))
        le = self.lineEdit()
        if le is not None:
            le.setTextMargins(self.STEP_W, 0, self.STEP_W, 0)

    def sizeHint(self):  # noqa: N802
        h = super().sizeHint()
        h.setWidth(h.width() + 2 * self.STEP_W)
        h.setHeight(max(h.height(), 38))
        return h

    def minimumSizeHint(self):  # noqa: N802
        h = super().minimumSizeHint()
        h.setWidth(h.width() + 2 * self.STEP_W)
        return h

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        h = self.height() - 8
        self._minus.setGeometry(4, 4, h, h)
        self._plus.setGeometry(self.width() - 4 - h, 4, h, h)

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        if hasattr(self, "_plus"):
            self._plus.update()
            self._minus.update()

    def textFromValue(self, v: int) -> str:  # noqa: N802
        return jalali.fa(v)

    def valueFromText(self, text: str) -> int:  # noqa: N802
        t = text.translate(self._BACK)
        for part in (self.prefix(), self.suffix()):
            if part:
                t = t.replace(part.translate(self._BACK), "")
        digits = "".join(ch for ch in t if ch.isdigit())
        return int(digits) if digits else self.minimum()

    def validate(self, text: str, pos: int):
        from PyQt6.QtGui import QValidator
        t = text.translate(self._BACK)
        for part in (self.prefix(), self.suffix()):
            if part:
                t = t.replace(part.translate(self._BACK), "")
        t = t.strip()
        if t == self.specialValueText().strip() or not t:
            return (QValidator.State.Intermediate if not t else QValidator.State.Acceptable, text, pos)
        if not t.isdigit():
            return (QValidator.State.Invalid, text, pos)
        v = int(t)
        ok = self.minimum() <= v <= self.maximum()
        return (QValidator.State.Acceptable if ok else QValidator.State.Intermediate, text, pos)


class PasswordEdit(QWidget):
    """Password field with a show/hide toggle."""
    returnPressed = pyqtSignal()

    def __init__(self, placeholder: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.edit.returnPressed.connect(self.returnPressed)
        self.textChanged = self.edit.textChanged
        from .fx_widgets import EyeToggle
        self.eye = EyeToggle()
        self.eye.setToolTip("نمایش / پنهان‌کردن")
        self.eye.toggled.connect(lambda on: self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.eye)

    def text(self) -> str:
        return self.edit.text()

    def clear(self) -> None:
        self.edit.clear()
        self.eye.setChecked(False)

    def setFocus(self, *a):  # noqa: N802
        self.edit.setFocus(*a)


class JalaliDateEdit(QWidget):
    """A day on the vault's {jy,jm,jd} dicts: a pill that opens a small Jalali calendar. Optional «no date» checkbox.
    ``year`` / ``month`` / ``day`` stay as hidden state holders so the value logic (and old callers) are unchanged."""

    changed = pyqtSignal()

    def __init__(self, optional: bool = True, value: dict | None = None):
        super().__init__()
        from .datepick import DateButton
        from .fx_widgets import Combo
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.optional = optional
        self.enabled_cb = QCheckBox("تاریخ")
        self.enabled_cb.setMinimumWidth(96)                       # «تاریخ» and «تا تاریخ» rows line their pills up
        self.year, self.month, self.day = Combo(self), Combo(self), Combo(self)
        for c in (self.year, self.month, self.day):
            c.hide()
        today = jalali.today_jalali()
        for y in range(today["jy"] - 3, today["jy"] + 8):
            self.year.addItem(jalali.fa(y), y)
        for i, m in enumerate(jalali.MONTHS_FA):
            self.month.addItem(m, i + 1)
        self.btn = DateButton()
        self.btn.changed.connect(self._from_calendar)
        if optional:
            lay.addWidget(self.enabled_cb)
            self.enabled_cb.toggled.connect(self._sync_enabled)
        lay.addWidget(self.btn)
        lay.addStretch(1)
        self.month.currentIndexChanged.connect(self._fill_days)
        self.year.currentIndexChanged.connect(self._fill_days)
        self.set_value(value if value else (None if optional else today))

    def _fill_days(self) -> None:
        y, m = self.year.currentData(), self.month.currentData()
        if y is None or m is None:
            return
        cur = self.day.currentData() or 1
        self.day.blockSignals(True)
        self.day.clear()
        for d in range(1, jalali.month_length(y, m) + 1):
            self.day.addItem(jalali.fa(d), d)
        self.day.setCurrentIndex(min(cur, self.day.count()) - 1)
        self.day.blockSignals(False)

    def _sync_enabled(self, on: bool) -> None:
        self.btn.setEnabled(on)
        self.btn.update()

    def _from_calendar(self, v: dict) -> None:
        self.set_value(v)
        self.changed.emit()

    def set_value(self, due: dict | None) -> None:
        base = due or jalali.today_jalali()
        if self.year.findData(base["jy"]) < 0:
            self.year.addItem(jalali.fa(base["jy"]), base["jy"])
        self.year.setCurrentIndex(self.year.findData(base["jy"]))
        self.month.setCurrentIndex(base["jm"] - 1)
        self._fill_days()
        self.day.setCurrentIndex(base["jd"] - 1)
        if self.optional:
            self.enabled_cb.setChecked(due is not None)
            self._sync_enabled(due is not None)
        self.btn.set_value(self._raw())

    def _raw(self) -> dict:
        return {"jy": self.year.currentData(), "jm": self.month.currentData(), "jd": self.day.currentData()}

    def value(self) -> dict | None:
        if self.optional and not self.enabled_cb.isChecked():
            return None
        return self._raw()


class Heatmap(QWidget):
    """GitHub-style habit heatmap. Weeks run right->left (Persian week: Sat..Fri)."""
    dayClicked = pyqtSignal(object)   # datetime.date

    def __init__(self, weeks: int = 20, theme: str = "dark"):
        super().__init__()
        self.max_weeks, self.weeks, self.log, self.theme = weeks, weeks, {}, theme
        self.cell, self.gap = 13, 3
        self.setFixedHeight(7 * (self.cell + self.gap) + 4)
        self.setMinimumWidth(8 * (self.cell + self.gap))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, log: dict, theme: str) -> None:
        self.log, self.theme = log or {}, theme
        self.update()

    def resizeEvent(self, e):  # noqa: N802
        # cells grow (11..20 px) so the grid fills the card instead of leaving a blank strip
        w = max(self.width(), 1)
        cell = max(11, min(20, int(w / self.max_weeks) - self.gap))
        if cell != self.cell:
            self.cell = cell
            self.setFixedHeight(7 * (self.cell + self.gap) + 4)
        step = self.cell + self.gap
        self.weeks = max(8, min(self.max_weeks, w // step))
        super().resizeEvent(e)

    def _first(self) -> dt.date:
        today = dt.date.today()
        sat = today - dt.timedelta(days=jalali.weekday_index(today))
        return sat - dt.timedelta(weeks=self.weeks - 1)

    def _rect(self, col: int, row: int) -> QRectF:
        step = self.cell + self.gap
        x = self.width() - (col + 1) * step
        return QRectF(x, row * step + 2, self.cell, self.cell)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = PALETTES[self.theme]
        first, today = self._first(), dt.date.today()
        for col in range(self.weeks):
            for row in range(7):
                d = first + dt.timedelta(weeks=col, days=row)
                if d > today:
                    continue
                on = d.isoformat() in self.log
                if on:
                    p.setBrush(QColor(c["accent"]))
                    p.setPen(Qt.PenStyle.NoPen)
                else:
                    off = QColor(c["muted"])
                    off.setAlphaF(0.20)
                    p.setBrush(off)
                    p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(self._rect(col, row), self.cell * 0.28, self.cell * 0.28)
                if d == today:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(c["accent"]), 1.4))
                    p.drawRoundedRect(self._rect(col, row).adjusted(-1, -1, 1, 1), self.cell * 0.32, self.cell * 0.32)

    def mousePressEvent(self, e):  # noqa: N802
        first, today = self._first(), dt.date.today()
        pt = e.position()
        for col in range(self.weeks):
            for row in range(7):
                if self._rect(col, row).contains(pt):
                    d = first + dt.timedelta(weeks=col, days=row)
                    if d <= today:
                        self.dayClicked.emit(d)
                    return


class BarChart(QWidget):
    """Minimal vertical bar chart for a series of (label, value)."""

    def __init__(self, theme: str = "dark"):
        super().__init__()
        self.data: list[tuple[str, int]] = []
        self.theme = theme
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[tuple[str, int]], theme: str) -> None:
        self.data, self.theme = data, theme
        self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = PALETTES[self.theme]
        n = len(self.data)
        if not n:
            return
        mx = max(1, max(v for _, v in self.data))
        w, h = self.width(), self.height() - 6
        slot = w / n
        bw = max(3.0, slot * 0.62)
        p.setPen(QPen(QColor(c["line"]), 1))
        p.drawLine(QPointF(0, h), QPointF(w, h))
        p.setPen(Qt.PenStyle.NoPen)
        for i, (_lab, v) in enumerate(self.data):
            # RTL: newest on the left is confusing, so keep chronological right->left like the calendar
            x = w - (i + 1) * slot + (slot - bw) / 2
            bh = (h - 4) * (v / mx)
            p.setBrush(QColor(c["accent"] if v else c["panel2"]))
            p.drawRoundedRect(QRectF(x, h - max(bh, 2), bw, max(bh, 2)), 2, 2)


def one_accent(root: QWidget) -> None:
    """Brand colour on ONE button per page: when several filled «Primary» buttons are visible together, the empty
    state's call-to-action wins (else the first one, i.e. the page header's) and the rest turn neutral. Buttons living
    inside item views (per-row actions) are left alone."""
    from PyQt6.QtWidgets import QAbstractItemView
    cands = []
    for b in root.findChildren(QPushButton):
        if b.property("_prim") is None and b.objectName() == "Primary":
            b.setProperty("_prim", True)
        if not b.property("_prim") or not b.isVisibleTo(root):
            continue
        if not b.property("cta"):                                  # an empty-state CTA may sit inside a view's viewport
            p = b.parentWidget()
            while p is not None and p is not root and not isinstance(p, QAbstractItemView):
                p = p.parentWidget()
            if isinstance(p, QAbstractItemView):
                continue
        cands.append(b)
    if not cands:
        return
    win = next((b for b in reversed(cands) if b.property("cta")), cands[0])
    for b in cands:
        want = "Primary" if b is win else ""
        if b.objectName() != want:
            b.setObjectName(want)
            st = b.style()
            st.unpolish(b)
            st.polish(b)
