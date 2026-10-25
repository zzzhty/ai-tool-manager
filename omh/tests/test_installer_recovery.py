"""Installer recovery boundaries using disposable homes and local Git objects."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_oh_my_harness as installer
import manager_state
import omh
import omh_bootstrap as bootstrap
import plugin_package_identity


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class InstallerRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "manager with spaces"
        self.origin = self.root / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-b", "main")
        git(self.origin, "config", "user.name", "Recovery Test")
        git(self.origin, "config", "user.email", "test@example.invalid")
        for name in (*bootstrap._REQUIRED_FILES, "scripts/omh_bootstrap.py"):
            target = self.origin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# fixture\n", encoding="utf-8")
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-m", "initial")
        self.initial = git(self.origin, "rev-parse", "HEAD")
        (self.origin / "current.txt").write_text("current revision", encoding="utf-8")
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-m", "current")
        self.current = git(self.origin, "rev-parse", "HEAD")
        self.home.mkdir()
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.home / "repo")], check=True)
        installer.write_install_state(
            home=self.home, repository=str(self.origin), ref="main", repo=self.home / "repo",
            harness="copilot", launchers=installer.launcher_paths(self.home),
            status="ready", revision=self.initial,
        )
        manager_state.derive_initial_state(
            self.home, repository=str(self.origin), revision=self.current,
            release_version="1.0.0", bundle_identity="bundle", persist=True,
        )
        desired_path = self.home / "state/desired.json"
        desired = json.loads(desired_path.read_text())
        desired["harnesses"] = ["copilot", "zcode"]
        desired["updatePolicy"]["channel"] = "stable"
        desired["updatePolicy"]["userSetting"] = "preserve"
        desired_path.write_text(json.dumps(desired), encoding="utf-8")
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        path_patch = mock.patch.object(installer, "ensure_user_path")
        self.path = path_patch.start()
        self.addCleanup(path_patch.stop)

    def invoke(self, *args):
        with mock.patch.object(sys, "argv", ["installer", "--home", str(self.home), *args]):
            installer.main()

    def contents(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def legacy(self):
        (self.home / "state/manager.json").unlink()
        (self.home / "state/desired.json").unlink()

    def test_ready_requires_choice_even_with_yes_and_flags_are_exclusive(self):
        before = self.contents()
        with mock.patch.object(installer, "_interactive_stdin", return_value=False), \
             self.assertRaisesRegex(SystemExit, "choose --repair or --reinstall"):
            self.invoke("--yes")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.invoke("--repair", "--reinstall")
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(before, self.contents())

    def test_interactive_default_and_eof_cancel_without_writes(self):
        before = self.contents()
        for answer in ("", "cancel", EOFError()):
            with self.subTest(answer=answer), mock.patch.object(installer, "_interactive_stdin", return_value=True), \
                 mock.patch("builtins.input", side_effect=[answer]), mock.patch.object(installer, "run") as run:
                self.invoke("--yes")
                run.assert_not_called()
                self.assertEqual(before, self.contents())

    def test_dry_run_preserves_all_files_and_does_not_create_lock(self):
        for mode in ("--repair", "--reinstall"):
            before = self.contents()
            with self.subTest(mode=mode), mock.patch.object(installer, "run") as run:
                self.invoke(mode, "--dry-run", "--no-path")
                run.assert_not_called()
                self.assertEqual(before, self.contents())
                self.assertFalse((self.home / "state/manager.lock").exists())

    def test_repair_delegates_all_installed_harnesses_and_preserves_state(self):
        receipt = (self.home / "state/install.json").read_bytes()
        desired = (self.home / "state/desired.json").read_bytes()
        with mock.patch.object(installer, "run") as run:
            self.invoke("--repair", "--harness", "copilot", "--no-path")
        self.assertEqual(run.call_args.args[0][-4:], ["--home", str(self.home), "repair", "--no-path"])
        self.assertEqual((self.home / "state/install.json").read_bytes(), receipt)
        self.assertEqual((self.home / "state/desired.json").read_bytes(), desired)
        self.path.assert_not_called()

    def test_repair_and_reinstall_allow_alias_convergence_and_preserve_user_policy(self):
        for mode in ("--repair", "--reinstall"):
            path = self.home / "state/desired.json"
            original = json.loads(path.read_text())
            original["harnesses"] = ["copilot", "gemini", "zcode"]
            original["note"] = "user metadata"
            path.write_text(json.dumps(original))
            receipt = (self.home / "state/install.json").read_bytes()

            def child(command):
                payload = json.loads(path.read_text())
                payload["harnesses"] = ["copilot-cli", "gemini-cli", "zcode"]
                payload["updatedAt"] = "changed"
                path.write_text(json.dumps(payload))

            with self.subTest(mode=mode), mock.patch.object(installer, "run", side_effect=child):
                self.invoke(mode, "--harness", "copilot-cli", "--no-path")
            expected = {**original, "harnesses": ["copilot-cli", "gemini-cli", "zcode"]}
            self.assertEqual(json.loads(path.read_text()), expected)
            self.assertEqual((self.home / "state/install.json").read_bytes(), receipt)

    def test_reinstall_preserves_user_files_and_legacy_rewritten_receipts(self):
        runtime = self.home / "venv"
        runtime.mkdir()
        (runtime / "user-note").write_text("keep old runtime data")
        (self.home / "bin").mkdir()
        (self.home / "bin/custom-command").write_text("keep custom command")
        (self.home / "notes").write_text("keep user data")
        receipt = (self.home / "state/install.json").read_bytes()
        desired = (self.home / "state/desired.json").read_bytes()

        def old_manager(command):
            self.assertEqual(command[-3:], ["repair", "--reclone", "--rebuild"])
            self.assertFalse(runtime.exists())
            runtime.mkdir()
            (runtime / "new-runtime").write_text("ready")
            payload = json.loads(receipt)
            payload["revision"] = self.current
            (self.home / "state/install.json").write_text(json.dumps(payload))
            payload = json.loads(desired)
            del payload["updatePolicy"]["userSetting"]
            (self.home / "state/desired.json").write_text(json.dumps(payload))

        with mock.patch.object(installer, "run", side_effect=old_manager):
            self.invoke("--reinstall")
        self.assertEqual((self.home / "state/install.json").read_bytes(), receipt)
        self.assertEqual((self.home / "state/desired.json").read_bytes(), desired)
        backup, = (self.home / "state/repair-backups").glob("venv-*")
        self.assertEqual((backup / "user-note").read_text(), "keep old runtime data")
        self.assertTrue((runtime / "new-runtime").is_file())
        self.assertEqual((self.home / "bin/custom-command").read_text(), "keep custom command")
        self.assertEqual((self.home / "notes").read_text(), "keep user data")

    def test_failed_reinstall_restores_runtime_and_propagates_failure(self):
        (self.home / "venv").mkdir()
        (self.home / "venv/keep").write_text("old")
        receipt = (self.home / "state/install.json").read_bytes()
        with mock.patch.object(installer, "run", side_effect=subprocess.CalledProcessError(37, ["repair"])), \
             self.assertRaises(subprocess.CalledProcessError) as error:
            self.invoke("--reinstall")
        self.assertEqual(error.exception.returncode, 37)
        self.assertEqual((self.home / "venv/keep").read_text(), "old")
        self.assertEqual((self.home / "state/install.json").read_bytes(), receipt)
        with bootstrap._mutation_lock(self.home):
            pass  # Failure released the shared manager lock.

    def test_recovery_does_not_hide_corrupt_or_unexpected_child_state(self):
        for name, payload in (("install.json", "{broken"),
                              ("desired.json", '{"harnesses": ["other"]}')):
            path = self.home / "state" / name
            original = path.read_bytes()
            def damage(command):
                path.write_text(payload)
            with self.subTest(name=name), mock.patch.object(installer, "run", side_effect=damage), \
                 self.assertRaisesRegex(SystemExit, "preserved"):
                self.invoke("--repair")
            self.assertEqual(path.read_text(), payload)
            path.write_bytes(original)

    def test_legacy_migration_uses_current_managed_revision_and_dry_run_is_read_only(self):
        self.legacy()
        receipt = (self.home / "state/install.json").read_bytes()
        before = self.contents()
        with mock.patch.object(plugin_package_identity, "require_repository_identity",
                               return_value={"releaseVersion": "1.0.0", "bundleIdentity": "bundle"}), \
             mock.patch.object(installer, "run"):
            self.invoke("--repair", "--dry-run")
            self.assertEqual(before, self.contents())
            self.invoke("--repair")
        manager = json.loads((self.home / "state/manager.json").read_text())
        self.assertEqual(manager["revision"], self.current)
        self.assertNotEqual(manager["revision"], self.initial)
        self.assertEqual((self.home / "state/install.json").read_bytes(), receipt)

    def test_legacy_dirty_foreign_or_missing_checkout_is_not_migrated(self):
        self.legacy()
        (self.home / "repo/user-work").write_text("unpublished")
        before = self.contents()
        with self.assertRaisesRegex(SystemExit, "uncommitted"):
            self.invoke("--repair")
        self.assertEqual(before, self.contents())
        (self.home / "repo/user-work").unlink()
        git(self.home / "repo", "remote", "set-url", "origin", "foreign")
        with self.assertRaisesRegex(SystemExit, "remote does not match"):
            self.invoke("--repair")
        (self.home / "repo").rename(self.root / "removed-repo")
        with self.assertRaisesRegex(SystemExit, "legacy managed repository"):
            self.invoke("--repair")
        self.assertFalse((self.home / "state/manager.json").exists())

    def test_damaged_state_and_unsupported_journal_fail_before_mutation(self):
        manager_path = self.home / "state/manager.json"
        original = manager_path.read_bytes()
        for payload in (b"{broken", b'{"product":"foreign"}'):
            manager_path.write_bytes(payload)
            before = self.contents()
            with self.assertRaises(SystemExit):
                self.invoke("--reinstall")
            self.assertEqual(before, self.contents())
        manager_path.unlink()
        before = self.contents()
        with self.assertRaisesRegex(SystemExit, "lifecycle state is incomplete"):
            self.invoke("--repair")
        self.assertEqual(before, self.contents())
        manager_path.write_bytes(original)
        operations = self.home / "state/operations"
        operations.mkdir()
        (operations / "current.json").write_text('{"command":"unknown"}')
        with self.assertRaisesRegex(SystemExit, "unsupported interrupted"):
            self.invoke("--reinstall")
        self.assertFalse((self.home / "bootstrap").exists())
        self.assertEqual((operations / "current.json").read_text(), '{"command":"unknown"}')

    def test_ready_recovery_rejects_source_harness_and_path_changes(self):
        before = self.contents()
        for args in (("--repository", "foreign"), ("--ref", "other"), ("--harness", "claude"),
                     ("--adopt-current-checkout",), ("--resume-fast-forward",)):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.invoke("--repair", *args)
            self.assertEqual(before, self.contents())
        receipt_path = self.home / "state/install.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["paths"]["home"] = str(self.root / "other")
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(SystemExit, "does not prove ownership"):
            self.invoke("--reinstall")
        self.assertFalse((self.home / "state/manager.lock").exists())

    def test_recovery_flags_cannot_initialize_a_new_home_or_bypass_incomplete_gates(self):
        receipt = self.home / "state/install.json"
        payload = json.loads(receipt.read_text())
        payload["status"] = "installing"
        receipt.write_text(json.dumps(payload))
        for mode in ("--repair", "--reinstall"):
            with self.assertRaisesRegex(SystemExit, "incomplete installation"):
                self.invoke(mode)
        receipt.unlink()
        for mode in ("--repair", "--reinstall"):
            with self.assertRaisesRegex(SystemExit, "existing owned installation"):
                self.invoke(mode)
        self.assertFalse((self.home / "state/manager.lock").exists())

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_linked_managed_components_are_preserved(self):
        outside = self.root / "outside"
        outside.mkdir()
        for name in ("venv", "bin", "bootstrap", "state/repair-backups", "state/harnesses"):
            link = self.home / name
            link.symlink_to(outside, target_is_directory=True)
            with self.subTest(name=name), self.assertRaisesRegex(SystemExit, "ordinary directory"):
                self.invoke("--reinstall")
            self.assertTrue(link.is_symlink())
            link.unlink()
        self.assertEqual(list(outside.iterdir()), [])

    def test_concurrent_manager_mutation_blocks_recovery_before_launcher_writes(self):
        with manager_state.ManagerLock(self.home), self.assertRaisesRegex(SystemExit, "already running"):
            self.invoke("--reinstall")
        self.assertFalse((self.home / "bootstrap").exists())

    def test_interrupted_update_retains_ownership_of_desired_rollback(self):
        operations = self.home / "state/operations"
        operations.mkdir()
        (operations / "current.json").write_text(json.dumps({
            "command": "update", "before": {"revision": self.initial},
            "target": {"revision": self.current},
        }))
        desired_path = self.home / "state/desired.json"
        rollback = json.loads(desired_path.read_text())
        rollback["harnesses"] = ["zcode"]
        rollback["updatePolicy"]["channel"] = "main"

        def recover(command):
            desired_path.write_text(json.dumps(rollback))
            (operations / "current.json").unlink()

        with mock.patch.object(installer, "run", side_effect=recover):
            self.invoke("--repair")
        self.assertEqual(json.loads(desired_path.read_text()), rollback)

    def test_direct_manager_repair_keeps_ready_receipt_and_desired_policy(self):
        manager, desired = installer._lifecycle_state(self.home)
        receipt = (self.home / "state/install.json").read_bytes()
        desired_bytes = (self.home / "state/desired.json").read_bytes()
        args = omh.build_parser().parse_args(["--home", str(self.home), "repair", "--no-path"])
        with mock.patch.object(omh, "_state_context", return_value=(manager, desired)), \
             mock.patch.object(omh, "_bootstrap_tooling"), mock.patch.object(installer, "write_launchers"), \
             mock.patch.object(omh, "_refresh_one") as refresh, mock.patch.object(omh, "_write_harness_state"):
            omh.command_manager_repair(args)
        self.assertEqual(refresh.call_count, 2)
        self.assertEqual((self.home / "state/install.json").read_bytes(), receipt)
        current = json.loads((self.home / "state/desired.json").read_bytes())
        previous = json.loads(desired_bytes)
        self.assertEqual(current["harnesses"], ["copilot-cli", "zcode"])
        self.assertEqual(current["updatePolicy"], previous["updatePolicy"])


if __name__ == "__main__":
    unittest.main()
