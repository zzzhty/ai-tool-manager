//! Production defaults always use OS storage; injection is explicit per instance.
use crate::{windows, Error, Result};
use std::{path::PathBuf, sync::Arc};
use zeroize::Zeroizing;

pub trait Protector: Send + Sync {
    fn crypt(&self, input: &[u8], protect: bool) -> Result<Zeroizing<Vec<u8>>>;
}
pub struct SystemProtector;
impl Protector for SystemProtector {
    fn crypt(&self, input: &[u8], protect: bool) -> Result<Zeroizing<Vec<u8>>> {
        windows::crypt(input, protect)
    }
}
pub fn system() -> Arc<dyn Protector> {
    Arc::new(SystemProtector)
}
pub fn demo_protector() -> Result<Arc<dyn Protector>> {
    #[cfg(target_os = "linux")]
    {
        let mut key = Zeroizing::new([0; 32]);
        getrandom::getrandom(key.as_mut())
            .map_err(|_| Error::new("STORAGE_RANDOM", "安全随机源不可用。"))?;
        Ok(Arc::new(crate::linux::AeadProtector::new(key)))
    }
    #[cfg(target_os = "macos")]
    {
        let mut key = Zeroizing::new([0; 32]);
        getrandom::getrandom(key.as_mut())
            .map_err(|_| Error::new("STORAGE_RANDOM", "安全随机源不可用。"))?;
        Ok(Arc::new(crate::macos::AeadProtector::new(key)))
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        Ok(system())
    }
}

pub fn data_directory() -> Result<PathBuf> {
    #[cfg(windows)]
    {
        std::env::var_os("LOCALAPPDATA")
            .map(|p| PathBuf::from(p).join("atm"))
            .ok_or(Error::new("DATA_PATH", "无法确定本地用户目录。"))
    }
    #[cfg(target_os = "linux")]
    {
        let base = std::env::var_os("XDG_DATA_HOME")
            .filter(|p| !p.is_empty())
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|p| PathBuf::from(p).join(".local/share")))
            .ok_or(Error::new("DATA_PATH", "无法确定本地用户目录。"))?;
        if !base.is_absolute() {
            return Err(Error::new("DATA_PATH", "用户数据目录必须为绝对路径。"));
        }
        // 历史数据目录名：ATM 改名时特意保留，避免迁移已有密钥库。
        Ok(base.join("atm"))
    }
    #[cfg(target_os = "macos")]
    {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| Error::new("DATA_PATH", "无法确定本地用户目录。"))?;
        macos_data_directory(&home)
    }
    #[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
    {
        Err(Error::new(
            "PLATFORM_UNSUPPORTED",
            "此平台暂不支持安全存储。",
        ))
    }
}

pub fn vault_filename() -> &'static str {
    if cfg!(any(target_os = "linux", target_os = "macos")) {
        "vault.atmvault"
    } else {
        "vault.dpapi"
    }
}
pub fn template_filename() -> &'static str {
    if cfg!(any(target_os = "linux", target_os = "macos")) {
        "templates.atmvault"
    } else {
        "templates.dpapi"
    }
}
pub fn ensure_directory(path: &std::path::Path) -> Result<()> {
    #[cfg(target_os = "linux")]
    {
        crate::linux::ensure_private_directory(path)
    }
    #[cfg(target_os = "macos")]
    {
        crate::macos::ensure_private_directory(path)
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        std::fs::create_dir_all(path).map_err(Error::io)
    }
}
pub fn file_exists(path: &std::path::Path) -> Result<bool> {
    match std::fs::symlink_metadata(path) {
        Ok(_metadata) => {
            #[cfg(any(target_os = "linux", target_os = "macos"))]
            if _metadata.file_type().is_symlink() {
                return Err(Error::new("PATH_REPARSE", "加密存储拒绝链接目标。"));
            }
            Ok(true)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(Error::io(e)),
    }
}

pub fn kind() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos_keychain"
    } else if cfg!(target_os = "linux") {
        "linux_secret_service"
    } else if cfg!(windows) {
        "windows_dpapi"
    } else {
        "unsupported"
    }
}

pub fn initialize(directory: &std::path::Path, confirmed: bool) -> Result<()> {
    if !confirmed {
        return Err(Error::new("CONFIRM_REQUIRED", "须确认连接系统安全存储。"));
    }
    #[cfg(target_os = "linux")]
    {
        let _ = directory;
        crate::linux::initialize_storage(confirmed)
    }
    #[cfg(target_os = "macos")]
    {
        crate::macos::initialize_storage(directory, confirmed)
    }
    #[cfg(windows)]
    {
        let _ = directory;
        Ok(())
    }
    #[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
    {
        let _ = directory;
        Err(Error::new(
            "PLATFORM_UNSUPPORTED",
            "此平台暂不支持安全存储。",
        ))
    }
}

#[cfg(any(target_os = "macos", test))]
fn macos_data_directory(home: &std::path::Path) -> Result<PathBuf> {
    if !home.is_absolute() || home.to_string_lossy().chars().any(char::is_control) {
        return Err(Error::new("DATA_PATH", "用户主目录须为本机绝对路径。"));
    }
    Ok(home.join("Library/Application Support/atm"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn macos_application_support_resolution_is_pure_and_rejects_relative_home() {
        let home = std::env::temp_dir().join("TEST_ONLY_home");
        assert_eq!(
            macos_data_directory(&home).unwrap(),
            home.join("Library/Application Support/atm")
        );
        assert_eq!(
            macos_data_directory(std::path::Path::new("relative"))
                .unwrap_err()
                .code,
            "DATA_PATH"
        );
    }
    #[test]
    fn unconfirmed_initialization_cannot_access_any_os_backend() {
        assert_eq!(
            initialize(std::path::Path::new("TEST_ONLY_missing"), false)
                .unwrap_err()
                .code,
            "CONFIRM_REQUIRED"
        );
    }
}
