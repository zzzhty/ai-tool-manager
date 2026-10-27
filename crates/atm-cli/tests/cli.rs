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
            ("ATM_HOME", self.home.path().join("test-atm-harness")),
        ]
    }

    fn manager_data(&self) -> PathBuf {
        if cfg!(target_os = "macos") {
            self.home.path().join("Library/Application Support/atm")
        } else {
            self.data.path().join("atm")
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
    atm_command(env, arguments).output().unwrap()
}

fn atm_command(env: &Env, arguments: &[&str]) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_atm"));
    command.args(arguments);
    // Inherited tool-root overrides must never escape the fixture home.
    for key in [
        "CLAUDE_CONFIG_DIR",
        "COPILOT_HOME",
        "CODEX_HOME",
        "GEMINI_CLI_HOME",
        "OPENCLAW_STATE_DIR",
        "OPENCLAW_HOME",
        "OPENCLAW_PROFILE",
        "PI_CODING_AGENT_DIR",
        "ATM_ENGINE_SOURCE",
        "ATM_BOOTSTRAP_PYTHON",
    ] {
        command.env_remove(key);
    }
    for (key, value) in env.vars() {
        command.env(key, &value);
    }
    command
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
            "publish",
            "skills",
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
    let missing = atm(&env, &["publish", "skills", source.to_str().unwrap()]);
    assert_code(&missing, 1);
    assert!(String::from_utf8_lossy(&missing.stderr).contains("CLI_ARGUMENT"));
    let ok = atm(
        &env,
        &[
            "publish",
            "skills",
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
    let list = atm(&env, &["list", "skills"]);
    assert_ok(&list);
    let text = String::from_utf8_lossy(&list.stdout);
    assert!(text.contains("ATM 投影"));
    assert!(text.contains("cli-skill"));
    assert!(text.contains("根不存在"));
    // Check passes; breaking the link fails check and refresh repairs it.
    let check = atm(&env, &["check", "skills"]);
    assert_ok(&check);
    let link = env.home.path().join(".zcode/skills/cli-skill");
    remove_projection(&link);
    let broken = atm(&env, &["check", "skills"]);
    assert_code(&broken, 1);
    let repaired = atm(&env, &["update", "skills"]);
    assert_ok(&repaired);
    assert!(link.join("SKILL.md").is_file());
    let json = atm(&env, &["check", "skills", "--json"]);
    assert_ok(&json);
    let items = json_items(&json);
    assert_eq!(items.len(), 2);
    assert!(items.iter().all(|item| item["status"] == "ok"));
    // Unproject removes the registry-recorded projection only.
    let unproject = atm(
        &env,
        &["unproject", "skills", "cli-skill", "--from", "zcode"],
    );
    assert_ok(&unproject);
    assert!(!link.exists());
    assert!(env.canonical("cli-skill").join("SKILL.md").is_file());
    // Unpublish drains the rest and removes the canonical copy.
    let unpublish = atm(&env, &["unpublish", "skills", "cli-skill"]);
    assert_code(&unpublish, 1); // copilot projection still present
    let drained = atm(
        &env,
        &["unpublish", "skills", "cli-skill", "--with-projections"],
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
            "install",
            "skills",
            source.to_str().unwrap(),
            "--to",
            "zcode",
            "--name",
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
    let copy = atm(&env, &["copy", "skills", "zcode", "standalone", "copilot"]);
    assert_ok(&copy);
    let collision = atm(&env, &["copy", "skills", "zcode", "standalone", "copilot"]);
    assert_code(&collision, 1);
    assert!(String::from_utf8_lossy(&collision.stderr).contains("SKILLS_TAKEN"));
    // Uninstall to trash; trash listing; restore.
    let uninstall = atm(&env, &["uninstall", "skills", "zcode", "standalone"]);
    assert_ok(&uninstall);
    assert!(!env.home.path().join(".zcode/skills/standalone").exists());
    let trash = atm(&env, &["list", "skills", "--trash"]);
    assert_ok(&trash);
    assert!(String::from_utf8_lossy(&trash.stdout).contains("zcode/standalone"));
    let restore = atm(&env, &["restore", "skills", "zcode/standalone"]);
    assert_ok(&restore);
    assert!(env
        .home
        .path()
        .join(".zcode/skills/standalone/SKILL.md")
        .is_file());
    // Purge path: uninstall again, then purge by id.
    assert_ok(&atm(&env, &["uninstall", "skills", "zcode", "standalone"]));
    let purge = atm(&env, &["purge", "skills", "zcode/standalone"]);
    assert_ok(&purge);
    let trash = atm(&env, &["list", "skills", "--trash", "--json"]);
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
    assert!(String::from_utf8_lossy(&help.stdout).contains("atm list skills"));
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
    let healthy = atm(&env, &["check", "skills", "alpha", "--json"]);
    assert_ok(&healthy);
    assert!(healthy.stderr.is_empty());
    let items = json_items(&healthy);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["source"], "alpha");
    assert_eq!(items[0]["status"], "ok");

    // A failed check still emits exactly one parseable JSON value on stdout.
    let broken = atm(&env, &["check", "skills", "--json", "beta"]);
    assert_code(&broken, 1);
    let items = json_items(&broken);
    assert_eq!(items.len(), 1);
    assert_eq!(items[0]["source"], "beta");
    assert_eq!(items[0]["status"], "broken_link");

    remove_projection(&env.projection("alpha"));
    let repaired = atm(&env, &["update", "skills", "alpha"]);
    assert_ok(&repaired);
    assert!(env.projection("alpha").join("SKILL.md").is_file());
    assert!(fs::symlink_metadata(env.projection("beta")).is_err());
    assert!(!String::from_utf8_lossy(&repaired.stdout).contains("beta"));

    // Even a forced named refresh must not replace an unrelated occupied target.
    fs::create_dir_all(env.projection("beta")).unwrap();
    let unrelated_file = env.projection("beta").join("unrelated.txt");
    fs::write(&unrelated_file, b"TEST_ONLY: preserve beta").unwrap();
    remove_projection(&env.projection("alpha"));
    let forced = atm(&env, &["update", "skills", "alpha", "--force"]);
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
    assert_ok(&atm(&env, &["check", "skills", "alpha", "--json"]));
}

#[test]
fn empty_check_json_is_parseable_without_a_success_suffix() {
    let env = Env::new();
    let output = atm(&env, &["check", "skills", "--json"]);
    assert_ok(&output);
    assert!(output.stderr.is_empty());
    assert!(json_items(&output).is_empty());
}

#[test]
fn inventory_and_check_create_storage_compatible_shared_directories() {
    for first_command in ["list", "check"] {
        let env = Env::new();
        assert!(!env.manager_data().exists());
        assert_ok(&atm(&env, &[first_command, "skills", "--json"]));
        assert_private_directory(&env.manager_data());

        // Either constructor may run first; the other must accept its shared
        // data directory without changing permissions or breaking vault access.
        let second_command = if first_command == "list" {
            "check"
        } else {
            "list"
        };
        assert_ok(&atm(&env, &[second_command, "skills", "--json"]));
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
    const HOLDER: &str = "ATM_TEST_LOCK_HOLDER";
    if let Some(path) = std::env::var_os(HOLDER) {
        use std::io::Write;
        let _lock = atm_core::windows::open_lock(Path::new(&path)).unwrap();
        println!("LOCK_READY");
        std::io::stdout().flush().unwrap();
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).unwrap();
        return;
    }
    let env = Env::new();
    publish_fixture(&env, "alpha");
    remove_projection(&env.projection("alpha"));
    let registry_root = env.manager_data().join("skills-sources");
    let registry_before = fs::read(registry_root.join("registry.json")).unwrap();
    let canonical_before = fs::read(env.canonical("alpha").join("SKILL.md")).unwrap();

    // A dedicated holder prevents unrelated parallel subprocess tests from
    // inheriting this process's flock during fork and delaying its release.
    use std::io::{BufRead, BufReader, Write};
    use std::process::Stdio;
    let mut holder = Command::new(std::env::current_exe().unwrap())
        .args([
            "child_cli_respects_registry_lock_and_recovers_after_release",
            "--exact",
            "--nocapture",
        ])
        .env(HOLDER, registry_root.join("registry.lock"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut output = BufReader::new(holder.stdout.take().unwrap());
    loop {
        let mut line = String::new();
        assert_ne!(
            output.read_line(&mut line).unwrap(),
            0,
            "lock holder exited before acquiring lock"
        );
        if line.trim() == "LOCK_READY" {
            break;
        }
    }
    for arguments in [
        &["check", "skills", "alpha", "--json"][..],
        &["update", "skills", "alpha", "--force"][..],
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
    holder
        .stdin
        .take()
        .unwrap()
        .write_all(b"release\n")
        .unwrap();
    assert!(holder.wait().unwrap().success());

    assert_ok(&atm(&env, &["update", "skills", "alpha"]));
    assert!(env.projection("alpha").join("SKILL.md").is_file());
    let output = atm(&env, &["check", "skills", "alpha", "--json"]);
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
        &["list", "skills", "extra"],
        &["list", "skills", "--force"],
        &["list", "skills", "--json", "--json"],
        &["check", "skills", "alpha", "beta"],
        &["check", "skills", "--name", "alpha"],
        &["check", "skills", "alpha", "--force"],
        &["check", "skills", "-x"],
        &["check", "skills", ""],
        &["update", "skills", "alpha", "beta", "--force"],
        &["update", "skills", "--name", "alpha"],
        &["update", "skills", "alpha", "--json"],
        &["update", "skills", "--force", "--force"],
        &[
            "publish", "skills", "source", "extra", "--name", "alpha", "--to", "zcode",
        ],
        &["publish", "skills", "source", "--name", "alpha"],
        &["publish", "skills", "source", "--name", "--to", "zcode"],
        &["publish", "skills", "source", "--name", "", "--to", "zcode"],
        &[
            "publish", "skills", "source", "--name", "alpha", "--name", "beta", "--to", "zcode",
        ],
        &["publish", "skills", "source", "--name", "alpha", "--to", ""],
        &[
            "publish", "skills", "source", "--name", "alpha", "--to", "zcode,",
        ],
        &[
            "publish",
            "skills",
            "source",
            "--name",
            "alpha",
            "--to",
            "zcode,zcode",
        ],
        &["project", "skills", "alpha", "extra", "--to", "zcode"],
        &["project", "skills", "alpha", "--to", "zcode,copilot"],
        &[
            "project", "skills", "alpha", "--to", "zcode", "--to", "copilot",
        ],
        &["project", "skills", "alpha", "--from", "zcode"],
        &["unproject", "skills", "alpha", "extra", "--from", "zcode"],
        &["unproject", "skills", "alpha", "--to", "zcode"],
        &["unproject", "skills", "alpha", "--from"],
        &[
            "unpublish",
            "skills",
            "alpha",
            "extra",
            "--with-projections",
        ],
        &["unpublish", "skills", "alpha", "--force"],
        &["install", "skills", "source", "zcode", "alpha", "extra"],
        &["install", "skills", "source", "zcode", "--name", "alpha"],
        &["uninstall", "skills", "zcode", "alpha", "extra"],
        &["copy", "skills", "zcode", "alpha", "copilot", "extra"],
        &["list", "skills", "--trash", "extra"],
        &["restore", "skills", "zcode/alpha", "extra"],
        &["purge", "skills", "zcode/alpha", "extra"],
        &["purge", "skills", "zcode/alpha", "--force"],
        &[
            "install",
            "skills",
            "src",
            "--to",
            "zcode",
            "--harness",
            "codex",
        ],
        &["install", "skills", "--harness", "codex,"],
        &["check", "skills", "--strict"],
        &["check", "skills", "alpha", "--harness", "codex"],
        &["repair", "skills"],
        &["repair", "skills", "--harness", ""],
        &["install", "hooks"],
        &["install", "hooks", "--harness", "zcode"],
        &["install", "hooks", "--harness", "codex", "extra"],
        &["harness", "--"],
        &["harness", "bootstrap", "--home", "relative/path"],
        &["harness", "status", "extra"],
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

    let output = atm(&env, &["update", "skills", "alpha", "beta", "--force"]);
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
    let output = atm(&env, &["update", "skills", "missing"]);
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
    let output = atm(&env, &["update", "skills", "owned"]);
    assert_code(&output, 1);
    assert!(String::from_utf8_lossy(&output.stderr).contains("PROJECTION_BROKEN"));
    assert_eq!(
        fs::read(env.projection("owned").join("SKILL.md")).unwrap(),
        b"TEST_ONLY_edit"
    );
    fs::rename(env.projection("owned"), env.home.path().join("retired")).unwrap();
    write_skill(&env.home.path().join(".zcode/skills"), "owned");
    for arguments in [
        &["update", "skills", "owned"][..],
        &["update", "skills", "owned", "--force"][..],
    ] {
        let output = atm(&env, arguments);
        assert_code(&output, 1);
        assert!(String::from_utf8_lossy(&output.stdout).contains("ownership_unknown"));
        assert!(String::from_utf8_lossy(&output.stderr).contains("PROJECTION_BROKEN"));
    }
}

#[test]
fn environment_override_cannot_expose_or_change_shared_agent_skills() {
    let env = Env::new();
    let source = write_skill(env.sources.path(), "source");
    assert_ok(&atm(
        &env,
        &[
            "install",
            "skills",
            source.to_str().unwrap(),
            "--to",
            "codex",
            "--name",
            "restore-me",
        ],
    ));
    assert_ok(&atm(&env, &["uninstall", "skills", "codex", "restore-me"]));
    assert_ok(&atm(
        &env,
        &[
            "publish",
            "skills",
            source.to_str().unwrap(),
            "--name",
            "owned",
            "--to",
            "codex",
        ],
    ));
    let shared = env.home.path().join(".agents/skills");
    let kept = write_skill(&shared, "kept");
    let before = fs::read(kept.join("SKILL.md")).unwrap();
    let registry = env.manager_data().join("skills-sources/registry.json");
    let receipt = fs::read(&registry).unwrap();
    let run = |args: &[&str]| {
        atm_command(&env, args)
            .env("CODEX_HOME", env.home.path().join(".agents"))
            .output()
            .unwrap()
    };
    let output = run(&["list", "skills", "--json"]);
    assert_ok(&output);
    let inventory: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(inventory["roots"]
        .as_array()
        .unwrap()
        .iter()
        .all(|r| r["id"] != "codex"));
    let check = run(&["check", "skills", "owned", "--json"]);
    assert_code(&check, 1);
    assert_eq!(json_items(&check)[0]["status"], "broken_link");
    for args in [
        vec![
            "install",
            "skills",
            source.to_str().unwrap(),
            "--to",
            "codex",
            "--name",
            "new",
        ],
        vec!["copy", "skills", "codex", "kept", "zcode"],
        vec!["uninstall", "skills", "codex", "kept"],
        vec!["restore", "skills", "codex/restore-me"],
        vec![
            "publish",
            "skills",
            source.to_str().unwrap(),
            "--name",
            "new",
            "--to",
            "codex",
        ],
        vec!["update", "skills", "owned", "--force"],
        vec!["unproject", "skills", "owned", "--from", "codex", "--force"],
        vec!["unpublish", "skills", "owned", "--with-projections"],
    ] {
        let output = run(&args);
        assert_code(&output, 1);
        assert!(String::from_utf8_lossy(&output.stderr).contains("SKILLS_PROTECTED"));
    }
    assert_eq!(fs::read(&registry).unwrap(), receipt);
    assert_eq!(fs::read(kept.join("SKILL.md")).unwrap(), before);
    assert_eq!(fs::read_dir(&shared).unwrap().count(), 1);
    assert!(env
        .home
        .path()
        .join(".codex/skills/owned/SKILL.md")
        .is_file());
    assert_ok(&run(&[
        "install",
        "skills",
        source.to_str().unwrap(),
        "--to",
        "zcode",
        "--name",
        "ordinary",
    ]));
}

// ---------------------------------------------------------------------------
// Rust distribution: no interpreter or external engine is reachable.
mod rust_distribution {
    use super::*;

    fn manager_home(env: &Env) -> PathBuf {
        env.home.path().join("test-atm-harness")
    }

    fn payload(env: &Env) -> PathBuf {
        let source = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../harness")
            .canonicalize()
            .unwrap();
        let bundle = atm_core::distribution::source::load(&source).unwrap();
        let target = env.sources.path().join("payload with spaces 测试");
        fs::create_dir_all(&target).unwrap();
        for directory in bundle.manifest["directories"]
            .as_array()
            .into_iter()
            .flatten()
        {
            fs::create_dir_all(target.join(directory.as_str().unwrap())).unwrap();
        }
        for (relative, bytes) in bundle.files {
            let path = target.join(relative);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, bytes).unwrap();
        }
        fs::copy(
            source.join("distribution-manifest.json"),
            target.join("distribution-manifest.json"),
        )
        .unwrap();
        target
    }

    fn native(env: &Env, args: &[&str]) -> std::process::Output {
        atm_command(env, args).env("PATH", "").output().unwrap()
    }

    fn bootstrap(env: &Env, source: &Path) {
        assert_ok(
            &atm_command(
                env,
                &["harness", "bootstrap", "--source", source.to_str().unwrap()],
            )
            .env("PATH", "")
            .output()
            .unwrap(),
        );
    }

    #[test]
    fn content_export_import_and_offline_cache_are_separate_from_installation() {
        let env = Env::new();
        let root = payload(&env);
        let old: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join("distribution-manifest.json")).unwrap())
                .unwrap();
        let content = serde_json::json!({"schemaVersion":1,"product":"omh-content","releaseVersion":old["releaseVersion"],"packages":old["packages"],"runtimeGroups":old["runtimeGroups"],"runtimeBindings":old["runtimeBindings"],"historicalIdentities":old["historicalIdentities"],"compositions":{"default":old["packages"].as_array().unwrap().iter().map(|p|p["name"].clone()).collect::<Vec<_>>()}});
        fs::write(
            root.join("content-manifest.json"),
            serde_json::to_vec(&content).unwrap(),
        )
        .unwrap();
        fs::write(root.join("LICENSE"), "TEST_ONLY export license").unwrap();
        let archive = env.sources.path().join("content.omh");
        let lock = archive.with_extension("lock.json");
        assert_ok(&native(
            &env,
            &[
                "harness",
                "export",
                "--source",
                root.to_str().unwrap(),
                "--output",
                archive.to_str().unwrap(),
                "--repository",
                "https://github.com/TEST_ONLY/content",
                "--revision",
                &"a".repeat(40),
                "--url",
                "https://github.com/TEST_ONLY/content/releases/download/test/content.omh",
            ],
        ));
        assert!(!manager_home(&env).exists());
        let result = native(
            &env,
            &[
                "harness",
                "import",
                "--archive",
                archive.to_str().unwrap(),
                "--lock",
                lock.to_str().unwrap(),
            ],
        );
        assert_ok(&result);
        let imported: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
        assert_eq!(imported["selected"], false);
        assert!(!manager_home(&env).join("state/distribution.json").exists());
        assert!(!env.home.path().join(".codex").exists());
        fs::remove_file(archive).unwrap();
        assert_ok(&native(
            &env,
            &[
                "harness",
                "fetch",
                "--lock",
                lock.to_str().unwrap(),
                "--output",
                imported["source"].as_str().unwrap(),
            ],
        ));
        bootstrap(&env, Path::new(imported["source"].as_str().unwrap()));
        assert_ok(&native(
            &env,
            &["install", "skills", "--harness", "claude-code,codex"],
        ));
        assert_ok(&native(&env, &["harness", "--", "doctor"]));
        assert!(!manager_home(&env).join("venv").exists());
        assert!(!env.home.path().join(".codex/hooks.json").exists());
    }

    #[test]
    fn static_lifecycle_uses_only_complete_offline_cache_without_python() {
        let env = Env::new();
        let source = payload(&env);
        assert_ok(&native(&env, &["harness", "status", "--json"]));
        assert!(!manager_home(&env).exists());
        bootstrap(&env, &source);
        assert!(!manager_home(&env).join("venv").exists());
        fs::remove_dir_all(&source).unwrap();
        assert_ok(&native(
            &env,
            &["harness", "plan", "install", "--harness", "zcode"],
        ));
        assert!(!env.home.path().join(".zcode").exists());
        assert_ok(&native(&env, &["install", "skills", "--harness", "zcode"]));
        assert_ok(&native(&env, &["update", "skills", "--harness", "zcode"]));
        assert_ok(&native(
            &env,
            &["check", "skills", "--harness", "zcode", "--strict"],
        ));
        let user_file = env.home.path().join(".zcode/user-file.txt");
        fs::write(&user_file, "TEST_ONLY user file").unwrap();
        assert_ok(&native(
            &env,
            &["uninstall", "skills", "--harness", "zcode"],
        ));
        assert_eq!(
            fs::read_to_string(user_file).unwrap(),
            "TEST_ONLY user file"
        );
        assert!(!env.home.path().join(".zcode/AGENTS.md").exists());
    }

    #[test]
    fn native_update_and_remove_refuse_modified_owned_files() {
        let env = Env::new();
        let source = payload(&env);
        bootstrap(&env, &source);
        assert_ok(&native(&env, &["install", "skills", "--harness", "zcode"]));
        let instructions = env.home.path().join(".zcode/AGENTS.md");
        fs::write(&instructions, "TEST_ONLY user revision").unwrap();
        assert_code(
            &native(&env, &["update", "skills", "--harness", "zcode"]),
            1,
        );
        assert_code(
            &native(&env, &["uninstall", "skills", "--harness", "zcode"]),
            1,
        );
        assert_eq!(
            fs::read_to_string(&instructions).unwrap(),
            "TEST_ONLY user revision"
        );
    }

    #[test]
    fn missing_target_retirement_option_is_bounded_to_adoption() {
        let env = Env::new();
        let source = payload(&env);
        let home = env.home.path().join("retirement manager");
        for command in ["bootstrap", "sync", "status"] {
            let output = native(
                &env,
                &[
                    "harness",
                    command,
                    "--home",
                    home.to_str().unwrap(),
                    "--retire-missing",
                    "openclaw",
                ],
            );
            assert_code(&output, 1);
            assert!(String::from_utf8_lossy(&output.stderr).contains("CLI_ARGUMENT"));
            assert!(!home.exists());
        }
        for value in ["openclaw,", "openclaw,openclaw", ","] {
            let output = native(
                &env,
                &[
                    "harness",
                    "adopt",
                    "--home",
                    home.to_str().unwrap(),
                    "--retire-missing",
                    value,
                ],
            );
            assert_code(&output, 1);
            assert!(String::from_utf8_lossy(&output.stderr).contains("CLI_ARGUMENT"));
            assert!(!home.exists());
        }
        let output = native(
            &env,
            &[
                "harness",
                "adopt",
                "--dry-run",
                "--home",
                home.to_str().unwrap(),
                "--source",
                source.to_str().unwrap(),
                "--retire-missing",
                "openclaw",
            ],
        );
        assert_code(&output, 1);
        assert!(String::from_utf8_lossy(&output.stderr).contains("HARNESS_LEGACY_INVALID"));
        assert!(!home.exists());
    }

    #[test]
    fn retired_hook_install_refuses_before_creating_state_or_python() {
        let env = Env::new();
        for args in [
            vec!["install", "hooks", "--harness", "codex"],
            vec!["install", "hooks", "--harness", "codex", "--dry-run"],
        ] {
            let output = native(&env, &args);
            assert_code(&output, 1);
            assert!(String::from_utf8_lossy(&output.stderr).contains("HARNESS_HOOK_RETIRED"));
            assert!(!manager_home(&env).exists());
            assert!(!env.home.path().join(".codex/hooks.json").exists());
        }
    }

    #[test]
    fn adoption_preview_does_not_initialize_an_uninstalled_manager() {
        let env = Env::new();
        let source = payload(&env);
        let home = env.home.path().join("preview manager 测试");
        let output = native(
            &env,
            &[
                "harness",
                "adopt",
                "--dry-run",
                "--source",
                source.to_str().unwrap(),
                "--home",
                home.to_str().unwrap(),
            ],
        );
        assert_code(&output, 1);
        assert!(String::from_utf8_lossy(&output.stderr).contains("HARNESS_LEGACY_INVALID"));
        assert!(!home.exists());
        assert!(!env.home.path().join(".codex").exists());
    }

    #[test]
    fn bootstrap_with_explicit_home_does_not_enable_hooks_or_create_shared_venv() {
        let env = Env::new();
        let source = payload(&env);
        let home = env.home.path().join("chosen manager 测试");
        assert_ok(&native(
            &env,
            &[
                "harness",
                "bootstrap",
                "--source",
                source.to_str().unwrap(),
                "--home",
                home.to_str().unwrap(),
            ],
        ));
        assert!(!manager_home(&env).exists());
        assert!(!home.join("venv").exists());
        assert!(!env.home.path().join(".codex/hooks.json").exists());
        assert!(!env.home.path().join(".codex/config.toml").exists());
        let missing = env.home.path().join("missing python");
        assert_code(
            &native(
                &env,
                &[
                    "harness",
                    "runtime",
                    "prepare",
                    "watcher",
                    "--home",
                    home.to_str().unwrap(),
                    "--python",
                    missing.to_str().unwrap(),
                    "--offline",
                ],
            ),
            1,
        );
        assert!(!env.home.path().join(".codex/hooks.json").exists());
    }

    #[test]
    fn explicit_home_plan_respects_tool_root_overrides_without_writing_targets() {
        let env = Env::new();
        let source = payload(&env);
        bootstrap(&env, &source);
        let codex = env.sources.path().join("overridden Codex 测试");
        let output = atm_command(
            &env,
            &[
                "harness",
                "plan",
                "install",
                "--harness",
                "codex",
                "--home",
                manager_home(&env).to_str().unwrap(),
            ],
        )
        .env("PATH", "")
        .env("CODEX_HOME", &codex)
        .output()
        .unwrap();
        assert_ok(&output);
        let plan: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        let physical_parent = codex.parent().unwrap().canonicalize().unwrap();
        assert!(plan["files"].as_array().unwrap().iter().any(|path| {
            let path = Path::new(path.as_str().unwrap());
            let root = path.parent().unwrap();
            // Windows may expand RUNNER~1 or use a different path prefix.
            // Compare the existing parent identity and exact requested leaf.
            path.file_name().unwrap() == "AGENTS.md"
                && root.file_name() == codex.file_name()
                && root.parent().unwrap().canonicalize().unwrap() == physical_parent
        }));
        assert!(!codex.exists());
        assert!(!env.home.path().join(".codex").exists());
    }

    #[test]
    fn malformed_payload_and_unknown_legacy_commands_never_launch_an_engine() {
        let env = Env::new();
        let payload = env.sources.path().join("invalid");
        fs::create_dir_all(&payload).unwrap();
        fs::write(payload.join("distribution-manifest.json"), "{}").unwrap();
        assert_code(
            &native(
                &env,
                &[
                    "harness",
                    "bootstrap",
                    "--source",
                    payload.to_str().unwrap(),
                ],
            ),
            1,
        );
        assert!(!manager_home(&env).exists());
        for args in [
            vec!["harness", "--", "machine", "--protocol", "1", "status"],
            vec!["harness", "--", "update"],
            vec!["harness", "nope"],
        ] {
            let output = native(&env, &args);
            assert_code(&output, 1);
            assert!(String::from_utf8_lossy(&output.stderr).contains("CLI_COMMAND"));
        }
        assert!(!manager_home(&env).exists());
    }

    #[test]
    fn runtime_preparation_requires_explicit_absolute_interpreter_before_mutation() {
        let env = Env::new();
        for args in [
            vec!["harness", "runtime", "prepare", "watcher"],
            vec![
                "harness", "runtime", "prepare", "watcher", "--python", "python3",
            ],
            vec![
                "harness",
                "runtime",
                "prepare",
                "watcher",
                "--python",
                "relative/python",
            ],
        ] {
            let output = native(&env, &args);
            assert_code(&output, 1);
            assert!(String::from_utf8_lossy(&output.stderr).contains("CLI_ARGUMENT"));
        }
        assert!(!manager_home(&env).exists());
    }
}
