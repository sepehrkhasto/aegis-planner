# SPDX-License-Identifier: GPL-3.0-or-later
"""Monkey test: thousands of random user actions against the real window (offscreen), with every error recorded.

    python tools/chaos_gui.py --seed 1 --steps 1500

Random clicks, double clicks, right clicks, drags, wheel turns, key presses, typing (Persian, Latin, digits, junk),
page changes, theme changes, window resizes, locking and unlocking. Modal dialogs, menus and file pickers are answered
automatically (and also poked at) so nothing ever blocks. Any uncaught exception, Qt warning, vault invariant break or a
final vault that does not survive a save -> reload round trip is reported with the last actions, so a run is repeatable
from its seed.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt, qInstallMessageHandler
from PyQt6.QtGui import QDesktopServices, QKeyEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QColorDialog, QComboBox,
                             QDialog, QFileDialog, QInputDialog, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QTextEdit,
                             QWidget)

from aegis_desktop.core.store import VaultStore
from aegis_desktop.ui import dialogs, theme
from aegis_desktop.ui.main_window import MainWindow

PW = "correct horse battery 42"
TEXTS = ["", "کار", "جلسه فردا ۱۰:۳۰", "a", "x" * 400, "🙂 ایموجی", "<b>x</b>", "0", "-1", "۱۲۳", "۱۴۰۵/۰۲/۳۰", "2026-02-30",
         "فردا ساعت ۱۴ تا ۱۵ #کار !مهم", "‌", "‮ابج", "a\nb\nc", "۲۴:۰۰", "99:99", "  ", "%s %d {0}", "'\";--", "\\"]
KEYS = [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Delete,
        Qt.Key.Key_Backspace, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp,
        Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Space, Qt.Key.Key_F2, Qt.Key.Key_F5]
CTRL = [Qt.Key.Key_K, Qt.Key.Key_N, Qt.Key.Key_Z, Qt.Key.Key_F, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_1, Qt.Key.Key_2,
        Qt.Key.Key_3, Qt.Key.Key_4, Qt.Key.Key_5, Qt.Key.Key_6, Qt.Key.Key_7, Qt.Key.Key_8, Qt.Key.Key_9, Qt.Key.Key_D,
        Qt.Key.Key_E, Qt.Key.Key_B, Qt.Key.Key_T]
BAD_WARNINGS = ("QFont::setPointSize", "QPainter::", "QWidget::setLayout", "QObject::", "Cannot create children",
                "QLayout::", "QTimer::", "QPixmap::", "Unknown property", "QBackingStore", "QGraphicsEffect", "Could not parse")
IGNORED = ("propagateSizeHints", "This plugin does not support", "Could not load the Qt platform", "QStandardPaths",
           "QFontDatabase", "Note that Qt no longer", "libpng warning", "QSocketNotifier", "QSystemTrayIcon")


class Chaos:
    def __init__(self, seed: int, steps: int, tmp: Path, verbose: bool, mode: str = "normal") -> None:
        self.rng = random.Random(seed)
        self.seed, self.steps, self.tmp, self.verbose = seed, steps, tmp, verbose
        self.log: list[str] = []
        self.errors: list[tuple[str, str, list[str]]] = []
        self.warnings: list[str] = []
        self.depth = 0
        self.check_every = 50
        self.trace = 0
        self.counts: dict[str, int] = {}
        self.app = QApplication.instance() or QApplication(sys.argv[:1])
        self.app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        theme.load_font(self.app)
        from aegis_desktop.ui import micro
        micro.MotionDialog.REAP_MS = 300
        self._patch()
        self.win = MainWindow(VaultStore(tmp / "data"), self.app, tmp / "data" / "prefs.json")
        self.win.resize(1280, 800)
        self.win.show()
        self.win.auth.s1.edit.setText(PW)
        self.win.auth.s2.edit.setText(PW)
        self.win.auth._create()
        from aegis_desktop.ui import moments
        for o in self.win.shell.findChildren(moments._Doors):
            o.hide()
            o.deleteLater()
        if mode != "empty":
            self._seed_data(1500 if mode == "big" else 120)

    # ------------------------------------------------------------------ plumbing
    def _note(self, what: str) -> None:
        self.log.append(what)
        del self.log[:-40]
        if self.verbose:
            print(what, flush=True)

    def _fail(self, kind: str, msg: str) -> None:
        self.errors.append((kind, msg, list(self.log[-15:])))

    def _patch(self) -> None:
        me = self

        def hook(et, ev, tb):
            me._fail("exception", "".join(traceback.format_exception(et, ev, tb)))

        sys.excepthook = hook

        def qt_msg(_mode, _ctx, msg):
            if any(i in msg for i in IGNORED):
                return
            me.warnings.append(msg + "   [after: " + (me.log[-1] if me.log else "-") + "]")
            if any(b in msg for b in BAD_WARNINGS):
                me._fail("qt-warning", msg)

        self._prev_handler = qInstallMessageHandler(qt_msg)

        def fake_exec(dlg, *a):
            if me.depth >= 3:
                dlg.reject()
                return 0
            me.depth += 1
            try:
                me._note(f"dialog {type(dlg).__name__}")
                dlg.show()
                QApplication.processEvents()
                for _ in range(me.rng.randint(0, 7)):
                    if not dlg.isVisible():                 # a key press closed it: nothing left to poke at
                        break
                    me.act(dlg)
                if dlg.isVisible():
                    (dlg.accept if me.rng.random() < 0.55 else dlg.reject)()
                    QApplication.processEvents()
                if dlg.isVisible():
                    dlg.hide()
                return dlg.result()
            except RuntimeError:                            # closed and freed while it was being poked: that is what it is for
                return 0
            finally:
                me.depth -= 1

        QDialog.exec = fake_exec

        def menu_exec(menu, *a, **k):
            acts = [x for x in menu.actions() if x.isEnabled() and not x.isSeparator()]
            if not acts or me.rng.random() < 0.25:
                return None
            x = me.rng.choice(acts)
            me._note(f"menu -> {x.text()[:20]}")
            x.trigger()
            return x

        QMenu.exec = menu_exec
        QMessageBox.exec = lambda self, *a: 0

        def save_name(*a, **k):
            if me.rng.random() < 0.2:
                return "", ""
            return str(me.tmp / f"out{me.rng.randint(0, 9)}{me.rng.choice(['.aegis', '.pdf', '.ics', '.md', '.png', '.txt'])}"), ""

        def open_name(*a, **k):
            outs = sorted(me.tmp.glob("out*.aegis"))
            if not outs or me.rng.random() < 0.3:
                return "", ""
            return str(me.rng.choice(outs)), ""

        QFileDialog.getSaveFileName = staticmethod(save_name)
        QFileDialog.getOpenFileName = staticmethod(open_name)
        QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: me.rng.choice(["", str(me.tmp / "bk"), "/nonexistent/x"]))
        QInputDialog.getText = staticmethod(lambda *a, **k: (me.rng.choice([PW, "wrong", "", TEXTS[5]]), me.rng.random() < 0.8))
        QColorDialog.getColor = staticmethod(lambda *a, **k: a[0] if a else None)
        QDesktopServices.openUrl = staticmethod(lambda *a, **k: True)
        import subprocess
        subprocess.Popen = lambda *a, **k: None
        from aegis_desktop.ui import settings_page
        for name in ("open_folder", "_open_path", "reveal"):
            if hasattr(settings_page, name):
                setattr(settings_page, name, lambda *a, **k: None)
        MainWindow._quit = lambda self: None
        self._real_info, self._real_warn = dialogs.info, dialogs.warn
        dialogs.info = lambda *a, **k: None
        dialogs.warn = lambda *a, **k: None
        dialogs.ask = lambda *a, **k: me.rng.random() < 0.6

    def _seed_data(self, n_tasks: int = 120) -> None:
        from aegis_desktop.core import jalali, logic
        import datetime as dt
        v = self.win.store.vault
        r = self.rng
        for i in range(n_tasks):
            t = logic.new_task(f"تسک {i}", due=jalali.date_to_due(dt.date.today() + dt.timedelta(days=r.randint(-20, 40))),
                               tags=[r.choice(["کار", "خانه", "x"])], rep=r.choice(["none", "none", "daily", "weekly"]))
            t["priority"] = r.choice(["low", "med", "high"]) if "priority" in t else t.get("priority")
            if r.random() < 0.3:
                t.update(done=True, doneAt="2026-09-10T08:00:00.000Z", status="done")
            v["tasks"].append(t)
        for i in range(15):
            v["notes"].append(logic.new_note(f"یادداشت {i}", "متن\n==مهم==\n- [ ] کار\n[[یادداشت 1]]", folder=r.choice(["", "کار"])))
        for i in range(6):
            h = logic.new_habit(f"عادت {i}", r.randint(1, 7))
            for k in range(40):
                h["log"][(dt.date.today() - dt.timedelta(days=r.randint(0, 80))).isoformat()] = {"d": 1}
            v["habits"].append(h)
        for i in range(4):
            v["goals"].append(logic.new_goal(f"هدف {i}", ms=[{"text": "م", "done": bool(k % 2)} for k in range(3)],
                                             deadline=jalali.date_to_due(dt.date.today() + dt.timedelta(days=90))))
        self.win.store.dirty = True
        self.win.refresh_all()

    # ------------------------------------------------------------------ helpers
    def _scope_widgets(self, scope: QWidget) -> list[QWidget]:
        out = []
        for w in scope.findChildren(QWidget):
            if w.isVisible() and w.isEnabled() and w.width() > 3 and w.height() > 3:
                out.append(w)
        return out

    def _point(self, w: QWidget) -> QPoint:
        return QPoint(self.rng.randint(1, max(1, w.width() - 2)), self.rng.randint(1, max(1, w.height() - 2)))

    def _scope(self) -> QWidget:
        tops = [t for t in QApplication.topLevelWidgets() if t.isVisible() and isinstance(t, QDialog)]
        return tops[-1] if tops else self.win

    # ------------------------------------------------------------------ actions
    def a_click(self, scope, widgets, kind="click"):
        w = self.rng.choice(widgets)
        if isinstance(w, QAbstractButton) and self.rng.random() < 0.7:
            pos = QPoint(w.width() // 2, w.height() // 2)
        else:
            pos = self._point(w)
        self._note(f"{kind} {type(w).__name__}:{w.objectName()} @{pos.x()},{pos.y()}")
        if kind == "click":
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        elif kind == "dbl":
            QTest.mouseDClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        elif kind == "right":
            QTest.mouseClick(w, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pos)
        elif kind == "shift":
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos)
        elif kind == "ctrl":
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos)

    def a_drag(self, scope, widgets):
        w = self.rng.choice(widgets)
        a, b = self._point(w), self._point(w)
        self._note(f"drag {type(w).__name__}:{w.objectName()} {a.x()},{a.y()}->{b.x()},{b.y()}")
        QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        steps = self.rng.randint(1, 4)
        for i in range(1, steps + 1):
            p = QPoint(a.x() + (b.x() - a.x()) * i // steps, a.y() + (b.y() - a.y()) * i // steps)
            QTest.mouseMove(w, p)
            QApplication.processEvents()
        if self.rng.random() < 0.9:
            QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
        else:
            w.hide()
            w.show()
            QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)

    def a_wheel(self, scope, widgets):
        w = self.rng.choice(widgets)
        pos = self._point(w)
        d = self.rng.choice([-240, -120, 120, 240, 1, -1])
        self._note(f"wheel {type(w).__name__}:{w.objectName()} {d}")
        ev = QWheelEvent(QPointF(pos), QPointF(w.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, d), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.ControlModifier if self.rng.random() < 0.15 else Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(w, ev)

    def a_key(self, scope, widgets):
        tgt = QApplication.focusWidget() if self.rng.random() < 0.7 else self.rng.choice(widgets)
        tgt = tgt or scope
        r = self.rng.random()
        if r < 0.22:
            k = self.rng.choice(CTRL)
            mod = Qt.KeyboardModifier.ControlModifier
            if self.rng.random() < 0.15:
                mod |= Qt.KeyboardModifier.ShiftModifier
            self._note(f"key Ctrl+{k.name[4:]} -> {type(tgt).__name__}")
            QTest.keyClick(tgt, k, mod)
        else:
            k = self.rng.choice(KEYS)
            self._note(f"key {k.name[4:]} -> {type(tgt).__name__}")
            QTest.keyClick(tgt, k)

    def a_type(self, scope, widgets):
        edits = [w for w in widgets if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox))]
        if not edits:
            return
        w = self.rng.choice(edits)
        s = self.rng.choice(TEXTS)
        self._note(f"type {type(w).__name__}:{w.objectName()} {s[:12]!r}")
        w.setFocus()
        if self.rng.random() < 0.4:
            QTest.keyClick(w, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        if self.rng.random() < 0.5 or isinstance(w, QAbstractSpinBox):        # a spin box's line edit is typed into, never set
            if isinstance(w, QAbstractSpinBox):
                w = w.lineEdit()
            self._type_text(w, s[:60])
        else:
            w.setProperty("_chaos", 1)
            if isinstance(w, QLineEdit):
                w.setText(s)
            elif isinstance(w, (QTextEdit, QPlainTextEdit)):
                w.setPlainText(s)
        if self.rng.random() < 0.4:
            QTest.keyClick(w, Qt.Key.Key_Return)

    @staticmethod
    def _type_text(w, text: str) -> None:
        """QTest.keyClicks asserts on anything outside Latin-1, so real key events with the character's own text are sent."""
        for ch in text:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(w, QKeyEvent(kind, 0, Qt.KeyboardModifier.NoModifier, ch))

    def a_combo(self, scope, widgets):
        cs = [w for w in widgets if isinstance(w, QComboBox) and w.count()]
        if not cs:
            return
        c = self.rng.choice(cs)
        i = self.rng.randrange(c.count())
        self._note(f"combo {c.objectName()} -> {i}")
        c.setCurrentIndex(i)

    def a_page(self):
        if not self.win.store.is_unlocked:
            return
        key = self.rng.choice(list(self.win.pages.keys()))
        self._note(f"page {key}")
        self.win.show_page(key)

    def a_theme(self):
        if not self.win.store.is_unlocked:
            return
        key = self.rng.choice(theme.THEME_ORDER)
        self._note(f"theme {key}")
        self.win.set_pref("palette", key)

    def a_resize(self):
        w, h = self.rng.choice([700, 820, 900, 1024, 1280, 1600, 1920, 2400]), self.rng.choice([520, 600, 700, 800, 1000, 1200])
        self._note(f"resize {w}x{h}")
        self.win.resize(w, h)

    def a_lock(self):
        if self.win.store.is_unlocked:
            self._note("LOCK")
            self.win.lock()
        else:
            self._unlock()

    def _unlock(self):
        for _ in range(2):
            if self.win.store.is_unlocked:
                return
            bad = self.rng.random() < 0.3
            self._note("unlock " + ("wrong" if bad else "ok"))
            self.win.auth.u1.edit.setText("not the password" if bad else PW)
            self.win.auth._unlock()
            QApplication.processEvents()

    def a_pref(self):
        k, v = self.rng.choice([("reduce_motion", True), ("reduce_motion", False), ("sounds", False), ("density", "compact"),
                                ("density", "cozy"), ("font_pt", 9), ("font_pt", 11), ("font_pt", 10), ("side_compact", True),
                                ("side_compact", False), ("ambient", False), ("ambient", True)])
        self._note(f"pref {k}={v}")
        if self.win.store.is_unlocked:
            self.win.set_pref(k, v)

    def act(self, scope=None):
        scope = scope or self._scope()
        if not self.win.store.is_unlocked and scope is self.win:
            self._unlock()
            scope = self._scope()
        widgets = self._scope_widgets(scope)
        r = self.rng.random()
        try:
            if not widgets:
                self._note("no widgets")
                return
            for name, lo, hi, fn in (
                    ("click", 0, .34, lambda: self.a_click(scope, widgets)),
                    ("dbl", .34, .39, lambda: self.a_click(scope, widgets, "dbl")),
                    ("right", .39, .47, lambda: self.a_click(scope, widgets, "right")),
                    ("mod", .47, .50, lambda: self.a_click(scope, widgets, self.rng.choice(["shift", "ctrl"]))),
                    ("drag", .50, .58, lambda: self.a_drag(scope, widgets)),
                    ("wheel", .58, .63, lambda: self.a_wheel(scope, widgets)),
                    ("key", .63, .75, lambda: self.a_key(scope, widgets)),
                    ("type", .75, .86, lambda: self.a_type(scope, widgets)),
                    ("combo", .86, .88, lambda: self.a_combo(scope, widgets)),
                    ("page", .88, .94, self.a_page),
                    ("theme", .94, .955, self.a_theme),
                    ("resize", .955, .975, self.a_resize),
                    ("pref", .975, .985, self.a_pref),
                    ("lock", .985, 1.01, self.a_lock)):
                if lo <= r < hi:
                    self.counts[name] = self.counts.get(name, 0) + 1
                    fn()
                    break
        except RuntimeError as exc:                     # a C++ object deleted by an earlier action: a normal race for a monkey
            if "has been deleted" not in str(exc):
                self._fail("runtime", traceback.format_exc())
        QTest.qWait(self.rng.choice([0, 0, 0, 2, 5, 15]))

    # ------------------------------------------------------------------ invariants
    def _trace_row(self, step: int) -> None:
        """Widget / object / memory counts: after the pages have all been built they must stop growing."""
        import gc
        QApplication.processEvents()
        for tl in QApplication.topLevelWidgets():
            if tl is not self.win and tl.isVisible() and isinstance(tl, QDialog):
                tl.close()
        QTest.qWait(300)
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        gc.collect()
        with open("/proc/self/statm") as fh:
            rss = int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576
        print(f"  step {step:>5}: widgets {len(self.app.allWidgets()):>5}  python objects {len(gc.get_objects()):>7}  RSS {rss:>5.0f} MB", flush=True)

    def check_invariants(self) -> None:
        st = self.win.store
        if not st.is_unlocked:
            return
        v = st.vault
        for key in ("tasks", "archive", "notes", "habits", "goals"):
            ids = [x.get("id") for x in v.get(key, [])]
            if any(not i for i in ids):
                self._fail("invariant", f"{key}: entity without id")
            if len(ids) != len(set(ids)):
                import collections
                dup = [k for k, n in collections.Counter(ids).items() if n > 1][:3]
                detail = [(x.get("id"), x.get("title"), x.get("rep") or x.get("repeat"), x.get("seriesId"), x.get("done")) for x in v[key] if x.get("id") in dup][:6]
                self._fail("invariant", f"{key}: duplicate ids {detail}")
        for t in v.get("tasks", []):
            if not isinstance(t.get("title"), str) or not isinstance(t.get("subs", []), list):
                self._fail("invariant", f"task broken: {str(t)[:120]}")
                break
        try:
            json.dumps(v, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            self._fail("invariant", f"vault not serialisable: {exc}")

    def run(self) -> int:
        t0 = time.time()
        for n in range(self.steps):
            self.act()
            if self.trace and n % self.trace == self.trace - 1:
                self._trace_row(n + 1)
            if n % self.check_every == self.check_every - 1:
                QApplication.processEvents()
                self.check_invariants()
                if len(self.errors) > 12:
                    break
        # tidy: close strays, unlock, save, compare with what a fresh process would read
        for tl in QApplication.topLevelWidgets():
            if tl is not self.win and tl.isVisible():
                tl.close()
        QApplication.processEvents()
        self._unlock()
        if self.win.store.is_unlocked:
            self.win._flush_notes()
            self.win.store.save()
            live = json.loads(json.dumps(self.win.store.vault, sort_keys=True))
            again = VaultStore(self.tmp / "data")
            try:
                again.unlock(PW)
                if json.loads(json.dumps(again.vault, sort_keys=True)) != live:
                    self._fail("persistence", "saved vault differs from the live one after reload")
            except Exception as exc:                                  # noqa: BLE001
                self._fail("persistence", f"reload failed: {exc!r}")
        self.win.store.dirty = False
        dt = time.time() - t0
        print(f"seed {self.seed}: {self.steps} steps in {dt:.0f}s  actions={self.counts}  errors={len(self.errors)}  "
              f"qt-warnings={len(self.warnings)}", flush=True)
        seen = set()
        for kind, msg, recent in self.errors:
            key = (kind, msg.strip().splitlines()[-1][:160])
            if key in seen:
                continue
            seen.add(key)
            print(f"\n[{kind}] {msg}\n  last actions:\n    " + "\n    ".join(recent), flush=True)
        for w in sorted(set(self.warnings))[:20]:
            print("  qt:", w[:200])
        return 1 if self.errors else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--check-every", type=int, default=50)
    ap.add_argument("--trace", type=int, default=0, help="print widget/object/memory counts every N steps")
    ap.add_argument("--mode", choices=["normal", "empty", "big"], default="normal")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        c = Chaos(a.seed, a.steps, Path(d), a.verbose, a.mode)
        c.check_every = a.check_every
        c.trace = a.trace
        (Path(d) / "bk").mkdir()
        code = c.run()
        c.win.close()
        return code


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)                      # same as the real launcher: no PyQt wrapper walk at interpreter teardown
