use atm_core::distribution::{
    source::{self, hub},
    Service,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};
use tempfile::TempDir;

fn write(root: &Path, path: &str, value: impl AsRef<[u8]>) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, value).unwrap();
}
fn json_write(root: &Path, path: &str, value: Value) {
    write(root, path, serde_json::to_vec_pretty(&value).unwrap());
}
fn fixture() -> TempDir {
    let temp = TempDir::new().unwrap();
    let root = temp.path();
    write(root, "VERSION", b"1.2.0\n");
    write(root, "LICENSE", b"TEST_ONLY license\n");
    write(
        root,
        "agents/global-instructions.md",
        b"TEST_ONLY instructions\n",
    );
    write(
        root,
        "agents/operating-principles.md",
        b"TEST_ONLY support\n",
    );
    write(root,"plugins/demo/skills/test-only/SKILL.md",b"---\nname: test-only\ndescription: Synthetic contract fixture\n---\nExplicit invocation only.\n");
    json_write(
        root,
        "plugins/demo/.codex-plugin/plugin.json",
        json!({"name":"demo","version":"pending","skills":"./skills/"}),
    );
    let declaration = json!({"schemaVersion":1,"product":"omh-content","releaseVersion":"1.2.0","packages":[{"name":"demo","path":"plugins/demo","kind":"skills"}],"runtimeGroups":[],"runtimeBindings":{},"historicalIdentities":{},"compositions":{"default":["demo"]}});
    json_write(root, "content-manifest.json", declaration);
    // Legacy manifest supports the existing plugin identity developer API only;
    // it is deliberately absent from the exported archive.
    json_write(
        root,
        "distribution-manifest.json",
        json!({"schemaVersion":1,"product":"atm-harness-distribution","algorithm":"sha256-atm-distribution-v1","releaseVersion":"1.2.0","packages":[{"name":"demo","path":"plugins/demo","kind":"skills"}],"files":[]}),
    );
    seal_plugin(root);
    temp
}
fn seal_plugin(root: &Path) {
    let hash = source::plugin_content_identity(root, "demo", "1.2.0").unwrap();
    let version = format!("1.2.0+codex.{}", &hash[..16]);
    let path = root.join("plugins/demo/.codex-plugin/plugin.json");
    let mut plugin: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    plugin["version"] = json!(version);
    fs::write(path, serde_json::to_vec_pretty(&plugin).unwrap()).unwrap();
    json_write(
        root,
        ".agents/plugins/marketplace.json",
        json!({"name":"atm-harness","plugins":[{"name":"demo","source":{"source":"local","path":"./plugins/demo"}}]}),
    );
    json_write(
        root,
        ".agents/plugins/install-manifest.json",
        json!({"harness":"codex","marketplace":"atm-harness","plugins":[{"name":"demo","install":true,"check":true}]}),
    );
    let items = json!([{"name":"demo","version":version,"contentSha256":hash}]);
    let digest=format!("sha256:{:x}",Sha256::digest(serde_json::to_vec(&json!({"algorithm":"sha256-canonical-plugin-tree-v1","releaseVersion":"1.2.0","plugins":items})).unwrap()));
    json_write(
        root,
        ".agents/plugins/distribution-identity.json",
        json!({"schemaVersion":1,"algorithm":"sha256-canonical-plugin-tree-v1","generationLength":16,"releaseVersion":"1.2.0","bundleIdentity":digest,"plugins":[{"name":"demo","versionAuthority":"release","version":version,"generation":&hash[..16],"contentSha256":hash}]}),
    );
}
fn export(root: &Path, archive: &Path) -> atm_core::Result<Value> {
    hub::export(
        root,
        archive,
        "https://github.com/TEST_ONLY/content",
        &"a".repeat(40),
        "https://github.com/TEST_ONLY/content/releases/download/v1.2.0/content.omh",
        "default",
    )
}
fn lock_path(archive: &Path) -> PathBuf {
    archive.with_extension("lock.json")
}

