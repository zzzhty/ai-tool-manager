//! Inert OMH archives: content declarations, an explicitly selected version lock,
//! and installation receipts have separate owners. No supplier path is a host path.
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use std::io::{Read, Write};
use std::time::Duration;

const CONTENT: &str = "content-manifest.json";
const LOCK: &str = "content-lock.json";
const HUB_ALGORITHM: &str = "sha256-omh-content-v1";
const MAX_ARCHIVE: usize = 192 * 1024 * 1024;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ContentManifest {
    schema_version: u32,
    product: String,
    release_version: String,
    packages: Vec<Package>,
    runtime_groups: Vec<Value>,
    runtime_bindings: BTreeMap<String, String>,
    historical_identities: BTreeMap<String, String>,
    compositions: BTreeMap<String, Vec<String>>,
}

/// A reviewed lock is selected locally. Neither a fetched manifest nor an archive
/// may replace it or choose another URL, revision, composition or destination.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ContentLock {
    pub schema_version: u32,
    pub product: String,
    pub algorithm: String,
    pub repository: String,
    pub revision: String,
    pub artifact_url: String,
    pub release_version: String,
    pub composition: String,
    pub manifest_sha256: String,
    pub archive_sha256: String,
    pub content_identity: String,
    files: Vec<FileLock>,
    directories: Vec<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Archive {
    schema_version: u32,
    product: String,
    manifest: ContentManifest,
    files: Vec<ArchiveFile>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ArchiveFile {
    path: String,
    base64: String,
}

fn bytes<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    // Value maps sort keys, retaining the existing cross-platform canonical JSON rule.
    serde_json::to_vec(&serde_json::to_value(value).map_err(|_| invalid())?).map_err(|_| invalid())
}
fn https(url: &str) -> Result<reqwest::Url> {
    let parsed = reqwest::Url::parse(url).map_err(|_| invalid())?;
    if parsed.scheme() != "https"
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.fragment().is_some()
        || parsed.port().is_some()
    {
        return Err(invalid());
    }
    Ok(parsed)
}
fn origin(lock: &ContentLock) -> Result<()> {
    let repo = https(&lock.repository)?;
    let parts: Vec<_> = repo.path().trim_matches('/').split('/').collect();
    if repo.host_str() != Some("github.com")
        || repo.query().is_some()
        || parts.len() != 2
        || parts.iter().any(|s| !is_name(s))
        || lock.repository.ends_with('/')
        || lock.revision.len() != 40
        || !lock
            .revision
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err(invalid());
    }
    let artifact = https(&lock.artifact_url)?;
    if artifact.query().is_some()
        || !lock
            .artifact_url
            .starts_with(&format!("{}/releases/download/", lock.repository))
        || !lock.artifact_url.ends_with(".omh")
    {
        return Err(invalid());
    }
    Ok(())
}
fn identity(lock: &ContentLock) -> Result<String> {
    let mut value = serde_json::to_value(lock).map_err(|_| invalid())?;
    let map = value.as_object_mut().ok_or_else(invalid)?;
    map.remove("contentIdentity");
    map.remove("archiveSha256");
    let mut digest = Sha256::new();
    digest.update(format!("{HUB_ALGORITHM}\0").as_bytes());
    record(&mut digest, &bytes(&value)?);
    Ok(format!("{:x}", digest.finalize()))
}
fn lock_valid(lock: &ContentLock) -> Result<()> {
    origin(lock)?;
    if lock.schema_version != 1
        || lock.product != "omh-content-lock"
        || lock.algorithm != HUB_ALGORITHM
        || !is_name(&lock.composition)
        || !is_digest(&lock.archive_sha256)
        || !is_digest(&lock.manifest_sha256)
        || !is_digest(&lock.content_identity)
        || identity(lock)? != lock.content_identity
        || lock.files.len() > MAX_FILES
        || lock.directories.len() > MAX_FILES
    {
        return Err(invalid());
    }
    Ok(())
}
pub fn read_lock(path: &Path) -> Result<ContentLock> {
    let lock: ContentLock = serde_json::from_slice(&read_file(path)?).map_err(|_| invalid())?;
    lock_valid(&lock)?;
    Ok(lock)
}
fn manifest(content: &ContentManifest, lock: &ContentLock) -> Result<Manifest> {
    if content.schema_version != 1
        || content.product != "omh-content"
        || content.release_version != lock.release_version
        || hash(&bytes(content)?) != lock.manifest_sha256
        || content
            .runtime_bindings
            .keys()
            .any(|key| key.starts_with("hook:"))
        || content.compositions.is_empty()
    {
        return Err(invalid());
    }
    let names: BTreeSet<_> = content.packages.iter().map(|p| p.name.as_str()).collect();
    for (name, selected) in &content.compositions {
        let unique: BTreeSet<_> = selected.iter().map(String::as_str).collect();
        if !is_name(name)
            || unique.len() != selected.len()
            || unique.is_empty()
            || !unique.is_subset(&names)
        {
            return Err(invalid());
        }
    }
    // An archive contains exactly one complete composition; native plugin identity
    // never describes a partial package. Default exports currently contain all 30 skills.
    let selected = content
        .compositions
        .get(&lock.composition)
        .ok_or_else(invalid)?;
    if selected.iter().map(String::as_str).collect::<BTreeSet<_>>() != names {
        return Err(Error::new(
            "HARNESS_COMPOSITION",
            "该导出包未包含所选组合的精确完整包集合。",
        ));
    }
    let combined = Manifest {
        schema_version: 1,
        product: "atm-harness-distribution".into(),
        algorithm: ALGORITHM.into(),
        release_version: content.release_version.clone(),
        packages: content.packages.clone(),
        files: lock.files.clone(),
        directories: lock.directories.clone(),
        runtime_groups: content.runtime_groups.clone(),
        runtime_bindings: content.runtime_bindings.clone(),
        historical_identities: content.historical_identities.clone(),
    };
    let mut combined = parse_manifest(&bytes(&combined)?)?;
    combined.schema_version = 2;
    combined.product = "omh-content".into();
    combined.algorithm = HUB_ALGORITHM.into();
    Ok(combined)
}
fn no_implicit_execution(bundle: &Bundle) -> Result<()> {
    for (path, data) in &bundle.files {
        let parts: Vec<_> = path.split('/').collect();
        if path.ends_with("/codex_hook_adapter.py")
            || path.split('/').any(|p| p == "hooks")
            || path.ends_with("/hooks.json")
            || path.ends_with("/.mcp.json")
            || path.ends_with("/mcp.json")
            || (parts.first() == Some(&"plugins")
                && parts.get(2).is_some_and(|p| {
                    ["commands", "agents", ".claude-plugin", ".cursor-plugin"].contains(p)
                }))
        {
            return Err(invalid());
        }
        if path.ends_with("/.codex-plugin/plugin.json") {
            let value: Value = serde_json::from_slice(data).map_err(|_| invalid())?;
            let allowed = [
                "name",
                "version",
                "description",
                "author",
                "skills",
                "interface",
                "homepage",
                "repository",
                "license",
                "keywords",
            ];
            if value
                .as_object()
                .is_none_or(|m| m.keys().any(|k| !allowed.contains(&k.as_str())))
                || value["skills"] != "./skills/"
            {
                return Err(invalid());
            }
        }
    }
    Ok(())
}
fn verified(root: &Path, content: &ContentManifest, lock: &ContentLock) -> Result<Bundle> {
    lock_valid(lock)?;
    let combined = manifest(content, lock)?;
    let metadata = BTreeMap::from([
        (CONTENT.into(), bytes(content)?),
        (LOCK.into(), bytes(lock)?),
    ]);
    let bundle = verify_bundle(
        root,
        combined,
        metadata,
        Some(lock.content_identity.clone()),
    )?;
    no_implicit_execution(&bundle)?;
    Ok(bundle)
}
pub(super) fn load(root: &Path) -> Result<Bundle> {
    let content: ContentManifest =
        serde_json::from_slice(&read_file(&root.join(CONTENT))?).map_err(|_| invalid())?;
    let bundle = verified(root, &content, &read_lock(&root.join(LOCK))?)?;
    let mut permitted: BTreeSet<_> = bundle.files.keys().cloned().collect();
    let catalog = root.join("canonical-catalog.json");
    if catalog.exists() {
        if read_file(&catalog)?
            != serde_json::to_vec_pretty(&bundle.catalog).map_err(|_| invalid())?
        {
            return Err(invalid());
        }
        permitted.insert("canonical-catalog.json".into());
    }
    let mut dirs = BTreeSet::new();
    for path in &permitted {
        let mut parent = Path::new(path).parent();
        while let Some(p) = parent.filter(|p| !p.as_os_str().is_empty()) {
            dirs.insert(p.to_string_lossy().replace('\\', "/"));
            parent = p.parent();
        }
    }
    for path in bundle.manifest["directories"]
        .as_array()
        .into_iter()
        .flatten()
    {
        dirs.insert(path.as_str().ok_or_else(invalid)?.to_owned());
    }
    check_cache_tree(root, root, &permitted, &dirs, 0)?;
    Ok(bundle)
}

