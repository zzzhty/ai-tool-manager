use atm_core::distribution::legacy::{inspect, inspect_targets};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};
use tempfile::TempDir;

fn write(path: &Path, bytes: impl AsRef<[u8]>) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, bytes).unwrap();
}
fn write_json(path: &Path, value: serde_json::Value) {
    write(path, serde_json::to_vec_pretty(&value).unwrap());
}
fn hash_source(root: &Path) -> String {
    fn walk(root: &Path, path: &Path, hash: &mut Sha256) {
        let mut entries = fs::read_dir(path)
            .unwrap()
            .map(Result::unwrap)
            .collect::<Vec<_>>();
        entries.sort_by_key(|entry| entry.file_name());
        for entry in &entries {
            if entry.file_type().unwrap().is_file() && entry.file_name() != ".atm-embedded.json" {
                let relative = entry
                    .path()
                    .strip_prefix(root)
                    .unwrap()
                    .to_str()
                    .unwrap()
                    .replace('\\', "/");
                let bytes = fs::read(entry.path()).unwrap();
                hash.update((relative.len() as u64).to_be_bytes());
                hash.update(relative.as_bytes());
                hash.update((bytes.len() as u64).to_be_bytes());
                hash.update(bytes);
            }
        }
        for entry in &entries {
            if entry.file_type().unwrap().is_dir() {
                walk(root, &entry.path(), hash);
            }
        }
    }
    let mut hash = Sha256::new();
    hash.update(b"atm-engine-content-v1\0");
    walk(root, root, &mut hash);
    format!("sha256:{:x}", hash.finalize())
}
struct Fixture {
    _temp: TempDir,
    home: PathBuf,
    target: PathBuf,
}
impl Fixture {
    fn new(installed: bool) -> Self {
        let temp = TempDir::new().unwrap();
        let home = temp.path().join("管理 Home");
        let target = temp.path().join("Fake User/.zcode");
        let repo = home.join("repo");
        write(
            &repo.join("scripts/engine.py"),
            b"# verified retired engine\n",
        );
        write(
            &repo.join("scripts/manager_state.py"),
            b"# verified state owner\n",
        );
        write(
            &repo.join("scripts/atm_bootstrap.py"),
            b"# verified bootstrap\n",
        );
        write(
            &repo.join("agents/global-instructions.md"),
            b"# ordinary source instructions\n",
        );
        write(
            &repo.join("plugins/workflow/skills/task/SKILL.md"),
            b"---\nname: task\n---\n# Task\n",
        );
        write_json(
            &repo.join(".agents/harnesses/registry.json"),
            json!({
                "sources":{"instructions":{"current":"agents/global-instructions.md"}},
                "harnesses":{"zcode":{"skills":{"driver":"directory-projection","relativePath":"skills"},"instructions":{"driver":"managed-file","relativePath":"AGENTS.md"}}}
            }),
        );
        let identity = hash_source(&repo);
        let revision = format!(
            "{:x}",
            Sha256::digest(format!("{identity}|1.1.0").as_bytes())
        );
        write_json(
            &repo.join(".atm-embedded.json"),
            json!({"sourceMode":"atm-embedded","engineIdentityAlgorithm":"atm-engine-content-v1","engineIdentity":identity,"embeddedVersion":"1.1.0","embeddedIdentity":"bundle-identity"}),
        );
        write_json(
            &home.join("state/manager.json"),
            json!({"schemaVersion":"2026-08-24","product":"atm-harness","status":"ready","repository":"https://github.com/zzzhty/ai-tooling-manager","revision":&revision[..40],"releaseVersion":"1.1.0","bundleIdentity":"bundle-identity","channel":"embedded"}),
        );
        write_json(
            &home.join("state/desired.json"),
            json!({"schemaVersion":"2026-08-24","harnesses":if installed {vec!["zcode"]}else{vec![]},"updatePolicy":{"channel":"stable"}}),
        );
        if installed {
            write_json(
                &home.join("state/harnesses/zcode.json"),
                json!({"schemaVersion":"2026-08-24","harness":"zcode","status":"ready","managerRevision":&revision[..40],"releaseVersion":"1.1.0","bundleIdentity":"bundle-identity","root":target,"updatedAt":"2026-10-26T00:00:00Z"}),
            );
        }
        Self {
            _temp: temp,
            home,
            target,
        }
    }
    fn roots(&self) -> BTreeMap<String, PathBuf> {
        BTreeMap::from([("zcode".into(), self.target.clone())])
    }
}

