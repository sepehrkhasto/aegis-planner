# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut real static weights (300/400/500/600/700) out of the bundled variable Vazirmatn (same family, same licence - nothing new).

Qt registers a variable font as ONE style ("Regular"), so every weight the UI asked for above 500 was a faux-bold smear and 300/500/600
looked identical to 400. Static instances give the UI honest Light / Regular / Medium / SemiBold / Bold.

Run once (python tools/make_font_instances.py); the results live in aegis_desktop/assets/fonts/Vazirmatn-<weight>.ttf.
"""
from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "aegis_desktop" / "assets" / "Vazirmatn.ttf"
OUT = ROOT / "aegis_desktop" / "assets" / "fonts"
WEIGHTS = {300: "Light", 400: "Regular", 500: "Medium", 600: "SemiBold", 700: "Bold"}
FAMILY = "Vazirmatn"


def cut(weight: int, style: str) -> Path:
    inst = instancer.instantiateVariableFont(TTFont(SRC), {"wght": weight}, inplace=False)
    ribbi = style in ("Regular", "Bold")                         # the four-style family Windows GDI understands
    names = inst["name"]
    names.names = [n for n in names.names if n.nameID not in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25)]
    for nid, text in ((1, FAMILY if ribbi else f"{FAMILY} {style}"), (2, style if ribbi else "Regular"),
                      (3, f"{FAMILY}-{style};static"), (4, f"{FAMILY} {style}"), (6, f"{FAMILY}-{style}"),
                      (16, FAMILY), (17, style)):
        names.setName(text, nid, 3, 1, 0x409)
    os2 = inst["OS/2"]
    os2.usWeightClass = weight
    sel = os2.fsSelection & ~(0x01 | 0x20 | 0x40)                 # clear italic / bold / regular
    os2.fsSelection = sel | (0x20 if style == "Bold" else 0x40 if style == "Regular" else 0)
    inst["head"].macStyle = 1 if style == "Bold" else 0
    for tag in ("STAT",):
        if tag in inst:
            del inst[tag]
    dest = OUT / f"{FAMILY}-{weight}.ttf"
    inst.save(dest)
    return dest


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for w, s in WEIGHTS.items():
        d = cut(w, s)
        print(d.name, d.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
