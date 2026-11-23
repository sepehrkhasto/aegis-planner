// SPDX-License-Identifier: GPL-3.0-or-later
//! Wrapping the data key.
//!
//! A vault's data is encrypted with a random data key (DEK). The DEK is stored
//! encrypted ("wrapped") under a key derived from the password, and optionally a
//! second time under a key derived from the recovery key. Changing the password
//! then only rewraps 32 bytes.

use crate::aead::{self, Nonce, TAG_LEN};
use crate::secret::KEY_LEN;
use crate::{Error, Key256};

/// Length of a wrapped key: 32 bytes of ciphertext plus the tag.
pub const WRAPPED_LEN: usize = KEY_LEN + TAG_LEN;

/// A DEK encrypted under a KEK.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WrappedKey {
    /// Nonce used for this wrapping.
    pub nonce: Nonce,
    /// `AES-256-GCM(KEK, DEK)`: ciphertext ‖ tag.
    pub sealed: Vec<u8>,
}

/// Wraps `dek` under `kek` with a fresh nonce.
///
/// # Errors
/// [`Error::Rng`] if no nonce can be drawn.
pub fn wrap(kek: &Key256, dek: &Key256) -> Result<WrappedKey, Error> {
    let (nonce, sealed) = aead::seal(kek, &[], dek.expose())?;
    Ok(WrappedKey { nonce, sealed })
}

/// Unwraps a DEK.
///
/// # Errors
/// [`Error::Authentication`] when `kek` is wrong or the wrapped key was
/// modified; [`Error::InvalidLength`] when it decrypts to something that is not
/// a 32-byte key.
pub fn unwrap(kek: &Key256, wrapped: &WrappedKey) -> Result<Key256, Error> {
    let plain = aead::open(kek, &wrapped.nonce, &[], &wrapped.sealed)?;
    Key256::from_slice(plain.expose())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;
    use crate::rng;

    #[test]
    fn wrap_unwrap() {
        let (kek, dek) = (rng::key().unwrap(), rng::key().unwrap());
        let w = wrap(&kek, &dek).unwrap();
        assert_eq!(w.sealed.len(), WRAPPED_LEN);
        assert_eq!(unwrap(&kek, &w).unwrap(), dek);
        assert_eq!(unwrap(&rng::key().unwrap(), &w).unwrap_err(), Error::Authentication);
    }

    #[test]
    fn short_plaintext_is_not_a_key() {
        let kek = rng::key().unwrap();
        let (nonce, sealed) = aead::seal(&kek, &[], &[1; 16]).unwrap();
        let err = unwrap(&kek, &WrappedKey { nonce, sealed }).unwrap_err();
        assert!(matches!(err, Error::InvalidLength { expected: 32, actual: 16, .. }));
    }
}
