use atm_core::{
    application::configuration::{ConfigurationSession, TargetView},
    skills::SkillsService,
    storage::{self, Protector},
    Error, Result, TargetMapping,
};
use std::{fs, sync::Arc};
use uuid::Uuid;
use zeroize::Zeroizing;

struct Unavailable;
impl Protector for Unavailable {
    fn crypt(&self, _: &[u8], _: bool) -> Result<Zeroizing<Vec<u8>>> {
        Err(Error::new("STORAGE_UNAVAILABLE", "TEST_ONLY"))
    }
}

#[test]
fn failed_configuration_is_lazy_retryable_and_does_not_block_skills() {
    let temporary = tempfile::tempdir().unwrap();
    let directory = temporary.path().join("configuration");
    let mut session =
        ConfigurationSession::new(Ok(directory.clone()), Arc::new(Unavailable), false);
    session.invalidate();
    assert!(!directory.exists());
    storage::ensure_directory(&directory).unwrap();
    fs::write(
        directory.join(storage::vault_filename()),
        b"TEST_ONLY_unavailable",
    )
    .unwrap();
    assert_eq!(session.get().err().unwrap().code, "STORAGE_UNAVAILABLE");
    let skills = SkillsService::new(temporary.path().into(), temporary.path().join("trash"))
        .with_manager_home(None);
    assert_eq!(skills.inventory().unwrap().roots.len(), 10);
    fs::remove_file(directory.join(storage::vault_filename())).unwrap();
    fs::write(directory.join("templates.required"), b"TEST_ONLY").unwrap();
    assert_eq!(session.get().err().unwrap().code, "TEMPLATE_STORE_MISSING");
    assert_eq!(skills.inventory().unwrap().roots.len(), 10);
    fs::remove_file(directory.join("templates.required")).unwrap();
    assert!(session.get().unwrap().snapshot().unwrap().keys.is_empty());
}

#[test]
fn shared_configuration_preserves_schema_guards_confirmation_and_single_use_preview() {
    let temporary = tempfile::tempdir().unwrap();
    let directory = temporary.path().join("configuration");
    let protector = storage::demo_protector().unwrap();
    let file = temporary.path().join("config.json");
    fs::write(&file, br#"{"apiKey":"TEST_ONLY_old","enabled":true}"#).unwrap();
    let mut session = ConfigurationSession::new(Ok(directory.clone()), protector.clone(), false);
    let service = session.get().unwrap();
    let key = service
        .save_key(
            None,
            "TEST_ONLY".into(),
            Zeroizing::new("TEST_ONLY_new".into()),
        )
        .unwrap();
    let path = file.to_string_lossy().into_owned();
    let candidate = service.infer_template(path.clone()).unwrap();
    let schema = r#"{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"object","properties":{"apiKey":{"type":"string"},"enabled":{"type":"boolean"}},"required":["enabled"]}"#;
    let template = service
        .save_template(
            candidate.id,
            "TEST_ONLY".into(),
            vec!["/apiKey".into()],
            Some(schema.into()),
        )
        .unwrap();
    let target = service
        .save_target(TargetView {
            target: TargetMapping {
                id: Uuid::nil(),
                label: "TEST_ONLY".into(),
                file_path: path,
                pointer: "/apiKey".into(),
                key_id: key,
                bearer_prefix: false,
                replace_variables: false,
            },
            template_id: Some(template),
        })
        .unwrap();
    let preview = service.preview(vec![target]).unwrap();
    assert_eq!(
        service.apply_preview(preview.id, false).err().unwrap().code,
        "CONFIRM_REQUIRED"
    );
    let result = service.apply_preview(preview.id, true).unwrap();
    assert!(matches!(
        result[0].outcome,
        atm_core::batch::Outcome::Applied
    ));
    assert_eq!(
        service.apply_preview(preview.id, true).err().unwrap().code,
        "PREVIEW_EXPIRED"
    );
    drop(session);
    let mut session = ConfigurationSession::new(Ok(directory), protector, false);
    let service = session.get().unwrap();
    assert_eq!(
        service.snapshot().unwrap().targets[0].template_id,
        Some(template)
    );
    fs::write(&file, br#"{"apiKey":"TEST_ONLY_new"}"#).unwrap();
    let rejected = service.preview(vec![target]).unwrap();
    assert!(rejected.files[0].error.is_some());
    assert_eq!(fs::read(&file).unwrap(), br#"{"apiKey":"TEST_ONLY_new"}"#);
}
