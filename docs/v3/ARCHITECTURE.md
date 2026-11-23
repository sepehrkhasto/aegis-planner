# Aegis 3 architecture

Aegis 3 is a rewrite of Aegis Planner 2.x. All logic lives in a Rust core that is
shared by every front end. The front end only renders views and sends commands.
It never sees a key and never touches the vault file.

## Layers

```
            +-------------------------------------------------------------+
 front end  |  desktop app (Windows, Linux)      later: Android           |
            +------------------------------+------------------------------+
                                           | commands / queries (no keys)
            +------------------------------v------------------------------+
 facade     |  aegis-core     one stable API, error codes, view models    |
            +------+-----------+-----------+-----------+-----------+------+
 services   | aegis-store | aegis-sync | aegis-domain               |
            |  atomic I/O  |  HLC, merge |  tasks, recurrence, habits, |
            |  backups     |  .aegissync |  goals, notes, reports,     |
            |  revisions   |  QR chunks  |  quick-add, search          |
            +------+-------+------+------+------------+---------------+
 data       | aegis-model  typed vault model, normalisation, migrations |
            +---------------------------+-------------------------------+
 file       | aegis-format securevault1 (v1) and v2 container           |
            +---------------------------+-------------------------------+
 crypto     | aegis-crypto KDFs, AEAD, key wrapping, recovery keys      |
            +-----------------------------------------------------------+
 calendar   | aegis-jalali (no dependencies)                            |
            +-----------------------------------------------------------+
```

Each crate depends only on crates below it. The lower crates (`aegis-crypto`,
`aegis-format`, `aegis-jalali`, `aegis-model`) do no I/O and keep no global state,
so they can be fuzzed and tested in isolation.

## Crates

| crate | status | responsibility |
|---|---|---|
| `aegis-crypto` | v1 done | PBKDF2-SHA256, AES-256-GCM (`ct‖tag`), DEK wrapping, recovery keys, password variants, secret types that zeroise on drop |
| `aegis-format` | v1 read done | `securevault1` JSON container: size limits, validation, open to plaintext bytes; v2 later |
| `aegis-model` | planned | serde model that preserves unknown fields; repair and migration rules equal to 2.x `normalize()` |
| `aegis-jalali` | planned | Jalali ⇄ Gregorian (33-year arithmetic, same as jalaali-js / 2.x) |
| `aegis-domain` | planned | pure domain logic |
| `aegis-store` | planned | the only crate that touches the file system |
| `aegis-sync` | planned | change log, merge, packages |
| `aegis-core` | planned | facade for front ends |

## Reference implementation

`legacy/` holds the 2.x Python application unchanged. `tools/vectors/` imports
it and writes test vectors and sample vault files to `testdata/`. The Rust test
suites read those files. A 2.x behaviour that Aegis 3 changes on purpose is
listed in `docs/v3/ROADMAP.fa.md` ("چیزهایی که آگاهانه عوض می‌شوند").

## Security boundaries

- The master password, the KEK and the DEK exist only inside the core, in types
  that wipe their memory on drop and have no `Debug`/`Display` that prints them.
- Untrusted input (vault files, backups, imports, sync packages, QR frames) goes
  through `aegis-format` / `aegis-sync` parsers. They enforce size and parameter
  limits *before* doing expensive work, return typed errors and never panic.
  Each parser gets a fuzz target.
- No network code in the core.

See `docs/v3/ENGINEERING.md` for the rules every change has to follow.
