#![cfg(any(target_os = "linux", target_os = "macos"))]
// Only TEST_ONLY fixtures under temporary roots. No real harness directories,
// no atm-harness installation and no network are touched. Link classification
// is POSIX symlink semantics; Windows junctions compile via the same code paths.
use atm_core::projection::ProjectionRegistry;
use atm_core::skills::{SkillEntryView, SkillsInventoryView, SkillsService};
use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};

const FRONT: &str =
    "---\nname: \"test-skill\"\ndescription: A TEST_ONLY skill used by fixtures.\n---";

fn write_skill(root: &Path, name: &str, frontmatter: &str) -> PathBuf {
    let dir = root.join(name);
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("SKILL.md"), format!("{frontmatter}\n# Body\n")).unwrap();
    fs::create_dir_all(dir.join("assets")).unwrap();
    fs::write(dir.join("assets").join("note.txt"), b"TEST_ONLY").unwrap();
    dir
}

struct Fixture {
    home: tempfile::TempDir,
    /// Keeps the trash directory alive for the whole test even when a case
    /// only exercises inventory or install paths.
    #[allow(dead_code)]
    trash: tempfile::TempDir,
    sources: tempfile::TempDir,
    service: SkillsService,
    repo: PathBuf,
}

fn fixture() -> Fixture {
    let home = tempfile::tempdir().unwrap();
    let trash = tempfile::tempdir().unwrap();
    let sources = tempfile::tempdir().unwrap();
    let repo = home.path().join(".atm").join("repo");
    fs::create_dir_all(repo.join("plugins").join("demo")).unwrap();
    let service = SkillsService::new(home.path().to_path_buf(), trash.path().join("private"))
        .with_manager_home(Some(home.path().join(".atm")));
    Fixture {
        home,
        trash,
        sources,
        service,
        repo,
    }
}

fn claude_root(fixture: &Fixture) -> PathBuf {
    fixture.home.path().join(".claude").join("skills")
}

fn find<'a>(inventory: &'a SkillsInventoryView, id: &str, name: &str) -> &'a SkillEntryView {
    inventory
        .roots
        .iter()
        .find(|root| root.id == id)
        .unwrap()
        .entries
        .iter()
        .find(|entry| entry.name == name)
        .unwrap()
}

#[test]
fn inventory_classifies_links_directories_and_excludes_dot_entries() {
    let f = fixture();
    let managed_source = write_skill(&f.repo.join("plugins").join("demo"), "managed", FRONT);
    let root = claude_root(&f);
    fs::create_dir_all(&root).unwrap();
    symlink(&managed_source, root.join("managed")).unwrap();
    let foreign = write_skill(f.sources.path(), "foreign", FRONT);
    symlink(&foreign, root.join("linked")).unwrap();
    symlink(root.join("gone-nowhere"), root.join("broken")).unwrap();
    write_skill(&root, "plain", FRONT);
    fs::write(root.join("stray.txt"), b"TEST_ONLY").unwrap();
    // Dot entries (Codex system skills, staging leftovers) never appear.
    fs::create_dir_all(root.join(".system")).unwrap();
    fs::create_dir_all(root.join(".atm-skills-staging-x")).unwrap();

    let inventory = f.service.inventory().unwrap();
    let claude = inventory
        .roots
        .iter()
        .find(|r| r.id == "claude-code")
        .unwrap();
    assert!(claude.exists);
    let names: Vec<_> = claude.entries.iter().map(|e| e.name.as_str()).collect();
    assert_eq!(names, ["broken", "linked", "managed", "plain", "stray.txt"]);
    assert_eq!(
        find(&inventory, "claude-code", "managed").kind,
        "engine_managed"
    );
    assert_eq!(find(&inventory, "claude-code", "linked").kind, "symlink");
    assert_eq!(find(&inventory, "claude-code", "broken").kind, "symlink");
    assert_eq!(find(&inventory, "claude-code", "plain").kind, "directory");
    assert_eq!(find(&inventory, "claude-code", "stray.txt").kind, "other");
    assert_eq!(
        find(&inventory, "claude-code", "plain")
            .display_name
            .as_deref(),
        Some("test-skill")
    );
    assert!(find(&inventory, "claude-code", "plain")
        .description
        .as_deref()
        .unwrap_or_default()
        .starts_with("A TEST_ONLY skill"));
    assert!(claude.entries.iter().all(|e| !e.name.starts_with('.')));
}

