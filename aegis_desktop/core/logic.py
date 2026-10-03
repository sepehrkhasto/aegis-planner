# SPDX-License-Identifier: GPL-3.0-or-later
"""Domain logic over the vault dict (tasks, habits, goals, notes, reports).

Pure functions - no Qt, no I/O - so they are unit-testable headless. Data shapes
match the web app exactly so vaults round-trip between both apps.
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache
from typing import Iterable

from . import jalali
from .store import now_iso, uid

CATEGORIES = [("study", "درس"), ("work", "کار"), ("sport", "ورزش"),
              ("personal", "شخصی"), ("exam", "امتحان"), ("other", "سایر")]
PRIORITIES = [("high", "زیاد"), ("normal", "معمولی"), ("low", "کم")]
HORIZONS = [("short", "کوتاه‌مدت"), ("long", "بلندمدت")]
REPEATS = [("none", "بدون تکرار"), ("daily", "روزانه"), ("weekly", "هفتگی")]
GOAL_HORIZONS = [("month", "ماهانه"), ("year", "سالانه"), ("long", "بلندمدت")]
KANBAN_COLS = [("todo", "انجام‌نشده"), ("doing", "در حال انجام"), ("done", "انجام‌شده")]
CAT_LABEL = dict(CATEGORIES)
PR_LABEL = dict(PRIORITIES)


_FOLD = str.maketrans({**{chr(0x06F0 + i): str(i) for i in range(10)},          # ۰-۹ Persian digits
                       **{chr(0x0660 + i): str(i) for i in range(10)},          # ٠-٩ Arabic-Indic digits
                       "\u064A": "\u06CC", "\u0649": "\u06CC",                 # Arabic yeh / alef maksura -> Persian yeh
                       "\u0643": "\u06A9", "\u0629": "\u0647", "\u06C0": "\u0647",  # Arabic kaf -> keheh, teh marbuta/heh-yeh -> heh
                       "\u0623": "\u0627", "\u0625": "\u0627", "\u0622": "\u0627"})  # hamza / madda alef -> alef


def fold(s: str) -> str:
    """Search key: the same text typed on a Persian, Arabic or English keyboard compares equal (۱۲ = 12,
    كار = کار, آب = اب). One character in, one out - match positions stay valid for highlighting."""
    return (s or "").translate(_FOLD).lower()


def iso_day(d: dt.date) -> str:
    return d.isoformat()


# ------------------------------------------------------------------ tasks ---
def new_task(title: str, **kw) -> dict:
    t = {"id": uid("t"), "title": title, "notes": "", "cat": "personal", "pr": "normal",
         "hz": "short", "tags": [], "rep": "none", "link": "", "color": "c0", "goalId": "",
         "subs": [], "due": None, "done": False, "createdAt": now_iso(), "doneAt": None,
         "timeFrom": "", "timeTo": "", "dueEnd": None}
    t.update(kw)
    return t


def is_event(x: dict) -> bool:
    return x.get("kind") == "event"


def task_date(x: dict) -> dt.date | None:
    return jalali.due_to_date(x.get("due"))


def is_overdue(x: dict, today: dt.date | None = None) -> bool:
    d = task_date(x)
    return bool(d and not x.get("done") and d < (today or dt.date.today()))


MAX_SPAN_DAYS = 800          # a multi-day task never spans more than this in any view (same cap everywhere)


def tasks_on(v: dict, day: dt.date) -> list[dict]:
    """Tasks whose due date, or multi-day range [due..dueEnd], covers ``day``."""
    out = []
    for x in v.get("tasks", []):
        d0 = task_date(x)
        if not d0:
            continue
        d1 = jalali.due_to_date(x.get("dueEnd")) or d0
        if d0 <= day <= min(max(d0, d1), d0 + dt.timedelta(days=MAX_SPAN_DAYS)):          # an end before the start is treated as a single day
            out.append(x)
    out.sort(key=lambda x: (x.get("timeFrom") or "99:99", x.get("title", "")))
    return out


def build_day_index(v: dict, max_span: int = MAX_SPAN_DAYS) -> dict[dt.date, list[dict]]:
    """date -> tasks covering that day, built in ONE pass (O(N + span)). Use this when many days are queried
    (month/week grids); tasks_on() rescans every task per call."""
    idx: dict[dt.date, list[dict]] = {}
    for x in v.get("tasks", []):
        d0 = task_date(x)
        if not d0:
            continue
        d1 = jalali.due_to_date(x.get("dueEnd")) or d0
        span = min((d1 - d0).days, max_span) if d1 >= d0 else 0
        for i in range(span + 1):
            idx.setdefault(d0 + dt.timedelta(days=i), []).append(x)
    for lst in idx.values():
        lst.sort(key=lambda x: (x.get("timeFrom") or "99:99", x.get("title", "")))
    return idx


def _next_due(due: dict, rep: str) -> dict | None:
    base = jalali.due_to_date(due)
    if base is None:
        return None
    return jalali.date_to_due(base + dt.timedelta(days=7 if rep == "weekly" else 1))


def _due_key(due) -> tuple | None:
    if not isinstance(due, dict):
        return None
    return (due.get("jy"), due.get("jm"), due.get("jd"))


def _skip_set(v: dict, sid: str) -> set:
    """Dates of a series the user deleted on purpose; they must never be created again."""
    raw = (v.get("settings") or {}).get("seriesSkips", {})
    lst = raw.get(sid, []) if isinstance(raw, dict) else []
    return {tuple(k) for k in lst if isinstance(k, (list, tuple)) and len(k) == 3}


def _add_skip(v: dict, task: dict) -> None:
    sid, key = task.get("seriesId"), _due_key(task.get("due"))
    if not sid or not key or None in key:
        return
    sk = v.setdefault("settings", {}).setdefault("seriesSkips", {})
    if not isinstance(sk, dict):
        sk = v["settings"]["seriesSkips"] = {}
    lst = sk.setdefault(sid, [])
    if list(key) not in lst:
        lst.append(list(key))
    del lst[:-400]


def _prune_skips(v: dict, today: dt.date) -> None:
    sk = (v.get("settings") or {}).get("seriesSkips")
    if not isinstance(sk, dict):
        return
    live = {x.get("seriesId") for x in v.get("tasks", []) if x.get("seriesId")}
    for sid in list(sk):
        keep = []
        for k in sk[sid] if isinstance(sk[sid], list) else []:
            try:
                d = jalali.due_to_date({"jy": k[0], "jm": k[1], "jd": k[2]})
            except (TypeError, ValueError, IndexError, KeyError):
                d = None
            if d and d >= today:
                keep.append(k)
        if keep and sid in live:
            sk[sid] = keep
        else:
            del sk[sid]


def extend_series(v: dict, today: dt.date | None = None, max_new: int = 2000) -> int:
    """Rolling horizon: keep every ACTIVE recurring series (it still has an open occurrence) filled from today up to
    its horizon (daily 30 days, weekly 56 days). Idempotent; never re-creates a date that exists or was deleted."""
    today = today or dt.date.today()
    series: dict[str, list[dict]] = {}
    for x in v.get("tasks", []):
        if x.get("seriesId") and x.get("rep") in ("daily", "weekly") and jalali.due_to_date(x.get("due")):
            series.setdefault(x["seriesId"], []).append(x)
    made = 0
    for sid, items in series.items():
        if made >= max_new:
            break
        if all(x.get("done") for x in items):
            continue
        tpl = max(items, key=lambda x: jalali.due_to_date(x["due"]))
        step = 7 if tpl["rep"] == "weekly" else 1
        end = today + dt.timedelta(days=56 if step == 7 else 30)
        t0 = jalali.due_to_date(tpl["due"])
        k = 0 if t0 >= today else -((t0 - today).days // step)        # first aligned date on or after today
        cursor = t0 + dt.timedelta(days=k * step)
        have = {_due_key(x["due"]) for x in items}
        skip = _skip_set(v, sid)
        span_end = jalali.due_to_date(tpl.get("dueEnd"))
        span = (span_end - t0) if span_end and span_end > t0 else None
        n = 0
        while cursor <= end and n < 400:
            due = jalali.date_to_due(cursor)
            key = _due_key(due)
            if key not in have and key not in skip:
                have.add(key)
                extra = {"kind": tpl["kind"]} if tpl.get("kind") else {}
                if span is not None:
                    extra["dueEnd"] = jalali.date_to_due(cursor + span)
                v["tasks"].append(new_task(
                    tpl["title"], notes=tpl.get("notes", ""), cat=tpl.get("cat", "personal"),
                    pr=tpl.get("pr", "normal"), hz=tpl.get("hz", "short"), tags=list(tpl.get("tags", [])),
                    rep=tpl["rep"], seriesId=sid, link=tpl.get("link", ""),
                    timeFrom=tpl.get("timeFrom", ""), timeTo=tpl.get("timeTo", ""),
                    color=tpl.get("color", "c0"), goalId=tpl.get("goalId", ""),
                    subs=[{"text": q["text"], "done": False} for q in tpl.get("subs", [])], due=due, **extra))
                n += 1
            cursor += dt.timedelta(days=step)
        made += n
    _prune_skips(v, today)
    return made


def materialize_series(v: dict, base: dict) -> int:
    """Create upcoming occurrences of a recurring task (daily: 30 days, weekly:
    8 weeks) as independent tasks sharing a seriesId. Deduplicates by date."""
    if not base.get("due"):
        return 0
    sid = base.setdefault("seriesId", uid("s"))
    step = 7 if base.get("rep") == "weekly" else 1
    horizon = 56 if base.get("rep") == "weekly" else 30
    tasks = v.setdefault("tasks", [])
    existing = {(x["due"].get("jy"), x["due"].get("jm"), x["due"].get("jd"))
                for x in tasks if x.get("seriesId") == sid and isinstance(x.get("due"), dict)} | _skip_set(v, sid)
    start = jalali.due_to_date(base["due"])
    if start is None:                                             # invalid stored date: nothing to repeat from
        return 0
    cursor, end, n = start, start + dt.timedelta(days=horizon), 0
    span_end = jalali.due_to_date(base.get("dueEnd"))
    span = (span_end - start) if span_end and span_end > start else None
    while cursor <= end and n < 400:
        due = jalali.date_to_due(cursor)
        key = (due["jy"], due["jm"], due["jd"])
        if key not in existing:
            existing.add(key)
            extra = {"kind": base["kind"]} if base.get("kind") else {}
            if span is not None:
                extra["dueEnd"] = jalali.date_to_due(cursor + span)
            tasks.append(new_task(
                base["title"], notes=base.get("notes", ""), cat=base.get("cat", "personal"),
                pr=base.get("pr", "normal"), hz=base.get("hz", "short"), tags=list(base.get("tags", [])),
                rep=base["rep"], seriesId=sid, link=base.get("link", ""),
                timeFrom=base.get("timeFrom", ""), timeTo=base.get("timeTo", ""),
                color=base.get("color", "c0"), goalId=base.get("goalId", ""),
                subs=[{"text": s["text"], "done": False} for s in base.get("subs", [])], due=due, **extra))
            n += 1
        cursor += dt.timedelta(days=step)
    return n


def set_done(v: dict, task: dict, done: bool) -> None:
    task["done"] = done
    task["doneAt"] = now_iso() if done else None
    if done:
        task["status"] = "done"
    elif task.get("status") == "done":
        task["status"] = "todo"
    rep = task.get("rep")
    if done and rep and rep != "none" and task.get("due"):
        if task.get("seriesId"):
            materialize_series(v, task)
        else:
            nxt = _next_due(task["due"], rep)
            # ticking / un-ticking / ticking again must not pile up duplicate follow-ups
            dup = nxt and any(not x.get("done") and x is not task and x.get("title") == task.get("title")
                              and x.get("due") == nxt and x.get("rep") == rep for x in v["tasks"])
            if nxt and not dup:
                copy = dict(task)
                copy.update(id=uid("t"), done=False, doneAt=None, status="todo", createdAt=now_iso(), due=nxt,
                            tags=list(task.get("tags") or []),
                            subs=[{"text": s["text"], "done": False} for s in task.get("subs", [])])
                end, d0, d1 = task.get("dueEnd"), task_date(task), jalali.due_to_date(nxt)
                if end and d0 and d1 and jalali.due_to_date(end):     # keep a multi-day span the same length
                    copy["dueEnd"] = jalali.date_to_due(jalali.due_to_date(end) + (d1 - d0))
                v["tasks"].append(copy)


def kanban_status(x: dict) -> str:
    st = x.get("status")
    if st in ("todo", "doing", "done"):
        return st
    return "done" if x.get("done") else "todo"


def set_status(task: dict, status: str) -> None:
    task["status"] = status
    if status == "done":
        if not task.get("done"):
            task["done"], task["doneAt"] = True, now_iso()
    elif task.get("done"):
        task["done"], task["doneAt"] = False, None


def filter_tasks(v: dict, *, status="open", cat="all", pr="all", q="", tag="") -> list[dict]:
    q = fold(q.strip())
    out = []
    for x in v.get("tasks", []):
        if status == "open" and x.get("done"):
            continue
        if status == "done" and not x.get("done"):
            continue
        if cat != "all" and x.get("cat") != cat:
            continue
        if pr != "all" and x.get("pr") != pr:
            continue
        if tag and tag not in (x.get("tags") or []):
            continue
        if q and q not in fold(x.get("title", "") + " " + x.get("notes", "") + " " + " ".join(x.get("tags") or [])):
            continue
        out.append(x)
    prio = {"high": 0, "normal": 1, "low": 2}

    def key(x):
        d = task_date(x)
        return (d is None, d or dt.date.max, prio.get(x.get("pr"), 1), x.get("title", ""))
    out.sort(key=key)
    return out


def remove_task(store, task: dict) -> None:
    _add_skip(store.vault, task)
    store.trash_put("task", task)
    store.vault["tasks"] = [x for x in store.vault["tasks"] if x["id"] != task["id"]]


def restore_from_trash(v: dict, entry: dict) -> bool:
    bucket = {"task": "tasks", "note": "notes", "habit": "habits", "goal": "goals"}.get(entry.get("kind"))
    item = entry.get("item")
    if not bucket or not isinstance(item, dict):
        return False
    items = v.setdefault(bucket, [])
    if any(x.get("id") == item.get("id") for x in items):     # e.g. the same item came back via a merge
        item["id"] = uid(bucket[0])                            # ids must stay unique: edits/deletes address by id
    items.append(item)
    if bucket == "tasks":
        sk = (v.get("settings") or {}).get("seriesSkips")
        key = _due_key(item.get("due"))
        if isinstance(sk, dict) and key and isinstance(sk.get(item.get("seriesId")), list):
            sk[item["seriesId"]] = [k for k in sk[item["seriesId"]] if tuple(k) != key]
    v["trash"] = [t for t in v.get("trash", []) if t is not entry]
    return True


def archive_old_tasks(v: dict, days: int = 90) -> int:
    cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - days * 86400
    keep, moved = [], 0
    for x in v.get("tasks", []):
        ts = None
        if x.get("done") and x.get("doneAt"):
            try:
                ts = dt.datetime.fromisoformat(x["doneAt"].replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
        if ts is not None and ts < cutoff:
            v.setdefault("archive", []).append(x)
            moved += 1
        else:
            keep.append(x)
    if moved:
        v["tasks"] = keep
    return moved


def all_tags(v: dict) -> list[str]:
    seen = {}
    for x in v.get("tasks", []):
        for t in x.get("tags") or []:
            seen[t] = seen.get(t, 0) + 1
    return sorted(seen, key=lambda t: (-seen[t], t))


# ----------------------------------------------------------------- habits ---
def habit_goal(h: dict) -> int:
    try:
        n = int(h.get("perWeek") or 7)
    except (TypeError, ValueError):
        n = 7
    return max(1, min(7, n))


def _week_count(h: dict, end: dt.date) -> int:
    log = h.get("log") or {}
    return sum(1 for i in range(7) if iso_day(end - dt.timedelta(days=i)) in log)


def habit_streak(h: dict, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    log = h.get("log") or {}
    goal = habit_goal(h)
    if goal >= 7:
        d = today
        if iso_day(d) not in log:
            d -= dt.timedelta(days=1)
        n = 0
        while iso_day(d) in log:
            n += 1
            d -= dt.timedelta(days=1)
        return n
    weeks, cur = 0, today
    if _week_count(h, cur) >= goal:
        weeks += 1
    cur -= dt.timedelta(days=7)
    while _week_count(h, cur) >= goal:
        weeks += 1
        cur -= dt.timedelta(days=7)
    return weeks


def habit_stats(h: dict, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    log = h.get("log") or {}

    def back(n):
        return sum(1 for i in range(n) if iso_day(today - dt.timedelta(days=i)) in log)
    best = run = 0
    prev = None
    for k in sorted(log):
        try:
            d = dt.date.fromisoformat(k)
        except ValueError:
            continue
        run = run + 1 if prev and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    goal = habit_goal(h)
    return {"week": back(7), "month": back(30), "best": best, "streak": habit_streak(h, today),
            "goal": goal, "daily": goal >= 7, "metWeek": back(7) >= goal}


def habit_toggle(h: dict, day: dt.date) -> bool:
    log = h.setdefault("log", {})
    k = iso_day(day)
    if k in log:
        del log[k]
        return False
    log[k] = {"d": 1}
    return True


def new_habit(name: str, per_week: int = 7) -> dict:
    return {"id": uid("h"), "name": name, "log": {}, "perWeek": per_week, "createdAt": now_iso()}


# ------------------------------------------------------------------ goals ---
def new_goal(title: str, **kw) -> dict:
    g = {"id": uid("g"), "title": title, "desc": "", "horizon": "year", "deadline": None,
         "ms": [], "createdAt": now_iso()}
    g.update(kw)
    return g


def _tasks_and_archive(v: dict):
    """Finished tasks move to the archive after a while; a goal's progress must still count them."""
    for key in ("tasks", "archive"):
        for x in v.get(key) or ():
            if isinstance(x, dict):
                yield x


