# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings sidebar (shadcn dialog-sidebar style) and breadcrumb."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .theme import AL_R
from .theme import rr as _rad
from . import icons
from .theme import PALETTES


def _theme(w: QWidget) -> str:
    win = w.window()
    return getattr(win, "theme", "dark")


class SettingsNav(QWidget):
    changed = pyqtSignal(int)
    ROW = 38

    def __init__(self, items):
        super().__init__()
        self.items = items
        self.cur = 0
        self.hover = -1
        self.setFixedWidth(200)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, self.ROW * len(self.items) + 16)

    def _at(self, pos) -> int:
        i = int((pos.y() - 8) // self.ROW)
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._at(e.position())
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self.hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._at(e.position())
        if i >= 0 and i != self.cur:
            self.cur = i
            self.update()
            self.changed.emit(i)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES[_theme(self)]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), _rad(12), _rad(12))
        for i, (_k, text, ic) in enumerate(self.items):
            r = QRectF(8, 8 + i * self.ROW, self.width() - 16, self.ROW - 4)
            on = i == self.cur
            if on or i == self.hover:
                c = QColor(pal["panel2"]) if on else QColor(pal["text"])
                if not on:
                    c.setAlphaF(0.04)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(r, _rad(8), _rad(8))
                if on:                                         # the same slim start-edge bar as the main navigation
                    p.setBrush(QColor(pal["accent"]))
                    p.drawRoundedRect(QRectF(r.right() - 5, r.center().y() - 8, 3, 16), 1.5, 1.5)
            col = pal["text"] if on else pal["muted"]
            p.drawPixmap(int(r.right() - 30), int(r.center().y() - 9), icons.pixmap(ic, col, 18))
            f = QFont(self.font())
            f.setBold(on)
            p.setFont(f)
            p.setPen(QColor(col))
            p.drawText(QRectF(r.left() + 8, r.top(), r.width() - 46, r.height()),
                       AL_R | Qt.AlignmentFlag.AlignVCenter, text)


class Breadcrumb(QWidget):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.setFixedHeight(34)

    def set_path(self, path) -> None:
        self.path = path
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES[_theme(self)]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = self.width() - 4
        for i, t in enumerate(self.path):
            last = i == len(self.path) - 1
            f = QFont(self.font())
            f.setBold(last)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(t)
            p.setPen(QColor(pal["text"] if last else pal["muted"]))
            p.drawText(QRectF(x - w, 0, w, self.height()), Qt.AlignmentFlag.AlignVCenter, t)
            x -= w
            if not last:  # chevron pointing left (RTL)
                p.setPen(QPen(QColor(pal["muted"]), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                cy = self.height() / 2
                x -= 12
                p.drawLine(int(x + 3), int(cy - 4), int(x - 1), int(cy))
                p.drawLine(int(x - 1), int(cy), int(x + 3), int(cy + 4))
                x -= 12


class ThemeCard(QWidget):
    """Large preview of one theme: a miniature window painted with that theme's own colours."""
    clicked = pyqtSignal(str)
    MIN_W, H = 150, 138

    def __init__(self, key: str, theme: dict):
        super().__init__()
        self.key, self.t, self.on, self.hover = key, theme, False, False
        self.setMinimumWidth(self.MIN_W)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self.setToolTip(f"{theme['fa']} — {theme['en']}")
        self.setAccessibleName(f"تم {theme['fa']}")

    def enterEvent(self, e) -> None:  # noqa: N802
        self.hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.key)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        c = self.t["pal"]
        cur = PALETTES[_theme(self)]
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rad = 12.0
        border = QColor(cur["accent"] if self.on else (cur["muted"] if self.hover else cur["line"]))
        p.setPen(QPen(border, 2.0 if self.on else 1.0))
        p.setBrush(QColor(c["bg"]))
        p.drawRoundedRect(r, rad, rad)
        # miniature window: sidebar strip on the right (RTL), two cards, accent button, ring
        p.setPen(Qt.PenStyle.NoPen)
        side = QRectF(r.right() - 34, r.top() + 1, 33, r.height() - 2)
        p.setBrush(QColor(c["panel"]))
        p.drawRoundedRect(side, rad - 1, rad - 1)
        for k in range(4):
            p.setBrush(QColor(c["accent"]) if k == 0 else QColor(c["line"]))
            p.drawRoundedRect(QRectF(side.left() + 8, side.top() + 14 + k * 11, 17, 5), 2.5, 2.5)
        body = QRectF(r.left() + 10, r.top() + 10, r.width() - 34 - 22, r.height() - 20)
        p.setBrush(QColor(c["panel"]))
        p.setPen(QPen(QColor(c["line"]), 1))
        p.drawRoundedRect(QRectF(body.left(), body.top(), body.width(), 34), 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["text"]))
        p.drawRoundedRect(QRectF(body.right() - 40, body.top() + 9, 30, 4.5), 2.2, 2.2)
        p.setBrush(QColor(c["muted"]))
        p.drawRoundedRect(QRectF(body.right() - 28, body.top() + 19, 18, 4), 2, 2)
        p.setBrush(QColor(c["accent"]))
        p.drawRoundedRect(QRectF(body.left() + 8, body.top() + 9, 26, 16), 5, 5)
        ring = QRectF(body.right() - 28, body.top() + 42, 26, 26)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(c["line"]), 4))
        p.drawEllipse(ring)
        p.setPen(QPen(QColor(c["accent2"]), 4, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, 90 * 16, -230 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["panel2"]))
        p.drawRoundedRect(QRectF(body.left(), body.top() + 42, body.width() - 38, 26), 6, 6)
        for k, key in enumerate(("accent", "accent2", "hi", "ok")):
            p.setBrush(QColor(c[key]))
            p.drawEllipse(QPointF(body.right() - 46 - 12 - k * 13, body.top() + 55), 4.2, 4.2)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        p.setFont(f)
        p.setPen(QColor(c["text"]))
        room = int(body.width() + 12)
        name = QFontMetrics(f).elidedText(self.t["fa"], Qt.TextElideMode.ElideLeft, room)
        p.drawText(QRectF(body.left() - 12, r.bottom() - 40, body.width() + 12, 18), AL_R | Qt.AlignmentFlag.AlignVCenter, name)
        if self.t.get("tag"):                                                  # the tag gets its own line: side by side the two collided
            f.setBold(False)
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
            p.setFont(f)
            p.setPen(QColor(c["muted"]))
            tag = QFontMetrics(f).elidedText(self.t["tag"], Qt.TextElideMode.ElideLeft, room)
            p.drawText(QRectF(body.left() - 12, r.bottom() - 23, body.width() + 12, 15), AL_R | Qt.AlignmentFlag.AlignVCenter, tag)
        if self.on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(cur["accent"]))
            p.drawEllipse(QPointF(r.left() + 16, r.top() + 16), 8, 8)
            p.drawPixmap(int(r.left() + 16 - 6), int(r.top() + 16 - 6), icons.pixmap("tick", cur["ink"], 12))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(cur["accent"]), 1.2, Qt.PenStyle.DotLine))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), rad + 1, rad + 1)


