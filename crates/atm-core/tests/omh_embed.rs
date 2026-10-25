//! Embedded-engine invocation construction: fixed argv, bounds and the
//! not-installed guidance, all without spawning processes.
use atm_core::omh_embed;
use std::fs;
use std::path::PathBuf;
use tempfile::TempDir;

fn fixture_home() -> (TempDir, PathBuf) {
    let home = tempfile::tempdir().unwrap();
    let root = home.path().join("test-oh-my-harness");
    fs::create_dir_all(root.join("repo/scripts")).unwrap();
    fs::write(root.join("repo/scripts/omh.py"), b"# TEST_ONLY\n").unwrap();
    let venv = root.join(if cfg!(windows) {
        "venv/Scripts/python.exe"
    } else {
        "venv/bin/python"
    });
    fs::create_dir_all(venv.parent().unwrap()).unwrap();
    fs::write(&venv, b"TEST_ONLY").unwrap();
    (home, root)
}

#[test]
fn harness_invocation_builds_fixed_argv_with_home_first() {
    let (_guard, home) = fixture_home();
    let engine = vec!["install".to_owned(), "codex".to_owned()];
    let (python, argv) = omh_embed::harness_invocation(&home, &engine).unwrap();
    let expected_python = home.join(if cfg!(windows) {
        "venv/Scripts/python.exe"
    } else {
        "venv/bin/python"
    });
    assert_eq!(python, expected_python);
    assert_eq!(argv[0], home.join("repo/scripts/omh.py").to_string_lossy());
    assert_eq!(argv[1], "--home");
    assert_eq!(argv[2], home.to_string_lossy());
    assert_eq!(&argv[3..], &["install", "codex"]);
}

#[test]
fn missing_engine_files_report_bootstrap_guidance() {
    let home = tempfile::tempdir().unwrap();
    let error = omh_embed::harness_invocation(home.path(), &["status".into()]).unwrap_err();
    assert_eq!(error.code, "OMH_NOT_INSTALLED");
    assert!(error.message.contains("atm harness bootstrap"));
    let error = omh_embed::watcher_invocation(home.path(), &["doctor".into()]).unwrap_err();
    assert_eq!(error.code, "OMH_NOT_INSTALLED");
}

#[test]
fn oversized_engine_argv_is_rejected_before_spawning() {
    let (_guard, home) = fixture_home();
    let many: Vec<String> = (0..70).map(|index| format!("arg{index}")).collect();
    let error = omh_embed::harness_invocation(&home, &many).unwrap_err();
    assert_eq!(error.code, "CLI_ARGUMENT");
    let long = vec!["x".repeat(5000)];
    let error = omh_embed::harness_invocation(&home, &long).unwrap_err();
    assert_eq!(error.code, "CLI_ARGUMENT");
}

#[test]
fn watcher_invocation_prefixes_the_skill_subcommand() {
    let (_guard, home) = fixture_home();
    let watcher = home.join("repo/plugins/watcher/scripts/watcher");
    fs::create_dir_all(watcher.parent().unwrap()).unwrap();
    fs::write(&watcher, b"# TEST_ONLY\n").unwrap();
    let (_python, argv) =
        omh_embed::watcher_invocation(&home, &["install-hook".into(), "--apply".into()]).unwrap();
    assert_eq!(argv[0], "-B");
    assert_eq!(argv[1], watcher.to_string_lossy());
    assert_eq!(argv[2], "skill");
    assert_eq!(&argv[3..], &["install-hook", "--apply"]);
}

#[test]
fn embed_invocation_rejects_unknown_maintenance_commands() {
    let home = tempfile::tempdir().unwrap();
    let error = omh_embed::embed_invocation("nope", home.path()).unwrap_err();
    assert_eq!(error.code, "CLI_COMMAND");
}

#[test]
fn embedded_source_dir_resolves_the_repository_tree_without_env() {
    // In this workspace the compile-time fallback points at the vendored tree.
    if std::env::var_os(omh_embed::SOURCE_ENV).is_some() {
        return; // An explicit override is itself valid; nothing to assert here.
    }
    let source = omh_embed::embedded_source_dir().unwrap();
    assert!(source.join("scripts/omh.py").is_file());
    assert!(source.join("scripts/atm_embed.py").is_file());
}
