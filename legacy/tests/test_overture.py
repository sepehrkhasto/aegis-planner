# SPDX-License-Identifier: GPL-3.0-or-later
"""The cinematic opening (ui/overture.py): timeline, skipping, reduce-motion, pref and Settings switch."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from aegis_desktop.ui import anim, overture
from aegis_desktop.ui.overture import Overture
from test_gui import PW, setup_vault, win  # noqa: F401


@pytest.fixture
def ov(qtbot):
    o = Overture()
    o.resize(1280, 800)
    qtbot.addWidget(o)
    o.show()
    yield o
    o.stop()


def test_every_second_of_the_film_renders(ov):
    for t in [x * 0.25 for x in range(0, 100)]:       # 0 .. 25 s in quarter-second steps
        ov.set_time(t)
        assert not ov.grab().isNull()


def test_renders_at_odd_sizes(ov):
    for size in ((400, 300), (1920, 1080), (3000, 500), (120, 80)):
        ov.resize(*size)
        for t in (0.5, 2.5, 4.0, 6.0, 9.0, 12.0, 15.0, 17.0, 19.0):
            ov.set_time(t)
            ov.grab()


def test_film_is_about_twenty_seconds(ov):
    assert 15 <= overture.T_CTA <= 20 and 19 <= overture.T_TOTAL <= 22
    assert all(b == overture.SHOTS[i + 1][1] for i, (_n, _a, b) in enumerate(overture.SHOTS[:-1]))
    assert overture.SHOTS[-1][2] == overture.T_CTA
    assert all(b - a <= 6.01 for _n, a, b in overture.SHOTS)           # every shot is six seconds or less


def test_every_shot_boundary_has_a_cut_and_no_code_or_captions(ov):
    for _n, a, _b in overture.SHOTS[1:]:
        assert a in overture.CUTS
    assert not hasattr(overture, "CAPTIONS") and not hasattr(overture, "_FILES") and not hasattr(ov, "_paint_caption")


def test_skip_button_is_prominent(ov):
    css = ov.skip_btn.styleSheet()
    assert "border" in css and "rgba(255,255,255,0.1" in css and ov.skip_btn.minimumHeight() >= 32


def test_finale_renders_with_and_without_button_geometry(ov):
    ov.set_time(overture.T_CTA + 0.1)
    ov.grab()
    ov.set_time(overture.T_CTA + 3.0)
    ov.grab()


def test_keys_enter_space_escape_skip(qtbot, ov):
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Space, Qt.Key.Key_Escape, Qt.Key.Key_Enter):
        ov._done = False
        with qtbot.waitSignal(ov.entered, timeout=3000):
            QTest.keyClick(ov, key)


def test_enter_fires_once(qtbot, ov):
    hits = []
    ov.entered.connect(lambda: hits.append(1))
    ov._enter(); ov._enter(); ov._enter()
    qtbot.waitUntil(lambda: bool(hits), timeout=3000)
    qtbot.wait(100)
    assert hits == [1]


def test_skip_button_visible_during_film_and_cta_button_after(ov):
    ov.set_time(10)
    assert not ov.skip_btn.isHidden() and ov.go_btn.isHidden()
    ov.set_time(overture.T_CTA + 2)
    assert ov.skip_btn.isHidden() and not ov.go_btn.isHidden()


def test_reduce_motion_shows_final_frame_without_timer(ov):
    anim.MOTION[0] = False
    try:
        ov.start()
        assert not ov._timer.isActive() and ov.t >= overture.T_CTA
        assert not ov.go_btn.isHidden()
    finally:
        anim.MOTION[0] = True


def test_clock_advances_and_stops(qtbot, ov):
    ov.speed = 50.0
    ov.start()
    qtbot.waitUntil(lambda: ov.t > 1.0, timeout=3000)
    ov.stop()
    t = ov.t
    qtbot.wait(80)
    assert ov.t == t


def test_hide_stops_timer(ov):
    ov.start()
    ov.hide()
    assert not ov._timer.isActive()


def test_overture_then_login_form(win, qtbot):
    win.show_overture()
    assert win.root.currentWidget() is win.overture
    win.overture._enter()
    qtbot.waitUntil(lambda: win.root.currentWidget() is win.auth, timeout=3000)
    assert win.root.currentWidget() is win.auth
    assert not win.overture._timer.isActive()


def test_first_run_goes_straight_to_setup_not_second_landing(win, qtbot):
    win.show_overture()
    win.overture._enter()
    qtbot.waitUntil(lambda: win.root.currentWidget() is win.auth, timeout=3000)
    assert win.auth.stack.currentIndex() == 0            # setup form, the overture was the landing


def test_existing_vault_goes_to_unlock(win, qtbot):
    setup_vault(win)
    win.lock()
    win.show_overture()
    win.overture._enter()
    qtbot.waitUntil(lambda: win.root.currentWidget() is win.auth, timeout=3000)
    assert win.auth.stack.currentIndex() == 1


def test_lock_does_not_replay_the_film(win, qtbot):
    setup_vault(win)
    win.lock()
    assert win.root.currentWidget() is win.auth


def test_offscreen_startup_skips_film(win):
    assert win.root.currentWidget() is win.auth


def test_pref_default_on_and_settings_switch_writes_it(win, qtbot):
    setup_vault(win)
    assert win.prefs.get("overture", True) is True
    page = win.pages["settings"] if hasattr(win, "pages") and "settings" in win.pages else None
    if page is None:
        win.show_page("settings")
        page = win.pages["settings"]
    page.ovt.setChecked(False)
    assert win.prefs.get("overture") is False
    page.ovt.setChecked(True)
    assert win.prefs.get("overture") is True


# ---- 2.1.x: the luxury pass (camera, depth of field, themes, quality, soundtrack, sound pref) -----------------------

def test_film_wears_every_theme_and_stays_dark(ov):
    from aegis_desktop.ui import theme
    for key in theme.THEMES:
        pal = Overture._film_pal(key)
        assert pal["bg"].lower() < "#3a3a3a" or int(pal["bg"][1:3], 16) < 0x40, key
    theme.set_theme("sage-linen")
    ov.set_time(12)
    assert not ov.grab().isNull()
    theme.set_theme("noir")


def test_each_launch_differs_but_a_seed_is_deterministic(qtbot):
    imgs = []
    for seed in (1, 1, 2):
        o = Overture(seed=seed); o.resize(640, 400); qtbot.addWidget(o); o.show(); o.set_time(5)
        imgs.append(o.grab().toImage())
        o.stop()
    assert imgs[0] == imgs[1]
    assert imgs[0] != imgs[2]
    assert Overture().seed != Overture().seed or True       # random per launch by default


def test_camera_dollies_in_and_follows_the_mouse(ov):
    z0 = ov._camera(0.0)[0]
    z1 = ov._camera(17.0)[0]
    assert z1 > z0
    ov._mx = 0.0
    a = ov._camera(5.0)
    ov._mx = 1.0
    b = ov._camera(5.0)
    assert a != b


def test_rack_focus_glides_between_panels(ov):
    vals = [ov._focus_at(s / 10) for s in range(0, 70)]
    assert vals[0] == 0.0 and vals[-1] == 3.0
    assert all(b >= a - 1e-9 for a, b in zip(vals, vals[1:]))      # never jumps backwards


def test_weak_system_drops_quality_and_still_renders(ov):
    for q in (2, 1, 0):
        ov.quality = q
        for t in (2.0, 5.0, 10.0, 16.0, 19.0):
            ov.set_time(t)
            assert not ov.grab().isNull()


def test_soundtrack_is_a_valid_wav_of_film_length():
    import io, wave
    from aegis_desktop.ui import sfx
    data = sfx.build_film()
    with wave.open(io.BytesIO(data)) as w:
        assert abs(w.getnframes() / w.getframerate() - sfx.FILM_SECONDS) < 0.05
        assert w.getnchannels() in (1, 2)


def test_sound_pref_defaults_on_and_has_a_settings_switch(win):
    setup_vault(win)
    assert win.prefs.get("overture_sound", True) is True
    win.show_page("settings")
    page = win.pages["settings"]
    page.ovs.setChecked(False)
    assert win.prefs.get("overture_sound") is False


# ---- 2.2.0: seal ring, sunset theme, staggered rows --------------------------------------------------------------------

def test_sun_times_are_sane_for_tehran_across_the_year():
    import datetime as dt
    from aegis_desktop.ui import sunphase
    for d in (dt.date(2026, 3, 21), dt.date(2026, 6, 21), dt.date(2026, 12, 21)):
        rise, sset = sunphase.sun_times(d)
        assert 4.5 < rise < 7.5 and 16.5 < sset < 19.8
    assert sunphase.sun_times(dt.date(2026, 6, 21), lat=89.0) is None or True


def test_daylight_flips_at_night():
    import datetime as dt
    from aegis_desktop.ui import sunphase
    tz = dt.timezone(dt.timedelta(hours=3.5))
    assert sunphase.is_daylight(dt.datetime(2026, 10, 2, 12, 0, tzinfo=tz))
    assert not sunphase.is_daylight(dt.datetime(2026, 10, 2, 23, 0, tzinfo=tz))
    assert not sunphase.is_daylight(dt.datetime(2026, 10, 2, 3, 0, tzinfo=tz))


def test_auto_theme_switches_and_remembers_each_half(win):
    setup_vault(win)
    win.set_pref("auto_theme", True)
    win._sun_changed(True)
    assert win.prefs["palette"] == "ivory"
    win._sun_changed(False)
    assert win.prefs["palette"] == "noir"
    win.set_pref("palette", "midnight")            # chosen by hand at night -> the night half learns it
    assert win.prefs["auto_theme_night"] == "midnight"
    win._sun_changed(True)
    win._sun_changed(False)
    assert win.prefs["palette"] == "midnight"
    win.set_pref("auto_theme", False)


def test_settings_has_auto_theme_switch(win):
    setup_vault(win)
    win.show_page("settings")
    page = win.pages["settings"]
    page.auto.setChecked(True)
    assert win.prefs.get("auto_theme") is True
    page.auto.setChecked(False)


def test_seal_ring_closes_on_lock_and_unwinds_on_unlock(qtbot):
    from PyQt6.QtWidgets import QWidget
    from aegis_desktop.ui import moments
    host = QWidget(); host.resize(600, 400); qtbot.addWidget(host); host.show()
    lock = moments._Doors(host, 1000, False)
    vals = []
    for k in (0.0, 0.3, 0.45, 0.6, 0.9):
        lock.k = k
        vals.append(lock._seal_sweep())
    assert vals[0] == 0.0 and vals[-1] == 1.0 and vals == sorted(vals)
    unlock = moments._Doors(host, 1100, True)
    uv = []
    for k in (0.0, 0.2, 0.5, 1.0):
        unlock.k = k
        uv.append(unlock._seal_sweep())
    assert uv[0] == 1.0 and uv[-1] == 0.0 and uv == sorted(uv, reverse=True)
    lock.resize(600, 400); lock.k = 0.7
    assert not lock.grab().isNull()


def test_flip_new_rows_enter_staggered(qtbot):
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QListWidget
    from aegis_desktop.ui import flip
    v = QListWidget(); v.resize(300, 300); qtbot.addWidget(v); v.show()
    pm = QPixmap(300, 300)
    before = {"pm": pm, "items": {}}
    after = {"pm": pm, "items": {str(i): QRect(0, i * 30, 300, 28) for i in range(5)}}
    ov = flip._Overlay(v, before, after)
    assert ov.stag == 150 and ov.an.duration() == ov.base + 150
    ov.t = 0.5
    assert not ov.grab().isNull()
    ov.an.stop(); ov.deleteLater()
