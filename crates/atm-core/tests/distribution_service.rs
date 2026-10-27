use atm_core::distribution::{source, Service};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs, path::Path};
use tempfile::TempDir;

fn write(root: &Path, path: &str, bytes: impl AsRef<[u8]>) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, bytes).unwrap();
}
fn json_write(root: &Path, path: &str, value: Value) {
    write(root, path, serde_json::to_vec_pretty(&value).unwrap());
}
fn update_plugin_identity(root: &Path) {
    let release = fs::read_to_string(root.join("VERSION"))
        .unwrap()
        .trim()
        .to_owned();
    let digest = source::plugin_content_identity(root, "maintenance", &release).unwrap();
    let version = format!("{release}+codex.{}", &digest[..16]);
    let plugin_path = "plugins/maintenance/.codex-plugin/plugin.json";
    let mut plugin: Value =
        serde_json::from_slice(&fs::read(root.join(plugin_path)).unwrap()).unwrap();
    plugin["version"] = json!(version);
    json_write(root, plugin_path, plugin);
    let bundle = json!({"algorithm":"sha256-canonical-plugin-tree-v1","releaseVersion":release,"plugins":[{"name":"maintenance","version":version,"contentSha256":digest}]});
    let bundle_digest = format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(&bundle).unwrap())
    );
    json_write(
        root,
        ".agents/plugins/distribution-identity.json",
        json!({"schemaVersion":1,"algorithm":"sha256-canonical-plugin-tree-v1","generationLength":16,"releaseVersion":release,"bundleIdentity":bundle_digest,"plugins":[{"name":"maintenance","versionAuthority":"release","version":version,"generation":&digest[..16],"contentSha256":digest}]}),
    );
}
fn fixture() -> TempDir {
    let dir = tempfile::Builder::new()
        .prefix("ATM 内容 source ")
        .tempdir()
        .unwrap();
    let root = dir.path();
    let version = "1.0.0+codex.aaaaaaaaaaaaaaaa";
    write(root, "VERSION", "1.0.0\n");
    write(root, "agents/global-instructions.md", "# Instructions\n");
    write(root, "agents/operating-principles.md", "# Principles\n");
    json_write(
        root,
        ".agents/harnesses/registry.json",
        serde_json::from_slice(include_bytes!("../../../policy/harnesses/registry.json")).unwrap(),
    );
    json_write(root, ".agents/harnesses/registry.schema.json", json!({}));
    json_write(
        root,
        ".agents/plugins/marketplace.json",
        json!({"name":"atm-harness","plugins":[{"name":"maintenance","source":{"source":"local","path":"./plugins/maintenance"}}]}),
    );
    json_write(
        root,
        ".agents/plugins/install-manifest.json",
        json!({"harness":"codex","marketplace":"atm-harness","plugins":[{"name":"maintenance","install":true,"check":true}]}),
    );
    json_write(
        root,
        ".agents/plugins/distribution-identity.json",
        json!({"schemaVersion":1,"releaseVersion":"1.0.0","plugins":[{"name":"maintenance","version":version,"generation":"aaaaaaaaaaaaaaaa","contentSha256":"a".repeat(64)}]}),
    );
    json_write(
        root,
        "plugins/maintenance/.codex-plugin/plugin.json",
        json!({"name":"maintenance","version":version,"skills":"./skills/"}),
    );
    json_write(
        root,
        "plugins/maintenance/.codex-plugin/skill-watcher.json",
        json!({"schema_version":1,"skills":{"watcher:housekeeping":{"role":"specialized","aliases":["clean"]}},"legacy_names":{"old:cleanup":"watcher:housekeeping"}}),
    );
    write(
        root,
        "plugins/maintenance/skills/housekeeping/SKILL.md",
        "---\nname: housekeeping\ndescription: Maintain workspace\n---\nUse this skill.\n",
    );
    json_write(
        root,
        "distribution-manifest.json",
        json!({"schemaVersion":1,"product":"atm-harness-distribution","algorithm":"sha256-atm-distribution-v1","releaseVersion":"1.0.0","packages":[{"name":"maintenance","path":"plugins/maintenance","kind":"skills"}],"files":[],"runtimeGroups":[],"runtimeBindings":{},"historicalIdentities":{"maintenance:housekeeping":"watcher:housekeeping"}}),
    );
    update_plugin_identity(root);
    source::seal(root).unwrap();
    dir
}
fn environment() -> (TempDir, Service, std::path::PathBuf, std::path::PathBuf) {
    let temp = tempfile::Builder::new()
        .prefix("TEST_ONLY ATM 用户 path ")
        .tempdir()
        .unwrap();
    let home = temp.path().join("manager home");
    let user = temp.path().join("user home");
    let skills = user.join(".zcode/skills");
    let service = Service::new(home.clone(), user).unwrap();
    (temp, service, home, skills)
}
fn targets() -> Vec<String> {
    vec!["zcode".to_owned()]
}
fn skill_path(skills: &Path) -> std::path::PathBuf {
    skills.join("housekeeping/SKILL.md")
}
#[test]
fn text_lifecycle_is_rust_only_and_preserves_user_content() {
    let content = fixture();
    let (_temp, service, home, skills) = environment();
    assert!(service.status().unwrap()["manager"].is_null());
    service.bootstrap(content.path(), false).unwrap();
    let preview = service.plan("install", &targets()).unwrap();
    assert!(!skills.exists(), "preview must not create client files");
    service.apply(preview).unwrap();
    let old = fs::read(skill_path(&skills)).unwrap();
    assert!(skills.parent().unwrap().join("AGENTS.md").is_file());
    let status = service.status().unwrap();
    assert_eq!(status["desiredHarnesses"], json!(["zcode"]));
    assert_eq!(status["runtimes"], json!({}));
    assert_eq!(status["hooksEnabled"], false);
    write(content.path(),"plugins/maintenance/skills/housekeeping/SKILL.md","---\nname: housekeeping\ndescription: Maintain workspace\n---\nUpdated trusted instructions.\n");
    update_plugin_identity(content.path());
    source::seal(content.path()).unwrap();
    service.bootstrap(content.path(), false).unwrap();
    assert_eq!(
        fs::read(skill_path(&skills)).unwrap(),
        old,
        "cache sync is separate from client apply"
    );
    service.execute("refresh", &targets()).unwrap();
    assert!(fs::read_to_string(skill_path(&skills))
        .unwrap()
        .contains("Updated trusted instructions."));
    assert_eq!(service.diagnose().unwrap()["passed"], true);
    write(&skills, "user-skill/SKILL.md", "user-owned");
    write(&home, "logs/user-log.jsonl", "historical user event\n");
    write(&home, "reports/user-report.txt", "user-owned report\n");
    service.execute("remove", &targets()).unwrap();
    assert!(!skill_path(&skills).exists());
    assert_eq!(
        fs::read(skills.join("user-skill/SKILL.md")).unwrap(),
        b"user-owned"
    );
    assert_eq!(
        fs::read(home.join("logs/user-log.jsonl")).unwrap(),
        b"historical user event\n"
    );
    assert!(home.join("reports/user-report.txt").exists());
    assert_eq!(service.status().unwrap()["desiredHarnesses"], json!([]));
    service.execute("remove", &targets()).unwrap();
}
#[test]
fn complete_cache_runs_offline_and_missing_cache_never_falls_back_to_python() {
    let content = fixture();
    let (_temp, service, home, skills) = environment();
    let bundle = source::load(content.path()).unwrap();
    service.bootstrap(content.path(), false).unwrap();
    drop(content);
    service.execute("install", &targets()).unwrap();
    service.execute("refresh", &targets()).unwrap();
    fs::remove_file(
        home.join("cache/content")
            .join(&bundle.identity)
            .join("plugins/maintenance/skills/housekeeping/SKILL.md"),
    )
    .unwrap();
    assert_eq!(
        service.execute("refresh", &targets()).unwrap_err().code,
        "HARNESS_SOURCE_INVALID"
    );
    assert_eq!(
        service.status().unwrap()["observation"],
        "recorded-state-only"
    );
    assert_eq!(service.diagnose().unwrap()["passed"], false);
    service.execute("remove", &targets()).unwrap();
    assert!(!skill_path(&skills).exists());
}
#[test]
fn user_modifications_and_same_name_foreign_files_stop_before_mutation() {
    let content = fixture();
    let (_temp, service, _home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    write(&skills, "housekeeping/SKILL.md", "foreign");
    assert_eq!(
        service.execute("install", &targets()).unwrap_err().code,
        "HARNESS_CONFLICT"
    );
    assert!(!skills.parent().unwrap().join("AGENTS.md").exists());
    assert_eq!(service.status().unwrap()["desiredHarnesses"], json!([]));
    fs::remove_file(skill_path(&skills)).unwrap();
    fs::remove_dir(skills.join("housekeeping")).unwrap();
    service.execute("install", &targets()).unwrap();
    let preview = service.plan("refresh", &targets()).unwrap();
    fs::write(skill_path(&skills), "user edit after preview").unwrap();
    assert_eq!(service.apply(preview).unwrap_err().code, "HARNESS_CONFLICT");
    assert_eq!(
        service.execute("remove", &targets()).unwrap_err().code,
        "HARNESS_CONFLICT"
    );
    assert_eq!(
        fs::read_to_string(skill_path(&skills)).unwrap(),
        "user edit after preview"
    );
}
#[test]
fn one_physical_target_cannot_gain_competing_receipts() {
    let content = fixture();
    let (temp, _service, home, _skills) = environment();
    let shared = temp.path().join("shared client/skills");
    let roots = std::collections::BTreeMap::from([
        ("copilot-cli".to_owned(), shared.clone()),
        ("vscode".to_owned(), shared),
    ]);
    let service = Service::new(home, temp.path().join("user"))
        .unwrap()
        .with_target_roots(roots);
    service.bootstrap(content.path(), false).unwrap();
    let both = vec!["copilot-cli".to_owned(), "vscode".to_owned()];
    assert_eq!(
        service.plan("install", &both).unwrap_err().code,
        "HARNESS_OWNER_CONFLICT"
    );
    service
        .execute("install", &["copilot-cli".to_owned()])
        .unwrap();
    assert_eq!(
        service
            .plan("install", &["vscode".to_owned()])
            .unwrap_err()
            .code,
        "HARNESS_OWNER_CONFLICT"
    );
    assert_eq!(
        service.status().unwrap()["desiredHarnesses"],
        json!(["copilot-cli"])
    );
}
fn simulated_pending(home: &Path, path: &Path, before: &[u8], after: &[u8]) {
    let node = |bytes: &[u8]| json!({"kind":"file","value":bytes});
    json_write(
        home,
        "state/rust-journal.json",
        json!({"schemaVersion":2,"product":"atm-harness","transactionId":"00000000-0000-4000-8000-000000000001","committed":false,"changes":[{"path":path,"before":node(before),"after":node(after)}]}),
    );
    fs::write(path, after).unwrap();
}
#[test]
fn interrupted_apply_is_visible_and_explicit_recovery_restores_previous_bytes() {
    let content = fixture();
    let (_temp, service, home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let path = skill_path(&skills);
    let old = fs::read(&path).unwrap();
    simulated_pending(&home, &path, &old, b"partial new payload");
    assert_eq!(service.status().unwrap()["manager"]["status"], "degraded");
    assert_eq!(service.status().unwrap()["operation"]["command"], "recover");
    assert!(service.execute("refresh", &targets()).is_err());
    service.recover().unwrap();
    assert_eq!(fs::read(&path).unwrap(), old);
    assert!(!home.join("state/rust-journal.json").exists());
    assert_eq!(service.status().unwrap()["manager"]["status"], "ready");
}
#[test]
fn recovery_preserves_post_interruption_edits_and_retains_evidence() {
    let content = fixture();
    let (_temp, service, home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let path = skill_path(&skills);
    let old = fs::read(&path).unwrap();
    simulated_pending(&home, &path, &old, b"partial new payload");
    fs::write(&path, b"user changed after crash").unwrap();
    assert_eq!(service.recover().unwrap_err().code, "HARNESS_CONFLICT");
    assert_eq!(fs::read(&path).unwrap(), b"user changed after crash");
    assert!(home.join("state/rust-journal.json").exists());
}
#[test]
fn held_native_lock_fails_without_changing_client_files() {
    let content = fixture();
    let (_temp, service, home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(home.join("state/manager.lock"))
        .unwrap();
    lock.try_lock().unwrap();
    assert_eq!(
        service.execute("install", &targets()).unwrap_err().code,
        "HARNESS_BUSY"
    );
    assert!(!skills.exists());
    drop(lock);
    service.execute("install", &targets()).unwrap();
}
#[test]
#[cfg(windows)]
fn local_ownership_guard_recognizes_verbatim_and_case_path_aliases() {
    let content = fixture();
    let (_temp, service, home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let owned = skills.join("housekeeping");
    let verbatim = owned.canonicalize().unwrap();
    assert!(atm_core::distribution::owns_path(&home, &verbatim));
    let case_alias = owned.parent().unwrap().join("HOUSEKEEPING");
    assert!(atm_core::distribution::owns_path(&home, &case_alias));
    assert!(!atm_core::distribution::owns_path(
        &home,
        &skills.join("unrelated-user-skill")
    ));
}

#[test]
fn local_skill_commands_cannot_take_over_distribution_owned_plain_copies() {
    let content = fixture();
    let (temp, service, home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let user = skills.parent().unwrap().parent().unwrap().to_path_buf();
    let local = atm_core::skills::SkillsService::new(user, temp.path().join("local-trash"))
        .with_manager_home(Some(home));
    let before = fs::read(skill_path(&skills)).unwrap();
    assert_eq!(
        local.uninstall("zcode", "housekeeping").unwrap_err().code,
        "SKILLS_ENGINE_LOCKED"
    );
    assert_eq!(
        local
            .copy_to("zcode", "housekeeping", "claude-code")
            .unwrap_err()
            .code,
        "SKILLS_ENGINE_LOCKED"
    );
    assert_eq!(fs::read(skill_path(&skills)).unwrap(), before);
}

#[test]
fn cache_sync_does_not_relabel_the_previously_installed_client_release() {
    let content = fixture();
    let (_temp, service, _home, _skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let before = service.status().unwrap();
    write(content.path(), "VERSION", "1.1.0\n");
    let path = content.path().join("distribution-manifest.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    manifest["releaseVersion"] = json!("1.1.0");
    fs::write(path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    update_plugin_identity(content.path());
    source::seal(content.path()).unwrap();
    service.bootstrap(content.path(), false).unwrap();
    let synced = service.status().unwrap();
    assert_eq!(synced["manager"]["releaseVersion"], "1.1.0");
    assert_eq!(
        synced["harnessReceipts"]["zcode"][0]["releaseVersion"],
        "1.0.0"
    );
    assert_eq!(
        synced["harnessReceipts"]["zcode"][0]["sourceIdentity"],
        before["harnessReceipts"]["zcode"][0]["sourceIdentity"]
    );
    service.execute("refresh", &targets()).unwrap();
    assert_eq!(
        service.status().unwrap()["harnessReceipts"]["zcode"][0]["releaseVersion"],
        "1.1.0"
    );
}
#[test]
fn cached_catalog_drift_blocks_sync_without_overwriting_the_changed_snapshot() {
    let content = fixture();
    let (_temp, service, home, _skills) = environment();
    let bundle = source::load(content.path()).unwrap();
    service.bootstrap(content.path(), false).unwrap();
    let path = home
        .join("cache/content")
        .join(bundle.identity)
        .join("canonical-catalog.json");
    fs::write(&path, b"{\"changed\":true}").unwrap();
    assert_eq!(
        service.bootstrap(content.path(), false).unwrap_err().code,
        "HARNESS_STATE_INVALID"
    );
    assert_eq!(fs::read(path).unwrap(), b"{\"changed\":true}");
}
#[test]
fn unrelated_local_skills_can_coexist_with_managed_distribution_files() {
    let content = fixture();
    let (temp, service, home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let user = skills.parent().unwrap().parent().unwrap().to_path_buf();
    let local = atm_core::skills::SkillsService::new(user, temp.path().join("local-trash"))
        .with_manager_home(Some(home));
    let source = temp.path().join("personal source");
    write(
        &source,
        "SKILL.md",
        "---\nname: personal-note\ndescription: TEST_ONLY local\n---\nPersonal notes.\n",
    );
    local.install(&source, "zcode", "personal-note").unwrap();
    assert!(skills.join("personal-note/SKILL.md").is_file());
    local.uninstall("zcode", "personal-note").unwrap();
    assert!(skill_path(&skills).is_file());
}

#[test]
fn declared_empty_payload_directories_are_owned_without_erasing_user_files() {
    let content = fixture();
    fs::create_dir_all(
        content
            .path()
            .join("plugins/maintenance/skills/housekeeping/empty"),
    )
    .unwrap();
    update_plugin_identity(content.path());
    source::seal(content.path()).unwrap();
    let (_temp, service, _home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let empty = skills.join("housekeeping/empty");
    assert!(empty.is_dir());
    fs::write(empty.join("user-note"), "keep").unwrap();
    assert!(service.execute("remove", &targets()).is_err());
    assert_eq!(fs::read_to_string(empty.join("user-note")).unwrap(), "keep");
    fs::remove_file(empty.join("user-note")).unwrap();
    service.execute("remove", &targets()).unwrap();
    assert!(!empty.exists());
}

#[test]
fn same_named_foreign_directory_is_not_adopted_and_uninstall_prunes_owned_slots() {
    let content = fixture();
    let (_temp, service, _home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    fs::create_dir_all(skills.join("housekeeping")).unwrap();
    fs::write(skills.join("housekeeping/user.txt"), "foreign").unwrap();
    assert!(service.execute("install", &targets()).is_err());
    assert!(!skill_path(&skills).exists());
    fs::remove_file(skills.join("housekeeping/user.txt")).unwrap();
    fs::remove_dir(skills.join("housekeeping")).unwrap();
    service.execute("install", &targets()).unwrap();
    service.execute("remove", &targets()).unwrap();
    assert!(!skills.join("housekeeping").exists());
    service.execute("install", &targets()).unwrap();
    fs::write(skills.join("housekeeping/user.txt"), "retained").unwrap();
    fs::create_dir(skills.join("housekeeping/user-empty")).unwrap();
    service.execute("remove", &targets()).unwrap();
    assert_eq!(
        fs::read_to_string(skills.join("housekeeping/user.txt")).unwrap(),
        "retained"
    );
    assert!(skills.join("housekeeping/user-empty").is_dir());
}

#[test]
fn written_receipt_conforms_to_published_contract() {
    let content = fixture();
    let (_temp, service, home, _skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let schema: Value = serde_json::from_slice(include_bytes!(
        "../../../policy/distribution/receipt.schema.json"
    ))
    .unwrap();
    let state: Value =
        serde_json::from_slice(&fs::read(home.join("state/distribution.json")).unwrap()).unwrap();
    assert!(jsonschema::validator_for(&schema).unwrap().is_valid(&state));
}

#[test]
fn update_populates_previously_empty_owned_directory_without_dropping_new_files() {
    let content = fixture();
    let source_empty = content
        .path()
        .join("plugins/maintenance/skills/housekeeping/empty");
    fs::create_dir_all(&source_empty).unwrap();
    update_plugin_identity(content.path());
    source::seal(content.path()).unwrap();
    let (_temp, service, _home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    fs::write(source_empty.join("new.txt"), "new content").unwrap();
    update_plugin_identity(content.path());
    source::seal(content.path()).unwrap();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("refresh", &targets()).unwrap();
    assert_eq!(
        fs::read_to_string(skills.join("housekeeping/empty/new.txt")).unwrap(),
        "new content"
    );
    assert_eq!(service.diagnose().unwrap()["passed"], true);
    service.execute("remove", &targets()).unwrap();
    assert!(!skills.join("housekeeping").exists());
}

#[cfg(unix)]
#[test]
fn mixed_skill_update_and_removal_preserve_private_user_file_permissions() {
    use std::os::unix::fs::PermissionsExt;
    let content = fixture();
    let (_temp, service, _home, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let private = skills.join("housekeeping/private.txt");
    fs::write(&private, "TEST_ONLY private").unwrap();
    fs::set_permissions(&private, fs::Permissions::from_mode(0o600)).unwrap();
    service.execute("refresh", &targets()).unwrap();
    assert_eq!(
        fs::metadata(&private).unwrap().permissions().mode() & 0o777,
        0o600
    );
    service.execute("remove", &targets()).unwrap();
    assert_eq!(
        fs::metadata(&private).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[test]
fn codex_cache_extra_content_is_diagnosed_and_never_adopted_on_refresh() {
    let content = fixture();
    let (_temp, service, home, _skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &["codex".into()]).unwrap();
    let state: Value =
        serde_json::from_slice(&fs::read(home.join("state/distribution.json")).unwrap()).unwrap();
    let receipt = state["receipts"]
        .as_object()
        .unwrap()
        .values()
        .next()
        .unwrap();
    let manifest = receipt["files"]
        .as_object()
        .unwrap()
        .keys()
        .find(|p| Path::new(p).ends_with(".codex-plugin/plugin.json"))
        .unwrap();
    let version = Path::new(manifest).parent().unwrap().parent().unwrap();
    let extra = version.join("foreign.txt");
    fs::write(&extra, "user content").unwrap();
    assert_eq!(service.diagnose().unwrap()["passed"], false);
    assert!(service.execute("refresh", &["codex".into()]).is_err());
    service.execute("remove", &["codex".into()]).unwrap();
    assert_eq!(fs::read_to_string(extra).unwrap(), "user content");
}

#[test]
fn retired_hooks_refuse_enable_and_require_removal_before_content_sync() {
    let source = fixture();
    let (_temp, service, home, _skills) = environment();
    for dry_run in [false, true] {
        assert_eq!(
            service.hooks(true, dry_run).unwrap_err().code,
            "HARNESS_HOOK_RETIRED"
        );
        assert!(!home.exists());
    }
    service.bootstrap(source.path(), false).unwrap();
    service.execute("install", &["codex".into()]).unwrap();
    // Real hook owners use the service's normalized root. fs::canonicalize
    // alone would instead put a verbatim Windows prefix into this fixture.
    let status = service.status().unwrap();
    let target = Path::new(
        status["harnessReceipts"]["codex"][0]["root"]
            .as_str()
            .unwrap(),
    )
    .join("hooks.json");
    let groups:std::collections::BTreeMap<_,_>=atm_core::distribution::hooks::EVENTS.into_iter().map(|event|(
        event.to_owned(),json!({"hooks":[{"type":"command","command":"TEST_ONLY old collector","statusMessage":format!("Watcher skill: observe {event}")}]}),
    )).collect();
    let mut config = json!({"user":true,"hooks":{}});
    for (event, group) in &groups {
        config["hooks"][event] = json!([group]);
    }
    write(
        target.parent().unwrap(),
        "hooks.json",
        serde_json::to_vec(&config).unwrap(),
    );
    let state_path = home.join("state/distribution.json");
    let mut state: Value = serde_json::from_slice(&fs::read(&state_path).unwrap()).unwrap();
    state["hooks"] = json!({"schemaVersion":1,"owner":"atm-harness:watcher","target":target,"groups":groups,
        "runtime":{"id":"watcher","identity":"old","root":home.join("missing-venv"),"python":home.join("missing-venv/bin/python"),"external":false},
        "bundleRoot":home.join("cache/content").join(state["sourceIdentity"].as_str().unwrap()),"hooksPreexisted":false,"preservedEmptyEvents":[]});
    fs::write(&state_path, serde_json::to_vec_pretty(&state).unwrap()).unwrap();
    write(&home, "logs/history.jsonl", b"keep old evidence\n");
    let before = fs::read(&state_path).unwrap();
    assert_eq!(
        service.bootstrap(source.path(), false).unwrap_err().code,
        "HARNESS_HOOK_RETIREMENT_REQUIRED"
    );
    assert_eq!(fs::read(&state_path).unwrap(), before);
    let check = service.check_hooks().unwrap();
    assert_eq!(check["passed"], false);
    assert_eq!(check["ownershipVerified"], true);
    assert_eq!(check["issue"], "retired-hook-enabled");
    service.hooks(false, true).unwrap();
    assert_eq!(fs::read(&state_path).unwrap(), before);
    service.hooks(false, false).unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(target).unwrap()).unwrap(),
        json!({"user":true})
    );
    service.bootstrap(source.path(), false).unwrap();
    assert_eq!(service.status().unwrap()["hooksEnabled"], false);
    assert_eq!(
        fs::read(home.join("logs/history.jsonl")).unwrap(),
        b"keep old evidence\n"
    );
}

#[test]
fn manager_relocation_preserves_history_and_has_one_owner_with_stable_client_plan() {
    let content = fixture();
    let (temp, service, old, _) = environment();
    let user = temp.path().join("user home");
    let targets = vec!["claude-code".into(), "codex".into()];
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets).unwrap();
    write(&old, "historical/log.jsonl", b"keep historical evidence\n");
    write(
        &user,
        ".codex/hooks.json",
        b"{\"hooks\":{\"Other\":[{\"user\":true}]}}\n",
    );
    let old_receipt = fs::read(old.join("state/distribution.json")).unwrap();
    // A manager move may also select the newly published content release.
    fs::write(content.path().join("VERSION"), "1.0.1\n").unwrap();
    let manifest_path = content.path().join("distribution-manifest.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
    manifest["releaseVersion"] = json!("1.0.1");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    update_plugin_identity(content.path());
    source::seal(content.path()).unwrap();
    let new = user.join(".atm");
    let plan = service.plan_relocation(&new, content.path()).unwrap();
    assert!(!new.exists());
    assert_eq!(plan.targets, targets);
    assert!(plan.runtime_groups.is_empty());
    let result = service.relocate(plan, None, true).unwrap();
    assert_eq!(result["migrated"], true);
    assert!(!old.join("state/distribution.json").exists());
    assert!(old.join("state/relocated.json").is_file());
    assert_eq!(
        fs::read(old.join("historical/log.jsonl")).unwrap(),
        b"keep historical evidence\n"
    );
    assert_eq!(
        service.bootstrap(content.path(), false).unwrap_err().code,
        "HARNESS_HOME_RELOCATED"
    );
    let owner = Service::new(new.clone(), user.clone()).unwrap();
    assert_eq!(owner.diagnose().unwrap()["passed"], true);
    assert!(owner.plan("refresh", &targets).unwrap().files.is_empty());
    assert_eq!(owner.status().unwrap()["hooksEnabled"], false);
    let record: Value =
        serde_json::from_slice(&fs::read(new.join("state/relocation.json")).unwrap()).unwrap();
    assert_eq!(record["completed"], true);
    assert_eq!(
        record["previous"],
        serde_json::from_slice::<Value>(&old_receipt).unwrap()
    );
    #[cfg(unix)]
    {
        let previous: Value = serde_json::from_slice(&old_receipt).unwrap();
        let old_plugin_file = previous["receipts"]
            .as_object()
            .unwrap()
            .values()
            .flat_map(|r| r["files"].as_object().unwrap().keys())
            .find(|p| p.ends_with("/.codex-plugin/plugin.json"))
            .unwrap();
        let old_plugin_root = Path::new(old_plugin_file)
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        assert!(!old_plugin_root.exists());
        let foreign = temp.path().join("user cache");
        fs::create_dir(&foreign).unwrap();
        std::os::unix::fs::symlink(&foreign, old_plugin_root).unwrap();
        assert!(
            owner.status().is_ok(),
            "history is not the current ownership authority"
        );
    }
    assert!(!user.join(".openclaw").exists());
    assert_eq!(
        fs::read(user.join(".codex/hooks.json")).unwrap(),
        b"{\"hooks\":{\"Other\":[{\"user\":true}]}}\n"
    );
    // Archiving the old home after acceptance must not make a later recovery
    // command recreate it. Retained recovery history belongs to the new owner.
    fs::rename(&old, temp.path().join("archive")).unwrap();
    owner.recover().unwrap();
    assert!(!old.exists());
    assert_eq!(
        service.bootstrap(content.path(), false).unwrap_err().code,
        "HARNESS_HOME_RELOCATED"
    );
    assert!(service.recover().is_err());
    assert!(!old.exists());
}

#[test]
fn relocation_refuses_existing_destinations_edits_and_preview_apply_races() {
    let content = fixture();
    let (temp, service, old, skills) = environment();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let new = temp.path().join("destination");
    let preview = service.plan_relocation(&new, content.path()).unwrap();
    write(&new, "user.txt", b"keep me");
    assert!(service.relocate(preview, None, true).is_err());
    assert!(service.plan_relocation(&new, content.path()).is_err());
    assert_eq!(fs::read(new.join("user.txt")).unwrap(), b"keep me");
    assert!(old.join("state/distribution.json").is_file());
    let second = temp.path().join("second destination");
    let preview = service.plan_relocation(&second, content.path()).unwrap();
    fs::write(skill_path(&skills), b"user edit").unwrap();
    assert!(service.relocate(preview, None, true).is_err());
    assert_eq!(fs::read(skill_path(&skills)).unwrap(), b"user edit");
    assert!(old.join("state/distribution.json").is_file());
    assert!(!old.join("state/relocated.json").exists());
    assert!(!second.join("state/distribution.json").exists());
    let prepared = Service::new(second.clone(), temp.path().join("user home")).unwrap();
    assert_eq!(
        prepared.bootstrap(content.path(), false).unwrap_err().code,
        "HARNESS_RELOCATION_PENDING"
    );
    assert_eq!(prepared.recover().unwrap()["activeHome"], json!(old));
    assert!(!second.join("state/distribution.json").exists());
    assert!(service.plan_relocation(&second, content.path()).is_err());
}

#[cfg(unix)]
#[test]
fn relocation_rebuilds_selected_runtimes_at_final_paths_without_moving_old_environments() {
    use std::os::unix::fs::PermissionsExt;
    let content = fixture();
    let manifest_path = content.path().join("distribution-manifest.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
    manifest["runtimeGroups"] =
        json!([{"id":"workflow","minimumPython":[3,11],"imports":[],"requirementsLock":null}]);
    fs::write(manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    source::seal(content.path()).unwrap();
    let (temp, service, old, _) = environment();
    let python = temp.path().join("test-only-python");
    fs::write(&python, r#"#!/bin/sh
if [ "$3" = "-m" ] && [ "$4" = "venv" ]; then
  /bin/mkdir -p "$5/bin"
  /bin/cp "$0" "$5/bin/python"
  /bin/chmod 755 "$5/bin/python"
  /usr/bin/printf 'home = /fake/base\n' > "$5/pyvenv.cfg"
  exit 0
fi
case "$0" in */bin/python) prefix=$(/usr/bin/dirname "$(/usr/bin/dirname "$0")");; *) prefix=/fake/base;; esac
/usr/bin/printf '{"version":[3,11],"prefix":"%s","basePrefix":"/fake/base","distributions":{},"modules":{}}\n' "$prefix"
"#).unwrap();
    fs::set_permissions(&python, fs::Permissions::from_mode(0o755)).unwrap();
    service.bootstrap(content.path(), false).unwrap();
    service.execute("install", &targets()).unwrap();
    let before = service
        .prepare_runtime("workflow", &python, None, true)
        .unwrap();
    let old_python = std::path::PathBuf::from(before["prepared"]["python"].as_str().unwrap());
    let destination = temp.path().join("new manager");
    let plan = service
        .plan_relocation(&destination, content.path())
        .unwrap();
    assert_eq!(plan.runtime_groups, vec!["workflow"]);
    assert_eq!(
        service.relocate(plan.clone(), None, true).unwrap_err().code,
        "HARNESS_PYTHON_REQUIRED"
    );
    assert!(!destination.exists());
    service.relocate(plan, Some(&python), true).unwrap();
    let owner = Service::new(destination.clone(), temp.path().join("user home")).unwrap();
    let status = owner.status().unwrap();
    let new_python =
        std::path::PathBuf::from(status["runtimes"]["workflow"]["python"].as_str().unwrap());
    assert!(new_python.starts_with(&destination));
    assert!(new_python.is_file());
    assert!(old_python.starts_with(&old));
    assert!(old_python.is_file());
    assert_ne!(new_python, old_python);
    assert!(owner.plan("refresh", &targets()).unwrap().files.is_empty());
    assert_eq!(status["hooksEnabled"], false);
}
