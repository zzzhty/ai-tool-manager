// Only TEST_ONLY fixtures under temporary roots. Link projection is POSIX
// symlink semantics; copy projection (Windows) compiles through the same paths.
use atm_core::projection::ProjectionRegistry;
use atm_core::skills::SkillsService;
use std::fs;
#[cfg(unix)]
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

const FRONT: &str = "---\nname: \"proj-skill\"\ndescription: A TEST_ONLY projection fixture.\n---";

fn write_skill(root: &Path, name: &str) -> PathBuf {
    let dir = root.join(name);
    fs::create_dir_all(dir.join("assets")).unwrap();
    fs::write(dir.join("SKILL.md"), format!("{FRONT}\n# Body\n")).unwrap();
    fs::write(dir.join("assets").join("note.txt"), b"TEST_ONLY").unwrap();
    dir
}

struct Fixture {
    home: tempfile::TempDir,
    sources: tempfile::TempDir,
    registry_root: tempfile::TempDir,
    registry: ProjectionRegistry,
}

fn fixture() -> Fixture {
    let home = tempfile::tempdir().unwrap();
    let sources = tempfile::tempdir().unwrap();
    let registry_root = tempfile::tempdir().unwrap();
    let registry = ProjectionRegistry::at_root(
        registry_root.path().join("private"),
        home.path().to_path_buf(),
    )
    .unwrap();
    Fixture {
        home,
        sources,
        registry_root,
        registry,
    }
}

fn service(fixture: &Fixture) -> SkillsService {
    SkillsService::new(
        fixture.home.path().to_path_buf(),
        fixture.registry_root.path().join("trash"),
    )
    .with_manager_home(None)
    .with_sources_root(Some(fixture.registry.sources_root()))
}

fn zcode_root(fixture: &Fixture) -> PathBuf {
    fixture.home.path().join(".zcode").join("skills")
}

#[test]
fn explicit_roots_ignore_inherited_overrides() {
    const CHILD: &str = "ATM_TEST_ROOT_ISOLATION_CHILD";
    if std::env::var_os(CHILD).is_some() {
        let f = fixture();
        let source = write_skill(f.sources.path(), "src");
        let service = service(&f);
        let inventory = service.inventory().unwrap();
        assert!(inventory
            .roots
            .iter()
            .all(|root| Path::new(&root.path).starts_with(f.home.path())));
        service.install(&source, "claude-code", "local").unwrap();
        service.copy_to("claude-code", "local", "copilot").unwrap();
        let trash = service.uninstall("copilot", "local").unwrap();
        service.restore(&trash).unwrap();
        assert!(f
            .home
            .path()
            .join(".copilot/skills/local/SKILL.md")
            .is_file());
        f.registry
            .publish(
                &source,
                "projected",
                &["claude-code".into(), "copilot".into()],
            )
            .unwrap();
        assert!(f
            .registry
            .refresh(None, false)
            .unwrap()
            .iter()
            .all(|item| item.status == "ok"));
        f.registry.unpublish("projected", true).unwrap();
        // The application's environment-based constructor must still honor overrides.
        let live = SkillsService::from_environment()
            .unwrap()
            .inventory()
            .unwrap();
        for (id, key) in [
            ("copilot", "COPILOT_HOME"),
            ("claude-code", "CLAUDE_CONFIG_DIR"),
        ] {
            assert_eq!(
                Path::new(&live.roots.iter().find(|r| r.id == id).unwrap().path),
                PathBuf::from(std::env::var_os(key).unwrap()).join("skills")
            );
        }
        return;
    }
    // Set overrides only in a child process; Rust's parallel tests share the parent environment.
    let outside = tempfile::tempdir().unwrap();
    let child_home = tempfile::tempdir().unwrap();
    let mut command = std::process::Command::new(std::env::current_exe().unwrap());
    command
        .args([
            "explicit_roots_ignore_inherited_overrides",
            "--exact",
            "--nocapture",
        ])
        .env(CHILD, "1")
        .env("HOME", child_home.path())
        .env("USERPROFILE", child_home.path())
        .env("XDG_DATA_HOME", child_home.path().join("data"))
        .env("LOCALAPPDATA", child_home.path().join("data"))
        .env("ATM_HOME", child_home.path().join("harness"))
        .env("ATM_SKILLS_LIVE", "0")
        .env("ATM_ENGINE_LIVE", "0")
        .env_remove("ATM_TEST_ENGINE_CHECKOUT");
    for key in [
        "CLAUDE_CONFIG_DIR",
        "COPILOT_HOME",
        "CODEX_HOME",
        "GEMINI_CLI_HOME",
        "OPENCLAW_STATE_DIR",
        "PI_CODING_AGENT_DIR",
    ] {
        let path = outside.path().join(key);
        fs::create_dir(&path).unwrap();
        fs::write(path.join("sentinel"), "TEST_ONLY untouched").unwrap();
        command.env(key, path);
    }
    #[cfg(unix)]
    {
        // A forked child inherits a copy of every open descriptor, so spawning
        // this binary while other parallel tests hold advisory locks pins those
        // locks until exec and makes their next acquisition fail with VAULT_BUSY.
        // Close the inherited descriptors before exec to keep the spawn inert.
        use std::os::unix::process::CommandExt;
        unsafe {
            command.pre_exec(|| {
                if libc::close_range(3, libc::c_uint::MAX, 0) != 0 {
                    for fd in 3..1024 {
                        libc::close(fd);
                    }
                }
                Ok(())
            });
        }
    }
    let output = command.output().unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    for entry in fs::read_dir(outside.path()).unwrap() {
        let path = entry.unwrap().path();
        assert_eq!(fs::read_dir(&path).unwrap().count(), 1);
        assert_eq!(
            fs::read_to_string(path.join("sentinel")).unwrap(),
            "TEST_ONLY untouched"
        );
    }
}

