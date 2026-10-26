use atm_core::distribution::{adapters, source::Bundle};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use tempfile::TempDir;

fn fixture() -> Bundle {
    let registry: Value = serde_json::from_slice(include_bytes!(
        "../../../harness/.agents/harnesses/registry.json"
    ))
    .unwrap();
    let mut files = BTreeMap::new();
    files.insert(
        ".agents/harnesses/registry.json".into(),
        serde_json::to_vec(&registry).unwrap(),
    );
    files.insert(
        "agents/global-instructions.md".into(),
        b"TEST_ONLY instructions\n".to_vec(),
    );
    files.insert(
        "agents/operating-principles.md".into(),
        b"TEST_ONLY operating principles\n".to_vec(),
    );
    files.insert(".agents/plugins/marketplace.json".into(), serde_json::to_vec(&json!({"name":"atm-harness","plugins":[{"name":"workflow","source":{"source":"local","path":"./plugins/workflow"}}]})).unwrap());
    files.insert(
        "plugins/workflow/.codex-plugin/plugin.json".into(),
        serde_json::to_vec(
            &json!({"name":"workflow","version":"1.0.0+codex.1234","skills":"./skills/"}),
        )
        .unwrap(),
    );
    files.insert(
        "plugins/workflow/scripts/shared.py".into(),
        b"SHARED_VALUE = 1\n".to_vec(),
    );
    files.insert(
        "plugins/workflow/skills/one/SKILL.md".into(),
        b"---\nname: one\n---\nUse scripts/check.py.\n".to_vec(),
    );
    files.insert(
        "plugins/workflow/skills/one/scripts/check.py".into(),
        b"from pathlib import Path\nSHARED = Path(__file__).resolve().parents[3] / \"scripts\"\n"
            .to_vec(),
    );
    Bundle {
        identity: "a".repeat(64),
        release: "1.0.0".into(),
        files,
        catalog: json!({"skills":[{"id":"workflow:one","plugin":"workflow","name":"one","directoryName":"one","path":"plugins/workflow/skills/one","aliases":[]}]}),
        manifest: json!({"schemaVersion":1}),
    }
}
fn cache(temp: &TempDir) -> std::path::PathBuf {
    temp.path().join("cache with spaces 中文")
}

#[test]
fn all_registry_clients_project_static_content_without_processes() {
    let temp = TempDir::new().unwrap();
    let bundle = fixture();
    let expected = [
        ("zcode", Some("AGENTS.md")),
        ("claude", Some("CLAUDE.md")),
        ("copilot", Some("copilot-instructions.md")),
        ("vscode", Some("copilot-instructions.md")),
        ("gemini", Some("GEMINI.md")),
        ("opencode", Some("AGENTS.md")),
        ("openclaw", None),
        ("pi", Some("AGENTS.md")),
        ("omp", Some("AGENTS.md")),
    ];
    for (target, instructions) in expected {
        let root = temp.path().join(target);
        let planned = adapters::plan(&bundle, &cache(&temp), target, &root.join("skills")).unwrap();
        assert!(planned
            .iter()
            .any(|file| file.path == root.join("skills/one/SKILL.md")));
        let helper = planned
            .iter()
            .find(|file| file.path == root.join("skills/one/scripts/check.py"))
            .unwrap();
        let text = String::from_utf8(helper.bytes.clone()).unwrap();
        assert!(text.contains("cache with spaces 中文"));
        assert!(!text.contains("parents[3]"));
        if let Some(name) = instructions {
            assert!(planned
                .iter()
                .any(|file| file.path == root.join(name)
                    && file.bytes == b"TEST_ONLY instructions\n"));
        } else {
            assert_eq!(planned.len(), 2);
        }
        assert!(!root.exists(), "planning must not write targets");
    }
}

