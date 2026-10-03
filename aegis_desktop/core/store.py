# SPDX-License-Identifier: GPL-3.0-or-later
"""Local encrypted vault file: create / unlock / save / backup / export / import.

Everything lives in one JSON file (``vault.aegis``) that has the same fields as
the web app's ``securevault1`` export bundle, plus an optional ``recovery``
block. No network access happens anywhere in this module.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as _dt
import functools
import json
import shutil
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import crypto
from .log import log
from .crypto import KeyMeta, WrongPassword

FORMAT = "securevault1"
TRASH_DAYS = 30
JOURNAL_FOLDER = "ژورنال"
LIST_FOLDER = "چک‌لیست"
MAX_BACKUPS = 30          # default retention; user-configurable (keep_backups)
MIN_KEEP = 3
MAX_FILE_BYTES = 256 * 1024 * 1024   # refuse absurdly large vault/backup files instead of exhausting memory
KEY_FIELDS = ("kdf", "iterations", "salt", "wrappedKey", "wrappedKeyIv")
BACKUP_REASONS = {"auto": "خودکار", "unlock": "هنگام باز کردن", "exit": "هنگام بستن", "manual": "دستی",
                  "rekey": "پیش از تغییر رمز", "before-import": "پیش از وارد کردن", "before-merge": "پیش از ادغام",
                  "before-restore": "پیش از بازگردانی", "restored": "بازگردانی‌شده",
                  "uninstall": "پیش از حذف برنامه"}


BACKUP_UNREACHABLE = "پوشه‌ی پشتیبان در دسترس نیست."
_REPEATABLE = ("auto", "unlock")


def _backup_order(p: Path):
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0
    return (p.name[6:21], mtime)


class VaultError(Exception):
    """User-presentable vault problem (message is Persian)."""


@contextlib.contextmanager
def _damaged_is_vaulterror():
    """A hand-edited / truncated file can fail inside crypto with ValueError (bad base64, unsupported KDF) or
    KeyError; those are 'this file is damaged', never a crash. WrongPassword is not affected."""
    try:
        yield
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("damaged key material: %s", type(exc).__name__)
        raise VaultError("فایل ولت آسیب دیده یا دست‌کاری‌شده است. از پوشهٔ پشتیبان‌ها استفاده کن.") from exc


def uid(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):x}{uuid.uuid4().hex[:8]}"


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_vault_id() -> str:
    """A random, NON-secret label for a vault (16 hex chars). It sits in the file's plain header like the salt does and is
    never used as key material; the certificate shows it so the person can tell two vaults or two backups apart."""
    return os.urandom(8).hex()


def empty_vault() -> dict:
    return {
        "version": 1, "notes": [], "tasks": [], "journal": [], "habits": [],
        "lists": [], "goals": [], "templates": [], "archive": [],
        "wellness": {"water": {}, "sleep": {}}, "trash": [], "settings": {},
    }


_LIST_KEYS = ("notes", "tasks", "journal", "habits", "lists", "goals", "templates", "archive", "trash")
_ID_KEYS = ("notes", "tasks", "habits", "goals", "templates", "archive")     # entities addressed by id
# field -> expected type, per entity: a present-but-wrong-typed value (None from another client, a hand edit) is reset
# to an empty one so the UI never has to defend against it. Missing optional fields stay missing.
_COERCE = {"tasks": {"title": str, "notes": str, "tags": list, "subs": list},
           "notes": {"title": str, "body": str, "html": str},
           "habits": {"name": str, "log": dict},
           "goals": {"title": str, "ms": list},
           "archive": {"title": str, "tags": list, "subs": list}}
_REQUIRED = {"habits": {"name": "", "log": {}}, "goals": {"title": "", "ms": []}}     # the UI reads these unconditionally
# scalar text fields: str or None. Anything else (a list in "pr", a number in "cat"...) is removed so the reader's
# default applies - sorting, grouping and label lookups then never meet an unhashable or non-text value.
_TASK_STR = ("cat", "pr", "hz", "rep", "status", "kind", "timeFrom", "timeTo", "color", "goalId", "link",
             "seriesId", "doneAt", "createdAt", "updatedAt")
_STR_FIELDS = {"tasks": _TASK_STR, "archive": _TASK_STR,
               "notes": ("folder", "createdAt", "updatedAt", "jdate", "variant", "color"),
               "habits": ("createdAt", "color", "icon"), "goals": ("desc", "horizon", "createdAt", "color")}
_BOOL_FIELDS = {"tasks": ("done",), "archive": ("done",), "notes": ("pinned",)}
_DUE_FIELDS = {"tasks": ("due", "dueEnd"), "archive": ("due", "dueEnd"), "goals": ("deadline",)}
_DICT_LISTS = ("subs", "ms")                                                        # lists of {text, done} objects


_BLOCK_KINDS = ("text", "ink", "flow")
MAX_BLOCKS = 200


def _clean_blocks(blocks) -> list:
    """A note's extra blocks (text paragraphs, sketches, flowcharts) after the first text: only well-formed dicts of a known
    kind survive, each with a unique id. The sketch / flowchart contents are repaired by the UI that draws them."""
    if not isinstance(blocks, list):
        return []
    out, seen = [], set()
    for b in blocks[:MAX_BLOCKS]:
        if not isinstance(b, dict) or b.get("t") not in _BLOCK_KINDS:
            continue
        if b["t"] == "text" and not isinstance(b.get("text"), str):
            b["text"] = ""
        if b["t"] == "ink" and not isinstance(b.get("strokes"), list):
            b["strokes"] = []
        if b["t"] == "flow":
            for f in ("nodes", "edges"):
                if not isinstance(b.get(f), list):
                    b[f] = []
        if not isinstance(b.get("id"), str) or not b["id"] or b["id"] in seen:
            b["id"] = uid("b")
        seen.add(b["id"])
        out.append(b)
    return out


def _flag(v) -> bool:
    """A foreign 'done' / 'pinned' value as a real boolean: numbers by value, everything else is False."""
    return bool(v) if isinstance(v, (int, float)) and v == v else False


def _valid_due(d) -> bool:
    if not isinstance(d, dict):
        return False
    try:
        jy, jm, jd = d["jy"], d["jm"], d["jd"]
    except KeyError:
        return False
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in (jy, jm, jd)):
        return False
    from . import jalali                                  # a day that does not exist is as broken as a missing one
    return -1000 < jy < 5000 and jalali.due_to_date(d) is not None


def normalize(v) -> dict:
    """Guarantee the known shape, keep every unknown key (forward compatible
    with newer web versions), and run the same one-way migrations as the web app.

    Structural hardening: a collection that is not a list becomes an empty one, entries that are not objects are
    dropped and entries without a usable id get one - so a damaged or foreign file can never crash a page later."""
    base = empty_vault()
    if not isinstance(v, dict):
        return base
    out = dict(v)
    for k, default in base.items():
        if out.get(k) is None:
            out[k] = default
    for k in _LIST_KEYS:
        items = out[k]
        if not isinstance(items, list):
            out[k] = items = []
        if any(not isinstance(x, dict) for x in items):
            out[k] = items = [x for x in items if isinstance(x, dict)]
        if k in _ID_KEYS:
            seen: set[str] = set()
            for x in items:
                if not isinstance(x.get("id"), str) or not x["id"] or x["id"] in seen:
                    x["id"] = uid(k[:1])
                seen.add(x["id"])
        types, required = _COERCE.get(k, {}), _REQUIRED.get(k, {})
        dues = _DUE_FIELDS.get(k, ())
        if types or required or dues:
            for x in items:
                for f in dues:                    # a half-formed Jalali date would crash pickers and calendars
                    d = x.get(f)
                    if d is not None and not _valid_due(d):
                        x[f] = None
                for f, default in required.items():
                    x.setdefault(f, copy.deepcopy(default))
                for f, typ in types.items():
                    if f in x and not isinstance(x[f], typ):
                        x[f] = typ()
                for f in _DICT_LISTS:
                    if f in x and any(not isinstance(e, dict) for e in x[f]):
                        x[f] = [e for e in x[f] if isinstance(e, dict)]
                    for e in x.get(f) or ():                     # checklist rows: text is text, done is a flag
                        e.setdefault("text", "")                 # dialogs and recurrence read row["text"] directly
                        if not isinstance(e.get("text", ""), str):
                            e["text"] = "" if e.get("text") is None or isinstance(e.get("text"), (list, dict)) else str(e["text"])
                        if "done" in e and not isinstance(e["done"], bool):
                            e["done"] = _flag(e["done"])
                if isinstance(x.get("tags"), list) and any(not isinstance(t, str) for t in x["tags"]):
                    x["tags"] = [t if isinstance(t, str) else str(t) for t in x["tags"]
                                 if isinstance(t, str) or (isinstance(t, (int, float)) and not isinstance(t, bool) and t == t)]
        for f in _STR_FIELDS.get(k, ()):
            for x in items:
                if f in x and x[f] is not None and not isinstance(x[f], str):
                    del x[f]
        if k == "notes":
            for x in items:
                if not isinstance(x.get("folder", ""), str):
                    x["folder"] = ""
                if "blocks" in x:
                    x["blocks"] = _clean_blocks(x["blocks"])
                    if not x["blocks"]:
                        del x["blocks"]
        for f in _BOOL_FIELDS.get(k, ()):
            for x in items:
                if f in x and not isinstance(x[f], bool):
                    x[f] = _flag(x[f])
    if not isinstance(out["settings"], dict):
        out["settings"] = {}
    if "pomoLog" in out["settings"] and not isinstance(out["settings"]["pomoLog"], dict):
        out["settings"]["pomoLog"] = {}
    out["trash"] = [t for t in out["trash"] if isinstance(t.get("item"), dict)]
    for t in out["trash"]:
        if not isinstance(t.get("kind"), str):
            t["kind"] = "task"
        if not isinstance(t.get("at"), str):
            t.pop("at", None)
    w = out["wellness"]
    if not isinstance(w, dict):
        w = out["wellness"] = {}
    for k in ("water", "sleep"):
        if not isinstance(w.get(k), dict):
            w[k] = {}
    _migrate_journal(out)
    _migrate_lists(out)
    out.pop("passwords", None)
    out.pop("plans", None)
    return out


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _rev(raw: dict) -> int:
    r = raw.get("revision") if isinstance(raw, dict) else 0
    return r if isinstance(r, int) and not isinstance(r, bool) and r >= 0 else 0


def _fresh_id(v: dict, wanted) -> str:
    """Keep a legacy id when it is a usable string not yet taken by a note; otherwise mint one."""
    used = {n.get("id") for n in v["notes"] if isinstance(n, dict)}
    return wanted if isinstance(wanted, str) and wanted and wanted not in used else uid("n")


def _text(x) -> str:
    return x if isinstance(x, str) else ("" if x is None else str(x))


def _migrate_journal(v: dict) -> None:
    if not v.get("journal"):
        return
    for e in v["journal"]:
        if not isinstance(e, dict):
            continue
        if not isinstance(e.get("date"), str):
            e["date"] = "" if e.get("date") is None else str(e["date"])
        v["notes"].append({
            "id": _fresh_id(v, e.get("id")), "title": _text(e.get("title")) or e["date"],
            "body": _text(e.get("body")), "html": _text(e.get("html")),
            "folder": JOURNAL_FOLDER, "mood": e.get("mood"), "jdate": e.get("date"),
            "createdAt": e.get("createdAt") or (e["date"] + "T12:00:00.000Z" if e.get("date") else now_iso()),
            "updatedAt": e.get("updatedAt") or e.get("createdAt") or now_iso(), "pinned": False,
        })
    v["journal"] = []


def _migrate_lists(v: dict) -> None:
    if not v.get("lists"):
        return
    for L in v["lists"]:
        if not isinstance(L, dict):
            continue
        items = [i for i in (L.get("items") if isinstance(L.get("items"), list) else []) if isinstance(i, dict)]
        text = "\n".join(("☑ " if i.get("done") else "☐ ") + str(i.get("text", "")) for i in items)
        v["notes"].append({
            "id": _fresh_id(v, L.get("id")), "title": _text(L.get("name")), "body": text, "html": "",
            "folder": LIST_FOLDER, "mood": None,
            "createdAt": L.get("createdAt") or now_iso(),
            "updatedAt": L.get("updatedAt") or L.get("createdAt") or now_iso(), "pinned": False,
        })
    v["lists"] = []


def default_data_dir() -> Path:
    """%APPDATA%\\AegisPlanner on Windows; ~/.local/share/AegisPlanner elsewhere."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "AegisPlanner"


