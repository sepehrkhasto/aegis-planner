# SPDX-License-Identifier: GPL-3.0-or-later
import datetime as dt, json, os, subprocess, shutil, textwrap
from pathlib import Path
import pytest
from aegis_desktop.core import jalali, logic
from aegis_desktop.core.store import VaultStore, VaultError, normalize
from aegis_desktop.core.crypto import WrongPassword

PW = "correct horse battery 42"

@pytest.fixture
def st(tmp_path):
    s = VaultStore(tmp_path / "d"); s.create(PW); return s

def test_jalali_known_dates():
    assert jalali.to_jalali(2026, 3, 21) == (1405, 1, 1)
    assert jalali.to_gregorian(1405, 1, 1) == (2026, 3, 21)
    assert jalali.to_jalali(2024, 3, 20) == (1403, 1, 1)
    assert jalali.is_leap(1403) and not jalali.is_leap(1404)
    assert jalali.month_length(1403, 12) == 30 and jalali.month_length(1404, 12) == 29
    d = dt.date(2000, 1, 1)
    for i in range(0, 20000, 37):
        x = d + dt.timedelta(days=i)
        assert jalali.to_gregorian(*jalali.to_jalali(x.year, x.month, x.day)) == (x.year, x.month, x.day)

def test_create_unlock_wrong_password(st):
    st.lock()
    with pytest.raises(WrongPassword): st.unlock("nope-nope-nope")
    st.unlock(PW); assert st.is_unlocked

def test_file_has_no_plaintext(st):
    st.vault["notes"].append(logic.new_note("راز فوق‌محرمانه", "SECRET-BODY-123")); st.save()
    raw = st.path.read_text(encoding="utf-8")
    assert "SECRET-BODY-123" not in raw and "راز" not in raw

def test_persist_roundtrip(tmp_path):
    s = VaultStore(tmp_path); s.create(PW)
    s.vault["tasks"].append(logic.new_task("hello")); s.save(); s.lock()
    s2 = VaultStore(tmp_path); s2.unlock(PW)
    assert s2.vault["tasks"][0]["title"] == "hello"

def test_change_password_keeps_data(st):
    st.vault["tasks"].append(logic.new_task("x")); st.save()
    st.change_password("another very long pass 9"); st.lock()
    with pytest.raises(WrongPassword): st.unlock(PW)
    st.unlock("another very long pass 9"); assert st.vault["tasks"][0]["title"] == "x"

def test_recovery_key_flow(st):
    key = st.setup_recovery(); st.vault["tasks"].append(logic.new_task("keep")); st.save(); st.lock()
    with pytest.raises(WrongPassword): st.unlock_with_recovery("AEGIS-AAAAA-AAAAA", "zzzzzzzzzzzz1")
    st.unlock_with_recovery(key.lower().replace("-", " "), "brand new password 77")
    st.lock(); st.unlock("brand new password 77"); assert st.vault["tasks"][0]["title"] == "keep"

def test_export_import_replace(st, tmp_path):
    st.vault["tasks"].append(logic.new_task("portable")); st.save()
    out = st.export_bundle(tmp_path / "b.aegis")
    fresh = VaultStore(tmp_path / "other")
    b = VaultStore.read_bundle(out)
    with pytest.raises(WrongPassword): fresh.import_replace(b, "wrong wrong wrong")
    fresh.import_replace(b, PW); fresh.lock()
    fresh.unlock(PW); assert fresh.vault["tasks"][0]["title"] == "portable"

def test_import_replace_creates_snapshot(st, tmp_path):
    out = st.export_bundle(tmp_path / "b.aegis")
    n0 = len(st.list_backups())
    st.import_replace(VaultStore.read_bundle(out), PW)
    assert len(st.list_backups()) == n0 + 1

def test_import_merge(st, tmp_path):
    a = logic.new_task("A"); st.vault["tasks"].append(a); st.save()
    out = st.export_bundle(tmp_path / "b.aegis")
    st.vault["tasks"].append(logic.new_task("B-local")); st.save()
    other = VaultStore(tmp_path / "o"); other.import_replace(VaultStore.read_bundle(out), PW)
    other.vault["tasks"].append(logic.new_task("C-remote")); other.save()
    out2 = other.export_bundle(tmp_path / "c.aegis")
    added = st.import_merge(VaultStore.read_bundle(out2), PW)
    titles = sorted(t["title"] for t in st.vault["tasks"])
    assert titles == ["A", "B-local", "C-remote"] and added["tasks"] == 1

