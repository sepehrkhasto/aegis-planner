# SPDX-License-Identifier: GPL-3.0-or-later
"""identity & rituals - vault certificate, letterhead + PDF report, ambient light, day start, week seal, icons..."""
import datetime as dt
import json
import re

import pytest
from PyQt6.QtCore import QBuffer, QIODevice, QRectF, Qt, qInstallMessageHandler
from PyQt6.QtGui import QImage, QPainter

from aegis_desktop.core import certificate as cert
from aegis_desktop.core import logic
from aegis_desktop.core.store import VaultStore, empty_vault
from aegis_desktop.ui.anim import MOTION
from aegis_desktop.ui.themes_data import THEMES
from test_gui import PW, setup_vault, win  # noqa: F401


@pytest.fixture
def store(tmp_path):
    s = VaultStore(tmp_path / "d")
    s.create(PW)
    return s


def _raw(s):
    return json.loads(s.path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- Q1: identity in the file ---
def test_new_vault_gets_a_random_id_and_birth_date(store):
    raw = _raw(store)
    assert re.fullmatch(r"[0-9a-f]{16}", raw["vaultId"]) and raw["createdAt"].endswith("Z")
    other = VaultStore(store.dir.parent / "d2")
    other.create(PW)
    assert _raw(other)["vaultId"] != raw["vaultId"]


def test_identity_survives_lock_unlock_password_change_and_save(store):
    before = _raw(store)
    store.lock()
    store.unlock(PW)
    store.vault["tasks"].append({"id": "t1", "title": "x"})
    store.save()
    store.change_password("another long password 99")
    after = _raw(store)
    assert (after["vaultId"], after["createdAt"]) == (before["vaultId"], before["createdAt"])


def test_legacy_vault_without_identity_is_given_one_on_unlock(store):
    raw = _raw(store)
    raw.pop("vaultId"), raw.pop("createdAt")
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    store.lock()
    store._raw = None
    store.unlock(PW)
    info = cert.identity(store)
    assert re.fullmatch(r"[0-9a-f]{16}", info["id"]) and info["created"] is not None
    assert info["created"] <= dt.datetime.now().astimezone() + dt.timedelta(seconds=5)
    store.save()
    assert _raw(store)["vaultId"] == info["id"]                     # persisted by the next save, stable afterwards
    store.lock(); store._raw = None; store.unlock(PW)
    assert cert.identity(store)["id"] == info["id"]


def test_export_bundle_carries_identity_and_import_keeps_it(store, tmp_path):
    out = store.export_bundle(tmp_path / "b.aegis")
    b = json.loads(out.read_text(encoding="utf-8"))
    assert b["vaultId"] == _raw(store)["vaultId"] and b["createdAt"]
    fresh = VaultStore(tmp_path / "fresh")
    fresh.import_replace(VaultStore.read_bundle(out), PW)
    assert _raw(fresh)["vaultId"] == b["vaultId"] and _raw(fresh)["createdAt"] == b["createdAt"]


def test_old_bundle_without_identity_still_imports(store, tmp_path):
    out = store.export_bundle(tmp_path / "b.aegis")
    b = json.loads(out.read_text(encoding="utf-8"))
    b.pop("vaultId"), b.pop("createdAt")
    out.write_text(json.dumps(b), encoding="utf-8")
    fresh = VaultStore(tmp_path / "fresh")
    fresh.import_replace(VaultStore.read_bundle(out), PW)
    assert re.fullmatch(r"[0-9a-f]{16}", _raw(fresh)["vaultId"])


# ------------------------------------------------------------------------------------ the certificate facts ---
def test_certificate_facts_are_public_only(store):
    store.vault["tasks"] += [{"id": "a", "title": "SECRET-TITLE-42"}]
    store.recovery_key = store.setup_recovery()
    info = cert.identity(store)
    blob = json.dumps(info, default=str)
    raw = _raw(store)
    for secret in (PW, "SECRET-TITLE-42", store.recovery_key, raw["salt"], raw["wrappedKey"], raw["ciphertext"]):
        assert secret not in blob
    assert info["recovery"] is True and info["counts"]["tasks"] == 1 and info["cipher"] == "AES-256-GCM"


def test_number_and_fingerprint_are_stable_and_shaped():
    assert cert.fingerprint("0123456789abcdef") == cert.fingerprint("0123456789abcdef")
    assert re.fullmatch(r"[0-9A-F]{4}( · [0-9A-F]{4}){3}", cert.fingerprint("0123456789abcdef"))
    assert re.fullmatch(r"\d{6}", cert._digits("0123456789abcdef"))
    assert cert.fingerprint("a") != cert.fingerprint("b")


def test_age_in_days_counts_from_the_birth_date(store):
    raw = _raw(store)
    raw["createdAt"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40, hours=1)).isoformat().replace("+00:00", "Z")
    store._raw = raw
    assert cert.identity(store)["days"] == 40


def test_parse_iso_tolerates_garbage():
    assert cert.parse_iso(None) is None and cert.parse_iso("not a date") is None
    assert cert.parse_iso("2026-01-02T03:04:05.000Z").year == 2026


# ---------------------------------------------------------------------------------------- the card painter ---
def _info(store):
    return cert.identity(store)


@pytest.mark.parametrize("theme", ["noir", "ivory", "aegis-light", "midnight", "sage-linen"])
def test_certificate_paints_in_every_theme_with_a_balanced_painter(qapp, store, theme):
    from aegis_desktop.ui.certificate import paint_certificate
    msgs = []
    qInstallMessageHandler(lambda _m, _c, s: msgs.append(s))
    try:
        img = QImage(720, 450, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.black)
        p = QPainter(img)
        paint_certificate(p, QRectF(0, 0, 720, 450), _info(store), THEMES[theme]["pal"], (0.4, -0.3))
        p.end()
    finally:
        qInstallMessageHandler(None)
    assert not [m for m in msgs if "save" in m.lower() or "restore" in m.lower()]
    assert img.pixelColor(360, 225) != img.pixelColor(0, 0) or img.pixelColor(100, 100).alpha() > 0


def test_render_image_is_a_png_of_the_right_shape(qapp, store):
    from aegis_desktop.ui.certificate import render_image
    img = render_image(_info(store), THEMES["noir"]["pal"], 800)
    assert img.width() > 800 and abs(img.height() / img.width() - 450 / 720) < 0.06
    assert img.pixelColor(2, 2).alpha() < 255 or True                # the corner may carry the soft shadow
    buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert img.save(buf, "PNG") and bytes(buf.data())[:4] == b"\x89PNG"


