#![cfg(any(target_os = "linux", target_os = "macos", windows))]
// End-to-end CLI runs against TEST_ONLY fixtures with isolated platform home,
// data and harness roots per invocation. No real harness roots are touched.
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

struct Env {
    home: tempfile::TempDir,
    data: tempfile::TempDir,
    sources: tempfile::TempDir,
}

impl Env {
    fn new() -> Self {
        Self {
            home: tempfile::tempdir().unwrap(),
            data: tempfile::tempdir().unwrap(),
            sources: tempfile::tempdir().unwrap(),
        }
    }

    fn vars(&self) -> [(&'static str, PathBuf); 5] {
        [
            ("HOME", self.home.path().to_path_buf()),
            ("USERPROFILE", self.home.path().to_path_buf()),
            ("XDG_DATA_HOME", self.data.path().to_path_buf()),
            ("LOCALAPPDATA", self.data.path().to_path_buf()),
            (
                "OH_MY_HARNESS_HOME",
                self.home.path().join("test-oh-my-harness"),
            ),
        ]
    }

    fn manager_data(&self) -> PathBuf {
        if cfg!(target_os = "macos") {
            self.home
                .path()
                .join("Library/Application Support/LocalKeyManager")
        } else {
            self.data.path().join(if cfg!(windows) {
                "LocalKeyManager"
            } else {
                "local-key-manager"
            })
        }
    }

    fn canonical(&self, name: &str) -> PathBuf {
        self.manager_data()
            .join("skills-sources/sources")
            .join(name)
    }

    fn projection(&self, name: &str) -> PathBuf {
        self.home.path().join(".zcode/skills").join(name)
    }
}

fn atm(env: &Env, arguments: &[&str]) -> std::process::Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_atm"));
    command.args(arguments);
    // Inherited tool-root overrides must never escape the fixture home.
    for key in [
        "CLAUDE_CONFIG_DIR",
        "COPILOT_HOME",
        "CODEX_HOME",
        "GEMINI_CLI_HOME",
        "OPENCLAW_STATE_DIR",
        "PI_CODING_AGENT_DIR",
    ] {
        command.env_remove(key);
    }
    for (key, value) in env.vars() {
        command.env(key, &value);
    }
    command.output().unwrap()
}

