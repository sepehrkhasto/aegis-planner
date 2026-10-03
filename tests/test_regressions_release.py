# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests: each reproduces a defect found in release review."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from aegis_desktop.core import jalali, logic
from aegis_desktop.core.crypto import WrongPassword
from aegis_desktop.core.nlp import parse_quick
from aegis_desktop.core.store import VaultError, VaultStore
from aegis_desktop.ui import dialogs
from test_gui import PW, setup_vault, win  # noqa: F401

PW1 = "first password 123"
PW2 = "second password 456"


@pytest.fixture
def st(tmp_path):
    s = VaultStore(tmp_path / "d")
    s.create(PW1)
    return s


# ------------------------------------------------------------------ store / crypto ---
def test_lone_surrogate_never_blocks_saving(st):
    st.vault["tasks"].append(logic.new_task("split emoji \ud83d"))
    st.save()
    st.lock()
    st.unlock(PW1)
    assert st.vault["tasks"][-1]["title"].startswith("split emoji")
    assert "\ud83d" not in st.vault["tasks"][-1]["title"]


def test_valid_emoji_roundtrips_untouched(st):
    st.vault["tasks"].append(logic.new_task("پروژه 🚀 نهایی"))
    st.save()
    st.lock()
    st.unlock(PW1)
    assert st.vault["tasks"][-1]["title"] == "پروژه 🚀 نهایی"


def test_recovery_key_works_with_or_without_the_prefix(st):
    key = st.setup_recovery()
    assert key.startswith("AEGIS-")
    for variant in (lambda k: k, str.lower, lambda k: k.removeprefix("AEGIS-"), lambda k: k.removeprefix("AEGIS-").replace("-", " ")):
        typed = variant(key)
        st.lock()
        st.unlock_with_recovery(typed, PW2 + "x")
        assert st.is_unlocked
        key = st.change_password(PW1) or key                  # a plain password change makes a NEW recovery key
        assert key.startswith("AEGIS-")
    st.lock()
    with pytest.raises(WrongPassword):
        st.unlock_with_recovery("AEGIS-00000-00000-00000-00000-00000", PW2)


def test_forgot_password_works_with_an_unreachable_backup_folder(st, tmp_path):
    key = st.setup_recovery()
    st.lock()
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    st.set_backup_dir(blocker / "sub")                       # mkdir fails: a drive that is not plugged in
    st.unlock_with_recovery(key, PW2)
    assert st.is_unlocked
    st.lock()
    st.unlock(PW2)


