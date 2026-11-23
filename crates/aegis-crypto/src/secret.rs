// SPDX-License-Identifier: GPL-3.0-or-later
//! Types for secret values.
//!
//! All of them overwrite their memory with zeros when dropped, print as
//! `[redacted]`, and are not `Clone`: a copy of a secret has to be made on
//! purpose with [`Key256::duplicate`].
//!
//! Zeroising is best effort. It removes the value from memory this crate owns;
//! it cannot reach copies the operating system makes (swap, crash dumps).

use core::fmt;

use zeroize::Zeroizing;

use crate::Error;

/// Length of every symmetric key in Aegis, in bytes.
pub const KEY_LEN: usize = 32;

/// A 256-bit symmetric key (KEK or DEK).
pub struct Key256(Zeroizing<[u8; KEY_LEN]>);

impl Key256 {
    /// Wraps an array that the caller already owns.
    #[must_use]
    pub fn from_array(bytes: [u8; KEY_LEN]) -> Self {
        Self(Zeroizing::new(bytes))
    }

    /// Copies a key out of a slice.
    ///
    /// # Errors
    /// [`Error::InvalidLength`] if `bytes` is not exactly 32 bytes long.
    pub fn from_slice(bytes: &[u8]) -> Result<Self, Error> {
        let mut key = Zeroizing::new([0u8; KEY_LEN]);
        if bytes.len() != KEY_LEN {
            return Err(Error::InvalidLength { what: "key", expected: KEY_LEN, actual: bytes.len() });
        }
        key.copy_from_slice(bytes);
        Ok(Self(key))
    }

    /// The key bytes. Keep the borrow short and never copy them into a type
    /// that does not zeroise.
    #[must_use]
    pub fn expose(&self) -> &[u8; KEY_LEN] {
        &self.0
    }

    /// An explicit copy, for the rare place that needs two owners.
    #[must_use]
    pub fn duplicate(&self) -> Self {
        Self(Zeroizing::new(*self.0))
    }

    /// Mutable access for code that fills the key in place (key derivation).
    pub(crate) fn as_mut(&mut self) -> &mut [u8; KEY_LEN] {
        &mut self.0
    }

    /// An all-zero key to be filled in place.
    pub(crate) fn zeroed() -> Self {
        Self(Zeroizing::new([0u8; KEY_LEN]))
    }
}

impl PartialEq for Key256 {
    /// Constant-time comparison.
    fn eq(&self, other: &Self) -> bool {
        self.0.iter().zip(other.0.iter()).fold(0u8, |acc, (a, b)| acc | (a ^ b)) == 0
    }
}

impl Eq for Key256 {}

impl fmt::Debug for Key256 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Key256([redacted])")
    }
}

/// Secret bytes of any length (decrypted vault data, decoded recovery keys).
pub struct SecretBytes(Zeroizing<Vec<u8>>);

impl SecretBytes {
    /// Takes ownership of a vector.
    #[must_use]
    pub fn new(bytes: Vec<u8>) -> Self {
        Self(Zeroizing::new(bytes))
    }

    /// The bytes.
    #[must_use]
    pub fn expose(&self) -> &[u8] {
        &self.0
    }

    /// Length in bytes.
    #[must_use]
    pub fn len(&self) -> usize {
        self.0.len()
    }

    /// `true` when there are no bytes.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub(crate) fn as_mut_vec(&mut self) -> &mut Vec<u8> {
        &mut self.0
    }
}

impl fmt::Debug for SecretBytes {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "SecretBytes([redacted; {}])", self.0.len())
    }
}

/// A secret text (password, recovery key).
pub struct SecretString(Zeroizing<String>);

impl SecretString {
    /// Takes ownership of a string.
    #[must_use]
    pub fn new(text: String) -> Self {
        Self(Zeroizing::new(text))
    }

    /// The text.
    #[must_use]
    pub fn expose(&self) -> &str {
        &self.0
    }
}

impl PartialEq for SecretString {
    fn eq(&self, other: &Self) -> bool {
        self.0.as_bytes() == other.0.as_bytes()
    }
}

impl Eq for SecretString {}

impl fmt::Debug for SecretString {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("SecretString([redacted])")
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    #[test]
    fn debug_output_hides_secrets() {
        let k = Key256::from_array([7; KEY_LEN]);
        assert_eq!(format!("{k:?}"), "Key256([redacted])");
        assert!(!format!("{:?}", SecretString::new("hunter2".into())).contains("hunter2"));
        assert_eq!(format!("{:?}", SecretBytes::new(vec![1, 2, 3])), "SecretBytes([redacted; 3])");
    }

    #[test]
    fn from_slice_checks_length() {
        assert!(Key256::from_slice(&[0; 31]).is_err());
        assert!(Key256::from_slice(&[0; 33]).is_err());
        assert_eq!(Key256::from_slice(&[9; 32]).unwrap(), Key256::from_array([9; 32]));
    }

    #[test]
    fn equality_compares_all_bytes() {
        let mut b = [1u8; KEY_LEN];
        let a = Key256::from_array(b);
        b[KEY_LEN - 1] = 2;
        assert_ne!(a, Key256::from_array(b));
        assert_eq!(a, a.duplicate());
    }
}
