# SPDX-License-Identifier: GPL-3.0-or-later
"""card sheen, High-Contrast theme, What's new, accessible names, contrast ratios."""
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QAbstractButton

from aegis_desktop import __version__
from aegis_desktop.ui import theme
from aegis_desktop.ui.a11y import ensure_names
from aegis_desktop.ui.whatsnew import CHANGES, WhatsNew, notes_for
from aegis_desktop.ui.widgets import CardFrame, card
from test_gui import setup_vault, win  # noqa: F401


def _lum(c: str) -> float:
    q = QColor(c)
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(q.redF()) + 0.7152 * f(q.greenF()) + 0.0722 * f(q.blueF())


def ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_every_theme_keeps_readable_text():
    for k, t in theme.THEMES.items():
        p = t["pal"]
        assert ratio(p["text"], p["bg"]) >= 7, k
        assert ratio(p["muted"], p["bg"]) >= 4.5, k
        assert ratio(p["ink"], p["accent"]) >= 4.5, k


def test_new_themes_apply_and_sidebar_dots_survive(win):
    setup_vault(win)
    win.set_pref("palette", "sage-forest")
    assert win.theme == "dark"
    assert win.theme_dots.cur == win.theme_dots.order[0]                    # not in the capsule: no dot claims it
    for k in win.pages:
        win.show_page(k); QTest.qWait(30)
        assert not win.pages[k].grab().isNull()
    st = win.pages["settings"]; st.refresh()
    assert "sage-forest" in st.picker.cards


def test_card_sheen_paints_on_dark_and_light(win):
    setup_vault(win)
    f, _l = card()
    assert isinstance(f, CardFrame)
    f.resize(300, 100)
    for pref in ("ivory", "aegis-light", "sunset"):
        win.set_pref("palette", pref)
        f.setParent(win.shell); f.show()
        assert not f.grab().isNull()
    f.deleteLater()


def test_version_and_whatsnew(win):
    assert __version__ == "2.11.10" and notes_for(__version__) and len(CHANGES[__version__]) >= 2
    setup_vault(win)
    d = WhatsNew(win)
    assert not d.grab().isNull()
    d.accept()
    assert win.prefs["seen_version"] == __version__
    assert notes_for("0.0.1") == []


def test_all_buttons_have_spoken_names(win):
    setup_vault(win)
    for k in win.pages:
        win.show_page(k); QTest.qWait(40)
    ensure_names(win)
    bad = [type(b).__name__ for b in win.findChildren(QAbstractButton)
           if not (b.accessibleName() or b.text().strip() or b.objectName().startswith("qt_"))]
    assert not bad, bad
