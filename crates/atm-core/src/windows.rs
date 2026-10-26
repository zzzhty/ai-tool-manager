#[cfg(not(any(target_os = "linux", target_os = "macos")))]
use crate::Error;
use crate::Result;
use sha2::{Digest, Sha256};
#[cfg(not(any(target_os = "linux", target_os = "macos")))]
use std::{fs::File, path::Path};
use zeroize::Zeroizing;

pub const ENTROPY: &[u8] = b"ai-tooling-manager/v1/CurrentUser";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fingerprint {
    pub hash: String,
    pub last_write: u64,
    pub identity: String,
    pub length: u64,
}
pub struct FileSnapshot {
    pub path: String,
    pub bytes: Zeroizing<Vec<u8>>,
    pub fingerprint: Fingerprint,
}
pub fn hash(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut result = String::with_capacity(64);
    for byte in Sha256::digest(bytes) {
        result.push(HEX[(byte >> 4) as usize] as char);
        result.push(HEX[(byte & 0x0f) as usize] as char);
    }
    result
}

#[cfg(windows)]
mod native {
    use super::*;
    use crate::{MAX_CONFIG_BYTES, MAX_ENCRYPTED_BYTES};
    use std::io::Read;
    use std::{
        ffi::c_void,
        fs::OpenOptions,
        os::windows::{
            fs::{MetadataExt, OpenOptionsExt},
            io::AsRawHandle,
        },
        ptr,
    };
    use zeroize::Zeroize;

