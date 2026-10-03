# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests: each reproduces a previously found defect."""
from __future__ import annotations

import datetime as dt

import pytest

from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import VaultStore, normalize
from test_gui import PW, setup_vault, win  # noqa: F401


# ------------------------------------------------------------------ core ---
def test_normalize_survives_oddly_typed_legacy_data():
    v = normalize({"journal": [{"date": 20240101}, 5, {"date": None, "body": "x"}],
                   "lists": [{"items": [1]}, {"items": "abc"}, "bad", {"items": [{"text": "a", "done": True}]}]})
    assert isinstance(v["notes"], list)


def test_local_date_never_raises_on_extreme_timestamps():
    for iso in ("9999-12-31T23:59:59Z", "0001-01-01T00:00:00Z"):
        logic._local_date(iso)            # must not raise (None or a date)


def test_report_survives_bad_pomo_log_keys():
    v = {"tasks": [], "settings": {"pomoLog": {1: 2, "2999-01-01": 5, "bad": 1}}}
    logic.report_summary(v, 7)


def test_report_counts_none_category():
    t = logic.new_task("a")
    t["cat"] = None
    t["done"], t["doneAt"] = True, logic.now_iso()
    r = logic.report_summary({"tasks": [t], "settings": {}}, 7)
    assert r is not None


def test_week_streak_not_broken_before_today_ends():
    today = dt.date.today()
    h = {"id": "h1", "name": "x", "log": {}}
    v = {"tasks": [], "habits": [h], "settings": {}}
    for i in range(1, 6):
        h["log"][(today - dt.timedelta(days=i)).isoformat()] = True
    s = logic.week_summary(v, today)
    assert s["streak"] == logic.habit_streak(h, today) == 5


def test_span_cap_is_the_same_in_index_and_tasks_on():
    t = logic.new_task("long", due=jalali.date_to_due(dt.date(2025, 1, 1)))
    t["dueEnd"] = jalali.date_to_due(dt.date(2026, 6, 1))
    v = {"tasks": [t]}
    day = dt.date(2026, 5, 1)
    assert (t in logic.tasks_on(v, day)) == (t in logic.build_day_index(v).get(day, []))


def test_ics_status_is_valid_for_events():
    t = logic.new_task("a", due=jalali.date_to_due(dt.date.today()))
    t["done"] = True
    out = logic.export_ics({"tasks": [t]})
    assert "STATUS:COMPLETED" not in out


def test_restore_from_trash_reports_failure():
    v = {"tasks": [], "trash": []}
    assert logic.restore_from_trash(v, {"kind": "alien", "item": {"id": "x"}}) is False
    assert logic.restore_from_trash(v, {"kind": "task", "item": {"id": "x", "title": "t"}}) is True


def test_nested_locked_calls_do_not_deadlock_with_a_pending_job(tmp_path, monkeypatch):
    import threading
    import aegis_desktop.core.store as st
    s = VaultStore(tmp_path / "d")
    s.create("Aaaa-bbbb-1234")
    real = st._atomic_write
    gate = threading.Event()
    monkeypatch.setattr(st, "_atomic_write", lambda *a, **k: (gate.wait(1), real(*a, **k))[1])
    s.dirty = True
    done = []

    def worker():
        with s._lock:                      # holds the lock, then calls a decorated method
            s.save_async  # noqa: B018
            s.snapshot("manual")
            done.append(1)
    s.dirty = True
    s.save_async()
    t = threading.Thread(target=worker)
    t.start()
    t.join(5)
    gate.set()
    s._drain()
    assert done == [1] and not t.is_alive()


# ------------------------------------------------------------------ gui ---
def test_deleting_the_open_note_disables_the_editor(win):
    setup_vault(win)
    win.show_page("notes")
    p = win.pages["notes"]
    p._new()
    assert p.title_in.isEnabled()
    p._delete(confirm=False)
    assert p.cur is None and not p.title_in.isEnabled() and not p.body.toPlainText()


def test_lock_unbinds_the_notes_editor(win):
    setup_vault(win)
    win.show_page("notes")
    p = win.pages["notes"]
    p._new()
    win.lock()
    assert not p.body.isEnabled() and not p.title_in.text()


