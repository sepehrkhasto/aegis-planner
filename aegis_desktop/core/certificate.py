# SPDX-License-Identifier: GPL-3.0-or-later
"""Facts for the Vault Certificate: everything here is PUBLIC metadata of the vault file (or counts of what is in it).
No key material, no password, no recovery key, no content of any note or task ever enters this module's output."""
from __future__ import annotations

import datetime as dt
import hashlib

from . import crypto, jalali
from .store import VaultStore as Store

CIPHER = "AES-256-GCM"


def _digits(vault_id: str) -> str:
    """Six stable digits derived from the id (the 'serial number' on the certificate)."""
    n = int(hashlib.sha256(("aegis-no:" + vault_id).encode()).hexdigest()[:12], 16) % 1_000_000
    return f"{n:06d}"


def fingerprint(vault_id: str) -> str:
    """``7F3A · 91C2 · B04D · 5E18`` - a readable checksum of the vault id, for telling vaults apart at a glance."""
    h = hashlib.sha256(("aegis-fp:" + vault_id).encode()).hexdigest().upper()[:16]
    return " · ".join(h[i:i + 4] for i in range(0, 16, 4))


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone() if d.tzinfo else d.replace(tzinfo=dt.timezone.utc).astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def identity(store: Store, now: dt.datetime | None = None) -> dict:
    """Everything the certificate shows. Needs an unlocked vault (for the counts); the id and dates come from the header."""
    raw = store._load_raw()
    v = store.vault or {}
    now = now or dt.datetime.now().astimezone()
    vid = str(raw.get("vaultId") or "")
    created = parse_iso(raw.get("createdAt"))
    saved = parse_iso(raw.get("savedAt"))
    days = max(0, (now - created).days) if created else 0
    try:
        backups = len(store.list_backups())
    except OSError:
        backups = 0
    if created:
        j = jalali.date_to_due(created.date())
        created_fa = f"{jalali.fa(j['jd'])} {jalali.MONTHS_FA[j['jm'] - 1]} {jalali.fa(j['jy'])}"
    else:
        created_fa = "—"
    return {
        "id": vid,
        "number": _digits(vid) if vid else "000000",
        "fingerprint": fingerprint(vid) if vid else "—",
        "created": created,
        "created_fa": created_fa,
        "days": days,
        "revision": (raw.get("revision") if isinstance(raw.get("revision"), int) else 0),
        "saved": saved,
        "cipher": CIPHER,
        "kdf": f"PBKDF2-SHA256 · {int(raw.get('iterations') or crypto.KDF_ITERATIONS):,}",
        "recovery": bool(raw.get("recovery")),
        "backups": backups,
        "counts": {k: len(v.get(k) or []) for k in ("tasks", "notes", "journal", "habits", "goals")},
    }