fn assert_ok(output: &std::process::Output) {
    assert!(
        output.status.success(),
        "expected success, got {:?}: {}",
        output.status.code(),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn assert_code(output: &std::process::Output, expected: i32) {
    assert_eq!(
        output.status.code(),
        Some(expected),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

fn write_skill(root: &Path, name: &str) -> PathBuf {
    let dir = root.join(name);
    fs::create_dir_all(dir.join("assets")).unwrap();
    fs::write(
        dir.join("SKILL.md"),
        "---\nname: cli-skill\ndescription: A TEST_ONLY CLI fixture.\n---\n# Body\n",
    )
    .unwrap();
    fs::write(dir.join("assets").join("n.txt"), b"TEST_ONLY").unwrap();
    dir
}

fn remove_projection(path: &Path) {
    if cfg!(windows) {
        fs::remove_dir_all(path).unwrap();
    } else {
        fs::remove_file(path).unwrap();
    }
}

fn json_items(output: &std::process::Output) -> Vec<serde_json::Value> {
    serde_json::from_slice(&output.stdout).unwrap_or_else(|error| {
        panic!(
            "stdout must be one JSON array: {error}; stdout: {}",
            String::from_utf8_lossy(&output.stdout)
        )
    })
}

fn publish_fixture(env: &Env, name: &str) {
    let source = write_skill(env.sources.path(), name);
    assert_ok(&atm(
        env,
        &[
            "skills",
            "publish",
            source.to_str().unwrap(),
            "--name",
            name,
            "--to",
            "zcode",
        ],
    ));
}

#[test]
fn full_publish_check_refresh_unproject_lifecycle_through_the_cli() {
    let env = Env::new();
    let source = write_skill(env.sources.path(), "my-skill");
    // Publish requires --name and at least one target.
    let missing = atm(&env, &["skills", "publish", source.to_str().unwrap()]);
    assert_code(&missing, 1);
    assert!(String::from_utf8_lossy(&missing.stderr).contains("CLI_ARGUMENT"));
    let ok = atm(
        &env,
        &[
            "skills",
            "publish",
            source.to_str().unwrap(),
            "--name",
            "cli-skill",
            "--to",
            "zcode,copilot",
        ],
    );
    assert_ok(&ok);
    assert!(String::from_utf8_lossy(&ok.stdout).contains("已投影：zcode/cli-skill"));
    // Inventory classifies and counts.
    let list = atm(&env, &["skills", "inventory"]);
    assert_ok(&list);
    let text = String::from_utf8_lossy(&list.stdout);
    assert!(text.contains("ATM 投影"));
    assert!(text.contains("cli-skill"));
    assert!(text.contains("根不存在"));
    // Check passes; breaking the link fails check and refresh repairs it.
    let check = atm(&env, &["skills", "check"]);
    assert_ok(&check);
    let link = env.home.path().join(".zcode/skills/cli-skill");
    remove_projection(&link);
    let broken = atm(&env, &["skills", "check"]);
    assert_code(&broken, 1);
    let repaired = atm(&env, &["skills", "refresh"]);
    assert_ok(&repaired);
    assert!(link.join("SKILL.md").is_file());
    let json = atm(&env, &["skills", "check", "--json"]);
    assert_ok(&json);
    let items = json_items(&json);
    assert_eq!(items.len(), 2);
    assert!(items.iter().all(|item| item["status"] == "ok"));
    // Unproject removes the registry-recorded projection only.
    let unproject = atm(
        &env,
        &["skills", "unproject", "cli-skill", "--from", "zcode"],
    );
    assert_ok(&unproject);
    assert!(!link.exists());
    assert!(env.canonical("cli-skill").join("SKILL.md").is_file());
    // Unpublish drains the rest and removes the canonical copy.
    let unpublish = atm(&env, &["skills", "unpublish", "cli-skill"]);
    assert_code(&unpublish, 1); // copilot projection still present
    let drained = atm(
        &env,
        &["skills", "unpublish", "cli-skill", "--with-projections"],
    );
    assert_ok(&drained);
    assert!(!env.home.path().join(".copilot/skills/cli-skill").exists());
    assert!(!env.canonical("cli-skill").exists());
}

#[test]
fn install_uninstall_copy_and_trash_lifecycle_through_the_cli() {
    let env = Env::new();
    let source = write_skill(env.sources.path(), "standalone");
    let install = atm(
        &env,
        &[
            "skills",
            "install",
            source.to_str().unwrap(),
            "zcode",
            "standalone",
        ],
    );
    assert_ok(&install);
    assert!(env
        .home
        .path()
        .join(".zcode/skills/standalone/SKILL.md")
        .is_file());
    // Copy to another root; the second copy refuses on collision.
    let copy = atm(&env, &["skills", "copy", "zcode", "standalone", "copilot"]);
    assert_ok(&copy);
    let collision = atm(&env, &["skills", "copy", "zcode", "standalone", "copilot"]);
    assert_code(&collision, 1);
    assert!(String::from_utf8_lossy(&collision.stderr).contains("SKILLS_TAKEN"));
    // Uninstall to trash; trash listing; restore.
    let uninstall = atm(&env, &["skills", "uninstall", "zcode", "standalone"]);
    assert_ok(&uninstall);
    assert!(!env.home.path().join(".zcode/skills/standalone").exists());
    let trash = atm(&env, &["skills", "trash"]);
    assert_ok(&trash);
    assert!(String::from_utf8_lossy(&trash.stdout).contains("zcode/standalone"));
    let restore = atm(&env, &["skills", "restore", "zcode/standalone"]);
    assert_ok(&restore);
    assert!(env
        .home
        .path()
        .join(".zcode/skills/standalone/SKILL.md")
        .is_file());
    // Purge path: uninstall again, then purge by id.
    assert_ok(&atm(&env, &["skills", "uninstall", "zcode", "standalone"]));
    let purge = atm(&env, &["skills", "purge", "zcode/standalone"]);
    assert_ok(&purge);
    let trash = atm(&env, &["skills", "trash", "--json"]);
    assert_ok(&trash);
    assert!(String::from_utf8_lossy(&trash.stdout).trim() == "[]");
}

#[test]
fn unknown_commands_and_help_are_handled_without_touching_the_environment() {
    let env = Env::new();
    let unknown = atm(&env, &["skills", "nope"]);
    assert_code(&unknown, 1);
    assert!(String::from_utf8_lossy(&unknown.stderr).contains("CLI_COMMAND"));
    let help = atm(&env, &["help"]);
    assert_ok(&help);
    assert!(String::from_utf8_lossy(&help.stdout).contains("atm skills inventory"));
    // Bare invocation prints usage and exits successfully.
    let bare = atm(&env, &[]);
    assert_ok(&bare);
    // The isolated environment stays untouched by help/usage.
    assert!(!env.home.path().join(".zcode").exists());
}

#[test]
fn named_check_and_refresh_leave_other_sources_untouched() {
    let env = Env::new();
    publish_fixture(&env, "alpha");
    publish_fixture(&env, "beta");
    let beta_canonical = fs::read(env.canonical("beta").join("SKILL.md")).unwrap();
    let registry_path = env.manager_data().join("skills-sources/registry.json");
    let registry_before = fs::read(&registry_path).unwrap();

    remove_projection(&env.projection("beta"));
    let healthy = atm(&env, &["skills", "check", "alpha", "--json"]);
    assert_ok(&healthy);
    assert!(healthy.stderr.is_empty());
    let items = json_items(&healthy);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["source"], "alpha");
    assert_eq!(items[0]["status"], "ok");

    // A failed check still emits exactly one parseable JSON value on stdout.
    let broken = atm(&env, &["skills", "check", "--json", "beta"]);
    assert_code(&broken, 1);
    let items = json_items(&broken);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["source"], "beta");
    assert_eq!(items[0]["status"], "broken_link");

    remove_projection(&env.projection("alpha"));
    let repaired = atm(&env, &["skills", "refresh", "alpha"]);
    assert_ok(&repaired);
    assert!(env.projection("alpha").join("SKILL.md").is_file());
    assert!(fs::symlink_metadata(env.projection("beta")).is_err());
    assert!(!String::from_utf8_lossy(&repaired.stdout).contains("beta"));

    // Even a forced named refresh must not replace an unrelated occupied target.
    fs::create_dir_all(env.projection("beta")).unwrap();
    let unrelated_file = env.projection("beta").join("unrelated.txt");
    fs::write(&unrelated_file, b"TEST_ONLY: preserve beta").unwrap();
    remove_projection(&env.projection("alpha"));
    let forced = atm(&env, &["skills", "refresh", "alpha", "--force"]);
    assert_ok(&forced);
    assert!(env.projection("alpha").join("SKILL.md").is_file());
    assert_eq!(
        fs::read(&unrelated_file).unwrap(),
        b"TEST_ONLY: preserve beta"
    );
    assert_eq!(
        fs::read(env.canonical("beta").join("SKILL.md")).unwrap(),
        beta_canonical
    );
    // Recreating alpha's Windows copy legitimately changes its directory
    // identity receipt. The unrelated beta record must stay exactly unchanged.
    let before: Vec<serde_json::Value> = serde_json::from_slice(&registry_before).unwrap();
    let after: Vec<serde_json::Value> =
        serde_json::from_slice(&fs::read(&registry_path).unwrap()).unwrap();
    assert_eq!(after.len(), before.len());
    assert_eq!(
        after.iter().find(|record| record["name"] == "beta"),
        before.iter().find(|record| record["name"] == "beta")
    );
    assert_ok(&atm(&env, &["skills", "check", "alpha", "--json"]));
}

#[test]
fn empty_check_json_is_parseable_without_a_success_suffix() {
    let env = Env::new();
    let output = atm(&env, &["skills", "check", "--json"]);
    assert_ok(&output);
    assert!(output.stderr.is_empty());
    assert!(json_items(&output).is_empty());
}

#[test]
fn inventory_and_check_create_storage_compatible_shared_directories() {
    for first_command in ["inventory", "check"] {
        let env = Env::new();
        assert!(!env.manager_data().exists());
        assert_ok(&atm(&env, &["skills", first_command, "--json"]));
        assert_private_directory(&env.manager_data());

        // Either constructor may run first; the other must accept its shared
        // data directory without changing permissions or breaking vault access.
        let second_command = if first_command == "inventory" {
            "check"
        } else {
            "inventory"
        };
        assert_ok(&atm(&env, &["skills", second_command, "--json"]));
        for path in [
            env.manager_data(),
            env.manager_data().join("skills-trash"),
            env.manager_data().join("skills-sources"),
            env.manager_data().join("skills-sources/sources"),
        ] {
            assert_private_directory(&path);
        }
    }
}

fn assert_private_directory(path: &Path) {
    assert!(path.is_dir(), "expected directory: {}", path.display());
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(path).unwrap().permissions().mode() & 0o777,
            0o700,
            "directory permissions: {}",
            path.display()
        );
    }
    // Exercise the same validation used by the encrypted storage constructor.
    atm_core::storage::ensure_directory(path).unwrap();
}

