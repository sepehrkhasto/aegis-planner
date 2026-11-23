// SPDX-License-Identifier: GPL-3.0-or-later
//! Opens every sample vault written by Aegis 2.x (`testdata/v1/samples/`) and
//! checks that Aegis 3 reaches the same outcome 2.x does: the same data key,
//! byte-identical plaintext, and the same refusal for damaged or hostile files.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing, clippy::panic, missing_docs)]

use std::path::PathBuf;

use aegis_format::OpenError;
use aegis_format::v1::VaultFileV1;
use serde_json::Value;
use sha2::{Digest, Sha256};

fn samples_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../testdata/v1/samples")
}

/// What Aegis 3 does with one file, in the vocabulary of `index.json`.
fn outcome(case: &Value) -> String {
    let bytes = std::fs::read(samples_dir().join(case["file"].as_str().unwrap())).unwrap();
    let file = match VaultFileV1::parse(&bytes) {
        Ok(f) => f,
        Err(_) => return "invalid".into(),
    };
    let dek = match file.unlock(case["password"].as_str().unwrap()) {
        Ok(k) => k,
        Err(OpenError::WrongPassword) => return "wrong_password".into(),
        Err(e) => return format!("unlock error {e:?}"),
    };
    if let Some(want) = case["dek"].as_str() {
        assert_eq!(hex::encode(dek.expose()), want, "data key differs from 2.x");
    }
    match file.decrypt(&dek) {
        Ok(None) => assert!(case["plaintext_sha256"].is_null()),
        Ok(Some(plain)) => {
            assert_eq!(plain.len(), usize::try_from(case["plaintext_len"].as_u64().unwrap()).unwrap());
            assert_eq!(hex::encode(Sha256::digest(plain.expose())), case["plaintext_sha256"].as_str().unwrap());
        }
        Err(OpenError::Damaged) => return "damaged".into(),
        Err(e) => return format!("decrypt error {e:?}"),
    }
    for key in ["recovery_key", "recovery_key_typed"] {
        if let Some(typed) = case[key].as_str() {
            let opened = file.unlock_with_recovery(typed).unwrap();
            assert_eq!(opened.dek, dek, "{key} opens a different key");
        }
    }
    "ok".into()
}

#[test]
fn every_2x_sample_has_the_2x_outcome() {
    let index: Value = serde_json::from_slice(&std::fs::read(samples_dir().join("index.json")).unwrap()).unwrap();
    let cases = index["cases"].as_array().unwrap();
    assert!(cases.len() >= 14, "sample index looks truncated");
    for case in cases {
        assert_eq!(outcome(case), case["expect"].as_str().unwrap(), "{}", case["file"]);
    }
}

#[test]
fn unknown_fields_are_kept_for_rewriting() {
    let bytes = std::fs::read(samples_dir().join("sample-empty.json")).unwrap();
    let file = VaultFileV1::parse(&bytes).unwrap();
    assert_eq!(file.fields()["unknownFutureField"]["keep"], Value::Bool(true));
    assert_eq!(file.revision(), Some(0));
}

#[test]
fn wrong_recovery_key_is_refused() {
    let bytes = std::fs::read(samples_dir().join("sample-recovery.json")).unwrap();
    let file = VaultFileV1::parse(&bytes).unwrap();
    assert!(file.has_recovery());
    assert_eq!(
        file.unlock_with_recovery("AEGIS-00000-00000-00000-00000-00000-00000-00").unwrap_err(),
        OpenError::WrongPassword
    );
}
