//! Cross-harness local skill inventory and bounded install/uninstall/copy.
//! Works without atm-harness; when a manager installation exists, links into
//! its managed checkout are classified `engine_managed` and never mutated here.
use crate::harness::resolve_manager_home;
use crate::{storage, Error, Result};
use serde::Serialize;
use std::fs;
use std::io::Read;
#[cfg(windows)]
use std::os::windows::fs::MetadataExt;
use std::path::{Component, Path, PathBuf};
use uuid::Uuid;

const MAX_ENTRIES_PER_ROOT: usize = 256;
const MAX_SKILL_MD_BYTES: usize = 256 * 1024;
const MAX_INSTALL_FILES: usize = 512;
const MAX_INSTALL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_INSTALL_DEPTH: usize = 8;
const MAX_NAME_BYTES: usize = 64;
const STAGING_PREFIX: &str = ".atm-skills-staging-";

use crate::tool_catalog::{find as root_spec, TOOLS as ROOTS};

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SkillEntryView {
    pub name: String,
    /// `engine_managed` | `symlink` | `directory` | `other`
    pub kind: &'static str,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub link_target: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SkillRootView {
    pub id: &'static str,
    pub label: &'static str,
    pub path: String,
    pub exists: bool,
    pub entries: Vec<SkillEntryView>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SkillTrashView {
    /// `<root_id>/<entry>` relative to the trash root; the restore handle.
    pub id: String,
    pub root_id: String,
    pub name: String,
    pub origin_path: String,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SkillsInventoryView {
    pub roots: Vec<SkillRootView>,
    pub trash: Vec<SkillTrashView>,
    pub manager_home: Option<String>,
}

/// User home directory, matching the atm-harness default resolution.
pub(crate) fn user_home() -> Result<PathBuf> {
    let variable = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    std::env::var_os(variable)
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| Error::new("SKILLS_HOME", "无法确定用户主目录，无法盘点技能。"))
}

#[cfg(windows)]
pub(crate) fn is_link_metadata(metadata: &fs::Metadata) -> bool {
    // Reparse points cover directory junctions; std only reports real symlinks.
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    metadata.file_type().is_symlink()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
pub(crate) fn is_link_metadata(metadata: &fs::Metadata) -> bool {
    metadata.file_type().is_symlink()
}

pub(crate) fn checked_name(name: &str) -> Result<()> {
    let valid = !name.is_empty()
        && name.len() <= MAX_NAME_BYTES
        && !name.starts_with('.')
        && !name
            .chars()
            .any(|c| c.is_control() || c == '/' || c == '\\' || c == ':');
    if valid {
        Ok(())
    } else {
        Err(Error::new(
            "SKILLS_NAME",
            "技能名称不合法：不得为空、以点开头或包含路径/控制字符。",
        ))
    }
}

/// Read at most the limit plus one byte; reject special files and links before reading.
pub(crate) fn read_bounded(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path).map_err(Error::io)?;
    if is_link_metadata(&metadata) || !metadata.is_file() || metadata.len() > limit {
        return Err(Error::new("SKILLS_LIMIT", "文件类型或大小超出安全范围。"));
    }
    let mut bytes = Vec::new();
    fs::File::open(path)
        .map_err(Error::io)?
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(Error::io)?;
    if bytes.len() as u64 > limit {
        return Err(Error::new("SKILLS_LIMIT", "文件大小超出安全范围。"));
    }
    Ok(bytes)
}

/// Strict frontmatter probe: only literal `name:` / `description:` lines inside
/// the first `---` block. Anything else stays unknown instead of being guessed.
fn read_frontmatter(dir: &Path) -> (Option<String>, Option<String>) {
    let mut name = None;
    let mut description = None;
    let Ok(bytes) = read_bounded(&dir.join("SKILL.md"), MAX_SKILL_MD_BYTES as u64) else {
        return (None, None);
    };
    let Ok(text) = String::from_utf8(bytes) else {
        return (None, None);
    };
    if text.len() > MAX_SKILL_MD_BYTES {
        return (None, None);
    }
    let mut lines = text.lines();
    if lines.next().map(str::trim) != Some("---") {
        return (None, None);
    }
    for line in lines {
        let trimmed = line.trim();
        if trimmed == "---" {
            break;
        }
        for (key, slot) in [("name", &mut name), ("description", &mut description)] {
            if let Some(value) = trimmed
                .strip_prefix(key)
                .and_then(|rest| rest.strip_prefix(':'))
            {
                if slot.is_none() {
                    let cleaned = value.trim().trim_matches('"').trim_matches('\'');
                    if !cleaned.is_empty() {
                        *slot = Some(cleaned.to_owned());
                    }
                }
            }
        }
    }
    (name, description)
}

fn classify_entry(
    entry_path: &Path,
    entry_name: &str,
    manager_repo: Option<&Path>,
) -> SkillEntryView {
    let build = |kind: &'static str, link_target: Option<String>| {
        let (display_name, description) = if kind == "other" {
            (None, None)
        } else {
            read_frontmatter(entry_path)
        };
        SkillEntryView {
            name: entry_name.to_owned(),
            kind,
            display_name,
            description,
            link_target,
        }
    };
    let Ok(metadata) = fs::symlink_metadata(entry_path) else {
        return build("other", None);
    };
    if is_link_metadata(&metadata) {
        let target = fs::read_link(entry_path)
            .map(|path| path.to_string_lossy().into_owned())
            .ok();
        let managed = match manager_repo {
            Some(repo) => path_within(entry_path, repo),
            None => false,
        };
        let (display_name, description) = read_frontmatter(entry_path);
        return SkillEntryView {
            name: entry_name.to_owned(),
            kind: if managed { "engine_managed" } else { "symlink" },
            display_name,
            description,
            link_target: target,
        };
    }
    if metadata.is_dir() {
        return build("directory", None);
    }
    build("other", None)
}

