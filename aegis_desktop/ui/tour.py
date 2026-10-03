# SPDX-License-Identifier: GPL-3.0-or-later
"""The tour: a spotlight that walks through the real app, page by page.

One dimmed layer sits over the window with a soft-edged hole around whatever is being explained; the hole glides from one
target to the next while a glass card (title, two short lines, the keys to know, a progress line) settles beside it. It runs
on the real pages - each step opens its page first - so nothing on screen is a screenshot that can go stale.

* ``STEPS``      the full first-run tour (also replayable: Settings → About, Ctrl+K «معرفی»).
* ``FEATURES``   single-step spotlights for «نشانم بده» in the what's-new card (see ``whatsnew.py``).
* ``Tour``       the overlay; ``win.tour`` holds the one that is running.

Keys: → / ← (RTL: ← is forward) · Enter / Space next · Esc ends. Motion respects «کاهش حرکت».
"""
from __future__ import annotations

import dataclasses
import math
import time
from typing import Callable

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import __version__
from ..core.jalali import fa
from . import anim, theme
from .combo_popup import paint_glass
from .premium import alpha
from .widgets import button, label


@dataclasses.dataclass(frozen=True)
class Step:
    key: str
    title: str
    text: str
    page: str | None = None                                # opened first
    target: Callable | None = None                         # win -> QWidget | QRect | None (None = the card sits in the middle)
    keys: tuple[str, ...] = ()                             # shortcuts worth knowing, drawn as small keycaps
    prep: Callable | None = None                           # win -> None, runs after the page is open (e.g. pick a settings section)
    pad: int = 8
    hero: bool = False                                     # centred card with the brand mark (first and last step)


# ------------------------------------------------------------------------------------------------ targets ---
def _rect(win, w) -> QRect:
    return QRect(w.mapTo(win, QPoint(0, 0)), w.size())


def _union(win, ws) -> QRect:
    out = QRect()
    for w in ws:
        if w is not None and w.isVisible():
            out = out.united(_rect(win, w))
    return out


def _cards(win, key):
    from PyQt6.QtWidgets import QFrame
    page = win.pages[key]
    return [c for c in page.findChildren(QFrame) if c.objectName() == "Card" and c.isVisible()]


def _head(win, key, extra: int = 0) -> QRect:
    """The page title band (title + its main buttons), optionally ``extra`` px lower to take the filter row in."""
    r = _rect(win, win.pages[key])
    return QRect(r.x() + 14, r.y() + 12, r.width() - 28, 62 + extra)


def _above_cards(win, key) -> QRect:
    r = _rect(win, win.pages[key])
    cs = _cards(win, key)
    if not cs:
        return _head(win, key, 120)
    top = min(_rect(win, c).top() for c in cs)
    return QRect(r.x() + 14, r.y() + 12, r.width() - 28, max(90, top - r.y() - 22))


def _t_nav(win):
    return _union(win, [win.nav_btns[k] for k, _t in win.NAV if k != "settings"])


def _t_today(win):
    return _above_cards(win, "today")


def _t_tasks(win):
    return _head(win, "tasks", 58)


def _t_calendar(win):
    return win.pages["calendar"].stack


def _t_kanban(win):
    cs = _cards(win, "kanban")
    if not cs:
        return _head(win, "kanban", 60)
    u = _union(win, cs)
    return QRect(u.x(), u.y() - 60, u.width(), 190)


def _t_focus(win):
    cs = _cards(win, "focus")
    return _union(win, cs) if cs else _head(win, "focus", 40)


def _t_picker(win):
    st = win.pages["settings"]
    return st.picker if hasattr(st, "picker") else _head(win, "settings")


def _settings_section(win, key: str) -> None:
    st = win.pages["settings"]
    keys = [k for k, _t, _i in st.nav.items]
    if key in keys:
        i = keys.index(key)
        st.nav.cur = i                                     # the side list follows, like a click on it
        st.nav.update()
        st._goto(i)


def _p_appearance(win) -> None:
    _settings_section(win, "appearance")


def _p_about(win) -> None:
    _settings_section(win, "about")


def _p_year(win) -> None:
    win.pages["calendar"]._go_view(1)


