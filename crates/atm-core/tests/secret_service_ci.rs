#![cfg(target_os = "linux")]
// Opt-in only in the private D-Bus runner fixture. Never runs against Home.
use atm_core::{
    batch::{BatchUpdater, Outcome},
    linux, storage, TargetMapping, Vault,
};
use std::{fs, path::PathBuf};
use uuid::Uuid;
use zeroize::Zeroizing;

#[test]
#[ignore = "CI-only: requires isolated HOME, D-Bus and TEST_ONLY keyring"]
fn isolated_secret_service_lifecycle() {
    assert_eq!(std::env::var("CI").as_deref(), Ok("true"));
    assert_eq!(
        std::env::var("ATM_ISOLATED_KEYRING_TEST").as_deref(),
        Ok("1")
    );
    let root = PathBuf::from(std::env::var_os("ATM_TEST_ROOT").expect("isolated root"));
    assert!(root.is_absolute());
    assert_eq!(
        PathBuf::from(std::env::var_os("HOME").unwrap()),
        root.join("home")
    );
    assert!(std::env::var("DBUS_SESSION_BUS_ADDRESS")
        .unwrap()
        .starts_with("unix:"));
    let directory = root.join("TEST_ONLY_vault");
    let config = root.join("TEST_ONLY_config.jsonc");
    let phase = std::env::var("ATM_KEYRING_PHASE").unwrap();
    let original =
        b"{\r\n // TEST_ONLY comment\r\n \"key\":\"TEST_ONLY_OLD\", \"keep\":1.00,\r\n}\r\n";
    if phase == "create" {
        assert_eq!(
            linux::initialize_storage(false).unwrap_err().code,
            "CONFIRM_REQUIRED"
        );
        linux::initialize_storage(true).expect("create real Secret Service application item");
        linux::initialize_storage(true).expect("existing item is not replaced");
        fs::write(&config, original).unwrap();
        let mut vault = Vault::open(&directory).unwrap();
        let key = vault
            .save_key(
                None,
                "TEST_ONLY".into(),
                Zeroizing::new("TEST_ONLY_NEW".into()),
            )
            .unwrap();
        let target = vault
            .save_target(TargetMapping {
                id: Uuid::nil(),
                label: "TEST_ONLY".into(),
                file_path: config.to_str().unwrap().into(),
                pointer: "/key".into(),
                key_id: key,
                bearer_prefix: false,
                replace_variables: false,
            })
            .unwrap();
        let batch = BatchUpdater::new(vault.backup_directory());
        let mut preview = batch.preview(&vault, &[target]);
        let id = preview.id;
        assert_eq!(
            batch.apply(&mut preview, id, true).unwrap()[0].outcome,
            Outcome::Applied
        );
        let cipher = fs::read(directory.join(storage::vault_filename())).unwrap();
        assert!(!cipher.windows(13).any(|v| v == b"TEST_ONLY_NEW"));
        drop(vault);
        assert_eq!(Vault::open(&directory).unwrap().snapshot().keys.len(), 1);
        let service =
            secret_service::blocking::SecretService::connect(secret_service::EncryptionType::Dh)
                .unwrap();
        service.get_default_collection().unwrap().lock().unwrap();
        assert_eq!(
            linux::crypt(b"TEST_ONLY_LOCKED", true).unwrap_err().code,
            "STORAGE_LOCKED"
        );
        assert_eq!(
            linux::initialize_storage(true).unwrap_err().code,
            "STORAGE_LOCKED"
        );
    } else {
        assert_eq!(phase, "reopen");
        // The shell harness restarted the real daemon and unlocked the persisted test keyring.
        let vault = Vault::open(&directory)
            .expect("retrieve same persisted master key after daemon restart");
        assert_eq!(vault.snapshot().keys.len(), 1);
        let batch = BatchUpdater::new(vault.backup_directory());
        let backups = batch.backups().unwrap();
        assert_eq!(backups.len(), 1);
        assert!(backups[0].error.is_none());
        let mut rollback = batch.preview_rollback(&backups[0].backup_path).unwrap();
        let id = rollback.id;
        assert_eq!(
            batch.apply(&mut rollback, id, true).unwrap()[0].outcome,
            Outcome::Applied
        );
        assert_eq!(fs::read(config).unwrap(), original);
    }
    println!("SECRET_SERVICE_LIFECYCLE_PHASE=PASS ({phase})");
}
