//! macOS native file operations and Keychain-backed encryption. No plaintext fallback.
pub use crate::macos_keychain::AeadProtector;
use crate::{
    windows::{hash, FileSnapshot, Fingerprint},
    Error, Result, MAX_CONFIG_BYTES,
};
use std::{
    ffi::{c_void, CString, OsStr},
    fs::File,
    io::{Read, Seek, SeekFrom},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::MetadataExt},
    },
    path::{Component, Path, PathBuf},
};
use zeroize::Zeroizing;

extern "C" {
    fn fcopyfile(from_fd: i32, to_fd: i32, state: *mut c_void, flags: u32) -> i32;
    fn renameatx_np(
        from_fd: i32,
        from: *const std::ffi::c_char,
        to_fd: i32,
        to: *const std::ffi::c_char,
        flags: u32,
    ) -> i32;
    fn acl_get_fd_np(fd: i32, kind: u32) -> *mut c_void;
    fn acl_get_entry(acl: *mut c_void, entry: i32, output: *mut *mut c_void) -> i32;
    fn acl_free(acl: *mut c_void) -> i32;
}
fn has_acl(file: &File) -> Result<bool> {
    // SAFETY: SDK ACL_TYPE_EXTENDED, a live fd, and exactly one acl_free for
    // the returned owned ACL. macOS returns 0 for an entry, -1/EINVAL at end.
    unsafe {
        let acl = acl_get_fd_np(file.as_raw_fd(), 0x00000100);
        if acl.is_null() {
            if std::io::Error::last_os_error().raw_os_error() == Some(libc::ENOENT) {
                return Ok(false);
            }
            return Err(Error::new("STAGING_SECURITY", "无法验证文件 ACL，未替换。"));
        }
        let mut entry = std::ptr::null_mut();
        let result = acl_get_entry(acl, 0, &mut entry);
        let error = std::io::Error::last_os_error().raw_os_error();
        acl_free(acl);
        if result == 0 {
            Ok(true)
        } else if error == Some(libc::EINVAL) {
            Ok(false)
        } else {
            Err(Error::new("STAGING_SECURITY", "无法验证文件 ACL，未替换。"))
        }
    }
}
fn system_alias(path: &Path) -> Result<PathBuf> {
    // These are OS-owned aliases on macOS, not permission to follow arbitrary
    // user links. Verify the root-owned link and its exact documented target.
    for (alias, target) in [
        ("/var", "/private/var"),
        ("/tmp", "/private/tmp"),
        ("/etc", "/private/etc"),
    ] {
        if let Ok(tail) = path.strip_prefix(alias) {
            let metadata = std::fs::symlink_metadata(alias)?;
            if metadata.file_type().is_symlink() {
                let actual = std::fs::read_link(alias)?;
                // Apple installs these root aliases as either absolute links
                // or root-relative "private/tmp" / "private/var" spellings.
                if metadata.uid() != 0
                    || (actual != Path::new(target) && actual != Path::new(&target[1..]))
                {
                    return Err(path_error());
                }
                return Ok(Path::new(target).join(tail));
            }
        }
    }
    Ok(path.into())
}
fn check_private_file(file: &File) -> Result<()> {
    let metadata = file.metadata()?;
    if metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0
        || has_acl(file)?
    {
        return Err(Error::new(
            "STORAGE_PERMISSIONS",
            "安全存储文件须由本人拥有且权限为 0600；不支持额外 ACL。",
        ));
    }
    Ok(())
}
pub fn open_encrypted(path: &Path) -> Result<File> {
    let file = open_regular(path)?;
    check_private_file(&file)?;
    Ok(file)
}
pub fn crypt(input: &[u8], protect: bool) -> Result<Zeroizing<Vec<u8>>> {
    crate::macos_keychain::crypt_with(&crate::macos_keychain::NativeKeychain, input, protect)
}
pub fn initialize_storage(directory: &Path, confirmed: bool) -> Result<()> {
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认连接 macOS Keychain。",
        ));
    }
    ensure_private_directory(directory)?;
    let mut existing = false;
    for name in [
        crate::storage::vault_filename(),
        crate::storage::template_filename(),
        "templates.required",
    ] {
        existing |= crate::storage::file_exists(&directory.join(name))?;
    }
    let backups = directory.join("backups");
    if crate::storage::file_exists(&backups)? {
        ensure_private_directory(&backups)?;
        existing |= std::fs::read_dir(backups)?.next().is_some();
    }
    crate::macos_keychain::initialize_with(&crate::macos_keychain::NativeKeychain, true, existing)
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
    let normalized = system_alias(path)?;
    let path = normalized.as_path();
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
    check_filesystem(&dir)?;
    if m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o077 != 0 || has_acl(&dir)? {
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
    check_filesystem(file)
}
fn filesystem_policy(name: &[u8], local: bool) -> Result<()> {
    if local && matches!(name, b"apfs" | b"hfs") {
        return Ok(());
    }
    Err(Error::new(
        "PATH_LOCAL",
        "仅支持本机 APFS/HFS+；不支持网络、FUSE 或未知文件系统。",
    ))
}
fn check_filesystem(file: &File) -> Result<()> {
    // SAFETY: a live fd and an initialized SDK statfs output buffer.
    let mut info: libc::statfs = unsafe { std::mem::zeroed() };
    if unsafe { libc::fstatfs(file.as_raw_fd(), &mut info) } != 0 {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    let name: Vec<u8> = info
        .f_fstypename
        .iter()
        .map(|b| *b as u8)
        .take_while(|b| *b != 0)
        .collect();
    filesystem_policy(&name, (info.f_flags as u64 & libc::MNT_LOCAL as u64) != 0)
}
pub fn open_regular(path: &Path) -> Result<File> {
    let (dir, name) = parent(path)?;
    let file = open_at(&dir, name, libc::O_RDONLY, 0)?;
    check_file(&file)?;
    Ok(file)
}
pub fn canonical(path: &str) -> Result<String> {
    let file = open_regular(Path::new(path))?;
    let mut bytes = [0u8; libc::PATH_MAX as usize];
    // SAFETY: Darwin F_GETPATH writes at most PATH_MAX bytes into this buffer.
    if unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETPATH, bytes.as_mut_ptr()) } != 0 {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    let end = bytes.iter().position(|b| *b == 0).ok_or_else(path_error)?;
    std::str::from_utf8(&bytes[..end])
        .map(str::to_owned)
        .map_err(|_| path_error())
}
pub fn equal_case(a: &str, b: &str) -> bool {
    a == b
}

