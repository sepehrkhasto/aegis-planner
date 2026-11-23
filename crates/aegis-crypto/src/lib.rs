// SPDX-License-Identifier: GPL-3.0-or-later
//! Cryptographic primitives of Aegis.
//!
//! This crate does no I/O and keeps no state. It provides:
//!
//! * [`secret`]: key and password types that wipe their memory when dropped;
//! * [`kdf`]: password-based key derivation (PBKDF2-HMAC-SHA256);
//! * [`aead`]: AES-256-GCM with the WebCrypto layout (`ciphertext ‖ tag`);
//! * [`wrap`]: wrapping a data key (DEK) with a key-encryption key (KEK);
//! * [`password`]: the keyboard-layout variants a password is tried in;
//! * [`recovery`]: recovery-key text encoding;
//! * [`rng`]: the operating system's random number generator.
//!
//! The file format that ties these together lives in `aegis-format`. The exact
//! behaviour that has to stay compatible with Aegis 2.x is specified in
//! `docs/v3/spec/format-v1.md`.

#![forbid(unsafe_code)]

pub mod aead;
mod error;
pub mod kdf;
pub mod password;
pub mod recovery;
pub mod rng;
pub mod secret;
pub mod wrap;

pub use error::Error;
pub use secret::{Key256, SecretBytes, SecretString};
