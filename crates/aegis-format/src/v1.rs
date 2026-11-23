// SPDX-License-Identifier: GPL-3.0-or-later
//! Format v1: the `securevault1` JSON container (Aegis 2.x and the web app).
//!
//! Reading happens in three steps, each of which can fail on its own:
//!
//! 1. [`VaultFileV1::parse`] checks size, JSON shape, the KDF name and cost,
//!    and decodes the base64 fields. Nothing is derived yet, so a hostile file
//!    costs almost nothing to reject.
//! 2. [`VaultFileV1::unlock`] (or [`VaultFileV1::unlock_with_recovery`]) derives
//!    the key-encryption key and unwraps the data key.
//! 3. [`VaultFileV1::decrypt`] authenticates and decrypts the vault JSON.
//!
//! The specification is `docs/v3/spec/format-v1.md`.

use core::num::NonZeroU32;

use aegis_crypto::aead::{self, NONCE_LEN, Nonce};
use aegis_crypto::wrap::{self, WrappedKey};
use aegis_crypto::{Key256, SecretBytes, SecretString, kdf, password, recovery};
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use serde_json::{Map, Value};

use crate::{FieldProblem, FormatError, MAX_FILE_BYTES, OpenError};

/// Value of the `format` field written by 2.x.
pub const FORMAT_NAME: &str = "securevault1";
/// The only key derivation function of format v1.
pub const KDF_NAME: &str = "PBKDF2-SHA256";
/// Lowest iteration count accepted (2.x `MIN_ACCEPTED_ITERATIONS`).
pub const MIN_ITERATIONS: u32 = 100_000;
/// Highest iteration count accepted (2.x `MAX_ACCEPTED_ITERATIONS`): a file
/// asking for more would freeze the application while deriving.
pub const MAX_ITERATIONS: u32 = 5_000_000;
/// Iteration count 2.x writes.
pub const DEFAULT_ITERATIONS: u32 = 600_000;

/// Data encrypted with AES-256-GCM: the nonce and `ciphertext ‖ tag`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sealed {
    /// The nonce.
    pub nonce: Nonce,
    /// Ciphertext followed by the tag.
    pub bytes: Vec<u8>,
}

/// A data key opened with a recovery key.
#[derive(Debug)]
pub struct RecoveryUnlock {
    /// The data key.
    pub dek: Key256,
    /// The candidate text that worked (the typed key, or the typed key with
    /// `AEGIS-` added). 2.x uses it to rewrap the key after a password reset.
    pub key_text: SecretString,
}

/// A parsed v1 container. The original JSON object is kept so that a rewrite
/// preserves every field, including ones this version does not know.
#[derive(Debug, Clone)]
pub struct VaultFileV1 {
    iterations: NonZeroU32,
    salt: Vec<u8>,
    wrapped: WrappedKey,
    data: Option<Sealed>,
    fields: Map<String, Value>,
}

/// Fields that must be strings in every v1 file (2.x `validate_bundle`).
const REQUIRED_STRINGS: [&str; 6] = ["kdf", "salt", "wrappedKey", "wrappedKeyIv", "ciphertext", "ciphertextIv"];

fn field_err(name: &'static str, problem: FieldProblem) -> FormatError {
    FormatError::Field { name, problem }
}

fn string_field<'a>(obj: &'a Map<String, Value>, name: &'static str) -> Result<&'a str, FormatError> {
    match obj.get(name) {
        None => Err(field_err(name, FieldProblem::Missing)),
        Some(Value::String(s)) => Ok(s),
        Some(_) => Err(field_err(name, FieldProblem::WrongType)),
    }
}

fn b64(name: &'static str, text: &str) -> Result<Vec<u8>, FormatError> {
    STANDARD.decode(text).map_err(|_| field_err(name, FieldProblem::BadBase64))
}

fn b64_nonce(name: &'static str, text: &str) -> Result<Nonce, FormatError> {
    let raw = b64(name, text)?;
    let actual = raw.len();
    raw.try_into().map_err(|_| field_err(name, FieldProblem::BadLength { expected: NONCE_LEN, actual }))
}

/// `iterations` must be a JSON integer (not a float, not a boolean) within
/// [`MIN_ITERATIONS`, `MAX_ITERATIONS`].
fn iterations(obj: &Map<String, Value>) -> Result<NonZeroU32, FormatError> {
    let value = obj.get("iterations").ok_or(field_err("iterations", FieldProblem::Missing))?;
    let Value::Number(n) = value else { return Err(field_err("iterations", FieldProblem::WrongType)) };
    let raw = match (n.as_u64(), n.as_i64()) {
        (Some(u), _) => i64::try_from(u).unwrap_or(i64::MAX),
        (None, Some(i)) => i,
        (None, None) => return Err(field_err("iterations", FieldProblem::WrongType)),
    };
    u32::try_from(raw)
        .ok()
        .filter(|n| (MIN_ITERATIONS..=MAX_ITERATIONS).contains(n))
        .and_then(NonZeroU32::new)
        .ok_or(FormatError::CostOutOfRange { iterations: raw })
}

