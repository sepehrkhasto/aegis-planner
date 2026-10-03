# SPDX-License-Identifier: GPL-3.0-or-later
"""Setup / unlock screen. PBKDF2 runs on a worker thread so the window never freezes."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QEventLoop, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget)

from ..core import crypto, logic
from ..core.log import friendly
from ..core.crypto import WrongPassword
from ..core.store import VaultError, VaultStore
from . import dialogs
from .landing import BorderGlow, ParticleText
from .voice import VOICE
from .widgets import PasswordEdit, button, label


def glow_card():
    f = BorderGlow()
    lay = QVBoxLayout(f)
    lay.setContentsMargins(28, 26, 28, 26)
    lay.setSpacing(12)
    return f, lay


def _busy_overlay():
    """Dimmed layer with bouncing balls over the active window while work runs."""
    from PyQt6.QtWidgets import QVBoxLayout as V, QWidget as W
    from .fx_widgets import BounceLoader
    host = QApplication.activeWindow()
    if host is None:
        return None
    ov = W(host)
    ov.setStyleSheet("background: rgba(10,12,20,150);")
    ov.setGeometry(host.rect())
    lay = V(ov)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(BounceLoader())
    ov.show()
    ov.raise_()
    return ov


_busy_depth = 0


def busy() -> bool:
    """True while a worker-thread operation (key derivation, import...) is in flight. Timer-driven UI code
    (autosave, idle lock, reminders...) must stand down meanwhile instead of touching the vault."""
    return _busy_depth > 0


def run_blocking(fn, overlay: bool = True):
    """Run ``fn`` on a thread while keeping the UI (repaints only) alive. ``overlay=False`` skips the dimmed
    bouncing-balls layer (the caller shows its own indicator, e.g. a spinner inside the button)."""
    global _busy_depth
    ex = ThreadPoolExecutor(max_workers=1)
    _busy_depth += 1
    fut = ex.submit(fn)
    QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
    ov = _busy_overlay() if overlay else None
    try:
        while not fut.done():
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 30)
            time.sleep(0.01)
    finally:
        _busy_depth -= 1
        if ov:
            ov.hide()
            ov.setParent(None)
            ov.deleteLater()
        QApplication.restoreOverrideCursor()
        ex.shutdown(wait=True)
    return fut.result()


class AuthScreen(QWidget):
    unlocked = pyqtSignal()

    def __init__(self, store: VaultStore):
        super().__init__()
        self.store = store
        self.fails = 0
        self.locked_until = 0.0
        from PyQt6.QtWidgets import QFrame, QScrollArea
        top = QVBoxLayout(self)
        top.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        top.addWidget(sc)
        inner = QWidget()
        sc.setWidget(inner)
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 8, 0, 24)
        outer.addStretch(1)
        from .cinema import GlowMark
        self.mark = GlowMark(64)
        outer.addWidget(self.mark, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.setSpacing(0)
        self.hero = ParticleText("AEGIS")
        self.hero.setFixedHeight(190)
        outer.addWidget(self.hero)
        from .brand import Tagline
        outer.addWidget(Tagline())
        outer.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch(1)
        self.stack = QStackedWidget()
        self.stack.setFixedWidth(440)
        row.addWidget(self.stack)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_unlock())
        self.stack.addWidget(self._build_landing())
        self.stack.currentChanged.connect(self._fit_stack)
        self._fit_stack(0)
        self.tick = QTimer(self, interval=500)
        self.tick.timeout.connect(self._throttle_tick)

    def _fit_stack(self, idx: int) -> None:
        """Size the card to the visible page only (not the tallest page)."""
        w = self.stack.widget(idx)
        if w is not None:
            self.stack.setFixedHeight(w.sizeHint().height())

    # ---- builders
    def _brand(self, lay) -> None:
        return   # the particle wordmark above the card is the brand

    def _build_landing(self) -> QWidget:
        f, l = glow_card()
        l.addWidget(label("خوش آمدی", "H2"))
        l.addWidget(label("برنامه‌ریز شخصی Aegis: همه‌چیز، از تسک و یادداشت تا عادت و هدف، "
                          "فقط روی همین کامپیوتر و با رمزنگاری قوی نگه‌داری می‌شود.", "Muted", True))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for t in ("AES-256", "کاملاً آفلاین", "بدون حساب کاربری"):
            c = QLabel(t)
            c.setObjectName("Chip")
            chips.addWidget(c)
        chips.addStretch(1)
        l.addLayout(chips)
        self.start_btn = button("شروع", "Primary", self._start)
        self.start_btn.setMinimumHeight(40)
        l.addWidget(self.start_btn)
        l.addWidget(button("بازیابی از فایل پشتیبان…", "Link", self._restore))
        return f

    def _start(self) -> None:
        self.stack.setCurrentIndex(0)
        self.s1.setFocus()

    def _build_setup(self) -> QWidget:
        f, l = glow_card()
        self._brand(l)
        l.addWidget(label("ساخت رمز اصلی", "H2"))
        l.addWidget(label("همه‌چیز فقط روی همین کامپیوتر و رمزنگاری‌شده ذخیره می‌شود. این رمز را جایی امن بنویس؛ "
                          "نسخه‌ای از آن جای دیگری نیست.", "Muted", True))
        from .cinema import LockGlyph
        self.s_lock = LockGlyph()
        l.addWidget(self.s_lock, 0, Qt.AlignmentFlag.AlignHCenter)
        self.s1, self.s2 = PasswordEdit("رمز اصلی (حداقل ۱۰ کاراکتر)"), PasswordEdit("تکرار رمز")
        self.s1.textChanged.connect(lambda t: self.s_lock.set_level(len(t) / 10.0))
        self.s1.returnPressed.connect(self.s2.setFocus)
        self.s2.returnPressed.connect(self._create)
        l.addWidget(self.s1)
        from .fx_widgets import StrengthMeter
        self.meter = StrengthMeter()
        self.s1.textChanged.connect(self.meter.set_password)
        l.addWidget(self.meter)
        l.addWidget(self.s2)
        self.s_err = label("", "Danger", True)
        l.addWidget(self.s_err)
        self.s_btn = button("ساخت ولت", "Primary", self._create)
        l.addWidget(self.s_btn)
        l.addWidget(label("یا", "Muted"))
        l.addWidget(button("بازیابی از فایل پشتیبان (.aegis یا خروجی نسخه‌ی وب)…", slot=self._restore))
        return f

    def _build_unlock(self) -> QWidget:
        f, l = glow_card()
        self._brand(l)
        from .cinema import LockGlyph
        self.u_lock = LockGlyph()
        l.addWidget(self.u_lock, 0, Qt.AlignmentFlag.AlignHCenter)
        l.addWidget(label(VOICE["locked"], "H2"))
        self.u1 = PasswordEdit("رمز اصلی")
        self.u1.textChanged.connect(lambda t: self.u_lock.set_level(min(1.0, len(t) / 8.0)))
        self.u1.returnPressed.connect(self._unlock)
        l.addWidget(self.u1)
        self.u_err = label("", "Danger", True)
        l.addWidget(self.u_err)
        self.u_btn = button("باز کردن", "Primary", self._unlock)
        l.addWidget(self.u_btn)
        h = QHBoxLayout()
        h.addWidget(button("رمز را فراموش کرده‌ام", "Link", self._forgot))
        h.addStretch(1)
        h.addWidget(button("وارد کردن پشتیبان…", "Link", self._restore))
        l.addLayout(h)
        return f

    # ---- public
    def show_appropriate(self, skip_welcome: bool = False) -> None:
        self.s1.clear(); self.s2.clear(); self.u1.clear()
        self.s_lock.set_level(0); self.u_lock.set_level(0)
        self.s_err.setText(""); self.u_err.setText("")
        if self.store.exists():
            self.stack.setCurrentIndex(1)
            self.u1.setFocus()
        else:
            if skip_welcome:                # the overture already was the landing
                self.stack.setCurrentIndex(0)
                self.s1.setFocus()
            else:
                self.stack.setCurrentIndex(2)   # first launch: landing, then the setup form
                self.start_btn.setFocus()
        self.hero.replay()

    # ---- actions
    def _busy(self, on: bool, btn=None, text: str | None = None) -> None:
        """Lock both buttons while work runs; ``btn`` additionally shows a spinner and ``text``."""
        from .anim import set_loading
        for b in (self.s_btn, self.u_btn):
            if on and b is btn:
                set_loading(b, True, text)
            else:
                set_loading(b, False)                 # no-op unless it was loading
                b.setEnabled(not on)

    def _create(self) -> None:
        probs = crypto.password_problems(self.s1.text())
        if probs:
            self.s_err.setText(" ".join(probs))
            return
        if self.s1.text() != self.s2.text():
            self.s_err.setText("دو رمز یکسان نیستند.")
            return
        pw = self.s1.text()
        seed = {}
        logic.starter_content(seed)
        self._busy(True, self.s_btn, "در حال ساخت…")
        self.s_err.setText("در حال ساخت ولت رمزنگاری‌شده…")
        try:
            run_blocking(lambda: self.store.create(pw, seed), overlay=False)
        except (VaultError, OSError) as e:
            self.s_err.setText(friendly(e, "create") or "ساخت ولت ناموفق بود.")
            self._busy(False)
            return
        self._busy(False)
        self._success()
        self.created_now = True                     # main window plays the longer «vault sealed» ritual once
        self.unlocked.emit()

    def _success(self) -> None:
        """The padlock shuts, the mark flashes, the (optional) chime plays - then the vault opens."""
        from . import sfx
        self.u_lock.set_level(1.0)
        self.s_lock.set_level(1.0)
        self.mark.flash()
        sfx.play("open")

    def _throttle_tick(self) -> None:
        left = self.locked_until - time.time()
        if left <= 0:
            self.tick.stop()
            self.u_btn.setEnabled(True)
            self.u_err.setText("")
        else:
            self.u_err.setText(f"تلاش‌های ناموفق زیاد بود؛ {int(left) + 1} ثانیه صبر کن.")

    def _unlock(self) -> None:
        if time.time() < self.locked_until:
            return
        pw = self.u1.text()
        if not pw:
            return
        self._busy(True, self.u_btn, "در حال باز کردن…")
        self.u_err.setText("")
        try:
            run_blocking(lambda: self.store.unlock(pw), overlay=False)
        except WrongPassword:
            self.fails += 1
            self.u1.clear()
            self._busy(False)
            self.u_err.setText("رمز درست نیست.")
            if self.fails >= 5:   # brute-force speed bump (the KDF is the real defence)
                self.locked_until = time.time() + min(300, 5 * 2 ** (self.fails - 5))
                self.u_btn.setEnabled(False)
                self.tick.start()
            return
        except VaultError as e:
            self.u_err.setText(friendly(e))
            self._busy(False)
            return
        self.fails = 0
        self._busy(False)
        self._success()
        self.unlocked.emit()

    def _forgot(self) -> None:
        if not self.store.has_recovery():
            dialogs.info(self, "بازیابی", "برای این ولت کلید بازیابی ساخته نشده بود، پس رمز اصلی قابل بازیابی نیست.\n"
                                          "اگر فایل پشتیبانی داری، «وارد کردن پشتیبان» را بزن.")
            return
        d = dialogs.RecoveryUnlockDialog(self)
        if d.exec():
            key, new_pw = d.key.text(), d.p1.text()          # read widgets here, on the UI thread
            try:
                run_blocking(lambda: self.store.unlock_with_recovery(key, new_pw))
            except WrongPassword:
                dialogs.warn(self, "بازیابی", "کلید بازیابی درست نیست.")
                return
            except (VaultError, OSError) as e:
                dialogs.warn(self, "بازیابی", friendly(e))
                return
            self.unlocked.emit()

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل پشتیبان", "", "Aegis vault (*.aegis *.json);;All files (*)")
        if not path:
            return
        try:
            bundle = VaultStore.read_bundle(path)
        except VaultError as e:
            dialogs.warn(self, "وارد کردن", friendly(e))
            return
        if self.store.exists() and not dialogs.ask(
                self, "جایگزینی ولت", "ولت فعلی این کامپیوتر با فایل انتخابی جایگزین می‌شود (از نسخه‌ی فعلی، پیش از آن، پشتیبان گرفته می‌شود). ادامه؟", True, "ادامه"):
            return
        d = dialogs.ImportDialog(self, path, can_merge=False)
        if not d.exec():
            return
        pw = d.pw.text()
        try:
            run_blocking(lambda: self.store.import_replace(bundle, pw))
        except WrongPassword:
            dialogs.warn(self, "وارد کردن", "رمز درست نیست یا فایل آسیب دیده است.")
            return
        except (VaultError, OSError) as e:
            dialogs.warn(self, "وارد کردن", friendly(e))
            return
        self.unlocked.emit()
