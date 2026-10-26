//! Packaged payload location. Distribution execution lives in `distribution::Service`.
use crate::{Error, Result};
use std::path::PathBuf;

pub const SOURCE_ENV: &str = "ATM_ENGINE_SOURCE";

/// Resolve the manifest-backed payload, without invoking an installer or interpreter.
pub fn embedded_source_dir() -> Result<PathBuf> {
    crate::distribution::source::locate()
}

/// Bound the legacy Rust command namespace before parsing. It is not a process escape hatch.
pub fn bound_engine_args(args: &[String]) -> Result<()> {
    if args.len() > 64
        || args
            .iter()
            .any(|arg| arg.len() > 4096 || arg.chars().any(char::is_control))
        || args.iter().map(String::len).sum::<usize>() > 32 * 1024
    {
        return Err(Error::new(
            "CLI_ARGUMENT",
            "harness 参数过多、过长或包含控制字符。",
        ));
    }
    Ok(())
}