#[test]
fn publish_adopts_source_and_projects_links_that_inventory_classifies() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "my-source");
    let projected = f
        .registry
        .publish(&source, "proj-skill", &["zcode".into(), "copilot".into()])
        .unwrap();
    assert_eq!(projected, vec!["zcode/proj-skill", "copilot/proj-skill"]);
    // The link resolves into the canonical sources area.
    assert!(zcode_root(&f).join("proj-skill").join("SKILL.md").is_file());
    let resolved = fs::canonicalize(zcode_root(&f).join("proj-skill")).unwrap();
    if cfg!(unix) {
        assert!(resolved.starts_with(fs::canonicalize(f.registry.sources_root()).unwrap()));
    }
    // Inventory classifies it as an lkm projection.
    let snapshot = service(&f).inventory().unwrap();
    let entry = snapshot
        .roots
        .iter()
        .find(|root| root.id == "zcode")
        .unwrap()
        .entries
        .iter()
        .find(|entry| entry.name == "proj-skill")
        .unwrap();
    assert_eq!(entry.kind, "lkm_projected");
    assert_eq!(entry.display_name.as_deref(), Some("proj-skill"));
    // Registry lists one source with two projections.
    let records = f.registry.list().unwrap();
    assert_eq!(records.len(), 1);
    assert_eq!(
        records[0].materialization,
        atm_core::projection::materialization_mode()
    );
    assert_eq!(records[0].projections.len(), 2);
}

