# SPDX-License-Identifier: GPL-3.0-or-later
"""Calendar printing: day / week / month PDFs (and QPrinter), overflow pages, hostile titles, and the «پرینت» button."""
import datetime as dt
import shutil
import subprocess
import time

import pytest

from aegis_desktop.core import jalali, logic
from aegis_desktop.ui import calendar_print as cp, letterhead
from aegis_desktop.ui.theme import THEMES
from test_gui import setup_vault, win  # noqa: F401

ANCHOR = dt.date(*jalali.to_gregorian(1405, 7, 10))          # a Friday, mid-month
PAL = THEMES["noir"]["pal"]


def _t(title, day, **kw):
    return logic.new_task(title, due=jalali.date_to_due(day), **kw)


def _pages(path) -> int:
    data = open(path, "rb").read()
    assert data[:5] == b"%PDF-" and b"%%EOF" in data[-32:]
    return data.count(b"/Type /Page\n") or data.count(b"/Type /Page") - data.count(b"/Type /Pages")


def _busy(n=500):
    out = []
    for i in range(n):
        d = ANCHOR + dt.timedelta(days=(i * 7) % 40 - 15)
        kw = {"pr": ("high", "normal", "low")[i % 3]}
        if i % 2:
            kw["timeFrom"] = f"{6 + i % 16:02d}:{(i % 2) * 30:02d}"
            if i % 4 == 1:
                kw["timeTo"] = f"{7 + i % 16:02d}:45"
        t = _t(f"تسک {i} با عنوان کمی بلندتر برای آزمایش", d, **kw)
        t["done"] = i % 5 == 0
        if i % 11 == 0:
            t["dueEnd"] = jalali.date_to_due(d + dt.timedelta(days=3))
        out.append(t)
    return out


WEIRD = ["", "   ", "x" * 5000, "Meeting با علی ‏RTL‎ mixed Latin", "تسک\nچندخطی\tبا تب", "<b>html</b> & \"quotes\"", "😀 emoji 🎉",
         "۱۲۳ 456 ٧٨٩", "‮ override ‬", "A" * 40 + " " + "ب" * 40, None, 42]


@pytest.mark.parametrize("mode", cp.MODES)
def test_every_mode_writes_a_valid_pdf(qapp, tmp_path, mode):
    out = str(tmp_path / f"{mode}.pdf")
    n = cp.render_calendar_pdf(out, mode, ANCHOR, _busy(60), PAL, today=ANCHOR)
    assert n >= 1 and _pages(out) == n and len(open(out, "rb").read()) > 4000


@pytest.mark.parametrize("mode", cp.MODES)
def test_empty_calendar_prints_one_page(qapp, tmp_path, mode):
    out = str(tmp_path / "e.pdf")
    assert cp.render_calendar_pdf(out, mode, ANCHOR, [], None) == 1
    assert _pages(out) == 1


def test_busy_month_overflows_onto_a_full_list(qapp, tmp_path):
    out = str(tmp_path / "m.pdf")
    n = cp.render_calendar_pdf(out, "month", ANCHOR, _busy(500), PAL, today=ANCHOR)
    assert n > 1 and _pages(out) == n
    quiet = cp.render_calendar_pdf(str(tmp_path / "q.pdf"), "month", ANCHOR, [_t("یک", ANCHOR), _t("دو", ANCHOR + dt.timedelta(days=1))], PAL)
    assert quiet == 1                                                       # nothing overflows -> no list page


def test_busy_week_and_day_continue_on_extra_pages(qapp, tmp_path):
    tasks = [_t(f"روز {i}", ANCHOR, **({"timeFrom": "10:00"} if i % 2 else {})) for i in range(120)]
    assert cp.render_calendar_pdf(str(tmp_path / "d.pdf"), "day", ANCHOR, tasks, PAL) > 1
    assert cp.render_calendar_pdf(str(tmp_path / "w.pdf"), "week", ANCHOR, tasks, PAL) > 1


def test_hostile_titles_and_fields_do_not_crash(qapp, tmp_path):
    tasks = []
    for i, ttl in enumerate(WEIRD):
        t = _t("x", ANCHOR + dt.timedelta(days=i % 3), pr="high")
        t["title"] = ttl
        t["timeFrom"] = ["bad", "25:99", "09:00", "", None, "9:5"][i % 6]
        t["timeTo"] = ["08:00", "x", None, "23:59", "10:00", ""][i % 6]
        t["pr"] = ["high", "low", "weird", None, "normal", 7][i % 6]
        tasks.append(t)
    tasks.append({"id": "bad", "title": "no due"})                         # no date at all
    tasks.append(_t("end before start", ANCHOR, dueEnd=jalali.date_to_due(ANCHOR - dt.timedelta(days=5))))
    tasks.append(_t("very long span", ANCHOR, dueEnd=jalali.date_to_due(ANCHOR + dt.timedelta(days=5000))))
    for mode in cp.MODES:
        assert cp.render_calendar_pdf(str(tmp_path / f"{mode}.pdf"), mode, ANCHOR, tasks, PAL, today=ANCHOR) >= 1


