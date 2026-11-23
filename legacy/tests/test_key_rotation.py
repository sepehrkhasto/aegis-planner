# SPDX-License-Identifier: GPL-3.0-or-later
import json

import pytest

from aegis_desktop.core import crypto
from aegis_desktop.core.store import VaultStore, VaultError

PW = "Old-password-123"
NEW = "New-password-456"


def mk(tmp_path, recovery=False):
    s = VaultStore(tmp_path / "d")
    s.create(PW)
    s.vault["tasks"].append({"id": "t_1", "title": "راز"})
    s.dirty = True
    s.save()
    key = s.setup_recovery() if recovery else None
    return s, key


def test_dek_changes_and_data_survives(tmp_path):
    s, _ = mk(tmp_path)
    old = bytes(s._dek)
    assert s.change_password(NEW) is None
    assert bytes(s._dek) != old
    s.lock()
    with pytest.raises(Exception):
        s.unlock(PW)
    s.unlock(NEW)
    assert s.vault["tasks"][0]["title"] == "راز"


def test_old_dek_cannot_read_vault_or_backups(tmp_path):
    s, _ = mk(tmp_path)
    old = bytes(s._dek)
    s.snapshot("manual")
    s.change_password(NEW)
    files = [s.path, *s.list_backups()]
    assert len(files) >= 2
    for p in files:
        b = json.loads(p.read_text(encoding="utf-8"))
        if b["ciphertext"]:
            with pytest.raises(crypto.WrongPassword):
                crypto.decrypt_vault(old, b["ciphertextIv"], b["ciphertext"])
            assert crypto.decrypt_vault(bytes(s._dek), b["ciphertextIv"], b["ciphertext"])["tasks"]


def test_backups_open_with_new_password_only(tmp_path):
    s, _ = mk(tmp_path)
    s.snapshot("manual")
    s.change_password(NEW)
    s.lock()
    for p in s.list_backups():
        b = json.loads(p.read_text(encoding="utf-8"))
        meta = crypto.KeyMeta.from_dict(b)
        with pytest.raises(crypto.WrongPassword):
            crypto.unlock(PW, meta)
        dek = crypto.unlock(NEW, meta)
        assert crypto.decrypt_vault(dek, b["ciphertextIv"], b["ciphertext"])["tasks"]


def test_pinned_backup_stays_pinned_and_keeps_mtime(tmp_path):
    s, _ = mk(tmp_path)
    p = s.snapshot("manual")
    p = s.set_pinned(p, True)
    m = p.stat().st_mtime
    s.change_password(NEW)
    assert p.exists() and p.stat().st_mtime == pytest.approx(m, abs=1)


def test_recovery_key_replaced_when_not_supplied(tmp_path):
    s, key = mk(tmp_path, recovery=True)
    fresh = s.change_password(NEW)
    assert fresh and fresh != key
    s.lock()
    with pytest.raises(Exception):
        s.unlock_with_recovery(key, "Another-pass-789")
    s.unlock_with_recovery(fresh, "Another-pass-789")
    assert s.vault["tasks"]


def test_recovery_flow_keeps_the_same_key_valid(tmp_path):
    s, key = mk(tmp_path, recovery=True)
    s.lock()
    s.unlock_with_recovery(key, NEW)
    s.lock()
    s.unlock(NEW)
    s.lock()
    s.unlock_with_recovery(key, "Third-pass-12345")      # still the same recovery key
    assert s.vault["tasks"][0]["title"] == "راز"


def test_recovery_key_typed_without_prefix(tmp_path):
    s, key = mk(tmp_path, recovery=True)
    s.lock()
    s.unlock_with_recovery(key.replace("AEGIS-", ""), NEW)
    s.lock()
    s.unlock_with_recovery(key, "Third-pass-12345")


def test_failed_change_rolls_back(tmp_path, monkeypatch):
    s, _ = mk(tmp_path)
    old = bytes(s._dek)
    import aegis_desktop.core.store as st

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(st, "_atomic_write", boom)
    with pytest.raises(OSError):
        s.change_password(NEW)
    monkeypatch.undo()
    assert bytes(s._dek) == old
    s.lock()
    s.unlock(PW)
    assert s.vault["tasks"]


def test_no_recovery_stays_none(tmp_path):
    s, _ = mk(tmp_path)
    s.change_password(NEW)
    assert not s.has_recovery()


def test_locked_store_refuses(tmp_path):
    s, _ = mk(tmp_path)
    s.lock()
    with pytest.raises(VaultError):
        s.change_password(NEW)


# ---- recurring horizon ----
import datetime as dt

from aegis_desktop.core import logic, jalali


class _S:
    def __init__(self, v):
        self.vault = v

    def trash_put(self, kind, item):
        self.vault.setdefault("trash", []).append({"kind": kind, "item": item})


