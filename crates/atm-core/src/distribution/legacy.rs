//! One-time, explicit ownership transfer from the retired Python distributor.
//!
//! These readers never run Python and never mutate an installation. Historical
//! receipts, reports and logs are not editing authorities. The application must
//! hold `state/manager.lock`, apply the returned exact snapshots in its journal,
//! and activate the Rust receipt only after retiring the old entry points.
use super::Artifact;
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Component, Path, PathBuf},
    process::{Command, Stdio},
};

const SCHEMA: &str = "2026-08-24";
const MAX_FILE: u64 = 32 * 1024 * 1024;
const MAX_FILES: usize = 100_000;
const MAX_TREE: usize = 256 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyFile {
    pub path: PathBuf,
    pub bytes: Vec<u8>,
    pub sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyHandoff {
    pub identity: String,
    pub product: String,
    pub desired_harnesses: Vec<String>,
    /// Recorded roots are evidence only; callers must bind them to independently
    /// resolved/explicitly selected roots before inspecting external targets.
    pub roots: BTreeMap<String, PathBuf>,
    pub archives: Vec<Artifact>,
    pub retire: Vec<LegacyFile>,
    pub repository: PathBuf,
    pub source_identity: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyTarget {
    pub harness: String,
    pub path: PathBuf,
    pub kind: String,
    pub bytes: Option<Vec<u8>>,
    pub link_target: Option<PathBuf>,
    /// Exact ordinary source files for materializing a proven skill link. The
    /// transaction must recheck the link before replacing it with this tree.
    pub files: BTreeMap<String, Vec<u8>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyCodex {
    pub config_path: PathBuf,
    pub config_bytes: Vec<u8>,
    pub marketplace: String,
    pub plugins: Vec<String>,
    pub source_root: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyHookChange {
    pub path: PathBuf,
    pub before: Vec<u8>,
    pub after: Vec<u8>,
}

fn invalid() -> Error {
    Error::new(
        "HARNESS_LEGACY_INVALID",
        "旧分发状态或来源证明无效；保留原文件并停止交接。",
    )
}
fn pending() -> Error {
    Error::new(
        "HARNESS_LEGACY_PENDING",
        "旧分发仍有待恢复操作；先恢复旧操作，再显式交接。",
    )
}
fn changed() -> Error {
    Error::new(
        "HARNESS_LEGACY_CHANGED",
        "旧分发文件已修改或目标所有权不明；保留原文件并停止交接。",
    )
}
fn is_reparse(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        let _ = metadata;
        false
    }
}
fn exists(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}
fn absolute(path: &Path) -> Result<()> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
        || path.to_string_lossy().chars().any(char::is_control)
    {
        return Err(invalid());
    }
    Ok(())
}
/// Never follow an ancestor link while interpreting a recorded path.
fn ordinary_ancestors(path: &Path) -> Result<()> {
    absolute(path)?;
    for ancestor in path.ancestors().skip(1) {
        if exists(ancestor)? {
            let metadata = fs::symlink_metadata(ancestor)?;
            if !metadata.is_dir() || metadata.file_type().is_symlink() || is_reparse(&metadata) {
                return Err(invalid());
            }
        }
    }
    Ok(())
}
fn read_file(path: &Path) -> Result<Vec<u8>> {
    ordinary_ancestors(path)?;
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || is_reparse(&metadata)
        || metadata.len() > MAX_FILE
    {
        return Err(invalid());
    }
    let data = fs::read(path)?;
    if data.len() as u64 > MAX_FILE {
        return Err(invalid());
    }
    Ok(data)
}
fn json(path: &Path) -> Result<(Value, Vec<u8>)> {
    let bytes = read_file(path)?;
    let value: Value = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    if !value.is_object() {
        return Err(invalid());
    }
    Ok((value, bytes))
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn legacy_file(path: PathBuf, bytes: Vec<u8>) -> LegacyFile {
    LegacyFile {
        sha256: digest(&bytes),
        path,
        bytes,
    }
}
fn nonempty<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
        .ok_or_else(invalid)
}
fn product(value: &Value) -> Result<&str> {
    let name = nonempty(value, "product")?;
    if !matches!(name, "atm-harness" | "oh-my-harness") {
        return Err(invalid());
    }
    Ok(name)
}
fn relative(raw: &str) -> Result<PathBuf> {
    let path = Path::new(raw);
    if raw.is_empty()
        || raw.contains('\\')
        || raw.contains(':')
        || raw.chars().any(char::is_control)
        || path.is_absolute()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(invalid());
    }
    Ok(path.to_path_buf())
}
fn ignored(name: &str) -> bool {
    matches!(
        name,
        ".git" | "__pycache__" | ".venv" | ".atm-embedded.json"
    ) || name.ends_with(".pyc")
        || name.ends_with(".pyo")
}
fn tree(root: &Path) -> Result<BTreeMap<String, Vec<u8>>> {
    fn walk(
        root: &Path,
        path: &Path,
        output: &mut BTreeMap<String, Vec<u8>>,
        total: &mut usize,
    ) -> Result<()> {
        ordinary_ancestors(path)?;
        let metadata = fs::symlink_metadata(path)?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() || is_reparse(&metadata) {
            return Err(invalid());
        }
        let mut children = fs::read_dir(path)?.collect::<std::result::Result<Vec<_>, _>>()?;
        children.sort_by_key(|child| child.file_name());
        let mut folded = BTreeSet::new();
        for child in children {
            let name = child.file_name().into_string().map_err(|_| invalid())?;
            if ignored(&name) {
                continue;
            }
            if !folded.insert(name.to_lowercase()) {
                return Err(invalid());
            }
            let path = child.path();
            let metadata = fs::symlink_metadata(&path)?;
            if metadata.file_type().is_symlink() || is_reparse(&metadata) {
                return Err(invalid());
            }
            if metadata.is_dir() {
                walk(root, &path, output, total)?;
            } else if metadata.is_file() {
                let bytes = read_file(&path)?;
                *total = total.checked_add(bytes.len()).ok_or_else(invalid)?;
                if *total > MAX_TREE || output.len() >= MAX_FILES {
                    return Err(invalid());
                }
                let name = path
                    .strip_prefix(root)
                    .map_err(|_| invalid())?
                    .to_str()
                    .ok_or_else(invalid)?
                    .replace('\\', "/");
                output.insert(name, bytes);
            } else {
                return Err(invalid());
            }
        }
        Ok(())
    }
    let mut output = BTreeMap::new();
    walk(root, root, &mut output, &mut 0)?;
    Ok(output)
}
/// Match the predecessor's os.walk ordering: files at each directory before its
/// sorted child directories. A global path sort is a different hash algorithm.
fn embedded_identity(files: &BTreeMap<String, Vec<u8>>) -> String {
    fn walk(prefix: &str, files: &BTreeMap<String, Vec<u8>>, hash: &mut Sha256) {
        let mut children = BTreeSet::new();
        for (path, bytes) in files {
            if let Some(tail) = path.strip_prefix(prefix) {
                if let Some((directory, _)) = tail.split_once('/') {
                    children.insert(directory.to_owned());
                } else {
                    hash.update((path.len() as u64).to_be_bytes());
                    hash.update(path.as_bytes());
                    hash.update((bytes.len() as u64).to_be_bytes());
                    hash.update(bytes);
                }
            }
        }
        for child in children {
            walk(&format!("{prefix}{child}/"), files, hash);
        }
    }
    let mut hash = Sha256::new();
    hash.update(b"atm-engine-content-v1\0");
    walk("", files, &mut hash);
    format!("sha256:{:x}", hash.finalize())
}
fn git_read(repo: &Path, args: &[&str]) -> Result<String> {
    let result = Command::new("git")
        .args(["--no-optional-locks", "-c", "core.fsmonitor=false", "-C"])
        .arg(repo)
        .args(args)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .output()
        .map_err(|_| {
            Error::new(
                "HARNESS_LEGACY_GIT",
                "旧 Git 分发交接需要可用的 Git；不会联网或运行 Python。",
            )
        })?;
    if !result.status.success() || result.stdout.len() > 1024 * 1024 {
        return Err(invalid());
    }
    String::from_utf8(result.stdout).map_err(|_| invalid())
}
fn source_identity(
    repo: &Path,
    manager: &Value,
    files: &BTreeMap<String, Vec<u8>>,
) -> Result<String> {
    let marker = repo.join(".atm-embedded.json");
    if exists(&marker)? {
        let (marker, _) = json(&marker)?;
        if marker["sourceMode"] != "atm-embedded"
            || marker["engineIdentityAlgorithm"] != "atm-engine-content-v1"
            || marker["engineIdentity"] != embedded_identity(files)
            || marker["embeddedVersion"] != manager["releaseVersion"]
            || marker["embeddedIdentity"] != manager["bundleIdentity"]
            || manager["channel"] != "embedded"
        {
            return Err(changed());
        }
        let engine = nonempty(&marker, "engineIdentity")?;
        let release = nonempty(&marker, "embeddedVersion")?;
        if manager["revision"] != digest(format!("{engine}|{release}").as_bytes())[..40] {
            return Err(invalid());
        }
        Ok(engine.to_owned())
    } else {
        if !exists(&repo.join(".git"))? {
            return Err(invalid());
        }
        let revision = nonempty(manager, "revision")?;
        if revision.len() != 40
            || !revision.bytes().all(|c| c.is_ascii_hexdigit())
            || git_read(repo, &["rev-parse", "HEAD"])?.trim() != revision
            || !git_read(repo, &["status", "--porcelain", "--untracked-files=all"])?
                .trim()
                .is_empty()
            || git_read(repo, &["remote", "get-url", "origin"])?.trim()
                != nonempty(manager, "repository")?
        {
            return Err(changed());
        }
        Ok(format!("git:{revision}:{}", embedded_identity(files)))
    }
}
fn launcher_from_source(source: &[u8], windows: bool) -> Result<Vec<u8>> {
    let text = std::str::from_utf8(source)
        .map_err(|_| invalid())?
        .replace("\r\n", "\n");
    let section = text
        .split_once(if windows {
            "def windows_launcher("
        } else {
            "def posix_launcher("
        })
        .ok_or_else(invalid)?
        .1;
    let literal = section
        .split_once("return r'''")
        .ok_or_else(invalid)?
        .1
        .split_once("'''")
        .ok_or_else(invalid)?
        .0;
    Ok(if windows {
        literal.replace('\n', "\r\n").into_bytes()
    } else {
        literal.as_bytes().to_vec()
    })
}

/// Read and validate predecessor state. No write (including lock creation) is
/// performed. The application must call this again under the common manager lock
/// before applying the returned archive/retirement plan.
pub fn inspect(home: &Path) -> Result<Option<LegacyHandoff>> {
    absolute(home)?;
    ordinary_ancestors(&home.join("state/manager.json"))?;
    let manager_path = home.join("state/manager.json");
    let desired_path = home.join("state/desired.json");
    let initial_path = home.join("state/install.json");
    if exists(&home.join("state/operations/current.json"))? {
        return Err(pending());
    }
    let manager_exists = exists(&manager_path)?;
    let desired_exists = exists(&desired_path)?;
    if !manager_exists && !desired_exists {
        if exists(&initial_path)? || exists(&home.join("repo/scripts/engine.py"))? {
            return Err(Error::new(
                "HARNESS_LEGACY_INCOMPLETE",
                "旧分发缺少完整滚动状态；不能从历史安装收据推断当前所有权。",
            ));
        }
        return Ok(None);
    }
    if !manager_exists || !desired_exists {
        return Err(invalid());
    }
    if exists(&home.join("state/distribution.json"))? {
        return Err(Error::new(
            "HARNESS_DUAL_OWNER",
            "检测到两个分发所有者；保留状态并停止操作。",
        ));
    }
    let (manager, manager_bytes) = json(&manager_path)?;
    let (desired, desired_bytes) = json(&desired_path)?;
    let old_product = product(&manager)?.to_owned();
    if manager["schemaVersion"] != SCHEMA
        || manager["status"] != "ready"
        || desired["schemaVersion"] != SCHEMA
    {
        return Err(invalid());
    }
    for field in [
        "repository",
        "revision",
        "releaseVersion",
        "bundleIdentity",
        "channel",
    ] {
        nonempty(&manager, field)?;
    }
    if !matches!(
        desired
            .pointer("/updatePolicy/channel")
            .and_then(Value::as_str),
        Some("stable" | "main")
    ) {
        return Err(invalid());
    }
    let desired_harnesses: Vec<String> = desired["harnesses"]
        .as_array()
        .ok_or_else(invalid)?
        .iter()
        .map(|value| {
            value
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_owned)
                .ok_or_else(invalid)
        })
        .collect::<Result<_>>()?;
    if desired_harnesses
        .windows(2)
        .any(|names| names[0] >= names[1])
    {
        return Err(invalid());
    }
    let repo = home.join("repo");
    let source_files = tree(&repo)?;
    let source_identity = source_identity(&repo, &manager, &source_files)?;
    for name in [
        "scripts/engine.py",
        "scripts/manager_state.py",
        ".agents/harnesses/registry.json",
    ] {
        if !source_files.contains_key(name) {
            return Err(invalid());
        }
    }
    let registry: Value = serde_json::from_slice(&source_files[".agents/harnesses/registry.json"])
        .map_err(|_| invalid())?;
    let specs = registry["harnesses"].as_object().ok_or_else(invalid)?;
    let mut roots = BTreeMap::new();
    let mut historical = vec![
        legacy_file(manager_path, manager_bytes),
        legacy_file(desired_path, desired_bytes),
    ];
    for name in &desired_harnesses {
        let (canonical, spec) = specs
            .iter()
            .find(|(key, spec)| {
                *key == name
                    || spec["aliases"]
                        .as_array()
                        .is_some_and(|items| items.iter().any(|alias| alias == name))
            })
            .ok_or_else(invalid)?;
        let mut names = vec![canonical.clone()];
        if let Some(aliases) = spec["aliases"].as_array() {
            for alias in aliases {
                names.push(alias.as_str().ok_or_else(invalid)?.to_owned());
            }
        }
        let mut root = None;
        for receipt_name in names {
            relative(&receipt_name)?;
            let path = home
                .join("state/harnesses")
                .join(format!("{receipt_name}.json"));
            if !exists(&path)? {
                continue;
            }
            let (receipt, bytes) = json(&path)?;
            if receipt["schemaVersion"] != SCHEMA
                || receipt["status"] != "ready"
                || receipt["harness"] != receipt_name
            {
                return Err(invalid());
            }
            for field in [
                "managerRevision",
                "releaseVersion",
                "bundleIdentity",
                "updatedAt",
            ] {
                nonempty(&receipt, field)?;
            }
            let recorded = PathBuf::from(nonempty(&receipt, "root")?);
            absolute(&recorded)?;
            if root.as_ref().is_some_and(|previous| previous != &recorded) {
                return Err(invalid());
            }
            root = Some(recorded);
            historical.push(legacy_file(path, bytes));
        }
        let root = root.ok_or_else(invalid)?;
        if roots.insert(canonical.clone(), root).is_some() {
            return Err(invalid());
        }
    }
    let mut retained_initial = None;
    if exists(&initial_path)? {
        let (initial, bytes) = json(&initial_path)?;
        product(&initial)?;
        if initial["status"] != "ready" {
            return Err(invalid());
        }
        for (key, expected) in [
            ("home", home.to_path_buf()),
            ("repo", repo.clone()),
            ("venv", home.join("venv")),
        ] {
            if initial["paths"][key].as_str().map(Path::new) != Some(expected.as_path()) {
                return Err(invalid());
            }
        }
        retained_initial = Some(legacy_file(initial_path, bytes));
    }
    let mut retire = historical.clone();
    for (path, bytes) in &source_files {
        if path.starts_with("scripts/") {
            retire.push(legacy_file(repo.join(relative(path)?), bytes.clone()));
        }
    }
    let bootstrap = home.join("bootstrap/atm_bootstrap.py");
    if exists(&bootstrap)? {
        let bytes = read_file(&bootstrap)?;
        if source_files.get("scripts/atm_bootstrap.py") != Some(&bytes) {
            return Err(changed());
        }
        retire.push(legacy_file(bootstrap, bytes));
    }
    for name in ["oh-my-harness", "omh", "oh-my-harness.cmd", "omh.cmd"] {
        let path = home.join("bin").join(name);
        if !exists(&path)? {
            continue;
        }
        let bytes = read_file(&path)?;
        let source = source_files
            .get("scripts/install_engine.py")
            .ok_or_else(invalid)?;
        if bytes != launcher_from_source(source, name.ends_with(".cmd"))? {
            return Err(changed());
        }
        retire.push(legacy_file(path, bytes));
    }
    // Do not infer ownership of unrecorded target receipts.
    let receipts = home.join("state/harnesses");
    if exists(&receipts)? {
        let known: BTreeSet<_> = historical.iter().map(|entry| entry.path.clone()).collect();
        for entry in fs::read_dir(&receipts)? {
            let path = entry?.path();
            if !known.contains(&path) {
                return Err(invalid());
            }
        }
    }
    let mut hash = Sha256::new();
    hash.update(b"atm-legacy-handoff-v1\0");
    hash.update(source_identity.as_bytes());
    for entry in &historical {
        hash.update(&entry.bytes);
    }
    let identity = format!("{:x}", hash.finalize());
    let archive_root = home.join("state/legacy-handoff").join(&identity);
    let mut archives = Vec::new();
    for entry in retire.iter().chain(retained_initial.iter()) {
        let relative = entry.path.strip_prefix(home).map_err(|_| invalid())?;
        let path = archive_root.join(relative);
        if exists(&path)? {
            return Err(changed());
        }
        archives.push(Artifact {
            path,
            bytes: entry.bytes.clone(),
        });
    }
    Ok(Some(LegacyHandoff {
        identity,
        product: old_product,
        desired_harnesses: roots.keys().cloned().collect(),
        roots,
        archives,
        retire,
        repository: repo,
        source_identity,
    }))
}

