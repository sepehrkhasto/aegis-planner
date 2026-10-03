# SPDX-License-Identifier: GPL-3.0-or-later
"""vault doors (open / close), the day seal, brand voice, sounds, version + installer branding."""
import datetime as dt
import io
import wave
from pathlib import Path

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest

from aegis_desktop import __version__
from aegis_desktop.core import logic
from aegis_desktop.ui import brand, moments, sfx, theme
from aegis_desktop.ui.voice import VOICE
from aegis_desktop.ui.whatsnew import CHANGES, notes_for
from test_gui import setup_vault, win  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def _overlays(host, kind):
    return [c for c in host.findChildren(kind) if c.isVisible()]


def test_opening_doors_stay_shut_then_part_then_clean_up(win):
    setup_vault(win)
    win.show(); QTest.qWait(1400)                                # the real unlock already played its own doors
    ov = moments._Doors(win.shell, 1100, True)
    ov.k = 0.05
    assert ov._openness() == 0.0                                  # the whole shield is shown first
    ov.k = 0.6
    assert 0.2 < ov._openness() < 1.0
    ov.k = 1.0
    assert ov._openness() == 1.0
    ov.deleteLater()
    moments.unlock_bloom(win.shell)
    assert len(_overlays(win.shell, moments._Doors)) == 1
    QTest.qWait(1400)
    assert not _overlays(win.shell, moments._Doors)


def test_doors_paint_every_stage_without_error(win):
    setup_vault(win)
    win.show(); win.resize(1180, 760); QTest.qWait(60)
    snap = win.shell.grab()
    frames = []
    for opening in (True, False):
        ov = moments._Doors(win.root, 1000, opening, None if opening else snap)
        ov.setGeometry(win.root.rect()); ov.show()
        for k in (0.0, 0.1, 0.3, 0.55, 0.8, 1.0):
            ov.k = k
            frames.append(ov.grab().toImage())
        ov.hide(); ov.deleteLater()
    assert all(not f.isNull() for f in frames) and frames[0] != frames[3]


def test_lock_closes_the_doors_over_the_signin_and_locks_at_once(win):
    setup_vault(win)
    win.show(); win.resize(1180, 760); QTest.qWait(1400)
    win.lock()
    assert not win.store.is_unlocked and win.root.currentWidget() is win.auth      # security first, animation on top
    assert len(_overlays(win.root, moments._Doors)) == 1
    QTest.qWait(1300)
    assert not _overlays(win.root, moments._Doors)


def test_reduce_motion_skips_doors_and_seal(win):
    setup_vault(win)
    win.show(); QTest.qWait(1400)
    win.set_pref("reduce_motion", True)
    moments.unlock_bloom(win.shell)
    moments.seal_day(win.pages["today"])
    assert not _overlays(win.shell, moments._Doors) and not _overlays(win.shell, moments._Seal)
    win.set_pref("reduce_motion", False)
    moments.lock_close(win.root, None)                            # nothing to close over -> nothing happens
    assert not _overlays(win.root, moments._Doors)


def test_day_seal_stamps_once_and_dissolves(win):
    setup_vault(win)
    win.show(); win.show_page("today"); win.resize(1180, 760); QTest.qWait(1400)
    page = win.pages["today"]
    moments.seal_day(page)
    assert len(_overlays(page, moments._Seal)) == 1
    ov = _overlays(page, moments._Seal)[0]
    ov.setGeometry(page.rect())
    shots = []
    for k in (0.02, 0.13, 0.3, 0.6, 0.9):
        ov.k = k
        shots.append(ov.grab().toImage())
    assert shots[0].isNull() is False and shots[2] != shots[3]
    QTest.qWait(2900)
    assert not _overlays(page, moments._Seal)


def test_finishing_the_last_task_seals_the_day_once(win, monkeypatch):
    setup_vault(win)
    win.show_page("today"); QTest.qWait(700)
    hits = []
    monkeypatch.setattr(moments, "seal_day", lambda *a, **k: hits.append(1))
    v = win.store.vault
    for x in logic.tasks_on(v, dt.date.today()):
        logic.set_done(v, x, True)
        win.changed()
    assert len(hits) == 1
    assert VOICE["day_done"] in win.pages["today"].sub_lb.text()


def test_seal_paints_a_filled_gilt_disc(qapp):
    img = QImage(200, 200, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    brand.paint_seal(p, QPointF(100, 100), 80, theme.THEMES["noir"]["pal"])
    p.end()
    assert img.pixelColor(100, 100).alpha() > 200 and img.pixelColor(2, 2).alpha() == 0
    rim = img.pixelColor(100, 100 - 79)
    assert rim.alpha() > 150 and rim.lightness() > 90            # a bright metal rim


def test_brand_voice_in_the_interface(win):
    from PyQt6.QtWidgets import QLabel
    heads = [lb.text() for lb in win.auth.findChildren(QLabel)]
    assert VOICE["locked"] in heads and "ولت قفل است" not in heads
    setup_vault(win)
    win.schedule_save(); win._autosave()
    assert win.status_lb.text().startswith(VOICE["saved"])


def test_new_sounds_are_valid_and_signature_pair_mirrors(qapp):
    for name in ("open", "close", "seal"):
        data = sfx.build(name)
        with wave.open(io.BytesIO(data)) as w:
            assert w.getnchannels() == 1 and w.getnframes() > 2000
    assert sfx.build("open") != sfx.build("close")


def test_version_is_consistent_and_release_notes_exist():
    assert __version__ == "2.11.10" and notes_for("2.11.10") and notes_for("2.5.0") and notes_for("2.4.0") and notes_for("2.3.1") and notes_for("2.3.0") and notes_for("2.0.0") and notes_for("1.5.1") and notes_for("1.5.0") and notes_for("1.4.1") and notes_for("1.4.0") and len(CHANGES["2.0.0"]) >= 3 and notes_for("1.3.0") and notes_for("1.2.0")
    vi = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "2, 11, 10, 0" in vi and "2.11.10.0" in vi and '#define AppVersion "2.11.10"' in iss and "1.1.0" not in iss
    assert ".aegis" in iss and "DefaultIcon" in iss and "[Registry]" in iss
    for n in ("wiz_164", "wiz_246", "wiz_328", "small_55", "small_83", "small_110"):
        assert (ROOT / "packaging" / "installer_assets" / f"{n}.bmp").stat().st_size > 1000


def test_readme_documents_the_brand():
    r = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    assert "Brand guide" in r and "Gilt glint" in r and "Cormorant" in r and "2.11.10" in r