#[test]
fn handoff_is_read_only_preserves_receipts_and_logs_and_archives_exact_bytes() {
    let fixture = Fixture::new(false);
    write_json(
        &fixture.home.join("state/install.json"),
        json!({"product":"oh-my-harness","status":"ready","paths":{"home":fixture.home,"repo":fixture.home.join("repo"),"venv":fixture.home.join("venv")}}),
    );
    write(
        &fixture.home.join("logs/history.jsonl"),
        b"user immutable event\n",
    );
    write(
        &fixture.home.join("bootstrap/atm_bootstrap.py"),
        b"# verified bootstrap\n",
    );
    let initial = fs::read(fixture.home.join("state/install.json")).unwrap();
    let result = inspect(&fixture.home).unwrap().unwrap();
    assert!(result
        .retire
        .iter()
        .any(|file| file.path.ends_with("scripts/engine.py")));
    assert!(result
        .retire
        .iter()
        .any(|file| file.path.ends_with("state/manager.json")));
    assert!(!result
        .retire
        .iter()
        .any(|file| file.path.ends_with("install.json")));
    assert!(result
        .archives
        .iter()
        .any(|file| file.path.ends_with("install.json") && file.bytes == initial));
    assert!(result.archives.iter().all(|file| !file.path.exists()));
    assert_eq!(
        fs::read(fixture.home.join("state/install.json")).unwrap(),
        initial
    );
    assert_eq!(
        fs::read(fixture.home.join("logs/history.jsonl")).unwrap(),
        b"user immutable event\n"
    );
    assert!(fixture.home.join("repo/scripts/engine.py").exists());
}
#[test]
fn pending_legacy_journal_refuses_handoff_even_if_other_state_valid() {
    let fixture = Fixture::new(false);
    write_json(
        &fixture.home.join("state/operations/current.json"),
        json!({"phase":"switching"}),
    );
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_LEGACY_PENDING"
    );
}
#[test]
fn changed_old_source_and_partial_state_fail_closed() {
    let fixture = Fixture::new(false);
    write(
        &fixture.home.join("repo/scripts/engine.py"),
        b"user modification\n",
    );
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_LEGACY_CHANGED"
    );
    fs::remove_file(fixture.home.join("state/desired.json")).unwrap();
    assert!(inspect(&fixture.home).is_err());
}
#[test]
fn a_second_live_owner_is_never_adopted() {
    let fixture = Fixture::new(false);
    write_json(
        &fixture.home.join("state/distribution.json"),
        json!({"schemaVersion":1}),
    );
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_DUAL_OWNER"
    );
}
#[test]
fn root_receipt_is_not_a_write_authority_and_user_changes_are_preserved() {
    let fixture = Fixture::new(true);
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    assert!(inspect_targets(&fixture.home, &handoff, &BTreeMap::new()).is_err());
    write(
        &fixture.target.join("AGENTS.md"),
        b"user authored instructions\n",
    );
    assert_eq!(
        inspect_targets(&fixture.home, &handoff, &fixture.roots())
            .unwrap_err()
            .code,
        "HARNESS_LEGACY_CHANGED"
    );
    assert_eq!(
        fs::read(fixture.target.join("AGENTS.md")).unwrap(),
        b"user authored instructions\n"
    );
}
#[test]
fn ordinary_instruction_copy_requires_exact_verified_source_bytes() {
    let fixture = Fixture::new(true);
    write(
        &fixture.target.join("AGENTS.md"),
        b"# ordinary source instructions\n",
    );
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    let targets = inspect_targets(&fixture.home, &handoff, &fixture.roots()).unwrap();
    assert_eq!(targets.len(), 1);
    assert_eq!(targets[0].kind, "file");
    assert_eq!(
        targets[0].bytes.as_deref(),
        Some(b"# ordinary source instructions\n".as_slice())
    );
}
#[cfg(unix)]
#[test]
fn skill_link_proof_never_follows_a_foreign_destination_for_mutation() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::new(true);
    fs::create_dir_all(fixture.target.join("skills")).unwrap();
    let link = fixture.target.join("skills/task");
    symlink(
        fixture.home.join("repo/plugins/workflow/skills/task"),
        &link,
    )
    .unwrap();
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    let targets = inspect_targets(&fixture.home, &handoff, &fixture.roots()).unwrap();
    assert_eq!(targets.len(), 1);
    assert_eq!(targets[0].kind, "symlink");
    assert!(targets[0].files.contains_key("SKILL.md"));
    fs::remove_file(&link).unwrap();
    symlink(&fixture.home, &link).unwrap();
    assert!(inspect_targets(&fixture.home, &handoff, &fixture.roots()).is_err());
    assert!(fixture.home.join("state/manager.json").exists());
}
#[cfg(unix)]
#[test]
fn linked_state_or_repo_is_not_trusted() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::new(false);
    fs::rename(fixture.home.join("state"), fixture.home.join("old-state")).unwrap();
    symlink(fixture.home.join("old-state"), fixture.home.join("state")).unwrap();
    assert!(inspect(&fixture.home).is_err());
}
#[test]
fn initial_receipt_alone_cannot_reconstruct_current_ownership() {
    let temp = TempDir::new().unwrap();
    write_json(
        &temp.path().join("state/install.json"),
        json!({"product":"atm-harness","status":"ready"}),
    );
    assert_eq!(
        inspect(temp.path()).unwrap_err().code,
        "HARNESS_LEGACY_INCOMPLETE"
    );
}

