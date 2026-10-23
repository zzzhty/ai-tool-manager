// Only TEST_ONLY fixtures. No real oh-my-harness install, Git, Codex or network.
use atm_core::omh;
use serde_json::{json, Value};
use std::fs;

fn recorded_status() -> Value {
    // Mirrors `omh status --json` (recorded-state-only), with TEST_ONLY values.
    json!({
        "desiredHarnesses": ["claude-code", "codex", "copilot-cli", "openclaw", "pi-agent"],
        "harnessReceipts": {
            "claude-code": [{
                "bundleIdentity": "sha256:TEST_ONLY",
                "harness": "claude-code",
                "managerRevision": "TEST_ONLY_REVISION",
                "releaseVersion": "1.0.0",
                "root": "/TEST_ONLY/home/.claude",
                "schemaVersion": "2026-08-24",
                "status": "ready",
                "updatedAt": "2026-10-14T16:08:42.295941Z"
            }],
            "codex": [{
                "bundleIdentity": "sha256:TEST_ONLY",
                "harness": "codex",
                "managerRevision": "TEST_ONLY_REVISION",
                "releaseVersion": "1.0.0",
                "root": "/TEST_ONLY/home/.codex",
                "schemaVersion": "2026-08-24",
                "status": "ready",
                "updatedAt": "2026-10-14T16:10:44.095373Z"
            }]
        },
        "home": "/TEST_ONLY/home/.oh-my-harness",
        "initialReceipt": null,
        "manager": {
            "bundleIdentity": "sha256:TEST_ONLY",
            "channel": "main",
            "product": "oh-my-harness",
            "releaseVersion": "1.0.0",
            "repository": "git@github.com:zzzhty/oh-my-harness.git",
            "requestedRef": "origin/main",
            "revision": "TEST_ONLY_REVISION",
            "schemaVersion": "2026-08-24",
            "status": "ready",
            "updatedAt": "2026-10-14T16:08:42.116467Z"
        },
        "observation": "recorded-state-only",
        "operation": null,
        "product": "oh-my-harness",
        "stateKind": "recorded",
        "worktreeClean": null
    })
}

#[test]
fn manager_home_resolves_override_empty_env_and_default() {
    let home = std::path::Path::new("/TEST_ONLY/home");
    let override_path =
        omh::resolve_manager_home(Some(std::ffi::OsStr::new("/TEST_ONLY/override")), home);
    assert_eq!(
        override_path,
        std::path::PathBuf::from("/TEST_ONLY/override")
    );
    let empty = omh::resolve_manager_home(Some(std::ffi::OsStr::new("")), home);
    let default = omh::resolve_manager_home(None, home);
    let expected = if cfg!(windows) {
        r"\TEST_ONLY\home\.oh-my-harness"
    } else {
        "/TEST_ONLY/home/.oh-my-harness"
    };
    assert_eq!(empty, std::path::PathBuf::from(expected));
    assert_eq!(default, empty);
}

fn fixture_home_with_scripts() -> (tempfile::TempDir, std::path::PathBuf) {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY manager home");
    let python = if cfg!(windows) {
        home.join("venv/Scripts/python.exe")
    } else {
        home.join("venv/bin/python")
    };
    fs::create_dir_all(python.parent().unwrap()).unwrap();
    fs::create_dir_all(home.join("repo/scripts")).unwrap();
    fs::write(python, "TEST_ONLY").unwrap();
    fs::write(home.join("repo/scripts/omh.py"), "# TEST_ONLY data\n").unwrap();
    (root, home)
}

#[test]
fn invocation_rejects_missing_components_and_non_absolute_homes() {
    let (root, home) = fixture_home_with_scripts();
    assert!(omh::invocation(&home).is_ok());
    // Missing CLI data file means the checkout is not a usable installation source.
    fs::remove_file(home.join("repo/scripts/omh.py")).unwrap();
    let error = omh::invocation(&home).unwrap_err();
    assert_eq!(error.code, "OMH_NOT_INSTALLED");
    let relative = std::path::Path::new("TEST_ONLY/relative");
    assert_eq!(
        omh::invocation(relative).unwrap_err().code,
        "OMH_NOT_INSTALLED"
    );
    drop(root);
}