def test_recovery_dialog_is_closed_by_auto_lock(win, qtbot):
    setup_vault(win)
    from aegis_desktop.ui import dialogs
    d = dialogs.RecoveryKeyDialog(win, "AEGIS-AAAAA-BBBBB-CCCCC-DDDDD-EEEEE")
    d.show()
    assert d.isVisible()
    win._close_dialogs()
    assert not d.isVisible()


def test_multi_day_task_moves_by_grab_offset(win):
    setup_vault(win)
    win.show_page("calendar")
    cp = win.pages["calendar"]
    d0 = dt.date.today() + dt.timedelta(days=2)
    t = logic.new_task("n", due=jalali.date_to_due(d0))
    t["dueEnd"] = jalali.date_to_due(d0 + dt.timedelta(days=4))
    win.store.vault["tasks"].append(t)
    cp._move(t["id"], d0 + dt.timedelta(days=2), d0 + dt.timedelta(days=2))     # grabbed day 3, dropped on day 3
    assert logic.task_date(t) == d0
    cp._move(t["id"], d0 + dt.timedelta(days=3), d0 + dt.timedelta(days=2))     # one day later
    assert logic.task_date(t) == d0 + dt.timedelta(days=1)
    assert jalali.due_to_date(t["dueEnd"]) == d0 + dt.timedelta(days=5)


def test_retime_same_day_keeps_multi_day_task_in_place(win):
    setup_vault(win)
    win.show_page("calendar")
    cp = win.pages["calendar"]
    d0 = dt.date.today() + dt.timedelta(days=2)
    t = logic.new_task("n", due=jalali.date_to_due(d0))
    t["dueEnd"] = jalali.date_to_due(d0 + dt.timedelta(days=4))
    win.store.vault["tasks"].append(t)
    cp._retime(t["id"], d0 + dt.timedelta(days=2), 600, 660, d0 + dt.timedelta(days=2))
    assert logic.task_date(t) == d0 and t["timeFrom"] == "10:00"


def test_quick_create_after_lock_is_harmless(win):
    setup_vault(win)
    win.show_page("calendar")
    cp = win.pages["calendar"]
    win.lock()
    cp._commit_new("x", dt.date.today(), None, None, None)       # no TypeError on a locked vault
    assert cp._by_id is None and cp._day_idx is None


def test_kanban_drop_on_done_creates_next_occurrence(win):
    setup_vault(win)
    win.show_page("kanban")
    kp = win.pages["kanban"]
    t = logic.new_task("r", rep="daily", due=jalali.date_to_due(dt.date.today()))
    win.store.vault["tasks"].append(t)
    logic.materialize_series(win.store.vault, t)
    before = len(win.store.vault["tasks"])
    t2 = max(win.store.vault["tasks"], key=lambda x: jalali.due_to_date(x["due"]))
    kp._drop(t["id"], "done")
    assert t["done"]
    assert len(win.store.vault["tasks"]) >= before


def test_pages_refresh_is_safe_while_locked(win):
    setup_vault(win)
    for k in ("today", "kanban", "habits", "goals", "reports", "trash", "settings"):
        win.show_page(k)
    win.lock()
    for _k, p in win.pages.built():
        p.refresh()


def test_open_backups_button_survives_a_bad_folder(win, tmp_path, monkeypatch):
    setup_vault(win)
    win.show_page("settings")
    sp = win.pages["settings"]
    blocker = tmp_path / "f"
    blocker.write_text("x")
    win.store.set_backup_dir(blocker / "sub")
    from aegis_desktop.ui import dialogs
    seen = []
    monkeypatch.setattr(dialogs, "warn", lambda *a, **k: seen.append(a))
    sp._open_backups()
    assert seen


# ------------------------------------------------------------------ additional regressions ---
def _wait_until(fn, qtbot, ms=4000):
    qtbot.waitUntil(fn, timeout=ms)