def _replace(src: str, dst: Path, attempts: int = 8) -> None:
    """os.replace with a short back-off: on Windows an antivirus scanner, the search indexer or a cloud-sync
    client can hold the destination open for a few hundred ms, which surfaces as PermissionError (WinError 5/32)."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _atomic_write(path: Path, data: str) -> None:
    """Write-then-rename so a crash/power loss never leaves a half-written vault."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name[:48] + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, path)
        if os.name != "nt":                       # persist the rename itself (directory entry) on POSIX
            try:
                dfd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_bundle(path: Path):
    """Parse a vault / backup file, refusing anything absurdly large before it is read into memory."""
    if Path(path).stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file too large")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_bundle(b) -> bool:
    req = ("kdf", "salt", "wrappedKey", "wrappedKeyIv", "ciphertext", "ciphertextIv")
    return (isinstance(b, dict) and all(isinstance(b.get(k), str) for k in req)
            and isinstance(b.get("iterations"), int) and not isinstance(b.get("iterations"), bool))


def _locked(fn):
    """Serialise access to the store's mutable state. Key derivation / import run on a worker thread
    (auth.run_blocking) while Qt timers keep firing on the UI thread; without this a timer-driven save could
    interleave with an import and encrypt a half-updated vault."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        self._drain()
        with self._lock:
            return fn(self, *args, **kwargs)
    return wrapper


class VaultStore:
    def __init__(self, data_dir: Path | str | None = None):
        self._lock = threading.RLock()
        self._job: threading.Thread | None = None      # background save in flight (see save_async)
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.path = self.dir / "vault.aegis"
        self.backup_dir = self.dir / "backups"
        self.keep_backups = MAX_BACKUPS
        self.unlock_backup_s = 6 * 3600     # rolling backup on unlock (0 = off)
        self.backup_error: str | None = None
        self._raw: dict | None = None      # on-disk record (encrypted)
        self._dek: bytes | None = None
        self.vault: dict | None = None
        self.dirty = False

    # ---- state -----------------------------------------------------------
    def exists(self) -> bool:
        return self.path.is_file()

    @contextlib.contextmanager
    def _transaction(self):
        """All-or-nothing state change: if anything inside raises (disk full, antivirus lock...), the in-memory
        vault, data key and on-disk record are put back exactly as they were, so a failed operation never leaves
        the app pretending it happened."""
        prev = (self._raw, self._dek, self.vault, self.dirty)
        try:
            yield
        except BaseException:
            self._raw, self._dek, self.vault, self.dirty = prev
            raise

    @property
    def is_unlocked(self) -> bool:
        return self._dek is not None and self.vault is not None

    def has_recovery(self) -> bool:
        return bool(self._load_raw().get("recovery"))

    def _load_raw(self) -> dict:
        if self._raw is None:
            try:
                if self.path.stat().st_size > MAX_FILE_BYTES:
                    raise VaultError("فایل ولت بیش‌ازحد بزرگ است.")
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise VaultError("فایل ولت خوانده نشد یا خراب است. از پوشه‌ی پشتیبان‌ها استفاده کن.") from exc
            if not validate_bundle(raw):
                raise VaultError("ساختار فایل ولت معتبر نیست.")
            self._raw = raw
        return self._raw

    # ---- create / unlock -------------------------------------------------
    @_locked
    def create(self, password: str, seed: dict | None = None) -> None:
        if self.exists():
            raise VaultError("ولت از قبل وجود دارد.")
        meta, dek = crypto.create_key_material(password)
        with self._transaction():
            self._dek = bytearray(dek)
            self.vault = normalize(seed if seed is not None else empty_vault())
            self._raw = {"format": FORMAT, **meta.to_dict(), "ciphertext": "", "ciphertextIv": "",
                         "recovery": None, "revision": 0, "vaultId": new_vault_id(), "createdAt": now_iso()}
            self.save()

    @_locked
    def unlock(self, password: str) -> None:
        raw = self._load_raw()
        with _damaged_is_vaulterror():
            dek = crypto.unlock(password, KeyMeta.from_dict(raw))
        self._open_with(dek)

    @_locked
    def unlock_with_recovery(self, recovery_key: str, new_password: str) -> None:
        raw = self._load_raw()
        if not raw.get("recovery"):
            raise VaultError("برای این ولت کلید بازیابی ساخته نشده است.")
        with _damaged_is_vaulterror():
            dek, good_key = crypto.unwrap_with_recovery_ex(recovery_key, raw["recovery"])  # raises WrongPassword
        self._open_with(dek)
        try:
            self.change_password(new_password, recovery_key=good_key)
        except BaseException:
            self.lock()                                   # a failed reset must not leave the vault open behind the lock screen
            raise

    def _open_with(self, dek: bytes) -> None:
        raw = self._load_raw()
        if raw.get("ciphertext"):
            try:
                data = crypto.decrypt_vault(dek, raw["ciphertextIv"], raw["ciphertext"])
            except WrongPassword as exc:
                raise VaultError("رمز درست است اما داده‌های ولت آسیب دیده‌اند. از پوشه‌ی پشتیبان‌ها بازیابی کن.") from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise VaultError("رمز درست است اما داده‌های ولت آسیب دیده‌اند. از پوشه‌ی پشتیبان‌ها بازیابی کن.") from exc
        else:
            data = empty_vault()
        vault = normalize(data)
        self._purge_trash(vault)
        self._dek = bytearray(dek)
        self.vault = vault
        self._ensure_identity()
        if self.unlock_backup_s:
            try:                                          # a missing backup folder must never block unlocking
                self.snapshot("unlock", min_age_s=self.unlock_backup_s)
                self.backup_error = None
            except (OSError, VaultError) as exc:
                log.warning("unlock backup failed: %s", type(exc).__name__)
                self.backup_error = BACKUP_UNREACHABLE if isinstance(exc, OSError) else str(exc)

    def _ensure_identity(self) -> None:
        """Vaults made before 1.4 have no id / creation date: give them one (kept in memory, written by the next save).
        The date is the best honest guess - the oldest of the file's own timestamp and the oldest backup."""
        raw = self._load_raw()
        if raw.get("vaultId") and raw.get("createdAt"):
            return
        guess = None
        try:
            guess = _dt.datetime.fromtimestamp(self.path.stat().st_ctime, _dt.timezone.utc)
            for b in self.list_backups():
                w = self.backup_meta(b).get("when")
                if w is not None:
                    w = w.astimezone(_dt.timezone.utc) if w.tzinfo else w.astimezone().astimezone(_dt.timezone.utc)
                    guess = min(guess, w)
        except (OSError, VaultError, ValueError, KeyError, TypeError):
            pass
        iso = guess.isoformat(timespec="milliseconds").replace("+00:00", "Z") if guess else now_iso()
        self._raw = {**raw, "vaultId": raw.get("vaultId") or new_vault_id(), "createdAt": raw.get("createdAt") or iso}

    @_locked
    def lock(self) -> None:
        crypto.wipe(self._dek)
        self._dek = None
        self.vault = None
        self._raw = None
        self.dirty = False

    # ---- persistence -----------------------------------------------------
    def _drain(self) -> None:
        """Wait for a background save before anything else touches the vault, so writes can never reorder or be lost
        by a lock / password change / restore that slips in between. (Never called by the worker itself.)"""
        job = self._job
        if job is None or job is threading.current_thread():
            return
        owned = getattr(self._lock, "_is_owned", None)
        if owned is not None and owned():                 # nested call under the lock: the worker may be waiting for it
            return
        job.join()

    def wait_idle(self) -> None:
        """Block until no background save is running (public form of _drain)."""
        self._drain()

    def save_async(self, on_done=None) -> bool:
        """Like save(), but the slow half (encrypt + write) runs on a worker thread; only serialising stays on the
        caller. Returns False without doing anything if a previous background save is still running (the caller just
        tries again later; ``dirty`` stays set). ``on_done(error_or_None)`` is called FROM THE WORKER THREAD. A failed
        write sets ``dirty`` again so the next autosave retries."""
        job = self._job
        if job is not None and job.is_alive():
            return False
        with self._lock:
            if not self.is_unlocked:
                raise VaultError("ولت قفل است.")
            data = crypto.serialize_vault(self.vault)
            dek = bytes(self._dek)
            self.dirty = False

        def work():
            err = None
            try:
                with self._lock:
                    if self._dek is None or bytes(self._dek) != dek:
                        raise VaultError("ولت بین ذخیره عوض شد.")
                    raw = self._load_raw()
                    ct, iv = crypto.seal_vault(dek, data)
                    raw = {**raw, "format": FORMAT, "ciphertext": ct, "ciphertextIv": iv,
                           "revision": _rev(raw) + 1, "savedAt": now_iso()}
                    _atomic_write(self.path, json.dumps(raw, ensure_ascii=False))
                    self._raw = raw
            except BaseException as exc:                      # noqa: BLE001 - reported to the caller, never raised in a thread
                err = exc
                with self._lock:
                    if self._dek is not None:
                        self.dirty = True
            if on_done is not None:
                try:
                    on_done(err)
                except Exception:                             # noqa: BLE001
                    log.warning("save callback failed")

        t = threading.Thread(target=work, name="aegis-save", daemon=False)
        self._job = t
        t.start()
        return True

    @_locked
    def save(self) -> None:
        if not self.is_unlocked:
            raise VaultError("ولت قفل است.")
        raw = self._load_raw()
        ct, iv = crypto.encrypt_vault(self._dek, self.vault)
        raw = {**raw, "format": FORMAT, "ciphertext": ct, "ciphertextIv": iv,
               "revision": _rev(raw) + 1, "savedAt": now_iso()}
        _atomic_write(self.path, json.dumps(raw, ensure_ascii=False))
        self._raw = raw
        self.dirty = False

    # ---- automatic encrypted backups -------------------------------------
    # A backup is a byte-for-byte copy of the encrypted vault file, so it is protected exactly like the vault
    # (AES-256-GCM, key wrapped by the master password). Names: vault-YYYYmmdd-HHMMSS-<reason>[-keep].aegis
    # Files ending in "-keep" are pinned and never pruned by the retention limit.
    def set_backup_dir(self, path: Path | str | None) -> None:
        self.backup_dir = Path(path) if path else self.dir / "backups"

    @_locked
    def snapshot(self, reason: str = "auto", min_age_s: float = 0, protect=()) -> Path | None:
        """Copy the current encrypted file into the backup folder (atomically) and apply the retention limit.
        ``min_age_s`` skips the copy if the newest backup is younger than that. ``protect`` names backups the
        retention pass must not delete (the one being restored, the one just written)."""
        if not self.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        newest = self.list_backups()
        if min_age_s and newest:
            age = (_dt.datetime.now() - self.backup_meta(newest[0])["when"]).total_seconds()
            if 0 <= age < min_age_s:
                return None
        try:
            data = self.path.read_text(encoding="utf-8")
            valid = validate_bundle(json.loads(data))
        except ValueError:
            valid = False
        if not valid:                                       # never back up a corrupt file over good ones
            raise VaultError("فایل ولت معتبر نیست؛ پشتیبان گرفته نشد.")
        if reason in _REPEATABLE and newest and self._same_bytes(newest[0], data):
            return newest[0]                                # nothing changed since that copy: do not crowd out older history
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = self.backup_dir / f"vault-{stamp}-{reason}.aegis"
        n = 1
        while dst.exists():
            n += 1
            dst = self.backup_dir / f"vault-{stamp}-{reason}-{n}.aegis"
        _atomic_write(dst, data)
        self.prune_backups(protect=(dst, *protect))
        return dst

    @staticmethod
    def _same_bytes(backup: Path, data: str) -> bool:
        try:
            return backup.stat().st_size == len(data.encode("utf-8")) and backup.read_text(encoding="utf-8") == data
        except (OSError, ValueError):
            return False

    def _safety_snapshot(self, reason: str, protect=(), required: bool = True) -> Path | None:
        """The copy taken before a risky change. A damaged live file cannot be copied over good backups, so it is
        kept aside and the change goes ahead (that is exactly when a restore is needed); an unreachable backup
        folder blocks the change only when ``required``."""
        try:
            return self.snapshot(reason, protect=protect)
        except VaultError:
            self._set_aside_damaged()
            return None
        except OSError as exc:
            log.warning("safety backup failed: %s", type(exc).__name__)
            self.backup_error = BACKUP_UNREACHABLE
            if required:
                raise VaultError("پوشه‌ی پشتیبان در دسترس نیست؛ برای حفظ داده‌ها کاری انجام نشد. پوشه را در تنظیمات بررسی کن.") from exc
            return None

    def _set_aside_damaged(self) -> None:
        try:
            if self.path.is_file() and self.path.stat().st_size:
                dst = self.path.with_name(f"{self.path.name}.damaged-{_dt.datetime.now():%Y%m%d-%H%M%S}")
                shutil.copy2(self.path, dst)
        except OSError as exc:
            log.warning("damaged vault not kept aside: %s", type(exc).__name__)

    @_locked
    def prune_backups(self, protect=()) -> int:
        keep = max(MIN_KEEP, int(self.keep_backups or MAX_BACKUPS))
        safe = {Path(p) for p in protect}
        files = [p for p in self.list_backups() if not p.stem.endswith("-keep")]
        gone = 0
        for old in files[keep:]:
            if old in safe:
                continue
            try:
                old.unlink()
                gone += 1
            except OSError as exc:
                log.warning("could not prune backup: %s", type(exc).__name__)
        return gone

    def list_backups(self) -> list[Path]:
        try:
            if not self.backup_dir.is_dir():
                return []
            return sorted(self.backup_dir.glob("vault-*.aegis"), key=_backup_order, reverse=True)
        except OSError as exc:
            log.warning("backup folder unreadable: %s", type(exc).__name__)
            return []

    @staticmethod
    def backup_meta(path: Path) -> dict:
        """Cheap metadata (no decryption): time, reason, size, pinned, revision, structurally valid?"""
        st = path.stat()
        parts = path.stem.split("-")          # vault, YYYYmmdd, HHMMSS, reason..., [n], [keep]
        pinned = parts[-1] == "keep"
        core = parts[3:-1] if pinned else parts[3:]
        if core and core[-1].isdigit():
            core = core[:-1]
        reason = "-".join(core) or "auto"
        try:
            when = _dt.datetime.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S")
        except (IndexError, ValueError):
            when = _dt.datetime.fromtimestamp(st.st_mtime)
        rev, ok = None, False
        try:
            raw = _read_bundle(path)
            ok = validate_bundle(raw)
            rev = raw.get("revision")
        except (OSError, ValueError):
            pass
        return {"path": path, "when": when, "reason": reason, "label": BACKUP_REASONS.get(reason, reason),
                "size": st.st_size, "pinned": pinned, "revision": rev, "valid": ok}

    def open_backup(self, path: Path, password: str | None = None) -> dict:
        """Decrypt a backup for preview/verification. Uses the in-memory key first (the data key never changes
        when the password changes), falls back to ``password``. Raises WrongPassword / VaultError."""
        b = self.read_bundle(path)
        if not b["ciphertext"]:
            return empty_vault()
        if self._dek is not None:
            try:
                with _damaged_is_vaulterror():
                    return normalize(crypto.decrypt_vault(self._dek, b["ciphertextIv"], b["ciphertext"]))
            except WrongPassword:
                if password is None:
                    raise
        if password is None:
            raise WrongPassword()
        return self.decrypt_bundle(b, password)[0]

    @_locked
    def restore_backup(self, path: Path, password: str | None = None) -> None:
        """Replace the live vault with a backup. The current state is backed up first, so this is undoable.
        The current master password stays in force when the backup shares the data key."""
        if not self.is_unlocked:
            raise VaultError("ولت قفل است.")
        b = self.read_bundle(path)
        try:
            with _damaged_is_vaulterror():
                data = normalize(crypto.decrypt_vault(self._dek, b["ciphertextIv"], b["ciphertext"])) if b["ciphertext"] else empty_vault()
        except WrongPassword:
            if password is None:
                raise
            if self.dirty:
                self.save()
            self._safety_snapshot("before-restore", protect=(path,))
            self.import_replace(b, password, protect=(path,))
            return
        if self.dirty:
            self.save()
        self._safety_snapshot("before-restore", protect=(path,))
        with self._transaction():
            self._purge_trash(data)
            self.vault = data
            self.save()

    def set_pinned(self, path: Path, on: bool) -> Path:
        stem = path.stem[:-5] if path.stem.endswith("-keep") else path.stem
        dst = path.with_name(stem + ("-keep" if on else "") + path.suffix)
        if dst != path:
            if dst.exists():
                raise VaultError("پشتیبانی با همین نام از قبل وجود دارد.")
            os.replace(path, dst)
        return dst

    def _rewrap_backups(self, old_dek: bytes | None = None) -> int:
        """After a password / recovery change, bring every backup that shares our data key up to date so an OLD
        (possibly leaked) password or recovery key can no longer open old backups. With ``old_dek`` the data key
        itself was rotated: each backup is decrypted with the old key and encrypted again with the current one.
        Without it only the key envelope changes and the ciphertext is untouched."""
        raw = self._load_raw()
        n = 0
        for p in self.list_backups():
            try:
                st = p.stat()
                b = _read_bundle(p)
                if not validate_bundle(b):
                    continue
                if b["ciphertext"]:
                    data = crypto.decrypt_vault(old_dek or self._dek, b["ciphertextIv"], b["ciphertext"])   # same data key?
                    if old_dek is not None:
                        b["ciphertext"], b["ciphertextIv"] = crypto.encrypt_vault(self._dek, data)
                b.update({k: raw[k] for k in KEY_FIELDS})
                b["recovery"] = raw.get("recovery")
                _atomic_write(p, json.dumps(b, ensure_ascii=False))
                os.utime(p, (st.st_atime, st.st_mtime))
                n += 1
            except (OSError, ValueError, WrongPassword) as exc:
                log.warning("backup not re-keyed (%s): %s", p.name, type(exc).__name__)
                continue
        return n

    # ---- master password / recovery --------------------------------------
    def verify_password(self, password: str) -> bool:
        try:
            with _damaged_is_vaulterror():
                crypto.unlock(password, KeyMeta.from_dict(self._load_raw()))
            return True
        except WrongPassword:
            return False

    @_locked
    def change_password(self, new_password: str, recovery_key: str | None = None) -> str | None:
        """New master password and a NEW data key (the old key is retired, vault and backups are re-encrypted).
        The recovery key wraps the data key, so it must be re-made: with ``recovery_key`` (the one the user just
        typed to get in) it keeps working; otherwise, if a recovery key existed, a fresh one is made and returned
        ONCE - show it to the user. Returns None when there was no recovery key."""
        if not self.is_unlocked:
            raise VaultError("ولت قفل است.")
        if self.dirty:
            self.save()
        self._safety_snapshot("rekey", required=False)
        meta, new_dek = crypto.rotate(new_password)
        old_dek = self._dek
        raw0 = self._load_raw()
        fresh = None
        rec = None
        if raw0.get("recovery"):
            if recovery_key is None:
                fresh = crypto.new_recovery_key()
                recovery_key = fresh
            rec = crypto.wrap_with_recovery(new_dek, recovery_key)
        with self._transaction():
            self._dek = bytearray(new_dek)
            self._raw = {**raw0, **meta.to_dict(), "recovery": rec}
            self.save()
        self._rewrap_backups(old_dek=old_dek)
        crypto.wipe(old_dek)
        return fresh

    @_locked
    def setup_recovery(self) -> str:
        """Create (or replace) the recovery key. Returned ONCE; only the wrapped
        DEK is stored, so the key itself is never recoverable from the file."""
        if not self.is_unlocked:
            raise VaultError("ولت قفل است.")
        key = crypto.new_recovery_key()
        with self._transaction():
            self._raw = {**self._load_raw(), "recovery": crypto.wrap_with_recovery(self._dek, key)}
            self.save()
        self._rewrap_backups()          # an old recovery key must not open old backups either
        return key

    # ---- export / import -------------------------------------------------
    @_locked
    def export_bundle(self, dest: Path | str) -> Path:
        """Write a fully encrypted, web-compatible ``securevault1`` bundle."""
        if not self.is_unlocked:
            raise VaultError("ولت قفل است.")
        if self.dirty:
            self.save()
        raw = self._load_raw()
        bundle = {
            "format": FORMAT, "kdf": raw["kdf"], "iterations": raw["iterations"],
            "salt": raw["salt"], "wrappedKey": raw["wrappedKey"], "wrappedKeyIv": raw["wrappedKeyIv"],
            "ciphertext": raw["ciphertext"], "ciphertextIv": raw["ciphertextIv"],
            "exportedAt": now_iso(),
        }
        if raw.get("recovery"):
            bundle["recovery"] = raw["recovery"]
        for k in ("vaultId", "createdAt"):                         # the vault keeps its identity when restored elsewhere
            if raw.get(k):
                bundle[k] = raw[k]
        dest = Path(dest)
        _atomic_write(dest, json.dumps(bundle, ensure_ascii=False))
        self.vault.setdefault("settings", {})["lastExportAt"] = now_iso()
        self.save()
        return dest

    @staticmethod
    def read_bundle(path: Path | str) -> dict:
        try:
            if Path(path).stat().st_size > MAX_FILE_BYTES:
                raise VaultError("فایل انتخاب‌شده بیش‌ازحد بزرگ است.")
            b = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise VaultError("فایل انتخاب‌شده خوانده نشد یا JSON معتبر نیست.") from exc
        if not validate_bundle(b):
            raise VaultError("این فایل، پشتیبان معتبر Aegis نیست.")
        if not crypto.MIN_ACCEPTED_ITERATIONS <= b["iterations"] <= crypto.MAX_ACCEPTED_ITERATIONS or b["kdf"] != crypto.KDF_NAME:
            raise VaultError("پارامترهای رمزنگاری این فایل ضعیف‌اند؛ برای امنیت رد شد.")
        return b

    @staticmethod
    def decrypt_bundle(bundle: dict, password: str) -> tuple[dict, bytes]:
        """Decrypt a bundle with ITS OWN password. Raises WrongPassword."""
        with _damaged_is_vaulterror():
            dek = crypto.unlock(password, KeyMeta.from_dict(bundle))
            data = crypto.decrypt_vault(dek, bundle["ciphertextIv"], bundle["ciphertext"]) if bundle["ciphertext"] else empty_vault()
        return normalize(data), dek

    @_locked
    def import_replace(self, bundle: dict, password: str, protect=()) -> None:
        """Replace the whole vault with the bundle (its password becomes the
        master password). The current vault is snapshotted first.

        Works both when unlocked and when no vault exists yet (fresh install
        restoring a backup)."""
        vault, dek = self.decrypt_bundle(bundle, password)
        if self.exists():
            if self.is_unlocked and self.dirty:
                self.save()
            self._safety_snapshot("before-import", protect=protect)
        self._purge_trash(vault)
        with self._transaction():
            self._raw = {"format": FORMAT, **{k: bundle[k] for k in KEY_FIELDS},
                         "ciphertext": "", "ciphertextIv": "", "recovery": bundle.get("recovery"),
                         "revision": _rev(self._raw or {}),
                         "vaultId": bundle.get("vaultId") or (self._raw or {}).get("vaultId") or new_vault_id(),
                         "createdAt": bundle.get("createdAt") or (self._raw or {}).get("createdAt") or now_iso()}
            self._dek = bytearray(dek)
            self.vault = vault
            self.save()

    @_locked
    def import_merge(self, bundle: dict, password: str) -> dict:
        """Add items from the bundle that this vault does not have yet (matched
        by id). Nothing existing is overwritten or deleted. Returns counts."""
        if not self.is_unlocked:
            raise VaultError("ولت قفل است.")
        other, _ = self.decrypt_bundle(bundle, password)
        if self.dirty:
            self.save()
        self._safety_snapshot("before-merge")
        work = copy.deepcopy(self.vault)      # merge on a copy: a failed save leaves the live vault untouched
        added: dict[str, int] = {}
        for key in ("tasks", "notes", "habits", "goals", "templates", "archive"):
            mine = work.setdefault(key, [])
            by_id = {x["id"]: x for x in mine if isinstance(x, dict) and "id" in x}
            n = 0
            for x in other.get(key, []):
                cur = by_id.get(x["id"])
                if cur is None:
                    item = copy.deepcopy(x)
                    mine.append(item)
                    by_id[item["id"]] = item
                    n += 1
                elif key == "habits":
                    # union the tick logs of a habit that exists on both sides
                    log = cur.setdefault("log", {})
                    for day, val in (x.get("log") or {}).items():
                        if day not in log:
                            log[day] = val
                            n += 1
            added[key] = n
        with self._transaction():
            self.vault = work
            self.save()
        return added

    # ---- trash -----------------------------------------------------------
    def trash_put(self, kind: str, item: dict) -> None:
        self.vault.setdefault("trash", []).append({"kind": kind, "item": item, "at": now_iso()})

    def _purge_trash(self, vault: dict | None = None) -> None:
        vault = self.vault if vault is None else vault
        cutoff = time.time() - TRASH_DAYS * 86400
        keep = []
        for t in vault.get("trash", []):
            try:
                ts = _dt.datetime.fromisoformat(t["at"].replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError, AttributeError):
                ts = time.time()
            if ts > cutoff:
                keep.append(t)
        vault["trash"] = keep
