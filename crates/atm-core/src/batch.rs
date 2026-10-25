use crate::{
    jsonc::{self, EditRequest, EditResult, FieldView},
    storage::{self, Protector},
    vault::{encrypted_read_with, encrypted_write_with},
    windows::{self, FileSnapshot},
    Error, Result, Vault, MASK, MAX_CONFIG_BYTES,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
};
use uuid::Uuid;
use zeroize::Zeroizing;

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FileView {
    pub path: String,
    pub fields: Vec<FieldView>,
    pub encoding: String,
    pub changed: bool,
    pub error: Option<Error>,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewView {
    pub id: Uuid,
    pub files: Vec<FileView>,
}
struct FilePlan {
    view: FileView,
    original: Option<FileSnapshot>,
    replacement: Zeroizing<Vec<u8>>,
}
pub struct Preview {
    pub id: Uuid,
    files: Vec<FilePlan>,
    consumed: bool,
}
impl Preview {
    pub fn view(&self) -> PreviewView {
        PreviewView {
            id: self.id,
            files: self.files.iter().map(|file| file.view.clone()).collect(),
        }
    }
    pub fn cancel(&mut self) {
        self.files.clear();
        self.consumed = true;
    }
}
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum Outcome {
    Applied,
    Skipped,
    Conflict,
    Failed,
    AppliedUnverified,
    OutcomeUnknown,
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FileResult {
    pub path: String,
    pub outcome: Outcome,
    pub message: &'static str,
    pub code: Option<&'static str>,
    pub backup_path: Option<String>,
    pub temporary_path: Option<String>,
}
pub trait AtomicReplacer: Send + Sync {
    fn replace(&self, temporary: &Path, destination: &Path) -> Result<()>;
}
pub struct WindowsReplacer;
impl AtomicReplacer for WindowsReplacer {
    fn replace(&self, temporary: &Path, destination: &Path) -> Result<()> {
        windows::replace(temporary, destination)
    }
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "PascalCase")]
struct Backup {
    version: u32,
    file_path: String,
    #[serde(with = "base64_bytes")]
    original_bytes: Zeroizing<Vec<u8>>,
    original_hash: String,
    expected_after_hash: String,
    created_utc: DateTime<Utc>,
}
mod base64_bytes {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        bytes: &Zeroizing<Vec<u8>>,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let value = Zeroizing::new(STANDARD.encode(bytes.as_slice()));
        serializer.serialize_str(&value)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Zeroizing<Vec<u8>>, D::Error> {
        let value = Zeroizing::<String>::deserialize(deserializer)?;
        STANDARD
            .decode(value.as_bytes())
            .map(Zeroizing::new)
            .map_err(|_| serde::de::Error::custom("Invalid backup bytes"))
    }
}
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackupView {
    pub backup_path: String,
    pub file_path: String,
    pub created_utc: Option<DateTime<Utc>>,
    pub error: Option<Error>,
}

pub struct BatchUpdater {
    directory: PathBuf,
    replacer: Box<dyn AtomicReplacer>,
    protector: Arc<dyn Protector>,
}
impl BatchUpdater {
    pub fn new(directory: PathBuf) -> Self {
        Self {
            directory,
            replacer: Box::new(WindowsReplacer),
            protector: storage::system(),
        }
    }
    pub fn with_replacer(directory: PathBuf, replacer: Box<dyn AtomicReplacer>) -> Self {
        Self {
            directory,
            replacer,
            protector: storage::system(),
        }
    }
    pub fn with_protector(directory: PathBuf, protector: Arc<dyn Protector>) -> Self {
        Self {
            directory,
            replacer: Box::new(WindowsReplacer),
            protector,
        }
    }
    pub fn with_replacer_and_protector(
        directory: PathBuf,
        replacer: Box<dyn AtomicReplacer>,
        protector: Arc<dyn Protector>,
    ) -> Self {
        Self {
            directory,
            replacer,
            protector,
        }
    }
    pub fn preview(&self, vault: &Vault, selected: &[Uuid]) -> Preview {
        self.preview_with_validator(vault, selected, |_, original, requests| {
            jsonc::edit(original, requests)
        })
    }
    /// Validator runs once for each canonical file, before any writes or backups.
    /// It must return a fully validated, byte-preserving edit and static safe errors.
    pub fn preview_with_validator<F>(
        &self,
        vault: &Vault,
        selected: &[Uuid],
        validator: F,
    ) -> Preview
    where
        F: Fn(&str, &[u8], &[EditRequest]) -> Result<EditResult>,
    {
        if selected.len() > 500 {
            return Preview {
                id: Uuid::new_v4(),
                consumed: false,
                files: vec![Self::rejected(
                    "（所选目标）".into(),
                    Error::new("TARGET_LIMIT", "单次最多选择 500 个目标。"),
                )],
            };
        }
        let mut groups: Vec<(String, Vec<EditRequest>)> = Vec::new();
        let mut failures = Vec::new();
        for id in selected {
            let Some(target) = vault
                .document
                .targets
                .iter()
                .find(|target| target.id == *id)
            else {
                failures.push(Self::rejected(
                    "（未知目标）".to_owned(),
                    Error::new("TARGET_MISSING", "所选目标已不存在。"),
                ));
                continue;
            };
            let prepared = (|| {
                let path = windows::canonical(&target.file_path)?;
                let request = EditRequest {
                    label: target.label.clone(),
                    pointer: target.pointer.clone(),
                    secret: vault.secret(target.key_id)?,
                    bearer: target.bearer_prefix,
                    replace_variables: target.replace_variables,
                };
                Ok((path, request))
            })();
            match prepared {
                Ok((path, request)) => {
                    if let Some((_, requests)) = groups
                        .iter_mut()
                        .find(|(other, _)| windows::same_path(other, &path))
                    {
                        requests.push(request);
                    } else {
                        groups.push((path, vec![request]));
                    }
                }
                Err(error) => failures.push(Self::rejected(target.file_path.clone(), error)),
            }
        }
        let mut retained_bytes = 0usize;
        for (path, requests) in groups {
            let plan = (|| {
                // Both the original and prepared replacement stay in memory until
                // confirmation. Bound the whole batch, not just each input file.
                const MAX_PREVIEW_BYTES: usize = 128 * 1024 * 1024;
                if retained_bytes >= MAX_PREVIEW_BYTES {
                    return Err(Error::new(
                        "PREVIEW_SIZE",
                        "预览总大小超出上限，请减少所选文件。",
                    ));
                }
                let original = windows::read_snapshot(&path)?;
                let result = validator(&path, &original.bytes, &requests)?;
                if result.bytes.len() > MAX_CONFIG_BYTES {
                    return Err(Error::new("CONFIG_SIZE", "更新后的配置文件超过安全上限。"));
                }
                let cost = original.bytes.len() + result.bytes.len();
                if cost > MAX_PREVIEW_BYTES - retained_bytes {
                    return Err(Error::new(
                        "PREVIEW_SIZE",
                        "预览总大小超出上限，请减少所选文件。",
                    ));
                }
                retained_bytes += cost;
                let changed = original.bytes.as_slice() != result.bytes.as_slice();
                Ok(FilePlan {
                    view: FileView {
                        path: path.clone(),
                        fields: result.fields,
                        encoding: result.encoding,
                        changed,
                        error: None,
                    },
                    original: Some(original),
                    replacement: result.bytes,
                })
            })();
            failures.push(plan.unwrap_or_else(|error| Self::rejected(path, error)));
        }
        Preview {
            id: Uuid::new_v4(),
            files: failures,
            consumed: false,
        }
    }
    fn rejected(path: String, error: Error) -> FilePlan {
        FilePlan {
            view: FileView {
                path,
                fields: Vec::new(),
                encoding: String::new(),
                changed: false,
                error: Some(error),
            },
            original: None,
            replacement: Zeroizing::new(Vec::new()),
        }
    }
    pub fn apply(
        &self,
        preview: &mut Preview,
        id: Uuid,
        confirmed: bool,
    ) -> Result<Vec<FileResult>> {
        if !confirmed {
            return Err(Error::new(
                "CONFIRM_REQUIRED",
                "须确认遮罩预览后才允许应用。",
            ));
        }
        if preview.id != id || preview.consumed {
            return Err(Error::new(
                "PREVIEW_EXPIRED",
                "预览已失效、取消或使用，请重新预览。",
            ));
        }
        preview.consumed = true;
        let results = preview
            .files
            .iter()
            .map(|file| self.apply_file(file))
            .collect();
        preview.files.clear();
        Ok(results)
    }
    fn result(
        file: &FilePlan,
        outcome: Outcome,
        message: &'static str,
        code: Option<&'static str>,
        backup: Option<String>,
    ) -> FileResult {
        FileResult {
            path: file.view.path.clone(),
            outcome,
            message,
            code,
            backup_path: backup,
            temporary_path: None,
        }
    }
    fn apply_file(&self, file: &FilePlan) -> FileResult {
        if let Some(error) = file.view.error {
            return Self::result(file, Outcome::Failed, error.message, Some(error.code), None);
        }
        let mut backup = None;
        let mut temporary = None;
        let mut attempted = false;
        let operation = (|| {
            let expected = file
                .original
                .as_ref()
                .ok_or(Error::new("PREVIEW_INVALID", "预览无效。"))?;
            let path = windows::canonical(&file.view.path)?;
            if !windows::same_path(&path, &expected.path) {
                return Err(Error::new("FILE_CHANGED", "文件自预览后变化，请重新预览。"));
            }
            let mut guard = windows::open_guard(&path)?;
            let current = windows::snapshot(&path, &mut guard)?;
            if current.fingerprint != expected.fingerprint {
                return Err(Error::new("FILE_CHANGED", "文件自预览后变化，拒绝写入。"));
            }
            if !file.view.changed {
                return Ok(Outcome::Skipped);
            }
            backup = Some(self.save_backup(&path, &current.bytes, &file.replacement)?);
            let parent = Path::new(&path)
                .parent()
                .ok_or(Error::new("PATH_LOCAL", "路径无效。"))?;
            let temp = parent.join(format!(".atm-{}.tmp", Uuid::new_v4()));
            temporary = Some(temp.clone());
            let mut stage = windows::create_config_staging(&temp, &guard)?;
            stage.write_all(&file.replacement)?;
            stage.sync_all()?;
            drop(stage);
            if windows::read_snapshot(&path)?.fingerprint != expected.fingerprint {
                return Err(Error::new("FILE_CHANGED", "文件自预览后变化，拒绝写入。"));
            }
            attempted = true;
            self.replacer.replace(&temp, Path::new(&path))?;
            if windows::read_snapshot(&path)?.fingerprint.hash != windows::hash(&file.replacement) {
                return Ok(Outcome::AppliedUnverified);
            }
            Ok(Outcome::Applied)
        })();
        let mut result = match operation {
            Ok(outcome) => {
                let message = match outcome {
                    Outcome::Applied => "已原子替换并验证，加密备份已保存。",
                    Outcome::Skipped => "无需写入：值相同或已保留变量。",
                    _ => "替换已完成，但内容随后变化，需检查应用。",
                };
                let code = if outcome == Outcome::AppliedUnverified {
                    Some("POST_WRITE_CHANGED")
                } else {
                    None
                };
                Self::result(file, outcome, message, code, backup)
            }
            Err(error) => {
                let outcome = if attempted {
                    match windows::read_snapshot(&file.view.path) {
                        Ok(actual)
                            if actual.fingerprint.hash == windows::hash(&file.replacement) =>
                        {
                            Outcome::AppliedUnverified
                        }
                        Ok(actual)
                            if file.original.as_ref().is_some_and(|original| {
                                original.fingerprint.hash == actual.fingerprint.hash
                            }) =>
                        {
                            Outcome::Failed
                        }
                        _ => Outcome::OutcomeUnknown,
                    }
                } else if matches!(
                    error.code,
                    "FILE_CHANGED"
                        | "FILE_MISSING"
                        | "PATH_CHANGED"
                        | "PATH_REPARSE"
                        | "PATH_HARDLINK"
                ) {
                    Outcome::Conflict
                } else {
                    Outcome::Failed
                };
                let message = match outcome {
                    Outcome::AppliedUnverified => "写入内容存在，但最终验证未完成；保留备份。",
                    Outcome::OutcomeUnknown => "替换结果未确认；未自动覆盖或回滚，请检查文件。",
                    _ => error.message,
                };
                Self::result(file, outcome, message, Some(error.code), backup)
            }
        };
        if let Some(temp) = temporary {
            if let Err(error) = fs::remove_file(&temp) {
                if error.kind() != std::io::ErrorKind::NotFound {
                    result.temporary_path = Some(temp.to_string_lossy().into_owned());
                    result.message =
                        "操作已结束，但明文暂存文件未能清理，请关闭占用后处理所示路径。";
                }
            }
        }
        result
    }
    fn save_backup(&self, path: &str, original: &[u8], replacement: &[u8]) -> Result<String> {
        let payload = Backup {
            version: 1,
            file_path: path.to_owned(),
            original_bytes: Zeroizing::new(original.to_vec()),
            original_hash: windows::hash(original),
            expected_after_hash: windows::hash(replacement),
            created_utc: Utc::now(),
        };
        let bytes = Zeroizing::new(
            serde_json::to_vec(&payload)
                .map_err(|_| Error::new("BACKUP_FORMAT", "无法编码备份。"))?,
        );
        let path = self.directory.join(format!("{}.atmbackup", Uuid::new_v4()));
        encrypted_write_with(&path, &bytes, self.protector.as_ref())?;
        Ok(path.to_string_lossy().into_owned())
    }
    fn load_backup(&self, path: &Path) -> Result<Backup> {
        let payload: Backup =
            serde_json::from_slice(&encrypted_read_with(path, self.protector.as_ref())?)
                .map_err(|_| Error::new("BACKUP_FORMAT", "备份格式无效。"))?;
        if payload.version != 1
            || payload.original_bytes.len() > MAX_CONFIG_BYTES
            || payload.original_hash != windows::hash(&payload.original_bytes)
            || !is_absolute_local_path(&payload.file_path)
            || payload.expected_after_hash.len() != 64
            || !payload
                .expected_after_hash
                .chars()
                .all(|c| c.is_ascii_hexdigit())
        {
            return Err(Error::new("BACKUP_FORMAT", "备份格式或完整性无效。"));
        }
        Ok(payload)
    }
    pub fn backups(&self) -> Result<Vec<BackupView>> {
        if !self.directory.exists() {
            return Ok(Vec::new());
        }
        let mut views = Vec::new();
        for entry in fs::read_dir(&self.directory)? {
            let entry = entry?;
            let path = entry.path();
            if !backup_extension(&path) {
                continue;
            }
            let backup_path = path.to_string_lossy().into_owned();
            views.push(match self.load_backup(&path) {
                Ok(payload) => BackupView {
                    backup_path,
                    file_path: payload.file_path,
                    created_utc: Some(payload.created_utc),
                    error: None,
                },
                Err(error) => BackupView {
                    backup_path,
                    file_path: "（无法解密或无效）".to_owned(),
                    created_utc: None,
                    error: Some(error),
                },
            });
        }
        views.sort_by_key(|view| std::cmp::Reverse(view.created_utc));
        Ok(views)
    }
    pub fn preview_rollback(&self, backup_path: &str) -> Result<Preview> {
        let selected = Path::new(backup_path);
        if selected.parent() != Some(self.directory.as_path()) || !backup_extension(selected) {
            return Err(Error::new("BACKUP_SCOPE", "只能回滚本管理器的已列出备份。"));
        }
        let payload = self.load_backup(selected)?;
        let original = windows::read_snapshot(&payload.file_path)?;
        if original.fingerprint.hash != payload.expected_after_hash
            && original.fingerprint.hash != payload.original_hash
        {
            return Err(Error::new(
                "ROLLBACK_CONFLICT",
                "文件已有后续编辑，拒绝整文件回滚。",
            ));
        }
        let changed = original.bytes.as_slice() != payload.original_bytes.as_slice();
        let view = FileView {
            path: original.path.clone(),
            fields: vec![FieldView {
                label: "回滚整个文件".to_owned(),
                pointer: "（完整字节恢复）".to_owned(),
                before: MASK.to_owned(),
                after: MASK.to_owned(),
                status: if changed {
                    "内容匹配，可回滚"
                } else {
                    "已是原文，无需回滚"
                },
            }],
            encoding: "完整原始字节".to_owned(),
            changed,
            error: None,
        };
        Ok(Preview {
            id: Uuid::new_v4(),
            files: vec![FilePlan {
                view,
                original: Some(original),
                replacement: payload.original_bytes,
            }],
            consumed: false,
        })
    }
}

fn backup_extension(path: &Path) -> bool {
    path.extension()
        .and_then(|v| v.to_str())
        .is_some_and(|v| v.eq_ignore_ascii_case("atmbackup"))
}
fn is_absolute_local_path(path: &str) -> bool {
    #[cfg(any(target_os = "linux", target_os = "macos"))]
    {
        Path::new(path).is_absolute()
            && !path.chars().any(char::is_control)
            && !path.split('/').any(|p| p == "." || p == "..")
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        let bytes = path.as_bytes();
        bytes.len() >= 3
            && bytes[0].is_ascii_alphabetic()
            && bytes[1] == b':'
            && matches!(bytes[2], b'\\' | b'/')
            && !path[2..].contains(':')
            && !path.chars().any(char::is_control)
    }
}