#[cfg(unix)]
#[test]
fn publish_rejects_unauditable_sources_and_leaves_nothing_adopted() {
    let f = fixture();
    // No SKILL.md.
    let plain = f.sources.path().join("plain");
    fs::create_dir_all(&plain).unwrap();
    assert_eq!(
        f.registry
            .publish(&plain, "a", &["zcode".into()])
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
    // A nested link fails the audit and rolls back the adoption.
    let linked = write_skill(f.sources.path(), "linked");
    symlink(&plain, linked.join("nested")).unwrap();
    assert_eq!(
        f.registry
            .publish(&linked, "b", &["zcode".into()])
            .unwrap_err()
            .code,
        "SKILLS_UNAUDITABLE"
    );
    assert!(f.registry.list().unwrap().is_empty());
    for name in ["a", "b"] {
        assert!(!f.registry.sources_root().join(name).exists());
    }
    assert!(!zcode_root(&f).exists());
}

#[cfg(unix)]
#[test]
fn project_appends_rolls_back_intent_and_refuses_repetition() {
    use std::os::unix::fs::PermissionsExt;
    let f = fixture();
    let source = write_skill(f.sources.path(), "src");
    f.registry
        .publish(&source, "extra", &["zcode".into()])
        .unwrap();
    // Repeating the same root is refused without touching the registry.
    assert_eq!(
        f.registry.project("extra", "zcode").unwrap_err().code,
        "SKILLS_TAKEN"
    );
    assert_eq!(f.registry.list().unwrap()[0].projections.len(), 1);
    // A root whose parent cannot host the link rolls the persisted intent back.
    let copilot = f.home.path().join(".copilot");
    fs::create_dir(&copilot).unwrap();
    fs::set_permissions(&copilot, fs::Permissions::from_mode(0o555)).unwrap();
    let error = f.registry.project("extra", "copilot").unwrap_err();
    fs::set_permissions(&copilot, fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(error.code, "ACCESS_DENIED");
    let records = f.registry.list().unwrap();
    assert_eq!(records[0].projections.len(), 1);
    assert_eq!(records[0].projections[0].root_id, "zcode");
    // The healthy projection and canonical copy survive the rollback.
    assert!(zcode_root(&f).join("extra/SKILL.md").is_file());
    assert!(f.registry.sources_root().join("extra/SKILL.md").is_file());
    // Once the root is usable again the append succeeds.
    assert_eq!(
        f.registry.project("extra", "copilot").unwrap(),
        "copilot/extra"
    );
    assert!(f
        .registry
        .check(None)
        .unwrap()
        .iter()
        .all(|item| item.status == "ok"));
}

#[cfg(unix)]
#[test]
fn unproject_check_and_refresh_refuse_foreign_occupied_projection_slots() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "src");
    f.registry
        .publish(&source, "owned", &["zcode".into()])
        .unwrap();
    let target = zcode_root(&f).join("owned");
    // A plain directory in the registered slot is reported and never replaced.
    fs::remove_file(&target).unwrap();
    fs::create_dir(&target).unwrap();
    fs::write(target.join("user-edit"), b"TEST_ONLY").unwrap();
    assert_eq!(
        f.registry.check(Some("owned")).unwrap()[0].status,
        "modified_copy"
    );
    assert_eq!(
        f.registry
            .unproject("owned", "zcode", true)
            .unwrap_err()
            .code,
        "SKILLS_TAKEN"
    );
    assert_eq!(
        f.registry.refresh(Some("owned"), true).unwrap_err().code,
        "SKILLS_TAKEN"
    );
    assert_eq!(fs::read(target.join("user-edit")).unwrap(), b"TEST_ONLY");
    // A foreign link counts as a broken projection but is still never removed.
    fs::remove_dir_all(&target).unwrap();
    let foreign = write_skill(f.sources.path(), "foreign-dir");
    symlink(&foreign, &target).unwrap();
    assert_eq!(
        f.registry.check(Some("owned")).unwrap()[0].status,
        "broken_link"
    );
    assert_eq!(
        f.registry
            .unproject("owned", "zcode", true)
            .unwrap_err()
            .code,
        "SKILLS_TAKEN"
    );
    assert_eq!(
        f.registry.refresh(Some("owned"), true).unwrap_err().code,
        "SKILLS_TAKEN"
    );
    assert_eq!(fs::read_link(&target).unwrap(), foreign);
    // The registry and canonical copy stay intact for manual resolution.
    assert_eq!(f.registry.list().unwrap()[0].projections.len(), 1);
    assert!(f.registry.sources_root().join("owned/SKILL.md").is_file());
}

