# SPDX-License-Identifier: GPL-3.0-or-later
"""Diagnostics for developers, friendly messages for users.

* ``setup(data_dir)`` - rotating ``aegis.log`` next to the vault (3 x 256 KB). Technical facts only (exception type,
  errno, operation, traceback; file paths may appear) - never vault content, passwords or keys. The file stays local.
* ``friendly(exc)`` - the Persian sentence a user may read for any exception; the technical detail goes to the log
  instead, so raw ``[Errno 28] ... 'C:\\Users\\...'`` text never reaches a dialog.
"""
from __future__ import annotations

import errno
import logging
import logging.handlers
from pathlib import Path

NAME = "aegis"
log = logging.getLogger(NAME)
log.addHandler(logging.NullHandler())

_WIN_BUSY = {5, 32, 33}          # access denied / sharing violation / lock violation: antivirus, sync client, indexer
_WIN_FULL = {39, 112}            # handle disk full / not enough space


def setup(data_dir: Path | str) -> Path | None:
    """Attach the rotating file handler once. Returns the log path (None when the folder is not writable)."""
    for h in log.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            return Path(h.baseFilename)
    path = Path(data_dir) / "aegis.log"
    try:
        h = logging.handlers.RotatingFileHandler(path, maxBytes=256 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        return None
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    return path


def friendly(exc: BaseException, action: str = "") -> str:
    """User-facing Persian text for ``exc``; logs the technical detail. ``VaultError`` messages are already
    user-presentable and pass through unchanged."""
    from .store import VaultError                       # local import: store imports this module
    if isinstance(exc, VaultError):
        log.warning("%s: vault error: %s", action or "op", exc)
        return str(exc)
    log.warning("%s: %s errno=%s winerror=%s", action or "op", type(exc).__name__,
                getattr(exc, "errno", None), getattr(exc, "winerror", None), exc_info=exc)
    code, win = getattr(exc, "errno", None), getattr(exc, "winerror", None)
    if code == errno.ENOSPC or win in _WIN_FULL:
        return "فضای دیسک کافی نیست. کمی فضا آزاد کن و دوباره تلاش کن."
    if isinstance(exc, PermissionError) or code in (errno.EACCES, errno.EPERM) or win in _WIN_BUSY:
        return "دسترسی به فایل ممکن نیست؛ شاید برنامهٔ دیگری (آنتی‌ویروس یا همگام‌ساز) آن را باز نگه داشته یا پوشه فقط‌خواندنی است."
    if isinstance(exc, FileNotFoundError) or code == errno.ENOENT:
        return "فایل یا پوشه پیدا نشد."
    if code == errno.EROFS:
        return "این محل فقط‌خواندنی است."
    if isinstance(exc, OSError):
        return "خواندن یا نوشتن فایل ناموفق بود."
    return "مشکلی پیش آمد."