#[test]
fn child_cli_respects_registry_lock_and_recovers_after_release() {
    let env = Env::new();
    publish_fixture(&env, "alpha");
    remove_projection(&env.projection("alpha"));
    let registry_root = env.manager_data().join("skills-sources");
    let registry_before = fs::read(registry_root.join("registry.json")).unwrap();
    let canonical_before = fs::read(env.canonical("alpha").join("SKILL.md")).unwrap();

    // Hold the production OS lock in this process while a separate CLI process
    // attempts both a read and a mutating repair. Neither should bypass it.
    let lock = atm_core::windows::open_lock(&registry_root.join("registry.lock")).unwrap();
    for arguments in [
        &["skills", "check", "alpha", "--json"][..],
        &["skills", "refresh", "alpha", "--force"][..],
    ] {
        let output = atm(&env, arguments);
        assert_code(&output, 1);
        assert!(String::from_utf8_lossy(&output.stderr).contains("VAULT_BUSY"));
        assert!(output.stdout.is_empty());
        assert!(fs::symlink_metadata(env.projection("alpha")).is_err());
        assert_eq!(
            fs::read(registry_root.join("registry.json")).unwrap(),
            registry_before
        );
        assert_eq!(
            fs::read(env.canonical("alpha").join("SKILL.md")).unwrap(),
            canonical_before
        );
    }
    drop(lock);

    assert_ok(&atm(&env, &["skills", "refresh", "alpha"]));
    assert!(env.projection("alpha").join("SKILL.md").is_file());
    let output = atm(&env, &["skills", "check", "alpha", "--json"]);
    assert_ok(&output);
    let items = json_items(&output);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["source"], "alpha");
    assert_eq!(items[0]["status"], "ok");
}

