# SPDX-License-Identifier: GPL-3.0-or-later
"""Performance report: numbers, not assertions (the assertions live in tests/test_qa_gui.py).

    python tools/bench.py

Measured offscreen on whatever machine runs it, so absolute milliseconds are only a guide; the shape matters - does a
page, a save or a search grow with the size of the vault in a way that would hurt a person with years of data?
"""
from __future__ import annotations

import datetime as dt
import gc
import os
import random
import resource
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import VaultStore, empty_vault, normalize
from aegis_desktop.ui import theme
from aegis_desktop.ui.main_window import MainWindow

PW = "correct horse battery 42"


def vault(n_tasks: int, n_notes: int = 0) -> dict:
    r = random.Random(7)
    v = empty_vault()
    today = dt.date.today()
    for i in range(n_tasks):
        t = logic.new_task(f"تسک شماره {i} برای بنچمارک", due=jalali.date_to_due(today + dt.timedelta(days=r.randint(-400, 400))),
                           tags=[r.choice(["کار", "خانه", "مالی", "سلامت"])], rep=r.choice(["none"] * 8 + ["daily", "weekly"]))
        if r.random() < 0.5:
            t.update(done=True, doneAt="2026-09-10T08:00:00.000Z", status="done")
        v["tasks"].append(t)
    for i in range(n_notes):
        v["notes"].append(logic.new_note(f"یادداشت {i}", ("متن طولانی " * 60 + "\n") * 4, folder=r.choice(["", "کار", "شخصی"])))
    for i in range(12):
        h = logic.new_habit(f"عادت {i}", r.randint(1, 7))
        for k in range(700):
            if r.random() < 0.6:
                h["log"][(today - dt.timedelta(days=k)).isoformat()] = {"d": 1}
        v["habits"].append(h)
    v["goals"] = [logic.new_goal(f"هدف {i}", ms=[{"text": "م", "done": k % 2 == 0} for k in range(5)]) for i in range(30)]
    return normalize(v)


def ms(fn, *a, n: int = 1):
    t = time.perf_counter()
    for _ in range(n):
        out = fn(*a)
    return (time.perf_counter() - t) * 1000 / n, out


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def settle(wait: int = 0) -> None:
    QApplication.processEvents()
    if wait:
        QTest.qWait(wait)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.load_font(app)
    tmp = Path(tempfile.mkdtemp())

    print("== core (no UI)")
    print(f"{'tasks':>7} {'normalize':>10} {'save':>8} {'open':>8} {'file KB':>8} {'report':>8} {'goals':>8} {'filter':>8}")
    for n in (200, 1000, 5000, 20000):
        v = vault(n)
        d = tmp / f"core{n}"
        st = VaultStore(d)
        st.create(PW)
        st.vault = v
        t_norm, _ = ms(normalize, v)
        t_save, _ = ms(st.save)
        size = st.path.stat().st_size / 1024
        st.lock()
        t_open, _ = ms(st.unlock, PW)
        v = st.vault
        t_stats, _ = ms(logic.report_summary, v, 365)
        t_goal, _ = ms(logic.goal_progress_map, v)
        t_ser, _ = ms(logic.filter_tasks, v)
        print(f"{n:>7} {t_norm:>9.0f}m {t_save:>7.0f}m {t_open:>7.0f}m {size:>8.0f} {t_stats:>7.0f}m {t_goal:>7.0f}m {t_ser:>7.0f}m")
        st.lock()

    print("\n== window")
    t0 = time.perf_counter()
    w = MainWindow(VaultStore(tmp / "ui"), app, tmp / "ui" / "prefs.json")
    w.resize(1280, 800)
    w.show()
    settle()
    print(f"window constructed and shown (locked): {(time.perf_counter() - t0) * 1000:.0f} ms")
    w.auth.s1.edit.setText(PW)
    w.auth.s2.edit.setText(PW)
    t0 = time.perf_counter()
    w.auth._create()
    settle()
    print(f"create vault + first screen: {(time.perf_counter() - t0) * 1000:.0f} ms  (includes the 600k-round key derivation)")
    from aegis_desktop.ui import moments
    for o in w.shell.findChildren(moments._Doors):
        o.hide()
        o.deleteLater()

    print(f"\n{'tasks':>7} " + " ".join(f"{k[:7]:>8}" for k in w.pages.keys()) + f" {'theme':>8} {'lock+unl':>9}")
    rows = []
    for n in (200, 1000, 5000, 20000):
        w.store.vault = vault(n, n_notes=min(n // 5, 1500))
        w.store.dirty = False
        w.refresh_all()
        settle(150)
        cells = []
        for key in w.pages.keys():
            settle()
            t = time.perf_counter()
            w.show_page(key)
            settle()
            cells.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        for th in ("midnight", "aegis-light", "noir"):
            w.set_pref("palette", th)
            settle()
        theme_ms = (time.perf_counter() - t) * 1000 / 3
        w.store.save()
        t = time.perf_counter()
        w.lock()
        settle()
        w.auth.u1.edit.setText(PW)
        w.auth._unlock()
        settle()
        lock_ms = (time.perf_counter() - t) * 1000
        rows.append((n, cells, theme_ms, lock_ms))
        print(f"{n:>7} " + " ".join(f"{c:>7.0f}m" for c in cells) + f" {theme_ms:>7.0f}m {lock_ms:>8.0f}m", flush=True)

    print("\n== typing in the task search (20000 tasks)")
    w.show_page("tasks")
    p = w.pages["tasks"]
    p.q.edit.clear()
    settle(400)
    lat = []
    for ch in "تسک شماره ۱۲۳":
        t = time.perf_counter()
        p.q.edit.setText(p.q.edit.text() + ch)
        settle()
        lat.append((time.perf_counter() - t) * 1000)
    settle(600)
    print(f"per keystroke: max {max(lat):.0f} ms, mean {sum(lat) / len(lat):.0f} ms; filtered rows {p.table.rowCount()}")
    t = time.perf_counter()
    p.q.edit.clear()
    settle(400)
    print(f"clear + full list again: {(time.perf_counter() - t) * 1000 - 400:.0f} ms")

    print("\n== leaks (1000 tasks)")
    w.store.vault = vault(1000, 200)
    w.store.dirty = False
    w.refresh_all()
    keys = list(w.pages)
    for k in keys * 2:
        w.show_page(k)
        settle()
    settle(800)
    gc.collect()
    widgets0, rss0 = len(app.allWidgets()), rss_mb()
    for i in range(400):
        w.show_page(keys[i % len(keys)])
        settle()
        if i % 100 == 99:
            w.set_pref("palette", ("aegis-light", "noir")[i // 100 % 2])
    settle(1500)
    gc.collect()
    widgets1, rss1 = len(app.allWidgets()), rss_mb()
    print(f"after 400 page switches + 4 theme switches: widgets {widgets0} -> {widgets1}, peak RSS {rss0:.0f} -> {rss1:.0f} MB")
    w.store.dirty = False
    w.close()


if __name__ == "__main__":
    main()