/// Resolve existing ancestors and link targets while normalizing missing tails.
/// Canonicalizing only the candidate misses aliased manager roots; canonicalizing
/// only complete paths misses broken projections and not-yet-created targets.
fn normalized_path(path: &Path, links: usize) -> PathBuf {
    let mut result = if path.is_absolute() {
        PathBuf::new()
    } else {
        std::env::current_dir().unwrap_or_default()
    };
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                result.pop();
            }
            _ => {
                result.push(component.as_os_str());
                if let Ok(canonical) = fs::canonicalize(&result) {
                    result = canonical;
                } else if links < 40 {
                    if let Ok(target) = fs::read_link(&result) {
                        let target = if target.is_absolute() {
                            target
                        } else {
                            result.parent().unwrap_or(Path::new("")).join(target)
                        };
                        result = normalized_path(&target, links + 1);
                    }
                }
            }
        }
    }
    result
}

pub(crate) fn path_within(path: &Path, root: &Path) -> bool {
    normalized_path(path, 0).starts_with(normalized_path(root, 0))
}

/// Shared agent skills are outside ATM ownership, including root/ancestor aliases.
pub(crate) fn require_unprotected_skill_path(home: &Path, path: &Path) -> Result<()> {
    if path_within(path, &home.join(".agents/skills")) {
        return Err(Error::new(
            "SKILLS_PROTECTED",
            "共享 .agents/skills 目录不由 ATM 管理；已拒绝访问。",
        ));
    }
    Ok(())
}

/// One bounded recursive copy plan. Links and unusual file types are rejected
/// so every installed byte is auditable plain content.
pub(crate) struct CopyBudget {
    pub(crate) files: usize,
    pub(crate) bytes: u64,
}

pub(crate) fn copy_tree(
    source: &Path,
    target: &Path,
    depth: usize,
    budget: &mut CopyBudget,
) -> Result<()> {
    if depth > MAX_INSTALL_DEPTH {
        return Err(Error::new("SKILLS_LIMIT", "技能目录嵌套超过安全深度上限。"));
    }
    for entry in fs::read_dir(source).map_err(Error::io)? {
        let entry = entry.map_err(Error::io)?;
        let entry_path = entry.path();
        let metadata = entry.metadata().map_err(Error::io)?;
        if is_link_metadata(&metadata) {
            return Err(Error::new(
                "SKILLS_UNAUDITABLE",
                "技能目录包含链接或特殊文件，内容无法完整审计，已拒绝安装。",
            ));
        }
        if metadata.is_dir() {
            let child = target.join(entry.file_name());
            fs::create_dir(&child).map_err(Error::io)?;
            copy_tree(&entry_path, &child, depth + 1, budget)?;
        } else if metadata.is_file() {
            budget.files += 1;
            budget.bytes += metadata.len();
            if budget.files > MAX_INSTALL_FILES {
                return Err(Error::new("SKILLS_LIMIT", "技能文件数超出安全上限。"));
            }
            if budget.bytes > MAX_INSTALL_BYTES {
                return Err(Error::new("SKILLS_LIMIT", "技能总大小超出安全上限。"));
            }
            fs::copy(&entry_path, target.join(entry.file_name())).map_err(Error::io)?;
        } else {
            return Err(Error::new(
                "SKILLS_UNAUDITABLE",
                "技能目录包含非常规文件，已拒绝安装。",
            ));
        }
    }
    Ok(())
}