def test_failed_recovery_reset_leaves_the_vault_locked(st, monkeypatch):
    key = st.setup_recovery()
    st.lock()
    monkeypatch.setattr(VaultStore, "save", lambda self: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        st.unlock_with_recovery(key, PW2)
    assert not st.is_unlocked and st.vault is None


def test_restore_from_a_zero_byte_or_truncated_live_file(st):
    st.vault["tasks"].append(logic.new_task("keep me"))
    st.save()
    good = st.snapshot("manual")
    for damage in ("", '{"format": "securevault1", "ci'):
        st.path.write_text(damage, encoding="utf-8")
        st.restore_backup(good)
        assert any(t["title"] == "keep me" for t in st.vault["tasks"])
        st.lock()
        st.unlock(PW1)
        assert any(t["title"] == "keep me" for t in st.vault["tasks"])
    if damage:
        assert list(st.dir.glob("vault.aegis.damaged-*"))   # the broken file is kept aside, not silently lost


def test_import_replace_over_a_damaged_live_file(st, tmp_path):
    other = VaultStore(tmp_path / "other")
    other.create(PW2)
    other.vault["tasks"].append(logic.new_task("from elsewhere"))
    other.save()
    bundle = VaultStore.read_bundle(other.path)
    st.path.write_text("not json at all", encoding="utf-8")
    st.import_replace(bundle, PW2)
    assert any(t["title"] == "from elsewhere" for t in st.vault["tasks"])


def test_risky_changes_refuse_when_the_backup_folder_is_unreachable(st, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    st.set_backup_dir(blocker / "sub")
    other = VaultStore(tmp_path / "o")
    other.create(PW2)
    bundle = VaultStore.read_bundle(other.path)
    with pytest.raises(VaultError) as e:
        st.import_replace(bundle, PW2)
    assert str(tmp_path) not in str(e.value)                 # a Persian message, not a raw OS path


def test_lock_forgets_the_file_so_an_outside_replacement_is_seen(tmp_path):
    a = VaultStore(tmp_path / "d")
    a.create(PW1)
    a.lock()
    b = VaultStore(tmp_path / "other")
    b.create(PW2)
    (tmp_path / "d" / "vault.aegis").write_text(b.path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(WrongPassword):
        a.unlock(PW1)
    a.unlock(PW2)
    assert a.is_unlocked


def test_future_dated_backups_do_not_swallow_new_ones(st):
    st.keep_backups = 3
    st.backup_dir.mkdir(parents=True, exist_ok=True)
    raw = st.path.read_text(encoding="utf-8")
    for i in range(4):
        (st.backup_dir / f"vault-20991231-23595{i}-manual.aegis").write_text(raw, encoding="utf-8")
    st.vault["tasks"].append(logic.new_task("x"))
    st.save()
    dst = st.snapshot("manual")
    assert dst is not None and dst.exists()
    st.unlock_backup_s = 3600
    st.vault["tasks"].append(logic.new_task("y"))
    st.save()
    assert st.snapshot("unlock", min_age_s=3600) is not None      # a future-stamped backup is not "just taken"


def test_restoring_the_oldest_backup_keeps_its_own_file(st):
    st.keep_backups = 3
    made = []
    for i in range(3):
        st.vault["tasks"].append(logic.new_task(f"v{i}"))
        st.save()
        made.append(st.snapshot("manual"))
    st.restore_backup(made[0])
    assert made[0].exists()
    assert len(st.vault["tasks"]) == 1


def test_unchanged_vault_is_not_backed_up_again_and_again(st):
    first = st.snapshot("auto")
    assert st.snapshot("auto") == first and st.snapshot("unlock") == first
    assert len(st.list_backups()) == 1
    assert st.snapshot("manual") != first                     # a manual backup is always honoured
    assert len(st.list_backups()) == 2


def test_unlock_reports_a_friendly_backup_problem(tmp_path):
    s = VaultStore(tmp_path / "d")
    s.create(PW1)
    s.lock()
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    s.set_backup_dir(blocker / "sub")
    s.unlock_backup_s = 3600
    s.unlock(PW1)
    assert s.is_unlocked and s.backup_error and str(tmp_path) not in s.backup_error


def test_unreadable_backup_folder_lists_nothing_instead_of_crashing(st, monkeypatch):
    monkeypatch.setattr(Path, "glob", lambda self, pat: (_ for _ in ()).throw(PermissionError("denied")))
    assert st.list_backups() == []


def test_long_export_names_do_not_break_the_temp_file(tmp_path):
    from aegis_desktop.core.store import _atomic_write
    name = "پشتیبان-" + "a" * 200 + ".aegis"
    _atomic_write(tmp_path / name, "{}")
    assert (tmp_path / name).read_text() == "{}"
    assert not list(tmp_path.glob("*.tmp"))


# ------------------------------------------------------------------------- logic ---
def test_recurring_multiday_task_keeps_its_span_and_kind():
    today = dt.date(2026, 3, 1)
    v = {"tasks": []}
    base = logic.new_task("workshop", due=jalali.date_to_due(today), dueEnd=jalali.date_to_due(today + dt.timedelta(days=2)),
                          rep="weekly", kind="event")
    v["tasks"].append(base)
    logic.materialize_series(v, base)
    later = [t for t in v["tasks"] if t is not base]
    assert later and all(t.get("kind") == "event" for t in later)
    for t in later:
        assert (jalali.due_to_date(t["dueEnd"]) - jalali.due_to_date(t["due"])).days == 2


def test_goal_progress_survives_archiving():
    v = {"goals": [{"id": "g1", "ms": []}], "archive": [], "tasks": []}
    old = jalali.date_to_due(dt.date.today() - dt.timedelta(days=200))
    for i in range(9):
        v["tasks"].append(logic.new_task(f"d{i}", goalId="g1", done=True, due=old, doneAt="2020-01-01T00:00:00.000Z"))
    v["tasks"].append(logic.new_task("open", goalId="g1"))
    before = logic.goal_progress(v, v["goals"][0])
    assert before == 90
    assert logic.archive_old_tasks(v, days=90) > 0
    assert logic.goal_progress(v, v["goals"][0]) == 90
    assert logic.goal_progress_map(v)["g1"] == 90


def test_calendar_never_stores_or_exports_24_00():
    from aegis_desktop.ui.calendar_kit import hm, hm_end
    assert hm_end(1440) == "23:59" and hm_end(600) == "10:00" and hm(1440) == "24:00"
    d = jalali.date_to_due(dt.date(2026, 5, 5))
    bad = logic.new_task("late", due=d, timeFrom="22:00", timeTo="24:00")
    ics = logic.export_ics({"tasks": [bad]})
    assert "T240000" not in ics and "DTSTART:20260505T220000" in ics


def test_midnight_words():
    T = dt.date(2026, 4, 1)
    q = parse_quick("فردا ۱۲ شب جلسه", T)
    assert q.time_from == "23:59" and jalali.due_to_date(q.due) == T + dt.timedelta(days=1)
    assert parse_quick("ساعت ۱۲ ظهر ناهار", T).time_from == "12:00"
    assert parse_quick("۹ شب فیلم", T).time_from == "21:00"


# --------------------------------------------------------------------------- GUI ---
def test_palette_recents_never_put_titles_on_disk(win):
    setup_vault(win)
    t = logic.new_task("Confidential: acquisition of Acme Corp")
    win.store.vault["tasks"].append(t)
    n = logic.new_note("Secret memo", "body")
    win.store.vault["notes"].append(n)
    win.changed()
    pal = dialogs_palette(win)
    pal._remember("task", t["id"], t["title"], "")
    pal._remember("note", n["id"], n["title"], "")
    pal._remember("page", "tasks", "تسک‌ها", "")
    pal.reject()
    disk = win.prefs_path.read_text(encoding="utf-8")
    assert "Acme" not in disk and "Secret" not in disk and "tasks" in disk
    assert [e[0] for e in win.recent][:2] == ["page", "note"]
    win.lock()
    assert all(e[0] in ("page", "cmd") for e in win.recent)


def test_old_prefs_with_titles_are_scrubbed_on_load(win):
    win.prefs_path.parent.mkdir(parents=True, exist_ok=True)
    win.prefs_path.write_text(json.dumps({"palette_recent": [["task", "t1", "Acme takeover", ""], ["page", "today", "امروز", ""]]}),
                              encoding="utf-8")
    prefs = win._load_prefs()
    assert prefs["palette_recent"] == [["page", "today", "امروز", ""]]
    assert "Acme" not in win.prefs_path.read_text(encoding="utf-8")


def dialogs_palette(win):
    from aegis_desktop.ui.main_window import Palette
    return Palette(win)


def test_notes_editor_rebinds_after_a_backup_is_restored(win):
    setup_vault(win)
    n = logic.new_note("T", "old text")
    win.store.vault["notes"].append(n)
    win.changed()
    win.store.save()
    snap = win.store.snapshot("manual")
    n["body"] = "edited later"
    n["html"] = ""
    win.changed()
    win.show_page("notes")
    page = win.pages["notes"]
    page.select_id(n["id"])
    win.store.restore_backup(snap)
    win.vault_replaced()
    live = next(x for x in win.store.vault["notes"] if x["id"] == n["id"])
    assert page.cur is live and "old text" in page.body.toPlainText()
    page.body.setPlainText("typed after restore")
    page._commit() if page._save_timer.isActive() else page._do_commit()
    assert "typed after restore" in logic.note_text(live)


def test_replacing_the_vault_withdraws_the_pending_undo(win):
    setup_vault(win)
    t = win.store.vault["tasks"][0]
    win.changed("x", undo=win.snapshot([t["id"]]))
    assert win._undo is not None
    win.vault_replaced()
    assert win._undo is None


def test_lock_closes_open_dialogs(win):
    setup_vault(win)
    d = dialogs.TaskDialog(win, win.store.vault, None, None, None)
    d.show()
    QTest.qWait(30)
    assert d.isVisible()
    win.lock()
    assert not d.isVisible() and not win.store.is_unlocked


def test_automatic_lock_does_not_nag_when_saving_fails(win, monkeypatch):
    setup_vault(win)
    win.store.dirty = True
    monkeypatch.setattr(VaultStore, "save", lambda self: (_ for _ in ()).throw(OSError("locked by antivirus")))
    monkeypatch.setattr(dialogs, "warn", lambda *a, **k: pytest.fail("a modal warning for an automatic lock"))
    win.lock(auto=True)
    assert win.store.is_unlocked and "قفل خودکار" in win.status_lb.text()
    win.store.dirty = False


def test_closing_with_a_failed_final_save_asks_first(win, monkeypatch):
    setup_vault(win)
    win.store.dirty = True
    monkeypatch.setattr(VaultStore, "save", lambda self: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: False)              # the user cancels: stay open
    ev = __import__("PyQt6.QtGui", fromlist=["QCloseEvent"]).QCloseEvent()
    win.closeEvent(ev)
    assert not ev.isAccepted() and win.isVisible()
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)               # "close without saving"
    ev2 = __import__("PyQt6.QtGui", fromlist=["QCloseEvent"]).QCloseEvent()
    win.closeEvent(ev2)
    assert ev2.isAccepted()
    win.store.dirty = False


def test_keep_spinner_does_not_fire_while_typing(win):
    setup_vault(win)
    sp = win.pages["settings"]
    assert sp.b_keep.keyboardTracking() is False


def test_secret_leaves_the_clipboard_after_a_while(win):
    dialogs._copy_secret("AEGIS-TEST-KEY", seconds=0)
    assert QApplication.clipboard().text() == "AEGIS-TEST-KEY"
    QTest.qWait(80)
    QApplication.processEvents()
    assert QApplication.clipboard().text() == ""
    QApplication.clipboard().setText("something else")
    dialogs._copy_secret("AEGIS-OTHER", seconds=0)
    QApplication.clipboard().setText("the user copied this meanwhile")
    QTest.qWait(80)
    assert QApplication.clipboard().text() == "the user copied this meanwhile"


def test_reminders_survive_foreign_clock_values(win):
    setup_vault(win)
    today = jalali.date_to_due(dt.date.today())
    for bad in ("24:00", "99:99", "7:5", "ab:cd"):
        win.store.vault["tasks"].append(logic.new_task("r", due=today, timeFrom=bad))
    win._reminders()


def test_locking_with_a_pending_search_debounce_raises_nothing(win, monkeypatch):
    setup_vault(win)
    errors = []
    monkeypatch.setattr("sys.excepthook", lambda *a: errors.append(a))
    win.show_page("notes")
    win.show_page("tasks")
    win.pages["notes"].q.setText("ابر")
    win.pages["tasks"].q.setText("کار")
    win.lock()
    QTest.qWait(400)
    QApplication.processEvents()
    assert not errors
    assert not win.pages["notes"]._q_timer.isActive() and not win.pages["tasks"]._q_timer.isActive()
    win.pages["notes"]._fill_list()
    win.pages["tasks"].refresh()


def test_ids_stay_unique_in_a_burst():
    from aegis_desktop.core.store import uid
    ids = [uid("t") for _ in range(60000)]
    assert len(set(ids)) == len(ids)


def test_normalize_heals_duplicate_ids_and_is_idempotent():
    from aegis_desktop.core.store import empty_vault, normalize
    v = empty_vault()
    a, b, c = logic.new_task("a"), logic.new_task("b"), logic.new_task("c")
    b["id"] = c["id"] = a["id"]
    v["tasks"] = [a, b, c]
    g1, g2 = logic.new_goal("g"), logic.new_goal("h")
    g2["id"] = g1["id"]
    v["goals"] = [g1, g2]
    out = normalize(v)
    ids = [t["id"] for t in out["tasks"]]
    assert len(set(ids)) == 3 and ids[0] == a["id"]
    assert [t["title"] for t in out["tasks"]] == ["a", "b", "c"]
    assert len({g["id"] for g in out["goals"]}) == 2
    assert [t["id"] for t in normalize(out)["tasks"]] == ids


def test_finished_entrance_animations_do_not_pile_up_on_long_lived_cards(win):
    from PyQt6.QtCore import QCoreApplication, QEvent, QVariantAnimation
    setup_vault(win)
    keys = ["today", "tasks", "kanban", "reports", "habits", "goals"]

    def settle(ms):
        QTest.qWait(ms)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()

    for k in keys * 2:
        win.show_page(k)
        settle(120)
    settle(1800)
    before = len(win.findChildren(QVariantAnimation))
    for k in keys * 5:
        win.show_page(k)
        settle(60)
    settle(2200)
    after = len(win.findChildren(QVariantAnimation))
    assert after - before <= 6, (before, after)


def test_finished_dialogs_are_freed_instead_of_piling_up_under_the_window(win, monkeypatch):
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QDialog
    from aegis_desktop.ui import micro
    from aegis_desktop.ui.main_window import Palette
    setup_vault(win)
    monkeypatch.setattr(micro.MotionDialog, "REAP_MS", 40)

    def settle(ms):
        QTest.qWait(ms)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        QApplication.processEvents()

    settle(100)
    before = len(win.findChildren(QDialog))
    for _ in range(6):
        for make in (lambda: dialogs.TaskDialog(win, win.store.vault, None, None, None), lambda: Palette(win),
                     lambda: dialogs.HabitDialog(win, None), lambda: dialogs.GoalDialog(win, None)):
            d = make()
            d.show()
            QTest.qWait(10)
            assert d.isVisible()
            d.reject()
            assert d.result() == 0                              # the answer is readable right after it closes
            del d
    settle(400)
    assert len(win.findChildren(QDialog)) - before <= 1


def test_a_dialog_that_is_shown_again_is_not_freed_under_the_caller(win, monkeypatch):
    from aegis_desktop.ui import micro
    setup_vault(win)
    monkeypatch.setattr(micro.MotionDialog, "REAP_MS", 30)
    d = dialogs.HabitDialog(win, None)
    d.show()
    d.reject()
    d.show()
    QTest.qWait(150)
    assert d.isVisible()
    d.reject()


def test_context_menus_do_not_stay_behind_after_they_close(win):
    from PyQt6.QtCore import QCoreApplication, QEvent, QPoint
    from PyQt6.QtWidgets import QMenu
    from aegis_desktop.ui import theme
    from aegis_desktop.ui.premium import pmenu
    setup_vault(win)
    pal = theme.PALETTES[win.theme]
    before = len(win.findChildren(QMenu))
    for _ in range(12):
        m = pmenu(win, pal, [("edit", "ویرایش", lambda: None, False), None, ("trash", "حذف", lambda: None, True)])
        m.popup(win.mapToGlobal(QPoint(40, 40)))
        QApplication.processEvents()
        m.hide()
        QApplication.processEvents()
    QTest.qWait(50)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QApplication.processEvents()
    assert len(win.findChildren(QMenu)) - before <= 1


def test_charts_survive_new_data_shorter_than_the_hovered_point(qtbot):
    from aegis_desktop.ui.charts import AreaChart, GroupedBars, HorizontalBars, Radar
    a = AreaChart()
    a.set_data([(str(i), i) for i in range(10)], second=list(range(10)))
    b = GroupedBars()
    b.set_data([(str(i), i, i) for i in range(10)])
    h = HorizontalBars()
    h.set_data([(str(i), i, i) for i in range(10)])
    r = Radar()
    r.set_data([str(i) for i in range(8)], list(range(8)))
    for w in (a, b, h, r):
        qtbot.addWidget(w)
        w.resize(420, 260)
        w.show()
        w._hover = 7
        w.p = 1.0
    a.set_data([("x", 1), ("y", 2)], second=[1, 2])
    b.set_data([("x", 1, 1)])
    h.set_data([("x", 1, 1)])
    r.set_data(["a", "b", "c"], [1, 2, 3])
    for w in (a, b, h, r):
        assert not w.grab().isNull()
        assert w._hover is None
