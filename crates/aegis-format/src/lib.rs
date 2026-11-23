// SPDX-License-Identifier: GPL-3.0-or-later
//! The Aegis vault container.
//!
//! [`v1`] reads the `securevault1` JSON container that Aegis 2.x and the web
//! app write (`docs/v3/spec/format-v1.md`). Format v2 arrives in roadmap
//! phase 20.
//!
//! Everything here treats its input as hostile: size and cost limits are
//! checked before any expensive work, and every failure is a typed error.
//! The crate does no file I/O; callers pass bytes.

#![forbid(unsafe_code)]

mod error;
pub mod v1;

pub use error::{FieldProblem, FormatError, OpenError};

/// Largest vault, backup or export file Aegis accepts, in bytes (256 MiB).
pub const MAX_FILE_BYTES: usize = 256 * 1024 * 1024;
