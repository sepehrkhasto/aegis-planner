# SPDX-License-Identifier: GPL-3.0-or-later
"""Zero-knowledge primitives, byte-compatible with the Aegis web app (crypto.js).

Key hierarchy:
    master password --PBKDF2-SHA256 (600k)--> KEK  (never stored)
    random 256-bit DEK, wrapped by KEK with AES-256-GCM (stored)
    vault JSON --AES-256-GCM(DEK)--> ciphertext (stored)

All binary values are base64 strings and AES-GCM output is ``ciphertext||tag``
exactly like WebCrypto, so a ``securevault1`` bundle produced by either app
opens in the other.
"""
from __future__ import annotations

import base64
import json
import os
import re
import unicodedata
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KDF_NAME = "PBKDF2-SHA256"
KDF_ITERATIONS = 600_000          # floor: never lower this to make unlock "faster"
MIN_ACCEPTED_ITERATIONS = 100_000  # refuse bundles weaker than this
MAX_ACCEPTED_ITERATIONS = 5_000_000  # refuse absurd values from an untrusted file (would freeze the app: DoS)
PIN_ITERATIONS = 150_000


class WrongPassword(Exception):
    """AES-GCM authentication failed: wrong password / key, or corrupt data."""


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text)


def _derive(secret: bytes, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(secret)


def _encrypt(key: bytes, plaintext: bytes) -> tuple[str, str]:
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    return b64e(iv), b64e(ct)


def _decrypt(key: bytes, iv_b64: str, ct_b64: str) -> bytes:
    try:
        return AESGCM(key).decrypt(b64d(iv_b64), b64d(ct_b64), None)
    except (InvalidTag, ValueError) as exc:
        raise WrongPassword() from exc


@dataclass
class KeyMeta:
    """Public (non-secret) key-wrapping parameters stored next to the vault."""
    kdf: str
    iterations: int
    salt: str
    wrappedKey: str
    wrappedKeyIv: str

    def to_dict(self) -> dict:
        return {
            "kdf": self.kdf, "iterations": self.iterations, "salt": self.salt,
            "wrappedKey": self.wrappedKey, "wrappedKeyIv": self.wrappedKeyIv,
        }

    @staticmethod
    def from_dict(d: dict) -> "KeyMeta":
        return KeyMeta(d["kdf"], int(d["iterations"]), d["salt"], d["wrappedKey"], d["wrappedKeyIv"])


def create_key_material(password: str, iterations: int = KDF_ITERATIONS) -> tuple[KeyMeta, bytes]:
    """New vault: returns (meta, dek)."""
    salt = os.urandom(16)
    kek = _derive(password.encode("utf-8"), salt, iterations)
    dek = os.urandom(32)
    iv, ct = _encrypt(kek, dek)
    return KeyMeta(KDF_NAME, iterations, b64e(salt), ct, iv), dek


_TO_FA = str.maketrans({"\u064A": "\u06CC", "\u0649": "\u06CC", "\u0643": "\u06A9"})   # Arabic yeh/kaf -> Persian
_TO_AR = str.maketrans({"\u06CC": "\u064A", "\u06A9": "\u0643"})                       # Persian yeh/kaf -> Arabic


def password_variants(password: str) -> list[str]:
    """The typed password first, then the same text as other keyboards produce it: Unicode NFC, and Persian vs
    Arabic yeh / kaf (Windows' Arabic and Persian layouts emit different code points for the same key). Exact
    first, so an unaffected password costs nothing extra; a wrong password costs one derivation per variant."""
    out = []
    nfc = unicodedata.normalize("NFC", password)
    for v in (password, nfc, nfc.translate(_TO_FA), nfc.translate(_TO_AR)):
        if v not in out:
            out.append(v)
    return out


def unlock(password: str, meta: KeyMeta) -> bytes:
    """Return the DEK. Raises WrongPassword. Tries the keyboard variants of the password (see password_variants)."""
    if meta.kdf != KDF_NAME:
        raise ValueError("unsupported KDF")
    if not MIN_ACCEPTED_ITERATIONS <= meta.iterations <= MAX_ACCEPTED_ITERATIONS:
        raise ValueError("KDF iteration count out of range; refusing to open")
    salt = b64d(meta.salt)
    for pw in password_variants(password):
        kek = _derive(pw.encode("utf-8"), salt, meta.iterations)
        try:
            return _decrypt(kek, meta.wrappedKeyIv, meta.wrappedKey)
        except WrongPassword:
            continue
    raise WrongPassword()


def rotate(new_password: str) -> tuple[KeyMeta, bytes]:
    """Change master password AND data key: a brand-new random DEK wrapped by the new password. Everything that was
    encrypted with the old DEK must be re-encrypted by the caller."""
    return create_key_material(new_password)


def rewrap(dek: bytes, new_password: str) -> KeyMeta:
    """Change master password: only the DEK is re-wrapped, vault stays valid."""
    salt = os.urandom(16)
    kek = _derive(new_password.encode("utf-8"), salt, KDF_ITERATIONS)
    iv, ct = _encrypt(kek, dek)
    return KeyMeta(KDF_NAME, KDF_ITERATIONS, b64e(salt), ct, iv)


def serialize_vault(obj: dict) -> bytes:
    """The plaintext that gets encrypted. Cheap enough to run on the UI thread; sealing it is the slower half."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:                                   # a lone surrogate (an emoji cut in half) must never make every save fail
        return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace").encode("utf-8")


def seal_vault(dek: bytes, data: bytes) -> tuple[str, str]:
    """Returns (ciphertext_b64, iv_b64) for already-serialised vault bytes."""
    iv, ct = _encrypt(dek, data)
    return ct, iv


def encrypt_vault(dek: bytes, obj: dict) -> tuple[str, str]:
    """Returns (ciphertext_b64, iv_b64)."""
    return seal_vault(dek, serialize_vault(obj))


def decrypt_vault(dek: bytes, iv_b64: str, ct_b64: str) -> dict:
    return json.loads(_decrypt(dek, iv_b64, ct_b64).decode("utf-8"))


# ---- recovery key (Crockford base32, same alphabet/format as the web app) ----
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _to_base32(data: bytes) -> str:
    bits = val = 0
    out = []
    for byte in data:
        val = (val << 8) | byte
        bits += 8
        while bits >= 5:
            out.append(_B32[(val >> (bits - 5)) & 31])
            bits -= 5
        val &= (1 << bits) - 1
    if bits > 0:
        out.append(_B32[(val << (5 - bits)) & 31])
    return "".join(out)


def _from_base32(text: str) -> bytes:
    clean = re.sub(r"[^0-9A-Z]", "", text.upper())
    clean = clean.replace("O", "0").replace("I", "1").replace("L", "1").replace("U", "V")
    bits = val = 0
    out = bytearray()
    for ch in clean:
        idx = _B32.find(ch)
        if idx < 0:
            continue
        val = (val << 5) | idx
        bits += 5
        if bits >= 8:
            out.append((val >> (bits - 8)) & 255)
            bits -= 8
            val &= (1 << bits) - 1
    return bytes(out)


def new_recovery_key() -> str:
    s = _to_base32(os.urandom(20))
    return "AEGIS-" + "-".join(re.findall(r".{1,5}", s))


def wrap_with_recovery(dek: bytes, recovery_key: str) -> dict:
    salt = os.urandom(16)
    kek = _derive(_from_base32(recovery_key), salt, KDF_ITERATIONS)
    iv, ct = _encrypt(kek, dek)
    return {"salt": b64e(salt), "wrappedKey": ct, "wrappedKeyIv": iv}


def _recovery_candidates(recovery_key: str) -> list[str]:
    text = recovery_key.strip()
    out = [text]
    if not re.sub(r"[^A-Za-z0-9]", "", text).upper().startswith("AEGIS"):
        out.append("AEGIS-" + text)
    return out


def unwrap_with_recovery_ex(recovery_key: str, rec: dict) -> tuple[bytes, str]:
    """Like unwrap_with_recovery, also returning the exact key text that worked (typed with or without "AEGIS-")."""
    try:
        salt, iv, wk = b64d(rec["salt"]), rec["wrappedKeyIv"], rec["wrappedKey"]
    except (KeyError, TypeError, ValueError) as exc:
        raise WrongPassword() from exc
    for cand in _recovery_candidates(recovery_key):
        kek = _derive(_from_base32(cand), salt, KDF_ITERATIONS)
        try:
            return _decrypt(kek, iv, wk), cand
        except WrongPassword:
            continue
    raise WrongPassword()


def unwrap_with_recovery(recovery_key: str, rec: dict) -> bytes:
    return unwrap_with_recovery_ex(recovery_key, rec)[0]


# ---- password strength (minimal, offline) ----
def password_problems(pw: str) -> list[str]:
    """Return human-readable (Persian) problems; empty list means acceptable."""
    probs = []
    if len(pw) < 10:
        probs.append("رمز باید حداقل ۱۰ کاراکتر باشد.")
    classes = sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 2 and len(pw) < 16:
        probs.append("ترکیبی از حروف، عدد یا نماد استفاده کن (یا رمزی بلندتر از ۱۶ کاراکتر).")
    return probs


def wipe(buf) -> None:
    """Best-effort: overwrite a key held in a bytearray. (Immutable ``bytes`` copies made by libraries cannot be
    reached from Python; this shortens how long the live key sits in our own memory, it is not a guarantee.)"""
    if isinstance(buf, bytearray):
        for i in range(len(buf)):
            buf[i] = 0
