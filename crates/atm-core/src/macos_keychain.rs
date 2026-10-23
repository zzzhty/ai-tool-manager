//! macOS envelope and a narrow Keychain seam. Ordinary tests never use Keychain.
use crate::{storage::Protector, Error, Result, MAX_ENCRYPTED_BYTES};
use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce,
};
use zeroize::Zeroizing;

pub(crate) const SERVICE: &str = "com.localkeymanager.desktop.storage.v1";
pub(crate) const ACCOUNT: &str = "macos-aes-gcm-master-v1";
const HEADER: &[u8] = b"LKM-MACOS-V1\0";

pub(crate) trait Keychain {
    fn read(&self) -> Result<Vec<Zeroizing<Vec<u8>>>>;
    fn add(&self, key: &[u8]) -> Result<()>;
}

fn read_key(backend: &impl Keychain) -> Result<Option<Zeroizing<[u8; 32]>>> {
    let matches = backend.read()?;
    if matches.is_empty() {
        return Ok(None);
    }
    if matches.len() != 1 || matches[0].len() != 32 {
        return Err(Error::new(
            "STORAGE_KEY",
            "Keychain 中的应用主密钥重复或格式无效；未选择或覆盖条目。",
        ));
    }
    let mut key = Zeroizing::new([0; 32]);
    key.copy_from_slice(&matches[0]);
    Ok(Some(key))
}

pub(crate) fn initialize_with(
    backend: &impl Keychain,
    confirmed: bool,
    encrypted_data_exists: bool,
) -> Result<()> {
    if !confirmed {
        return Err(Error::new(
            "CONFIRM_REQUIRED",
            "须确认在 macOS Keychain 中创建或连接应用主密钥。",
        ));
    }
    if read_key(backend)?.is_some() {
        return Ok(());
    }
    if encrypted_data_exists {
        return Err(Error::new(
            "STORAGE_KEY_MISSING",
            "加密数据存在但 Keychain 主密钥缺失；不会创建替换密钥。请恢复原主密钥。",
        ));
    }
    let mut key = Zeroizing::new([0; 32]);
    getrandom::getrandom(key.as_mut())
        .map_err(|_| Error::new("STORAGE_RANDOM", "安全随机源不可用。"))?;
    backend.add(key.as_ref())?;
    let loaded = read_key(backend)?
        .ok_or_else(|| Error::new("STORAGE_KEY", "未能确认新建的应用主密钥。"))?;
    if loaded.as_ref() != key.as_ref() {
        return Err(Error::new(
            "STORAGE_KEY",
            "主密钥初始化发生并发变化；拒绝继续写入。",
        ));
    }
    Ok(())
}

pub(crate) fn crypt_with(
    backend: &impl Keychain,
    input: &[u8],
    protect: bool,
) -> Result<Zeroizing<Vec<u8>>> {
    if !protect && !input.starts_with(HEADER) {
        return Err(Error::new(
            "STORAGE_FORMAT",
            "macOS 不支持解密 Linux、DPAPI 或明文文件。",
        ));
    }
    let key = read_key(backend)?.ok_or_else(|| {
        if protect {
            Error::new(
                "STORAGE_NOT_CONNECTED",
                "请先主动连接 macOS Keychain 安全存储；不会自动创建主密钥。",
            )
        } else {
            Error::new(
                "STORAGE_KEY_MISSING",
                "加密数据存在但 Keychain 主密钥缺失；请恢复原主密钥，不会自动创建替换密钥。",
            )
        }
    })?;
    AeadProtector::new(key).crypt(input, protect)
}

/// Explicit memory-only protector for demo and synthetic fixtures.
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
        let limit = if protect {
            MAX_ENCRYPTED_BYTES - HEADER.len() - 28
        } else {
            MAX_ENCRYPTED_BYTES
        };
        if input.len() > limit {
            return Err(Error::new("DATA_SIZE", "数据超出安全上限。"));
        }
        let cipher = Aes256Gcm::new_from_slice(self.key.as_ref())
            .map_err(|_| Error::new("STORAGE_KEY", "加密主密钥无效。"))?;
        if protect {
            let mut nonce = [0; 12];
            getrandom::getrandom(&mut nonce)
                .map_err(|_| Error::new("STORAGE_RANDOM", "安全随机源不可用。"))?;
            let encrypted = cipher
                .encrypt(
                    Nonce::from_slice(&nonce),
                    Payload {
                        msg: input,
                        aad: HEADER,
                    },
                )
                .map_err(|_| Error::new("STORAGE_CRYPTO", "加密失败。"))?;
            let mut output = Vec::with_capacity(HEADER.len() + 12 + encrypted.len());
            output.extend(HEADER);
            output.extend(nonce);
            output.extend(encrypted);
            Ok(Zeroizing::new(output))
        } else {
            if !input.starts_with(HEADER) || input.len() < HEADER.len() + 28 {
                return Err(Error::new(
                    "STORAGE_FORMAT",
                    "不是 macOS 支持的加密文件；未改动原文件。",
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
                        "解密或完整性验证失败；请检查 Keychain 和备份。",
                    )
                })
        }
    }
}

