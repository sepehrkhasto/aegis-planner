# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared page chrome: every page opens with the same header, the same engraved rule and the same toolbar rhythm.

``page_head`` builds: title + one-line subtitle on the start side (right), the page's actions on the end side (left), and a hairline
«engraved rule» under them with a short bright notch at the start - the brand's signature, the same one the PDF letterhead uses.
``toolbar`` lays a row of controls (search, chips, segmented switches, filters) at one fixed height and gap."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .fx_widgets import Combo, _fpal
from .widgets import label

BAR_H = 38                      # every control in a toolbar is this tall
HEAD_GAP = 12
TOOL_GAP = 8


class EngravedRule(QWidget):
    """A hairline across the page; the first 56px (the start side) glow in the accent colour and fade into the line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(9)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2.0
        line = QColor(pal["line"])
        w = float(self.width())
        right = QRectF(0, y - 0.5, w, 1.0)
        g = QLinearGradient(w, 0, 0, 0)                      # RTL: the start of the page is the right edge
        acc = QColor(pal["accent2"])
        acc.setAlpha(210)
        g.setColorAt(0.0, acc)
        g.setColorAt(min(0.2, 90.0 / max(w, 1.0)), line)
        g.setColorAt(1.0, QColor(line.red(), line.green(), line.blue(), 40))
        p.fillRect(right, g)
        p.end()


def _as_label(x, name: str) -> QLabel | None:
    if x is None:
        return None
    if isinstance(x, str):
        return label(x, name)
    return x


def page_head(title, sub=None, *actions: QWidget, rule: bool = True) -> QVBoxLayout:
    """Header block for a page. ``title``/``sub`` may be strings or ready labels (a page that updates them keeps its reference)."""
    box = QVBoxLayout()
    box.setSpacing(HEAD_GAP - 4)
    box.setContentsMargins(0, 0, 0, 0)
    row = QHBoxLayout()
    row.setSpacing(TOOL_GAP)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = _as_label(title, "H1")
    col.addWidget(t)
    s = _as_label(sub, "Muted")
    if s is not None:
        col.addWidget(s)
    row.addLayout(col)
    row.addStretch(1)
    for w in actions:
        row.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
    box.addLayout(row)
    if rule:
        box.addWidget(EngravedRule())
    return box


def toolbar(*items, stretch_first: bool = False) -> QHBoxLayout:
    """A row of controls with one gap; ``stretch_first`` lets the first widget (usually the search box) take the spare width."""
    row = QHBoxLayout()
    row.setSpacing(TOOL_GAP)
    row.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(items):
        if w is None:
            continue
        if isinstance(w, int):
            row.addSpacing(w)
        elif w == "stretch":
            row.addStretch(1)
        else:
            row.addWidget(w, 1 if (stretch_first and i == 0) else 0)
    return row


class ColHead(QWidget):
    """A board column's heading: a status dot, the name and a count pill (kanban)."""

    def __init__(self, name: str, tone: str = "muted", parent=None):
        super().__init__(parent)
        self.name, self.n, self.tone = name, 0, tone
        self.setFixedHeight(30)
        self.setAccessibleName(name)

    def set(self, name: str, n: int) -> None:
        self.name, self.n = name, n
        self.setAccessibleName(f"{name} ({n})")
        self.update()

    def setText(self, t: str) -> None:  # noqa: N802  (QLabel-compatible: "name (count)")
        self.name = t.rsplit(" (", 1)[0]
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from PyQt6.QtGui import QFont
        from ..core.jalali import fa
        from .premium import alpha
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        col = QColor(pal.get({"muted": "muted", "accent": "accent2", "ok": "ok"}.get(self.tone, "muted"), pal["muted"]))
        x = r.right() - 4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(x - 8, r.center().y() - 4, 8, 8))
        x -= 18
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(QColor(pal["text"]))
        tw = p.fontMetrics().horizontalAdvance(self.name)
        p.drawText(QRectF(x - tw - 2, 0, tw + 4, r.height()), Qt.AlignmentFlag.AlignCenter, self.name)
        x -= tw + 12
        p.setFont(self.font())
        cs = fa(self.n)
        cw = p.fontMetrics().horizontalAdvance(cs) + 14
        box = QRectF(x - cw, r.center().y() - 10, cw, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(pal["accent"], 0.12))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor(pal["muted"]))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, cs)
        p.end()


