# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end GUI tests (offscreen): drive the real widgets like a user would."""
import datetime as dt, json, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog
from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import VaultStore
from aegis_desktop.ui import dialogs, main_window as mw_mod, theme
from aegis_desktop.ui.main_window import MainWindow

PW = "correct horse battery 42"

@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    app = QApplication.instance()
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.load_font(app)
    # never block on modal message boxes in tests
    monkeypatch.setattr(dialogs, "info", lambda *a, **k: None)
    monkeypatch.setattr(dialogs, "warn", lambda *a, **k: (_ for _ in ()).throw(AssertionError("warn: %s" % (a[2:],))))
    w = MainWindow(VaultStore(tmp_path / "data"), app, tmp_path / "data" / "prefs.json")
    w.show()
    yield w
    # really destroy the window: a closed-but-alive window keeps ~700 widgets and its app-wide event filters, and
    # every later setStyleSheet() re-polishes all of them (the suite got slower and slower, then looked hung)
    from PyQt6.QtCore import QCoreApplication, QEvent
    w.store.dirty = False
    for tl in QApplication.topLevelWidgets():
        if tl is not w and tl.isVisible():
            tl.close()
    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QApplication.processEvents()

def setup_vault(w):
    w.auth.s1.edit.setText(PW); w.auth.s2.edit.setText(PW); w.auth._create()
    assert w.store.is_unlocked and w.root.currentWidget() is w.shell
    from aegis_desktop.ui import moments                     # the 2.4 s first-run ritual is not what most tests are about
    for o in w.shell.findChildren(moments._Doors):
        o.hide(); o.deleteLater()

def test_setup_rejects_weak_and_mismatch(win):
    win.auth.s1.edit.setText("short"); win.auth.s2.edit.setText("short"); win.auth._create()
    assert not win.store.exists() and "۱۰" in win.auth.s_err.text()
    win.auth.s1.edit.setText(PW); win.auth.s2.edit.setText(PW + "x"); win.auth._create()
    assert not win.store.exists() and "یکسان" in win.auth.s_err.text()

def test_full_flow_lock_unlock_persist(win):
    setup_vault(win)
    assert len(win.store.vault["tasks"]) == 4          # starter content
    win.pages["today"].quick.setText("کار تازه"); win.pages["today"]._quick_add()
    assert any(t["title"] == "کار تازه" for t in win.store.vault["tasks"])
    win.lock()
    assert not win.store.is_unlocked and win.root.currentWidget() is win.auth
    win.auth.u1.edit.setText("wrong password!!"); win.auth._unlock()
    assert "درست نیست" in win.auth.u_err.text() and not win.store.is_unlocked
    win.auth.u1.edit.setText(PW); win.auth._unlock()
    assert win.store.is_unlocked
    assert any(t["title"] == "کار تازه" for t in win.store.vault["tasks"])   # survived a lock/unlock cycle from disk

def test_no_plaintext_on_disk_after_use(win):
    setup_vault(win)
    win.store.vault["notes"].append(logic.new_note("عنوان محرمانه", "متن-خیلی-محرمانه")); win.changed()
    win.lock()
    raw = win.store.path.read_text(encoding="utf-8")
    assert "محرمانه" not in raw
    for f in win.store.dir.rglob("*"):
        if f.is_file(): assert "محرمانه" not in f.read_text(encoding="utf-8", errors="ignore"), f

def test_locked_ui_holds_no_decrypted_text(win):
    setup_vault(win)
    win.show_page("tasks"); win.show_page("notes")
    win.lock()
    assert win.pages["tasks"].table.rowCount() == 0 and win.pages["today"].today.count() == 0
    assert win.pages["notes"].list.count() == 0 and win.pages["notes"].body.toPlainText() == ""

def test_task_toggle_and_recurring(win):
    setup_vault(win)
    v = win.store.vault
    t = logic.new_task("daily thing", rep="daily", due=jalali.today_jalali()); v["tasks"].append(t)
    logic.materialize_series(v, t); win.changed()
    n = len(v["tasks"])
    win.show_page("tasks")
    tp = win.pages["tasks"]
    row = next(r for r in range(tp.table.rowCount()) if tp.table.item(r, 1).data(Qt.ItemDataRole.UserRole) == t["id"])
    tp.table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    assert t["done"] and t.get("doneAt") and len(v["tasks"]) >= n     # series stays filled

def test_kanban_move(win):
    setup_vault(win)
    x = win.store.vault["tasks"][0]
    win.pages["kanban"]._drop(x["id"], "doing"); assert logic.kanban_status(x) == "doing" and not x["done"]
    win.pages["kanban"]._drop(x["id"], "done"); assert x["done"] is True
    win.pages["kanban"]._drop(x["id"], "todo"); assert x["done"] is False

def test_calendar_navigation_and_day(win):
    setup_vault(win)
    cp = win.pages["calendar"]; win.show_page("calendar")
    y, m = cp.jy, cp.jm
    cp._shift(1); assert (cp.jy, cp.jm) == ((y, m + 1) if m < 12 else (y + 1, 1))
    cp._today(); assert cp.selected == dt.date.today()
    assert cp.day_list.count() == 4    # the four starter tasks are due today

def test_notes_autosave_and_trash_restore(win, qtbot):
    setup_vault(win)
    np_ = win.pages["notes"]; win.show_page("notes")
    np_._new()
    np_.title_in.setText("T"); np_.title_in.textEdited.emit("T")
    np_.body.setPlainText("hello <b>world</b>")
    qtbot.waitUntil(lambda: not np_._save_timer.isActive(), timeout=3000)
    n = next(n for n in win.store.vault["notes"] if n["title"] == "T")
    assert n["body"] == "hello <b>world</b>" and "&lt;b&gt;" in n["html"]      # html is escaped, not injected
    win.store.save(); win.lock(); win.auth.u1.edit.setText(PW); win.auth._unlock()
    assert any(n["title"] == "T" for n in win.store.vault["notes"])
    # delete -> trash -> restore
    win.show_page("notes"); win.pages["notes"].select_id(n["id"])
    monkey = dialogs.ask; dialogs.ask = lambda *a, **k: True
    try: win.pages["notes"]._delete()
    finally: dialogs.ask = monkey
    assert not any(x["id"] == n["id"] for x in win.store.vault["notes"]) and win.store.vault["trash"]
    win.show_page("trash"); win.pages["trash"].list.setCurrentRow(0); win.pages["trash"]._restore()
    assert any(x["id"] == n["id"] for x in win.store.vault["notes"])

