from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from harness_registry import load_harness_registry, resolve_harness_plan  # noqa: E402
from sync_harness_instructions import (  # noqa: E402
    apply_instruction_sync,
    check_instruction_sync,
    prepare_instruction_sync,
    remove_instruction_sync,
)


class HarnessInstructionSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.source = self.root / "repo" / "AGENTS.md"
        self.source.parent.mkdir()
        self.source.write_text("canonical instructions\n", encoding="utf-8")
        self.peer = self.source.with_name("global-instructions.md")
        self.peer.write_text("canonical instructions\n", encoding="utf-8")
        self.registry = load_harness_registry()

    def plan(self, harness: str):
        environment = {"CODEX_HOME": str(self.root / "codex")}
        plan = resolve_harness_plan(
            self.registry,
            harness,
            environ=environment,
            user_home=self.root / "home",
            os_name="posix",
        )
        return replace(
            plan,
            instructions_source=self.source,
            instructions_migration=replace(
                plan.instructions_migration,
                peer_source=self.peer,
            ),
        )

    def test_missing_copy_target_can_be_explicitly_auto_confirmed(self) -> None:
        plan = self.plan("zcode")
        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=True,
            output=lambda _message: None,
        )
        apply_instruction_sync(prepared, dry_run=False)
        self.assertEqual(plan.instructions_target.read_text(encoding="utf-8"), self.source.read_text(encoding="utf-8"))
        self.assertFalse(plan.instructions_target.is_symlink())
        self.assertEqual(check_instruction_sync(plan), [])

    def test_existing_different_file_requires_live_confirmation_even_with_yes(self) -> None:
        plan = self.plan("zcode")
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.write_text("user instructions\n", encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "was not confirmed"):
            prepare_instruction_sync(
                plan,
                dry_run=False,
                assume_yes=True,
                input_fn=lambda _prompt: "no",
                output=lambda _message: None,
            )

        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=True,
            input_fn=lambda _prompt: "yes",
            output=lambda _message: None,
        )
        apply_instruction_sync(prepared, dry_run=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "canonical instructions\n")

    def test_codex_posix_symlink_is_the_registry_owned_materialization(self) -> None:
        plan = self.plan("codex")
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.symlink_to(self.source)

        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=False,
            output=lambda _message: None,
        )
        self.assertEqual(prepared.action, "current")
        self.assertEqual(check_instruction_sync(plan), [])

    def test_unmanaged_symlink_and_codex_override_fail_closed(self) -> None:
        zcode = self.plan("zcode")
        other = self.root / "other.md"
        other.write_text("other\n", encoding="utf-8")
        zcode.instructions_target.parent.mkdir(parents=True)
        zcode.instructions_target.symlink_to(other)
        with self.assertRaisesRegex(SystemExit, "unmanaged instructions symlink"):
            prepare_instruction_sync(
                zcode,
                dry_run=False,
                assume_yes=True,
                output=lambda _message: None,
            )

    def test_exact_former_repo_symlink_requires_live_confirmation(self) -> None:
        plan = self.plan("codex")
        retired_source = self.root / "retired-repo" / "AGENTS.md"
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.symlink_to(retired_source)

        with self.assertRaisesRegex(SystemExit, "was not confirmed"):
            prepare_instruction_sync(
                plan,
                dry_run=False,
                assume_yes=True,
                explicit_former_sources=(retired_source,),
                input_fn=lambda _prompt: "no",
                output=lambda _message: None,
            )

        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=True,
            explicit_former_sources=(retired_source,),
            input_fn=lambda _prompt: "yes",
            output=lambda _message: None,
        )
        apply_instruction_sync(prepared, dry_run=False)
        self.assertEqual(target.resolve(strict=False), self.source.resolve(strict=False))

        codex = self.plan("codex")
        shadow = codex.instruction_shadow_paths[0]
        shadow.parent.mkdir(parents=True, exist_ok=True)
        shadow.write_text("override\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "would be shadowed"):
            prepare_instruction_sync(
                codex,
                dry_run=True,
                assume_yes=False,
                output=lambda _message: None,
            )

    def test_registry_peer_symlink_is_migrated_without_live_confirmation(self) -> None:
        plan = self.plan("codex")
        self.peer.write_text("previous checkpoint\n", encoding="utf-8")
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.symlink_to(self.peer)

        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=False,
            input_fn=lambda _prompt: "no",
            output=lambda _message: None,
        )

        self.assertEqual(prepared.provenance, "registry-peer")
        self.assertTrue(prepared.approved)
        self.assertIn("migration is pending", check_instruction_sync(plan)[0])
        apply_instruction_sync(prepared, dry_run=False)
        self.assertEqual(target.resolve(strict=False), self.source.resolve(strict=False))

    def test_operation_journal_digest_authorizes_copy_forward_and_rollback(self) -> None:
        plan = self.plan("zcode")
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.write_text("previous checkpoint\n", encoding="utf-8")
        previous_digest = hashlib.sha256(target.read_bytes()).hexdigest()

        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=False,
            operation_managed_digests=(previous_digest,),
            input_fn=lambda _prompt: "no",
            output=lambda _message: None,
        )

        self.assertEqual(prepared.provenance, "operation-journal")
        self.assertTrue(prepared.approved)
        apply_instruction_sync(prepared, dry_run=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "canonical instructions\n")

        forward_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        self.source.write_text("previous checkpoint\n", encoding="utf-8")
        self.peer.write_text("unrelated peer\n", encoding="utf-8")
        rollback = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=False,
            operation_managed_digests=(forward_digest,),
            input_fn=lambda _prompt: "no",
            output=lambda _message: None,
        )
        self.assertEqual(rollback.provenance, "operation-journal")
        apply_instruction_sync(rollback, dry_run=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "previous checkpoint\n")

    def test_explicit_former_repo_and_unmanaged_copy_do_not_gain_auto_approval(self) -> None:
        plan = self.plan("zcode")
        former = self.root / "former/AGENTS.md"
        former.parent.mkdir()
        former.write_text("former checkpoint\n", encoding="utf-8")
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.write_bytes(former.read_bytes())

        with self.assertRaisesRegex(SystemExit, "was not confirmed"):
            prepare_instruction_sync(
                plan,
                dry_run=False,
                assume_yes=True,
                explicit_former_sources=(former,),
                input_fn=lambda _prompt: "no",
                output=lambda _message: None,
            )

        with self.assertRaisesRegex(SystemExit, "was not confirmed"):
            prepare_instruction_sync(
                plan,
                dry_run=False,
                assume_yes=True,
                explicit_former_sources=(former,),
                input_fn=lambda _prompt: (_ for _ in ()).throw(EOFError()),
                output=lambda _message: None,
            )

        target.write_text("unmanaged\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "was not confirmed"):
            prepare_instruction_sync(
                plan,
                dry_run=False,
                assume_yes=True,
                input_fn=lambda _prompt: "no",
                output=lambda _message: None,
            )

    def test_remove_accepts_registry_peer_copy(self) -> None:
        plan = self.plan("zcode")
        self.peer.write_text("previous checkpoint\n", encoding="utf-8")
        target = plan.instructions_target
        target.parent.mkdir(parents=True)
        target.write_bytes(self.peer.read_bytes())

        remove_instruction_sync(plan, dry_run=False)
        self.assertFalse(target.exists())

    def test_target_change_after_preflight_aborts_atomic_write(self) -> None:
        plan = self.plan("zcode")
        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=True,
            output=lambda _message: None,
        )
        plan.instructions_target.parent.mkdir(parents=True)
        plan.instructions_target.write_text("appeared\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "changed after preflight"):
            apply_instruction_sync(prepared, dry_run=False)

    def test_source_change_after_preflight_aborts_atomic_write(self) -> None:
        plan = self.plan("zcode")
        prepared = prepare_instruction_sync(
            plan,
            dry_run=False,
            assume_yes=True,
            output=lambda _message: None,
        )
        self.source.write_text("changed after confirmation\n", encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "source changed after preflight"):
            apply_instruction_sync(prepared, dry_run=False)
        self.assertFalse(plan.instructions_target.exists())


if __name__ == "__main__":
    unittest.main()
