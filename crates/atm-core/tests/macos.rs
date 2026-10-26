#![cfg(target_os = "macos")]
// TEST_ONLY files and injected memory keys. No Keychain API or provider is used.
use atm_core::{
    batch::{BatchUpdater, Outcome},
    macos::{self, AeadProtector},
    storage::{self, Protector},
    TargetMapping, Vault,
};
use std::{
    fs,
    io::Write,
    os::{
        fd::AsRawFd,
        unix::fs::{symlink, MetadataExt, PermissionsExt},
    },
    path::Path,
    sync::Arc,
};
use uuid::Uuid;
use zeroize::Zeroizing;

fn protector() -> Arc<dyn Protector> {
    Arc::new(AeadProtector::new(Zeroizing::new([0xa5; 32])))
}
fn fixture(root: &Path) -> (Vault, BatchUpdater, String, Uuid) {
    let p = protector();
    let mut vault = Vault::open_with_protector(&root.join("TEST_ONLY_vault"), p.clone()).unwrap();
    let file = root.join("TEST_ONLY_config.jsonc");
    fs::write(
        &file,
        b"{\r\n // TEST_ONLY\r\n \"key\":\"TEST_ONLY_OLD\", \"other\":1.00,\r\n}\r\n",
    )
    .unwrap();
    let key = vault
        .save_key(
            None,
            "TEST_ONLY_key".into(),
            Zeroizing::new("TEST_ONLY_NEW".into()),
        )
        .unwrap();
    let target = vault
        .save_target(TargetMapping {
            id: Uuid::nil(),
            label: "TEST_ONLY_target".into(),
            file_path: file.to_string_lossy().into_owned(),
            pointer: "/key".into(),
            key_id: key,
            bearer_prefix: false,
            replace_variables: false,
        })
        .unwrap();
    let path = vault.snapshot().targets[0].file_path.clone();
    let batch = BatchUpdater::with_protector(vault.backup_directory(), p);
    (vault, batch, path, target)
}

#[test]
fn memory_only_vault_roundtrip_private_modes_and_locking() {
    let root = tempfile::tempdir().unwrap();
    let (vault, _, _, _) = fixture(root.path());
    let directory = vault.directory().to_owned();
    assert_eq!(storage::kind(), "macos_keychain");
    assert_eq!(storage::vault_filename(), "vault.atmvault");
    let encrypted = fs::read(directory.join(storage::vault_filename())).unwrap();
    assert!(encrypted.starts_with(b"LKM-MACOS-V1\0"));
    assert!(!encrypted.windows(13).any(|p| p == b"TEST_ONLY_NEW"));
    assert_eq!(fs::metadata(&directory).unwrap().mode() & 0o777, 0o700);
    assert_eq!(
        fs::metadata(directory.join(storage::vault_filename()))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    assert!(
        matches!(Vault::open_with_protector(&directory,protector()),Err(e) if e.code=="VAULT_BUSY")
    );
    drop(vault);
    assert_eq!(
        Vault::open_with_protector(&directory, protector())
            .unwrap()
            .snapshot()
            .keys
            .len(),
        1
    );
    // The demo entry point must return a memory key, never the system protector.
    let demo = storage::demo_protector().unwrap();
    let cipher = demo.crypt(b"TEST_ONLY_demo", true).unwrap();
    assert_eq!(
        demo.crypt(&cipher, false).unwrap().as_slice(),
        b"TEST_ONLY_demo"
    );
}

#[test]
fn jsonc_update_and_posix_backup_rollback_preserve_bytes_modes_and_xattrs() {
    let root = tempfile::tempdir().unwrap();
    let (vault, batch, path, id) = fixture(root.path());
    let original = fs::read(&path).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o640)).unwrap();
    let file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    let name = c"user.atm-test-only";
    let value = b"TEST_ONLY_xattr";
    // Darwin xattr APIs operate only on this synthetic, owned fixture fd.
    assert_eq!(
        unsafe {
            libc::fsetxattr(
                file.as_raw_fd(),
                name.as_ptr(),
                value.as_ptr().cast(),
                value.len(),
                0,
                0,
            )
        },
        0
    );
    file.sync_all().unwrap();
    drop(file);
    let fingerprint_before = atm_core::windows::read_snapshot(&path).unwrap().fingerprint;
    let mut preview = batch.preview(&vault, &[id]);
    let preview_id = preview.id;
    let applied = batch.apply(&mut preview, preview_id, true).unwrap();
    let fingerprint_after = atm_core::windows::read_snapshot(&path).unwrap().fingerprint;
    assert_eq!(
        applied[0].outcome,
        Outcome::Applied,
        "{applied:#?}\nbefore={fingerprint_before:?}\nafter={fingerprint_after:?}"
    );
    assert_eq!(
        fs::read(&path).unwrap(),
        String::from_utf8(original.clone())
            .unwrap()
            .replace("TEST_ONLY_OLD", "TEST_ONLY_NEW")
            .as_bytes()
    );
    assert_eq!(fs::metadata(&path).unwrap().mode() & 0o777, 0o640);
    let file = fs::File::open(&path).unwrap();
    let mut actual = [0u8; 64];
    let length = unsafe {
        libc::fgetxattr(
            file.as_raw_fd(),
            name.as_ptr(),
            actual.as_mut_ptr().cast(),
            actual.len(),
            0,
            0,
        )
    };
    assert_eq!(length, value.len() as isize);
    assert_eq!(&actual[..length as usize], value);
    let backups = batch.backups().unwrap();
    assert_eq!(backups.len(), 1);
    let mut rollback = batch.preview_rollback(&backups[0].backup_path).unwrap();
    let rollback_id = rollback.id;
    assert_eq!(
        batch.apply(&mut rollback, rollback_id, true).unwrap()[0].outcome,
        Outcome::Applied
    );
    assert_eq!(fs::read(path).unwrap(), original);
}