def _t_tasks_filters(win):
    pg = win.pages["tasks"]
    combos = [c for c in pg.findChildren(QWidget) if type(c).__name__ == "Combo" and c.isVisible()]
    return _union(win, combos) if combos else _head(win, "tasks", 58)


def _t_new_task(win):
    from PyQt6.QtWidgets import QPushButton
    pg = win.pages["tasks"]
    for b in pg.findChildren(QPushButton):
        if b.objectName() == "Primary" and b.isVisible():
            return b
    return _head(win, "tasks")


def _t_about(win):
    st = win.pages["settings"]
    return _rect(win, st.stack)


N_THEMES = len(theme.THEME_ORDER)

STEPS: list[Step] = [
    Step("welcome", "به ایجیس خوش آمدی",
         "برنامه‌ریزی که فقط مال توست: همه‌چیز رمزنگاری می‌شود و روی همین کامپیوتر می‌ماند. یک تور کوتاه بزنیم؟",
         hero=True),
    Step("nav", "همه‌ی بخش‌ها اینجاست",
         "از سایدبار بین صفحه‌ها برو. با Ctrl+۱ تا Ctrl+۹ هم می‌شود بدون ماوس رفت.", "today", _t_nav, ("Ctrl", "۱ … ۹")),
    Step("today", "امروز",
         "هر روز از اینجا شروع می‌شود: کارهای امروز، پیشرفتت و یک نگاه سریع به هفته. کاری که تمام شد را تیک بزن.",
         "today", _t_today),
    Step("tasks", "تسک‌ها",
         "همه‌ی کارها در یک فهرست: جست‌وجو، فیلتر و گروه‌بندی. تسک تازه را از هر جای برنامه با Ctrl+N بساز.",
         "tasks", _t_tasks, ("Ctrl", "N")),
    Step("calendar", "تقویم، مثل تقویم گوگل",
         "روی شبکه بکش تا تسک بسازی. تسک را بکش تا جابه‌جا شود و لبه‌ی پایینش را بکش تا طولش عوض شود.",
         "calendar", _t_calendar, ("M", "W", "D", "A", "Y", "T"), _p_year),
    Step("kanban", "کانبان",
         "کارت‌ها را بین «انجام‌نشده»، «در حال انجام» و «انجام‌شده» بکش و رها کن؛ راست‌کلیک هم همین کار را می‌کند.",
         "kanban", _t_kanban),
    Step("notes", "یادداشت‌ها",
         "برای فکرها و متن‌های بلند. در پوشه‌ها مرتب می‌شوند، هر تغییر خودکار ذخیره می‌شود و خروجی Markdown هم داری.",
         "notes", lambda w: _head(w, "notes")),
    Step("habits", "عادت‌ها",
         "هر روز یک تیک. رگه‌ی روزهای پشت‌سرهم و نقشه‌ی گرمای کل سال را ببین.",
         "habits", lambda w: _head(w, "habits")),
    Step("goals", "هدف‌ها",
         "هدف بزرگ را به قدم‌های کوچک بشکن و تسک‌ها را به آن وصل کن؛ درصد پیشرفت خودش حساب می‌شود.",
         "goals", lambda w: _head(w, "goals")),
    Step("focus", "تمرکز",
         "تایمر تمرکز با حلقه‌ی ۶۰ نشانه. برای یک صفحه‌ی کاملاً خلوت، حالت تمرکز کامل را بزن.",
         "focus", _t_focus, ("Ctrl", "Shift", "F")),
    Step("reports", "گزارش‌ها",
         "روند کارها و عادت‌هایت در نمودار. خروجی PDF و «مهر هفته» هم همین‌جاست؛ در PDF فقط عدد و نمودار می‌آید، نه متن کارها.",
         "reports", lambda w: _head(w, "reports")),
    Step("trash", "سطل زباله",
         "هر چیزی که حذف کنی ۳۰ روز اینجا می‌ماند؛ هر وقت خواستی برش می‌گردانی.",
         "trash", lambda w: _head(w, "trash")),
    Step("palette", "جست‌وجو و دستورها",
         "Ctrl+K را بزن: بین همه‌چیز بگرد، بنویس «تسک بساز فردا ساعت ۱۰ جلسه» یا تم را عوض کن.",
         "today", lambda w: w.cmd_hint, ("Ctrl", "K")),
    Step("themes", "تم‌ها",
         f"{fa(N_THEMES)} تم، تیره و روشن؛ با یک کلیک عوض می‌شود. همه‌شان کنار هم در تنظیمات ← ظاهر هستند.",
         "today", lambda w: w.theme_dots),
    Step("lock", "قفل با یک کلیک",
         "وقتی از پشت میز بلند می‌شوی، ولت را قفل کن. بعد از چند دقیقه بی‌کاری هم خودکار قفل می‌شود.",
         "today", lambda w: w.lock_btn, ("Ctrl", "L")),
    Step("settings", "تنظیمات",
         "رمز اصلی، پشتیبان‌گیری، ظاهر و رفتار برنامه. این تور را هم از بخش «درباره» می‌شود دوباره دید.",
         "today", lambda w: w.nav_btns["settings"]),
    Step("done", "آماده‌ای",
         "همین بود. هر وقت خواستی دوباره ببینی: Ctrl+K را بزن و بنویس «معرفی».", "today", hero=True),
]

