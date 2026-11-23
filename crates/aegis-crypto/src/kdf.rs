// SPDX-License-Identifier: GPL-3.0-or-later
//! Password-based key derivation.
//!
//! Only PBKDF2-HMAC-SHA256 exists so far: it is what format v1 uses. Argon2id
//! for format v2 arrives in roadmap phase 15. The cost parameters are checked by
//! the format layer *before* calling in here; this module derives whatever it
//! is asked to.

use core::num::NonZeroU32;

use sha2::Sha256;

use crate::Key256;

/// PBKDF2-HMAC-SHA256 with a 32-byte output.
///
/// `secret` is the password (UTF-8 bytes) or a decoded recovery key.
#[must_use]
pub fn pbkdf2_sha256(secret: &[u8], salt: &[u8], iterations: NonZeroU32) -> Key256 {
    let mut out = Key256::zeroed();
    pbkdf2::pbkdf2_hmac::<Sha256>(secret, salt, iterations.get(), out.as_mut());
    out
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    /// RFC 7914 §11 / RFC 6070-style vector for PBKDF2-HMAC-SHA256.
    #[test]
    fn known_answer() {
        let k = pbkdf2_sha256(b"password", b"salt", NonZeroU32::new(1).unwrap());
        assert_eq!(hex::encode(k.expose()), "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b");
    }
}
