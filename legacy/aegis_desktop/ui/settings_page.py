# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings: security, backup (export / import), appearance, focus, about."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
import subprocess
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QStackedWidget, QFileDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout,
                             QWidget)

from .fx_widgets import Combo
from .. import __version__
from ..core.jalali import fa
from ..core.log import friendly
from ..core.store import VaultError
from .tokens import PAGE
from . import dialogs
from .auth import run_blocking
from .pages import Page
from .widgets import FaSpinBox, PathLabel, button, label
from .motion_widgets import BellToggle
from .settings_widgets import Breadcrumb, SettingsNav, ThemePicker
from .backup_ui import BackupBrowser, BackupHero, Section, Switch, human_size, rel_time
from .theme import PALETTES
from .theme import THEME_ORDER, THEMES


def open_folder(path) -> None:
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class SettingsPage(Page):
    title = "تنظیمات"

    def __init__(self, ctx):
        super().__init__(ctx)
        self._loading = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*PAGE)
        outer.addLayout(self.header("تنظیمات"))
        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)
        self.nav = SettingsNav([("security", "امنیت", "lock"), ("backup", "پشتیبان‌گیری", "backup"),
                                ("appearance", "ظاهر", "palette"), ("focus", "تمرکز و یادآوری", "bell"),
                                ("data", "نگهداری داده", "database"), ("help", "راهنما", "bookmark"),
                                ("about", "درباره", "info")])
        body.addWidget(self.nav, 0, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        self.crumb = Breadcrumb(["تنظیمات", "امنیت"])
        self.crumb.hide()                                  # the selected nav item and the card's own title already say where you are
        right.addWidget(self.crumb)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        body.addLayout(right, 1)
        self._sec: dict[str, QVBoxLayout] = {}
        for key, _t, _i in self.nav.items:
            sc = QScrollArea()
            sc.setProperty("edges", True)
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            inner = QWidget()
            cl = QVBoxLayout(inner)
            cl.setSpacing(14)
            sc.setWidget(inner)
            self.stack.addWidget(sc)
            self._sec[key] = cl
        self.nav.changed.connect(self._goto)
        self._sections: list = []
        self._built: set[str] = set()
        self._builders = {k: getattr(self, f"_build_{k}") for k in tuple(k for k, _t, _i in self.nav.items)}
        self._ensure("security")                          # the other sections are built when they are first opened
        self._loading = False

    # ------------------------------------------------------------------------------------- lazy sections ---
    # Every widget alive is re-styled on each theme switch (settings alone was ~270 of them), so a section is built
    # the first time it is opened. Reading an attribute of an unbuilt section (``page.b_every``) builds the rest.
    _ATTR_SECTION = {**{n: "security" for n in ("rec_lb", "rec_btn", "autolock")},
                     **{n: "backup" for n in ("hero", "b_auto", "b_every", "r_every", "b_exit", "r_exit", "b_keep", "r_keep",
                                              "b_dir", "b_dir_reset", "last_export", "path_lb")},
                     **{n: "appearance" for n in ("picker", "fsize", "dens", "snd", "ghk", "ghk_desc", "amb", "dr", "calm", "ovt", "ovs", "auto", "preview")},
                     "help": "help", "upd": "about",
                     **{n: "focus" for n in ("pw", "pb", "bell", "remind")}}

    def __getattr__(self, name):
        sec = SettingsPage._ATTR_SECTION.get(name)
        d = self.__dict__
        if sec is not None and "_built" in d and sec not in d["_built"]:
            self._ensure(sec)
            if name in self.__dict__:
                return self.__dict__[name]
        raise AttributeError(name)

    def _ensure(self, key: str) -> None:
        if key in self._built:
            return
        was = self._loading
        self._loading = True
        self._built.add(key)
        self._builders[key]()
        self._sec[key].addStretch(1)
        self._loading = was
        from . import scrollfx
        from .a11y import ensure_names
        scrollfx.attach(self)                                           # sections are built late: same treatment as the rest
        ensure_names(self)
        if self.ctx.store.is_unlocked:
            self._fill_values(key)
        QTimer.singleShot(0, self.one_accent)

    def _ensure_all(self) -> None:
        for key, _t, _i in self.nav.items:
            self._ensure(key)

    def _sect(self, key, icon, title, sub=""):
        sc = Section(icon, title, sub)
        self._sections.append(sc)
        self._sec[key].addWidget(sc)
        sc.paint_icon(PALETTES[self.ctx.theme])
        return sc

    def _build_security(self) -> None:
        ctx = self.ctx
        sc = self._sect("security", "lock", "امنیت ولت", "رمزنگاری سرتاسری روی همین دستگاه؛ بدون رمز یا کلید بازیابی، هیچ‌کس — حتی ما — به داده‌ها دسترسی ندارد.")
        sc.add_row("رمز اصلی", "رمز فعلی را عوض کن؛ همه‌ی پشتیبان‌ها هم با رمز جدید قفل می‌شوند.",
                   button("تغییر رمز اصلی…", slot=self._change_pw))
        self.rec_lb = label("", "Muted", True)
        self.rec_btn = button("", slot=self._recovery)
        row = sc.add_row("کلید بازیابی", "", self.rec_btn)
        row.layout().itemAt(0).layout().addWidget(self.rec_lb)
        self.autolock = FaSpinBox()
        self.autolock.setRange(0, 240)
        self.autolock.setSuffix(" دقیقه")
        self.autolock.setSpecialValueText("خاموش")
        self.autolock.setMinimumWidth(130)
        self.autolock.valueChanged.connect(lambda v: self._pref("autolock_min", v))
        sc.add_row("قفل خودکار", "پس از این مدت بی‌فعالیتی، ولت قفل و داده‌ها از حافظه پاک می‌شوند.", self.autolock)
        sc.add_row("قفل فوری", "میان‌بر: Ctrl+L", button("قفل کن", slot=ctx.lock))
        sc.add_row("گواهی ولت", "کارت شماره، تاریخ ساخت و شناسهٔ غیرمحرمانهٔ ولت؛ قابل ذخیره به‌صورت تصویر.",
                   button("نمایش گواهی…", slot=lambda: ctx.show_certificate()))

    def _build_backup(self) -> None:
        ctx = self.ctx
        self.hero = BackupHero()
        self._sec["backup"].addWidget(self.hero)
        hr = QHBoxLayout()
        hr.addStretch(1)
        hr.addWidget(button("مرور و بازگردانی پشتیبان‌ها…", slot=self._browse))
        hr.addWidget(button("＋ پشتیبان‌گیری الان", "Primary", lambda: ctx.backup_now("manual")))
        self._sec["backup"].addLayout(hr)
        sc = self._sect("backup", "backup", "پشتیبان‌گیری خودکار", "کپی رمزنگاری‌شده‌ی کامل ولت، بی‌صدا و در پس‌زمینه. هیچ داده‌ای رمزنگاری‌نشده روی دیسک نوشته نمی‌شود.")
        self.b_auto = Switch()
        self.b_auto.toggled.connect(lambda v: (self._pref("backup_auto", v), self._sync_backup_enabled()))
        sc.add_row("پشتیبان خودکار", "هر چند وقت یک بار، از ولت یک نسخه‌ی رمزنگاری‌شده گرفته می‌شود.", self.b_auto)
        self.b_every = Combo()
        for h, t in ctx.BACKUP_EVERY:
            self.b_every.addItem(t, h)
        self.b_every.setMinimumWidth(150)
        self.b_every.currentIndexChanged.connect(lambda _=0: self._pref("backup_every_h", self.b_every.currentData()))
        self.r_every = sc.add_row("تناوب", "فاصله‌ی زمانی بین دو پشتیبان خودکار (وقتی برنامه باز است).", self.b_every)
        self.b_exit = Switch()
        self.b_exit.toggled.connect(lambda v: self._pref("backup_on_exit", v))
        self.r_exit = sc.add_row("هنگام قفل کردن یا بستن", "آخرین تغییرات همیشه پشتیبان دارند (حداکثر هر ۱۵ دقیقه یک بار).", self.b_exit)
        self.b_keep = FaSpinBox()
        self.b_keep.setRange(3, 500)
        self.b_keep.setSuffix(" نسخه")
        self.b_keep.setMinimumWidth(130)
        self.b_keep.setKeyboardTracking(False)
        self.b_keep.valueChanged.connect(self._keep_changed)
        self.r_keep = sc.add_row("تعداد نگه‌داری", "قدیمی‌ترین‌ها خودکار حذف می‌شوند؛ نسخه‌های سنجاق‌شده هرگز.", self.b_keep)
        self.b_dir = PathLabel()
        dirbox = QHBoxLayout()
        dirbox.setSpacing(8)
        dirbox.addWidget(button("تغییر پوشه…", slot=self._pick_dir))
        self.b_dir_reset = button("پیش‌فرض", slot=lambda: self._set_dir(""))
        dirbox.addWidget(self.b_dir_reset)
        dirbox.addWidget(button("باز کردن", slot=self._open_backups))
        dw = QWidget()
        dw.setLayout(dirbox)
        row = sc.add_row("محل ذخیره", "می‌توانی پوشه‌ای روی هارد دوم، فلش یا پوشه‌ی همگام‌شده (مثل Syncthing) انتخاب کنی — فایل‌ها همیشه رمزنگاری‌شده‌اند.", dw)
        row.layout().itemAt(0).layout().addWidget(self.b_dir)

        sc = self._sect("backup", "database", "انتقال به دستگاه دیگر", "خروجی .aegis فقط با رمز اصلی همین ولت باز می‌شود و با نسخه‌ی وب Aegis هم سازگار است.")
        self.last_export = label("", "Muted", True)
        ew = QWidget()
        el = QHBoxLayout(ew)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(button("وارد کردن ولت…", slot=ctx.import_vault))
        el.addWidget(button("خروجی رمزنگاری‌شده…", "Primary", ctx.export_vault))
        row = sc.add_row("خروجی و ورود ولت", "", ew)
        row.layout().itemAt(0).layout().addWidget(self.last_export)
        rw = QWidget()
        rl = QHBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(button("یادداشت‌ها ← Markdown", slot=lambda: ctx.export_notes_md(None, "notes")))
        rl.addWidget(button("تسک‌ها ← تقویم (.ics)", slot=ctx.export_ics))
        sc.add_row("خروجی خوانا", "این فایل‌ها رمزنگاری نمی‌شوند؛ با دقت نگه‌شان دار.", rw)
        self.path_lb = PathLabel()
        row = sc.add_row("پوشه‌ی داده", "", button("باز کردن", slot=lambda: open_folder(ctx.store.dir)))
        row.layout().itemAt(0).layout().addWidget(self.path_lb)

    def _build_appearance(self) -> None:
        sc = self._sect("appearance", "palette", "تم", "تم اصلی «نوآر» است؛ هر تم بلافاصله روی کل برنامه اعمال می‌شود.")
        self.picker = ThemePicker(THEMES, THEME_ORDER)
        self.picker.picked.connect(lambda k: self._pref("palette", k))
        sc.add_widget(self.picker)
        sc = self._sect("appearance", "sun", "نمایش", "پیش‌نمایش زنده: اندازه و چگالی را عوض کن و همین‌جا ببین.")
        from .settings_widgets import LivePreview
        self.preview = LivePreview()
        sc.add_widget(self.preview, hair=False)
        self.fsize = FaSpinBox()
        self.fsize.setRange(8, 16)
        self.fsize.setSuffix(" pt")
        self.fsize.setMinimumWidth(110)
        self.fsize.valueChanged.connect(lambda v: (self._pref("font_pt", v), self.preview.set_look(pt=v)))
        sc.add_row("اندازه‌ی متن", "اندازه‌ی قلم Vazirmatn در کل برنامه.", self.fsize)
        self.dens = Combo()
        self.dens.addItem("راحت", "comfortable")
        self.dens.addItem("فشرده", "compact")
        self.dens.currentIndexChanged.connect(lambda _=0: (self._pref("density", self.dens.currentData()),
                                                           self.preview.set_look(dense=self.dens.currentData() == "compact")))
        sc.add_row("چگالی ردیف‌های تسک", "«فشرده» ردیف‌ها را کوتاه‌تر می‌کند تا تسک بیشتری یک‌جا ببینی.", self.dens)
        sc = self._sect("appearance", "sparkle", "حس و حرکت", "صدا، نور و انیمیشن؛ همه‌چیز را می‌شود آرام‌تر کرد.")
        self.snd = Switch()
        self.snd.toggled.connect(lambda v: self._pref("sounds", v))
        sc.add_row("صدای ظریف", "تیک انجام تسک، باز شدن ولت و پایان پومودورو؛ خیلی آرام و پیش‌فرض خاموش.", self.snd)
        self.amb = Switch()
        self.amb.toggled.connect(lambda v: self._pref("ambient", v))
        sc.add_row("نور محیطی", "روشنایی خیلی ملایم صفحه با ساعت روز عوض می‌شود: خنک شب، گرم غروب. اگر نمی‌خواهی خاموشش کن.", self.amb)
        self.calm = Switch()
        self.calm.toggled.connect(lambda v: self._pref("reduce_motion", v))
        sc.add_row("کاهش حرکت", "انیمیشن‌های ورود و راه‌راه‌ها خاموش می‌شوند؛ برای چشم‌های حساس یا سیستم‌های ضعیف.", self.calm)
        sc = self._sect("appearance", "sun", "روز و شب", "تم و نوری که با ساعت روز هماهنگ می‌شوند.")
        self.auto = Switch()
        self.auto.toggled.connect(lambda v: self._pref("auto_theme", v))
        sc.add_row("تم خودکار با غروب", "بعد از غروب آفتاب تم شبانه (پیش‌فرض نوآر) و بعد از طلوع تم روزانه (پیش‌فرض عاج) فعال می‌شود. هر تمی که هنگام روشن بودن این گزینه انتخاب کنی برای همان نیمه‌ی روز یادآوری می‌شود.", self.auto)
        sc = self._sect("appearance", "play", "شروع و دسترسی سریع", "آنچه هنگام باز کردن برنامه می‌بینی و راه‌های سریع‌تر برای شروع کار.")
        self.dr = Switch()
        self.dr.toggled.connect(lambda v: self._pref("day_ritual", v))
        sc.add_row("شروع روز", "اولین بار که هر روز ولت را باز می‌کنی، یک کارت آرام می‌گوید امروز چه در پیش داری (Esc می‌بندد).", self.dr)
        self.ovt = Switch()
        self.ovt.toggled.connect(lambda v: self._pref("overture", v))
        sc.add_row("لندینگ سینمایی", "هنگام باز کردن برنامه، یک فیلم ۲۰ ثانیه‌ای نمایش داده می‌شود؛ هر لحظه می‌شود رد کرد. خاموش = مستقیم فرم ورود.", self.ovt)
        self.ovs = Switch()
        self.ovs.toggled.connect(lambda v: self._pref("overture_sound", v))
        sc.add_row("صدای لندینگ", "موسیقی و جلوه‌های صوتی آرام فیلم آغازین (فقط ویندوز). خاموش = فیلم بی‌صدا.", self.ovs)
        from . import hotkey
        if hotkey.available():
            self.ghk = Switch()
            self.ghk.toggled.connect(lambda v: self._pref("global_hotkey", v))
            row = sc.add_row("افزودن سریع از هرجا", self._hotkey_text(), self.ghk)
            self.ghk_desc = next((lb for lb in row.findChildren(QLabel) if lb.objectName() == "Muted"), None)

    def _build_focus(self) -> None:
        sc = self._sect("focus", "focus", "پومودورو")
        self.pw, self.pb = FaSpinBox(), FaSpinBox()
        for w, sfx in ((self.pw, " دقیقه"), (self.pb, " دقیقه")):
            w.setRange(1, 180)
            w.setSuffix(sfx)
            w.setMinimumWidth(120)
        self.pw.valueChanged.connect(lambda v: self._vset("pomoWork", v))
        self.pb.valueChanged.connect(lambda v: self._vset("pomoBreak", v))
        sc.add_row("زمان کار", "طول هر جلسه‌ی تمرکز.", self.pw)
        sc.add_row("زمان استراحت", "استراحت کوتاه بین جلسه‌ها.", self.pb)
        sc = self._sect("focus", "bell", "یادآوری", "یادآورها فقط وقتی برنامه و ولت باز است کار می‌کنند؛ برنامه‌ی قفل‌شده چیزی از داده‌هایت نمی‌داند.")
        self.bell = BellToggle("یادآوری خاموش", "یادآوری روشن")
        self.bell.toggled.connect(lambda on: self.remind.setValue(10 if on and self.remind.value() == 0 else (0 if not on else self.remind.value())))
        sc.add_row("اعلان تسک‌های ساعت‌دار", "", self.bell)
        self.remind = FaSpinBox()
        self.remind.setRange(0, 120)
        self.remind.setSuffix(" دقیقه قبل")
        self.remind.setSpecialValueText("خاموش")
        self.remind.setMinimumWidth(140)
        self.remind.valueChanged.connect(lambda v: self._pref("remind_min", v))
        sc.add_row("زمان یادآوری", "چند دقیقه پیش از شروع تسک خبرت کنم.", self.remind)

    def _build_data(self) -> None:
        ctx = self.ctx
        sc = self._sect("data", "database", "نگهداری داده")
        sc.add_row("بایگانی تسک‌های قدیمی", "تسک‌های انجام‌شده‌ی قدیمی‌تر از ۹۰ روز به بایگانی می‌روند تا فهرست‌ها سبک بمانند.",
                   button("بایگانی کن", slot=ctx.archive_old))
        sc.add_row("سطل زباله", "موارد حذف‌شده ۳۰ روز نگه داشته می‌شوند و بعد برای همیشه پاک می‌شوند.",
                   button("باز کردن سطل", slot=lambda: ctx.show_page("trash")))

    def _build_help(self) -> None:
        from .help_view import HelpView
        self.help = HelpView()
        self._sec["help"].addWidget(self.help)

    def _build_about(self) -> None:
        ctx = self.ctx
        from .premium import BrandMark
        _bm = BrandMark(72)
        self._sec["about"].addWidget(_bm, 0, Qt.AlignmentFlag.AlignHCenter)
        sc = self._sect("about", "shield", f"Aegis Planner  ·  نسخه‌ی {fa(__version__)}",
                  "برنامه‌ریز شخصی رمزنگاری‌شده، تمام‌آفلاین.")
        sc.add_row("رمزنگاری", "کلید از رمز اصلی با PBKDF2‑SHA256 و ۶۰۰٬۰۰۰ تکرار مشتق می‌شود؛ داده با AES‑256‑GCM رمزنگاری و اصالت‌سنجی می‌شود.")
        sc.add_row("حریم خصوصی", "به‌طور پیش‌فرض برنامه هیچ اتصال شبکه‌ای ندارد. تنها استثنا، بررسی اختیاری به‌روزرسانی است که فقط با روشن کردن خودت کار می‌کند؛ هیچ داده، آمار یا گزارشی از ولت خارج نمی‌شود.")
        self.upd = Switch()
        self.upd.toggled.connect(lambda v: self._pref("update_check", v))
        sc.add_row("بررسی خودکار به‌روزرسانی", "پیش‌فرض خاموش. اگر روشن کنی، روزی یک‌بار فقط شمارهٔ آخرین نسخه از صفحهٔ عمومی GitHub پرسیده می‌شود؛ هیچ اطلاعاتی از تو یا ولت فرستاده نمی‌شود و چیزی هم خودکار نصب نمی‌شود.",
                   self.upd)
        sc.add_row("بررسی همین حالا", "یک‌بار از GitHub می‌پرسد نسخهٔ جدیدتری هست یا نه (نیاز به اینترنت).",
                   button("بررسی نسخهٔ جدید", slot=lambda: ctx.check_updates(True)))
        sc.add_row("میان‌برها", "جست‌وجوی سراسری: Ctrl+K  ·  تسک جدید: Ctrl+N  ·  قفل: Ctrl+L  ·  رفتن به صفحه‌ها: Ctrl+1 تا Ctrl+9")
        sc.add_row("تازه‌های این نسخه", "چه چیزی اضافه شد، چه چیزی بهتر شد و چه چیزی درست شد؛ کنار هر مورد «نشانم بده» جایش را روی برنامه نشان می‌دهد.",
                   button("نمایش تازه‌ها", slot=lambda: ctx.show_whatsnew(force=True)))
        sc.add_row("معرفی برنامه", "یک تور کوتاه روی خود برنامه، از سایدبار تا تنظیمات. هر وقت خواستی دوباره ببینش.",
                   button("شروع تور", slot=lambda: ctx.show_tour()))

    def _hotkey_text(self) -> str:
        from . import hotkey
        lab = getattr(self.ctx, "hotkey_label", None) or hotkey.DEFAULT_LABEL
        return f"با {lab} یک جعبه‌ی کوچک باز می‌شود تا بدون رفتن به برنامه تسک بسازی (ولت باید باز باشد)."

    def sync_hotkey_text(self) -> None:
        """The shortcut that actually got registered (a busy Ctrl+Alt+Space falls back to another) is what the row promises."""
        lb = self.__dict__.get("ghk_desc")
        if lb is not None:
            lb.setText(self._hotkey_text())

    def _goto(self, idx: int) -> None:
        self._ensure(self.nav.items[idx][0])
        self.stack.setCurrentIndex(idx)
        self.crumb.set_path(["تنظیمات", self.nav.items[idx][1]])
        QTimer.singleShot(0, self.one_accent)              # each section has its own primary; only the visible one keeps the brand colour

    def _pref(self, key: str, val) -> None:
        if not self._loading:
            self.ctx.set_pref(key, val)

    def _vset(self, key: str, val) -> None:
        if self.ctx.store.is_unlocked and not self._loading:
            self.v.setdefault("settings", {})[key] = val
            self.ctx.store.dirty = True
            self.ctx.schedule_save()

    def _change_pw(self) -> None:
        d = dialogs.NewPasswordDialog(self, "تغییر رمز اصلی", ask_current=True, verify=self.ctx.store.verify_password)
        if d.exec():
            pw = d.password()
            try:
                self.ctx._flush_notes()
                fresh = run_blocking(lambda: self.ctx.store.change_password(pw))
                self.ctx.notify("رمز اصلی تغییر کرد.", kind="success", title="امنیت")
                if fresh:
                    dialogs.RecoveryKeyDialog(self, fresh).exec()
                    self.refresh()
            except (VaultError, OSError) as e:
                dialogs.warn(self, "خطا", f"رمز تغییر نکرد: {friendly(e)}")

    def _recovery(self) -> None:
        had = self.ctx.store.has_recovery()
        if had and not dialogs.ask(self, "کلید بازیابی جدید", "کلید بازیابی قبلی از کار می‌افتد. ادامه بدهیم؟", True, "بساز"):
            return
        try:
            key = run_blocking(self.ctx.store.setup_recovery)
        except (VaultError, OSError) as e:
            dialogs.warn(self, "کلید بازیابی", f"ساخته نشد: {friendly(e)}")
            return
        dialogs.RecoveryKeyDialog(self, key).exec()
        self.refresh()

    # ---- backups
    def _browse(self) -> None:
        d = BackupBrowser(self.ctx)
        d.exec()
        self.refresh_backup()

    def _keep_changed(self, v: int) -> None:
        if self._loading:
            return
        self._pref("backup_keep", v)
        n = len([p for p in self.ctx.store.list_backups() if not p.stem.endswith("-keep")])
        if n > v and dialogs.ask(self, "تعداد نگه‌داری", f"{fa(n - v)} پشتیبان قدیمی بیش از این حد است. همین حالا حذف شوند؟\n"
                                 "(اگر نه، در پشتیبان‌گیری بعدی حذف می‌شوند.)", True, "حذف کن"):
            self.ctx.store.prune_backups()
        self.refresh_backup()

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "پوشه‌ی پشتیبان‌ها", str(self.ctx.store.backup_dir))
        if d:
            self._set_dir(d)

    def _set_dir(self, d: str) -> None:
        old = self.ctx.store.backup_dir
        new = Path(d) if d else self.ctx.store.dir / "backups"
        if new.resolve() == old.resolve():
            return
        try:
            new.mkdir(parents=True, exist_ok=True)
            probe = new / ".aegis-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            dialogs.warn(self, "محل ذخیره", f"در این پوشه نمی‌شود نوشت:\n{friendly(e)}")
            return
        olds = self.ctx.store.list_backups()
        self._pref("backup_dir", d)
        if olds and dialogs.ask(self, "انتقال پشتیبان‌ها", f"{fa(len(olds))} پشتیبان در پوشه‌ی قبلی هست. به پوشه‌ی جدید کپی شوند؟", False, "کپی کن"):
            import shutil
            for p in olds:
                try:
                    shutil.copy2(p, new / p.name)
                except OSError:
                    pass
        self.ctx.backup_now("manual", quiet=True)
        self.refresh_backup()

    def _sync_backup_enabled(self) -> None:
        on = self.b_auto.isChecked()
        for r in (self.r_every, self.r_exit):
            r.setEnabled(on)
        self.refresh_backup()

    def refresh_backup(self) -> None:
        if "backup" not in self._built:
            return
        st, p = self.ctx.store, self.ctx.prefs
        custom = bool(p.get("backup_dir"))
        self.b_dir.setText(str(st.backup_dir) + ("" if custom else "  (پیش‌فرض)"))
        self.b_dir_reset.setEnabled(custom)
        try:
            files = st.list_backups()
            metas = [st.backup_meta(f) for f in files[:1]]
            total = sum(f.stat().st_size for f in files)
        except OSError:
            files, metas, total = [], [], 0
        on = bool(p.get("backup_auto", True))
        every = int(p.get("backup_every_h", 6))
        every_t = dict(self.ctx.BACKUP_EVERY).get(every, "")
        if st.backup_error:
            self.hero.set("error", "پشتیبان‌گیری با مشکل روبه‌رو شد",
                          [st.backup_error, "پوشه‌ی پشتیبان را بررسی کن یا به پیش‌فرض برگردان."])
            return
        if not files:
            self.hero.set("warn" if on else "off", "هنوز هیچ پشتیبانی نداری",
                          ["همین حالا اولین پشتیبان رمزنگاری‌شده را بگیر.", f"پشتیبان خودکار: {'روشن · ' + every_t if on else 'خاموش'}"])
            return
        last = metas[0]["when"]
        age_h = (dt.datetime.now() - last).total_seconds() / 3600
        fresh = age_h <= max(every * 1.5, 1.5)
        lines = [f"آخرین پشتیبان: {rel_time(last)}  ·  {metas[0]['label']}",
                 f"{fa(len(files))} نسخه  ·  {human_size(total)}  ·  نگه‌داری {fa(st.keep_backups)} نسخه  ·  "
                 + (f"خودکار {every_t}" if on else "پشتیبان خودکار خاموش است")]
        if not on:
            self.hero.set("off", "پشتیبان خودکار خاموش است", lines)
        elif fresh:
            self.hero.set("ok", "داده‌هایت امن و پشتیبان‌گیری‌شده‌اند", lines)
        else:
            self.hero.set("warn", "آخرین پشتیبان قدیمی است", lines)

    def _open_backups(self) -> None:
        try:
            self.ctx.store.backup_dir.mkdir(parents=True, exist_ok=True)
            open_folder(self.ctx.store.backup_dir)
        except OSError as e:
            dialogs.warn(self, "پوشه‌ی پشتیبان", f"پوشه باز نشد: {friendly(e)}")

    def refresh(self) -> None:
        if not self.ctx.store.is_unlocked:
            return
        for key in [k for k, _t, _i in self.nav.items if k in self._built]:
            self._fill_values(key)

    def _fill_values(self, key: str) -> None:
        """Put the current prefs / vault settings into the widgets of one (built) section."""
        was, self._loading = self._loading, True
        st, p = self.ctx.store, self.ctx.prefs
        pal = PALETTES[self.ctx.theme]
        if key == "security":
            self.rec_lb.setText("✓ کلید بازیابی فعال است؛ آن را جایی امن و بیرون از این کامپیوتر نگه دار." if st.has_recovery() else
                                "هنوز کلید بازیابی نساخته‌ای. اگر رمز اصلی را فراموش کنی، بدون آن هیچ راهی برای بازگرداندن داده‌ها نیست.")
            self.rec_lb.setStyleSheet(f"color: {pal['ok'] if st.has_recovery() else pal['warn']};")
            self.rec_btn.setText("ساخت کلید بازیابی جدید…" if st.has_recovery() else "ساخت کلید بازیابی…")
            self.autolock.setValue(int(p.get("autolock_min", 15)))
        elif key == "backup":
            last = (self.v.get("settings") or {}).get("lastExportAt")
            self.last_export.setText("آخرین خروجی: " + (fa(last[:10]) if last else "هرگز — برای انتقال یا نگه‌داری بیرون از این کامپیوتر، یک خروجی بگیر."))
            self.path_lb.setText(str(st.path))
            self.b_auto.set_quiet(bool(p.get("backup_auto", True)))
            self.b_exit.set_quiet(bool(p.get("backup_on_exit", True)))
            self.b_every.setCurrentIndex(max(0, self.b_every.findData(int(p.get("backup_every_h", 6)))))
            self.b_keep.setValue(int(p.get("backup_keep", 30)))
            for r in (self.r_every, self.r_exit):
                r.setEnabled(self.b_auto.isChecked())
        elif key == "appearance":
            self.picker.set_current(p.get("palette", "noir"))
            self.fsize.setValue(int(p.get("font_pt", 10)))
            self.calm.set_quiet(bool(p.get("reduce_motion", False)))
            self.auto.set_quiet(bool(p.get("auto_theme", False)))
            self.ovt.set_quiet(bool(p.get("overture", True)))
            self.ovs.set_quiet(bool(p.get("overture_sound", True)))
            self.amb.set_quiet(bool(p.get("ambient", True)))
            self.dr.set_quiet(bool(p.get("day_ritual", True)))
            self.snd.set_quiet(bool(p.get("sounds", False)))
            if "upd" in self.__dict__:
                self.upd.set_quiet(bool(p.get("update_check", False)))
            if "ghk" in self.__dict__:
                self.ghk.set_quiet(bool(p.get("global_hotkey", True)))
            self.dens.setCurrentIndex(max(0, self.dens.findData(p.get("density", "comfortable"))))
            self.preview.set_look(pt=int(p.get("font_pt", self.fsize.value())), dense=self.dens.currentData() == "compact")
        elif key == "focus":
            self.remind.setValue(int(p.get("remind_min", 10)))
            self.bell.set_state(self.remind.value() > 0)
            s = self.v.get("settings") or {}
            self.pw.setValue(int(s.get("pomoWork", 25)))
            self.pb.setValue(int(s.get("pomoBreak", 5)))
        for sc in self._sections:
            sc.paint_icon(pal)
        self._loading = was
        if key == "backup":
            self.refresh_backup()
