//! Optional, isolated Python payload environments. This module never runs an installer engine.
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    ffi::OsString,
    fs::{self, File, OpenOptions},
    io::Read,
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeSpec {
    pub id: String,
    pub minimum_python: [u32; 2],
    #[serde(default)]
    pub requirements_lock: Option<String>,
    #[serde(default)]
    pub imports: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreparedRuntime {
    pub id: String,
    pub identity: String,
    pub root: PathBuf,
    pub python: PathBuf,
    pub external: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Probe {
    version: Vec<u32>,
    prefix: PathBuf,
    base_prefix: PathBuf,
    distributions: BTreeMap<String, String>,
    modules: BTreeMap<String, bool>,
}

fn invalid() -> Error {
    Error::new(
        "HARNESS_RUNTIME_SPEC",
        "Python payload 的 runtime 声明或锁定依赖无效。",
    )
}
fn python_missing() -> Error {
    Error::new(
        "HARNESS_PYTHON_REQUIRED",
        "选定 payload 需要声明版本的 Python；请显式提供可执行解释器绝对路径，ATM 不会下载解释器。",
    )
}
fn runtime_bad() -> Error {
    Error::new(
        "HARNESS_RUNTIME_INVALID",
        "Python payload 环境与声明不符；现有有效环境和引用保持不变。",
    )
}
fn portable_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 100
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}
fn is_link(metadata: &fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return true;
        }
    }
    false
}
/// Refuse linked/reparse ancestors of locations ATM will write. Interpreters may
/// themselves be ordinary platform symlinks; no interpreter path is ever written.
fn checked_path(path: &Path) -> Result<()> {
    if !path.is_absolute() || path.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err(invalid());
    }
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(metadata) if is_link(&metadata) => return Err(invalid()),
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

fn lock_bytes(spec: &RuntimeSpec, bundle_root: &Path) -> Result<Vec<u8>> {
    if !portable_id(&spec.id)
        || spec.minimum_python[0] != 3
        || spec.minimum_python[1] < 11
        || spec.imports.iter().any(|name| {
            name.is_empty() || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
        })
    {
        return Err(invalid());
    }
    match &spec.requirements_lock {
        None => Ok(Vec::new()),
        Some(relative) => {
            let path = Path::new(relative);
            if relative.is_empty()
                || relative.contains('\\')
                || path
                    .components()
                    .any(|c| !matches!(c, Component::Normal(_)))
            {
                return Err(invalid());
            }
            let root = fs::canonicalize(bundle_root).map_err(Error::io)?;
            let full = root.join(path);
            checked_path(&full)?;
            let metadata = fs::metadata(&full).map_err(Error::io)?;
            if !metadata.is_file() || metadata.len() > 1024 * 1024 {
                return Err(invalid());
            }
            fs::read(full).map_err(Error::io)
        }
    }
}

/// Restricted, hash-locked requirement grammar. Index/URL/editable directives and
/// unpinned transitive dependencies are deliberately rejected before subprocesses.
pub fn validate_spec_lock(
    spec: &RuntimeSpec,
    bundle_root: &Path,
) -> Result<BTreeMap<String, String>> {
    parse_lock(&lock_bytes(spec, bundle_root)?)
}
fn parse_lock(bytes: &[u8]) -> Result<BTreeMap<String, String>> {
    let text = std::str::from_utf8(bytes).map_err(|_| invalid())?;
    let joined = text.replace("\\\r\n", " ").replace("\\\n", " ");
    let mut packages = BTreeMap::new();
    for line in joined.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut words = line.split_whitespace();
        let requirement = words.next().ok_or_else(invalid)?;
        let (name, version) = requirement.split_once("==").ok_or_else(invalid)?;
        if name.is_empty()
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
            || version.is_empty()
            || !version
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'+' | b'!' | b'-' | b'_'))
        {
            return Err(invalid());
        }
        let hashes: Vec<_> = words.collect();
        if hashes.is_empty()
            || hashes.iter().any(|hash| {
                hash.strip_prefix("--hash=sha256:").is_none_or(|digest| {
                    digest.len() != 64 || !digest.bytes().all(|c| c.is_ascii_hexdigit())
                })
            })
            || packages
                .insert(name.to_owned(), version.to_owned())
                .is_some()
        {
            return Err(invalid());
        }
    }
    Ok(packages)
}

