# SPDX-License-Identifier: GPL-3.0-or-later
"""Notes with sketches and flowcharts: data cleaning, the editor page, persistence, export."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from test_gui import win, setup_vault, PW  # noqa: F401
from aegis_desktop.core import logic
from aegis_desktop.ui import note_blocks as nb, note_export
from aegis_desktop.ui.note_blocks import BlockFrame

INK = {"t": "ink", "h": 240, "bg": "dots", "strokes": [{"c": "text", "w": 2.4, "m": 0, "p": [10, 10, 200, 90, 400, 30], "q": []}]}
FLOW = {"t": "flow", "nodes": [{"id": "a", "k": "start", "x": 0, "y": 0, "w": 120, "h": 44, "t": "شروع"},
                               {"id": "b", "k": "proc", "x": 0, "y": 100, "w": 120, "h": 44, "t": "کار"}],
        "edges": [{"a": "a", "b": "b", "l": ""}]}


def test_clean_rejects_junk():
    assert nb.clean_ink({"strokes": "x"})["strokes"] == []
    d = nb.clean_ink({"h": 99999, "bg": "zzz", "strokes": [{"p": [1, 2, 3]}, {"p": [0, 0, 5, 5]}]})
    assert d["bg"] in ("dots", "lines", "grid", "blank") and d["h"] < 99999
    f = nb.clean_flow({"nodes": [{"id": "a"}, 5], "edges": [{"a": "a", "b": "ghost"}]})
    assert f["edges"] == []


def test_logic_helpers():
    n = {"body": "hello", "blocks": [{"t": "text", "text": "more"}, FLOW, INK]}
    t = logic.note_full_text(n)
    assert "hello" in t and "more" in t and "شروع" in t


def test_page_blocks_roundtrip(win, qtbot):
    setup_vault(win)
    win.show_page("notes")
    pg = win.pages["notes"]
    pg._new()
    assert pg.views.currentIndex() == 1
    pg.title_in.setText("طرح")
    pg.body.setPlainText("خط اول")
    pg.add_block("ink")
    pg.add_block("flow")
    ink = next(b for b in pg._tail if isinstance(b, BlockFrame) and b.kind == "ink")
    ink.canvas.set_data(INK)
    flow = next(b for b in pg._tail if isinstance(b, BlockFrame) and b.kind == "flow")
    flow.canvas.set_data(FLOW)
    pg.flush()
    n = pg.cur
    kinds = [b["t"] for b in n["blocks"]]
    assert "ink" in kinds and "flow" in kinds
    pg._back()
    assert pg.views.currentIndex() == 0
    pg.select_id(n["id"])
    assert [b.kind for b in pg._tail if isinstance(b, BlockFrame)] == ["ink", "flow"]
    # persists through the vault
    win.store.save(); win.lock(); win.auth.u1.edit.setText(PW); win.auth._unlock()
    n2 = next(x for x in win.store.vault["notes"] if x["id"] == n["id"])
    assert [b["t"] for b in n2["blocks"]].count("ink") == 1 and len(next(b for b in n2["blocks"] if b["t"] == "flow")["nodes"]) == 2
    win.show_page("notes"); pg = win.pages["notes"]; pg.select_id(n["id"])
    # delete / undo
    blk = pg._tail[0]
    pg._remove_block(blk)
    assert blk not in pg._tail
    pg._restore_block(blk)
    assert blk in pg._tail


def test_export_all_formats(win, qtbot, tmp_path):
    setup_vault(win)
    note = {"id": "x", "title": "خروجی", "body": "# تیتر\n- [ ] کار\n**پررنگ** متن", "folder": "کار", "blocks": [INK, FLOW, {"t": "text", "text": "پایان"}]}
    pdf = tmp_path / "a.pdf"
    assert note_export.render_note_pdf(str(pdf), note) >= 1 and pdf.stat().st_size > 1500
    png = tmp_path / "a.png"
    assert note_export.render_note_image(note).save(str(png))
    md = tmp_path / "a.md"
    pg = win.pages["notes"]
    assert note_export.export_note(pg, note, "md", str(md))
    txt = md.read_text(encoding="utf-8")
    assert "a_files/sketch-1.png" in txt and (tmp_path / "a_files" / "flowchart-2.png").exists()


def test_long_note_paginates(tmp_path):
    note = {"id": "y", "title": "بلند", "body": "\n".join(f"خط شماره {i} " + "کلمه " * 20 for i in range(160)), "blocks": [INK] * 3}
    assert note_export.render_note_pdf(str(tmp_path / "l.pdf"), note) >= 3


def test_popovers_survive_repeated_use(win, qtbot):
    """Regression (2.3.0): the colour / info popups deleted their widget with the menu, so the next note action crashed."""
    from PyQt6.QtWidgets import QApplication
    setup_vault(win)
    win.show_page("notes")
    pg = win.pages["notes"]
    pg._new()
    for _ in range(3):
        pg._popup(pg.btn_color, pg.variant)
        QApplication.processEvents()
        pg._popups_close() if hasattr(pg, "_popups_close") else [p.hide() for p in pg._pops.values()]
        QApplication.processEvents()
        pg._popup(pg.btn_info, pg.stats)
        [p.hide() for p in pg._pops.values()]
        QApplication.processEvents()
    pg.variant.set_value("blue")
    pg._set_enabled(True)
    pg.select_id(pg.cur["id"])
    pg._delete(False)
    pg._new()
    pg.refresh()
    assert pg.cur is not None