fn reseal(fixture: &Fixture) {
    let identity = hash_source(&fixture.home.join("repo"));
    let revision = format!(
        "{:x}",
        Sha256::digest(format!("{identity}|1.1.0").as_bytes())
    );
    write_json(
        &fixture.home.join("repo/.atm-embedded.json"),
        json!({"sourceMode":"atm-embedded","engineIdentityAlgorithm":"atm-engine-content-v1","engineIdentity":identity,"embeddedVersion":"1.1.0","embeddedIdentity":"bundle-identity"}),
    );
    let path = fixture.home.join("state/manager.json");
    let mut manager: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    manager["revision"] = json!(&revision[..40]);
    write_json(&path, manager);
}
fn codex_fixture() -> Fixture {
    let fixture = Fixture::new(false);
    let repo = fixture.home.join("repo");
    write_json(
        &repo.join(".agents/harnesses/registry.json"),
        json!({"sources":{"instructions":{"current":"agents/global-instructions.md"}},"harnesses":{"codex":{"skills":{"driver":"codex-marketplace"},"instructions":{"driver":"managed-file","relativePath":"AGENTS.md"}}}}),
    );
    write_json(
        &repo.join(".agents/plugins/marketplace.json"),
        json!({"name":"atm-harness","plugins":[{"name":"workflow"}]}),
    );
    write_json(
        &repo.join(".agents/plugins/install-manifest.json"),
        json!({"marketplace":"atm-harness","plugins":[{"name":"workflow","install":true}]}),
    );
    write_json(
        &repo.join("plugins/workflow/.codex-plugin/plugin.json"),
        json!({"name":"workflow","version":"1.0.0+codex.0123456789abcdef"}),
    );
    write_json(
        &fixture.home.join("state/desired.json"),
        json!({"schemaVersion":"2026-08-24","harnesses":["codex"],"updatePolicy":{"channel":"stable"}}),
    );
    write_json(
        &fixture.home.join("state/harnesses/codex.json"),
        json!({"schemaVersion":"2026-08-24","harness":"codex","status":"ready","managerRevision":"recorded","releaseVersion":"1.1.0","bundleIdentity":"bundle-identity","root":fixture.target,"updatedAt":"2026-10-26T00:00:00Z"}),
    );
    let cache = fixture
        .target
        .join("plugins/cache/atm-harness/workflow/1.0.0+codex.0123456789abcdef");
    for path in [".codex-plugin/plugin.json", "skills/task/SKILL.md"] {
        write(
            &cache.join(path),
            fs::read(repo.join("plugins/workflow").join(path)).unwrap(),
        );
    }
    write(&fixture.target.join("config.toml"),format!("# retained user preference\nmodel = 'TEST_ONLY'\n\n[marketplaces.atm-harness]\nsource_type = 'local'\nsource = {:?}\n\n[plugins.'workflow@atm-harness']\nenabled = true\n",repo.to_string_lossy()));
    reseal(&fixture);
    fixture
}
#[test]
fn codex_cache_and_shared_config_have_separate_exact_ownership_evidence() {
    use atm_core::distribution::{adapters::legacy_codex_ownership, legacy::codex_evidence};
    let fixture = codex_fixture();
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    let roots = BTreeMap::from([("codex".into(), fixture.target.clone())]);
    let targets = inspect_targets(&fixture.home, &handoff, &roots).unwrap();
    assert_eq!(targets.len(), 1);
    assert_eq!(targets[0].kind, "directory");
    assert!(targets[0].files.contains_key("skills/task/SKILL.md"));
    let evidence = codex_evidence(&handoff, &fixture.target).unwrap().unwrap();
    let ownership = legacy_codex_ownership(
        &evidence.config_bytes,
        &evidence.marketplace,
        &evidence.source_root,
        &evidence.plugins,
    )
    .unwrap();
    assert_eq!(ownership["kind"], "codex-toml");
    let cache = fixture
        .target
        .join("plugins/cache/atm-harness/workflow/1.0.0+codex.0123456789abcdef");
    write(&cache.join("user-file.txt"), b"must preserve");
    assert!(inspect_targets(&fixture.home, &handoff, &roots).is_err());
    assert_eq!(
        fs::read(cache.join("user-file.txt")).unwrap(),
        b"must preserve"
    );
}
#[test]
fn hook_handoff_disables_only_exact_old_groups_and_preserves_user_entries() {
    use atm_core::distribution::legacy::hook_retirement;
    let fixture = Fixture::new(false);
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    // Temp paths deliberately contain spaces/Unicode, so every path is quoted
    // by the historical POSIX shlex quoting rule.
    #[cfg(not(windows))]
    let command = format!(
        "'{}' -B '{}' skill observe --repo-root '{}'",
        fixture.home.join("venv/bin/python").display(),
        fixture
            .home
            .join("repo/plugins/watcher/scripts/watcher")
            .display(),
        fixture.home.join("repo").display()
    );
    #[cfg(windows)]
    let command = format!(
        "\"{}\" -B \"{}\" skill observe --repo-root \"{}\"",
        fixture.home.join("venv/Scripts/python.exe").display(),
        fixture
            .home
            .join("repo/plugins/watcher/scripts/watcher")
            .display(),
        fixture.home.join("repo").display()
    );
    let owned = json!({"hooks":[{"type":"command","async":false,"command":command,"timeoutSec":10,"statusMessage":"Watcher skill: observe Stop"}]});
    let foreign = json!({"hooks":[{"type":"command","command":"TEST_ONLY_USER_COMMAND"}]});
    write_json(
        &fixture.target.join("hooks.json"),
        json!({"userField":true,"hooks":{"Stop":[owned,foreign.clone()],"Custom":[]}}),
    );
    let change = hook_retirement(&handoff, &fixture.target).unwrap().unwrap();
    let after: serde_json::Value = serde_json::from_slice(&change.after).unwrap();
    assert_eq!(after["hooks"]["Stop"], json!([foreign]));
    assert_eq!(after["hooks"]["Custom"], json!([]));
    assert_eq!(after["userField"], true);
    assert_eq!(fs::read(&change.path).unwrap(), change.before);
    let mut altered: serde_json::Value = serde_json::from_slice(&change.before).unwrap();
    altered["hooks"]["Stop"][0]["hooks"][0]["timeoutSec"] = json!(20);
    write_json(&change.path, altered);
    assert!(hook_retirement(&handoff, &fixture.target).is_err());
}

