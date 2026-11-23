// SPDX-License-Identifier: GPL-3.0-or-later
use thiserror::Error;

/// Every way an operation of this crate can fail.
///
/// Variants carry no key material and no plaintext, so an error can be logged.
#[derive(Debug, Error, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum Error {
    /// The operating system could not supply random bytes.
    #[error("the system random number generator failed")]
    Rng,
    /// AES-GCM authentication failed: wrong key, or the data was modified.
    #[error("authentication failed")]
    Authentication,
    /// The input is longer than AES-GCM can process.
    #[error("input too long for AES-GCM")]
    TooLong,
    /// A value had the wrong length.
    #[error("{what} must be {expected} bytes, got {actual}")]
    InvalidLength {
        /// Which value.
        what: &'static str,
        /// Required length in bytes.
        expected: usize,
        /// Length that was supplied.
        actual: usize,
    },
}
