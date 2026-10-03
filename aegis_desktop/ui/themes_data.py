# SPDX-License-Identifier: GPL-3.0-or-later
"""Aegis themes - the whole colour system. Each theme is a complete palette (there is no separate dark/light switch).

Three brand themes, written by hand: ``noir`` (Aegis Noir, the default: deep cool near-black, neutral text, ONE restrained
accent, brushed platinum), ``ivory`` (عاج, warm paper) and ``aegis-light`` (چینی, porcelain). Thirteen more come from
curated four-colour palettes: ``_make`` builds a complete theme from the four swatches and then *enforces* contrast
(text on every surface, muted text, the ink on the accent, accent used as text) so no palette can ship unreadable.
``mode`` tells the app which PALETTES slot ("dark" | "light") the theme fills.
Palette keys: bg page · panel surface · panel2 elevated surface · line border · text/muted · accent (+ink on it, acc_text
= accent readable as text) · accent2 (focus / info) · hi highlight · danger/warn/ok · soft (selected surface) · edge.
"""

DEFAULT = "noir"
SIGNATURE = "noir"                       # the brand theme: splash, monogram on day themes, installer art


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def _mix(a: str, b: str, t: float) -> str:
    A, B = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(A, B)))


def _lum(h: str) -> float:
    def lin(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def _ensure(fg: str, bg: str, need: float, toward: str) -> str:
    """Push ``fg`` toward ``toward`` (white or black) until it reads at ``need``:1 on ``bg``."""
    t = 0.0
    out = fg
    while contrast(out, bg) < need and t < 1.0:
        t += 0.04
        out = _mix(fg, toward, t)
    return out


def _make(en: str, fa: str, tag: str, mode: str, bg: str, panel: str, panel2: str, accent: str, accent2: str,
          hi: str | None = None, tint: str | None = None) -> dict:
    dark = mode == "dark"
    white, black = "#ffffff", "#000000"
    tint = tint or panel
    text = _mix(white, tint, 0.07) if dark else _mix(black, tint, 0.10)
    text = _ensure(text, panel2, 9.0, white if dark else black)
    muted = _ensure(_mix(text, bg, 0.42), panel2, 4.8, white if dark else black)
    line = _mix(bg, text, 0.12 if dark else 0.14)
    edge = _mix(bg, text, 0.20 if dark else 0.20)
    soft = _mix(panel, accent, 0.12 if dark else 0.10)
    acc = accent if dark else _ensure(accent, panel, 4.5, black)         # a day accent must carry white ink
    ink = white if contrast(white, acc) >= contrast("#0a0a0c", acc) else "#0a0a0c"
    acc_text = _ensure(accent, panel, 4.6, white if dark else black)
    signal = dict(danger="#ef6b73", warn="#e5a94a", ok="#5fcf9c") if dark else dict(danger="#c23a48", warn="#9a6509", ok="#1a7d51")
    signal = {k: _ensure(v, panel2, 4.5, white if dark else black) for k, v in signal.items()}
    a2 = accent2 if dark else _ensure(accent2, panel, 3.2, black)
    chart = [acc if dark else acc, a2] + (["#b58fd6", "#6fbf9e", "#d9a066", "#8a8f98"] if dark else ["#b8577a", "#2f8f63", "#c07a1a", "#6b6e76"])
    return dict(en=en, fa=fa, tag=tag, mode=mode, radius=8, chart=chart,
                pal=dict(bg=bg, panel=panel, panel2=panel2, line=line, text=text, muted=muted, accent=acc, accent2=a2, ink=ink,
                         hi=_ensure(hi or accent2, panel, 3.2, white if dark else black), soft=soft, acc_text=acc_text, edge=edge, **signal))


THEMES = {
    "noir": dict(
        en="Aegis Noir", fa="آیجیس نوآر", tag="امضای برند", mode="dark", radius=8,
        chart=["#c9ced8", "#7f9bd6", "#b58fd6", "#6fbf9e", "#d9a066", "#8a8f98"],
        pal=dict(bg="#060607", panel="#0c0c0e", panel2="#131316", line="#212226", text="#ededf0", muted="#8b8c93",
                 accent="#dfe2e8", accent2="#f2f4f8", ink="#0a0a0c", hi="#f5f6f9", danger="#ef6b73", warn="#e5a94a",
                 ok="#5fcf9c", soft="#17171a", acc_text="#e9ebf0", edge="#2c2d32")),
    "ivory": dict(
        en="Aegis Ivory", fa="عاج", tag="کاغذ گرم", mode="light", radius=8,
        chart=["#3b3020", "#4a7ba8", "#a8505f", "#3f8a5f", "#b9791c", "#7b7462"],
        pal=dict(bg="#f5f1e8", panel="#fffdf8", panel2="#ece6d8", line="#ded6c4", text="#1c1913", muted="#625b4b",
                 accent="#3b3020", accent2="#5a4a2e", ink="#fffdf8", hi="#6e5a35", danger="#b83a3a", warn="#95620c",
                 ok="#2b7a4f", soft="#ebe4d3", acc_text="#3b3020", edge="#d6ceba")),
    "aegis-light": dict(
        en="Aegis Porcelain", fa="چینی", tag="روز", mode="light", radius=8,
        chart=["#3a3c44", "#3f7fb5", "#b8577a", "#2f8f63", "#c07a1a", "#6b6e76"],
        pal=dict(bg="#f4f4f6", panel="#ffffff", panel2="#eceef1", line="#dfe1e6", text="#111114", muted="#63666e",
                 accent="#25262b", accent2="#3a3c44", ink="#ffffff", hi="#55586a", danger="#c23a48", warn="#946a0c",
                 ok="#1a7d51", soft="#e9eaee", acc_text="#25262b", edge="#dfe1e6")),
    "deep-sea": _make("Deep Sea", "اعماق دریا", "", "dark", "#141d22", "#1B262C", "#223540", "#3282B8", "#BBE1FA", "#BBE1FA"),
    "coffee": _make("Coffee House", "قهوه‌خانه", "", "dark", "#1f2527", "#2C3639", "#3F4E4F", "#A27B5C", "#DCD7C9", "#DCD7C9"),
    "midnight": _make("Midnight Blue", "نیمه‌شب", "", "dark", "#061a33", "#0A2647", "#144272", "#2C74B3", "#8fc1f2", "#a9d0f7"),
    "teal-night": _make("Teal Night", "شب فیروزه‌ای", "", "dark", "#1f2525", "#2C3333", "#395B64", "#A5C9CA", "#E7F6F2", "#E7F6F2"),
    "slate": _make("Slate Ink", "جوهر لاجوردی", "", "dark", "#171d2b", "#212A3E", "#394867", "#9BA4B5", "#F1F6F9", "#F1F6F9"),
    "sunset": _make("Sunset Plum", "غروب آلویی", "", "dark", "#161d27", "#1d2a39", "#355C7D", "#F67280", "#f3a0b6", "#f9b9c4"),
    "sage-forest": _make("Sage Forest", "جنگل مریم‌گلی", "", "dark", "#1a2118", "#273022", "#40513B", "#9DC08B", "#EDF1D6", "#EDF1D6"),
    "ocean": _make("Ocean Depth", "ژرفای اقیانوس", "", "dark", "#0d2a3a", "#164863", "#1d5c7c", "#9BBEC8", "#DDF2FD", "#DDF2FD"),
    "mist": _make("Mist & Sand", "مه و ماسه", "", "light", "#EEE9DA", "#fbf9f2", "#e1e1d4", "#6096B4", "#93BFCF", "#4d7f9c"),
    "navy-snow": _make("Navy Snow", "برف و سرمه‌ای", "", "light", "#F9F7F7", "#ffffff", "#DBE2EF", "#3F72AF", "#112D4E", "#3F72AF"),
    "blush-dusk": _make("Blush Dusk", "گرگ‌ومیش صورتی", "", "light", "#F6F6F6", "#fffafa", "#FFE2E2", "#8785A2", "#b86f7a", "#8785A2"),
    "aqua": _make("Aqua Cream", "آبی فیروزه‌ای", "", "light", "#E3FDFD", "#f6fefe", "#CBF1F5", "#3aa6ad", "#71C9CE", "#3aa6ad"),
    "sage-linen": _make("Sage Linen", "کتان مریم‌گلی", "", "light", "#F7F2EB", "#fffdf9", "#EAE2D6", "#8B9A6E", "#6d7c52", "#8B9A6E"),
}
ORDER = ["noir", "deep-sea", "coffee", "midnight", "teal-night", "slate", "sunset", "sage-forest", "ocean",
         "aegis-light", "ivory", "mist", "navy-snow", "blush-dusk", "aqua", "sage-linen"]
DOTS = ["noir", "ivory", "aegis-light"]  # the sidebar capsule: one quiet row; Settings shows every theme
assert all(k in THEMES and not THEMES[k].get("hidden") for k in DOTS) and set(ORDER) == set(THEMES)
LIGHT = [k for k in ORDER if THEMES[k]["mode"] == "light"]        # Settings lists themes in two groups: dark, light
DARK = [k for k in ORDER if THEMES[k]["mode"] == "dark"]
