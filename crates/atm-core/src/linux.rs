//! Linux file operations and authenticated envelopes. No plaintext fallback.
use crate::{
    storage::Protector,
    windows::{hash, FileSnapshot, Fingerprint},
    Error, Result, MAX_CONFIG_BYTES, MAX_ENCRYPTED_BYTES,
};
use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce,
};
use std::{
    ffi::{CString, OsStr},
    fs::File,
    io::{Read, Seek, SeekFrom},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::MetadataExt},
    },
    path::{Component, Path},
};
use zeroize::Zeroizing;

const HEADER: &[u8] = b"LKM-LINUX-V1\0";
fn keyring_error(_: secret_service::Error) -> Error {
    Error::new(
        "STORAGE_UNAVAILABLE",
        "会话 Secret Service 不可用；请在系统中启用并解锁 keyring。不会回退到明文。",
    )
}
fn connect_keyring() -> Result<secret_service::blocking::SecretService<'static>> {
    if !std::env::var("DBUS_SESSION_BUS_ADDRESS").is_ok_and(|v| v.starts_with("unix:")) {
        return Err(Error::new(
            "STORAGE_UNAVAILABLE",
            "没有本机会话 keyring，安全存储不可用。",
        ));
    }
    secret_service::blocking::SecretService::connect(secret_service::EncryptionType::Dh)
        .map_err(keyring_error)
}
fn key_attributes() -> std::collections::HashMap<&'static str, &'static str> {
    std::collections::HashMap::from([
        ("application", "ai-tooling-manager"),
        ("purpose", "linux-aead-master-v1"),
    ])
}
fn storage_key() -> Result<Zeroizing<[u8; 32]>> {
    let service = connect_keyring()?;
    let items = service
        .search_items(key_attributes())
        .map_err(keyring_error)?;
    if !items.locked.is_empty() {
        return Err(Error::new(
            "STORAGE_LOCKED",
            "应用主密钥已锁定；请先在系统 keyring 中解锁。",
        ));
    }
    if items.unlocked.is_empty() {
        return Err(Error::new(
            "STORAGE_NOT_CONNECTED",
            "请先主动连接安全存储并确认在 keyring 中创建本应用主密钥。",
        ));
    }
    if items.unlocked.len() != 1 {
        return Err(Error::new(
            "STORAGE_KEY",
            "发现重复应用主密钥，拒绝选择或覆盖。",
        ));
    }
    let raw = Zeroizing::new(items.unlocked[0].get_secret().map_err(keyring_error)?);
    if raw.len() != 32 {
        return Err(Error::new(
            "STORAGE_KEY",
            "keyring 中的应用主密钥格式无效。",
        ));
    }
    let mut key = Zeroizing::new([0; 32]);
    key.copy_from_slice(&raw);
    Ok(key)
}
/// Only called by a user-confirmed product command; never by startup or tests.
pub fn initialize_storage(confirmed: bool) -> Result<()> {
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认在会话 keyring 中创建应用主密钥。",
        ));
    }
    let service = connect_keyring()?;
    let items = service
        .search_items(key_attributes())
        .map_err(keyring_error)?;
    if !items.locked.is_empty() {
        return Err(Error::new(
            "STORAGE_LOCKED",
            "主密钥已锁定；未创建或替换条目。",
        ));
    }
    if items.unlocked.len() > 1 {
        return Err(Error::new("STORAGE_KEY", "发现重复应用主密钥，拒绝覆盖。"));
    }
    if items.unlocked.len() == 1 {
        drop(items);
        drop(service);
        return storage_key().map(|_| ());
    }
    let collection = service.get_default_collection().map_err(keyring_error)?;
    if collection.is_locked().map_err(keyring_error)? {
        return Err(Error::new(
            "STORAGE_LOCKED",
            "默认 keyring 已锁定；不会自动解锁或新建集合。",
        ));
    }
    let mut key = Zeroizing::new([0u8; 32]);
    getrandom::getrandom(key.as_mut())
        .map_err(|_| Error::new("STORAGE_RANDOM", "安全随机源不可用。"))?;
    collection
        .create_item(
            "Local Key Manager encryption key",
            key_attributes(),
            key.as_ref(),
            false,
            "application/octet-stream",
        )
        .map_err(keyring_error)?;
    // Reject duplicates caused by concurrent first connections; never pick an arbitrary key.
    drop(collection);
    drop(items);
    drop(service);
    let loaded = storage_key()?;
    if loaded.as_ref() != key.as_ref() {
        return Err(Error::new(
            "STORAGE_KEY",
            "主密钥初始化发生并发变化；拒绝继续写入。",
        ));
    }
    Ok(())
}
pub fn crypt(input: &[u8], protect: bool) -> Result<Zeroizing<Vec<u8>>> {
    if !protect && !input.starts_with(HEADER) {
        return Err(Error::new(
            "STORAGE_FORMAT",
            "Linux 不支持解密 DPAPI 或明文文件。",
        ));
    }
    AeadProtector::new(storage_key()?).crypt(input, protect)
}
fn path_error() -> Error {
    Error::new(
        "PATH_LOCAL",
        "请选择本机绝对路径的普通文件；不支持链接或路径跳转。",
    )
}
fn c_name(name: &OsStr) -> Result<CString> {
    CString::new(name.as_bytes()).map_err(|_| path_error())
}
fn valid_path(path: &Path) -> Result<()> {
    if !path.is_absolute()
        || path
            .as_os_str()
            .as_bytes()
            .iter()
            .any(|b| *b < 32 || *b == 127)
        || path
            .as_os_str()
            .as_bytes()
            .split(|b| *b == b'/')
            .any(|p| p == b"." || p == b"..")
    {
        return Err(path_error());
    }
    Ok(())
}
fn root() -> Result<File> {
    // SAFETY: static NUL-terminated path and valid flags; successful fd is owned.
    let fd = unsafe {
        libc::open(
            c"/".as_ptr(),
            libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC,
        )
    };
    if fd < 0 {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    Ok(unsafe { File::from_raw_fd(fd) })
}
fn open_at(parent: &File, name: &OsStr, flags: i32, mode: u32) -> Result<File> {
    let name = c_name(name)?;
    // SAFETY: borrowed live directory fd and NUL-terminated name, fd transferred once.
    let fd = unsafe {
        libc::openat(
            parent.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK,
            mode,
        )
    };
    if fd < 0 {
        let e = std::io::Error::last_os_error();
        return Err(
            if matches!(e.raw_os_error(), Some(libc::ELOOP | libc::ENOTDIR)) {
                Error::new("PATH_REPARSE", "拒绝符号链接或非目录路径。")
            } else {
                Error::io(e)
            },
        );
    }
    Ok(unsafe { File::from_raw_fd(fd) })
}
fn directory(path: &Path, create: bool) -> Result<File> {
    valid_path(path)?;
    let mut current = root()?;
    for component in path.components() {
        let Component::Normal(name) = component else {
            continue;
        };
        match open_at(&current, name, libc::O_RDONLY | libc::O_DIRECTORY, 0) {
            Ok(next) => current = next,
            Err(e) if create && e.code == "FILE_MISSING" => {
                let c = c_name(name)?;
                // SAFETY: directory descriptor and name are live; only a private directory is created.
                if unsafe { libc::mkdirat(current.as_raw_fd(), c.as_ptr(), 0o700) } != 0 {
                    return Err(Error::io(std::io::Error::last_os_error()));
                }
                current.sync_all()?;
                current = open_at(&current, name, libc::O_RDONLY | libc::O_DIRECTORY, 0)?;
            }
            Err(e) => return Err(e),
        }
    }
    Ok(current)
}
fn parent(path: &Path) -> Result<(File, &OsStr)> {
    valid_path(path)?;
    let dir = path.parent().ok_or_else(path_error)?;
    let name = path.file_name().ok_or_else(path_error)?;
    Ok((directory(dir, false)?, name))
}
pub fn ensure_private_directory(path: &Path) -> Result<()> {
    let dir = directory(path, true)?;
    let m = dir.metadata()?;
    // SAFETY: geteuid has no parameters and no side effects.
    if m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o077 != 0 {
        return Err(Error::new(
            "STORAGE_PERMISSIONS",
            "应用数据目录必须由当前用户拥有且仅本人可访问（0700）；未更改现有权限。",
        ));
    }
    Ok(())
}
fn check_file(file: &File) -> Result<()> {
    let m = file.metadata()?;
    if !m.is_file() {
        return Err(path_error());
    }
    if m.nlink() != 1 {
        return Err(Error::new(
            "PATH_HARDLINK",
            "不支持有多个硬链接的配置或存储文件。",
        ));
    }
    // SAFETY: statfs points to a valid, initialized output buffer.
    let mut info: libc::statfs = unsafe { std::mem::zeroed() };
    if unsafe { libc::fstatfs(file.as_raw_fd(), &mut info) } != 0 {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    check_filesystem_type(info.f_type as u32)
}
fn check_filesystem_type(kind: u32) -> Result<()> {
    // Native local kernel filesystems; FUSE and unrecognized types cannot prove locality.
    if !matches!(
        kind,
        0xef53 | 0x58465342 | 0x9123683e | 0xf2f52010 | 0x01021994 | 0x858458f6 | 0x794c7630
    ) {
        return Err(Error::new(
            "PATH_LOCAL",
            "仅支持已识别的本地内核文件系统；不支持 FUSE、远程、系统虚拟或未知文件系统。",
        ));
    }
    Ok(())
}
pub fn open_regular(path: &Path) -> Result<File> {
    let (dir, name) = parent(path)?;
    let file = open_at(&dir, name, libc::O_RDONLY, 0)?;
    check_file(&file)?;
    Ok(file)
}
pub fn canonical(path: &str) -> Result<String> {
    let file = open_regular(Path::new(path))?;
    drop(file);
    // Each component has already been opened without following links.
    Path::new(path)
        .components()
        .collect::<std::path::PathBuf>()
        .to_str()
        .map(str::to_owned)
        .ok_or_else(path_error)
}
pub fn equal_case(a: &str, b: &str) -> bool {
    a == b
}
pub fn open_guard(path: &str) -> Result<File> {
    open_regular(Path::new(path))
}
pub fn create_staging(path: &Path) -> Result<File> {
    let (dir, name) = parent(path)?;
    let file = open_at(
        &dir,
        name,
        libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
        0o600,
    )?;
    check_file(&file)?;
    Ok(file)
}
pub fn create_config_staging(path: &Path, original: &File) -> Result<File> {
    let m = original.metadata()?;
    if m.mode() & 0o222 == 0 {
        return Err(Error::new("ACCESS_DENIED", "目标配置只读，未替换。"));
    }
    // Avoid silently dropping custom ACLs or other extended security metadata.
    // SAFETY: no output buffer is requested; f{list,get}xattr only reports metadata lengths.
    if unsafe { libc::flistxattr(original.as_raw_fd(), std::ptr::null_mut(), 0) } != 0 {
        return Err(Error::new(
            "STAGING_SECURITY",
            "目标含扩展属性或 ACL，暂不支持安全保留，未替换。",
        ));
    }
    if m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o7000 != 0 {
        return Err(Error::new(
            "STAGING_SECURITY",
            "不支持其他用户拥有或带特殊权限的配置。",
        ));
    }
    let stage = create_staging(path)?;
    // A new inode can inherit a default ACL even when the moved-in original
    // has no ACL. Restoring its ordinary group bits could activate named users.
    // Reject before writing plaintext; the caller owns staging cleanup.
    // SAFETY: a live descriptor, no output buffer; this only queries name lengths.
    if unsafe { libc::flistxattr(stage.as_raw_fd(), std::ptr::null_mut(), 0) } != 0 {
        return Err(Error::new(
            "STAGING_SECURITY",
            "暂存文件继承了 ACL 或扩展属性，无法确认权限边界，未替换。",
        ));
    }
    // Staging is 0600 until immediately before rename; broad source modes never expose staging.
    Ok(stage)
}
pub fn open_lock(path: &Path) -> Result<File> {
    let (dir, name) = parent(path)?;
    let file = open_at(&dir, name, libc::O_RDWR | libc::O_CREAT, 0o600)?;
    check_file(&file)?;
    if file.metadata()?.mode() & 0o077 != 0 {
        return Err(Error::new(
            "STORAGE_PERMISSIONS",
            "锁文件权限过宽，未更改现有权限。",
        ));
    }
    // SAFETY: the fd is live and its owner remains in the Vault.
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err(Error::new("VAULT_BUSY", "此密钥库已由另一个窗口打开。"));
    }
    Ok(file)
}
fn signature(m: &std::fs::Metadata) -> (u64, u64, i64, i64, i64, i64, u64, u32) {
    (
        m.dev(),
        m.ino(),
        m.mtime(),
        m.mtime_nsec(),
        m.ctime(),
        m.ctime_nsec(),
        m.len(),
        m.mode(),
    )
}
pub fn snapshot(path: &str, file: &mut File) -> Result<FileSnapshot> {
    check_file(file)?;
    let before = file.metadata()?;
    if before.len() > MAX_CONFIG_BYTES as u64 {
        return Err(Error::new("CONFIG_SIZE", "配置文件超过 16 MiB，拒绝处理。"));
    }
    let named = open_regular(Path::new(path))?.metadata()?;
    if signature(&before) != signature(&named) {
        return Err(Error::new("FILE_CHANGED", "文件自预览后变化，请重新预览。"));
    }
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Zeroizing::new(Vec::new());
    (&mut *file)
        .take(MAX_CONFIG_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_CONFIG_BYTES
        || signature(&before) != signature(&file.metadata()?)
        || signature(&before) != signature(&open_regular(Path::new(path))?.metadata()?)
    {
        return Err(Error::new("FILE_CHANGED", "读取期间文件变化，请重新预览。"));
    }
    Ok(FileSnapshot {
        path: path.into(),
        fingerprint: Fingerprint {
            hash: hash(&bytes),
            length: bytes.len() as u64,
            last_write: (before.mtime() as u64)
                .wrapping_mul(1_000_000_000)
                .wrapping_add(before.mtime_nsec() as u64),
            identity: format!(
                "{}:{}:{}:{}",
                before.dev(),
                before.ino(),
                before.ctime(),
                before.ctime_nsec()
            ),
        },
        bytes,
    })
}
pub fn replace(temp: &Path, destination: &Path) -> Result<()> {
    if temp.parent() != destination.parent() {
        return Err(path_error());
    }
    let (dir, temp_name) = parent(temp)?;
    let dest_name = destination.file_name().ok_or_else(path_error)?;
    let dest = open_at(&dir, dest_name, libc::O_RDONLY, 0)?;
    check_file(&dest)?;
    let m = dest.metadata()?;
    if m.mode() & 0o222 == 0 {
        return Err(Error::new("ACCESS_DENIED", "目标配置只读，未替换。"));
    }
    let stage = open_at(&dir, temp_name, libc::O_RDWR, 0)?;
    check_file(&stage)?;
    // Preserve ordinary destination mode and group only at the final rename.
    // SAFETY: the open descriptor belongs to this private staging file.
    if unsafe { libc::fchown(stage.as_raw_fd(), m.uid(), m.gid()) } != 0 {
        return Err(Error::new("STAGING_SECURITY", "无法保留目标权限，未替换。"));
    }
    stage.sync_all()?;
    let temp_name = c_name(temp_name)?;
    let dest_name = c_name(dest_name)?;
    // Both names are anchored to the same directory fd; no shell or path traversal.
    if unsafe {
        libc::renameat(
            dir.as_raw_fd(),
            temp_name.as_ptr(),
            dir.as_raw_fd(),
            dest_name.as_ptr(),
        )
    } != 0
    {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    // Widen ordinary permissions only after the plaintext staging name is gone.
    if unsafe { libc::fchmod(stage.as_raw_fd(), m.mode() & 0o777) } != 0 {
        return Err(Error::new(
            "STAGING_SECURITY",
            "替换后权限未能恢复，请核对目标文件。",
        ));
    }
    stage.sync_all()?;
    dir.sync_all()?;
    Ok(())
}
pub fn sync_parent(path: &Path) -> Result<()> {
    directory(path.parent().ok_or_else(path_error)?, false)?
        .sync_all()
        .map_err(Error::io)
}
pub fn install_new(temp: &Path, destination: &Path) -> Result<()> {
    if temp.parent() != destination.parent() {
        return Err(path_error());
    }
    let (dir, source) = parent(temp)?;
    let destination = c_name(destination.file_name().ok_or_else(path_error)?)?;
    let source = c_name(source)?;
    // No-overwrite installation anchored to one checked directory descriptor.
    if unsafe {
        libc::renameat2(
            dir.as_raw_fd(),
            source.as_ptr(),
            dir.as_raw_fd(),
            destination.as_ptr(),
            libc::RENAME_NOREPLACE,
        )
    } != 0
    {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    dir.sync_all().map_err(Error::io)
}

/// Explicit in-memory key holder, also used by isolated synthetic tests.
pub struct AeadProtector {
    key: Zeroizing<[u8; 32]>,
}
impl AeadProtector {
    pub fn new(key: Zeroizing<[u8; 32]>) -> Self {
        Self { key }
    }
}
impl Protector for AeadProtector {
    fn crypt(&self, input: &[u8], protect: bool) -> Result<Zeroizing<Vec<u8>>> {
        let cipher = Aes256Gcm::new_from_slice(self.key.as_ref())
            .map_err(|_| Error::new("STORAGE_KEY", "加密主密钥无效。"))?;
        if input.len() > MAX_ENCRYPTED_BYTES - HEADER.len() - 28 {
            return Err(Error::new("DATA_SIZE", "数据超出安全上限。"));
        }
        if protect {
            let mut nonce = [0; 12];
            getrandom::getrandom(&mut nonce)
                .map_err(|_| Error::new("STORAGE_RANDOM", "安全随机源不可用。"))?;
            let cipher_text = cipher
                .encrypt(
                    Nonce::from_slice(&nonce),
                    Payload {
                        msg: input,
                        aad: HEADER,
                    },
                )
                .map_err(|_| Error::new("STORAGE_CRYPTO", "加密失败。"))?;
            let mut output = Vec::with_capacity(HEADER.len() + 12 + cipher_text.len());
            output.extend(HEADER);
            output.extend(nonce);
            output.extend(cipher_text);
            Ok(Zeroizing::new(output))
        } else {
            if !input.starts_with(HEADER) || input.len() < HEADER.len() + 28 {
                return Err(Error::new(
                    "STORAGE_FORMAT",
                    "不是此平台支持的加密文件；未改动原文件。",
                ));
            }
            cipher
                .decrypt(
                    Nonce::from_slice(&input[HEADER.len()..HEADER.len() + 12]),
                    Payload {
                        msg: &input[HEADER.len() + 12..],
                        aad: HEADER,
                    },
                )
                .map(Zeroizing::new)
                .map_err(|_| {
                    Error::new(
                        "STORAGE_CRYPTO",
                        "解密或完整性验证失败；请检查 keyring 和备份。",
                    )
                })
        }
    }
}

#[cfg(test)]
mod filesystem_policy_tests {
    use super::check_filesystem_type;

    #[test]
    fn fuse_remote_virtual_and_unknown_filesystems_are_rejected() {
        // Linux uapi magic.h oracle; no mounts, keyring or credentials are used.
        for kind in [
            0x65735546, 0x6969, 0x517b, 0xff534d42, 0xfe534d42, 0x00c36400, 0x01021997, 0x9fa0,
            0x62656572, 0xdeadbeef,
        ] {
            assert!(matches!(check_filesystem_type(kind), Err(e) if e.code == "PATH_LOCAL"));
        }
    }

    #[test]
    fn native_kernel_filesystems_used_by_local_and_ci_fixtures_are_allowed() {
        for kind in [0xef53, 0x58465342, 0x01021994, 0x794c7630] {
            assert!(check_filesystem_type(kind).is_ok());
        }
    }
}