#[test]
fn unpublish_with_projections_keeps_the_remaining_record_when_one_slot_is_foreign() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "src");
    f.registry
        .publish(&source, "dual", &["zcode".into(), "copilot".into()])
        .unwrap();
    // The second projection's slot is occupied by unrelated content.
    let occupied = f.home.path().join(".copilot").join("skills").join("dual");
    // Keep the original directory alive on Windows so its identity cannot be
    // reused by the foreign directory that takes its place.
    fs::rename(&occupied, f.home.path().join("displaced-projection")).unwrap();
    fs::create_dir(&occupied).unwrap();
    fs::write(occupied.join("keep"), b"TEST_ONLY").unwrap();
    assert_eq!(
        f.registry.unpublish("dual", true).unwrap_err().code,
        if cfg!(windows) {
            "PROJECTION_OWNERSHIP"
        } else {
            "SKILLS_TAKEN"
        }
    );
    // The zcode projection was torn down and unregistered first; the record
    // keeps exactly the blocked copilot projection with its source intact.
    let records = f.registry.list().unwrap();
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].projections.len(), 1);
    assert_eq!(records[0].projections[0].root_id, "copilot");
    assert!(!zcode_root(&f).join("dual").exists());
    assert!(f.registry.sources_root().join("dual/SKILL.md").is_file());
    assert_eq!(fs::read(occupied.join("keep")).unwrap(), b"TEST_ONLY");
    // Clearing the foreign entry lets unpublish finish cleanly.
    fs::remove_dir_all(&occupied).unwrap();
    f.registry.unpublish("dual", true).unwrap();
    assert!(f.registry.list().unwrap().is_empty());
    assert!(!f.registry.sources_root().join("dual").exists());
}

#[test]
fn publish_rolls_back_projections_and_adoption_on_failure() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "good");
    // Pre-occupy the copilot root so the second projection fails.
    let copilot = f.home.path().join(".copilot").join("skills");
    fs::create_dir_all(&copilot).unwrap();
    fs::create_dir_all(copilot.join("taken")).unwrap();
    let error = f
        .registry
        .publish(&source, "taken", &["zcode".into(), "copilot".into()])
        .unwrap_err();
    assert_eq!(error.code, "SKILLS_TAKEN");
    // zcode projection was rolled back and no canonical copy remains.
    assert!(!zcode_root(&f).join("taken").exists());
    assert!(!f.registry.sources_root().join("taken").exists());
    assert!(f.registry.list().unwrap().is_empty());
}

#[cfg(unix)]
#[test]
fn check_reports_ok_broken_and_refresh_repairs() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "skill-a");
    f.registry
        .publish(&source, "skill-a", &["zcode".into()])
        .unwrap();
    assert!(f
        .registry
        .check(None)
        .unwrap()
        .iter()
        .all(|item| item.status == "ok"));
    // Break the link, then refresh repairs it.
    fs::remove_file(zcode_root(&f).join("skill-a")).unwrap();
    let statuses: Vec<_> = f
        .registry
        .check(None)
        .unwrap()
        .into_iter()
        .map(|item| item.status.to_owned())
        .collect();
    assert_eq!(statuses, ["broken_link"]);
    let repaired = f.registry.refresh(None, false).unwrap();
    assert!(repaired.iter().all(|item| item.status == "ok"));
    assert!(zcode_root(&f).join("skill-a").join("SKILL.md").is_file());
    // Editing through the link is canonical content; check stays ok.
    fs::write(zcode_root(&f).join("skill-a").join("EDITED"), b"TEST_ONLY").unwrap();
    assert!(f
        .registry
        .check(None)
        .unwrap()
        .iter()
        .all(|item| item.status == "ok"));
    assert!(f
        .registry
        .sources_root()
        .join("skill-a")
        .join("EDITED")
        .exists());
}

#[cfg(unix)]
#[test]
fn unproject_removes_only_its_own_links_and_unpublish_enforces_projection_drain() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "skill-b");
    f.registry
        .publish(&source, "skill-b", &["zcode".into(), "copilot".into()])
        .unwrap();
    // A foreign link is refused.
    let foreign = write_skill(f.sources.path(), "foreign-target");
    symlink(&foreign, zcode_root(&f).join("foreign")).unwrap();
    assert_eq!(
        f.registry
            .unproject_link("zcode", "foreign", false)
            .unwrap_err()
            .code,
        "SKILLS_MISSING"
    );
    assert!(zcode_root(&f).join("foreign").exists());
    // unpublish with projections still present is refused.
    assert_eq!(
        f.registry.unpublish("skill-b", false).unwrap_err().code,
        "PROJECTION_TARGET"
    );
    f.registry.unproject("skill-b", "zcode", false).unwrap();
    assert!(!zcode_root(&f).join("skill-b").exists());
    assert!(f
        .registry
        .sources_root()
        .join("skill-b")
        .join("SKILL.md")
        .is_file());
    f.registry.unproject("skill-b", "copilot", false).unwrap();
    f.registry.unpublish("skill-b", false).unwrap();
    assert!(f.registry.list().unwrap().is_empty());
    assert!(!f.registry.sources_root().join("skill-b").exists());
    // Unknown projection handle.
    assert_eq!(
        f.registry
            .unproject("skill-b", "zcode", false)
            .unwrap_err()
            .code,
        "SKILLS_MISSING"
    );
}