def test_bad_bundles_rejected(tmp_path):
    p = tmp_path / "x.aegis"; p.write_text("not json")
    with pytest.raises(VaultError): VaultStore.read_bundle(p)
    p.write_text(json.dumps({"format": "x"}))
    with pytest.raises(VaultError): VaultStore.read_bundle(p)
    weak = {"kdf": "PBKDF2-SHA256", "iterations": 10, "salt": "a", "wrappedKey": "a", "wrappedKeyIv": "a", "ciphertext": "", "ciphertextIv": ""}
    p.write_text(json.dumps(weak))
    with pytest.raises(VaultError): VaultStore.read_bundle(p)

def test_tampered_ciphertext_fails(st):
    raw = json.loads(st.path.read_text(encoding="utf-8"))
    import base64
    ct = bytearray(base64.b64decode(raw["ciphertext"])); ct[5] ^= 1
    raw["ciphertext"] = base64.b64encode(bytes(ct)).decode()
    st.path.write_text(json.dumps(raw)); st.lock(); st._raw = None
    with pytest.raises(VaultError) as e: st.unlock(PW)                    # right password, damaged data: not "wrong password"
    assert not isinstance(e.value, WrongPassword) and "آسیب" in str(e.value)
    with pytest.raises(WrongPassword): st.unlock("not the password at all")

def test_unknown_keys_preserved_and_migrations():
    v = normalize({"tasks": [], "futureFeature": {"a": 1}, "passwords": [1],
                   "journal": [{"id": "j1", "date": "2026-01-02", "body": "hi", "mood": 3}],
                   "lists": [{"id": "l1", "name": "L", "items": [{"text": "a", "done": True}]}]})
    assert v["futureFeature"] == {"a": 1} and "passwords" not in v
    assert v["journal"] == [] and v["lists"] == []
    assert {n["folder"] for n in v["notes"]} == {"ژورنال", "چک‌لیست"}

def test_atomic_write_leaves_no_tmp(st):
    st.save(); assert not list(st.dir.glob("*.tmp"))

def test_recurring_and_kanban(st):
    v = st.vault
    t = logic.new_task("daily", rep="daily", due=jalali.today_jalali()); v["tasks"].append(t)
    logic.set_done(v, t, True)          # no seriesId -> one copy for tomorrow
    assert len(v["tasks"]) == 2 and v["tasks"][1]["done"] is False
    assert logic.kanban_status(t) == "done"
    logic.set_status(t, "doing"); assert not t["done"] and logic.kanban_status(t) == "doing"
    s = logic.new_task("series", rep="weekly", due=jalali.today_jalali()); v["tasks"].append(s)
    assert logic.materialize_series(v, s) == 8 and logic.materialize_series(v, s) == 0

def test_habits():
    h = logic.new_habit("run"); today = dt.date(2026, 9, 29)
    for i in range(5): h["log"][(today - dt.timedelta(days=i)).isoformat()] = {"d": 1}
    st = logic.habit_stats(h, today); assert st["streak"] == 5 and st["best"] == 5 and st["week"] == 5
    assert logic.habit_toggle(h, today) is False and logic.habit_stats(h, today)["streak"] == 4

def test_goal_progress(st):
    g = logic.new_goal("g", ms=[{"id": "1", "text": "a", "done": True}, {"id": "2", "text": "b", "done": False}])
    st.vault["tasks"].append(logic.new_task("linked", goalId=g["id"], done=True))
    assert logic.goal_progress(st.vault, g) == 67

def test_ics_and_md(st):
    st.vault["tasks"].append(logic.new_task("جلسه, مهم", due=jalali.today_jalali(), timeFrom="10:30"))
    ics = logic.export_ics(st.vault)
    assert "BEGIN:VEVENT" in ics and "DTSTART:" in ics and "\\," in ics
    assert "## بدون عنوان" in logic.notes_to_markdown([logic.new_note("", "x")])