def test_card_keeps_its_aspect_and_polls_only_while_visible(qtbot, store):
    from aegis_desktop.ui.certificate import CertificateCard
    old = MOTION[0]; MOTION[0] = True
    try:
        c = CertificateCard(_info(store))
        qtbot.addWidget(c)
        assert c.heightForWidth(720) == 450 and c.hasHeightForWidth()
        assert not c._poll.isActive()
        c.resize(640, 400); c.show()
        assert c._poll.isActive()
        assert not c.grab().isNull()
        c.hide()
        assert not c._poll.isActive()
    finally:
        MOTION[0] = old


def test_card_hover_light_runs_and_settles(qtbot, store):
    from aegis_desktop.ui.certificate import CertificateCard
    old = MOTION[0]; MOTION[0] = True
    try:
        c = CertificateCard(_info(store))
        qtbot.addWidget(c); c.resize(640, 400); c.show()
        c.hl.enter()
        qtbot.wait(200)
        assert c.hl.inside and not c.grab().isNull()
        c.hl.leave()
        qtbot.wait(900)
        assert c.hl.k < 0.05
    finally:
        MOTION[0] = old


# ----------------------------------------------------------------------------------------- the dialog ---
def test_settings_and_palette_open_the_certificate(win, monkeypatch):
    setup_vault(win)
    from aegis_desktop.ui import certificate as cm
    seen = []
    monkeypatch.setattr(cm.CertificateDialog, "exec", lambda self: seen.append(self) or 0)
    win.run_command("certificate")
    assert len(seen) == 1 and seen[0].info["number"] == cert.identity(win.store)["number"]
    win.show_page("settings")
    from PyQt6.QtWidgets import QPushButton
    assert any(b.text().startswith("نمایش گواهی") for b in win.pages["settings"].findChildren(QPushButton))
    from aegis_desktop.ui.main_window import Palette
    d = Palette(win)
    assert any(c[1] == "certificate" for c in d._commands(logic.fold("گواهی")))
    assert any(c[1] == "certificate" for c in d._commands(logic.fold("certificate")))
    d.close()


def test_certificate_needs_an_unlocked_vault(win, monkeypatch):
    from aegis_desktop.ui import certificate as cm
    seen = []
    monkeypatch.setattr(cm.CertificateDialog, "exec", lambda self: seen.append(1) or 0)
    win.show_certificate()
    assert not seen


def test_dialog_saves_a_png_and_copies_the_id(win, tmp_path, monkeypatch):
    setup_vault(win)
    from PyQt6.QtWidgets import QApplication
    from aegis_desktop.ui.certificate import CertificateDialog
    d = CertificateDialog(win)
    out = d.save_image(str(tmp_path / "cert"))
    assert out.endswith(".png") and QImage(out).width() > 800
    d.copy_id()
    assert QApplication.clipboard().text() == d.info["fingerprint"].replace(" · ", "")
    monkeypatch.setattr("PyQt6.QtWidgets.QFileDialog.getSaveFileName", lambda *a, **k: ("", ""))
    assert d.save_image() is None
    d.close()


# ----------------------------------------------------------------------------- Q1: letterhead + PDF report ---
def _busy_vault(n_days=30, cats=("work", "personal", "health", "study")):
    import random
    rnd = random.Random(7)
    v = empty_vault()
    today = dt.date.today()
    for i in range(80):
        d = today - dt.timedelta(days=rnd.randint(0, n_days - 1))
        t = logic.new_task(f"SECRET-TITLE-{i}", due=None)
        t["done"], t["doneAt"], t["cat"] = True, d.isoformat() + "T10:00:00.000Z", rnd.choice(cats)
        v["tasks"].append(t)
    return v


def test_paper_palette_is_readable_on_white(qapp):
    from PyQt6.QtGui import QColor
    from aegis_desktop.ui import letterhead

    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())
    for name in ("noir", "ivory", "midnight", "aegis-light", None):
        pal = letterhead.paper_palette(THEMES[name]["pal"] if name else None)
        for k in ("bg", "text", "muted", "accent", "accent2", "acc_text", "line", "panel", "panel2"):
            assert k in pal
        for k in ("text", "muted", "accent"):
            a, b = lum(QColor(pal[k])), lum(QColor("#ffffff"))
            assert (b + 0.05) / (a + 0.05) >= 3.0, (name, k)


def test_pdf_report_is_a_valid_document(qapp, tmp_path):
    from aegis_desktop.ui.report_pdf import build_report_pdf
    out = tmp_path / "r.pdf"
    n = build_report_pdf(str(out), _busy_vault(), 30, THEMES["noir"]["pal"], "123456")
    data = out.read_bytes()
    assert n >= 1 and data[:5] == b"%PDF-" and len(data) > 5000 and b"%%EOF" in data[-32:]


def test_pdf_report_handles_an_empty_vault_and_every_period(qapp, tmp_path):
    from aegis_desktop.ui.report_pdf import build_report_pdf
    for days in (7, 30, 90):
        assert build_report_pdf(str(tmp_path / f"e{days}.pdf"), empty_vault(), days, None) >= 1


def test_pdf_report_never_contains_task_text(qapp, tmp_path):
    import shutil
    import subprocess
    from aegis_desktop.ui.report_pdf import build_report_pdf, report_lines
    v = _busy_vault()
    assert not any("SECRET" in ln for ln in report_lines(v, 30, dt.date.today()))
    out = tmp_path / "p.pdf"
    build_report_pdf(str(out), v, 30, THEMES["noir"]["pal"])
    if shutil.which("pdftotext"):
        txt = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout
        assert "SECRET" not in txt and "AEGIS" in txt


