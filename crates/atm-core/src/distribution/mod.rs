//! Rust-owned harness distribution application service.
pub mod adapters;
pub mod hooks;
pub mod legacy;
pub mod runtime;
mod service;
pub mod source;
mod transaction;
pub use service::owns_path;
pub use service::Service;

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// A desired ordinary file; adapters only plan and never mutate targets.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Artifact {
    pub path: PathBuf,
    pub bytes: Vec<u8>,
}
