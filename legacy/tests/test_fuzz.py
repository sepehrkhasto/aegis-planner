# SPDX-License-Identifier: GPL-3.0-or-later
"""Robustness: a vault written by another client, an older version or a hand edit must never crash the app.

Every entity field is randomly type-confused (None, numbers, lists, dicts, huge / odd strings, half dates...), the vault
goes through ``normalize`` exactly like a file being opened, and then every domain function the UI calls runs on it.
Deterministic seeds, so a failure is reproducible.
"""
import copy
import datetime as dt
import json
import random

import pytest

from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import TRASH_DAYS, VaultStore, empty_vault, normalize

JUNK = [None, 0, -1, 7, 3.5, True, False, "", "x", "‌", "٪۱", "a" * 5000, "<script>", "\x00﻿", [], [1, "a", None],
        [{"text": 3}], {}, {"a": 1}, {"jy": "x"}, {"jy": 1404, "jm": 13, "jd": 1}, {"jy": 1404, "jm": 7, "jd": 31},
        {"jy": 1403, "jm": 12, "jd": 30}, {"jy": 1404, "jm": 12, "jd": 30}, "2026-02-30", "not-a-date", float("nan")]


def _task(r: random.Random, i: int) -> dict:
    t = logic.new_task(f"تسک {i}", due=jalali.date_to_due(dt.date(2026, 9, 1) + dt.timedelta(days=r.randint(-60, 60))),
                       tags=["کار", "#x"], subs=[{"text": "یک", "done": False}], rep=r.choice(["none", "daily", "weekly"]))
    if r.random() < 0.5:
        t.update(done=True, doneAt="2026-09-10T08:00:00.000Z", status="done")
    return t


def _vault(seed: int) -> dict:
    r = random.Random(seed)
    v = empty_vault()
    v["tasks"] = [_task(r, i) for i in range(12)]
    v["archive"] = [_task(r, 100 + i) for i in range(3)]
    v["notes"] = [logic.new_note(f"یادداشت {i}", "متن\n==مهم==\n- [ ] کار", folder=r.choice(["", "کار"])) for i in range(5)]
    v["habits"] = [logic.new_habit(f"عادت {i}", r.randint(1, 7)) for i in range(4)]
    for h in v["habits"]:
        for k in range(20):
            h["log"][(dt.date(2026, 9, 29) - dt.timedelta(days=r.randint(0, 40))).isoformat()] = {"d": 1}
    v["goals"] = [logic.new_goal(f"هدف {i}", ms=[{"text": "م", "done": bool(k % 2)} for k in range(3)],
                                 deadline=jalali.date_to_due(dt.date(2026, 12, 1))) for i in range(3)]
    v["tasks"][0]["goalId"] = v["goals"][0]["id"]
    v["settings"] = {"pomoLog": {"2026-09-28": 3}}
    v["trash"] = [{"kind": "task", "item": _task(r, 999), "at": "2026-09-20T10:00:00.000Z"}]
    # --- corrupt: every field of a random subset of entities gets a random junk value
    for key in ("tasks", "archive", "notes", "habits", "goals"):
        for ent in v[key]:
            for f in list(ent):
                if r.random() < 0.35:
                    ent[f] = copy.deepcopy(r.choice(JUNK))
    for f in ("settings", "wellness", "trash", "templates"):
        if r.random() < 0.3:
            v[f] = copy.deepcopy(r.choice(JUNK))
    if r.random() < 0.3:
        v["settings"] = {"pomoLog": copy.deepcopy(r.choice(JUNK))}
    if r.random() < 0.2:
        v["tasks"].append(copy.deepcopy(r.choice(JUNK)))                  # not even an object
    return v


