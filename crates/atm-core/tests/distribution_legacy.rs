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
        fixture
            .home
            .join("venv")
            .join("Scripts")
            .join("python.exe")
            .display(),
        fixture
            .home
            .join("repo")
            .join("plugins")
            .join("watcher")
            .join("scripts")
            .join("watcher")
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
    let document = config.parse::<toml_edit::Document>().unwrap();
    let marketplace_source = document["marketplaces"]["atm-harness"]["source"]
        .as_str()
        .unwrap();
    let expected_cache = fixture.home.join("cache").join("content").join(
        atm_core::distribution::source::load(&source)
            .unwrap()
            .identity,
    );
    assert_eq!(Path::new(marketplace_source), expected_cache);
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

// Exact launcher templates from the supported OMH predecessor. They are inert
// fixture bytes: no shell/Python launcher is executed by these tests.
const OMH_POSIX_LAUNCHER: &str = r#"#!/usr/bin/env sh
set -eu
bootstrap_python=
if [ -n "${OH_MY_HARNESS_BOOTSTRAP_PYTHON:-}" ]; then
    bootstrap_python=$OH_MY_HARNESS_BOOTSTRAP_PYTHON
    "$bootstrap_python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
        echo "error: OH_MY_HARNESS_BOOTSTRAP_PYTHON must select Python 3.11 or newer" >&2
        exit 1
    }
else
    for candidate in python3 python python3.14 python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
            bootstrap_python=$(command -v "$candidate")
            break
        fi
    done
fi
if [ -z "$bootstrap_python" ]; then
    echo "error: Python 3.11 or newer not found; set OH_MY_HARNESS_BOOTSTRAP_PYTHON" >&2
    exit 1