def test_multi_day_tasks_appear_on_every_day_of_the_week(qapp, tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext missing")
    t = _t("MULTIDAYTASK", ANCHOR - dt.timedelta(days=2), dueEnd=jalali.date_to_due(ANCHOR))
    out = tmp_path / "w.pdf"
    cp.render_calendar_pdf(str(out), "week", ANCHOR, [t], PAL)
    txt = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout
    assert txt.count("MULTIDAYTASK") == 3


def test_titles_range_and_month_length(qapp):
    assert cp.range_title("month", ANCHOR) == "مهر ۱۴۰۵"
    assert cp.range_title("week", ANCHOR) == "هفته ۴ تا ۱۰ مهر ۱۴۰۵"          # Saturday 4th .. Friday 10th
    assert cp.range_title("day", ANCHOR) == "جمعه ۱۰ مهر ۱۴۰۵"
    cross = dt.date(*jalali.to_gregorian(1405, 7, 29))
    assert "مهر" in cp.range_title("week", cross) and "آبان" in cp.range_title("week", cross)
    assert len(cp.range_dates("month", ANCHOR)) == 30 and len(cp.range_dates("week", ANCHOR)) == 7
    esf = dt.date(*jalali.to_gregorian(1403, 12, 5))                         # 1403 is leap: 30 days
    assert len(cp.range_dates("month", esf)) == 30
    assert len(cp.range_dates("month", dt.date(*jalali.to_gregorian(1404, 12, 5)))) == 29
    assert cp.range_dates("week", ANCHOR)[0].weekday() == 5                 # Saturday first


def test_pdf_text_has_persian_digits_and_the_brand(qapp, tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext missing")
    out = tmp_path / "m.pdf"
    cp.render_calendar_pdf(str(out), "month", ANCHOR, [_t("جلسه", ANCHOR, timeFrom="09:30")], PAL, today=ANCHOR)
    txt = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout
    import unicodedata
    txt = unicodedata.normalize("NFKC", txt)                                  # pdftotext hands back Arabic presentation forms
    assert "Aegis Planner" in txt and "۱۴۰۵" in txt and "۰۹" in txt and "صفحه" in txt and "جلسه" in txt


def test_font_scale_is_restored_after_a_failure(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "_month", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        cp.render_calendar_pdf(str(tmp_path / "x.pdf"), "month", ANCHOR, [], None)
    assert letterhead.UNIT[0] == 1.0


def test_unknown_mode_is_rejected(qapp, tmp_path):
    with pytest.raises(ValueError):
        cp.render_calendar_pdf(str(tmp_path / "x.pdf"), "year", ANCHOR, [], None)


def test_heavy_month_renders_in_reasonable_time(qapp, tmp_path):
    t0 = time.time()
    cp.render_calendar_pdf(str(tmp_path / "h.pdf"), "month", ANCHOR, _busy(500), PAL)
    assert time.time() - t0 < 25


def test_renders_to_a_qprinter_device(qapp, tmp_path):
    from PyQt6.QtPrintSupport import QPrinter
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setOutputFileName(str(tmp_path / "p.pdf"))
    assert cp.render_calendar_pdf(pr, "week", ANCHOR, _busy(30), PAL) >= 1
    assert open(tmp_path / "p.pdf", "rb").read(5) == b"%PDF-"


# ------------------------------------------------------------------------------------------------ the page ---
def _cal(win):
    setup_vault(win)
    win.show_page("calendar")
    return win.pages["calendar"]


def test_calendar_page_has_the_print_button_and_saves_each_mode(win, tmp_path):
    cal = _cal(win)
    assert cal.print_btn.text() == "پرینت" and not cal.print_btn.icon().isNull()
    for mode in cp.MODES:
        out = cal.print_pdf(mode, str(tmp_path / f"{mode}"))
        assert out.endswith(".pdf") and open(out, "rb").read(5) == b"%PDF-"
    assert cal.print_pdf("month", str(tmp_path / "nodir" / "x.pdf")) is None          # unwritable -> a toast, not a crash


def test_print_respects_the_page_filters(win, tmp_path):
    cal = _cal(win)
    cal.selected = dt.date.today()
    win.store.vault["tasks"].append(_t("باز", cal.selected))
    done = _t("انجام", cal.selected)
    done["done"] = True
    win.store.vault["tasks"].append(done)
    cal.refresh()
    assert {x["title"] for x in cal._print_tasks("day")} >= {"باز", "انجام"}
    cal.status.setCurrentIndex(cal.status.findData("open"))
    assert "انجام" not in {x["title"] for x in cal._print_tasks("day")}


def test_print_to_a_printer_object(win, tmp_path):
    from PyQt6.QtPrintSupport import QPrinter
    cal = _cal(win)
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setOutputFileName(str(tmp_path / "paper.pdf"))
    assert cal.print_paper("week", pr) is True
    assert open(tmp_path / "paper.pdf", "rb").read(5) == b"%PDF-"
    win.lock()
    assert cal.print_pdf("day", str(tmp_path / "locked.pdf")) is None


def test_print_menu_lists_day_week_month(win):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMenu
    cal = _cal(win)
    seen = []

    def peek():
        m = QApplication.activePopupWidget()
        if isinstance(m, QMenu):
            seen.extend((a.text(), [s.text() for s in a.menu().actions()]) for a in m.actions() if a.menu())
            m.close()
    QTimer.singleShot(250, peek)
    cal._print_menu()
    assert [t for t, _ in seen] == ["چاپ روز", "چاپ هفته", "چاپ ماه"]
    assert all(s == ["ذخیره PDF…", "چاپ…"] for _t_, s in seen)
