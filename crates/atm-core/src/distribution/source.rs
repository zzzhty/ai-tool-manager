//! Verified, explicitly inventoried content. No executable installer or repository scan
//! is shipped to clients; only the selected payload and a Rust-built catalog travel.
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};

pub mod hub;

const MANIFEST: &str = "distribution-manifest.json";
const ALGORITHM: &str = "sha256-atm-distribution-v1";
const MAX_FILE_BYTES: u64 = 16 * 1024 * 1024;
const MAX_BUNDLE_BYTES: usize = 128 * 1024 * 1024;
const MAX_FILES: usize = 5000;

#[derive(Debug, Clone)]
pub struct Bundle {
    pub identity: String,
    pub release: String,
    pub files: BTreeMap<String, Vec<u8>>,
    pub catalog: Value,
    pub manifest: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Manifest {
    schema_version: u32,
    product: String,
    algorithm: String,
    release_version: String,
    packages: Vec<Package>,
    files: Vec<FileLock>,
    #[serde(default)]
    directories: Vec<String>,
    #[serde(default)]
    runtime_groups: Vec<Value>,
    #[serde(default)]
    runtime_bindings: BTreeMap<String, String>,
    #[serde(default)]
    historical_identities: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Package {
    name: String,
    path: String,
    kind: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FileLock {
    path: String,
    sha256: String,
}

fn invalid() -> Error {
    Error::new(
        "HARNESS_SOURCE_INVALID",
        "分发来源、版本锁或内容校验失败；请使用完整且匹配版本的 ATM 内容包。",
    )
}
fn missing() -> Error {
    Error::new("HARNESS_SOURCE_MISSING", "未找到 Rust harness 内容包；请保留随程序的 harness 目录，或设置绝对路径 ATM_ENGINE_SOURCE。")
}
fn is_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
        && s.as_bytes()[0].is_ascii_alphanumeric()
}
fn is_digest(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn portable(path: &str) -> Result<()> {
    if path.is_empty()
        || path.contains('\\')
        || path.contains(':')
        || path.chars().any(char::is_control)
        || Path::new(path).is_absolute()
        || path.split('/').any(|part| {
            part.is_empty()
                || part == "."
                || part == ".."
                || part.ends_with(['.', ' '])
                || part.contains(['<', '>', '"', '|', '?', '*'])
                || matches!(
                    part.split('.')
                        .next()
                        .unwrap_or("")
                        .to_ascii_uppercase()
                        .as_str(),
                    "CON"
                        | "PRN"
                        | "AUX"
                        | "NUL"
                        | "COM1"
                        | "COM2"
                        | "COM3"
                        | "COM4"
                        | "COM5"
                        | "COM6"
                        | "COM7"
                        | "COM8"
                        | "COM9"
                        | "LPT1"
                        | "LPT2"
                        | "LPT3"
                        | "LPT4"
                        | "LPT5"
                        | "LPT6"
                        | "LPT7"
                        | "LPT8"
                        | "LPT9"
                )
        })
    {
        return Err(invalid());
    }
    Ok(())
}
fn reparse(meta: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        meta.file_attributes() & 0x400 != 0
    }
    #[cfg(not(windows))]
    {
        let _ = meta;
        false
    }
}
fn check_path(path: &Path, file: bool) -> Result<fs::Metadata> {
    if !path.is_absolute() {
        return Err(invalid());
    }
    for ancestor in path.ancestors() {
        let meta = fs::symlink_metadata(ancestor).map_err(|_| invalid())?;
        if meta.file_type().is_symlink() || reparse(&meta) {
            return Err(invalid());
        }
    }
    let meta = fs::symlink_metadata(path).map_err(|_| invalid())?;
    if (file && !meta.is_file()) || (!file && !meta.is_dir()) {
        return Err(invalid());
    }
    Ok(meta)
}
fn canonical_bytes(bytes: Vec<u8>) -> Vec<u8> {
    if !bytes.contains(&0) && std::str::from_utf8(&bytes).is_ok() {
        let mut out = Vec::with_capacity(bytes.len());
        let mut index = 0;
        while index < bytes.len() {
            if bytes[index] == b'\r' && bytes.get(index + 1) == Some(&b'\n') {
                index += 1;
            }
            out.push(bytes[index]);
            index += 1;
        }
        out
    } else {
        bytes
    }
}
fn read_file(path: &Path) -> Result<Vec<u8>> {
    let before = check_path(path, true)?;
    if before.len() > MAX_FILE_BYTES {
        return Err(invalid());
    }
    let bytes = fs::read(path).map_err(|_| invalid())?;
    let after = check_path(path, true)?;
    if before.len() != after.len()
        || before.modified().ok() != after.modified().ok()
        || bytes.len() as u64 != after.len()
    {
        return Err(invalid());
    }
    Ok(canonical_bytes(bytes))
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value.get(key).and_then(Value::as_str).ok_or_else(invalid)
}
fn parse_manifest(bytes: &[u8]) -> Result<Manifest> {
    let manifest: Manifest = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if manifest.schema_version != 1
        || manifest.product != "atm-harness-distribution"
        || manifest.algorithm != ALGORITHM
        || manifest.release_version.is_empty()
        || manifest.release_version.len() > 128
        || manifest.files.len() > MAX_FILES
        || manifest.directories.len() > MAX_FILES
    {
        return Err(invalid());
    }
    let mut names = BTreeSet::new();
    for package in &manifest.packages {
        if !is_name(&package.name)
            || package.path != format!("plugins/{}", package.name)
            || package.kind != "skills"
            || !names.insert(package.name.clone())
        {
            return Err(invalid());
        }
    }
    if names.is_empty() {
        return Err(invalid());
    }
    let mut groups = BTreeSet::new();
    for group in &manifest.runtime_groups {
        let id = field(group, "id")?;
        if !is_name(id) || !groups.insert(id.to_owned()) {
            return Err(invalid());
        }
        let minimum = group
            .get("minimumPython")
            .and_then(Value::as_array)
            .ok_or_else(invalid)?;
        if minimum.len() != 2 || minimum.iter().any(|n| n.as_u64().is_none()) {
            return Err(invalid());
        }
        if let Some(lock) = group.get("requirementsLock").filter(|v| !v.is_null()) {
            portable(lock.as_str().ok_or_else(invalid)?)?;
        }
        if group
            .get("imports")
            .and_then(Value::as_array)
            .is_none_or(|a| a.iter().any(|v| v.as_str().is_none()))
        {
            return Err(invalid());
        }
    }
    if manifest
        .runtime_bindings
        .values()
        .any(|id| !groups.contains(id))
    {
        return Err(invalid());
    }
    Ok(manifest)
}
fn allowed(path: &str, manifest: &Manifest) -> bool {
    if manifest.schema_version == 2 && path.starts_with(".agents/harnesses/") {
        return false;
    }
    if manifest.schema_version == 2 && path == "LICENSE" {
        return true;
    }
    if matches!(
        path,
        "VERSION"
            | "agents/global-instructions.md"
            | "agents/operating-principles.md"
            | ".agents/harnesses/registry.json"
            | ".agents/harnesses/registry.schema.json"
            | ".agents/plugins/marketplace.json"
            | ".agents/plugins/install-manifest.json"
            | ".agents/plugins/distribution-identity.json"
    ) {
        return true;
    }
    let parts: Vec<_> = path.split('/').collect();
    if parts.iter().any(|p| {
        matches!(
            *p,
            "__pycache__"
                | ".pytest_cache"
                | ".mypy_cache"
                | ".ruff_cache"
                | ".git"
                | ".venv"
                | "node_modules"
        )
    }) || path.ends_with(".pyc")
        || path.ends_with(".pyo")
        || parts.last() == Some(&".DS_Store")
    {
        return false;
    }
    if parts.len() >= 3
        && parts[0] == "plugins"
        && manifest.packages.iter().any(|p| p.name == parts[1])
    {
        return true;
    }
    if parts.len() >= 3
        && parts[0] == "runtimes"
        && manifest.runtime_groups.iter().any(|v| v["id"] == parts[1])
    {
        return matches!(parts[2], "scripts" | "config")
            || (parts.len() == 3
                && (matches!(
                    parts[2],
                    "README.md"
                        | "runtime.json"
                        | "requirements.lock"
                        | "requirements.txt"
                        | "LICENSE"
                ) || (parts[2].starts_with("requirements-") && parts[2].ends_with(".lock"))));
    }
    false
}

/// Resolve an explicitly selected package, then an adjacent packaged payload.
/// Only debug builds may use the development checkout; release never uses it.
pub fn locate() -> Result<PathBuf> {
    if let Some(raw) = std::env::var_os("ATM_ENGINE_SOURCE").filter(|s| !s.is_empty()) {
        let root = PathBuf::from(raw);
        check_path(&root, false)?;
        if !has_payload(&root) {
            return Err(missing());
        }
        return Ok(root);
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            let root = parent.join("harness");
            if has_payload(&root) {
                check_path(&root, false)?;
                return Ok(root);
            }
        }
    }
    #[cfg(debug_assertions)]
    {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../harness");
        let root = root.canonicalize().map_err(|_| missing())?;
        if has_payload(&root) {
            check_path(&root, false)?;
            return Ok(root);
        }
    }
    Err(missing())
}

fn has_payload(root: &Path) -> bool {
    root.join(MANIFEST).is_file()
        || (root.join("content-manifest.json").is_file()
            && root.join("content-lock.json").is_file())
}

/// Verify every locked byte before producing a usable payload or catalog. The
/// caller's cache identity pins this package on later operations and offline use.
pub fn load(root: &Path) -> Result<Bundle> {
    check_path(root, false)?;
    if root.join("content-lock.json").exists() {
        if root.join(MANIFEST).exists() {
            return Err(invalid());
        }
        return hub::load(root);
    }
    let manifest_bytes = read_file(&root.join(MANIFEST))?;
    load_manifest(root, manifest_bytes)
}
fn load_manifest(root: &Path, manifest_bytes: Vec<u8>) -> Result<Bundle> {
    let manifest = parse_manifest(&manifest_bytes)?;
    verify_bundle(
        root,
        manifest,
        BTreeMap::from([(MANIFEST.to_owned(), manifest_bytes)]),
        None,
    )
}
fn verify_bundle(
    root: &Path,
    manifest: Manifest,
    metadata: BTreeMap<String, Vec<u8>>,
    hub_identity: Option<String>,
) -> Result<Bundle> {
    let mut files = BTreeMap::new();
    let mut folded = BTreeMap::new();
    let mut total = 0usize;
    let mut declared_dirs = BTreeSet::new();
    for directory in &manifest.directories {
        portable(directory)?;
        if !allowed(&format!("{directory}/_directory_"), &manifest)
            || !declared_dirs.insert(directory)
        {
            return Err(invalid());
        }
        check_path(&root.join(directory), false)?;
        let previous = folded.insert(directory.to_lowercase(), directory.clone());
        if previous.is_some_and(|previous| previous != *directory) {
            return Err(invalid());
        }
    }
    for item in &manifest.files {
        portable(&item.path)?;
        if !allowed(&item.path, &manifest) || !is_digest(&item.sha256) {
            return Err(invalid());
        }
        // Include ancestor names: A/x and a/y are colliding directories too.
        let mut prefix = String::new();
        for part in item.path.split('/') {
            if !prefix.is_empty() {
                prefix.push('/');
            }
            prefix.push_str(part);
            let old = folded.insert(prefix.to_lowercase(), prefix.clone());
            if old.is_some_and(|old| old != prefix) {
                return Err(invalid());
            }
        }
        let bytes = read_file(&root.join(&item.path))?;
        total = total.checked_add(bytes.len()).ok_or_else(invalid)?;
        if total > MAX_BUNDLE_BYTES
            || hash(&bytes) != item.sha256
            || files.insert(item.path.clone(), bytes).is_some()
        {
            return Err(invalid());
        }
    }
    for package in &manifest.packages {
        let mut actual_files = BTreeSet::new();
        let mut actual_dirs = BTreeSet::new();
        inventory(
            root,
            &root.join(&package.path),
            &manifest,
            &mut actual_files,
            &mut actual_dirs,
        )?;
        let prefix = format!("{}/", package.path);
        let expected_files = files
            .keys()
            .filter(|path| path.starts_with(&prefix))
            .cloned()
            .collect();
        let expected_dirs = manifest
            .directories
            .iter()
            .filter(|path| path.starts_with(&prefix))
            .cloned()
            .collect();
        if actual_files != expected_files || actual_dirs != expected_dirs {
            return Err(invalid());
        }
    }
    // A cache may not add importable runtime files outside the locked
    // inventory: an extra json.py could otherwise shadow the standard library.
    for group in &manifest.runtime_groups {
        let relative = format!("runtimes/{}", field(group, "id")?);
        let runtime = root.join(&relative);
        if runtime.exists() {
            let mut actual_files = BTreeSet::new();
            let mut actual_dirs = BTreeSet::new();
            inventory(
                root,
                &runtime,
                &manifest,
                &mut actual_files,
                &mut actual_dirs,
            )?;
            let prefix = format!("{relative}/");
            let expected_files = files
                .keys()
                .filter(|path| path.starts_with(&prefix))
                .cloned()
                .collect();
            let expected_dirs = manifest
                .directories
                .iter()
                .filter(|path| path.starts_with(&prefix))
                .cloned()
                .collect();
            if actual_files != expected_files || actual_dirs != expected_dirs {
                return Err(invalid());
            }
        }
    }
    for required in [
        "VERSION",
        "agents/global-instructions.md",
        "agents/operating-principles.md",
        ".agents/plugins/marketplace.json",
        ".agents/plugins/install-manifest.json",
        ".agents/plugins/distribution-identity.json",
    ] {
        if !files.contains_key(required) {
            return Err(invalid());
        }
    }
    if manifest.schema_version == 1 && !files.contains_key(".agents/harnesses/registry.json") {
        return Err(invalid());
    }
    if std::str::from_utf8(&files["VERSION"])
        .map_err(|_| invalid())?
        .trim()
        != manifest.release_version
    {
        return Err(invalid());
    }
    validate_packages(&manifest, &files)?;
    for group in &manifest.runtime_groups {
        if let Some(lock) = group.get("requirementsLock").and_then(Value::as_str) {
            if !files.contains_key(lock) {
                return Err(invalid());
            }
        }
    }
    for group in &manifest.runtime_groups {
        let spec: super::runtime::RuntimeSpec =
            serde_json::from_value(group.clone()).map_err(|_| invalid())?;
        super::runtime::validate_spec_lock(&spec, root)?;
    }
    let manifest_value = serde_json::to_value(&manifest).map_err(|_| invalid())?;
    let canonical_manifest = serde_json::to_vec(&manifest_value).map_err(|_| invalid())?;
    let mut digest = Sha256::new();
    digest.update(format!("{ALGORITHM}\0").as_bytes());
    record(&mut digest, &canonical_manifest);
    for (path, bytes) in &files {
        record(&mut digest, path.as_bytes());
        record(&mut digest, bytes);
    }
    let identity = hub_identity.unwrap_or_else(|| format!("{:x}", digest.finalize()));
    let catalog = catalog(&manifest, &files, &identity)?;
    files.extend(metadata);
    Ok(Bundle {
        identity,
        release: manifest.release_version.clone(),
        files,
        catalog,
        manifest: manifest_value,
    })
}
fn record(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_be_bytes());
    hash.update(bytes);
}
fn json_file(files: &BTreeMap<String, Vec<u8>>, path: &str) -> Result<Value> {
    serde_json::from_slice(files.get(path).ok_or_else(invalid)?).map_err(|_| invalid())
}
fn validate_packages(manifest: &Manifest, files: &BTreeMap<String, Vec<u8>>) -> Result<()> {
    let marketplace = json_file(files, ".agents/plugins/marketplace.json")?;
    if marketplace["name"] != "atm-harness" {
        return Err(invalid());
    }
    let entries = marketplace["plugins"].as_array().ok_or_else(invalid)?;
    let ledger = json_file(files, ".agents/plugins/distribution-identity.json")?;
    if ledger["schemaVersion"] != 1 || ledger["releaseVersion"] != manifest.release_version {
        return Err(invalid());
    }
    let locked = ledger["plugins"].as_array().ok_or_else(invalid)?;
    if entries.len() != manifest.packages.len() || locked.len() != manifest.packages.len() {
        return Err(invalid());
    }
    let mut names = BTreeSet::new();
    let mut expected_plugins = Vec::new();
    for package in &manifest.packages {
        let metadata = json_file(
            files,
            &format!("{}/.codex-plugin/plugin.json", package.path),
        )?;
        if metadata["name"] != package.name {
            return Err(invalid());
        }
        let version = field(&metadata, "version")?;
        let actual_digest = plugin_digest(
            &package.path,
            &manifest.release_version,
            &manifest.directories,
            files,
        )?;
        let expected_version = format!(
            "{}+codex.{}",
            manifest.release_version,
            &actual_digest[..16]
        );
        if version != expected_version {
            return Err(invalid());
        }
        expected_plugins.push(json!({"name":package.name,"versionAuthority":"release","version":expected_version,"generation":&actual_digest[..16],"contentSha256":actual_digest}));
        let pinned = locked
            .iter()
            .filter(|entry| entry["name"] == package.name)
            .collect::<Vec<_>>();
        if pinned.len() != 1
            || pinned[0]["version"] != version
            || !is_digest(field(pinned[0], "contentSha256")?)
        {
            return Err(invalid());
        }
        let generation = field(pinned[0], "generation")?;
        if generation.len() != 16
            || !field(pinned[0], "contentSha256")?.starts_with(generation)
            || !version.ends_with(&format!("+codex.{generation}"))
        {
            return Err(invalid());
        }
        let candidates = entries
            .iter()
            .filter(|entry| entry["name"] == package.name)
            .collect::<Vec<_>>();
        if candidates.len() != 1
            || candidates[0]
                .pointer("/source/source")
                .and_then(Value::as_str)
                != Some("local")
            || candidates[0]
                .pointer("/source/path")
                .and_then(Value::as_str)
                != Some(format!("./{}", package.path).as_str())
        {
            return Err(invalid());
        }
        names.insert(package.name.clone());
    }
    expected_plugins.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
    let bundle_payload = json!({"algorithm":"sha256-canonical-plugin-tree-v1","releaseVersion":manifest.release_version,"plugins":expected_plugins.iter().map(|entry| json!({"name":entry["name"],"version":entry["version"],"contentSha256":entry["contentSha256"]})).collect::<Vec<_>>()});
    let expected_ledger = json!({"schemaVersion":1,"algorithm":"sha256-canonical-plugin-tree-v1","generationLength":16,"releaseVersion":manifest.release_version,"bundleIdentity":format!("sha256:{}", hash(&serde_json::to_vec(&bundle_payload).map_err(|_|invalid())?)),"plugins":expected_plugins});
    if ledger != expected_ledger {
        return Err(invalid());
    }
    let install = json_file(files, ".agents/plugins/install-manifest.json")?;
    if install["marketplace"] != "atm-harness" || install["harness"] != "codex" {
        return Err(invalid());
    }
    let selected = install["plugins"].as_array().ok_or_else(invalid)?;
    let mut seen = BTreeSet::new();
    for entry in selected {
        let name = field(entry, "name")?;
        if !names.contains(name)
            || !seen.insert(name)
            || !entry["install"].is_boolean()
            || !entry["check"].is_boolean()
        {
            return Err(invalid());
        }
    }
    if seen.len() != names.len() {
        return Err(invalid());
    }
    Ok(())
}
fn skill_name(bytes: &[u8]) -> Result<String> {
    let text = std::str::from_utf8(bytes).map_err(|_| invalid())?;
    let mut lines = text.lines();
    if lines.next() != Some("---") {
        return Err(invalid());
    }
    let mut name = None;
    let mut closed = false;
    for line in lines {
        if line.trim_end() == "---" {
            closed = true;
            break;
        }
        if let Some(value) = line.strip_prefix("name:") {
            if name.is_some() {
                return Err(invalid());
            }
            let raw = value.trim();
            let raw = if raw.len() >= 2
                && (raw.starts_with('"') && raw.ends_with('"')
                    || raw.starts_with('\'') && raw.ends_with('\''))
            {
                &raw[1..raw.len() - 1]
            } else {
                raw
            };
            if !is_name(raw) {
                return Err(invalid());
            }
            name = Some(raw.to_owned());
        }
    }
    if !closed {
        return Err(invalid());
    }
    name.ok_or_else(invalid)
}
fn catalog(
    manifest: &Manifest,
    files: &BTreeMap<String, Vec<u8>>,
    identity: &str,
) -> Result<Value> {
    let mut skills = Vec::new();
    let mut names = BTreeSet::new();
    let mut identities = BTreeSet::new();
    let mut current_ids = BTreeSet::new();
    for (path, bytes) in files {
        let parts: Vec<_> = path.split('/').collect();
        if parts.len() != 5
            || parts[0] != "plugins"
            || parts[2] != "skills"
            || parts[4] != "SKILL.md"
        {
            continue;
        }
        let name = skill_name(bytes)?;
        if !names.insert(name.clone()) {
            return Err(invalid());
        }
        let current = format!("{}:{name}", parts[1]);
        let stable = manifest
            .historical_identities
            .get(&current)
            .unwrap_or(&current);
        if stable.split(':').count() != 2
            || stable.split(':').any(|p| !is_name(p))
            || !identities.insert(stable.clone())
        {
            return Err(invalid());
        }
        current_ids.insert(current.clone());
        let aliases = BTreeSet::from([current.clone(), stable.clone()]);
        skills.push(json!({"id":stable,"plugin":parts[1],"name":name,"directoryName":parts[3],"path":parts[..4].join("/"),"aliases":aliases}));
    }
    if skills.is_empty()
        || manifest
            .historical_identities
            .keys()
            .any(|key| !current_ids.contains(key))
    {
        return Err(invalid());
    }
    for key in manifest.runtime_bindings.keys() {
        // Read old cached manifests for receipt/recovery compatibility only.
        // New bundles omit this retired binding; the service refuses activation.
        if key != "hook:watcher" && !current_ids.contains(key) && !identities.contains(key) {
            return Err(invalid());
        }
    }
    let mut overlays = Vec::new();
    for package in &manifest.packages {
        let path = format!("{}/.codex-plugin/skill-watcher.json", package.path);
        if files.contains_key(&path) {
            let data = json_file(files, &path)?;
            let own = skills
                .iter()
                .filter(|skill| skill["plugin"] == package.name)
                .map(|skill| skill["id"].as_str().unwrap().to_owned())
                .collect();
            validate_overlay(&data, &own, &identities)?;
            overlays.push(json!({"plugin":package.name,"path":path,"data":data}));
        }
    }
    Ok(
        json!({"schemaVersion":1,"product":"atm-harness-catalog","sourceIdentity":identity,"skills":skills,"attributionOverlays":overlays}),
    )
}
fn validate_overlay(
    data: &Value,
    own: &BTreeSet<String>,
    identities: &BTreeSet<String>,
) -> Result<()> {
    if data["schema_version"] != 1 {
        return Err(invalid());
    }
    for (id, metadata) in data["skills"].as_object().ok_or_else(invalid)? {
        if !own.contains(id) || !metadata.is_object() {
            return Err(invalid());
        }
        if let Some(role) = metadata.get("role") {
            if !matches!(
                role.as_str(),
                Some("entrypoint" | "wrapper" | "discipline" | "specialized")
            ) {
                return Err(invalid());
            }
        }
        if let Some(group) = metadata.get("logical_group") {
            let group = group.as_str().ok_or_else(invalid)?;
            if group.is_empty()
                || group.split('-').any(|part| {
                    part.is_empty()
                        || !part
                            .bytes()
                            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
                })
            {
                return Err(invalid());
            }
        }
        if let Some(aliases) = metadata.get("aliases") {
            for alias in aliases.as_array().ok_or_else(invalid)? {
                if let Some(value) = alias.as_str() {
                    if value.trim().is_empty() {
                        return Err(invalid());
                    }
                } else {
                    if field(alias, "value")?.trim().is_empty() {
                        return Err(invalid());
                    }
                    if let Some(kind) = alias.get("kind") {
                        if kind.as_str().is_none_or(|value| value.trim().is_empty()) {
                            return Err(invalid());
                        }
                    }
                    if let Some(mode) = alias.get("match") {
                        if !matches!(mode.as_str(), Some("exact" | "phrase" | "token")) {
                            return Err(invalid());
                        }
                    }
                }
            }
        }
        if let Some(supporting) = metadata.get("supporting_skills") {
            if supporting.as_array().is_none_or(|a| {
                a.iter()
                    .any(|id| id.as_str().is_none_or(|id| !identities.contains(id)))
            }) {
                return Err(invalid());
            }
        }
    }
    if let Some(legacy) = data.get("legacy_names") {
        for (old, new) in legacy.as_object().ok_or_else(invalid)? {
            if old.is_empty() || new.as_str().is_none_or(|id| !identities.contains(id)) {
                return Err(invalid());
            }
        }
    }
    Ok(())
}