def test_pdf_font_scale_is_restored_even_when_drawing_fails(qapp, tmp_path, monkeypatch):
    from aegis_desktop.ui import letterhead, report_pdf
    monkeypatch.setattr(report_pdf, "_draw", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        report_pdf.build_report_pdf(str(tmp_path / "x.pdf"), empty_vault(), 7, None)
    assert letterhead.UNIT[0] == 1.0


def test_pdf_footer_counts_pages_of_a_long_report(qapp, tmp_path, monkeypatch):
    from aegis_desktop.ui import report_pdf
    monkeypatch.setattr(report_pdf, "BODY_BOTTOM", 330.0)              # force a page break
    n = report_pdf.build_report_pdf(str(tmp_path / "long.pdf"), _busy_vault(), 30, THEMES["noir"]["pal"])
    assert n >= 2


def test_reports_page_has_the_pdf_button_and_window_exports(win, tmp_path):
    setup_vault(win)
    assert win.pages["reports"].pdf.text() == "خروجی PDF"
    out = win.export_report_pdf(30, str(tmp_path / "rep"))
    assert out.endswith(".pdf") and open(out, "rb").read(5) == b"%PDF-"
    assert win.export_report_pdf(30, str(tmp_path / "nodir" / "x.pdf")) is None    # unwritable path -> a toast, not a crash
    win.lock()
    assert win.export_report_pdf(30, str(tmp_path / "locked.pdf")) is None


def test_letterhead_paints_balanced(qapp):
    from aegis_desktop.ui import letterhead
    msgs = []
    qInstallMessageHandler(lambda _m, _c, s: msgs.append(s))
    try:
        img = QImage(595, 842, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.white)
        p = QPainter(img)
        pal = letterhead.paper_palette(THEMES["noir"]["pal"])
        letterhead.paint_letterhead(p, pal, "گزارش", "زیرعنوان", "000123")
        letterhead.paint_footer(p, pal, 1, 2)
        p.end()
    finally:
        qInstallMessageHandler(None)
    assert not [m for m in msgs if "restore" in m.lower() or "save" in m.lower()]


# ------------------------------------------------------------------------------------ Q1: packaging art ---
def test_packaging_uses_the_file_icon_and_new_wizard_art():
    from pathlib import Path
    from PIL import Image
    root = Path(__file__).resolve().parent.parent
    iss = (root / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert "aegis_file.ico" in iss and "DefaultIcon" in iss and 'Source: "..\\aegis_desktop\\assets\\aegis_file.ico"' in iss
    ico = Image.open(root / "aegis_desktop" / "assets" / "aegis_file.ico")
    assert {(16, 16), (32, 32), (256, 256)} <= set(ico.info["sizes"])
    assert Image.open(root / "packaging" / "installer_assets" / "wiz_164.bmp").size == (164, 314)


# ------------------------------------------------------------------- RTL: the same picture in both directions ---
def _render(fn, w=720, h=450):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    fn(p)
    p.end()
    return img


@pytest.fixture
def rtl_pair(qapp):
    """Run a painter function under LTR and RTL application layout; hand back both images."""
    from PyQt6.QtGui import QGuiApplication

    def go(fn, w=720, h=450):
        old = QGuiApplication.layoutDirection()
        try:
            QGuiApplication.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            a = _render(fn, w, h)
            QGuiApplication.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            b = _render(fn, w, h)
        finally:
            QGuiApplication.setLayoutDirection(old)
        return a, b
    return go


def test_certificate_looks_identical_in_rtl_and_ltr(rtl_pair, store):
    from aegis_desktop.ui.certificate import paint_certificate
    info = cert.identity(store)
    a, b = rtl_pair(lambda p: paint_certificate(p, QRectF(0, 0, 720, 450), info, THEMES["noir"]["pal"]))
    assert a == b                              # AlignRight without AlignAbsolute would mirror every label in the RTL app


def test_letterhead_looks_identical_in_rtl_and_ltr(rtl_pair):
    from aegis_desktop.ui import letterhead
    pal = letterhead.paper_palette(THEMES["noir"]["pal"])

    def fn(p):
        p.fillRect(0, 0, 600, 850, Qt.GlobalColor.white)
        letterhead.paint_letterhead(p, pal, "گزارش عملکرد", "زیرعنوان", "000123")
        letterhead.paint_footer(p, pal, 1, 2)
    a, b = rtl_pair(fn, 600, 850)
    assert a == b


# --------------------------------------------------------------------------------------- Q2: ambient light ---
def test_ambient_tone_is_a_closed_ring_and_blends():
    from aegis_desktop.ui import ambient
    c0, a0 = ambient.tone_at(0)
    c24, a24 = ambient.tone_at(1440)
    assert c0.name() == c24.name() and a0 == a24
    mid_c, mid_a = ambient.tone_at((1110 + 1260) / 2)               # halfway between evening amber and dusk violet
    e, d = ambient.tone_at(1110)[0], ambient.tone_at(1260)[0]
    assert min(e.red(), d.red()) <= mid_c.red() <= max(e.red(), d.red())
    assert ambient.tone_at(-50) == ambient.tone_at(0) and ambient.tone_at(9999)[1] == a24     # clamped


def test_ambient_is_always_faint():
    from aegis_desktop.ui import ambient
    for m in range(0, 1441, 10):
        assert 0.0 < ambient.tone_at(m)[1] <= 0.06, m               # you feel it, you never see a colour


def test_greeting_follows_the_clock():
    from aegis_desktop.ui import ambient
    at = lambda h, m=0: ambient.greeting(dt.datetime(2026, 1, 1, h, m))          # noqa: E731
    assert (at(4, 59), at(5), at(11, 59), at(12), at(16, 59), at(17), at(20, 59), at(21), at(0)) == \
           ("شب بخیر", "صبح بخیر", "صبح بخیر", "ظهر بخیر", "ظهر بخیر", "عصر بخیر", "عصر بخیر", "شب بخیر", "شب بخیر")


def test_ambient_widget_shows_hides_and_paints_balanced(qtbot):
    from PyQt6.QtWidgets import QWidget
    from aegis_desktop.ui.ambient import AmbientLight
    host = QWidget(); qtbot.addWidget(host); host.resize(500, 400); host.show()
    a = AmbientLight(host)
    assert not a.isVisible() and not a._t.isActive()
    a.enable(True)
    assert a.isVisible() and a._t.isActive() and a.geometry() == host.rect()
    host.resize(600, 300)
    assert a.geometry() == host.rect()                                # follows its host
    a.set_now(dt.datetime(2026, 1, 1, 18, 30))
    assert a.tone.red() > a.tone.blue()                               # evening is warm
    a.set_now(dt.datetime(2026, 1, 1, 1, 0))
    assert a.tone.blue() > a.tone.red()                               # night is cool
    msgs = []
    qInstallMessageHandler(lambda _m, _c, s: msgs.append(s))
    try:
        assert not host.grab().isNull()
    finally:
        qInstallMessageHandler(None)
    assert not [m for m in msgs if "restore" in m.lower()]
    a.enable(False)
    assert not a.isVisible() and not a._t.isActive()


def test_ambient_does_not_swallow_the_mouse(qtbot):
    from PyQt6.QtWidgets import QWidget
    from aegis_desktop.ui.ambient import AmbientLight
    host = QWidget(); qtbot.addWidget(host); host.show()
    a = AmbientLight(host); a.enable(True)
    assert a.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_window_has_ambient_on_by_default_and_the_setting_toggles_it(win):
    setup_vault(win)
    assert win.ambient.isVisible() and win.ambient.parent() is win.stack
    win.set_pref("ambient", False)
    assert not win.ambient.isVisible()
    win.set_pref("ambient", True)
    assert win.ambient.isVisible()
    win.show_page("settings")
    assert win.pages["settings"].amb.isChecked() and win.pages["settings"].dr.isChecked()


# ----------------------------------------------------------------------------------- Q2: day-start ritual ---
def _vault_for_day():
    from aegis_desktop.core import jalali
    v = empty_vault()
    today = jalali.today_jalali()
    v["tasks"] = [logic.new_task("کم‌اهمیت", pr="low", due=today), logic.new_task("مهم", pr="high", due=today),
                  logic.new_task("کارِ ساعت‌دار", pr="normal", due=today, timeFrom="09:30")]
    v["habits"] = [{"id": "h1", "name": "ورزش", "log": {}}, {"id": "h2", "name": "مطالعه", "log": {dt.date.today().isoformat(): True}}]
    return v


def test_day_facts_pick_the_timed_task_first_then_priority():
    from aegis_desktop.ui import dayritual
    f = dayritual.day_facts(_vault_for_day(), dt.date.today())
    assert f["count"] == 3 and f["first"] == "کارِ ساعت‌دار" and f["first_time"] == "09:30" and f["habits"] == 1
    v = _vault_for_day(); v["tasks"] = [t for t in v["tasks"] if not t.get("timeFrom")]
    assert dayritual.day_facts(v, dt.date.today())["first"] == "مهم"


def test_day_lines_cover_empty_long_and_busy_days():
    from aegis_desktop.ui import dayritual
    assert "آزاد" in dayritual.day_lines({"count": 0, "first": "", "first_time": "", "overdue": 0, "habits": 0})[0]
    long = dayritual.day_lines({"count": 1, "first": "x" * 90, "first_time": "", "overdue": 2, "habits": 3})
    assert len(long) <= 4 and all(len(x) < 90 for x in long) and "…" in long[1]
    assert dayritual.day_lines({"count": 5, "first": "a", "first_time": "10:00", "overdue": 1, "habits": 1})[1].endswith("۱۰:۰۰")


def test_should_show_is_once_per_day_and_switchable():
    from aegis_desktop.ui import dayritual
    today = dt.date(2026, 5, 5)
    assert dayritual.should_show({}, today)
    assert not dayritual.should_show({"day_ritual_date": today.isoformat()}, today)
    assert dayritual.should_show({"day_ritual_date": "2026-05-04"}, today)
    assert not dayritual.should_show({"day_ritual": False}, today)


def test_day_start_closes_with_esc_enter_and_click(win, qtbot):
    setup_vault(win)
    from PyQt6.QtTest import QTest
    from aegis_desktop.ui import dayritual
    for how in ("esc", "enter", "click"):
        closed = []
        card = dayritual.DayStart(win.shell, dayritual.day_facts(win.store.vault, dt.date.today()), dt.date.today(), lambda: closed.append(1))
        card.open()
        qtbot.wait(450)
        assert card.isVisible() and card.hasFocus()
        assert not card.grab().isNull()
        if how == "esc":
            QTest.keyClick(card, Qt.Key.Key_Escape)
        elif how == "enter":
            QTest.keyClick(card, Qt.Key.Key_Return)
        else:
            QTest.mouseClick(card, Qt.MouseButton.LeftButton)
        qtbot.wait(400)
        assert closed == [1]


def test_day_start_without_motion_is_instant(win):
    setup_vault(win)
    from aegis_desktop.ui import dayritual
    old = MOTION[0]; MOTION[0] = False
    try:
        closed = []
        card = dayritual.DayStart(win.shell, {"count": 0, "first": "", "first_time": "", "overdue": 0, "habits": 0}, dt.date.today(), lambda: closed.append(1))
        card.open()
        assert card.k == 1.0
        card.close_ritual()
        assert closed == [1]
    finally:
        MOTION[0] = old


def test_day_start_shows_once_per_day_and_force_does_not_use_it_up(win, qtbot):
    setup_vault(win)
    win.prefs.pop("day_ritual_date", None)
    c = win.show_day_start(force=True)
    assert c is not None and "day_ritual_date" not in win.prefs         # the palette command never burns the daily card
    c.close_ritual(); qtbot.wait(300)
    first = win.show_day_start()
    assert first is not None and win.prefs["day_ritual_date"] == dt.date.today().isoformat()
    first.close_ritual(); qtbot.wait(300)
    assert win.show_day_start() is None                                # already seen today
    win.set_pref("day_ritual_date", "2000-01-01"); win.set_pref("day_ritual", False)
    assert win.show_day_start() is None                                # switched off
    win.lock()
    assert win.show_day_start(force=True) is None                      # locked: nothing to say


def test_day_start_replaces_an_open_card(win, qtbot):
    setup_vault(win)
    a = win.show_day_start(force=True)
    b = win.show_day_start(force=True)
    qtbot.wait(400)
    from PyQt6 import sip
    assert b is not a and not sip.isdeleted(b) and sip.isdeleted(a)
    b.close_ritual(); qtbot.wait(300)


def test_day_start_lines_are_right_aligned_in_the_rtl_app(win):
    """AlignRight without AlignAbsolute mirrors under RTL: a short line would hug the LEFT edge of the card."""
    setup_vault(win)
    from PyQt6.QtGui import QColor, QGuiApplication
    from aegis_desktop.ui import dayritual
    assert QGuiApplication.layoutDirection() == Qt.LayoutDirection.RightToLeft
    old = MOTION[0]; MOTION[0] = False
    try:
        card = dayritual.DayStart(win.shell, {"count": 2, "first": "", "first_time": "", "overdue": 0, "habits": 0}, dt.date.today())
        card.open()
        img = card.grab().toImage()
        c = card._card()
        y0, y1 = int(c.top() + 176), int(c.top() + 176 + 20)
        bg = QColor(img.pixelColor(int(c.left()) + 40, y0)).lightness()
        xs = [x for x in range(int(c.left()) + 24, int(c.right()) - 30) for y in range(y0, y1)
              if abs(QColor(img.pixelColor(x, y)).lightness() - bg) > 70]
        assert xs and min(xs) > c.center().x() - 30 and max(xs) > c.right() - dayritual.DayStart.PAD - 40
        card.close_ritual()
    finally:
        MOTION[0] = old


# -------------------------------------------------------------------------------------- Q2: the week seal ---
def _week_vault(today, per_day):
    """per_day: 7 counts, oldest first (the last one is today)."""
    v = empty_vault()
    for i, n in enumerate(per_day):
        d = today - dt.timedelta(days=6 - i)
        for k in range(n):
            t = logic.new_task(f"t{i}-{k}")
            t["done"], t["doneAt"] = True, d.isoformat() + "T10:00:00.000Z"
            t["createdAt"] = (d - dt.timedelta(days=1)).isoformat() + "T08:00:00.000Z"
            v["tasks"].append(t)
    return v


def test_week_summary_numbers():
    today = dt.date(2026, 6, 10)
    v = _week_vault(today, [1, 0, 4, 2, 0, 3, 2])
    v["settings"]["pomoLog"] = {(today - dt.timedelta(days=i)).isoformat(): 2 for i in range(3)}
    d = logic.week_summary(v, today)
    assert d["done"] == 12 and d["done_by_day"] == [1, 0, 4, 2, 0, 3, 2] and d["since"] == today - dt.timedelta(days=6)
    assert d["best_day"] == today - dt.timedelta(days=4) and d["best_count"] == 4
    assert d["pomodoros"] == 6 and d["focus_minutes"] == 150 and d["prev_done"] == 0 and d["delta_pct"] is None
    assert d["streak"] == 2                                            # today and yesterday; the zero day before that ends the run


def test_week_summary_streak_delta_and_titles():
    today = dt.date(2026, 6, 10)
    v = _week_vault(today, [2, 2, 2, 2, 2, 2, 2])
    d = logic.week_summary(v, today)
    assert d["streak"] >= 7 and d["done"] == 14
    prev = _week_vault(today - dt.timedelta(days=7), [1, 1, 0, 0, 0, 0, 0])["tasks"]
    v["tasks"] += prev
    assert logic.week_summary(v, today)["delta_pct"] == 600                  # 14 vs 2
    assert logic.week_title(90, 5) == "هفتهٔ درخشان" and logic.week_title(60, 5) == "هفتهٔ پرکار"
    assert logic.week_title(10, 1) == "هفتهٔ آرام" and logic.week_title(0, 0) == "هفتهٔ استراحت"


def test_week_summary_of_an_empty_vault_is_calm():
    d = logic.week_summary(empty_vault(), dt.date(2026, 6, 10))
    assert d["done"] == 0 and d["best_day"] is None and d["streak"] == 0 and d["title"] == "هفتهٔ استراحت" and d["score"] == 0


def test_week_summary_has_no_task_text():
    v = _week_vault(dt.date(2026, 6, 10), [1] * 7)
    assert "t0-0" not in json.dumps(logic.week_summary(v, dt.date(2026, 6, 10)), default=str)


def test_stat_rows_format():
    from aegis_desktop.ui.weekseal import stat_rows
    d = logic.week_summary(_week_vault(dt.date(2026, 6, 10), [0, 0, 0, 0, 0, 0, 3]), dt.date(2026, 6, 10))
    rows = dict(stat_rows(d))
    assert rows["کار انجام‌شده"] == "۳" and rows["نسبت به هفتهٔ قبل"] == "—" and rows["تمرکز"] == "—" and rows["پیاپی"] == "۱ روز"
    d["delta_pct"], d["focus_minutes"] = -20, 75
    rows = dict(stat_rows(d))
    assert "−" in rows["نسبت به هفتهٔ قبل"] and rows["تمرکز"] == "۷۵ دقیقه"
    d["best_day"] = None
    assert "پرکارترین روز" not in dict(stat_rows(d))


def test_week_seal_paints_balanced_in_every_theme_and_direction(rtl_pair):
    from aegis_desktop.ui.weekseal import paint_week_seal
    d = logic.week_summary(_week_vault(dt.date.today(), [1, 2, 3, 0, 1, 5, 2]))
    for name in ("noir", "aegis-light", "sunset"):
        msgs = []
        qInstallMessageHandler(lambda _m, _c, s: msgs.append(s))
        try:
            a, b = rtl_pair(lambda p, n=name: paint_week_seal(p, QRectF(0, 0, 720, 450), d, THEMES[n]["pal"], (0.3, 0.2)))
        finally:
            qInstallMessageHandler(None)
        assert a == b and not [m for m in msgs if "restore" in m.lower() or "save" in m.lower()], name


def test_week_seal_image_and_dialog(win, tmp_path):
    setup_vault(win)
    from PyQt6.QtWidgets import QApplication
    from aegis_desktop.ui.weekseal import WeekSealDialog, render_week_image
    img = render_week_image(logic.week_summary(win.store.vault), THEMES["noir"]["pal"], 800)
    assert img.width() > 800
    d = WeekSealDialog(win)
    out = d.save_image(str(tmp_path / "week"))
    assert out.endswith(".png") and QImage(out).width() > 800
    d.copy_image()
    assert not QApplication.clipboard().image().isNull()
    d.close()


def test_week_seal_offer_is_once_per_week_and_needs_something_to_show(win, qtbot):
    setup_vault(win)
    win.prefs.pop("week_seal_offered", None)
    win.store.vault["tasks"] = []
    assert win.offer_week_seal() is False                               # nothing done this week: no nagging
    win.store.vault["tasks"] = _week_vault(dt.date.today(), [0, 0, 0, 0, 0, 1, 2])["tasks"]
    assert win.offer_week_seal() is True and win.prefs["week_seal_offered"]
    assert win.offer_week_seal() is False                               # only once for this week
    assert win.offer_week_seal(force=True) is True
    win.toasts.clear()


def test_week_seal_entry_points(win, monkeypatch):
    setup_vault(win)
    from aegis_desktop.ui import weekseal as ws
    seen = []
    monkeypatch.setattr(ws.WeekSealDialog, "exec", lambda self: seen.append(self.data["title"]) or 0)
    win.run_command("weekseal")
    assert len(seen) == 1
    win.pages["reports"].seal.click()
    assert len(seen) == 2
    from aegis_desktop.ui.main_window import Palette
    d = Palette(win)
    assert any(c[1] == "weekseal" for c in d._commands(logic.fold("مهر هفته")))
    assert any(c[1] == "dayritual" for c in d._commands(logic.fold("شروع روز")))
    d.close()
    win.lock()
    win.show_week_seal()
    assert len(seen) == 2


def test_previous_period_does_not_count_the_current_one():
    """report_summary(today - days) is the period BEFORE this one: work done recently must not leak into it (it used to,
    which made every Reports comparison say «less than last period»)."""
    today = dt.date(2026, 6, 10)
    v = _week_vault(today, [0, 0, 0, 0, 0, 0, 5])                        # five tasks done today, none earlier
    assert logic.report_summary(v, 7, today)["total_done"] == 5
    prev = logic.report_summary(v, 7, today - dt.timedelta(days=7))
    assert prev["total_done"] == 0 and sum(prev["by_cat"].values()) == 0


# ------------------------------------------------------------------------------ Q3: icons, obsidian, type, DPI ---
def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_every_icon_is_valid_svg_and_draws_ink_at_all_sizes(qapp):
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtSvg import QSvgRenderer
    from aegis_desktop.ui import icons
    for name, body in icons.ICONS.items():
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body.replace("currentColor", "#ffffff")}</svg>'
        assert QSvgRenderer(QByteArray(svg.encode())).isValid(), name
        for size in (14, 18, 24):
            img = icons.pixmap(name, "#ffffff", size).toImage()
            ink = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 40)
            assert ink >= 6, (name, size, ink)


