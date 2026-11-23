// SPDX-License-Identifier: GPL-3.0-or-later
//! Password variants.
//!
//! The Persian and Arabic keyboard layouts on Windows type different code
//! points for the "same" letters (ی/ي, ک/ك). A password created on one layout
//! must still open on the other, so unlocking tries a short list of variants.

use unicode_normalization::UnicodeNormalization;

use crate::SecretString;

/// Arabic → Persian letters (2.x `_TO_FA`).
fn to_persian(c: char) -> char {
    match c {
        '\u{064A}' | '\u{0649}' => '\u{06CC}', // ARABIC YEH, ALEF MAKSURA → FARSI YEH
        '\u{0643}' => '\u{06A9}',              // ARABIC KAF → KEHEH
        _ => c,
    }
}

/// Persian → Arabic letters (2.x `_TO_AR`).
fn to_arabic(c: char) -> char {
    match c {
        '\u{06CC}' => '\u{064A}',
        '\u{06A9}' => '\u{0643}',
        _ => c,
    }
}

/// The candidates a v1 vault is unlocked with, in order, without duplicates:
/// the password as typed, its NFC form, NFC with Arabic letters turned
/// Persian, and NFC with Persian letters turned Arabic.
///
/// The typed form comes first so an unaffected password costs one derivation.
/// See `docs/v3/spec/format-v1.md` §3.
#[must_use]
pub fn legacy_variants(password: &str) -> Vec<SecretString> {
    let nfc: String = password.nfc().collect();
    let fa: String = nfc.chars().map(to_persian).collect();
    let ar: String = nfc.chars().map(to_arabic).collect();
    let mut out: Vec<SecretString> = Vec::with_capacity(4);
    for candidate in [password.to_owned(), nfc, fa, ar] {
        if !out.iter().any(|s| s.expose() == candidate) {
            out.push(SecretString::new(candidate));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn texts(pw: &str) -> Vec<String> {
        legacy_variants(pw).iter().map(|s| s.expose().to_owned()).collect()
    }

    #[test]
    fn plain_ascii_has_one_variant() {
        assert_eq!(texts("hunter2"), ["hunter2"]);
    }

    #[test]
    fn arabic_letters_get_a_persian_variant() {
        assert_eq!(texts("يك"), ["يك", "یک"]);
        assert_eq!(texts("یک"), ["یک", "يك"]);
    }
}