#[test]
fn invalid_arguments_fail_before_any_environment_changes() {
    let env = Env::new();
    let invalid: &[&[&str]] = &[
        &["help", "extra"],
        &["--help", "extra"],
        &["skills"],
        &["skills", "inventory", "extra"],
        &["skills", "inventory", "--force"],
        &["skills", "inventory", "--json", "--json"],
        &["skills", "check", "alpha", "beta"],
        &["skills", "check", "--name", "alpha"],
        &["skills", "check", "alpha", "--force"],
        &["skills", "check", "-x"],
        &["skills", "check", ""],
        &["skills", "refresh", "alpha", "beta", "--force"],
        &["skills", "refresh", "--name", "alpha"],
        &["skills", "refresh", "alpha", "--json"],
        &["skills", "refresh", "--force", "--force"],
        &[
            "skills", "publish", "source", "extra", "--name", "alpha", "--to", "zcode",
        ],
        &["skills", "publish", "source", "--name", "alpha"],
        &["skills", "publish", "source", "--name", "--to", "zcode"],
        &["skills", "publish", "source", "--name", "", "--to", "zcode"],
        &[
            "skills", "publish", "source", "--name", "alpha", "--name", "beta", "--to", "zcode",
        ],
        &["skills", "publish", "source", "--name", "alpha", "--to", ""],
        &[
            "skills", "publish", "source", "--name", "alpha", "--to", "zcode,",
        ],
        &[
            "skills",
            "publish",
            "source",
            "--name",
            "alpha",
            "--to",
            "zcode,zcode",
        ],
        &["skills", "project", "alpha", "extra", "--to", "zcode"],
        &["skills", "project", "alpha", "--to", "zcode,copilot"],
        &[
            "skills", "project", "alpha", "--to", "zcode", "--to", "copilot",
        ],
        &["skills", "project", "alpha", "--from", "zcode"],
        &["skills", "unproject", "alpha", "extra", "--from", "zcode"],
        &["skills", "unproject", "alpha", "--to", "zcode"],
        &["skills", "unproject", "alpha", "--from"],
        &[
            "skills",
            "unpublish",
            "alpha",
            "extra",
            "--with-projections",
        ],
        &["skills", "unpublish", "alpha", "--force"],
        &["skills", "install", "source", "zcode", "alpha", "extra"],
        &["skills", "install", "source", "zcode", "--name", "alpha"],
        &["skills", "uninstall", "zcode", "alpha", "extra"],
        &["skills", "copy", "zcode", "alpha", "copilot", "extra"],
        &["skills", "trash", "extra"],
        &["skills", "restore", "zcode/alpha", "extra"],
        &["skills", "purge", "zcode/alpha", "extra"],
        &["skills", "purge", "zcode/alpha", "--force"],
    ];
    for arguments in invalid {
        let output = atm(&env, arguments);
        assert_eq!(output.status.code(), Some(1), "arguments: {arguments:?}");
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("CLI_ARGUMENT"),
            "arguments: {arguments:?}; stderr: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.is_empty(), "arguments: {arguments:?}");
        assert_eq!(fs::read_dir(env.home.path()).unwrap().count(), 0);
        assert_eq!(fs::read_dir(env.data.path()).unwrap().count(), 0);
        assert_eq!(fs::read_dir(env.sources.path()).unwrap().count(), 0);
    }
}