fn check_cache_tree(
    root: &Path,
    dir: &Path,
    files: &BTreeSet<String>,
    dirs: &BTreeSet<String>,
    depth: usize,
) -> Result<()> {
    if depth > 32 {
        return Err(invalid());
    }
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        let metadata = fs::symlink_metadata(&path)?;
        if metadata.file_type().is_symlink() || reparse(&metadata) {
            return Err(invalid());
        }
        let name = path
            .file_name()
            .and_then(|s| s.to_str())
            .ok_or_else(invalid)?;
        // Only artifact directories are transient; bytecode beside scripts is
        // an importable file and may not appear outside the locked inventory.
        if matches!(
            name,
            "__pycache__" | ".pytest_cache" | ".mypy_cache" | ".ruff_cache"
        ) {
            continue;
        }
        let relative = path
            .strip_prefix(root)
            .map_err(|_| invalid())?
            .to_str()
            .ok_or_else(invalid)?
            .replace('\\', "/");
        if metadata.is_dir() {
            if !dirs.contains(&relative) {
                return Err(invalid());
            }
            check_cache_tree(root, &path, files, dirs, depth + 1)?;
        } else if !metadata.is_file() || !files.contains(&relative) {
            return Err(invalid());
        }
    }
    Ok(())
}

/// Export a reviewed authoring checkout. This does not mutate source or Home and
/// uses the same Rust file/package/catalog validation as import and installation.
pub fn export(
    root: &Path,
    output: &Path,
    repository: &str,
    revision: &str,
    artifact_url: &str,
    composition: &str,
) -> Result<Value> {
    check_path(root, false)?;
    let content: ContentManifest =
        serde_json::from_slice(&read_file(&root.join(CONTENT))?).map_err(|_| invalid())?;
    let mut lock = ContentLock {
        schema_version: 1,
        product: "omh-content-lock".into(),
        algorithm: HUB_ALGORITHM.into(),
        repository: repository.into(),
        revision: revision.into(),
        artifact_url: artifact_url.into(),
        release_version: content.release_version.clone(),
        composition: composition.into(),
        manifest_sha256: hash(&bytes(&content)?),
        archive_sha256: "0".repeat(64),
        content_identity: String::new(),
        files: Vec::new(),
        directories: Vec::new(),
    };
    origin(&lock)?;
    let combined = manifest(&content, &lock)?;
    let mut paths: BTreeSet<String> = [
        "VERSION",
        "LICENSE",
        "agents/global-instructions.md",
        "agents/operating-principles.md",
        ".agents/plugins/marketplace.json",
        ".agents/plugins/install-manifest.json",
        ".agents/plugins/distribution-identity.json",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect();
    let mut directories = BTreeSet::new();
    for package in &combined.packages {
        inventory(
            root,
            &root.join(&package.path),
            &combined,
            &mut paths,
            &mut directories,
        )?;
    }
    for group in &combined.runtime_groups {
        let path = root.join("runtimes").join(field(group, "id")?);
        if path.exists() {
            inventory(root, &path, &combined, &mut paths, &mut directories)?;
        }
    }
    let mut archive_files = Vec::new();
    for path in paths {
        let data = read_file(&root.join(&path))?;
        lock.files.push(FileLock {
            path: path.clone(),
            sha256: hash(&data),
        });
        archive_files.push(ArchiveFile {
            path,
            base64: STANDARD.encode(data),
        });
    }
    lock.directories = directories.into_iter().collect();
    lock.content_identity = identity(&lock)?;
    let archive = Archive {
        schema_version: 1,
        product: "omh-content-archive".into(),
        manifest: content.clone(),
        files: archive_files,
    };
    let archive_bytes = bytes(&archive)?;
    if archive_bytes.len() > MAX_ARCHIVE {
        return Err(invalid());
    }
    lock.archive_sha256 = hash(&archive_bytes);
    verified(root, &content, &lock)?;
    let lock_path = output.with_extension("lock.json");
    for path in [output, lock_path.as_path()] {
        crate::distribution::transaction::safe_path(path)?;
        if fs::symlink_metadata(path).is_ok() {
            return Err(crate::distribution::transaction::conflict());
        }
    }
    write_new(output, &archive_bytes)?;
    write_new(&lock_path, &bytes(&lock)?)?;
    Ok(
        json!({"archive":output,"lock":lock_path,"contentIdentity":lock.content_identity,"archiveSha256":lock.archive_sha256,"releaseVersion":lock.release_version}),
    )
}
fn write_new(path: &Path, data: &[u8]) -> Result<()> {
    crate::distribution::transaction::safe_path(path)?;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)?;
    file.write_all(data)?;
    file.sync_all()?;
    Ok(())
}

