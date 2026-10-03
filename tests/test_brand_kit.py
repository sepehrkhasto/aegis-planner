# SPDX-License-Identifier: GPL-3.0-or-later
"""the Aegis brand kit - Obsidian & gold theme as default, monogram, display face, grain, engraved lines, cards."""
import json

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PyQt6.QtTest import QTest

from aegis_desktop.ui import brand, theme
from aegis_desktop.ui.widgets import CardFrame, card
from test_gui import setup_vault, win  # noqa: F401


def test_signature_theme_is_default_and_the_brand_three_survive():
    assert theme.DEFAULT_THEME == "noir" == theme.SIGNATURE and theme.THEME_ORDER[0] == "noir"
    assert theme.THEMES["noir"]["en"] == "Aegis Noir" and theme.THEMES["ivory"]["fa"] == "عاج"
    assert theme.THEMES["aegis-light"]["mode"] == "light" and theme.THEMES["aegis-light"]["pal"]["accent"] == "#25262b"
    assert theme.THEME_DOTS == ["noir", "ivory", "aegis-light"]      # the curated ones live in Settings
    for k in theme.THEMES:                                       # every theme is a complete palette
        assert set(theme.THEMES[k]["pal"]) == set(theme.THEMES["noir"]["pal"])


def test_display_font_registers_and_metal_ramp(qapp):
    assert brand.load_display_font() == "Cormorant Garamond"
    assert "Cormorant Garamond" in QFontDatabase.families()
    stops = brand.gilt_stops(theme.THEMES["noir"]["pal"])
    assert [round(p, 2) for p, _ in stops] == sorted(round(p, 2) for p, _ in stops)
    assert stops[0][1].lightness() > stops[-1][1].lightness()     # bright shoulder -> deep base


def test_monogram_renders_crisply_at_every_size(qapp):
    pal = theme.THEMES["noir"]["pal"]
    seen = set()
    for s in (16, 24, 32, 64, 256):
        img = brand.render_mark(s, pal).toImage()
        assert img.width() == s
        seen.add(img.pixelColor(s // 2, int(s * 0.62)).rgb())
        assert img.pixelColor(0, 0).alpha() == 0                  # rounded tile: the corner is transparent
        c = img.pixelColor(s // 2, int(s * 0.60))
        assert c.alpha() > 200
    big = brand.render_mark(256, pal).toImage()
    rim = big.pixelColor(128, 2)                                  # the metal rim: bright against obsidian
    assert rim.lightness() > 120


def test_brand_assets_are_the_new_mark(qapp):
    from PIL import Image
    ico = Image.open(theme.asset_path("icon.ico"))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])
    px = QImage(str(theme.asset_path("icon.png")))
    assert px.width() == 512 and px.pixelColor(256, 8).lightness() > 100      # metal rim present


def test_grain_is_deterministic_dark_only_and_subtle(qapp):
    dark, light = theme.THEMES["noir"]["pal"], theme.THEMES["aegis-light"]["pal"]

    def paint(pal):
        img = QImage(120, 120, QImage.Format.Format_ARGB32)
        img.fill(QColor(pal["panel"]))
        p = QPainter(img)
        brand.paint_grain(p, QRectF(0, 0, 120, 120), pal)
        p.end()
        return img
    a, b = paint(dark), paint(dark)
    assert a == b
    ref = QColor(dark["panel"])
    diffs = [abs(a.pixelColor(x, y).lightness() - ref.lightness()) for x in range(0, 120, 3) for y in range(0, 120, 3)]
    assert max(diffs) <= 16 and 0 < sum(diffs) / len(diffs) <= 3                        # visible as texture, never as dirt
    flat = QImage(120, 120, QImage.Format.Format_ARGB32)
    flat.fill(QColor(light["panel"]))
    assert paint(light) == flat                                   # light themes stay clean


def test_engrave_line_has_a_dark_and_a_light_row(qtbot):
    ln = brand.EngraveLine()
    ln.setStyleSheet("background:#0e0d0b")
    qtbot.addWidget(ln)
    ln.resize(200, 2)
    img = ln.grab().toImage()
    assert ln.height() == 2 and img.pixelColor(100, 0).lightness() < img.pixelColor(100, 1).lightness() + 80
    assert img.pixelColor(100, 0) != img.pixelColor(100, 1)


def test_card_depth_and_crest_render_in_every_theme(win):
    f, _l = card()
    g = CardFrame(crest=True)
    assert f.property("crest") is False and g.property("crest") is True
    for f_ in (f, g):
        f_.resize(320, 120)
        f_.setParent(win.shell)
    for key in theme.THEME_ORDER:
        win.set_pref("palette", key)
        for f_ in (f, g):
            f_.show()
            assert not f_.grab().isNull()
    win.set_pref("palette", "coffee")
    f.show(); g.show()
    plain, crest = f.grab().toImage(), g.grab().toImage()
    assert plain != crest                                        # the corner ticks are really drawn
    f.deleteLater(); g.deleteLater()


def test_the_accent_is_scarce_on_every_page(win):
    """Colour is a signature, not a surface. With a chromatic accent (midnight blue) count accent-coloured pixels per page.
    (On Noir the accent is platinum = almost the text colour, so the rule is enforced on the chromatic variants.)"""
    setup_vault(win)
    win.set_pref("palette", "midnight")
    win.resize(1180, 760)
    acc = QColor(theme.PALETTES["dark"]["accent"])
    worst = (0.0, "")
    for k in win.pages:
        win.show_page(k)
        QTest.qWait(700)
        img = win.grab().toImage()
        n = hit = 0
        for y in range(0, img.height(), 3):
            for x in range(0, img.width(), 3):
                c = img.pixelColor(x, y)
                n += 1
                if abs(c.red() - acc.red()) + abs(c.green() - acc.green()) + abs(c.blue() - acc.blue()) < 70:
                    hit += 1
        worst = max(worst, (hit / n, k))
    assert worst[0] < 0.06, f"accent covers {worst[0]:.1%} of the {worst[1]} page"


def test_splash_and_lockup_widgets(qtbot, qapp):
    from aegis_desktop.ui.splash import _pixmap
    pm = _pixmap()
    assert not pm.isNull() and pm.width() == 1040
    wm = brand.Wordmark("AEGIS", 20)
    tg = brand.Tagline()
    for w in (wm, tg):
        qtbot.addWidget(w)
        w.resize(w.sizeHint().width() if w.width() < 10 else w.width(), w.height())
        w.resize(300, w.height())
        assert not w.grab().isNull()
    assert wm.width() > 60


def test_old_default_themes_migrate_once_to_noir(win, tmp_path):
    p = tmp_path / "p.json"
    win.prefs_path = p
    for old in ("aegis", "goldblack", "graphite", "obsidian", "noir-rose", "contrast"):      # themes removed in 2.1
        p.write_text(json.dumps({"palette": old}), encoding="utf-8")
        got = win._load_prefs()
        assert got["palette"] == "noir" and got["brand_theme_v"] == 2
    p.write_text(json.dumps({"palette": "ocean", "brand_theme_v": 2}), encoding="utf-8")
    assert win._load_prefs()["palette"] == "ocean"                # a deliberate later choice is respected


def test_sidebar_uses_the_display_face_and_frame(win):
    from aegis_desktop.ui.nav import SideFrame
    assert isinstance(win.side, SideFrame)
    assert "Cormorant Garamond" in win.styleSheet() or "Cormorant Garamond" in win.app.styleSheet()