def test_habits_goals(win):
    setup_vault(win)
    h = logic.new_habit("read"); win.store.vault["habits"].append(h)
    g = logic.new_goal("g", ms=[{"id": "1", "text": "a", "done": False}]); win.store.vault["goals"].append(g)
    win.changed(); win.show_page("habits"); win.show_page("goals")
    win.pages["habits"]._tick(h, dt.date.today()); assert logic.habit_stats(h)["streak"] == 1
    win.pages["goals"]._ms(g["ms"][0], True); assert logic.goal_progress(win.store.vault, g) == 100
    from aegis_desktop.ui.premium import GoalCard, HabitCard
    hp, gp = win.pages["habits"], win.pages["goals"]
    assert hp.box.itemAt(1).widget().__class__ is HabitCard and gp.box.itemAt(0).widget().__class__ is GoalCard
    hp._open.add(h["id"]); hp.refresh(); gp._expand(g["id"]); gp.refresh()      # expand paths must not raise

def test_export_import_via_ui(win, tmp_path, monkeypatch):
    setup_vault(win)
    win.store.vault["tasks"].append(logic.new_task("carry-me")); win.changed()
    out = tmp_path / "backup.aegis"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    win.export_vault(); assert out.exists()
    b = json.loads(out.read_text(encoding="utf-8"))
    assert b["format"] == "securevault1" and "carry-me" not in out.read_text(encoding="utf-8")
    # a second machine: fresh app, restore from the backup on the setup screen
    w2 = MainWindow(VaultStore(tmp_path / "pc2"), QApplication.instance(), tmp_path / "pc2" / "prefs.json")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(dialogs.ImportDialog, "exec", lambda self: (self.pw.edit.setText(PW), True)[1])
    w2.auth._restore()
    assert w2.store.is_unlocked and any(t["title"] == "carry-me" for t in w2.store.vault["tasks"])
    # wrong password -> nothing changes
    w3 = MainWindow(VaultStore(tmp_path / "pc3"), QApplication.instance(), tmp_path / "pc3" / "prefs.json")
    monkeypatch.setattr(dialogs.ImportDialog, "exec", lambda self: (self.pw.edit.setText("nope nope nope"), True)[1])
    monkeypatch.setattr(dialogs, "warn", lambda *a, **k: None)
    w3.auth._restore(); assert not w3.store.exists()

def test_import_merge_and_replace_in_app(win, tmp_path, monkeypatch):
    setup_vault(win)
    out = tmp_path / "b.aegis"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    win.export_vault()
    win.store.vault["tasks"].append(logic.new_task("local-only")); win.changed()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(out), "")))
    def fake_exec(self): self.pw.edit.setText(PW); self.replace.setChecked(True); self.merge.setChecked(False); return True
    monkeypatch.setattr(dialogs.ImportDialog, "exec", fake_exec)
    win.import_vault()
    assert not any(t["title"] == "local-only" for t in win.store.vault["tasks"])   # replaced
    assert win.store.list_backups()                                                # and a safety snapshot exists

def test_change_password_and_recovery_ui_paths(win, monkeypatch):
    setup_vault(win)
    monkeypatch.setattr(dialogs.RecoveryKeyDialog, "exec", lambda self: 1)
    win.pages["settings"]._recovery()
    assert win.store.has_recovery()
    monkeypatch.setattr(dialogs.NewPasswordDialog, "exec", lambda self: 1)
    monkeypatch.setattr(dialogs.NewPasswordDialog, "password", lambda self: "an entirely new pass 5!")
    win.pages["settings"]._change_pw()
    win.lock(); win.auth.u1.edit.setText("an entirely new pass 5!"); win.auth._unlock()
    assert win.store.is_unlocked

def test_all_pages_render_all_themes(win):
    setup_vault(win)
    for th in theme.THEME_ORDER:
        win.set_pref("palette", th)
        assert win.theme == theme.mode_of(th)
        for k in win.pages:
            win.show_page(k)
            assert not win.grab().isNull()

def test_palette_search(win):
    setup_vault(win)
    p = mw_mod.Palette(win); p._fill("Aegis")
    kinds = {p.list.item(i).data(Qt.ItemDataRole.UserRole)[0] for i in range(p.list.count())}
    assert "task" in kinds or "note" in kinds

def test_reminder_fires_once(win):
    setup_vault(win)
    now = dt.datetime.now()                       # due this minute: stable even right before midnight
    t = logic.new_task("meeting", due=jalali.today_jalali(), timeFrom=now.strftime("%H:%M")); win.store.vault["tasks"].append(t)
    got = []; win.notify = lambda m, beep=False, **k: got.append(m)
    win.prefs["remind_min"] = 10
    win._reminders(); win._reminders()
    assert len(got) == 1 and "meeting" in got[0]

def test_autolock(win):
    setup_vault(win)
    win.prefs["autolock_min"] = 1; win.last_activity -= 120
    win._idle_check(); assert not win.store.is_unlocked

