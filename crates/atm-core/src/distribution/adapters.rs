//! Pure client projections. Filesystem mutations and ownership live in the service.
//!
//! A native plugin keeps its complete package identity. Directory projections copy
//! skill files and bind the known shared-helper expression to the immutable cache.
use super::{source::Bundle, Artifact};
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Component, Path, PathBuf};
use toml_edit::{Document, Item, Table};

#[derive(Debug, Clone)]
pub struct AdapterPlan {
    pub artifacts: Vec<Artifact>,
    pub shared: Vec<SharedArtifact>,
    /// Empty leaf directories are part of native package identity as well.
    pub empty_directories: Vec<PathBuf>,
    /// Settings and absent shadow files that must still match at apply time.
    pub observed: Vec<(PathBuf, Option<Vec<u8>>)>,
}

#[derive(Debug, Clone)]
pub struct SharedArtifact {
    pub artifact: Artifact,
    pub ownership: Value,
    /// Exact bytes merged by this plan, not a later filesystem snapshot.
    pub before: Option<Vec<u8>>,
}

fn invalid() -> Error {
    Error::new("HARNESS_ADAPTER", "客户端分发元数据或配置格式无效。")
}
fn conflict() -> Error {
    Error::new(
        "HARNESS_CONFLICT",
        "目标已存在同名条目、重复插件来源或用户修改；请先处理冲突。",
    )
}
fn relative(raw: &str) -> Result<PathBuf> {
    if raw.is_empty()
        || raw.contains('\\')
        || raw.contains(':')
        || raw.chars().any(char::is_control)
        || raw.split('/').any(|part| {
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
    let path = Path::new(raw);
    if path
        .components()
        .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err(invalid());
    }
    Ok(path.to_owned())
}
fn identifier(raw: &str) -> Result<&str> {
    if raw.is_empty()
        || !raw
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_.+".contains(&c))
        || raw == "."
        || raw == ".."
    {
        return Err(invalid());
    }
    Ok(raw)
}
fn text<'a>(value: &'a Value, field: &str) -> Result<&'a str> {
    value.get(field).and_then(Value::as_str).ok_or_else(invalid)
}
fn json_file(bundle: &Bundle, path: &str) -> Result<Value> {
    serde_json::from_slice(bundle.files.get(path).ok_or_else(invalid)?).map_err(|_| invalid())
}
fn regular_bytes(path: &Path) -> Result<Option<Vec<u8>>> {
    match fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
        Ok(metadata) => {
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                if metadata.file_attributes() & 0x400 != 0 {
                    return Err(conflict());
                }
            }
            if !metadata.is_file() || metadata.file_type().is_symlink() {
                return Err(conflict());
            }
            if metadata.len() > 16 * 1024 * 1024 {
                return Err(invalid());
            }
            Ok(Some(fs::read(path)?))
        }
    }
}
fn exists(path: &Path) -> Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

/// Plan the complete distribution with no prior shared configuration ownership.
/// The service uses `plan_owned` for updates and persists `shared.ownership`.
pub fn plan(
    bundle: &Bundle,
    cache_root: &Path,
    target: &str,
    skills_root: &Path,
) -> Result<Vec<Artifact>> {
    let planned = plan_owned(bundle, cache_root, target, skills_root, &BTreeMap::new())?;
    if !planned.empty_directories.is_empty() {
        return Err(Error::new(
            "HARNESS_PLAN_DIRECTORY",
            "分发含空目录，请使用完整 application service 计划。",
        ));
    }
    Ok(planned
        .artifacts
        .into_iter()
        .chain(planned.shared.into_iter().map(|item| item.artifact))
        .collect())
}

pub fn plan_owned(
    bundle: &Bundle,
    cache_root: &Path,
    target: &str,
    skills_root: &Path,
    previous: &BTreeMap<PathBuf, Value>,
) -> Result<AdapterPlan> {
    plan_owned_selected(bundle, cache_root, target, skills_root, previous, None)
}

