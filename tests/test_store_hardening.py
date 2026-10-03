# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage failure modes: damaged files, full disks, locked folders, password changes and backups."""
import errno
import json
import os
from pathlib import Path

import pytest

from aegis_desktop.core import crypto, store as store_mod
from aegis_desktop.core.crypto import WrongPassword
from aegis_desktop.core.store import VaultError, VaultStore

PW = "correct horse battery 42"


@pytest.fixture
def st(tmp_path):
    s = VaultStore(tmp_path / "d")
    s.create(PW)
    return s


def _reopen(s):
    return VaultStore(s.dir)


@pytest.mark.parametrize("content", ["", "{", "null", "[]", '{"format":"securevault1"}', "\x00\x01garbage"])
def test_unreadable_vault_file_is_a_friendly_vaulterror(st, content):
    st.lock()
    st.path.write_text(content, encoding="utf-8")
    with pytest.raises(VaultError):
        _reopen(st).unlock(PW)


def test_tampered_ciphertext_is_detected(st):
    st.vault["tasks"].append({"id": "t1", "title": "سری"})
    st.save(); st.lock()
    raw = json.loads(st.path.read_text(encoding="utf-8"))
    ct = bytearray(crypto.b64d(raw["ciphertext"])); ct[10] ^= 0x01            # one flipped bit
    raw["ciphertext"] = crypto.b64e(bytes(ct))
    st.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(VaultError) as e:                                       # AES-GCM authentication fails: damage, not "wrong password"
        _reopen(st).unlock(PW)
    assert not isinstance(e.value, WrongPassword)


@pytest.mark.parametrize("iters", [1, 99_999, 50_000_000])
def test_hostile_kdf_parameters_are_refused(st, iters):
    st.lock()
    raw = json.loads(st.path.read_text(encoding="utf-8")); raw["iterations"] = iters
    st.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises((VaultError, ValueError)):
        _reopen(st).unlock(PW)


def test_disk_full_during_save_changes_nothing(st, monkeypatch):
    st.vault["tasks"].append({"id": "keep", "title": "قبلی"}); st.save()
    before = st.path.read_bytes()
    st.vault["tasks"].append({"id": "new", "title": "جدید"}); st.dirty = True

    def full(*_a, **_k):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(store_mod.os, "fsync", full)
    with pytest.raises(OSError):
        st.save()
    assert st.path.read_bytes() == before                                      # old file intact
    assert st.dirty and [t["id"] for t in st.vault["tasks"]] == ["keep", "new"]  # edits still in memory
    assert not [p for p in st.dir.iterdir() if p.suffix == ".tmp"]             # no temp debris
    monkeypatch.undo()
    st.save()
    s2 = _reopen(st); s2.unlock(PW)
    assert [t["id"] for t in s2.vault["tasks"]] == ["keep", "new"]


def test_failed_password_change_keeps_old_password(st, monkeypatch):
    real = store_mod._atomic_write
    calls = {"n": 0}

    def flaky(path, data):
        if Path(path) == st.path:
            calls["n"] += 1
            raise OSError(errno.EACCES, "denied")
        return real(path, data)
    monkeypatch.setattr(store_mod, "_atomic_write", flaky)
    with pytest.raises(OSError):
        st.change_password("another strong password 7")
    monkeypatch.undo()
    st.lock()
    s2 = _reopen(st); s2.unlock(PW)                                            # still the old password
    assert s2.is_unlocked


def test_old_password_cannot_open_backups_after_rekey(st):
    st.snapshot("manual")
    st.change_password("brand new password 99")
    for b in st.list_backups():
        bundle = VaultStore.read_bundle(b)
        with pytest.raises(WrongPassword):
            VaultStore.decrypt_bundle(bundle, PW)
        VaultStore.decrypt_bundle(bundle, "brand new password 99")


def test_backup_retention_keeps_pinned_and_minimum(st):
    st.keep_backups = 3
    made = [st.snapshot("manual") for _ in range(6)]
    pinned = st.set_pinned(made[0], True)
    for i in range(3):
        st.vault["tasks"].append({"id": f"x{i}", "title": "x"}); st.save()
        st.snapshot("auto")
    names = [p.name for p in st.list_backups()]
    assert pinned.name in names
    assert len([n for n in names if not n.endswith("-keep.aegis")]) == 3


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="POSIX permissions; root ignores them")
def test_readonly_backup_folder_does_not_block_unlock(st, tmp_path):
    ro = tmp_path / "ro"; ro.mkdir(); os.chmod(ro, 0o500)
    try:
        st.lock()
        s2 = _reopen(st); s2.set_backup_dir(ro); s2.unlock_backup_s = 1
        s2.unlock(PW)
        assert s2.is_unlocked and s2.backup_error
    finally:
        os.chmod(ro, 0o700)


def test_import_rejects_non_bundles_and_huge_files(st, tmp_path):
    p = tmp_path / "x.aegis"
    p.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    with pytest.raises(VaultError):
        VaultStore.read_bundle(p)
    big = tmp_path / "big.aegis"
    with open(big, "wb") as f:
        f.seek(store_mod.MAX_FILE_BYTES + 1); f.write(b"0")
    with pytest.raises(VaultError):
        VaultStore.read_bundle(big)


def test_merge_does_not_touch_live_vault_when_save_fails(st, monkeypatch, tmp_path):
    other = VaultStore(tmp_path / "o"); other.create(PW)
    other.vault["tasks"].append({"id": "from-other", "title": "x"}); other.save()
    bundle = VaultStore.read_bundle(other.export_bundle(tmp_path / "o.aegis"))
    before = [t["id"] for t in st.vault["tasks"]]
    real = store_mod._atomic_write

    def fail_vault(path, data):
        if Path(path) == st.path:
            raise OSError(errno.ENOSPC, "full")
        return real(path, data)
    monkeypatch.setattr(store_mod, "_atomic_write", fail_vault)
    with pytest.raises(OSError):
        st.import_merge(bundle, PW)
    assert [t["id"] for t in st.vault["tasks"]] == before


# ---- password typed on another keyboard layout / normalization ----------------------------------------------------
def test_password_created_with_arabic_yeh_opens_with_persian_yeh(tmp_path):
    s = VaultStore(tmp_path / "k"); s.create("كليد ميز 12345")          # Arabic kaf / yeh (Arabic keyboard)
    s.lock()
    s2 = VaultStore(tmp_path / "k"); s2.unlock("کلید میز 12345")          # Persian kaf / yeh (Persian keyboard)
    assert s2.is_unlocked
    s2.lock(); s3 = VaultStore(tmp_path / "k"); s3.unlock("كليد ميز 12345")
    assert s3.is_unlocked


def test_decomposed_unicode_password_still_opens(tmp_path):
    import unicodedata
    pw = "Café-Straße ۱۲۳۴۵"
    s = VaultStore(tmp_path / "n"); s.create(unicodedata.normalize("NFC", pw)); s.lock()
    s2 = VaultStore(tmp_path / "n"); s2.unlock(unicodedata.normalize("NFD", pw))
    assert s2.is_unlocked


def test_ascii_password_costs_a_single_derivation():
    assert crypto.password_variants("correct horse battery 42") == ["correct horse battery 42"]


def test_lock_overwrites_the_data_key_in_place(st):
    key = st._dek
    assert isinstance(key, bytearray) and any(key)
    st.lock()
    assert st._dek is None and not any(key)                               # the buffer we held is zeroed