# ------------------------------------------------------------------------------------------------ chips ---
def _motion() -> bool:
    from .anim import MOTION
    return bool(MOTION[0])


def _mixc(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def _tint(c, a: float) -> QColor:
    c = QColor(c)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class ChipCombo(Combo):
    """A filter as a pill: at rest it shows only its caption («دسته»); once a value is chosen it turns into a soft accent
    pill that reads «دسته: کار». Same API (and the same floating drop-down) as ``Combo``; the first row is the «all» row."""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.caption = caption
        self.setFixedHeight(BAR_H)
        self.set_default(0)
        self.currentIndexChanged.connect(lambda _=0: self.updateGeometry())
        self.setAccessibleName(caption)

    def shown_text(self) -> str:
        return f"{self.caption}: {self.currentText()}" if self.is_filtering() else self.caption

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.shown_text()) + 2 * 14 + 22, BAR_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h = self._hov.value if self.isEnabled() else 0.0
        flt = self.is_filtering() and self.isEnabled()
        focus = self.hasFocus() or self._pop is not None
        rad = r.height() / 2
        if flt:
            fill, edge = _tint(pal["accent"], 0.15), _tint(pal["accent2"], 0.55)
            ink = QColor(pal["acc_text"])
        else:
            fill = _mixc(QColor(pal["panel"]), QColor(pal["panel2"]), h)
            edge = _mixc(QColor(pal["line"]), QColor(pal["muted"]), 0.35 * h)
            ink = _mixc(QColor(pal["muted"]), QColor(pal["text"]), 0.4 + 0.6 * h)
        if focus:
            edge = QColor(pal["accent2"])
        p.setPen(QPen(edge, 1.4 if focus else 1))
        p.setBrush(fill)
        p.drawRoundedRect(r, rad, rad)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        text = r.adjusted(14 + 14, 0, -14, 0) if rtl else r.adjusted(14, 0, -14 - 14, 0)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.Medium if flt else QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(ink)
        al = (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignAbsolute
        p.drawText(text, al | Qt.AlignmentFlag.AlignVCenter, self.shown_text())
        cx = r.left() + 14 if rtl else r.right() - 14
        cy, up = r.center().y(), (-1 if self._pop is not None else 1)
        p.setPen(QPen(ink, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(cx - 3.5, cy - 1.6 * up), QPointF(cx, cy + 1.6 * up), QPointF(cx + 3.5, cy - 1.6 * up)]))