/// Selections use stable catalog IDs or bare catalog names. Native Codex selection
/// must contain every skill of each selected plugin to preserve package identity.
pub fn plan_owned_selected(
    bundle: &Bundle,
    cache_root: &Path,
    target: &str,
    skills_root: &Path,
    previous: &BTreeMap<PathBuf, Value>,
    selected: Option<&[String]>,
) -> Result<AdapterPlan> {
    if !cache_root.is_absolute() || !skills_root.is_absolute() {
        return Err(invalid());
    }
    let registry = json_file(bundle, ".agents/harnesses/registry.json")?;
    let harnesses = registry
        .get("harnesses")
        .and_then(Value::as_object)
        .ok_or_else(invalid)?;
    let canonical = if harnesses.contains_key(target) {
        target
    } else {
        harnesses
            .iter()
            .find(|(_, spec)| {
                spec.get("aliases")
                    .and_then(Value::as_array)
                    .is_some_and(|aliases| aliases.iter().any(|name| name.as_str() == Some(target)))
            })
            .map(|(name, _)| name.as_str())
            .ok_or_else(invalid)?
    };
    let spec = &harnesses[canonical];
    let skill_path = spec
        .get("localSkillsPath")
        .and_then(Value::as_str)
        .or_else(|| spec.pointer("/skills/relativePath").and_then(Value::as_str))
        .ok_or_else(invalid)?;
    let mut root = skills_root.to_path_buf();
    for component in relative(skill_path)?.components().rev() {
        if root.file_name() != Some(component.as_os_str()) || !root.pop() {
            return Err(invalid());
        }
    }
    let skills = bundle
        .catalog
        .get("skills")
        .and_then(Value::as_array)
        .ok_or_else(invalid)?;
    let selected_set =
        selected.map(|names| names.iter().map(String::as_str).collect::<BTreeSet<_>>());
    if selected_set.as_ref().is_some_and(|names| names.is_empty()) {
        return Err(invalid());
    }
    if let Some(names) = &selected_set {
        if names.iter().any(|name| {
            !skills.iter().any(|skill| {
                skill.get("id").and_then(Value::as_str) == Some(name)
                    || skill.get("name").and_then(Value::as_str) == Some(name)
            })
        }) {
            return Err(invalid());
        }
    }
    let chosen: Vec<_> = skills
        .iter()
        .filter(|skill| {
            selected_set.as_ref().is_none_or(|names| {
                skill
                    .get("id")
                    .and_then(Value::as_str)
                    .is_some_and(|name| names.contains(name))
                    || skill
                        .get("name")
                        .and_then(Value::as_str)
                        .is_some_and(|name| names.contains(name))
            })
        })
        .collect();
    let mut result = AdapterPlan {
        artifacts: Vec::new(),
        shared: Vec::new(),
        observed: Vec::new(),
        empty_directories: Vec::new(),
    };
    let empty_directories = empty_source_directories(bundle)?;
    match spec.pointer("/skills/driver").and_then(Value::as_str) {
        Some("directory-projection") => {
            let mut names = BTreeSet::new();
            for skill in &chosen {
                let name = identifier(text(skill, "name")?)?;
                if !names.insert(name.to_lowercase()) {
                    return Err(invalid());
                }
                let plugin = identifier(text(skill, "plugin")?)?;
                let directory = text(skill, "path")?.trim_end_matches('/');
                relative(directory)?;
                let prefix = format!("{directory}/");
                if !bundle.files.contains_key(&format!("{prefix}SKILL.md")) {
                    return Err(invalid());
                }
                for (path, bytes) in &bundle.files {
                    let Some(suffix) = path.strip_prefix(&prefix) else {
                        continue;
                    };
                    let mut bytes = bytes.clone();
                    if suffix.ends_with(".py") {
                        let original = String::from_utf8(bytes).map_err(|_| invalid())?;
                        let shared = cache_root.join("plugins").join(plugin).join("scripts");
                        let expression = format!(
                            "Path({})",
                            serde_json::to_string(shared.to_str().ok_or_else(invalid)?)
                                .map_err(|_| invalid())?
                        );
                        bytes = original
                            .replace(
                                "Path(__file__).resolve().parents[3] / \"scripts\"",
                                &expression,
                            )
                            .into_bytes();
                    }
                    result.artifacts.push(Artifact {
                        path: skills_root.join(name).join(relative(suffix)?),
                        bytes,
                    });
                }
                for directory in &empty_directories {
                    if let Some(suffix) = directory.strip_prefix(&prefix) {
                        result
                            .empty_directories
                            .push(skills_root.join(name).join(relative(suffix)?));
                    }
                }
            }
        }
        Some("codex-marketplace") => {
            let plugins: BTreeSet<_> = chosen
                .iter()
                .map(|skill| text(skill, "plugin"))
                .collect::<Result<_>>()?;
            if skills.iter().any(|skill| {
                skill
                    .get("plugin")
                    .and_then(Value::as_str)
                    .is_some_and(|plugin| plugins.contains(plugin))
                    && !chosen.contains(&skill)
            }) {
                return Err(Error::new(
                    "HARNESS_SELECTION",
                    "Codex 必须选择完整插件，不能以同一版本身份安装部分技能。",
                ));
            }
            let marketplace_path = text(&spec["skills"], "marketplacePath")?;
            let marketplace = json_file(bundle, marketplace_path)?;
            let marketplace_name = identifier(text(&marketplace, "name")?)?;
            let mut desired = Vec::new();
            let mut source_table = Table::new();
            source_table["source_type"] = toml_edit::value("local");
            source_table["source"] = toml_edit::value(cache_root.to_str().ok_or_else(invalid)?);
            desired.push((
                "marketplaces".to_owned(),
                marketplace_name.to_owned(),
                Item::Table(source_table),
            ));
            for plugin in &plugins {
                identifier(plugin)?;
                let manifest = json_file(
                    bundle,
                    &format!("plugins/{plugin}/.codex-plugin/plugin.json"),
                )?;
                if text(&manifest, "name")? != *plugin {
                    return Err(invalid());
                }
                let version = identifier(text(&manifest, "version")?)?;
                let prefix = format!("plugins/{plugin}/");
                let destination = root
                    .join("plugins/cache")
                    .join(marketplace_name)
                    .join(plugin)
                    .join(version);
                for (path, bytes) in &bundle.files {
                    if let Some(suffix) = path.strip_prefix(&prefix) {
                        result.artifacts.push(Artifact {
                            path: destination.join(relative(suffix)?),
                            bytes: bytes.clone(),
                        });
                    }
                }
                for directory in &empty_directories {
                    if let Some(suffix) = directory.strip_prefix(&prefix) {
                        result
                            .empty_directories
                            .push(destination.join(relative(suffix)?));
                    }
                }
                let mut enabled = Table::new();
                enabled["enabled"] = toml_edit::value(true);
                desired.push((
                    "plugins".to_owned(),
                    format!("{plugin}@{marketplace_name}"),
                    Item::Table(enabled),
                ));
            }
            let config_path = root.join("config.toml");
            let current = regular_bytes(&config_path)?;
            let mut known_names: BTreeSet<String> = skills
                .iter()
                .filter_map(|s| s.get("plugin").and_then(Value::as_str))
                .map(str::to_owned)
                .collect();
            for skill in skills {
                if let Some(id) = skill.get("id").and_then(Value::as_str) {
                    if let Some((plugin, _)) = id.split_once(':') {
                        known_names.insert(plugin.to_owned());
                    }
                }
            }
            let shared = merge_codex(
                current.as_deref(),
                &desired,
                previous.get(&config_path),
                &known_names,
                marketplace_name,
            )?;
            result.shared.push(SharedArtifact {
                artifact: Artifact {
                    path: config_path,
                    bytes: shared.0,
                },
                ownership: shared.1,
                before: current,
            });
        }
        _ => return Err(invalid()),
    }
    plan_instructions(
        bundle,
        &registry,
        spec,
        &root,
        &mut result.artifacts,
        &mut result.observed,
    )?;
    if spec
        .get("extras")
        .and_then(Value::as_array)
        .is_some_and(|extras| {
            extras
                .iter()
                .any(|extra| extra.as_str() == Some("codex-agent-support"))
        })
    {
        let source = bundle
            .files
            .get("agents/operating-principles.md")
            .ok_or_else(|| {
                Error::new(
                    "HARNESS_PAYLOAD_INCOMPLETE",
                    "内容包缺少 Codex agent support 文件 agents/operating-principles.md。",
                )
            })?;
        let mut bytes = b"# Managed by atm-harness Rust distribution.\n# Source: agents/operating-principles.md\n# Do not edit this target file directly.\n\n".to_vec();
        bytes.extend_from_slice(source);
        if !bytes.ends_with(b"\n") {
            bytes.push(b'\n');
        }
        result.artifacts.push(Artifact {
            path: root.join("agents/operating-principles.md"),
            bytes,
        });
    }
    result.artifacts.sort_by(|a, b| a.path.cmp(&b.path));
    result.empty_directories.sort();
    result.empty_directories.dedup();
    if result
        .artifacts
        .windows(2)
        .any(|items| items[0].path == items[1].path)
    {
        return Err(invalid());
    }
    Ok(result)
}