fn target_file(harness: &str, path: PathBuf, expected: &[u8]) -> Result<Option<LegacyTarget>> {
    if !exists(&path)? {
        return Ok(None);
    }
    let bytes = read_file(&path)?;
    if bytes != expected {
        return Err(changed());
    }
    Ok(Some(LegacyTarget {
        harness: harness.into(),
        path,
        kind: "file".into(),
        bytes: Some(bytes),
        link_target: None,
        files: BTreeMap::new(),
    }))
}
fn target_link(
    harness: &str,
    path: PathBuf,
    source: &Path,
    files: BTreeMap<String, Vec<u8>>,
) -> Result<Option<LegacyTarget>> {
    if !exists(&path)? {
        return Ok(None);
    }
    ordinary_ancestors(&path)?;
    let metadata = fs::symlink_metadata(&path)?;
    if !(metadata.file_type().is_symlink() || is_reparse(&metadata) && metadata.is_dir()) {
        return Err(changed());
    }
    let raw = fs::read_link(&path)?;
    let resolved = if raw.is_absolute() {
        raw.clone()
    } else {
        path.parent().ok_or_else(invalid)?.join(&raw)
    };
    // Canonicalization is only comparison, never an authority for writing to the
    // resolved target. The resulting journal changes the link itself.
    if resolved.canonicalize()? != source.canonicalize()? {
        return Err(changed());
    }
    Ok(Some(LegacyTarget {
        harness: harness.into(),
        path,
        kind: "symlink".into(),
        bytes: None,
        link_target: Some(raw),
        files,
    }))
}

