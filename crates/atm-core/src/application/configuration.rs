//! Configuration workflow shared by GUI and CLI, including preview/schema guards.
use super::template_store::{Assignment, TemplateStore};
use crate::{
    batch::{BackupView, BatchUpdater, FileResult, Preview, PreviewView},
    jsonc,
    storage::{self, Protector},
    templates::{self, ApplicationIdentity, TemplateCandidate},
    windows, Error, KeyView, Result, TargetMapping, Vault,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    sync::Arc,
};
use uuid::Uuid;
use zeroize::Zeroizing;

pub struct Configuration {
    vault: Vault,
    updater: BatchUpdater,
    preview: Option<Preview>,
    templates: TemplateStore,
    candidate: Option<TemplateCandidate>,
    demo: bool,
}

// Construction is inert. Only configuration operations open encrypted storage.
// A failed open never becomes a usable configuration service.
pub struct ConfigurationSession {
    directory: Result<PathBuf>,
    protector: Arc<dyn Protector>,
    demo: bool,
    service: Option<Configuration>,
}
impl ConfigurationSession {
    pub fn new(directory: Result<PathBuf>, protector: Arc<dyn Protector>, demo: bool) -> Self {
        Self {
            directory,
            protector,
            demo,
            service: None,
        }
    }
    pub fn directory(&self) -> Result<&Path> {
        self.directory.as_deref().map_err(|error| *error)
    }
    pub fn get(&mut self) -> Result<&mut Configuration> {
        if self.service.is_none() {
            self.service = Some(Configuration::open(
                self.directory()?,
                self.protector.clone(),
                self.demo,
            )?);
        }
        Ok(self.service.as_mut().expect("opened configuration"))
    }
    pub fn invalidate(&mut self) {
        if let Some(service) = &mut self.service {
            service.invalidate();
        }
    }
}

#[derive(Clone, Serialize, Deserialize)]
pub struct TargetView {
    #[serde(flatten)]
    pub target: TargetMapping,
    #[serde(rename = "TemplateId", default)]
    pub template_id: Option<Uuid>,
}
#[derive(Serialize)]
pub struct TemplateField {
    pub pointer: String,
    pub label: String,
    pub kind: &'static str,
}
#[derive(Serialize)]
pub struct TemplateView {
    pub id: Uuid,
    pub name: String,
    pub fields: Vec<TemplateField>,
}
#[derive(Serialize)]
pub struct ConfigurationSnapshot {
    pub keys: Vec<KeyView>,
    pub targets: Vec<TargetView>,
    pub templates: Vec<TemplateView>,
    #[serde(rename = "storageKind")]
    pub storage_kind: &'static str,
    pub demo: bool,
}
#[derive(Serialize)]
pub struct CandidateView {
    pub id: Uuid,
    pub name: String,
    pub fields: Vec<TemplateField>,
    pub schema: serde_json::Value,
    pub warnings: Vec<String>,
}
fn fields(template: &templates::Template) -> Vec<TemplateField> {
    template
        .bindings
        .iter()
        .map(|binding| TemplateField {
            pointer: binding.pointer.clone(),
            label: binding.name.clone(),
            kind: "string",
        })
        .collect()
}
impl Configuration {
    pub fn open(directory: &Path, protector: Arc<dyn Protector>, demo: bool) -> Result<Self> {
        let vault = Vault::open_with_protector(directory, protector.clone())?;
        let templates = TemplateStore::load_with_protector(directory, protector.clone())?;
        let updater = BatchUpdater::with_protector(vault.backup_directory(), protector);
        Ok(Self {
            vault,
            templates,
            updater,
            preview: None,
            candidate: None,
            demo,
        })
    }
    pub fn directory(&self) -> &Path {
        self.vault.directory()
    }
    pub fn usage_credential(&self, id: Uuid) -> Result<(Zeroizing<String>, String)> {
        let key = self.vault.usage_credential(id)?;
        let view = self
            .vault
            .snapshot()
            .keys
            .into_iter()
            .find(|k| k.id == id)
            .ok_or(Error::new("KEY_MISSING", "密钥已不存在。"))?;
        Ok((key, format!("{}:{}", id, view.updated_utc)))
    }
    pub fn invalidate(&mut self) {
        if let Some(mut plan) = self.preview.take() {
            plan.cancel();
        }
    }
    pub fn snapshot(&self) -> Result<ConfigurationSnapshot> {
        let snap = self.vault.snapshot();
        Ok(ConfigurationSnapshot {
            storage_kind: storage::kind(),
            demo: self.demo,
            keys: snap.keys,
            targets: snap
                .targets
                .into_iter()
                .map(|target| TargetView {
                    template_id: self
                        .templates
                        .assignments
                        .get(&target.id)
                        .and_then(|a| a.template_id),
                    target,
                })
                .collect(),
            templates: self
                .templates
                .templates
                .values()
                .map(|t| TemplateView {
                    id: t.id,
                    name: t.name.clone(),
                    fields: fields(t),
                })
                .collect(),
        })
    }

