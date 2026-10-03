# SPDX-License-Identifier: GPL-3.0-or-later
"""The 2.4 design-system pieces: filter chips, the status tabs, the toggle chip and the editor sheet."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from test_gui import PW, setup_vault, win  # noqa: F401
from aegis_desktop.ui import dialogs
from aegis_desktop.ui.system import BAR_H, ChipCombo, ChipToggle, ChoiceTabs


def test_chip_combo_shows_caption_until_filtering(qtbot):
    c = ChipCombo("دسته")
    qtbot.addWidget(c)
    c.addItem("همه‌ی دسته‌ها", "all")
    c.addItem("کار", "work")
    c.show()
    assert c.shown_text() == "دسته" and c.height() == BAR_H
    w0 = c.sizeHint().width()
    c.setCurrentIndex(1)
    assert c.is_filtering() and c.shown_text() == "دسته: کار" and c.sizeHint().width() > w0
    assert not c.grab().isNull()
    c.setCurrentIndex(0)
    assert c.shown_text() == "دسته"


def test_choice_tabs_speaks_combo(qtbot):
    t = ChoiceTabs()
    qtbot.addWidget(t)
    t.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    for k, x in (("open", "باز"), ("done", "انجام‌شده"), ("all", "همه")):
        t.addItem(x, k)
    t.show()
    seen = []
    t.currentIndexChanged.connect(seen.append)
    assert t.currentData() == "open" and t.findData("all") == 2 and t.count() == 3
    t.setCurrentIndex(2)
    assert t.currentData() == "all" and seen == [2]
    t.blockSignals(True)
    t.setCurrentIndex(0)
    t.blockSignals(False)
    assert t.currentData() == "open" and seen == [2]
    qtbot.keyClick(t, Qt.Key.Key_Left)                      # RTL: Left goes forward
    assert t.currentIndex() == 1
    assert not t.grab().isNull()


def test_chip_toggle(qtbot):
    b = ChipToggle("گروه‌بندی")
    qtbot.addWidget(b)
    b.show()
    got = []
    b.toggled.connect(got.append)
    qtbot.mouseClick(b, Qt.MouseButton.LeftButton)
    assert b.isChecked() and got == [True]
    qtbot.wait(300)
    assert not b.grab().isNull()
    b.setChecked(False)
    assert got == [True, False]


def test_tasks_toolbar_uses_chips(win, qtbot):
    setup_vault(win)
    win.show_page("tasks")
    tp = win.pages["tasks"]
    assert isinstance(tp.status, ChoiceTabs) and isinstance(tp.cat, ChipCombo) and isinstance(tp.group, ChipToggle)
    tp.cat.setCurrentIndex(tp.cat.findData("work"))
    assert tp.cat.is_filtering()
    tp._clear_filters()
    assert not tp.cat.is_filtering() and tp.status.currentData() == "open"
    cp = win.pages["calendar"]
    assert isinstance(cp.status, ChipCombo) and isinstance(cp.cat, ChipCombo)


def test_open_task_has_no_status_badge(win):
    from aegis_desktop.core import logic
    from aegis_desktop.ui.task_table import COL_STATUS
    setup_vault(win)
    win.store.vault["tasks"].append(logic.new_task("x"))
    win.show_page("tasks")
    tp = win.pages["tasks"]
    tp.refresh()
    m = tp.table.model()
    texts = {m.data(m.index(r, COL_STATUS)) for r in range(m.rowCount())}
    assert "انجام‌نشده" not in texts


def test_editor_sheets(win, qtbot):
    setup_vault(win)
    for d in (dialogs.TaskDialog(win, win.store.vault), dialogs.GoalDialog(win), dialogs.HabitDialog(win)):
        qtbot.addWidget(d)
        d.show()
        assert d.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert d.title.objectName() == "SheetTitle" if hasattr(d, "title") and d.__class__ is not dialogs.HabitDialog else True
        assert not d.grab().isNull()
        assert d._close.isVisible()
        d.reject()
    d = dialogs.HabitDialog(win)
    qtbot.addWidget(d)
    d.show()
    d.name.setText("ورزش")
    d.activateWindow()
    d.name.setFocus()
    qtbot.wait(50)
    qtbot.keyClick(d, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert d.result() == 1 and d.result_habit()["name"] == "ورزش"


def test_settings_crumb_hidden(win):
    setup_vault(win)
    win.show_page("settings")
    assert win.pages["settings"].crumb.isHidden()


def test_more_section_opens_by_click_in_the_sheet(win, qtbot):
    """Regression (2.4.0): the sheet's drag-to-move swallowed the click, so «گزینه‌های بیشتر» never opened."""
    setup_vault(win)
    d = dialogs.TaskDialog(win, win.store.vault)
    qtbot.addWidget(d)
    d.show()
    qtbot.wait(50)
    assert not d.more.is_open()
    qtbot.mouseClick(d.more.head, Qt.MouseButton.LeftButton)
    qtbot.wait(400)
    assert d.more.is_open() and d.tags.isVisibleTo(d)
    qtbot.mouseClick(d.more.head, Qt.MouseButton.LeftButton)
    qtbot.wait(400)
    assert not d.more.is_open()
    d.reject()


