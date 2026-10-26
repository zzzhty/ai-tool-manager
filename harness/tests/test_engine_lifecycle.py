from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import manager_state  # noqa: E402
import engine  # noqa: E402
import atm_bootstrap  # noqa: E402
from sync_harness_instructions import remove_instruction_sync  # noqa: E402


class ManagerStateTests(unittest.TestCase):
    def write_install(self, home: Path, *, status: str = "ready") -> None:
        state = home / "state"
        state.mkdir(parents=True)
        (state / "install.json").write_text(
            json.dumps(
                {
                    "product": "atm-harness",
                    "status": status,
                    "repository": "https://example.invalid/atm-harness.git",
                    "ref": "main",
                    "revision": "a" * 40,
                    "harness": "codex",
                    "paths": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_ready_install_receipt_migrates_default_harness_to_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".atm"
            self.write_install(home)
            manager, desired = manager_state.load_or_initialize(
                home,
                repository="ignored",
                revision="b" * 40,
                release_version="1.0.0",
                bundle_identity="sha256:bundle",
                persist=True,
            )
            self.assertEqual(desired["harnesses"], ["codex"])
            self.assertEqual(manager["releaseVersion"], "1.0.0")
            self.assertTrue((home / "state" / "manager.json").is_file())
            self.assertTrue((home / "state" / "desired.json").is_file())

    def test_incomplete_initial_install_does_not_claim_harness_desired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".atm"
            self.write_install(home, status="installing")
            _manager, desired = manager_state.load_or_initialize(
                home,
                repository="ignored",
                revision="b" * 40,
                release_version="1.0.0",
                bundle_identity="sha256:bundle",
                persist=False,
            )
            self.assertEqual(desired["harnesses"], [])


class OmhCliTests(unittest.TestCase):
    def registry(self):
        registry = engine._load_registry()
        return replace(
            registry,
            harnesses={key: registry.harnesses[key] for key in ("claude-code", "codex", "zcode")},
        )

    def test_no_subcommand_is_refresh(self) -> None:
        self.assertEqual(engine._normalize_argv([]), ["refresh"])
        self.assertEqual(
            engine._normalize_argv(["--home", "/tmp/engine-home", "--yes"]),
            ["--home", "/tmp/engine-home", "refresh", "--yes"],
        )

    def test_top_level_help_is_not_rewritten_to_refresh(self) -> None:
        self.assertEqual(engine._normalize_argv(["--help"]), ["--help"])
        self.assertEqual(engine._normalize_argv(["-Help"]), ["--help"])
        self.assertEqual(
            engine._normalize_argv(["--home", "/tmp/engine-home", "--help"]),
            ["--home", "/tmp/engine-home", "--help"],
        )

    def test_top_level_help_hides_internal_resume_commands(self) -> None:
        help_text = engine.build_parser().format_help()

        self.assertIn("update", help_text)
        self.assertIn("recover", help_text)
        self.assertNotIn("_resume-update", help_text)
        self.assertNotIn("_resume-rollback", help_text)
        self.assertNotIn(argparse.SUPPRESS, help_text)

    def test_harness_command_help_lists_registry_owned_target_choices(self) -> None:
        registry = self.registry()
        with mock.patch.object(engine, "load_harness_metadata", return_value=registry):
            parser = engine.build_parser()

        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        expected = "Available harnesses: claude-code, codex, zcode."
        for command in ("install", "refresh", "remove", "check", "doctor", "repair"):
            with self.subTest(command=command):
                help_text = " ".join(subparsers.choices[command].format_help().split())
                self.assertIn(expected, help_text)
                self.assertIn("claude = claude-code", help_text)
                if command == "install":
                    self.assertIn("every available harness", help_text)
                    self.assertIn("Default: codex", help_text)
                else:
                    self.assertIn("all installed harnesses", help_text)
                if command == "remove":
                    self.assertIn("there is no default target", help_text)

    def test_aliases_are_normalized_and_deduplicated_across_commands(self) -> None:
        parser = engine.build_parser()
        for command in ("install", "refresh", "remove", "check", "doctor", "repair"):
            with self.subTest(command=command):
                args = parser.parse_args([command, "copilot", "copilot-cli", "--harness", "claude"])
                targets = engine._target_set(args, desired=("copilot",), mode=command)
                self.assertEqual(targets, ("copilot-cli", "claude-code"))
                all_args = parser.parse_args([command, "--all"])
                self.assertEqual(
                    engine._target_set(all_args, desired=("copilot",), mode=command),
                    engine._load_registry().choices if command == "install" else ("copilot-cli",),
                )

    def test_unknown_alias_is_rejected_before_any_lifecycle_state_access(self) -> None:
        error = io.StringIO()
        with mock.patch.object(engine, "_state_context") as state, contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as raised:
                engine.main(["install", "copliot"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unknown harness 'copliot'", error.getvalue())
        self.assertIn("copilot = copilot-cli", error.getvalue())
        state.assert_not_called()

    def test_install_and_remove_alias_share_one_canonical_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "manager"
            manager_state.atomic_write_json(home / "state/install.json", {
                "product": "atm-harness", "status": "installing", "harness": "codex",
            })
            manager, desired = manager_state.derive_initial_state(
                home, repository="https://example.invalid/repo.git", revision="a" * 40,
                release_version="1.0.0", bundle_identity="fixture", persist=True,
            )
            with (
                mock.patch.object(engine, "_state_context", return_value=(manager, desired)),
                mock.patch.object(engine, "_refresh_one") as refresh,
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "fixture")),
                mock.patch.object(engine, "_revision", return_value="a" * 40),
                mock.patch.dict(os.environ, {"COPILOT_HOME": str(Path(tmp) / "copilot")}),
            ):
                engine.main(["--home", str(home), "install", "copilot", "copilot-cli"])
            refresh.assert_called_once()
            self.assertEqual(refresh.call_args.kwargs["harness"], "copilot-cli")
            desired = json.loads((home / "state/desired.json").read_text())
            self.assertEqual(desired["harnesses"], ["copilot-cli"])
            receipt = manager_state.harness_file(home, "copilot-cli")
            self.assertEqual(json.loads(receipt.read_text())["harness"], "copilot-cli")
            self.assertFalse(manager_state.harness_file(home, "copilot").exists())
            with (
                mock.patch.object(engine, "_state_context", return_value=(manager, desired)),
                mock.patch.object(engine, "_remove_one") as remove,
            ):
                engine.main(["--home", str(home), "remove", "copilot"])
            self.assertEqual(remove.call_args.kwargs["harness"], "copilot-cli")
            self.assertEqual(json.loads((home / "state/desired.json").read_text())["harnesses"], [])
            self.assertFalse(receipt.exists())

    def test_internal_resume_commands_remain_dispatchable(self) -> None:
        with (
            mock.patch.object(
                engine,
                "command_resume_update",
                return_value=0,
            ) as resume_update,
            mock.patch.object(
                engine,
                "command_resume_rollback",
                return_value=0,
            ) as resume_rollback,
        ):
            update_result = engine.main(
                [
                    "--home",
                    "/manager",
                    "_resume-update",
                    "--operation-id",
                    "op-1",
                ]
            )
            rollback_result = engine.main(
                [
                    "--home=/manager",
                    "_resume-rollback",
                    "--operation-id",
                    "op-1",
                    "--detail",
                    "test failure",
                ]
            )

        self.assertEqual(update_result, 0)
        update_args = resume_update.call_args.args[0]
        self.assertEqual(update_args.home, "/manager")
        self.assertEqual(update_args.operation_id, "op-1")
        self.assertEqual(rollback_result, 0)
        rollback_args = resume_rollback.call_args.args[0]
        self.assertEqual(rollback_args.home, "/manager")
        self.assertEqual(rollback_args.operation_id, "op-1")
        self.assertEqual(rollback_args.detail, "test failure")

    def test_remove_without_target_does_not_expand_to_all_desired(self) -> None:
        args = argparse.Namespace(targets=[], harness=None, all=False)
        with mock.patch.object(engine, "_load_registry", return_value=self.registry()):
            targets = engine._target_set(
                args,
                desired=("codex", "zcode"),
                mode="remove",
            )
        self.assertEqual(targets, ())

    def test_install_without_target_uses_registry_default(self) -> None:
        args = argparse.Namespace(targets=[], harness=None, all=False)
        with mock.patch.object(engine, "_load_registry", return_value=self.registry()):
            targets = engine._target_set(args, desired=(), mode="install")
        self.assertEqual(targets, ("codex",))

    def test_refresh_repair_is_public_parser_surface(self) -> None:
        parser = engine.build_parser()
        args = parser.parse_args(["refresh", "codex", "--repair"])
        self.assertEqual(args.command, "refresh")
        self.assertEqual(args.targets, ["codex"])
        self.assertTrue(args.repair)

    def test_internal_refresh_forwards_only_the_active_operation_id(self) -> None:
        args = argparse.Namespace(
            codex_home=None,
            codex=None,
            yes=True,
            dry_run=False,
            repair=False,
            migrate_marketplace=False,
            migrate_from_repo=None,
            operation_id="op-1",
        )
        command = engine._common_refresh_args(
            args,
            home=Path("/manager"),
            harness="zcode",
        )
        self.assertEqual(command[-2:], ["--operation-id", "op-1"])

    def test_latest_stable_tag_uses_semver_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "x").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "x"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            for tag in ("v1.0.0", "v1.2.0", "v1.10.0", "v2.0.0-rc1"):
                subprocess.run(["git", "-C", str(repo), "tag", tag], check=True)
            self.assertEqual(engine._latest_stable_tag(repo), "v1.10.0")


class LifecycleStateBoundaryTests(unittest.TestCase):
    def test_state_context_rejects_checkout_drift_outside_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".atm"
            repo = home / "repo"
            repo.mkdir(parents=True)
            (home / "state").mkdir()
            (home / "state" / "install.json").write_text(
                json.dumps(
                    {
                        "product": "atm-harness",
                        "status": "ready",
                        "repository": "repo",
                        "ref": "main",
                        "revision": "a" * 40,
                        "harness": "codex",
                        "paths": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manager_state.write_manager(
                home,
                repository="repo",
                revision="a" * 40,
                release_version="1.0.0",
                bundle_identity="sha256:old",
                channel="stable",
                requested_ref="v1.0.0",
            )
            manager_state.atomic_write_json(
                manager_state.desired_file(home),
                {
                    "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                    "harnesses": ["codex"],
                    "updatePolicy": {"channel": "stable"},
                    "updatedAt": "test",
                },
            )
            with (
                mock.patch.object(engine, "REPO_ROOT", repo),
                mock.patch.object(engine, "_repository", return_value="repo"),
                mock.patch.object(engine, "_revision", return_value="b" * 40),
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "sha256:new")),
            ):
                with self.assertRaisesRegex(SystemExit, "differs from manager lifecycle state"):
                    engine._state_context(home, persist=False)

    def test_degraded_manager_blocks_normal_mutation_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".atm"
            repo = home / "repo"
            repo.mkdir(parents=True)
            (home / "state").mkdir()
            (home / "state" / "install.json").write_text(
                json.dumps(
                    {
                        "product": "atm-harness",
                        "status": "ready",
                        "repository": "repo",
                        "ref": "main",
                        "revision": "a" * 40,
                        "harness": "codex",
                        "paths": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manager_state.write_manager(
                home,
                repository="repo",
                revision="a" * 40,
                release_version="1.0.0",
                bundle_identity="sha256:bundle",
                channel="main",
                requested_ref="origin/main",
                status="degraded",
            )
            manager_state.atomic_write_json(
                manager_state.desired_file(home),
                {
                    "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                    "harnesses": [],
                    "updatePolicy": {"channel": "main"},
                    "updatedAt": "test",
                },
            )
            with (
                mock.patch.object(engine, "REPO_ROOT", repo),
                mock.patch.object(engine, "_repository", return_value="repo"),
                mock.patch.object(engine, "_revision", return_value="a" * 40),
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "sha256:bundle")),
            ):
                with self.assertRaisesRegex(SystemExit, "lifecycle is degraded"):
                    engine._state_context(home, persist=False)
                manager, _ = engine._state_context(
                    home, persist=False, allow_degraded=True
                )
            self.assertEqual(manager["status"], "degraded")

    def test_active_operation_blocks_normal_mutation_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / "repo").mkdir(parents=True)
            manager = {
                "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                "product": "atm-harness",
                "status": "ready",
                "repository": "repo",
                "channel": "stable",
                "requestedRef": "v1.0.0",
                "revision": "a" * 40,
                "releaseVersion": "1.0.0",
                "bundleIdentity": "sha256:bundle",
            }
            desired = {
                "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                "harnesses": ["codex"],
                "updatePolicy": {"channel": "stable"},
            }
            with (
                mock.patch.object(engine, "REPO_ROOT", home / "repo"),
                mock.patch.object(engine, "_repository", return_value="repo"),
                mock.patch.object(engine, "_revision", return_value="a" * 40),
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "sha256:bundle")),
                mock.patch.object(engine, "load_or_initialize", return_value=(manager, desired)),
                mock.patch.object(
                    engine,
                    "load_current_operation",
                    return_value={
                        "command": "update",
                        "phase": "checkout-switched",
                        "operationId": "op-1",
                    },
                ),
            ):
                with self.assertRaisesRegex(SystemExit, "interrupted manager operation"):
                    engine._state_context(home, persist=False)

    def test_read_only_context_can_inspect_active_operation_and_revision_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / "repo").mkdir(parents=True)
            manager = {
                "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                "product": "atm-harness",
                "status": "ready",
                "repository": "repo",
                "channel": "stable",
                "requestedRef": "v1.0.0",
                "revision": "a" * 40,
                "releaseVersion": "1.0.0",
                "bundleIdentity": "sha256:old",
            }
            desired = {
                "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                "harnesses": ["codex"],
                "updatePolicy": {"channel": "stable"},
            }
            with (
                mock.patch.object(engine, "REPO_ROOT", home / "repo"),
                mock.patch.object(engine, "_repository", return_value="repo"),
                mock.patch.object(engine, "_revision", return_value="b" * 40),
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "sha256:new")),
                mock.patch.object(engine, "load_or_initialize", return_value=(manager, desired)),
                mock.patch.object(
                    engine,
                    "load_current_operation",
                    return_value={
                        "command": "update",
                        "phase": "checkout-switched",
                        "operationId": "op-1",
                    },
                ),
            ):
                observed, _ = engine._state_context(
                    home,
                    persist=False,
                    allow_manager_drift=True,
                    allow_active_operation=True,
                )
            self.assertEqual(observed["revision"], "a" * 40)

    def test_internal_update_resume_may_cross_only_the_journaled_revision_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / ".atm"
            repo = home / "repo"
            repo.mkdir(parents=True)
            (home / "state").mkdir()
            (home / "state" / "install.json").write_text(
                json.dumps(
                    {
                        "product": "atm-harness",
                        "status": "ready",
                        "repository": "repo",
                        "ref": "main",
                        "revision": "a" * 40,
                        "harness": "codex",
                        "paths": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manager_state.write_manager(
                home,
                repository="repo",
                revision="a" * 40,
                release_version="1.0.0",
                bundle_identity="sha256:old",
                channel="stable",
                requested_ref="v1.0.0",
            )
            manager_state.atomic_write_json(
                manager_state.desired_file(home),
                {
                    "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                    "harnesses": [],
                    "updatePolicy": {"channel": "stable"},
                    "updatedAt": "test",
                },
            )
            with (
                mock.patch.object(engine, "REPO_ROOT", repo),
                mock.patch.object(engine, "_repository", return_value="repo"),
                mock.patch.object(engine, "_revision", return_value="b" * 40),
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "sha256:new")),
            ):
                manager, _desired = engine._state_context(
                    home, persist=False, allow_manager_drift=True
                )
            self.assertEqual(manager["revision"], "a" * 40)


class UpdateTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        for target in ("engine.ensure_user_path", "install_engine.write_launchers"):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_remote_pair(self, root: Path) -> tuple[Path, str, str]:
        remote = root / "remote.git"
        writer = root / "writer"
        home_repo = root / "home" / "repo"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        subprocess.run(["git", "clone", "-q", str(remote), str(writer)], check=True)
        for repo in (writer,):
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        (writer / ".agents/harnesses").mkdir(parents=True)
        (writer / ".agents/harnesses/registry.json").write_text(
            json.dumps({"sources": {"instructions": "AGENTS.md"}}) + "\n",
            encoding="utf-8",
        )
        (writer / "AGENTS.md").write_text("instructions\n", encoding="utf-8")
        (writer / "marker.txt").write_text("old\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(writer), "add", "."], check=True)
        subprocess.run(["git", "-C", str(writer), "commit", "-qm", "old"], check=True)
        subprocess.run(["git", "-C", str(writer), "branch", "-M", "main"], check=True)
        subprocess.run(["git", "-C", str(writer), "push", "-qu", "origin", "main"], check=True)
        subprocess.run(["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        subprocess.run(["git", "clone", "-q", str(remote), str(home_repo)], check=True)
        old = subprocess.check_output(["git", "-C", str(home_repo), "rev-parse", "HEAD"], text=True).strip()
        (writer / "marker.txt").write_text("new\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(writer), "add", "marker.txt"], check=True)
        subprocess.run(["git", "-C", str(writer), "commit", "-qm", "new"], check=True)
        subprocess.run(["git", "-C", str(writer), "push", "-q", "origin", "main"], check=True)
        new = subprocess.check_output(["git", "-C", str(writer), "rev-parse", "HEAD"], text=True).strip()
        return home_repo, old, new

    def seed_state(
        self,
        home: Path,
        repo: Path,
        old: str,
        *,
        bundle_identity: str = "sha256:old",
    ) -> None:
        (home / "state").mkdir(parents=True, exist_ok=True)
        (home / "state" / "install.json").write_text(
            json.dumps(
                {
                    "product": "atm-harness",
                    "status": "ready",
                    "repository": str(repo.parent.parent / "remote.git"),
                    "ref": "main",
                    "revision": old,
                    "harness": "codex",
                    "paths": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        manager_state.write_manager(
            home,
            repository=str(repo.parent.parent / "remote.git"),
            revision=old,
            # Full-tree fixtures carry the vendored VERSION; keep the legacy
            # constant for minimal fixtures that ship no VERSION file.
            release_version=(repo / "VERSION").read_text(encoding="utf-8").strip()
            if (repo / "VERSION").is_file()
            else "1.0.0",
            bundle_identity=bundle_identity,
            channel="main",
            requested_ref="origin/main",
        )
        manager_state.atomic_write_json(
            manager_state.desired_file(home),
            {
                "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                "harnesses": [],
                "updatePolicy": {"channel": "main"},
                "updatedAt": "test",
            },
        )

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            home=None, check=False, channel="main", to=None, allow_downgrade=False
        )

    def test_same_revision_update_commits_channel_and_requested_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = home / "repo"
            repo.mkdir(parents=True)
            manager = {
                "repository": "repo",
                "revision": "a" * 40,
                "releaseVersion": "1.0.0",
                "bundleIdentity": "sha256:bundle",
                "channel": "main",
                "requestedRef": "origin/main",
            }
            desired = {
                "harnesses": ["codex"],
                "updatePolicy": {"channel": "main"},
            }
            args = argparse.Namespace(
                home=str(home),
                check=False,
                channel="stable",
                to="v1.0.0",
                allow_downgrade=False,
            )
            with (
                mock.patch.object(engine, "ManagerLock"),
                mock.patch.object(engine, "_state_context", return_value=(manager, desired)),
                mock.patch.object(engine, "_worktree_clean", return_value=True),
                mock.patch.object(engine, "_repository", return_value="repo"),
                mock.patch.object(engine, "_git"),
                mock.patch.object(engine, "_target_revision", return_value=("v1.0.0", "a" * 40)),
                mock.patch.object(engine, "_revision", return_value="a" * 40),
                mock.patch.object(engine, "_validate_update_target", return_value=("1.0.0", "sha256:bundle")),
                mock.patch.object(engine, "write_manager") as write_manager,
                mock.patch.object(engine, "write_desired") as write_desired,
                mock.patch.object(engine, "_refresh_one") as refresh,
                mock.patch.object(engine, "_write_harness_state") as receipt,
            ):
                self.assertEqual(engine.command_update(args), 0)

            write_manager.assert_called_once_with(
                home,
                repository="repo",
                revision="a" * 40,
                release_version="1.0.0",
                bundle_identity="sha256:bundle",
                channel="stable",
                requested_ref="v1.0.0",
            )
            write_desired.assert_called_once_with(
                home, ("codex",), channel="stable"
            )

            refresh.assert_called_once()
            self.assertTrue(refresh.call_args.kwargs["check_after"])
            receipt.assert_called_once_with(home, "codex")

    def test_check_does_not_revalidate_predecessor_after_semantic_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            writer = root / "writer"
            home = root / "home"
            repo = home / "repo"
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            shutil.copytree(
                REPO_ROOT,
                writer,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            subprocess.run(
                ["git", "-C", str(writer), "init", "-q"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(writer), "remote", "add", "origin", str(remote)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(writer), "checkout", "-qB", "main"], check=True
            )
            subprocess.run(
                ["git", "-C", str(writer), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(writer), "config", "user.name", "Test"],
                check=True,
            )
            registry_path = writer / ".agents/harnesses/registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["sources"]["instructions"]["migration"][
                "requiredPredecessorRevision"
            ] = "0" * 40
            registry_path.write_text(
                json.dumps(registry, indent=2) + "\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "-C", str(writer), "add", "."],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(writer), "commit", "-qm", "semantic split"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(writer), "push", "-qu", "origin", "main"],
                check=True,
            )
            subprocess.run(
                ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
                check=True,
            )
            subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True)
            old = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()

            (writer / "steady-update-marker").write_text("new\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(writer), "add", "steady-update-marker"], check=True
            )
            subprocess.run(
                ["git", "-C", str(writer), "commit", "-qm", "steady update"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(writer), "push", "-q", "origin", "main"],
                check=True,
            )

            identity = json.loads(
                (repo / ".agents/plugins/distribution-identity.json").read_text(
                    encoding="utf-8"
                )
            )
            self.seed_state(
                home,
                repo,
                old,
                bundle_identity=str(identity["bundleIdentity"]),
            )
            args = argparse.Namespace(
                **{**vars(self.args()), "home": str(home), "check": True}
            )
            with mock.patch.object(engine, "REPO_ROOT", repo):
                self.assertEqual(engine.command_update(args), 0)

    def test_update_commits_new_manager_state_only_after_new_cli_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, old, new = self.make_remote_pair(root)
            home = repo.parent
            self.seed_state(home, repo, old)

            def distribution(path: Path) -> tuple[str, str]:
                revision = subprocess.check_output(
                    ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
                ).strip()
                return ("1.0.0", "sha256:new" if revision == new else "sha256:old")

            def invoke(_repo: Path, _home: Path, command: str, *extra: str):
                self.assertEqual(command, "_resume-update")
                operation_id = extra[extra.index("--operation-id") + 1]
                rc = engine.command_resume_update(
                    argparse.Namespace(home=str(home), operation_id=operation_id)
                )
                return subprocess.CompletedProcess([], rc)

            with (
                mock.patch.object(engine, "REPO_ROOT", repo),
                mock.patch.object(engine, "_distribution", side_effect=distribution),
                mock.patch.object(engine, "_validate_update_target", return_value=("1.0.0", "sha256:new")),
                mock.patch.object(engine, "_bootstrap_tooling"),
                mock.patch.object(engine, "_invoke_internal", side_effect=invoke),
            ):
                engine.command_update(argparse.Namespace(**{**vars(self.args()), "home": str(home)}))

            self.assertEqual(
                subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
                new,
            )
            manager = json.loads(manager_state.manager_file(home).read_text(encoding="utf-8"))
            self.assertEqual(manager["revision"], new)
            self.assertEqual(manager["bundleIdentity"], "sha256:new")
            self.assertFalse(manager_state.current_operation_file(home).exists())
            history = list(manager_state.operation_history_dir(home).glob("*.json"))
            self.assertEqual(len(history), 1)
            operation = json.loads(history[0].read_text(encoding="utf-8"))
            self.assertEqual(
                operation["before"]["instructionsSource"]["sha256"],
                operation["target"]["instructionsSource"]["sha256"],
            )

    def test_failed_new_cli_rolls_checkout_and_state_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, old, _new = self.make_remote_pair(root)
            home = repo.parent
            self.seed_state(home, repo, old)
            calls: list[str] = []

            def invoke(_repo: Path, _home: Path, command: str, *extra: str):
                calls.append(command)
                operation_id = extra[extra.index("--operation-id") + 1]
                if command == "_resume-update":
                    return subprocess.CompletedProcess([], 17)
                rc = engine.command_resume_rollback(
                    argparse.Namespace(
                        home=str(home), operation_id=operation_id, detail="test failure"
                    )
                )
                return subprocess.CompletedProcess([], rc)

            with (
                mock.patch.object(engine, "REPO_ROOT", repo),
                mock.patch.object(engine, "_distribution", return_value=("1.0.0", "sha256:old")),
                mock.patch.object(engine, "_validate_update_target", return_value=("1.0.0", "sha256:new")),
                mock.patch.object(engine, "_bootstrap_tooling"),
                mock.patch.object(engine, "_invoke_internal", side_effect=invoke),
            ):
                with self.assertRaisesRegex(SystemExit, "was rolled back"):
                    engine.command_update(argparse.Namespace(**{**vars(self.args()), "home": str(home)}))

            self.assertEqual(calls, ["_resume-update", "_resume-rollback"])
            self.assertEqual(
                subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
                old,
            )
            manager = json.loads(manager_state.manager_file(home).read_text(encoding="utf-8"))
            self.assertEqual(manager["revision"], old)
            self.assertFalse(manager_state.current_operation_file(home).exists())


class InstructionMigrationTransitionTests(unittest.TestCase):
    @staticmethod
    def migration_source(stage: str, *, predecessor: str | None = None) -> dict:
        current, peer = engine.INSTRUCTIONS_MIGRATION_ORIENTATION[stage]
        migration = {
            "id": engine.INSTRUCTIONS_MIGRATION_ID,
            "stage": stage,
            "peer": peer,
            "peerSha256": "1" * 64,
        }
        if predecessor is not None:
            migration["requiredPredecessorRevision"] = predecessor
        return {
            "path": current,
            "sha256": "1" * 64,
            "migration": migration,
        }

    def test_required_predecessor_blocks_a_direct_jump(self) -> None:
        predecessor = "a" * 40
        before_source = {"path": "AGENTS.md", "sha256": "1" * 64}
        target_source = self.migration_source(
            "source-switched", predecessor=predecessor
        )
        with (
            mock.patch.object(
                engine,
                "_instruction_source_at_revision",
                return_value=self.migration_source("bridge-ready"),
            ),
            mock.patch.object(
                engine,
                "_git",
                side_effect=(
                    subprocess.CompletedProcess([], 0, "", ""),
                    subprocess.CompletedProcess([], 1, "", "not ancestor"),
                ),
            ),
            self.assertRaisesRegex(SystemExit, f"atm harness -- update --to {predecessor}"),
        ):
            engine._validate_instruction_transition(
                Path("/repo"),
                before_revision="b" * 40,
                target_revision="c" * 40,
                before_source=before_source,
                target_source=target_source,
            )

    def test_predecessor_must_be_the_same_migration_and_exact_previous_stage(self) -> None:
        predecessor = "a" * 40
        target_source = self.migration_source(
            "semantic-split", predecessor=predecessor
        )
        wrong_stage = self.migration_source("bridge-ready")
        with (
            mock.patch.object(
                engine,
                "_instruction_source_at_revision",
                return_value=wrong_stage,
            ),
            mock.patch.object(engine, "_git") as git,
            self.assertRaisesRegex(SystemExit, "not the exact previous stage"),
        ):
            engine._validate_instruction_transition(
                Path("/repo"),
                before_revision="b" * 40,
                target_revision="c" * 40,
                before_source=self.migration_source("source-switched"),
                target_source=target_source,
            )
        git.assert_not_called()

        wrong_id = self.migration_source("source-switched")
        wrong_id["migration"]["id"] = "other-migration"
        with (
            mock.patch.object(
                engine,
                "_instruction_source_at_revision",
                return_value=wrong_id,
            ),
            self.assertRaisesRegex(SystemExit, "different migration id"),
        ):
            engine._validate_instruction_transition(
                Path("/repo"),
                before_revision="b" * 40,
                target_revision="c" * 40,
                before_source=self.migration_source("source-switched"),
                target_source=target_source,
            )

    def test_predecessor_must_exist_and_be_an_ancestor_of_the_target(self) -> None:
        predecessor = "a" * 40
        target_source = self.migration_source(
            "source-switched", predecessor=predecessor
        )
        with (
            mock.patch.object(
                engine,
                "_instruction_source_at_revision",
                side_effect=SystemExit("has no regular file"),
            ),
            self.assertRaisesRegex(SystemExit, "has no regular file"),
        ):
            engine._validate_instruction_transition(
                Path("/repo"),
                before_revision="b" * 40,
                target_revision="c" * 40,
                before_source=self.migration_source("bridge-ready"),
                target_source=target_source,
            )

        with (
            mock.patch.object(
                engine,
                "_instruction_source_at_revision",
                return_value=self.migration_source("bridge-ready"),
            ),
            mock.patch.object(
                engine,
                "_git",
                return_value=subprocess.CompletedProcess([], 1, "", "not ancestor"),
            ),
            self.assertRaisesRegex(SystemExit, "not an ancestor of the target"),
        ):
            engine._validate_instruction_transition(
                Path("/repo"),
                before_revision="b" * 40,
                target_revision="c" * 40,
                before_source=self.migration_source("bridge-ready"),
                target_source=target_source,
            )

    def test_git_ancestry_failure_is_not_reported_as_a_missing_checkpoint(self) -> None:
        predecessor = "a" * 40
        with (
            mock.patch.object(
                engine,
                "_instruction_source_at_revision",
                return_value=self.migration_source("bridge-ready"),
            ),
            mock.patch.object(
                engine,
                "_git",
                return_value=subprocess.CompletedProcess([], 128, "", "git failed"),
            ),
            self.assertRaisesRegex(
                SystemExit,
                "cannot validate instruction source migration target ancestry.*git failed",
            ),
        ):
            engine._validate_instruction_transition(
                Path("/repo"),
                before_revision="b" * 40,
                target_revision="c" * 40,
                before_source=self.migration_source("bridge-ready"),
                target_source=self.migration_source(
                    "source-switched", predecessor=predecessor
                ),
            )

    def test_resume_guard_precedes_manager_and_harness_mutation(self) -> None:
        operation = {
            "operationId": "op-1",
            "command": "update",
            "phase": "tooling-ready",
            "before": {"revision": "a" * 40},
            "target": {"revision": "b" * 40},
        }
        with tempfile.TemporaryDirectory() as tmp:
            manager_home = str(Path(tmp) / "manager")
            with (
                mock.patch.object(engine, "load_current_operation", return_value=operation),
                mock.patch.object(
                    engine,
                    "_journal_instruction_transition",
                    side_effect=SystemExit("bridge checkpoint first"),
                ),
                mock.patch.object(engine, "write_manager") as write_manager,
                mock.patch.object(engine, "_refresh_one") as refresh,
                self.assertRaisesRegex(SystemExit, "bridge checkpoint first"),
            ):
                engine.command_resume_update(
                    argparse.Namespace(home=manager_home, operation_id="op-1")
                )
        write_manager.assert_not_called()
        refresh.assert_not_called()

    def test_missing_revision_blob_is_reported_without_subprocess_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "Test"],
                check=True,
            )
            repo.joinpath("marker").write_text("x\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "marker"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            revision = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True,
            ).strip()

            with self.assertRaisesRegex(SystemExit, "has no regular file"):
                engine._git_blob(repo, revision, "missing")


class RemoveStateTransactionTests(unittest.TestCase):
    def test_remove_failure_preserves_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(
                home=str(Path(tmp) / "home"),
                targets=["codex"],
                harness=None,
                all=False,
                codex_home=None,
                codex=None,
                yes=True,
                dry_run=False,
            )
            desired = {
                "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
                "harnesses": ["codex"],
                "updatePolicy": {"channel": "stable"},
            }
            with (
                mock.patch.object(engine, "ManagerLock"),
                mock.patch.object(engine, "_state_context", return_value=({}, desired)),
                mock.patch.object(engine, "_remove_one", side_effect=SystemExit("remove failed")),
                mock.patch.object(engine, "write_desired") as write_desired,
            ):
                with self.assertRaisesRegex(SystemExit, "remove failed"):
                    engine.command_remove(args)
            write_desired.assert_not_called()


class ManagerRepairInstructionTests(unittest.TestCase):
    def test_manager_repair_does_not_claim_operation_journal_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            desired = {"harnesses": ["zcode"]}
            with (
                mock.patch.object(engine, "ManagerLock"),
                mock.patch.object(engine, "_state_context", return_value=({"repository": "repo", "revision": "a" * 40, "releaseVersion": "1.0.0", "bundleIdentity": "bundle", "channel": "main"}, desired)),
                mock.patch.object(engine, "_bootstrap_tooling"),
                mock.patch("install_engine.write_launchers"),
                mock.patch.object(engine, "_refresh_one") as refresh,
                mock.patch.object(engine, "_write_harness_state"),
                mock.patch.object(engine, "write_desired"),
                mock.patch.object(engine, "write_manager"),
                mock.patch.object(engine, "ensure_user_path"),
            ):
                self.assertEqual(
                    engine.command_manager_repair(argparse.Namespace(home=str(home))),
                    0,
                )

            refresh_args = refresh.call_args.args[0]
            self.assertTrue(refresh_args.repair)
            self.assertIsNone(refresh_args.operation_id)
            self.assertTrue(refresh.call_args.kwargs["check_after"])


class InstructionRemovalTests(unittest.TestCase):
    def test_remove_current_managed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "AGENTS.md"
            target = root / "target.md"
            source.write_text("managed\n", encoding="utf-8")
            target.write_text("managed\n", encoding="utf-8")
            plan = SimpleNamespace(
                instructions_source=source,
                instructions_migration=SimpleNamespace(peer_source=root / "peer.md"),
                instructions_target=target,
                instructions_materialization="copy",
                harness_id="zcode",
            )
            plan.instructions_migration.peer_source.write_text(
                "peer\n", encoding="utf-8"
            )
            remove_instruction_sync(plan, dry_run=False)
            self.assertFalse(target.exists())

    def test_remove_refuses_changed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "AGENTS.md"
            target = root / "target.md"
            source.write_text("managed\n", encoding="utf-8")
            target.write_text("user changed\n", encoding="utf-8")
            plan = SimpleNamespace(
                instructions_source=source,
                instructions_migration=SimpleNamespace(peer_source=root / "peer.md"),
                instructions_target=target,
                instructions_materialization="copy",
                harness_id="zcode",
            )
            plan.instructions_migration.peer_source.write_text(
                "peer\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(SystemExit, "changed or unmanaged"):
                remove_instruction_sync(plan, dry_run=False)
            self.assertTrue(target.exists())


class BootstrapHelpTests(unittest.TestCase):
    def test_real_help_does_not_require_site_packages(self) -> None:
        result = subprocess.run(
            [sys.executable, "-S", str(REPO_ROOT / "scripts" / "engine.py"), "--help"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: atm harness --", result.stdout)

    def test_install_help_lists_current_harnesses_without_site_packages(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                str(REPO_ROOT / "scripts" / "engine.py"),
                "install",
                "--help",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Available harnesses:", result.stdout)
        self.assertIn("pi-agent", result.stdout)

    def test_help_bypasses_tooling_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            scripts = home / "repo" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "engine.py").write_text("pass\n", encoding="utf-8")
            (scripts / "bootstrap_tooling_env.py").write_text("pass\n", encoding="utf-8")
            with (
                mock.patch.object(atm_bootstrap.sys, "version_info", (3, 10, 13)),
                mock.patch.object(atm_bootstrap.subprocess, "run") as run,
            ):
                run.return_value = subprocess.CompletedProcess([], 0)
                self.assertEqual(
                    atm_bootstrap.main(["--home", str(home), "--help"]),
                    0,
                )
            run.assert_not_called()
            self.assertFalse((home / "venv").exists())

    def test_subcommand_help_never_repairs_checkout_or_bootstraps_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            cli = home / "repo/scripts/engine.py"
            cli.parent.mkdir(parents=True)
            cli.write_text("pass\n", encoding="utf-8")
            tooling = atm_bootstrap._venv_python(home)
            tooling.parent.mkdir(parents=True)
            tooling.touch()
            for arguments in (
                ["install", "--help"], ["refresh", "-h"],
                ["repair", "--help"],
                ["manager", "repair", "--help"], ["manager", "uninstall", "-Help"],
            ):
                with (
                    self.subTest(arguments=arguments),
                    mock.patch.object(atm_bootstrap.sys, "version_info", (3, 10, 13)),
                    mock.patch.object(atm_bootstrap, "_repair_checkout") as repair,
                    mock.patch.object(atm_bootstrap.subprocess, "run") as run,
                ):
                    run.return_value = subprocess.CompletedProcess([], 0)
                    self.assertEqual(atm_bootstrap.main(["--home", str(home), *arguments]), 0)
                    repair.assert_not_called()
                    run.assert_not_called()
            self.assertFalse(atm_bootstrap._is_help_request(["install", "--", "--help"]))

    def test_unsupported_python_rejects_repair_before_checkout_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            with (
                mock.patch.object(atm_bootstrap.sys, "version_info", (3, 10, 13)),
                mock.patch.object(atm_bootstrap, "_repair_checkout") as repair_checkout,
                mock.patch.object(atm_bootstrap.subprocess, "run") as run,
                self.assertRaisesRegex(SystemExit, "Python 3.11 or newer is required"),
            ):
                atm_bootstrap.main(["--home", str(home), "manager", "repair"])

            repair_checkout.assert_not_called()
            run.assert_not_called()


class BootstrapRepairTests(unittest.TestCase):
    def test_bootstrap_can_reconstruct_missing_managed_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            (source / "marker.txt").write_text("manager", encoding="utf-8")
            for name in atm_bootstrap._REQUIRED_FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-qm", "base"], check=True)
            revision = subprocess.check_output(
                ["git", "-C", str(source), "rev-parse", "HEAD"],
                text=True,
            ).strip()

            home = root / "home"
            (home / "state").mkdir(parents=True)
            (home / "state" / "manager.json").write_text(
                json.dumps(
                    {
                        "product": "atm-harness",
                        "repository": str(source),
                        "revision": revision,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            atm_bootstrap._repair_checkout(home)
            self.assertEqual((home / "repo" / "marker.txt").read_text(encoding="utf-8"), "manager")
            head = subprocess.check_output(
                ["git", "-C", str(home / "repo"), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            self.assertEqual(head, revision)


if __name__ == "__main__":
    unittest.main()