fi
omh_command=$0
case "$omh_command" in
    */*) ;;
    *) omh_command=$(command -v "$omh_command") ;;
esac
omh_home=$("$bootstrap_python" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parent.parent)' "$omh_command")
exec "$bootstrap_python" "$omh_home/bootstrap/omh_bootstrap.py" --home "$omh_home" "$@"
"#;
const OMH_WINDOWS_LAUNCHER: &str = r#"@echo off
setlocal DisableDelayedExpansion
for %%I in ("%~dp0..") do set "OMH_HOME=%%~fI"
if defined OH_MY_HARNESS_BOOTSTRAP_PYTHON (
  "%OH_MY_HARNESS_BOOTSTRAP_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
  if errorlevel 1 (
    echo error: OH_MY_HARNESS_BOOTSTRAP_PYTHON must select Python 3.11 or newer 1>&2
    exit /b 1
  )
  set "OHM_PY=%OH_MY_HARNESS_BOOTSTRAP_PYTHON%"
  goto :run
)
for %%P in (python py python3) do (
  %%P -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
  if not errorlevel 1 (
    set "OHM_PY=%%P"
    goto :run
  )
)
echo error: Python 3.11 or newer not found; set OH_MY_HARNESS_BOOTSTRAP_PYTHON 1>&2
exit /b 1
:run
(
"%OHM_PY%" "%OMH_HOME%\bootstrap\omh_bootstrap.py" --home "%OMH_HOME%" %*
call exit /b %%ERRORLEVEL%%
)
"#;

fn fixture_git(repo: &Path, args: &[&str]) -> String {
    let result = std::process::Command::new("git")
        .args([
            "--no-optional-locks",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.fsmonitor=false",
            "-C",
        ])
        .arg(repo)
        .args(args)
        .env("GIT_AUTHOR_NAME", "TEST_ONLY")
        .env("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
        .env("GIT_COMMITTER_NAME", "TEST_ONLY")
        .env("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "Git fixture command {args:?} failed: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    String::from_utf8(result.stdout).unwrap().trim().into()
}
fn convert_to_pinned_omh(fixture: &Fixture) {
    let repo = fixture.home.join("repo");
    fs::remove_file(repo.join(".atm-embedded.json")).unwrap();
    fs::rename(repo.join("scripts/engine.py"), repo.join("scripts/omh.py")).unwrap();
    fs::rename(
        repo.join("scripts/atm_bootstrap.py"),
        repo.join("scripts/omh_bootstrap.py"),
    )
    .unwrap();
    let installer=format!("def posix_launcher(*, home, repo):\n    return r'''{OMH_POSIX_LAUNCHER}'''\n\ndef windows_launcher(*, home, repo):\n    return r'''{OMH_WINDOWS_LAUNCHER}'''.replace(\"\\n\", \"\\r\\n\")\n");
    write(&repo.join("scripts/install_oh_my_harness.py"), installer);
    write(
        &fixture.home.join("bootstrap/omh_bootstrap.py"),
        fs::read(repo.join("scripts/omh_bootstrap.py")).unwrap(),
    );
    for name in ["omh", "oh-my-harness"] {
        write(&fixture.home.join("bin").join(name), OMH_POSIX_LAUNCHER);
    }
    for name in ["omh.cmd", "oh-my-harness.cmd"] {
        write(
            &fixture.home.join("bin").join(name),
            OMH_WINDOWS_LAUNCHER.replace('\n', "\r\n"),
        );
    }
    // All Git writes are confined to this disposable synthetic predecessor. Use
    // plumbing to create fixture evidence without invoking commit hooks.
    fixture_git(&repo, &["init", "--quiet", "--object-format=sha1"]);
    fixture_git(&repo, &["add", "--all"]);
    let tree = fixture_git(&repo, &["write-tree"]);
    let revision = fixture_git(
        &repo,
        &["commit-tree", &tree, "-m", "TEST_ONLY legacy fixture"],
    );
    fixture_git(&repo, &["update-ref", "HEAD", &revision]);
    fixture_git(
        &repo,
        &[
            "remote",
            "add",
            "origin",
            "https://example.invalid/TEST_ONLY/oh-my-harness.git",
        ],
    );
    assert_eq!(
        fixture_git(&repo, &["status", "--porcelain", "--untracked-files=all"]),
        ""
    );
    let manager_path = fixture.home.join("state/manager.json");
    let mut manager: serde_json::Value =
        serde_json::from_slice(&fs::read(&manager_path).unwrap()).unwrap();
    manager["product"] = json!("oh-my-harness");
    manager["revision"] = json!(revision);
    manager["channel"] = json!("main");
    manager["repository"] = json!("https://example.invalid/TEST_ONLY/oh-my-harness.git");
    write_json(&manager_path, manager);
}
fn snapshot_tree(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    fn walk(root: &Path, path: &Path, output: &mut BTreeMap<PathBuf, Vec<u8>>) {
        for entry in fs::read_dir(path).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            let metadata = fs::symlink_metadata(&path).unwrap();
            let relative = path.strip_prefix(root).unwrap().to_path_buf();
            if metadata.file_type().is_symlink() {
                let mut bytes = b"LINK\0".to_vec();
                bytes.extend_from_slice(
                    fs::read_link(&path).unwrap().as_os_str().as_encoded_bytes(),
                );
                output.insert(relative, bytes);
            } else if metadata.is_dir() {
                output.insert(relative, b"DIR".to_vec());
                walk(root, &path, output);
            } else {
                let mut bytes = b"FILE\0".to_vec();
                bytes.extend(fs::read(path).unwrap());
                output.insert(relative, bytes);
            }
        }
    }
    let mut output = BTreeMap::new();
    walk(root, root, &mut output);
    output
}
#[test]
fn pinned_omh_source_maps_exact_historical_entrypoints_and_launchers() {
    let fixture = Fixture::new(false);
    convert_to_pinned_omh(&fixture);
    let before = snapshot_tree(&fixture.home);
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    assert_eq!(handoff.product, "oh-my-harness");
    assert!(handoff.source_identity.starts_with("git:"));
    for path in [
        "repo/scripts/omh.py",
        "repo/scripts/install_oh_my_harness.py",
        "repo/scripts/omh_bootstrap.py",
        "bootstrap/omh_bootstrap.py",
        "bin/omh",
        "bin/oh-my-harness",
        "bin/omh.cmd",
        "bin/oh-my-harness.cmd",
    ] {
        assert!(
            handoff
                .retire
                .iter()
                .any(|file| file.path == fixture.home.join(path)),
            "missing retirement {path}"
        );
    }
    assert_eq!(snapshot_tree(&fixture.home), before);
    let manager_path = fixture.home.join("state/manager.json");
    let mut manager: serde_json::Value =
        serde_json::from_slice(&fs::read(&manager_path).unwrap()).unwrap();
    manager["product"] = json!("atm-harness");
    write_json(&manager_path, manager);
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_LEGACY_INVALID",
        "wrong product must not fall back to OMH filenames"
    );
}
#[test]
fn omh_launcher_bootstrap_and_pinned_source_drift_are_preserved_and_rejected() {
    let fixture = Fixture::new(false);
    convert_to_pinned_omh(&fixture);
    let launcher = fixture.home.join("bin/omh");
    write(&launcher, b"user-edited launcher\n");
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_LEGACY_CHANGED"
    );
    assert_eq!(fs::read(&launcher).unwrap(), b"user-edited launcher\n");
    write(&launcher, OMH_POSIX_LAUNCHER);
    let bootstrap = fixture.home.join("bootstrap/omh_bootstrap.py");
    write(&bootstrap, b"user-edited bootstrap\n");
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_LEGACY_CHANGED"
    );
    assert_eq!(fs::read(&bootstrap).unwrap(), b"user-edited bootstrap\n");
    write(
        &bootstrap,
        fs::read(fixture.home.join("repo/scripts/omh_bootstrap.py")).unwrap(),
    );
    let engine = fixture.home.join("repo/scripts/omh.py");
    write(&engine, b"user-edited engine\n");
    assert_eq!(
        inspect(&fixture.home).unwrap_err().code,
        "HARNESS_LEGACY_CHANGED"
    );
    assert_eq!(fs::read(engine).unwrap(), b"user-edited engine\n");
}
#[test]
fn omh_codex_support_uses_its_exact_historical_marker() {
    let fixture = codex_fixture();
    write(
        &fixture.home.join("repo/agents/operating-principles.md"),
        b"TEST_ONLY support\n",
    );
    convert_to_pinned_omh(&fixture);
    let target = fixture.target.join("agents/operating-principles.md");
    write(&target,b"# Managed by oh-my-harness scripts/sync_codex_agents.py.\n# Source: agents/operating-principles.md\n# Do not edit this target file directly.\n\nTEST_ONLY support\n");
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    let roots = BTreeMap::from([("codex".into(), fixture.target.clone())]);
    let targets = inspect_targets(&fixture.home, &handoff, &roots).unwrap();
    assert!(targets.iter().any(|item| item.path == target));
    write(&target, b"user customized support\n");
    assert!(inspect_targets(&fixture.home, &handoff, &roots).is_err());
}
#[test]
fn adoption_preview_is_read_only_reports_exact_changes_and_apply_revalidates() {
    let fixture = Fixture::new(true);
    convert_to_pinned_omh(&fixture);
    write(
        &fixture.target.join("AGENTS.md"),
        b"# ordinary source instructions\n",
    );
    let source = new_source(&fixture);
    let service = service(&fixture, "zcode");
    let before = snapshot_tree(fixture._temp.path());
    let preview = service.preview_adopt(&source).unwrap();
    assert_eq!(
        snapshot_tree(fixture._temp.path()),
        before,
        "preview must not create cache, lock, journal or state"
    );
    assert_eq!(preview["dryRun"], true);
    assert_eq!(preview["legacyProduct"], "oh-my-harness");
    assert_eq!(preview["cache"]["action"], "create");
    assert_eq!(
        preview["targets"],
        json!([{"harness":"zcode","root":fixture.target}])
    );
    assert_eq!(preview["hooksEnabledAfter"], false);
    let changes = preview["changes"].as_array().unwrap();
    let change = changes
        .iter()
        .find(|item| item["path"] == json!(fixture.target.join("AGENTS.md")))
        .unwrap();
    assert_eq!(change["action"], "replace");
    assert_eq!(change["before"]["kind"], "file");
    assert_eq!(
        change["before"]["sha256"],
        format!("{:x}", Sha256::digest(b"# ordinary source instructions\n"))
    );
    assert_eq!(
        change["after"]["sha256"],
        format!("{:x}", Sha256::digest(b"# New Rust-owned instructions\n"))
    );
    assert!(!serde_json::to_string(&preview)
        .unwrap()
        .contains("New Rust-owned instructions"));
    write(
        &fixture.target.join("AGENTS.md"),
        b"changed after preview\n",
    );
    assert_eq!(
        service.bootstrap(&source, true).unwrap_err().code,
        "HARNESS_LEGACY_CHANGED"
    );
    assert!(!fixture.home.join("cache").exists());
    assert!(!fixture.home.join("state/distribution.json").exists());
    assert!(fixture.home.join("repo/scripts/omh.py").exists());
    write(
        &fixture.target.join("AGENTS.md"),
        b"# ordinary source instructions\n",
    );
    let status = service.bootstrap(&source, true).unwrap();
    assert_eq!(status["desiredHarnesses"], json!(["zcode"]));
    for path in [
        "repo/scripts/omh.py",
        "bootstrap/omh_bootstrap.py",
        "bin/omh",
        "bin/omh.cmd",
    ] {
        assert!(!fixture.home.join(path).exists());
    }
}
#[test]
fn failed_adoption_preview_preserves_every_file_and_creates_no_lock() {
    let fixture = Fixture::new(true);
    let source = new_source(&fixture);
    write(&fixture.target.join("AGENTS.md"), b"user content\n");
    let before = snapshot_tree(fixture._temp.path());
    assert!(service(&fixture, "zcode").preview_adopt(&source).is_err());
    assert_eq!(snapshot_tree(fixture._temp.path()), before);
    assert!(!fixture.home.join("state/manager.lock").exists());
    assert!(!fixture.home.join("cache").exists());
}

#[cfg(windows)]
#[test]
fn legacy_roots_bind_to_the_same_physical_directory_and_emit_caller_paths() {
    let fixture = codex_fixture();
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    // canonicalize expands a runner's possible 8.3 alias and produces the
    // extended Windows prefix. Neither spelling establishes a second owner.
    let allowed_root = fixture.target.canonicalize().unwrap();
    let roots = BTreeMap::from([("codex".into(), allowed_root.clone())]);
    let targets = inspect_targets(&fixture.home, &handoff, &roots).unwrap();
    assert!(!targets.is_empty());
    assert!(targets
        .iter()
        .all(|item| item.path.starts_with(&allowed_root)));
    let evidence = atm_core::distribution::legacy::codex_evidence(&handoff, &allowed_root)
        .unwrap()
        .unwrap();
    assert_eq!(evidence.config_path, allowed_root.join("config.toml"));
    let wrong = fixture._temp.path().join("unrelated physical root");
    fs::create_dir_all(&wrong).unwrap();
    assert!(inspect_targets(
        &fixture.home,
        &handoff,
        &BTreeMap::from([("codex".into(), wrong.clone())])
    )
    .is_err());
    assert!(atm_core::distribution::legacy::codex_evidence(&handoff, &wrong).is_err());
}

#[cfg(unix)]
#[test]
fn physical_root_binding_still_rejects_a_linked_receipt_root() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::new(true);
    write(
        &fixture.target.join("AGENTS.md"),
        b"# ordinary source instructions\n",
    );
    let alias = fixture._temp.path().join("linked root");
    symlink(&fixture.target, &alias).unwrap();
    let receipt_path = fixture.home.join("state/harnesses/zcode.json");
    let mut receipt: serde_json::Value =
        serde_json::from_slice(&fs::read(&receipt_path).unwrap()).unwrap();
    receipt["root"] = json!(alias);
    write_json(&receipt_path, receipt);
    let handoff = inspect(&fixture.home).unwrap().unwrap();
    assert!(inspect_targets(&fixture.home, &handoff, &fixture.roots()).is_err());
    assert_eq!(
        fs::read(fixture.target.join("AGENTS.md")).unwrap(),
        b"# ordinary source instructions\n"
    );
}