# single-step spotlights, keyed by what «تازه‌ها» points at ("نشانم بده")
FEATURES: dict[str, Step] = {
    "calendar": Step("f-calendar", "روی تقویم بکش",
                     "روی شبکه‌ی هفته یا روز بکش تا تسک بسازی؛ تسک را بکش تا جابه‌جا شود و لبه‌ی پایینش را بکش تا طولش عوض شود.",
                     "calendar", _t_calendar, ("M", "W", "D", "A", "Y", "T"), _p_year),
    "calendar_year": Step("f-year", "نمای سال و مینی‌تقویم",
                          "کنار همین صفحه یک مینی‌تقویم است؛ نمای «سال» را از همین دکمه‌ها باز کن.",
                          "calendar", lambda w: w.pages["calendar"].seg, ("Y",)),
    "forms": Step("f-forms", "فرم‌های جمع‌وجورتر",
                  "فقط چیزهایی که هر بار لازم است اول می‌آید؛ بقیه پشت «گزینه‌های بیشتر» است. دکمه‌ی تسک جدید را بزن و ببین.",
                  "tasks", _t_new_task),
    "sort": Step("f-sort", "فیلتر و مرتب‌سازی تازه",
                 "لیست‌های کشویی حالا شیشه‌ای‌اند و وقتی فیلتری روشن است، یک نقطه کنار آن می‌نشیند.",
                 "tasks", _t_tasks_filters),
    "themes": Step("f-themes", "تم‌های تیره و روشن",
                   "تم‌ها در دو بخش‌اند: تیره و روشن. چهار تم روشن تازه هم اضافه شده است.",
                   "settings", _t_picker, (), _p_appearance),
    "palette": Step("f-palette", "بستن جست‌وجو",
                    "پنجره‌ی Ctrl+K حالا دکمه‌ی × دارد و با کلیک بیرون از آن هم بسته می‌شود.",
                    None, lambda w: w.cmd_hint, ("Ctrl", "K")),
    "tour": Step("f-tour", "تور معرفی",
                 "این تور را هر وقت خواستی از همین‌جا دوباره ببین.",
                 "settings", _t_about, (), _p_about),
    "about": Step("f-about", "تازه‌های هر نسخه",
                  "فهرست تغییرهای همین نسخه همیشه در «درباره» است.",
                  "settings", _t_about, (), _p_about),
}


_RLM = "\u200f"


# ------------------------------------------------------------------------------------------------ pieces ---
class _Keys(QWidget):
    """Small keycaps: «Ctrl + K»."""
    def __init__(self, keys: tuple[str, ...]):
        super().__init__()
        self.keys = keys
        self.setFixedHeight(28)

    def _widths(self) -> list[int]:
        f = QFont(self.font())
        f.setBold(True)
        fm = QFontMetrics(f)
        return [max(26, fm.horizontalAdvance(k) + 16) for k in self.keys]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(sum(self._widths()) + 6 * max(0, len(self.keys) - 1), 28)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        p.setFont(f)
        rtl = self.isRightToLeft()
        x = self.width() if rtl else 0
        for k, w in zip(self.keys, self._widths()):
            r = QRectF(x - w if rtl else x, 2, w, 24)
            p.setPen(QPen(QColor(pal["line"]), 1))
            p.setBrush(alpha(pal["text"], 0.06))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
            p.setPen(QColor(pal["text"]))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, k)
            x += -(w + 6) if rtl else (w + 6)

    def _pal(self) -> dict:
        from .fx_widgets import _fpal
        return _fpal(self)