fn codex_manifest(handoff: &LegacyHandoff) -> Result<(String, Vec<String>)> {
    let (manifest, _) = json(
        &handoff
            .repository
            .join(".agents/plugins/install-manifest.json"),
    )?;
    let (marketplace, _) = json(&handoff.repository.join(".agents/plugins/marketplace.json"))?;
    let name = nonempty(&manifest, "marketplace")?;
    relative(name)?;
    if marketplace["name"] != name {
        return Err(invalid());
    }
    let mut plugins = Vec::new();
    for plugin in manifest["plugins"].as_array().ok_or_else(invalid)? {
        if plugin["install"].as_bool().ok_or_else(invalid)? {
            let plugin = nonempty(plugin, "name")?;
            relative(plugin)?;
            if plugin.contains('/') || plugins.iter().any(|known| known == plugin) {
                return Err(invalid());
            }
            plugins.push(plugin.to_owned());
        }
    }
    if plugins.is_empty() {
        return Err(invalid());
    }
    Ok((name.to_owned(), plugins))
}

/// Parameters for the Codex adapter's narrow TOML ownership importer. This does
/// not claim ownership of the whole shared configuration file.
pub fn codex_evidence(handoff: &LegacyHandoff, allowed_root: &Path) -> Result<Option<LegacyCodex>> {
    let Some(root) = handoff.roots.get("codex") else {
        return Ok(None);
    };
    if root != allowed_root {
        return Err(changed());
    }
    let (marketplace, plugins) = codex_manifest(handoff)?;
    let config_path = root.join("config.toml");
    let config_bytes = read_file(&config_path)?;
    Ok(Some(LegacyCodex {
        config_path,
        config_bytes,
        marketplace,
        plugins,
        source_root: handoff.repository.clone(),
    }))
}

