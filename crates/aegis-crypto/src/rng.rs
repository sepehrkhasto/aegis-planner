// SPDX-License-Identifier: GPL-3.0-or-later
//! Random bytes from the operating system (`getrandom`).
//!
//! There is no user-space generator and no fallback: if the OS cannot supply
//! randomness, the operation fails.

use crate::{Error, Key256, aead::Nonce};

/// Fills `buf` with random bytes.
///
/// # Errors
/// [`Error::Rng`] when the operating system generator fails.
pub fn fill(buf: &mut [u8]) -> Result<(), Error> {
    getrandom::fill(buf).map_err(|_| Error::Rng)
}

/// A fresh random 256-bit key.
///
/// # Errors
/// [`Error::Rng`] when the operating system generator fails.
pub fn key() -> Result<Key256, Error> {
    let mut k = Key256::zeroed();
    fill(k.as_mut())?;
    Ok(k)
}

/// A fresh random 96-bit AES-GCM nonce.
///
/// # Errors
/// [`Error::Rng`] when the operating system generator fails.
pub fn nonce() -> Result<Nonce, Error> {
    let mut n = [0u8; crate::aead::NONCE_LEN];
    fill(&mut n)?;
    Ok(n)
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]

    #[test]
    fn keys_and_nonces_differ() {
        assert_ne!(super::key().unwrap(), super::key().unwrap());
        assert_ne!(super::nonce().unwrap(), super::nonce().unwrap());
    }
}
