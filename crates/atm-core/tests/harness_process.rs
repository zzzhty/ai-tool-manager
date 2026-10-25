#![cfg(any(target_os = "linux", target_os = "macos"))]
// Only TEST_ONLY Python fixtures are launched. No real atm-harness install, Git or network.
use atm_core::harness;
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    time::{Duration, Instant},
};

fn status_payload() -> Value {
    json!({
        "product": "atm-harness",
        "observation": "recorded-state-only",
        "stateKind": "recorded",
        "operation": null,
        "worktreeClean": null,
        "desiredHarnesses": ["codex"],
        "harnessReceipts": {"codex": [{"harness": "codex", "status": "ready", "root": "/TEST_ONLY/home/.codex", "releaseVersion": "1.0.0", "updatedAt": "2026-10-14T16:10:44.095373Z"}]},
        "manager": {"product": "atm-harness", "channel": "main", "status": "ready", "releaseVersion": "1.0.0", "revision": "TEST_ONLY_REVISION", "repository": "git@github.com:zzzhty/atm-harness.git"}
    })
}

fn fixture(script: &str) -> (tempfile::TempDir, PathBuf) {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY manager home");
    let python = home.join("venv/bin/python");
    fs::create_dir_all(python.parent().unwrap()).unwrap();
    fs::create_dir_all(home.join("repo/scripts")).unwrap();
    fs::write(&python, script).unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o700)).unwrap();
    fs::write(home.join("repo/scripts/engine.py"), "# TEST_ONLY data\n").unwrap();
    (root, home)
}

fn print_script(payload: &Value, exit_code: i32) -> String {
    // The payload is printed as raw JSON text; TEST_ONLY fixtures contain no quotes.
    format!(
        "#!/usr/bin/python3\nimport sys\nprint(r'''{payload}''', flush=True)\nsys.exit({exit_code})\n"
    )
}

/// One bounded retry after a first error: a transient OS-level spawn failure under
/// full-suite parallel load is environmental. Deterministic fixture outcomes
/// (protocol rejections, exit failures) reproduce identically on the retry.
fn query_with_spawn_retry(
    home: &std::path::Path,
) -> atm_core::Result<atm_core::harness::HarnessStatusSnapshot> {
    let first = harness::query(home);
    if first.is_ok() {
        return first;
    }
    std::thread::sleep(Duration::from_millis(250));
    harness::query(home)
}

#[test]
fn one_bounded_query_parses_the_recorded_snapshot_without_writes() {
    let script = print_script(&status_payload(), 0);
    let (_root, home) = fixture(&script);
    let snapshot = query_with_spawn_retry(&home).unwrap();
    assert_eq!(snapshot.source, "recorded");
    assert!(snapshot.installed);
    assert_eq!(snapshot.manager_status.as_deref(), Some("ready"));
    assert_eq!(
        snapshot.harnesses[0].root.as_deref(),
        Some("/TEST_ONLY/home/.codex")
    );
}

#[test]
fn wrong_product_non_json_and_cli_failures_fail_closed() {
    let mut payload = status_payload();
    payload["product"] = json!("other");
    for (script, expected) in [
        (print_script(&payload, 0), "HARNESS_PROTOCOL"),
        (
            "#!/usr/bin/python3\nprint('TEST_ONLY not json', flush=True)\n".to_owned(),
            "HARNESS_PROTOCOL",
        ),
        (
            "#!/usr/bin/python3\nimport sys\nprint('TEST_ONLY not json', flush=True)\nsys.exit(1)\n".to_owned(),
            "HARNESS_CLI_FAILED",
        ),
    ] {
        let (_root, home) = fixture(&script);
        let error = query_with_spawn_retry(&home).unwrap_err();
        assert_eq!(error.code, expected);
    }
}

#[test]
fn nonzero_exit_with_product_payload_maps_to_runtime_unavailable() {
    let script = print_script(&status_payload(), 3);
    let (_root, home) = fixture(&script);
    assert_eq!(
        query_with_spawn_retry(&home).unwrap_err().code,
        "HARNESS_RUNTIME"
    );
}

#[test]
fn oversized_status_output_is_rejected_not_truncated_into_a_false_snapshot() {
    let script = "#!/usr/bin/python3\nprint('x' * 300000, flush=True)\n".to_owned();
    let (_root, home) = fixture(&script);
    assert_eq!(
        query_with_spawn_retry(&home).unwrap_err().code,
        "HARNESS_PROTOCOL"
    );
}

#[test]
fn timeout_kills_a_wedged_status_query_within_the_bound() {
    let script = "#!/usr/bin/python3\nimport time\ntime.sleep(30)\n".to_owned();
    let (_root, home) = fixture(&script);
    let start = Instant::now();
    let error = harness::query_with_timeout(&home, Duration::from_millis(300)).unwrap_err();
    // A transient spawn failure maps to a launch error, not HARNESS_TIMEOUT; retry once.
    let error = if error.code == "HARNESS_TIMEOUT" {
        error
    } else {
        std::thread::sleep(Duration::from_millis(250));
        harness::query_with_timeout(&home, Duration::from_millis(300)).unwrap_err()
    };
    assert_eq!(error.code, "HARNESS_TIMEOUT");
    // Parallel test runners may delay process startup; 30s sleep must never be awaited.
    assert!(start.elapsed() < Duration::from_secs(8));
}

#[test]
fn the_timeout_bound_cannot_be_grown_past_the_product_limit() {
    let (_root, home) = fixture("#!/usr/bin/python3\nprint('{}')\n");
    for timeout in [Duration::ZERO, Duration::from_secs(11)] {
        let error = harness::query_with_timeout(&home, timeout).unwrap_err();
        assert_eq!(error.code, "HARNESS_TIMEOUT");
    }
}

#[test]
fn missing_venv_reports_install_absence_without_spawning() {
    let root = tempfile::tempdir().unwrap();
    let home = root.path().join("TEST_ONLY empty");
    let error = harness::query(&home).unwrap_err();
    assert_eq!(error.code, "HARNESS_NOT_INSTALLED");
}

// Explicit live check against a real installation; excluded from ordinary runs.
#[test]
fn live_query_against_a_real_installation_when_explicitly_requested() {
    if std::env::var("ATM_ENGINE_LIVE")
        .map(|value| value != "1")
        .unwrap_or(true)
    {
        return;
    }
    let snapshot = harness::query_from_environment().expect("live harness status query");
    println!("{}", serde_json::to_string_pretty(&snapshot).unwrap());
}

#[test]
fn timeout_still_bounds_child_after_both_output_pipes_close() {
    let (_root, home) =
        fixture("#!/usr/bin/python3\nimport os,time\nos.close(1)\nos.close(2)\ntime.sleep(30)\n");
    let start = Instant::now();
    let error = harness::query_with_timeout(&home, Duration::from_millis(300)).unwrap_err();
    assert_eq!(error.code, "HARNESS_TIMEOUT");
    assert!(start.elapsed() < Duration::from_secs(8));
}
