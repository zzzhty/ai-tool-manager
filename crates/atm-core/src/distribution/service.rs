//! One application service for CLI and desktop; Python belongs only to opted-in payloads.
use super::{
    adapters, hooks, runtime, source,
    transaction::{self, Change, Lock, Node},
};
use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Receipt {
    target: String,
    root: PathBuf,
    source_identity: String,
    release_version: String,
    files: BTreeMap<PathBuf, String>,
    empty_directories: BTreeSet<PathBuf>,
    shared: BTreeMap<PathBuf, Value>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct State {
    schema_version: u32,
    product: String,
    source_identity: String,
    release_version: String,
    receipts: BTreeMap<String, Receipt>,
    runtimes: BTreeMap<String, runtime::PreparedRuntime>,
    hooks: Option<hooks::HookOwnership>,
    adopted_legacy: Option<String>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Plan {
    pub operation: String,
    pub targets: Vec<String>,
    pub files: Vec<PathBuf>,
    #[serde(skip)]
    home: PathBuf,
    #[serde(skip)]
    changes: Vec<Change>,
    #[serde(skip)]
    guards: Vec<Change>,
}
struct AdoptionPlan {
    legacy_product: String,
    handoff_identity: String,
    targets: BTreeMap<String, PathBuf>,
    retired_missing_targets: BTreeMap<String, PathBuf>,
    changes: Vec<Change>,
}
#[derive(Clone, Debug)]
pub struct Service {
    home: PathBuf,
    user: PathBuf,
    inherit_environment: bool,
    target_roots: BTreeMap<String, PathBuf>,
}
mod relocation;
pub use relocation::RelocationPlan;

fn invalid() -> Error {
    Error::new(
        "HARNESS_STATE_INVALID",
        "Rust 分发记录无效或存在未知所有权；未修改安装。",
    )
}
fn uninstalled() -> Error {
    Error::new(
        "HARNESS_NOT_INSTALLED",
        "尚未准备 Rust 分发缓存；请执行 atm harness bootstrap，旧安装请显式交接。",
    )
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn encode(value: &impl Serialize) -> Result<Vec<u8>> {
    serde_json::to_vec_pretty(value).map_err(|_| invalid())
}
impl Service {
    pub fn new(home: PathBuf, user: PathBuf) -> Result<Self> {
        transaction::safe_path(&home.join("state/distribution.json"))?;
        transaction::safe_path(&user.join(".atm-check"))?;
        Ok(Self {
            home,
            user,
            inherit_environment: false,
            target_roots: BTreeMap::new(),
        })
    }
    pub fn from_environment() -> Result<Self> {
        let user = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
            .ok_or_else(invalid)?;
        let home =
            crate::harness::resolve_manager_home(std::env::var_os("ATM_HOME").as_deref(), &user);
        let mut service = Self::new(home, user)?;
        service.inherit_environment = true;
        Ok(service)
    }
    pub fn with_environment(mut self) -> Self {
        self.inherit_environment = true;
        self
    }
    pub fn with_target_roots(mut self, roots: BTreeMap<String, PathBuf>) -> Self {
        self.target_roots = roots;
        self
    }
    fn state_path(&self) -> PathBuf {
        self.home.join("state/distribution.json")
    }
    fn read_state(&self) -> Result<Option<State>> {
        self.relocation_guard()?;
        let Some(bytes) = transaction::file_bytes(&self.state_path())? else {
            return Ok(None);
        };
        let state = decode_state(&bytes)?;
        if self.home.join("state/manager.json").exists()
            || self.home.join("state/desired.json").exists()
        {
            return Err(Error::new(
                "HARNESS_DUAL_OWNER",
                "检测到旧引擎与 Rust 分发同时声明所有权；已停止操作。",
            ));
        }
        Ok(Some(state))
    }
    fn state(&self) -> Result<State> {
        self.read_state()?.ok_or_else(uninstalled)
    }
    fn root(&self, target: &str) -> Result<(String, PathBuf)> {
        let tool = crate::tool_catalog::find(target)
            .map_err(|_| Error::new("HARNESS_REQUEST", "未知 harness 名称。"))?;
        let skills = if let Some(path) = self.target_roots.get(tool.id) {
            path.clone()
        } else {
            tool.resolve(&self.user, self.inherit_environment)?
        };
        transaction::safe_path(&skills.join(".atm-check"))?;
        let skills = physical_path(&skills)?;
        let manager = physical_path(&self.home)?;
        if physical_overlap(&skills, &manager) {
            return Err(invalid());
        }
        Ok((tool.id.to_owned(), skills))
    }
    fn cache(&self, identity: &str) -> PathBuf {
        self.home.join("cache/content").join(identity)
    }
    fn bundle(&self, state: &State) -> Result<source::Bundle> {
        let bundle = source::load(&self.cache(&state.source_identity))?;
        if bundle.identity != state.source_identity
            || transaction::file_bytes(
                &self
                    .cache(&state.source_identity)
                    .join("canonical-catalog.json"),
            )? != Some(encode(&bundle.catalog)?)
        {
            return Err(invalid());
        }
        Ok(bundle)
    }
    fn cached_bundle_exists(&self, bundle: &source::Bundle) -> Result<bool> {
        let final_path = self.cache(&bundle.identity);
        transaction::safe_path(&final_path.join("distribution-manifest.json"))?;
        if final_path.exists() {
            let cached = source::load(&final_path)?;
            if cached.identity != bundle.identity
                || transaction::file_bytes(&final_path.join("canonical-catalog.json"))?
                    != Some(encode(&bundle.catalog)?)
            {
                return Err(invalid());
            }
            return Ok(true);
        }
        Ok(false)
    }
    fn cache_bundle(&self, bundle: &source::Bundle) -> Result<PathBuf> {
        let final_path = self.cache(&bundle.identity);
        if self.cached_bundle_exists(bundle)? {
            return Ok(final_path);
        }
        let stage = self
            .home
            .join("cache/content")
            .join(format!(".stage-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&stage)?;
        let result = (|| {
            for directory in bundle.manifest["directories"]
                .as_array()
                .into_iter()
                .flatten()
            {
                fs::create_dir_all(stage.join(directory.as_str().ok_or_else(invalid)?))?;
            }
            for (path, bytes) in &bundle.files {
                transaction::atomic_write(&stage.join(path), bytes)?;
            }
            if bundle.manifest["schemaVersion"] == 1 {
                transaction::atomic_write(
                    &stage.join("distribution-manifest.json"),
                    &encode(&bundle.manifest)?,
                )?;
            }
            transaction::atomic_write(
                &stage.join("canonical-catalog.json"),
                &encode(&bundle.catalog)?,
            )?;
            if source::load(&stage)?.identity != bundle.identity {
                return Err(invalid());
            }
            fs::rename(&stage, &final_path)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_dir_all(&stage);
        }
        result?;
        Ok(final_path)
    }
    pub fn bootstrap(&self, source_root: &Path, adopt_legacy: bool) -> Result<Value> {
        self.relocation_guard()?;
        let bundle = source::load(source_root)?;
        let _lock = Lock::acquire(&self.home)?;
        if transaction::pending(&self.home) {
            return Err(Error::new(
                "HARNESS_RECOVERY_REQUIRED",
                "先恢复未完成的 Rust 分发事务。",
            ));
        }
        let previous = self.read_state()?;
        if previous.as_ref().is_some_and(|state| state.hooks.is_some()) {
            return Err(Error::new("HARNESS_HOOK_RETIREMENT_REQUIRED", "更新内容前请先执行 atm uninstall hooks --harness codex，退役已记录的 skill-watcher hooks。"));
        }
        if previous.is_none()
            && (self.home.join("state/manager.json").exists()
                || self.home.join("state/desired.json").exists()
                || self.home.join("repo/scripts/engine.py").exists()
                || self.home.join("repo/scripts/omh.py").exists()
                || self.home.join("state/install.json").exists())
        {
            if !adopt_legacy {
                return Err(Error::new(
                    "HARNESS_LEGACY_HANDOFF_REQUIRED",
                    "检测到旧 Python 分发所有权；请显式执行 atm harness adopt。",
                ));
            }
            return self.apply_adoption(&bundle, &[]);
        }
        self.cache_bundle(&bundle)?;
        let mut next = previous.unwrap_or(State {
            schema_version: 1,
            product: "atm-harness".into(),
            source_identity: bundle.identity.clone(),
            release_version: bundle.release.clone(),
            receipts: BTreeMap::new(),
            runtimes: BTreeMap::new(),
            hooks: None,
            adopted_legacy: None,
        });
        next.source_identity = bundle.identity;
        next.release_version = bundle.release;
        let change = Change {
            path: self.state_path(),
            before: transaction::snapshot(&self.state_path())?,
            after: Some(Node::File(encode(&next)?)),
        };
        transaction::apply(&self.home, vec![change])?;
        self.status()
    }
    /// Import is an inactive cache operation. Selecting a source and applying to
    /// clients remain explicit sync and plan/apply operations.
    pub fn import_content(
        &self,
        lock: &source::hub::ContentLock,
        archive: Option<&Path>,
    ) -> Result<Value> {
        self.relocation_guard()?;
        let _lock = Lock::acquire(&self.home)?;
        if transaction::pending(&self.home) {
            return Err(Error::new(
                "HARNESS_RECOVERY_REQUIRED",
                "先恢复未完成的 Rust 分发事务。",
            ));
        }
        self.read_state()?;
        let output = self.cache(&lock.content_identity);
        let bundle = if let Some(archive) = archive {
            source::hub::import_archive(archive, lock, &output)?
        } else {
            source::hub::fetch(lock, &output)?
        };
        Ok(
            json!({"imported":true,"selected":false,"source":output,"contentIdentity":bundle.identity,"releaseVersion":bundle.release,"hooksEnabled":false}),
        )
    }
    pub fn status(&self) -> Result<Value> {
        let Some(state) = self.read_state()? else {
            return Ok(
                json!({"product":"atm-harness","observation":"recorded-state-only","manager":null,"desiredHarnesses":[],"harnessReceipts":{},"operation":if transaction::pending(&self.home){json!({"command":"recover"})}else{Value::Null},"worktreeClean":null}),
            );
        };
        let mut receipts = serde_json::Map::new();
        for receipt in state.receipts.values() {
            receipts.insert(receipt.target.clone(),json!([{"harness":receipt.target,"root":receipt.root,"status":"ready","releaseVersion":receipt.release_version,"sourceIdentity":receipt.source_identity}]));
        }
        Ok(
            json!({"product":"atm-harness","observation":"recorded-state-only","manager":{"product":"atm-harness","status":if transaction::pending(&self.home){"degraded"}else{"ready"},"channel":"embedded","releaseVersion":state.release_version,"revision":state.source_identity,"repository":self.cache(&state.source_identity)},"desiredHarnesses":state.receipts.values().map(|r|r.target.clone()).collect::<Vec<_>>(),"harnessReceipts":receipts,"operation":if transaction::pending(&self.home){json!({"command":"recover"})}else{Value::Null},"worktreeClean":null,"runtimes":state.runtimes,"hooksEnabled":state.hooks.is_some()}),
        )
    }
    pub fn plan(&self, operation: &str, targets: &[String]) -> Result<Plan> {
        self.relocation_guard()?;
        if !["install", "refresh", "repair", "remove"].contains(&operation) || targets.is_empty() {
            return Err(Error::new(
                "HARNESS_REQUEST",
                "请指定支持的操作和至少一个 harness。",
            ));
        }
        if self.home.join("state/manager.json").exists()
            || self.home.join("state/desired.json").exists()
        {
            return Err(Error::new(
                "HARNESS_DUAL_OWNER",
                "旧引擎与 Rust 分发同时声明所有权；操作已停止。",
            ));
        }
        let original = transaction::snapshot(&self.state_path())?;
        let state: State = match &original {
            Some(Node::File(bytes)) => decode_state(bytes)?,
            _ => return Err(uninstalled()),
        };
        if state.schema_version != 1 || state.product != "atm-harness" {
            return Err(invalid());
        }
        let bundle = if operation == "remove" {
            None
        } else {
            Some(self.bundle(&state)?)
        };
        self.plan_from_state(operation, targets, original, state, bundle)
    }
    fn plan_from_state(
        &self,
        operation: &str,
        targets: &[String],
        original: Option<Node>,
        mut state: State,
        bundle: Option<source::Bundle>,
    ) -> Result<Plan> {
        let mut changes = Vec::new();
        let mut guards = Vec::new();
        let mut selected = BTreeSet::new();
        let mut canonical = Vec::new();
        for target in targets {
            let (id, skills) = self.root(target)?;
            let root = skills.parent().ok_or_else(invalid)?.to_path_buf();
            let key = physical_key(&root);
            if !selected.insert(key.clone()) {
                return Err(Error::new(
                    "HARNESS_OWNER_CONFLICT",
                    "多个 harness 解析到同一物理目标；每个目标仅允许一个 owner。",
                ));
            }
            if state
                .receipts
                .values()
                .any(|r| physical_key(&r.root) != key && physical_overlap(&root, &r.root))
            {
                return Err(Error::new(
                    "HARNESS_OWNER_CONFLICT",
                    "分发目标与现有受管目标重叠。",
                ));
            }
            let previous = state.receipts.get(&key).cloned();
            if previous.as_ref().is_some_and(|r| r.target != id) {
                return Err(Error::new(
                    "HARNESS_OWNER_CONFLICT",
                    "该物理目标已由另一个 harness receipt 管理。",
                ));
            }
            let native_guards = if id == "codex" && operation != "remove" {
                if let Some(receipt) = &previous {
                    codex_shape(receipt, operation == "repair")?
                } else {
                    Vec::new()
                }
            } else {
                Vec::new()
            };
            canonical.push(id.clone());
            let mut slots = BTreeSet::new();
            if let Some(receipt) = &previous {
                for path in receipt.files.keys().chain(receipt.empty_directories.iter()) {
                    if let Some(slot) = managed_slot(&id, &root, &skills, path) {
                        slots.insert(slot);
                    }
                }
            }
            if operation == "remove" {
                if let Some(receipt) = previous {
                    for (path, hash) in receipt.files {
                        let before = transaction::snapshot(&path)?;
                        if let Some(Node::File(bytes)) = &before {
                            if digest(bytes) != hash {
                                return Err(transaction::conflict());
                            }
                        } else if before.is_some() {
                            return Err(transaction::conflict());
                        }
                        changes.push(Change {
                            path,
                            before,
                            after: None,
                        });
                    }
                    for path in receipt.empty_directories {
                        let before = transaction::snapshot(&path)?;
                        if before.is_some() && before != Some(Node::Directory(BTreeMap::new())) {
                            return Err(transaction::conflict());
                        }
                        changes.push(Change {
                            path,
                            before,
                            after: None,
                        });
                    }
                    for (path, ownership) in receipt.shared {
                        let current = transaction::file_bytes(&path)?;
                        let restored = adapters::restore_shared(current.as_deref(), &ownership)?;
                        changes.push(Change {
                            path,
                            before: current.map(Node::File),
                            after: restored.map(Node::File),
                        });
                    }
                    state.receipts.remove(&key);
                }
                group_changes(&mut changes, &slots)?;
                continue;
            }
            let bundle = bundle.as_ref().unwrap();
            for skill in bundle.catalog["skills"].as_array().into_iter().flatten() {
                if let Some(name) = skill["name"].as_str() {
                    if fs::symlink_metadata(self.user.join(".agents/skills").join(name)).is_ok() {
                        return Err(Error::new("HARNESS_EXCLUDED_ROOT","共享 .agents/skills 中存在同名技能；请先显式处理重复发现，不会自动清理。"));
                    }
                }
            }
            let empty = BTreeMap::new();
            let desired = adapters::plan_owned(
                bundle,
                &self.cache(&state.source_identity),
                &id,
                &skills,
                previous.as_ref().map(|r| &r.shared).unwrap_or(&empty),
            )?;
            for path in desired
                .artifacts
                .iter()
                .map(|a| &a.path)
                .chain(desired.empty_directories.iter())
            {
                if let Some(slot) = managed_slot(&id, &root, &skills, path) {
                    if !slots.contains(&slot) && transaction::snapshot(&slot)?.is_some() {
                        return Err(transaction::conflict());
                    }
                    slots.insert(slot);
                }
            }
            for (path, before) in &desired.observed {
                let value = before.clone().map(Node::File);
                if transaction::snapshot(path)? != value {
                    return Err(transaction::conflict());
                }
                if !changes.iter().any(|c: &Change| c.path == *path) {
                    changes.push(Change {
                        path: path.clone(),
                        before: value.clone(),
                        after: value,
                    });
                }
            }
            let empty_directories: BTreeSet<_> = desired.empty_directories.into_iter().collect();
            for path in &empty_directories {
                let before = transaction::snapshot(path)?;
                if before.is_some()
                    && (before != Some(Node::Directory(BTreeMap::new()))
                        || !previous
                            .as_ref()
                            .is_some_and(|r| r.empty_directories.contains(path)))
                {
                    return Err(transaction::conflict());
                }
                changes.push(Change {
                    path: path.clone(),
                    before,
                    after: Some(Node::Directory(BTreeMap::new())),
                });
            }
            if let Some(old) = &previous {
                for path in &old.empty_directories {
                    if !empty_directories.contains(path)
                        && !desired.artifacts.iter().any(|a| a.path.starts_with(path))
                    {
                        let before = transaction::snapshot(path)?;
                        if before.is_some() && before != Some(Node::Directory(BTreeMap::new())) {
                            return Err(transaction::conflict());
                        }
                        changes.push(Change {
                            path: path.clone(),
                            before,
                            after: None,
                        });
                    }
                }
            }
            let mut files = BTreeMap::new();
            let mut shared = BTreeMap::new();
            for artifact in desired.artifacts {
                if !artifact.path.starts_with(&root) {
                    return Err(invalid());
                }
                let before = transaction::snapshot(&artifact.path)?;
                let owned = previous.as_ref().and_then(|r| r.files.get(&artifact.path));
                match (&before, owned) {
                    (None, _) => (),
                    (Some(Node::File(bytes)), Some(hash)) if digest(bytes) == *hash => (),
                    _ => return Err(transaction::conflict()),
                }
                files.insert(artifact.path.clone(), digest(&artifact.bytes));
                let after = Some(Node::File(artifact.bytes));
                changes.push(Change {
                    path: artifact.path,
                    before,
                    after,
                });
            }
            if let Some(previous) = &previous {
                for (path, hash) in &previous.files {
                    if !files.contains_key(path) {
                        let before = transaction::snapshot(path)?;
                        if let Some(Node::File(bytes)) = &before {
                            if digest(bytes) != *hash {
                                return Err(transaction::conflict());
                            }
                        } else if before.is_some() {
                            return Err(transaction::conflict());
                        }
                        if before.is_some() {
                            changes.push(Change {
                                path: path.clone(),
                                before,
                                after: None,
                            });
                        }
                    }
                }
            }
            for entry in desired.shared {
                let path = entry.artifact.path;
                if !path.starts_with(&root) {
                    return Err(invalid());
                }
                if transaction::file_bytes(&path)? != entry.before {
                    return Err(transaction::conflict());
                }
                let before = entry.before.map(Node::File);
                let after = Some(Node::File(entry.artifact.bytes));
                shared.insert(path.clone(), entry.ownership);
                changes.push(Change {
                    path,
                    before,
                    after,
                });
            }
            group_changes(&mut changes, &slots)?;
            for guard in native_guards {
                if transaction::snapshot(&guard.path)? != guard.before {
                    return Err(transaction::conflict());
                }
                if let Some(change) = changes.iter().find(|c| c.path == guard.path) {
                    if change.before != guard.before {
                        return Err(transaction::conflict());
                    }
                }
                guards.push(guard);
            }
            state.receipts.insert(
                key,
                Receipt {
                    target: id,
                    root,
                    source_identity: state.source_identity.clone(),
                    release_version: state.release_version.clone(),
                    files,
                    empty_directories,
                    shared,
                },
            );
        }
        changes.push(Change {
            path: self.state_path(),
            before: original,
            after: Some(Node::File(encode(&state)?)),
        });
        let files = changes
            .iter()
            .filter(|c| c.before != c.after)
            .map(|c| c.path.clone())
            .collect();
        Ok(Plan {
            operation: operation.into(),
            targets: canonical,
            files,
            home: self.home.clone(),
            changes,
            guards,
        })
    }
    pub fn apply(&self, plan: Plan) -> Result<Value> {
        self.relocation_guard()?;
        if plan.home != self.home {
            return Err(invalid());
        }
        let _lock = Lock::acquire(&self.home)?;
        for guard in &plan.guards {
            if transaction::snapshot(&guard.path)? != guard.before {
                return Err(transaction::conflict());
            }
        }
        transaction::apply(&self.home, plan.changes)?;
        self.status()
    }
    pub fn execute(&self, operation: &str, targets: &[String]) -> Result<Value> {
        self.apply(self.plan(operation, targets)?)
    }
    pub fn recover(&self) -> Result<Value> {
        if let Some(result) = self.recover_relocation()? {
            return Ok(result);
        }
        self.relocation_guard()?;
        let _lock = Lock::acquire(&self.home)?;
        transaction::recover(&self.home)?;
        self.status()
    }
    pub fn diagnose(&self) -> Result<Value> {
        let state = self.state()?;
        let mut issues = Vec::new();
        if self.bundle(&state).is_err() {
            issues.push("content-cache-invalid".to_owned());
        }
        if transaction::pending(&self.home) {
            issues.push("recovery-required".into());
        }
        for receipt in state.receipts.values() {
            if receipt.target == "codex" && codex_shape(receipt, false).is_err() {
                issues.push("native-package-drift".into());
            }
            for (path, hash) in &receipt.files {
                if transaction::file_bytes(path)?.is_none_or(|bytes| digest(&bytes) != *hash) {
                    issues.push(format!("managed-file-drift:{}", path.display()));
                }
            }
            for (path, ownership) in &receipt.shared {
                if adapters::restore_shared(transaction::file_bytes(path)?.as_deref(), ownership)
                    .is_err()
                {
                    issues.push(format!("shared-config-drift:{}", path.display()));
                }
            }
        }
        if self.check_hooks()?.get("passed").and_then(Value::as_bool) == Some(false) {
            issues.push("retired-hook-enabled-or-drift".into());
        }
        Ok(
            json!({"passed":issues.is_empty(),"exitCode":if issues.is_empty(){0}else{1},"issues":issues}),
        )
    }
    pub fn prepare_runtime(
        &self,
        group: &str,
        python: &Path,
        external_venv: Option<&Path>,
        offline: bool,
    ) -> Result<Value> {
        self.relocation_guard()?;
        let _lock = Lock::acquire(&self.home)?;
        if transaction::pending(&self.home) {
            return Err(Error::new(
                "HARNESS_RECOVERY_REQUIRED",
                "先恢复未完成的 Rust 分发事务。",
            ));
        }
        let mut state = self.state()?;
        let bundle = self.bundle(&state)?;
        let spec: runtime::RuntimeSpec = serde_json::from_value(
            bundle.manifest["runtimeGroups"]
                .as_array()
                .and_then(|v| v.iter().find(|g| g["id"].as_str() == Some(group)))
                .cloned()
                .ok_or_else(|| {
                    Error::new("HARNESS_RUNTIME_SPEC", "没有声明该 payload runtime 组。")
                })?,
        )
        .map_err(|_| invalid())?;
        let prepared = runtime::prepare(
            &self.home,
            &self.cache(&state.source_identity),
            &spec,
            python,
            external_venv,
            offline,
        )?;
        state.runtimes.insert(group.into(), prepared.clone());
        transaction::apply(
            &self.home,
            vec![Change {
                path: self.state_path(),
                before: transaction::snapshot(&self.state_path())?,
                after: Some(Node::File(encode(&state)?)),
            }],
        )?;
        Ok(json!({"prepared":prepared,"hooksEnabled":state.hooks.is_some()}))
    }
    pub fn hooks(&self, enable: bool, dry_run: bool) -> Result<Value> {
        if enable {
            return Err(hooks::retired());
        }
        self.relocation_guard()?;
        let _lock = if dry_run {
            None
        } else {
            Some(Lock::acquire(&self.home)?)
        };
        if transaction::pending(&self.home) {
            return Err(Error::new(
                "HARNESS_RECOVERY_REQUIRED",
                "先恢复未完成的 Rust 分发事务。",
            ));
        }
        let mut state = self.state()?;
        let (_, skills) = self.root("codex")?;
        let target = skills.parent().ok_or_else(invalid)?.join("hooks.json");
        let current = transaction::file_bytes(&target)?;
        let plan = hooks::plan_removal(
            &target,
            current.as_deref(),
            state.hooks.as_ref(),
            &self.cache(&state.source_identity),
        )?;
        if dry_run {
            return Ok(
                json!({"dryRun":true,"enabled":enable,"changes":plan.artifact.map(|a|a.path)}),
            );
        }
        let mut changes = Vec::new();
        if let Some(artifact) = plan.artifact {
            changes.push(Change {
                path: target,
                before: current.map(Node::File),
                after: Some(Node::File(artifact.bytes)),
            });
        }
        state.hooks = plan.ownership;
        changes.push(Change {
            path: self.state_path(),
            before: transaction::snapshot(&self.state_path())?,
            after: Some(Node::File(encode(&state)?)),
        });
        transaction::apply(&self.home, changes)?;
        Ok(json!({"enabled":state.hooks.is_some()}))
    }
    pub fn check_hooks(&self) -> Result<Value> {
        let state = self.state()?;
        let Some(owner) = state.hooks.as_ref() else {
            return Ok(json!({"passed":true,"enabled":false,"exitCode":0}));
        };
        let valid = (|| -> Result<()> {
            let current = transaction::file_bytes(&owner.target)?;
            hooks::plan_removal(
                &owner.target,
                current.as_deref(),
                Some(owner),
                &owner.bundle_root,
            )?;
            Ok(())
        })()
        .is_ok();
        Ok(
            json!({"passed":false,"enabled":true,"retired":true,"ownershipVerified":valid,"issue":if valid{"retired-hook-enabled"}else{"hook-drift"},"exitCode":1}),
        )
    }
    /// Read-only adoption preview. A later apply rebuilds this same plan under
    /// the manager lock; preview does not reserve ownership or promise that
    /// independently edited targets will still match.
    pub fn preview_adopt(&self, source_root: &Path, retire_missing: &[String]) -> Result<Value> {
        let bundle = source::load(source_root)?;
        let cached = self.cached_bundle_exists(&bundle)?;
        let plan = self.build_adoption_plan(&bundle, retire_missing)?;
        let changes = plan
            .changes
            .iter()
            .map(|change| {
                Ok(json!({
                    "path": change.path,
                    "action": if change.before == change.after { "observe" }
                        else if change.before.is_none() { "create" }
                        else if change.after.is_none() { "remove" } else { "replace" },
                    "before": node_summary(change.before.as_ref())?,
                    "after": node_summary(change.after.as_ref())?,
                }))
            })
            .collect::<Result<Vec<Value>>>()?;
        Ok(json!({
            "operation": "adopt", "dryRun": true, "managerHome": self.home,
            "legacyProduct": plan.legacy_product, "handoffIdentity": plan.handoff_identity,
            "sourceIdentity": bundle.identity, "releaseVersion": bundle.release,
            "targets": plan.targets.into_iter().map(|(harness, root)| json!({"harness":harness,"root":root})).collect::<Vec<_>>(),
            "retiredMissingTargets": plan.retired_missing_targets,
            "cache": {"path": self.cache(&bundle.identity), "action": if cached {"reuse"} else {"create"}, "payloadFiles":bundle.files.len()},
            "hooksEnabledAfter": false, "changes": changes,
        }))
    }
    pub fn adopt(&self, source_root: &Path, retire_missing: &[String]) -> Result<Value> {
        self.relocation_guard()?;
        let bundle = source::load(source_root)?;
        let _lock = Lock::acquire(&self.home)?;
        self.apply_adoption(&bundle, retire_missing)
    }
    fn apply_adoption(&self, bundle: &source::Bundle, retire_missing: &[String]) -> Result<Value> {
        // Both entry points hold the common predecessor/Rust manager lock.
        // Build and validate before creating a cache or touching target state.
        let plan = self.build_adoption_plan(bundle, retire_missing)?;
        self.cache_bundle(bundle)?;
        transaction::apply(&self.home, plan.changes)?;
        self.status()
    }
    fn build_adoption_plan(
        &self,
        bundle: &source::Bundle,
        retire_missing: &[String],
    ) -> Result<AdoptionPlan> {
        self.relocation_guard()?;
        if transaction::pending(&self.home) {
            return Err(Error::new(
                "HARNESS_RECOVERY_REQUIRED",
                "先恢复未完成的 Rust 分发事务。",
            ));
        }
        let handoff = super::legacy::inspect(&self.home)?.ok_or_else(|| {
            Error::new(
                "HARNESS_LEGACY_INVALID",
                "未检测到可验证的旧分发状态；未进行交接。",
            )
        })?;
        let mut allowed = BTreeMap::new();
        let mut physical = BTreeSet::new();
        for target in &handoff.desired_harnesses {
            let (id, skills) = self.root(target)?;
            let root = skills.parent().ok_or_else(invalid)?.to_path_buf();
            if !physical.insert(root.clone()) {
                return Err(Error::new(
                    "HARNESS_OWNER_CONFLICT",
                    "旧记录含同一物理目标的多个所有者；请先明确交接目标。",
                ));
            }
            allowed.insert(id, root);
        }
        let mut retired_missing_targets = BTreeMap::new();
        for target in retire_missing {
            let tool = crate::tool_catalog::find(target)
                .map_err(|_| Error::new("HARNESS_REQUEST", "未知退役目标。"))?;
            let root = allowed.get(tool.id).ok_or_else(|| {
                Error::new("HARNESS_REQUEST", "退役目标必须属于已记录的旧分发选择。")
            })?;
            if retired_missing_targets
                .insert(tool.id.to_owned(), root.clone())
                .is_some()
            {
                return Err(Error::new("HARNESS_REQUEST", "退役目标不能重复。"));
            }
            // Check the entire root, not just managed files. Symlinks (including
            // dangling ones), empty directories and user-only roots all count as present.
            match fs::symlink_metadata(root) {
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => (),
                Err(error) => return Err(error.into()),
                Ok(_) => {
                    return Err(Error::new(
                        "HARNESS_RETIRE_ROOT_PRESENT",
                        "显式退役要求旧目标根目录完全缺失；现有文件保持原状。",
                    ))
                }
            }
        }
        // Inspect all recorded roots before excluding any: retirement must not
        // bypass independent root binding or predecessor ownership evidence.
        let old_targets = super::legacy::inspect_targets(&self.home, &handoff, &allowed)?;
        allowed.retain(|target, _| !retired_missing_targets.contains_key(target));
        let cache = self.cache(&bundle.identity);
        let mut changes = Vec::new();
        let mut state = State {
            schema_version: 1,
            product: "atm-harness".into(),
            source_identity: bundle.identity.clone(),
            release_version: bundle.release.clone(),
            receipts: BTreeMap::new(),
            runtimes: BTreeMap::new(),
            hooks: None,
            adopted_legacy: Some(handoff.identity.clone()),
        };
        for (target, root) in &allowed {
            let (_, skills) = self.root(target)?;
            let mut previous = BTreeMap::new();
            if target == "codex" {
                if let Some(evidence) = super::legacy::codex_evidence(&handoff, root)? {
                    let ownership = adapters::legacy_codex_ownership(
                        &evidence.config_bytes,
                        &evidence.marketplace,
                        &evidence.source_root,
                        &evidence.plugins,
                    )?;
                    previous.insert(evidence.config_path, ownership);
                }
            }
            let desired = adapters::plan_owned(bundle, &cache, target, &skills, &previous)?;
            let empty_directories: BTreeSet<_> =
                desired.empty_directories.iter().cloned().collect();
            let mut remaining_dirs = empty_directories.clone();
            let mut remaining: BTreeMap<PathBuf, Vec<u8>> = desired
                .artifacts
                .into_iter()
                .map(|a| (a.path, a.bytes))
                .collect();
            let files = remaining
                .iter()
                .map(|(p, b)| (p.clone(), digest(b)))
                .collect();
            for old in old_targets.iter().filter(|old| old.harness == *target) {
                match old.kind.as_str() {
                    "symlink" => {
                        let before =
                            Some(Node::Symlink(old.link_target.clone().ok_or_else(invalid)?));
                        let after = if old.files.is_empty() {
                            remaining.remove(&old.path).map(Node::File)
                        } else {
                            let subtree: Vec<_> = remaining
                                .keys()
                                .filter(|p| p.starts_with(&old.path))
                                .cloned()
                                .collect();
                            if subtree.is_empty() {
                                None
                            } else {
                                let mut tree = BTreeMap::new();
                                for path in subtree {
                                    let bytes = remaining.remove(&path).unwrap();
                                    insert_tree(
                                        &mut tree,
                                        path.strip_prefix(&old.path).map_err(|_| invalid())?,
                                        bytes,
                                    )?;
                                }
                                let dirs: Vec<_> = remaining_dirs
                                    .iter()
                                    .filter(|p| p.starts_with(&old.path))
                                    .cloned()
                                    .collect();
                                for directory in dirs {
                                    insert_directory(
                                        &mut tree,
                                        directory.strip_prefix(&old.path).map_err(|_| invalid())?,
                                    )?;
                                    remaining_dirs.remove(&directory);
                                }
                                Some(Node::Directory(tree))
                            }
                        };
                        changes.push(Change {
                            path: old.path.clone(),
                            before,
                            after,
                        });
                    }
                    "file" => {
                        let before = Some(Node::File(old.bytes.clone().ok_or_else(invalid)?));
                        let after = remaining.remove(&old.path).map(Node::File);
                        changes.push(Change {
                            path: old.path.clone(),
                            before,
                            after,
                        });
                    }
                    "directory" => {
                        for (relative, bytes) in &old.files {
                            let path = old.path.join(relative);
                            let before = Some(Node::File(bytes.clone()));
                            let after = remaining.remove(&path).map(Node::File);
                            changes.push(Change {
                                path,
                                before,
                                after,
                            });
                        }
                    }
                    _ => return Err(invalid()),
                }
            }
            for path in remaining_dirs {
                let before = transaction::snapshot(&path)?;
                if before.is_some() {
                    return Err(transaction::conflict());
                }
                changes.push(Change {
                    path,
                    before,
                    after: Some(Node::Directory(BTreeMap::new())),
                });
            }
            for (path, bytes) in remaining {
                let before = transaction::snapshot(&path)?;
                if before.is_some() {
                    return Err(transaction::conflict());
                }
                changes.push(Change {
                    path,
                    before,
                    after: Some(Node::File(bytes)),
                });
            }
            let mut shared = BTreeMap::new();
            for entry in desired.shared {
                let path = entry.artifact.path;
                let before = entry.before.map(Node::File);
                if transaction::snapshot(&path)? != before {
                    return Err(transaction::conflict());
                }
                shared.insert(path.clone(), entry.ownership);
                changes.push(Change {
                    path,
                    before,
                    after: Some(Node::File(entry.artifact.bytes)),
                });
            }
            for (path, bytes) in desired.observed {
                let node = bytes.map(Node::File);
                if !changes.iter().any(|c| c.path == path) {
                    changes.push(Change {
                        path,
                        before: node.clone(),
                        after: node,
                    });
                }
            }
            state.receipts.insert(
                physical_key(root),
                Receipt {
                    target: target.clone(),
                    root: root.clone(),
                    source_identity: bundle.identity.clone(),
                    release_version: bundle.release.clone(),
                    files,
                    empty_directories,
                    shared,
                },
            );
        }
        let (_, codex_skills) = self.root("codex")?;
        {
            if let Some(change) = super::legacy::hook_retirement(
                &handoff,
                codex_skills.parent().ok_or_else(invalid)?,
            )? {
                changes.push(Change {
                    path: change.path,
                    before: Some(Node::File(change.before)),
                    after: Some(Node::File(change.after)),
                });
            }
        }
        for artifact in handoff.archives {
            changes.push(Change {
                path: artifact.path,
                before: None,
                after: Some(Node::File(artifact.bytes)),
            });
        }
        if !retired_missing_targets.is_empty() {
            changes.push(Change {
                path: self
                    .home
                    .join("state/legacy-handoff")
                    .join(&handoff.identity)
                    .join("retired-missing-targets.json"),
                before: None,
                after: Some(Node::File(encode(&json!({
                    "schemaVersion": 1,
                    "reason": "explicit-missing-root-retirement",
                    "handoffIdentity": handoff.identity,
                    "targets": retired_missing_targets,
                }))?)),
            });
        }
        for file in handoff.retire {
            changes.push(Change {
                path: file.path,
                before: Some(Node::File(file.bytes)),
                after: None,
            });
        }
        changes.push(Change {
            path: self.state_path(),
            before: None,
            after: Some(Node::File(encode(&state)?)),
        });
        // Persist absence observations in the existing journal. Preflight and
        // the final forward steps recheck them; recovery never deletes a root
        // that appeared independently after preview or interruption.
        for root in retired_missing_targets.values() {
            changes.push(Change {
                path: root.clone(),
                before: None,
                after: None,
            });
        }
        transaction::validate_plan(&self.home, &changes)?;
        Ok(AdoptionPlan {
            legacy_product: handoff.product,
            handoff_identity: handoff.identity,
            targets: allowed,
            retired_missing_targets,
            changes,
        })
    }
}

fn node_summary(node: Option<&Node>) -> Result<Value> {
    match node {
        None => Ok(Value::Null),
        Some(Node::File(bytes)) => Ok(
            json!({"kind":"file","sha256":digest(bytes),"bytes":bytes.len(),"hashAlgorithm":"sha256"}),
        ),
        Some(Node::Symlink(target)) => Ok(
            json!({"kind":"symlink","target":target,"sha256":digest(target.to_str().ok_or_else(invalid)?.as_bytes()),"hashAlgorithm":"sha256-utf8-link-v1"}),
        ),
        Some(node @ Node::Directory(entries)) => Ok(
            json!({"kind":"directory","sha256":digest(&encode(node)?),"entries":entries.len(),"hashAlgorithm":"sha256-atm-node-json-v1"}),
        ),
    }
}
/// Local skill tools consult the same receipt authority before mutating copies.
pub fn owns_path(home: &Path, path: &Path) -> bool {
    let bytes = match fs::read(home.join("state/distribution.json")) {
        Ok(v) => v,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return false,
        Err(_) => return true,
    };
    let state: State = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(_) => return true,
    };
    // Resolve platform aliases in the parent while retaining the leaf itself:
    // a user-replaced skill symlink still belongs to its recorded location.
    let physical = match (path.parent(), path.file_name()) {
        (Some(parent), Some(leaf)) => physical_path(parent).map(|parent| parent.join(leaf)),
        _ => physical_path(path),
    };
    let Ok(physical) = physical else {
        return true;
    };
    let candidates = [physical_key(path), physical_key(&physical)];
    state.receipts.values().any(|r| {
        r.files
            .keys()
            .chain(r.shared.keys())
            .chain(r.empty_directories.iter())
            .any(|p| {
                let key = physical_key(p);
                candidates
                    .iter()
                    .any(|candidate| Path::new(&key).starts_with(Path::new(candidate)))
            })
    })
}

fn insert_tree(tree: &mut BTreeMap<String, Node>, path: &Path, bytes: Vec<u8>) -> Result<()> {
    let mut parts = path.components();
    let name = parts
        .next()
        .and_then(|c| c.as_os_str().to_str())
        .ok_or_else(invalid)?
        .to_owned();
    let rest = parts.as_path();
    if rest.as_os_str().is_empty() {
        if tree.insert(name, Node::File(bytes)).is_some() {
            return Err(invalid());
        }
        return Ok(());
    }
    let entry = tree
        .entry(name)
        .or_insert_with(|| Node::Directory(BTreeMap::new()));
    let Node::Directory(child) = entry else {
        return Err(invalid());
    };
    insert_tree(child, rest, bytes)
}

fn decode_state(bytes: &[u8]) -> Result<State> {
    let state: State = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if state.schema_version != 1
        || state.product != "atm-harness"
        || state.source_identity.len() != 64
    {
        return Err(invalid());
    }
    let mut roots = BTreeSet::new();
    for (key, receipt) in &state.receipts {
        if key != &physical_key(&receipt.root)
            || !receipt.root.is_absolute()
            || !roots.insert(receipt.root.clone())
        {
            return Err(invalid());
        }
        for path in receipt
            .files
            .keys()
            .chain(receipt.shared.keys())
            .chain(receipt.empty_directories.iter())
        {
            transaction::safe_path(path)?;
            if !path.starts_with(&receipt.root) {
                return Err(invalid());
            }
        }
    }
    Ok(state)
}

fn physical_key(path: &Path) -> String {
    let key = path.to_string_lossy().into_owned();
    if cfg!(windows) {
        key.to_ascii_lowercase()
    } else {
        key
    }
}
fn physical_path(path: &Path) -> Result<PathBuf> {
    let mut parent = path;
    let mut tail = Vec::new();
    while !parent.exists() {
        tail.push(parent.file_name().ok_or_else(invalid)?.to_os_string());
        parent = parent.parent().ok_or_else(invalid)?;
    }
    let mut result = fs::canonicalize(parent)?;
    #[cfg(windows)]
    {
        use std::os::windows::ffi::{OsStrExt, OsStringExt};
        let units: Vec<u16> = result.as_os_str().encode_wide().collect();
        let extended: Vec<u16> = "\\\\?\\".encode_utf16().collect();
        let unc: Vec<u16> = "UNC\\".encode_utf16().collect();
        if units.starts_with(&extended) {
            let tail = &units[extended.len()..];
            let normalized = if tail.starts_with(&unc) {
                let mut p: Vec<u16> = "\\\\".encode_utf16().collect();
                p.extend_from_slice(&tail[unc.len()..]);
                p
            } else {
                tail.to_vec()
            };
            result = PathBuf::from(std::ffi::OsString::from_wide(&normalized));
        }
    }
    for name in tail.iter().rev() {
        result.push(name);
    }
    Ok(result)
}

fn insert_directory(tree: &mut BTreeMap<String, Node>, path: &Path) -> Result<()> {
    let mut parts = path.components();
    let Some(first) = parts.next() else {
        return Ok(());
    };
    let name = first.as_os_str().to_str().ok_or_else(invalid)?.to_owned();
    let entry = tree
        .entry(name)
        .or_insert_with(|| Node::Directory(BTreeMap::new()));
    let Node::Directory(child) = entry else {
        return Err(invalid());
    };
    insert_directory(child, parts.as_path())
}

fn managed_slot(target: &str, root: &Path, skills: &Path, path: &Path) -> Option<PathBuf> {
    let (base, depth) = if target == "codex" {
        (root.join("plugins/cache"), 3)
    } else {
        (skills.to_path_buf(), 1)
    };
    let relative = path.strip_prefix(&base).ok()?;
    let components: Vec<_> = relative.components().collect();
    if components.len() < depth {
        return None;
    }
    let mut slot = base;
    for part in components.iter().take(depth) {
        slot.push(part.as_os_str());
    }
    Some(slot)
}
fn tree_at<'a>(node: &'a Option<Node>, path: &Path) -> Option<&'a Node> {
    let mut current = node.as_ref()?;
    for part in path.components() {
        let Node::Directory(tree) = current else {
            return None;
        };
        current = tree.get(part.as_os_str().to_str()?)?;
    }
    Some(current)
}
fn tree_set(node: &mut Option<Node>, path: &Path, value: Option<Node>) -> Result<()> {
    if path.as_os_str().is_empty() {
        *node = value;
        return Ok(());
    }
    if node.is_none() {
        *node = Some(Node::Directory(BTreeMap::new()));
    }
    let Some(Node::Directory(tree)) = node else {
        return Err(transaction::conflict());
    };
    let mut parts = path.components();
    let name = parts
        .next()
        .and_then(|c| c.as_os_str().to_str())
        .ok_or_else(invalid)?
        .to_owned();
    let mut child = tree.remove(&name);
    tree_set(&mut child, parts.as_path(), value)?;
    if let Some(child) = child {
        tree.insert(name, child);
    }
    Ok(())
}
fn prune_empty(node: &mut Option<Node>) {
    if let Some(Node::Directory(tree)) = node {
        tree.retain(|_, child| {
            let mut wrapped = Some(child.clone());
            prune_empty(&mut wrapped);
            if let Some(value) = wrapped {
                *child = value;
                true
            } else {
                false
            }
        });
        if tree.is_empty() {
            *node = None;
        }
    }
}
fn group_changes(changes: &mut Vec<Change>, slots: &BTreeSet<PathBuf>) -> Result<()> {
    for slot in slots {
        let relevant: Vec<_> = changes
            .iter()
            .filter(|c| c.path.starts_with(slot))
            .cloned()
            .collect();
        if relevant.is_empty() {
            continue;
        }
        let before = transaction::snapshot(slot)?;
        // Mixed directories remain per-file operations: never recreate unowned
        // bytes or weaken their permissions/ACLs while updating managed files.
        if has_unowned(&before, slot, &relevant) {
            continue;
        }
        let mut after = before.clone();
        let mut keep_empty: Vec<_> = relevant
            .iter()
            .filter(|c| matches!(&c.after,Some(Node::Directory(entries)) if entries.is_empty()))
            .map(|c| c.path.clone())
            .collect();
        let mut existing_empty = Vec::new();
        collect_empty(&before, slot, &mut existing_empty);
        keep_empty.extend(existing_empty.into_iter().filter(|path| {
            !relevant
                .iter()
                .any(|c| c.path == *path && c.after.is_none())
        }));
        for change in &relevant {
            let relative = change.path.strip_prefix(slot).map_err(|_| invalid())?;
            if tree_at(&before, relative) != change.before.as_ref() {
                return Err(transaction::conflict());
            }
            tree_set(&mut after, relative, change.after.clone())?;
        }
        prune_empty(&mut after);
        for path in keep_empty {
            let relative = path.strip_prefix(slot).map_err(|_| invalid())?;
            match tree_at(&after, relative) {
                Some(Node::Directory(_)) => (),
                None => tree_set(&mut after, relative, Some(Node::Directory(BTreeMap::new())))?,
                _ => return Err(transaction::conflict()),
            }
        }
        changes.retain(|c| !c.path.starts_with(slot));
        changes.push(Change {
            path: slot.clone(),
            before,
            after,
        });
    }
    Ok(())
}

fn collect_empty(node: &Option<Node>, path: &Path, out: &mut Vec<PathBuf>) {
    if let Some(Node::Directory(tree)) = node {
        if tree.is_empty() {
            out.push(path.to_path_buf());
        } else {
            for (name, child) in tree {
                collect_empty(&Some(child.clone()), &path.join(name), out);
            }
        }
    }
}

fn physical_overlap(a: &Path, b: &Path) -> bool {
    let a = physical_key(a);
    let b = physical_key(b);
    let sep = if cfg!(windows) { "\\" } else { "/" };
    a == b
        || a.starts_with(&(b.trim_end_matches(['/', '\\']).to_owned() + sep))
        || b.starts_with(&(a.trim_end_matches(['/', '\\']).to_owned() + sep))
}
fn has_unowned(node: &Option<Node>, path: &Path, changes: &[Change]) -> bool {
    match node {
        None => false,
        Some(Node::Directory(tree)) => {
            if tree.is_empty() {
                return !changes.iter().any(|c| c.path == path);
            }
            tree.iter()
                .any(|(name, child)| has_unowned(&Some(child.clone()), &path.join(name), changes))
        }
        Some(_) => !changes.iter().any(|c| c.path == path),
    }
}
fn native_ignored(path: &Path) -> bool {
    path.components().any(|c| {
        c.as_os_str().to_str().is_some_and(|n| {
            matches!(
                n,
                "__pycache__"
                    | ".pytest_cache"
                    | ".mypy_cache"
                    | ".ruff_cache"
                    | ".git"
                    | ".venv"
                    | "node_modules"
                    | ".DS_Store"
            ) || n.ends_with(".pyc")
                || n.ends_with(".pyo")
        })
    })
}
fn check_native_node(node: &Node, path: &Path, slot: &Path, receipt: &Receipt) -> Result<()> {
    if matches!(node, Node::Symlink(_)) {
        return Err(transaction::conflict());
    }
    if native_ignored(path.strip_prefix(slot).map_err(|_| invalid())?) {
        return Ok(());
    }
    match node {
        Node::File(bytes) => {
            if receipt.files.get(path) != Some(&digest(bytes)) {
                return Err(transaction::conflict());
            }
        }
        Node::Directory(tree) => {
            if !receipt
                .files
                .keys()
                .chain(receipt.empty_directories.iter())
                .any(|p| p == path || p.starts_with(path))
            {
                return Err(transaction::conflict());
            }
            for (name, child) in tree {
                check_native_node(child, &path.join(name), slot, receipt)?;
            }
        }
        Node::Symlink(_) => unreachable!(),
    }
    Ok(())
}
fn codex_shape(receipt: &Receipt, allow_missing: bool) -> Result<Vec<Change>> {
    let mut slots = BTreeSet::new();
    for path in receipt.files.keys().chain(receipt.empty_directories.iter()) {
        if let Some(slot) = managed_slot("codex", &receipt.root, &receipt.root.join("skills"), path)
        {
            slots.insert(slot);
        }
    }
    let mut guards = Vec::new();
    for slot in slots {
        let node = transaction::snapshot(&slot)?;
        if let Some(node) = &node {
            check_native_node(node, &slot, &slot, receipt)?;
        } else if !allow_missing {
            return Err(transaction::conflict());
        }
        guards.push(Change {
            path: slot,
            before: node.clone(),
            after: node,
        });
    }
    if !allow_missing {
        for (path, hash) in &receipt.files {
            if transaction::file_bytes(path)?.is_none_or(|bytes| digest(&bytes) != *hash) {
                return Err(transaction::conflict());
            }
        }
        for path in &receipt.empty_directories {
            if transaction::snapshot(path)? != Some(Node::Directory(BTreeMap::new())) {
                return Err(transaction::conflict());
            }
        }
    }
    Ok(guards)
}