pub fn venv_python(root: &Path, windows: bool) -> PathBuf {
    root.join(if windows {
        "Scripts/python.exe"
    } else {
        "bin/python"
    })
}

/// Exposed argv construction keeps platform quoting out of process invocation.
pub fn pip_arguments(lock: &Path, wheel_cache: &Path, offline: bool) -> Vec<OsString> {
    let mut args: Vec<OsString> = [
        "-I",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "install",
        "--no-input",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-cache-dir",
    ]
    .into_iter()
    .map(OsString::from)
    .collect();
    if offline {
        args.push("--no-index".into());
        args.push("--find-links".into());
        args.push(wheel_cache.as_os_str().to_owned());
    }
    args.push("--requirement".into());
    args.push(lock.as_os_str().to_owned());
    args
}

fn bounded_run(program: &Path, args: &[OsString], timeout: Duration) -> Result<Vec<u8>> {
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .env_remove("VIRTUAL_ENV")
        .env_remove("PIP_TARGET")
        .env_remove("PIP_PREFIX")
        .env_remove("PIP_USER")
        .env("PYTHONDONTWRITEBYTECODE", "1");
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| python_missing())?;
    #[cfg(windows)]
    let _job = match crate::usage::process::WindowsJob::attach(&child) {
        Ok(job) => job,
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(runtime_bad());
        }
    };
    let mut stdout = child.stdout.take().ok_or_else(runtime_bad)?;
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let mut buffer = [0; 8192];
        while let Ok(length) = stdout.read(&mut buffer) {
            if length == 0 {
                break;
            }
            let keep = length.min((65537usize).saturating_sub(bytes.len()));
            bytes.extend_from_slice(&buffer[..keep]);
        }
        let _ = sender.send(bytes);
    });
    let start = Instant::now();
    let mut output = None;
    loop {
        if output.is_none() {
            output = receiver.try_recv().ok();
        }
        match child.try_wait() {
            Ok(Some(status)) if output.is_some() => {
                let bytes = output.unwrap();
                return if status.success() && bytes.len() <= 65536 {
                    Ok(bytes)
                } else {
                    Err(runtime_bad())
                };
            }
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(runtime_bad());
            }
            _ => {}
        }
        if start.elapsed() >= timeout {
            #[cfg(unix)]
            unsafe {
                libc::kill(-(child.id() as i32), libc::SIGKILL);
            }
            let _ = child.kill();
            let _ = child.wait();
            return Err(Error::new(
                "HARNESS_RUNTIME_TIMEOUT",
                "Python payload 环境准备超时；旧引用未切换。",
            ));
        }
        thread::sleep(Duration::from_millis(10));
    }
}

const PROBE: &str = r#"import importlib.util, importlib.metadata, json, sys
names, modules = json.loads(sys.argv[1])
distributions = {}
for name in names:
    try: distributions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: distributions[name] = ''
print(json.dumps({'version': list(sys.version_info[:2]), 'prefix': sys.prefix, 'basePrefix': sys.base_prefix, 'distributions': distributions, 'modules': {name: importlib.util.find_spec(name) is not None for name in modules}}))
"#;
fn probe(
    python: &Path,
    spec: &RuntimeSpec,
    packages: &BTreeMap<String, String>,
    root: Option<&Path>,
) -> Result<Probe> {
    if !python.is_absolute() || !python.is_file() {
        return Err(python_missing());
    }
    let input = serde_json::to_string(&(packages.keys().collect::<Vec<_>>(), &spec.imports))
        .map_err(|_| invalid())?;
    let bytes = bounded_run(
        python,
        &[
            "-I".into(),
            "-B".into(),
            "-c".into(),
            PROBE.into(),
            input.into(),
        ],
        Duration::from_secs(15),
    )?;
    let result: Probe = serde_json::from_slice(&bytes).map_err(|_| runtime_bad())?;
    if result.version.len() != 2
        || result.version[0] != spec.minimum_python[0]
        || result.version[1] < spec.minimum_python[1]
        || result.distributions != *packages
        || spec
            .imports
            .iter()
            .any(|name| result.modules.get(name) != Some(&true))
    {
        return Err(runtime_bad());
    }
    if let Some(root) = root {
        if fs::canonicalize(&result.prefix).map_err(Error::io)?
            != fs::canonicalize(root).map_err(Error::io)?
            || result.prefix == result.base_prefix
        {
            return Err(runtime_bad());
        }
    }
    Ok(result)
}