def test_lock_refuses_when_save_fails(win, monkeypatch):
    setup_vault(win)
    win.store.dirty = True
    monkeypatch.setattr(win.store, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    shown = []; monkeypatch.setattr(dialogs, "warn", lambda *a, **k: shown.append(a))
    win.lock()
    assert win.store.is_unlocked and shown        # never lose data by locking on a failed save

def test_bruteforce_speed_bump(win):
    setup_vault(win); win.lock()
    for _ in range(5):
        win.auth.u1.edit.setText("bad bad bad bad"); win.auth._unlock()
    assert not win.auth.u_btn.isEnabled()

def test_autosave_failure_does_not_crash_and_retries(win, monkeypatch):
    setup_vault(win)
    win.store.dirty = True
    real_save = win.store.save
    monkeypatch.setattr(win.store, "save", lambda: (_ for _ in ()).throw(PermissionError("locked by antivirus")))
    win._autosave()                       # must not raise into Qt
    assert win.save_timer.isActive() and "ذخیره نشد" in win.status_lb.text()
    win.save_timer.stop()
    monkeypatch.setattr(win.store, "save", real_save)   # the disk "recovers"; window teardown saves fine
    win._autosave(); assert not win.store.dirty


def test_auto_backup_settings_and_browser(win, tmp_path):
    setup_vault(win)
    win.set_pref("backup_dir", str(tmp_path / "bk")); win.set_pref("backup_keep", 5)
    assert win.store.backup_dir == tmp_path / "bk" and win.store.keep_backups == 5
    for _ in range(3): assert win.backup_now("manual")
    win.set_pref("backup_auto", False)
    assert win.store.unlock_backup_s == 0
    sp = win.pages["settings"]; sp.refresh()
    assert len(win.store.list_backups()) >= 3 and sp.hero.state in ("ok", "off")
    from aegis_desktop.ui.backup_ui import BackupBrowser
    d = BackupBrowser(win)
    assert d._cur() is not None and d.b_restore.isEnabled()
    d.close()


def test_pomodoro_survives_lock_and_uses_wall_clock(win, monkeypatch):
    import time as _t
    setup_vault(win)
    f = win.pages["focus"]
    base = _t.monotonic()
    f.left = 3
    f._toggle()
    assert f.running
    f._deadline = _t.monotonic() - 0.01                # the clock moved on (sleep / a busy UI) - no tick was lost
    win.lock()                                          # auto-lock fires mid-session
    assert not win.store.is_unlocked
    f._tick()                                           # must not touch the closed vault
    assert f._pending == 1 and f.mode == "break" and not f.running
    win.auth.u1.edit.setText(PW); win.auth._unlock()
    assert win.store.is_unlocked
    assert win.store.vault["settings"]["pomoLog"][logic.iso_day(dt.date.today())] == 1 and f._pending == 0


def test_pomodoro_pause_freezes_remaining(win):
    import time as _t
    setup_vault(win)
    f = win.pages["focus"]
    f.left = 100
    f._toggle()
    f._deadline = _t.monotonic() + 40.2
    f._toggle()
    assert not f.running and f.left == 41


def test_delete_note_keeps_last_keystrokes_in_trash(win):
    setup_vault(win)
    n = win.pages["notes"]
    n._new()
    n.body.setPlainText("آخرین کلمات")
    n._delete(confirm=False)                            # hold-to-delete: no dialog, pending edit still in the debounce
    assert win.store.vault["trash"][-1]["item"]["body"] == "آخرین کلمات"


def test_tasks_table_bulk_fill_matches_data(win):
    setup_vault(win)
    for i in range(50):
        win.store.vault["tasks"].append(logic.new_task(f"bulk {i}", due=dict(jalali.today_jalali()), color="c1" if i % 2 else "c0"))
    win.changed()
    win.show_page("tasks")
    t = win.pages["tasks"].table
    assert t.rowCount() >= 54 and t.updatesEnabled()
    assert all(not (t.item(r, c).flags() & Qt.ItemFlag.ItemIsEditable) for r in range(t.rowCount()) for c in range(6) if c != 1)   # only the title cell is (inline-)editable
    assert all(t.item(r, 1).flags() & Qt.ItemFlag.ItemIsEditable for r in range(t.rowCount()))


def test_damaged_prefs_never_break_startup(win, tmp_path):
    p = tmp_path / "bad-prefs.json"
    win.prefs_path = p
    p.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert win._load_prefs() == {}
    p.write_text('{"font_pt": "big", "autolock_min": -5, "backup_keep": 99999, "backup_every_h": true, "palette": "falcon", "theme": "light"}', encoding="utf-8")
    got = win._load_prefs()
    assert (got["font_pt"], got["autolock_min"], got["backup_keep"], got["backup_every_h"]) == (10, 15, 30, 6)
    assert got["palette"] == "aegis-light" and "theme" not in got                        # legacy prefs migrate to the brand themes
    p.write_text("{oops", encoding="utf-8")
    assert win._load_prefs() == {}
    win.set_pref("autolock_min", 20)                    # atomic write leaves no temp files behind
    assert json.loads(p.read_text(encoding="utf-8"))["autolock_min"] == 20
    assert not list(tmp_path.glob("bad-prefs.json.*.tmp"))


# ------------------------------------------------------------------ redesigned UI pieces ---
def _click(w, pos=None, button=Qt.MouseButton.LeftButton):
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import QPoint
    QTest.mouseClick(w, button, Qt.KeyboardModifier.NoModifier, pos if pos is not None else QPoint(w.width() // 2, w.height() // 2))

def test_tactile_buttons_and_dock(qtbot):
    from PyQt6.QtGui import QIcon
    from aegis_desktop.ui import tactile
    from aegis_desktop.ui.fx_widgets import IconToolButton
    from aegis_desktop.ui.theme import PALETTES
    b = IconToolButton("lock", "قفل", size=40); qtbot.addWidget(b); b.show()
    assert (b.width(), b.height()) == (40, 43)
    with qtbot.waitSignal(b.clicked, timeout=1000):
        _click(b)
    assert not b.grab().isNull()
    dock = tactile.ToolDock(size=36); qtbot.addWidget(dock)
    for k in ("bold", "italic", "save"):
        dock.add_tool(k, k, k)
    dock.show()
    with qtbot.waitSignal(dock.picked, timeout=1000) as sig:
        _click(dock.button("italic"))
    assert sig.args == ["italic"]
    dock.set_enabled_all(False)
    assert not any(dock.button(k).isEnabled() for k in ("bold", "italic", "save"))
    assert not dock.grab().isNull()
    for fam in PALETTES.values():                      # every sidebar glyph paints on every palette
        for name in ("today", "tasks", "notes", "reports", "settings"):
            ic = tactile.tile_icon(name, fam, True, 34)
            assert isinstance(ic, QIcon) and not ic.isNull()

def test_progress_ring_card_stage_click_and_data(qtbot):
    from aegis_desktop.ui.report_widgets import ProgressRingCard
    c = ProgressRingCard("dark"); qtbot.addWidget(c); c.resize(330, 420)
    c.set_data([("الف", 100, None), ("ب", 40, None), ("ج", 250, None)], 60, "تکمیل‌شده", "dark")
    assert [round(v) for _l, v, _c in c.stages] == [100, 40, 100]        # values are clamped to 0-100
    c.show(); qtbot.wait(50); c.grab()                                    # paints (rects are laid out by painting)
    assert len(c._rects) == 3
    with qtbot.waitSignal(c.stage_clicked, timeout=1000) as sig:
        _click(c, c._rects[1].center().toPoint())
    assert sig.args == [1] and c._active == 1 and c._target() == 40
    _click(c, c._rects[1].center().toPoint())                             # a second click returns to the overall value
    assert c._active is None and c._target() == 60
    c.set_data([], 0, "خالی", "dark")                                     # empty data must still paint
    c.grab()

def test_activity_calendar_month_navigation(qtbot):
    from aegis_desktop.ui.report_widgets import ActivityCalendar
    asked = []
    cal = ActivityCalendar(lambda a, b: asked.append((a, b)) or {a: 3}, "dark"); qtbot.addWidget(cal)
    cal.resize(320, 280); cal.show(); cal.grab()
    jy, jm = cal.jy, cal.jm
    cal._shift(1)
    assert (cal.jy, cal.jm) == ((jy, jm + 1) if jm < 12 else (jy + 1, 1))
    cal._shift(-1)
    assert (cal.jy, cal.jm) == (jy, jm)
    cal.jm = 12; cal._shift(1)
    assert cal.jm == 1                                                    # rolls into the next year
    a, b = asked[-1]
    assert a < b and (b - a).days in (28, 29, 30)                         # exactly one Jalali month is requested
    cal.grab()

def test_reports_page_has_ring_cards_and_calendar(win):
    setup_vault(win)
    win.show_page("reports"); QApplication.processEvents()
    p = win.pages["reports"]
    assert p.ring_cat.stages is not None and p.activity.provider is not None
    win.store.vault["tasks"].append(logic.new_task("انجام‌شده", due=jalali.today_jalali(), done=True)); win.changed()
    p.refresh()
    assert p.ring_cat.overall > 0
    assert not p.grab().isNull()

def test_notes_editor_dock_and_paper(win):
    setup_vault(win)
    win.show_page("notes"); QApplication.processEvents()
    p = win.pages["notes"]
    assert not p.dock.button("bold").isEnabled()                          # nothing selected -> tools are off
    p._new()
    assert p.dock.button("bold").isEnabled() and p.body.isEnabled()
    p.body.setPlainText("سلام")
    p.body.selectAll()
    p.dock.button("bold").click()
    assert p.body.toPlainText() == "**سلام**"
    p.body.setPlainText("خط"); p.dock.button("list").click()
    assert p.body.toPlainText().startswith("- [ ] ")
    # the page is right-to-left: text hugs the right edge, direction stays automatic per paragraph
    opt = p.body.document().defaultTextOption()
    assert opt.alignment() & Qt.AlignmentFlag.AlignRight and opt.textDirection() == Qt.LayoutDirection.LayoutDirectionAuto
    assert not p.paper.grab().isNull()

def test_toast_notifications(win, qtbot):
    setup_vault(win)
    h = win.toasts
    win.notify("«جلسه» ساعت ۱۴:۳۰", kind="reminder", title="یادآوری تسک")
    assert h.count() == 1 and win.status_lb.text() == "«جلسه» ساعت ۱۴:۳۰"
    win.notify("«جلسه» ساعت ۱۴:۳۰", kind="reminder", title="یادآوری تسک")          # duplicate within 2 s is dropped
    assert h.count() == 1
    for i in range(5):
        win.notify(f"پیام {i}", kind="alert" if i % 2 else "info")
    qtbot.waitUntil(lambda: sum(1 for t in h._toasts if not t._closing) <= 3, timeout=3000)   # at most 3 stay
    top = h._toasts[0]
    qtbot.waitUntil(top.isVisible, timeout=3000)                                         # a burst pops in one by one
    assert "پیام 4" in top.accessibleName()
    long = h.push("خیلی " * 120, "info")
    assert long._shown.endswith("…") and long.height() < 140                            # long text is clipped to 2 lines
    top.close_toast()
    qtbot.waitUntil(lambda: top not in h._toasts, timeout=3000)
    h.clear(); assert h.count() == 0
    assert h.push("   ") is None                                                          # blank messages are ignored

def test_toast_pops_in_with_scale(win, qtbot):
    setup_vault(win)
    h = win.toasts
    t = h.push("پیام تست", "info", "عنوان", ms=4000)
    qtbot.waitUntil(lambda: t.isVisible() and t._vis.value > 0.2, timeout=2000)
    assert t._vis.value <= 1.1                                                          # overshoot stays small
    qtbot.waitUntil(lambda: abs(t._vis.value - 1.0) < 0.01, timeout=2000)
    assert not t.grab().isNull()
    burst = [h.push(f"دسته {i}", "info", ms=4000) for i in range(3)]
    assert [b for b in burst if b is None] == []
    qtbot.waitUntil(lambda: all(b.isVisible() for b in burst if not b._closing), timeout=3000)
    h.clear()


def test_stagger_entrance_leaves_no_effect(win, qtbot):
    """The entrance only changes painting (offset + opacity): geometry always equals what the layout says."""
    from aegis_desktop.ui import anim
    setup_vault(win)
    win.show_page("today")
    pg = win.stack.currentWidget()
    qtbot.wait(60)
    anim.stagger_in(pg)
    tg = anim._entrance_targets(pg)
    assert tg, "the today page has cards to animate"
    rest = {id(w): w.geometry() for w in tg}
    st = list(pg._stagger)
    qtbot.wait(200)
    assert all(s["w"].geometry() == rest[id(s["w"])] for s in st)                     # never moved by the animation
    win.resize(win.width() + 140, win.height()); qtbot.wait(80)                         # resize mid-flight
    anim.finish_stagger(pg)
    assert pg._stagger == [] and all(s["w"].graphicsEffect() is None for s in st)
    anim.MOTION[0] = False
    try:
        anim.stagger_in(pg)
        assert pg._stagger == []                                                        # reduced motion: nothing moves
    finally:
        anim.MOTION[0] = True
    anim.stagger_in(pg)
    ws = [s["w"] for s in pg._stagger]
    qtbot.waitUntil(lambda: pg._stagger == [] and all(w.graphicsEffect() is None for w in ws), timeout=6000)
    for w in ws:                                                                        # layout never disagreed
        lay = w.parentWidget().layout()
        lay.invalidate(); lay.activate()
    assert not pg.grab().isNull()


def test_toast_pauses_on_hover_and_click_dismisses(win, qtbot):
    from PyQt6.QtCore import QPoint
    setup_vault(win)
    h = win.toasts
    t = h.push("سلام", "success", "امنیت", ms=1600)
    qtbot.wait(400)
    _click(t, QPoint(t.width() // 2, t.height() // 2))                                    # click on the body: dismiss
    qtbot.waitUntil(lambda: t not in h._toasts, timeout=3000)


# ------------------------------------------------------------------ motion ---
def test_number_ticker_and_kpi_tile(qtbot):
    from aegis_desktop.ui.anim import parse_number
    assert parse_number("۱۲٪") == ("", 12.0, "٪", 0)
    assert parse_number("+3.5 ساعت") == ("+", 3.5, " ساعت", 1)
    assert parse_number("—") is None
    from aegis_desktop.ui.premium import KpiTile
    t = KpiTile("check", "success"); qtbot.addWidget(t); t.resize(240, 104)
    t.set("۴۲", "انجام‌شده")
    assert t.value == "۴۲"
    qtbot.waitUntil(lambda: t._tick.shown() == "۴۲", timeout=3000)            # counted up to the value
    t.set("۷", "انجام‌شده")
    qtbot.waitUntil(lambda: t._tick.shown() == "۷", timeout=3000)             # and back down
    t.set("—", "x"); assert t._tick.shown() == "—"                            # non-numeric text is shown as is
    t.show(); qtbot.wait(30); assert not t.grab().isNull()

def test_marker_highlight_in_notes(win, qtbot):
    from aegis_desktop.ui.anim import mark_progress, sweep_rect
    from aegis_desktop.ui.premium import MARK_RE
    assert MARK_RE.findall("a ==b c== d ==e== == f ==") == ["b c", "e"]        # spaces right inside the marks: not a highlight
    assert mark_progress(10.0, 9.0) == 0.0 and mark_progress(10.0, 12.0) == 1.0
    r0, r1 = sweep_rect(10, 110, 0, 20, 0.5, True), sweep_rect(10, 110, 0, 20, 0.5, False)
    assert r0.right() > r1.right() and abs(r0.width() - r1.width()) < 1e-6      # RTL sweeps from the right edge
    setup_vault(win)
    win.show_page("notes"); QApplication.processEvents()
    p = win.pages["notes"]
    p._new(); p.body.setPlainText("سلام ==دنیا== و ==متن دوم==")
    p.body.grab()
    assert set(p.body._marks) == {"==دنیا==", "==متن دوم=="}
    p.body.selectAll(); p.body.setPlainText("بدون هایلایت"); p.body.grab()
    assert p.body._marks == {}                                                # a new text starts with a clean slate
    p.body.setPlainText("جمله"); p.body.selectAll(); p.dock.button("mark").click()
    assert p.body.toPlainText() == "==جمله=="
    qtbot.waitUntil(lambda: len(p.body.extraSelections()) == 2, timeout=1000)  # the '==' delimiters are dimmed
    assert not p.list.grab().isNull()                                          # card previews render the mark, without '=='

def test_palette_match_highlight(win, qtbot):
    setup_vault(win)
    d = mw_mod.Palette(win); qtbot.addWidget(d); d.show()
    d.q.setText("تسک")
    assert d._needle == "تسک" and d._mark_timer.isActive()
    assert not d.list.viewport().grab().isNull()
    qtbot.waitUntil(lambda: not d._mark_timer.isActive(), timeout=4000)        # repainting stops when the strokes are done
    d.q.setText(""); assert d._needle == ""

def test_link_button_underline(qtbot):
    from aegis_desktop.ui.anim import LinkButton
    from aegis_desktop.ui.widgets import button
    b = button("رمز را فراموش کرده‌ام", "Link"); qtbot.addWidget(b); b.show()
    assert isinstance(b, LinkButton) and b.objectName() == "Link"
    assert b._head.value == 0.0
    b._enter(); qtbot.waitUntil(lambda: b._head.value > 0.95, timeout=2000)
    assert not b.grab().isNull()
    b._leave(); qtbot.waitUntil(lambda: b._head.value == 0.0 and b._tail.value == 0.0, timeout=2000)   # left through the far edge, reset
    got = []; b.clicked.connect(lambda: got.append(1)); _click(b); assert got == [1]

def test_scramble_label_settles_and_keeps_text(qtbot):
    from aegis_desktop.ui.anim import ScrambleLabel
    lb = ScrambleLabel("گزارش‌ها و تحلیل 12"); qtbot.addWidget(lb); lb.show()
    lb.replay(300)
    qtbot.wait(60)
    assert lb._run and len(lb._shown) == len(lb.text()) and lb.text() == "گزارش‌ها و تحلیل 12"
    assert all(a == b for a, b in zip(lb._shown, lb.text()) if b.isspace())        # spaces never shuffle
    assert not lb.grab().isNull()
    qtbot.waitUntil(lambda: not lb._run, timeout=3000)
    assert lb.text() == "گزارش‌ها و تحلیل 12"
    wrapped = ScrambleLabel("x"); wrapped.setWordWrap(True); wrapped.replay(); assert not wrapped._run   # multi-line labels are left alone

def test_page_title_scrambles_on_navigation(win, qtbot):
    from aegis_desktop.ui.anim import ScrambleLabel
    setup_vault(win)
    win.show_page("tasks"); QApplication.processEvents()
    titles = [l for l in win.pages["tasks"].findChildren(ScrambleLabel) if l.objectName() == "H1"]
    assert titles and titles[0]._run
    qtbot.waitUntil(lambda: not titles[0]._run, timeout=3000)
    assert win._brand_lb.text() == "Aegis Planner"

def test_loading_button_state(qtbot):
    from PyQt6.QtWidgets import QPushButton
    from aegis_desktop.ui.anim import Spinner, set_loading
    b = QPushButton("باز کردن"); qtbot.addWidget(b); b.resize(200, 40); b.show()
    set_loading(b, True, "در حال باز کردن…")
    assert not b.isEnabled() and b.text() == "در حال باز کردن…" and b.findChildren(Spinner)
    set_loading(b, True, "again")                                            # idempotent
    assert len(b.findChildren(Spinner)) == 1
    qtbot.wait(40); assert not b.grab().isNull()
    set_loading(b, False)
    assert b.isEnabled() and b.text() == "باز کردن" and not b.findChildren(Spinner)
    for kind in ("arc", "ring"):
        sp = Spinner(20, kind); qtbot.addWidget(sp); sp.show(); qtbot.wait(30); assert not sp.grab().isNull()

def test_unlock_button_shows_spinner_while_deriving_key(win, monkeypatch):
    from aegis_desktop.ui import anim
    setup_vault(win); win.lock()
    seen = []
    orig = anim.set_loading
    monkeypatch.setattr(anim, "set_loading", lambda b, on, text=None: (seen.append((b is win.auth.u_btn, on, text)), orig(b, on, text))[1])
    win.auth.u1.edit.setText(PW); win.auth._unlock()
    assert win.store.is_unlocked
    assert (True, True, "در حال باز کردن…") in seen and win.auth.u_btn.isEnabled() and win.auth.u_btn.text() == "باز کردن"

def test_gooey_thumb_path_and_segments(qtbot):
    from PyQt6.QtCore import QRectF
    from aegis_desktop.ui.motion_widgets import JellyRadio, RubberSegment, gooey_path
    rest = gooey_path(0, 60, 0, 30, 60, 10)                                    # resting thumb: a plain rounded rect
    assert rest.boundingRect() == QRectF(0, 0, 60, 30)
    stretched = gooey_path(0, 200, 0, 30, 60, 10)                              # travelling: two round ends + a pinched neck
    assert stretched.boundingRect().width() == pytest.approx(200, abs=0.5)
    assert stretched.contains(QRectF(0, 0, 60, 30).center()) and stretched.contains(QRectF(140, 0, 60, 30).center())
    assert not stretched.contains(QRectF(95, 0, 10, 2).center())               # the neck is pinched at its top edge
    for w in (RubberSegment(["روز", "هفته", "ماه"]), JellyRadio(["الف", "ب", "ج"])):
        qtbot.addWidget(w); w.show(); w.set_index(2); qtbot.wait(90); assert not w.grab().isNull()
        qtbot.waitUntil(lambda w=w: abs(w._lead.value - w._rects()[2].left()) < 1, timeout=2000)

def test_reports_new_charts(win):
    setup_vault(win)
    v = win.store.vault
    for i in range(12):
        v["tasks"].append(_done_task_gui(dt.date.today() - dt.timedelta(days=i * 3)))
    win.changed()
    win.show_page("reports"); QApplication.processEvents()
    p = win.pages["reports"]
    p.refresh()
    assert len(p.hbars.data) == 7 and all(len(r) == 3 for r in p.hbars.data)
    assert [r["kind"] for r in p.spark.rows] == ["area", "bars", "line", "bars", "pie"]
    assert len(p.spark.rows[0]["values"]) == p.days.currentData()
    assert p.area.data2 is not None and len(p.area.data2) == len(p.area.data)
    for w in (p.hbars, p.spark, p.area):
        w.resize(420, 320); w.show(); QApplication.processEvents()
        assert not w.grab().isNull()
    p.hbars._hover = 3; p.hbars.update(); assert not p.hbars.grab().isNull()      # tooltip path

def _done_task_gui(day):
    t = logic.new_task("y")
    t["done"] = True
    t["doneAt"] = t["createdAt"] = dt.datetime.combine(day, dt.time(12, 0)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return t


# ------------------------------------------------ segmented bars, tasks table, pagination ---
def test_segmented_progress_bar(win, qtbot):
    from PyQt6.QtGui import QColor
    from aegis_desktop.ui import anim
    from aegis_desktop.ui.premium import SegmentedProgress, distinct_color
    pal = theme.PALETTES[win.theme]
    base = QColor(pal["accent"])
    other = distinct_color(pal, [base])
    assert min(((other.red() - t.red()) ** 2 + (other.green() - t.green()) ** 2 + (other.blue() - t.blue()) ** 2) ** 0.5
               for t in [base]) >= 60                                                  # the second colour is clearly different
    bar = SegmentedProgress([(3, base, "مراحل"), (0, other, "هیچ"), (2, other, "تسک")], 8)
    qtbot.addWidget(bar); bar.resize(420, bar.height()); bar.show()
    assert len(bar.segments) == 2 and bar.filled == pytest.approx(5 / 8)              # empty segments are dropped
    assert "مراحل ۳" in bar.toolTip() and "باقی‌مانده ۳" in bar.toolTip()
    assert bar in anim._STRIPE_W                                                       # unfinished + visible: stripes march
    qtbot.wait(60); anim.stripe_tick(); assert not bar.grab().isNull()
    bar.hide(); assert bar not in anim._STRIPE_W                                        # hidden: no clock work
    full = SegmentedProgress([(4, base, "الف")], 4); qtbot.addWidget(full); full.show()
    assert full.filled == pytest.approx(1.0) and full not in anim._STRIPE_W             # complete: static
    old = anim.MOTION[0]
    anim.MOTION[0] = False
    try:
        calm = SegmentedProgress([(1, base, "الف")], 4); qtbot.addWidget(calm); calm.show()
        assert calm not in anim._STRIPE_W and not calm.grab().isNull()
    finally:
        anim.MOTION[0] = old


def test_goal_and_habit_cards_carry_segmented_bar(win):
    from aegis_desktop.ui.premium import GoalCard, HabitCard, SegmentedProgress
    setup_vault(win)
    v = win.store.vault
    g = logic.new_goal("هدف تست", ms=[{"id": "a", "text": "الف", "done": True}, {"id": "b", "text": "ب", "done": False}])
    v["goals"].append(g)
    for i, (done, st) in enumerate([(True, "done"), (False, "doing"), (False, "todo")]):
        t = logic.new_task(f"t{i}", goalId=g["id"])
        logic.set_status(t, st)
        v["tasks"].append(t)
    h = logic.new_habit("ورزش")
    for d in range(10):
        logic.habit_toggle(h, dt.date.today() - dt.timedelta(days=d))
    v["habits"].append(h)
    win.changed()
    win.show_page("goals"); win.pages["goals"].refresh()
    card = next(w for w in win.pages["goals"].findChildren(GoalCard) if w.gid == g["id"])
    bar = card.findChild(SegmentedProgress)
    assert bar is not None and bar.total == 5
    assert [round(n) for n, _c, _t in bar.segments] == [1, 1, 1]                        # milestone / done task / doing task
    win.show_page("habits"); win.pages["habits"].refresh()
    hc = next(w for w in win.pages["habits"].findChildren(HabitCard) if w.hid == h["id"])
    hb = hc.findChild(SegmentedProgress)
    assert hb is not None and hb.total == 30 and [round(n) for n, _c, _t in hb.segments] == [7, 3]


def test_tasks_table_hover_status_and_round_buttons(win, qtbot, monkeypatch):
    from PyQt6.QtCore import QPoint, QRectF
    from PyQt6.QtTest import QTest
    from aegis_desktop.ui.task_table import COL_ACT, COL_STATUS, COL_TITLE, button_rects
    setup_vault(win)
    v = win.store.vault
    v["tasks"].clear()
    late = logic.new_task("عقب افتاده", due=jalali.date_to_due(dt.date.today() - dt.timedelta(days=2)))
    doing = logic.new_task("در جریان"); logic.set_status(doing, "doing")
    fin = logic.new_task("تمام شده"); logic.set_status(fin, "done")
    v["tasks"] += [late, doing, fin]
    win.changed()
    win.show_page("tasks"); tp = win.pages["tasks"]; tp.status.setCurrentIndex(tp.status.findData("all")); tp.refresh()
    qtbot.wait(80)
    tb = tp.table
    assert tb.columnCount() == 8
    labels = {tb.item(r, COL_TITLE).text(): tb.item(r, COL_STATUS).text() for r in range(tb.rowCount())}
    assert labels == {"عقب افتاده": "عقب‌افتاده", "در جریان": "در حال انجام", "تمام شده": "انجام‌شده"}
    row = next(r for r in range(tb.rowCount()) if tb.item(r, COL_TITLE).data(Qt.ItemDataRole.UserRole) == doing["id"])
    cell = QRectF(tb.visualRect(tb.model().index(row, COL_ACT)))
    btn = [r.center().toPoint() for r in button_rects(cell)]
    QTest.mouseMove(tb.viewport(), btn[1]); qtbot.wait(30)
    assert tb.hover_row == row and tb.hover_btn == 1                                      # row wash + delete button hovered
    qtbot.waitUntil(lambda: tb.row_hover(row) > 0.95, timeout=2000)
    assert not tb.viewport().grab().isNull()
    QTest.mouseMove(tb.viewport(), QPoint(2, 2)); qtbot.wait(20)
    # edit button
    seen = []
    monkeypatch.setattr(win, "edit_task_id", lambda tid: seen.append(tid))
    QTest.mouseClick(tb.viewport(), Qt.MouseButton.LeftButton, pos=btn[0])
    assert seen == [doing["id"]] and not tb.selectedItems()                                # clicking a button never selects the row
    # a click on the title cell does select
    QTest.mouseClick(tb.viewport(), Qt.MouseButton.LeftButton, pos=tb.visualRect(tb.model().index(row, COL_TITLE)).center())
    assert tb.selectedItems()
    # delete button -> trash
    QTest.mouseClick(tb.viewport(), Qt.MouseButton.LeftButton, pos=btn[1])
    assert not any(t["id"] == doing["id"] for t in v["tasks"]) and any(e["item"].get("id") == doing["id"] for e in v["trash"])
    assert tb.rowCount() == 2


def test_tasks_table_hides_minor_columns_when_narrow(win, qtbot):
    from aegis_desktop.ui.task_table import COL_CAT, COL_TAGS
    setup_vault(win)
    win.resize(1300, 800); win.show_page("tasks"); qtbot.wait(80)
    tb = win.pages["tasks"].table
    assert not tb.isColumnHidden(COL_TAGS) and not tb.isColumnHidden(COL_CAT)
    win.resize(920, 700); qtbot.wait(120)
    assert tb.isColumnHidden(COL_TAGS) and tb.isColumnHidden(COL_CAT)


def test_paginator_widget(qtbot):
    from PyQt6.QtTest import QTest
    from aegis_desktop.ui.paginator import Paginator, page_count, page_items
    assert page_count(0, 8) == 1 and page_count(8, 8) == 1 and page_count(9, 8) == 2
    assert page_items(1, 3) == [1, 2, 3]
    assert page_items(1, 10) == [1, 2, 3, 4, None, 10]
    assert page_items(5, 10) == [1, None, 4, 5, 6, None, 10]
    assert page_items(10, 10) == [1, None, 7, 8, 9, 10]
    assert all(len(page_items(c, 40)) <= 7 for c in range(1, 41))
    pg = Paginator(); qtbot.addWidget(pg); pg.resize(520, pg.height())
    pg.show()
    pg.set_state(1, 5, 8)
    assert not pg.isVisible()                                                              # one page: the control hides itself
    pg.set_state(1, 30, 8); pg.show()
    assert pg.isVisible() and pg.pages == 4 and pg.range_text() == "۱–۸ از ۳۰"
    got = []
    pg.pageChanged.connect(got.append)
    cells = {(k, v): r for k, v, r in pg._cells()}
    QTest.mouseClick(pg, Qt.MouseButton.LeftButton, pos=cells[("page", 3)].center().toPoint())
    assert got == [3] and pg.page == 3
    QTest.mouseClick(pg, Qt.MouseButton.LeftButton, pos=pg._cells()[0][2].center().toPoint())   # "قبلی" is first (right edge)
    assert got == [3, 2]
    QTest.keyClick(pg, Qt.Key.Key_Left); assert pg.page == 3                                # RTL: left arrow = next
    QTest.keyClick(pg, Qt.Key.Key_End); assert pg.page == 4
    QTest.keyClick(pg, Qt.Key.Key_Left); assert pg.page == 4                                # clamped, no extra signal
    assert got[-1] == 4 and got.count(4) == 1
    QTest.mouseClick(pg, Qt.MouseButton.LeftButton, pos=pg._cells()[-1][2].center().toPoint())  # disabled "بعدی": nothing
    assert pg.page == 4
    qtbot.wait(350); assert not pg.grab().isNull()
    pg.set_state(9, 10, 8); assert pg.page == 2                                              # page clamps when the list shrinks


def test_trash_pagination(win, qtbot):
    setup_vault(win)
    v = win.store.vault
    v["trash"].clear()
    for i in range(19):
        win.store.trash_put("task", {"id": f"x{i}", "title": f"حذف {i}"})
    win.changed(); win.show_page("trash"); tp = win.pages["trash"]; tp.refresh()
    assert tp.pager.isVisible() and tp.pager.pages == 3 and tp.list.count() == 8
    assert tp.list.item(0).text() == "حذف 18"                                               # newest first
    tp.pager.go(3); assert tp.list.count() == 3 and tp.list.item(2).text() == "حذف 0"
    tp.list.setCurrentRow(0); tp._restore()                                                   # restore works from any page
    assert any(t["id"] == "x2" for t in v["tasks"]) and len(v["trash"]) == 18
    assert tp.pager.pages == 3 and tp.list.count() == 2
    tp.pager.go(3); tp.list.setCurrentRow(0); tp._restore(); tp.list.setCurrentRow(0); tp._restore()
    assert tp.pager.pages == 2 and tp.pager.page == 2 and tp.list.count() == 8               # last page emptied -> falls back
    v["trash"].clear(); win.changed()
    assert not tp.pager.isVisible() and tp.list.count() == 0


def test_backup_browser_pagination(win, tmp_path):
    from aegis_desktop.ui.backup_ui import BackupBrowser
    setup_vault(win)
    win.set_pref("backup_dir", str(tmp_path / "bk")); win.set_pref("backup_keep", 40)
    for _ in range(11):
        assert win.backup_now("manual")
    d = BackupBrowser(win); d.show()
    n = len(win.store.list_backups())
    assert n >= 11 and d.pager.isVisible() and d.pager.pages == -(-n // d.PAGE)
    rows = lambda: [d.list.item(i) for i in range(d.list.count()) if d.list.item(i).data(Qt.ItemDataRole.UserRole + 1) != "head"]
    assert len(rows()) == d.PAGE
    d.pager.go(2)
    assert len(rows()) == min(d.PAGE, n - d.PAGE) and d._cur() is not None                    # a row is selected on the new page
    last = d._metas[-1]["path"]
    d._load(last)                                                                            # asking for an old backup jumps to its page
    assert d.pager.page == d.pager.pages and d._cur()["path"] == last
    d.close()


def test_brand_themes_and_theme_dots(win, qtbot):
    from PyQt6.QtTest import QTest
    assert theme.THEME_DOTS == ["noir", "ivory", "aegis-light"] and theme.THEME_ORDER[0] == "noir" and theme.DEFAULT_THEME == "noir"
    assert theme.THEMES["noir"]["pal"]["accent"] == "#dfe2e8" and theme.THEMES["noir"]["pal"]["bg"] == "#060607"
    assert win.theme == "dark" and win.prefs.get("palette", "noir") == "noir"
    d = win.theme_dots
    assert len(d.order) == 3
    d.picked.emit("aegis-light")
    assert win.theme == "light" and theme.PALETTES["light"]["accent"] == "#25262b" and d.cur == "aegis-light"
    win.set_pref("palette", "midnight"); assert win.theme == "dark" and theme.PALETTES["dark"]["accent"].lower() == "#2c74b3"
    d.show(); qtbot.wait(400); assert not d.grab().isNull()
    QTest.mouseClick(d, Qt.MouseButton.LeftButton, pos=d._center(2).toPoint())               # right-most dot = first theme
    assert win.prefs["palette"] == "noir"
    QTest.keyClick(d, Qt.Key.Key_Left); assert win.prefs["palette"] == "ivory"              # RTL: left arrow = next
    setup_vault(win)
    st = win.pages["settings"]; st.refresh()
    assert set(st.picker.cards) == set(theme.THEME_ORDER) and st.picker.cards["ivory"].on
    st.picker.picked.emit("ocean"); st.refresh()
    assert win.theme == "dark" and st.picker.cards["ocean"].on and not st.picker.cards["ivory"].on
