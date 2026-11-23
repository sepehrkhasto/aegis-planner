# SPDX-License-Identifier: GPL-3.0-or-later
"""Field focus: when a text field takes focus, one bright arc travels once around its border and settles into the normal
focus colour (~0.5 s). Paint-only child overlay; nothing runs while typing. Installed once, application-wide."""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

from .anim import MOTION
from .fx_widgets import _fpal
from .theme import rr

FIELDS = (QLineEdit, QTextEdit, QPlainTextEdit)
REASONS = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.MouseFocusReason,
           Qt.FocusReason.ShortcutFocusReason, Qt.FocusReason.OtherFocusReason)
MS = 560


def eligible(w: QWidget) -> bool:
    """A real, visible, bordered field (not the inner line edit of a spin box / combo / self-drawn search box)."""
    if not isinstance(w, FIELDS) or w.isReadOnly() or w.height() < 28 or w.width() < 60:
        return False
    if isinstance(w.parentWidget(), (QAbstractSpinBox, QComboBox)):
        return False
    return "border:none" not in w.styleSheet().replace(" ", "")


class Sweep(QWidget):
    def __init__(self, field: QWidget):
        super().__init__(field)
        self.field = field
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(field.rect())
        self.k = 0.0
        self.an = QVariantAnimation(self)
        self.an.setStartValue(0.0)
        self.an.setEndValue(1.0)
        self.an.setDuration(MS)
        self.an.setEasingCurve(QEasingCurve(QEasingCurve.Type.InOutCubic))
        self.an.valueChanged.connect(self._step)
        self.an.finished.connect(self._done)

    def run(self) -> None:
        self.setGeometry(self.field.rect())
        self.show()
        self.raise_()
        self.an.stop()
        self.an.start()

    def _step(self, v) -> None:
        self.k = float(v)
        self.update()

    def _done(self) -> None:
        self.hide()

    def path(self) -> QPainterPath:
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = min(rr(9), r.height() / 2)
        pth = QPainterPath()
        pth.addRoundedRect(r, rad, rad)
        return pth

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self.field)
        pth = self.path()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        head = self.k
        span = 0.34 * (1.0 - 0.3 * self.k)
        n = 44
        fade = 1.0 - max(0.0, (self.k - 0.7) / 0.3)                  # the light drains away at the end
        col = QColor(pal["accent2"])
        prev = None
        for i in range(n + 1):
            t = head - span * (1 - i / n)
            if t < 0:
                continue
            pt = pth.pointAtPercent(t % 1.0)
            if prev is not None:
                c = QColor(col)
                c.setAlphaF(min(1.0, 0.95 * (i / n) ** 1.6) * fade)
                p.setPen(QPen(c, 1.2 + 1.4 * (i / n), cap=Qt.PenCapStyle.RoundCap))
                p.drawLine(prev, pt)
            prev = pt


class FocusFx(QObject):
    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.FocusIn and MOTION[0] and isinstance(obj, FIELDS):
            try:
                if ev.reason() in REASONS and eligible(obj):
                    sw = getattr(obj, "_sweep", None)
                    if sw is None:
                        sw = obj._sweep = Sweep(obj)
                    sw.run()
            except RuntimeError:
                pass
        return False


_INSTALLED: dict = {}


def install(app: QApplication | None = None) -> FocusFx | None:
    app = app or QApplication.instance()
    if app is None:
        return None
    if "f" not in _INSTALLED:
        f = FocusFx(app)
        app.installEventFilter(f)
        _INSTALLED["f"] = f
    return _INSTALLED["f"]