    #[repr(C)]
    struct Blob {
        size: u32,
        data: *mut u8,
    }
    #[repr(C)]
    #[derive(Default)]
    struct Time {
        low: u32,
        high: u32,
    }
    #[repr(C)]
    #[derive(Default)]
    struct Info {
        attributes: u32,
        creation: Time,
        access: Time,
        write: Time,
        volume: u32,
        size_high: u32,
        size_low: u32,
        links: u32,
        index_high: u32,
        index_low: u32,
    }
    #[link(name = "crypt32")]
    extern "system" {
        fn CryptProtectData(
            input: *const Blob,
            description: *const u16,
            entropy: *const Blob,
            reserved: *mut c_void,
            prompt: *mut c_void,
            flags: u32,
            output: *mut Blob,
        ) -> i32;
        fn CryptUnprotectData(
            input: *const Blob,
            description: *mut *mut u16,
            entropy: *const Blob,
            reserved: *mut c_void,
            prompt: *mut c_void,
            flags: u32,
            output: *mut Blob,
        ) -> i32;
    }
    #[link(name = "advapi32")]
    extern "system" {
        fn GetSecurityInfo(
            handle: *mut c_void,
            object_type: u32,
            information: u32,
            owner: *mut *mut c_void,
            group: *mut *mut c_void,
            dacl: *mut *mut c_void,
            sacl: *mut *mut c_void,
            descriptor: *mut *mut c_void,
        ) -> u32;
        fn SetSecurityInfo(
            handle: *mut c_void,
            object_type: u32,
            information: u32,
            owner: *mut c_void,
            group: *mut c_void,
            dacl: *mut c_void,
            sacl: *mut c_void,
        ) -> u32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn LocalFree(memory: *mut c_void) -> *mut c_void;
        fn GetFileInformationByHandle(handle: *mut c_void, info: *mut Info) -> i32;
        fn GetFinalPathNameByHandleW(
            handle: *mut c_void,
            path: *mut u16,
            length: u32,
            flags: u32,
        ) -> u32;
        fn ReplaceFileW(
            replaced: *const u16,
            replacement: *const u16,
            backup: *const u16,
            flags: u32,
            exclude: *mut c_void,
            reserved: *mut c_void,
        ) -> i32;
        fn GetDriveTypeW(root: *const u16) -> u32;
        fn GetFileType(handle: *mut c_void) -> u32;
        fn CompareStringOrdinal(
            left: *const u16,
            left_len: i32,
            right: *const u16,
            right_len: i32,
            ignore_case: i32,
        ) -> i32;
    }
    pub fn equal_case(left: &str, right: &str) -> bool {
        if left.is_empty() || right.is_empty() {
            return left.is_empty() && right.is_empty();
        }
        let a: Vec<u16> = left.encode_utf16().collect();
        let b: Vec<u16> = right.encode_utf16().collect();
        // SAFETY: counted, live UTF-16 buffers; no NUL termination is required.
        unsafe {
            CompareStringOrdinal(a.as_ptr(), a.len() as i32, b.as_ptr(), b.len() as i32, 1) == 2
        }
    }
    pub fn crypt(input: &[u8], protect: bool) -> Result<Zeroizing<Vec<u8>>> {
        if input.len() > MAX_ENCRYPTED_BYTES {
            return Err(Error::new("DATA_SIZE", "数据超出安全上限。"));
        }
        let data = Blob {
            size: input.len() as u32,
            data: input.as_ptr() as *mut u8,
        };
        let entropy = Blob {
            size: ENTROPY.len() as u32,
            data: ENTROPY.as_ptr() as *mut u8,
        };
        let mut output = Blob {
            size: 0,
            data: ptr::null_mut(),
        };
        // SAFETY: DPAPI only reads counted input/entropy buffers. Flag 1 is UI_FORBIDDEN,
        // and LOCAL_MACHINE is never set: ciphertext stays scoped to the current user.
        let ok = unsafe {
            if protect {
                CryptProtectData(
                    &data,
                    ptr::null(),
                    &entropy,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    1,
                    &mut output,
                )
            } else {
                CryptUnprotectData(
                    &data,
                    ptr::null_mut(),
                    &entropy,
                    ptr::null_mut(),
                    ptr::null_mut(),
                    1,
                    &mut output,
                )
            }
        };
        // Always release native allocations, including an error/oversize result.
        // The OS owns and reports this buffer; DPAPI never allocates into Rust memory.
        struct Output(Blob);
        impl Drop for Output {
            fn drop(&mut self) {
                if !self.0.data.is_null() {
                    unsafe {
                        std::slice::from_raw_parts_mut(self.0.data, self.0.size as usize).zeroize();
                        LocalFree(self.0.data.cast());
                    }
                }
            }
        }
        let output = Output(output);
        if ok == 0 {
            return Err(Error::new(
                "DPAPI_FAILED",
                "当前 Windows 用户无法加解密此数据。",
            ));
        }
        if output.0.size as usize > MAX_ENCRYPTED_BYTES
            || (output.0.data.is_null() && output.0.size != 0)
        {
            return Err(Error::new("DPAPI_SIZE", "DPAPI 输出无效。"));
        }
        if output.0.size == 0 {
            return Ok(Zeroizing::new(Vec::new()));
        }
        // SAFETY: successful DPAPI returns a LocalAlloc buffer of output.size bytes.
        let slice = unsafe { std::slice::from_raw_parts(output.0.data, output.0.size as usize) };
        Ok(Zeroizing::new(slice.to_vec()))
    }
    fn info(file: &File) -> Result<Info> {
        let mut value = Info::default();
        if unsafe { GetFileInformationByHandle(file.as_raw_handle(), &mut value) } == 0 {
            return Err(Error::new("FILE_INFO", "无法读取文件标识。"));
        }
        Ok(value)
    }
    /// Stable directory receipt, without hashing contents or following reparse points.
    pub fn directory_identity(path: &Path) -> Result<String> {
        let file = OpenOptions::new()
            .read(true)
            .share_mode(1 | 2 | 4)
            .custom_flags(0x02000000 | 0x00200000)
            .open(path)
            .map_err(Error::io)?;
        let value = info(&file)?;
        if value.attributes & 0x10 == 0 || value.attributes & 0x400 != 0 {
            return Err(Error::new("PROJECTION_OWNERSHIP", "投影目录身份无法验证。"));
        }
        Ok(format!(
            "{:08x}:{:08x}{:08x}:{:08x}{:08x}",
            value.volume,
            value.index_high,
            value.index_low,
            value.creation.high,
            value.creation.low
        ))
    }