def goal_progress(v: dict, g: dict) -> int | None:
    ms = g.get("ms") or []
    linked = [x for x in _tasks_and_archive(v) if x.get("goalId") == g["id"]]
    total = len(ms) + len(linked)
    if not total:
        return None
    done = sum(1 for m in ms if m.get("done")) + sum(1 for x in linked if x.get("done"))
    return round(done / total * 100)


def goal_progress_map(v: dict) -> dict[str, int | None]:
    """goal id -> progress %, for every goal in ONE pass over the tasks (goal_progress() rescans them per goal)."""
    tot: dict[str, int] = {}
    dn: dict[str, int] = {}
    for x in _tasks_and_archive(v):
        gid = x.get("goalId")
        if gid:
            tot[gid] = tot.get(gid, 0) + 1
            if x.get("done"):
                dn[gid] = dn.get(gid, 0) + 1
    out: dict[str, int | None] = {}
    for g in v.get("goals", []):
        ms = g.get("ms") or []
        total = len(ms) + tot.get(g["id"], 0)
        out[g["id"]] = round((sum(1 for m in ms if m.get("done")) + dn.get(g["id"], 0)) / total * 100) if total else None
    return out


def goal_days_left(g: dict, today: dt.date | None = None) -> int | None:
    d = jalali.due_to_date(g.get("deadline"))
    return None if d is None else (d - (today or dt.date.today())).days