fn directory_names(root: &Path) -> Result<BTreeSet<String>> {
    fn walk(root: &Path, path: &Path, names: &mut BTreeSet<String>) -> Result<()> {
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let name = entry.file_name().into_string().map_err(|_| invalid())?;
            if ignored(&name) {
                continue;
            }
            let metadata = fs::symlink_metadata(entry.path())?;
            if metadata.file_type().is_symlink() || is_reparse(&metadata) {
                return Err(changed());
            }
            if metadata.is_dir() {
                names.insert(
                    entry
                        .path()
                        .strip_prefix(root)
                        .map_err(|_| invalid())?
                        .to_str()
                        .ok_or_else(invalid)?
                        .replace('\\', "/"),
                );
                walk(root, &entry.path(), names)?;
            }
        }
        Ok(())
    }
    let mut names = BTreeSet::new();
    walk(root, root, &mut names)?;
    Ok(names)
}

fn normalized(bytes: &[u8]) -> Vec<u8> {
    match std::str::from_utf8(bytes) {
        Ok(text) => text.replace("\r\n", "\n").into_bytes(),
        Err(_) => bytes.to_vec(),
    }
}

fn codex_caches(handoff: &LegacyHandoff, root: &Path) -> Result<Vec<LegacyTarget>> {
    let (marketplace, plugins) = codex_manifest(handoff)?;
    let mut output = Vec::new();
    for plugin in plugins {
        let source = handoff.repository.join("plugins").join(&plugin);
        let (manifest, _) = json(&source.join(".codex-plugin/plugin.json"))?;
        if manifest["name"] != plugin {
            return Err(invalid());
        }
        let version = nonempty(&manifest, "version")?;
        relative(version)?;
        if version.contains('/') {
            return Err(invalid());
        }
        let path = root
            .join("plugins/cache")
            .join(&marketplace)
            .join(&plugin)
            .join(version);
        if !exists(&path)? {
            return Err(changed());
        }
        let expected = tree(&source)?;
        let actual = tree(&path)?;
        if expected.keys().ne(actual.keys())
            || expected
                .iter()
                .any(|(name, bytes)| normalized(bytes) != normalized(&actual[name]))
            || directory_names(&source)? != directory_names(&path)?
        {
            return Err(changed());
        }
        output.push(LegacyTarget {
            harness: "codex".into(),
            path,
            kind: "directory".into(),
            bytes: None,
            link_target: None,
            files: actual,
        });
    }
    Ok(output)
}

