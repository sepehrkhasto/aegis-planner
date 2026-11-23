# SPDX-License-Identifier: GPL-3.0-or-later
"""Small flat building blocks of the notes UI: icon buttons, colour dots, pills and a segmented switch.

Everything reads the live palette at paint time (``_fpal``), so a theme switch needs no restyling, and nothing here runs a
timer: hover and press are drawn from the widget state."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QWidget

from . import icons
from .fx_widgets import _fpal
from .premium import alpha
from .theme import rr


class FlatIconButton(QAbstractButton):
    """A quiet icon button: no frame at rest, a soft tint on hover, the accent tint when checked."""

    def __init__(self, icon_name: str, tip: str = "", size: int = 30, parent=None, *, danger: bool = False):
        super().__init__(parent)
        self.icon_name, self.danger = icon_name, danger
        self.setToolTip(tip)
        self.setAccessibleName(tip or icon_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedSize(size, size)
        self._hover = False

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        base = pal["danger"] if self.danger else pal["accent"]
        if on or self._hover or self.isDown():
            col = alpha(base, 0.22 if on else (0.16 if self.isDown() else 0.10))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(r, rr(9), rr(9))
        if self.hasFocus():
            p.setPen(QPen(alpha(pal["accent2"], 0.8), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, rr(9), rr(9))
        if not self.isEnabled():
            colr = alpha(pal["muted"], 0.4).name(QColor.NameFormat.HexArgb)
        elif self.danger and (self._hover or self.isDown()):
            colr = pal["danger"]
        else:
            colr = pal["acc_text"] if on else (pal["text"] if self._hover else pal["muted"])
        s = int(min(self.width(), self.height()) * 0.58)
        pm = icons.pixmap(self.icon_name, colr, s)
        p.drawPixmap(int((self.width() - s) / 2), int((self.height() - s) / 2), pm)


class ColorDot(QAbstractButton):
    """A round colour swatch (ink colour / note colour); a ring marks the chosen one."""

    def __init__(self, color_fn, tip: str = "", size: int = 22, parent=None):
        super().__init__(parent)
        self.color_fn = color_fn                      # called with the live palette -> hex, so dots follow the theme
        self.setCheckable(True)
        self.setToolTip(tip)
        self.setAccessibleName(tip or "color")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QRectF(self.rect()).center()
        rad = min(self.width(), self.height()) / 2 - 3.5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.color_fn(pal)))
        p.drawEllipse(c, rad, rad)
        if self.isChecked():
            p.setPen(QPen(alpha(pal["text"], 0.9), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rad + 3, rad + 3)
        elif self.underMouse():
            p.setPen(QPen(alpha(pal["muted"], 0.7), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rad + 3, rad + 3)

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(e)


class Pill(QAbstractButton):
    """A rounded text chip: folder filters in the gallery, shape names in the flow toolbar."""

    def __init__(self, text: str, parent=None, *, count: int | None = None, icon_name: str = ""):
        super().__init__(parent)
        self.setText(text)
        self.count, self.icon_name = count, icon_name
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedHeight(32)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self.text()) + 26
        if self.count is not None:
            w += fm.horizontalAdvance(str(self.count)) + 14
        if self.icon_name:
            w += 22
        return QSize(w, 32)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse() or self.isDown()
        p.setBrush(alpha(pal["accent"], 0.20) if on else (alpha(pal["accent"], 0.08) if hover else alpha(pal["panel"], 1.0)))
        p.setPen(QPen(alpha(pal["accent2"], 0.55) if on else QColor(pal["line"]), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.hasFocus():
            p.setPen(QPen(alpha(pal["accent2"], 0.8), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), r.height() / 2, r.height() / 2)
        col = QColor(pal["acc_text"] if on else pal["text"])
        x = r.right() - 13
        fm = p.fontMetrics()
        if self.icon_name:
            p.drawPixmap(int(x - 16), int(r.center().y() - 8), icons.pixmap(self.icon_name, col.name(), 16))
            x -= 22
        tw = fm.horizontalAdvance(self.text())
        p.setPen(col)
        p.drawText(QRectF(x - tw - 2, r.top(), tw + 4, r.height()), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.count is not None:
            cs = str(self.count)
            cw = fm.horizontalAdvance(cs) + 10
            cr = QRectF(x - tw - 8 - cw, r.center().y() - 9, cw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(alpha(pal["accent"], 0.16 if on else 0.10))
            p.drawRoundedRect(cr, 9, 9)
            p.setPen(QColor(pal["acc_text"] if on else pal["muted"]))
            p.drawText(cr, Qt.AlignmentFlag.AlignCenter, cs)

    def enterEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(e)


class Segmented(QWidget):
    """Two or three icon segments (grid / list): exactly one is on."""

    changed = pyqtSignal(str)

    def __init__(self, items: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self.items = items                              # (key, icon, tooltip)
        self.cur = items[0][0]
        self.setFixedSize(34 * len(items) + 6, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(" / ".join(i[2] for i in items))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Arrow keys (either direction) and Space move through the segments."""
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            keys = [i[0] for i in self.items]
            step = 1 if k != Qt.Key.Key_Left else -1
            self.set_current(keys[(keys.index(self.cur) + step) % len(keys)], True)
            return
        super().keyPressEvent(e)

    def set_current(self, key: str, emit: bool = False) -> None:
        if key == self.cur or key not in {i[0] for i in self.items}:
            return
        self.cur = key
        self.update()
        if emit:
            self.changed.emit(key)

    def _seg(self, i: int) -> QRectF:
        return QRectF(3 + 34 * i, 3, 34, 28)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        for i, (key, _ic, _tip) in enumerate(self.items):
            if self._seg(i).contains(e.position()):
                self.set_current(key, True)
                return

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(alpha(pal["accent2"], 0.8) if self.hasFocus() else QColor(pal["line"]), 1.4 if self.hasFocus() else 1))
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(r, rr(10), rr(10))
        for i, (key, ic, _tip) in enumerate(self.items):
            sr = self._seg(i)
            on = key == self.cur
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(alpha(pal["accent"], 0.20))
                p.drawRoundedRect(sr, rr(8), rr(8))
            col = pal["acc_text"] if on else pal["muted"]
            p.drawPixmap(int(sr.center().x() - 9), int(sr.center().y() - 9), icons.pixmap(ic, col, 18))

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.ToolTip:
            from PyQt6.QtWidgets import QToolTip
            for i, (_k, _ic, tip) in enumerate(self.items):
                if self._seg(i).contains(ev.pos().toPointF()):
                    QToolTip.showText(ev.globalPos(), tip, self)
                    return True
        return super().event(ev)


