# SPDX-License-Identifier: GPL-3.0-or-later
"""Real-Windows visual QA: renders every page, in every theme, at the display scales people actually use
(100 / 125 / 150 / 200 %), on the REAL Windows platform plugin (not offscreen), with a throwaway demo vault.

    python tools\\windows_qa.py            -> qa_output\\<scale>\\<theme>_<page>.png  + qa_output\\report.txt

Nothing touches your real vault: a temporary data folder is used and deleted.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "qa_output"
SCALES = ("1", "1.25", "1.5", "2")


def render(scale: str) -> None:
    sys.path.insert(0, str(ROOT))
    from PyQt6.QtCore import Qt, qInstallMessageHandler
    from PyQt6.QtWidgets import QApplication
    warnings: list[str] = []
    qInstallMessageHandler(lambda _m, _c, msg: warnings.append(msg))
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    from aegis_desktop.core import jalali, logic
    from aegis_desktop.core.store import VaultStore
    from aegis_desktop.ui import dialogs, theme
    from aegis_desktop.ui.main_window import MainWindow
    theme.load_font(app)
    dialogs.info = lambda *a, **k: None
    d = Path(tempfile.mkdtemp(prefix="aegis-qa-"))
    w = MainWindow(VaultStore(d / "data"), app, d / "data" / "prefs.json")
    w.resize(1280, 800)
    w.show()
    w.auth.s1.edit.setText("qa demo password 2026"); w.auth.s2.edit.setText("qa demo password 2026"); w.auth._create()
    v = w.store.vault
    today = dt.date.today()
    for i, (t, pr, off) in enumerate((("ارسال گزارش هفتگی", "high", -2), ("تمرین دوره جنگو", "normal", 0),
                                       ("جلسه با تیم", "high", 1), ("Review PR #42", "low", 3))):
        v["tasks"].append(logic.new_task(t, pr=pr, due=jalali.date_to_due(today + dt.timedelta(days=off)), tags=["پروژه"]))
    h = logic.new_habit("مطالعه")
    for k in (0, 1, 2, 4, 5):
        h["log"][(today - dt.timedelta(days=k)).isoformat()] = {"d": 1}
    v["habits"].append(h)
    v["goals"].append(logic.new_goal("انتشار نسخه‌ی اول", ms=[{"text": "طراحی", "done": True}, {"text": "تست", "done": False}]))
    w.refresh_all()
    out = OUT / f"scale_{scale}"
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for th in (theme.THEME_ORDER[:1] if os.environ.get("AEGIS_QA_QUICK") else theme.THEME_ORDER):
        w.set_pref("palette", th)
        for key in w.pages:
            t0 = time.perf_counter()
            w.show_page(key)
            app.processEvents()
            ms = (time.perf_counter() - t0) * 1000
            time.sleep(0.9)                                   # let entrance animations settle
            for _ in range(20):
                app.processEvents()
            w.grab().save(str(out / f"{th}_{key}.png"))
            report.append(f"{scale}\t{th}\t{key}\t{ms:.0f} ms")
    report += specials(app, w, out)
    w.store.dirty = False
    w.close()
    (out / "report.txt").write_text("\n".join(report + ["", "Qt warnings:"] + sorted(set(warnings))), encoding="utf-8")
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def specials(app, w, out: Path) -> list[str]:
    """1.4.0 things that only a real display can vouch for: what Windows really gives us (screen, DPI, fonts), and the
    certificate / week seal / day start / PDF rendered on it."""
    from PyQt6.QtGui import QFont, QFontDatabase, QFontInfo, QGuiApplication
    from aegis_desktop.ui import theme
    from aegis_desktop.ui.main_window import default_size
    rows = ["", "== 1.4.0 facts =="]
    scr = QGuiApplication.primaryScreen()
    rows.append(f"screen\t{scr.name()}\tgeometry {scr.geometry().width()}x{scr.geometry().height()}\tavailable "
                f"{scr.availableGeometry().width()}x{scr.availableGeometry().height()}\tdpr {scr.devicePixelRatio()}\tlogicalDpi {scr.logicalDotsPerInch():.0f}")
    rows.append(f"default window size\t{default_size()}")
    rows.append(f"window now\t{w.width()}x{w.height()}\tsidebar tight: {getattr(w, '_side_tight', None)}")
    fam = app.font().family()
    rows.append(f"app font\t{fam}\tfamilies {app.font().families()}")
    for wt in (300, 400, 500, 600, 700):
        f = QFont("Vazirmatn", 12)
        f.setWeight(QFont.Weight(wt))
        fi = QFontInfo(f)
        rows.append(f"Vazirmatn weight {wt}\tresolved {fi.family()} / {fi.styleName()} / weight {fi.weight()} / exact {fi.exactMatch()}")
    rows.append("Vazirmatn styles\t" + ", ".join(QFontDatabase.styles("Vazirmatn")))
    for name, make in (("certificate", lambda: __import__("aegis_desktop.ui.certificate", fromlist=["x"]).CertificateDialog(w)),
                       ("weekseal", lambda: __import__("aegis_desktop.ui.weekseal", fromlist=["x"]).WeekSealDialog(w))):
        try:
            d = make()
            d.show()
            for _ in range(30):
                app.processEvents()
            time.sleep(0.6)
            d.grab().save(str(out / f"special_{name}.png"))
            d.close()
            rows.append(f"{name}\tok")
        except Exception as e:  # noqa: BLE001 - a QA script reports, it never stops
            rows.append(f"{name}\tFAILED {e!r}")
    try:
        card = w.show_day_start(force=True)
        time.sleep(0.8)
        for _ in range(30):
            app.processEvents()
        w.grab().save(str(out / "special_daystart.png"))
        if card is not None:
            card.close_ritual()
        rows.append("day start\tok")
    except Exception as e:  # noqa: BLE001
        rows.append(f"day start\tFAILED {e!r}")
    try:
        pdf = out / "special_report.pdf"
        n = w.export_report_pdf(30, str(pdf))
        rows.append(f"report pdf\t{'ok ' + str(pdf.stat().st_size) + ' bytes' if n and pdf.exists() else 'FAILED'}")
    except Exception as e:  # noqa: BLE001
        rows.append(f"report pdf\tFAILED {e!r}")
    w.set_pref("palette", theme.DEFAULT_THEME)
    return rows


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--render":
        render(sys.argv[2])
        return 0
    scales = SCALES
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":       # one scale, one theme: a smoke test of this script itself
        os.environ["AEGIS_QA_QUICK"] = "1"
        scales = ("1",)
    OUT.mkdir(exist_ok=True)
    lines = []
    for s in scales:
        env = dict(os.environ, QT_SCALE_FACTOR=s, QT_ENABLE_HIGHDPI_SCALING="1")
        env.pop("QT_QPA_PLATFORM", None)                     # the real platform plugin
        r = subprocess.run([sys.executable, __file__, "--render", s], env=env)
        lines.append(f"scale {s}: {'ok' if r.returncode == 0 else 'FAILED (' + str(r.returncode) + ')'}")
        print(lines[-1], flush=True)
    rep = OUT / "report.txt"
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for s in scales:
        f = OUT / f"scale_{s}" / "report.txt"
        if f.exists():
            rep.write_text(rep.read_text(encoding="utf-8") + "\n" + f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    print(f"done -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