fn empty_source_directories(bundle: &Bundle) -> Result<Vec<&str>> {
    let directories = bundle.manifest.get("directories").and_then(Value::as_array);
    let directories: Vec<_> = directories
        .into_iter()
        .flatten()
        .map(|directory| directory.as_str().ok_or_else(invalid))
        .collect::<Result<_>>()?;
    for directory in &directories {
        relative(directory)?;
    }
    Ok(directories
        .iter()
        .copied()
        .filter(|directory| {
            let prefix = format!("{directory}/");
            !bundle.files.keys().any(|path| path.starts_with(&prefix))
                && !directories.iter().any(|child| child.starts_with(&prefix))
        })
        .collect())
}

fn plan_instructions(
    bundle: &Bundle,
    registry: &Value,
    spec: &Value,
    root: &Path,
    files: &mut Vec<Artifact>,
    observed: &mut Vec<(PathBuf, Option<Vec<u8>>)>,
) -> Result<()> {
    let instructions = spec.get("instructions").ok_or_else(invalid)?;
    if instructions.get("driver").and_then(Value::as_str) == Some("none") {
        return Ok(());
    }
    for shadow in instructions
        .get("shadowPaths")
        .and_then(Value::as_array)
        .ok_or_else(invalid)?
    {
        let path = root.join(relative(shadow.as_str().ok_or_else(invalid)?)?);
        if exists(&path)? {
            return Err(Error::new(
                "HARNESS_SHADOW",
                "客户端指令被 override 文件遮蔽；请先处理该文件。",
            ));
        }
        observed.push((path, None));
    }
    let destination = match text(instructions, "driver")? {
        "managed-file" => relative(text(instructions, "relativePath")?)?,
        "settings-derived-file" => {
            let settings_path = root.join(relative(text(instructions, "settingsPath")?)?);
            let settings_bytes = regular_bytes(&settings_path)?;
            let settings = match settings_bytes.as_deref() {
                Some(bytes) => serde_json::from_slice::<Value>(bytes).map_err(|_| invalid())?,
                None => Value::Null,
            };
            observed.push((settings_path, settings_bytes));
            let mut value = &settings;
            for key in instructions
                .get("settingPath")
                .and_then(Value::as_array)
                .ok_or_else(invalid)?
            {
                value = value
                    .get(key.as_str().ok_or_else(invalid)?)
                    .unwrap_or(&Value::Null);
            }
            let raw = match value {
                Value::Null => text(instructions, "defaultRelativePath")?,
                Value::String(raw) => raw,
                Value::Array(values) if values.len() == 1 => {
                    values[0].as_str().ok_or_else(invalid)?
                }
                _ => {
                    return Err(Error::new(
                        "HARNESS_INSTRUCTIONS",
                        "客户端 context.fileName 必须是一个相对文件名；多个目标不受支持。",
                    ))
                }
            };
            relative(raw)?
        }
        _ => return Err(invalid()),
    };
    let source = registry
        .pointer("/sources/instructions/current")
        .and_then(Value::as_str)
        .ok_or_else(invalid)?;
    files.push(Artifact {
        path: root.join(destination),
        bytes: bundle.files.get(source).ok_or_else(invalid)?.clone(),
    });
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Ownership {
    schema_version: u32,
    kind: String,
    original: Option<Vec<u8>>,
    installed: Vec<u8>,
    roots: Vec<RootOwnership>,
    entries: Vec<EntryOwnership>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RootOwnership {
    section: String,
    existed: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EntryOwnership {
    section: String,
    key: String,
    value: String,
}
fn document(bytes: Option<&[u8]>) -> Result<Document> {
    std::str::from_utf8(bytes.unwrap_or_default())
        .map_err(|_| invalid())?
        .parse()
        .map_err(|_| invalid())
}
fn read_ownership(value: &Value) -> Result<Ownership> {
    let receipt: Ownership = serde_json::from_value(value.clone()).map_err(|_| invalid())?;
    if receipt.schema_version != 1
        || receipt.kind != "codex-toml"
        || receipt
            .entries
            .iter()
            .any(|entry| !matches!(entry.section.as_str(), "plugins" | "marketplaces"))
        || receipt
            .roots
            .iter()
            .any(|root| !matches!(root.section.as_str(), "plugins" | "marketplaces"))
    {
        return Err(invalid());
    }
    Ok(receipt)
}
fn remove_owned(doc: &mut Document, ownership: &Ownership) -> Result<()> {
    for entry in &ownership.entries {
        let actual = doc
            .get(&entry.section)
            .and_then(Item::as_table_like)
            .and_then(|root| root.get(&entry.key))
            .ok_or_else(conflict)?;
        if actual.to_string() != entry.value {
            return Err(conflict());
        }
    }
    for entry in &ownership.entries {
        doc.get_mut(&entry.section)
            .and_then(Item::as_table_like_mut)
            .ok_or_else(conflict)?
            .remove(&entry.key);
    }
    for root in &ownership.roots {
        if !root.existed
            && doc
                .get(&root.section)
                .and_then(Item::as_table_like)
                .is_some_and(|table| table.is_empty())
        {
            doc.remove(&root.section);
        }
    }
    Ok(())
}
fn merge_codex(
    current: Option<&[u8]>,
    desired: &[(String, String, Item)],
    previous: Option<&Value>,
    known_plugins: &BTreeSet<String>,
    marketplace: &str,
) -> Result<(Vec<u8>, Value)> {
    let mut doc = document(current)?;
    let (original, roots) = if let Some(previous) = previous {
        let ownership = read_ownership(previous)?;
        remove_owned(&mut doc, &ownership)?;
        // Carry user edits made between installations into the uninstall baseline.
        // Only an exact unmodified previous output may reuse its original bytes.
        let original = if current == Some(ownership.installed.as_slice()) {
            ownership.original
        } else {
            let baseline = doc.to_string().into_bytes();
            if ownership.original.is_none() && baseline.iter().all(u8::is_ascii_whitespace) {
                None
            } else {
                Some(baseline)
            }
        };
        (original, ownership.roots)
    } else {
        (
            current.map(<[u8]>::to_vec),
            ["plugins", "marketplaces"]
                .iter()
                .map(|section| RootOwnership {
                    section: (*section).into(),
                    existed: doc.contains_key(section),
                })
                .collect(),
        )
    };
    if let Some(plugins) = doc.get("plugins") {
        let plugins = plugins.as_table_like().ok_or_else(invalid)?;
        for (selector, values) in plugins.iter() {
            if let Some((plugin, source)) = selector.rsplit_once('@') {
                if known_plugins.contains(plugin)
                    && source != marketplace
                    && values
                        .as_table_like()
                        .and_then(|table| table.get("enabled"))
                        .and_then(Item::as_bool)
                        == Some(true)
                {
                    return Err(conflict());
                }
            }
        }
    }
    for (section, key, value) in desired {
        if !doc.contains_key(section) {
            doc[section] = Item::Table(Table::new());
        }
        let table = doc
            .get_mut(section)
            .and_then(Item::as_table_like_mut)
            .ok_or_else(invalid)?;
        if table.contains_key(key) {
            return Err(conflict());
        }
        table.insert(key, value.clone());
    }
    let installed = doc.to_string().into_bytes();
    // Parse emitted bytes, so receipt comparisons include the same table trivia as
    // subsequent reads. Each whole owned entry is protected, not just enabled.
    let emitted = document(Some(&installed))?;
    let entries = desired
        .iter()
        .map(|(section, key, _)| {
            Ok(EntryOwnership {
                section: section.clone(),
                key: key.clone(),
                value: emitted
                    .get(section)
                    .and_then(Item::as_table_like)
                    .and_then(|root| root.get(key))
                    .ok_or_else(invalid)?
                    .to_string(),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    let ownership = Ownership {
        schema_version: 1,
        kind: "codex-toml".into(),
        original,
        installed: installed.clone(),
        roots,
        entries,
    };
    Ok((
        installed,
        serde_json::to_value(ownership).map_err(|_| invalid())?,
    ))
}

/// Remove only proven owned entries. Unrelated user additions and comments remain.
/// Exact unmodified bytes restore the original file (or absence) exactly.
pub fn restore_shared(current: Option<&[u8]>, ownership: &Value) -> Result<Option<Vec<u8>>> {
    let ownership = read_ownership(ownership)?;
    let Some(current) = current else {
        return Err(conflict());
    };
    let mut doc = document(Some(current))?;
    remove_owned(&mut doc, &ownership)?;
    if current == ownership.installed {
        return Ok(ownership.original);
    }
    let restored = doc.to_string().into_bytes();
    if ownership.original.is_none() && restored.iter().all(u8::is_ascii_whitespace) {
        Ok(None)
    } else {
        Ok(Some(restored))
    }
}

/// Explicit old-engine handoff only. Caller proves the source root and plugin list
/// from verified legacy state. Existing owned entries must have the exact old
/// source binding and enabled shape; arbitrary user keys cannot be adopted.
pub fn legacy_codex_ownership(
    current: &[u8],
    marketplace: &str,
    source_root: &Path,
    plugins: &[String],
) -> Result<Value> {
    identifier(marketplace)?;
    if !source_root.is_absolute() {
        return Err(invalid());
    }
    let mut doc = document(Some(current))?;
    if doc
        .get("marketplaces")
        .and_then(Item::as_table_like)
        .and_then(|table| table.get(marketplace))
        .and_then(Item::as_table_like)
        .and_then(|table| table.get("source_type"))
        .and_then(Item::as_str)
        == Some("git")
    {
        return Err(Error::new(
            "HARNESS_LEGACY_MARKETPLACE_UNSUPPORTED",
            "尚不支持交接 Git 绑定的 Codex marketplace；已保留旧配置和分发所有权。",
        ));
    }
    let mut desired = Vec::new();
    let mut source = Table::new();
    source["source_type"] = toml_edit::value("local");
    source["source"] = toml_edit::value(source_root.to_str().ok_or_else(invalid)?);
    desired.push((
        "marketplaces".to_owned(),
        marketplace.to_owned(),
        Item::Table(source),
    ));
    for plugin in plugins {
        identifier(plugin)?;
        let mut enabled = Table::new();
        enabled["enabled"] = toml_edit::value(true);
        desired.push((
            "plugins".to_owned(),
            format!("{plugin}@{marketplace}"),
            Item::Table(enabled),
        ));
    }
    let mut entries = Vec::new();
    for (section, key, expected) in &desired {
        let actual = doc
            .get(section)
            .and_then(Item::as_table_like)
            .and_then(|table| table.get(key))
            .ok_or_else(conflict)?;
        let actual_table = actual.as_table_like().ok_or_else(conflict)?;
        let expected_table = expected.as_table_like().ok_or_else(invalid)?;
        if actual_table.len() != expected_table.len()
            || expected_table.iter().any(|(key, value)| {
                actual_table
                    .get(key)
                    .is_none_or(|actual| match (value.as_str(), value.as_bool()) {
                        (Some(expected), _) => actual.as_str() != Some(expected),
                        (_, Some(expected)) => actual.as_bool() != Some(expected),
                        _ => true,
                    })
            })
        {
            return Err(conflict());
        }
        entries.push(EntryOwnership {
            section: section.clone(),
            key: key.clone(),
            value: actual.to_string(),
        });
    }
    let roots = ["plugins", "marketplaces"]
        .iter()
        .map(|section| RootOwnership {
            section: (*section).into(),
            existed: false,
        })
        .collect();
    let mut ownership = Ownership {
        schema_version: 1,
        kind: "codex-toml".into(),
        original: None,
        installed: current.to_vec(),
        roots,
        entries,
    };
    remove_owned(&mut doc, &ownership)?;
    let baseline = doc.to_string().into_bytes();
    ownership.original = (!baseline.iter().all(u8::is_ascii_whitespace)).then_some(baseline);
    for root in &mut ownership.roots {
        root.existed = doc.contains_key(&root.section);
    }
    serde_json::to_value(ownership).map_err(|_| invalid())
}