class FormatBar(QWidget):
    """The editor's tool strip: flat icon buttons in a soft rounded bar. Same small API as the old tool dock
    (``add_tool`` / ``button`` / ``add_gap`` / ``set_enabled_all``), laid out horizontally."""

    picked = pyqtSignal(str)

    def __init__(self, parent=None, size: int = 34):
        super().__init__(parent)
        from PyQt6.QtWidgets import QHBoxLayout
        self.size_ = size
        self._buttons: dict[str, FlatIconButton] = {}
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(8, 5, 8, 5)
        self._lay.setSpacing(2)
        self.setFixedHeight(size + 12)

    def add_tool(self, key: str, icon_name: str, tip: str, *, checkable: bool = False, danger: bool = False) -> FlatIconButton:
        b = FlatIconButton(icon_name, tip, self.size_, self, danger=danger)
        b.setCheckable(checkable)
        b.clicked.connect(lambda _=False, k=key: self.picked.emit(k))
        self._lay.addWidget(b)
        self._buttons[key] = b
        return b

    def add_gap(self, px: int = 8) -> None:
        self._lay.addSpacing(px)

    def add_sep(self) -> None:
        self._lay.addSpacing(5)
        sep = _Sep(self)
        self._lay.addWidget(sep)
        self._lay.addSpacing(5)

    def add_stretch(self) -> None:
        self._lay.addStretch(1)

    def button(self, key: str) -> FlatIconButton:
        return self._buttons[key]

    def set_enabled_all(self, on: bool) -> None:
        for b in self._buttons.values():
            b.setEnabled(on)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(alpha(pal["panel"], 1.0))
        p.drawRoundedRect(r, rr(14), rr(14))


class _Sep(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1, 20)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), alpha(_fpal(self)["line"], 0.9))