pub(crate) fn auditable_source(source: &Path) -> Result<()> {
    if !source.is_absolute()
        || source.to_string_lossy().chars().any(char::is_control)
        || is_link_metadata(
            &fs::symlink_metadata(source)
                .map_err(|_| Error::new("SKILLS_SOURCE", "源目录不存在或无法访问。"))?,
        )
        || !source.is_dir()
    {
        return Err(Error::new(
            "SKILLS_SOURCE",
            "请选择包含 SKILL.md 的本机普通技能目录。",
        ));
    }
    if !source.join("SKILL.md").is_file() {
        return Err(Error::new(
            "SKILLS_SOURCE",
            "所选目录不含 SKILL.md，不是可安装的技能。",
        ));
    }
    Ok(())
}

pub(crate) fn target_root_dir(
    home: &Path,
    root_id: &str,
    inherit_environment: bool,
) -> Result<PathBuf> {
    let root = root_spec(root_id)?.resolve(home, inherit_environment)?;
    require_unprotected_skill_path(home, &root)?;
    Ok(root)
}

// Aliases and tools sharing a physical root must preserve existing ownership.
pub(crate) fn same_root(home: &Path, inherit: bool, a: &str, b: &str) -> bool {
    match (
        target_root_dir(home, a, inherit),
        target_root_dir(home, b, inherit),
    ) {
        (Ok(a), Ok(b)) => normalized_path(&a, 0) == normalized_path(&b, 0),
        _ => a == b,
    }
}

// New collision records use a reserved container, retaining the original name
// separately from the handle. Existing root/name trash directories stay readable.
const TRASH_RECORD_PREFIX: &str = ".atm-trash-";

fn checked_legacy_trash_name(name: &str) -> Result<()> {
    // Older versions appended timestamps to 64-byte skill names. Keep those
    // records visible and purgeable without relaxing names for new installs.
    if name.len() > 255
        || name.is_empty()
        || name.starts_with('.')
        || name
            .chars()
            .any(|c| c.is_control() || c == '/' || c == '\\' || c == ':')
    {
        return Err(Error::new("SKILLS_TRASH", "保管区名称无效。"));
    }
    Ok(())
}

fn trash_record_name(path: &Path, handle: &str) -> Result<String> {
    if let Some(id) = handle.strip_prefix(TRASH_RECORD_PREFIX) {
        Uuid::parse_str(id).map_err(|_| Error::new("SKILLS_TRASH", "保管区条目无效。"))?;
        let bytes = read_bounded(&path.join("original-name"), MAX_NAME_BYTES as u64)?;
        let name =
            String::from_utf8(bytes).map_err(|_| Error::new("SKILLS_TRASH", "保管区名称无效。"))?;
        checked_name(&name)?;
        Ok(name)
    } else {
        checked_legacy_trash_name(handle)?;
        Ok(handle.to_owned())
    }
}

fn cleanup_trash_record(path: &Path) {
    // Never recursively delete the container: a concurrent writer's data must
    // survive. These are only called after its skill was moved or removed.
    if let Some(parent) = path.parent().filter(|p| {
        p.file_name()
            .is_some_and(|n| n.to_string_lossy().starts_with(TRASH_RECORD_PREFIX))
    }) {
        let _ = fs::remove_file(parent.join("original-name"));
        let _ = fs::remove_dir(parent);
    }
}