#[test]
fn invalid_forced_refresh_does_not_repair_any_projection() {
    let env = Env::new();
    publish_fixture(&env, "alpha");
    publish_fixture(&env, "beta");
    remove_projection(&env.projection("alpha"));
    remove_projection(&env.projection("beta"));
    let registry_path = env.manager_data().join("skills-sources/registry.json");
    let registry_before = fs::read(&registry_path).unwrap();

    let output = atm(&env, &["skills", "refresh", "alpha", "beta", "--force"]);
    assert_code(&output, 1);
    assert!(String::from_utf8_lossy(&output.stderr).contains("CLI_ARGUMENT"));
    assert!(fs::symlink_metadata(env.projection("alpha")).is_err());
    assert!(fs::symlink_metadata(env.projection("beta")).is_err());
    assert_eq!(fs::read(&registry_path).unwrap(), registry_before);
}

#[test]
fn refresh_reports_nonzero_when_the_canonical_source_is_missing() {
    let env = Env::new();
    publish_fixture(&env, "missing");
    fs::remove_dir_all(env.canonical("missing")).unwrap();
    let output = atm(&env, &["skills", "refresh", "missing"]);
    assert_code(&output, 1);
    assert!(String::from_utf8_lossy(&output.stdout).contains("断链"));
    assert!(String::from_utf8_lossy(&output.stderr).contains("PROJECTION_BROKEN"));
}

#[cfg(windows)]
#[test]
fn refresh_reports_nonzero_for_unforced_edits_and_unknown_ownership() {
    let env = Env::new();
    publish_fixture(&env, "owned");
    fs::write(env.projection("owned").join("SKILL.md"), b"TEST_ONLY_edit").unwrap();
    let output = atm(&env, &["skills", "refresh", "owned"]);
    assert_code(&output, 1);
    assert!(String::from_utf8_lossy(&output.stderr).contains("PROJECTION_BROKEN"));
    assert_eq!(
        fs::read(env.projection("owned").join("SKILL.md")).unwrap(),
        b"TEST_ONLY_edit"
    );
    fs::rename(env.projection("owned"), env.home.path().join("retired")).unwrap();
    write_skill(&env.home.path().join(".zcode/skills"), "owned");
    for arguments in [
        &["skills", "refresh", "owned"][..],
        &["skills", "refresh", "owned", "--force"][..],
    ] {
        let output = atm(&env, arguments);
        assert_code(&output, 1);
        assert!(String::from_utf8_lossy(&output.stdout).contains("ownership_unknown"));
        assert!(String::from_utf8_lossy(&output.stderr).contains("PROJECTION_BROKEN"));
    }
}
