use atm_core::harness_embed;

#[test]
fn argument_bounds_reject_oversize_and_control_characters() {
    assert!(harness_embed::bound_engine_args(&["status".into()]).is_ok());
    for arguments in [
        vec!["x".into(); 65],
        vec!["x".repeat(4097)],
        vec!["a\nb".into()],
        vec!["x".repeat(4096); 9],
    ] {
        assert_eq!(
            harness_embed::bound_engine_args(&arguments)
                .unwrap_err()
                .code,
            "CLI_ARGUMENT"
        );
    }
}

#[test]
fn packaged_source_requires_manifest_not_python_entrypoint() {
    if std::env::var_os(harness_embed::SOURCE_ENV).is_some() {
        return;
    }
    let source = harness_embed::embedded_source_dir().unwrap();
    assert!(source.join("distribution-manifest.json").is_file());
}