def _exercise(v: dict) -> None:
    today = dt.date(2026, 9, 29)
    logic.build_day_index(v)
    for d in (today, today - dt.timedelta(days=40)):
        logic.tasks_on(v, d)
    for st in ("open", "done", "all"):
        logic.filter_tasks(v, status=st, q="ک", tag="کار")
    logic.all_tags(v)
    for x in v["tasks"]:
        logic.task_date(x); logic.is_overdue(x, today); logic.kanban_status(x)
    for h in v["habits"]:
        logic.habit_stats(h, today); logic.habit_streak(h, today); logic.habit_goal(h)
    logic.goal_progress_map(v)
    for g in v["goals"]:
        logic.goal_progress(v, g); logic.goal_days_left(g, today)
    logic.note_folders(v)
    logic.notes_to_markdown(v["notes"])
    for n in v["notes"]:
        logic.note_text(n)
    logic.export_ics(v)
    logic.report_summary(v, 30, today)
    logic.weekly_flow(v, 8, today)
    logic.weekday_done(v, 30, today)
    logic.weekday_compare(v, 30, today)
    logic.daily_metrics(v, 30, today)
    logic.priority_open(v)
    logic.scores(v, 30, today)
    logic.category_progress(v, 30, today)
    logic.activity_days(v, today - dt.timedelta(days=60), today)
    logic.archive_old_tasks(copy.deepcopy(v), 30)
    logic.pomo_add(copy.deepcopy(v), today)
    w = copy.deepcopy(v)                                                   # mutations the UI performs
    for x in w["tasks"][:6]:
        logic.set_done(w, x, True)
        logic.set_done(w, x, False)
        logic.set_status(x, "doing")
    for e in list(w["trash"]):
        logic.restore_from_trash(w, e)
    for h in w["habits"]:
        logic.habit_toggle(h, today)
    json.dumps(w, ensure_ascii=False)                                      # still serialisable


@pytest.mark.parametrize("seed", range(160))
def test_corrupted_vaults_never_crash_domain_logic(seed):
    v = normalize(_vault(seed))
    _exercise(v)


@pytest.mark.parametrize("seed", range(40))
def test_normalize_is_idempotent_and_keeps_shape(seed):
    once = normalize(_vault(seed))
    twice = normalize(copy.deepcopy(once))
    assert json.dumps(once, sort_keys=True, default=str) == json.dumps(twice, sort_keys=True, default=str)
    for k in ("tasks", "notes", "habits", "goals", "archive", "trash"):
        assert isinstance(once[k], list) and all(isinstance(x, dict) for x in once[k])
    ids = [x["id"] for x in once["tasks"]]
    assert all(isinstance(i, str) and i for i in ids)


def test_normalized_strings_and_lists_are_clean():
    """Fields the UI renders as text / iterates as lists always have the right element types after normalize."""
    for seed in range(80):
        v = normalize(_vault(seed))
        for x in v["tasks"] + v["archive"]:
            assert all(isinstance(t, str) for t in x.get("tags", []))
            assert all(isinstance(s.get("text", ""), str) for s in x.get("subs", []))
            for f in ("cat", "pr", "rep", "status", "kind", "timeFrom", "timeTo", "color", "goalId", "link"):
                assert x.get(f) is None or isinstance(x[f], str), (f, x[f])
        for n in v["notes"]:
            assert isinstance(n.get("folder", ""), str)
        for g in v["goals"]:
            assert all(isinstance(m.get("text", ""), str) for m in g["ms"])
        assert isinstance(v["settings"].get("pomoLog", {}), dict)


# ---- Jalali calendar edge cases ------------------------------------------------------------------------------------
def test_jalali_month_lengths_and_leap_years():
    for jy in (1399, 1403, 1408):                                          # 33-year cycle leap years around now
        assert jalali.is_leap(jy) and jalali.month_length(jy, 12) == 30
    for jy in (1400, 1401, 1402, 1404, 1405):
        assert not jalali.is_leap(jy) and jalali.month_length(jy, 12) == 29
    assert [jalali.month_length(1404, m) for m in range(1, 13)] == [31] * 6 + [30] * 5 + [29]


def test_impossible_jalali_dates_are_rejected_not_rolled_over():
    """31 Mehr or 30 Esfand of a common year does not exist; it must not silently become the next day."""
    assert jalali.due_to_date({"jy": 1404, "jm": 7, "jd": 31}) is None
    assert jalali.due_to_date({"jy": 1404, "jm": 12, "jd": 30}) is None
    assert jalali.due_to_date({"jy": 1403, "jm": 12, "jd": 30}) == dt.date(2025, 3, 20)
    assert jalali.due_to_date({"jy": 1404, "jm": 0, "jd": 5}) is None
    v = normalize({"tasks": [{"id": "a", "title": "x", "due": {"jy": 1404, "jm": 7, "jd": 31}}]})
    assert v["tasks"][0]["due"] is None                                    # normalize drops it instead


