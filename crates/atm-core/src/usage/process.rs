//! Bounded, argv-only stdio transport. Product entry requires explicit CLI/account consent.
use super::{
    bounded_json,
    codex::{self, Rpc, RpcFailure, RpcResult},
    Status, MAX_RESPONSE_BYTES,
};
use crate::{Error, Result};
use serde_json::{json, Value};
use std::{
    io::{self, BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::mpsc::{self, Receiver, Sender},
    thread,
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

pub struct StdioRpc {
    child: Child,
    input: ChildStdin,
    messages: Receiver<RpcResult<Value>>,
    reader: Option<thread::JoinHandle<()>>,
    next_id: u64,
    changed: bool,
    deadline: Instant,
    watchdog_cancel: Sender<()>,
    watchdog: Option<thread::JoinHandle<()>>,
    #[cfg(windows)]
    job: WindowsJob,
}
// Only fixed stages, error kinds and numeric OS codes are diagnostic data.
// Never print paths, arguments, environment values or the OS error's display text.
fn write_cli_diagnostic(writer: &mut impl Write, stage: &'static str, error: Option<&io::Error>) {
    // Diagnostics must not turn a recoverable launch failure into a panic if
    // stderr is closed or unwritable.
    let _ = match error {
        Some(error) => writeln!(
            writer,
            "Codex CLI startup failed: stage={stage} kind={:?} os_code={:?}",
            error.kind(),
            error.raw_os_error()
        ),
        None => writeln!(writer, "Codex CLI startup failed: stage={stage}"),
    };
}
fn cli_io_error(stage: &'static str, error: io::Error) -> Error {
    write_cli_diagnostic(&mut io::stderr(), stage, Some(&error));
    cli_error()
}
fn cli_stage_error(stage: &'static str) -> Error {
    write_cli_diagnostic(&mut io::stderr(), stage, None);
    cli_error()
}
fn cli_error() -> Error {
    Error::new(
        "CLI_UNAVAILABLE",
        "无法启动所选 Codex 原生可执行文件；请检查安装与路径。",
    )
}
pub fn executable(path: &Path) -> Result<PathBuf> {
    if !path.is_absolute() || path.to_string_lossy().chars().any(char::is_control) {
        return Err(Error::new(
            "CLI_PATH",
            "请明确选择 Codex 可执行文件的绝对路径。",
        ));
    }
    if path.extension().and_then(|e| e.to_str()).is_some_and(|e| {
        ["cmd", "bat", "ps1"]
            .iter()
            .any(|s| e.eq_ignore_ascii_case(s))
    }) {
        return Err(Error::new(
            "CLI_SHIM",
            "请选择 Codex 原生可执行文件；不通过 shell 执行 cmd/bat/PowerShell shim。",
        ));
    }
    let resolved = path
        .canonicalize()
        .map_err(|error| cli_io_error("canonicalize", error))?;
    let metadata = resolved
        .metadata()
        .map_err(|error| cli_io_error("metadata", error))?;
    if !metadata.is_file() {
        return Err(cli_stage_error("not_file"));
    }
    Ok(resolved)
}
impl StdioRpc {
    pub fn launch(cli: &Path, profile: &Path, confirmed: bool) -> Result<Self> {
        Self::launch_with_timeout(cli, profile, confirmed, Duration::from_secs(24))
    }
    pub fn launch_with_timeout(
        cli: &Path,
        profile: &Path,
        confirmed: bool,
        timeout: Duration,
    ) -> Result<Self> {
        if !confirmed {
            return Err(Error::new(
                "CONFIRM_REQUIRED",
                "请先确认 CLI 联网和帐号使用。",
            ));
        }
        if timeout.is_zero() || timeout > Duration::from_secs(24) {
            return Err(Error::new("CLI_TIMEOUT", "CLI 查询时限无效。"));
        }
        if !profile.is_absolute() || profile.to_string_lossy().chars().any(char::is_control) {
            return Err(Error::new(
                "CLI_PROFILE",
                "CLI 帐号目录须为明确的绝对路径。",
            ));
        }
        let executable = executable(cli)?;
        let mut command = Command::new(executable);
        command
            .args(["app-server"])
            .env("CODEX_HOME", profile)
            .stdin(Stdio::piped())
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
        let mut child = command
            .spawn()
            .map_err(|error| cli_io_error("spawn", error))?;
        #[cfg(windows)]
        let job = match WindowsJob::attach(&child) {
            Ok(job) => job,
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(e);
            }
        };
        let input = child
            .stdin
            .take()
            .ok_or_else(|| cli_stage_error("stdin_pipe"))?;
        let output = child
            .stdout
            .take()
            .ok_or_else(|| cli_stage_error("stdout_pipe"))?;
        let (sender, messages) = mpsc::channel();
        let (watchdog_cancel, cancel) = mpsc::channel();
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        let child_id = child.id();
        #[cfg(windows)]
        let job_handle = job.0 as usize;
        let watchdog = thread::spawn(move || {
            if cancel.recv_timeout(timeout).is_err() {
                #[cfg(any(target_os = "linux", target_os = "macos"))]
                unsafe {
                    libc::kill(-(child_id as i32), libc::SIGKILL);
                }
                #[cfg(windows)]
                unsafe {
                    windows_sys::Win32::System::JobObjects::TerminateJobObject(job_handle as _, 1);
                }
            }
        });
        let reader = thread::spawn(move || {
            let mut reader = BufReader::new(output);
            let mut total = 0usize;
            loop {
                let mut bytes = Zeroizing::new(Vec::new());
                loop {
                    let buffer = match reader.fill_buf() {
                        Ok(b) => b,
                        Err(_) => {
                            let _ = sender.send(Err(RpcFailure::new(
                                Status::Unavailable,
                                "cli_stream_failed",
                            )));
                            return;
                        }
                    };
                    if buffer.is_empty() {
                        return;
                    }
                    let amount = buffer
                        .iter()
                        .position(|b| *b == b'\n')
                        .map_or(buffer.len(), |n| n + 1);
                    total += amount;
                    if bytes.len() + amount > MAX_RESPONSE_BYTES || total > 1024 * 1024 {
                        let _ = sender.send(Err(RpcFailure::new(
                            Status::ProtocolError,
                            "cli_output_limit",
                        )));
                        return;
                    }
                    let complete = buffer[amount - 1] == b'\n';
                    bytes.extend_from_slice(&buffer[..amount]);
                    reader.consume(amount);
                    if complete {
                        break;
                    }
                }
                let value = bounded_json(&bytes)
                    .map_err(|_| RpcFailure::new(Status::ProtocolError, "cli_invalid_json"));
                if sender.send(value).is_err() {
                    return;
                }
            }
        });
        Ok(Self {
            child,
            input,
            messages,
            reader: Some(reader),
            next_id: 0,
            changed: false,
            deadline: Instant::now() + timeout,
            watchdog_cancel,
            watchdog: Some(watchdog),
            #[cfg(windows)]
            job,
        })
    }
    fn write(&mut self, value: &Value) -> RpcResult<()> {
        serde_json::to_writer(&mut self.input, value)
            .map_err(|_| RpcFailure::new(Status::Unavailable, "cli_write_failed"))?;
        self.input
            .write_all(b"\n")
            .and_then(|_| self.input.flush())
            .map_err(|_| RpcFailure::new(Status::Unavailable, "cli_write_failed"))
    }
}
impl Rpc for StdioRpc {
    fn request(&mut self, method: &'static str, params: Value) -> RpcResult<Value> {
        if !matches!(
            method,
            "initialize" | "account/read" | "account/rateLimits/read"
        ) {
            return Err(RpcFailure::new(Status::ProtocolError, "rpc_method_blocked"));
        }
        self.next_id += 1;
        let id = self.next_id;
        self.write(&json!({"id":id,"method":method,"params":params}))?;
        let deadline = self.deadline.min(Instant::now() + Duration::from_secs(8));
        for _ in 0..128 {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(RpcFailure::new(Status::Unavailable, "cli_timeout"));
            }
            let value = self
                .messages
                .recv_timeout(remaining)
                .map_err(|_| RpcFailure::new(Status::Unavailable, "cli_timeout_or_closed"))??;
            if let Some(method) = value.get("method").and_then(Value::as_str) {
                if method == "account/updated" {
                    self.changed = true;
                }
                if method == "account/chatgptAuthTokens/refresh" {
                    return Err(RpcFailure::new(Status::Expired, "external_refresh_blocked"));
                }
                if let Some(server_id) = value.get("id") {
                    self.write(&json!({"id":server_id,"error":{"code":-32601,"message":"Read-only quota client does not service server requests"}}))?;
                }
                continue;
            }
            if value.get("id").and_then(Value::as_u64) != Some(id) {
                return Err(RpcFailure::new(Status::ProtocolError, "cli_response_id"));
            }
            if let Some(error) = value.get("error") {
                return Err(codex::rpc_error(error));
            }
            return value
                .get("result")
                .cloned()
                .ok_or(RpcFailure::new(Status::ProtocolError, "cli_result_missing"));
        }
        Err(RpcFailure::new(
            Status::ProtocolError,
            "cli_notification_limit",
        ))
    }
    fn notify(&mut self, method: &'static str) -> RpcResult<()> {
        if method != "initialized" {
            return Err(RpcFailure::new(Status::ProtocolError, "rpc_method_blocked"));
        }
        self.write(&json!({"method":"initialized"}))
    }
    fn reset_account_changed(&mut self) {
        self.changed = false;
    }
    fn account_changed(&self) -> bool {
        self.changed
    }
}
impl Drop for StdioRpc {
    fn drop(&mut self) {
        // Wake and join before releasing the PID/job, preventing handle reuse races.
        let _ = self.watchdog_cancel.send(());
        if let Some(watchdog) = self.watchdog.take() {
            let _ = watchdog.join();
        }
        #[cfg(any(target_os = "linux", target_os = "macos"))]
        // SAFETY: child has its own process group created by this transport; no unrelated group is targeted.
        unsafe {
            libc::kill(-(self.child.id() as i32), libc::SIGKILL);
        }
        #[cfg(windows)]
        self.job.terminate();
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}
#[cfg(windows)]
pub(crate) struct WindowsJob(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
impl WindowsJob {
    pub(crate) fn attach(child: &Child) -> Result<Self> {
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::{Foundation::CloseHandle, System::JobObjects::*};
        unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return Err(cli_error());
            }
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &limits as *const _ as *const _,
                std::mem::size_of_val(&limits) as u32,
            ) == 0
                || AssignProcessToJobObject(handle, child.as_raw_handle()) == 0
            {
                CloseHandle(handle);
                return Err(cli_error());
            }
            Ok(Self(handle))
        }
    }
    fn terminate(&mut self) {
        if !self.0.is_null() {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.0);
            }
            self.0 = std::ptr::null_mut();
        }
    }
}
#[cfg(windows)]
impl Drop for WindowsJob {
    fn drop(&mut self) {
        self.terminate();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn startup_diagnostic_excludes_error_text_and_preserves_kind_and_os_code() {
        let mut output = Vec::new();
        let error = io::Error::new(
            io::ErrorKind::PermissionDenied,
            "TEST_ONLY_secret_path_token",
        );
        write_cli_diagnostic(&mut output, "spawn", Some(&error));
        assert_eq!(
            String::from_utf8(output).unwrap(),
            "Codex CLI startup failed: stage=spawn kind=PermissionDenied os_code=None\n"
        );
        let mut output = Vec::new();
        let error = io::Error::from_raw_os_error(2);
        write_cli_diagnostic(&mut output, "canonicalize", Some(&error));
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("stage=canonicalize"));
        assert!(output.contains("os_code=Some(2)"));
    }

    #[test]
    fn startup_diagnostic_survives_a_closed_sink() {
        struct Closed;
        impl Write for Closed {
            fn write(&mut self, _: &[u8]) -> io::Result<usize> {
                Err(io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }
        write_cli_diagnostic(&mut Closed, "spawn", Some(&io::ErrorKind::NotFound.into()));
        write_cli_diagnostic(&mut Closed, "not_file", None);
    }
}