/// Resolves a trash handle from the inventory against the real trash root,
/// rejecting any path that escapes the managed area.
fn checked_trash_path(trash_root: &Path, trash_id: &str) -> Result<(PathBuf, String, String)> {
    let invalid = || Error::new("SKILLS_TRASH", "保管区条目无效，请重新盘点。");
    if trash_id.starts_with('/') || trash_id.starts_with('\\') {
        return Err(invalid());
    }
    // Accept old Windows handles, but always emit portable '/' handles.
    let mut parts = trash_id.split(['/', '\\']);
    let (root_id, name) = match (parts.next(), parts.next(), parts.next()) {
        (Some(root), Some(name), None) if root_spec(root).is_ok() && !name.is_empty() => {
            (root.to_owned(), name.to_owned())
        }
        _ => return Err(invalid()),
    };
    // Validate the handle before joining, including traversal components.
    if !name.starts_with(TRASH_RECORD_PREFIX) {
        checked_legacy_trash_name(&name)?;
    } else if Uuid::parse_str(&name[TRASH_RECORD_PREFIX.len()..]).is_err() {
        return Err(invalid());
    }
    let record = trash_root.join(&root_id).join(&name);
    let record_metadata = fs::symlink_metadata(&record).map_err(|_| invalid())?;
    if is_link_metadata(&record_metadata) || !record_metadata.is_dir() {
        return Err(invalid());
    }
    let resolved_root = fs::canonicalize(trash_root).map_err(|_| invalid())?;
    if !fs::canonicalize(&record)
        .map_err(|_| invalid())?
        .starts_with(&resolved_root)
    {
        return Err(invalid());
    }
    let original_name = trash_record_name(&record, &name)?;
    let path = if name.starts_with(TRASH_RECORD_PREFIX) {
        record.join("skill")
    } else {
        record
    };
    let metadata = fs::symlink_metadata(&path).map_err(|_| invalid())?;
    if is_link_metadata(&metadata) || !metadata.is_dir() {
        return Err(invalid());
    }
    let resolved = fs::canonicalize(&path).map_err(|_| invalid())?;
    if !resolved.starts_with(&resolved_root) {
        return Err(invalid());
    }
    Ok((resolved, root_id, original_name))
}

/// Bounded, manager-independent service. Construct with the user home and the
/// trash root (normally `<data>/skills-trash`).
pub struct SkillsService {
    home: PathBuf,
    trash_root: PathBuf,
    manager_home: Option<PathBuf>,
    sources_root: Option<PathBuf>,
    inherit_environment: bool,
}

impl SkillsService {
    /// Explicit roots: harness environment overrides are ignored.
    pub fn new(home: PathBuf, trash_root: PathBuf) -> Self {
        Self {
            home,
            trash_root,
            manager_home: None,
            sources_root: None,
            inherit_environment: false,
        }
    }

    /// Test seam: pins the atm-harness home instead of reading the environment.
    pub fn with_manager_home(mut self, manager_home: Option<PathBuf>) -> Self {
        self.manager_home = manager_home;
        self
    }

    /// Test seam: pins this manager's projection sources directory.
    pub fn with_sources_root(mut self, sources_root: Option<PathBuf>) -> Self {
        self.sources_root = sources_root;
        self
    }

    pub fn from_environment() -> Result<Self> {
        let home = user_home()?;
        storage::ensure_directory(&storage::data_directory()?)?;
        let manager_home = resolve_manager_home(std::env::var_os("ATM_HOME").as_deref(), &home);
        Ok(Self {
            home,
            manager_home: Some(manager_home),
            inherit_environment: true,
            sources_root: Some(
                storage::data_directory()?
                    .join("skills-sources")
                    .join("sources"),
            ),
            trash_root: {
                let root = storage::data_directory()?.join("skills-trash");
                storage::ensure_directory(&root)?;
                root
            },
        })
    }

    fn projection_guard(&self) -> Result<Option<fs::File>> {
        self.sources_root
            .as_ref()
            .and_then(|root| root.parent())
            .map(|root| {
                crate::projection::ProjectionRegistry::at_root(root.into(), self.home.clone())?
                    .lock()
            })
            .transpose()
    }

    fn reject_registered(&self, root_id: &str, name: &str) -> Result<()> {
        if self.projection_records()?.iter().any(|record| {
            record.projections.iter().any(|p| {
                same_root(&self.home, self.inherit_environment, &p.root_id, root_id)
                    && p.link_name == name
            })
        }) {
            return Err(Error::new(
                "SKILLS_PROJECTED",
                "该条目是本管理器的技能投影；请用 atm skills unproject 撤除。",
            ));
        }
        Ok(())
    }

