from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import install_oh_my_harness as installer  # noqa: E402


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(installer, "ensure_user_path")
        self.ensure_user_path = patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def seed_bootstrap(repo: Path) -> None:
        source = REPO_ROOT / "scripts" / "omh_bootstrap.py"
        target = repo / "scripts" / "omh_bootstrap.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        registry = repo / ".agents/harnesses/registry.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / ".agents/harnesses/registry.json", registry)

    def test_launcher_help_uses_platform_wrapper_syntax(self) -> None:
        self.assertEqual(installer.launcher_help_invocation("nt"), "omh --help")
        self.assertEqual(installer.launcher_help_invocation("posix"), "omh --help")

    @unittest.skipUnless(os.name == "nt", "Windows batch execution")
    def test_running_launcher_preserves_exit_code_when_update_replaces_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "manager home (test)&!"
            env = {**os.environ, "OH_MY_HARNESS_BOOTSTRAP_PYTHON": sys.executable}
            for exit_code in (0, 7):
                with self.subTest(exit_code=exit_code), contextlib.redirect_stdout(io.StringIO()):
                    launcher = installer.write_launchers(home=home, repo=REPO_ROOT, dry_run=False)[1]
                    # A changed future launcher must not be read by this running CMD.
                    replacement = "@echo off\r\n" + "rem future launcher padding\r\n" * 120 + "exit /b 91\r\n"
                    shim = (
                        "import sys\nfrom pathlib import Path\nfrom unittest import mock\n"
                        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
                        "import install_oh_my_harness as installer\n"
                        "assert sys.argv[4] == 'argument with spaces (test)&!'\n"
                        "assert sys.argv[5] == 'literal|<>^'\n"
                        f"with mock.patch.object(installer, 'expected_launcher_content', return_value={replacement!r}):\n"
                        f"    installer.write_launchers(home=Path(sys.argv[2]), repo=Path({str(REPO_ROOT)!r}), dry_run=False)\n"
                        "sys.exit(int(sys.argv[3]))\n"
                    )
                    installer._bootstrap_script_path(home).write_text(shim, encoding="utf-8")
                    completed = subprocess.run(
                        f'cmd.exe /d /s /c ""{launcher}" {exit_code} "argument with spaces (test)&!" "literal|<>^""',
                        env=env, capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(completed.returncode, exit_code, completed.stdout + completed.stderr)

    def test_unsupported_python_is_rejected_before_manager_home_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            with (
                mock.patch.object(installer.sys, "version_info", (3, 10, 13)),
                mock.patch.object(
                    installer.sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        "https://example.invalid/oh-my-harness.git",
                        "--dry-run",
                    ],
                ),
                mock.patch.object(installer, "run") as run,
                self.assertRaisesRegex(SystemExit, "Python 3.11 or newer is required"),
            ):
                installer.main()

            run.assert_not_called()
            self.assertFalse(home.exists())

    @unittest.skipIf(os.name == "nt", "POSIX launcher assertion")
    def test_long_and_short_launchers_are_identical_ordinary_executables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            launchers = installer.write_launchers(home=home, repo=repo, dry_run=False)

            long_command, short_command = launchers
            self.assertFalse(long_command.is_symlink())
            self.assertFalse(short_command.is_symlink())
            self.assertEqual(
                long_command.read_text(encoding="utf-8"),
                short_command.read_text(encoding="utf-8"),
            )
            content = long_command.read_text(encoding="utf-8")
            self.assertIn('"$omh_home/bootstrap/omh_bootstrap.py"', content)
            self.assertIn('--home "$omh_home"', content)
            self.assertTrue(long_command.stat().st_mode & stat.S_IXUSR)

    def test_windows_aliases_dispatch_to_one_powershell_wrapper(self) -> None:
        home = Path(r"C:\Users\Tester\.oh-my-harness")
        repo = home / "repo"
        content = installer.windows_launcher(home=home, repo=repo)
        self.assertIn('%OMH_HOME%\\bootstrap\\omh_bootstrap.py', content)
        self.assertIn('--home "', content)
        self.assertIn("%*", content)

    def test_install_refuses_existing_manager_owned_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            (home / "venv").mkdir(parents=True)
            with self.assertRaisesRegex(SystemExit, "existing manager-owned paths"):
                installer.validate_install_root(home)

    def test_adoption_allows_only_the_exact_existing_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            installer.validate_install_root(home, adopted_repo=repo)

            (home / "bin").mkdir()
            with self.assertRaisesRegex(SystemExit, "existing manager-owned paths"):
                installer.validate_install_root(home, adopted_repo=repo)

    def test_ordinary_directory_rejects_windows_reparse_metadata(self) -> None:
        metadata = mock.Mock(
            st_mode=stat.S_IFDIR,
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
        )
        with mock.patch.object(Path, "lstat", return_value=metadata):
            self.assertFalse(installer.is_ordinary_directory(Path("managed")))

    @unittest.skipIf(os.name == "nt", "POSIX symlink setup")
    def test_recovery_rejects_a_linked_state_root_before_reading_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / ".oh-my-harness"
            external_state = root / "external-state"
            home.mkdir()
            external_state.mkdir()
            external_state.joinpath("install.json").write_text("{}\n", encoding="utf-8")
            (home / "state").symlink_to(external_state, target_is_directory=True)

            with mock.patch.object(
                sys,
                "argv",
                [
                    "install_oh_my_harness.py",
                    "--home",
                    str(home),
                    "--repository",
                    "https://example.invalid/oh-my-harness.git",
                ],
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "managed state root must be an ordinary directory",
                ):
                    installer.main()

    @unittest.skipIf(os.name == "nt", "POSIX symlink setup")
    def test_recovery_rejects_a_linked_repository_root_before_git_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / ".oh-my-harness"
            external_repo = root / "external-repo"
            (home / "state").mkdir(parents=True)
            (home / "state" / "install.json").write_text("{}\n", encoding="utf-8")
            external_repo.mkdir()
            (home / "repo").symlink_to(external_repo, target_is_directory=True)

            with mock.patch.object(
                sys,
                "argv",
                [
                    "install_oh_my_harness.py",
                    "--home",
                    str(home),
                    "--repository",
                    "https://example.invalid/oh-my-harness.git",
                ],
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "managed repository root must be an ordinary directory",
                ):
                    installer.main()

    def test_dry_run_does_not_create_manager_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        "https://example.invalid/oh-my-harness.git",
                        "--dry-run",
                    ],
                ),
                mock.patch.object(installer, "run") as run,
            ):
                installer.main()

            self.assertFalse(home.exists())
            run.assert_called_once()
            self.assertTrue(run.call_args.kwargs["dry_run"])

    def test_adopted_checkout_forwards_the_exact_retired_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            retired_repo = Path(tmp) / "former-checkout"
            with (
                mock.patch.object(installer, "SOURCE_ROOT", repo),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        "https://example.invalid/oh-my-harness.git",
                        "--adopt-current-checkout",
                        "--migrate-from-repo",
                        str(retired_repo),
                    ],
                ),
                mock.patch.object(installer, "write_install_state"),
                mock.patch.object(installer, "invoke_refresh") as refresh,
            ):
                installer.main()

            self.assertTrue(installer.launcher_paths(home)[1].is_file())
            self.assertEqual(
                refresh.call_args.kwargs["migrate_from_repo"],
                retired_repo,
            )

    def test_bootstrap_alias_uses_canonical_receipt_and_refresh_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "manager"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            with (
                mock.patch.object(installer, "SOURCE_ROOT", repo),
                mock.patch.object(sys, "argv", [
                    "install_oh_my_harness.py", "--home", str(home),
                    "--repository", "https://example.invalid/repo.git",
                    "--harness", "copilot", "--adopt-current-checkout",
                ]),
                mock.patch.object(installer, "installed_revision", return_value="a" * 40),
                mock.patch.object(installer, "invoke_refresh") as refresh,
            ):
                installer.main()
            self.assertEqual(refresh.call_args.kwargs["harness"], "copilot-cli")
            receipt = json.loads((home / "state/install.json").read_text())
            self.assertEqual(receipt["harness"], "copilot-cli")
            self.assertEqual(receipt["status"], "ready")

    def test_bootstrap_old_ref_uses_target_canonical_receipt_and_command(self) -> None:
        for target_name in ("copilot-cli", "copilot"):
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "manager"
                repo = home / "repo"
                repo.mkdir(parents=True)
                self.seed_bootstrap(repo)
                target_registry = repo / ".agents/harnesses/registry.json"
                payload = json.loads(target_registry.read_text())
                for short in ("copilot", "gemini"):
                    if target_name == "copilot":
                        # Model ADR 0018's short-canonical revision, not today's registry.
                        entry = payload["harnesses"].pop(short + "-cli")
                        entry["aliases"] = [short + "-cli"]
                        payload["harnesses"][short] = entry
                    else:
                        # The older pre-alias revision accepted only the full key.
                        payload["harnesses"][short + "-cli"].pop("aliases", None)
                target_registry.write_text(json.dumps(payload))
                with (
                    mock.patch.object(installer, "SOURCE_ROOT", repo),
                    mock.patch.object(sys, "argv", ["installer", "--home", str(home),
                        "--repository", "https://example.invalid/repo.git", "--harness", "copilot-cli",
                        "--adopt-current-checkout"]),
                    mock.patch.object(installer, "installed_revision", return_value="a" * 40),
                    mock.patch.object(installer, "invoke_refresh") as refresh,
                ):
                    installer.main()
                self.assertEqual(refresh.call_args.kwargs["harness"], target_name)
                self.assertEqual(json.loads((home / "state/install.json").read_text())["harness"], target_name)

    def test_unknown_bootstrap_harness_fails_before_creating_manager_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "manager"
            error = io.StringIO()
            with (
                mock.patch.object(sys, "argv", [
                    "install_oh_my_harness.py", "--home", str(home), "--harness", "copliot",
                ]),
                mock.patch.object(installer, "clone_repository") as clone,
                contextlib.redirect_stderr(error),
                self.assertRaises(SystemExit) as raised,
            ):
                installer.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("copilot = copilot-cli", error.getvalue())
            self.assertFalse(home.exists())
            clone.assert_not_called()

    def test_repeated_incomplete_install_keeps_exact_checkout_gate_from_either_source(self) -> None:
        for external in (False, True):
            with self.subTest(external=external), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / ".oh-my-harness"
                repo = home / "repo"
                repo.mkdir(parents=True)
                source = Path(tmp) / "external-checkout" if external else repo
                self.seed_bootstrap(source)
                repository = "https://example.invalid/oh-my-harness.git"
                with mock.patch.object(installer, "installed_revision", return_value="a" * 40):
                    installer.write_install_state(
                        home=home, repository=repository, ref="main", repo=repo,
                        harness="codex", launchers=installer.launcher_paths(home), status="installing",
                    )
                before = (home / "state/install.json").read_bytes()
                with (
                    mock.patch.object(installer, "SOURCE_ROOT", source),
                    mock.patch.object(sys, "argv", ["installer", "--home", str(home), "--repository", repository]),
                    mock.patch.object(installer, "clone_repository") as clone,
                    mock.patch.object(installer, "run") as run,
                    mock.patch.object(installer, "invoke_refresh") as refresh,
                    self.assertRaisesRegex(SystemExit, "managed checkout revision is unavailable"),
                ):
                    installer.main()
                clone.assert_not_called()
                refresh.assert_not_called()
                run.assert_not_called()
                self.assertFalse(installer.launcher_paths(home)[1].exists())
                self.ensure_user_path.assert_not_called()
                self.assertEqual((home / "state/install.json").read_bytes(), before)

    def test_exact_resume_rejects_a_dirty_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            repository = "https://example.invalid/oh-my-harness.git"
            revision = "1" * 40
            with mock.patch.object(installer, "installed_revision", return_value=revision):
                launchers = installer.write_launchers(home=home, repo=repo, dry_run=False)
                installer.write_install_state(
                    home=home,
                    repository=repository,
                    ref="main",
                    repo=repo,
                    harness="codex",
                    launchers=launchers,
                    status="installing",
                )

            dirty = subprocess.CompletedProcess(
                ["git", "status", "--porcelain"],
                0,
                stdout=" M scripts/install_oh_my_harness.py\n",
                stderr="",
            )
            with (
                mock.patch.object(installer, "installed_revision", return_value=revision),
                mock.patch.object(installer.subprocess, "run", return_value=dirty),
            ):
                with self.assertRaisesRegex(SystemExit, "uncommitted changes"):
                    installer.validate_incomplete_adoption(
                        home=home,
                        repo=repo,
                        repository=repository,
                        ref="main",
                        harness="codex",
                    )

    def test_recovery_keeps_the_validated_revision_when_head_moves_during_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            repository = "https://example.invalid/oh-my-harness.git"
            original_revision = "1" * 40
            changed_revision = "2" * 40
            with mock.patch.object(
                installer,
                "installed_revision",
                return_value=original_revision,
            ):
                launchers = installer.write_launchers(home=home, repo=repo, dry_run=False)
                installer.write_install_state(
                    home=home,
                    repository=repository,
                    ref="main",
                    repo=repo,
                    harness="codex",
                    launchers=launchers,
                    status="installing",
                )

            with (
                mock.patch.object(installer, "SOURCE_ROOT", repo),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        repository,
                        "--harness",
                        "codex",
                        "--adopt-current-checkout",
                    ],
                ),
                mock.patch.object(
                    installer,
                    "installed_revision",
                    side_effect=[
                        original_revision,
                        original_revision,
                        changed_revision,
                    ],
                ),
                mock.patch.object(installer, "validate_checkout_clean_and_remote"),
                mock.patch.object(installer, "invoke_refresh") as refresh,
            ):
                with self.assertRaisesRegex(SystemExit, "revision changed after refresh"):
                    installer.main()

            refresh.assert_called_once()
            state = json.loads(
                (home / "state" / "install.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "installing")
            self.assertEqual(state["revision"], original_revision)

    @unittest.skipUnless(shutil.which("git"), "Git fast-forward resume test")
    def test_explicit_fast_forward_resume_accepts_a_clean_pushed_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / ".oh-my-harness"
            repo = home / "repo"
            remote = root / "remote.git"

            def git(*arguments: str) -> str:
                result = subprocess.run(
                    ["git", *arguments],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()

            git("init", "--bare", str(remote))
            git("clone", str(remote), str(repo))
            self.seed_bootstrap(repo)
            git("-C", str(repo), "config", "user.name", "Installer Test")
            git("-C", str(repo), "config", "user.email", "installer@example.invalid")
            repo.joinpath("seed.txt").write_text("old\n", encoding="utf-8")
            git("-C", str(repo), "add", "seed.txt", "scripts/omh_bootstrap.py", ".agents")
            git("-C", str(repo), "commit", "-m", "old")
            git("-C", str(repo), "branch", "-M", "main")
            git("-C", str(repo), "push", "-u", "origin", "main")
            old_revision = installer.installed_revision(repo)

            launchers = installer.write_launchers(home=home, repo=repo, dry_run=False)
            installer.write_install_state(
                home=home,
                repository=str(remote),
                ref="main",
                repo=repo,
                harness="copilot-cli",
                launchers=launchers,
                status="installing",
            )

            repo.joinpath("seed.txt").write_text("new\n", encoding="utf-8")
            git("-C", str(repo), "add", "seed.txt")
            git("-C", str(repo), "commit", "-m", "new")
            git("-C", str(repo), "push", "origin", "main")
            new_revision = installer.installed_revision(repo)

            with (
                mock.patch.object(installer, "SOURCE_ROOT", repo),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        str(remote),
                        "--harness",
                        "copilot",
                        "--resume-fast-forward",
                    ],
                ),
                mock.patch.object(installer, "invoke_refresh") as refresh,
            ):
                installer.main()

            refresh.assert_called_once()
            state = json.loads(
                (home / "state" / "install.json").read_text(encoding="utf-8")
            )
            self.assertNotEqual(old_revision, new_revision)
            self.assertEqual(state["revision"], new_revision)
            self.assertEqual(state["status"], "ready")
            self.assertEqual(state["harness"], "copilot-cli")
            self.assertEqual(refresh.call_args.kwargs["harness"], "copilot-cli")

    def test_fast_forward_resume_rejects_a_dirty_checkout(self) -> None:
        dirty = subprocess.CompletedProcess(
            ["git", "status", "--porcelain"],
            0,
            stdout="?? local-change.txt\n",
            stderr="",
        )
        with mock.patch.object(installer.subprocess, "run", return_value=dirty):
            with self.assertRaisesRegex(SystemExit, "uncommitted changes"):
                installer.validate_revision_fast_forward(
                    repo=Path("managed-repo"),
                    repository="https://example.invalid/oh-my-harness.git",
                    ref="main",
                    previous_revision="1" * 40,
                    current_revision="2" * 40,
                )

    def test_revision_drift_still_fails_without_explicit_fast_forward_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            repository = "https://example.invalid/oh-my-harness.git"
            with mock.patch.object(installer, "installed_revision", return_value="1" * 40):
                launchers = installer.write_launchers(home=home, repo=repo, dry_run=False)
                installer.write_install_state(
                    home=home,
                    repository=repository,
                    ref="main",
                    repo=repo,
                    harness="codex",
                    launchers=launchers,
                    status="installing",
                )

            with mock.patch.object(installer, "installed_revision", return_value="2" * 40):
                with self.assertRaisesRegex(SystemExit, "mismatched fields: revision"):
                    installer.validate_incomplete_adoption(
                        home=home,
                        repo=repo,
                        repository=repository,
                        ref="main",
                        harness="codex",
                    )

    def test_fast_forward_resume_rejects_unpublished_or_non_descendant_head(self) -> None:
        clean = subprocess.CompletedProcess(
            ["git", "status", "--porcelain"],
            0,
            stdout="",
            stderr="",
        )
        current_revision = "2" * 40
        cases = (
            (
                "unpublished",
                subprocess.CompletedProcess(
                    ["git", "rev-parse"],
                    0,
                    stdout="3" * 40 + "\n",
                    stderr="",
                ),
                None,
                "not the published requested ref",
            ),
            (
                "non-descendant",
                subprocess.CompletedProcess(
                    ["git", "rev-parse"],
                    0,
                    stdout=current_revision + "\n",
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    ["git", "merge-base", "--is-ancestor"],
                    1,
                    stdout="",
                    stderr="",
                ),
                "did not fast-forward",
            ),
        )
        for label, remote, ancestor, expected in cases:
            results = [clean, remote]
            if ancestor is not None:
                results.append(ancestor)
            with (
                self.subTest(label=label),
                mock.patch.object(
                    installer,
                    "repository_from_checkout",
                    return_value="https://example.invalid/oh-my-harness.git",
                ),
                mock.patch.object(installer.subprocess, "run", side_effect=results),
            ):
                with self.assertRaisesRegex(SystemExit, expected):
                    installer.validate_revision_fast_forward(
                        repo=Path("managed-repo"),
                        repository="https://example.invalid/oh-my-harness.git",
                        ref="main",
                        previous_revision="1" * 40,
                        current_revision=current_revision,
                    )

    def test_fast_forward_resume_requires_an_incomplete_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        "https://example.invalid/oh-my-harness.git",
                        "--resume-fast-forward",
                    ],
                ),
                mock.patch.object(installer, "clone_repository") as clone,
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "requires an incomplete installation state",
                ):
                    installer.main()

            clone.assert_not_called()

    def test_managed_checkout_without_installing_state_requires_explicit_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            with (
                mock.patch.object(installer, "SOURCE_ROOT", repo),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "install_oh_my_harness.py",
                        "--home",
                        str(home),
                        "--repository",
                        "https://example.invalid/oh-my-harness.git",
                    ],
                ),
                mock.patch.object(installer, "clone_repository") as clone,
            ):
                with self.assertRaisesRegex(SystemExit, "existing manager-owned paths"):
                    installer.main()

            clone.assert_not_called()

    def test_incomplete_install_accepts_exact_crlf_launcher_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            repository = "https://example.invalid/oh-my-harness.git"
            expected_content = "@echo off\r\nexit /b 0\r\n"
            launchers = installer.launcher_paths(home)
            for launcher in launchers:
                launcher.parent.mkdir(parents=True, exist_ok=True)
                launcher.write_text(expected_content, encoding="utf-8", newline="")

            with (
                mock.patch.object(installer, "installed_revision", return_value="abc123"),
                mock.patch.object(
                    installer,
                    "expected_launcher_content",
                    return_value=expected_content,
                ),
                mock.patch.object(installer, "validate_checkout_clean_and_remote"),
            ):
                installer.write_install_state(
                    home=home,
                    repository=repository,
                    ref="main",
                    repo=repo,
                    harness="codex",
                    launchers=launchers,
                    status="installing",
                )
                recovery = installer.validate_incomplete_adoption(
                    home=home,
                    repo=repo,
                    repository=repository,
                    ref="main",
                    harness="codex",
                )

            self.assertIsNotNone(recovery)
            assert recovery is not None
            self.assertEqual(
                recovery.allowed_existing,
                frozenset({home / "venv", home / "bin", home / "state", home / "bootstrap"}),
            )

    def test_exact_installing_state_rejects_shape_and_launcher_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".oh-my-harness"
            repo = home / "repo"
            repo.mkdir(parents=True)
            self.seed_bootstrap(repo)
            repository = "https://example.invalid/oh-my-harness.git"
            launchers = installer.write_launchers(home=home, repo=repo, dry_run=False)
            with (
                mock.patch.object(installer, "installed_revision", return_value="abc123"),
                mock.patch.object(installer, "validate_checkout_clean_and_remote"),
            ):
                installer.write_install_state(
                    home=home,
                    repository=repository,
                    ref="main",
                    repo=repo,
                    harness="codex",
                    launchers=launchers,
                    status="installing",
                )
                state_file = home / "state" / "install.json"
                payload = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(
                    set(payload),
                    {
                        "product",
                        "status",
                        "repository",
                        "ref",
                        "revision",
                        "harness",
                        "paths",
                    },
                )
                recovery = installer.validate_incomplete_adoption(
                    home=home,
                    repo=repo,
                    repository=repository,
                    ref="main",
                    harness="codex",
                )

                self.assertIsNotNone(recovery)
                assert recovery is not None
                self.assertEqual(
                    recovery.allowed_existing,
                    frozenset({home / "venv", home / "bin", home / "state", home / "bootstrap"}),
                )
                installer.validate_install_root(
                    home,
                    adopted_repo=repo,
                    allowed_existing=recovery.allowed_existing,
                )

                invalid_payloads = {
                    "legacy schemaVersion": {**payload, "schemaVersion": 1},
                    "missing product": {
                        key: value for key, value in payload.items() if key != "product"
                    },
                }
                for case, invalid_payload in invalid_payloads.items():
                    with self.subTest(case=case):
                        state_file.write_text(
                            json.dumps(
                                invalid_payload,
                                ensure_ascii=False,
                                indent=2,
                                sort_keys=True,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                        with self.assertRaisesRegex(SystemExit, "unsupported shape"):
                            installer.validate_incomplete_adoption(
                                home=home,
                                repo=repo,
                                repository=repository,
                                ref="main",
                                harness="codex",
                            )

                state_file.write_text(
                    json.dumps(
                        {**payload, "status": "ready"},
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(SystemExit, "mismatched fields: status"):
                    installer.validate_incomplete_adoption(
                        home=home,
                        repo=repo,
                        repository=repository,
                        ref="main",
                        harness="codex",
                    )

                state_file.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                launchers[1].write_text("drift\n", encoding="utf-8")
                with self.assertRaisesRegex(SystemExit, "launcher content changed"):
                    installer.validate_incomplete_adoption(
                        home=home,
                        repo=repo,
                        repository=repository,
                        ref="main",
                        harness="codex",
                    )

    def test_cli_reports_expected_and_command_failures_without_tracebacks(self) -> None:
        cases = (
            (
                SystemExit("specific installation failure"),
                1,
                "error: specific installation failure",
            ),
            (
                subprocess.CalledProcessError(17, ["git", "clone", "source", "target"]),
                17,
                "error: command failed with exit code 17: git clone source target",
            ),
        )
        for failure, expected_code, expected_message in cases:
            with self.subTest(failure=type(failure).__name__):
                stderr = io.StringIO()
                with (
                    mock.patch.object(installer, "main", side_effect=failure),
                    contextlib.redirect_stderr(stderr),
                ):
                    exit_code = installer.cli()

                self.assertEqual(exit_code, expected_code)
                self.assertIn(expected_message, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())


@unittest.skipUnless(
    os.name == "nt" and shutil.which("powershell.exe"),
    "Windows PowerShell wrapper test",
)
class PowerShellInstallerWrapperTests(unittest.TestCase):
    def test_python_failure_is_reported_without_a_powershell_exception(self) -> None:
        environment = dict(os.environ)
        environment["OH_MY_HARNESS_BOOTSTRAP_PYTHON"] = sys.executable
        result = subprocess.run(
            [
                shutil.which("powershell.exe") or "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(REPO_ROOT / "install.ps1"),
                "-MigrateMarketplace",
                "--home",
                "relative-manager-home",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "error: OH_MY_HARNESS_HOME must be an absolute path",
            result.stderr,
        )
        self.assertIn("installation failed with exit code", result.stderr)
        self.assertNotIn("\x1b", result.stderr)
        self.assertNotIn("Exception:", result.stderr)
        self.assertNotIn("At ", result.stderr)

    def test_wrapper_uses_console_color_only_for_interactive_errors(self) -> None:
        script = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("function Write-AccentError", script)
        self.assertIn("[Console]::IsErrorRedirected", script)
        self.assertIn("[Console]::ForegroundColor", script)
        self.assertIn("Test-Path Env:NO_COLOR", script)
        self.assertIn("[switch]$MigrateMarketplace", script)
        self.assertIn('$forwardedInstallerArguments += "--migrate-marketplace"', script)


if __name__ == "__main__":
    unittest.main()