class _GroupHead(QWidget):
    """«تیره» / «روشن» - a quiet section title with the number of themes and a hairline running to the far side."""
    H = 26

    def __init__(self, text: str, n: int, parent=None):
        super().__init__(parent)
        self.text, self.n = text, n
        self.setFixedHeight(self.H)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _e) -> None:  # noqa: N802
        from ..core.jalali import fa
        pal = PALETTES[_theme(self)]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(self.text)
        rtl = self.isRightToLeft()
        x0 = self.width() - 2 if rtl else 2
        r = QRectF(x0 - w, 0, w, self.height()) if rtl else QRectF(x0, 0, w, self.height())
        p.setPen(QColor(pal["text"]))
        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignLeft, self.text)
        f.setBold(False)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        p.setFont(f)
        cnt = fa(self.n)
        cw = QFontMetrics(f).horizontalAdvance(cnt)
        cx = r.left() - 10 - cw if rtl else r.right() + 10
        p.setPen(QColor(pal["muted"]))
        p.drawText(QRectF(cx, 0, cw, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignLeft, cnt)
        y = self.height() / 2.0
        a, b = (2.0, cx - 12) if rtl else (cx + cw + 12, self.width() - 2.0)
        if b > a:
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.drawLine(QPointF(a, y), QPointF(b, y))


class ThemePicker(QWidget):
    """Every theme as a preview card, in two groups - «تیره» (dark) and «روشن» (light) - each a grid that re-flows with the
    width: ten cards in one row were 1500 px wide and pushed the whole settings page into a horizontal scroll. Between
    2 and 5 columns, each card at least ``ThemeCard.MIN_W`` wide. Positions are computed here (not by a layout), so the
    height the page needs is always known and exact."""
    picked = pyqtSignal(str)
    GAP = 12
    HEAD_GAP, GROUP_GAP = 8, 22
    GROUPS = (("dark", "تیره"), ("light", "روشن"))

    def __init__(self, themes: dict, order: list[str]):
        super().__init__()
        self.cards: dict[str, ThemeCard] = {}
        self.heads: dict[str, _GroupHead] = {}
        self._groups: list[tuple[str, list[str]]] = []
        for mode, title in self.GROUPS:
            keys = [k for k in order if themes[k].get("mode") == mode]
            if not keys:
                continue
            head = _GroupHead(title, len(keys), self)
            self.heads[mode] = head
            self._groups.append((mode, keys))
            for k in keys:
                c = ThemeCard(k, themes[k])
                c.setParent(self)
                c.clicked.connect(self.picked)
                self.cards[k] = c
        self._cols = 0
        self._need = 0
        self.setMinimumWidth(2 * ThemeCard.MIN_W + self.GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._place(4 * (ThemeCard.MIN_W + self.GAP) - self.GAP)

    @staticmethod
    def columns_for(width: int) -> int:
        return max(2, min(5, (width + ThemePicker.GAP) // (ThemeCard.MIN_W + ThemePicker.GAP)))

    def _place(self, width: int) -> None:
        cols = self.columns_for(width)
        self._cols = cols
        cw = (width - (cols - 1) * self.GAP) / cols
        rtl = self.isRightToLeft()
        y = 0
        for mode, keys in self._groups:
            self.heads[mode].setGeometry(0, y, width, _GroupHead.H)
            y += _GroupHead.H + self.HEAD_GAP
            for i, k in enumerate(keys):
                row, col = divmod(i, cols)
                x = width - (col + 1) * cw - col * self.GAP if rtl else col * (cw + self.GAP)
                self.cards[k].setGeometry(round(x), y + row * (ThemeCard.H + self.GAP), round(cw), ThemeCard.H)
            rows = -(-len(keys) // cols)
            y += rows * ThemeCard.H + (rows - 1) * self.GAP + self.GROUP_GAP
        need = max(0, y - self.GROUP_GAP)
        if need != self._need:
            self._need = need
            self.setMinimumHeight(need)
            self.setMaximumHeight(need)
            self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(4 * (ThemeCard.MIN_W + self.GAP) - self.GAP, self._need)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._place(self.width())
        super().resizeEvent(e)

    def set_current(self, key: str) -> None:
        for k, c in self.cards.items():
            c.on = k == key
            c.update()


class LivePreview(QWidget):
    """A tiny sample of the task list that follows the text-size and density controls while they are being changed."""

    SAMPLES = (("بازبینی طرح معماری", "کار", True), ("خرید هدیهٔ تولد", "شخصی", False), ("تماس با حسابدار", "مالی", False))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pt = 10
        self.dense = False
        self.setMinimumHeight(self._need())
        self.setAccessibleName("پیش‌نمایش")

    def _row_h(self) -> int:
        return int(self.pt * (2.4 if self.dense else 3.3))

    def _need(self) -> int:
        return self._row_h() * len(self.SAMPLES) + 28

    def set_look(self, pt: int | None = None, dense: bool | None = None) -> None:
        if pt is not None:
            self.pt = max(8, min(16, int(pt)))
        if dense is not None:
            self.dense = bool(dense)
        self.setMinimumHeight(self._need())
        self.setMaximumHeight(self._need())
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, self._need())

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = PALETTES.get(_theme(self)) or next(iter(PALETTES.values()))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(QColor(pal["bg"]))
        p.drawRoundedRect(r, _rad(10), _rad(10))
        f = QFont(self.font())
        f.setPointSizeF(float(self.pt))
        rtl = self.isRightToLeft()
        h = self._row_h()
        y = 14.0
        for i, (title, cat, done) in enumerate(self.SAMPLES):
            row = QRectF(14, y, self.width() - 28, h)
            if i:
                p.setPen(QPen(QColor(pal["line"]), 1))
                p.drawLine(QPointF(row.left(), y), QPointF(row.right(), y))
            cy = row.center().y()
            box = QRectF(row.right() - 18 if rtl else row.left(), cy - 8, 16, 16)
            p.setPen(QPen(QColor(pal["accent"] if done else pal["muted"]), 1.4))
            p.setBrush(QColor(pal["accent"]) if done else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 5, 5)
            if done:
                p.setPen(QPen(QColor(pal["bg"]), 1.8))
                p.drawLine(QPointF(box.left() + 4, cy), QPointF(box.left() + 7, cy + 3))
                p.drawLine(QPointF(box.left() + 7, cy + 3), QPointF(box.left() + 12, cy - 3))
            p.setFont(f)
            tcol = pal["muted"] if done else pal["text"]
            p.setPen(QColor(tcol))
            tx = QRectF(row.left() + 90, y, row.width() - 90 - 28, h) if rtl else QRectF(row.left() + 28, y, row.width() - 28 - 90, h)
            fm = QFontMetrics(f)
            p.drawText(tx, int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)),
                       fm.elidedText(title, Qt.TextElideMode.ElideRight, int(tx.width())))
            cf = QFont(f)
            cf.setPointSizeF(max(7.0, self.pt - 2))
            p.setFont(cf)
            p.setPen(QColor(pal["muted"]))
            cr = QRectF(row.left(), y, 80, h) if rtl else QRectF(row.right() - 80, y, 80, h)
            p.drawText(cr, int(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if rtl else Qt.AlignmentFlag.AlignRight)), cat)
            y += h
