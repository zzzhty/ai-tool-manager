"""Regression coverage for the public repair/update and relocatable launchers."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_tooling_env as tooling
import install_oh_my_harness as installer
import omh
import omh_bootstrap as bootstrap


class PublicCommandTests(unittest.TestCase):
    def test_repair_options_match_legacy_spelling(self):
        parser = omh.build_parser()
        for prefix in (["repair"], ["manager", "repair"]):
            args = parser.parse_args([*prefix, "codex", "--rebuild", "--reclone", "--no-path"])
            self.assertIs(args.func, omh.command_manager_repair)
            self.assertEqual(args.targets, ["codex"])
            self.assertTrue(args.rebuild and args.reclone and args.no_path)

    def test_update_shortcuts_keep_legacy_options(self):
        parser = omh.build_parser()
        for value in ("main", "stable", "v1.0.0"):
            self.assertEqual(parser.parse_args(["update", value]).target, value)
        self.assertEqual(parser.parse_args(["update", "--channel", "main"]).channel, "main")
        self.assertEqual(parser.parse_args(["update", "--to", "v1.0.0"]).to, "v1.0.0")

    def test_conflicting_update_selector_fails_before_mutation(self):
        args = omh.build_parser().parse_args(["update", "main", "--channel", "stable"])
        with mock.patch.object(omh, "ManagerLock") as lock, self.assertRaises(SystemExit):
            omh.command_update(args)
        lock.assert_not_called()

    def test_repair_forces_materialization_and_keeps_codex_options_scoped(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            home = Path(tmp)
            manager = dict(repository="origin", revision="a" * 40, releaseVersion="1.0.0",
                           bundleIdentity="bundle", channel="main")
            args = omh.build_parser().parse_args(["--home", tmp, "repair", "--migrate-marketplace"])
            with (
                mock.patch.object(omh, "_state_context", return_value=(manager, {"harnesses": ["codex", "zcode"]})),
                mock.patch.object(omh, "_bootstrap_tooling"),
                mock.patch.object(installer, "write_launchers"),
                mock.patch.object(omh, "ensure_user_path") as path,
                mock.patch.object(omh, "_refresh_one") as refresh,
                mock.patch.object(omh, "_write_harness_state"),
                mock.patch.object(omh, "write_desired"),
                mock.patch.object(omh, "write_manager"),
            ):
                omh.command_manager_repair(args)
            self.assertEqual(refresh.call_count, 2)
            for call in refresh.call_args_list:
                self.assertTrue(call.args[0].repair)
                self.assertIsNone(call.args[0].operation_id)
                self.assertTrue(call.kwargs["check_after"])
            self.assertTrue(refresh.call_args_list[0].args[0].migrate_marketplace)
            self.assertFalse(refresh.call_args_list[1].args[0].migrate_marketplace)
            path.assert_called_once_with(home, dry_run=False)

    def test_repair_failure_does_not_mark_manager_ready(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            args = omh.build_parser().parse_args(["--home", tmp, "repair", "--no-path"])
            with (
                mock.patch.object(omh, "_state_context", return_value=({}, {"harnesses": ["codex"]})),
                mock.patch.object(omh, "_bootstrap_tooling"),
                mock.patch.object(installer, "write_launchers"),
                mock.patch.object(omh, "_refresh_one", side_effect=RuntimeError("injected")),
                mock.patch.object(omh, "_write_harness_state") as receipt,
                mock.patch.object(omh, "write_manager") as manager,
                self.assertRaisesRegex(RuntimeError, "injected"),
            ):
                omh.command_manager_repair(args)
            receipt.assert_not_called()
            manager.assert_not_called()

    def test_no_path_skips_registration_during_installer_repair(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            home = Path(tmp) / "manager"
            (home / "state").mkdir(parents=True)
            (home / "state/install.json").write_text(json.dumps({
                "product": "oh-my-harness", "repository": "origin", "ref": "main",
                "status": "ready", "harness": "codex", "revision": "a" * 40,
                "paths": {
                    "home": str(home), "repo": str(home / "repo"), "venv": str(home / "venv"),
                    "python": str(installer.venv_python(home / "venv")),
                    "launchers": [str(p) for p in installer.launcher_paths(home)],
                },
            }), encoding="utf-8")
            from manager_state import derive_initial_state
            derive_initial_state(home, repository="origin", revision="a" * 40,
                                 release_version="1.0.0", bundle_identity="bundle", persist=True)
            with (
                mock.patch.object(sys, "argv", ["installer", "--home", str(home), "--repair", "--no-path"]),
                mock.patch.object(installer, "write_launchers"),
                mock.patch.object(installer, "ensure_user_path") as path,
                mock.patch.object(installer, "run") as run,
            ):
                installer.main()
            path.assert_not_called()
            self.assertEqual(run.call_args.args[0][-2:], ["repair", "--no-path"])


class NativeLauncherTests(unittest.TestCase):
    def test_launcher_follows_its_home_after_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old manager"
            (old / "bin").mkdir(parents=True)
            (old / "bootstrap").mkdir()
            path = installer.launcher_paths(old)[1]
            path.write_bytes(installer.expected_launcher_content(home=old, repo=old / "repo").encode("utf-8"))
            path.chmod(0o755)
            (old / "bootstrap/omh_bootstrap.py").write_text(
                "import json,sys; print(json.dumps(sys.argv[1:]))\n", encoding="utf-8",
            )
            moved = Path(tmp) / "moved manager"
            old.rename(moved)
            result = subprocess.run(
                [str(moved / "bin" / path.name), "repair", "argument with spaces"],
                env={**os.environ, "OH_MY_HARNESS_BOOTSTRAP_PYTHON": sys.executable},
                capture_output=True, text=True, check=True,
            )
            arguments = json.loads(result.stdout)
            self.assertEqual(arguments[0], "--home")
            self.assertEqual(Path(arguments[1]).resolve(), moved.resolve())
            self.assertEqual(arguments[2:], ["repair", "argument with spaces"])

    @unittest.skipIf(os.name == "nt", "POSIX external symlink")
    def test_launcher_follows_external_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "manager"
            (home / "bin").mkdir(parents=True)
            (home / "bootstrap").mkdir()
            launcher = home / "bin/omh"
            launcher.write_text(installer.posix_launcher(home=home, repo=home / "repo"), encoding="utf-8")
            launcher.chmod(0o755)
            (home / "bootstrap/omh_bootstrap.py").write_text(
                "import json,sys; print(json.dumps(sys.argv[1:]))\n", encoding="utf-8",
            )
            link = Path(tmp) / "external-omh"
            link.symlink_to(launcher)
            result = subprocess.run([str(link), "status"], capture_output=True, text=True, check=True,
                                    env={**os.environ, "OH_MY_HARNESS_BOOTSTRAP_PYTHON": sys.executable})
            arguments = json.loads(result.stdout)
            self.assertEqual(arguments[0], "--home")
            self.assertEqual(Path(arguments[1]).resolve(), home.resolve())
            self.assertEqual(arguments[2:], ["status"])


class ToolingFastPathTests(unittest.TestCase):
    def test_ready_environment_does_not_recreate_or_install(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            with (
                mock.patch.object(tooling, "venv_health", return_value=(True, "healthy")),
                mock.patch.object(tooling, "_dependencies_ready", return_value=True),
                mock.patch.object(tooling, "create_venv") as create,
                mock.patch.object(tooling, "refresh_dependencies") as install,
            ):
                tooling.bootstrap_tooling_env(root / "venv", root / "requirements", dry_run=False)
            create.assert_not_called()
            install.assert_not_called()

    def test_requirements_change_refreshes_dependencies_without_recreating_venv(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            with (
                mock.patch.object(tooling, "venv_health", return_value=(True, "healthy")),
                mock.patch.object(tooling, "_dependencies_ready", return_value=False),
                mock.patch.object(tooling, "create_venv") as create,
                mock.patch.object(tooling, "refresh_dependencies") as install,
                mock.patch.object(tooling, "_record_requirements") as receipt,
            ):
                tooling.bootstrap_tooling_env(root / "venv", root / "requirements", dry_run=False)
            create.assert_not_called()
            install.assert_called_once()
            receipt.assert_called_once()

    def test_failed_install_does_not_record_ready_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            with (
                mock.patch.object(tooling, "venv_health", return_value=(True, "healthy")),
                mock.patch.object(tooling, "_dependencies_ready", return_value=False),
                mock.patch.object(tooling, "refresh_dependencies", side_effect=RuntimeError("injected")),
                mock.patch.object(tooling, "_record_requirements") as receipt,
                self.assertRaisesRegex(RuntimeError, "injected"),
            ):
                tooling.bootstrap_tooling_env(root / "venv", root / "requirements", dry_run=False)
            receipt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