class _Bar(QWidget):
    """A hairline progress line; it fills from the reading side."""
    def __init__(self):
        super().__init__()
        self.k = 0.0
        self.setFixedHeight(4)

    def set(self, k: float) -> None:
        self.k = max(0.0, min(1.0, k))
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from .fx_widgets import _fpal
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(0, 0.5, self.width(), 3)
        p.setBrush(QColor(pal["line"]))
        p.drawRoundedRect(r, 1.5, 1.5)
        w = r.width() * self.k
        fr = QRectF(r.right() - w if self.isRightToLeft() else r.left(), r.top(), w, r.height())
        p.setBrush(QColor(pal["accent"]))
        p.drawRoundedRect(fr, 1.5, 1.5)


class _Card(QWidget):
    W, SH = 348, 22
    prev, nxt, skip = pyqtSignal(), pyqtSignal(), pyqtSignal()

    def __init__(self, parent, pal_of):
        super().__init__(parent)
        self._pal_of = pal_of
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(self.SH + 20, self.SH + 16, self.SH + 20, self.SH + 16)
        self.lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.badge = QLabel("")
        self.badge.setObjectName("Muted")
        self.b_skip = button("رد شدن", "Link", self.skip.emit)
        top.addWidget(self.badge)
        top.addStretch(1)
        top.addWidget(self.b_skip)
        self.lay.addLayout(top)
        from .premium import BrandMark
        self.mark = BrandMark(46)
        self.lay.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label("", "H2", True)
        self.text = label("", "Muted", True)
        self.text.setMinimumWidth(self.W - 40)
        self.keys_host = QHBoxLayout()
        self.keys_host.setContentsMargins(0, 2, 0, 0)
        self.keys: _Keys | None = None
        self.bar = _Bar()
        self.b_prev = button("قبلی", "", self.prev.emit)
        self.b_next = button("بعدی", "Primary", self.nxt.emit)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.b_next)
        row.addWidget(self.b_prev)
        row.addStretch(1)
        self.lay.addWidget(self.title)
        self.lay.addWidget(self.text)
        self.lay.addLayout(self.keys_host)
        self.lay.addSpacing(4)
        self.lay.addWidget(self.bar)
        self.lay.addSpacing(2)
        self.lay.addLayout(row)
        self.setFixedWidth(self.W + 2 * self.SH)

    def set_step(self, st: Step, i: int, n: int, single: bool) -> None:
        self.title.setText(_RLM + st.title)                    # a line that opens with «Ctrl+K» would otherwise flip the whole paragraph to LTR
        self.text.setText(_RLM + st.text)
        al = Qt.AlignmentFlag.AlignHCenter if st.hero else Qt.AlignmentFlag.AlignRight
        self.title.setAlignment(al | Qt.AlignmentFlag.AlignVCenter)
        self.text.setAlignment(al | Qt.AlignmentFlag.AlignTop)
        self.mark.setVisible(st.hero)
        while self.keys_host.count():                          # clear last step's keys (and their stretch)
            it = self.keys_host.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self.keys = None
        if st.keys:
            self.keys = _Keys(st.keys)
            self.keys_host.addWidget(self.keys)
            self.keys_host.addStretch(1)
            self.keys.show()                                   # a widget added to a live layout stays «hidden» (= zero height) until the loop turns
        self.badge.setText("" if single else f"{fa(i + 1)} از {fa(n)}")
        self.bar.setVisible(not single)
        self.bar.set((i + 1) / max(1, n))
        self.b_skip.setVisible(not single and i < n - 1)
        self.b_prev.setVisible(not single and i > 0)
        self.b_next.setText("فهمیدم" if single else "شروع کنیم" if i == n - 1 else "بریم" if i == 0 else "بعدی")
        self.fit()

    def fit(self) -> None:
        """Height = what the wrapped text needs at this width (labels must be polished first or their font is still the default)."""
        for w in [self, *self.findChildren(QWidget)]:
            w.ensurePolished()
        self.lay.invalidate()
        self.lay.activate()
        h = max(self.lay.heightForWidth(self.width()), self.lay.minimumSize().height())
        self.setFixedHeight(h)
        self.lay.activate()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_glass(p, QRectF(self.SH, self.SH, self.width() - 2 * self.SH, self.height() - 2 * self.SH), self._pal_of(), min(theme.rr(14), 16))


