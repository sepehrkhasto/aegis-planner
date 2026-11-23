# Vault format v2 (`aegis-vault`, version 2)

Status: **draft**. It becomes normative when phase 23 implements it; until
then it changes only through review. Format v1 is described in
`format-v1.md` and stays readable forever.

## 1. Goals

| goal | how |
|---|---|
| A wrong password, a damaged file and a tampered file are told apart | key-check value (§5.3), AEAD on everything that matters |
| Every field that affects meaning is authenticated | the header is the AEAD associated data of the payload (§4) |
| An older copy of the vault is noticed | authenticated revision + per-device memory (§7) |
| Brute force on a stolen file is expensive, including on GPUs | Argon2id (§5.1) |
| Several independent ways to open one vault | key slots, as in LUKS (§5) |
| Changing the password does not re-encrypt the data | the data key (DEK) is wrapped per slot |
| A hostile file cannot freeze or exhaust the device | every size and cost is bounded before work starts (§8) |
| Future changes without breaking old readers silently | explicit version, unknown-field rules (§9) |

Not goals: hiding the file's existence, size or save time; protecting a vault
while it is open on a compromised device.

## 2. Notation

`‖` concatenation · `u64be(x)` 8-byte big-endian · `utf8(s)` UTF-8 bytes ·
`b64(x)` standard base64 with padding · `AEAD` AES-256-GCM, output
`ciphertext ‖ tag`, 12-byte random nonce · `HKDF` HKDF-SHA256 (RFC 5869).
All strings in the domain-separation labels are ASCII.

## 3. Container

A UTF-8 JSON object, at most 256 MiB:

```json
{
  "format": "aegis-vault",
  "version": 2,
  "header": "<b64 of the header bytes>",
  "keyslots": [ { …slot… }, … ],
  "payload": { "nonce": "<b64, 12 bytes>", "ciphertext": "<b64>" }
}
```

A reader detects v2 by `format == "aegis-vault"` and `version == 2`. A file
with `format == "aegis-vault"` and a larger `version` is refused as "made by a
newer Aegis". Anything else goes to the v1 reader.

## 4. Header

`header` holds the **exact bytes** of a UTF-8 JSON object. Readers parse
those bytes and use them, unchanged, as the AEAD associated data of the
payload. Nothing has to be canonicalised: what is authenticated is what is
stored. At most 16 KiB.

| field | type | meaning |
|---|---|---|
| `vaultId` | string, 32 hex chars | 128 random bits fixed at creation; binds slots and sync packages to this vault |
| `revision` | integer ≥ 1 | +1 on every save |
| `createdAt`, `savedAt` | string | RFC 3339 UTC |
| `savedBy` | object | `{ "deviceId": 32 hex, "app": "aegis-desktop", "appVersion": "3.0.0" }` |
| `schema` | integer | version of the vault data model (`model-v2.md`, phase 7) |
| `codec` | string | `"json"`; `"zstd+json"` is reserved |
| `keyCheck` | string, b64 | §5.3 |

Every save writes new header bytes (the revision changes). A writer copies
fields it does not know, with their values, into the new header, so they stay
authenticated.

## 5. Keys and key slots

```
DEK          = 32 random bytes, fixed for the life of the vault
               (rotated only by an explicit "rotate data key")
payload key  = HKDF(ikm = DEK, salt = utf8(vaultId), info = "aegis-v2 payload", L = 32)
check key    = HKDF(ikm = DEK, salt = utf8(vaultId), info = "aegis-v2 key-check", L = 32)
```

The DEK itself never encrypts anything; subkeys separate its uses, and new
uses (attachments, sync packages) get their own `info` label.

### 5.1 Slot types

Every slot wraps the same DEK under its own key-encryption key (KEK):

| `type` | KEK | notes |
|---|---|---|
| `password` | Argon2id(normalized password, salt, m, t, p), 32 bytes | normalisation v2, §6 |
| `recovery` | HKDF(ikm = recovery secret, salt, info = "aegis-v2 recovery", 32) | secret has 160 bits of entropy, so no slow KDF is needed |
| `device` | a key held by the OS keystore (Android Keystore, Windows Hello, Secret Service) | the slot stores only an opaque key handle |
| `fido2` | HKDF of a FIDO2 `hmac-secret` output | hardware security key, optional |

Slot object:

```json
{ "id": "a3f0…", "type": "password",
  "kdf": { "alg": "argon2id", "m": 65536, "t": 3, "p": 1, "salt": "<b64, 16 bytes>" },
  "nonce": "<b64, 12 bytes>", "wrapped": "<b64, 48 bytes>" }
```