impl VaultFileV1 {
    /// Parses and validates a container without deriving any key.
    ///
    /// # Errors
    /// [`FormatError`] describing the first problem found.
    pub fn parse(bytes: &[u8]) -> Result<Self, FormatError> {
        if bytes.len() > MAX_FILE_BYTES {
            return Err(FormatError::TooLarge { size: bytes.len() });
        }
        let value: Value = serde_json::from_slice(bytes).map_err(|_| FormatError::NotJson)?;
        let Value::Object(fields) = value else { return Err(FormatError::NotObject) };
        for name in REQUIRED_STRINGS {
            string_field(&fields, name)?;
        }
        let iterations = iterations(&fields)?;
        if string_field(&fields, "kdf")? != KDF_NAME {
            return Err(FormatError::UnsupportedKdf);
        }
        let salt = b64("salt", string_field(&fields, "salt")?)?;
        let wrapped = WrappedKey {
            nonce: b64_nonce("wrappedKeyIv", string_field(&fields, "wrappedKeyIv")?)?,
            sealed: b64("wrappedKey", string_field(&fields, "wrappedKey")?)?,
        };
        let ciphertext = string_field(&fields, "ciphertext")?;
        let data = if ciphertext.is_empty() {
            None // 2.x: a vault that has never been saved has no data yet.
        } else {
            Some(Sealed {
                nonce: b64_nonce("ciphertextIv", string_field(&fields, "ciphertextIv")?)?,
                bytes: b64("ciphertext", ciphertext)?,
            })
        };
        Ok(Self { iterations, salt, wrapped, data, fields })
    }

    /// PBKDF2 iteration count of the password envelope.
    #[must_use]
    pub fn iterations(&self) -> u32 {
        self.iterations.get()
    }

    /// The save counter, if present and a non-negative integer. It is not
    /// authenticated in v1: treat it as a hint.
    #[must_use]
    pub fn revision(&self) -> Option<u64> {
        self.fields.get("revision").and_then(Value::as_u64)
    }

    /// The public vault label, if present.
    #[must_use]
    pub fn vault_id(&self) -> Option<&str> {
        self.fields.get("vaultId").and_then(Value::as_str)
    }

    /// `true` when the file has a recovery-key envelope.
    #[must_use]
    pub fn has_recovery(&self) -> bool {
        self.fields.get("recovery").is_some_and(|v| !v.is_null())
    }

    /// `true` when the vault has never been saved and holds no data.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.data.is_none()
    }

    /// Every field of the original JSON object, for a lossless rewrite.
    #[must_use]
    pub fn fields(&self) -> &Map<String, Value> {
        &self.fields
    }

    /// Unwraps the data key with the master password, trying the keyboard
    /// variants of format v1 §3 in order.
    ///
    /// Each variant costs one full key derivation; an unaffected password
    /// costs one, a wrong one up to four.
    ///
    /// # Errors
    /// [`OpenError::WrongPassword`] when no variant unwraps the key;
    /// [`OpenError::Damaged`] when it unwraps to something that is not a key.
    pub fn unlock(&self, password: &str) -> Result<Key256, OpenError> {
        for candidate in password::legacy_variants(password) {
            let kek = kdf::pbkdf2_sha256(candidate.expose().as_bytes(), &self.salt, self.iterations);
            match try_unwrap(&kek, &self.wrapped)? {
                Some(dek) => return Ok(dek),
                None => continue,
            }
        }
        Err(OpenError::WrongPassword)
    }

    /// Unwraps the data key with a recovery key, as typed by the user
    /// (format v1 §5).
    ///
    /// # Errors
    /// [`OpenError::NoRecovery`] when the vault has no recovery key,
    /// [`OpenError::RecoveryDamaged`] when its envelope is malformed,
    /// [`OpenError::WrongPassword`] when the key does not match.
    pub fn unlock_with_recovery(&self, typed: &str) -> Result<RecoveryUnlock, OpenError> {
        let (salt, wrapped) = self.recovery_envelope()?;
        for candidate in recovery::legacy_candidates(typed) {
            let secret = recovery::decode_lenient(candidate.expose());
            let kek = kdf::pbkdf2_sha256(secret.expose(), &salt, recovery::LEGACY_ITERATIONS);
            if let Some(dek) = try_unwrap(&kek, &wrapped)? {
                return Ok(RecoveryUnlock { dek, key_text: candidate });
            }
        }
        Err(OpenError::WrongPassword)
    }

    fn recovery_envelope(&self) -> Result<(Vec<u8>, WrappedKey), OpenError> {
        let rec = match self.fields.get("recovery") {
            None | Some(Value::Null) => return Err(OpenError::NoRecovery),
            Some(Value::Object(rec)) => rec,
            Some(_) => return Err(OpenError::RecoveryDamaged),
        };
        let part =
            |name| -> Result<&str, OpenError> { string_field(rec, name).map_err(|_| OpenError::RecoveryDamaged) };
        let damaged = |_| OpenError::RecoveryDamaged;
        let salt = b64("recovery.salt", part("salt")?).map_err(damaged)?;
        let wrapped = WrappedKey {
            nonce: b64_nonce("recovery.wrappedKeyIv", part("wrappedKeyIv")?).map_err(damaged)?,
            sealed: b64("recovery.wrappedKey", part("wrappedKey")?).map_err(damaged)?,
        };
        Ok((salt, wrapped))
    }

    /// Authenticates and decrypts the vault JSON.
    ///
    /// Returns `None` for a vault that has never been saved.
    ///
    /// # Errors
    /// [`OpenError::Damaged`] when authentication fails: the key unwrapped, so
    /// the data itself was modified or corrupted.
    pub fn decrypt(&self, dek: &Key256) -> Result<Option<SecretBytes>, OpenError> {
        let Some(data) = &self.data else { return Ok(None) };
        aead::open(dek, &data.nonce, &[], &data.bytes).map(Some).map_err(|_| OpenError::Damaged)
    }
}