/// Prove target ownership against caller-selected roots. Directory links are
/// represented exactly; no recursive deletion or traversal through them occurs.
pub fn inspect_targets(
    home: &Path,
    handoff: &LegacyHandoff,
    allowed_roots: &BTreeMap<String, PathBuf>,
) -> Result<Vec<LegacyTarget>> {
    if handoff.repository != home.join("repo") {
        return Err(invalid());
    }
    let current = inspect(home)?.ok_or_else(invalid)?;
    if current.identity != handoff.identity
        || current.roots != handoff.roots
        || current.source_identity != handoff.source_identity
    {
        return Err(changed());
    }
    let (registry, _) = json(&handoff.repository.join(".agents/harnesses/registry.json"))?;
    let source_name = registry
        .pointer("/sources/instructions/current")
        .and_then(Value::as_str)
        .or_else(|| {
            registry
                .pointer("/sources/instructions")
                .and_then(Value::as_str)
        })
        .ok_or_else(invalid)?;
    let source = handoff.repository.join(relative(source_name)?);
    let instructions = read_file(&source)?;
    let mut skills = Vec::new();
    let plugin_root = handoff.repository.join("plugins");
    for plugin in fs::read_dir(&plugin_root)? {
        let root = plugin?.path().join("skills");
        if !exists(&root)? {
            continue;
        }
        ordinary_ancestors(&root.join("SKILL.md"))?;
        for entry in fs::read_dir(root)? {
            let directory = entry?.path();
            let skill = directory.join("SKILL.md");
            if !exists(&skill)? {
                continue;
            }
            let bytes = read_file(&skill)?;
            let text = std::str::from_utf8(&bytes).map_err(|_| invalid())?;
            let header = text
                .strip_prefix("---\n")
                .or_else(|| text.strip_prefix("---\r\n"))
                .ok_or_else(invalid)?;
            let body = header.split_once("\n---").ok_or_else(invalid)?.0;
            let name = body
                .lines()
                .find_map(|line| line.strip_prefix("name:"))
                .ok_or_else(invalid)?
                .trim()
                .trim_matches(['\'', '"']);
            if name.is_empty()
                || !name
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'.' | b'_' | b'-'))
            {
                return Err(invalid());
            }
            skills.push((name.to_owned(), directory));
        }
    }
    let mut output = Vec::new();
    for (harness, root) in &handoff.roots {
        if allowed_roots.get(harness) != Some(root) {
            return Err(changed());
        }
        ordinary_ancestors(&root.join("ownership-probe"))?;
        let spec = &registry["harnesses"][harness];
        match spec.pointer("/skills/driver").and_then(Value::as_str) {
            Some("directory-projection") => {
                let skills_root = root.join(relative(
                    spec.pointer("/skills/relativePath")
                        .and_then(Value::as_str)
                        .ok_or_else(invalid)?,
                )?);
                for (name, directory) in &skills {
                    if let Some(target) =
                        target_link(harness, skills_root.join(name), directory, tree(directory)?)?
                    {
                        output.push(target);
                    }
                }
            }
            Some("codex-marketplace") => {
                output.extend(codex_caches(handoff, root)?);
            }
            _ => return Err(invalid()),
        }
        let instruction_spec = &spec["instructions"];
        let relative_target = match instruction_spec["driver"].as_str() {
            Some("none") => None,
            Some("managed-file") => Some(relative(nonempty(instruction_spec, "relativePath")?)?),
            Some("settings-derived-file") => {
                let settings = root.join(relative(nonempty(instruction_spec, "settingsPath")?)?);
                let name = if exists(&settings)? {
                    let (settings, _) = json(&settings)?;
                    let mut cursor = &settings;
                    for key in instruction_spec["settingPath"]
                        .as_array()
                        .ok_or_else(invalid)?
                    {
                        cursor = &cursor[key.as_str().ok_or_else(invalid)?];
                    }
                    if cursor.is_null() {
                        nonempty(instruction_spec, "defaultRelativePath")?.to_owned()
                    } else if let Some(name) = cursor.as_str() {
                        name.to_owned()
                    } else if let Some(items) = cursor.as_array() {
                        if items.len() != 1 {
                            return Err(invalid());
                        }
                        items[0].as_str().ok_or_else(invalid)?.to_owned()
                    } else {
                        return Err(invalid());
                    }
                } else {
                    nonempty(instruction_spec, "defaultRelativePath")?.to_owned()
                };
                Some(relative(&name)?)
            }
            _ => return Err(invalid()),
        };
        if let Some(relative_target) = relative_target {
            let path = root.join(relative_target);
            if exists(&path)? && fs::symlink_metadata(&path)?.file_type().is_symlink() {
                if let Some(target) = target_link(harness, path, &source, BTreeMap::new())? {
                    output.push(target);
                }
            } else if let Some(target) = target_file(harness, path, &instructions)? {
                output.push(target);
            }
        }
        if harness == "codex" {
            let support = handoff.repository.join("agents/operating-principles.md");
            if exists(&support)? {
                let mut text=String::from("# Managed by atm-harness scripts/sync_codex_agents.py.\n# Source: agents/operating-principles.md\n# Do not edit this target file directly.\n\n");
                text.push_str(std::str::from_utf8(&read_file(&support)?).map_err(|_| invalid())?);
                if !text.ends_with('\n') {
                    text.push('\n');
                }
                if let Some(target) = target_file(
                    harness,
                    root.join("agents/operating-principles.md"),
                    text.as_bytes(),
                )? {
                    output.push(target);
                }
            }
        }
    }
    Ok(output)
}

