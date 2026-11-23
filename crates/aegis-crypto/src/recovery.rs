// SPDX-License-Identifier: GPL-3.0-or-later
//! Recovery-key text, format v1.
//!
//! A v1 recovery key is 20 random bytes in Crockford's base32 alphabet,
//! shown as `AEGIS-XXXXX-…-XX`. Decoding is deliberately forgiving and decodes
//! the *whole* text, including the `AEGIS` prefix, which is therefore part of
//! the key-derivation input. That quirk is kept bit for bit so existing keys
//! keep working; `docs/v3/spec/format-v1.md` §5 has the details.

use core::num::NonZeroU32;

use crate::{Error, SecretBytes, SecretString, rng};

/// PBKDF2 rounds for the recovery KEK. Fixed by 2.x; not stored in the file.
pub const LEGACY_ITERATIONS: NonZeroU32 = match NonZeroU32::new(600_000) {
    Some(n) => n,
    None => NonZeroU32::MIN,
};

/// Random bytes in a new v1 recovery key.
pub const LEGACY_KEY_BYTES: usize = 20;

const ALPHABET: [char; 32] = [
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'M', 'N', 'P',
    'Q', 'R', 'S', 'T', 'V', 'W', 'X', 'Y', 'Z',
];

fn symbol(index: u32) -> char {
    // `index` is masked to 5 bits by every caller, so it is always in range.
    ALPHABET.get(usize::try_from(index & 31).unwrap_or(0)).copied().unwrap_or('0')
}

fn value(c: char) -> Option<u32> {
    ALPHABET.iter().position(|&a| a == c).and_then(|i| u32::try_from(i).ok())
}

/// Encodes bytes, most significant bit first; a final partial group is padded
/// with zero bits on the right. No separators, no check symbol.
#[must_use]
pub fn encode(data: &[u8]) -> String {
    let mut out = String::with_capacity(data.len().saturating_mul(8).div_ceil(5));
    let (mut acc, mut bits) = (0u32, 0u32);
    for &byte in data {
        acc = (acc << 8) | u32::from(byte);
        bits += 8;
        while bits >= 5 {
            out.push(symbol(acc >> (bits - 5)));
            bits -= 5;
        }
        acc &= (1 << bits) - 1;
    }
    if bits > 0 {
        out.push(symbol(acc << (5 - bits)));
    }
    out
}

/// Python's `str.strip()`: Unicode white space plus the ASCII information
/// separators U+001C–U+001F, which Python also treats as space.
fn py_strip(text: &str) -> &str {
    text.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

/// Decodes recovery-key text the way 2.x does: full Unicode upper-casing, drop
/// everything that is not ASCII `0-9A-Z`, read `O` as `0`, `I`/`L` as `1`, `U`
/// as `V`, emit a byte every 8 bits, drop leftover bits.
#[must_use]
pub fn decode_lenient(text: &str) -> SecretBytes {
    let upper = SecretString::new(text.to_uppercase());
    // Five bits per symbol: the output is never longer than the input, so the
    // buffer is allocated once and never reallocated (no stray copies).
    let mut out = SecretBytes::new(Vec::with_capacity(upper.expose().len()));
    let (mut acc, mut bits) = (0u32, 0u32);
    for c in upper.expose().chars() {
        let c = match c {
            'O' => '0',
            'I' | 'L' => '1',
            'U' => 'V',
            c => c,
        };
        let Some(v) = value(c) else { continue };
        acc = (acc << 5) | v;
        bits += 5;
        if bits >= 8 {
            out.as_mut_vec().push(u8::try_from((acc >> (bits - 8)) & 0xFF).unwrap_or(0));
            bits -= 8;
            acc &= (1 << bits) - 1;
        }
    }
    out
}

/// The texts tried when a user types a v1 recovery key: the trimmed text, and,
/// unless it already starts with `AEGIS`, the same text with `AEGIS-` in front.
#[must_use]
pub fn legacy_candidates(typed: &str) -> Vec<SecretString> {
    let text = py_strip(typed);
    let mut out = vec![SecretString::new(text.to_owned())];
    let alnum =
        SecretString::new(text.chars().filter(char::is_ascii_alphanumeric).map(|c| c.to_ascii_uppercase()).collect());
    if !alnum.expose().starts_with("AEGIS") {
        out.push(SecretString::new(format!("AEGIS-{text}")));
    }
    out
}

/// A new v1 recovery key: `AEGIS-` followed by 32 symbols in groups of five.
///
/// # Errors
/// [`Error::Rng`] if the system random generator fails.
pub fn generate_legacy() -> Result<SecretString, Error> {
    let mut raw = SecretBytes::new(vec![0u8; LEGACY_KEY_BYTES]);
    rng::fill(raw.as_mut_vec())?;
    let symbols = SecretString::new(encode(raw.expose()));
    let mut text = String::with_capacity(64); // 44 characters: never reallocates
    text.push_str("AEGIS");
    for (i, c) in symbols.expose().chars().enumerate() {
        if i % 5 == 0 {
            text.push('-');
        }
        text.push(c);
    }
    Ok(SecretString::new(text))
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    #[test]
    fn generated_key_shape_and_round_trip() {
        let k = generate_legacy().unwrap();
        let parts: Vec<&str> = k.expose().split('-').collect();
        assert_eq!(parts.first(), Some(&"AEGIS"));
        assert_eq!(parts.iter().skip(1).map(|p| p.len()).collect::<Vec<_>>(), [5, 5, 5, 5, 5, 5, 2]);
        let body: String = parts.iter().skip(1).copied().collect();
        assert_eq!(encode(decode_lenient(&body).expose()), body);
    }

    #[test]
    fn python_strip_also_removes_information_separators() {
        assert_eq!(py_strip("\u{1c} ab\u{a0}\t"), "ab");
    }
}