/// Developer/package operation: regenerate only the declared payload inventory.
/// This is never called by install, update, cache loading or recovery. It does not
/// make an untrusted package trusted; release review owns the resulting manifest.
pub fn seal(root: &Path) -> Result<()> {
    check_path(root, false)?;
    let mut manifest = parse_manifest(&read_file(&root.join(MANIFEST))?)?;
    let mut paths = BTreeSet::new();
    let mut directories = BTreeSet::new();
    for path in [
        "VERSION",
        "agents/global-instructions.md",
        "agents/operating-principles.md",
        ".agents/harnesses/registry.json",
        ".agents/harnesses/registry.schema.json",
        ".agents/plugins/marketplace.json",
        ".agents/plugins/install-manifest.json",
        ".agents/plugins/distribution-identity.json",
    ] {
        paths.insert(path.to_owned());
    }
    for package in &manifest.packages {
        inventory(
            root,
            &root.join(&package.path),
            &manifest,
            &mut paths,
            &mut directories,
        )?;
    }
    for group in &manifest.runtime_groups {
        let runtime = root.join("runtimes").join(field(group, "id")?);
        if runtime.exists() {
            inventory(root, &runtime, &manifest, &mut paths, &mut directories)?;
        }
    }
    manifest.directories = directories.into_iter().collect();
    manifest.files = paths
        .into_iter()
        .map(|path| {
            let bytes = read_file(&root.join(&path))?;
            Ok(FileLock {
                path,
                sha256: hash(&bytes),
            })
        })
        .collect::<Result<_>>()?;
    let mut bytes = serde_json::to_vec_pretty(&manifest).map_err(|_| invalid())?;
    bytes.push(b'\n');
    load_manifest(root, bytes.clone())?;
    let temporary = root.join(format!(".distribution-manifest-{}.tmp", std::process::id()));
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)?;
    if let Err(error) = file.write_all(&bytes).and_then(|()| file.sync_all()) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    drop(file);
    if let Err(error) = fs::rename(&temporary, root.join(MANIFEST)) {
        let _ = fs::remove_file(&temporary);
        return Err(error.into());
    }
    Ok(())
}
fn inventory(
    root: &Path,
    path: &Path,
    manifest: &Manifest,
    paths: &mut BTreeSet<String>,
    directories: &mut BTreeSet<String>,
) -> Result<()> {
    check_path(path, false)?;
    if paths.len() > MAX_FILES || directories.len() > MAX_FILES {
        return Err(invalid());
    }
    for entry in fs::read_dir(path)? {
        let path = entry?.path();
        let relative = path
            .strip_prefix(root)
            .map_err(|_| invalid())?
            .to_str()
            .ok_or_else(invalid)?
            .replace('\\', "/");
        portable(&relative)?;
        let meta = fs::symlink_metadata(&path)?;
        if meta.file_type().is_symlink() || reparse(&meta) {
            return Err(invalid());
        }
        if meta.is_dir() {
            let depth = relative.split('/').count();
            // Package roots need traversal to discover the explicitly allowed
            // subtrees. Canonical plugin content includes tests and documentation;
            // installer trees, runtime tests and transient caches stay outside.
            if depth <= 2 || allowed(&format!("{relative}/_inventory_"), manifest) {
                directories.insert(relative);
                inventory(root, &path, manifest, paths, directories)?;
            }
        } else if meta.is_file() {
            if allowed(&relative, manifest) {
                paths.insert(relative);
            }
        } else {
            return Err(invalid());
        }
    }
    Ok(())
}