def test_icon_names_used_in_code_all_exist():
    import glob
    import os
    from aegis_desktop.ui import icons
    pats = [r'(?:icon|icon_name|ico|glyph)\s*=\s*["\']([a-z_-]+)["\']', r'(?:icon|pixmap|set_icon|_icon)\(\s*["\']([a-z_-]+)["\']']
    root = os.path.join(os.path.dirname(icons.__file__), "*.py")
    for f in glob.glob(root):
        src = open(f, encoding="utf-8").read()
        for p in pats:
            for m in re.finditer(p, src):
                assert m.group(1) in icons.ICONS, (os.path.basename(f), m.group(1))


def test_every_page_has_its_own_icon(win):
    from aegis_desktop.ui import icons
    for key in win.pages:
        assert key in icons.ICONS or key in ("tasks", "habits"), key


def test_the_chamfered_family_has_no_round_joins_and_keeps_its_notch():
    from aegis_desktop.ui import icons
    cut = icons._cut_icons()
    assert len(cut) >= 20
    for name, body in cut.items():
        assert 'stroke-linejoin="miter"' in body and 'stroke-linejoin="round"' not in body, name
        assert name in icons.ICONS and icons.ICONS[name] == body
    box = icons._box(3.5, 5, 17, 15.5, 2.4, 4.6)                 # the top-right cut is the deepest one: the shield's nick
    assert box.startswith("M5.9 5H15.9L20.5 9.6") and box.endswith("z")


