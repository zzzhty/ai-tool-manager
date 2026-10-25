//! Embedded harness-engine plumbing for the `atm` CLI maintenance group and
//! the engine/hook delegation verbs. The GUI never bootstraps: it keeps using
//! `omh::invocation` against the materialized manager home, so this module is
//! consumed only by `atm-cli`.
//!
//! Resolution order for the embedded source tree: `ATM_OMH_SOURCE` override,
//! an `omh/` directory beside the executable (installed layouts), then the
//! compile-time repository path (development checkouts and cargo tests).
use crate::{Error, Result};
use std::path::{Path, PathBuf};

pub const SOURCE_ENV: &str = "ATM_OMH_SOURCE";
/// Reuses the engine's own bootstrap override so one variable drives both sides.
pub const BASE_PYTHON_ENV: &str = "OH_MY_HARNESS_BOOTSTRAP_PYTHON";
const MAX_ARGV_TOKENS: usize = 64;
const MAX_TOKEN_BYTES: usize = 4096;
const MAX_TOTAL_BYTES: usize = 32 * 1024;

fn source_error() -> Error {
    Error::new(
        "OMH_SOURCE_MISSING",
        "未找到内嵌 harness 引擎源目录；请设置 ATM_OMH_SOURCE 指向 omh 源树。",
    )
}

/// Absolute path to the vendored engine tree containing `scripts/omh.py`.
pub fn embedded_source_dir() -> Result<PathBuf> {
    if let Some(value) = std::env::var_os(SOURCE_ENV) {
        let path = PathBuf::from(&value);
        if path.is_absolute() && path.join("scripts/omh.py").is_file() {
            return Ok(path);
        }
        return Err(source_error());
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(root) = executable.parent() {
            let adjacent = root.join("omh");
            if adjacent.join("scripts/omh.py").is_file() {
                return Ok(adjacent);
            }
        }
    }
    let compiled = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../omh");
    if compiled.join("scripts/omh.py").is_file() {
        return Ok(compiled);
    }
    Err(source_error())
}

fn python_version(path: &Path) -> Option<(u32, u32)> {
    let output = std::process::Command::new(path)
        .arg("--version")
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&output.stdout);
    let line = if text.trim().is_empty() {
        String::from_utf8_lossy(&output.stderr)
    } else {
        text
    };
    let mut parts = line.split_whitespace();
    let major = parts.nth(1)?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    Some((major, minor))
}

/// A base Python (>= 3.11) for pre-venv bootstrap work.
pub fn base_python() -> Result<PathBuf> {
    if let Some(value) = std::env::var_os(BASE_PYTHON_ENV) {
        return Ok(PathBuf::from(value));
    }
    for name in ["python3", "python"] {
        let Ok(path) = which_lookup(name) else {
            continue;
        };
        match python_version(&path) {
            Some(version) if version >= (3, 11) => return Ok(path),
            Some(_) => {
                return Err(Error::new(
                    "OMH_PYTHON_MISSING",
                    "系统 Python 版本过低（需要 3.11+）；请安装后重试。",
                ))
            }
            None => continue,
        }
    }
    Err(Error::new(
        "OMH_PYTHON_MISSING",
        "未找到可用的 Python 3.11+；请安装后重试，或用 OH_MY_HARNESS_BOOTSTRAP_PYTHON 指定。",
    ))
}

/// Minimal PATH lookup without pulling a dependency: absolute wins, otherwise
/// the first PATH entry containing the executable on this platform.
fn which_lookup(name: &str) -> Result<PathBuf> {
    let program = if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_owned()
    };
    let candidate = Path::new(&program);
    if candidate.is_absolute() {
        return if candidate.is_file() {
            Ok(candidate.to_path_buf())
        } else {
            Err(Error::new("OMH_PYTHON_MISSING", "指定的 Python 不存在。"))
        };
    }
    if let Some(paths) = std::env::var_os("PATH") {
        for directory in std::env::split_paths(&paths) {
            let full = directory.join(&program);
            if full.is_file() {
                return Ok(full);
            }
        }
    }
    Err(Error::new("OMH_PYTHON_MISSING", "PATH 中未找到 Python。"))
}

fn not_installed() -> Error {
    Error::new(
        "OMH_NOT_INSTALLED",
        "未检测到内置 harness 引擎；请先运行 atm harness bootstrap。",
    )
}

fn venv_python(home: &Path) -> Result<PathBuf> {
    let python = home.join(if cfg!(windows) {
        "venv/Scripts/python.exe"
    } else {
        "venv/bin/python"
    });
    if !python.is_file() {
        return Err(not_installed());
    }
    Ok(python)
}

/// Rejects oversized delegation argv before any process is spawned.
pub fn bound_engine_args(args: &[String]) -> Result<()> {
    if args.len() > MAX_ARGV_TOKENS {
        return Err(Error::new("CLI_ARGUMENT", "引擎参数过多。"));
    }
    let total: usize = args.iter().map(String::len).sum();
    if total > MAX_TOTAL_BYTES || args.iter().any(|arg| arg.len() > MAX_TOKEN_BYTES) {
        return Err(Error::new("CLI_ARGUMENT", "引擎参数过长。"));
    }
    Ok(())
}

/// Fixed-argv engine invocation against the materialized manager home:
/// `<venv python> <repo>/scripts/omh.py --home <home> <args...>`, no shell.
pub fn harness_invocation(home: &Path, engine_args: &[String]) -> Result<(PathBuf, Vec<String>)> {
    let python = venv_python(home)?;
    let cli = home.join("repo/scripts/omh.py");
    if !cli.is_file() {
        return Err(not_installed());
    }
    bound_engine_args(engine_args)?;
    let mut args = vec![
        cli.to_string_lossy().into_owned(),
        "--home".into(),
        home.to_string_lossy().into_owned(),
    ];
    args.extend(engine_args.iter().cloned());
    Ok((python, args))
}

/// Watcher plugin delegation: `<venv python> -B <repo>/plugins/watcher/scripts/watcher skill <args...>`.
pub fn watcher_invocation(home: &Path, skill_args: &[String]) -> Result<(PathBuf, Vec<String>)> {
    let python = venv_python(home)?;
    let watcher = home.join("repo/plugins/watcher/scripts/watcher");
    if !watcher.is_file() {
        return Err(Error::new(
            "OMH_NOT_INSTALLED",
            "未检测到 watcher 插件 CLI；请先运行 atm harness bootstrap。",
        ));
    }
    bound_engine_args(skill_args)?;
    let mut args = vec![
        "-B".into(),
        watcher.to_string_lossy().into_owned(),
        "skill".into(),
    ];
    args.extend(skill_args.iter().cloned());
    Ok((python, args))
}

/// `<base python> <embedded>/scripts/atm_embed.py <command> --source ... --home ...`
pub fn embed_invocation(command: &str, home: &Path) -> Result<(PathBuf, Vec<String>)> {
    if !matches!(command, "bootstrap" | "sync") {
        return Err(Error::new("CLI_COMMAND", "未知 harness 维护命令。"));
    }
    let python = base_python()?;
    let source = embedded_source_dir()?;
    let script = source.join("scripts/atm_embed.py");
    if !script.is_file() {
        return Err(source_error());
    }
    Ok((
        python,
        vec![
            script.to_string_lossy().into_owned(),
            command.into(),
            "--source".into(),
            source.to_string_lossy().into_owned(),
            "--home".into(),
            home.to_string_lossy().into_owned(),
        ],
    ))
}
