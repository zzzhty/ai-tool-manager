//! Read-only views of Rust-owned harness distribution receipts.
//! Recorded status does not execute Python, clients, network requests, or repair.
use crate::{Error, Result};
use serde::Serialize;
use serde_json::Value;
use std::path::{Path, PathBuf};

pub const MANAGER_HOME_ENV: &str = "ATM_HOME";

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HarnessDistribution {
    pub name: String,
    pub status: Option<String>,
    pub root: Option<String>,
    pub release_version: Option<String>,
    pub updated_at: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct HarnessStatusSnapshot {
    /// Where the snapshot claims to come from: `recorded` or `synthetic_demo`.
    pub source: String,
    pub manager_home: String,
    pub installed: bool,
    pub manager_status: Option<String>,
    pub channel: Option<String>,
    pub release_version: Option<String>,
    pub revision: Option<String>,
    pub repository: Option<String>,
    pub harnesses: Vec<HarnessDistribution>,
    pub operation_kind: Option<String>,
    /// `None` means the manager did not report it; never presented as clean or dirty.
    pub worktree_clean: Option<bool>,
}

/// `ATM_HOME` wins when non-empty, otherwise the user home default.
pub fn resolve_manager_home(env_value: Option<&std::ffi::OsStr>, home: &Path) -> PathBuf {
    match env_value {
        Some(value) if !value.is_empty() => PathBuf::from(value),
        _ => home.join(".atm"),
    }
}

fn user_home() -> Result<PathBuf> {
    let variable = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    std::env::var_os(variable)
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| Error::new("HARNESS_HOME", "无法确定用户主目录，无法定位 atm-harness。"))
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value.get(key)?.as_str().map(str::to_owned)
}

fn operation_kind(value: &Value) -> Option<String> {
    match value.get("operation")? {
        Value::Null => None,
        value @ Value::Object(_) => Some(
            string_field(value, "kind")
                .or_else(|| string_field(value, "operation"))
                .or_else(|| string_field(value, "command"))
                .unwrap_or_else(|| "unknown".into()),
        ),
        _ => Some("unknown".into()),
    }
}

fn harness_views(status: &Value) -> Vec<HarnessDistribution> {
    let receipts = status.get("harnessReceipts");
    let mut names = Vec::new();
    for name in status
        .get("desiredHarnesses")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        if !names.iter().any(|known: &String| known == name) {
            names.push(name.to_owned());
        }
    }
    names
        .into_iter()
        .map(|name| {
            let receipt = receipts
                .and_then(|receipts| receipts.get(&name))
                .and_then(Value::as_array)
                .and_then(|entries| entries.first());
            HarnessDistribution {
                name,
                status: receipt.and_then(|receipt| string_field(receipt, "status")),
                root: receipt.and_then(|receipt| string_field(receipt, "root")),
                release_version: receipt
                    .and_then(|receipt| string_field(receipt, "releaseVersion")),
                updated_at: receipt.and_then(|receipt| string_field(receipt, "updatedAt")),
            }
        })
        .collect()
}

/// Projects only the snapshot fields the UI shows; everything unreported stays `None`.
/// The one hard identity gate: the payload must declare itself as atm-harness.
pub fn parse(status: &Value, manager_home: &str, source: &str) -> Result<HarnessStatusSnapshot> {
    if string_field(status, "product").as_deref() != Some("atm-harness") {
        return Err(Error::new(
            "HARNESS_PROTOCOL",
            "atm-harness 状态输出无法安全识别，已丢弃。",
        ));
    }
    let manager = status.get("manager").filter(|manager| manager.is_object());
    Ok(HarnessStatusSnapshot {
        source: source.to_owned(),
        manager_home: manager_home.to_owned(),
        installed: manager.is_some(),
        manager_status: manager.and_then(|manager| string_field(manager, "status")),
        channel: manager.and_then(|manager| string_field(manager, "channel")),
        release_version: manager.and_then(|manager| string_field(manager, "releaseVersion")),
        revision: manager.and_then(|manager| string_field(manager, "revision")),
        repository: manager.and_then(|manager| string_field(manager, "repository")),
        harnesses: harness_views(status),
        operation_kind: operation_kind(status),
        worktree_clean: status.get("worktreeClean").and_then(Value::as_bool),
    })
}

/// Resolves the manager home without touching recorded state.
pub fn manager_home_from_environment() -> Result<PathBuf> {
    let home = resolve_manager_home(std::env::var_os(MANAGER_HOME_ENV).as_deref(), &user_home()?);
    if !home.is_absolute() {
        return Err(Error::new("HARNESS_HOME", "ATM_HOME 必须是绝对路径。"));
    }
    Ok(home)
}

/// Read the Rust receipt directly. No process, interpreter, cache validation or repair.
pub fn query(manager_home: &Path) -> Result<HarnessStatusSnapshot> {
    let service = crate::distribution::Service::new(manager_home.to_path_buf(), user_home()?)?;
    parse(
        &service.status()?,
        &manager_home.to_string_lossy(),
        "recorded",
    )
}

pub fn query_from_environment() -> Result<HarnessStatusSnapshot> {
    query(&manager_home_from_environment()?)
}
