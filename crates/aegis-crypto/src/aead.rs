// SPDX-License-Identifier: GPL-3.0-or-later
//! AES-256-GCM.
//!
//! The output layout is `ciphertext ‖ 16-byte tag`, the same as WebCrypto, so
//! data sealed here opens in the Aegis web app and the other way round.
//!
//! Decryption works in place inside a zeroising buffer: the plaintext never
//! exists in memory that is not wiped on drop.

use aes_gcm::Aes256Gcm;
use aes_gcm::aead::generic_array::GenericArray;
use aes_gcm::aead::{AeadInPlace, KeyInit};

use crate::{Error, Key256, SecretBytes, rng};

/// Nonce length in bytes.
pub const NONCE_LEN: usize = 12;
/// Authentication tag length in bytes.
pub const TAG_LEN: usize = 16;

/// A 96-bit nonce.
pub type Nonce = [u8; NONCE_LEN];

fn cipher(key: &Key256) -> Aes256Gcm {
    Aes256Gcm::new(GenericArray::from_slice(key.expose()))
}

/// Encrypts `plaintext` under a fresh random nonce.
///
/// Returns the nonce and `ciphertext ‖ tag`. This is the function to use; a
/// nonce must never be used twice with the same key.
///
/// # Errors
/// [`Error::Rng`] if no nonce can be drawn, [`Error::TooLong`] if the input
/// exceeds the AES-GCM limit.
pub fn seal(key: &Key256, aad: &[u8], plaintext: &[u8]) -> Result<(Nonce, Vec<u8>), Error> {
    let nonce = rng::nonce()?;
    let sealed = seal_with_nonce(key, &nonce, aad, plaintext)?;
    Ok((nonce, sealed))
}

/// Encrypts with a caller-chosen nonce.
///
/// **Only for known-answer tests.** Reusing a nonce with the same key destroys
/// both confidentiality and integrity of AES-GCM. Production code calls [`seal`].
///
/// # Errors
/// [`Error::TooLong`] if the input exceeds the AES-GCM limit.
pub fn seal_with_nonce(key: &Key256, nonce: &Nonce, aad: &[u8], plaintext: &[u8]) -> Result<Vec<u8>, Error> {
    let mut buf = Vec::with_capacity(plaintext.len().saturating_add(TAG_LEN));
    buf.extend_from_slice(plaintext);
    cipher(key).encrypt_in_place(GenericArray::from_slice(nonce), aad, &mut buf).map_err(|_| Error::TooLong)?;
    Ok(buf)
}

/// Decrypts `ciphertext ‖ tag`.
///
/// # Errors
/// [`Error::Authentication`] when the key is wrong or any byte of the nonce,
/// associated data or ciphertext was changed.
pub fn open(key: &Key256, nonce: &Nonce, aad: &[u8], sealed: &[u8]) -> Result<SecretBytes, Error> {
    if sealed.len() < TAG_LEN {
        return Err(Error::Authentication);
    }
    let mut buf = SecretBytes::new(sealed.to_vec());
    cipher(key)
        .decrypt_in_place(GenericArray::from_slice(nonce), aad, buf.as_mut_vec())
        .map_err(|_| Error::Authentication)?;
    Ok(buf)
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, clippy::indexing_slicing)]
    use super::*;

    #[test]
    fn round_trip_and_tamper() {
        let key = rng::key().unwrap();
        let (nonce, mut ct) = seal(&key, b"hdr", b"secret data").unwrap();
        assert_eq!(ct.len(), 11 + TAG_LEN);
        assert_eq!(open(&key, &nonce, b"hdr", &ct).unwrap().expose(), b"secret data");
        assert_eq!(open(&key, &nonce, b"other", &ct).unwrap_err(), Error::Authentication);
        ct[0] ^= 1;
        assert_eq!(open(&key, &nonce, b"hdr", &ct).unwrap_err(), Error::Authentication);
    }

    #[test]
    fn short_input_is_rejected_not_panicking() {
        let key = rng::key().unwrap();
        assert_eq!(open(&key, &[0; NONCE_LEN], b"", &[0; 3]).unwrap_err(), Error::Authentication);
        assert_eq!(open(&key, &[0; NONCE_LEN], b"", &[]).unwrap_err(), Error::Authentication);
    }
}