/// `Ok(None)` means "this KEK is not the right one", so the caller can try the
/// next candidate.
fn try_unwrap(kek: &Key256, wrapped: &WrappedKey) -> Result<Option<Key256>, OpenError> {
    match wrap::unwrap(kek, wrapped) {
        Ok(dek) => Ok(Some(dek)),
        Err(aegis_crypto::Error::Authentication) => Ok(None),
        Err(aegis_crypto::Error::InvalidLength { .. }) => Err(OpenError::Damaged),
        Err(e) => Err(OpenError::Crypto(e)),
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used)]
    use super::*;

    fn minimal(iterations: &str) -> String {
        format!(
            r#"{{"kdf":"PBKDF2-SHA256","iterations":{iterations},"salt":"AAAAAAAAAAAAAAAAAAAAAA==",
            "wrappedKey":"AAAA","wrappedKeyIv":"AAAAAAAAAAAAAAAA","ciphertext":"","ciphertextIv":""}}"#
        )
    }

    #[test]
    fn rejects_non_json_and_non_objects() {
        assert_eq!(VaultFileV1::parse(b"").unwrap_err(), FormatError::NotJson);
        assert_eq!(VaultFileV1::parse(b"[1]").unwrap_err(), FormatError::NotObject);
        assert_eq!(VaultFileV1::parse(b"\xEF\xBB\xBF{}").unwrap_err(), FormatError::NotJson);
        assert_eq!(VaultFileV1::parse(b"{\"x\": NaN}").unwrap_err(), FormatError::NotJson);
    }

    #[test]
    fn rejects_oversized_input_before_parsing() {
        let big = vec![b' '; MAX_FILE_BYTES + 1];
        assert_eq!(VaultFileV1::parse(&big).unwrap_err(), FormatError::TooLarge { size: MAX_FILE_BYTES + 1 });
    }

    #[test]
    fn iteration_bounds() {
        assert!(VaultFileV1::parse(minimal("100000").as_bytes()).is_ok());
        assert!(VaultFileV1::parse(minimal("5000000").as_bytes()).is_ok());
        for bad in ["99999", "5000001", "-1", "0", "18446744073709551615"] {
            assert!(
                matches!(VaultFileV1::parse(minimal(bad).as_bytes()), Err(FormatError::CostOutOfRange { .. })),
                "{bad}"
            );
        }
        for bad in ["600000.0", "true", "\"600000\"", "null", "1e30"] {
            assert_eq!(
                VaultFileV1::parse(minimal(bad).as_bytes()).unwrap_err(),
                field_err("iterations", FieldProblem::WrongType),
                "{bad}"
            );
        }
    }

    #[test]
    fn empty_vault_has_no_data() {
        let f = VaultFileV1::parse(minimal("100000").as_bytes()).unwrap();
        assert!(f.is_empty());
        assert!(!f.has_recovery());
        assert_eq!(f.decrypt(&Key256::from_array([0; 32])).unwrap().map(|b| b.len()), None);
    }

    #[test]
    fn non_canonical_base64_and_bad_nonce_length() {
        let bad_pad = minimal("100000").replace("AAAAAAAAAAAAAAAAAAAAAA==", "AAAAAAAAAAAAAAAAAAAAAA");
        assert_eq!(VaultFileV1::parse(bad_pad.as_bytes()).unwrap_err(), field_err("salt", FieldProblem::BadBase64));
        let short_iv = minimal("100000").replace("AAAAAAAAAAAAAAAA", "AAAA");
        assert_eq!(
            VaultFileV1::parse(short_iv.as_bytes()).unwrap_err(),
            field_err("wrappedKeyIv", FieldProblem::BadLength { expected: 12, actual: 3 })
        );
    }

    #[test]
    fn recovery_states() {
        let f = VaultFileV1::parse(minimal("100000").as_bytes()).unwrap();
        assert_eq!(f.unlock_with_recovery("x").unwrap_err(), OpenError::NoRecovery);
        let with = minimal("100000").replace("\"ciphertext\"", "\"recovery\":{\"salt\":1},\"ciphertext\"");
        let f = VaultFileV1::parse(with.as_bytes()).unwrap();
        assert!(f.has_recovery());
        assert_eq!(f.unlock_with_recovery("x").unwrap_err(), OpenError::RecoveryDamaged);
    }
}