    fn projection_records(&self) -> Result<Vec<crate::projection::SourceRecord>> {
        match self.sources_root.as_ref().and_then(|root| root.parent()) {
            Some(root) => crate::projection::ProjectionRegistry::read_records(
                root,
                &self.home,
                self.inherit_environment,
            ),
            None => Ok(Vec::new()),
        }
    }

    pub fn inventory(&self) -> Result<SkillsInventoryView> {
        let manager_repo = self
            .manager_home
            .as_ref()
            .map(|manager| fs::canonicalize(manager).unwrap_or_else(|_| manager.clone()));
        let sources_root = self.sources_root.as_deref();
        let records = self.projection_records()?;
        let mut roots = Vec::new();
        for spec in ROOTS {
            let root_dir = match target_root_dir(&self.home, spec.id, self.inherit_environment) {
                Ok(root) => root,
                Err(error) if error.code == "SKILLS_PROTECTED" => continue,
                Err(error) => return Err(error),
            };
            let mut entries = Vec::new();
            let exists = root_dir.is_dir();
            if exists {
                for entry in fs::read_dir(&root_dir).map_err(Error::io)? {
                    let entry = entry.map_err(Error::io)?;
                    let entry_name = entry.file_name().to_string_lossy().into_owned();
                    if entry_name.starts_with('.')
                        || require_unprotected_skill_path(&self.home, &entry.path()).is_err()
                    {
                        continue;
                    }
                    if entries.len() >= MAX_ENTRIES_PER_ROOT {
                        break;
                    }
                    let mut view =
                        classify_entry(&entry.path(), &entry_name, manager_repo.as_deref());
                    if records.iter().any(|record| {
                        record.projections.iter().any(|p| {
                            same_root(&self.home, self.inherit_environment, &p.root_id, spec.id)
                                && p.link_name == entry_name
                        })
                    }) {
                        view.kind = "lkm_projected";
                    }
                    if view.kind == "symlink" {
                        // A link into this manager's own canonical sources area
                        // is a projection, not a foreign link.
                        if let (Some(sources), Ok(resolved)) =
                            (sources_root, fs::canonicalize(entry.path()))
                        {
                            if resolved.starts_with(sources) {
                                view.kind = "lkm_projected";
                            }
                        }
                    }
                    entries.push(view);
                }
                entries.sort_by(|a, b| a.name.cmp(&b.name));
            }
            roots.push(SkillRootView {
                id: spec.id,
                label: spec.label,
                path: root_dir.to_string_lossy().into_owned(),
                exists,
                entries,
            });
        }
        let mut trash = Vec::new();
        if let Ok(groups) = fs::read_dir(&self.trash_root) {
            for group in groups.flatten() {
                let root_id = group.file_name().to_string_lossy().into_owned();
                if root_spec(&root_id).is_err() {
                    continue;
                }
                for item in fs::read_dir(group.path()).into_iter().flatten().flatten() {
                    let name = item.file_name().to_string_lossy().into_owned();
                    let Ok((_, _, original_name)) =
                        checked_trash_path(&self.trash_root, &format!("{root_id}/{name}"))
                    else {
                        continue;
                    };
                    if name.starts_with(TRASH_RECORD_PREFIX) && !item.path().join("skill").is_dir()
                    {
                        continue;
                    }
                    trash.push(SkillTrashView {
                        id: format!("{root_id}/{name}"),
                        root_id: root_id.clone(),
                        origin_path: item.path().to_string_lossy().into_owned(),
                        name: original_name,
                    });
                }
            }
        }
        trash.sort_by(|a, b| a.id.cmp(&b.id));
        Ok(SkillsInventoryView {
            manager_home: manager_repo
                .as_ref()
                .map(|repo| repo.to_string_lossy().into_owned()),
            roots,
            trash,
        })
    }

    /// Copies an audited local skill directory into a declared root.
    pub fn install(&self, source: &Path, root_id: &str, name: &str) -> Result<String> {
        self.copy_into(
            source,
            &target_root_dir(&self.home, root_id, self.inherit_environment)?,
            root_id,
            name,
        )
    }