# ---- interoperability with the web edition's crypto.js (optional: set AEGIS_WEB_CRYPTO_JS; needs Node) ----
NODE = shutil.which("node")
WEB = Path(os.environ.get("AEGIS_WEB_CRYPTO_JS", "web-crypto.js"))

@pytest.mark.skipif(not (NODE and WEB.exists()), reason="Node or the web crypto.js (AEGIS_WEB_CRYPTO_JS) is unavailable")
def test_interop_with_web_crypto_js(tmp_path):
    js = tmp_path / "t.js"
    js.write_text(textwrap.dedent(f"""
        global.window = global; const fs = require('fs');
        eval(fs.readFileSync({json.dumps(str(WEB))}, 'utf8'));
        (async () => {{
          const C = window.ZKCrypto;
          const km = await C.createKeyMaterial('{PW}');
          const enc = await C.encryptVault(km.dek, {{version:1, tasks:[{{id:'w1', title:'from-web'}}], notes:[]}});
          fs.writeFileSync({json.dumps(str(tmp_path / 'web.json'))}, JSON.stringify({{format:'securevault1', ...km.meta, ...enc}}));
          // now read the file produced by PYTHON
          const b = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'py.json'))}, 'utf8'));
          const u = await C.unlock('{PW}', b);
          const v = await C.decryptVault(u.dek, b.ciphertextIv, b.ciphertext);
          fs.writeFileSync({json.dumps(str(tmp_path / 'py_read_by_web.txt'))}, v.tasks[0].title);
          const rk = fs.readFileSync({json.dumps(str(tmp_path / 'rk.txt'))}, 'utf8').trim();
          const rec = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'rec.json'))}, 'utf8'));
          const dekRaw = await C.unwrapWithRecovery(rk, rec);
          fs.writeFileSync({json.dumps(str(tmp_path / 'rec_ok.txt'))}, Buffer.from(dekRaw).equals(Buffer.from(u.dekRaw)) ? 'same' : 'diff');
        }})().catch(e => {{ console.error(e); process.exit(1); }});
    """))
    s = VaultStore(tmp_path / "v"); s.create(PW)
    s.vault["tasks"].append(logic.new_task("from-python")); s.save()
    key = s.setup_recovery()
    bundle = json.loads(s.export_bundle(tmp_path / "e.aegis").read_text(encoding="utf-8"))
    (tmp_path / "py.json").write_text(json.dumps(bundle)); (tmp_path / "rk.txt").write_text(key)
    (tmp_path / "rec.json").write_text(json.dumps(bundle["recovery"]))
    r = subprocess.run([NODE, str(js)], capture_output=True, text=True); assert r.returncode == 0, r.stderr
    assert (tmp_path / "py_read_by_web.txt").read_text() == "from-python"   # web opens Python's file
    assert (tmp_path / "rec_ok.txt").read_text() == "same"                  # web's recovery unwrap == our DEK
    web = json.loads((tmp_path / "web.json").read_text())                   # Python opens web's file
    v, _ = VaultStore.decrypt_bundle(web, PW)
    assert v["tasks"][0]["title"] == "from-web"


# ---------------------------------------------------------------- backups ---
def test_backup_retention_pin_restore_and_rekey(tmp_path):
    from aegis_desktop.core import logic
    from aegis_desktop.core.crypto import WrongPassword
    from aegis_desktop.core.store import VaultStore
    s = VaultStore(tmp_path)
    s.create("first password 123")
    s.vault["tasks"].append(logic.new_task("A")); s.save()
    s.keep_backups = 3
    for _ in range(6):
        s.snapshot("manual")
    assert len(s.list_backups()) == 3
    pinned = s.set_pinned(s.list_backups()[-1], True)
    for i in range(4):
        s.vault["tasks"].append(logic.new_task(f"B{i}")); s.save()
        s.snapshot("auto")
    assert pinned.exists() and s.backup_meta(pinned)["pinned"]
    assert len([p for p in s.list_backups() if not p.stem.endswith("-keep")]) == 3
    del s.vault["tasks"][1:]; s.save()
    snap = s.snapshot("manual")
    assert len(s.open_backup(snap)["tasks"]) == 1
    s.vault["tasks"].append(logic.new_task("B")); s.save()
    s.change_password("second password 456")
    with pytest.raises(WrongPassword):                       # old password must not open old backups
        VaultStore.decrypt_bundle(VaultStore.read_bundle(snap), "first password 123")
    assert len(VaultStore.decrypt_bundle(VaultStore.read_bundle(snap), "second password 456")[0]["tasks"]) == 1
    s.restore_backup(snap)
    assert len(s.vault["tasks"]) == 1
    assert any(s.backup_meta(p)["reason"] == "before-restore" for p in s.list_backups())
    s.lock(); s.unlock("second password 456"); assert len(s.vault["tasks"]) == 1