def _series(start, rep="daily", n=1):
    v = {"tasks": [], "settings": {}, "trash": []}
    t = logic.new_task("ورزش", rep=rep, due=jalali.date_to_due(start))
    v["tasks"].append(t)
    logic.materialize_series(v, t)
    return v


def _dates(v):
    return sorted(jalali.due_to_date(x["due"]) for x in v["tasks"])


def test_extend_fills_from_today_after_a_long_absence():
    start = dt.date.today() - dt.timedelta(days=90)
    v = _series(start)
    assert max(_dates(v)) < dt.date.today()
    assert logic.extend_series(v) > 0
    d = _dates(v)
    assert max(d) == dt.date.today() + dt.timedelta(days=30)
    assert dt.date.today() in d
    assert len(d) == len(set(d))


def test_extend_is_idempotent_and_weekly_stays_aligned():
    start = dt.date.today() - dt.timedelta(days=50)
    v = _series(start, "weekly")
    logic.extend_series(v)
    n = len(v["tasks"])
    assert logic.extend_series(v) == 0 and len(v["tasks"]) == n
    for d in _dates(v):
        assert (d - start).days % 7 == 0


def test_deleted_occurrence_never_comes_back():
    v = _series(dt.date.today())
    s = _S(v)
    victim = next(x for x in v["tasks"] if jalali.due_to_date(x["due"]) == dt.date.today() + dt.timedelta(days=5))
    logic.remove_task(s, victim)
    logic.extend_series(v, dt.date.today() + dt.timedelta(days=3))
    assert dt.date.today() + dt.timedelta(days=5) not in _dates(v)
    v["trash"].clear()                                   # trash purged: the date must still stay deleted
    logic.extend_series(v, dt.date.today() + dt.timedelta(days=4))
    assert dt.date.today() + dt.timedelta(days=5) not in _dates(v)


def test_restore_from_trash_lifts_the_skip():
    v = _series(dt.date.today())
    s = _S(v)
    victim = next(x for x in v["tasks"] if jalali.due_to_date(x["due"]) == dt.date.today() + dt.timedelta(days=5))
    logic.remove_task(s, victim)
    logic.restore_from_trash(v, v["trash"][0])
    assert dt.date.today() + dt.timedelta(days=5) in _dates(v)
    assert not v["settings"]["seriesSkips"].get(victim["seriesId"])


def test_finished_series_is_not_resurrected():
    v = _series(dt.date.today() - dt.timedelta(days=40))
    for x in v["tasks"]:
        x["done"] = True
    assert logic.extend_series(v) == 0


def test_skips_pruned_when_series_gone():
    v = _series(dt.date.today())
    s = _S(v)
    logic.remove_task(s, v["tasks"][3])
    sid = v["tasks"][0]["seriesId"]
    v["tasks"] = []
    logic.extend_series(v)
    assert sid not in v["settings"].get("seriesSkips", {})


# ---- background save ----
import threading
import time as _t


def _wait(fn, s=5):
    end = _t.time() + s
    while _t.time() < end:
        if fn():
            return True
        _t.sleep(0.01)
    return False


def test_save_async_writes_and_reopens(tmp_path):
    s, _ = mk(tmp_path)
    s.vault["tasks"].append({"id": "t_2", "title": "پس‌زمینه"})
    s.dirty = True
    res = []
    assert s.save_async(res.append)
    assert not s.dirty
    assert _wait(lambda: res)
    assert res == [None]
    s.lock()
    s.unlock(PW)
    assert any(t["title"] == "پس‌زمینه" for t in s.vault["tasks"])


def test_lock_waits_for_pending_write_no_data_loss(tmp_path, monkeypatch):
    s, _ = mk(tmp_path)
    import aegis_desktop.core.store as st
    real = st._atomic_write
    gate = threading.Event()

    def slow(*a, **k):
        gate.wait(2)
        return real(*a, **k)
    monkeypatch.setattr(st, "_atomic_write", slow)
    s.vault["tasks"].append({"id": "t_3", "title": "نباید گم شود"})
    s.dirty = True
    assert s.save_async()
    threading.Timer(0.3, gate.set).start()
    s.lock()                                            # must block until the write is done
    monkeypatch.undo()
    s.unlock(PW)
    assert any(t["title"] == "نباید گم شود" for t in s.vault["tasks"])


def test_second_async_is_refused_while_running(tmp_path, monkeypatch):
    s, _ = mk(tmp_path)
    import aegis_desktop.core.store as st
    real = st._atomic_write
    gate = threading.Event()
    monkeypatch.setattr(st, "_atomic_write", lambda *a, **k: (gate.wait(2), real(*a, **k))[1])
    s.dirty = True
    assert s.save_async()
    s.dirty = True
    assert s.save_async() is False
    assert s.dirty                                       # still pending: nothing was marked saved
    gate.set()
    s._drain()


