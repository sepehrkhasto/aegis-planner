# SPDX-License-Identifier: GPL-3.0-or-later
"""Fonts, radius scale and the application stylesheet; the colours live in themes_data.py."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtCore import Qt

from .tokens import TYPE as TY
from .tokens import WEIGHT as FW
from .themes_data import DEFAULT as DEFAULT_THEME, DOTS as THEME_DOTS, ORDER as THEME_ORDER, SIGNATURE, THEMES  # noqa: F401  (re-exported)

PALETTES = {"dark": dict(THEMES["noir"]["pal"]), "light": dict(THEMES["aegis-light"]["pal"])}   # slots filled by set_theme()
RADIUS = [8]
THEME = [DEFAULT_THEME]


def mode_of(key: str) -> str:
    """"dark" | "light" - the PALETTES slot a theme lives in (unknown keys fall back to the default theme)."""
    return (THEMES.get(key) or THEMES[DEFAULT_THEME])["mode"]


def set_theme(key: str) -> str:
    """Activate a theme in place (widgets read PALETTES at paint time). Returns the mode it fills."""
    key = key if key in THEMES else DEFAULT_THEME
    t = THEMES[key]
    PALETTES[t["mode"]].update(t["pal"])
    RADIUS[0] = max(8, int(t.get("radius", 8)))
    THEME[0] = key
    return t["mode"]


# Qt mirrors AlignLeft/AlignRight in an RTL app (AlignRight lands on the visual *left*). Custom painting always
# means a physical side, so use these instead of the bare flags.
AL_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute
AL_L = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute


def rr(n: float) -> float:
    """Scale a design radius (authored for the default 8px theme) to the active theme's radius."""
    return max(0.0, n * RADIUS[0] / 8.0)


def chart_colors(mode: str) -> list:
    return list(THEMES[THEME[0]]["chart"])


def asset_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "assets" / name
    if not p.exists():                                  # PyInstaller layout fallback
        p = base / "aegis_desktop" / "assets" / name
    return p


def load_font(app, point_size: int = 10) -> str:
    """Vazirmatn for Persian (and Persian digits), Inter for Latin text - both SIL OFL, bundled in assets/.
    Qt picks the font per script run from the family list, so a mixed line («Aegis ۱۲ مهر Ctrl+K») renders each
    part in the face designed for it."""
    family = "Segoe UI"
    fonts = asset_path("fonts")
    statics = sorted(fonts.glob("Vazirmatn-*.ttf")) if fonts.is_dir() else []
    # Real Light/Regular/Medium/SemiBold/Bold cut from the variable font (tools/make_font_instances.py). Qt registers a
    # variable font as a single style, which turned every weight above Regular into a faux-bold smear; the static cuts are the
    # same family, so nothing changes but the letters get honest weights. The variable file stays as the fallback.
    for ttf in statics or [asset_path("Vazirmatn.ttf")]:
        fid = QFontDatabase.addApplicationFont(str(ttf))
        if fid >= 0 and family == "Segoe UI":
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                family = fams[0]
    latin = None
    for ttf in sorted(fonts.glob("Inter-*.ttf")) if fonts.is_dir() else []:
        lid = QFontDatabase.addApplicationFont(str(ttf))
        if lid >= 0 and QFontDatabase.applicationFontFamilies(lid):
            latin = QFontDatabase.applicationFontFamilies(lid)[0]
    f = QFont(family, point_size)
    if latin:
        f.setFamilies([latin, family])
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(f)
    from .brand import load_display_font
    load_display_font()                                 # Cormorant Garamond: the brand's display face (Latin only)
    return family


def _ui_assets(c: dict) -> dict:
    """Render the small glyphs QSS needs as image files (chevron for combos, tick for check indicators)."""
    import tempfile

    from PyQt6.QtCore import QByteArray
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    from . import icons

    d = Path(tempfile.gettempdir()) / "aegis_ui"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    out = {}
    for key, icon, color in (("chev", "chevron", c["muted"]), ("chev_hi", "chevron", c["text"]),
                             ("tick", "tick", c["ink"]), ("up", "chevron_up", c["muted"])):
        stem = f"{key}_{color.lstrip('#')}"
        for scale, suffix in ((1, ""), (2, "@2x")):
            f = d / f"{stem}{suffix}.png"
            if not f.exists():
                px = 14 * scale
                svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                       + icons.ICONS[icon].replace("currentColor", color) + "</svg>")
                img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(Qt.GlobalColor.transparent)
                p = QPainter(img)
                QSvgRenderer(QByteArray(svg.encode())).render(p)
                p.end()
                img.save(str(f), "PNG")
        out[key] = (d / f"{stem}.png").as_posix()
    return out