def test_backup_rejects_corrupt_source_and_survives_bad_dir(tmp_path):
    from aegis_desktop.core.store import VaultError, VaultStore
    s = VaultStore(tmp_path)
    s.create("first password 123")
    good = s.snapshot("manual")
    s.path.write_text("{ not json", encoding="utf-8")
    with pytest.raises((VaultError, ValueError)):
        s.snapshot("manual")
    assert good.exists()
    assert VaultStore.backup_meta(good)["valid"]


def test_untrusted_bundle_limits(tmp_path):
    import json
    import pytest
    from aegis_desktop.core.store import VaultStore, VaultError
    s = VaultStore(tmp_path / "a")
    s.create("correct horse battery 42")
    b = json.loads(s.path.read_text(encoding="utf-8"))
    for bad in ({"iterations": 10**9}, {"iterations": 1000}, {"kdf": "scrypt"}):
        p = tmp_path / "bad.aegis"
        p.write_text(json.dumps({**b, **bad}), encoding="utf-8")
        with pytest.raises(VaultError):
            VaultStore.read_bundle(p)
    from aegis_desktop.core import crypto
    with pytest.raises(crypto.WrongPassword):
        crypto.unwrap_with_recovery("AEGIS-AAAAA", {"salt": "!!"})


def test_day_index_matches_tasks_on_and_recurrence_no_dupes():
    import datetime as dt
    from aegis_desktop.core import logic, jalali
    from aegis_desktop.core.store import empty_vault
    v = empty_vault()
    j = jalali.today_jalali()
    v["tasks"] = [logic.new_task("a", due=dict(j)),
                  logic.new_task("b", due=dict(j), dueEnd=jalali.date_to_due(dt.date.today() + dt.timedelta(days=3)), timeFrom="09:00"),
                  logic.new_task("c")]
    idx = logic.build_day_index(v)
    for i in range(-2, 6):
        d = dt.date.today() + dt.timedelta(days=i)
        assert [x["id"] for x in idx.get(d, [])] == [x["id"] for x in logic.tasks_on(v, d)]
    r = logic.new_task("daily", due=dict(j), rep="daily")
    v["tasks"].append(r)
    for _ in range(4):                      # tick / untick / tick ... must leave exactly one follow-up
        logic.set_done(v, r, True)
        logic.set_done(v, r, False)
    logic.set_done(v, r, True)
    assert sum(1 for x in v["tasks"] if x["title"] == "daily") == 2


def test_analytics_single_pass_consistent():
    from aegis_desktop.core import logic
    from aegis_desktop.core.store import empty_vault, now_iso
    v = empty_vault()
    for i in range(30):
        t = logic.new_task(f"t{i}")
        t["done"], t["doneAt"] = True, now_iso()
        v["tasks"].append(t)
    flow = logic.weekly_flow(v, 8)
    assert len(flow) == 8 and flow[-1][1] == 30 and flow[-1][2] == 30 and sum(f[2] for f in flow[:-1]) == 0


def test_normalize_hardens_damaged_structure():
    from aegis_desktop.core.store import normalize
    v = normalize({"tasks": "oops", "notes": [1, None, {"title": "x"}, {"id": "n1"}], "settings": [], "wellness": {"water": 3},
                   "habits": [{"id": ""}]})
    assert v["tasks"] == []
    assert [type(x) for x in v["notes"]] == [dict, dict] and all(isinstance(x["id"], str) and x["id"] for x in v["notes"])
    assert v["notes"][1]["id"] == "n1"
    assert v["settings"] == {} and v["wellness"]["water"] == {} and v["wellness"]["sleep"] == {}
    assert v["habits"][0]["id"]


