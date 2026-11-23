// SPDX-License-Identifier: GPL-3.0-or-later
use thiserror::Error;

/// What is wrong with one field of a container.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum FieldProblem {
    /// The field is absent.
    Missing,
    /// The field has the wrong JSON type.
    WrongType,
    /// The text is not canonical standard base64.
    BadBase64,
    /// The decoded value has the wrong length.
    BadLength {
        /// Required length in bytes.
        expected: usize,
        /// Length found.
        actual: usize,
    },
}

/// The file is not a container this version can open. Nothing was decrypted.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum FormatError {
    /// Larger than [`crate::MAX_FILE_BYTES`].
    #[error("file is {size} bytes, larger than the limit")]
    TooLarge {
        /// Size of the input in bytes.
        size: usize,
    },
    /// Not valid JSON (this includes a byte-order mark and `NaN`/`Infinity`).
    #[error("not valid JSON")]
    NotJson,
    /// Valid JSON, but not an object.
    #[error("not a JSON object")]
    NotObject,
    /// A field is missing or malformed.
    #[error("field `{name}`: {problem:?}")]
    Field {
        /// Field name as it appears in the file.
        name: &'static str,
        /// What is wrong with it.
        problem: FieldProblem,
    },
    /// The `kdf` field names an algorithm this version does not implement.
    #[error("unsupported key derivation function")]
    UnsupportedKdf,
    /// The KDF cost is outside the accepted range (too weak, or so high that
    /// deriving would freeze the application).
    #[error("key derivation cost {iterations} is outside the accepted range")]
    CostOutOfRange {
        /// The iteration count found in the file, clamped to the `i64` range.
        iterations: i64,
    },
}

/// Opening a well-formed container failed.
#[derive(Debug, Error, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum OpenError {
    /// None of the password variants (or recovery-key candidates) unwraps the
    /// data key. Also reported when the wrapped key itself was modified, which
    /// is indistinguishable from a wrong password.
    #[error("wrong password")]
    WrongPassword,
    /// The key unwrapped, but the data failed authentication or is not what
    /// the format requires: the file was damaged or tampered with.
    #[error("the vault data is damaged")]
    Damaged,
    /// The vault has no recovery key.
    #[error("this vault has no recovery key")]
    NoRecovery,
    /// The recovery block exists but is malformed.
    #[error("the recovery block is damaged")]
    RecoveryDamaged,
    /// A cryptographic operation failed for a reason other than
    /// authentication (for example the random number generator).
    #[error("cryptographic failure: {0}")]
    Crypto(aegis_crypto::Error),
}