fn predecessor_command(args: &[String], windows: bool) -> String {
    if !windows {
        return args
            .iter()
            .map(|arg| {
                if !arg.is_empty()
                    && arg
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_@%+=:,./-".contains(&c))
                {
                    arg.clone()
                } else {
                    format!("'{}'", arg.replace('\'', "'\"'\"'"))
                }
            })
            .collect::<Vec<_>>()
            .join(" ");
    }
    // Python subprocess.list2cmdline / MS C argv quoting. This is a comparison
    // with already-installed evidence, never a new execution command.
    args.iter()
        .map(|arg| {
            let quote = arg.is_empty() || arg.contains([' ', '\t']);
            let mut result = String::new();
            if quote {
                result.push('"');
            }
            let mut slashes = 0;
            for c in arg.chars() {
                match c {
                    '\\' => slashes += 1,
                    '"' => {
                        result.push_str(&"\\".repeat(slashes * 2 + 1));
                        result.push('"');
                        slashes = 0;
                    }
                    _ => {
                        result.push_str(&"\\".repeat(slashes));
                        slashes = 0;
                        result.push(c);
                    }
                }
            }
            result.push_str(&"\\".repeat(if quote { slashes * 2 } else { slashes }));
            if quote {
                result.push('"');
            }
            result
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Explicit adoption retires proven predecessor hooks, leaving hook execution
/// disabled until the caller explicitly prepares and enables the new runtime.
/// A prefix is only an ambiguity detector, never sufficient ownership evidence.
pub fn hook_retirement(
    handoff: &LegacyHandoff,
    allowed_root: &Path,
) -> Result<Option<LegacyHookChange>> {
    if handoff
        .roots
        .get("codex")
        .is_some_and(|root| root != allowed_root)
    {
        return Err(changed());
    }
    // Hooks were independently installable; they need not have a skill receipt.
    // The caller supplies the independently selected Codex root in that case.
    let path = allowed_root.join("hooks.json");
    if !exists(&path)? {
        return Ok(None);
    }
    let (mut config, before) = json(&path)?;
    let Some(hooks) = config.get_mut("hooks") else {
        return Ok(None);
    };
    let hooks = hooks.as_object_mut().ok_or_else(invalid)?;
    let home = handoff.repository.parent().ok_or_else(invalid)?;
    let python = home.join(if cfg!(windows) {
        "venv/Scripts/python.exe"
    } else {
        "venv/bin/python"
    });
    let command = predecessor_command(
        &[
            python.to_string_lossy().into_owned(),
            "-B".into(),
            handoff
                .repository
                .join("plugins/watcher/scripts/watcher")
                .to_string_lossy()
                .into_owned(),
            "skill".into(),
            "observe".into(),
            "--repo-root".into(),
            handoff.repository.to_string_lossy().into_owned(),
        ],
        cfg!(windows),
    );
    let mut removed = 0;
    let mut empty_events = Vec::new();
    for (event, groups) in hooks.iter_mut() {
        let groups = groups.as_array_mut().ok_or_else(invalid)?;
        let expected = serde_json::json!({"hooks":[{"type":"command","async":false,"command":command,"timeoutSec":10,"statusMessage":format!("Watcher skill: observe {event}")}]});
        let mut owned = None;
        for (index, group) in groups.iter().enumerate() {
            let handlers = group
                .get("hooks")
                .and_then(Value::as_array)
                .ok_or_else(invalid)?;
            let watcher = handlers.iter().any(|handler| {
                let status = handler["statusMessage"].as_str().unwrap_or("");
                let command = handler["command"].as_str().unwrap_or("");
                status.starts_with("Watcher skill:")
                    || status.starts_with("Skill Watcher:")
                    || command.contains("codex_hook_adapter.py")
                    || command.contains("plugins/watcher/scripts/watcher")
                    || command.contains("plugins\\watcher\\scripts\\watcher")
            });
            if watcher {
                if !super::hooks::EVENTS.contains(&event.as_str())
                    || group != &expected
                    || owned.is_some()
                {
                    return Err(changed());
                }
                owned = Some(index);
            }
        }
        if let Some(index) = owned {
            groups.remove(index);
            removed += 1;
            if groups.is_empty() {
                empty_events.push(event.clone());
            }
        }
    }
    if removed == 0 {
        return Ok(None);
    }
    for event in empty_events {
        hooks.remove(&event);
    }
    if hooks.is_empty() {
        config.as_object_mut().ok_or_else(invalid)?.remove("hooks");
    }
    let mut after = serde_json::to_vec_pretty(&config).map_err(|_| invalid())?;
    after.push(b'\n');
    Ok(Some(LegacyHookChange {
        path,
        before,
        after,
    }))
}