def test_nowruz_and_year_boundaries_round_trip():
    for g in (dt.date(2025, 3, 20), dt.date(2025, 3, 21), dt.date(2026, 3, 20), dt.date(2026, 3, 21), dt.date(2024, 12, 31)):
        assert jalali.due_to_date(jalali.date_to_due(g)) == g


# ---- recurrence --------------------------------------------------------------------------------------------------------
def test_daily_recurrence_ticked_repeatedly_never_duplicates():
    v = empty_vault()
    t = logic.new_task("روزانه", rep="daily", due=jalali.date_to_due(dt.date(2026, 9, 29)))
    v["tasks"].append(t)
    for _ in range(5):
        logic.set_done(v, t, True)
        logic.set_done(v, t, False)
    logic.set_done(v, t, True)
    follow = [x for x in v["tasks"] if x is not t]
    assert len(follow) == 1 and logic.task_date(follow[0]) == dt.date(2026, 9, 30)


def test_weekly_series_materializes_once_per_date():
    v = empty_vault()
    t = logic.new_task("هفتگی", rep="weekly", due=jalali.date_to_due(dt.date(2026, 9, 29)))
    v["tasks"].append(t)
    n1 = logic.materialize_series(v, t)
    n2 = logic.materialize_series(v, t)
    assert n1 == 8 and n2 == 0                                              # 8 more weeks; the base keeps its own date
    dates = [logic.task_date(x) for x in v["tasks"] if x.get("seriesId") == t["seriesId"] and x is not t]
    assert len(dates) == len(set(dates))


def test_multiday_task_keeps_its_span_when_it_repeats():
    v = empty_vault()
    t = logic.new_task("سفر", rep="weekly", due=jalali.date_to_due(dt.date(2026, 9, 29)),
                       dueEnd=jalali.date_to_due(dt.date(2026, 10, 1)))
    v["tasks"].append(t)
    logic.set_done(v, t, True)
    nxt = [x for x in v["tasks"] if x is not t][0]
    assert (jalali.due_to_date(nxt["dueEnd"]) - logic.task_date(nxt)).days == 2


# ---- trash -----------------------------------------------------------------------------------------------------------------
def test_trash_purges_after_retention_and_survives_bad_timestamps(tmp_path):
    s = VaultStore(tmp_path / "d"); s.create("correct horse battery 42")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=TRASH_DAYS + 1)).isoformat().replace("+00:00", "Z")
    s.vault["trash"] = [{"kind": "task", "item": {"id": "a"}, "at": old},
                        {"kind": "task", "item": {"id": "b"}, "at": "garbage"},
                        {"kind": "task", "item": {"id": "c"}}]
    s._purge_trash()
    assert [t["item"]["id"] for t in s.vault["trash"]] == ["b", "c"]      # unknown age: kept (never lose data)


def test_restore_twice_keeps_ids_unique():
    v = empty_vault()
    t = logic.new_task("x"); v["tasks"].append(t)
    v["trash"] = [{"kind": "task", "item": copy.deepcopy(t), "at": "2026-09-01T00:00:00Z"}]
    logic.restore_from_trash(v, v["trash"][0])
    ids = [x["id"] for x in v["tasks"]]
    assert len(ids) == 2 and len(set(ids)) == 2 and v["trash"] == []


# ---- search folding --------------------------------------------------------------------------------------------------
def test_search_matches_across_keyboards_and_digit_systems():
    v = empty_vault()
    v["tasks"] = [logic.new_task("كار شماره 12"), logic.new_task("تمرین آب"), logic.new_task("جلسه ۳")]
    titles = lambda q: [x["title"] for x in logic.filter_tasks(v, status="all", q=q)]   # noqa: E731
    assert titles("کار") == ["كار شماره 12"]               # Persian kaf finds Arabic kaf
    assert titles("شماره ۱۲") == ["كار شماره 12"]          # Persian digits find ASCII digits
    assert titles("اب") == ["تمرین آب"]
    assert titles("3") == ["جلسه ۳"]
    assert len(logic.fold("آزمون ۱۲۳ ABC")) == len("آزمون ۱۲۳ ABC")    # 1:1 - highlight positions stay valid
