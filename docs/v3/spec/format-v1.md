# Vault format v1 (`securevault1`)

This document describes, byte for byte, the file format written by Aegis
Planner 2.x (`legacy/aegis_desktop/core/crypto.py` and `store.py`) and by the
Aegis web app (`crypto.js`). Aegis 3 must read every file that 2.x reads. Where
Aegis 3 is deliberately stricter, the section says so under **Aegis 3**.

The same container is used for the live vault (`vault.aegis`), every backup
(`backups/vault-*.aegis`) and exported bundles.

## 1. Container

A UTF-8 encoded JSON object. Readers refuse files larger than 256 MiB
(268 435 456 bytes) before reading them.

| field | type | required | meaning |
|---|---|---|---|
| `format` | string | no | `"securevault1"` when written by 2.x; not checked on read |
| `kdf` | string | yes | must be `"PBKDF2-SHA256"` |
| `iterations` | integer | yes | PBKDF2 iteration count; JSON integer, not a float or boolean |
| `salt` | string | yes | base64 of the KDF salt (16 bytes when written by 2.x) |
| `wrappedKey` | string | yes | base64 of `AES-256-GCM(KEK, DEK)` = 32-byte ciphertext ‖ 16-byte tag |
| `wrappedKeyIv` | string | yes | base64 of the 12-byte nonce used for `wrappedKey` |
| `ciphertext` | string | yes | base64 of `AES-256-GCM(DEK, vault JSON)`; the empty string means "no data yet" |
| `ciphertextIv` | string | yes | base64 of the 12-byte nonce for `ciphertext`; may be empty when `ciphertext` is |
| `recovery` | object or null | no | recovery-key envelope, §5 |
| `revision` | integer | no | save counter, +1 per save; **not authenticated** |
| `vaultId` | string | no | 16 hex characters, a public label |
| `createdAt`, `savedAt`, `exportedAt` | string | no | ISO-8601 UTC timestamps (`...Z`) |

Any other field must be preserved by a writer that rewrites the file.

Validity check used by 2.x (`validate_bundle`): the six "required" fields are
strings, and `iterations` is an integer that is not a boolean. Nothing else is
checked before key derivation.

**Aegis 3:** same rule, plus base64 must be canonical standard alphabet with
padding (2.x's decoder silently skipped invalid characters; files written by
2.x and the web app are always canonical). Decoded nonces must be 12 bytes and
the unwrapped DEK must be 32 bytes, otherwise the file is reported as damaged
(2.x would have accepted a 16- or 24-byte DEK, which no writer produces).
Non-standard JSON (`NaN`, `Infinity`, a byte-order mark) is refused; no
writer produces it. A malformed `recovery` block is reported as damaged
instead of as a wrong recovery key, and never prevents unlocking with the
password.

## 2. Key derivation

```
KEK = PBKDF2-HMAC-SHA256(password = UTF-8(p), salt = salt, c = iterations, dkLen = 32)
```

`iterations` must satisfy `100 000 ≤ iterations ≤ 5 000 000`; outside that range
the file is refused before any derivation (the upper bound prevents a hostile
file from freezing the app). 2.x writes 600 000.

## 3. Password variants

Windows' Persian and Arabic keyboard layouts produce different code points for
the same key. To unlock, 2.x tries these candidates in order, skipping
duplicates, and stops at the first one whose key unwraps:

1. the password exactly as typed;
2. `NFC(password)`;
3. `NFC(password)` with U+064A → U+06CC, U+0649 → U+06CC, U+0643 → U+06A9 (Arabic → Persian);
4. `NFC(password)` with U+06CC → U+064A, U+06A9 → U+0643 (Persian → Arabic).

Creating a vault or changing the password derives from the password **as typed**.

## 4. Key wrapping and data

```
DEK         = 32 random bytes
wrappedKey  = AES-256-GCM-Encrypt(key = KEK, nonce = wrappedKeyIv, aad = ∅, plaintext = DEK)
ciphertext  = AES-256-GCM-Encrypt(key = DEK, nonce = ciphertextIv, aad = ∅, plaintext = UTF-8(JSON(vault)))
```

AES-GCM output is the ciphertext followed by the 16-byte tag (WebCrypto layout).
Nonces are 12 random bytes, fresh for every encryption. No associated data is
used, so none of the container's other fields are authenticated.

An authentication failure while unwrapping means "wrong password" (after all
variants). An authentication failure while decrypting `ciphertext` with a DEK
that unwrapped correctly means the data is damaged.

The plaintext is the vault object serialised as compact JSON (`ensure_ascii =
false`). Its schema is described in `model-v1.md` (phase 7).

## 5. Recovery key

`recovery`, when present and not null:

| field | meaning |
|---|---|
| `salt` | base64, 16 bytes |
| `wrappedKey` | base64, `AES-256-GCM(RKEK, DEK)` |
| `wrappedKeyIv` | base64, 12 bytes |

The recovery KEK always uses **600 000** iterations; the count is not stored.

```
RKEK = PBKDF2-HMAC-SHA256(password = base32_decode(text), salt, 600 000, 32)
```

### 5.1 Key text

A new key is 20 random bytes, encoded with the alphabet
`0123456789ABCDEFGHJKMNPQRSTVWXYZ` (Crockford, no check symbol), most
significant bit first; a final group of fewer than 5 bits is padded with zero
bits on the right. The 32 characters are split into groups of 5 and shown as
`AEGIS-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XX`.

### 5.2 Decoding (compatibility quirk)

`base32_decode(text)`:

1. full Unicode upper-casing of `text`;
2. delete every character that is not ASCII `0-9` or `A-Z`;
3. replace `O`→`0`, `I`→`1`, `L`→`1`, `U`→`V`;
4. read 5 bits per character, emit a byte every 8 bits, drop leftover bits.

The **whole** text is decoded, including the `AEGIS` prefix, which therefore is
part of the KDF input. The prefix is not optional: to accept a key typed without
it, 2.x tries two candidates, in this order:

1. `strip(text)`;
2. `"AEGIS-" + strip(text)`, only when the alphanumeric characters of
   `strip(text)`, upper-cased, do not already start with `AEGIS`.

This quirk is kept for v1. The v2 recovery key (phase 16) fixes it.

## 6. Limits worth knowing

- Nothing outside `wrappedKey` and `ciphertext` is authenticated. A file can be
  replaced by an older valid copy (rollback) without detection. Fixed in v2.
- PBKDF2 is not memory-hard. v2 uses Argon2id.