#[test]
fn symlink_hardlink_and_path_traversal_are_rejected() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("TEST_ONLY.json");
    fs::write(&path, b"{}").unwrap();
    let link = root.path().join("TEST_ONLY-link.json");
    symlink(&path, &link).unwrap();
    assert!(macos::canonical(link.to_str().unwrap()).is_err());
    let parent = root.path().join("TEST_ONLY-parent");
    symlink(root.path(), &parent).unwrap();
    assert!(macos::canonical(parent.join("TEST_ONLY.json").to_str().unwrap()).is_err());
    assert!(macos::canonical(root.path().join("../TEST_ONLY.json").to_str().unwrap()).is_err());
    let hard = root.path().join("TEST_ONLY-hard.json");
    fs::hard_link(&path, &hard).unwrap();
    assert_eq!(
        macos::canonical(path.to_str().unwrap()).unwrap_err().code,
        "PATH_HARDLINK"
    );
}

#[test]
fn fixed_system_tmp_alias_is_supported_without_following_user_links() {
    let root = tempfile::Builder::new()
        .prefix("TEST_ONLY-atm-")
        .tempdir_in("/tmp")
        .unwrap();
    let file = root.path().join("fixture.json");
    fs::write(&file, b"{}").unwrap();
    let canonical = macos::canonical(file.to_str().unwrap()).unwrap();
    assert!(canonical.starts_with("/private/tmp/"));
    assert!(macos::same_path(file.to_str().unwrap(), &canonical));
}

#[test]
fn path_identity_respects_the_actual_volume_case_semantics() {
    let root = tempfile::tempdir().unwrap();
    let first = root.path().join("TEST_ONLY_CASE.json");
    fs::write(&first, b"{}").unwrap();
    let second = root.path().join("test_only_case.json");
    match fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&second)
    {
        Ok(mut file) => {
            file.write_all(b"{}").unwrap();
            assert!(!atm_core::windows::same_path(
                first.to_str().unwrap(),
                second.to_str().unwrap()
            ));
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => assert!(
            atm_core::windows::same_path(first.to_str().unwrap(), second.to_str().unwrap())
        ),
        Err(e) => panic!("TEST_ONLY fixture creation failed: {e}"),
    }
    assert!(!macos::equal_case("KeyName", "keyname"));
}

#[test]
fn changed_preview_and_no_replace_installation_fail_closed() {
    let root = tempfile::tempdir().unwrap();
    let (vault, batch, path, id) = fixture(root.path());
    let mut preview = batch.preview(&vault, &[id]);
    let preview_id = preview.id;
    fs::write(&path, b"{\"key\":\"TEST_ONLY_OTHER\"}").unwrap();
    assert_eq!(
        batch.apply(&mut preview, preview_id, true).unwrap()[0].outcome,
        Outcome::Conflict
    );
    let destination = root.path().join("TEST_ONLY-destination");
    fs::write(&destination, b"TEST_ONLY_existing").unwrap();
    let stage = root.path().join("TEST_ONLY-stage");
    let mut file = macos::create_staging(&stage).unwrap();
    file.write_all(b"TEST_ONLY_new").unwrap();
    drop(file);
    assert!(macos::install_new(&stage, &destination).is_err());
    assert_eq!(fs::read(destination).unwrap(), b"TEST_ONLY_existing");
    assert!(stage.exists());
}

#[test]
fn broad_private_directory_or_encrypted_file_modes_are_not_repaired_automatically() {
    let root = tempfile::tempdir().unwrap();
    let directory = root.path().join("TEST_ONLY_broad");
    fs::create_dir(&directory).unwrap();
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(
        storage::ensure_directory(&directory).unwrap_err().code,
        "STORAGE_PERMISSIONS"
    );
    let (vault, _, _, _) = fixture(root.path());
    let encrypted = vault.directory().join(storage::vault_filename());
    drop(vault);
    fs::set_permissions(&encrypted, fs::Permissions::from_mode(0o644)).unwrap();
    assert_eq!(
        macos::open_encrypted(&encrypted).unwrap_err().code,
        "STORAGE_PERMISSIONS"
    );
}

#[test]
fn copying_staging_metadata_does_not_modify_the_previewed_source() {
    let root = tempfile::tempdir().unwrap();
    let file = root.path().join("TEST_ONLY-source.json");
    fs::write(&file, b"{}").unwrap();
    let owned = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&file)
        .unwrap();
    let attr = c"user.atm-test-only";
    assert_eq!(
        unsafe {
            libc::fsetxattr(
                owned.as_raw_fd(),
                attr.as_ptr(),
                b"TEST_ONLY".as_ptr().cast(),
                9,
                0,
                0,
            )
        },
        0
    );
    drop(owned);
    let before = atm_core::windows::read_snapshot(file.to_str().unwrap()).unwrap();
    let guard = macos::open_guard(file.to_str().unwrap()).unwrap();
    let stage = root.path().join("TEST_ONLY-stage");
    let staged = macos::create_config_staging(&stage, &guard).unwrap();
    (&staged).write_all(b"TEST_ONLY replacement").unwrap();
    staged.sync_all().unwrap();
    let after = atm_core::windows::read_snapshot(file.to_str().unwrap()).unwrap();
    assert_eq!(
        before.fingerprint, after.fingerprint,
        "staging must leave source metadata unchanged"
    );
    drop(staged);
}