#[test]
fn gemini_respects_single_configured_path_and_rejects_unsafe_or_multiple_targets() {
    let temp = TempDir::new().unwrap();
    let root = temp.path().join("gemini");
    fs::create_dir(&root).unwrap();
    let bundle = fixture();
    for value in [
        json!("instructions/CUSTOM.md"),
        json!(["instructions/CUSTOM.md"]),
    ] {
        fs::write(
            root.join("settings.json"),
            serde_json::to_vec(&json!({"context":{"fileName":value}})).unwrap(),
        )
        .unwrap();
        let files =
            adapters::plan(&bundle, &cache(&temp), "gemini-cli", &root.join("skills")).unwrap();
        assert!(files
            .iter()
            .any(|file| file.path == root.join("instructions/CUSTOM.md")));
        let checked = adapters::plan_owned(
            &bundle,
            &cache(&temp),
            "gemini-cli",
            &root.join("skills"),
            &BTreeMap::new(),
        )
        .unwrap();
        assert_eq!(
            checked.observed,
            vec![(
                root.join("settings.json"),
                Some(fs::read(root.join("settings.json")).unwrap())
            )]
        );
    }
    for value in [
        json!(["A.md", "B.md"]),
        json!([]),
        json!("../outside.md"),
        json!("C:\\escape.md"),
        json!("/absolute.md"),
    ] {
        fs::write(
            root.join("settings.json"),
            serde_json::to_vec(&json!({"context":{"fileName":value}})).unwrap(),
        )
        .unwrap();
        assert!(
            adapters::plan(&bundle, &cache(&temp), "gemini-cli", &root.join("skills")).is_err()
        );
    }
    fs::write(root.join("settings.json"), "{").unwrap();
    assert!(adapters::plan(&bundle, &cache(&temp), "gemini-cli", &root.join("skills")).is_err());
}

#[test]
fn shadowing_and_symlink_settings_fail_before_mutation() {
    let temp = TempDir::new().unwrap();
    let root = temp.path().join("pi");
    fs::create_dir(&root).unwrap();
    fs::write(root.join("AGENTS.override.md"), "USER").unwrap();
    assert_eq!(
        adapters::plan(&fixture(), &cache(&temp), "pi-agent", &root.join("skills"))
            .unwrap_err()
            .code,
        "HARNESS_SHADOW"
    );
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink("missing", root.join("settings.json")).unwrap();
        assert!(adapters::plan(
            &fixture(),
            &cache(&temp),
            "gemini-cli",
            &root.join("skills")
        )
        .is_err());
    }
}

#[test]
fn codex_projects_native_cache_and_merges_owned_tables_without_touching_neighbors() {
    let temp = TempDir::new().unwrap();
    let root = temp.path().join("codex");
    fs::create_dir(&root).unwrap();
    let original =
        b"# user comment\nmodel = 'USER_MODEL'\n[plugins.\"other@other-store\"]\nenabled = true\n";
    fs::write(root.join("config.toml"), original).unwrap();
    let bundle = fixture();
    let first = adapters::plan_owned(
        &bundle,
        &cache(&temp),
        "codex",
        &root.join("skills"),
        &BTreeMap::new(),
    )
    .unwrap();
    assert!(first.artifacts.iter().any(|file| file.path
        == root.join("plugins/cache/atm-harness/workflow/1.0.0+codex.1234/skills/one/SKILL.md")));
    assert!(!first
        .artifacts
        .iter()
        .any(|file| file.path.starts_with(root.join("skills"))));
    assert!(first
        .artifacts
        .iter()
        .any(|file| file.path == root.join("agents/operating-principles.md")));
    let shared = &first.shared[0];
    assert_eq!(shared.before.as_deref(), Some(original.as_slice()));
    let text = String::from_utf8(shared.artifact.bytes.clone()).unwrap();
    assert!(text.contains("# user comment"));
    assert!(text.contains("other@other-store"));
    assert!(text.contains("workflow@atm-harness"));
    assert_eq!(
        adapters::restore_shared(Some(&shared.artifact.bytes), &shared.ownership)
            .unwrap()
            .unwrap(),
        original
    );
    fs::write(&shared.artifact.path, &shared.artifact.bytes).unwrap();
    let previous = BTreeMap::from([(shared.artifact.path.clone(), shared.ownership.clone())]);
    let again = adapters::plan_owned(
        &bundle,
        &cache(&temp),
        "codex",
        &root.join("skills"),
        &previous,
    )
    .unwrap();
    assert_eq!(again.shared[0].artifact.bytes, shared.artifact.bytes);
    let changed_cache = temp.path().join("cache-updated");
    let updated = adapters::plan_owned(
        &bundle,
        &changed_cache,
        "codex",
        &root.join("skills"),
        &previous,
    )
    .unwrap();
    assert!(String::from_utf8(updated.shared[0].artifact.bytes.clone())
        .unwrap()
        .contains("cache-updated"));
    assert_eq!(
        adapters::restore_shared(
            Some(&updated.shared[0].artifact.bytes),
            &updated.shared[0].ownership
        )
        .unwrap()
        .unwrap(),
        original
    );
}