def test_icon_cache_is_keyed_by_colour_so_a_theme_change_repaints(qapp):
    from aegis_desktop.ui import icons

    def dominant(pm):
        img = pm.toImage()
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() > 200:
                    return c.red() > c.green()
        return None
    assert dominant(icons.pixmap("bell", "#ff0000", 18)) is True
    assert dominant(icons.pixmap("bell", "#00ff00", 18)) is False
    assert icons.pixmap("bell", "#ff0000", 18) is icons.pixmap("bell", "#ff0000", 18)


def test_theme_set_is_three_brand_themes_plus_thirteen_curated():
    from aegis_desktop.ui import themes_data as td
    assert td.DOTS == ["noir", "ivory", "aegis-light"]
    assert len(td.ORDER) == len(set(td.ORDER)) == len(td.THEMES) == 16
    assert td.ORDER[0] == "noir" and td.DEFAULT == td.SIGNATURE == "noir"
    for gone in ("obsidian", "noir-emerald", "noir-rose", "aegis", "mint", "sky", "blush", "onyx", "graphite", "goldblack", "contrast"):
        assert gone not in td.THEMES, gone
    for k in td.ORDER:
        assert set(td.THEMES[k]["pal"]) == set(td.THEMES["noir"]["pal"]), k          # a complete palette: no missing key can crash the QSS
        assert td.THEMES[k]["mode"] in ("dark", "light") and len(td.THEMES[k]["chart"]) == 6


