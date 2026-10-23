#![cfg(target_os = "linux")]
// All data and encryption keys are artificial TEST_ONLY fixtures; no OS keyring is queried.
use atm_core::{
    batch::{AtomicReplacer, BatchUpdater, Outcome},
    jsonc,
    linux::AeadProtector,
    storage::{self, Protector},
    templates::{self, ApplicationIdentity},
    windows, Error, Result, TargetMapping, Vault,
};
use std::{
    fs,
    os::unix::fs::{symlink, PermissionsExt},
    path::Path,
    sync::Arc,
};
use uuid::Uuid;
use zeroize::Zeroizing;

fn protector() -> Arc<dyn Protector> {
    Arc::new(AeadProtector::new(Zeroizing::new([0xa5; 32])))
}
fn fixture(root: &Path, original: &[u8]) -> (Vault, BatchUpdater, String, Uuid) {
    let p = protector();
    let mut vault = Vault::open_with_protector(&root.join("TEST_ONLY_vault"), p.clone()).unwrap();
    let file = root.join("TEST_ONLY_config.jsonc");
    fs::write(&file, original).unwrap();
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).unwrap();
    let key = vault
        .save_key(
            None,
            "TEST_ONLY_key".into(),
            Zeroizing::new("TEST_ONLY_NEW".into()),
        )
        .unwrap();
    let path = file.to_str().unwrap().to_owned();
    let target = vault
        .save_target(TargetMapping {
            id: Uuid::nil(),
            label: "TEST_ONLY_mapping".into(),
            file_path: path.clone(),
            pointer: "/key".into(),
            key_id: key,
            bearer_prefix: false,
            replace_variables: false,
        })
        .unwrap();
    let batch = BatchUpdater::with_protector(vault.backup_directory(), p);
    (vault, batch, path, target)
}
#[test]
fn encrypted_vault_roundtrip_lock_permissions_and_no_plaintext() {
    let root = tempfile::tempdir().unwrap();
    let (v, _, _, _) = fixture(root.path(), br#"{"key":"TEST_ONLY_OLD"}"#);
    let dir = v.directory().to_owned();
    let cipher = fs::read(dir.join(storage::vault_filename())).unwrap();
    assert!(!cipher.windows(13).any(|w| w == b"TEST_ONLY_NEW"));
    assert_eq!(
        fs::metadata(dir.join(storage::vault_filename()))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
    assert_eq!(
        fs::metadata(&dir).unwrap().permissions().mode() & 0o777,
        0o700
    );
    assert!(
        matches!(Vault::open_with_protector(&dir, protector()), Err(e) if e.code=="VAULT_BUSY")
    );
    drop(v);
    let reopened = Vault::open_with_protector(&dir, protector()).unwrap();
    assert_eq!(reopened.snapshot().keys.len(), 1);
}
#[test]
fn authenticated_encryption_rejects_wrong_key_tampering_and_foreign_format() {
    let p = protector();
    let plain = b"TEST_ONLY_SECRET_PAYLOAD";
    let encrypted = p.crypt(plain, true).unwrap();
    assert_eq!(p.crypt(&encrypted, false).unwrap().as_slice(), plain);
    assert_ne!(
        encrypted.as_slice(),
        p.crypt(plain, true).unwrap().as_slice()
    );
    let wrong = AeadProtector::new(Zeroizing::new([0x5a; 32]));
    assert!(wrong.crypt(&encrypted, false).is_err());
    let mut tampered = encrypted.to_vec();
    *tampered.last_mut().unwrap() ^= 1;
    assert!(p.crypt(&tampered, false).is_err());
    assert_eq!(
        p.crypt(b"TEST_ONLY_PLAINTEXT", false).unwrap_err().code,
        "STORAGE_FORMAT"
    );
}
#[test]
fn jsonc_exact_field_patch_and_encrypted_rollback_restore_original_bytes() {
    let root = tempfile::tempdir().unwrap();
    let original = b"{\r\n // TEST_ONLY_COMMENT\r\n \"key\":\"TEST_ONLY_OLD\", \"unchanged\":\"TEST_ONLY_OLD\", \"n\":1.00,\r\n}\r\n";
    let (v, b, path, target) = fixture(root.path(), original);
    let mut plan = b.preview(&v, &[target]);
    let id = plan.id;
    assert_eq!(
        b.apply(&mut plan, id, true).unwrap()[0].outcome,
        Outcome::Applied
    );
    let expected = String::from_utf8(original.to_vec()).unwrap().replacen(
        "\"key\":\"TEST_ONLY_OLD\"",
        "\"key\":\"TEST_ONLY_NEW\"",
        1,
    );
    assert_eq!(fs::read(&path).unwrap(), expected.as_bytes());
    let backups = b.backups().unwrap();
    assert_eq!(backups.len(), 1);
    assert!(backups[0].error.is_none());
    let cipher = fs::read(&backups[0].backup_path).unwrap();
    assert!(!cipher.windows(13).any(|w| w == b"TEST_ONLY_OLD"));
    let mut rollback = b.preview_rollback(&backups[0].backup_path).unwrap();
    let id = rollback.id;
    assert_eq!(
        b.apply(&mut rollback, id, true).unwrap()[0].outcome,
        Outcome::Applied
    );
    assert_eq!(fs::read(path).unwrap(), original);
}
#[test]
fn conflicts_identity_and_post_restore_edits_are_never_overwritten() {
    let root = tempfile::tempdir().unwrap();
    let original = br#"{"key":"TEST_ONLY_OLD"}"#;
    let (v, b, path, target) = fixture(root.path(), original);
    let mut plan = b.preview(&v, &[target]);
    let id = plan.id;
    fs::write(&path, br#"{"key":"TEST_ONLY_EXTERNAL"}"#).unwrap();
    assert_eq!(
        b.apply(&mut plan, id, true).unwrap()[0].outcome,
        Outcome::Conflict
    );
    assert!(b.backups().unwrap().is_empty());
    let mut plan = b.preview(&v, &[target]);
    let id = plan.id;
    b.apply(&mut plan, id, true).unwrap();
    let backup = b.backups().unwrap().remove(0);
    let mut plan = b.preview_rollback(&backup.backup_path).unwrap();
    let id = plan.id;
    fs::write(&path, br#"{"key":"TEST_ONLY_LATER"}"#).unwrap();
    assert_eq!(
        b.apply(&mut plan, id, true).unwrap()[0].outcome,
        Outcome::Conflict
    );
    assert_eq!(
        b.preview_rollback(&backup.backup_path).err().unwrap().code,
        "ROLLBACK_CONFLICT"
    );
}
#[test]
fn symlinks_hardlinks_parent_links_traversal_and_case_distinct_paths() {
    let root = tempfile::tempdir().unwrap();
    let file = root.path().join("TEST_ONLY_A.json");
    fs::write(&file, b"{}").unwrap();
    let lower = root.path().join("TEST_ONLY_a.json");
    fs::write(&lower, b"{}").unwrap();
    assert!(!windows::equal_case(
        file.to_str().unwrap(),
        lower.to_str().unwrap()
    ));
    let link = root.path().join("TEST_ONLY_link");
    symlink(&file, &link).unwrap();
    assert_eq!(
        windows::canonical(link.to_str().unwrap()).unwrap_err().code,
        "PATH_REPARSE"
    );
    let dir = root.path().join("TEST_ONLY_dir_link");
    symlink(root.path(), &dir).unwrap();
    assert!(windows::canonical(dir.join("TEST_ONLY_A.json").to_str().unwrap()).is_err());
    assert!(windows::canonical(root.path().join("../TEST_ONLY_any").to_str().unwrap()).is_err());
    let hard = root.path().join("TEST_ONLY_hard");
    fs::hard_link(&file, &hard).unwrap();
    assert_eq!(
        windows::canonical(file.to_str().unwrap()).unwrap_err().code,
        "PATH_HARDLINK"
    );
}
#[test]
fn read_only_config_refused_without_losing_original_or_leaking_stage() {
    let root = tempfile::tempdir().unwrap();
    let original = br#"{"key":"TEST_ONLY_OLD"}"#;
    let (v, b, path, target) = fixture(root.path(), original);
    fs::set_permissions(&path, fs::Permissions::from_mode(0o400)).unwrap();
    let mut plan = b.preview(&v, &[target]);
    let id = plan.id;
    assert_eq!(
        b.apply(&mut plan, id, true).unwrap()[0].outcome,
        Outcome::Failed
    );
    assert_eq!(fs::read(&path).unwrap(), original);
    assert!(fs::read_dir(root.path()).unwrap().all(|e| !e
        .unwrap()
        .file_name()
        .to_string_lossy()
        .ends_with(".tmp")));
}
struct FailReplace;
impl AtomicReplacer for FailReplace {
    fn replace(&self, _: &Path, _: &Path) -> Result<()> {
        Err(Error::new(
            "TEST_ONLY_FAILURE",
            "TEST_ONLY injected failure",
        ))
    }
}
#[test]
fn replacement_failure_keeps_encrypted_recovery_and_cleans_plaintext_stage() {
    let root = tempfile::tempdir().unwrap();
    let original = br#"{"key":"TEST_ONLY_OLD"}"#;
    let (v, _, path, target) = fixture(root.path(), original);
    let b = BatchUpdater::with_replacer_and_protector(
        v.backup_directory(),
        Box::new(FailReplace),
        protector(),
    );
    let mut plan = b.preview(&v, &[target]);
    let id = plan.id;
    let r = b.apply(&mut plan, id, true).unwrap().remove(0);
    assert_eq!(r.outcome, Outcome::Failed);
    assert!(r.backup_path.is_some());
    assert_eq!(fs::read(&path).unwrap(), original);
    assert!(fs::read_dir(root.path()).unwrap().all(|e| !e
        .unwrap()
        .file_name()
        .to_string_lossy()
        .ends_with(".tmp")));
}
#[test]
fn whole_config_schema_validation_blocks_file_write_and_backup() {
    let root = tempfile::tempdir().unwrap();
    let original = br#"{"key":"TEST_ONLY_OLD","count":"TEST_ONLY_WRONG_TYPE"}"#;
    let (v, b, path, target) = fixture(root.path(), original);
    let app = ApplicationIdentity {
        id: "test-only".into(),
        display_name: "TEST_ONLY".into(),
        config_file_names: vec![],
    };
    let mut candidate =
        templates::infer_candidate(original, app, "TEST_ONLY_template".into()).unwrap();
    candidate.template.schema["properties"]["count"] = serde_json::json!({"type":"integer"});
    candidate.template.write_allowlist = vec!["/key".into()];
    candidate.template.bindings.retain(|f| f.pointer == "/key");
    let template = templates::confirm_candidate(candidate, true).unwrap();
    let mut plan = b.preview_with_validator(&v, &[target], |_, bytes, requests| {
        templates::prepare_patch(&template, bytes, requests)
    });
    let id = plan.id;
    assert_eq!(
        b.apply(&mut plan, id, true).unwrap()[0].outcome,
        Outcome::Failed
    );
    assert_eq!(fs::read(path).unwrap(), original);
    assert!(b.backups().unwrap().is_empty());
}
#[test]
fn utf8_bom_and_utf16_linux_file_roundtrips_preserve_unrelated_bytes() {
    for encoding in 0..3 {
        let text = "{\r\n// TEST_ONLY_COMMENT\r\n\"key\":\"TEST_ONLY_OLD\",\"keep\":1.00,\r\n}\r\n";
        let mut bytes = match encoding {
            0 => vec![0xef, 0xbb, 0xbf],
            1 => vec![0xff, 0xfe],
            _ => vec![0xfe, 0xff],
        };
        if encoding == 0 {
            bytes.extend(text.as_bytes());
        } else {
            for u in text.encode_utf16() {
                bytes.extend(if encoding == 1 {
                    u.to_le_bytes()
                } else {
                    u.to_be_bytes()
                });
            }
        }
        let root = tempfile::tempdir().unwrap();
        let (v, b, path, target) = fixture(root.path(), &bytes);
        let mut plan = b.preview(&v, &[target]);
        let id = plan.id;
        assert_eq!(
            b.apply(&mut plan, id, true).unwrap()[0].outcome,
            Outcome::Applied
        );
        let parsed = jsonc::parse_value(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(parsed["key"], "TEST_ONLY_NEW");
        let backup = b.backups().unwrap().remove(0);
        let mut rollback = b.preview_rollback(&backup.backup_path).unwrap();
        let id = rollback.id;
        b.apply(&mut rollback, id, true).unwrap();
        assert_eq!(fs::read(path).unwrap(), bytes);
    }
}
#[test]
fn ordinary_mode_preservation_and_wide_storage_permissions_fail_closed() {
    let root = tempfile::tempdir().unwrap();
    let (v, b, path, target) = fixture(root.path(), br#"{"key":"TEST_ONLY_OLD"}"#);
    fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();
    let mut plan = b.preview(&v, &[target]);
    let id = plan.id;
    assert_eq!(
        b.apply(&mut plan, id, true).unwrap()[0].outcome,
        Outcome::Applied
    );
    assert_eq!(
        fs::metadata(path).unwrap().permissions().mode() & 0o777,
        0o640
    );
    let wide = root.path().join("TEST_ONLY_wide");
    fs::create_dir(&wide).unwrap();
    fs::set_permissions(&wide, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(
        matches!(Vault::open_with_protector(&wide,protector()),Err(e) if e.code=="STORAGE_PERMISSIONS")
    );
    assert_eq!(
        fs::metadata(wide).unwrap().permissions().mode() & 0o777,
        0o755
    );
}
#[test]
fn missing_keyring_never_falls_back_or_creates_user_credentials() {
    // A separate child gets an intentionally nonexistent private bus, never the Home bus.
    let root = tempfile::tempdir().unwrap();
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_atm-storage-probe"))
        .env(
            "DBUS_SESSION_BUS_ADDRESS",
            format!("unix:path={}/TEST_ONLY_absent_bus", root.path().display()),
        )
        .env("HOME", root.path())
        .env("XDG_DATA_HOME", root.path())
        .env("XDG_CONFIG_HOME", root.path())
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap().trim(),
        "STORAGE_UNAVAILABLE"
    );
    assert!(fs::read_dir(root.path()).unwrap().next().is_none());
}

#[test]
fn inherited_default_acl_cannot_grant_new_access_on_config_replacement() {
    use std::{ffi::CString, os::unix::ffi::OsStrExt};
    let root = tempfile::tempdir().unwrap();
    let original = br#"{"key":"TEST_ONLY_OLD"}"#;
    let (mut vault, batch, old_path, target_id) = fixture(root.path(), original);
    let inherited = root.path().join("TEST_ONLY_default_acl");
    fs::create_dir(&inherited).unwrap();
    let path = inherited.join("config.json");
    // Move an existing inode in: parent default ACL must not affect the original.
    fs::rename(old_path, &path).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();
    let mut target = vault
        .snapshot()
        .targets
        .into_iter()
        .find(|target| target.id == target_id)
        .unwrap();
    target.file_path = path.to_string_lossy().into_owned();
    vault.save_target(target).unwrap();
    let mut acl = 2u32.to_le_bytes().to_vec(); // Linux POSIX ACL xattr version.
    for (tag, permissions, id) in [
        (1u16, 7u16, u32::MAX), // owner
        (2, 4, 65534),          // named user, read
        (4, 0, u32::MAX),       // owning group
        (16, 4, u32::MAX),      // mask
        (32, 0, u32::MAX),      // other
    ] {
        acl.extend(tag.to_le_bytes());
        acl.extend(permissions.to_le_bytes());
        acl.extend(id.to_le_bytes());
    }
    let directory = CString::new(inherited.as_os_str().as_bytes()).unwrap();
    // SAFETY: all pointers and lengths refer to live NUL-terminated names/data.
    let result = unsafe {
        libc::setxattr(
            directory.as_ptr(),
            c"system.posix_acl_default".as_ptr(),
            acl.as_ptr().cast(),
            acl.len(),
            0,
        )
    };
    if result != 0 {
        let error = std::io::Error::last_os_error();
        if matches!(
            error.raw_os_error(),
            Some(libc::EINVAL | libc::EOPNOTSUPP | libc::EPERM)
        ) {
            eprintln!(
                "LINUX_DEFAULT_ACL=UNVERIFIED: fixture filesystem refused default ACL: {error}"
            );
            return;
        }
        panic!("cannot prepare synthetic default ACL fixture: {error}");
    }
    let access_acl = |path: &Path| {
        let path = CString::new(path.as_os_str().as_bytes()).unwrap();
        let mut bytes = vec![0u8; 1024];
        // SAFETY: live path/name and writable output buffer of the supplied size.
        let size = unsafe {
            libc::getxattr(
                path.as_ptr(),
                c"system.posix_acl_access".as_ptr(),
                bytes.as_mut_ptr().cast(),
                bytes.len(),
            )
        };
        if size < 0 {
            assert_eq!(
                std::io::Error::last_os_error().raw_os_error(),
                Some(libc::ENODATA)
            );
            Vec::new()
        } else {
            bytes.truncate(size as usize);
            bytes
        }
    };
    assert!(
        access_acl(&path).is_empty(),
        "moved original must have no access ACL"
    );
    // Prove this filesystem really inherits an ACL even at initial mode 0600.
    let probe = inherited.join("TEST_ONLY_empty_stage");
    drop(atm_core::linux::create_staging(&probe).unwrap());
    assert!(
        !access_acl(&probe).is_empty(),
        "no ACL inheritance was exercised"
    );
    fs::remove_file(probe).unwrap();
    let mut plan = batch.preview(&vault, &[target_id]);
    let id = plan.id;
    let results = batch.apply(&mut plan, id, true).unwrap();
    if results[0].outcome == Outcome::Applied {
        let acl = access_acl(&path);
        let mut named = 0u16;
        let mut mask = 7u16;
        for entry in acl.get(4..).unwrap_or_default().as_chunks::<8>().0 {
            let tag = u16::from_le_bytes(entry[..2].try_into().unwrap());
            let permissions = u16::from_le_bytes(entry[2..4].try_into().unwrap());
            if tag == 2 {
                named |= permissions;
            }
            if tag == 16 {
                mask = permissions;
            }
        }
        assert_eq!(named & mask, 0, "LINUX_DEFAULT_ACL=REPRODUCED: inherited named-user access became effective after restoring 0640");
    } else {
        assert_eq!(results[0].outcome, Outcome::Failed);
        assert_eq!(results[0].code, Some("STAGING_SECURITY"));
        assert_eq!(fs::read(&path).unwrap(), original);
        assert!(access_acl(&path).is_empty());
    }
    assert!(!fs::read_dir(&inherited).unwrap().any(|entry| entry
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".lkm-")));
    eprintln!("LINUX_DEFAULT_ACL=PASS: inherited ACL exercised; no new named-user access");
}