fn plugin_digest(
    prefix: &str,
    release: &str,
    directories: &[String],
    files: &BTreeMap<String, Vec<u8>>,
) -> Result<String> {
    let prefix = format!("{prefix}/");
    let mut entries = BTreeMap::<String, (&str, Vec<u8>)>::new();
    for directory in directories {
        if let Some(relative) = directory.strip_prefix(&prefix) {
            entries.insert(relative.to_owned(), ("directory", Vec::new()));
        }
    }
    for (path, bytes) in files {
        if let Some(relative) = path.strip_prefix(&prefix) {
            let payload = if relative == ".codex-plugin/plugin.json" {
                let mut value: Value = serde_json::from_slice(bytes).map_err(|_| invalid())?;
                value["version"] = json!(format!("{release}+codex.<content-identity>"));
                let mut bytes = serde_json::to_vec(&value).map_err(|_| invalid())?;
                bytes.push(b'\n');
                bytes
            } else {
                bytes.clone()
            };
            if entries
                .insert(relative.to_owned(), ("file", payload))
                .is_some()
            {
                return Err(invalid());
            }
        }
    }
    let mut digest = Sha256::new();
    digest.update(b"sha256-canonical-plugin-tree-v1\0");
    for (path, (kind, bytes)) in entries {
        record(&mut digest, path.as_bytes());
        record(&mut digest, kind.as_bytes());
        record(&mut digest, &bytes);
    }
    Ok(format!("{:x}", digest.finalize()))
}

/// Read-only compatibility oracle for the existing canonical plugin generation
/// contract. Includes ordinary directories and complete plugin content, including
/// tests/docs, while excluding the existing transient-cache classes.
pub fn plugin_content_identity(root: &Path, package: &str, release: &str) -> Result<String> {
    if !is_name(package) {
        return Err(invalid());
    }
    let manifest = parse_manifest(&read_file(&root.join(MANIFEST))?)?;
    if !manifest.packages.iter().any(|p| p.name == package) {
        return Err(invalid());
    }
    let mut paths = BTreeSet::new();
    let mut directories = BTreeSet::new();
    let prefix = format!("plugins/{package}");
    inventory(
        root,
        &root.join(&prefix),
        &manifest,
        &mut paths,
        &mut directories,
    )?;
    let files = paths
        .into_iter()
        .map(|path| Ok((path.clone(), read_file(&root.join(path))?)))
        .collect::<Result<_>>()?;
    plugin_digest(
        &prefix,
        release,
        &directories.into_iter().collect::<Vec<_>>(),
        &files,
    )
}