#[test]
fn inventory_uninstall_refuses_projection_entries() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "locked");
    f.registry
        .publish(&source, "locked", &["zcode".into()])
        .unwrap();
    let error = service(&f).uninstall("zcode", "locked").unwrap_err();
    assert_eq!(error.code, "SKILLS_PROJECTED");
    assert!(zcode_root(&f).join("locked").exists());
}

#[test]
fn invalid_names_duplicate_sources_and_missing_targets_fail_closed() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "src");
    assert_eq!(
        f.registry
            .publish(&source, ".hidden", &["zcode".into()])
            .unwrap_err()
            .code,
        "SKILLS_NAME"
    );
    f.registry
        .publish(&source, "dup", &["zcode".into()])
        .unwrap();
    assert_eq!(
        f.registry
            .publish(&source, "dup", &["copilot".into()])
            .unwrap_err()
            .code,
        "SKILLS_TAKEN"
    );
    assert_eq!(
        f.registry
            .publish(&source, "no-target", &[])
            .unwrap_err()
            .code,
        "PROJECTION_TARGET"
    );
    assert_eq!(
        f.registry
            .publish(&source, "bad-root", &["not-a-root".into()])
            .unwrap_err()
            .code,
        "SKILLS_NAME"
    );
    assert_eq!(
        f.registry
            .project("missing-source", "zcode")
            .unwrap_err()
            .code,
        "SKILLS_MISSING"
    );
}

// Explicit live check against the real environment; read-only, opt-in.
#[test]
fn live_projection_check_when_explicitly_requested() {
    if std::env::var("ATM_SKILLS_LIVE")
        .map(|value| value != "1")
        .unwrap_or(true)
    {
        return;
    }
    let registry = ProjectionRegistry::from_environment().unwrap();
    let items = registry.check(None).unwrap();
    for item in items {
        println!(
            "[{}] {} -> {}/{}",
            item.status, item.source, item.root_id, item.link_name
        );
    }
}

fn remove_projection(path: &Path) {
    if cfg!(windows) {
        fs::remove_dir_all(path).unwrap();
    } else {
        fs::remove_file(path).unwrap();
    }
}

#[test]
fn missing_projection_can_be_removed_and_missing_source_unpublished() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "missing");
    f.registry
        .publish(&source, "missing", &["zcode".into()])
        .unwrap();
    remove_projection(&zcode_root(&f).join("missing"));
    f.registry.unproject("missing", "zcode", false).unwrap();
    assert!(f.registry.list().unwrap()[0].projections.is_empty());
    fs::remove_dir_all(f.registry.sources_root().join("missing")).unwrap();
    f.registry.unpublish("missing", false).unwrap();
    assert!(f.registry.list().unwrap().is_empty());
}

#[test]
fn invalid_registry_never_becomes_an_empty_registry() {
    let f = fixture();
    let registry = f
        .registry
        .sources_root()
        .parent()
        .unwrap()
        .join("registry.json");
    fs::create_dir(&registry).unwrap();
    assert!(f.registry.list().is_err());
    fs::remove_dir(&registry).unwrap();
    fs::write(&registry, b"not json").unwrap();
    assert!(f.registry.list().is_err());
    fs::write(
        &registry,
        br#"[{"name":"../escape","materialization":"copy","projections":[]}]"#,
    )
    .unwrap();
    assert!(f.registry.list().is_err());
}

#[test]
fn registry_lock_blocks_another_instance() {
    let f = fixture();
    let root = f.registry.sources_root().parent().unwrap().to_path_buf();
    let _lock = atm_core::windows::open_lock(&root.join("registry.lock")).unwrap();
    let second = ProjectionRegistry::at_root(root, f.home.path().to_path_buf()).unwrap();
    assert!(second.list().is_err());
}