def test_notes_board_card_at_accepts_qpoint(win):
    """Regression (2.4.0 log): contextMenuEvent passes a QPoint, QRectF.contains() wants a QPointF."""
    from PyQt6.QtCore import QPoint
    setup_vault(win)
    win.show_page("notes")
    from aegis_desktop.core import logic
    win.store.vault["notes"].append(logic.new_note("t", "b", "f"))
    win.changed()
    win.show_page("notes")
    c = win.pages["notes"].board.canvas
    c.resize(900, 600)
    for r, n in c._cards[:1]:
        assert c._card_at(QPoint(int(r.center().x()), int(r.center().y())))["id"] == n["id"]
    assert c._card_at(QPoint(1, 1)) is None or isinstance(c._card_at(QPoint(1, 1)), dict)


# ---------------------------------------------------------------- the task editor is a page (2.5)
def _tasks(win):
    return win.store.vault["tasks"]


def test_new_task_opens_a_page_not_a_dialog(win, qtbot):
    setup_vault(win)
    n = len(_tasks(win))
    win.new_task(None)
    d = win._editor
    assert d is not None and d.embedded and win.stack.currentWidget() is d
    assert not d.isWindow()
    d.title.setText("طرح تازه")
    d.accept()
    assert win._editor is None and win.stack.currentWidget() is not d
    assert len(_tasks(win)) == n + 1 and _tasks(win)[-1]["title"] == "طرح تازه"


def test_page_editor_edit_existing_and_cancel_clean(win, qtbot):
    setup_vault(win)
    win.new_task(None); win._editor.title.setText("الف"); win._editor.accept()
    tid = _tasks(win)[-1]["id"]
    win.edit_task_id(tid)
    d = win._editor
    assert d.title.text() == "الف" and not d.is_dirty()
    d.reject()                                   # nothing typed, so no question
    assert win._editor is None
    assert _tasks(win)[-1]["title"] == "الف"


def test_page_editor_dirty_asks_and_can_stay(win, qtbot, monkeypatch):
    setup_vault(win)
    win.new_task(None)
    d = win._editor
    d.title.setText("نیمه‌کاره")
    assert d.is_dirty()
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: False)
    d.reject()
    assert win._editor is d                      # chose to stay
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    d.reject()
    assert win._editor is None and all(t["title"] != "نیمه‌کاره" for t in _tasks(win))


def test_page_editor_second_request_keeps_first(win, qtbot):
    setup_vault(win)
    win.new_task(None)
    d = win._editor
    win.new_task(None)
    assert win._editor is d
    d._discard = True; d.reject()


def test_page_editor_closed_by_navigation_and_lock(win, qtbot):
    setup_vault(win)
    win.new_task(None)
    win._editor.title.setText("x")
    win.lock()
    assert win._editor is None and not win.store.is_unlocked


def test_page_editor_empty_title_refused(win, qtbot):
    setup_vault(win)
    win.new_task(None)
    d = win._editor
    d.accept()
    assert win._editor is d and d.err.text()
    d._discard = True; d.reject()