#[test]
fn parse_projects_recorded_snapshot_and_keeps_unreported_values_unknown() {
    let status = recorded_status();
    let snapshot = omh::parse(&status, "/TEST_ONLY/home/.oh-my-harness", "recorded").unwrap();
    assert!(snapshot.installed);
    assert_eq!(snapshot.manager_status.as_deref(), Some("ready"));
    assert_eq!(snapshot.channel.as_deref(), Some("main"));
    assert_eq!(snapshot.release_version.as_deref(), Some("1.0.0"));
    assert_eq!(snapshot.revision, Some("TEST_ONLY_REVISION".to_owned()));
    assert_eq!(snapshot.operation_kind, None);
    assert_eq!(snapshot.worktree_clean, None);
    let names: Vec<_> = snapshot.harnesses.iter().map(|h| h.name.as_str()).collect();
    assert_eq!(
        names,
        [
            "claude-code",
            "codex",
            "copilot-cli",
            "openclaw",
            "pi-agent"
        ]
    );
    let claude = &snapshot.harnesses[0];
    assert_eq!(claude.status.as_deref(), Some("ready"));
    assert_eq!(claude.root.as_deref(), Some("/TEST_ONLY/home/.claude"));
    // A desired harness without any receipt stays listed but unknown.
    let pi = snapshot
        .harnesses
        .iter()
        .find(|h| h.name == "pi-agent")
        .unwrap();
    assert_eq!(pi.status, None);
    assert_eq!(pi.root, None);
    assert_eq!(pi.updated_at, None);
}

#[test]
fn parse_skips_non_string_and_duplicate_desired_names() {
    let mut status = recorded_status();
    status["desiredHarnesses"] = json!(["codex", 42, "codex", null, "openclaw"]);
    let snapshot = omh::parse(&status, "/TEST_ONLY", "recorded").unwrap();
    let names: Vec<_> = snapshot.harnesses.iter().map(|h| h.name.as_str()).collect();
    assert_eq!(names, ["codex", "openclaw"]);
}

#[test]
fn parse_maps_active_operation_and_worktree_state_without_invention() {
    let mut status = recorded_status();
    status["operation"] = json!({"kind": "update", "stage": "refresh"});
    status["worktreeClean"] = json!(true);
    let snapshot = omh::parse(&status, "/TEST_ONLY", "recorded").unwrap();
    assert_eq!(snapshot.operation_kind.as_deref(), Some("update"));
    assert_eq!(snapshot.worktree_clean, Some(true));
    status["operation"] = json!({"unexpected": "shape"});
    let snapshot = omh::parse(&status, "/TEST_ONLY", "recorded").unwrap();
    assert_eq!(snapshot.operation_kind.as_deref(), Some("unknown"));
    status["operation"] = json!("garbage");
    let snapshot = omh::parse(&status, "/TEST_ONLY", "recorded").unwrap();
    assert_eq!(snapshot.operation_kind.as_deref(), Some("unknown"));
}

#[test]
fn parse_fails_closed_when_the_payload_is_not_oh_my_harness() {
    let mut status = recorded_status();
    status["product"] = json!("other-product");
    assert_eq!(
        omh::parse(&status, "/TEST_ONLY", "recorded")
            .unwrap_err()
            .code,
        "OMH_PROTOCOL"
    );
    assert_eq!(
        omh::parse(&json!({}), "/TEST_ONLY", "recorded")
            .unwrap_err()
            .code,
        "OMH_PROTOCOL"
    );
}

#[test]
fn parse_reports_missing_manager_record_without_calling_it_uninstalled() {
    let mut status = recorded_status();
    status["manager"] = json!(null);
    let snapshot = omh::parse(&status, "/TEST_ONLY", "recorded").unwrap();
    assert!(!snapshot.installed);
    assert_eq!(snapshot.manager_status, None);
    assert!(!snapshot.harnesses.is_empty());
}

#[test]
fn snapshots_expose_only_declared_fields_to_the_ipc_boundary() {
    let snapshot = omh::parse(&recorded_status(), "/TEST_ONLY", "recorded").unwrap();
    let serialized = serde_json::to_value(&snapshot).unwrap();
    let mut keys: Vec<_> = serialized.as_object().unwrap().keys().collect();
    keys.sort_unstable();
    assert_eq!(
        keys,
        [
            "channel",
            "harnesses",
            "installed",
            "managerHome",
            "managerStatus",
            "operationKind",
            "releaseVersion",
            "repository",
            "revision",
            "source",
            "worktreeClean",
        ]
    );
}