#[cfg(unix)]
#[test]
fn force_refresh_never_replaces_foreign_or_engine_link() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "owned", &["zcode".into()])
        .unwrap();
    let target = zcode_root(&f).join("owned");
    fs::remove_file(&target).unwrap();
    let harness = write_skill(f.home.path(), ".atm");
    symlink(&harness, &target).unwrap();
    assert!(f.registry.refresh(Some("owned"), true).is_err());
    assert_eq!(fs::read_link(&target).unwrap(), harness);
}

#[cfg(windows)]
#[test]
fn copied_projection_modification_requires_force_and_is_bounded() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "copy", &["zcode".into()])
        .unwrap();
    let target = zcode_root(&f).join("copy");
    fs::OpenOptions::new()
        .write(true)
        .open(target.join("SKILL.md"))
        .unwrap()
        .set_len(1024 * 1024 * 1024)
        .unwrap();
    assert_eq!(
        f.registry.check(Some("copy")).unwrap()[0].status,
        "modified_copy"
    );
    assert!(f.registry.unproject("copy", "zcode", false).is_err());
    assert_eq!(
        service(&f).uninstall("zcode", "copy").unwrap_err().code,
        "SKILLS_PROJECTED"
    );
    f.registry.refresh(Some("copy"), true).unwrap();
    assert_eq!(f.registry.check(Some("copy")).unwrap()[0].status, "ok");
}

#[cfg(unix)]
#[test]
fn private_registry_root_is_created_without_broadening_existing_permissions() {
    use std::os::unix::fs::PermissionsExt;
    let f = fixture();
    let root = f.registry.sources_root().parent().unwrap().to_path_buf();
    assert_eq!(
        fs::metadata(&root).unwrap().permissions().mode() & 0o777,
        0o700
    );
    fs::set_permissions(&root, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(ProjectionRegistry::at_root(root, f.home.path().to_path_buf()).is_err());
}

#[cfg(windows)]
#[test]
fn force_refuses_replaced_directory_and_legacy_missing_receipt() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "copy", &["zcode".into()])
        .unwrap();
    let target = zcode_root(&f).join("copy");
    fs::rename(&target, zcode_root(&f).join("original")).unwrap();
    write_skill(&zcode_root(&f), "copy");
    assert_eq!(
        f.registry.check(Some("copy")).unwrap()[0].status,
        "ownership_unknown"
    );
    assert!(f.registry.unproject("copy", "zcode", true).is_err());
    assert_eq!(
        f.registry.refresh(Some("copy"), true).unwrap()[0].status,
        "ownership_unknown"
    );
    assert!(target.join("SKILL.md").exists());
    let registry = f
        .registry
        .sources_root()
        .parent()
        .unwrap()
        .join("registry.json");
    let mut records: serde_json::Value =
        serde_json::from_slice(&fs::read(&registry).unwrap()).unwrap();
    records[0]["projections"][0]
        .as_object_mut()
        .unwrap()
        .remove("directoryIdentity");
    fs::write(&registry, serde_json::to_vec(&records).unwrap()).unwrap();
    assert!(f.registry.unproject("copy", "zcode", true).is_err());
}

#[test]
fn native_install_cannot_occupy_missing_registered_projection() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "reserved", &["zcode".into()])
        .unwrap();
    remove_projection(&zcode_root(&f).join("reserved"));
    assert_eq!(
        service(&f)
            .install(&source, "zcode", "reserved")
            .unwrap_err()
            .code,
        "SKILLS_PROJECTED"
    );
}

#[test]
fn publish_cannot_adopt_engine_canonical_source() {
    let f = fixture();
    let source = write_skill(&f.home.path().join(".atm/repo"), "source");
    assert_eq!(
        f.registry
            .publish(&source, "copy", &["zcode".into()])
            .unwrap_err()
            .code,
        "SKILLS_ENGINE_LOCKED"
    );
}

#[test]
fn refresh_recreates_a_deleted_skills_root() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "owned", &["zcode".into()])
        .unwrap();
    remove_projection(&zcode_root(&f).join("owned"));
    fs::remove_dir(zcode_root(&f)).unwrap();
    let items = f.registry.refresh(Some("owned"), false).unwrap();
    assert!(items.iter().all(|item| item.status == "ok"));
    assert!(zcode_root(&f).join("owned/SKILL.md").is_file());
    assert_eq!(fs::read_dir(zcode_root(&f)).unwrap().count(), 1);
}

