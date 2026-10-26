use atm_core::distribution::{hooks, runtime::PreparedRuntime};
use serde_json::{json, Value};
use std::path::PathBuf;

fn root() -> PathBuf {
    std::env::temp_dir().join("TEST_ONLY hooks 空间")
}
fn runtime() -> PreparedRuntime {
    let root = root().join("venv 版本");
    PreparedRuntime {
        id: "watcher".into(),
        identity: "test-locked".into(),
        python: root.join("bin/python"),
        root,
        external: false,
    }
}

#[test]
fn explicit_enable_disable_preserves_foreign_entries_and_repeats() {
    let target = root().join("hooks.json");
    let runtime = runtime();
    let original = json!({"userField":{"keep":true},"hooks":{"Unknown":[],"Stop":[],"SessionStart":[{"matcher":"foreign","hooks":[{"type":"command","command":"user-owned"}]}]}});
    let original_bytes = serde_json::to_vec(&original).unwrap();
    let enabled = hooks::plan(
        &target,
        Some(&original_bytes),
        None,
        true,
        Some(&runtime),
        &root(),
    )
    .unwrap();
    let bytes = &enabled.artifact.as_ref().unwrap().bytes;
    let value: Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(value["hooks"]["SessionStart"].as_array().unwrap().len(), 2);
    assert_eq!(value["hooks"]["Unknown"], json!([]));
    let repeat = hooks::plan(
        &target,
        Some(bytes),
        enabled.ownership.as_ref(),
        true,
        Some(&runtime),
        &root(),
    )
    .unwrap();
    assert!(repeat.artifact.is_none());
    assert_eq!(repeat.ownership, enabled.ownership);
    let disabled = hooks::plan(
        &target,
        Some(bytes),
        enabled.ownership.as_ref(),
        false,
        None,
        &root(),
    )
    .unwrap();
    let disabled_bytes = &disabled.artifact.as_ref().unwrap().bytes;
    assert_eq!(
        serde_json::from_slice::<Value>(disabled_bytes).unwrap(),
        original
    );
    assert!(disabled.ownership.is_none());
    assert!(
        hooks::plan(&target, Some(disabled_bytes), None, false, None, &root())
            .unwrap()
            .artifact
            .is_none()
    );
}

#[test]
fn no_receipt_cannot_adopt_existing_hook_or_remove_user_modified_group() {
    let target = root().join("hooks.json");
    let runtime = runtime();
    let enabled = hooks::plan(&target, None, None, true, Some(&runtime), &root()).unwrap();
    let bytes = &enabled.artifact.as_ref().unwrap().bytes;
    assert_eq!(
        hooks::plan(&target, Some(bytes), None, true, Some(&runtime), &root())
            .unwrap_err()
            .code,
        "HARNESS_HOOK_CONFLICT"
    );
    let mut modified: Value = serde_json::from_slice(bytes).unwrap();
    modified["hooks"]["Stop"][0]["hooks"][0]["timeoutSec"] = json!(22);
    let modified = serde_json::to_vec(&modified).unwrap();
    for enable in [true, false] {
        assert_eq!(
            hooks::plan(
                &target,
                Some(&modified),
                enabled.ownership.as_ref(),
                enable,
                Some(&runtime),
                &root()
            )
            .unwrap_err()
            .code,
            "HARNESS_HOOK_CONFLICT"
        );
    }
}

#[test]
fn disabled_missing_config_is_noop_and_duplicate_owned_groups_are_ambiguous() {
    let target = root().join("hooks.json");
    let runtime = runtime();
    assert!(hooks::plan(&target, None, None, false, None, &root())
        .unwrap()
        .artifact
        .is_none());
    let enabled = hooks::plan(&target, None, None, true, Some(&runtime), &root()).unwrap();
    let mut value: Value = serde_json::from_slice(&enabled.artifact.unwrap().bytes).unwrap();
    let group = value["hooks"]["Stop"][0].clone();
    value["hooks"]["Stop"].as_array_mut().unwrap().push(group);
    assert_eq!(
        hooks::plan(
            &target,
            Some(&serde_json::to_vec(&value).unwrap()),
            enabled.ownership.as_ref(),
            false,
            None,
            &root()
        )
        .unwrap_err()
        .code,
        "HARNESS_HOOK_CONFLICT"
    );
}

#[test]
fn windows_space_unicode_and_trailing_backslash_quote_without_shell_expansion() {
    let line = hooks::command_line(
        &[
            r"C:\Program Files\Python 中文\python.exe".into(),
            r"C:\payload 路径\".into(),
        ],
        true,
    )
    .unwrap();
    assert_eq!(
        line,
        "\"C:\\Program Files\\Python 中文\\python.exe\" \"C:\\payload 路径\\\\\""
    );
    assert!(hooks::command_line(&[r"C:\%APPDATA%\python.exe".into()], true).is_err());
    assert!(hooks::command_line(&["bad\npath".into()], false).is_err());
    assert_eq!(
        hooks::command_line(&["user's python".into()], false).unwrap(),
        "'user'\\''s python'"
    );
}
