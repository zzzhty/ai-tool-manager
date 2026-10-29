use atm_core::distribution::source;
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
    let digest = source::plugin_content_identity(root, "maintenance", "1.0.0").unwrap();
    let version = format!("1.0.0+codex.{}", &digest[..16]);
    let plugin_path = "plugins/maintenance/.codex-plugin/plugin.json";
    let mut plugin: Value =
        serde_json::from_slice(&fs::read(root.join(plugin_path)).unwrap()).unwrap();
    plugin["version"] = json!(version);
    json_write(root, plugin_path, plugin);
    let bundle = json!({"algorithm":"sha256-canonical-plugin-tree-v1","releaseVersion":"1.0.0","plugins":[{"name":"maintenance","version":version,"contentSha256":digest}]});
    let bundle_digest = format!(
        "sha256:{:x}",
        Sha256::digest(serde_json::to_vec(&bundle).unwrap())
    );
    json_write(
        root,
        ".agents/plugins/distribution-identity.json",
        json!({"schemaVersion":1,"algorithm":"sha256-canonical-plugin-tree-v1","generationLength":16,"releaseVersion":"1.0.0","bundleIdentity":bundle_digest,"plugins":[{"name":"maintenance","versionAuthority":"release","version":version,"generation":&digest[..16],"contentSha256":digest}]}),
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
        json!({"schemaVersion":"fixture","harnesses":{}}),
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
#[test]
fn verified_text_payload_and_snapshot_work_without_interpreter_or_repository_scripts() {
    let dir = fixture();
    // Full installer trees stay outside the package. Canonical plugin tests
    // remain content because the preserved plugin identity covers them.
    write(
        dir.path(),
        "scripts/engine.py",
        "raise RuntimeError('must never execute')",
    );
    write(
        dir.path(),
        "plugins/maintenance/tests/test_private.py",
        "private dev fixture",
    );
    fs::create_dir_all(dir.path().join("plugins/maintenance/empty")).unwrap();
    update_plugin_identity(dir.path());
    source::seal(dir.path()).unwrap();
    let bundle = source::load(dir.path()).unwrap();
    assert_eq!(bundle.identity.len(), 64);
    assert!(!bundle.files.keys().any(|p| p.starts_with("scripts/")));
    assert!(bundle
        .files
        .contains_key("plugins/maintenance/tests/test_private.py"));
    let skill = &bundle.catalog["skills"][0];
    assert_eq!(skill["id"], "watcher:housekeeping");
    assert_eq!(skill["plugin"], "maintenance");
    assert_eq!(
        skill["aliases"],
        json!(["maintenance:housekeeping", "watcher:housekeeping"])
    );
    assert_eq!(
        bundle.catalog["attributionOverlays"][0]["data"]["legacy_names"]["old:cleanup"],
        "watcher:housekeeping"
    );
    let second = tempfile::tempdir().unwrap();
    for directory in bundle.manifest["directories"].as_array().unwrap() {
        fs::create_dir_all(second.path().join(directory.as_str().unwrap())).unwrap();
    }
    for (path, bytes) in &bundle.files {
        write(second.path(), path, bytes);
    }
    let offline = source::load(second.path()).unwrap();
    assert_eq!(offline.identity, bundle.identity);
    assert_eq!(offline.catalog, bundle.catalog);
}
#[test]
fn locked_payload_drift_and_missing_offline_content_fail_closed() {
    let dir = fixture();
    let path = dir
        .path()
        .join("plugins/maintenance/skills/housekeeping/SKILL.md");
    fs::write(&path, "modified").unwrap();
    assert_eq!(
        source::load(dir.path()).unwrap_err().code,
        "HARNESS_SOURCE_INVALID"
    );
    fs::remove_file(path).unwrap();
    assert!(source::load(dir.path()).is_err());
}
#[test]
fn portable_text_materialization_has_one_digest() {
    let dir = fixture();
    let old = source::load(dir.path()).unwrap();
    let path = dir
        .path()
        .join("plugins/maintenance/skills/housekeeping/SKILL.md");
    let contents = fs::read_to_string(&path).unwrap().replace('\n', "\r\n");
    fs::write(path, contents).unwrap();
    let new = source::load(dir.path()).unwrap();
    assert_eq!(new.identity, old.identity);
    assert_eq!(new.files, old.files);
}
#[test]
fn inventory_cannot_smuggle_installer_or_parent_paths() {
    for path in [
        "scripts/engine.py",
        "../outside",
        "plugins/maintenance/skills/CON/SKILL.md",
        "C:\\unsafe.py",
    ] {
        let dir = fixture();
        let manifest_path = dir.path().join("distribution-manifest.json");
        let mut value: Value = serde_json::from_slice(&fs::read(&manifest_path).unwrap()).unwrap();
        value["files"]
            .as_array_mut()
            .unwrap()
            .push(json!({"path":path,"sha256":"a".repeat(64)}));
        fs::write(manifest_path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(source::load(dir.path()).is_err(), "path {path}");
    }
}
#[test]
fn duplicate_catalog_names_case_collisions_and_unknown_overlays_fail_closed() {
    let dir = fixture();
    write(
        dir.path(),
        "plugins/maintenance/skills/duplicate/SKILL.md",
        "---\nname: housekeeping\n---\n",
    );
    update_plugin_identity(dir.path());
    assert!(source::seal(dir.path()).is_err());
    let dir = fixture();
    write(
        dir.path(),
        "plugins/maintenance/skills/housekeeping/Refs/a.txt",
        "a",
    );
    write(
        dir.path(),
        "plugins/maintenance/skills/housekeeping/Refs/b.txt",
        "b",
    );
    update_plugin_identity(dir.path());
    source::seal(dir.path()).unwrap();
    // A case-insensitive filesystem cannot represent two case-colliding
    // directories. Exercise the portable manifest boundary on every platform.
    let manifest_path = dir.path().join("distribution-manifest.json");
    let original = fs::read(&manifest_path).unwrap();
    let mut manifest: Value = serde_json::from_slice(&original).unwrap();
    let entry = manifest["files"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|entry| entry["path"] == "plugins/maintenance/skills/housekeeping/Refs/b.txt")
        .unwrap();
    entry["path"] = json!("plugins/maintenance/skills/housekeeping/refs/b.txt");
    fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    assert_eq!(
        source::load(dir.path()).unwrap_err().code,
        "HARNESS_SOURCE_INVALID"
    );
    fs::write(manifest_path, original).unwrap();

    // Retain source-tree collision coverage wherever the filesystem can create
    // distinct directories; do not turn a valid Windows/macOS tree into a failure.
    write(
        dir.path(),
        "plugins/maintenance/skills/housekeeping/refs/c.txt",
        "c",
    );
    let names: std::collections::BTreeSet<_> =
        fs::read_dir(dir.path().join("plugins/maintenance/skills/housekeeping"))
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
    if names.contains(std::ffi::OsStr::new("Refs")) && names.contains(std::ffi::OsStr::new("refs"))
    {
        update_plugin_identity(dir.path());
        assert!(source::seal(dir.path()).is_err());
    }
    let dir = fixture();
    json_write(
        dir.path(),
        "plugins/maintenance/.codex-plugin/skill-watcher.json",
        json!({"schema_version":1,"skills":{"unknown:skill":{}},"legacy_names":{}}),
    );
    update_plugin_identity(dir.path());
    assert!(source::seal(dir.path()).is_err());
}
#[test]
fn missing_runtime_lock_and_manifest_version_mismatch_are_rejected() {
    let dir = fixture();
    let path = dir.path().join("distribution-manifest.json");
    let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    value["runtimeGroups"] = json!([{"id":"watcher","minimumPython":[3,11],"imports":["yaml"],"requirementsLock":"runtimes/watcher/requirements.lock"}]);
    fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(source::load(dir.path()).is_err());
    value["runtimeGroups"] = json!([]);
    value["schemaVersion"] = json!(999);
    fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(source::load(dir.path()).is_err());
}
#[cfg(unix)]
#[test]
fn symlink_payload_and_symlink_root_are_never_followed() {
    use std::os::unix::fs::symlink;
    let dir = fixture();
    let path = dir
        .path()
        .join("plugins/maintenance/skills/housekeeping/SKILL.md");
    let external = tempfile::tempdir().unwrap();
    fs::rename(&path, external.path().join("original")).unwrap();
    symlink(external.path().join("original"), path).unwrap();
    assert!(source::load(dir.path()).is_err());
    let dir = fixture();
    symlink(dir.path(), external.path().join("alias")).unwrap();
    assert!(source::load(&external.path().join("alias")).is_err());
}

#[test]
fn unlisted_importable_runtime_files_are_not_accepted_in_cache() {
    let dir = fixture();
    let path = dir.path().join("distribution-manifest.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    manifest["runtimeGroups"] =
        json!([{"id":"watcher","minimumPython":[3,11],"requirementsLock":null,"imports":[]}]);
    fs::write(path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    write(
        dir.path(),
        "runtimes/watcher/scripts/watcher",
        "# TEST_ONLY runtime entry
",
    );
    source::seal(dir.path()).unwrap();
    source::load(dir.path()).unwrap();
    write(
        dir.path(),
        "runtimes/watcher/scripts/json.py",
        "raise RuntimeError('unlisted shadow module')
",
    );
    assert_eq!(
        source::load(dir.path()).unwrap_err().code,
        "HARNESS_SOURCE_INVALID"
    );
}

#[test]
fn bare_bytecode_beside_scripts_is_rejected_while_pycache_trees_stay_transient() {
    let dir = fixture();
    let path = dir.path().join("distribution-manifest.json");
    let mut manifest: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    manifest["runtimeGroups"] =
        json!([{"id":"watcher","minimumPython":[3,11],"requirementsLock":null,"imports":[]}]);
    fs::write(path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    write(
        dir.path(),
        "runtimes/watcher/scripts/watcher",
        "# TEST_ONLY runtime entry
",
    );
    source::seal(dir.path()).unwrap();
    write(
        dir.path(),
        "runtimes/watcher/scripts/__pycache__/entry.cpython-311.pyc",
        "TEST_ONLY bytecode",
    );
    source::load(dir.path()).unwrap();
    write(
        dir.path(),
        "runtimes/watcher/scripts/json.pyc",
        "TEST_ONLY bytecode",
    );
    assert_eq!(
        source::load(dir.path()).unwrap_err().code,
        "HARNESS_SOURCE_INVALID"
    );
}