#[test]
fn explicit_archive_round_trip_is_inert_offline_and_uses_existing_ownership() {
    let source = fixture();
    let temp = TempDir::new().unwrap();
    let archive = temp.path().join("content.omh");
    export(source.path(), &archive).unwrap();
    let lock = hub::read_lock(&lock_path(&archive)).unwrap();
    let manager = temp.path().join("manager");
    let user = temp.path().join("user");
    let service = Service::new(manager.clone(), user.clone()).unwrap();
    let imported = service.import_content(&lock, Some(&archive)).unwrap();
    assert_eq!(imported["selected"], false);
    assert!(!user.exists());
    assert!(!manager.join("state/distribution.json").exists());
    let cache = PathBuf::from(imported["source"].as_str().unwrap());
    let bundle = source::load(&cache).unwrap();
    assert_eq!(bundle.identity, lock.content_identity);
    assert!(!cache.join("distribution-manifest.json").exists());
    assert!(!cache.join(".agents/harnesses").exists());
    fs::remove_file(archive).unwrap(); // A verified cache needs no download or interpreter.
    assert_eq!(hub::fetch(&lock, &cache).unwrap().identity, bundle.identity);
    write(&cache, "plugins/demo/.codex-plugin/hooks.json", b"{}");
    assert!(hub::fetch(&lock, &cache).is_err());
    fs::remove_file(cache.join("plugins/demo/.codex-plugin/hooks.json")).unwrap();
    service.bootstrap(&cache, false).unwrap();
    service
        .execute("install", &["claude-code".into(), "codex".into()])
        .unwrap();
    assert_eq!(service.status().unwrap()["hooksEnabled"], false);
    assert!(service
        .plan("refresh", &["claude-code".into(), "codex".into()])
        .unwrap()
        .files
        .is_empty());
    assert!(!user.join(".codex/hooks.json").exists());
    write(&user, ".claude/skills/test-only/SKILL.md", b"user work\n");
    assert_eq!(
        service
            .execute("refresh", &["claude-code".into()])
            .unwrap_err()
            .code,
        "HARNESS_CONFLICT"
    );
    assert_eq!(
        fs::read(user.join(".claude/skills/test-only/SKILL.md")).unwrap(),
        b"user work\n"
    );
}

#[test]
fn unknown_install_fields_hook_capabilities_and_bad_compositions_cannot_export() {
    for change in ["install", "hook", "composition"] {
        let source = fixture();
        let root = source.path();
        let temp = TempDir::new().unwrap();
        let archive = temp.path().join("rejected.omh");
        if change == "hook" {
            let path = root.join("plugins/demo/.codex-plugin/plugin.json");
            let mut plugin: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            plugin["hooks"] = json!("./hooks.json");
            fs::write(path, serde_json::to_vec(&plugin).unwrap()).unwrap();
            seal_plugin(root);
        } else {
            let path = root.join("content-manifest.json");
            let mut manifest: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
            if change == "install" {
                manifest["installScript"] = json!("payload.py");
            } else {
                manifest["compositions"]["default"] = json!(["unknown"]);
            }
            fs::write(path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        }
        assert!(export(root, &archive).is_err(), "{change}");
        assert!(!archive.exists());
    }
}

#[test]
fn corrupt_archives_unknown_fields_and_existing_user_destinations_are_preserved() {
    let source = fixture();
    let temp = TempDir::new().unwrap();
    let archive = temp.path().join("content.omh");
    export(source.path(), &archive).unwrap();
    let lock = hub::read_lock(&lock_path(&archive)).unwrap();
    let original = fs::read(&archive).unwrap();
    let out = temp.path().join("output");
    for change in ["bytes", "unknown", "traversal", "duplicate"] {
        let mut value: Value = serde_json::from_slice(&original).unwrap();
        match change {
            "bytes" => value["files"][0]["base64"] = json!("dGFtcGVyZWQ="),
            "unknown" => value["installScript"] = json!("payload.py"),
            "traversal" => value["files"][0]["path"] = json!("../outside"),
            "duplicate" => {
                let first = value["files"][0].clone();
                value["files"].as_array_mut().unwrap().push(first);
            }
            _ => unreachable!(),
        }
        let data = serde_json::to_vec(&value).unwrap();
        fs::write(&archive, &data).unwrap();
        let mut altered = lock.clone();
        altered.archive_sha256 = format!("{:x}", Sha256::digest(&data));
        assert!(
            hub::import_archive(&archive, &altered, &out).is_err(),
            "{change}"
        );
        assert!(!out.exists());
        assert!(!temp.path().join("outside").exists());
    }
    fs::write(&archive, original).unwrap();
    write(&out, "user.txt", b"keep me");
    assert!(hub::import_archive(&archive, &lock, &out).is_err());
    assert_eq!(fs::read(out.join("user.txt")).unwrap(), b"keep me");
}
