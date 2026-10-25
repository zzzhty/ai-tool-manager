"""Regression tests for update rollback and external user PATH ownership."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import install_oh_my_harness as installer
import manager_environment as environment
import omh


class RuntimeRollbackTests(unittest.TestCase):
    @contextlib.contextmanager
    def transaction(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            home = Path(tmp) / "manager"
            repo = home / "repo"
            source = repo / "scripts/omh_bootstrap.py"
            source.parent.mkdir(parents=True)
            source.write_text("# original runtime\n", encoding="utf-8")
            installer.write_launchers(home=home, repo=repo, dry_run=False)
            for path in (*installer.launcher_paths(home), home / "bootstrap/omh_bootstrap.py"):
                path.write_text("# incompatible target runtime\n", encoding="utf-8")
            manager = dict(repository="source", revision="old", releaseVersion="1.0.0",
                           bundleIdentity="bundle", channel="main", requestedRef="main")
            operation = {"operationId": "test-operation", "command": "update",
                         "before": manager, "target": manager}
            for name, value in {
                "REPO_ROOT": repo, "load_current_operation": operation,
                "_journal_instruction_transition": operation, "_revision": "old",
                "_distribution": ("1.0.0", "bundle"),
                "_state_context": (manager, {"harnesses": []}),
            }.items():
                patch = mock.patch.object(omh, name, value) if name == "REPO_ROOT" else mock.patch.object(omh, name, return_value=value)
                stack.enter_context(patch)
            for name in ("write_manager", "write_desired", "update_operation"):
                stack.enter_context(mock.patch.object(omh, name))
            args = argparse.Namespace(home=str(home), operation_id="test-operation", detail="injected failure")
            yield home, repo, args

    def test_rollback_restores_bootstrap_and_launchers_before_success(self):
        with contextlib.redirect_stdout(io.StringIO()), self.transaction() as (home, repo, args):
            def verify_restored(*args, **kwargs):
                self.assertEqual((home / "bootstrap/omh_bootstrap.py").read_bytes(),
                                 (repo / "scripts/omh_bootstrap.py").read_bytes())
                for path in installer.launcher_paths(home):
                    self.assertEqual(path.read_bytes(), installer.expected_launcher_content(home=home, repo=repo).encode())
            with mock.patch.object(omh, "ensure_user_path") as register, \
                 mock.patch.object(omh, "finish_operation", side_effect=verify_restored) as finish:
                self.assertEqual(omh.command_resume_rollback(args), 0)
            finish.assert_called_once_with(home, outcome="rolled-back", detail="injected failure")
            register.assert_not_called()

    def test_failed_launcher_restore_does_not_report_rollback_complete(self):
        with contextlib.redirect_stdout(io.StringIO()), self.transaction() as (_, _, args):
            with mock.patch.object(installer, "write_launchers", side_effect=OSError("injected write failure")), \
                 mock.patch.object(omh, "finish_operation") as finish, \
                 self.assertRaisesRegex(OSError, "injected write failure"):
                omh.command_resume_rollback(args)
            finish.assert_not_called()

    def test_path_failure_does_not_replace_old_shim_on_upgrade(self):
        with contextlib.redirect_stdout(io.StringIO()), self.transaction() as (home, _, args):
            shim = home / "bootstrap/omh_bootstrap.py"
            original = shim.read_bytes()
            with mock.patch.object(omh, "ensure_user_path", side_effect=RuntimeError("edited PATH block")), \
                 mock.patch.object(installer, "write_launchers") as write, \
                 mock.patch.object(omh, "finish_operation") as finish, \
                 self.assertRaisesRegex(RuntimeError, "edited PATH block"):
                omh.command_resume_update(args)
            write.assert_not_called()
            finish.assert_not_called()
            self.assertEqual(shim.read_bytes(), original)


@unittest.skipIf(os.name == "nt", "POSIX external shell profiles")
class ExternalProfileOwnershipTests(unittest.TestCase):
    CASES = (("/bin/zsh", "ZDOTDIR", (".zshrc",)),
             ("/bin/fish", "XDG_CONFIG_HOME", ("fish/conf.d/oh-my-harness.fish",)))

    @contextlib.contextmanager
    def setup_profiles(self, shell, variable, names):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user = root / "user"
            user.mkdir()
            manager = user / ".oh-my-harness"
            external = root / "external-config"
            paths = [external / name for name in names]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# personal shell config\n", encoding="utf-8")
            with mock.patch.object(environment.Path, "home", return_value=user), \
                 mock.patch.dict(os.environ, {"HOME": str(user), "SHELL": shell, variable: str(external)}), \
                 contextlib.redirect_stdout(io.StringIO()):
                environment.ensure_user_path(manager)
                yield root, manager, paths

    def test_uninstall_after_external_root_unset_cleans_exact_owned_blocks(self):
        for shell, variable, names in self.CASES:
            with self.subTest(shell=shell), self.setup_profiles(shell, variable, names) as (_, manager, paths):
                os.environ.pop(variable)
                environment.ensure_user_path(manager, remove=True)
                for path in paths:
                    self.assertEqual(path.read_text(), "# personal shell config\n")
                self.assertFalse((manager / "state/environment.json").exists())

    def test_changed_external_root_cleans_old_profiles_and_records_new_ones(self):
        for shell, variable, names in self.CASES:
            with self.subTest(shell=shell), self.setup_profiles(shell, variable, names) as (root, manager, paths):
                new_root = root / "new-config"
                os.environ[variable] = str(new_root)
                environment.ensure_user_path(manager)
                for path in paths:
                    self.assertEqual(path.read_text(), "# personal shell config\n")
                receipt = json.loads((manager / "state/environment.json").read_text())
                recorded = {item["path"] for item in receipt["profiles"]}
                for name in names:
                    path = new_root / name
                    self.assertIn(str(path), recorded)
                    self.assertIn(environment.START, path.read_text())
                self.assertTrue(recorded.isdisjoint(map(str, paths)))
                environment.ensure_user_path(manager, remove=True)
                for name in names:
                    self.assertNotIn(environment.START, (new_root / name).read_text())

    def test_edited_external_block_aborts_uninstall(self):
        for shell, variable, names in self.CASES:
            with self.subTest(shell=shell), self.setup_profiles(shell, variable, names) as (_, manager, paths):
                path = paths[0]
                damaged = path.read_text().replace(environment.START + "\n", environment.START + "\n# edited\n")
                path.write_text(damaged, encoding="utf-8")
                receipt = manager / "state/environment.json"
                original_receipt = receipt.read_bytes()
                os.environ.pop(variable)
                with self.assertRaisesRegex(RuntimeError, "edited"):
                    environment.ensure_user_path(manager, remove=True)
                self.assertEqual(path.read_text(), damaged)
                self.assertEqual(receipt.read_bytes(), original_receipt)

    def test_inactive_unmanaged_profile_is_never_given_a_new_block(self):
        for shell, variable, names in self.CASES:
            with self.subTest(shell=shell), self.setup_profiles(shell, variable, names) as (_, manager, paths):
                for path in paths:
                    path.write_text("# already removed by user\n", encoding="utf-8")
                os.environ.pop(variable)
                environment.ensure_user_path(manager)
                for path in paths:
                    self.assertEqual(path.read_text(), "# already removed by user\n")

    def test_copied_receipt_does_not_cleanup_another_users_external_root(self):
        for shell, variable, names in self.CASES:
            with self.subTest(shell=shell), self.setup_profiles(shell, variable, names) as (root, manager, paths):
                original = {path: path.read_bytes() for path in paths}
                os.environ.pop(variable)
                other_user = root / "other-user"
                other_user.mkdir()
                with mock.patch.object(environment.Path, "home", return_value=other_user):
                    environment.ensure_user_path(manager, remove=True)
                self.assertEqual(original, {path: path.read_bytes() for path in paths})


if __name__ == "__main__":
    unittest.main()