    fn local_syntax(path: &str) -> Result<()> {
        let bytes = path.as_bytes();
        if bytes.len() < 3
            || !bytes[0].is_ascii_alphabetic()
            || bytes[1] != b':'
            || !matches!(bytes[2], b'\\' | b'/')
            || path[2..].contains(':')
            || path.chars().any(char::is_control)
        {
            return Err(Error::new(
                "PATH_LOCAL",
                "请选本机磁盘的普通文件绝对路径；不支持网络或设备路径。",
            ));
        }
        // Win32 normalizes trailing dots/spaces and recognizes DOS devices even
        // with an extension. Reject those spellings before opening any handle.
        for part in path[3..].split(['\\', '/']) {
            if matches!(part, "" | "." | "..") {
                continue;
            }
            let stem = part.split('.').next().unwrap_or("").to_ascii_uppercase();
            let device = matches!(
                stem.as_str(),
                "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$"
            ) || ["COM", "LPT"].iter().any(|prefix| {
                stem.strip_prefix(*prefix).is_some_and(|suffix| {
                    matches!(
                        suffix,
                        "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
                    )
                })
            });
            if device
                || part.ends_with('.')
                || part.ends_with(' ')
                || part.contains(['*', '?', '"', '<', '>', '|'])
            {
                return Err(Error::new("PATH_LOCAL", "路径包含设备名称或不明确的字符。"));
            }
        }
        let root: Vec<u16> = format!("{}:\\", bytes[0] as char)
            .encode_utf16()
            .chain(Some(0))
            .collect();
        // Drive letters can be mapped network shares. The resolved spelling alone
        // does not establish that a destination is on a local disk.
        if !matches!(unsafe { GetDriveTypeW(root.as_ptr()) }, 2 | 3 | 5 | 6) {
            return Err(Error::new(
                "PATH_LOCAL",
                "仅支持本机磁盘，不支持映射网络驱动器。",
            ));
        }
        Ok(())
    }
    fn ordinary_components(path: &str) -> Result<()> {
        for part in Path::new(path).ancestors() {
            // metadata follows links; symlink_metadata inspects the link itself.
            if std::fs::symlink_metadata(part)?.file_attributes() & 0x400 != 0 {
                return Err(Error::new("PATH_REPARSE", "不支持符号链接或目录联接。"));
            }
        }
        Ok(())
    }
    fn resolved(file: &File) -> Result<String> {
        if unsafe { GetFileType(file.as_raw_handle()) } != 1 {
            return Err(Error::new("PATH_LOCAL", "目标必须是本机磁盘上的普通文件。"));
        }
        let value = info(file)?;
        if value.attributes & (0x400 | 0x10) != 0 {
            return Err(Error::new("PATH_REPARSE", "不支持链接或目录目标。"));
        }
        if value.links != 1 {
            return Err(Error::new("PATH_HARDLINK", "不支持多硬链接文件。"));
        }
        let mut buffer = vec![0u16; 32768];
        let size = unsafe {
            GetFinalPathNameByHandleW(
                file.as_raw_handle(),
                buffer.as_mut_ptr(),
                buffer.len() as u32,
                0,
            )
        };
        if size == 0 || size as usize >= buffer.len() {
            return Err(Error::new("PATH_RESOLVE", "无法确认规范路径。"));
        }
        let value = String::from_utf16(&buffer[..size as usize])
            .map_err(|_| Error::new("PATH_ENCODING", "文件路径编码无效。"))?;
        let value = value.strip_prefix("\\\\?\\").unwrap_or(&value);
        local_syntax(value)?;
        ordinary_components(value)?;
        Ok(value.to_owned())
    }
    pub fn canonical(path: &str) -> Result<String> {
        local_syntax(path)?;
        if Path::new(path)
            .extension()
            .and_then(|e| e.to_str())
            .is_some_and(|e| e.eq_ignore_ascii_case("toml"))
        {
            return Err(Error::new(
                "TOML_UNSUPPORTED",
                "仅支持 JSON/JSONC；TOML 尚不支持。",
            ));
        }
        ordinary_components(path)?;
        resolved(&open_guard(path)?)
    }
    pub fn open_guard(path: &str) -> Result<File> {
        // OPEN_REPARSE_POINT prevents following a last-component link installed
        // after canonicalization. Snapshot validates the opened handle as well.
        Ok(OpenOptions::new()
            .read(true)
            .share_mode(1 | 4)
            .custom_flags(0x00200000)
            .open(path)?)
    }
    pub fn create_staging(path: &Path) -> Result<File> {
        Ok(OpenOptions::new()
            .write(true)
            .create_new(true)
            .share_mode(0)
            .open(path)?)
    }
    struct FileDacl {
        descriptor: *mut c_void,
        dacl: *mut c_void,
    }
    impl Drop for FileDacl {
        fn drop(&mut self) {
            if !self.descriptor.is_null() {
                unsafe {
                    LocalFree(self.descriptor);
                }
            }
        }
    }
    fn file_dacl(file: &File) -> Result<FileDacl> {
        let mut security = FileDacl {
            descriptor: ptr::null_mut(),
            dacl: ptr::null_mut(),
        };
        // GetSecurityInfo requires READ_CONTROL (included in GENERIC_READ).
        // DACL pointers remain valid until the returned LocalAlloc descriptor is freed.
        let status = unsafe {
            GetSecurityInfo(
                file.as_raw_handle(),
                1,
                4,
                ptr::null_mut(),
                ptr::null_mut(),
                &mut security.dacl,
                ptr::null_mut(),
                &mut security.descriptor,
            )
        };
        if status != 0 || security.descriptor.is_null() || security.dacl.is_null() {
            // An absent/null DACL grants everyone access; do not silently create
            // broadly readable plaintext when no restrictive ACL can be copied.
            return Err(Error::new(
                "STAGING_SECURITY",
                "无法读取目标文件的访问限制，拒绝创建明文暂存内容。",
            ));
        }
        Ok(security)
    }
    pub fn create_config_staging(path: &Path, destination: &File) -> Result<File> {
        let security = file_dacl(destination)?;
        // Create an empty exclusive file, then restrict that exact handle before
        // writing any plaintext. WRITE_DAC is requested only for our new file.
        let stage = OpenOptions::new()
            .write(true)
            .create_new(true)
            .share_mode(0)
            .access_mode(0x40000000 | 0x00040000 | 0x00020000)
            .open(path)?;
        // SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        // Protection prevents the parent directory from adding broader inherited ACEs.
        // https://learn.microsoft.com/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo
        let status = unsafe {
            SetSecurityInfo(
                stage.as_raw_handle(),
                1,
                0x80000004,
                ptr::null_mut(),
                ptr::null_mut(),
                security.dacl,
                ptr::null_mut(),
            )
        };
        if status != 0 {
            return Err(Error::new(
                "STAGING_SECURITY",
                "无法保护暂存文件，未写入明文配置。",
            ));
        }
        Ok(stage)
    }
    pub fn open_lock(path: &Path) -> Result<File> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .share_mode(0)
            .open(path)
            .map_err(|_| Error::new("VAULT_BUSY", "此密钥库已由另一个窗口打开。"))
    }
    pub fn snapshot(path: &str, file: &mut File) -> Result<FileSnapshot> {
        use std::io::{Seek, SeekFrom};
        let actual_path = resolved(file)?;
        if !equal_case(&actual_path, path) {
            return Err(Error::new(
                "FILE_CHANGED",
                "读取的文件路径已变化，请重新预览。",
            ));
        }
        let before = info(file)?;
        let length = ((before.size_high as u64) << 32) | before.size_low as u64;
        if length > MAX_CONFIG_BYTES as u64 {
            return Err(Error::new("CONFIG_SIZE", "配置文件超过 16 MiB，拒绝处理。"));
        }
        if before.links != 1 || before.attributes & (0x400 | 0x10) != 0 {
            return Err(Error::new(
                "PATH_CHANGED",
                "文件链接状态已改变，请重新选择普通文件。",
            ));
        }
        file.seek(SeekFrom::Start(0))?;
        let mut bytes = Zeroizing::new(vec![0; length as usize]);
        file.read_exact(&mut bytes)?;
        let after = info(file)?;
        let identity =
            |v: &Info| format!("{:08X}:{:08X}{:08X}", v.volume, v.index_high, v.index_low);
        let time = |v: &Info| ((v.write.high as u64) << 32) | v.write.low as u64;
        if identity(&before) != identity(&after)
            || time(&before) != time(&after)
            || before.size_high != after.size_high
            || before.size_low != after.size_low
            || before.links != after.links
            || before.attributes != after.attributes
            || !equal_case(&resolved(file)?, path)
        {
            return Err(Error::new("FILE_CHANGED", "文件变化，请重新预览。"));
        }
        let fingerprint = Fingerprint {
            hash: hash(&bytes),
            last_write: time(&before),
            identity: identity(&before),
            length,
        };
        Ok(FileSnapshot {
            path: path.to_owned(),
            bytes,
            fingerprint,
        })
    }
    pub fn replace(temp: &Path, destination: &Path) -> Result<()> {
        let wide = |p: &Path| {
            use std::os::windows::ffi::OsStrExt;
            p.as_os_str()
                .encode_wide()
                .chain(Some(0))
                .collect::<Vec<_>>()
        };
        let temp = wide(temp);
        let destination = wide(destination);
        if unsafe {
            ReplaceFileW(
                destination.as_ptr(),
                temp.as_ptr(),
                std::ptr::null(),
                0,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        } == 0
        {
            return Err(Error::io(std::io::Error::last_os_error()));
        }
        Ok(())
    }
    #[cfg(test)]
    mod acl_tests {
        use super::*;
        use std::io::Write;
        #[link(name = "advapi32")]
        extern "system" {
            fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
                text: *const u16,
                revision: u32,
                descriptor: *mut *mut c_void,
                size: *mut u32,
            ) -> i32;
            fn GetSecurityDescriptorDacl(
                descriptor: *mut c_void,
                present: *mut i32,
                dacl: *mut *mut c_void,
                defaulted: *mut i32,
            ) -> i32;
            fn ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor: *mut c_void,
                revision: u32,
                information: u32,
                text: *mut *mut u16,
                length: *mut u32,
            ) -> i32;
        }
        fn set_fixture_dacl(path: &Path, directory: bool, sddl: &str) {
            let text: Vec<u16> = sddl.encode_utf16().chain(Some(0)).collect();
            let mut descriptor = FileDacl {
                descriptor: ptr::null_mut(),
                dacl: ptr::null_mut(),
            };
            assert_ne!(
                unsafe {
                    ConvertStringSecurityDescriptorToSecurityDescriptorW(
                        text.as_ptr(),
                        1,
                        &mut descriptor.descriptor,
                        ptr::null_mut(),
                    )
                },
                0
            );
            let mut present = 0;
            let mut defaulted = 0;
            assert_ne!(
                unsafe {
                    GetSecurityDescriptorDacl(
                        descriptor.descriptor,
                        &mut present,
                        &mut descriptor.dacl,
                        &mut defaulted,
                    )
                },
                0
            );
            assert_ne!(present, 0);
            let file = OpenOptions::new()
                .access_mode(0x00040000 | 0x00020000)
                .share_mode(7)
                .custom_flags(if directory { 0x02000000 } else { 0 })
                .open(path)
                .expect("fixture security handle");
            assert_eq!(
                unsafe {
                    SetSecurityInfo(
                        file.as_raw_handle(),
                        1,
                        0x80000004,
                        ptr::null_mut(),
                        ptr::null_mut(),
                        descriptor.dacl,
                        ptr::null_mut(),
                    )
                },
                0
            );
        }
        fn dacl_text(file: &File) -> String {
            let security = file_dacl(file).expect("query test DACL");
            let mut text = ptr::null_mut();
            let mut length = 0;
            assert_ne!(
                unsafe {
                    ConvertSecurityDescriptorToStringSecurityDescriptorW(
                        security.descriptor,
                        1,
                        4,
                        &mut text,
                        &mut length,
                    )
                },
                0
            );
            let value = unsafe {
                String::from_utf16_lossy(std::slice::from_raw_parts(text, length as usize))
            };
            unsafe {
                LocalFree(text.cast());
            }
            value.trim_end_matches('\0').to_owned()
        }
        #[test]
        fn plaintext_staging_copies_protected_destination_dacl_before_writing() {
            let root = tempfile::tempdir().expect("isolated ACL fixture");
            // Synthetic-only directory: deliberately broader than its destination.
            set_fixture_dacl(root.path(), true, "D:P(A;OICI;FA;;;WD)");
            let destination = root.path().join("restricted.json");
            std::fs::write(&destination, b"FAKE_ORIGINAL").expect("fixture");
            set_fixture_dacl(&destination, false, "D:P(A;;FA;;;OW)(A;;FA;;;SY)");
            let guard = open_guard(destination.to_str().expect("path")).expect("destination guard");
            let expected = dacl_text(&guard);
            let temporary = root.path().join(".atm-acl-test.tmp");
            let mut stage =
                create_config_staging(&temporary, &guard).expect("restricted empty stage");
            assert_eq!(stage.metadata().expect("stage info").len(), 0);
            assert_eq!(dacl_text(&stage), expected);
            stage
                .write_all(b"FAKE_PLAINTEXT_ONLY")
                .expect("write after ACL");
            stage.sync_all().expect("flush");
            drop(stage);
            // The protection must survive the close-to-replace interval.
            assert_eq!(
                dacl_text(&File::open(&temporary).expect("owner can reopen")),
                expected
            );
            assert!(expected.starts_with("D:P"));
        }
    }
}