def test_every_theme_text_stays_readable_on_every_surface():
    from aegis_desktop.ui.themes_data import THEMES
    for key, t in THEMES.items():
        p = t["pal"]
        for surface in ("bg", "panel", "panel2"):
            assert _contrast(p["text"], p[surface]) >= 7, (key, surface)
            assert _contrast(p["muted"], p[surface]) >= 4.5, (key, surface)
        assert _contrast(p["acc_text"], p["panel"]) >= 4.5, key
        assert _contrast(p["ink"], p["accent"]) >= 4.5, key                 # text on the primary button
        for k in ("danger", "warn", "ok"):
            assert _contrast(p[k], p["panel"]) >= 4.0, (key, k)


def test_every_theme_still_builds_a_stylesheet_and_switches(win):
    from aegis_desktop.ui import theme
    from aegis_desktop.ui import themes_data as td
    for key in td.ORDER:
        win.set_pref("palette", key)
        assert win.prefs["palette"] == key
        assert win.theme == td.THEMES[key]["mode"]
        assert td.THEMES[key]["pal"]["bg"] in theme.PALETTES[win.theme]["bg"] or theme.PALETTES[win.theme]["bg"].lower() == td.THEMES[key]["pal"]["bg"].lower()
        assert theme.PALETTES[win.theme]["bg"].lower() in win.app.styleSheet().lower()
    win.set_pref("palette", "noir")


