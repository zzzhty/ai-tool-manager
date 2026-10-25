"""Persisted-state regressions for the Copilot and Gemini full-name migration."""

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
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import install_oh_my_harness as installer  # noqa: E402
import manager_state  # noqa: E402
import omh  # noqa: E402


class HarnessNameMigrationTests(unittest.TestCase):
    repository = "https://example.invalid/oh-my-harness.git"
    revision = "a" * 40
    release = "1.0.0"
    bundle = "sha256:migration-fixture"
    pairs = (("copilot-cli", "copilot"), ("gemini-cli", "gemini"))

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_install(self, home: Path, harness: str) -> None:
        manager_state.atomic_write_json(home / "state/install.json", {
            "product": "oh-my-harness", "status": "ready",
            "repository": self.repository, "ref": "main",
            "revision": self.revision, "harness": harness,
            "paths": {"repo": str(REPO_ROOT)},
        })

    def load_state(self, home: Path, *, persist: bool = True):
        return manager_state.load_or_initialize(
            home, repository=self.repository, revision=self.revision,
            release_version=self.release, bundle_identity=self.bundle, persist=persist,
        )

    def seed_home(self, name: str, harnesses: list[str]) -> Path:
        home = self.root / name
        self.write_install(home, "copilot")
        self.load_state(home)
        # Deliberately bypass the canonical writer to model pre-migration files.
        manager_state.atomic_write_json(manager_state.desired_file(home), {
            "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
            "harnesses": sorted(set(harnesses)),
            "updatePolicy": {"channel": "main", "fixturePolicy": "preserve-me"},
            "updatedAt": "2026-01-01T00:00:00Z",
        })
        # Keep lock creation out of mutation-failure filesystem comparisons.
        (home / "state/manager.lock").write_bytes(b"\0")
        return home

    def seed_receipt(self, home: Path, harness: str) -> Path:
        path = manager_state.harness_file(home, harness)
        manager_state.atomic_write_json(path, {
            "schemaVersion": manager_state.STATE_SCHEMA_VERSION,
            "harness": harness, "status": "ready",
            "managerRevision": "b" * 40, "releaseVersion": "0.9.0",
            "bundleIdentity": "sha256:old-bundle", "root": "/old/target",
            "updatedAt": "2026-01-01T00:00:00Z",
        })
        return path

    def write_receipt(self, home: Path, harness: str) -> None:
        manager_state.write_harness_receipt(
            home, harness=harness, manager_revision=self.revision,
            release_version=self.release, bundle_identity=self.bundle,
            root=str(self.root / "targets" / harness),
        )

    def snapshot(self, home: Path, *, omit_lock: bool = False) -> dict:
        result = {}
        for path in [home, *sorted(home.rglob("*"))]:
            if omit_lock and path.name == manager_state.LOCK_FILE:
                continue
            stat = path.lstat()
            if path.is_symlink():
                content = ("symlink", os.readlink(path))
            elif path.is_file():
                content = ("file", path.read_bytes())
            else:
                content = ("directory",)
            result[str(path.relative_to(home))] = (stat.st_mode, stat.st_mtime_ns, content)
        return result

    @contextlib.contextmanager
    def lifecycle_environment(self):
        # Exercise the actual state reader/writers while keeping materialization,
        # checkout inspection, launcher installation and tooling out of these tests.
        with contextlib.ExitStack() as stack:
            for name, value in (
                ("repo_path", REPO_ROOT), ("_repository", self.repository),
                ("_revision", self.revision), ("_distribution", (self.release, self.bundle)),
                ("_worktree_clean", True),
            ):
                stack.enter_context(mock.patch.object(omh, name, return_value=value))
            stack.enter_context(mock.patch.object(
                omh, "_resolve_plan",
                side_effect=lambda harness, *, codex_home=None: SimpleNamespace(root=codex_home or self.root / "targets" / harness),
            ))
            effects = {
                name: stack.enter_context(mock.patch.object(omh, name))
                for name in ("_refresh_one", "_remove_one", "_bootstrap_tooling", "ensure_user_path")
            }
            effects["_run"] = stack.enter_context(mock.patch.object(
                omh, "_run", return_value=subprocess.CompletedProcess([], 0),
            ))
            effects["write_launchers"] = stack.enter_context(mock.patch.object(installer, "write_launchers"))
            yield effects

    def run_command(self, home: Path, *arguments: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(omh.main(["--home", str(home), *arguments]), 0)
        return output.getvalue()

    def assert_canonical_receipt(self, home: Path, canonical: str, legacy: str) -> None:
        receipt = json.loads(manager_state.harness_file(home, canonical).read_text())
        self.assertEqual(receipt["harness"], canonical)
        self.assertEqual(receipt["managerRevision"], self.revision)
        self.assertEqual(receipt["bundleIdentity"], self.bundle)
        self.assertFalse(manager_state.harness_file(home, legacy).exists())

    def test_legacy_initial_receipt_derives_canonical_state_without_rewriting_history(self) -> None:
        for canonical, legacy in self.pairs:
            for persist in (False, True):
                with self.subTest(harness=legacy, persist=persist):
                    home = self.root / f"{canonical}-{persist}"
                    self.write_install(home, legacy)
                    install = home / "state/install.json"
                    original = (install.read_bytes(), install.stat().st_mtime_ns)
                    before = self.snapshot(home)
                    _manager, desired = self.load_state(home, persist=persist)
                    self.assertEqual(desired["harnesses"], [canonical])
                    self.assertEqual((install.read_bytes(), install.stat().st_mtime_ns), original)
                    if persist:
                        self.assertEqual(json.loads(manager_state.desired_file(home).read_text())["harnesses"], [canonical])
                    else:
                        self.assertEqual(self.snapshot(home), before)

    def test_mixed_desired_state_reads_canonical_set_but_raw_loader_preserves_rollback_input(self) -> None:
        names = ["copilot", "gemini-cli", "gemini", "copilot-cli"]
        home = self.seed_home("mixed-read", names)
        before = self.snapshot(home)
        for persist in (False, True):
            with self.subTest(persist=persist):
                _manager, desired = self.load_state(home, persist=persist)
                self.assertEqual(desired["harnesses"], sorted(names))
                self.assertEqual(manager_state.desired_harnesses(desired), ("copilot-cli", "gemini-cli"))
                self.assertEqual(self.snapshot(home), before)

    def test_write_desired_canonicalizes_and_deduplicates_preserving_policy(self) -> None:
        home = self.seed_home("desired-write", ["copilot", "gemini"])
        policy = json.loads(manager_state.desired_file(home).read_text())["updatePolicy"]
        payload = manager_state.write_desired(home, ["gemini", "copilot-cli", "copilot", "gemini-cli", "gemini-cli"])
        self.assertEqual(payload["harnesses"], ["copilot-cli", "gemini-cli"])
        self.assertEqual(payload["updatePolicy"], policy)
        self.assertEqual(json.loads(manager_state.desired_file(home).read_text()), payload)

    def test_implicit_and_all_targets_normalize_legacy_desired_for_every_command(self) -> None:
        desired = ("copilot", "copilot-cli", "gemini", "gemini-cli")
        for mode in ("install", "refresh", "remove", "check", "doctor", "repair"):
            with self.subTest(mode=mode):
                args = argparse.Namespace(targets=[], harness=None, all=True)
                expected = omh._load_registry().choices if mode == "install" else ("copilot-cli", "gemini-cli")
                self.assertEqual(omh._target_set(args, desired=desired, mode=mode), expected)
                args.all = False
                expected = ("codex",) if mode == "install" else () if mode == "remove" else ("copilot-cli", "gemini-cli")
                self.assertEqual(omh._target_set(args, desired=desired, mode=mode), expected)

    def test_receipt_write_converges_both_spellings_and_preserves_unrelated_files(self) -> None:
        for canonical, legacy in self.pairs:
            for selected in (canonical, legacy):
                with self.subTest(harness=selected):
                    home = self.seed_home(selected, [legacy])
                    self.seed_receipt(home, legacy)
                    self.seed_receipt(home, canonical)
                    unrelated = manager_state.harness_file(home, "unrelated")
                    unrelated.write_bytes(b"unowned content\n")
                    self.write_receipt(home, selected)
                    self.assert_canonical_receipt(home, canonical, legacy)
                    self.assertEqual(unrelated.read_bytes(), b"unowned content\n")
                    # Repeating an alias mutation keeps exactly one current identity.
                    self.write_receipt(home, selected)
                    self.assert_canonical_receipt(home, canonical, legacy)
                    self.assertEqual(unrelated.read_bytes(), b"unowned content\n")

    def test_failed_canonical_receipt_write_preserves_legacy_and_current_receipts(self) -> None:
        home = self.seed_home("write-failure", ["copilot"])
        self.seed_receipt(home, "copilot")
        self.seed_receipt(home, "copilot-cli")
        before = self.snapshot(home)
        with mock.patch.object(manager_state, "atomic_write_json", side_effect=OSError("injected write failure")):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                self.write_receipt(home, "copilot-cli")
        self.assertEqual(self.snapshot(home), before)

    def test_downgrade_receipts_keep_source_until_atomic_legacy_target_is_written(self) -> None:
        home = self.seed_home("translate-current", ["copilot-cli", "gemini-cli"])
        originals = {}
        for canonical, legacy in self.pairs:
            path = self.seed_receipt(home, canonical)
            originals[legacy] = json.loads(path.read_text())
        desired = manager_state.desired_file(home).read_bytes()
        install = (home / "state/install.json").read_bytes()
        atomic_write = manager_state.atomic_write_json
        written = []

        def checked_write(target: Path, payload: dict) -> None:
            source = manager_state.harness_file(home, target.stem + "-cli")
            self.assertTrue(source.is_file(), "source removed before the atomic target write")
            self.assertEqual(json.loads(source.read_text()), originals[target.stem])
            atomic_write(target, payload)
            self.assertTrue(source.is_file(), "source must survive until the write returns")
            self.assertEqual(json.loads(target.read_text())["harness"], target.stem)
            written.append(target.stem)

        with mock.patch.object(manager_state, "atomic_write_json", side_effect=checked_write):
            manager_state.translate_harness_receipts(home, [legacy for _canonical, legacy in self.pairs])
        self.assertEqual(written, ["copilot", "gemini"])
        for canonical, legacy in self.pairs:
            self.assertFalse(manager_state.harness_file(home, canonical).exists())
            self.assertEqual(json.loads(manager_state.harness_file(home, legacy).read_text()), {
                **originals[legacy], "harness": legacy,
            })
        self.assertEqual(manager_state.desired_file(home).read_bytes(), desired)
        self.assertEqual((home / "state/install.json").read_bytes(), install)

    def test_downgrade_receipts_converge_mixed_names_without_losing_current_metadata(self) -> None:
        home = self.seed_home("translate-mixed", ["copilot-cli", "copilot", "gemini-cli", "gemini"])
        current = {}
        for canonical, legacy in self.pairs:
            self.seed_receipt(home, legacy)
            path = self.seed_receipt(home, canonical)
            payload = {**json.loads(path.read_text()), "managerRevision": self.revision, "root": f"/current/{canonical}"}
            manager_state.atomic_write_json(path, payload)
            current[legacy] = payload
        unrelated = self.seed_receipt(home, "codex")
        original_unrelated = (unrelated.read_bytes(), unrelated.stat().st_mtime_ns)
        manager_state.translate_harness_receipts(home, ["copilot", "gemini", "copilot"])
        self.assertEqual(sorted(path.name for path in unrelated.parent.iterdir()), ["codex.json", "copilot.json", "gemini.json"])
        for _canonical, legacy in self.pairs:
            self.assertEqual(json.loads(manager_state.harness_file(home, legacy).read_text()), {
                **current[legacy], "harness": legacy,
            })
        self.assertEqual((unrelated.read_bytes(), unrelated.stat().st_mtime_ns), original_unrelated)

    def test_failed_downgrade_target_write_preserves_current_and_legacy_receipts(self) -> None:
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                home = self.seed_home(f"translate-failure-{mixed}", ["gemini-cli"])
                self.seed_receipt(home, "gemini-cli")
                if mixed:
                    self.seed_receipt(home, "gemini")
                before = self.snapshot(home)
                with mock.patch.object(manager_state, "atomic_write_json", side_effect=OSError("injected downgrade write failure")):
                    with self.assertRaisesRegex(OSError, "injected downgrade write failure"):
                        manager_state.translate_harness_receipts(home, ["gemini"])
                self.assertEqual(self.snapshot(home), before)

    def test_downgrade_translation_is_noop_for_existing_target_names_and_missing_receipts(self) -> None:
        home = self.seed_home("translate-noop", ["copilot-cli"])
        self.seed_receipt(home, "copilot-cli")
        before = self.snapshot(home)
        manager_state.translate_harness_receipts(home, ["copilot-cli", "gemini"])
        self.assertEqual(self.snapshot(home), before)

    @unittest.skipIf(os.name == "nt", "symlinks require platform-specific privileges")
    def test_downgrade_translation_refuses_linked_parent_source_and_target(self) -> None:
        for kind in ("parent", "source", "target", "dangling-target"):
            with self.subTest(kind=kind):
                home = self.seed_home(f"translate-linked-{kind}", ["copilot-cli"])
                source = self.seed_receipt(home, "copilot-cli")
                external = self.root / f"outside-{kind}"
                if kind == "parent":
                    source.parent.rename(external)
                    source.parent.symlink_to(external, target_is_directory=True)
                else:
                    external.mkdir()
                    target = external / "receipt.json"
                    if kind != "dangling-target":
                        target.write_bytes(source.read_bytes())
                    if kind == "source":
                        source.unlink()
                        source.symlink_to(target)
                    else:
                        manager_state.harness_file(home, "copilot").symlink_to(target)
                before = self.snapshot(home)
                outside_before = self.snapshot(external)
                with self.assertRaises(SystemExit):
                    manager_state.translate_harness_receipts(home, ["copilot"])
                self.assertEqual(self.snapshot(home), before)
                self.assertEqual(self.snapshot(external), outside_before)

    def test_unowned_or_corrupt_alias_receipts_are_preserved_by_write_and_remove(self) -> None:
        invalid = {
            "bad-json": b"{not-json", "not-object": b"[]",
            "wrong-schema": json.dumps({"schemaVersion": "unknown", "harness": "copilot"}).encode(),
            "wrong-owner": json.dumps({"schemaVersion": manager_state.STATE_SCHEMA_VERSION, "harness": "gemini"}).encode(),
            "unknown-owner": json.dumps({"schemaVersion": manager_state.STATE_SCHEMA_VERSION, "harness": "unrecognized"}).encode(),
        }
        for kind, content in invalid.items():
            for action in ("write", "remove"):
                with self.subTest(kind=kind, action=action):
                    home = self.seed_home(f"{kind}-{action}", ["copilot"])
                    self.seed_receipt(home, "copilot-cli")
                    legacy = self.seed_receipt(home, "copilot")
                    legacy.write_bytes(content)
                    before = self.snapshot(home)
                    with self.assertRaises(SystemExit):
                        if action == "write":
                            self.write_receipt(home, "copilot-cli")
                        else:
                            manager_state.remove_harness_receipt(home, "copilot-cli")
                    self.assertEqual(self.snapshot(home), before)

    @unittest.skipIf(os.name == "nt", "symlinks require platform-specific privileges")
    def test_alias_receipt_symlinks_including_dangling_links_are_never_followed(self) -> None:
        for dangling in (False, True):
            for action in ("write", "remove"):
                with self.subTest(dangling=dangling, action=action):
                    home = self.seed_home(f"symlink-{dangling}-{action}", ["gemini"])
                    current = self.seed_receipt(home, "gemini-cli")
                    target = home / "external-receipt.json"
                    if not dangling:
                        target.write_bytes(current.read_bytes())
                    manager_state.harness_file(home, "gemini").symlink_to(target)
                    before = self.snapshot(home)
                    with self.assertRaises(SystemExit):
                        if action == "write":
                            self.write_receipt(home, "gemini-cli")
                        else:
                            manager_state.remove_harness_receipt(home, "gemini")
                    self.assertEqual(self.snapshot(home), before)

    def test_install_over_legacy_state_refreshes_once_and_does_not_duplicate_desired(self) -> None:
        for canonical, legacy in self.pairs:
            with self.subTest(harness=canonical):
                home = self.seed_home(f"install-{canonical}", [legacy])
                self.seed_receipt(home, legacy)
                install = (home / "state/install.json").read_bytes()
                with self.lifecycle_environment() as effects:
                    self.run_command(home, "install", canonical, legacy)
                effects["_refresh_one"].assert_called_once()
                self.assertEqual(effects["_refresh_one"].call_args.kwargs["harness"], canonical)
                self.assertEqual(json.loads(manager_state.desired_file(home).read_text())["harnesses"], [canonical])
                self.assert_canonical_receipt(home, canonical, legacy)
                self.assertEqual((home / "state/install.json").read_bytes(), install)

    def test_remove_short_old_and_all_targets_delete_both_valid_receipt_names(self) -> None:
        for canonical, legacy in self.pairs:
            for selected in (canonical, legacy, "--all"):
                with self.subTest(harness=canonical, selected=selected):
                    home = self.seed_home(f"remove-{canonical}-{selected}", [canonical, legacy])
                    self.seed_receipt(home, legacy)
                    self.seed_receipt(home, canonical)
                    install = (home / "state/install.json").read_bytes()
                    with self.lifecycle_environment() as effects:
                        self.run_command(home, "remove", selected)
                    effects["_remove_one"].assert_called_once()
                    self.assertEqual(effects["_remove_one"].call_args.kwargs["harness"], canonical)
                    self.assertEqual(json.loads(manager_state.desired_file(home).read_text())["harnesses"], [])
                    self.assertFalse(manager_state.harness_file(home, canonical).exists())
                    self.assertFalse(manager_state.harness_file(home, legacy).exists())
                    self.assertEqual((home / "state/install.json").read_bytes(), install)

    def test_remove_rejects_invalid_receipt_before_external_cleanup_or_desired_mutation(self) -> None:
        for selected in ("copilot-cli", "copilot", "--all"):
            with self.subTest(selected=selected):
                home = self.seed_home(f"remove-invalid-{selected}", ["copilot"])
                self.seed_receipt(home, "copilot-cli")
                self.seed_receipt(home, "copilot").write_bytes(b"{unowned-content")
                before = self.snapshot(home, omit_lock=True)
                with self.lifecycle_environment() as effects:
                    with self.assertRaises(SystemExit):
                        self.run_command(home, "remove", selected)
                effects["_remove_one"].assert_not_called()
                self.assertEqual(self.snapshot(home, omit_lock=True), before)

    def test_refresh_and_repair_converge_mixed_state_after_success(self) -> None:
        for command in ("refresh", "repair"):
            for arguments in ((), ("--all",)):
                with self.subTest(command=command, arguments=arguments):
                    home = self.seed_home(f"{command}-{len(arguments)}", ["copilot", "copilot-cli", "gemini", "gemini-cli"])
                    for canonical, legacy in self.pairs:
                        self.seed_receipt(home, legacy)
                        self.seed_receipt(home, canonical)
                    install = home / "state/install.json"
                    original = (install.read_bytes(), install.stat().st_mtime_ns)
                    with self.lifecycle_environment() as effects:
                        self.run_command(home, command, *arguments)
                    self.assertEqual([call.kwargs["harness"] for call in effects["_refresh_one"].call_args_list], ["copilot-cli", "gemini-cli"])
                    self.assertEqual(json.loads(manager_state.desired_file(home).read_text())["harnesses"], ["copilot-cli", "gemini-cli"])
                    for canonical, legacy in self.pairs:
                        self.assert_canonical_receipt(home, canonical, legacy)
                    self.assertEqual((install.read_bytes(), install.stat().st_mtime_ns), original)

    def test_failed_materialization_does_not_normalize_desired_or_receipts(self) -> None:
        for command, arguments, effect in (
            ("install", ("copilot-cli",), "_refresh_one"),
            ("refresh", (), "_refresh_one"),
            ("repair", (), "_refresh_one"),
            ("remove", ("copilot-cli",), "_remove_one"),
        ):
            with self.subTest(command=command):
                home = self.seed_home(f"failed-{command}", ["copilot", "gemini"])
                for _canonical, legacy in self.pairs:
                    self.seed_receipt(home, legacy)
                before = self.snapshot(home, omit_lock=True)
                with self.lifecycle_environment() as effects:
                    effects[effect].side_effect = RuntimeError("injected materialization failure")
                    with self.assertRaisesRegex(RuntimeError, "injected materialization failure"):
                        self.run_command(home, command, *arguments)
                self.assertEqual(self.snapshot(home, omit_lock=True), before)

    def test_status_check_and_doctor_read_legacy_state_without_writing_any_files(self) -> None:
        for command in ("status", "check", "doctor"):
            with self.subTest(command=command):
                home = self.seed_home(f"readonly-{command}", ["copilot", "copilot-cli", "gemini"])
                for _canonical, legacy in self.pairs:
                    self.seed_receipt(home, legacy)
                before = self.snapshot(home)
                with self.lifecycle_environment() as effects:
                    output = self.run_command(home, command, *(["--json"] if command == "status" else []))
                self.assertEqual(self.snapshot(home), before)
                if command == "status":
                    self.assertEqual(json.loads(output)["desiredHarnesses"], ["copilot-cli", "gemini-cli"])
                else:
                    commands = [call.args[0] for call in effects["_run"].call_args_list]
                    self.assertEqual([args[args.index("--harness") + 1] for args in commands], ["copilot-cli", "gemini-cli"])
                    self.assertTrue(all(("--strict-warnings" in args) == (command == "doctor") for args in commands))

    def test_dry_run_keeps_legacy_files_and_names_byte_for_byte(self) -> None:
        for command in ("install", "refresh", "remove", "repair"):
            with self.subTest(command=command):
                home = self.seed_home(f"dryrun-{command}", ["copilot", "gemini"])
                for _canonical, legacy in self.pairs:
                    self.seed_receipt(home, legacy)
                before = self.snapshot(home)
                with self.lifecycle_environment() as effects:
                    self.run_command(home, command, "--all", "--dry-run")
                self.assertEqual(self.snapshot(home), before)
                effects["_bootstrap_tooling"].assert_not_called()
                effects["write_launchers"].assert_not_called()
                selected = effects["_remove_one"] if command == "remove" else effects["_refresh_one"]
                names = [call.kwargs["harness"] for call in selected.call_args_list]
                self.assertIn("copilot-cli", names)
                self.assertIn("gemini-cli", names)
                self.assertNotIn("copilot", names)
                self.assertNotIn("gemini", names)


if __name__ == "__main__":
    unittest.main()