# ------------------------------------------------------------------ notes ---
def new_note(title: str = "", body: str = "", folder: str = "") -> dict:
    return {"id": uid("n"), "title": title, "body": body, "html": _text_to_html(body),
            "folder": folder, "mood": None, "pinned": False,
            "createdAt": now_iso(), "updatedAt": now_iso()}


def _text_to_html(text: str) -> str:
    """Plain text -> the minimal HTML the web editor accepts (paragraphs only)."""
    if not text:
        return ""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return "".join(f"<p>{esc(line) if line else '<br>'}</p>" for line in text.split("\n"))


def html_to_text(html: str) -> str:
    s = re.sub(r"<\s*br\s*/?>", "\n", html or "", flags=re.I)
    s = re.sub(r"</\s*(p|div|li|h[1-6]|blockquote)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def set_note_body(note: dict, body: str) -> None:
    note["body"] = body
    note["html"] = _text_to_html(body)   # keep the web editor's copy in sync
    note["updatedAt"] = now_iso()


def note_text(n: dict) -> str:
    return n.get("body") or html_to_text(n.get("html", ""))


def note_full_text(n: dict) -> str:
    """Everything searchable in a note: the first text, the text blocks after it and the words inside flowcharts."""
    parts = [note_text(n)]
    for b in n.get("blocks") or ():
        if not isinstance(b, dict):
            continue
        if b.get("t") == "text" and isinstance(b.get("text"), str):
            parts.append(b["text"])
        elif b.get("t") == "flow":
            parts.extend(str(x.get("t", "")) for x in b.get("nodes") or () if isinstance(x, dict) and x.get("t"))
    return "\n".join(p for p in parts if p)


def note_block_counts(n: dict) -> tuple[int, int]:
    """(sketches, flowcharts) a note holds."""
    bl = [b for b in (n.get("blocks") or ()) if isinstance(b, dict)]
    return sum(1 for b in bl if b.get("t") == "ink"), sum(1 for b in bl if b.get("t") == "flow")


def notes_to_markdown(notes: Iterable[dict]) -> str:
    parts = []
    for n in notes:
        head = "## " + (n.get("title") or "بدون عنوان")
        if n.get("folder"):
            head += f"  \n*پوشه: {n['folder']}*"
        parts.append(head + "\n\n" + note_full_text(n) + "\n")
    return "\n---\n\n".join(parts)


def note_folders(v: dict) -> list[str]:
    return sorted({n.get("folder", "") for n in v.get("notes", []) if n.get("folder")})


# -------------------------------------------------------------------- ICS ---
def _ics_escape(s) -> str:
    s = str(s).replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line: str) -> str:
    """RFC 5545 3.1: content lines are folded at 75 octets (never inside a multi-byte UTF-8 character)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return "\r\n ".join(out)


def export_ics(v: dict) -> str:
    """Tasks/events with a due date -> iCalendar (opens in any calendar app)."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Aegis Planner Desktop//FA", "CALSCALE:GREGORIAN"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    hhmm = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
    for x in v.get("tasks", []):
        d = task_date(x)
        if not d:
            continue
        last = max(d, jalali.due_to_date(x.get("dueEnd")) or d)
        uid_ = re.sub(r"[^\w.-]", "_", str(x.get("id", "")))
        lines += ["BEGIN:VEVENT", f"UID:{uid_}@aegis-desktop", f"DTSTAMP:{stamp}",
                  f"SUMMARY:{_ics_escape(x.get('title', ''))}"]
        tf, tt = x.get("timeFrom"), x.get("timeTo")
        if isinstance(tf, str) and hhmm.fullmatch(tf):
            lines.append(f"DTSTART:{d:%Y%m%d}T{tf.replace(':', '')}00")
            if isinstance(tt, str) and hhmm.fullmatch(tt) and (last, tt) > (d, tf):     # never end before it starts
                lines.append(f"DTEND:{last:%Y%m%d}T{tt.replace(':', '')}00")
        else:
            end = last + dt.timedelta(days=1)
            lines += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
        if x.get("notes"):
            lines.append(f"DESCRIPTION:{_ics_escape(x['notes'])}")
        lines.append("STATUS:CONFIRMED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(ln) for ln in lines) + "\r\n"


# ---------------------------------------------------------------- reports ---
def report_summary(v: dict, days: int = 30, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    since = today - dt.timedelta(days=days - 1)
    done_per_day: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    total_done = 0
    for x in list(v.get("tasks", [])) + list(v.get("archive", [])):
        if not x.get("done") or not x.get("doneAt"):
            continue
        d = _done_date(x)
        if d is None:
            continue
        if since <= d <= today:                 # a window has two ends: "the previous period" must not count this one
            done_per_day[iso_day(d)] = done_per_day.get(iso_day(d), 0) + 1
            c = x.get("cat") or "other"
            by_cat[c] = by_cat.get(c, 0) + 1
            total_done += 1
    open_n = sum(1 for x in v.get("tasks", []) if not x.get("done"))
    overdue = sum(1 for x in v.get("tasks", []) if is_overdue(x, today))
    pomo = ((v.get("settings") or {}).get("pomoLog") or {})
    pomo_days = {k: n for k, n in pomo.items() if isinstance(k, str) and iso_day(since) <= k <= iso_day(today)}
    series = [(iso_day(since + dt.timedelta(days=i)),
               done_per_day.get(iso_day(since + dt.timedelta(days=i)), 0)) for i in range(days)]
    return {"total_done": total_done, "open": open_n, "overdue": overdue, "by_cat": by_cat,
            "series": series, "pomodoros": sum(int(n) for n in pomo_days.values() if isinstance(n, (int, float))),
            "days": days}


# ---------------------------------------------------------------- pomodoro ---
def pomo_add(v: dict, day: dt.date | None = None) -> int:
    log = v.setdefault("settings", {}).setdefault("pomoLog", {})
    k = iso_day(day or dt.date.today())
    try:
        log[k] = int(log.get(k, 0)) + 1
    except (TypeError, ValueError):
        log[k] = 1
    return log[k]


# ---------------------------------------------------------------- starter ---
def starter_content(v: dict) -> None:
    j = jalali.today_jalali()
    v["tasks"] = [
        new_task("به Aegis خوش آمدی — این تسک را تیک بزن!", pr="high", due=dict(j)),
        new_task("به «تقویم» برو و برای یک روز تسک بساز", due=dict(j)),
        new_task("از «تنظیمات» ظاهر برنامه را انتخاب کن", due=dict(j)),
        new_task("از «تنظیمات» یک پشتیبان رمزنگاری‌شده بگیر", due=dict(j)),
    ]
    n = new_note("شروع کار با Aegis",
                 "همه‌چیز فقط روی همین کامپیوتر و رمزنگاری‌شده ذخیره می‌شود؛ هیچ اتصال اینترنتی‌ای وجود ندارد.\n\n"
                 "• تسک‌ها: Ctrl+N\n• قفل فوری: Ctrl+L\n• جست‌وجوی سریع: Ctrl+K\n"
                 "• پشتیبان‌گیری: تنظیمات ← خروجی ولت")
    n["pinned"] = True
    v["notes"] = [n]


# ---------------------------------------------------------------- analytics ---
@lru_cache(maxsize=65536)
def _local_date(iso: str) -> dt.date | None:
    """ISO timestamp -> local calendar day. Memoised: analytics touch every task several times per refresh."""
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().date()
    except (ValueError, AttributeError, TypeError, OverflowError, OSError):
        return None


def _done_date(x: dict) -> dt.date | None:
    return _local_date(x.get("doneAt") or "")


def _created_date(x: dict) -> dt.date | None:
    return _local_date(x.get("createdAt") or "")


def _all_tasks(v: dict) -> list[dict]:
    return list(v.get("tasks", [])) + list(v.get("archive", []))


def weekly_flow(v: dict, weeks: int = 8, today: dt.date | None = None) -> list[tuple[str, int, int]]:
    """[(label, created, done)] for the last ``weeks`` Saturday-based weeks (oldest first)."""
    today = today or dt.date.today()
    start = today - dt.timedelta(days=jalali.weekday_index(today))
    first = start - dt.timedelta(weeks=weeks - 1)
    created, done = [0] * weeks, [0] * weeks
    for x in _all_tasks(v):                        # one pass, O(N) - not one pass per week
        d = _created_date(x)
        if d and first <= d <= start + dt.timedelta(days=6):
            created[(d - first).days // 7] += 1
        if x.get("done"):
            d = _done_date(x)
            if d and first <= d <= start + dt.timedelta(days=6):
                done[(d - first).days // 7] += 1
    out = []
    for w in range(weeks):
        j = jalali.date_to_due(first + dt.timedelta(weeks=w))
        out.append((f"{j['jd']} {jalali.MONTHS_FA[j['jm'] - 1]}", created[w], done[w]))
    return out


def weekday_done(v: dict, days: int = 30, today: dt.date | None = None) -> list[int]:
    """Done counts per weekday (Saturday first) inside the window."""
    today = today or dt.date.today()
    since = today - dt.timedelta(days=days - 1)
    res = [0] * 7
    for x in _all_tasks(v):
        if x.get("done") and (d := _done_date(x)) and since <= d <= today:
            res[jalali.weekday_index(d)] += 1
    return res


def weekday_compare(v: dict, days: int = 30, today: dt.date | None = None) -> tuple[list[int], list[int]]:
    """(this period, the period before it): done counts per weekday (Saturday first)."""
    today = today or dt.date.today()
    return weekday_done(v, days, today), weekday_done(v, days, today - dt.timedelta(days=days))


def daily_metrics(v: dict, days: int = 30, today: dt.date | None = None) -> dict[str, list[int]]:
    """Per-day series (oldest first, ``days`` long) for the sparklines: tasks done / created, habit ticks, pomodoros."""
    today = today or dt.date.today()
    since = today - dt.timedelta(days=days - 1)
    done, created, habits, pomo = ([0] * days for _ in range(4))
    for x in _all_tasks(v):                            # one pass over the tasks
        d = _created_date(x)
        if d and since <= d <= today:
            created[(d - since).days] += 1
        if x.get("done"):
            d = _done_date(x)
            if d and since <= d <= today:
                done[(d - since).days] += 1
    for h in v.get("habits", []):
        for k in (h.get("log") or {}):
            try:
                d = dt.date.fromisoformat(k)
            except ValueError:
                continue
            if since <= d <= today:
                habits[(d - since).days] += 1
    log = ((v.get("settings") or {}).get("pomoLog") or {})
    for i in range(days):
        try:
            pomo[i] = int(log.get(iso_day(since + dt.timedelta(days=i)), 0))
        except (TypeError, ValueError):
            pomo[i] = 0
    return {"done": done, "created": created, "habits": habits, "pomo": pomo}


def priority_open(v: dict) -> dict[str, int]:
    out = {"high": 0, "normal": 0, "low": 0}
    for x in v.get("tasks", []):
        if not x.get("done"):
            out[x.get("pr") if x.get("pr") in out else "normal"] += 1
    return out


def scores(v: dict, days: int = 30, today: dt.date | None = None) -> dict[str, int]:
    """0-100 health scores: completion, punctuality, habit consistency, goals."""
    today = today or dt.date.today()
    since = today - dt.timedelta(days=days - 1)
    tasks = _all_tasks(v)
    due_in = [x for x in tasks if (d := task_date(x)) and since <= d <= today]
    done_in = [x for x in due_in if x.get("done")]
    completion = round(len(done_in) / len(due_in) * 100) if due_in else 0
    on_time = [x for x in done_in if (dd := _done_date(x)) and dd <= (task_date(x) or today)]
    punctual = round(len(on_time) / len(done_in) * 100) if done_in else 0
    habits = v.get("habits", [])
    if habits:
        keys = {iso_day(since + dt.timedelta(days=i)) for i in range(days)}
        hits = sum(len(keys & set((h.get("log") or {}).keys())) for h in habits)
        habit = min(100, round(hits / (len(habits) * days) * 100))
    else:
        habit = 0
    gp = [p for g in v.get("goals", []) if (p := goal_progress(v, g)) is not None]
    goal = round(sum(gp) / len(gp)) if gp else 0
    return {"completion": completion, "punctual": punctual, "habit": habit, "goal": goal}


def category_progress(v: dict, days: int = 30, today: dt.date | None = None) -> list[tuple[str, int, int]]:
    """(category, done, total) for the tasks DUE inside the window - the completion rate per category.
    Busiest category first."""
    today = today or dt.date.today()
    since = today - dt.timedelta(days=days - 1)
    agg: dict[str, list[int]] = {}
    for x in _all_tasks(v):
        d = task_date(x)
        if d and since <= d <= today:
            a = agg.setdefault(x.get("cat") or "other", [0, 0])
            a[1] += 1
            if x.get("done"):
                a[0] += 1
    return sorted(((c, a[0], a[1]) for c, a in agg.items()), key=lambda t: (-t[2], t[0]))


def activity_days(v: dict, since: dt.date, until: dt.date) -> dict[dt.date, int]:
    """day -> how many things were finished that day (tasks done + habit ticks), for the activity calendar."""
    out: dict[dt.date, int] = {}
    for x in _all_tasks(v):
        if x.get("done"):
            d = _done_date(x)
            if d and since <= d <= until:
                out[d] = out.get(d, 0) + 1
    for h in v.get("habits", []):
        for k in (h.get("log") or {}):
            try:
                d = dt.date.fromisoformat(k)
            except ValueError:
                continue
            if since <= d <= until:
                out[d] = out.get(d, 0) + 1
    return out


# ------------------------------------------------------------- week seal ---
def week_summary(v: dict, today: dt.date | None = None) -> dict:
    """The last 7 days (today included) in numbers, for the «مهر هفته» card. Aggregates only - no task text.

    ``done_by_day`` is oldest first; ``score`` is the mean of the health scores that have data (0 when nothing is measurable);
    ``streak`` counts back from today over days with any activity (a task or a habit tick)."""
    today = today or dt.date.today()
    since = today - dt.timedelta(days=6)
    cur = report_summary(v, 7, today)
    prev = report_summary(v, 7, today - dt.timedelta(days=7))
    by_day = [n for _d, n in cur["series"]]
    sc = scores(v, 7, today)
    have = [x for x in sc.values() if x > 0]
    act = activity_days(v, today - dt.timedelta(days=60), today)
    streak = 0
    d = today if act.get(today) else today - dt.timedelta(days=1)      # a streak is not broken until a whole day passes
    while act.get(d):
        streak += 1
        d -= dt.timedelta(days=1)
    work = int((v.get("settings") or {}).get("pomoWork", 25) or 25)
    best = max(range(7), key=lambda i: by_day[i]) if any(by_day) else None
    delta = None if not prev["total_done"] else round((cur["total_done"] - prev["total_done"]) / prev["total_done"] * 100)
    score = round(sum(have) / len(have)) if have else 0
    return {"since": since, "until": today, "done": cur["total_done"], "prev_done": prev["total_done"], "delta_pct": delta,
            "done_by_day": by_day, "best_day": (since + dt.timedelta(days=best)) if best is not None else None,
            "best_count": by_day[best] if best is not None else 0, "pomodoros": cur["pomodoros"],
            "focus_minutes": cur["pomodoros"] * work, "streak": streak, "score": score, "overdue": cur["overdue"],
            "title": week_title(score, cur["total_done"])}


def week_title(score: int, done: int) -> str:
    if not done and not score:
        return "هفتهٔ استراحت"
    if score >= 80:
        return "هفتهٔ درخشان"
    if score >= 55:
        return "هفتهٔ پرکار"
    return "هفتهٔ آرام"