    /// Copies an already inventoried skill into another declared root.
    pub fn copy_to(&self, source_root: &str, name: &str, target_root: &str) -> Result<String> {
        checked_name(name)?;
        let source = target_root_dir(&self.home, source_root, self.inherit_environment)?.join(name);
        auditable_source(&source)?;
        self.copy_into(
            &source,
            &target_root_dir(&self.home, target_root, self.inherit_environment)?,
            target_root,
            name,
        )
    }

    fn copy_into(
        &self,
        source: &Path,
        target_root_dir: &Path,
        root_id: &str,
        name: &str,
    ) -> Result<String> {
        let _guard = self.projection_guard()?;
        checked_name(name)?;
        self.reject_registered(root_id, name)?;
        require_unprotected_skill_path(&self.home, source)?;
        if self
            .manager_home
            .as_ref()
            .is_some_and(|root| path_within(source, root) || path_within(target_root_dir, root))
        {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "atm-harness 管理内容只能通过 harness 命令变更。",
            ));
        }
        auditable_source(source)?;
        fs::create_dir_all(target_root_dir).map_err(Error::io)?;
        let target = target_root_dir.join(name);
        if fs::symlink_metadata(&target).is_ok() {
            return Err(Error::new(
                "SKILLS_TAKEN",
                "目标根已存在同名条目；不会覆盖，请换一个名称或先处理现有条目。",
            ));
        }
        let staging = target_root_dir.join(format!("{STAGING_PREFIX}{}", Uuid::new_v4()));
        let cleanup = |staging: &Path| {
            let _ = fs::remove_dir_all(staging);
        };
        fs::create_dir(&staging).map_err(Error::io)?;
        let mut budget = CopyBudget { files: 0, bytes: 0 };
        if let Err(error) = copy_tree(source, &staging, 0, &mut budget) {
            cleanup(&staging);
            return Err(error);
        }
        if let Err(error) = fs::rename(&staging, &target) {
            cleanup(&staging);
            return Err(Error::io(error));
        }
        Ok(format!("{root_id}/{name}"))
    }

    /// Moves a real directory skill into the recoverable trash area, or unlinks
    /// a non-managed link. atm-harness managed links are refused outright.
    pub fn uninstall(&self, root_id: &str, name: &str) -> Result<String> {
        let _guard = self.projection_guard()?;
        checked_name(name)?;
        storage::ensure_directory(&self.trash_root)?;
        if self.projection_records()?.iter().any(|record| {
            record.projections.iter().any(|p| {
                same_root(&self.home, self.inherit_environment, &p.root_id, root_id)
                    && p.link_name == name
            })
        }) {
            return Err(Error::new(
                "SKILLS_PROJECTED",
                "该条目是本管理器的技能投影；请用 atm skills unproject 撤除。",
            ));
        }
        let target = target_root_dir(&self.home, root_id, self.inherit_environment)?.join(name);
        require_unprotected_skill_path(&self.home, &target)?;
        if self
            .manager_home
            .as_ref()
            .is_some_and(|root| path_within(&target, root))
        {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "atm-harness 管理内容只能通过 harness 命令变更。",
            ));
        }
        let metadata = fs::symlink_metadata(&target)
            .map_err(|_| Error::new("SKILLS_MISSING", "条目已不存在，请重新盘点。"))?;
        let manager_repo = self
            .manager_home
            .as_ref()
            .map(|manager| fs::canonicalize(manager).unwrap_or_else(|_| manager.clone()));
        let view = classify_entry(&target, name, manager_repo.as_deref());
        if view.kind == "engine_managed" {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "该条目由 atm-harness 管理；请在终端用 harness 命令变更。",
            ));
        }
        if view.kind == "symlink" {
            // A link into this manager's own sources area is a projection;
            // removal must go through the registry to stay consistent.
            if let Some(sources) = self.sources_root.as_deref() {
                if fs::canonicalize(&target).is_ok_and(|resolved| resolved.starts_with(sources)) {
                    return Err(Error::new(
                        "SKILLS_PROJECTED",
                        "该条目是本管理器的技能投影；请用 atm skills unproject 撤除。",
                    ));
                }
            }
        }
        if is_link_metadata(&metadata) {
            return Err(Error::new(
                "SKILLS_FOREIGN_LINK",
                "非 ATM 登记链接只读；请用其所属工具或手动处理。",
            ));
        }
        if !metadata.is_dir() {
            return Err(Error::new(
                "SKILLS_MISSING",
                "普通文件不是技能条目，请手动处理。",
            ));
        }
        let group = self.trash_root.join(root_id);
        fs::create_dir_all(&group).map_err(Error::io)?;
        let base = group.join(name);
        let (destination, handle) = if fs::symlink_metadata(&base).is_ok() {
            let handle = format!("{TRASH_RECORD_PREFIX}{}", Uuid::new_v4());
            let record = group.join(&handle);
            fs::create_dir(&record).map_err(Error::io)?;
            if let Err(error) = fs::write(record.join("original-name"), name) {
                let _ = fs::remove_file(record.join("original-name"));
                let _ = fs::remove_dir(&record);
                return Err(Error::io(error));
            }
            (record.join("skill"), handle)
        } else {
            (base, name.to_owned())
        };
        // Rename-only deliberately fails safely across filesystems. Never delete
        // the original or another writer's destination on failure.
        if let Err(error) = fs::rename(&target, &destination) {
            if handle.starts_with(TRASH_RECORD_PREFIX) {
                cleanup_trash_record(&destination);
            }
            return Err(Error::io(error));
        }
        Ok(format!("{root_id}/{handle}"))
    }

    /// Moves a previously uninstalled skill back into its declared root.
    pub fn restore(&self, trash_id: &str) -> Result<String> {
        let _guard = self.projection_guard()?;
        let trash_root = self.trash_root.clone();
        let (path, root_id, name) = checked_trash_path(&trash_root, trash_id)?;
        checked_name(&name)?;
        self.reject_registered(&root_id, &name)?;
        let target = target_root_dir(&self.home, &root_id, self.inherit_environment)?.join(&name);
        if self
            .manager_home
            .as_ref()
            .is_some_and(|root| path_within(&target, root))
        {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "atm-harness 管理内容只能通过 harness 命令变更。",
            ));
        }
        if fs::symlink_metadata(&target).is_ok() {
            return Err(Error::new(
                "SKILLS_TAKEN",
                "目标根现已存在同名条目；恢复被拒绝，请先处理现有条目。",
            ));
        }
        fs::create_dir_all(target_root_dir(
            &self.home,
            &root_id,
            self.inherit_environment,
        )?)
        .map_err(Error::io)?;
        fs::rename(&path, &target).map_err(Error::io)?;
        cleanup_trash_record(&path);
        Ok(format!("{root_id}/{name}"))
    }

    /// Permanently deletes a trashed skill after path containment checks.
    pub fn purge(&self, trash_id: &str) -> Result<()> {
        let trash_root = self.trash_root.clone();
        let (path, _root_id, _name) = checked_trash_path(&trash_root, trash_id)?;
        fs::remove_dir_all(&path).map_err(Error::io)?;
        cleanup_trash_record(&path);
        Ok(())
    }
}

#[cfg(test)]
mod ownership_path_tests {
    use super::*;

    #[test]
    fn nonexistent_roots_and_parent_components_are_normalized() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("missing/../manager");
        assert!(path_within(&temp.path().join("manager/skills/new"), &root));
        assert!(!path_within(&temp.path().join("manager/../foreign"), &root));
        assert!(!path_within(
            &temp.path().join("manager-other/skill"),
            &root
        ));
    }

    #[cfg(unix)]
    #[test]
    fn broken_relative_links_and_aliases_resolve_before_parent_components() {
        use std::os::unix::fs::symlink;
        let temp = tempfile::tempdir().unwrap();
        fs::create_dir_all(temp.path().join("real/manager")).unwrap();
        symlink("real/manager", temp.path().join("alias")).unwrap();
        symlink("alias/missing/skill", temp.path().join("broken")).unwrap();
        assert!(path_within(
            &temp.path().join("broken"),
            &temp.path().join("alias")
        ));
        assert!(path_within(
            &temp.path().join("alias/../manager/new"),
            &temp.path().join("real/manager")
        ));
        assert!(!path_within(
            &temp.path().join("alias/../foreign/new"),
            &temp.path().join("real/manager")
        ));
    }
}
