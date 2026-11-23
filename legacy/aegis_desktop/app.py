# SPDX-License-Identifier: GPL-3.0-or-later
"""Entry point: python -m aegis_desktop  [--data-dir PATH]"""
from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QLockFile, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .core import log as _log
from .core.store import VaultStore, default_data_dir
from .ui import theme


def _install_excepthook(data_dir: Path) -> None:
    """An unhandled exception in a Qt slot would otherwise abort the whole process (and
    lose unsaved edits). Log it (no vault content - only the traceback) and keep running.
    The dialog is rate-limited: a fault inside a paint handler would otherwise pop a message box per frame."""
    import time
    import traceback

    state = {"last": 0.0, "seen": set()}
    log_path = _log.setup(data_dir)

    def hook(etype, value, tb):
        _log.log.critical("unhandled %s", etype.__name__, exc_info=(etype, value, tb))
        sig = (etype.__name__, traceback.extract_tb(tb)[-1][:3] if tb else None)
        now = time.monotonic()
        if sig in state["seen"] and now - state["last"] < 60:
            return
        state["seen"].add(sig)
        state["last"] = now
        try:
            from .ui import dialogs
            dialogs.warn(None, "Aegis Planner", "مشکلی پیش آمد، اما داده‌های تو امن‌اند و برنامه به کار ادامه می‌دهد.\n"
                         "اگر تکرار شد، فایل aegis.log را از پوشه‌ی داده برای پشتیبانی بفرست.")
        except Exception:
            try:
                QMessageBox.warning(None, "Aegis Planner", "مشکلی پیش آمد؛ جزئیات در aegis.log ذخیره شد.")
            except Exception:
                pass
    sys.excepthook = hook
    threading.excepthook = lambda a: _log.log.critical("unhandled %s in thread", a.exc_type.__name__,   # log only: never touch widgets off the UI thread
                                                        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    _log.log.info("start pid=%s log=%s", os.getpid(), log_path)


def _log_environment(app: QApplication) -> None:
    """One line that answers most "it does not look right on my computer" reports: versions, Windows build, screens."""
    import platform
    try:
        screens = ", ".join(f"{s.size().width()}x{s.size().height()}@{s.devicePixelRatio():g}" for s in app.screens())
        _log.log.info("env app=%s python=%s qt=%s pyqt=%s os=%s screens=[%s]", __version__, platform.python_version(),
                      QT_VERSION_STR, PYQT_VERSION_STR, platform.platform(), screens)
    except Exception:  # noqa: BLE001
        pass


APP_MUTEX = "AegisPlannerRunning"
_mutex_handle = None


def _hold_app_mutex() -> None:
    """Name the running instance for the installer and uninstaller (Inno Setup's AppMutex): they ask the person to
    close the program instead of failing halfway on locked files. No-op off Windows."""
    global _mutex_handle
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception:  # noqa: BLE001
        _mutex_handle = None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aegis-planner")
    ap.add_argument("--data-dir", help="where vault.aegis and backups live (default: %%APPDATA%%\\AegisPlanner)")
    ap.add_argument("--uninstall-confirm", action="store_true", help=argparse.SUPPRESS)
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])
    data_dir = Path(args.data_dir or os.environ.get("AEGIS_DATA_DIR") or default_data_dir())
    if args.uninstall_confirm:
        from .ui import uninstall_dialog
        return uninstall_dialog.run(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    _install_excepthook(data_dir)
    if sys.platform.startswith("win"):        # own taskbar identity/icon instead of "python.exe"
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AegisPlanner.Desktop.1")
        except Exception:  # noqa: BLE001
            pass
    _hold_app_mutex()
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("Aegis Planner")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("AegisPlanner")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setWindowIcon(QIcon(str(theme.asset_path("icon.png"))))
    theme.load_font(app)
    _log_environment(app)

    lock = QLockFile(str(data_dir / "app.lock"))
    # QLockFile also detects a dead owner PID, so a crashed instance never blocks the next start
    if not lock.tryLock(100):
        QMessageBox.information(None, "Aegis Planner", "برنامه از قبل در حال اجراست.")
        return 0

    from .ui.splash import BrandSplash
    splash = BrandSplash()
    splash.show()
    app.processEvents()
    from .ui.main_window import MainWindow
    win = MainWindow(VaultStore(data_dir), app, data_dir / "prefs.json")
    win.show()
    splash.finish_with(win)
    code = app.exec()
    lock.unlock()
    return code


def run() -> None:
    """Entry point for the executable: everything is saved and unlocked by now, so leave without the interpreter's
    teardown. PyQt6 walks every live Qt wrapper while the interpreter shuts down, and with a large widget tree that
    walk can crash AFTER a perfectly clean quit (a Windows error dialog for nothing)."""
    import logging
    code = 1
    try:
        code = int(main() or 0)
    finally:
        try:
            logging.shutdown()
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:                                                  # noqa: BLE001
            pass
    os._exit(code)
