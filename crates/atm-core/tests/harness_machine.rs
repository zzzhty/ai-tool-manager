use atm_core::harness_machine;

#[test]
fn capabilities_are_native_and_do_not_create_state() {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY manager 测试");
    let caps = harness_machine::capabilities_at(&home).unwrap();
    assert!(caps.harnesses.contains(&"codex".to_owned()));
    for operation in ["install", "refresh", "remove", "repair"] {
        assert!(caps.operations[operation].supported);
        assert!(caps.operations[operation].requires_confirmation);
        assert!(caps.operations[operation].explicit_harnesses);
    }
    assert!(!caps.operations["check"].requires_confirmation);
    assert!(!caps.operations["doctor"].explicit_harnesses);
    assert!(!caps.operations["update"].supported);
    assert!(!home.exists());
}

#[test]
fn confirmation_unknown_duplicate_and_alias_duplicate_fail_before_writes() {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY manager");
    assert_eq!(
        harness_machine::execute_at(&home, "install", &["codex".into()], false)
            .unwrap_err()
            .code,
        "HARNESS_CONFIRMATION_REQUIRED"
    );
    for targets in [
        vec!["--all".into()],
        vec!["codex".into(), "codex".into()],
        vec!["claude".into(), "claude-code".into()],
        vec![],
    ] {
        assert_eq!(
            harness_machine::execute_at(&home, "install", &targets, true)
                .unwrap_err()
                .code,
            "HARNESS_REQUEST"
        );
    }
    assert_eq!(
        harness_machine::execute_at(&home, "update", &["codex".into()], true)
            .unwrap_err()
            .code,
        "HARNESS_UNSUPPORTED"
    );
    assert!(!home.exists());
}