class ChipToggle(QAbstractButton):
    """A checkable pill (e.g. «گروه‌بندی»): quiet outline when off, soft accent fill with a check dot when on."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(BAR_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._k = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=180)
        self._k.valueChanged.connect(self._step)
        self.toggled.connect(self._glide)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._kv = 1.0 if self.isChecked() else 0.0

    def _glide(self, on: bool) -> None:
        if not (_motion() and self.isVisible()):
            self._kv = 1.0 if on else 0.0
            self.update()
            return
        self._k.stop()
        self._k.setStartValue(self._kv)
        self._k.setEndValue(1.0 if on else 0.0)
        self._k.start()

    def _step(self, v) -> None:
        self._kv = float(v)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 2 * 14 + 20, BAR_H)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        k = self._kv
        h = 1.0 if self.underMouse() else 0.0
        off_fill = _mixc(QColor(pal["panel"]), QColor(pal["panel2"]), h)
        fill = _mixc(off_fill, _mixc(QColor(pal["panel"]), QColor(pal["accent"]), 0.16), k)
        edge = _mixc(_mixc(QColor(pal["line"]), QColor(pal["muted"]), 0.3 * h), QColor(pal["accent2"]), 0.55 * k)
        if self.hasFocus():
            edge = QColor(pal["accent2"])
        p.setPen(QPen(edge, 1.4 if self.hasFocus() else 1))
        p.setBrush(fill)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        ink = _mixc(_mixc(QColor(pal["muted"]), QColor(pal["text"]), 0.4 + 0.6 * h), QColor(pal["acc_text"]), k)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        dot_x = r.right() - 15 if rtl else r.left() + 15
        p.setPen(QPen(ink, 1.5))
        p.setBrush(_tint(ink, 0.18 + 0.82 * k))
        p.drawEllipse(QPointF(dot_x, r.center().y()), 4.0, 4.0)
        if k > 0.01:                                                   # a tick grows inside the dot
            p.setPen(QPen(QColor(pal["bg"]), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            c = QPointF(dot_x, r.center().y())
            s = k * 1.0
            p.drawPolyline(QPolygonF([QPointF(c.x() - 1.9 * s, c.y() + 0.1 * s), QPointF(c.x() - 0.5 * s, c.y() + 1.5 * s),
                                      QPointF(c.x() + 2.0 * s, c.y() - 1.4 * s)]))
        p.setPen(ink)
        f = QFont(self.font())
        f.setWeight(QFont.Weight.Medium if self.isChecked() else QFont.Weight.Normal)
        p.setFont(f)
        tr = r.adjusted(14, 0, -(14 + 12), 0) if rtl else r.adjusted(14 + 12, 0, -14, 0)
        al = (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignAbsolute
        p.drawText(tr, al | Qt.AlignmentFlag.AlignVCenter, self.text())


class ChoiceTabs(QWidget):
    """«باز / انجام‌شده / همه»: a pill track with a thumb that glides to the chosen text. Speaks the ``Combo`` dialect
    (addItem / currentData / currentIndex / setCurrentIndex / findData / currentIndexChanged) so it can replace one."""

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, object]] = []
        self._cur = 0
        self._x, self._w = 0.0, 0.0
        self._from = self._to = (0.0, 0.0)
        self._a = QVariantAnimation(self, duration=240)
        self._a.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        self._a.valueChanged.connect(self._glide)
        self.setFixedHeight(BAR_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self._hover = -1
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    # ---- Combo-like API
    def addItem(self, text: str, data=None) -> None:  # noqa: N802
        self._items.append((text, data))
        self.updateGeometry()
        self._snap()

    def count(self) -> int:
        return len(self._items)

    def value(self):
        return self.currentData()

    def currentIndex(self) -> int:  # noqa: N802
        return self._cur

    def currentData(self):  # noqa: N802
        return self._items[self._cur][1] if self._items else None

    def currentText(self) -> str:  # noqa: N802
        return self._items[self._cur][0] if self._items else ""

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._items[i][0]

    def findData(self, data) -> int:  # noqa: N802
        return next((i for i, (_t, d) in enumerate(self._items) if d == data), -1)

    def set_default(self, _i) -> None:
        pass

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if not (0 <= i < len(self._items)) or i == self._cur:
            return
        self._cur = i
        self._aim()
        self.update()
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(i)

    # ---- geometry: segments are laid out from the right edge (RTL) with equal padding
    def _widths(self) -> list[float]:
        fm = QFontMetrics(self.font())
        return [fm.horizontalAdvance(t) + 2 * 16 for t, _d in self._items]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(sum(self._widths())) + 8, BAR_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _seg(self, i: int) -> tuple[float, float]:
        ws = self._widths()
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        x = self.width() - 4 if rtl else 4
        for j, w in enumerate(ws):
            x0 = x - w if rtl else x
            if j == i:
                return x0, w
            x = x0 if rtl else x + w
        return 4.0, 0.0

    def _snap(self) -> None:
        self._x, self._w = self._seg(self._cur)

    def _aim(self) -> None:
        x, w = self._seg(self._cur)
        if not (_motion() and self.isVisible()):
            self._x, self._w = x, w
            return
        self._a.stop()
        self._from = (self._x, self._w)
        self._to = (x, w)
        self._a.setStartValue(0.0)
        self._a.setEndValue(1.0)
        self._a.start()

    def _glide(self, v) -> None:
        k = float(v)
        fx, fw = self._from
        tx, tw = self._to
        self._x, self._w = fx + (tx - fx) * k, fw + (tw - fw) * k
        self.update()

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._snap()
        super().resizeEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        self._snap()
        super().showEvent(e)

    # ---- input
    def _hit(self, pos) -> int:
        for i in range(len(self._items)):
            x, w = self._seg(i)
            if x <= pos.x() <= x + w:
                return i
        return -1

    def mousePressEvent(self, e) -> None:  # noqa: N802
        i = self._hit(e.position())
        if i >= 0:
            self.setCurrentIndex(i)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        i = self._hit(e.position())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            step = (1 if k == Qt.Key.Key_Left else -1) * (1 if rtl else -1)
            self.setCurrentIndex(max(0, min(len(self._items) - 1, self._cur + step)))
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_mixc(QColor(pal["line"]), QColor(pal["accent2"]), 0.6) if self.hasFocus() else QColor(pal["line"]),
                      1.4 if self.hasFocus() else 1))
        p.setBrush(QColor(pal["panel"]))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        th = QRectF(self._x, 4, self._w, r.height() - 7)
        p.setPen(QPen(_tint(pal["accent2"], 0.35), 1))
        p.setBrush(_tint(pal["accent"], 0.20))
        p.drawRoundedRect(th, th.height() / 2, th.height() / 2)
        for i, (t, _d) in enumerate(self._items):
            x, w = self._seg(i)
            on = i == self._cur
            hov = i == self._hover and not on
            col = QColor(pal["acc_text"]) if on else _mixc(QColor(pal["muted"]), QColor(pal["text"]), 0.6 if hov else 0.0)
            f = QFont(self.font())
            f.setWeight(QFont.Weight.Medium if on else QFont.Weight.Normal)
            p.setFont(f)
            p.setPen(col)
            p.drawText(QRectF(x, 0, w, r.height() + 1), Qt.AlignmentFlag.AlignCenter, t)


class StepNav(QWidget):
    """‹ امروز › in one pill: previous / today / next for a calendar. Arrows follow the reading direction."""

    prev = pyqtSignal()
    today = pyqtSignal()
    next = pyqtSignal()

    ARROW = 38

    def __init__(self, today_text: str = "امروز", parent=None):
        super().__init__(parent)
        self._text = today_text
        self._hover = -1
        self.setFixedHeight(BAR_H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("پیمایش تقویم")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.ARROW * 2 + self.fontMetrics().horizontalAdvance(self._text) + 36, BAR_H)

    def _zones(self) -> list[QRectF]:
        """[start, middle, end] in reading order (RTL: right to left)."""
        w, a = float(self.width()), float(self.ARROW)
        left, mid, right = QRectF(0, 0, a, BAR_H), QRectF(a, 0, w - 2 * a, BAR_H), QRectF(w - a, 0, a, BAR_H)
        return [right, mid, left] if self.isRightToLeft() else [left, mid, right]

    def _at(self, pos) -> int:
        for i, r in enumerate(self._zones()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        h = self._at(e.position())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        i = self._at(e.position())
        if i == 0:
            self.prev.emit()
        elif i == 1:
            self.today.emit()
        elif i == 2:
            self.next.emit()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from . import icons
        from PyQt6.QtGui import QTransform
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = r.height() / 2
        p.setBrush(QColor(pal["panel"]))
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.drawRoundedRect(r, rad, rad)
        zs = self._zones()
        rtl = self.isRightToLeft()
        for i, z in enumerate(zs):
            if self._hover == i:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(pal["soft"]))
                p.drawRoundedRect(z.adjusted(3, 3, -3, -3), rad - 3, rad - 3)
            if i == 1:
                p.setPen(QColor(pal["text"]))
                p.drawText(z, int(Qt.AlignmentFlag.AlignCenter), self._text)
            else:
                pm = icons.pixmap("chevron", pal["text"] if self._hover == i else pal["muted"], 16)
                ang = 90 if (i == 0) != rtl else -90                  # the chevron points down by default
                pm = pm.transformed(QTransform().rotate(ang), Qt.TransformationMode.SmoothTransformation)
                k = pm.devicePixelRatio() or 1.0
                p.drawPixmap(int(z.center().x() - pm.width() / k / 2), int(z.center().y() - pm.height() / k / 2), pm)
        p.setPen(QPen(QColor(pal["line"]), 1))
        for x in (zs[1].left(), zs[1].right()):
            p.drawLine(QPointF(x, 9), QPointF(x, BAR_H - 9))
