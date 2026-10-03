# SPDX-License-Identifier: GPL-3.0-or-later
"""The uninstaller's confirmation screen, its exit codes, and the contract with packaging/installer.iss."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from aegis_desktop import app as app_mod
from aegis_desktop.core.store import VaultStore
from aegis_desktop.ui import theme, uninstall_dialog as ud

PW = "a long enough password 1"
ISS = Path(__file__).resolve().parent.parent / "packaging" / "installer.iss"


@pytest.fixture(autouse=True)
def _app(qtbot):
    app = QApplication.instance()
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    theme.load_font(app)
    mode = theme.set_theme(theme.DEFAULT_THEME)
    theme.apply_palette(app, mode)
    theme.install_stylesheet(app, theme.stylesheet(mode))


def make(tmp_path, backups=2, custom=None):
    data = tmp_path / "AegisPlanner"
    s = VaultStore(data)
    s.create(PW)
    if custom is not None:
        data.joinpath("prefs.json").write_text(json.dumps({"backup_dir": str(custom)}), encoding="utf-8")
        s.set_backup_dir(custom)
    for i in range(backups):
        s.vault["tasks"].append({"id": f"t{i}", "title": f"t{i}"})
        s.save()
        s.snapshot("manual")
    s.lock()
    return data


def test_gather_reads_the_default_and_a_custom_backup_folder(tmp_path):
    f = ud.gather(make(tmp_path, 3))
    assert f.vault and f.count == 3 and not f.custom and f.backup_dir.name == "backups" and f.newest is not None
    other = tmp_path / "elsewhere"
    f2 = ud.gather(make(tmp_path / "x", 2, custom=other))
    assert f2.custom and f2.backup_dir == other and f2.count == 2


def test_gather_survives_a_missing_or_broken_data_folder(tmp_path):
    f = ud.gather(tmp_path / "nothing")
    assert not f.vault and f.count == 0
    d = tmp_path / "AegisPlanner"
    d.mkdir()
    (d / "prefs.json").write_text('{"backup_dir": 5}', encoding="utf-8")
    assert ud.gather(d).custom is False
    (d / "prefs.json").write_text("not json", encoding="utf-8")
    assert ud.gather(d).count == 0


def test_the_screen_says_what_goes_and_what_stays(tmp_path):
    dlg = ud.UninstallDialog(ud.gather(make(tmp_path, 4)))
    dlg.show()
    text = " ".join(lb.text() for lb in dlg.findChildren(type(dlg.note)))
    assert "پاک می‌شود" in text and "می‌ماند" in text
    assert "۴ نسخه" in dlg.count_lb.text() and str(dlg.facts.backup_dir) == dlg.path_lb.text()
    assert dlg.keep_copy.isChecked() and not dlg.warn.isVisible()
    assert dlg.cancel.isDefault() and not dlg.ok.isDefault()        # an absent-minded Enter never deletes anything
    dlg.close()


def test_no_backups_is_a_loud_warning(tmp_path):
    dlg = ud.UninstallDialog(ud.gather(make(tmp_path, 0)))
    dlg.show()
    assert dlg.warn.isVisible() and "برای همیشه" in dlg.warn.text() and dlg.keep_copy.isChecked()
    dlg.close()


def test_no_vault_hides_the_safety_copy(tmp_path):
    (tmp_path / "AegisPlanner").mkdir()
    dlg = ud.UninstallDialog(ud.gather(tmp_path / "AegisPlanner"))
    dlg.show()
    assert not dlg.keep_copy.isVisible() and dlg.warn.isVisible()
    dlg.close()


def test_proceed_saves_a_pinned_final_copy(tmp_path):
    data = make(tmp_path, 1)
    dlg = ud.UninstallDialog(ud.gather(data))
    dlg.show()
    dlg.ok.click()
    assert dlg.result() == 1 and dlg.saved is not None and dlg.saved.exists()
    s = VaultStore(data)
    meta = s.backup_meta(dlg.saved)
    assert meta["pinned"] and meta["reason"] == "uninstall" and meta["label"] == "پیش از حذف برنامه" and meta["valid"]
    s.unlock(PW)
    assert len(s.open_backup(dlg.saved)["tasks"]) == len(s.vault["tasks"])


def test_unchecked_means_no_extra_copy(tmp_path):
    data = make(tmp_path, 1)
    before = len(list((data / "backups").glob("*.aegis")))
    dlg = ud.UninstallDialog(ud.gather(data))
    dlg.show()
    dlg.keep_copy.setChecked(False)
    dlg.ok.click()
    assert dlg.result() == 1 and dlg.saved is None
    assert len(list((data / "backups").glob("*.aegis"))) == before


def test_cancel_and_escape_leave_everything_alone(tmp_path):
    data = make(tmp_path, 1)
    before = sorted(p.name for p in data.rglob("*"))
    for how in ("button", "escape"):
        dlg = ud.UninstallDialog(ud.gather(data))
        dlg.show()
        if how == "button":
            dlg.cancel.click()
        else:
            QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg.result() == 0 and dlg.saved is None
    assert sorted(p.name for p in data.rglob("*")) == before


def test_failed_final_copy_asks_again_instead_of_blocking(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder should be")
    data = make(tmp_path, 1)
    f = ud.gather(data)
    f.backup_dir, f.custom = blocker / "sub", True               # a backup drive that is not plugged in
    dlg = ud.UninstallDialog(f)
    dlg.show()
    dlg.ok.click()
    assert dlg.result() == 0 and dlg.warn.isVisible() and "ساخته نشد" in dlg.warn.text()
    assert str(tmp_path) not in dlg.warn.text()
    assert not dlg.keep_copy.isChecked() and "بدون نسخه" in dlg.ok.text()
    dlg.ok.click()
    assert dlg.result() == 1 and dlg.saved is None


def test_a_damaged_vault_is_copied_as_it_is(tmp_path):
    data = make(tmp_path, 0)
    (data / "vault.aegis").write_text("{ truncated", encoding="utf-8")
    saved = ud.make_final_copy(ud.gather(data))
    assert saved is not None and saved.read_text(encoding="utf-8") == "{ truncated"


def test_main_answers_with_the_exit_codes_the_uninstaller_waits_for(tmp_path, monkeypatch):
    data = tmp_path / "never-created"
    for accepted, code in ((1, ud.EXIT_PROCEED), (0, ud.EXIT_CANCEL)):
        monkeypatch.setattr(ud.UninstallDialog, "exec", lambda self, a=accepted: a)
        assert app_mod.main(["--uninstall-confirm", "--data-dir", str(data)]) == code
    assert not data.exists()                                      # no folder, log or lock file is created by the check


def test_installer_and_app_agree_on_the_contract():
    iss = ISS.read_text(encoding="utf-8")
    assert f"AppMutex={app_mod.APP_MUTEX}" in iss
    assert "--uninstall-confirm" in iss and "/CONFIRM" in iss and "/PURGE" in iss
    assert re.search(rf"ConfirmProceed = {ud.EXIT_PROCEED};", iss) and re.search(rf"ConfirmCancel = {ud.EXIT_CANCEL};", iss)
    for name in ("vault.aegis", "prefs.json", "app.lock"):
        assert f"\\{name}" in iss
    assert "\\backups" in iss and "DelTree" not in iss             # the backup folder is never a deletion target


def test_the_mutex_helper_is_harmless_off_windows():
    app_mod._hold_app_mutex()