#[test]
fn missing_roots_report_exists_false_with_declared_paths() {
    let f = fixture();
    let inventory = f.service.inventory().unwrap();
    assert_eq!(inventory.roots.len(), 10);
    assert!(inventory.roots.iter().any(|root| root.id == "vscode"));
    assert!(inventory.roots.iter().any(|root| root.id == "oh-my-pi"));
    let zcode = inventory.roots.iter().find(|r| r.id == "zcode").unwrap();
    assert!(!zcode.exists);
    assert!(zcode.entries.is_empty());
    assert!(zcode.path.ends_with(".zcode/skills"));
    assert!(inventory
        .roots
        .iter()
        .find(|r| r.id == "gemini-cli")
        .unwrap()
        .path
        .ends_with(".gemini/skills"));
    assert!(inventory
        .roots
        .iter()
        .find(|r| r.id == "opencode")
        .unwrap()
        .path
        .ends_with(".config/opencode/skills"));
    // Inventory must not create any root as a side effect.
    assert!(!f.home.path().join(".zcode").exists());
    assert!(inventory.trash.is_empty());
}

#[test]
fn install_copies_an_audited_directory_atomically_and_inventories_it() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "my-skill", FRONT);
    fs::write(source.join("assets").join("deep.txt"), b"TEST_ONLY_DEEP").unwrap();
    let root = claude_root(&f);
    let installed = f
        .service
        .install(&source, "claude-code", "my-skill")
        .unwrap();
    assert_eq!(installed, "claude-code/my-skill");
    assert!(root.join("my-skill").join("SKILL.md").is_file());
    assert!(root
        .join("my-skill")
        .join("assets")
        .join("deep.txt")
        .is_file());
    assert!(fs::read_dir(&root)
        .unwrap()
        .filter_map(Result::ok)
        .all(|e| !e
            .file_name()
            .to_string_lossy()
            .starts_with(".atm-skills-staging")));
    let inventory = f.service.inventory().unwrap();
    assert_eq!(
        find(&inventory, "claude-code", "my-skill").kind,
        "directory"
    );
    assert!(inventory.trash.is_empty());
}