#[cfg(target_os = "macos")]
pub(crate) use native::NativeKeychain;

#[cfg(target_os = "macos")]
mod native {
    // Signatures/constants follow the installed Apple Security/CoreFoundation SDK.
    // No shell, credentials in argv, item update/delete, synchronization or UI unlock.
    use super::*;
    use std::{
        ffi::{c_void, CString},
        ptr,
    };
    type Ref = *const c_void;
    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        static kCFTypeDictionaryKeyCallBacks: c_void;
        static kCFTypeDictionaryValueCallBacks: c_void;
        static kCFBooleanTrue: Ref;
        static kCFBooleanFalse: Ref;
        fn CFDictionaryCreate(
            allocator: Ref,
            keys: *const Ref,
            values: *const Ref,
            count: isize,
            keys_cb: Ref,
            values_cb: Ref,
        ) -> Ref;
        fn CFStringCreateWithCString(
            allocator: Ref,
            text: *const std::ffi::c_char,
            encoding: u32,
        ) -> Ref;
        fn CFDataCreate(allocator: Ref, bytes: *const u8, count: isize) -> Ref;
        fn CFDataGetLength(data: Ref) -> isize;
        fn CFDataGetBytePtr(data: Ref) -> *const u8;
        fn CFDataGetTypeID() -> usize;
        fn CFArrayGetCount(array: Ref) -> isize;
        fn CFArrayGetValueAtIndex(array: Ref, index: isize) -> Ref;
        fn CFArrayGetTypeID() -> usize;
        fn CFGetTypeID(value: Ref) -> usize;
        fn CFRelease(value: Ref);
    }
    #[link(name = "Security", kind = "framework")]
    extern "C" {
        static kSecClass: Ref;
        static kSecClassGenericPassword: Ref;
        static kSecAttrService: Ref;
        static kSecAttrAccount: Ref;
        static kSecAttrLabel: Ref;
        static kSecAttrSynchronizable: Ref;
        static kSecUseAuthenticationUI: Ref;
        static kSecUseAuthenticationUIFail: Ref;
        static kSecMatchLimit: Ref;
        static kSecMatchLimitAll: Ref;
        static kSecReturnData: Ref;
        static kSecValueData: Ref;
        fn SecItemCopyMatching(query: Ref, result: *mut Ref) -> i32;
        fn SecItemAdd(attributes: Ref, result: *mut Ref) -> i32;
    }
    struct Owned(Ref);
    impl Owned {
        fn checked(value: Ref) -> Result<Self> {
            if value.is_null() {
                Err(Error::new(
                    "STORAGE_UNAVAILABLE",
                    "无法准备 Keychain 请求。",
                ))
            } else {
                Ok(Self(value))
            }
        }
        fn string(text: &str) -> Result<Self> {
            let text =
                CString::new(text).map_err(|_| Error::new("STORAGE_KEY", "Keychain 标识无效。"))?;
            // SAFETY: NUL-terminated UTF-8 input is valid until CF has copied it.
            Self::checked(unsafe {
                CFStringCreateWithCString(ptr::null(), text.as_ptr(), 0x08000100)
            })
        }
    }
    impl Drop for Owned {
        fn drop(&mut self) {
            // SAFETY: every Owned contains one non-null retained Create/Copy result.
            unsafe {
                CFRelease(self.0);
            }
        }
    }
    fn query(extra: &[(Ref, Ref)]) -> Result<Owned> {
        let service = Owned::string(SERVICE)?;
        let account = Owned::string(ACCOUNT)?;
        // SAFETY: SDK constants are process-lifetime CF objects; CF callbacks retain
        // each key/value, including the local service/account strings.
        unsafe {
            let mut entries = vec![
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service.0),
                (kSecAttrAccount, account.0),
                (kSecAttrSynchronizable, kCFBooleanFalse),
                (kSecUseAuthenticationUI, kSecUseAuthenticationUIFail),
            ];
            entries.extend_from_slice(extra);
            let keys: Vec<_> = entries.iter().map(|p| p.0).collect();
            let values: Vec<_> = entries.iter().map(|p| p.1).collect();
            Owned::checked(CFDictionaryCreate(
                ptr::null(),
                keys.as_ptr(),
                values.as_ptr(),
                entries.len() as isize,
                ptr::addr_of!(kCFTypeDictionaryKeyCallBacks),
                ptr::addr_of!(kCFTypeDictionaryValueCallBacks),
            ))
        }
    }
    fn status_error(status: i32) -> Error {
        match status {
            -25308 => Error::new(
                "STORAGE_LOCKED",
                "Keychain 已锁定或需要交互授权；未自动解锁。",
            ),
            -25293 | -128 => Error::new(
                "STORAGE_ACCESS_DENIED",
                "Keychain 拒绝访问；未更改条目或访问控制。",
            ),
            -25299 => Error::new(
                "STORAGE_KEY",
                "应用主密钥已存在或初始化发生并发变化；未覆盖。",
            ),
            _ => Error::new(
                "STORAGE_UNAVAILABLE",
                "macOS Keychain 不可用；不会回退到明文。",
            ),
        }
    }
    pub(crate) struct NativeKeychain;
    impl Keychain for NativeKeychain {
        fn read(&self) -> Result<Vec<Zeroizing<Vec<u8>>>> {
            // SAFETY: the query and output pointer remain alive across the SDK call.
            unsafe {
                let query = query(&[
                    (kSecMatchLimit, kSecMatchLimitAll),
                    (kSecReturnData, kCFBooleanTrue),
                ])?;
                let mut result = ptr::null();
                let status = SecItemCopyMatching(query.0, &mut result);
                if status == -25300 {
                    return Ok(Vec::new());
                }
                if status != 0 {
                    return Err(status_error(status));
                }
                let result = Owned::checked(result)?;
                if CFGetTypeID(result.0) != CFArrayGetTypeID() || CFArrayGetCount(result.0) != 1 {
                    return Err(Error::new("STORAGE_KEY", "应用主密钥重复或格式无效。"));
                }
                let data = CFArrayGetValueAtIndex(result.0, 0);
                if data.is_null()
                    || CFGetTypeID(data) != CFDataGetTypeID()
                    || CFDataGetLength(data) != 32
                {
                    return Err(Error::new("STORAGE_KEY", "Keychain 主密钥格式无效。"));
                }
                let bytes = CFDataGetBytePtr(data);
                if bytes.is_null() {
                    return Err(Error::new("STORAGE_KEY", "Keychain 主密钥无效。"));
                }
                Ok(vec![Zeroizing::new(
                    std::slice::from_raw_parts(bytes, 32).to_vec(),
                )])
            }
        }
        fn add(&self, key: &[u8]) -> Result<()> {
            if key.len() != 32 {
                return Err(Error::new("STORAGE_KEY", "应用主密钥无效。"));
            }
            // SAFETY: the SDK copies 32 valid bytes; CF dictionary retains data/label
            // until SecItemAdd returns. No update path exists for an existing item.
            unsafe {
                let data =
                    Owned::checked(CFDataCreate(ptr::null(), key.as_ptr(), key.len() as isize))?;
                let label = Owned::string("AI Tool Manager macOS encryption key")?;
                let attributes = query(&[(kSecValueData, data.0), (kSecAttrLabel, label.0)])?;
                let status = SecItemAdd(attributes.0, ptr::null_mut());
                if status == 0 {
                    Ok(())
                } else {
                    Err(status_error(status))
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::{Cell, RefCell};
    #[derive(Default)]
    struct Mock {
        items: RefCell<Vec<Vec<u8>>>,
        reads: Cell<usize>,
        adds: Cell<usize>,
        denied: Cell<bool>,
        race: Cell<bool>,
    }
    impl Keychain for Mock {
        fn read(&self) -> Result<Vec<Zeroizing<Vec<u8>>>> {
            self.reads.set(self.reads.get() + 1);
            if self.denied.get() {
                return Err(Error::new("STORAGE_ACCESS_DENIED", "TEST_ONLY denial"));
            }
            Ok(self
                .items
                .borrow()
                .iter()
                .cloned()
                .map(Zeroizing::new)
                .collect())
        }
        fn add(&self, key: &[u8]) -> Result<()> {
            self.adds.set(self.adds.get() + 1);
            self.items.borrow_mut().push(if self.race.get() {
                vec![0x55; 32]
            } else {
                key.to_vec()
            });
            Ok(())
        }
    }
    #[test]
    fn stable_platform_identity_and_distinct_authenticated_envelope() {
        assert_eq!(SERVICE, "com.localkeymanager.desktop.storage.v1");
        assert_eq!(ACCOUNT, "macos-aes-gcm-master-v1");
        let p = AeadProtector::new(Zeroizing::new([0xa5; 32]));
        let plain = b"TEST_ONLY_secret";
        let cipher = p.crypt(plain, true).unwrap();
        assert!(cipher.starts_with(HEADER));
        assert!(!cipher.windows(plain.len()).any(|part| part == plain));
        assert_eq!(p.crypt(&cipher, false).unwrap().as_slice(), plain);
        assert_ne!(p.crypt(plain, true).unwrap(), cipher);
        let mut changed = cipher.to_vec();
        *changed.last_mut().unwrap() ^= 1;
        assert_eq!(p.crypt(&changed, false).unwrap_err().code, "STORAGE_CRYPTO");
        assert!(AeadProtector::new(Zeroizing::new([0x55; 32]))
            .crypt(&cipher, false)
            .is_err());
        for foreign in [b"LKM-LINUX-V1\0fake".as_slice(), b"DPAPI", plain] {
            assert_eq!(p.crypt(foreign, false).unwrap_err().code, "STORAGE_FORMAT");
        }
    }
    #[test]
    fn confirmation_precedes_reads_and_creation() {
        let m = Mock::default();
        assert_eq!(
            initialize_with(&m, false, false).unwrap_err().code,
            "CONFIRM_REQUIRED"
        );
        assert_eq!((m.reads.get(), m.adds.get()), (0, 0));
        initialize_with(&m, true, false).unwrap();
        assert_eq!(m.adds.get(), 1);
        let encrypted = crypt_with(&m, b"TEST_ONLY_mock", true).unwrap();
        assert_eq!(
            crypt_with(&m, &encrypted, false).unwrap().as_slice(),
            b"TEST_ONLY_mock"
        );
        initialize_with(&m, true, true).unwrap();
        assert_eq!(m.adds.get(), 1);
    }
    #[test]
    fn missing_invalid_duplicate_and_denied_keys_never_create_replacements() {
        let m = Mock::default();
        assert_eq!(
            crypt_with(&m, b"TEST_ONLY", true).unwrap_err().code,
            "STORAGE_NOT_CONNECTED"
        );
        assert_eq!(
            initialize_with(&m, true, true).unwrap_err().code,
            "STORAGE_KEY_MISSING"
        );
        for keys in [vec![vec![0; 31]], vec![vec![0; 32], vec![1; 32]]] {
            *m.items.borrow_mut() = keys;
            assert_eq!(
                initialize_with(&m, true, false).unwrap_err().code,
                "STORAGE_KEY"
            );
        }
        m.denied.set(true);
        assert_eq!(
            initialize_with(&m, true, false).unwrap_err().code,
            "STORAGE_ACCESS_DENIED"
        );
        assert_eq!(m.adds.get(), 0);
    }
    #[test]
    fn lost_key_cannot_decrypt_existing_data_or_create_a_replacement() {
        let m = Mock::default();
        let encrypted = AeadProtector::new(Zeroizing::new([0xa5; 32]))
            .crypt(b"TEST_ONLY", true)
            .unwrap();
        assert_eq!(
            crypt_with(&m, &encrypted, false).unwrap_err().code,
            "STORAGE_KEY_MISSING"
        );
        assert_eq!(m.adds.get(), 0);
    }
    #[test]
    fn maximum_supported_plaintext_roundtrips_with_envelope_overhead() {
        let p = AeadProtector::new(Zeroizing::new([0xa5; 32]));
        let plain = Zeroizing::new(vec![0u8; MAX_ENCRYPTED_BYTES - HEADER.len() - 28]);
        let encrypted = p.crypt(&plain, true).unwrap();
        assert_eq!(encrypted.len(), MAX_ENCRYPTED_BYTES);
        assert_eq!(p.crypt(&encrypted, false).unwrap().len(), plain.len());
    }
    #[test]
    fn wrong_format_is_rejected_before_keychain_access_and_races_fail_closed() {
        let m = Mock::default();
        assert_eq!(
            crypt_with(&m, b"TEST_ONLY plaintext", false)
                .unwrap_err()
                .code,
            "STORAGE_FORMAT"
        );
        assert_eq!(m.reads.get(), 0);
        m.race.set(true);
        assert_eq!(
            initialize_with(&m, true, false).unwrap_err().code,
            "STORAGE_KEY"
        );
    }
}
