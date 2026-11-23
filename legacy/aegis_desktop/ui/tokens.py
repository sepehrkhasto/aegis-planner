# SPDX-License-Identifier: GPL-3.0-or-later
"""Design tokens: the one place that says how big text, gaps and corners are.

Type is a fixed scale (pt); spacing is a 4-point ladder; radii are four steps that ``theme.rr`` then scales with the
user's corner-roundness preference. Pages and the stylesheet read from here, so a value is never invented in place."""
from __future__ import annotations

# ------------------------------------------------------------------------------------------ type scale (pt) ---
TYPE = {
    "caption": 8.5,      # group labels, chips, status bar, hints
    "small": 10.0,       # secondary lines
    "body": 10.5,        # navigation, controls
    "h3": 13.0,          # tile / card headings
    "h2": 12.75,         # card titles
    "h1": 20.0,          # page titles
    "stat": 20.0,        # numbers in tiles
    "brand": 15.5,       # the wordmark in the sidebar
    "hero": 44.0,        # big numerals
}

# Real static weights of Vazirmatn (assets/fonts/Vazirmatn-<w>.ttf). Restraint reads as luxury: regular text stays 400, small
# labels and row titles step up to 500, headings to 600, and 700 is kept for the few things that must shout (a primary number).
WEIGHT = {"light": 300, "body": 400, "label": 500, "title": 600, "strong": 700}

# ---------------------------------------------------------------------------------------------- spacing (px) ---
SPACE = {"xxs": 2, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32, "huge": 48}
GAP = 12                     # default gap between siblings in a page
GAP_TIGHT = 8
GAP_LOOSE = 14
PAGE = (24, 20, 24, 20)      # left, top, right, bottom margin every page uses
CARD = (16, 14, 16, 14)      # inside a card
DIALOG = (22, 20, 22, 18)    # every dialog

# ----------------------------------------------------------------------------------------------- radius (px) ---
RADIUS = {"sm": 6, "md": 10, "lg": 14, "xl": 20}

# ---------------------------------------------------------------------------------------------------- motion ---
DURATION = {"instant": 90, "fast": 160, "base": 240, "slow": 420, "scene": 900}      # ms