fn new_source(fixture: &Fixture) -> PathBuf {
    use atm_core::distribution::source;
    let root = fixture._temp.path().join("Rust Content Bundle");
    write(&root.join("VERSION"), b"2.0.0\n");
    write(
        &root.join("agents/global-instructions.md"),
        b"# New Rust-owned instructions\n",
    );
    let mut registry: serde_json::Value = serde_json::from_slice(
        &fs::read(fixture.home.join("repo/.agents/harnesses/registry.json")).unwrap(),
    )
    .unwrap();
    for (name, spec) in registry["harnesses"].as_object_mut().unwrap() {
        spec["instructions"]["shadowPaths"] = json!([]);
        if name == "codex" {
            spec["localSkillsPath"] = json!("skills");
            spec["skills"]["marketplacePath"] = json!(".agents/plugins/marketplace.json");
        }
    }
    write_json(&root.join(".agents/harnesses/registry.json"), registry);
    write_json(
        &root.join(".agents/harnesses/registry.schema.json"),
        json!({}),
    );
    write_json(
        &root.join(".agents/plugins/marketplace.json"),
        json!({"name":"atm-harness","plugins":[{"name":"workflow","source":{"source":"local","path":"./plugins/workflow"}}]}),
    );
    write_json(
        &root.join(".agents/plugins/install-manifest.json"),
        json!({"harness":"codex","marketplace":"atm-harness","plugins":[{"name":"workflow","install":true,"check":true}]}),
    );
    write_json(
        &root.join("plugins/workflow/.codex-plugin/plugin.json"),
        json!({"name":"workflow","version":"2.0.0+codex.aaaaaaaaaaaaaaaa","skills":"./skills/"}),
    );
    write(
        &root.join("plugins/workflow/skills/task/SKILL.md"),
        b"---\nname: task\ndescription: Test-only static skill\n---\nNew Rust-owned skill.\n",
    );
    write_json(
        &root.join("distribution-manifest.json"),
        json!({"schemaVersion":1,"product":"atm-harness-distribution","algorithm":"sha256-atm-distribution-v1","releaseVersion":"2.0.0","packages":[{"name":"workflow","path":"plugins/workflow","kind":"skills"}],"files":[],"runtimeGroups":[],"runtimeBindings":{},"historicalIdentities":{}}),
    );
    let digest = source::plugin_content_identity(&root, "workflow", "2.0.0").unwrap();
    let version = format!("2.0.0+codex.{}", &digest[..16]);
    write_json(
        &root.join("plugins/workflow/.codex-plugin/plugin.json"),
        json!({"name":"workflow","version":version,"skills":"./skills/"}),
    );
    let bundle = json!({"algorithm":"sha256-canonical-plugin-tree-v1","releaseVersion":"2.0.0","plugins":[{"name":"workflow","version":version,"contentSha256":digest}]});
    let bundle_digest = format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(&bundle).unwrap())
    );
    write_json(
        &root.join(".agents/plugins/distribution-identity.json"),
        json!({"schemaVersion":1,"algorithm":"sha256-canonical-plugin-tree-v1","generationLength":16,"releaseVersion":"2.0.0","bundleIdentity":bundle_digest,"plugins":[{"name":"workflow","versionAuthority":"release","version":version,"generation":&digest[..16],"contentSha256":digest}]}),
    );
    write(
        &root.join("agents/operating-principles.md"),
        b"# Fake operating principles\n",
    );
    source::seal(&root).unwrap();
    root
}
fn service(fixture: &Fixture, target: &str) -> atm_core::distribution::Service {
    atm_core::distribution::Service::new(
        fixture.home.clone(),
        fixture._temp.path().join("FAKE_USER"),
    )
    .unwrap()
    .with_target_roots(BTreeMap::from([(
        target.into(),
        fixture.target.join("skills"),
    )]))
}
#[cfg(unix)]
#[test]
fn service_adopts_once_without_dual_owner_then_refreshes_and_uninstalls() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::new(true);
    fs::create_dir_all(fixture.target.join("skills")).unwrap();
    symlink(
        fixture.home.join("repo/plugins/workflow/skills/task"),
        fixture.target.join("skills/task"),
    )
    .unwrap();
    write(
        &fixture.target.join("AGENTS.md"),
        b"# ordinary source instructions\n",
    );
    write_json(
        &fixture.home.join("state/install.json"),
        json!({"product":"oh-my-harness","status":"ready","paths":{"home":fixture.home,"repo":fixture.home.join("repo"),"venv":fixture.home.join("venv")}}),
    );
    write(
        &fixture.home.join("logs/history.jsonl"),
        b"immutable user event\n",
    );
    let initial = fs::read(fixture.home.join("state/install.json")).unwrap();
    let source = new_source(&fixture);
    let service = service(&fixture, "zcode");
    assert_eq!(
        service.bootstrap(&source, false).unwrap_err().code,
        "HARNESS_LEGACY_HANDOFF_REQUIRED"
    );
    assert!(fixture.home.join("repo/scripts/engine.py").exists());
    let status = service.bootstrap(&source, true).unwrap();
    assert_eq!(status["desiredHarnesses"], json!(["zcode"]));
    assert_eq!(status["hooksEnabled"], false);
    assert!(fixture.home.join("state/distribution.json").is_file());
    assert!(!fixture.home.join("state/manager.json").exists());
    assert!(!fixture.home.join("state/desired.json").exists());
    assert!(!fixture.home.join("repo/scripts/engine.py").exists());
    assert!(!fixture.target.join("skills/task").is_symlink());
    assert_eq!(
        fs::read(fixture.home.join("state/install.json")).unwrap(),
        initial
    );
    assert_eq!(
        fs::read(fixture.home.join("logs/history.jsonl")).unwrap(),
        b"immutable user event\n"
    );
    assert_eq!(
        fs::read(fixture.target.join("AGENTS.md")).unwrap(),
        b"# New Rust-owned instructions\n"
    );
    service.execute("refresh", &["zcode".into()]).unwrap();
    service.bootstrap(&source, true).unwrap();
    service.execute("remove", &["zcode".into()]).unwrap();
    assert!(!fixture.target.join("AGENTS.md").exists());
    assert!(!fixture.target.join("skills/task/SKILL.md").exists());
    assert_eq!(service.status().unwrap()["desiredHarnesses"], json!([]));
    assert_eq!(
        fs::read(fixture.home.join("logs/history.jsonl")).unwrap(),
        b"immutable user event\n"
    );
}
#[test]
fn service_handoff_conflict_keeps_old_engine_and_user_file_unchanged() {
    let fixture = Fixture::new(true);
    write(
        &fixture.target.join("AGENTS.md"),
        b"user-authored instructions\n",
    );
    let old_manager = fs::read(fixture.home.join("state/manager.json")).unwrap();
    let source = new_source(&fixture);
    let service = service(&fixture, "zcode");
    assert!(service.bootstrap(&source, true).is_err());
    assert!(!fixture.home.join("state/distribution.json").exists());
    assert!(fixture.home.join("repo/scripts/engine.py").exists());
    assert_eq!(
        fs::read(fixture.home.join("state/manager.json")).unwrap(),
        old_manager
    );
    assert_eq!(
        fs::read(fixture.target.join("AGENTS.md")).unwrap(),
        b"user-authored instructions\n"
    );
}
#[test]
fn service_adopts_codex_shared_config_and_preserves_foreign_values_on_uninstall() {
    let fixture = codex_fixture();
    let source = new_source(&fixture);
    let service = service(&fixture, "codex");
    let old_cache = fixture
        .target
        .join("plugins/cache/atm-harness/workflow/1.0.0+codex.0123456789abcdef");
    // Transient runtime output is not payload ownership and must survive cleanup.
    write(
        &old_cache.join("__pycache__/user.pyc"),
        b"retained transient bytes",
    );
    let status = service.bootstrap(&source, true).unwrap();
    assert_eq!(status["desiredHarnesses"], json!(["codex"]));
    let config = fs::read_to_string(fixture.target.join("config.toml")).unwrap();
    assert!(config.contains("TEST_ONLY"));
    assert!(config.contains("cache/content"));
    assert_eq!(
        fs::read(old_cache.join("__pycache__/user.pyc")).unwrap(),
        b"retained transient bytes"
    );
    service.execute("remove", &["codex".into()]).unwrap();
    let config = fs::read_to_string(fixture.target.join("config.toml")).unwrap();
    assert!(config.contains("TEST_ONLY"));
    assert!(!config.contains("workflow@atm-harness"));
    assert!(fixture.home.join("state/legacy-handoff").is_dir());
}

