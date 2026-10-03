# SPDX-License-Identifier: GPL-3.0-or-later
"""The confirmation screen of the uninstaller: what is removed, what stays, and one last safety copy.

The Windows uninstaller (Inno Setup) runs ``AegisPlanner.exe --uninstall-confirm`` before it deletes anything. This
module decides nothing about deleting: it shows the person exactly what is about to happen, optionally saves a final
encrypted copy of the vault into the backup folder, and answers with an exit code (0 = go ahead, 3 = cancelled).
Whatever goes wrong here, the uninstaller falls back to a plain confirmation of its own.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QCheckBox, QHBoxLayout, QLabel, QVBoxLayout

from ..core.jalali import MONTHS_FA, fa, to_jalali
from ..core.store import VaultError, VaultStore, default_data_dir
from . import theme
from .micro import MotionDialog
from .premium import add_head
from .tokens import DIALOG, GAP_TIGHT
from .widgets import button, card, label

EXIT_PROCEED = 0
EXIT_CANCEL = 3


@dataclass
class Facts:
    data_dir: Path
    vault: bool
    backup_dir: Path
    custom: bool
    count: int
    newest: dt.datetime | None


def _prefs(data_dir: Path) -> dict:
    try:
        p = json.loads((data_dir / "prefs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return p if isinstance(p, dict) else {}


def gather(data_dir: Path) -> Facts:
    """Read-only look at the data folder: is there a vault, where are the backups, how many."""
    prefs = _prefs(data_dir)
    custom_dir = prefs.get("backup_dir")
    custom = isinstance(custom_dir, str) and bool(custom_dir.strip())
    store = VaultStore(data_dir)
    store.set_backup_dir(custom_dir if custom else None)
    backups = store.list_backups()
    newest = None
    if backups:
        try:
            newest = store.backup_meta(backups[0])["when"]
        except (OSError, ValueError, KeyError):
            newest = None
    return Facts(data_dir, store.exists(), store.backup_dir, custom, len(backups), newest)


def _day(d: dt.datetime) -> str:
    j = to_jalali(d.year, d.month, d.day)
    return f"{fa(j[2])} {MONTHS_FA[j[1] - 1]} {fa(j[0])}"


def backups_line(f: Facts) -> str:
    if not f.count:
        return "هنوز هیچ پشتیبانی در این پوشه نیست."
    line = f"{fa(f.count)} نسخه‌ی پشتیبان"
    if f.newest is not None:
        line += f" — آخرین: {_day(f.newest)}"
    return line


def make_final_copy(f: Facts) -> Path | None:
    """A last encrypted copy of the vault, pinned (never pruned), in the backup folder. A damaged vault is copied as it is:
    it may still be repairable later."""
    store = VaultStore(f.data_dir)
    store.set_backup_dir(f.backup_dir if f.custom else None)
    try:
        return store.snapshot("uninstall-keep")
    except VaultError:
        f.backup_dir.mkdir(parents=True, exist_ok=True)
        dst = f.backup_dir / f"vault-{dt.datetime.now():%Y%m%d-%H%M%S}-uninstall-keep.aegis"
        shutil.copy2(store.path, dst)
        return dst


class UninstallDialog(MotionDialog):
    SCRIM = False
    MORPH = False

    def __init__(self, facts: Facts, parent=None):
        super().__init__(parent)
        self.theme = theme.mode_of(theme.THEME[0])          # painted widgets look for the window's palette mode here
        self.facts = facts
        self.saved: Path | None = None
        self._skip_copy = False
        self.setWindowTitle("حذف Aegis Planner")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*DIALOG)
        lay.setSpacing(GAP_TIGHT + 4)

        gone, gl = card(QVBoxLayout, spacing=GAP_TIGHT)
        gl.addWidget(label("پاک می‌شود", "H2"))
        for text in ("برنامه و میان‌برهایش", "ولت رمزنگاری‌شده‌ی فعلی، با همه‌ی تسک‌ها، یادداشت‌ها، عادت‌ها و اهداف",
                     "تنظیمات، تم‌ها و گزارش‌های خطا"):
            gl.addWidget(label("•  " + text, "Muted", True))
        lay.addWidget(gone)

        stay, sl = card(QVBoxLayout, spacing=GAP_TIGHT)
        sl.addWidget(label("می‌ماند", "H2"))
        self.where = label("پوشه‌ی پشتیبان‌ها", "", True)
        sl.addWidget(self.where)
        self.count_lb = label(backups_line(facts), "Muted", True)
        sl.addWidget(self.count_lb)
        self.path_lb = QLabel(str(facts.backup_dir))
        self.path_lb.setObjectName("Muted")
        self.path_lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_lb.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.path_lb.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.path_lb.setWordWrap(True)
        sl.addWidget(self.path_lb)
        row = QHBoxLayout()
        self.open_btn = button("باز کردن پوشه", "Link", self._open_folder)
        self.open_btn.setEnabled(facts.backup_dir.is_dir())
        row.addWidget(self.open_btn)
        row.addStretch(1)
        sl.addLayout(row)
        lay.addWidget(stay)

        self.warn = label("", "Danger", True)
        self.warn.setVisible(False)
        lay.addWidget(self.warn)

        self.keep_copy = QCheckBox("پیش از حذف، یک نسخه‌ی پشتیبان نهایی (رمزگذاری‌شده) هم در همان پوشه ذخیره شود")
        self.keep_copy.setChecked(True)
        lay.addWidget(self.keep_copy)
        self.note = label("پشتیبان‌ها با رمز اصلی تو قفل شده‌اند؛ برای بازگرداندن آن‌ها بعداً همان رمز (یا کلید بازیابی) لازم است.",
                          "Muted", True)
        lay.addWidget(self.note)

        if not facts.vault:
            self.keep_copy.setChecked(False)
            self.keep_copy.setVisible(False)
            self.warn.setText("ولتی روی این کامپیوتر پیدا نشد؛ فقط خود برنامه حذف می‌شود.")
            self.warn.setObjectName("Muted")
            self.warn.setVisible(True)
        elif not facts.count:
            self.warn.setText("هیچ پشتیبانی وجود ندارد. اگر نسخه‌ی نهایی را نگیری، با حذف، اطلاعاتت برای همیشه از بین می‌رود.")
            self.warn.setVisible(True)

        bar = QHBoxLayout()
        self.ok = button("حذف کن", "", self._proceed)
        self.ok.setObjectName("Danger")
        self.cancel = button("انصراف", "", self.reject)
        bar.addWidget(self.ok)
        bar.addWidget(self.cancel)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.cancel.setDefault(True)
        self.cancel.setFocus()
        add_head(self, "trash", "حذف Aegis Planner", "برنامه و ولت از این کامپیوتر پاک می‌شوند؛ فقط پوشه‌ی پشتیبان‌ها می‌ماند.", "danger")

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.facts.backup_dir)))

    def _proceed(self) -> None:
        if self.keep_copy.isVisible() and self.keep_copy.isChecked() and not self._skip_copy:
            try:
                self.saved = make_final_copy(self.facts)
            except (VaultError, OSError) as exc:
                self._skip_copy = True
                self.keep_copy.setChecked(False)
                self.warn.setObjectName("Danger")
                self.warn.setText("نسخه‌ی نهایی ساخته نشد (" + _why(exc) + "). اگر می‌خواهی بدون آن ادامه بدهی دوباره «حذف کن» را بزن.")
                self.warn.setVisible(True)
                self.ok.setText("بدون نسخه‌ی نهایی حذف کن")
                self.style().unpolish(self.warn)
                self.style().polish(self.warn)
                return
        self.accept()


def _why(exc: Exception) -> str:
    if isinstance(exc, VaultError):
        return str(exc).rstrip(".")
    return "پوشه‌ی پشتیبان در دسترس نیست"


def run(data_dir: Path | None = None) -> int:
    """Show the screen and return the exit code the uninstaller waits for."""
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    key = _prefs(data_dir).get("palette")
    mode = theme.set_theme(key if isinstance(key, str) else theme.DEFAULT_THEME)
    theme.load_font(app)
    theme.apply_palette(app, mode)
    theme.install_stylesheet(app, theme.stylesheet(mode))
    dlg = UninstallDialog(gather(data_dir))
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    code = EXIT_PROCEED if dlg.exec() else EXIT_CANCEL
    dlg.hide()
    return code
