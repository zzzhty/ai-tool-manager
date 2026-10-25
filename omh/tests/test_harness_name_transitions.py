"""Cross-version state boundaries for the canonical harness-name migration."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import manager_state as state
import omh


class HarnessNameTransitionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "manager"
        self.manager = dict(repository="repo", revision="a" * 40, releaseVersion="1.0.0",
                            bundleIdentity="bundle", channel="main", requestedRef="main")
        self.desired = dict(schemaVersion=state.STATE_SCHEMA_VERSION,
                            harnesses=["copilot", "gemini"],
                            updatePolicy={"channel": "main", "userOption": "preserve"},
                            userMetadata="preserve", updatedAt="initial")
        state.atomic_write_json(state.desired_file(self.home), self.desired)
        for name in self.desired["harnesses"]:
            state.atomic_write_json(state.harness_file(self.home, name), {
                "schemaVersion": state.STATE_SCHEMA_VERSION, "harness": name,
                "managerRevision": "a" * 40, "root": str(self.home / name),
            })
        install = self.home / "state/install.json"
        install.write_text(json.dumps({"product": "oh-my-harness", "status": "ready",
                                      "harness": "copilot", "revision": "a" * 40}))
        self.legacy_files = {path: path.read_bytes() for path in
                             (install, *sorted((self.home / "state/harnesses").iterdir()))}
        self.operation = state.begin_operation(
            self.home, command="update", before=self.manager,
            target={**self.manager, "revision": "b" * 40})
        self.args = argparse.Namespace(home=str(self.home), operation_id=self.operation["operationId"])
        for target, replacement in (
            ("_journal_instruction_transition", lambda home, operation: operation),
            ("_revision", lambda repo: "b" * 40),
            ("_distribution", lambda repo: ("1.0.0", "bundle")),
            ("_state_context", lambda *args, **kwargs: (self.manager, self.desired)),
            ("ensure_user_path", lambda home: None),
        ):
            patcher = mock.patch.object(omh, target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch("install_oh_my_harness.write_launchers")
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_legacy_state(self):
        for path, content in self.legacy_files.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(json.loads(state.desired_file(self.home).read_text())["harnesses"],
                         ["copilot", "gemini"])
        self.assertEqual(sorted(path.name for path in (self.home / "state/harnesses").iterdir()),
                         ["copilot.json", "gemini.json"])

    def test_resume_keeps_legacy_state_until_commit_then_converges(self):
        seen = []

        def refresh(args, *, home, harness, check_after):
            self.assertIsNotNone(state.load_current_operation(home))
            self.assert_legacy_state()
            seen.append(harness)

        def receipt(home, harness):
            self.assertIsNone(state.load_current_operation(home))
            state.write_harness_receipt(home, harness=harness, manager_revision="b" * 40,
                                        release_version="1.0.0", bundle_identity="bundle", root="root")

        with mock.patch.object(omh, "_refresh_one", side_effect=refresh), \
             mock.patch.object(omh, "_write_harness_state", side_effect=receipt):
            self.assertEqual(omh.command_resume_update(self.args), 0)
        self.assertEqual(seen, ["copilot-cli", "gemini-cli"])
        current = json.loads(state.desired_file(self.home).read_text())
        self.assertEqual(current["harnesses"], ["copilot-cli", "gemini-cli"])
        self.assertEqual(current["updatePolicy"], self.desired["updatePolicy"])
        self.assertEqual(current["userMetadata"], "preserve")
        self.assertEqual(sorted(p.name for p in (self.home / "state/harnesses").iterdir()),
                         ["copilot-cli.json", "gemini-cli.json"])

    def test_failure_after_first_harness_leaves_state_consumable_by_old_rollback(self):
        with mock.patch.object(omh, "_refresh_one", side_effect=[None, SystemExit("closure failure")]), \
             mock.patch.object(omh, "_write_harness_state") as receipt, \
             self.assertRaisesRegex(SystemExit, "closure failure"):
            omh.command_resume_update(self.args)
        receipt.assert_not_called()
        self.assert_legacy_state()
        self.assertIsNotNone(state.load_current_operation(self.home))

    def test_path_failure_leaves_legacy_receipts_and_names_for_old_rollback(self):
        with mock.patch.object(omh, "_refresh_one"), \
             mock.patch.object(omh, "ensure_user_path", side_effect=SystemExit("PATH failure")), \
             self.assertRaisesRegex(SystemExit, "PATH failure"):
            omh.command_resume_update(self.args)
        self.assert_legacy_state()
        self.assertIsNotNone(state.load_current_operation(self.home))

    def test_post_commit_migration_failure_warns_without_triggering_old_rollback(self):
        for error in (OSError("disk full"), SystemExit("unsafe legacy receipt"),
                      subprocess.CalledProcessError(128, ["git", "rev-parse"]),
                      ValueError("invalid plan")):
            with self.subTest(error=type(error).__name__):
                state.atomic_write_json(state.current_operation_file(self.home), self.operation)
                output = io.StringIO()
                with mock.patch.object(omh, "_refresh_one"), \
                     mock.patch.object(omh, "_write_harness_state", side_effect=error), \
                     contextlib.redirect_stderr(output):
                    self.assertEqual(omh.command_resume_update(self.args), 0)
                self.assertIn("migration deferred", output.getvalue())
                self.assertIsNone(state.load_current_operation(self.home))
                self.assert_legacy_state()

    def test_update_preflights_receipts_before_journal_or_state_translation(self):
        for check in (False, True):
            args = argparse.Namespace(home=str(self.home), check=check, channel="main",
                                      to="old", allow_downgrade=True)
            before = state.desired_file(self.home).read_bytes()
            with self.subTest(check=check), contextlib.ExitStack() as stack:
                for name, value in (
                    ("ManagerLock", contextlib.nullcontext()),
                    ("_worktree_clean", True), ("_repository", "repo"),
                    ("_git", subprocess.CompletedProcess([], 0)),
                    ("_target_revision", ("old", "a" * 40)),
                    ("_validate_update_target", ("1.0.0", "bundle")),
                    ("_instruction_transition", ({}, {})),
                    ("_harness_names_at_revision", ("copilot", "gemini")),
                ):
                    stack.enter_context(mock.patch.object(omh, name, return_value=value))
                validate = stack.enter_context(mock.patch.object(
                    omh, "validate_harness_receipts", side_effect=SystemExit("unsafe receipt")))
                journal = stack.enter_context(mock.patch.object(omh, "begin_operation"))
                translate = stack.enter_context(mock.patch.object(omh, "translate_harness_receipts"))
                if check:
                    self.assertEqual(omh.command_update(args), 0)
                    validate.assert_not_called()
                else:
                    with self.assertRaisesRegex(SystemExit, "unsafe receipt"):
                        omh.command_update(args)
                journal.assert_not_called()
                translate.assert_not_called()
                self.assertEqual(state.desired_file(self.home).read_bytes(), before)

    def test_target_names_use_legacy_canonical_keys_even_without_input_aliases(self):
        registry = {"harnesses": {"copilot": {}, "gemini": {}, "zcode": {}}}
        with mock.patch.object(omh, "_git_blob", return_value=json.dumps(registry).encode()):
            self.assertEqual(omh._harness_names_at_revision(Path("repo"), "old", ["gemini-cli", "copilot-cli"]),
                             ("copilot", "gemini"))

    def test_target_names_use_pre_alias_full_canonical_keys(self):
        registry = {"harnesses": {"copilot-cli": {}, "gemini-cli": {}, "zcode": {}}}
        with mock.patch.object(omh, "_git_blob", return_value=json.dumps(registry).encode()):
            self.assertEqual(omh._harness_names_at_revision(Path("repo"), "pre-alias", ["gemini", "copilot"]),
                             ("copilot-cli", "gemini-cli"))

    def test_target_name_mapping_refuses_missing_or_ambiguous_distributions(self):
        for harnesses in ({"zcode": {}}, {"copilot-cli": {}, "copilot": {}}):
            with self.subTest(harnesses=harnesses), \
                 mock.patch.object(omh, "_git_blob", return_value=json.dumps({"harnesses": harnesses}).encode()), \
                 self.assertRaisesRegex(SystemExit, "cannot represent installed harness"):
                omh._harness_names_at_revision(Path("repo"), "old", ["copilot-cli"])


if __name__ == "__main__":
    unittest.main()