#[cfg(unix)]
#[test]
fn refresh_refuses_a_replaced_root_link_without_touching_foreign_content() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "owned", &["zcode".into()])
        .unwrap();
    remove_projection(&zcode_root(&f).join("owned"));
    fs::remove_dir(zcode_root(&f)).unwrap();
    let foreign = tempfile::tempdir().unwrap();
    fs::write(
        foreign.path().join("TEST_ONLY_marker"),
        b"TEST_ONLY_preserve",
    )
    .unwrap();
    symlink(foreign.path(), zcode_root(&f)).unwrap();
    assert!(f.registry.refresh(Some("owned"), true).is_err());
    assert_eq!(fs::read_dir(foreign.path()).unwrap().count(), 1);
    assert_eq!(
        fs::read(foreign.path().join("TEST_ONLY_marker")).unwrap(),
        b"TEST_ONLY_preserve"
    );
}

#[cfg(windows)]
fn copy_refresh_fixture() -> (Fixture, PathBuf, PathBuf, PathBuf) {
    let f = fixture();
    let source = write_skill(f.sources.path(), "source");
    f.registry
        .publish(&source, "owned", &["zcode".into()])
        .unwrap();
    let target = zcode_root(&f).join("owned");
    let canonical = f.registry.sources_root().join("owned");
    let registry = f
        .registry
        .sources_root()
        .parent()
        .unwrap()
        .join("registry.json");
    (f, target, canonical, registry)
}

#[cfg(windows)]
fn assert_copy_refresh_preserved(
    f: &Fixture,
    target: &Path,
    registry: &Path,
    old: &[u8],
    receipt: &[u8],
) {
    assert_eq!(fs::read(target.join("SKILL.md")).unwrap(), old);
    assert_eq!(fs::read(registry).unwrap(), receipt);
    assert_ne!(
        f.registry.check(Some("owned")).unwrap()[0].status,
        "ownership_unknown"
    );
    assert_eq!(
        fs::read_dir(zcode_root(f)).unwrap().count(),
        1,
        "staging/retired cleanup"
    );
}

#[cfg(windows)]
#[test]
fn forced_refresh_preserves_old_copy_and_receipt_when_new_source_exceeds_limits() {
    for excessive_files in [false, true] {
        let (f, target, canonical, registry) = copy_refresh_fixture();
        fs::write(target.join("SKILL.md"), b"TEST_ONLY_user_edit").unwrap();
        let old = fs::read(target.join("SKILL.md")).unwrap();
        let receipt = fs::read(&registry).unwrap();
        if excessive_files {
            for n in 0..513 {
                fs::write(canonical.join(format!("extra-{n}")), b"TEST_ONLY").unwrap();
            }
        } else {
            fs::File::create(canonical.join("oversize"))
                .unwrap()
                .set_len(8 * 1024 * 1024 + 1)
                .unwrap();
        }
        assert_eq!(
            f.registry.refresh(Some("owned"), true).unwrap_err().code,
            "SKILLS_LIMIT"
        );
        assert_copy_refresh_preserved(&f, &target, &registry, &old, &receipt);
    }
}

#[cfg(windows)]
#[test]
fn forced_refresh_preserves_old_copy_on_copy_io_or_handoff_failure() {
    use std::os::windows::fs::OpenOptionsExt;
    for lock_source in [false, true] {
        let (f, target, canonical, registry) = copy_refresh_fixture();
        fs::write(target.join("SKILL.md"), b"TEST_ONLY_user_edit").unwrap();
        let old = fs::read(target.join("SKILL.md")).unwrap();
        let receipt = fs::read(&registry).unwrap();
        let locked = if lock_source {
            canonical.join("SKILL.md")
        } else {
            target.join("SKILL.md")
        };
        // Source lock blocks copying. Target lock permits reads but denies delete/rename.
        let guard = fs::OpenOptions::new()
            .read(true)
            .share_mode(if lock_source { 0 } else { 1 })
            .open(locked)
            .unwrap();
        assert!(f.registry.refresh(Some("owned"), true).is_err());
        drop(guard);
        assert_copy_refresh_preserved(&f, &target, &registry, &old, &receipt);
    }
}