def test_page_editor_calendar_defaults(win, qtbot):
    setup_vault(win)
    due = {"jy": 1405, "jm": 7, "jd": 10}
    win.new_task(due)
    d = win._editor
    d.title.setText("با تاریخ"); d.accept()
    t = _tasks(win)[-1]
    assert t["title"] == "با تاریخ" and t.get("due")


# ---------------------------------------------------------------- Settings: Help + live preview (2.5)
def _settings(win):
    setup_vault(win)
    win.show_page("settings")
    st = win.pages["settings"]
    keys = [k for k, _t, _i in st.nav.items]
    st.nav.cur = keys.index("help"); st._goto(keys.index("help"))
    return st


def test_help_content_is_complete():
    from aegis_desktop.ui.help_content import FAQ, FEATURES, PRIVACY
    assert len(FAQ) >= 20 and len(FEATURES) >= 12 and len(PRIVACY) >= 8
    assert len({q for _c, q, _a in FAQ}) == len(FAQ)
    assert all(c and q and a for c, q, a in FAQ)
    text = " ".join(h + b for h, b in PRIVACY)
    for must in ("AES", "PBKDF2", "آفلاین", "کلید بازیابی", "aegis.log"):
        assert must in text, must


def test_help_section_tabs_and_faq(win, qtbot):
    st = _settings(win)
    hv = st.help
    assert hv.tabs.count() == 3 and hv.faq.isVisibleTo(hv) and not hv.privacy.isVisibleTo(hv)
    hv.tabs.setCurrentIndex(2)
    assert hv.privacy.isVisibleTo(hv) and not hv.faq.isVisibleTo(hv)
    hv.tabs.setCurrentIndex(1)
    assert hv.features.isVisibleTo(hv) and len(hv.features.cards) >= 12
    hv.tabs.setCurrentIndex(0)
    it = hv.faq.items[0]
    assert not it.open
    it.set_open(True)
    assert it.open and it.body.isVisibleTo(it)
    it.keyPressEvent(__import__("PyQt6.QtGui", fromlist=["QKeyEvent"]).QKeyEvent(
        __import__("PyQt6.QtCore", fromlist=["QEvent"]).QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    assert not it.open


def test_faq_search_folds_arabic_and_digits(win, qtbot):
    hv = _settings(win).help
    hv.faq.search.setText("كلید بازيابي")                 # Arabic kaf / yeh
    vis = [i for i in hv.faq.items if i.isVisibleTo(hv.faq)]
    assert vis and all("بازیابی" in i.q + i.a for i in vis)
    hv.faq.search.setText("۶۰۰۰۰۰")                        # Persian digits find the Latin / Persian number
    hv.faq.search.setText("zzzzqq")
    assert not any(i.isVisibleTo(hv.faq) for i in hv.faq.items) and hv.faq.empty.isVisibleTo(hv.faq)
    hv.faq.search.setText("")
    assert all(i.isVisibleTo(hv.faq) for i in hv.faq.items)


def test_appearance_live_preview_follows_controls(win, qtbot):
    setup_vault(win)
    win.show_page("settings")
    st = win.pages["settings"]
    h0 = st.preview.height()
    st.dens.setCurrentIndex(st.dens.findData("compact"))
    assert st.preview.dense and st.preview.height() < h0
    st.fsize.setValue(14)
    assert st.preview.pt == 14
    assert not st.preview.grab().isNull()


# ---------------------------------------------------------------- date popover, steppers, nav pill, goals tabs (2.5)
def test_date_edit_keeps_value_and_opens_calendar(qtbot):
    from aegis_desktop.ui.widgets import JalaliDateEdit
    e = JalaliDateEdit(True, {"jy": 1405, "jm": 7, "jd": 10})
    qtbot.addWidget(e); e.show()
    assert e.value() == {"jy": 1405, "jm": 7, "jd": 10}
    assert "۱۰ مهر" in e.btn.text_now() and not e.year.isVisible()
    e.btn.open_popover()
    cal = e.btn.cal
    assert cal.cur == (1405, 7)
    cal.shift_month(1)
    assert cal.cur == (1405, 8)
    cal._pick(21)                                   # a click on day 21 of Aban
    assert e.value() == {"jy": 1405, "jm": 8, "jd": 21} and not e.btn.pop.isVisible()
    e.enabled_cb.setChecked(False)
    assert e.value() is None and not e.btn.isEnabled()
    e.set_value(None)
    assert e.value() is None


def test_mini_calendar_month_math_and_keys(qtbot):
    from aegis_desktop.ui.datepick import MiniCalendar
    c = MiniCalendar({"jy": 1405, "jm": 12, "jd": 29})
    qtbot.addWidget(c); c.show()
    c.shift_month(1)
    assert c.cur == (1406, 1)
    c.shift_month(-2)
    assert c.cur == (1405, 11)
    got = []
    c.picked.connect(got.append)
    qtbot.keyClick(c, Qt.Key.Key_Return)
    assert got and got[0]["jm"] == 11
    assert not c.grab().isNull()


def test_spinbox_steppers(qtbot):
    from aegis_desktop.ui.widgets import FaSpinBox
    s = FaSpinBox(); qtbot.addWidget(s)
    s.setRange(3, 5); s.setValue(4); s.show()
    s._plus.click(); s._plus.click()
    assert s.value() == 5
    s._minus.click(); s._minus.click(); s._minus.click()
    assert s.value() == 3
    assert s.height() >= 38


def test_step_nav_signals(qtbot):
    from aegis_desktop.ui.system import StepNav
    n = StepNav(); qtbot.addWidget(n); n.show()
    n.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    got = []
    n.prev.connect(lambda: got.append("p")); n.today.connect(lambda: got.append("t")); n.next.connect(lambda: got.append("n"))
    from PyQt6.QtCore import QPoint
    for x, want in ((n.width() - 10, "p"), (n.width() // 2, "t"), (10, "n")):         # RTL: previous is on the right
        qtbot.mouseClick(n, Qt.MouseButton.LeftButton, pos=QPoint(x, n.height() // 2))
        assert got[-1] == want
    assert not n.grab().isNull()


def test_goals_filter_is_tabs(win, qtbot):
    from aegis_desktop.ui.system import ChoiceTabs
    setup_vault(win)
    win.show_page("goals")
    g = win.pages["goals"]
    assert isinstance(g.filter, ChoiceTabs) and g.filter.value() == "all"
    g.filter.setCurrentIndex(1)
    assert g.filter.value() != "all"


def test_calendar_nav_pill_moves_month(win, qtbot):
    setup_vault(win)
    win.show_page("calendar")
    cv = win.pages["calendar"]
    m0 = (cv.jy, cv.jm)
    cv.nav.next.emit()
    assert (cv.jy, cv.jm) != m0
    cv.nav.prev.emit()
    assert (cv.jy, cv.jm) == m0


# ---------------------------------------------------------------- Today: the «now» band (2.5)
def test_today_band_picks_task_and_starts_focus(win, qtbot):
    from aegis_desktop.core import logic, jalali
    setup_vault(win)
    v = win.store.vault
    v["tasks"].clear()
    t1 = logic.new_task("بعدی", due=jalali.today_jalali())
    t2 = logic.new_task("بعداً", due=jalali.date_to_due(__import__("datetime").date.today() + __import__("datetime").timedelta(days=5)))
    v["tasks"] += [t1, t2]
    win.changed()
    win.show_page("today")
    pg = win.pages["today"]
    pg.refresh()
    b = pg.band
    assert b.tid == t1["id"] and b.title.text().startswith("بعدی")
    assert b.b_start.isVisibleTo(b) and not b.b_add.isVisibleTo(b)
    b._start()
    fm = win._focus_mode
    assert fm.task_id == t1["id"] and fm.page.running
    fm.page._toggle()                                  # stop the timer again
    fm.leave()
    b._done()
    assert t1["done"]
    pg.refresh()
    assert b.tid is None and b.b_add.isVisibleTo(b) and not b.b_start.isVisibleTo(b)       # the future task is never "now"


def test_today_hides_empty_overdue_card(win, qtbot):
    from aegis_desktop.core import logic, jalali
    setup_vault(win)
    win.store.vault["tasks"].clear()
    win.show_page("today")
    pg = win.pages["today"]
    pg.refresh()
    assert not pg._card_over.isVisibleTo(pg)
    import datetime as dt
    win.store.vault["tasks"].append(logic.new_task("قدیمی", due=jalali.date_to_due(dt.date.today() - dt.timedelta(days=3))))
    pg.refresh()
    assert pg._card_over.isVisibleTo(pg)


# ---------------------------------------------------------------- goal / habit pages and the time field (2.11)
def test_goal_page_editor_roundtrip(win, qtbot, monkeypatch):
    setup_vault(win)
    n = len(win.store.vault["goals"])
    win.edit_goal(None)
    d = win._editor
    assert isinstance(d, dialogs.GoalDialog) and d.embedded and win.stack.currentWidget() is d
    d.title.setText("هدف آزمون")
    d._enter() if d.ms_in.text() else None
    d.ms_in.setText("گام اول"); d._enter()
    d.accept()
    assert win._editor is None and len(win.store.vault["goals"]) == n + 1
    g = win.store.vault["goals"][-1]
    assert g["title"] == "هدف آزمون" and [m["text"] for m in g["ms"]] == ["گام اول"]
    win.edit_goal(g)
    d = win._editor
    assert d.title.text() == "هدف آزمون" and not d.is_dirty()
    d.title.setText("تغییر")
    assert d.is_dirty()
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: False)
    d.reject()
    assert win._editor is d
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: True)
    d.reject()
    assert win._editor is None and g["title"] == "هدف آزمون"


def test_habit_page_editor_roundtrip(win, qtbot):
    setup_vault(win)
    n = len(win.store.vault["habits"])
    win.edit_habit(None)
    d = win._editor
    assert isinstance(d, dialogs.HabitDialog) and d.embedded
    d.accept()                                         # empty name is refused
    assert win._editor is d and d.err.text()
    d.name.setText("مطالعه"); d.per.setValue(5)
    d.accept()
    h = win.store.vault["habits"][-1]
    assert win._editor is None and len(win.store.vault["habits"]) == n + 1 and h["name"] == "مطالعه" and h["perWeek"] == 5


def test_goals_and_habits_pages_open_the_page_editor(win, qtbot):
    setup_vault(win)
    win.show_page("goals"); win.pages["goals"]._new()
    assert isinstance(win._editor, dialogs.GoalDialog)
    win._close_editor(discard=True)
    win.show_page("habits"); win.pages["habits"]._new()
    assert isinstance(win._editor, dialogs.HabitDialog)
    win._close_editor(discard=True)
    assert win._editor is None


def test_time_field_api_and_picker(qtbot):
    from PyQt6.QtCore import QTime
    from aegis_desktop.ui.timepick import TimeField
    f = TimeField(); qtbot.addWidget(f); f.show()
    got = []
    f.timeChanged.connect(got.append)
    f.setTime(QTime(9, 30))
    assert f.time().toString("HH:mm") == "09:30" and "۰۹:۳۰" in f.text_now() and got
    f.nudge(35)
    assert f.time().toString("HH:mm") == "10:05"
    f.nudge(-24 * 60 * 2 - 10)                         # wraps around midnight both ways
    assert f.time().toString("HH:mm") == "09:55"
    f.open_popover()
    g = f.grid
    assert g.h == 9 and g.m == 55 and not g.grab().isNull()
    done = []
    g.picked.connect(done.append)
    g.h, g.m = 14, 20
    g.picked.emit(QTime(14, 20))
    assert f.time().toString("HH:mm") == "14:20" and not f.pop.isVisible()


def test_task_form_uses_time_field_and_saves_times(win, qtbot):
    from PyQt6.QtCore import QTime
    setup_vault(win)
    win.new_task(None)
    d = win._editor
    d.title.setText("با ساعت")
    d.use_time.setChecked(True)
    d.t_from.setTime(QTime(8, 15)); d.t_to.setTime(QTime(9, 45))
    d.accept()
    t = win.store.vault["tasks"][-1]
    assert (t["timeFrom"], t["timeTo"]) == ("08:15", "09:45")