#[test]
fn install_failures_reject_and_leave_no_staging_directory() {
    let f = fixture();
    let root = claude_root(&f);
    fs::create_dir_all(&root).unwrap();
    // No SKILL.md.
    let plain = f.sources.path().join("plain-dir");
    fs::create_dir_all(&plain).unwrap();
    assert_eq!(
        f.service
            .install(&plain, "claude-code", "a")
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
    // Contains a symlink.
    let linked = write_skill(f.sources.path(), "linked-skill", FRONT);
    symlink(&plain, linked.join("inside")).unwrap();
    assert_eq!(
        f.service
            .install(&linked, "claude-code", "b")
            .unwrap_err()
            .code,
        "SKILLS_UNAUDITABLE"
    );
    // Relative source path.
    assert_eq!(
        f.service
            .install(Path::new("TEST_ONLY/relative"), "claude-code", "c")
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
    // Invalid names.
    let source = write_skill(f.sources.path(), "valid-source", FRONT);
    for name in [".hidden", "a/b", "../x", ""] {
        assert_eq!(
            f.service
                .install(&source, "claude-code", name)
                .unwrap_err()
                .code,
            "SKILLS_NAME",
            "name {name:?}"
        );
    }
    // Same-name target exists (any entry type).
    write_skill(&root, "taken", FRONT);
    assert_eq!(
        f.service
            .install(&source, "claude-code", "taken")
            .unwrap_err()
            .code,
        "SKILLS_TAKEN"
    );
    assert!(fs::read_dir(&root)
        .unwrap()
        .filter_map(Result::ok)
        .all(|e| !e
            .file_name()
            .to_string_lossy()
            .starts_with(".atm-skills-staging")));
}

#[test]
fn oversized_skill_sources_exceed_the_bounded_budget() {
    let f = fixture();
    let big = write_skill(f.sources.path(), "big", FRONT);
    for index in 0..520 {
        fs::write(
            big.join("assets").join(format!("f{index}.txt")),
            b"TEST_ONLY",
        )
        .unwrap();
    }
    assert_eq!(
        f.service
            .install(&big, "claude-code", "big")
            .unwrap_err()
            .code,
        "SKILLS_LIMIT"
    );
}

#[test]
fn uninstall_moves_directories_to_trash_and_rejects_managed_links() {
    let f = fixture();
    let managed_source = write_skill(&f.repo.join("plugins").join("demo"), "managed", FRONT);
    let root = claude_root(&f);
    fs::create_dir_all(&root).unwrap();
    symlink(&managed_source, root.join("managed")).unwrap();
    assert_eq!(
        f.service
            .uninstall("claude-code", "managed")
            .unwrap_err()
            .code,
        "SKILLS_ENGINE_LOCKED"
    );
    assert!(root.join("managed").exists());

    write_skill(&root, "mine", FRONT);
    let trash_id = f.service.uninstall("claude-code", "mine").unwrap();
    assert_eq!(trash_id, "claude-code/mine");
    assert!(!root.join("mine").exists());
    let inventory = f.service.inventory().unwrap();
    assert_eq!(inventory.trash.len(), 1);
    assert_eq!(inventory.trash[0].id, "claude-code/mine");
    assert_eq!(inventory.trash[0].root_id, "claude-code");

    // Foreign links stay read-only; both link and target survive.
    let foreign = write_skill(f.sources.path(), "elsewhere", FRONT);
    symlink(&foreign, root.join("linked")).unwrap();
    assert_eq!(
        f.service
            .uninstall("claude-code", "linked")
            .unwrap_err()
            .code,
        "SKILLS_FOREIGN_LINK"
    );
    assert!(root.join("linked").exists());
    assert!(foreign.join("SKILL.md").is_file());
    let inventory = f.service.inventory().unwrap();
    assert_eq!(inventory.trash.len(), 1, "links do not enter the trash");
}

#[test]
fn restore_and_purge_cover_the_trash_lifecycle_with_containment() {
    let f = fixture();
    let root = claude_root(&f);
    fs::create_dir_all(&root).unwrap();
    write_skill(&root, "mine", FRONT);
    f.service.uninstall("claude-code", "mine").unwrap();
    // Path escape and unknown roots are rejected before any filesystem effect.
    for bad in ["../escape", "unknown-root/x", "a/b/c", "claude-code/"] {
        assert_eq!(
            f.service.restore(bad).unwrap_err().code,
            "SKILLS_TRASH",
            "id {bad:?}"
        );
    }
    let restored = f.service.restore("claude-code/mine").unwrap();
    assert_eq!(restored, "claude-code/mine");
    assert!(root.join("mine").join("SKILL.md").is_file());
    // A second uninstall of the same name lands on a suffixed trash entry.
    f.service.uninstall("claude-code", "mine").unwrap();
    write_skill(&root, "mine", FRONT);
    assert_eq!(
        f.service.restore("claude-code/mine").unwrap_err().code,
        "SKILLS_TAKEN"
    );
    f.service.uninstall("claude-code", "mine").unwrap();
    let inventory = f.service.inventory().unwrap();
    assert!(inventory.trash.len() >= 2);
    // Purge removes exactly one trash entry.
    let purge_id = inventory.trash[0].id.clone();
    f.service.purge(&purge_id).unwrap();
    let inventory = f.service.inventory().unwrap();
    assert_eq!(
        inventory.trash.iter().filter(|t| t.id == purge_id).count(),
        0
    );
    assert_eq!(
        f.service.purge("../escape").unwrap_err().code,
        "SKILLS_TRASH"
    );
}

#[test]
fn copy_to_clones_between_roots_and_refuses_collisions() {
    let f = fixture();
    let source = write_skill(f.sources.path(), "shared", FRONT);
    f.service.install(&source, "zcode", "shared").unwrap();
    f.service.copy_to("zcode", "shared", "copilot").unwrap();
    let inventory = f.service.inventory().unwrap();
    assert_eq!(find(&inventory, "copilot-cli", "shared").kind, "directory");
    assert_eq!(
        find(&inventory, "copilot-cli", "shared")
            .display_name
            .as_deref(),
        Some("test-skill")
    );
    // Collision refuses without changing anything.
    let before = serde_json::to_string(&inventory).unwrap();
    assert_eq!(
        f.service
            .copy_to("zcode", "shared", "copilot")
            .unwrap_err()
            .code,
        "SKILLS_TAKEN"
    );
    let after = serde_json::to_string(&f.service.inventory().unwrap()).unwrap();
    assert_eq!(before, after);
    // Unknown source entry.
    assert_eq!(
        f.service
            .copy_to("zcode", "missing", "copilot")
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
}

// Explicit live check against the real harness roots; read-only, opt-in.
#[test]
fn live_inventory_against_real_roots_when_explicitly_requested() {
    if std::env::var("ATM_SKILLS_LIVE")
        .map(|value| value != "1")
        .unwrap_or(true)
    {
        return;
    }
    let service = SkillsService::from_environment().unwrap();
    let inventory = service.inventory().unwrap();
    println!("{}", serde_json::to_string_pretty(&inventory).unwrap());
}

#[test]
fn restore_refuses_registered_projection_names_and_recreates_a_missing_root() {
    let f = fixture();
    let registry_root = tempfile::tempdir().unwrap();
    let registry = ProjectionRegistry::at_root(
        registry_root.path().join("private"),
        f.home.path().to_path_buf(),
    )
    .unwrap();
    let service = SkillsService::new(f.home.path().to_path_buf(), f.trash.path().join("private"))
        .with_manager_home(Some(f.home.path().join(".atm")))
        .with_sources_root(Some(registry.sources_root()));
    let source = write_skill(f.sources.path(), "mine-src", FRONT);
    service.install(&source, "claude-code", "mine").unwrap();
    let trash_id = service.uninstall("claude-code", "mine").unwrap();
    // The same name is now a registered projection; restore must not land on it.
    registry
        .publish(&source, "mine", &["claude-code".into()])
        .unwrap();
    fs::remove_file(claude_root(&f).join("mine")).unwrap();
    assert_eq!(
        service.restore(&trash_id).unwrap_err().code,
        "SKILLS_PROJECTED"
    );
    assert_eq!(service.inventory().unwrap().trash.len(), 1);
    // Without the registration the restore recreates the deleted root.
    registry.unproject("mine", "claude-code", false).unwrap();
    registry.unpublish("mine", false).unwrap();
    fs::remove_dir_all(f.home.path().join(".claude")).unwrap();
    assert_eq!(service.restore(&trash_id).unwrap(), "claude-code/mine");
    assert!(claude_root(&f).join("mine").join("SKILL.md").is_file());
    assert!(service.inventory().unwrap().trash.is_empty());
}

#[test]
fn copy_and_uninstall_reject_projections_broken_links_and_plain_files() {
    let f = fixture();
    let registry_root = tempfile::tempdir().unwrap();
    let registry = ProjectionRegistry::at_root(
        registry_root.path().join("private"),
        f.home.path().to_path_buf(),
    )
    .unwrap();
    let service = SkillsService::new(f.home.path().to_path_buf(), f.trash.path().join("private"))
        .with_manager_home(Some(f.home.path().join(".atm")))
        .with_sources_root(Some(registry.sources_root()));
    let source = write_skill(f.sources.path(), "src", FRONT);
    registry
        .publish(&source, "proj", &["zcode".into()])
        .unwrap();
    let root = f.home.path().join(".zcode").join("skills");
    // A projection link is not an auditable source; POSIX projections have
    // no cross-root copy path.
    assert_eq!(
        service
            .copy_to("zcode", "proj", "copilot")
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
    assert!(f
        .home
        .path()
        .join(".copilot/skills/proj")
        .symlink_metadata()
        .is_err());
    // Broken foreign links and plain files are never copied or uninstalled.
    symlink(root.join("nowhere"), root.join("gone")).unwrap();
    fs::write(root.join("plain.txt"), b"TEST_ONLY").unwrap();
    assert_eq!(
        service
            .copy_to("zcode", "gone", "copilot")
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
    assert_eq!(
        service.uninstall("zcode", "gone").unwrap_err().code,
        "SKILLS_FOREIGN_LINK"
    );
    assert_eq!(
        service
            .copy_to("zcode", "plain.txt", "copilot")
            .unwrap_err()
            .code,
        "SKILLS_SOURCE"
    );
    assert_eq!(
        service.uninstall("zcode", "plain.txt").unwrap_err().code,
        "SKILLS_MISSING"
    );
    assert!(root.join("gone").symlink_metadata().is_ok());
    assert_eq!(fs::read(root.join("plain.txt")).unwrap(), b"TEST_ONLY");
    // A real local directory in the same root still copies across roots.
    write_skill(&root, "real", FRONT);
    service.copy_to("zcode", "real", "copilot").unwrap();
    assert!(f
        .home
        .path()
        .join(".copilot/skills/real/SKILL.md")
        .is_file());
    assert!(service.inventory().unwrap().trash.is_empty());
}

#[test]
fn broken_engine_links_stay_protected_and_oversized_frontmatter_is_not_read() {
    let f = fixture();
    let root = claude_root(&f);
    fs::create_dir_all(&root).unwrap();
    symlink(f.repo.join("gone/skill"), root.join("broken-managed")).unwrap();
    assert_eq!(
        f.service
            .uninstall("claude-code", "broken-managed")
            .unwrap_err()
            .code,
        "SKILLS_ENGINE_LOCKED"
    );
    assert_eq!(
        find(
            &f.service.inventory().unwrap(),
            "claude-code",
            "broken-managed"
        )
        .kind,
        "engine_managed"
    );
    let huge = write_skill(&root, "huge", FRONT);
    fs::OpenOptions::new()
        .write(true)
        .open(huge.join("SKILL.md"))
        .unwrap()
        .set_len(1024 * 1024 * 1024)
        .unwrap();
    assert!(find(&f.service.inventory().unwrap(), "claude-code", "huge")
        .description
        .is_none());
}

#[test]
fn aliased_manager_home_protects_real_owned_sources_and_missing_targets() {
    let f = fixture();
    let alias = f.home.path().join("manager-alias");
    symlink(f.home.path().join(".atm"), &alias).unwrap();
    let service = SkillsService::new(f.home.path().into(), f.trash.path().join("private"))
        .with_manager_home(Some(alias));
    let owned = write_skill(&f.repo, "owned", FRONT);
    assert_eq!(
        service.install(&owned, "zcode", "owned").unwrap_err().code,
        "SKILLS_ENGINE_LOCKED"
    );
    let foreign = write_skill(f.sources.path(), "foreign", FRONT);
    service.install(&foreign, "zcode", "foreign").unwrap();
    // An existing ancestor points into the manager, but the skills root is absent.
    symlink(f.home.path().join(".atm"), f.home.path().join(".claude")).unwrap();
    assert_eq!(
        service
            .install(&foreign, "claude-code", "new")
            .unwrap_err()
            .code,
        "SKILLS_ENGINE_LOCKED"
    );
    assert!(!f.home.path().join(".atm/skills").exists());
}

#[test]
fn duplicate_trash_restores_original_names_including_max_length_and_double_dots() {
    for name in ["mine".to_owned(), "x".repeat(64), "foo..bar".to_owned()] {
        let f = fixture();
        let root = claude_root(&f);
        write_skill(&root, &name, "first");
        let first = f.service.uninstall("claude-code", &name).unwrap();
        write_skill(&root, &name, "second");
        let second = f.service.uninstall("claude-code", &name).unwrap();
        assert_ne!(first, second);
        let inventory = f.service.inventory().unwrap();
        assert_eq!(inventory.trash.len(), 2);
        assert!(inventory.trash.iter().all(|item| item.name == name));
        assert_eq!(
            f.service.restore(&second).unwrap(),
            format!("claude-code/{name}")
        );
        assert!(fs::read_to_string(root.join(&name).join("SKILL.md"))
            .unwrap()
            .starts_with("second"));
        assert_eq!(f.service.restore(&first).unwrap_err().code, "SKILLS_TAKEN");
        f.service.purge(&first).unwrap();
        assert!(f.service.inventory().unwrap().trash.is_empty());
    }
}

#[test]
fn legacy_windows_handles_are_accepted_without_allowing_traversal() {
    let f = fixture();
    write_skill(&claude_root(&f), "foo..bar", FRONT);
    let id = f.service.uninstall("claude-code", "foo..bar").unwrap();
    assert_eq!(id, "claude-code/foo..bar");
    assert_eq!(f.service.restore("claude-code\\foo..bar").unwrap(), id);
    for bad in [
        "claude-code/..",
        "claude-code/../x",
        "claude-code\\..\\x",
        "claude-code/a\\b",
    ] {
        assert!(f.service.restore(bad).is_err(), "{bad}");
    }
}

#[test]
fn malformed_collision_record_never_restores_an_untrusted_name() {
    let f = fixture();
    let group = f.trash.path().join("private/claude-code");
    let handle = ".atm-trash-00000000-0000-0000-0000-000000000000";
    let record = group.join(handle);
    write_skill(&record, "skill", FRONT);
    fs::write(record.join("original-name"), "../escape").unwrap();
    assert!(f.service.restore(&format!("claude-code/{handle}")).is_err());
    assert!(record.join("skill/SKILL.md").exists());
}

#[test]
fn old_oversized_trash_handles_remain_visible_and_purgeable() {
    let f = fixture();
    let legacy_name = format!("{}-1720000000", "x".repeat(64));
    write_skill(
        &f.trash.path().join("private/claude-code"),
        &legacy_name,
        FRONT,
    );
    let inventory = f.service.inventory().unwrap();
    assert_eq!(inventory.trash.len(), 1);
    assert_eq!(inventory.trash[0].name, legacy_name);
    // No original-name metadata exists: never guess which suffix was generated.
    assert_eq!(
        f.service.restore(&inventory.trash[0].id).unwrap_err().code,
        "SKILLS_NAME"
    );
    f.service.purge(&inventory.trash[0].id).unwrap();
    assert!(f.service.inventory().unwrap().trash.is_empty());
}

#[test]
fn shared_agent_skills_are_hidden_and_unchanged_through_root_and_ancestor_links() {
    for ancestor in [false, true] {
        let f = fixture();
        let source = write_skill(f.sources.path(), "source", FRONT);
        f.service.install(&source, "zcode", "restore-me").unwrap();
        let trash = f.service.uninstall("zcode", "restore-me").unwrap();
        let tool_root = f.home.path().join(".zcode/skills");
        fs::remove_dir(&tool_root).unwrap();
        let shared = f.home.path().join(".agents/skills");
        let kept = write_skill(&shared, "kept", FRONT);
        let before = fs::read(kept.join("SKILL.md")).unwrap();
        if ancestor {
            fs::remove_dir(f.home.path().join(".zcode")).unwrap();
            symlink(f.home.path().join(".agents"), f.home.path().join(".zcode")).unwrap();
        } else {
            symlink(&shared, &tool_root).unwrap();
        }
        f.service.install(&source, "copilot", "ordinary").unwrap();
        let inventory = f.service.inventory().unwrap();
        assert!(inventory.roots.iter().all(|r| r.id != "zcode"));
        assert_eq!(
            find(&inventory, "copilot-cli", "ordinary").kind,
            "directory"
        );
        for result in [
            f.service.install(&source, "zcode", "new"),
            f.service.copy_to("copilot", "ordinary", "zcode"),
            f.service.copy_to("zcode", "kept", "copilot"),
            f.service.uninstall("zcode", "kept"),
            f.service.restore(&trash),
            f.service.install(&kept, "copilot", "adopt-shared"),
        ] {
            assert_eq!(result.unwrap_err().code, "SKILLS_PROTECTED");
        }
        assert_eq!(fs::read(kept.join("SKILL.md")).unwrap(), before);
        assert_eq!(fs::read_dir(&shared).unwrap().count(), 1);
        assert_eq!(f.service.inventory().unwrap().trash.len(), 1);
    }
}

#[test]
fn entry_links_into_shared_agent_skills_are_not_read_or_offered() {
    let f = fixture();
    let kept = write_skill(&f.home.path().join(".agents/skills"), "kept", FRONT);
    let root = f.home.path().join(".zcode/skills");
    fs::create_dir_all(&root).unwrap();
    symlink(&kept, root.join("shared-alias")).unwrap();
    let inventory = f.service.inventory().unwrap();
    assert!(inventory
        .roots
        .iter()
        .find(|r| r.id == "zcode")
        .unwrap()
        .entries
        .is_empty());
    assert_eq!(
        f.service
            .uninstall("zcode", "shared-alias")
            .unwrap_err()
            .code,
        "SKILLS_PROTECTED"
    );
    assert!(root.join("shared-alias").is_symlink());
    assert!(kept.join("SKILL.md").is_file());
}
