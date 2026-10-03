# SPDX-License-Identifier: GPL-3.0-or-later
"""Memory growth check: does a long session (page switches, theme changes, dialogs, lock/unlock) keep growing?

    python tools/leakcheck.py [rounds]

Prints the current (not peak) memory, Qt widget count and Python object count after every round, and - at the end - which
Python types grew the most. A healthy run flattens out after the first rounds.
"""
from __future__ import annotations

import collections
import gc
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from aegis_desktop.core.store import VaultStore
from aegis_desktop.core import logic
from aegis_desktop.ui import dialogs, micro, moments, theme
from aegis_desktop.ui.premium import pmenu
from aegis_desktop.ui.main_window import MainWindow, Palette

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from bench import PW, vault  # noqa: E402


def rss_mb() -> float:
    with open("/proc/self/statm") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576


def settle(ms: int = 0) -> None:
    QApplication.processEvents()
    if ms:
        QTest.qWait(ms)


def census() -> collections.Counter:
    return collections.Counter(type(o).__name__ for o in gc.get_objects())


def main(rounds: int = 8) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.load_font(app)
    dialogs.info = lambda *a, **k: None
    micro.MotionDialog.REAP_MS = 200
    tmp = Path(tempfile.mkdtemp())
    w = MainWindow(VaultStore(tmp / "d"), app, tmp / "d" / "prefs.json")
    w.resize(1280, 800)
    w.show()
    w.auth.s1.edit.setText(PW)
    w.auth.s2.edit.setText(PW)
    w.auth._create()
    for o in w.shell.findChildren(moments._Doors):
        o.hide()
        o.deleteLater()
    w.store.vault = vault(1000, 200)
    w.store.dirty = False
    w.refresh_all()
    keys = list(w.pages)
    rng = random.Random(3)
    themes = list(theme.THEME_ORDER)
    base = None
    print(f"{'round':>5} {'RSS MB':>8} {'widgets':>8} {'py objects':>11}")
    for r in range(rounds):
        for i in range(120):
            w.show_page(rng.choice(keys))
            settle()
        for th in rng.sample(themes, min(4, len(themes))):
            w.set_pref("palette", th)
            settle()
        w.set_pref("palette", "noir")
        w.show_page("tasks")
        for _ in range(8):                                   # dialogs, toasts and edits: what a working day is made of
            for make in (lambda: dialogs.TaskDialog(w, w.store.vault, None, None, None), lambda: Palette(w),
                         lambda: dialogs.GoalDialog(w, w.store.vault, None), lambda: dialogs.HabitDialog(w, None)):
                try:
                    d = make()
                except TypeError:
                    continue
                d.show()
                settle(40)
                d.reject()
                settle(40)
            m = pmenu(w, theme.PALETTES[w.theme], [("edit", "ویرایش", lambda: None, False), ("trash", "حذف", lambda: None, True)])
            m.popup(w.mapToGlobal(w.rect().center()))
            settle(20)
            m.hide()
            w.notify("پیام آزمایشی", kind="info")
            t = logic.new_task("تسک آزمایشی")
            w.store.vault["tasks"].append(t)
            w.changed("ساخته شد")
            logic.remove_task(w.store, t)
            w.changed("پاک شد")
            settle(30)
        w.show_page("calendar")
        cal = w.pages["calendar"]
        for _ in range(6):
            for name in ("next_month", "_next", "go_next", "next"):
                if hasattr(cal, name):
                    getattr(cal, name)()
                    break
            settle(30)
        w.lock()
        settle(50)
        w.auth.u1.edit.setText(PW)
        w.auth._unlock()
        settle(300)
        for _ in range(6):
            w.show_page(rng.choice(keys))
            settle(30)
        settle(800)
        gc.collect()
        settle(200)
        if r == 1:
            base = census()
        print(f"{r:>5} {rss_mb():>8.0f} {len(app.allWidgets()):>8} {len(gc.get_objects()):>11}", flush=True)
    now = census()
    if base is not None:
        grow = sorted(((now[k] - base.get(k, 0), k) for k in now), reverse=True)[:8]
        print("most grown python types since round 1:", ", ".join(f"{k} +{n}" for n, k in grow if n > 0))
    w.store.dirty = False
    w.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8))