def test_failed_background_save_blocks_lock_instead_of_losing_data(win, qtbot, monkeypatch):
    setup_vault(win)
    import aegis_desktop.core.store as st
    from aegis_desktop.ui import dialogs
    win.BIG_VAULT = 0                                           # force the background path
    win.store.vault["tasks"].append(logic.new_task("مهم"))
    win.store.dirty = True
    monkeypatch.setattr(st, "_atomic_write", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    seen = []
    monkeypatch.setattr(dialogs, "warn", lambda *a, **k: seen.append(a))
    win._autosave()
    win.store.wait_idle()
    assert win.store.dirty                                      # the worker put it back
    win.lock()
    assert win.store.is_unlocked and seen                       # refused to lock: nothing was lost
    monkeypatch.undo()
    win.lock()
    assert not win.store.is_unlocked
    win.store.unlock(PW)
    assert any(t["title"] == "مهم" for t in win.store.vault["tasks"])


def test_background_autosave_persists(win, qtbot):
    setup_vault(win)
    win.BIG_VAULT = 0
    win.store.vault["tasks"].append(logic.new_task("پس‌زمینه"))
    win.store.dirty = True
    win._autosave()
    win.store.wait_idle()
    qtbot.wait(50)
    assert not win.store.dirty
    s2 = VaultStore(win.store.dir)
    s2.unlock(PW)
    assert any(t["title"] == "پس‌زمینه" for t in s2.vault["tasks"])


def test_undo_restores_series_skip_marker(win):
    setup_vault(win)
    from aegis_desktop.ui.undo import UndoRecord
    v = win.store.vault
    t = logic.new_task("r", rep="daily", due=jalali.date_to_due(dt.date.today()))
    v["tasks"].append(t)
    logic.materialize_series(v, t)
    victim = next(x for x in v["tasks"] if x.get("seriesId") and x is not t)
    rec = UndoRecord(v, [victim["id"]])
    logic.remove_task(win.store, victim)
    assert v["settings"]["seriesSkips"]
    rec.apply(v)
    assert not v["settings"].get("seriesSkips")
    assert any(x["id"] == victim["id"] for x in v["tasks"])


def test_whatsnew_not_shown_while_locked(win, monkeypatch):
    setup_vault(win)
    win.lock()
    from aegis_desktop.ui import whatsnew
    monkeypatch.setattr(whatsnew.WhatsNew, "exec", lambda self: (_ for _ in ()).throw(AssertionError("opened while locked")))
    win.show_whatsnew()


def test_lock_clears_toasts(win):
    setup_vault(win)
    win.notify("«عنوان محرمانه»", kind="info")
    win.lock()
    assert not win.toasts._toasts


# ------------------------------------------------------------------ quick-add parser ---
from aegis_desktop.core.nlp import parse_quick

_T = dt.date(2026, 10, 1)


@pytest.mark.parametrize("text,title", [
    ("خرید ۲ صبحانه", "خرید 2 صبحانه"),
    ("۳ شبکه نصب", "3 شبکه نصب"),
    ("۱۰ amir", "10 amir"),
])
def test_number_before_a_word_is_not_a_time(text, title):
    q = parse_quick(text, _T)
    assert q.time_from == "" and q.title == title


def test_night_hours_after_midnight():
    assert parse_quick("۱ شب جلسه", _T).time_from == "01:00"
    assert parse_quick("۱۰ شب جلسه", _T).time_from == "22:00"
    assert parse_quick("۴ عصر جلسه", _T).time_from == "16:00"


def test_invalid_minutes_are_not_a_time():
    assert parse_quick("۱۰:۷۵ x", _T).time_from == ""


def test_linking_words_inside_the_title_stay():
    assert parse_quick("فردا جلسه در دانشگاه", _T).title == "جلسه در دانشگاه"
    assert parse_quick("فردا روز معلم", _T).title == "روز معلم"
    assert parse_quick("برای فردا ساعت ۱۰ جلسه", _T).title == "جلسه"


def test_explicit_year_is_honoured():
    q = parse_quick("۱۵ مهر ۱۴۰۶ آزمون", _T)
    assert q.due["jy"] == 1406 and q.title == "آزمون"


def test_huge_day_count_is_not_misread():
    assert parse_quick("x 99999 روز دیگر", _T).due is None


# ------------------------------------------------------------------ small widgets ---
def test_radar_pads_short_values(qtbot):
    from aegis_desktop.ui.charts import Radar
    r = Radar()
    qtbot.addWidget(r)
    r.resize(300, 300)
    r.set_data(["a", "b", "c", "d"], [1, 2])
    r.grab()
    assert len(r.values) == 4


def test_task_table_clear_resets_group_bands(win):
    setup_vault(win)
    win.show_page("tasks")
    tp = win.pages["tasks"]
    tbl = tp.table
    tbl.clear()
    m = tbl.model()
    assert not m.rows and not m.starts and not m.gkeys and not m.gcount