#[test]
fn config_edits_unrelated_to_owned_entries_survive_uninstall_but_owned_edits_fail() {
    let temp = TempDir::new().unwrap();
    let root = temp.path().join("codex");
    let planned = adapters::plan_owned(
        &fixture(),
        &cache(&temp),
        "codex",
        &root.join("skills"),
        &BTreeMap::new(),
    )
    .unwrap();
    let shared = &planned.shared[0];
    assert!(
        adapters::restore_shared(Some(&shared.artifact.bytes), &shared.ownership)
            .unwrap()
            .is_none()
    );
    let mut edited = shared.artifact.bytes.clone();
    edited.extend_from_slice(b"\n[projects.TEST_ONLY]\ntrust_level = 'trusted'\n");
    let restored = adapters::restore_shared(Some(&edited), &shared.ownership)
        .unwrap()
        .unwrap();
    let restored = String::from_utf8(restored).unwrap();
    assert!(restored.contains("TEST_ONLY"));
    assert!(!restored.contains("workflow@atm-harness"));
    fs::create_dir(&root).unwrap();
    fs::write(root.join("config.toml"), &edited).unwrap();
    let previous = BTreeMap::from([(shared.artifact.path.clone(), shared.ownership.clone())]);
    let updated = adapters::plan_owned(
        &fixture(),
        &temp.path().join("updated-cache"),
        "codex",
        &root.join("skills"),
        &previous,
    )
    .unwrap();
    let after_update = adapters::restore_shared(
        Some(&updated.shared[0].artifact.bytes),
        &updated.shared[0].ownership,
    )
    .unwrap()
    .unwrap();
    assert!(String::from_utf8(after_update)
        .unwrap()
        .contains("TEST_ONLY"));
    let changed = String::from_utf8(shared.artifact.bytes.clone())
        .unwrap()
        .replace("enabled = true", "enabled = false");
    assert_eq!(
        adapters::restore_shared(Some(changed.as_bytes()), &shared.ownership)
            .unwrap_err()
            .code,
        "HARNESS_CONFLICT"
    );
    assert!(adapters::restore_shared(None, &shared.ownership).is_err());
}

#[test]
fn unmanaged_same_selector_and_duplicate_marketplace_fail_closed() {
    let temp = TempDir::new().unwrap();
    let root = temp.path().join("codex");
    fs::create_dir(&root).unwrap();
    for config in [
        "[plugins.\"workflow@atm-harness\"]\nenabled = true\n",
        "[plugins.\"workflow@old-store\"]\nenabled = true\n",
        "plugins = false\n",
        "[marketplaces.atm-harness]\nsource_type='local'\nsource='USER'\n",
    ] {
        fs::write(root.join("config.toml"), config).unwrap();
        assert!(adapters::plan_owned(
            &fixture(),
            &cache(&temp),
            "codex",
            &root.join("skills"),
            &BTreeMap::new()
        )
        .is_err());
        assert_eq!(
            fs::read_to_string(root.join("config.toml")).unwrap(),
            config
        );
    }
}

#[test]
fn selections_reject_partial_native_package_and_unknown_names() {
    let temp = TempDir::new().unwrap();
    let mut bundle = fixture();
    bundle.catalog["skills"].as_array_mut().unwrap().push(json!({"id":"workflow:two","plugin":"workflow","name":"two","directoryName":"two","path":"plugins/workflow/skills/two"}));
    bundle.files.insert(
        "plugins/workflow/skills/two/SKILL.md".into(),
        b"---\nname: two\n---\n".to_vec(),
    );
    let skills_root = temp.path().join("zcode/skills");
    let chosen = vec!["workflow:one".into()];
    let direct = adapters::plan_owned_selected(
        &bundle,
        &cache(&temp),
        "zcode",
        &skills_root,
        &BTreeMap::new(),
        Some(&chosen),
    )
    .unwrap();
    assert!(!direct
        .artifacts
        .iter()
        .any(|file| file.path.starts_with(skills_root.join("two"))));
    assert_eq!(
        adapters::plan_owned_selected(
            &bundle,
            &cache(&temp),
            "codex",
            &temp.path().join("codex/skills"),
            &BTreeMap::new(),
            Some(&chosen)
        )
        .unwrap_err()
        .code,
        "HARNESS_SELECTION"
    );
    assert!(adapters::plan_owned_selected(
        &bundle,
        &cache(&temp),
        "zcode",
        &skills_root,
        &BTreeMap::new(),
        Some(&["unknown".into()])
    )
    .is_err());
}