/// Verify one prepared reference against the selected, validated bundle's current
/// declaration. This is a read-only interpreter probe, never an import of the
/// hook entry point and never a venv/pip operation.
pub fn verify(
    manager_home: &Path,
    bundle_root: &Path,
    spec: &RuntimeSpec,
    prepared: &PreparedRuntime,
) -> Result<()> {
    let locked = lock_bytes(spec, bundle_root)?;
    let packages = parse_lock(&locked)?;
    if prepared.id != spec.id
        || prepared.identity.len() != 64
        || !prepared.identity.bytes().all(|c| c.is_ascii_hexdigit())
        || prepared.python != venv_python(&prepared.root, cfg!(windows))
    {
        return Err(runtime_bad());
    }
    checked_path(&prepared.root)?;
    checked_path(&prepared.root.join("pyvenv.cfg"))?;
    if !prepared.root.join("pyvenv.cfg").is_file() {
        return Err(runtime_bad());
    }
    if prepared.external {
        let expected = format!(
            "{:x}",
            Sha256::digest(
                serde_json::to_vec(&(spec, &locked, &prepared.root)).map_err(|_| invalid())?
            )
        );
        if prepared.identity != expected {
            return Err(runtime_bad());
        }
    } else {
        if prepared.root
            != manager_home
                .join("runtimes")
                .join(&spec.id)
                .join(&prepared.identity)
        {
            return Err(runtime_bad());
        }
        let marker = prepared.root.join(".atm-runtime.json");
        checked_path(&marker)?;
        let recorded: PreparedRuntime =
            serde_json::from_slice(&fs::read(marker).map_err(|_| runtime_bad())?)
                .map_err(|_| runtime_bad())?;
        if recorded != *prepared {
            return Err(runtime_bad());
        }
    }
    probe(&prepared.python, spec, &packages, Some(&prepared.root))?;
    Ok(())
}