fn existing(output: &Path, lock: &ContentLock) -> Result<Option<Bundle>> {
    crate::distribution::transaction::safe_path(&output.join(LOCK))?;
    match fs::symlink_metadata(output) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
        Ok(_) => {
            let bundle = super::load(output)?;
            if bundle.identity != lock.content_identity {
                return Err(crate::distribution::transaction::conflict());
            }
            Ok(Some(bundle))
        }
    }
}
fn decode_archive(
    data: &[u8],
    lock: &ContentLock,
) -> Result<(ContentManifest, BTreeMap<String, Vec<u8>>)> {
    lock_valid(lock)?;
    if data.len() > MAX_ARCHIVE || hash(data) != lock.archive_sha256 {
        return Err(invalid());
    }
    let archive: Archive = serde_json::from_slice(data).map_err(|_| invalid())?;
    if archive.schema_version != 1
        || archive.product != "omh-content-archive"
        || archive.files.len() > MAX_FILES
    {
        return Err(invalid());
    }
    let combined = manifest(&archive.manifest, lock)?;
    let expected: BTreeMap<_, _> = lock
        .files
        .iter()
        .map(|f| (f.path.as_str(), f.sha256.as_str()))
        .collect();
    if expected.len() != lock.files.len() || archive.files.len() != expected.len() {
        return Err(invalid());
    }
    let mut files = BTreeMap::new();
    let mut total = 0usize;
    for file in archive.files {
        portable(&file.path)?;
        if !allowed(&file.path, &combined) || file.base64.len() > MAX_FILE_BYTES as usize * 2 {
            return Err(invalid());
        }
        let decoded = STANDARD.decode(file.base64).map_err(|_| invalid())?;
        total = total.checked_add(decoded.len()).ok_or_else(invalid)?;
        if decoded.len() > MAX_FILE_BYTES as usize
            || total > MAX_BUNDLE_BYTES
            || expected.get(file.path.as_str()).copied() != Some(hash(&decoded).as_str())
            || files.insert(file.path, decoded).is_some()
        {
            return Err(invalid());
        }
    }
    // Folded names include ancestors, so case-colliding directories and file/dir
    // overlap fail before any source-selected leaf is materialized.
    let mut paths = BTreeMap::new();
    for path in files.keys().chain(lock.directories.iter()) {
        portable(path)?;
        if !allowed(&format!("{path}/_directory_"), &combined) && !allowed(path, &combined) {
            return Err(invalid());
        }
        let mut prefix = String::new();
        let parts: Vec<_> = path.split('/').collect();
        for (i, part) in parts.iter().enumerate() {
            if !prefix.is_empty() {
                prefix.push('/');
            }
            prefix.push_str(part);
            if i + 1 < parts.len() && files.contains_key(&prefix) {
                return Err(invalid());
            }
            if paths
                .insert(prefix.to_lowercase(), prefix.clone())
                .is_some_and(|old| old != prefix)
            {
                return Err(invalid());
            }
        }
    }
    if lock.directories.iter().any(|p| files.contains_key(p)) {
        return Err(invalid());
    }
    Ok((archive.manifest, files))
}
fn import_bytes(data: &[u8], lock: &ContentLock, output: &Path) -> Result<Bundle> {
    let (content, files) = decode_archive(data, lock)?;
    if let Some(bundle) = existing(output, lock)? {
        return Ok(bundle);
    }
    let parent = output.parent().ok_or_else(invalid)?;
    crate::distribution::transaction::safe_path(&output.join(LOCK))?;
    fs::create_dir_all(parent)?;
    let stage = parent.join(format!(".omh-import-{}", uuid::Uuid::new_v4()));
    fs::create_dir(&stage)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&stage, fs::Permissions::from_mode(0o700))?;
    }
    let result = (|| {
        for directory in &lock.directories {
            fs::create_dir_all(stage.join(directory))?;
        }
        for (path, data) in files {
            let path = stage.join(path);
            fs::create_dir_all(path.parent().ok_or_else(invalid)?)?;
            write_new(&path, &data)?;
        }
        write_new(&stage.join(CONTENT), &bytes(&content)?)?;
        write_new(&stage.join(LOCK), &bytes(lock)?)?;
        let bundle = super::load(&stage)?;
        let catalog = serde_json::to_vec_pretty(&bundle.catalog).map_err(|_| invalid())?;
        write_new(&stage.join("canonical-catalog.json"), &catalog)?;
        // Destination must remain absent. A competing caller/user directory is
        // never replaced; use the same exclusive native rename as journal stages.
        crate::distribution::transaction::rename_exclusive(&stage, output)?;
        Ok(bundle)
    })();
    if result.is_err() && stage.exists() {
        // Only this newly-created private import stage is disposable. The
        // destination and any pre-existing cache are never cleanup candidates.
        let _ = fs::remove_dir_all(&stage);
    }
    result
}

