//! Single-source, multi-root skill projection: an atm-harness style
//! distribution model owned entirely by this manager. A skill source is
//! adopted into `<data>/skills-sources/sources/<name>` as the canonical copy,
//! then projected into declared harness roots as links (POSIX symlink) or
//! plain copies (Windows junction/symlink privileges are not assumed).
//! Projections are recorded in `registry.json`; check/refresh/remove only
//! ever touch links recorded there. atm-harness projections are never
//! listed or modified here — coexistence relies on both sides' same-name
//! refusal discipline.
use crate::skills::{
    auditable_source, checked_name, copy_tree, is_link_metadata, path_within, read_bounded,
    require_unprotected_skill_path, target_root_dir, user_home, CopyBudget,
};
use crate::{storage, windows, Error, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

const REGISTRY_FILE: &str = "registry.json";
const SOURCES_DIR: &str = "sources";
const MAX_PROJECTIONS_PER_SOURCE: usize = 16;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProjectionRecord {
    pub root_id: String,
    pub link_name: String,
    /// Windows directory identity; legacy/missing receipts fail closed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub directory_identity: Option<String>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Materialization {
    /// POSIX symlink into the canonical sources area.
    Link,
    /// Plain copy; Windows junctions/symlink privileges are not assumed.
    Copy,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceRecord {
    pub name: String,
    pub materialization: Materialization,
    pub projections: Vec<ProjectionRecord>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct CheckItem {
    pub source: String,
    pub root_id: String,
    pub link_name: String,
    /// `ok` | `broken_link` | `modified_copy` | `ownership_unknown`
    pub status: &'static str,
    pub detail: Option<String>,
}

pub fn materialization_mode() -> Materialization {
    if cfg!(windows) {
        Materialization::Copy
    } else {
        Materialization::Link
    }
}

fn create_materialization(canonical: &Path, target: &Path) -> Result<()> {
    if materialization_mode() == Materialization::Link {
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(canonical, target).map_err(Error::io)
        }
        #[cfg(not(unix))]
        {
            let _ = (canonical, target);
            Err(Error::new("PROJECTION_TARGET", "此平台不支持链接投影。"))
        }
    } else {
        fs::create_dir(target).map_err(Error::io)?;
        let mut budget = CopyBudget { files: 0, bytes: 0 };
        if let Err(error) = copy_tree(canonical, target, 0, &mut budget) {
            fs::remove_dir_all(target).map_err(|_| recovery_error())?;
            return Err(error);
        }
        Ok(())
    }
}

/// The registry plus canonical sources under one root directory.
pub struct ProjectionRegistry {
    root: PathBuf,
    home: PathBuf,
    inherit_environment: bool,
}

impl ProjectionRegistry {
    pub fn from_environment() -> Result<Self> {
        let data = storage::data_directory()?;
        storage::ensure_directory(&data)?;
        let root = data.join("skills-sources");
        let home = user_home()?;
        storage::ensure_directory(&root)?;
        storage::ensure_directory(&root.join(SOURCES_DIR))?;
        Ok(Self {
            root,
            home,
            inherit_environment: true,
        })
    }

    /// Explicit roots: harness and manager environment overrides are ignored.
    pub fn at_root(root: PathBuf, home: PathBuf) -> Result<Self> {
        storage::ensure_directory(&root)?;
        storage::ensure_directory(&root.join(SOURCES_DIR))?;
        Ok(Self {
            root,
            home,
            inherit_environment: false,
        })
    }

    fn manager_home(&self) -> PathBuf {
        let override_home = if self.inherit_environment {
            std::env::var_os("ATM_HOME")
        } else {
            None
        };
        crate::harness::resolve_manager_home(override_home.as_deref(), &self.home)
    }

    fn registry_path(&self) -> PathBuf {
        self.root.join(REGISTRY_FILE)
    }

    pub fn sources_root(&self) -> PathBuf {
        self.root.join(SOURCES_DIR)
    }

    fn canonical_dir(&self, name: &str) -> PathBuf {
        self.sources_root().join(name)
    }

    pub(crate) fn read_records(
        root: &Path,
        home: &Path,
        inherit_environment: bool,
    ) -> Result<Vec<SourceRecord>> {
        Self {
            root: root.into(),
            home: home.into(),
            inherit_environment,
        }
        .load()
    }

    pub(crate) fn lock(&self) -> Result<fs::File> {
        windows::open_lock(&self.root.join("registry.lock"))
    }

    fn load(&self) -> Result<Vec<SourceRecord>> {
        match fs::symlink_metadata(self.registry_path()) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(e) => return Err(Error::io(e)),
            Ok(_) => {}
        }
        let bytes = read_bounded(&self.registry_path(), 1024 * 1024)?;
        let records: Vec<SourceRecord> = serde_json::from_slice(&bytes).map_err(|_| {
            Error::new(
                "PROJECTION_REGISTRY",
                "技能投影登记无法解析；请勿手工编辑 registry.json。",
            )
        })?;
        let mut names = std::collections::HashSet::new();
        let mut targets = std::collections::HashSet::new();
        for record in &records {
            checked_name(&record.name)?;
            if !names.insert(&record.name) || record.projections.len() > MAX_PROJECTIONS_PER_SOURCE
            {
                return Err(Error::new(
                    "PROJECTION_REGISTRY",
                    "技能投影登记重复或超出上限。",
                ));
            }
            for projection in &record.projections {
                checked_name(&projection.link_name)?;
                // Keep receipts readable if a tool root is redirected into the
                // protected shared directory. Every access still checks the root.
                if let Err(error) =
                    target_root_dir(&self.home, &projection.root_id, self.inherit_environment)
                {
                    if error.code != "SKILLS_PROTECTED" {
                        return Err(error);
                    }
                }
                if projection.link_name != record.name
                    || !targets.insert((&projection.root_id, &projection.link_name))
                {
                    return Err(Error::new(
                        "PROJECTION_REGISTRY",
                        "技能投影登记目标无效或重复。",
                    ));
                }
            }
        }
        Ok(records)
    }

    fn save(&self, records: &[SourceRecord]) -> Result<()> {
        let mut text = serde_json::to_string_pretty(records)
            .map_err(|_| Error::new("PROJECTION_REGISTRY", "技能投影登记序列化失败。"))?;
        text.push('\n');
        let staging = self.root.join(format!(
            "registry.json.atm-staging-{}",
            uuid::Uuid::new_v4()
        ));
        let result = (|| {
            let mut options = fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options.open(&staging).map_err(Error::io)?;
            file.write_all(text.as_bytes()).map_err(Error::io)?;
            file.sync_all().map_err(Error::io)?;
            drop(file);
            if self.registry_path().exists() {
                windows::replace(&staging, &self.registry_path())
            } else {
                fs::rename(&staging, self.registry_path()).map_err(Error::io)
            }
        })();
        if result.is_err() {
            let _ = fs::remove_file(&staging);
        }
        result?;
        Ok(())
    }

    pub fn list(&self) -> Result<Vec<SourceRecord>> {
        let _lock = self.lock()?;
        self.load()
    }

    fn record_mut<'a>(records: &'a mut [SourceRecord], name: &str) -> Result<&'a mut SourceRecord> {
        records
            .iter_mut()
            .find(|record| record.name == name)
            .ok_or_else(|| Error::new("SKILLS_MISSING", "技能源不存在，请先发布。"))
    }

    /// Adopts an audited local directory as a canonical source and projects it
    /// into the declared roots. Same-name sources and entries are refused.
    pub fn publish(&self, source: &Path, name: &str, targets: &[String]) -> Result<Vec<String>> {
        let _lock = self.lock()?;
        checked_name(name)?;
        require_unprotected_skill_path(&self.home, source)?;
        auditable_source(source)?;
        let manager_home = self.manager_home();
        if path_within(source, &manager_home) {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "不能收编或重新投影 atm-harness 管理的技能。",
            ));
        }
        if targets.len() > MAX_PROJECTIONS_PER_SOURCE {
            return Err(Error::new(
                "PROJECTION_LIMIT",
                "单个技能源的投影数超出上限。",
            ));
        }
        if targets.is_empty() {
            return Err(Error::new(
                "PROJECTION_TARGET",
                "请至少选择一个投影目标工具根。",
            ));
        }
        let mut records = self.load()?;
        if records.iter().any(|record| record.name == name) {
            return Err(Error::new(
                "SKILLS_TAKEN",
                "已存在同名技能源；不会覆盖，请换一个名称或先 unpublish。",
            ));
        }
        // Check every destination before adoption; an intent is persisted before
        // creating projections so interrupted work remains visible and removable.
        let mut unique = std::collections::HashSet::new();
        for target in targets {
            if !unique.insert(target) {
                return Err(Error::new("SKILLS_TAKEN", "投影目标重复。"));
            }
            self.require_free_target(target, name)?;
        }
        let canonical = self.canonical_dir(name);
        fs::create_dir(&canonical).map_err(Error::io)?;
        let mut budget = CopyBudget { files: 0, bytes: 0 };
        if let Err(error) = copy_tree(source, &canonical, 0, &mut budget) {
            fs::remove_dir_all(&canonical).map_err(Error::io)?;
            return Err(error);
        }
        records.push(SourceRecord {
            name: name.to_owned(),
            materialization: materialization_mode(),
            projections: targets
                .iter()
                .map(|root_id| ProjectionRecord {
                    root_id: root_id.clone(),
                    link_name: name.to_owned(),
                    directory_identity: None,
                })
                .collect(),
        });
        if let Err(error) = self.save(&records) {
            fs::remove_dir_all(&canonical).map_err(Error::io)?;
            return Err(error);
        }
        let mut projected = Vec::new();
        let mut created = Vec::new();
        for target in targets {
            if let Err(error) = self.project_one(&canonical, target, name, &mut created) {
                if error.code == "PROJECTION_RECOVERY" {
                    return Err(error);
                }
                for existing in &created {
                    self.unproject_one(
                        &canonical,
                        &existing.root_id,
                        &existing.link_name,
                        false,
                        existing.directory_identity.as_deref(),
                    )?;
                }
                records.retain(|record| record.name != name);
                self.save(&records)?;
                fs::remove_dir_all(&canonical).map_err(Error::io)?;
                return Err(error);
            }
            let actual = created
                .last()
                .expect("successful projection has a receipt")
                .clone();
            let record = Self::record_mut(&mut records, name)?;
            *record
                .projections
                .iter_mut()
                .find(|p| p.root_id == *target)
                .expect("intent exists") = actual;
            self.save(&records)?;
            projected.push(format!("{target}/{name}"));
        }
        Ok(projected)
    }

    /// Projects an already published source into one more root.
    pub fn project(&self, name: &str, target_root: &str) -> Result<String> {
        let _lock = self.lock()?;
        let mut records = self.load()?;
        let canonical = self.canonical_dir(name);
        if !canonical.is_dir() {
            return Err(Error::new(
                "SKILLS_MISSING",
                "技能源目录缺失，登记已损坏；请 unpublish 后重新发布。",
            ));
        }
        {
            let record = Self::record_mut(&mut records, name)?;
            if record.projections.len() >= MAX_PROJECTIONS_PER_SOURCE {
                return Err(Error::new(
                    "PROJECTION_LIMIT",
                    "单个技能源的投影数超出上限。",
                ));
            }
            if record
                .projections
                .iter()
                .any(|projection| projection.root_id == target_root && projection.link_name == name)
            {
                return Err(Error::new("SKILLS_TAKEN", "该技能源已投影到此工具根。"));
            }
        }
        self.require_free_target(target_root, name)?;
        Self::record_mut(&mut records, name)?
            .projections
            .push(ProjectionRecord {
                root_id: target_root.into(),
                link_name: name.into(),
                directory_identity: None,
            });
        self.save(&records)?;
        let mut created = Vec::new();
        if let Err(error) = self.project_one(&canonical, target_root, name, &mut created) {
            if error.code == "PROJECTION_RECOVERY" {
                return Err(error);
            }
            Self::record_mut(&mut records, name)?
                .projections
                .retain(|p| p.root_id != target_root);
            self.save(&records)?;
            return Err(error);
        }
        let actual = created.pop().expect("successful projection has a receipt");
        *Self::record_mut(&mut records, name)?
            .projections
            .iter_mut()
            .find(|p| p.root_id == target_root)
            .expect("intent exists") = actual;
        self.save(&records)?;
        Ok(format!("{target_root}/{name}"))
    }

    fn require_free_target(&self, target_root: &str, name: &str) -> Result<()> {
        let root = target_root_dir(&self.home, target_root, self.inherit_environment)?;
        let manager_home = self.manager_home();
        if path_within(&root, &manager_home) {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "不能向 atm-harness 管理目录投影。",
            ));
        }
        let target = root.join(name);
        match fs::symlink_metadata(target) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(Error::io(e)),
            Ok(_) => Err(Error::new(
                "SKILLS_TAKEN",
                "目标根已存在同名条目；不会覆盖。",
            )),
        }
    }

    fn project_one(
        &self,
        canonical: &Path,
        target_root: &str,
        link_name: &str,
        projections: &mut Vec<ProjectionRecord>,
    ) -> Result<()> {
        checked_name(link_name)?;
        self.require_free_target(target_root, link_name)?;
        let root_dir = target_root_dir(&self.home, target_root, self.inherit_environment)?;
        fs::create_dir_all(&root_dir).map_err(Error::io)?;
        let target = root_dir.join(link_name);
        if fs::symlink_metadata(&target).is_ok() {
            return Err(Error::new(
                "SKILLS_TAKEN",
                "目标根已存在同名条目；不会覆盖。若它由 atm-harness 管理，请用 harness 命令处理。",
            ));
        }
        create_materialization(canonical, &target)?;
        projections.push(ProjectionRecord {
            root_id: target_root.to_owned(),
            link_name: link_name.to_owned(),
            directory_identity: projection_identity(&target).map_err(|_| recovery_error())?,
        });
        Ok(())
    }

    /// Removes one projection: unlinks, or deletes a copy only when unchanged
    /// (unless forced). Registry-only records are cleaned up as well.
    pub fn unproject(&self, name: &str, target_root: &str, force: bool) -> Result<()> {
        let _lock = self.lock()?;
        self.unproject_inner(name, target_root, force)
    }

    fn unproject_inner(&self, name: &str, target_root: &str, force: bool) -> Result<()> {
        let mut records = self.load()?;
        {
            let record = Self::record_mut(&mut records, name)?;
            if !record
                .projections
                .iter()
                .any(|projection| projection.root_id == target_root && projection.link_name == name)
            {
                return Err(Error::new(
                    "SKILLS_MISSING",
                    "登记中没有这个投影；请先用 check 核对。",
                ));
            }
        }
        let canonical = self.canonical_dir(name);
        let identity = Self::record_mut(&mut records, name)?
            .projections
            .iter()
            .find(|p| p.root_id == target_root)
            .and_then(|p| p.directory_identity.clone());
        self.unproject_one(&canonical, target_root, name, force, identity.as_deref())?;
        let record = Self::record_mut(&mut records, name)?;
        record.projections.retain(|projection| {
            !(projection.root_id == target_root && projection.link_name == name)
        });
        self.save(&records)?;
        Ok(())
    }

    /// Removes a projection found through inventory (no source name needed).
    pub fn unproject_link(&self, target_root: &str, link_name: &str, force: bool) -> Result<()> {
        let _lock = self.lock()?;
        let records = self.load()?;
        let record = records
            .iter()
            .find(|record| {
                record.projections.iter().any(|projection| {
                    projection.root_id == target_root && projection.link_name == link_name
                })
            })
            .ok_or_else(|| Error::new("SKILLS_MISSING", "该条目不是本管理器的投影。"))?;
        let name = record.name.clone();
        self.unproject_inner(&name, target_root, force)
    }

    fn unproject_one(
        &self,
        canonical: &Path,
        target_root: &str,
        link_name: &str,
        force: bool,
        expected_identity: Option<&str>,
    ) -> Result<()> {
        if self.removable_projection(canonical, target_root, link_name, force, expected_identity)? {
            let target =
                target_root_dir(&self.home, target_root, self.inherit_environment)?.join(link_name);
            remove_materialization(&target)?;
        }
        Ok(())
    }

    fn removable_projection(
        &self,
        canonical: &Path,
        target_root: &str,
        link_name: &str,
        force: bool,
        expected_identity: Option<&str>,
    ) -> Result<bool> {
        let root = target_root_dir(&self.home, target_root, self.inherit_environment)?;
        let manager_home = self.manager_home();
        if path_within(&root, &manager_home) {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "不能变更 atm-harness 管理目录。",
            ));
        }
        let target = root.join(link_name);
        let metadata = match fs::symlink_metadata(&target) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(e) => return Err(Error::io(e)),
            Ok(metadata) => metadata,
        };
        if is_link_metadata(&metadata) {
            if !self.link_points_to(&target, canonical) {
                return Err(Error::new(
                    "SKILLS_TAKEN",
                    "目标条目不是本管理器的投影链接，已拒绝移除。",
                ));
            }
            return Ok(true);
        }
        if metadata.is_dir() && materialization_mode() == Materialization::Copy {
            if !copy_identity_matches(&target, expected_identity) {
                return Err(Error::new(
                    "PROJECTION_OWNERSHIP",
                    "投影目录身份已变化或缺少登记凭据；即使 force 也不会删除，请手动核对。",
                ));
            }
            if self.compare_copy(canonical, &target) != "ok" && !force {
                return Err(Error::new(
                    "SKILLS_TAKEN",
                    "投影副本在目标根被修改过，已拒绝删除；确认放弃修改请使用 force。",
                ));
            }
            return Ok(true);
        }
        Err(Error::new(
            "SKILLS_TAKEN",
            "目标条目类型不是本管理器的投影形态，已拒绝移除。",
        ))
    }

    fn link_points_to(&self, target: &Path, canonical: &Path) -> bool {
        fs::read_link(target).is_ok_and(|link| {
            let absolute = if link.is_absolute() {
                link
            } else {
                target.parent().unwrap_or(target).join(link)
            };
            absolute == canonical
                || fs::canonicalize(absolute)
                    .ok()
                    .zip(fs::canonicalize(canonical).ok())
                    .is_some_and(|(a, b)| a == b)
        })
    }

    /// Recursively compares a projected copy against its canonical source,
    /// bounded by the same audit limits as installation.
    fn compare_copy(&self, canonical: &Path, copy: &Path) -> &'static str {
        fn walk(
            canonical: &Path,
            copy: &Path,
            files: &mut usize,
            bytes: &mut u64,
            depth: usize,
        ) -> &'static str {
            if depth > 8 {
                return "modified_copy";
            }
            let Ok(entries) = fs::read_dir(canonical) else {
                return "modified_copy";
            };
            let Ok(copy_entries) = fs::read_dir(copy) else {
                return "broken_link";
            };
            let copy_count = copy_entries.take(513).count();
            if copy_count > 512 {
                return "modified_copy";
            }
            let mut canonical_count = 0usize;
            for entry in entries {
                let Ok(entry) = entry else {
                    return "modified_copy";
                };
                canonical_count += 1;
                if canonical_count > copy_count {
                    return "modified_copy";
                }
                let copy_child = copy.join(entry.file_name());
                let Ok(metadata) = fs::symlink_metadata(entry.path()) else {
                    return "modified_copy";
                };
                if is_link_metadata(&metadata) {
                    return "modified_copy";
                }
                let Ok(copy_metadata) = fs::symlink_metadata(&copy_child) else {
                    return "modified_copy";
                };
                if is_link_metadata(&copy_metadata) {
                    return "modified_copy";
                }
                if metadata.is_dir() {
                    if !copy_metadata.is_dir() {
                        return "modified_copy";
                    }
                    match walk(&entry.path(), &copy_child, files, bytes, depth + 1) {
                        "ok" => {}
                        other => return other,
                    }
                } else if metadata.is_file() {
                    *files += 1;
                    if *files > 512 {
                        return "modified_copy";
                    }
                    *bytes += metadata.len();
                    if *bytes > 8 * 1024 * 1024 {
                        return "modified_copy";
                    }
                    match (
                        read_bounded(&entry.path(), 8 * 1024 * 1024),
                        read_bounded(&copy_child, 8 * 1024 * 1024),
                    ) {
                        (Ok(a), Ok(b)) if a == b => {}
                        _ => return "modified_copy",
                    }
                } else {
                    return "modified_copy";
                }
            }
            if canonical_count != copy_count {
                return "modified_copy";
            }
            "ok"
        }
        let mut files = 0usize;
        walk(canonical, copy, &mut files, &mut 0, 0)
    }

    /// Verifies every projection (or one source's) and returns per-item status.
    pub fn check(&self, name: Option<&str>) -> Result<Vec<CheckItem>> {
        let _lock = self.lock()?;
        self.check_inner(name)
    }

    fn check_inner(&self, name: Option<&str>) -> Result<Vec<CheckItem>> {
        let records = self.load()?;
        if let Some(selected) = name {
            checked_name(selected)?;
            if !records.iter().any(|record| record.name == selected) {
                return Err(Error::new("SKILLS_MISSING", "技能源不存在，请先发布。"));
            }
        }
        let mut items = Vec::new();
        for record in &records {
            if name.is_some_and(|selected| selected != record.name) {
                continue;
            }
            let canonical = self.canonical_dir(&record.name);
            if !canonical.is_dir() {
                items.push(CheckItem {
                    source: record.name.clone(),
                    root_id: String::new(),
                    link_name: String::new(),
                    status: "broken_link",
                    detail: Some("canonical 源目录缺失".into()),
                });
                continue;
            }
            for projection in &record.projections {
                let (status, detail) = match target_root_dir(
                    &self.home,
                    &projection.root_id,
                    self.inherit_environment,
                ) {
                    Err(error) if error.code == "SKILLS_PROTECTED" => (
                        "broken_link",
                        Some("工具根指向受保护的共享技能目录".to_owned()),
                    ),
                    Err(_) => ("broken_link", Some("未知工具根".to_owned())),
                    Ok(root_dir) => {
                        let target = root_dir.join(&projection.link_name);
                        match fs::symlink_metadata(&target) {
                            Err(_) => ("broken_link", None),
                            Ok(metadata) => {
                                if is_link_metadata(&metadata) {
                                    if self.link_points_to(&target, &canonical) {
                                        ("ok", None)
                                    } else {
                                        (
                                            "broken_link",
                                            Some("链接目标不是本源的 canonical 目录".into()),
                                        )
                                    }
                                } else if metadata.is_dir()
                                    && record.materialization == Materialization::Copy
                                {
                                    if copy_identity_matches(
                                        &target,
                                        projection.directory_identity.as_deref(),
                                    ) {
                                        (self.compare_copy(&canonical, &target), None)
                                    } else {
                                        (
                                            "ownership_unknown",
                                            Some("目录身份已变化或缺少登记凭据；请手动核对".into()),
                                        )
                                    }
                                } else {
                                    ("modified_copy", Some("目标条目被其它内容占用".into()))
                                }
                            }
                        }
                    }
                };
                items.push(CheckItem {
                    source: record.name.clone(),
                    root_id: projection.root_id.clone(),
                    link_name: projection.link_name.clone(),
                    status,
                    detail,
                });
            }
        }
        Ok(items)
    }

    /// Repairs projections: rebuilds broken links and re-copies when forced.
    /// Modified copies are skipped unless `force`.
    pub fn refresh(&self, name: Option<&str>, force: bool) -> Result<Vec<CheckItem>> {
        let _lock = self.lock()?;
        let mut records = self.load()?;
        for item in self.check_inner(name)? {
            let repair = match item.status {
                "ok" => false,
                "broken_link" => true,
                "modified_copy" => force,
                _ => false,
            };
            if repair {
                let canonical = self.canonical_dir(&item.source);
                if !canonical.is_dir() {
                    continue;
                }
                let root = self.refresh_root(&item.root_id)?;
                let target = root.join(&item.link_name);
                let record = Self::record_mut(&mut records, &item.source)?;
                let projection = record
                    .projections
                    .iter_mut()
                    .find(|p| p.root_id == item.root_id && p.link_name == item.link_name)
                    .expect("checked registry projection");
                let old_identity = projection.directory_identity.clone();
                self.removable_projection(
                    &canonical,
                    &item.root_id,
                    &item.link_name,
                    force,
                    old_identity.as_deref(),
                )?;

                // Fully audit/copy before moving the old projection. Force only
                // authorizes discarding edits after the replacement is ready.
                let staging = root.join(format!(".atm-staging-{}", uuid::Uuid::new_v4()));
                if materialization_mode() == Materialization::Copy {
                    auditable_source(&canonical)?;
                }
                create_materialization(&canonical, &staging)?;
                let prepared = (|| {
                    let identity = projection_identity(&staging)?;
                    if materialization_mode() == Materialization::Copy
                        && self.compare_copy(&canonical, &staging) != "ok"
                    {
                        return Err(Error::new(
                            "SKILLS_SOURCE",
                            "复制期间技能源变化，未替换投影。",
                        ));
                    }
                    // Recheck ownership and the root after the potentially slow copy.
                    self.refresh_root(&item.root_id)?;
                    let present = self.removable_projection(
                        &canonical,
                        &item.root_id,
                        &item.link_name,
                        force,
                        old_identity.as_deref(),
                    )?;
                    Ok((identity, present))
                })();
                let (identity, present) = match prepared {
                    Ok(value) => value,
                    Err(error) => {
                        remove_materialization(&staging).map_err(|_| refresh_recovery_error())?;
                        return Err(error);
                    }
                };
                let retired = root.join(format!(".atm-refresh-old-{}", uuid::Uuid::new_v4()));
                if present {
                    if let Err(error) = fs::rename(&target, &retired) {
                        remove_materialization(&staging).map_err(|_| refresh_recovery_error())?;
                        return Err(Error::io(error));
                    }
                    if materialization_mode() == Materialization::Copy
                        && !copy_identity_matches(&retired, old_identity.as_deref())
                    {
                        // Do not delete a directory that changed during handoff.
                        restore_retired(&retired, &target)?;
                        remove_materialization(&staging).map_err(|_| refresh_recovery_error())?;
                        return Err(Error::new(
                            "PROJECTION_OWNERSHIP",
                            "投影交接期间身份变化，已拒绝替换。",
                        ));
                    }
                }
                // Windows rename refuses any occupied destination. POSIX link
                // installation uses symlink creation, which also never overwrites.
                let installed = if materialization_mode() == Materialization::Link {
                    create_materialization(&canonical, &target)
                } else {
                    fs::rename(&staging, &target).map_err(Error::io)
                };
                if let Err(error) = installed {
                    if present {
                        restore_retired(&retired, &target)?;
                    }
                    remove_materialization(&staging).map_err(|_| refresh_recovery_error())?;
                    return Err(error);
                }
                projection.directory_identity = identity;
                if let Err(error) = self.save(&records) {
                    // Keep the old receipt and content together on persistence failure.
                    if materialization_mode() == Materialization::Copy {
                        fs::rename(&target, &staging).map_err(|_| refresh_recovery_error())?;
                    } else {
                        remove_materialization(&target).map_err(|_| refresh_recovery_error())?;
                    }
                    if present {
                        restore_retired(&retired, &target)?;
                    }
                    remove_materialization(&staging).map_err(|_| refresh_recovery_error())?;
                    return Err(error);
                }
                if materialization_mode() == Materialization::Link {
                    remove_materialization(&staging).map_err(|_| refresh_recovery_error())?;
                }
                if present {
                    remove_materialization(&retired).map_err(|_| refresh_recovery_error())?;
                }
            }
        }
        self.check_inner(name)
    }

    /// Validate existing components before recreating a missing skills root.
    fn refresh_root(&self, root_id: &str) -> Result<PathBuf> {
        let root = target_root_dir(&self.home, root_id, self.inherit_environment)?;
        let manager_home = self.manager_home();
        if path_within(&root, &manager_home) {
            return Err(Error::new(
                "SKILLS_ENGINE_LOCKED",
                "不能变更 atm-harness 管理目录。",
            ));
        }
        let check_components = || -> Result<()> {
            let mut path = PathBuf::new();
            for component in root.components() {
                path.push(component.as_os_str());
                match fs::symlink_metadata(&path) {
                    Ok(metadata)
                        if (is_link_metadata(&metadata) || !metadata.is_dir())
                            && !trusted_system_alias(&path, &metadata) =>
                    {
                        return Err(Error::new(
                            "SKILLS_ROOT",
                            "技能根路径包含链接或非目录，已拒绝变更。",
                        ));
                    }
                    Ok(_) => {}
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
                    Err(error) => return Err(Error::io(error)),
                }
            }
            Ok(())
        };
        check_components()?;
        fs::create_dir_all(&root).map_err(Error::io)?;
        check_components()?;
        Ok(root)
    }

    /// Removes a published source. All projections must be gone first unless
    /// `with_projections` tears them down (modified copies still refuse).
    pub fn unpublish(&self, name: &str, with_projections: bool) -> Result<Vec<String>> {
        let _lock = self.lock()?;
        let mut records = self.load()?;
        {
            let record = Self::record_mut(&mut records, name)?;
            if !record.projections.is_empty() && !with_projections {
                return Err(Error::new(
                    "PROJECTION_TARGET",
                    "该技能源仍有投影；先 unproject，或使用 with-projections 一并撤除。",
                ));
            }
        }
        let canonical = self.canonical_dir(name);

        let mut torn_down = Vec::new();
        if with_projections {
            let projections = Self::record_mut(&mut records, name)?.projections.clone();
            for projection in projections {
                self.unproject_one(
                    &canonical,
                    &projection.root_id,
                    &projection.link_name,
                    false,
                    projection.directory_identity.as_deref(),
                )?;
                Self::record_mut(&mut records, name)?
                    .projections
                    .retain(|p| p != &projection);
                self.save(&records)?;
                torn_down.push(format!("{}/{}", projection.root_id, projection.link_name));
            }
        }
        if canonical.exists() {
            fs::remove_dir_all(&canonical).map_err(Error::io)?;
        }
        records.retain(|record| record.name != name);
        self.save(&records)?;
        Ok(torn_down)
    }

    /// Whether a resolved link target lives inside the canonical sources area.
    pub fn owns_resolved(&self, resolved: &Path) -> bool {
        resolved.starts_with(self.sources_root())
    }
}