/// Build and verify at the final version path, then let the caller journal a
/// reference switch. Old environments and every failed partial attempt survive.
/// The caller serializes this with its manager transaction. A separate OS lock
/// additionally prevents two direct users of this API from preparing one group.
pub fn prepare(
    manager_home: &Path,
    bundle_root: &Path,
    spec: &RuntimeSpec,
    interpreter: &Path,
    external_venv: Option<&Path>,
    offline: bool,
) -> Result<PreparedRuntime> {
    let locked = lock_bytes(spec, bundle_root)?;
    let packages = parse_lock(&locked)?;
    if let Some(root) = external_venv {
        checked_path(root)?;
        if !root.join("pyvenv.cfg").is_file() {
            return Err(runtime_bad());
        }
        let python = venv_python(root, cfg!(windows));
        probe(&python, spec, &packages, Some(root))?;
        let identity = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&(spec, &locked, root)).map_err(|_| invalid())?)
        );
        return Ok(PreparedRuntime {
            id: spec.id.clone(),
            identity,
            root: root.to_path_buf(),
            python,
            external: true,
        });
    }
    if !interpreter.is_absolute() || !interpreter.is_file() {
        return Err(python_missing());
    }
    // Probe the system interpreter only for version; packages belong in the venv.
    let base_spec = RuntimeSpec {
        imports: Vec::new(),
        ..spec.clone()
    };
    let base = probe(interpreter, &base_spec, &BTreeMap::new(), None)?;
    let canonical_python = fs::canonicalize(interpreter).map_err(Error::io)?;
    let mut interpreter_hash = Sha256::new();
    let mut file = File::open(&canonical_python).map_err(Error::io)?;
    let mut buffer = [0; 65536];
    loop {
        let n = file.read(&mut buffer).map_err(Error::io)?;
        if n == 0 {
            break;
        }
        interpreter_hash.update(&buffer[..n]);
    }
    let identity = format!(
        "{:x}",
        Sha256::digest(
            serde_json::to_vec(&(
                spec,
                &locked,
                &canonical_python,
                base.version,
                format!("{:x}", interpreter_hash.finalize())
            ))
            .map_err(|_| invalid())?
        )
    );
    let group = manager_home.join("runtimes").join(&spec.id);
    checked_path(&group)?;
    fs::create_dir_all(&group).map_err(Error::io)?;
    checked_path(&group)?;
    let lock_path = group.join(".prepare.lock");
    checked_path(&lock_path)?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock_path)
        .map_err(Error::io)?;
    lock.try_lock().map_err(|_| {
        Error::new(
            "HARNESS_RUNTIME_BUSY",
            "该 Python 依赖组正在准备，或系统无法取得独占锁。",
        )
    })?;
    let root = group.join(&identity);
    checked_path(&root)?;
    let prepared = PreparedRuntime {
        id: spec.id.clone(),
        identity,
        python: venv_python(&root, cfg!(windows)),
        root: root.clone(),
        external: false,
    };
    let marker = root.join(".atm-runtime.json");
    if root.exists() {
        checked_path(&marker)?;
        let old: PreparedRuntime = serde_json::from_slice(&fs::read(&marker).map_err(|_| {
            Error::new(
                "HARNESS_RUNTIME_INCOMPLETE",
                "此版本环境尚未准备完成；保留失败现场和旧环境，请显式清理未完成版本后重试。",
            )
        })?)
        .map_err(|_| runtime_bad())?;
        if old != prepared {
            return Err(runtime_bad());
        }
        probe(&prepared.python, spec, &packages, Some(&root))?;
        return Ok(prepared);
    }
    fs::create_dir(&root).map_err(Error::io)?;
    // Marker is written only after final-path verification, never before.
    bounded_run(
        interpreter,
        &[
            "-I".into(),
            "-B".into(),
            "-m".into(),
            "venv".into(),
            root.as_os_str().to_owned(),
        ],
        Duration::from_secs(120),
    )?;
    if !packages.is_empty() {
        let lock_path = root.join("requirements.lock");
        fs::write(&lock_path, &locked).map_err(Error::io)?;
        let wheel_cache = manager_home.join("cache/wheels");
        if offline && !wheel_cache.is_dir() {
            return Err(Error::new(
                "HARNESS_RUNTIME_OFFLINE_MISSING",
                "离线 wheel 缓存缺少锁定依赖；旧环境和引用保持不变。",
            ));
        }
        checked_path(&wheel_cache)?;
        bounded_run(
            &prepared.python,
            &pip_arguments(&lock_path, &wheel_cache, offline),
            Duration::from_secs(300),
        )
        .map_err(|error| {
            if offline && error.code == "HARNESS_RUNTIME_INVALID" {
                Error::new(
                    "HARNESS_RUNTIME_OFFLINE_MISSING",
                    "离线 wheel 缓存未满足全部锁定依赖（含版本或哈希）；旧环境和引用保持不变。",
                )
            } else {
                error
            }
        })?;
    }
    probe(&prepared.python, spec, &packages, Some(&root))?;
    let bytes = serde_json::to_vec_pretty(&prepared).map_err(|_| invalid())?;
    let mut marker_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&marker)
        .map_err(Error::io)?;
    use std::io::Write;
    marker_file.write_all(&bytes).map_err(Error::io)?;
    marker_file.sync_all().map_err(Error::io)?;
    Ok(prepared)
}
