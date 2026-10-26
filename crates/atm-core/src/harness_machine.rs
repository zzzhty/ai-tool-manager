//! Narrow external harness machine v1 boundary. No shell, arbitrary argv, or state writes.
use crate::{harness, usage::bounded_json, Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread,
    time::{Duration, Instant},
};
static ACTIVE: AtomicBool = AtomicBool::new(false);
struct Gate;
impl Drop for Gate {
    fn drop(&mut self) {
        ACTIVE.store(false, Ordering::Release);
    }
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
fn error(code: &'static str) -> Error {
    Error::new(
        code,
        "harness 操作未完成；请核对记录态状态，必要时在终端使用 atm harness 命令处理。",
    )
}
fn home() -> Result<PathBuf> {
    let user = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .ok_or_else(|| error("HARNESS_HOME"))?;
    Ok(harness::resolve_manager_home(
        std::env::var_os(harness::MANAGER_HOME_ENV).as_deref(),
        &user,
    ))
}
fn envelope(value: Value, operation: &str, success: bool) -> Result<Value> {
    if value.get("protocolVersion").and_then(Value::as_u64) != Some(1)
        || value.get("operation").and_then(Value::as_str) != Some(operation)
    {
        return Err(error("HARNESS_PROTOCOL"));
    }
    // A completed diagnostic may intentionally exit nonzero when it finds issues.
    // Return only its typed exit status; never expose captured terminal logs.
    if ["check", "doctor"].contains(&operation) {
        if let Some(code) = value.pointer("/result/exitCode").and_then(Value::as_i64) {
            return Ok(
                serde_json::json!({ "operation": operation, "passed": success && value.get("ok").and_then(Value::as_bool) == Some(true) && code == 0, "exitCode": code }),
            );
        }
    }
    if value.get("ok").and_then(Value::as_bool) != Some(true) {
        let code = match value.pointer("/error/code").and_then(Value::as_str) {
            Some("confirmation_required") => "HARNESS_CONFIRMATION_REQUIRED",
            Some("busy") => "HARNESS_BUSY",
            Some("unsupported_protocol") => "HARNESS_UNSUPPORTED",
            Some("invalid_request") => "HARNESS_REQUEST",
            _ => "HARNESS_OPERATION_FAILED",
        };
        return Err(error(code));
    }
    if !success {
        return Err(error("HARNESS_OPERATION_FAILED"));
    }
    value
        .get("result")
        .cloned()
        .ok_or_else(|| error("HARNESS_PROTOCOL"))
}
fn run(home: &Path, operation: &str, targets: &[String], confirmed: bool) -> Result<Value> {
    let (program, mut args) = harness::invocation(home)?;
    args.truncate(args.len() - 2);
    args.extend([
        "machine".into(),
        "--protocol".into(),
        "1".into(),
        operation.into(),
    ]);
    for target in targets {
        args.extend(["--harness".into(), target.clone()]);
    }
    if confirmed {
        args.push("--confirm".into());
    }
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| error("HARNESS_CLI_FAILED"))?;
    #[cfg(windows)]
    let _job = match crate::usage::process::WindowsJob::attach(&child) {
        Ok(job) => job,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error("HARNESS_CLI_FAILED"));
        }
    };
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| error("HARNESS_CLI_FAILED"))?;
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut chunk = [0; 8192];
        while let Ok(n) = stdout.read(&mut chunk) {
            if n == 0 {
                break;
            }
            let count = n.min((crate::usage::MAX_RESPONSE_BYTES + 1).saturating_sub(bytes.len()));
            bytes.extend_from_slice(&chunk[..count]);
        }
        let _ = tx.send(bytes);
    });
    let deadline = Instant::now()
        + Duration::from_secs(if confirmed || ["check", "doctor"].contains(&operation) {
            120
        } else {
            10
        });
    let mut output = None;
    loop {
        if output.is_none() {
            output = rx.try_recv().ok();
        }
        match child.try_wait() {
            Ok(Some(status)) if output.is_some() => {
                return envelope(
                    bounded_json(&output.unwrap()).map_err(|_| error("HARNESS_PROTOCOL"))?,
                    operation,
                    status.success(),
                )
            }
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error("HARNESS_CLI_FAILED"));
            }
            _ => {}
        }
        if Instant::now() >= deadline {
            #[cfg(any(target_os = "linux", target_os = "macos"))]
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGKILL);
            }
            let _ = child.kill();
            let _ = child.wait();
            return Err(error("HARNESS_TIMEOUT"));
        }
        thread::sleep(Duration::from_millis(10));
    }
}
pub fn capabilities_at(home: &Path) -> Result<Capabilities> {
    let value = run(home, "capabilities", &[], false)?;
    let caps: Capabilities =
        serde_json::from_value(value).map_err(|_| error("HARNESS_PROTOCOL"))?;
    if caps.harnesses.len() > 64
        || caps.harnesses.iter().any(|s| {
            s.is_empty()
                || s.len() > 64
                || !s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        })
    {
        return Err(error("HARNESS_PROTOCOL"));
    }
    Ok(caps)
}
pub fn capabilities() -> Result<Capabilities> {
    capabilities_at(&home()?)
}
pub fn execute_at(home: &Path, operation: &str, targets: &[String], confirmed: bool) -> Result<()> {
    if !confirmed {
        return Err(error("HARNESS_CONFIRMATION_REQUIRED"));
    }
    if !["install", "refresh", "remove", "update", "repair"].contains(&operation)
        || targets.is_empty()
        || targets.len() > 64
    {
        return Err(error("HARNESS_REQUEST"));
    }
    ACTIVE
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| error("HARNESS_BUSY"))?;
    let _gate = Gate;
    let caps = capabilities_at(home)?;
    let cap = caps
        .operations
        .get(operation)
        .ok_or_else(|| error("HARNESS_UNSUPPORTED"))?;
    if !cap.supported || !cap.requires_confirmation || !cap.explicit_harnesses {
        return Err(error("HARNESS_UNSUPPORTED"));
    }
    if targets.iter().any(|t| !caps.harnesses.contains(t))
        || targets
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != targets.len()
    {
        return Err(error("HARNESS_REQUEST"));
    }
    run(home, operation, targets, true)?;
    Ok(())
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Diagnostic {
    pub operation: String,
    pub passed: bool,
    pub exit_code: i64,
}
pub fn diagnose(operation: &str) -> Result<Diagnostic> {
    if !["check", "doctor"].contains(&operation) {
        return Err(error("HARNESS_REQUEST"));
    }
    let home = home()?;
    ACTIVE
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .map_err(|_| error("HARNESS_BUSY"))?;
    let _gate = Gate;
    let caps = capabilities_at(&home)?;
    let cap = caps
        .operations
        .get(operation)
        .ok_or_else(|| error("HARNESS_UNSUPPORTED"))?;
    if !cap.supported || cap.requires_confirmation {
        return Err(error("HARNESS_UNSUPPORTED"));
    }
    serde_json::from_value(run(&home, operation, &[], false)?)
        .map_err(|_| error("HARNESS_PROTOCOL"))
}
pub fn execute(operation: &str, targets: &[String], confirmed: bool) -> Result<()> {
    execute_at(&home()?, operation, targets, confirmed)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unconfirmed_and_invalid_before_launch() {
        let p = Path::new("/TEST_ONLY/missing");
        assert_eq!(
            execute_at(p, "remove", &["codex".into()], false)
                .unwrap_err()
                .code,
            "HARNESS_CONFIRMATION_REQUIRED"
        );
        assert_eq!(
            execute_at(p, "shell", &["codex".into()], true)
                .unwrap_err()
                .code,
            "HARNESS_REQUEST"
        );
    }
    #[test]
    fn diagnostics_preserve_issue_exit_without_exposing_logs() {
        let result = envelope(serde_json::json!({"protocolVersion":1,"operation":"doctor","ok":false,"result":{"exitCode":1,"stdout":"SECRET","stderr":"SECRET"}}), "doctor", false).unwrap();
        assert_eq!(
            result,
            serde_json::json!({"operation":"doctor","passed":false,"exitCode":1})
        );
    }
    #[test]
    fn strict_envelope_and_safe_errors() {
        assert!(envelope(
            serde_json::json!({"protocolVersion":2,"operation":"status","ok":true,"result":{}}),
            "status",
            true
        )
        .is_err());
        let e=envelope(serde_json::json!({"protocolVersion":1,"operation":"remove","ok":false,"error":{"code":"busy","message":"SECRET"}}),"remove",false).unwrap_err();
        assert_eq!(e.code, "HARNESS_BUSY");
        assert!(!e.message.contains("SECRET"));
    }
}