/// Import a locally selected archive into an explicit inactive payload directory.
/// Does not update receipts, invoke Python/client commands, or enable any hooks.
pub fn import_archive(archive: &Path, lock: &ContentLock, output: &Path) -> Result<Bundle> {
    let size = check_path(archive, true)?.len();
    if size > MAX_ARCHIVE as u64 {
        return Err(invalid());
    }
    let data = fs::read(archive)?;
    import_bytes(&data, lock, output)
}

/// Fetch only the URL and digest in a locally reviewed lock. A complete cache is
/// usable offline; a bad cache is reported instead of silently repaired.
pub fn fetch(lock: &ContentLock, output: &Path) -> Result<Bundle> {
    lock_valid(lock)?;
    if let Some(bundle) = existing(output, lock)? {
        return Ok(bundle);
    }
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(90))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            let url = attempt.url();
            if attempt.previous().len() < 5
                && url.scheme() == "https"
                && matches!(
                    url.host_str(),
                    Some(
                        "github.com"
                            | "release-assets.githubusercontent.com"
                            | "objects.githubusercontent.com"
                    )
                )
                && url.username().is_empty()
                && url.password().is_none()
            {
                attempt.follow()
            } else {
                attempt.stop()
            }
        }))
        .build()
        .map_err(|_| Error::new("HARNESS_FETCH", "无法初始化内容下载。"))?;
    let response = client
        .get(&lock.artifact_url)
        .header(reqwest::header::USER_AGENT, "atm-content-import/1")
        .send()
        .map_err(|_| Error::new("HARNESS_FETCH", "内容下载失败；未修改缓存或安装记录。"))?;
    if !response.status().is_success()
        || response
            .content_length()
            .is_some_and(|n| n > MAX_ARCHIVE as u64)
    {
        return Err(Error::new(
            "HARNESS_FETCH",
            "内容下载返回不支持的状态或大小。",
        ));
    }
    let mut data = Vec::new();
    response
        .take(MAX_ARCHIVE as u64 + 1)
        .read_to_end(&mut data)?;
    import_bytes(&data, lock, output)
}
