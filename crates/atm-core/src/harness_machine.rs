//! Typed GUI adapter over the same Rust application service used by `atm`.
use crate::{distribution::Service, harness, tool_catalog, Error, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
};

static ACTIVE: AtomicBool = AtomicBool::new(false);
struct Gate;
impl Drop for Gate {
    fn drop(&mut self) {
        ACTIVE.store(false, Ordering::Release);
    }
}
fn gate() -> Result<Gate> {
    ACTIVE
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| Error::new("HARNESS_BUSY", "另一个 harness 操作正在运行。"))?;
    Ok(Gate)
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Capability {
    pub supported: bool,
    #[serde(default)]
    pub requires_confirmation: bool,
    #[serde(default)]
    pub explicit_harnesses: bool,
    #[serde(default)]
    pub reason: Option<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Capabilities {
    pub harnesses: Vec<String>,
    pub operations: BTreeMap<String, Capability>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostic {
    pub operation: String,
    pub passed: bool,
    pub exit_code: i64,
}

fn request_error() -> Error {
    Error::new("HARNESS_REQUEST", "harness 操作或目标无效。")
}
fn service_at(home: &Path) -> Result<Service> {
    let user_home = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(request_error)?;
    Service::new(home.to_path_buf(), user_home).map(Service::with_environment)
}

pub fn capabilities_at(home: &Path) -> Result<Capabilities> {
    if !home.is_absolute() {
        return Err(request_error());
    }
    let mut operations = BTreeMap::new();
    for operation in [
        "install", "refresh", "remove", "repair", "check", "doctor", "update", "recover",
    ] {
        let supported = !matches!(operation, "update" | "recover");
        let mutation = matches!(operation, "install" | "refresh" | "remove" | "repair");
        operations.insert(
            operation.into(),
            Capability {
                supported,
                requires_confirmation: mutation,
                explicit_harnesses: mutation,
                reason: (!supported).then(|| "请在终端使用 atm harness sync 或 recover。".into()),
            },
        );
    }
    Ok(Capabilities {
        harnesses: tool_catalog::TOOLS
            .iter()
            .map(|tool| tool.id.to_owned())
            .collect(),
        operations,
    })
}
pub fn capabilities() -> Result<Capabilities> {
    capabilities_at(&harness::manager_home_from_environment()?)
}

pub fn execute_at(home: &Path, operation: &str, targets: &[String], confirmed: bool) -> Result<()> {
    if !confirmed {
        return Err(Error::new(
            "HARNESS_CONFIRMATION_REQUIRED",
            "执行 harness 变更前需要明确确认。",
        ));
    }
    if !matches!(
        operation,
        "install" | "refresh" | "remove" | "repair" | "update"
    ) || targets.is_empty()
        || targets.len() > 64
    {
        return Err(request_error());
    }
    let caps = capabilities_at(home)?;
    if !caps
        .operations
        .get(operation)
        .is_some_and(|cap| cap.supported)
    {
        return Err(Error::new(
            "HARNESS_UNSUPPORTED",
            "此操作需要终端中的显式迁移或恢复命令。",
        ));
    }
    let mut canonical = BTreeSet::new();
    for target in targets {
        let id = tool_catalog::find(target).map_err(|_| request_error())?.id;
        if !canonical.insert(id) {
            return Err(request_error());
        }
    }
    let _gate = gate()?;
    service_at(home)?.execute(operation, targets)?;
    Ok(())
}
pub fn execute(operation: &str, targets: &[String], confirmed: bool) -> Result<()> {
    execute_at(
        &harness::manager_home_from_environment()?,
        operation,
        targets,
        confirmed,
    )
}
pub fn diagnose(operation: &str) -> Result<Diagnostic> {
    if !matches!(operation, "check" | "doctor") {
        return Err(request_error());
    }
    let _gate = gate()?;
    let result = Service::from_environment()?.diagnose()?;
    let passed = result
        .get("passed")
        .and_then(serde_json::Value::as_bool)
        .ok_or_else(|| Error::new("HARNESS_PROTOCOL", "harness 诊断结果缺少 passed 字段。"))?;
    let exit_code = result
        .get("exitCode")
        .and_then(serde_json::Value::as_i64)
        .ok_or_else(|| Error::new("HARNESS_PROTOCOL", "harness 诊断结果缺少 exitCode 字段。"))?;
    Ok(Diagnostic {
        operation: operation.into(),
        passed,
        exit_code,
    })
}
