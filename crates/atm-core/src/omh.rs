//! Read-only oh-my-harness manager snapshots. Only `status --json` is ever invoked:
//! a recorded-state-only command by the oh-my-harness public contract (no Git,
//! no Codex, no network, no runtime repair). No lifecycle mutation and no polling.
use crate::{usage::bounded_json, Error, Result};
use serde::Serialize;
use serde_json::Value;
use std::{
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

pub const MANAGER_HOME_ENV: &str = "OH_MY_HARNESS_HOME";
/// Bounded one-shot read; a wedged CLI is killed, never retried.
const QUERY_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_STDERR_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct OmhHarnessView {
    pub name: String,
    pub status: Option<String>,
    pub root: Option<String>,
    pub release_version: Option<String>,
    pub updated_at: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct OmhStatusSnapshot {
    /// Where the snapshot claims to come from: `recorded` or `synthetic_demo`.
    pub source: String,
    pub manager_home: String,
    pub installed: bool,
    pub manager_status: Option<String>,
    pub channel: Option<String>,
    pub release_version: Option<String>,
    pub revision: Option<String>,
    pub repository: Option<String>,
    pub harnesses: Vec<OmhHarnessView>,
    pub operation_kind: Option<String>,
    /// `None` means the manager did not report it; never presented as clean or dirty.
    pub worktree_clean: Option<bool>,
}

/// `OH_MY_HARNESS_HOME` wins when non-empty, otherwise the user home default.
pub fn resolve_manager_home(env_value: Option<&std::ffi::OsStr>, home: &Path) -> PathBuf {
    match env_value {
        Some(value) if !value.is_empty() => PathBuf::from(value),
        _ => home.join(".oh-my-harness"),
    }
}

fn user_home() -> Result<PathBuf> {
    let variable = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    std::env::var_os(variable)
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| Error::new("OMH_HOME", "无法确定用户主目录，无法定位 oh-my-harness。"))
}

fn checked_file(path: &Path, code: &'static str, message: &'static str) -> Result<PathBuf> {
    if !path.is_absolute() || path.to_string_lossy().chars().any(char::is_control) {
        return Err(Error::new(code, message));
    }
    if !path.is_file() {
        return Err(Error::new(
            "OMH_NOT_INSTALLED",
            "未检测到可用的 harness 引擎安装；请先运行 atm harness bootstrap 后再次查询。",
        ));
    }
    Ok(path.to_path_buf())
}

/// The venv interpreter plus the checkout CLI: both plain native files, no shell,
/// no cmd/bat shim. status needs no bootstrap shim, so direct invocation is equivalent.
pub fn invocation(manager_home: &Path) -> Result<(PathBuf, Vec<String>)> {
    let guard = "oh-my-harness 路径无效。";
    let python = checked_file(
        &manager_home.join(if cfg!(windows) {
            "venv/Scripts/python.exe"
        } else {
            "venv/bin/python"
        }),
        "OMH_NOT_INSTALLED",
        guard,
    )?;
    let cli = checked_file(
        &manager_home.join("repo/scripts/omh.py"),
        "OMH_NOT_INSTALLED",
        guard,
    )?;
    Ok((
        python,
        vec![
            cli.to_string_lossy().into_owned(),
            "--home".into(),
            manager_home.to_string_lossy().into_owned(),
            "status".into(),
            "--json".into(),
        ],
    ))
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

fn harness_views(status: &Value) -> Vec<OmhHarnessView> {
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
            OmhHarnessView {
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
/// The one hard identity gate: the payload must declare itself as oh-my-harness.
pub fn parse(status: &Value, manager_home: &str, source: &str) -> Result<OmhStatusSnapshot> {
    if string_field(status, "product").as_deref() != Some("oh-my-harness") {
        return Err(Error::new(
            "OMH_PROTOCOL",
            "oh-my-harness 状态输出无法安全识别，已丢弃。",
        ));
    }
    let manager = status.get("manager").filter(|manager| manager.is_object());
    Ok(OmhStatusSnapshot {
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

/// Collects a bounded pipe in the background; the deadline loop never blocks past it.
fn bounded_pipe(
    reader: impl Read + Send + 'static,
    cap: usize,
) -> (mpsc::Receiver<Vec<u8>>, thread::JoinHandle<()>) {
    let (sender, receiver) = mpsc::channel();
    let handle = thread::spawn(move || {
        let mut reader = reader;
        let mut collected = Vec::new();
        let mut chunk = [0u8; 8192];
        loop {
            match reader.read(&mut chunk) {
                Ok(0) | Err(_) => break,
                Ok(read) => {
                    // One byte past the cap marks oversize for the bounded parser,
                    // while the pipe keeps draining so the child can exit.
                    let room = (cap + 1).saturating_sub(collected.len());
                    if room > 0 {
                        collected.extend_from_slice(&chunk[..read.min(room)]);
                    }
                }
            }
        }
        let _ = sender.send(collected);
    });
    (receiver, handle)
}

/// Runs one bounded `status --json` query against a resolved manager home.
pub fn query(manager_home: &Path) -> Result<OmhStatusSnapshot> {
    query_with_timeout(manager_home, QUERY_TIMEOUT)
}

/// Test seams may shrink the bound; it can never grow past the product limit.
pub fn query_with_timeout(manager_home: &Path, timeout: Duration) -> Result<OmhStatusSnapshot> {
    if timeout.is_zero() || timeout > QUERY_TIMEOUT {
        return Err(Error::new("OMH_TIMEOUT", "oh-my-harness 查询时限无效。"));
    }
    let (program, args) = invocation(manager_home)?;
    let mut command = Command::new(&program);
    command
        .args(&args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
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
    let mut child = command.spawn().map_err(|error| match error.kind() {
        // The interpreter vanished between the existence check and exec.
        std::io::ErrorKind::NotFound => Error::new(
            "OMH_NOT_INSTALLED",
            "未检测到可用的 harness 引擎安装；请先运行 atm harness bootstrap 后再次查询。",
        ),
        // A transient OS-level launch failure must not read as a missing install.
        _ => Error::new(
            "OMH_CLI_FAILED",
            "无法启动 oh-my-harness 的工具解释器；请检查系统资源后重试。",
        ),
    })?;
    #[cfg(windows)]
    let _job = match crate::usage::process::WindowsJob::attach(&child) {
        Ok(job) => job,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(Error::new("OMH_CLI_FAILED", "无法限制 OMH 子进程。"));
        }
    };
    let stdout = child.stdout.take().ok_or(Error::new(
        "OMH_CLI_FAILED",
        "oh-my-harness 状态查询未能完成，未产生可读取的输出。",
    ))?;
    let stderr = child.stderr.take().ok_or(Error::new(
        "OMH_CLI_FAILED",
        "oh-my-harness 状态查询未能完成，未产生可读取的输出。",
    ))?;
    let (stdout_rx, stdout_task) = bounded_pipe(stdout, crate::usage::MAX_RESPONSE_BYTES);
    let (stderr_rx, stderr_task) = bounded_pipe(stderr, MAX_STDERR_BYTES);
    let deadline = Instant::now() + timeout;
    let mut out = None;
    let mut err = None;
    while out.is_none() || err.is_none() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            #[cfg(any(target_os = "linux", target_os = "macos"))]
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGKILL);
            }
            let _ = child.kill();
            let _ = child.wait();
            return Err(Error::new(
                "OMH_TIMEOUT",
                "oh-my-harness 状态查询超时，已终止；不会自动重试。",
            ));
        }
        if out.is_none() {
            out = stdout_rx.recv_timeout(remaining).ok();
            continue;
        }
        err = stderr_rx.recv_timeout(remaining).ok();
    }
    let _ = (stdout_task.join(), stderr_task.join());
    let status_ok = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status.success(),
            Err(_) => break false,
            Ok(None) => {}
        }
        if Instant::now() >= deadline {
            #[cfg(any(target_os = "linux", target_os = "macos"))]
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGKILL);
            }
            let _ = child.kill();
            let _ = child.wait();
            return Err(Error::new(
                "OMH_TIMEOUT",
                "oh-my-harness 查询超时，已终止。",
            ));
        }
        thread::sleep(Duration::from_millis(10));
    };
    let out = out.unwrap_or_default();
    let payload = bounded_json(&out).ok();
    if !status_ok {
        // A structured runtime_unavailable object still identifies the product.
        return match payload {
            Some(payload)
                if string_field(&payload, "product").as_deref() == Some("oh-my-harness") =>
            {
                Err(Error::new(
                    "OMH_RUNTIME",
                    "harness 引擎运行时不可用；请在终端运行 atm harness -- repair --rebuild 后重试。",
                ))
            }
            _ => Err(Error::new(
                "OMH_CLI_FAILED",
                "oh-my-harness 状态查询返回失败；请在终端运行 atm harness status 核对。",
            )),
        };
    }
    let payload = payload.ok_or(Error::new(
        "OMH_PROTOCOL",
        "oh-my-harness 状态输出无法安全识别，已丢弃。",
    ))?;
    parse(&payload, &manager_home.to_string_lossy(), "recorded")
}

/// Resolves the manager home from the process environment without querying.
pub fn manager_home_from_environment() -> Result<PathBuf> {
    Ok(resolve_manager_home(
        std::env::var_os(MANAGER_HOME_ENV).as_deref(),
        &user_home()?,
    ))
}

/// Resolves the manager home from the process environment and runs one query.
pub fn query_from_environment() -> Result<OmhStatusSnapshot> {
    let manager_home =
        resolve_manager_home(std::env::var_os(MANAGER_HOME_ENV).as_deref(), &user_home()?);
    query(&manager_home)
}
