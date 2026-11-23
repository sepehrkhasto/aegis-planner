# Engineering rules for Aegis 3

Aegis stores people's private data. A bug here can lose someone's work or leak
it, so these rules are not optional. CI checks most of them.

## Code

1. **No `unsafe`.** Every crate has `#![forbid(unsafe_code)]`. A future exception
   needs its own crate, a `// SAFETY:` proof on every block and a review.
2. **No panics in library code.** `unwrap`, `expect`, `panic!`, `todo!`,
   `unimplemented!` and unchecked indexing are denied by clippy outside tests.
   A function that can fail returns `Result` with a typed error.
3. **Typed errors.** Each crate has an `Error` enum (`thiserror`). Errors carry no
   secrets and no user content. Front ends map error *codes* to messages; the core
   never builds user-facing text.
4. **Secrets.** Keys and passwords live in `aegis_crypto::Secret*` types. They
   zeroise on drop, cannot be cloned by accident and print as `[redacted]`.
5. **Untrusted input** is bounded first (size, counts, KDF cost) and parsed second.
   Expensive work never starts before the limits pass.
6. **No global mutable state** and no I/O below `aegis-store`.
7. **Small units.** Prefer functions a reader can hold in their head. Clippy's
   `cognitive_complexity` is a warning; a reviewer asks for a split above it.
8. **Comments explain why.** A comment that repeats the code is removed. Every
   public item has a doc comment. Behaviour copied from 2.x for compatibility
   says so (`// 2.x compat:`).

## Tests

- Every behaviour that 2.x had is tested against vectors generated from
  `legacy/` (`tools/vectors/`). Vectors are committed; CI regenerates them and
  fails on a difference.
- Every parser of untrusted data gets a fuzz target (`cargo fuzz`).
- Merge and normalisation logic gets property tests (`proptest`).
- A bug fix comes with a test that failed before the fix.

## Dependencies

- Prefer audited, widely used crates (RustCrypto, serde). New dependencies need
  a reason in the commit message.
- `cargo-deny` checks licences (GPL-3.0-compatible only), advisories and sources.
- `Cargo.lock` is committed. The MSRV is set in the workspace `Cargo.toml`.

## Commits

- One logical change per commit, and every commit builds and passes tests.
- Subject: `area: imperative summary` (≤ 72 characters), for example
  `crypto: add PBKDF2-SHA256 key derivation`. The body says what and why, and
  names the roadmap phase (`Phase: 11`).
- No generated files except test vectors, and those are reproducible.

## Licence

All code is GPL-3.0-or-later. Every source file starts with
`// SPDX-License-Identifier: GPL-3.0-or-later`.
