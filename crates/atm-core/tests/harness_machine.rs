// TEST_ONLY isolated executable fixtures; never access a real harness installation.
#[cfg(any(target_os = "linux", target_os = "macos"))]
#[test]
fn machine_argv_capability_gate_and_scoped_confirmation() {
    use atm_core::harness_machine;
    use std::{fs, os::unix::fs::PermissionsExt};
    let temp = tempfile::tempdir().unwrap();
    let home = temp.path().join("TEST_ONLY manager home");
    fs::create_dir_all(home.join("venv/bin")).unwrap();
    fs::create_dir_all(home.join("repo/scripts")).unwrap();
    fs::write(home.join("repo/scripts/engine.py"), "# TEST_ONLY").unwrap();
    let program = home.join("venv/bin/python");
    fs::write(&program, r##"#!/bin/sh
# Test double: assert exact argv shape including whitespace-safe manager path.
[ "$2" = '--home' ] && [ "$4" = 'machine' ] && [ "$5" = '--protocol' ] && [ "$6" = '1' ] || exit 2
case "$7" in
 capabilities) printf '%s\n' '{"protocolVersion":1,"operation":"capabilities","ok":true,"result":{"harnesses":["codex"],"operations":{"remove":{"supported":true,"requiresConfirmation":true,"explicitHarnesses":true},"update":{"supported":false,"requiresConfirmation":true,"explicitHarnesses":true}}}}';;
 remove) [ "$8" = '--harness' ] && [ "$9" = codex ] && [ "${10}" = '--confirm' ] && [ "$#" = 10 ] || exit 2
 printf '%s\n' '{"protocolVersion":1,"operation":"remove","ok":true,"result":{"harnesses":["codex"],"exitCode":0}}';;
 *) exit 9;;
esac
"##).unwrap();
    fs::set_permissions(&program, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(harness_machine::capabilities_at(&home).unwrap().operations["remove"].supported);
    assert_eq!(
        harness_machine::execute_at(&home, "update", &["codex".into()], true)
            .unwrap_err()
            .code,
        "HARNESS_UNSUPPORTED"
    );
    assert_eq!(
        harness_machine::execute_at(&home, "remove", &["--all".into()], true)
            .unwrap_err()
            .code,
        "HARNESS_REQUEST"
    );
    assert_eq!(
        harness_machine::execute_at(&home, "remove", &["codex".into(), "codex".into()], true)
            .unwrap_err()
            .code,
        "HARNESS_REQUEST"
    );
    harness_machine::execute_at(&home, "remove", &["codex".into()], true).unwrap();
}

/// Opt-in conformance against a separately checked-out harness implementation.
/// Only capabilities/status are invoked, with a new isolated manager home.
#[cfg(any(target_os = "linux", target_os = "macos"))]
#[test]
fn actual_harness_v1_contract_when_checkout_is_explicitly_supplied() {
    use atm_core::{harness, harness_machine};
    use std::{fs, os::unix::fs::symlink, path::PathBuf, process::Command};
    let Some(checkout) = std::env::var_os("ATM_TEST_ENGINE_CHECKOUT").map(PathBuf::from) else {
        return;
    };
    assert!(checkout.join("scripts/engine.py").is_file());
    let temp = tempfile::tempdir().unwrap();
    let home = temp.path().join("TEST_ONLY isolated manager");
    fs::create_dir_all(home.join("venv/bin")).unwrap();
    symlink("/usr/bin/python3", home.join("venv/bin/python")).unwrap();
    symlink(&checkout, home.join("repo")).unwrap();
    let caps = harness_machine::capabilities_at(&home).unwrap();
    for operation in ["install", "refresh", "remove", "repair"] {
        let cap = &caps.operations[operation];
        assert!(cap.supported && cap.requires_confirmation && cap.explicit_harnesses);
    }
    for operation in ["check", "doctor"] {
        let cap = &caps.operations[operation];
        assert!(cap.supported && !cap.requires_confirmation && !cap.explicit_harnesses);
    }
    assert!(!caps.operations["update"].supported);
    assert!(!caps.operations["recover"].supported);
    assert!(caps.harnesses.contains(&"codex".to_owned()));
    let output = Command::new("/usr/bin/python3")
        .arg(checkout.join("scripts/engine.py"))
        .arg("--home")
        .arg(&home)
        .args(["machine", "--protocol", "1", "status"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let envelope: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["protocolVersion"], 1);
    assert_eq!(envelope["operation"], "status");
    assert_eq!(envelope["ok"], true);
    let snapshot =
        harness::parse(&envelope["result"], &home.to_string_lossy(), "recorded").unwrap();
    assert!(!snapshot.installed);
    assert!(snapshot.harnesses.is_empty());
    assert!(snapshot.operation_kind.is_none());
    assert_eq!(snapshot.source, "recorded");
    assert_eq!(snapshot.worktree_clean, None);
    // Read commands must not manufacture state in the isolated manager home.
    assert_eq!(fs::read_dir(&home).unwrap().count(), 2);
}
