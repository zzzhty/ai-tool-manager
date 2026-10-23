use crate::{
    jsonc,
    model::{KeyEntry, Secret, VaultDocument},
    storage::{self, Protector},
    windows, Error, KeyView, Result, SnapshotView, TargetMapping, MASK, MAX_ENCRYPTED_BYTES,
};
use chrono::Utc;
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::Arc,
};
use uuid::Uuid;
use zeroize::Zeroizing;

pub struct Vault {
    directory: PathBuf,
    _lock: File,
    pub(crate) document: VaultDocument,
    protector: Arc<dyn Protector>,
}
pub fn encrypted_read(path: &Path) -> Result<Zeroizing<Vec<u8>>> {
    encrypted_read_with(path, storage::system().as_ref())
}
pub fn encrypted_read_with(path: &Path, protector: &dyn Protector) -> Result<Zeroizing<Vec<u8>>> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(1).custom_flags(0x00200000);
    }
    #[cfg(target_os = "linux")]
    let input = crate::linux::open_regular(path)?;
    #[cfg(target_os = "macos")]
    let input = crate::macos::open_encrypted(path)?;
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    let input = options.open(path)?;
    let metadata = input.metadata()?;
    if !metadata.is_file() {
        return Err(Error::new("DATA_PATH", "加密存储目标必须是普通文件。"));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(Error::new("DATA_PATH", "加密存储不支持链接目标。"));
        }
    }
    if metadata.len() > MAX_ENCRYPTED_BYTES as u64 {
        return Err(Error::new("DATA_SIZE", "加密文件过大。"));
    }
    // Check the opened object and bound the read too, so a metadata/read race
    // cannot allocate an arbitrarily large encrypted file.
    let mut data = Zeroizing::new(Vec::with_capacity(metadata.len() as usize));
    input
        .take(MAX_ENCRYPTED_BYTES as u64 + 1)
        .read_to_end(&mut data)?;
    if data.len() > MAX_ENCRYPTED_BYTES {
        return Err(Error::new("DATA_SIZE", "加密文件过大。"));
    }
    protector.crypt(&data, false)
}
pub fn encrypted_write(path: &Path, bytes: &[u8]) -> Result<()> {
    encrypted_write_with(path, bytes, storage::system().as_ref())
}
pub fn encrypted_write_with(path: &Path, bytes: &[u8], protector: &dyn Protector) -> Result<()> {
    let protected = protector.crypt(bytes, true)?;
    let parent = path
        .parent()
        .ok_or(Error::new("DATA_PATH", "存储路径无效。"))?;
    storage::ensure_directory(parent)?;
    let temporary = parent.join(format!(".lkm-encrypted-{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut output = windows::create_staging(&temporary)?;
        output.write_all(&protected)?;
        output.sync_all()?;
        drop(output);
        if storage::file_exists(path)? {
            windows::replace(&temporary, path)?;
        } else {
            #[cfg(target_os = "linux")]
            crate::linux::install_new(&temporary, path)?;
            #[cfg(target_os = "macos")]
            crate::macos::install_new(&temporary, path)?;
            #[cfg(not(any(target_os = "linux", target_os = "macos")))]
            fs::rename(&temporary, path)?;
        }
        #[cfg(target_os = "linux")]
        crate::linux::sync_parent(path)?;
        #[cfg(target_os = "macos")]
        crate::macos::sync_parent(path)?;
        Ok(())
    })();
    let _ = fs::remove_file(temporary);
    result
}
impl Vault {
    pub fn open(directory: &Path) -> Result<Self> {
        Self::open_with_protector(directory, storage::system())
    }
    /// Explicit per-vault encryption dependency; production `open` always uses OS storage.
    pub fn open_with_protector(directory: &Path, protector: Arc<dyn Protector>) -> Result<Self> {
        storage::ensure_directory(directory)?;
        let lock = windows::open_lock(&directory.join("vault.lock"))?;
        let path = directory.join(storage::vault_filename());
        let document = if storage::file_exists(&path)? {
            serde_json::from_slice(&encrypted_read_with(&path, protector.as_ref())?)
                .map_err(|_| Error::new("VAULT_FORMAT", "密钥库格式或版本无效，原文件未改动。"))?
        } else {
            VaultDocument::default()
        };
        Self::validate(&document)?;
        Ok(Self {
            directory: directory.to_owned(),
            _lock: lock,
            document,
            protector,
        })
    }
    fn validate(document: &VaultDocument) -> Result<()> {
        let invalid = || Error::new("VAULT_FORMAT", "密钥库版本、条目或引用无效。");
        if document.version != 1 || document.keys.len() > 200 || document.targets.len() > 500 {
            return Err(invalid());
        }
        for (i, key) in document.keys.iter().enumerate() {
            if key.id.is_nil()
                || key.name.trim().is_empty()
                || key.name.encode_utf16().count() > 80
                || key.name.chars().any(char::is_control)
                || key.secret.0.is_empty()
                || key.secret.0.encode_utf16().count() > 8192
                || key.secret.0.chars().any(char::is_control)
                || key.secret.0.trim() != key.secret.0.as_str()
                || document.keys[..i]
                    .iter()
                    .any(|other| other.id == key.id || windows::equal_case(&other.name, &key.name))
            {
                return Err(invalid());
            }
        }
        for (i, target) in document.targets.iter().enumerate() {
            if target.id.is_nil()
                || target.label.trim().is_empty()
                || target.label.encode_utf16().count() > 80
                || target.label.chars().any(char::is_control)
                || target.file_path.is_empty()
                || target.file_path.encode_utf16().count() > 32767
                || target.file_path.chars().any(char::is_control)
                || jsonc::normalize(&target.pointer).is_err()
                || document.targets[..i].iter().any(|other| {
                    other.id == target.id
                        || (windows::same_path(&other.file_path, &target.file_path)
                            && other.pointer == target.pointer)
                })
                || !document.keys.iter().any(|key| key.id == target.key_id)
            {
                return Err(invalid());
            }
        }
        Ok(())
    }
    fn commit(&mut self, next: VaultDocument) -> Result<()> {
        Self::validate(&next)?;
        let bytes = Zeroizing::new(
            serde_json::to_vec(&next)
                .map_err(|_| Error::new("VAULT_FORMAT", "无法编码密钥库。"))?,
        );
        encrypted_write_with(
            &self.directory.join(storage::vault_filename()),
            &bytes,
            self.protector.as_ref(),
        )?;
        self.document = next;
        Ok(())
    }
    pub fn snapshot(&self) -> SnapshotView {
        SnapshotView {
            keys: self
                .document
                .keys
                .iter()
                .map(|key| KeyView {
                    id: key.id,
                    name: key.name.clone(),
                    mask: MASK,
                    updated_utc: key.updated_utc,
                })
                .collect(),
            targets: self.document.targets.clone(),
        }
    }
    pub fn directory(&self) -> &Path {
        &self.directory
    }
    pub fn backup_directory(&self) -> PathBuf {
        self.directory.join("backups")
    }
    pub fn save_key(
        &mut self,
        id: Option<Uuid>,
        name: String,
        new_secret: Zeroizing<String>,
    ) -> Result<Uuid> {
        let name = name.trim().to_owned();
        if name.encode_utf16().count() == 0
            || name.encode_utf16().count() > 80
            || name.chars().any(char::is_control)
        {
            return Err(Error::new("KEY_NAME", "名称须为 1–80 个可显示字符。"));
        }
        if self
            .document
            .keys
            .iter()
            .any(|key| Some(key.id) != id && windows::equal_case(&key.name, &name))
        {
            return Err(Error::new("KEY_DUPLICATE", "密钥名称已存在。"));
        }
        let current = id.and_then(|id| self.document.keys.iter().find(|key| key.id == id));
        if id.is_some() && current.is_none() {
            return Err(Error::new("KEY_MISSING", "所选密钥不存在。"));
        }
        let secret = if new_secret.is_empty() {
            current
                .map(|key| key.secret.0.clone())
                .unwrap_or(new_secret)
        } else {
            new_secret
        };
        if secret.is_empty()
            || secret.encode_utf16().count() > 8192
            || secret.chars().any(char::is_control)
            || secret.trim() != secret.as_str()
        {
            return Err(Error::new(
                "KEY_VALUE",
                "密钥不能为空、包含控制字符或首尾空白。",
            ));
        }
        let id = id.unwrap_or_else(Uuid::new_v4);
        let mut next = self.document.clone();
        next.keys.retain(|key| key.id != id);
        next.keys.push(KeyEntry {
            id,
            name,
            secret: Secret(secret),
            updated_utc: Utc::now(),
        });
        self.commit(next)?;
        Ok(id)
    }
    pub fn delete_key(&mut self, id: Uuid) -> Result<()> {
        if self
            .document
            .targets
            .iter()
            .any(|target| target.key_id == id)
        {
            return Err(Error::new("KEY_IN_USE", "请先修改或删除引用此密钥的目标。"));
        }
        let mut next = self.document.clone();
        let old = next.keys.len();
        next.keys.retain(|key| key.id != id);
        if next.keys.len() == old {
            return Err(Error::new("KEY_MISSING", "所选密钥不存在。"));
        }
        self.commit(next)
    }
    pub fn save_target(&mut self, mut target: TargetMapping) -> Result<Uuid> {
        if target.label.trim().is_empty()
            || target.label.encode_utf16().count() > 80
            || target.label.chars().any(char::is_control)
        {
            return Err(Error::new(
                "TARGET_LABEL",
                "工具用途须为 1–80 个可显示字符。",
            ));
        }
        if !self.document.keys.iter().any(|key| key.id == target.key_id) {
            return Err(Error::new("KEY_MISSING", "请先选择命名密钥。"));
        }
        target.file_path = windows::canonical(&target.file_path)?;
        target.pointer = jsonc::normalize(&target.pointer)?;
        if self.document.targets.iter().any(|other| {
            other.id != target.id
                && windows::same_path(&other.file_path, &target.file_path)
                && other.pointer == target.pointer
        }) {
            return Err(Error::new("TARGET_DUPLICATE", "此文件的同一字段已注册。"));
        }
        if target.id.is_nil() {
            target.id = Uuid::new_v4();
        }
        target.label = target.label.trim().to_owned();
        let id = target.id;
        let mut next = self.document.clone();
        next.targets.retain(|other| other.id != id);
        next.targets.push(target);
        self.commit(next)?;
        Ok(id)
    }
    pub fn delete_target(&mut self, id: Uuid) -> Result<()> {
        let mut next = self.document.clone();
        let old = next.targets.len();
        next.targets.retain(|target| target.id != id);
        if next.targets.len() == old {
            return Err(Error::new("TARGET_MISSING", "所选目标不存在。"));
        }
        self.commit(next)
    }
    pub(crate) fn secret(&self, id: Uuid) -> Result<Zeroizing<String>> {
        self.document
            .keys
            .iter()
            .find(|key| key.id == id)
            .map(|key| key.secret.0.clone())
            .ok_or(Error::new("KEY_MISSING", "映射引用的密钥不存在。"))
    }
    /// Backend-only provider credential. Never serialize or return through IPC.
    pub fn usage_credential(&self, id: Uuid) -> Result<Zeroizing<String>> {
        self.secret(id)
    }
}