pub fn same_path(a: &str, b: &str) -> bool {
    if a == b {
        return true;
    }
    // File identity handles APFS volume-specific case/Unicode behavior. Names
    // and paths are never blindly case-folded, including on case-sensitive APFS.
    if !Path::new(a).is_absolute() || !Path::new(b).is_absolute() {
        return false;
    }
    match (open_regular(Path::new(a)), open_regular(Path::new(b))) {
        (Ok(left), Ok(right)) => match (left.metadata(), right.metadata()) {
            (Ok(left), Ok(right)) => left.dev() == right.dev() && left.ino() == right.ino(),
            _ => false,
        },
        _ => false,
    }
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
    check_private_file(&file)?;
    Ok(file)
}
fn check_write_security(file: &File) -> Result<()> {
    let m = file.metadata()?;
    if m.mode() & 0o222 == 0 {
        return Err(Error::new("ACCESS_DENIED", "目标配置只读，未替换。"));
    }
    // Darwin flistxattr has a fourth options argument. Native fcopyfile below
    // preserves xattrs (including the OS-added provenance), without copying ACLs.
    if unsafe { libc::flistxattr(file.as_raw_fd(), std::ptr::null_mut(), 0, 0) } < 0
        || has_acl(file)?
    {
        return Err(Error::new(
            "STAGING_SECURITY",
            "目标 ACL 或扩展属性无法安全保留，未替换。",
        ));
    }
    if m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o7000 != 0 {
        return Err(Error::new(
            "STAGING_SECURITY",
            "不支持其他用户拥有或带特殊权限的配置。",
        ));
    }
    Ok(())
}
pub fn create_config_staging(path: &Path, original: &File) -> Result<File> {
    check_write_security(original)?;
    let stage = create_staging(path)?;
    copy_xattrs(original, &stage)?;
    Ok(stage)
}
fn copy_xattrs(original: &File, stage: &File) -> Result<()> {
    check_xattr_budget(original)?;
    // SAFETY: both descriptors are live; COPYFILE_XATTR is 1 << 2 in Apple's
    // copyfile.h. Do not copy data, ACLs, owner or ordinary modes into staging.
    if unsafe {
        fcopyfile(
            original.as_raw_fd(),
            stage.as_raw_fd(),
            std::ptr::null_mut(),
            1 << 2,
        )
    } != 0
    {
        return Err(Error::new(
            "STAGING_SECURITY",
            "无法完整保留目标扩展属性，未替换。",
        ));
    }
    check_private_file(stage)
}
fn check_xattr_budget(file: &File) -> Result<()> {
    let error = || {
        Error::new(
            "STAGING_SECURITY",
            "扩展属性超出安全范围或包含资源叉，未替换。",
        )
    };
    // Bound metadata as well as the ordinary JSON bytes. Resource forks are
    // separate file contents and are intentionally outside configuration scope.
    let size = unsafe { libc::flistxattr(file.as_raw_fd(), std::ptr::null_mut(), 0, 0) };
    if !(0..=16384).contains(&size) {
        return Err(error());
    }
    if size == 0 {
        return Ok(());
    }
    let mut names = vec![0u8; size as usize];
    let count =
        unsafe { libc::flistxattr(file.as_raw_fd(), names.as_mut_ptr().cast(), names.len(), 0) };
    if count < 0 || count as usize > names.len() {
        return Err(error());
    }
    names.truncate(count as usize);
    let mut total = 0usize;
    for name in names.split(|b| *b == 0).filter(|name| !name.is_empty()) {
        if name == b"com.apple.ResourceFork" {
            return Err(error());
        }
        let name = CString::new(name).map_err(|_| error())?;
        let length = unsafe {
            libc::fgetxattr(
                file.as_raw_fd(),
                name.as_ptr(),
                std::ptr::null_mut(),
                0,
                0,
                0,
            )
        };
        if !(0..=1048576).contains(&length) {
            return Err(error());
        }
        total = total.checked_add(length as usize).ok_or_else(error)?;
        if total > 8 * 1024 * 1024 {
            return Err(error());
        }
    }
    Ok(())
}
pub fn open_lock(path: &Path) -> Result<File> {
    let (dir, name) = parent(path)?;
    let file = open_at(&dir, name, libc::O_RDWR | libc::O_CREAT, 0o600)?;
    check_file(&file)?;
    if file.metadata()?.uid() != unsafe { libc::geteuid() }
        || file.metadata()?.mode() & 0o077 != 0
        || has_acl(&file)?
    {
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
    check_write_security(&dest)?;
    let stage = open_at(&dir, temp_name, libc::O_RDWR, 0)?;
    check_file(&stage)?;
    check_private_file(&stage)?;
    copy_xattrs(&dest, &stage)?;
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
    if unsafe { libc::fchmod(stage.as_raw_fd(), (m.mode() & 0o777) as libc::mode_t) } != 0 {
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
    let stage = open_at(&dir, source, libc::O_RDONLY, 0)?;
    check_file(&stage)?;
    check_private_file(&stage)?;
    let destination = c_name(destination.file_name().ok_or_else(path_error)?)?;
    let source = c_name(source)?;
    // No-overwrite installation anchored to one checked directory descriptor.
    if unsafe {
        renameatx_np(
            dir.as_raw_fd(),
            source.as_ptr(),
            dir.as_raw_fd(),
            destination.as_ptr(),
            0x00000004, // Darwin RENAME_EXCL (sys/stdio.h).
        )
    } != 0
    {
        return Err(Error::io(std::io::Error::last_os_error()));
    }
    dir.sync_all().map_err(Error::io)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_identified_local_native_filesystems_are_accepted() {
        for name in [b"apfs".as_slice(), b"hfs"] {
            assert!(filesystem_policy(name, true).is_ok());
            assert_eq!(
                filesystem_policy(name, false).unwrap_err().code,
                "PATH_LOCAL"
            );
        }
        for name in [b"smbfs".as_slice(), b"nfs", b"osxfuse", b"unknown"] {
            assert_eq!(
                filesystem_policy(name, true).unwrap_err().code,
                "PATH_LOCAL"
            );
        }
    }
}