#[test]
fn explicit_legacy_config_handoff_proves_binding_and_keeps_user_values() {
    let source = if cfg!(windows) {
        Path::new("C:/TEST_ONLY/old repo")
    } else {
        Path::new("/TEST_ONLY/old repo")
    };
    let source_literal = serde_json::to_string(source.to_str().unwrap()).unwrap();
    let config = format!("model = 'USER'\n[marketplaces.atm-harness]\nsource_type='local'\nsource={source_literal}\n[plugins.\"workflow@atm-harness\"]\nenabled=true\n");
    let proof = adapters::legacy_codex_ownership(
        config.as_bytes(),
        "atm-harness",
        source,
        &["workflow".into()],
    )
    .unwrap();
    let restored = adapters::restore_shared(Some(config.as_bytes()), &proof)
        .unwrap()
        .unwrap();
    assert!(String::from_utf8(restored)
        .unwrap()
        .contains("model = 'USER'"));
    assert!(adapters::legacy_codex_ownership(
        config.replace("enabled=true", "enabled=false").as_bytes(),
        "atm-harness",
        source,
        &["workflow".into()]
    )
    .is_err());
    assert_eq!(
        adapters::legacy_codex_ownership(
            config
                .replace("source_type='local'", "source_type='git'")
                .as_bytes(),
            "atm-harness",
            source,
            &["workflow".into()]
        )
        .unwrap_err()
        .code,
        "HARNESS_LEGACY_MARKETPLACE_UNSUPPORTED"
    );
    assert!(adapters::legacy_codex_ownership(
        config.replace(&source_literal, "123").as_bytes(),
        "atm-harness",
        source,
        &["workflow".into()],
    )
    .is_err());
}

#[test]
fn sealed_repository_payload_plans_complete_native_codex_distribution() {
    let temp = TempDir::new().unwrap();
    let source = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../harness")
        .canonicalize()
        .unwrap();
    let bundle = atm_core::distribution::source::load(&source).unwrap();
    let root = temp.path().join("Codex 空格");
    let planned = adapters::plan_owned(
        &bundle,
        &cache(&temp),
        "codex",
        &root.join("skills"),
        &BTreeMap::new(),
    )
    .unwrap();
    assert!(planned
        .artifacts
        .iter()
        .any(|file| file.path == root.join("agents/operating-principles.md")));
    for package in bundle.manifest["packages"].as_array().unwrap() {
        let plugin = package["name"].as_str().unwrap();
        let prefix = format!("plugins/{plugin}/");
        let manifest: Value =
            serde_json::from_slice(&bundle.files[&format!("{prefix}.codex-plugin/plugin.json")])
                .unwrap();
        let version = manifest["version"].as_str().unwrap();
        for (path, bytes) in &bundle.files {
            if let Some(relative) = path.strip_prefix(&prefix) {
                let destination = root
                    .join("plugins/cache/atm-harness")
                    .join(plugin)
                    .join(version)
                    .join(relative);
                assert!(planned
                    .artifacts
                    .iter()
                    .any(|file| file.path == destination && file.bytes == *bytes));
            }
        }
    }
    assert!(!root.exists());
    let mut incomplete = bundle;
    incomplete.files.remove("agents/operating-principles.md");
    assert_eq!(
        adapters::plan_owned(
            &incomplete,
            &cache(&temp),
            "codex",
            &root.join("skills"),
            &BTreeMap::new()
        )
        .unwrap_err()
        .code,
        "HARNESS_PAYLOAD_INCOMPLETE"
    );
}

#[test]
fn declared_empty_payload_directories_preserve_native_identity() {
    let temp = TempDir::new().unwrap();
    let mut bundle = fixture();
    bundle.manifest["directories"] = json!([
        "plugins/workflow",
        "plugins/workflow/skills",
        "plugins/workflow/skills/one",
        "plugins/workflow/skills/one/templates",
        "plugins/workflow/skills/one/templates/empty",
        "plugins/workflow/assets"
    ]);
    let root = temp.path().join("codex");
    let codex = adapters::plan_owned(
        &bundle,
        &cache(&temp),
        "codex",
        &root.join("skills"),
        &BTreeMap::new(),
    )
    .unwrap();
    let package = root.join("plugins/cache/atm-harness/workflow/1.0.0+codex.1234");
    assert_eq!(
        codex.empty_directories,
        vec![
            package.join("assets"),
            package.join("skills/one/templates/empty")
        ]
    );
    let direct = adapters::plan_owned(
        &bundle,
        &cache(&temp),
        "zcode",
        &root.join("skills"),
        &BTreeMap::new(),
    )
    .unwrap();
    assert_eq!(
        direct.empty_directories,
        vec![root.join("skills/one/templates/empty")]
    );
    assert_eq!(
        adapters::plan(&bundle, &cache(&temp), "codex", &root.join("skills"))
            .unwrap_err()
            .code,
        "HARNESS_PLAN_DIRECTORY"
    );
    assert!(!root.exists());
}
