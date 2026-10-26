//! Separate encrypted metadata for confirmed templates and their schema-bound target assignments.
use crate::{
    storage::{self, Protector},
    templates::{self, Template},
    vault::{encrypted_read_with, encrypted_write_with},
    windows, Error, Result, TargetMapping,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
use uuid::Uuid;
use zeroize::Zeroizing;

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Assignment {
    pub template_id: Option<Uuid>,
    pub mapping: TargetMapping,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TemplateStore {
    #[serde(skip, default = "storage::system")]
    protector: Arc<dyn Protector>,
    pub version: u32,
    pub templates: BTreeMap<Uuid, Template>,
    pub assignments: BTreeMap<Uuid, Assignment>,
}
impl Default for TemplateStore {
    fn default() -> Self {
        Self {
            protector: storage::system(),
            version: 1,
            templates: BTreeMap::new(),
            assignments: BTreeMap::new(),
        }
    }
}
impl TemplateStore {
    fn path(directory: &Path) -> PathBuf {
        directory.join(storage::template_filename())
    }
    pub fn load(directory: &Path) -> Result<Self> {
        Self::load_with_protector(directory, storage::system())
    }
    pub fn load_with_protector(directory: &Path, protector: Arc<dyn Protector>) -> Result<Self> {
        let path = Self::path(directory);
        if !storage::file_exists(&path)? {
            if directory.join("templates.required").exists() {
                return Err(Error::new(
                    "TEMPLATE_STORE_MISSING",
                    "模板侧车文件缺失；已停用配置编辑以避免丢失 Schema 保护。请恢复备份。",
                ));
            }
            return Ok(Self {
                protector,
                ..Self::default()
            });
        }
        if fs::metadata(&path)?.len() > 2 * 1024 * 1024 {
            return Err(Error::new("TEMPLATE_STORE", "模板存储过大。"));
        }
        let plain = encrypted_read_with(&path, protector.as_ref())?;
        let mut store: Self = serde_json::from_slice(&plain)
            .map_err(|_| Error::new("TEMPLATE_STORE", "模板存储无效，未修改原文件。"))?;
        store.protector = protector;
        store.validate()?;
        Ok(store)
    }
    fn validate(&self) -> Result<()> {
        if self.version != 1 || self.templates.len() > 100 || self.assignments.len() > 1000 {
            return Err(Error::new("TEMPLATE_STORE", "模板存储版本或数量无效。"));
        }
        for (id, template) in &self.templates {
            if *id != template.id {
                return Err(Error::new("TEMPLATE_STORE", "模板标识不一致。"));
            }
            templates::validate_template(template)?;
        }
        for (id, assignment) in &self.assignments {
            if *id != assignment.mapping.id
                || assignment
                    .template_id
                    .is_some_and(|id| !self.templates.contains_key(&id))
            {
                return Err(Error::new("TEMPLATE_STORE", "模板绑定无效。"));
            }
        }
        Ok(())
    }
    pub fn save(&self, directory: &Path) -> Result<()> {
        self.validate()?;
        let plain = Zeroizing::new(
            serde_json::to_vec(self)
                .map_err(|_| Error::new("TEMPLATE_STORE", "无法编码模板存储。"))?,
        );
        if plain.len() > 1024 * 1024 {
            return Err(Error::new("TEMPLATE_STORE", "模板存储过大。"));
        }
        storage::ensure_directory(directory)?;
        // A durable, value-free marker makes accidental sidecar loss fail closed.
        // It is not a defense against a same-user attacker deleting both files.
        let marker = directory.join("templates.required");
        let marker_created = !marker.exists();
        if marker_created {
            let mut options = OpenOptions::new();
            options.create_new(true).write(true);
            #[cfg(target_os = "macos")]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut required = options.open(&marker)?;
            required.write_all(b"ai-tooling-manager/template-sidecar/v1\n")?;
            required.sync_all()?;
        }
        let path = Self::path(directory);
        let result = encrypted_write_with(&path, &plain, self.protector.as_ref());
        // On a failed first save, no mapping/vault change has occurred yet. Remove
        // only our newly created marker if no sidecar exists, allowing safe retry.
        if result.is_err() && marker_created && !path.exists() {
            let _ = fs::remove_file(marker);
        }
        result
    }
    pub fn for_mapping(&self, target: &TargetMapping) -> Result<Option<&Template>> {
        let Some(assignment) = self.assignments.get(&target.id) else {
            return Ok(None);
        };
        // A schema-bound target cannot be silently repurposed; the pointer must keep matching.
        let old = &assignment.mapping;
        if old.pointer != target.pointer
            || !windows::same_path(&old.file_path, &target.file_path)
            || old.key_id != target.key_id
            || old.bearer_prefix != target.bearer_prefix
            || old.replace_variables != target.replace_variables
        {
            return Err(Error::new(
                "TEMPLATE_MAPPING_DRIFT",
                "映射已由其他版本修改；请重新确认模板绑定。",
            ));
        }
        assignment
            .template_id
            .map(|id| {
                self.templates
                    .get(&id)
                    .ok_or(Error::new("TEMPLATE_MISSING", "绑定模板不存在。"))
            })
            .transpose()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::templates::{confirm_candidate, infer_candidate, ApplicationIdentity};
    fn mapping() -> TargetMapping {
        TargetMapping {
            id: Uuid::new_v4(),
            label: "synthetic".into(),
            file_path: "C:\\fake\\config.json".into(),
            pointer: "/key".into(),
            key_id: Uuid::new_v4(),
            bearer_prefix: false,
            replace_variables: false,
        }
    }
    #[test]
    fn mapping_drift_never_silently_drops_template() {
        let mut candidate = infer_candidate(
            br#"{"key":"FAKE_SAMPLE"}"#,
            ApplicationIdentity {
                id: "fake".into(),
                display_name: "Fake".into(),
                config_file_names: vec![],
            },
            "Fake schema".into(),
        )
        .expect("candidate");
        candidate.template.write_allowlist.push("/key".into());
        let template = confirm_candidate(candidate, true).expect("confirmed");
        let id = template.id;
        let target = mapping();
        let mut store = TemplateStore::default();
        store.templates.insert(id, template);
        store.assignments.insert(
            target.id,
            Assignment {
                template_id: Some(id),
                mapping: target.clone(),
            },
        );
        assert!(store.for_mapping(&target).expect("unchanged").is_some());
        let mut changed = target.clone();
        changed.pointer = "/other".into();
        assert_eq!(
            store.for_mapping(&changed).expect_err("drift").code,
            "TEMPLATE_MAPPING_DRIFT"
        );
        changed = target.clone();
        changed.replace_variables = true;
        assert!(store.for_mapping(&changed).is_err());
        changed = target;
        changed.key_id = Uuid::new_v4();
        assert!(store.for_mapping(&changed).is_err());
    }
    #[test]
    fn legacy_mapping_without_sidecar_keeps_exact_patch_mode() {
        assert!(TemplateStore::default()
            .for_mapping(&mapping())
            .expect("legacy")
            .is_none());
    }
    #[test]
    fn missing_sidecar_marker_fails_closed() {
        let directory = std::env::temp_dir().join(format!("lkm-marker-test-{}", Uuid::new_v4()));
        fs::create_dir(&directory).expect("synthetic directory");
        fs::write(directory.join("templates.required"), b"required").expect("marker");
        assert_eq!(
            TemplateStore::load(&directory)
                .err()
                .expect("missing sidecar")
                .code,
            "TEMPLATE_STORE_MISSING"
        );
        fs::remove_dir_all(directory).expect("only remove own synthetic directory");
    }
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    #[test]
    fn sidecar_encrypts_structure_and_bindings_with_injected_test_only_key() {
        let root = tempfile::tempdir().unwrap();
        let directory = root.path().join("TEST_ONLY_store");
        storage::ensure_directory(&directory).unwrap();
        let protector: Arc<dyn Protector> = storage::demo_protector().unwrap();
        let mut store = TemplateStore::load_with_protector(&directory, protector.clone()).unwrap();
        let mut candidate = templates::infer_candidate(
            br#"{"key":"TEST_ONLY_VALUE"}"#,
            templates::ApplicationIdentity {
                id: "test-only".into(),
                display_name: "TEST_ONLY".into(),
                config_file_names: vec![],
            },
            "TEST_ONLY_SCHEMA".into(),
        )
        .unwrap();
        candidate.template.write_allowlist.push("/key".into());
        let template = templates::confirm_candidate(candidate, true).unwrap();
        store.templates.insert(template.id, template);
        store.save(&directory).unwrap();
        let cipher = fs::read(TemplateStore::path(&directory)).unwrap();
        assert!(!cipher.windows(16).any(|w| w == b"TEST_ONLY_SCHEMA"));
        let reopened = TemplateStore::load_with_protector(&directory, protector).unwrap();
        assert_eq!(reopened.templates.len(), 1);
        fs::remove_file(TemplateStore::path(&directory)).unwrap();
        assert_eq!(
            TemplateStore::load_with_protector(&directory, crate::storage::system())
                .err()
                .unwrap()
                .code,
            "TEMPLATE_STORE_MISSING"
        );
    }
}