def test_failed_async_write_keeps_dirty_and_reports(tmp_path, monkeypatch):
    s, _ = mk(tmp_path)
    import aegis_desktop.core.store as st

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(st, "_atomic_write", boom)
    s.vault["tasks"].append({"id": "t_4", "title": "x"})
    s.dirty = True
    res = []
    s.save_async(res.append)
    assert _wait(lambda: res)
    assert isinstance(res[0], OSError)
    assert s.dirty
    monkeypatch.undo()
    s.save()                                             # the retry succeeds and the file is consistent
    s.lock()
    s.unlock(PW)
    assert any(t["id"] == "t_4" for t in s.vault["tasks"])


def test_edit_during_write_stays_dirty(tmp_path, monkeypatch):
    s, _ = mk(tmp_path)
    import aegis_desktop.core.store as st
    real = st._atomic_write
    gate = threading.Event()
    monkeypatch.setattr(st, "_atomic_write", lambda *a, **k: (gate.wait(2), real(*a, **k))[1])
    s.dirty = True
    s.save_async()
    s.vault["tasks"].append({"id": "t_5", "title": "بعد از اسنپ‌شات"})
    s.dirty = True                                       # an edit made while the write runs
    gate.set()
    s._drain()
    assert s.dirty
    s.save()
    s.lock()
    s.unlock(PW)
    assert any(t["id"] == "t_5" for t in s.vault["tasks"])


def test_change_password_after_async_is_consistent(tmp_path):
    s, _ = mk(tmp_path)
    s.vault["tasks"].append({"id": "t_6", "title": "y"})
    s.dirty = True
    s.save_async()
    s.change_password(NEW)
    s.lock()
    s.unlock(NEW)
    assert any(t["id"] == "t_6" for t in s.vault["tasks"])


# ---- security: hostile files ----
def test_oversized_backup_is_not_read(tmp_path, monkeypatch):
    s, _ = mk(tmp_path)
    p = s.snapshot("manual")
    import aegis_desktop.core.store as st
    monkeypatch.setattr(st, "MAX_FILE_BYTES", 10)
    info = s._backup_info(p) if hasattr(s, "_backup_info") else None
    assert info is None or info["valid"] is False
    assert s._rewrap_backups() == 0


@pytest.mark.parametrize("mut", [
    lambda b: b.update(ciphertext="AAAA"),
    lambda b: b.update(wrappedKey="AAAA"),
    lambda b: b.update(salt=""),
    lambda b: b.update(iterations=1),
    lambda b: b.update(iterations=10 ** 12),
    lambda b: b.update(kdf="MD5"),
    lambda b: b.update(ciphertextIv="!!!"),
    lambda b: b.pop("wrappedKeyIv"),
    lambda b: b.update(wrappedKey=None),
])
def test_tampered_vault_file_fails_cleanly(tmp_path, mut):
    s, _ = mk(tmp_path)
    s.lock()
    b = json.loads(s.path.read_text(encoding="utf-8"))
    mut(b)
    s.path.write_text(json.dumps(b), encoding="utf-8")
    s2 = VaultStore(tmp_path / "d")
    with pytest.raises((VaultError, crypto.WrongPassword)):
        s2.unlock(PW)
    assert not s2.is_unlocked


def test_flipped_ciphertext_bit_is_detected(tmp_path):
    s, _ = mk(tmp_path)
    s.lock()
    b = json.loads(s.path.read_text(encoding="utf-8"))
    raw = bytearray(crypto.b64d(b["ciphertext"]))
    raw[len(raw) // 2] ^= 1
    b["ciphertext"] = crypto.b64e(bytes(raw))
    s.path.write_text(json.dumps(b), encoding="utf-8")
    with pytest.raises(VaultError):
        VaultStore(tmp_path / "d").unlock(PW)


def test_nonces_unique_and_file_has_no_plaintext(tmp_path):
    s, _ = mk(tmp_path)
    ivs = set()
    for i in range(200):
        s.vault["tasks"].append({"id": f"x{i}", "title": "رازِ-محرمانه"})
        s.dirty = True
        s.save()
        ivs.add(json.loads(s.path.read_text(encoding="utf-8"))["ciphertextIv"])
    assert len(ivs) == 200
    blob = s.path.read_bytes() + b"".join(p.read_bytes() for p in s.list_backups())
    assert "رازِ-محرمانه".encode() not in blob and PW.encode() not in blob


def test_no_temp_files_left_behind(tmp_path):
    s, _ = mk(tmp_path)
    s.change_password(NEW)
    s.dirty = True
    s.save_async()
    s._drain()
    assert not list((tmp_path / "d").rglob("*.tmp"))