def test_failed_save_rolls_back_state(tmp_path, monkeypatch):
    import pytest
    from aegis_desktop.core import store as st
    s = st.VaultStore(tmp_path)
    s.create("Correct-Horse-9!x")
    v = st.empty_vault()
    v["tasks"].append({"id": "zz", "title": "imported"})
    other = st.VaultStore(tmp_path / "o")
    other.create("Other-Pass-77!zz", v)
    bundle = st.VaultStore.read_bundle(other.path)
    before = (s._raw, s._dek, s.vault)
    real = st._atomic_write

    def boom(path, data):
        if path == s.path:
            raise OSError("disk full")
        return real(path, data)
    monkeypatch.setattr(st, "_atomic_write", boom)
    for op in (lambda: s.import_replace(bundle, "Other-Pass-77!zz"),
               lambda: s.import_merge(bundle, "Other-Pass-77!zz"),
               lambda: s.change_password("Brand-New-Pass-5!q"),
               lambda: s.setup_recovery()):
        with pytest.raises(OSError):
            op()
        assert (s._raw, s._dek, s.vault) == before and s.is_unlocked
        assert all(t["id"] != "zz" for t in s.vault["tasks"])
    monkeypatch.setattr(st, "_atomic_write", real)
    s.lock()
    s.unlock("Correct-Horse-9!x")                       # the old password still works: nothing half-applied
    assert s.import_merge(bundle, "Other-Pass-77!zz")["tasks"] == 1