#[cfg(windows)]
pub use native::{canonical, crypt, equal_case, open_guard, open_lock, replace, snapshot};
#[cfg(windows)]
pub(crate) use native::{create_config_staging, create_staging};

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
mod unsupported {
    use super::*;
    fn unsupported() -> Error {
        Error::new("WINDOWS_REQUIRED", "安全存储与文件应用仅支持 Windows。")
    }
    pub fn crypt(_: &[u8], _: bool) -> Result<Zeroizing<Vec<u8>>> {
        Err(unsupported())
    }
    pub fn equal_case(a: &str, b: &str) -> bool {
        a.eq_ignore_ascii_case(b)
    }
    pub fn canonical(_: &str) -> Result<String> {
        Err(unsupported())
    }
    pub fn open_guard(_: &str) -> Result<File> {
        Err(unsupported())
    }
    pub fn create_staging(_: &Path) -> Result<File> {
        Err(unsupported())
    }
    pub fn create_config_staging(_: &Path, _: &File) -> Result<File> {
        Err(unsupported())
    }
    pub fn open_lock(_: &Path) -> Result<File> {
        Err(unsupported())
    }
    pub fn snapshot(_: &str, _: &mut File) -> Result<FileSnapshot> {
        Err(unsupported())
    }
    pub fn replace(_: &Path, _: &Path) -> Result<()> {
        Err(unsupported())
    }
}
#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
pub use unsupported::{canonical, crypt, equal_case, open_guard, open_lock, replace, snapshot};
#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
pub(crate) use unsupported::{create_config_staging, create_staging};

#[cfg(target_os = "linux")]
pub use crate::linux::{canonical, crypt, equal_case, open_guard, open_lock, replace, snapshot};
#[cfg(target_os = "linux")]
pub(crate) use crate::linux::{create_config_staging, create_staging};

#[cfg(target_os = "macos")]
pub use crate::macos::{canonical, crypt, equal_case, open_guard, open_lock, replace, snapshot};
#[cfg(target_os = "macos")]
pub(crate) use crate::macos::{create_config_staging, create_staging};

/// File comparison may need filesystem identity on macOS. Keep ordinary name
/// comparison (`equal_case`) free of filesystem effects.
pub fn same_path(a: &str, b: &str) -> bool {
    #[cfg(target_os = "macos")]
    {
        crate::macos::same_path(a, b)
    }
    #[cfg(not(target_os = "macos"))]
    {
        equal_case(a, b)
    }
}

pub fn read_snapshot(path: &str) -> Result<FileSnapshot> {
    let path = canonical(path)?;
    snapshot(&path, &mut open_guard(&path)?)
}

#[cfg(windows)]
pub use native::directory_identity;