def stylesheet(name: str) -> str:
    c = PALETTES[name]
    a = _ui_assets(c)
    chev, chev_hi, tick, up = (a.get(k, "") for k in ("chev", "chev_hi", "tick", "up"))
    r = RADIUS[0]
    _m = QColor(c['muted'])
    sb = f"rgba({_m.red()},{_m.green()},{_m.blue()},0.16)"            # resting: a thin, barely-there translucent thumb
    sb_on = f"rgba({_m.red()},{_m.green()},{_m.blue()},0.55)"          # while scrolling (see scrollfx) / hovered
    sb_hot = f"rgba({_m.red()},{_m.green()},{_m.blue()},0.80)"
    card_border = f"border: 1px solid {c['line']};"
    _ac = QColor(c["accent"])
    prim_hi = _ac.lighter(112).name()          # hover: a touch brighter, never a different hue
    prim_lo = _ac.darker(112).name()
    _a2 = QColor(c["accent2"])
    link_c = _a2.lighter(140).name() if QColor(c["bg"]).lightness() < 128 else _a2.name()
    sel_bg = f"rgba({_a2.red()},{_a2.green()},{_a2.blue()},0.45)"     # text selection: calm indigo, readable text
    return f"""
* {{ outline: none; }}
QWidget {{ background: {c['bg']}; color: {c['text']}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['line']}; padding: 4px; }}

#Sidebar {{ background: {c['panel']}; border-left: 1px solid {c['line']}; }}
#Sidebar QLabel#Brand {{ font-family: 'Cormorant Garamond'; font-size: {TY['brand']}pt; font-weight: 700; color: {c['acc_text']}; padding: 0; }}
#Sidebar QLabel#BrandTile {{ background: {c['accent']}; color: {c['ink']}; border-radius: {r+1}px; font-weight: {FW['strong']}; font-size: {TY['h3']}pt; }}
#Sidebar QLabel#GroupLabel {{ color: {c['muted']}; font-size: {TY['caption']}pt; font-weight: {FW['label']}; padding: 6px 20px 6px 20px; }}
#Sidebar QLabel#BrandSub {{ color: {c['muted']}; font-size: {TY['caption']}pt; padding: 0; }}
#Sidebar QPushButton {{ background: transparent; border: none; border-radius: {r}px; text-align: left;
    padding: 9px 12px; margin: 1px 8px; color: {c['muted']}; font-size: {TY['body']}pt; }}
#Sidebar QPushButton:hover {{ background: {c['panel2']}; color: {c['text']}; }}
#Sidebar QPushButton:focus {{ border: 1px solid {c['accent2']}; }}
#Sidebar QFrame#SideDivider {{ background: {c['line']}; border: none; margin: 0 14px; max-height: 1px; }}
#Sidebar QPushButton:checked {{ background: {c['soft']}; color: {c['acc_text']}; font-weight: {FW['title']}; }}

.Card, QFrame#Card {{ background: {c['panel']}; {card_border} border-radius: {r+4}px; }}
QFrame#Card QLabel {{ background: transparent; }}
QLabel#H1 {{ font-size: {TY['h1']}pt; font-weight: {FW['title']}; }}
QLabel#H2 {{ font-size: {TY['h2']}pt; font-weight: {FW['title']}; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Danger {{ color: {c['danger']}; }}
QLabel#Ok {{ color: {c['ok']}; }}
QLabel#Big {{ font-size: {TY['hero']}pt; font-weight: {FW['title']}; color: {c['acc_text']}; }}
QLabel#Stat {{ font-size: {TY['stat']}pt; font-weight: {FW['title']}; color: {c['acc_text']}; }}

QPushButton {{ background: {c['panel2']}; border: 1px solid {c['line']}; border-radius: {r}px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {c['muted']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: {c['ink']}; border: 1px solid {c['accent']}; font-weight: {FW['title']}; }}
QPushButton#Primary:hover {{ background: {prim_hi}; border-color: {prim_hi}; }}
QPushButton#Primary:pressed {{ background: {prim_lo}; border-color: {prim_lo}; }}
QPushButton#Primary:disabled {{ background: {c['panel2']}; color: {c['muted']}; border-color: {c['line']}; }}
QLabel#HeroTag {{ color: {c['muted']}; font-size: {TY['small']}pt; letter-spacing: 3px; }}
QLabel#Chip {{ background: {c['soft']}; color: {c['acc_text']}; border-radius: {r+2}px; padding: 3px 10px; font-size: {TY['caption']}pt; font-weight: {FW['label']}; }}
QPushButton#Danger {{ color: {c['danger']}; }}
QPushButton#Toggle:checked {{ background: {c['soft']}; color: {c['acc_text']}; border-color: {c['accent']}; }}
QPushButton#Link {{ background: transparent; border: none; color: {link_c}; }}
QPushButton#Link:hover {{ color: {c['text']}; text-decoration: underline; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
    background: {c['panel']}; border: 1px solid {c['line']}; border-radius: {r}px; padding: 6px 8px;
    selection-background-color: {sel_bg}; selection-color: {c['text']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {c['accent2']}; }}
QComboBox {{ padding-left: 26px; }}
QSpinBox, QTimeEdit {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: {r}px;
    padding: 6px 8px 6px 24px; selection-background-color: {sel_bg}; selection-color: {c['text']}; }}
QSpinBox:focus, QTimeEdit:focus {{ border-color: {c['accent2']}; }}
QSpinBox::up-button, QTimeEdit::up-button {{ subcontrol-origin: border; subcontrol-position: top left; width: 22px;
    border: none; background: transparent; margin-top: 3px; }}
QSpinBox::down-button, QTimeEdit::down-button {{ subcontrol-origin: border; subcontrol-position: bottom left; width: 22px;
    border: none; background: transparent; margin-bottom: 3px; }}
QSpinBox::up-arrow, QTimeEdit::up-arrow {{ image: url({up}); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QTimeEdit::down-arrow {{ image: url({chev}); width: 11px; height: 11px; }}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center left; border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({chev}); width: 14px; height: 14px; }}
QComboBox:hover::down-arrow, QComboBox:focus::down-arrow, QComboBox:on::down-arrow {{ image: url({chev_hi}); }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['line']};
    selection-background-color: {c['soft']}; selection-color: {c['text']}; }}

QListWidget, QTableWidget, QTreeWidget {{ background: {c['panel']}; border: 1px solid {c['line']};
    border-radius: {r+2}px; alternate-background-color: {c['panel']}; gridline-color: {c['line']}; }}
QListWidget::item {{ padding: 7px 8px; border-radius: {max(2, r-2)}px; }}
QListWidget::item:selected, QTableWidget::item:selected, QTreeWidget::item:selected {{
    background: {c['soft']}; color: {c['text']}; }}
QHeaderView::section {{ background: transparent; color: {c['muted']}; border: none;
    border-bottom: 1px solid {c['line']}; padding: 6px; font-size: {TY['caption']}pt; font-weight: {FW['label']}; }}
QTableWidget::item {{ padding: 4px; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: {min(5, r)}px; border: 1.5px solid {c['muted']}; background: {c['panel']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({tick}); }}
QCheckBox::indicator:hover {{ border-color: {c['muted']}; }}
QRadioButton {{ spacing: 8px; background: transparent; }}
QRadioButton::indicator {{ width: 13px; height: 13px; border-radius: 8px; border: 1.5px solid {c['muted']}; background: {c['panel']}; }}
QRadioButton::indicator:hover {{ border-color: {c['muted']}; }}
QRadioButton::indicator:checked {{ width: 6px; height: 6px; border-radius: 8px; border: 5px solid {c['accent']}; background: {c['panel']}; }}
QAbstractItemView::indicator {{ width: 16px; height: 16px; border-radius: {min(5, r)}px; border: 1.5px solid {c['muted']}; background: {c['panel']}; }}
QAbstractItemView::indicator:hover {{ border-color: {c['muted']}; }}
QAbstractItemView::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({tick}); }}

QProgressBar {{ background: {c['panel2']}; border: none; border-radius: {max(2, r-2)}px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: {max(2, r-2)}px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 1px; }}
QScrollBar::handle:vertical {{ background: {sb}; border-radius: 2px; min-height: 36px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {sb_hot}; margin: 0; border-radius: 3px; }}
QScrollBar::handle:vertical:pressed {{ background: {sb_hot}; margin: 0; border-radius: 3px; }}
QScrollBar[active="true"]::handle:vertical {{ background: {sb_on}; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 1px 3px; }}
QScrollBar::handle:horizontal {{ background: {sb}; border-radius: 2px; min-width: 36px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover {{ background: {sb_hot}; margin: 0; border-radius: 3px; }}
QScrollBar[active="true"]::handle:horizontal {{ background: {sb_on}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

QMenu {{ background: {c['panel']}; border: 1px solid {c['line']}; border-radius: {r+4}px; padding: 6px; }}
QMenu::item {{ padding: 8px 14px 8px 26px; margin: 1px 0; border-radius: {max(4, r-1)}px; }}
QMenu::item:selected {{ background: {c['soft']}; color: {c['acc_text']}; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 5px 8px; }}
QDialog {{ background: {c['bg']}; }}
QGroupBox {{ border: 1px solid {c['line']}; border-radius: {r+2}px; margin-top: 14px; padding: 12px 10px 8px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; margin-right: 14px; padding: 0 6px; color: {c['muted']}; }}
QSplitter::handle {{ background: {c['line']}; }}
QTabWidget::pane {{ border: 1px solid {c['line']}; border-radius: {r}px; }}
QStatusBar {{ background: {c['panel']}; color: {c['muted']}; border-top: 1px solid {c['line']}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QWidget {{ background: transparent; }}
QLabel#StatusText {{ color: {c['muted']}; font-size: {TY['caption']}pt; }}
QPushButton:focus, QComboBox:focus {{ border-color: {c['accent2']}; }}
QLabel#RowTitle {{ font-weight: {FW['label']}; }}
QFrame#Hair {{ background: {c['line']}; border: none; }}
QWidget#SRow, QWidget#SRow QWidget {{ background: transparent; }}
/* the rule above (1 id + 2 types) outranks QPushButton#Primary (1 id + 1 type): a Primary button inside a settings row lost its fill
   and showed dark ink on nothing. Restated with an id on each side so it wins again. */
QWidget#SRow QPushButton#Primary {{ background: {c['accent']}; color: {c['ink']}; border: 1px solid {c['accent']}; }}
QWidget#SRow QPushButton#Primary:hover {{ background: {prim_hi}; border-color: {prim_hi}; }}
QWidget#SRow QPushButton#Primary:pressed {{ background: {prim_lo}; border-color: {prim_lo}; }}
QWidget#SRow QPushButton#Primary:disabled {{ background: {c['panel2']}; color: {c['muted']}; border-color: {c['line']}; }}
QListWidget#BackupList {{ background: transparent; border: none; }}
QListWidget#BackupList::item {{ background: transparent; border: none; }}
QWidget:disabled {{ color: {c['muted']}; }}
"""


