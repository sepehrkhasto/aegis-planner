# SPDX-License-Identifier: GPL-3.0-or-later
"""The brand voice: short, calm, sure. One place for the phrases that recur, so the tone never drifts.

Rules of thumb: say what happened in as few words as possible, in plain words (a status line says «ذخیره شد», not a
metaphor); keep the ceremonial «مهر» for the two or three moments that are about completion (the day seal, the week
seal); address the reader as «تو», never «شما»; never exclaim, never shout, no emoji.
"""

VOICE = {
    "saved": "ذخیره شد",                       # autosave status: «ذخیره شد ۱۲:۳۹:۳۰»
    "locked": "خوش برگشتی",                    # heading of the sign-in card (the vault is closed)
    "day_done": "همه‌ی کارهای امروز تمام شد",  # Today's sub-title when nothing is left
    "seal": "مهر شد",                          # caption of the day seal (a ceremony, so the metaphor stays)
    "vault_born": "ولتت آماده است",            # first run: the shield holds still while this line is engraved
}