    pub fn save_key(
        &mut self,
        id: Option<Uuid>,
        name: String,
        secret: Zeroizing<String>,
    ) -> Result<Uuid> {
        // Wrap the caller-owned plaintext before any fallible operation.
        self.invalidate();
        self.vault.save_key(id, name, secret)
    }

    pub fn delete_key(&mut self, id: Uuid) -> Result<()> {
        self.invalidate();
        self.vault.delete_key(id)
    }

    pub fn save_target(&mut self, mut target: TargetView) -> Result<Uuid> {
        self.invalidate();
        if target.target.id.is_nil() {
            target.target.id = Uuid::new_v4();
        }
        target.target.file_path = windows::canonical(&target.target.file_path)?;
        target.target.pointer = jsonc::normalize(&target.target.pointer)?;
        if let Some(id) = target.template_id {
            let t = self
                .templates
                .templates
                .get(&id)
                .ok_or(Error::new("TEMPLATE_MISSING", "请选择已保存模板。"))?;
            templates::validate_template(t)?;
            if !t.write_allowlist.contains(&target.target.pointer) {
                return Err(Error::new(
                    "TEMPLATE_ALLOWLIST",
                    "所选字段不在模板写入白名单内。",
                ));
            }
        }
        // Metadata is durable before exposing the mapping. An interrupted pair either
        // retains an explicit user-selected binding or fails closed on mapping drift.
        let old = self.templates.clone();
        let mut next = old.clone();
        next.assignments.insert(
            target.target.id,
            Assignment {
                template_id: target.template_id,
                mapping: target.target.clone(),
            },
        );
        next.save(self.vault.directory())?;
        self.templates = next;
        match self.vault.save_target(target.target) {
            Ok(id) => Ok(id),
            Err(error) => {
                if old.save(self.vault.directory()).is_ok() {
                    self.templates = old;
                }
                Err(error)
            }
        }
    }

    pub fn delete_target(&mut self, id: Uuid) -> Result<()> {
        self.invalidate();
        self.vault.delete_target(id)?;
        let mut next = self.templates.clone();
        next.assignments.remove(&id);
        next.save(self.vault.directory())?;
        self.templates = next;
        Ok(())
    }

    pub fn preview(&mut self, selected: Vec<Uuid>) -> Result<PreviewView> {
        self.invalidate();
        let snapshot = self.vault.snapshot();
        let mut per_file: Vec<(String, BTreeSet<Uuid>)> = Vec::new();
        let mut drift: Vec<(String, Error)> = Vec::new();
        // Every configured schema on a selected file remains active even when only
        // a different mapping on that file is selected. No schema bypass by checkbox.
        for target in &snapshot.targets {
            match self.templates.for_mapping(target) {
                Ok(Some(template)) => {
                    if let Some((_, ids)) = per_file
                        .iter_mut()
                        .find(|(path, _)| windows::same_path(path, &target.file_path))
                    {
                        ids.insert(template.id);
                    } else {
                        per_file.push((target.file_path.clone(), BTreeSet::from([template.id])));
                    }
                }
                Err(error) => drift.push((target.file_path.clone(), error)),
                Ok(None) => {}
            }
        }
        // Orphaned template bindings keep guarding their file; only an explicit
        // mapping/template removal may discard this file's prior guard.
        for assignment in self.templates.assignments.values() {
            if let Some(id) = assignment.template_id {
                if let Some((_, ids)) = per_file
                    .iter_mut()
                    .find(|(path, _)| windows::same_path(path, &assignment.mapping.file_path))
                {
                    ids.insert(id);
                } else {
                    per_file.push((assignment.mapping.file_path.clone(), BTreeSet::from([id])));
                }
            }
        }
        let plan = self.updater.preview_with_validator(
            &self.vault,
            &selected,
            |path, original, requests| {
                if let Some((_, error)) = drift
                    .iter()
                    .find(|(known, _)| windows::same_path(known, path))
                {
                    return Err(*error);
                }
                let Some((_, ids)) = per_file
                    .iter()
                    .find(|(known, _)| windows::same_path(known, path))
                else {
                    return jsonc::edit(original, requests);
                };
                if ids.len() != 1 {
                    return Err(Error::new(
                        "TEMPLATE_AMBIGUOUS",
                        "同一文件绑定多个不同模板，请统一后重试。",
                    ));
                }
                let id = ids
                    .first()
                    .ok_or(Error::new("TEMPLATE_MISSING", "模板不可用。"))?;
                let template = self
                    .templates
                    .templates
                    .get(id)
                    .ok_or(Error::new("TEMPLATE_MISSING", "模板不可用。"))?;
                templates::prepare_patch(template, original, requests)
            },
        );
        let view = plan.view();
        self.preview = Some(plan);
        Ok(view)
    }