`id` is 16 hex characters, random. A vault has at least one `password`
slot and at most 16 slots.

### 5.2 Wrapping

```
wrapped = AEAD(key = KEK, nonce, plaintext = DEK,
               aad = "aegis-v2 keyslot\0" ‖ utf8(vaultId) ‖ "\0" ‖ utf8(id) ‖ "\0" ‖ utf8(type) ‖ "\0" ‖ kdfString)
kdfString = "argon2id:m=<m>:t=<t>:p=<p>:salt=<salt b64>"   (password)
          | "hkdf-sha256:salt=<salt b64>"                   (recovery, fido2)
          | "device:<handle b64>"                           (device)
```

The associated data binds a slot to its vault, its identity and its KDF
parameters, so a slot copied from another vault, or edited, fails.

### 5.3 Key check

```
keyCheck = first 16 bytes of HMAC-SHA256(check key, "aegis-v2 key-check" ‖ utf8(vaultId))
```

After a slot unwraps, the reader recomputes `keyCheck` and compares in
constant time. A mismatch means the file was tampered with (a slot that
unwraps to a DEK other than the vault's). It also commits the vault to one
DEK: AES-GCM alone does not.

## 6. Password normalisation v2

Applied to the password before Argon2id, when a password slot is created
and every time it is used:

1. NFC;
2. Arabic letters to Persian: U+064A, U+0649 → U+06CC; U+0643 → U+06A9;
3. Persian (U+06F0–U+06F9) and Arabic-Indic (U+0660–U+0669) digits → ASCII `0`–`9`;
4. remove U+200C (ZWNJ) and U+200D (ZWJ);
5. nothing else: case, spaces and punctuation are significant.

One normalised form means one derivation per attempt, instead of up to four
in v1. The exact table and test vectors belong to phase 17.

## 7. Rollback detection

Each device keeps, **outside the vault**, the last `(vaultId, revision,
SHA-256(header bytes))` it opened or saved. Opening a file whose authenticated
`revision` is lower, or equal with a different header hash, is reported to the
user ("this is an older copy than the one this device last saw") with the
choice to open read-only, restore it on purpose, or cancel.

Limit: a device that never saw the newer revision cannot know. There is no
trusted clock or counter offline; this is detection, not prevention.

## 8. Limits enforced before any key derivation

| item | accepted |
|---|---|
| file size | ≤ 256 MiB |
| header bytes | ≤ 16 KiB |
| slots | 1–16, unique `id`s |
| Argon2id `m` (KiB) | 19 456 (19 MiB) – 1 048 576 (1 GiB) |
| Argon2id `t` | 2 – 10 |
| Argon2id `p` | 1 – 8 |
| salts | exactly 16 bytes |
| nonces | exactly 12 bytes |
| wrapped keys | exactly 48 bytes |

A device may refuse a valid `m` it cannot allocate, with a distinct error.

**Default for new slots:** `m = 65 536` (64 MiB), `t = 3`, `p = 1`, then raised
by calibration on the creating device until one derivation takes about 0.5 s,
never above `m = 262 144` so the vault still opens on a modest phone.
Unlocking a slot whose parameters are below the current default re-wraps it
with the new parameters (phase 26).

## 9. Compatibility rules

- Unknown top-level fields, header fields and slot fields are preserved on
  rewrite. An unknown slot `type` is preserved and skipped when unlocking.
- Fields are never re-purposed. A change of meaning is a new field or a new
  `version`.
- v1 → v2 migration (phase 25), after a successful v1 unlock: write a backup of
  the v1 file unchanged; create a new DEK, a `password` slot from the password
  as typed (normalised v2), header `revision = 1`; write atomically. The v1
  recovery key does not carry over (its secret is not known at that point); the
  app asks to create a v2 recovery key right away. Old v1 backups still open
  with the old password and recovery key.
- Export to v1 (phase 22) stays available for the web app; it is a copy, never
  the live vault.

## 10. Recovery key v2 text

20 random bytes, Crockford base32 (32 symbols), followed by 4 check symbols =
the first 20 bits of SHA-256(`"aegis-v2 recovery-check"` ‖ secret). Shown as
`AEGIS2-XXXXXX-XXXXXX-XXXXXX-XXXXXX-XXXXXX-XXXXXX` (36 symbols in six groups).
Parsing is strict about symbols (case-insensitive, `O`/`I`/`L` folded, dashes
and spaces ignored), the `AEGIS2` prefix is optional and **not** part of the
secret, and a wrong check is reported as a typo before any key derivation.