#[cfg(windows)]
#[test]
fn refresh_rolls_back_content_and_receipt_when_registry_save_fails() {
    let (f, target, canonical, registry) = copy_refresh_fixture();
    fs::write(canonical.join("SKILL.md"), b"TEST_ONLY_new_source").unwrap();
    let old = fs::read(target.join("SKILL.md")).unwrap();
    let receipt = fs::read(&registry).unwrap();
    let permissions = fs::metadata(&registry).unwrap().permissions();
    let mut readonly = permissions.clone();
    readonly.set_readonly(true);
    fs::set_permissions(&registry, readonly).unwrap();
    let result = f.registry.refresh(Some("owned"), true);
    fs::set_permissions(&registry, permissions).unwrap();
    assert!(result.is_err());
    assert_copy_refresh_preserved(&f, &target, &registry, &old, &receipt);
}

#[cfg(windows)]
#[test]
fn successful_copy_refresh_updates_directory_identity_and_cleans_retired_copy() {
    let (f, target, canonical, registry) = copy_refresh_fixture();
    let before = fs::read(&registry).unwrap();
    fs::write(canonical.join("SKILL.md"), b"TEST_ONLY_new_source").unwrap();
    assert_eq!(
        f.registry.refresh(Some("owned"), false).unwrap()[0].status,
        "modified_copy"
    );
    assert_ne!(
        fs::read(target.join("SKILL.md")).unwrap(),
        b"TEST_ONLY_new_source"
    );
    assert_eq!(
        f.registry.refresh(Some("owned"), true).unwrap()[0].status,
        "ok"
    );
    assert_eq!(
        fs::read(target.join("SKILL.md")).unwrap(),
        b"TEST_ONLY_new_source"
    );
    assert_ne!(fs::read(&registry).unwrap(), before);
    assert_eq!(fs::read_dir(zcode_root(&f)).unwrap().count(), 1);
    f.registry.unproject("owned", "zcode", false).unwrap();
}

#[cfg(windows)]
#[test]
fn forced_refresh_preserves_old_copy_when_new_source_contains_a_link() {
    let (f, target, canonical, registry) = copy_refresh_fixture();
    fs::write(target.join("SKILL.md"), b"TEST_ONLY_user_edit").unwrap();
    let old = fs::read(target.join("SKILL.md")).unwrap();
    let receipt = fs::read(&registry).unwrap();
    std::os::windows::fs::symlink_file(canonical.join("SKILL.md"), canonical.join("linked.md"))
        .unwrap();
    assert_eq!(
        f.registry.refresh(Some("owned"), true).unwrap_err().code,
        "SKILLS_UNAUDITABLE"
    );
    assert_copy_refresh_preserved(&f, &target, &registry, &old, &receipt);
}

#[cfg(unix)]
#[test]
fn publishing_and_projecting_cannot_enter_an_aliased_shared_agent_root() {
    let f = fixture();
    let shared = f.home.path().join(".agents/skills");
    let kept = write_skill(&shared, "kept");
    let source = write_skill(f.sources.path(), "source");
    fs::create_dir_all(f.home.path().join(".zcode")).unwrap();
    symlink(&shared, zcode_root(&f)).unwrap();
    assert_eq!(
        f.registry
            .publish(&source, "new", &["zcode".into()])
            .unwrap_err()
            .code,
        "SKILLS_PROTECTED"
    );
    assert!(!f.registry.sources_root().join("new").exists());
    f.registry
        .publish(&source, "ordinary", &["copilot".into()])
        .unwrap();
    assert_eq!(
        f.registry.project("ordinary", "zcode").unwrap_err().code,
        "SKILLS_PROTECTED"
    );
    assert_eq!(
        f.registry
            .publish(&kept, "adopt-shared", &["copilot".into()])
            .unwrap_err()
            .code,
        "SKILLS_PROTECTED"
    );
    assert_eq!(fs::read_dir(&shared).unwrap().count(), 1);
    assert_eq!(
        fs::read(kept.join("assets/note.txt")).unwrap(),
        b"TEST_ONLY"
    );
    assert_eq!(f.registry.list().unwrap()[0].projections.len(), 1);
}
