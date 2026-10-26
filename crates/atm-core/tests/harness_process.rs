//! Regression: recorded status has no interpreter or subprocess prerequisite.
use atm_core::harness;
use std::fs;

#[test]
fn missing_manager_status_is_read_only_without_a_python_installation() {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY absent manager 测试");
    let snapshot = harness::query(&home).unwrap();
    assert!(!snapshot.installed);
    assert_eq!(snapshot.worktree_clean, None);
    assert_eq!(snapshot.source, "recorded");
    assert!(!home.exists());
}

#[test]
fn legacy_interpreter_and_engine_files_cannot_execute_during_status() {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY old manager");
    fs::create_dir_all(home.join("venv/bin")).unwrap();
    fs::create_dir_all(home.join("repo/scripts")).unwrap();
    fs::write(
        home.join("venv/bin/python"),
        b"not executable; must never be run",
    )
    .unwrap();
    fs::write(
        home.join("repo/scripts/engine.py"),
        b"raise RuntimeError('must never run')",
    )
    .unwrap();
    let snapshot = harness::query(&home).unwrap();
    // Empty legacy scaffolding is not current installation evidence.
    assert!(!snapshot.installed);
    assert!(!home.join("state").exists());
}
