#![cfg(any(target_os = "linux", target_os = "macos"))]
// Only TEST_ONLY Python fixtures are launched. No real Codex CLI, auth files or network.
use atm_core::usage::{
    codex::{self, Rpc},
    process::StdioRpc,
    Status,
};
use serde_json::json;
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::Mutex,
    time::{Duration, Instant},
};
const SCRIPT: &str = r#"#!/usr/bin/python3
import json, os, sys
for line in sys.stdin:
    request = json.loads(line)
    with open(os.path.join(os.environ['CODEX_HOME'],'TEST_ONLY_requests.jsonl'),'a') as log:
        log.write(json.dumps(request)+'\n')
    if 'id' not in request or 'method' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'userAgent':'TEST_ONLY_CLI/1.0'}
    elif method == 'account/read':
        result = {'account':{'type':'chatgpt','email':'TEST_ONLY_A@example.invalid','planType':'pro'}}
    elif method == 'account/rateLimits/read':
        print(json.dumps({'method':'TEST_ONLY_notification','params':{}}),flush=True)
        result = {'accountId':'TEST_ONLY_A','ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':25,'windowDurationMins':15,'resetsAt':1791856800}}}
    else:
        raise RuntimeError('TEST_ONLY unexpected method')
    print(json.dumps({'id':request['id'],'result':result}),flush=True)
"#;
// A concurrent fork can inherit another fixture's writable script descriptor
// until exec, even though fs::write closes it in the parent. Exclude forks while
// writing fixtures, and keep the lock through spawn. RPC and cleanup stay parallel.
static FIXTURE_LAUNCH: Mutex<()> = Mutex::new(());
fn fixture(script: &str) -> (tempfile::TempDir, PathBuf, StdioRpc) {
    let (root, profile, transport, _started) =
        fixture_with_timeout(script, Duration::from_secs(24));
    (root, profile, transport)
}
fn fixture_with_timeout(
    script: &str,
    timeout: Duration,
) -> (tempfile::TempDir, PathBuf, StdioRpc, Instant) {
    let _guard = FIXTURE_LAUNCH.lock().unwrap();
    let root = tempfile::tempdir().unwrap();
    let cli = root.path().join("TEST_ONLY CLI with spaces");
    let profile = root.path().join("TEST_ONLY profile");
    fs::create_dir(&profile).unwrap();
    fs::write(&cli, script).unwrap();
    fs::set_permissions(&cli, fs::Permissions::from_mode(0o700)).unwrap();
    let started = Instant::now();
    let transport = StdioRpc::launch_with_timeout(&cli, &profile, true, timeout).unwrap();
    (root, profile, transport, started)
}
#[test]
fn fake_stdio_handshake_notifications_argv_and_profile_are_bounded() {
    let (_root, profile, mut transport) = fixture(SCRIPT);
    let snapshot = codex::query(
        &mut transport,
        "TEST_ONLY_PROFILE",
        true,
        chrono::Utc::now(),
    )
    .unwrap()
    .snapshot;
    assert_eq!(snapshot.status, Status::Ok);
    assert_eq!(snapshot.windows[0].remaining_percent, Some(75.));
    drop(transport);
    let log = fs::read_to_string(profile.join("TEST_ONLY_requests.jsonl")).unwrap();
    let requests: Vec<serde_json::Value> = log
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert_eq!(
        requests
            .iter()
            .filter_map(|v| v["method"].as_str())
            .collect::<Vec<_>>(),
        [
            "initialize",
            "initialized",
            "account/read",
            "account/rateLimits/read",
            "account/read"
        ]
    );
    assert!(requests
        .iter()
        .filter(|v| v["method"] == "account/read")
        .all(|v| v["params"]["refreshToken"] == false));
    assert!(!log.contains("login"));
    assert!(!log.contains("thread"));
    assert!(!log.contains("reset"));
}
#[test]
fn account_notifications_invalidate_snapshot_and_external_refresh_is_blocked() {
    let changed=SCRIPT.replace("print(json.dumps({'method':'TEST_ONLY_notification','params':{}}),flush=True)",
        "print(json.dumps({'method':'account/updated','params':{'authMode':'chatgpt'}}),flush=True)");
    let (_root, _profile, mut t) = fixture(&changed);
    let result = codex::query(&mut t, "TEST_ONLY", true, chrono::Utc::now()).unwrap();
    assert!(result.binding.is_none());
    assert!(result.snapshot.windows.is_empty());
    drop(t);
    let refresh=SCRIPT.replace("result = {'userAgent':'TEST_ONLY_CLI/1.0'}","print(json.dumps({'method':'account/chatgptAuthTokens/refresh','id':99,'params':{}}),flush=True)\n        result = {}");
    let (_root, _profile, mut t) = fixture(&refresh);
    assert_eq!(
        codex::query(&mut t, "TEST_ONLY", true, chrono::Utc::now())
            .unwrap()
            .snapshot
            .status,
        Status::Expired
    );
}
#[test]
fn malformed_stdout_oversized_line_and_wrong_response_id_fail_closed() {
    for script in [
        "#!/usr/bin/python3\nimport sys\nsys.stdin.readline()\nprint('TEST_ONLY not json',flush=True)\n",
        "#!/usr/bin/python3\nimport sys\nsys.stdin.readline()\nprint('x'*300000,flush=True)\n",
        "#!/usr/bin/python3\nimport sys\nsys.stdin.readline()\nprint('{\"id\":999,\"result\":{}}',flush=True)\n",
    ]{
        let(_root,_profile,mut t)=fixture(script);
        assert_eq!(t.request("initialize",json!({})).unwrap_err().status,Status::ProtocolError);
    }
}
#[test]
fn timeout_kills_fake_process_tree_and_does_not_wait_for_inherited_stdout() {
    let script="#!/usr/bin/python3\nimport subprocess,time\nsubprocess.Popen(['/usr/bin/python3','-c','import time; time.sleep(30)'])\ntime.sleep(30)\n";
    let (_root, _profile, mut t, start) = fixture_with_timeout(script, Duration::from_millis(200));
    assert_eq!(
        t.request("initialize", json!({})).unwrap_err().status,
        Status::Unavailable
    );
    drop(t);
    assert!(start.elapsed() < Duration::from_secs(3));
}
#[test]
fn consent_precedes_any_process_launch_or_file_access() {
    let path = std::path::Path::new("/TEST_ONLY/nonexistent");
    assert!(matches!(StdioRpc::launch(path,path,false),Err(e) if e.code=="CONFIRM_REQUIRED"));
}

#[test]
fn parallel_fixture_launches_complete_protocol() {
    let start = std::sync::Barrier::new(8);
    std::thread::scope(|scope| {
        for _ in 0..8 {
            scope.spawn(|| {
                start.wait();
                for _ in 0..8 {
                    let (_root, _profile, mut transport) = fixture(SCRIPT);
                    let response = transport.request("initialize", json!({})).unwrap();
                    assert_eq!(response["userAgent"], "TEST_ONLY_CLI/1.0");
                }
            });
        }
    });
}