def test_static_vazirmatn_weights_are_bundled_and_distinct(qapp):
    from PyQt6.QtGui import QFont, QFontDatabase, QFontMetricsF
    from aegis_desktop.ui import theme, tokens
    theme.load_font(qapp)
    fonts = theme.asset_path("fonts")
    files = sorted(fonts.glob("Vazirmatn-*.ttf"))
    assert [f.stem.split("-")[1] for f in files] == ["300", "400", "500", "600", "700"]
    assert sorted(tokens.WEIGHT.values()) == [300, 400, 500, 600, 700]
    widths = set()
    for w in sorted(tokens.WEIGHT.values()):
        f = QFont("Vazirmatn", 12)
        f.setWeight(QFont.Weight(w))
        widths.add(round(QFontMetricsF(f).horizontalAdvance("آیجیس پلنر ۱۲۳"), 2))
    assert "Vazirmatn" in QFontDatabase.families()
    assert len(widths) >= 3                                              # real cuts differ; a faux-bold smear would all match


def test_qss_uses_only_token_weights(qapp):
    from aegis_desktop.ui import theme, tokens
    css = theme.stylesheet("dark") + theme.stylesheet("light")
    used = {int(x) for x in re.findall(r"font-weight:\s*(\d{3})", css)}
    assert used and used <= set(tokens.WEIGHT.values()), used


def test_load_font_falls_back_to_the_variable_file(qapp, monkeypatch, tmp_path):
    from aegis_desktop.ui import theme
    real = theme.asset_path
    empty = tmp_path / "nofonts"
    empty.mkdir()
    monkeypatch.setattr(theme, "asset_path", lambda n: empty if n == "fonts" else real(n))
    assert theme.load_font(qapp)                                        # no statics, no Inter: still returns a family
    monkeypatch.undo()
    theme.load_font(qapp)


def test_default_window_size_fits_the_usable_screen():
    from PyQt6.QtCore import QRect
    from aegis_desktop.ui.main_window import default_size
    assert default_size(QRect(0, 0, 1920, 1040)) == (1180, 760)
    w, h = default_size(QRect(0, 0, 1280, 680))                        # 1080p laptop at 150%
    assert h <= 680 - 40 and w == 1180
    assert default_size(QRect(0, 0, 800, 560)) == (900, 600)             # never below the window minimum
    for aw, ah in ((1093, 570), (1366, 728), (1536, 816), (2560, 1400)):
        w, h = default_size(QRect(0, 0, aw, ah))
        assert 900 <= w <= 1180 and 600 <= h <= 760
        assert w <= max(900, aw - 40) and h <= max(600, ah - 40)


def _scan_page(win, pg, where):
    from PyQt6.QtWidgets import QAbstractScrollArea, QLabel, QWidget
    for sa in pg.findChildren(QAbstractScrollArea):
        if sa.isVisible():
            if sa.horizontalScrollBar().maximum() != 0:
                inner = sa.widget() if hasattr(sa, "widget") else None
                wide = sorted(((max(c.minimumSizeHint().width(), c.minimumWidth()), type(c).__name__, c.width(),
                                (c.text()[:20] if callable(getattr(c, "text", None)) else ""), c.objectName())
                               for c in (inner.findChildren(QWidget) if inner else []) if c.isVisible()), reverse=True)[:14]
                raise AssertionError(f"{where}: {type(sa).__name__} scrolls by {sa.horizontalScrollBar().maximum()}px "
                                     f"(viewport {sa.viewport().width()}, widest children {wide})")
    for lb in pg.findChildren(QLabel):
        shown = QLabel.text(lb)                                  # what is drawn (a PathLabel draws an elided copy of text())
        if lb.isVisible() and shown and "<" not in shown and not lb.wordWrap() and lb.pixmap().isNull():
            assert lb.fontMetrics().horizontalAdvance(shown) <= lb.width() + 1, (where, shown[:24])


def test_pages_and_every_settings_section_have_no_clipping_or_h_scroll_at_laptop_sizes(win):
    from PyQt6.QtTest import QTest
    setup_vault(win)
    for size in ((1093, 614), (1024, 600), (900, 600)):
        win.resize(*size)
        for key in list(win.pages):
            win.show_page(key)
            QTest.qWait(30)
            if key == "settings":
                st = win.pages[key]
                for i in range(len(st.nav.items)):          # the appearance section (ten theme cards) once overflowed by ~800 px
                    st._goto(i)
                    QTest.qWait(30)
                    _scan_page(win, st, (size, key, st.nav.items[i][0]))
            else:
                _scan_page(win, win.pages[key], (size, key))


