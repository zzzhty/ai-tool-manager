//! Local-key core. Public views never contain saved keys or configuration bytes.
pub mod batch;
mod error;
pub mod jsonc;
#[cfg(target_os = "linux")]
pub mod linux;
#[cfg(target_os = "macos")]
pub mod macos;
#[cfg(any(target_os = "macos", all(test, target_os = "linux")))]
mod macos_keychain;
mod model;
pub mod omh;
pub mod omh_embed;
pub mod omh_machine;
pub mod projection;
pub mod skills;
pub mod storage;
pub mod templates;
pub mod usage;
pub mod vault;
pub mod windows;

pub use error::{Error, Result};
pub use model::{KeyView, SnapshotView, TargetMapping};
pub use vault::Vault;

pub const MASK: &str = "••••••••";
pub const MAX_CONFIG_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_ENCRYPTED_BYTES: usize = 64 * 1024 * 1024;