#[test]
fn git_bound_marketplace_handoff_reports_unsupported_without_retiring_old_owner() {
    let fixture = codex_fixture();
    write_json(
        &fixture.home.join("state/install.json"),
        json!({"product":"atm-harness","status":"ready","paths":{"home":fixture.home,"repo":fixture.home.join("repo"),"venv":fixture.home.join("venv")}}),
    );
    let config_path = fixture.target.join("config.toml");
    let config = fs::read_to_string(&config_path)
        .unwrap()
        .replace("source_type = 'local'", "source_type = 'git'");
    fs::write(&config_path, &config).unwrap();
    let manager = fs::read(fixture.home.join("state/manager.json")).unwrap();
    let initial = fs::read(fixture.home.join("state/install.json")).unwrap();
    let source = new_source(&fixture);
    let error = service(&fixture, "codex")
        .bootstrap(&source, true)
        .unwrap_err();
    assert_eq!(error.code, "HARNESS_LEGACY_MARKETPLACE_UNSUPPORTED");
    assert_eq!(fs::read_to_string(config_path).unwrap(), config);
    assert_eq!(
        fs::read(fixture.home.join("state/manager.json")).unwrap(),
        manager
    );
    assert_eq!(
        fs::read(fixture.home.join("state/install.json")).unwrap(),
        initial
    );
    assert!(fixture.home.join("repo/scripts/engine.py").is_file());
    assert!(!fixture.home.join("state/distribution.json").exists());
    assert!(!fixture.home.join("state/legacy-handoff").exists());
}