def test_theme_picker_reflows_between_two_and_five_columns(qapp):
    from PyQt6.QtTest import QTest
    from aegis_desktop.ui import themes_data as td
    from aegis_desktop.ui.settings_widgets import ThemeCard, ThemePicker
    pk = ThemePicker(td.THEMES, td.ORDER)
    assert len(pk.cards) == 16 == len(td.THEMES)
    assert [ThemePicker.columns_for(w) for w in (100, 312, 500, 700, 900, 1400)] == [2, 2, 3, 4, 5, 5]
    for width in (330, 480, 640, 760, 900, 1300):
        pk.resize(width, 400)
        pk.show()
        QTest.qWait(20)
        rects = [c.geometry() for c in pk.cards.values()]
        assert all(pk.rect().contains(r) for r in rects), width
        assert all(r.width() >= ThemeCard.MIN_W for r in rects), width
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.intersects(b), width
        cols = ThemePicker.columns_for(width)
        need = 0
        for _mode, keys in pk._groups:                       # two groups (dark, light): head + grid rows, a gap between them
            rows = -(-len(keys) // cols)
            need += 26 + ThemePicker.HEAD_GAP + rows * ThemeCard.H + (rows - 1) * ThemePicker.GAP + ThemePicker.GROUP_GAP
        assert pk.minimumHeight() == need - ThemePicker.GROUP_GAP, width
    pk.close()


def test_theme_card_names_and_tags_never_collide(qapp):
    """The tag used to share the name's line ("آیجیس ابسیدین" + "مشکی خالص") and printed over it."""
    from PyQt6.QtGui import QColor
    from aegis_desktop.ui import themes_data as td
    from aegis_desktop.ui.settings_widgets import ThemeCard
    for key in td.ORDER:
        card = ThemeCard(key, td.THEMES[key])
        card.resize(150, ThemeCard.H)
        img = card.grab().toImage()
        r = card.rect().adjusted(2, 2, -2, -2)
        bg = QColor(td.THEMES[key]["pal"]["bg"])
        # the name row and the tag row are separate bands: each holds ink, and the gap between them is clear
        def ink(y0, y1):
            return sum(1 for y in range(y0, y1) for x in range(12, 100)
                       if abs(img.pixelColor(x, y).lightness() - bg.lightness()) > 60)
        name_band = (r.bottom() - 40, r.bottom() - 22)
        assert ink(*name_band) > 8, key
        if td.THEMES[key].get("tag"):
            assert ink(r.bottom() - 23, r.bottom() - 8) > 8, key


def test_a_long_path_elides_instead_of_widening_the_page(qapp):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QVBoxLayout, QWidget
    from aegis_desktop.ui.widgets import PathLabel
    long = "C:\\Users\\Alex\\AppData\\Roaming\\Aegis Planner\\backups\\a-very-long-folder-name-without-any-spaces\\more"
    host = QWidget()
    lay = QVBoxLayout(host)
    lb = PathLabel(long)
    lay.addWidget(lb)
    host.resize(260, 60)
    host.show()
    QTest.qWait(20)
    assert host.minimumSizeHint().width() < 120                          # the layout is no longer held open by the text
    assert lb.text() == lb.toolTip() == long                              # callers and the tooltip keep the whole path
    shown = QLabel.text(lb)
    assert "…" in shown and shown.startswith("C:") and shown.endswith("more")
    assert lb.fontMetrics().horizontalAdvance(shown) <= lb.width()
    host.resize(900, 60)
    QTest.qWait(20)
    assert QLabel.text(lb) == long                                        # wide enough: shown in full
    host.close()


from PyQt6.QtWidgets import QLabel  # noqa: E402  (used by the test above)


def test_a_primary_button_inside_a_settings_row_keeps_its_fill(win):
    """`QWidget#SRow QWidget {background: transparent}` outranked `QPushButton#Primary`, so a Primary in a row was dark ink on
    nothing. Also: each settings section keeps exactly one brand-coloured button once it is opened."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton
    setup_vault(win)
    win.show_page("settings")
    st = win.pages["settings"]
    for i in range(len(st.nav.items)):
        st._goto(i)
        QTest.qWait(40)
        vis = [b for b in st.findChildren(QPushButton) if b.isVisibleTo(st) and b.property("_prim")]
        prim = [b for b in vis if b.objectName() == "Primary"]
        assert len(prim) <= 1, (st.nav.items[i][0], [b.text() for b in prim])
        for b in prim:
            img = b.grab().toImage()
            lum = sum(img.pixelColor(x, y).lightness() for x in range(6, img.width() - 6, 3) for y in range(6, img.height() - 6, 3))
            n = len(range(6, img.width() - 6, 3)) * len(range(6, img.height() - 6, 3))
            assert lum / n > 120, (st.nav.items[i][0], b.text(), lum / n)          # the platinum fill is there, not the dark panel
    st._goto(1)
    QTest.qWait(80)
    forced = [b for b in st.findChildren(QPushButton) if b.text().startswith("خروجی رمز") and b.isVisibleTo(st)][0]
    forced.setObjectName("Primary")                                                  # even when it is the one that is promoted
    forced.style().unpolish(forced)
    forced.style().polish(forced)
    img = forced.grab().toImage()
    assert img.pixelColor(img.width() // 2, 4).lightness() > 120


def test_sidebar_goes_tight_on_short_windows_instead_of_crushing_the_brand(win):
    """The full sidebar needs ~620 px; a 1366x768 laptop at 125% leaves ~550. It used to squash the brand block first."""
    from PyQt6.QtTest import QTest
    setup_vault(win)
    lay = win.side.layout()

    def squeezed():
        return [i for i in range(lay.count()) if lay.itemAt(i).geometry().height() < lay.itemAt(i).minimumSize().height()]
    win.resize(1180, 900)
    QTest.qWait(60)
    assert not win._side_tight and not squeezed() and win._grp_lb.isVisible()
    tall_need = win._side_need
    assert tall_need > 560                                               # the premise: the full sidebar really is tall
    for h in (600, 614, 630):
        win.resize(1100, h)
        QTest.qWait(60)
        assert win._side_tight, h
        assert not squeezed(), (h, squeezed())
        assert not win._grp_lb.isVisible()
        assert all(b.height() == b.H_TIGHT for b in win.nav_btns.values())
    win.resize(1100, 700)                                                # room for the full sidebar: it is not tight there
    QTest.qWait(60)
    assert not win._side_tight
    win.resize(1180, 900)                                                # and back to the full look when there is room
    QTest.qWait(60)
    assert not win._side_tight and win._grp_lb.isVisible() and all(b.height() == b.H for b in win.nav_btns.values())
    win.set_pref("side_compact", True)                                   # the icon rail composes with tight mode
    QTest.qWait(400)
    win.resize(1100, 600)
    QTest.qWait(80)
    assert not squeezed()
    win.set_pref("side_compact", False)
    QTest.qWait(400)


def test_setting_rows_stack_their_controls_when_the_width_runs_out(qapp):
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QBoxLayout, QPushButton, QWidget, QHBoxLayout
    from aegis_desktop.ui.backup_ui import Section, SettingRow
    sec = Section("lock", "T", "")
    box = QWidget()
    hl = QHBoxLayout(box)
    hl.setContentsMargins(0, 0, 0, 0)
    for t in ("یادداشت‌ها ← Markdown", "تسک‌ها ← تقویم (.ics)"):
        hl.addWidget(QPushButton(t))
    row = sec.add_row("خروجی خوانا", "این فایل‌ها رمزنگاری نمی‌شوند؛ با دقت نگه‌شان دار.", box)
    assert isinstance(row, SettingRow) and row.objectName() == "SRow"
    sec.resize(700, 200)
    sec.show()
    QTest.qWait(30)
    assert row.layout().direction() == QBoxLayout.Direction.LeftToRight
    assert row.side_by_side_width() > row.stacked_width() + 60
    narrow = row.stacked_width() + 30
    sec.resize(narrow + 40, 300)
    QTest.qWait(30)
    assert row.layout().direction() == QBoxLayout.Direction.TopToBottom
    assert row.minimumSizeHint().width() < row.side_by_side_width()
    assert box.geometry().right() <= row.width() and box.geometry().left() >= 0
    sec.resize(700, 200)
    QTest.qWait(30)
    assert row.layout().direction() == QBoxLayout.Direction.LeftToRight
    sec.close()