    pub fn apply_preview(&mut self, id: Uuid, confirmed: bool) -> Result<Vec<FileResult>> {
        if !confirmed {
            return Err(Error::new(
                "CONFIRM_REQUIRED",
                "须确认遮罩预览后才允许应用。",
            ));
        }
        if self.preview.as_ref().is_none_or(|plan| plan.id != id) {
            return Err(Error::new("PREVIEW_EXPIRED", "预览已失效，请重新预览。"));
        }
        let mut plan = self
            .preview
            .take()
            .ok_or(Error::new("PREVIEW_EXPIRED", "预览已失效，请重新预览。"))?;
        self.updater.apply(&mut plan, id, true)
    }

    pub fn cancel_preview(&mut self) -> Result<()> {
        self.invalidate();
        Ok(())
    }

    pub fn list_backups(&self) -> Result<Vec<BackupView>> {
        self.updater.backups()
    }

    pub fn preview_rollback(&mut self, backup_path: String) -> Result<PreviewView> {
        self.invalidate();
        let plan = self.updater.preview_rollback(&backup_path)?;
        let view = plan.view();
        self.preview = Some(plan);
        Ok(view)
    }

    pub fn infer_template(&mut self, file_path: String) -> Result<CandidateView> {
        self.candidate = None;
        let original = windows::read_snapshot(&file_path)?;
        let filename = Path::new(&original.path)
            .file_name()
            .and_then(|v| v.to_str())
            .unwrap_or("config.json")
            .to_owned();
        let candidate = templates::infer_candidate(
            &original.bytes,
            ApplicationIdentity {
                id: "user-selected".into(),
                display_name: "用户选择的配置".into(),
                config_file_names: vec![filename],
            },
            "我的配置模板".into(),
        )?;
        let view = CandidateView {
            id: candidate.template.id,
            name: candidate.template.name.clone(),
            fields: fields(&candidate.template),
            schema: candidate.template.schema.clone(),
            warnings: candidate.warnings.clone(),
        };
        self.candidate = Some(candidate);
        Ok(view)
    }

    pub fn save_template(
        &mut self,
        candidate_id: Uuid,
        name: String,
        selected_pointers: Vec<String>,
        schema: Option<String>,
    ) -> Result<Uuid> {
        if selected_pointers.is_empty() || selected_pointers.len() > 1024 {
            return Err(Error::new(
                "TEMPLATE_ALLOWLIST",
                "请选择 1–1024 个精确字段。",
            ));
        }
        let candidate = self
            .candidate
            .as_ref()
            .ok_or(Error::new("CANDIDATE_EXPIRED", "候选已失效，请重新提取。"))?;
        if candidate.template.id != candidate_id {
            return Err(Error::new("CANDIDATE_EXPIRED", "候选已失效，请重新提取。"));
        }
        let mut candidate = candidate.clone();
        for pointer in &selected_pointers {
            if !candidate
                .template
                .bindings
                .iter()
                .any(|b| b.pointer == *pointer)
            {
                return Err(Error::new(
                    "TEMPLATE_ALLOWLIST",
                    "只能选择候选中的现有字符串字段。",
                ));
            }
        }
        candidate.template.name = name;
        candidate.template.write_allowlist = selected_pointers;
        candidate
            .template
            .bindings
            .retain(|b| candidate.template.write_allowlist.contains(&b.pointer));
        if let Some(schema) = schema {
            if schema.len() > 128 * 1024 {
                return Err(Error::new("SCHEMA_LIMIT", "Schema 太大。"));
            }
            let edited = jsonc::parse_value(schema.as_bytes()).map_err(|_| {
                Error::new(
                    "SCHEMA_INVALID",
                    "Schema 必须为无重复字段的有效 JSON 对象。",
                )
            })?;
            if edited != candidate.template.schema {
                candidate.template.source.kind = templates::SchemaSourceKind::UserAuthored;
                candidate.template.source.version = "user-reviewed-v1".into();
            }
            candidate.template.schema = edited;
        }
        let template = templates::confirm_candidate(candidate, true)?;
        let id = template.id;
        let mut next = self.templates.clone();
        next.templates.insert(id, template);
        next.save(self.vault.directory())?;
        self.templates = next;
        self.candidate = None;
        self.invalidate();
        Ok(id)
    }

    pub fn delete_template(&mut self, id: Uuid) -> Result<()> {
        let active_ids: BTreeSet<_> = self
            .vault
            .snapshot()
            .targets
            .into_iter()
            .map(|t| t.id)
            .collect();
        if self
            .templates
            .assignments
            .iter()
            .any(|(target_id, a)| active_ids.contains(target_id) && a.template_id == Some(id))
        {
            return Err(Error::new(
                "TEMPLATE_IN_USE",
                "请先取消使用此模板的映射绑定。",
            ));
        }
        let mut next = self.templates.clone();
        next.assignments.retain(|_, a| a.template_id != Some(id));
        if next.templates.remove(&id).is_none() {
            return Err(Error::new("TEMPLATE_MISSING", "模板不存在。"));
        }
        next.save(self.vault.directory())?;
        self.templates = next;
        self.invalidate();
        Ok(())
    }
}