fn trusted_system_alias(path: &Path, metadata: &fs::Metadata) -> bool {
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::fs::MetadataExt;
        let expected = match path.to_str() {
            Some("/var") => "/private/var",
            Some("/tmp") => "/private/tmp",
            Some("/etc") => "/private/etc",
            _ => return false,
        };
        metadata.uid() == 0
            && fs::read_link(path).is_ok_and(|target| {
                let target = if target.is_absolute() {
                    target
                } else {
                    path.parent().unwrap_or(path).join(target)
                };
                target == Path::new(expected)
            })
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (path, metadata);
        false
    }
}

fn remove_materialization(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(Error::io)?;
    if is_link_metadata(&metadata) {
        remove_link(path).map_err(Error::io)
    } else {
        fs::remove_dir_all(path).map_err(Error::io)
    }
}

fn restore_retired(retired: &Path, target: &Path) -> Result<()> {
    // Never overwrite an entry created by another actor during the handoff.
    if fs::symlink_metadata(target).is_ok() {
        return Err(refresh_recovery_error());
    }
    fs::rename(retired, target).map_err(|_| refresh_recovery_error())
}

fn refresh_recovery_error() -> Error {
    Error::new("PROJECTION_RECOVERY", "投影替换或清理未确认；内容和登记已保留，请核对 .atm-refresh-old-* 与 .atm-staging-*，勿直接删除。")
}

fn remove_link(path: &Path) -> std::io::Result<()> {
    #[cfg(windows)]
    if fs::symlink_metadata(path)?.is_dir() {
        return fs::remove_dir(path);
    }
    fs::remove_file(path)
}

fn projection_identity(path: &Path) -> Result<Option<String>> {
    #[cfg(windows)]
    {
        windows::directory_identity(path).map(Some)
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        Ok(None)
    }
}

fn copy_identity_matches(path: &Path, expected: Option<&str>) -> bool {
    match (projection_identity(path), expected) {
        (Ok(Some(actual)), Some(expected)) => actual == expected,
        _ => false,
    }
}

fn recovery_error() -> Error {
    Error::new(
        "PROJECTION_RECOVERY",
        "投影已部分创建但身份或清理未确认；登记与源目录已保留，请先 check 并手动核对。",
    )
}