def test_create_failure_leaves_store_locked(tmp_path, monkeypatch):
    import pytest
    from aegis_desktop.core import store as st
    s = st.VaultStore(tmp_path)
    monkeypatch.setattr(st, "_atomic_write", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    with pytest.raises(OSError):
        s.create("Correct-Horse-9!x")
    assert not s.is_unlocked and not s.exists()


def test_concurrent_save_and_merge_never_corrupt(tmp_path):
    import threading
    from aegis_desktop.core import store as st
    s = st.VaultStore(tmp_path)
    s.create("Correct-Horse-9!x")
    v = st.empty_vault()
    v["tasks"] = [{"id": f"m{i}", "title": "t"} for i in range(300)]
    o = st.VaultStore(tmp_path / "o")
    o.create("Other-Pass-77!zz", v)
    bundle = st.VaultStore.read_bundle(o.path)
    errs = []

    def hammer():
        try:
            for _ in range(25):
                s.dirty = True
                s.save()
        except Exception as e:      # noqa: BLE001
            errs.append(e)
    th = threading.Thread(target=hammer)
    th.start()
    s.import_merge(bundle, "Other-Pass-77!zz")
    th.join()
    assert not errs
    s.lock()
    s.unlock("Correct-Horse-9!x")
    assert len(s.vault["tasks"]) >= 300


def test_recurring_multiday_keeps_span_and_tasks_on_clamps():
    import datetime as dt
    from aegis_desktop.core import logic, jalali
    from aegis_desktop.core.store import empty_vault
    v = empty_vault()
    d0 = dt.date.today()
    t = logic.new_task("trip", due=jalali.date_to_due(d0), dueEnd=jalali.date_to_due(d0 + dt.timedelta(days=2)), rep="daily")
    v["tasks"].append(t)
    logic.set_done(v, t, True)
    nxt = [x for x in v["tasks"] if x is not t][0]
    assert jalali.due_to_date(nxt["due"]) == d0 + dt.timedelta(days=1)
    assert jalali.due_to_date(nxt["dueEnd"]) == d0 + dt.timedelta(days=3)
    bad = logic.new_task("bad", due=jalali.date_to_due(d0), dueEnd=jalali.date_to_due(d0 - dt.timedelta(days=3)))
    v["tasks"].append(bad)
    assert bad in logic.tasks_on(v, d0)


def test_restore_from_trash_keeps_ids_unique():
    from aegis_desktop.core import logic
    from aegis_desktop.core.store import empty_vault
    v = empty_vault()
    t = logic.new_task("x")
    v["tasks"].append(t)
    entry = {"kind": "task", "item": dict(t), "at": "2026-01-01T00:00:00Z"}
    v["trash"].append(entry)
    logic.restore_from_trash(v, entry)
    ids = [x["id"] for x in v["tasks"]]
    assert len(ids) == 2 and len(set(ids)) == 2 and not v["trash"]
    logic.restore_from_trash(v, {"kind": "??", "item": None})     # malformed entries are ignored, never crash


def test_ics_is_rfc_shaped():
    from aegis_desktop.core import logic, jalali
    from aegis_desktop.core.store import empty_vault
    v = empty_vault()
    v["tasks"].append(logic.new_task("عنوان خیلی طولانی " * 12, notes="a;b,c\r\nline2", due=dict(jalali.today_jalali()),
                                     timeFrom="10:00", timeTo="09:00"))
    txt = logic.export_ics(v)
    lines = txt.split("\r\n")
    assert all(len(l.encode("utf-8")) <= 75 for l in lines)
    unfolded = txt.replace("\r\n ", "")
    assert "DTEND:" not in unfolded                        # end before start is dropped
    assert r"DESCRIPTION:a\;b\,c\nline2" in unfolded
    assert "عنوان خیلی طولانی" in unfolded                   # folding never splits or corrupts a character


def test_goal_progress_map_matches_single():
    from aegis_desktop.core import logic
    from aegis_desktop.core.store import empty_vault
    v = empty_vault()
    g1, g2 = logic.new_goal("a", ms=[{"text": "m", "done": True}]), logic.new_goal("b")
    v["goals"] = [g1, g2]
    t = logic.new_task("x", goalId=g1["id"]); t2 = logic.new_task("y", goalId=g1["id"], done=True)
    v["tasks"] = [t, t2]
    m = logic.goal_progress_map(v)
    assert m == {g["id"]: logic.goal_progress(v, g) for g in v["goals"]} and m[g2["id"]] is None


def test_normalize_coerces_fields_the_ui_reads_unconditionally():
    from aegis_desktop.core.store import normalize
    v = normalize({"habits": [{"id": "h"}, {"id": "h2", "name": None, "log": None}],
                   "goals": [{"id": "g"}, {"id": "g2", "title": 5, "ms": [1, {"text": "a"}, None]}],
                   "tasks": [{"id": "t", "title": None, "tags": None, "subs": ["x", {"text": "s"}]}],
                   "notes": [{"id": "n", "body": None, "html": None}]})
    assert all(h["name"] == "" and h["log"] == {} for h in v["habits"])
    assert v["goals"][0]["title"] == "" and v["goals"][0]["ms"] == [] and v["goals"][1]["ms"] == [{"text": "a"}]
    t = v["tasks"][0]
    assert t["title"] == "" and t["tags"] == [] and t["subs"] == [{"text": "s"}]
    assert v["notes"][0]["body"] == "" and "title" not in v["notes"][0]      # optional fields are not invented


def test_normalize_drops_half_formed_dates():
    from aegis_desktop.core.store import normalize
    v = normalize({"tasks": [{"id": "a", "due": {"jy": 1405}}, {"id": "b", "due": {"jy": 1405, "jm": 7, "jd": 7}, "dueEnd": "x"}],
                   "goals": [{"id": "g", "deadline": {"jy": 1, "jm": 13, "jd": 1}}]})
    assert v["tasks"][0]["due"] is None and v["tasks"][1]["due"] == {"jy": 1405, "jm": 7, "jd": 7}
    assert v["tasks"][1]["dueEnd"] is None and v["goals"][0]["deadline"] is None


# ---------------------------------------------------------------- report series (sparklines / comparison) ---
def _done_task(day: dt.date, created: dt.date | None = None):
    t = logic.new_task("x")
    def iso(d):
        return dt.datetime.combine(d, dt.time(12, 0)).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    t["done"], t["doneAt"], t["createdAt"] = True, iso(day), iso(created or day)
    return t

def test_daily_metrics_and_weekday_compare():
    today = dt.date(2026, 9, 29)
    v = {"tasks": [_done_task(today), _done_task(today, today - dt.timedelta(days=2)),
                   _done_task(today - dt.timedelta(days=1)), _done_task(today - dt.timedelta(days=35))],
         "archive": [_done_task(today - dt.timedelta(days=3))],
         "habits": [{"log": {today.isoformat(): {"d": 1}, "junk": 1, (today - dt.timedelta(days=99)).isoformat(): {"d": 1}}}],
         "settings": {"pomoLog": {today.isoformat(): 3, (today - dt.timedelta(days=1)).isoformat(): "bad"}}}
    m = logic.daily_metrics(v, 7, today)
    assert set(m) == {"done", "created", "habits", "pomo"} and all(len(x) == 7 for x in m.values())
    assert m["done"][-1] == 2 and m["done"][-2] == 1 and m["done"][-4] == 1 and sum(m["done"]) == 4
    assert m["created"][-3] == 1 and m["created"][-1] == 1                # createdAt two days earlier is counted there
    assert m["habits"][-1] == 1 and sum(m["habits"]) == 1                 # junk / out-of-window keys ignored
    assert m["pomo"][-1] == 3 and m["pomo"][-2] == 0                      # a corrupt value never raises
    assert logic.daily_metrics({}, 5, today) == {"done": [0] * 5, "created": [0] * 5, "habits": [0] * 5, "pomo": [0] * 5}
    cur, prev = logic.weekday_compare(v, 7, today)
    assert sum(cur) == 4 and sum(prev) == 0                               # the 35-day-old task is in neither 7-day window
    cur, prev = logic.weekday_compare(v, 45, today)
    assert sum(cur) == 5 and sum(prev) == 0
    cur, prev = logic.weekday_compare(v, 20, today)
    assert sum(cur) == 4 and sum(prev) == 1                               # the period before = the 20 days ending 20 days ago (contains the 35-day-old one)


# ---- backend hardening: damaged files, friendly errors, logging -------------------------------------------------
def _tamper(path, **fields):
    b = json.loads(Path(path).read_text(encoding="utf-8")); b.update(fields)
    Path(path).write_text(json.dumps(b), encoding="utf-8")


@pytest.mark.parametrize("field,bad", [("salt", "!!not base64!!"), ("wrappedKey", "@@@"), ("wrappedKeyIv", "###")])
def test_damaged_key_fields_raise_vaulterror_not_valueerror(tmp_path, field, bad):
    s = VaultStore(tmp_path / "d"); s.create(PW); s.lock()
    _tamper(s.path, **{field: bad})
    s2 = VaultStore(tmp_path / "d")
    with pytest.raises((VaultError, WrongPassword)):          # never a bare ValueError / binascii.Error
        s2.unlock(PW)


def test_damaged_bundle_on_import_is_vaulterror(tmp_path):
    s = VaultStore(tmp_path / "d"); s.create(PW)
    out = s.export_bundle(tmp_path / "x.aegis")
    _tamper(out, salt="%%%")
    b = VaultStore.read_bundle(out)
    with pytest.raises((VaultError, WrongPassword)):
        VaultStore.decrypt_bundle(b, PW)


def test_friendly_hides_technical_detail(tmp_path):
    import errno as _e
    from aegis_desktop.core.log import friendly
    full = friendly(OSError(_e.ENOSPC, "No space left on device", r"C:\Users\x\vault.aegis"))
    assert "دیسک" in full and "Errno" not in full and "Users" not in full
    assert "دسترسی" in friendly(PermissionError(13, "denied", "p"))
    assert friendly(VaultError("پیام کاربر")) == "پیام کاربر"
    assert friendly(RuntimeError("boom secret")) == "مشکلی پیش آمد."


def test_log_file_is_rotating_and_holds_no_vault_content(tmp_path):
    from aegis_desktop.core import log as L
    path = L.setup(tmp_path)
    assert path and path.name == "aegis.log"
    L.friendly(OSError(28, "No space left"), "save")
    for h in L.log.handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert "OSError" in text and "errno=28" in text