_QSS_NOW: list = [None]
_FUSION_SET: list = [False]


def install_stylesheet(app, sheet: str) -> bool:
    """Put ``sheet`` on the application - fast. Replacing a live sheet makes Qt re-evaluate every rule for every widget
    it has ever built (~750 here, ten hidden pages included: ~0.9 s). Dropping the old sheet first makes Qt polish only the
    widgets that are on screen now; the rest are polished by Qt itself the moment they are shown. Returns False when the
    sheet is already installed (nothing to do)."""
    if _QSS_NOW[0] == sheet and app.styleSheet() == sheet:
        return False
    if app.styleSheet():
        app.setStyleSheet("")
    app.setStyleSheet(sheet)
    _QSS_NOW[0] = sheet
    return True


def apply_palette(app, name: str) -> None:
    """Fusion + a matching QPalette so natively-drawn parts (spin arrows, etc.) use the theme colors."""
    c = PALETTES[name]
    if not _FUSION_SET[0]:                       # re-creating the base style re-polishes every widget: once is enough
        app.setStyle("Fusion")
        _FUSION_SET[0] = True
    pal = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "panel"),
                      (QPalette.ColorRole.AlternateBase, "panel2"), (QPalette.ColorRole.Button, "panel2"),
                      (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Text, "text"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.BrightText, "text"),
                      (QPalette.ColorRole.ToolTipBase, "panel2"), (QPalette.ColorRole.ToolTipText, "text"),
                      (QPalette.ColorRole.Highlight, "accent"), (QPalette.ColorRole.HighlightedText, "ink"),
                      (QPalette.ColorRole.PlaceholderText, "muted"), (QPalette.ColorRole.Link, "accent")):
        pal.setColor(role, QColor(c[key]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["muted"]))
    app.setPalette(pal)
    try:
        from . import winchrome
        winchrome.set_theme(app, c, name == "dark")
    except Exception:  # noqa: BLE001 - cosmetic only
        pass
