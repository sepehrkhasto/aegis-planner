// SPDX-License-Identifier: GPL-3.0-or-later
//! Known-answer tests against vectors generated from Aegis 2.x
//! (`tools/vectors/gen_v1.py`, output in `testdata/v1/vectors.json`).
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing, clippy::panic, missing_docs)]

use std::num::NonZeroU32;
use std::path::PathBuf;
use std::sync::OnceLock;

use aegis_crypto::{Key256, aead, kdf, password, recovery, wrap};
use serde_json::Value;

fn vectors() -> &'static Value {
    static V: OnceLock<Value> = OnceLock::new();
    V.get_or_init(|| {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../testdata/v1/vectors.json");
        serde_json::from_slice(&std::fs::read(&path).expect("vectors.json")).expect("valid JSON")
    })
}

fn list(name: &str) -> &'static [Value] {
    vectors()[name].as_array().expect(name)
}

fn bytes(v: &Value) -> Vec<u8> {
    hex::decode(v.as_str().unwrap()).unwrap()
}

fn key(v: &Value) -> Key256 {
    Key256::from_slice(&bytes(v)).unwrap()
}

fn nonce(v: &Value) -> aead::Nonce {
    bytes(v).try_into().unwrap()
}

fn iterations(v: &Value) -> NonZeroU32 {
    NonZeroU32::new(u32::try_from(v.as_u64().unwrap()).unwrap()).unwrap()
}

#[test]
fn pbkdf2_matches_2x() {
    for case in list("pbkdf2_sha256") {
        let got = kdf::pbkdf2_sha256(&bytes(&case["secret"]), &bytes(&case["salt"]), iterations(&case["iterations"]));
        assert_eq!(hex::encode(got.expose()), case["key"].as_str().unwrap(), "{case}");
    }
}

#[test]
fn aes_gcm_matches_2x() {
    for case in list("aes256gcm") {
        let (k, n) = (key(&case["key"]), nonce(&case["nonce"]));
        let pt = bytes(&case["plaintext"]);
        let ct = aead::seal_with_nonce(&k, &n, &[], &pt).unwrap();
        assert_eq!(hex::encode(&ct), case["ciphertext"].as_str().unwrap());
        assert_eq!(aead::open(&k, &n, &[], &ct).unwrap().expose(), pt.as_slice());
    }
}

#[test]
fn password_variants_match_2x() {
    for case in list("password_variants") {
        let got: Vec<String> =
            password::legacy_variants(case["input"].as_str().unwrap()).iter().map(|s| s.expose().to_owned()).collect();
        let want: Vec<String> = serde_json::from_value(case["variants"].clone()).unwrap();
        assert_eq!(got, want, "input {:?}", case["input"]);
    }
}

#[test]
fn base32_matches_2x() {
    let b = &vectors()["base32"];
    for case in b["encode"].as_array().unwrap() {
        assert_eq!(recovery::encode(&bytes(&case["bytes"])), case["text"].as_str().unwrap());
    }
    for case in b["decode"].as_array().unwrap() {
        let got = recovery::decode_lenient(case["text"].as_str().unwrap());
        assert_eq!(hex::encode(got.expose()), case["bytes"].as_str().unwrap(), "text {:?}", case["text"]);
    }
    for case in b["candidates"].as_array().unwrap() {
        let got: Vec<String> =
            recovery::legacy_candidates(case["text"].as_str().unwrap()).iter().map(|s| s.expose().to_owned()).collect();
        let want: Vec<String> = serde_json::from_value(case["candidates"].clone()).unwrap();
        assert_eq!(got, want, "text {:?}", case["text"]);
    }
}

#[test]
fn key_wrap_matches_2x() {
    for case in list("key_wrap") {
        let kek = kdf::pbkdf2_sha256(
            case["password"].as_str().unwrap().as_bytes(),
            &bytes(&case["salt"]),
            iterations(&case["iterations"]),
        );
        assert_eq!(hex::encode(kek.expose()), case["kek"].as_str().unwrap());
        let w = wrap::WrappedKey { nonce: nonce(&case["nonce"]), sealed: bytes(&case["wrapped"]) };
        assert_eq!(wrap::unwrap(&kek, &w).unwrap(), key(&case["dek"]));
    }
}