# ------------------------------------------------------------------------------------------------- overlay ---
class Tour(QWidget):
    finished = pyqtSignal(bool)                       # True when the last step was reached

    def __init__(self, win, steps: list[Step] | None = None, single: bool = False, mark: bool = True):
        super().__init__(win)
        self.win = win
        self.steps = list(steps if steps is not None else STEPS)
        self.single, self._mark = single, mark
        self.i = -1
        self._hole: QRectF | None = None
        self._hole_an: QVariantAnimation | None = None
        self._closed = False
        self._t0 = time.monotonic()
        self._return_page = next((k for k, p in win.pages.built() if p is win.stack.currentWidget()), None)
        self.setGeometry(win.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("تور معرفی")
        self.card = _Card(self, self._pal)
        self.card.prev.connect(self.prev)
        self.card.nxt.connect(self.next)
        self.card.skip.connect(lambda: self.finish(False))
        self._fx = QGraphicsOpacityEffect(self.card)
        self._fx.setOpacity(0.0)
        self.card.setGraphicsEffect(self._fx)
        self._pulse = QTimer(self, interval=45)
        self._pulse.timeout.connect(self._pulse_tick)
        self._t_open = QTimer(self, singleShot=True)          # page open -> prepared -> measured: three beats, each cancellable
        self._t_open.timeout.connect(self._opened)
        self._t_arrive = QTimer(self, singleShot=True)
        self._t_arrive.timeout.connect(self._arrive)
        self._t_reflow = QTimer(self, singleShot=True)
        self._t_reflow.timeout.connect(self._reflow)
        win.installEventFilter(self)

    # ---- helpers
    def _pal(self) -> dict:
        return theme.PALETTES[self.win.theme]

    @property
    def n(self) -> int:
        return len(self.steps)

    def start(self) -> None:
        self.win.tour = self
        self.setGeometry(self.win.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._pulse.start()
        self.go(0)

    # ---- navigation
    def next(self) -> None:
        if self.i >= self.n - 1:
            self.finish(True)
        else:
            self.go(self.i + 1)

    def prev(self) -> None:
        if self.i > 0:
            self.go(self.i - 1)

    def go(self, i: int) -> None:
        if self._closed:
            return
        i = max(0, min(self.n - 1, i))
        first = self.i < 0
        self._t_open.stop()
        self._t_arrive.stop()
        self.i = i
        st = self.steps[i]
        self._card_opacity(0.0, 0 if first else 110)
        wait = 0
        if st.page:
            try:
                page = self.win.pages[st.page]
                if self.win.stack.currentWidget() is not page:
                    self.win.show_page(st.page)
                    wait = 430 if anim.MOTION[0] else 60
            except Exception:
                pass
        self._t_open.start(max(wait, 120 if not first else 30))

    def _opened(self) -> None:
        """The page is open (and has settled): run the step's own preparation, then measure and show."""
        if self._closed:
            return
        st = self.steps[self.i]
        if st.prep is not None:
            try:
                st.prep(self.win)
            except Exception:                        # a broken step must never trap the person inside the tour
                pass
        self._t_arrive.start(40 if st.prep else 0)

    def _arrive(self) -> None:
        if self._closed:
            return
        st = self.steps[self.i]
        target = self._resolve(st)
        hole = None if target is None else QRectF(target.adjusted(-st.pad, -st.pad, st.pad, st.pad)).intersected(
            QRectF(self.rect()).adjusted(4, 4, -4, -4))
        self.card.set_step(st, self.i, self.n, self.single)
        self._move_hole(hole)
        pos = self._place(hole)
        self._show_card(pos)
        self.raise_()

    def _resolve(self, st: Step) -> QRect | None:
        if st.target is None:
            return None
        try:
            t = st.target(self.win)
        except Exception:
            return None
        if t is None:
            return None
        r = _rect(self.win, t) if isinstance(t, QWidget) else QRect(t)
        return r if r.isValid() and r.width() > 4 and r.height() > 4 else None

    def _reflow(self) -> None:
        """The window changed size: same step, new geometry, no animation."""
        if self._closed or self.i < 0:
            return
        st = self.steps[self.i]
        target = self._resolve(st)
        hole = None if target is None else QRectF(target.adjusted(-st.pad, -st.pad, st.pad, st.pad)).intersected(
            QRectF(self.rect()).adjusted(4, 4, -4, -4))
        if self._hole_an is not None:
            self._hole_an.stop()
        self._hole = hole
        self.card.move(self._place(hole))
        self.update()

    # ---- placement
    def _place(self, hole: QRectF | None) -> QPoint:
        cw, ch = self.card.width(), self.card.height()
        W, H = self.width(), self.height()
        gap, m = 6, 8                                          # the card's own shadow margin already gives air
        inner = self.card.SH
        if hole is None:
            return QPoint((W - cw) // 2, max(m, (H - ch) // 2))
        h = hole.toRect()

        def fits(p: QPoint) -> bool:
            return p.x() + inner >= m and p.y() + inner >= m and p.x() + cw - inner <= W - m and p.y() + ch - inner <= H - m

        cx = min(max(h.center().x() - cw // 2, m - inner), W - cw + inner - m)
        cy = min(max(h.center().y() - ch // 2, m - inner), H - ch + inner - m)
        below = QPoint(cx, h.bottom() + gap - inner)
        above = QPoint(cx, h.top() - gap - ch + inner)
        left = QPoint(h.left() - gap - cw + inner, cy)
        right = QPoint(h.right() + gap - inner, cy)
        wide = h.width() > W * 0.55
        order = [below, above, left, right] if wide else [left, right, below, above]
        if not wide and h.center().x() > W / 2:
            order = [left, right, below, above]
        elif not wide:
            order = [right, left, below, above]
        for p in order:
            if fits(p):
                return p
        # nothing fits beside it (a big target): float over the lower middle of the window, inside the lit area
        return QPoint(min(max(h.center().x() - cw // 2, m - inner), W - cw + inner - m), H - ch + inner - 28)

    # ---- animation
    def _move_hole(self, new: QRectF | None) -> None:
        old = self._hole
        if self._hole_an is not None:
            self._hole_an.stop()
        if not anim.MOTION[0] or not self.isVisible():
            self._hole = new
            self.update()
            return
        if new is None:
            self._hole = None
            self.update()
            return
        a = old if old is not None else QRectF(new.center().x() - 2, new.center().y() - 2, 4, 4)
        an = QVariantAnimation(self)
        an.setDuration(460)
        an.setEasingCurve(QEasingCurve.Type.InOutCubic)
        an.setStartValue(0.0)
        an.setEndValue(1.0)

        def step(t) -> None:
            t = float(t)
            self._hole = QRectF(a.x() + (new.x() - a.x()) * t, a.y() + (new.y() - a.y()) * t,
                                a.width() + (new.width() - a.width()) * t, a.height() + (new.height() - a.height()) * t)
            self.update()
        an.valueChanged.connect(step)
        an.finished.connect(lambda: setattr(self, "_hole", new))
        an.start()
        self._hole_an = an

    def _card_opacity(self, to: float, ms: int) -> None:
        an = getattr(self, "_op_an", None)
        if an is not None:
            an.stop()
        if not anim.MOTION[0] or ms <= 0:
            self._fx.setOpacity(to)
            return
        an = QVariantAnimation(self)
        an.setDuration(ms)
        an.setStartValue(float(self._fx.opacity()))
        an.setEndValue(float(to))
        an.setEasingCurve(QEasingCurve.Type.OutCubic)
        an.valueChanged.connect(lambda v: self._fx.setOpacity(float(v)))
        an.start()
        self._op_an = an

    def _show_card(self, pos: QPoint) -> None:
        self.card.move(pos)
        self.card.show()
        if not anim.MOTION[0]:
            self._fx.setOpacity(1.0)
            return
        rise = QVariantAnimation(self)
        rise.setDuration(300)
        rise.setStartValue(float(pos.y() + 10))
        rise.setEndValue(float(pos.y()))
        rise.setEasingCurve(QEasingCurve.Type.OutCubic)
        rise.valueChanged.connect(lambda y: self.card.move(pos.x(), int(y)))
        rise.start()
        self._rise = rise
        self._card_opacity(1.0, 260)

    def _pulse_tick(self) -> None:
        if not anim.MOTION[0] or self._hole is None or not self.isVisible():
            return
        h = self._hole.toRect().adjusted(-24, -24, 24, 24)
        self.update(h)

    # ---- end
    def finish(self, walked: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        self._t_open.stop()
        self._t_arrive.stop()
        self._pulse.stop()
        win = self.win
        win.removeEventFilter(self)
        if self._mark:
            win.set_pref("onboarded", True)
            win.set_pref("seen_version", __version__)          # a new user doesn't also get «what's new»
        if getattr(win, "tour", None) is self:
            win.tour = None
        self.finished.emit(walked)
        back = self._return_page
        if back and not self.single:
            try:
                if win.stack.currentWidget() is not win.pages[back]:
                    win.show_page(back)
            except Exception:
                pass
        if anim.MOTION[0] and self.isVisible():
            fx = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(fx)
            an = QVariantAnimation(self)
            an.setDuration(200)
            an.setStartValue(1.0)
            an.setEndValue(0.0)
            an.valueChanged.connect(lambda v: fx.setOpacity(float(v)))
            an.finished.connect(self.deleteLater)
            an.start()
            self._out = an
        else:
            self.hide()
            self.deleteLater()

    # ---- events
    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is getattr(self, "win", None) and ev.type() == QEvent.Type.Resize and not getattr(self, "_closed", True):
            self.setGeometry(self.win.rect())
            self._t_reflow.start(0)
        return False

    def event(self, ev) -> bool:
        if ev.type() == QEvent.Type.ShortcutOverride:
            ev.accept()                                        # the tour owns the keyboard: «W» must not switch the calendar underneath it
            return True
        return super().event(ev)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        self.setFocus()
        e.accept()                                             # the dim layer swallows clicks: the tour is a guided look

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        e.accept()

    def wheelEvent(self, e) -> None:  # noqa: N802
        e.accept()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.finish(False)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            self.next()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Backspace, Qt.Key.Key_PageUp) and not self.single:
            self.prev()
        else:
            e.accept()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal()
        dark = QColor(pal["bg"]).lightness() < 128
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        veil = QColor(4, 5, 8, 182) if dark else QColor(16, 18, 26, 150)
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        h = self._hole
        if h is None or h.width() < 3:
            p.fillPath(full, veil)
            return
        rad = min(theme.rr(14), 18)
        hole = QPainterPath()
        hole.addRoundedRect(h, rad, rad)
        p.fillPath(full.subtracted(hole), veil)
        pulse = 0.5 + 0.5 * math.sin((time.monotonic() - self._t0) * 2.4) if anim.MOTION[0] else 0.5
        acc = QColor(pal["accent"])
        p.setBrush(Qt.BrushStyle.NoBrush)
        for w, a in ((12, 0.07), (7, 0.13), (3.5, 0.24)):     # a soft halo around the edge
            p.setPen(QPen(alpha(acc, a + 0.10 * pulse), w))
            p.drawRoundedRect(h, rad, rad)
        p.setPen(QPen(alpha(acc, 0.85), 1.4))
        p.drawRoundedRect(h, rad, rad)


def start(win, steps: list[Step] | None = None, single: bool = False, mark: bool = True) -> Tour:
    """Begin a tour on ``win`` (one at a time)."""
    old = getattr(win, "tour", None)
    if old is not None:
        old.finish(False)
    t = Tour(win, steps, single=single, mark=mark)
    t.start()
    return t


def show_feature(win, key: str) -> Tour | None:
    st = FEATURES.get(key)
    if st is None:
        return None
    return start(win, [st], single=True, mark=False)
