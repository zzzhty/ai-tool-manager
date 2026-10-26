from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "goal_sequence"
GOAL_CHECKER = ROOT / "skills" / "long-running-goal" / "scripts" / "check_goal_ready.py"
SEQUENCE_CHECKER = (
    ROOT / "skills" / "long-running-goal" / "scripts" / "check_goal_sequence.py"
)


class GoalSequenceCheckerTests(unittest.TestCase):
    @contextmanager
    def sequence_workspace(self) -> Iterator[Path]:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "goal_sequence"
            shutil.copytree(FIXTURE, destination)
            yield destination

    def run_checker(
        self, checker: Path, document: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(checker), str(document), *args],
            capture_output=True,
            check=False,
            text=True,
        )

    def run_sequence(
        self, workspace: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_checker(SEQUENCE_CHECKER, workspace / "sequence.md", *args)

    def replace_once(self, path: Path, old: str, new: str) -> None:
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, f"expected one occurrence in {path}: {old}")
        path.write_text(text.replace(old, new), encoding="utf-8")

    def regex_replace_once(self, path: Path, pattern: str, replacement: str) -> None:
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
        self.assertEqual(count, 1, f"expected one regex occurrence in {path}: {pattern}")
        path.write_text(updated, encoding="utf-8")

    def set_overall(self, path: Path, status: str) -> None:
        self.regex_replace_once(
            path,
            r"^Overall status: (?:Draft|Ready|In Progress|Closed)$",
            f"Overall status: {status}",
        )

    def set_milestone(
        self,
        path: Path,
        milestone: str,
        status: str,
        review: str = "Pending",
        checkpoint: str = "Pending",
    ) -> None:
        self.regex_replace_once(
            path,
            rf"^\| {re.escape(milestone)} \| (?:Not Started|Ready|In Progress|Blocked|Done) \| [^|\n]+ \| [^|\n]+ \|$",
            f"| {milestone} | {status} | {review} | {checkpoint} |",
        )

    def set_execution_row(self, workspace: Path, child_id: str, row: str) -> None:
        self.regex_replace_once(
            workspace / "sequence.md",
            rf"^\| \d+ \| {re.escape(child_id)} \| M\d+ \|.*$",
            row,
        )

    def set_child_state(self, path: Path, state: str, milestone_status: str) -> None:
        self.set_overall(path, state)
        self.set_milestone(path, "M0", milestone_status)

    def close_child(self, workspace: Path, child_id: str) -> None:
        order = 1 if child_id == "child-a" else 2
        depends_on = "n/a" if child_id == "child-a" else "child-a"
        self.set_execution_row(
            workspace,
            child_id,
            f"| {order} | {child_id} | M{order} | n/a | "
            f"[{child_id} closeout](closeouts/{child_id}.md) | {depends_on} | "
            f"Closed | Close Done | {child_id}-close-rev |",
        )

    def add_transition(
        self,
        workspace: Path,
        child_id: str,
        to_state: str,
        predecessor_revision: str,
        timestamp: str,
    ) -> None:
        parent = workspace / "sequence.md"
        text = parent.read_text(encoding="utf-8")
        pattern = (
            r"(?ms)(^## Transition Evidence\n.*?"
            r"^\|---\|---\|---\|---\|---\|---\|\n"
            r"(?:^\|.*\|\n)*)(?=\n*^## Reusable Prompt)"
        )
        row = (
            f"| {timestamp} | {child_id} | Draft | {to_state} | "
            f"{predecessor_revision} | Passed: handoff gate with atomic and sequence checks |\n"
        )
        updated, count = re.subn(pattern, lambda match: match.group(1) + row, text)
        self.assertEqual(count, 1, f"expected canonical Transition Evidence in {parent}")
        parent.write_text(updated, encoding="utf-8")

    def parent_in_progress(self, workspace: Path) -> Path:
        parent = workspace / "sequence.md"
        self.set_overall(parent, "In Progress")
        self.set_milestone(parent, "M0", "Done", "Passed", "Done")
        return parent

    def first_child_executing(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "In Progress")
        child = workspace / "children" / "child-a.md"
        self.set_child_state(child, "In Progress", "In Progress")
        self.set_execution_row(
            workspace,
            "child-a",
            "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | "
            "In Progress | M0 In Progress | n/a |",
        )
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )

    def first_child_ready(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "In Progress")
        child = workspace / "children" / "child-a.md"
        self.set_child_state(child, "Ready", "Ready")
        self.set_execution_row(
            workspace,
            "child-a",
            "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | "
            "Ready | M0 Ready | n/a |",
        )
        self.add_transition(
            workspace,
            "child-a",
            "Ready",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )

    def sequence_baseline_blocked(self, workspace: Path) -> None:
        parent = workspace / "sequence.md"
        self.set_overall(parent, "In Progress")
        self.set_milestone(parent, "M0", "Blocked")
        self.replace_once(
            parent,
            "## M0 - Sequence Baseline And First Promotion\n\n"
            "The sequence baseline is frozen and ready for the one parent execution authorization.",
            "## M0 - Sequence Baseline And First Promotion\n\n"
            "Runtime hard-stop evidence: 2026-07-13 sequence breakpoint remains after "
            "three diagnostic checks found the required local tool unavailable.\n\n"
            "The sequence baseline is frozen and ready for the one parent execution authorization.",
        )

    def successor_executing(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "Done", "Passed", "Done")
        self.set_milestone(parent, "M2", "In Progress")
        self.close_child(workspace, "child-a")
        child = workspace / "children" / "child-b.md"
        self.set_child_state(child, "In Progress", "In Progress")
        self.set_execution_row(
            workspace,
            "child-b",
            "| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | "
            "In Progress | M0 In Progress | n/a |",
        )
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )
        self.add_transition(
            workspace,
            "child-b",
            "In Progress",
            "child-a-close-rev",
            "2026-07-13T11:00:00+08:00",
        )

    def successor_ready(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "Done", "Passed", "Done")
        self.set_milestone(parent, "M2", "In Progress")
        self.close_child(workspace, "child-a")
        child = workspace / "children" / "child-b.md"
        self.set_child_state(child, "Ready", "Ready")
        self.set_execution_row(
            workspace,
            "child-b",
            "| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | "
            "Ready | M0 Ready | n/a |",
        )
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )
        self.add_transition(
            workspace,
            "child-b",
            "Ready",
            "child-a-close-rev",
            "2026-07-13T11:00:00+08:00",
        )

    def executing_child_blocked(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "Blocked")
        evidence = (
            "2026-07-13 child-a breakpoint remains after three diagnostic checks; "
            "the required credential is unavailable."
        )
        self.replace_once(
            parent,
            "## M1 - Child child-a\n\nExecute child-a only through its linked atomic goal contract.",
            f"## M1 - Child child-a\n\nRuntime hard-stop evidence: {evidence}\n\n"
            "Execute child-a only through its linked atomic goal contract.",
        )
        child = workspace / "children" / "child-a.md"
        self.set_child_state(child, "In Progress", "Blocked")
        self.replace_once(
            child,
            "## M0 milestone\n\nImplement the bounded child-a outcome.",
            f"## M0 milestone\n\nRuntime hard-stop evidence: {evidence}\n\n"
            "Implement the bounded child-a outcome.",
        )
        self.set_execution_row(
            workspace,
            "child-a",
            "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | "
            "In Progress | M0 Blocked | n/a |",
        )
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )

    def promotion_drift_blocked(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "Done", "Passed", "Done")
        self.set_milestone(parent, "M2", "Blocked")
        self.close_child(workspace, "child-a")
        self.replace_once(
            parent,
            "## M2 - Child child-b\n\nExecute child-b only after child-a is Closed and its handoff gate passes.",
            "## M2 - Child child-b\n\n"
            "Runtime hard-stop evidence: 2026-07-13 child-b semantic drift invalidated "
            "the handoff; diagnostics preserved the failure and require a fresh grill-with-docs "
            "marker before promotion.\n\n"
            "Execute child-b only after child-a is Closed and its handoff gate passes.",
        )
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )

    def integration_in_progress(self, workspace: Path) -> None:
        parent = self.parent_in_progress(workspace)
        self.set_milestone(parent, "M1", "Done", "Passed", "Done")
        self.set_milestone(parent, "M2", "Done", "Passed", "Done")
        self.set_milestone(parent, "M3", "In Progress")
        self.close_child(workspace, "child-a")
        self.close_child(workspace, "child-b")
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )
        self.add_transition(
            workspace,
            "child-b",
            "In Progress",
            "child-a-close-rev",
            "2026-07-13T11:00:00+08:00",
        )

    def final_closed(self, workspace: Path) -> None:
        parent = workspace / "sequence.md"
        self.set_overall(parent, "Closed")
        for milestone in ("M0", "M1", "M2", "M3", "Close"):
            self.set_milestone(parent, milestone, "Done", "Passed", "Done")
        self.close_child(workspace, "child-a")
        self.close_child(workspace, "child-b")
        self.add_transition(
            workspace,
            "child-a",
            "In Progress",
            "n/a",
            "2026-07-13T10:00:00+08:00",
        )
        self.add_transition(
            workspace,
            "child-b",
            "In Progress",
            "child-a-close-rev",
            "2026-07-13T11:00:00+08:00",
        )
        parent.write_text(
            parent.read_text(encoding="utf-8")
            + "\n## Close execution evidence\n\n"
            + "Validation: atomic, sequence, link, and integration checks passed.\n\n"
            + "Checkpoint evidence: final sequence revision recorded.\n",
            encoding="utf-8",
        )

    def assert_sequence_error(
        self,
        mutation: Callable[[Path], None],
        message: str,
        *args: str,
    ) -> None:
        with self.sequence_workspace() as workspace:
            mutation(workspace)
            completed = self.run_sequence(workspace, *args)
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn(message, completed.stderr)

    def test_valid_sequence_state_matrix(self) -> None:
        def all_draft(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            self.set_overall(parent, "Draft")
            self.set_milestone(parent, "M0", "Not Started")

        def promotion_revalidation(workspace: Path) -> None:
            self.promotion_drift_blocked(workspace)
            self.replace_once(
                workspace / "sequence.md", "require a fresh grill-with-docs marker before promotion",
                "require decision revalidation and a fresh marker before promotion",
            )

        cases: list[tuple[str, Callable[[Path], None], tuple[str, ...]]] = [
            ("all_draft", all_draft, ("--allow-draft",)),
            ("umbrella_ready_m0", lambda workspace: None, ()),
            ("sequence_baseline_hard_stop", self.sequence_baseline_blocked, ()),
            ("first_child_ready_parent_stays_in_progress", self.first_child_ready, ()),
            ("first_child_executing", self.first_child_executing, ()),
            ("successor_auto_promoted_ready", self.successor_ready, ()),
            ("successor_auto_promoted", self.successor_executing, ()),
            ("executing_child_hard_stop", self.executing_child_blocked, ()),
            ("promotion_drift_hard_stop", self.promotion_drift_blocked, ()),
            ("promotion_decision_revalidation", promotion_revalidation, ()),
            ("all_children_closed_integration", self.integration_in_progress, ()),
            ("final_closed", self.final_closed, ()),
        ]
        for name, mutation, args in cases:
            with self.subTest(name=name), self.sequence_workspace() as workspace:
                mutation(workspace)
                completed = self.run_sequence(workspace, *args)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_future_child_approval_does_not_block_preceding_work_or_inherit_parent_authority(self) -> None:
        gate = """
## Deferred approval gates

| Milestone | Action | Status | Approval evidence | Deferral basis |
| --- | --- | --- | --- | --- |
| M0 | Apply the reviewed release to the demo service | Pending | None | User decision: 2026-09-09 user turn 1 reserved child release approval until the artifact review. |
"""
        for stage in (None, self.first_child_executing, self.successor_executing):
            with self.subTest(stage=stage), self.sequence_workspace() as workspace:
                child = workspace / "children" / "child-b.md"
                child.write_text(child.read_text(encoding="utf-8") + gate, encoding="utf-8")
                if stage:
                    stage(workspace)
                completed = self.run_sequence(workspace)
                if stage == self.successor_executing:
                    self.assertEqual(completed.returncode, 1, completed.stdout)
                    self.assertIn("M0 cannot be In Progress with a Pending approval gate", completed.stderr)
                    self.replace_once(
                        child, "| Pending | None |",
                        "| Approved | User authorized the child release, 2026-09-08 task message |",
                    )
                    completed = self.run_sequence(workspace)
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_legacy_sequence_without_housekeeping_sections_remains_valid(self) -> None:
        with self.sequence_workspace() as workspace:
            for path in (
                workspace / "sequence.md",
                workspace / "children" / "child-a.md",
                workspace / "children" / "child-b.md",
            ):
                self.assertNotIn(
                    "## Task Temporary Cache / Housekeeping",
                    path.read_text(encoding="utf-8"),
                )
            completed = self.run_sequence(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_parent_timing_does_not_gate_child_readiness(self) -> None:
        with self.sequence_workspace() as workspace:
            parent = workspace / "sequence.md"
            self.regex_replace_once(
                parent,
                r"^## Preflight Time Assessment\n(?s:.*?)(?=^## Child Preflight Register)",
                """## Preflight Time Assessment

Assessment target: Ready-to-Closed

Assessment mode: Rough range

Rough elapsed-time estimate: 4-8 hours

Basis or blocker: 2026-07-20 serial roll-up assumes bounded local children, warm dependencies, and no external waits.

Critical-path time-cost distribution: Not required: rough range recorded.

""",
            )
            completed = self.run_sequence(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_parent_and_children_keep_independent_housekeeping_policies(self) -> None:
        def section(owner: str, policy: str, roots: str, boundary: str) -> str:
            return (
                "## Task Temporary Cache / Housekeeping\n\n"
                f"Close housekeeping policy: {policy}\n\n"
                "Housekeeping decision source: Explicit user confirmation recorded for "
                "this fixture.\n\n"
                "Task temporary cache root strategy: Resolve the host platform/runtime "
                f"standard temporary root, allocate a {owner}-owned namespace beneath the "
                "resolved root, and record the exact owner root before first use.\n\n"
                f"Recorded task temporary cache roots: {roots}\n\n"
                f"Housekeeping boundary: {boundary}\n\n"
            )

        with self.sequence_workspace() as workspace:
            parent = workspace / "sequence.md"
            child_a = workspace / "children" / "child-a.md"
            child_b = workspace / "children" / "child-b.md"
            self.replace_once(
                parent,
                "## Child Preflight Register",
                section(
                    "sequence",
                    "Enabled",
                    "Resolve and record before first use.",
                    "Use `watcher:housekeeping` only for inventoried sequence-owned "
                    "orchestration/integration disposable candidates; never cover child roots.",
                )
                + "## Child Preflight Register",
            )
            self.replace_once(
                child_a,
                "## Loop Blueprint / Harness",
                section(
                    "goal",
                    "Disabled",
                    "Resolve and record before first use.",
                    "Preserve and report every child-a-owned root without cleanup.",
                )
                + "## Loop Blueprint / Harness",
            )
            self.replace_once(
                child_b,
                "## Loop Blueprint / Harness",
                section(
                    "goal",
                    "Not applicable",
                    "Not applicable",
                    "No child-b task temporary cache root will be created.",
                )
                + "## Loop Blueprint / Harness",
            )

            completed = self.run_sequence(workspace)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            register = parent.read_text(encoding="utf-8").split(
                "## Child Preflight Register", 1
            )[1].split("## Child Execution Register", 1)[0]
            self.assertEqual(
                register.splitlines()[2],
                "| Child ID | Marker | Status | Source |",
            )

            self.replace_once(
                parent,
                "Use `watcher:housekeeping` only for inventoried sequence-owned "
                "orchestration/integration disposable candidates; never cover child roots.",
                "Use `watcher:housekeeping` to override every child policy and clean all "
                "child-owned roots too.",
            )
            rejected = self.run_sequence(workspace)
            self.assertEqual(rejected.returncode, 1, rejected.stdout)
            self.assertIn(
                "sequence parent housekeeping boundary must not inherit, widen, or override child policy",
                rejected.stderr,
            )

            widening = (
                "Use `watcher:housekeeping` to override every child policy and clean all "
                "child-owned roots too."
            )
            for variant in (
                "Use `watcher:housekeeping` to clean child-owned roots too.",
                "Use `watcher:housekeeping` to include child-owned roots in cleanup.",
                "Use `watcher:housekeeping` to cover child-owned roots.",
                "Use `watcher:housekeeping` for inventoried sequence-owned disposable "
                "candidates, do not clean durable evidence, and delete child-owned roots.",
            ):
                self.replace_once(parent, widening, variant)
                rejected = self.run_sequence(workspace)
                self.assertEqual(rejected.returncode, 1, rejected.stdout)
                self.assertIn(
                    "sequence parent housekeeping boundary must not inherit, widen, or override child policy",
                    rejected.stderr,
                )
                widening = variant

    def test_sequence_rejection_matrix(self) -> None:
        def marker_mismatch(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "preflight:demo-child-a:20260713-a",
                "preflight:demo-child-a:20260713-other",
            )

        def too_few_children(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            self.regex_replace_once(parent, r"^\| child-b \|.*\n", "")
            self.regex_replace_once(parent, r"^\| 2 \| child-b \|.*\n", "")

        def duplicate_order(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "| 2 | child-b | M2 |",
                "| 1 | child-b | M2 |",
            )

        def forward_dependency(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a |",
                "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | child-b |",
            )

        def multiple_current(workspace: Path) -> None:
            for child_id in ("child-a", "child-b"):
                child = workspace / "children" / f"{child_id}.md"
                self.set_child_state(child, "Ready", "Ready")
            self.set_execution_row(
                workspace,
                "child-a",
                "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | Ready | M0 Ready | n/a |",
            )
            self.set_execution_row(
                workspace,
                "child-b",
                "| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | Ready | M0 Ready | n/a |",
            )

        def current_milestone_drift(workspace: Path) -> None:
            self.first_child_executing(workspace)
            self.replace_once(
                workspace / "sequence.md", "M0 In Progress | n/a |", "M1 In Progress | n/a |"
            )

        def parent_mapping_error(workspace: Path) -> None:
            self.first_child_executing(workspace)
            self.set_milestone(workspace / "sequence.md", "M1", "Blocked")
            self.replace_once(
                workspace / "sequence.md",
                "## M1 - Child child-a\n\nExecute child-a only through its linked atomic goal contract.",
                "## M1 - Child child-a\n\nRuntime hard-stop evidence: unrelated parent stop.\n\n"
                "Execute child-a only through its linked atomic goal contract.",
            )

        def blocked_without_evidence(workspace: Path) -> None:
            self.promotion_drift_blocked(workspace)
            self.regex_replace_once(
                workspace / "sequence.md",
                r"^Runtime hard-stop evidence:.*$",
                "Promotion remains paused without a canonical evidence field.",
            )

        def closed_missing_evidence(workspace: Path) -> None:
            self.successor_executing(workspace)
            self.replace_once(
                workspace / "sequence.md",
                "[child-a closeout](closeouts/child-a.md)",
                "n/a",
            )
            self.replace_once(
                workspace / "sequence.md",
                "Closed | Close Done | child-a-close-rev |",
                "Closed | Close Done | n/a |",
            )

        def early_integration(workspace: Path) -> None:
            parent = self.parent_in_progress(workspace)
            self.set_milestone(parent, "M3", "In Progress")

        def early_close(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            self.set_overall(parent, "In Progress")
            for milestone in ("M0", "M1", "M2", "M3"):
                self.set_milestone(parent, milestone, "Done", "Passed", "Done")
            self.set_milestone(parent, "Close", "In Progress")

        def unknown_policy(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "Promotion policy: automatic-after-close",
                "Promotion policy: manual",
            )

        def missing_register(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            text = parent.read_text(encoding="utf-8")
            updated, count = re.subn(
                r"(?ms)^## Child Execution Register\n.*?(?=^## )",
                "",
                text,
            )
            self.assertEqual(count, 1)
            parent.write_text(updated, encoding="utf-8")

        def absolute_live_link(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "[child-a](children/child-a.md)",
                "[child-a](/tmp/child-a.md)",
            )

        def self_linked_child(workspace: Path) -> None:
            self.first_child_executing(workspace)
            parent = workspace / "sequence.md"
            self.replace_once(
                parent,
                "preflight:demo-child-a:20260713-a",
                "preflight:demo-sequence:20260713-parent",
            )
            self.replace_once(
                parent,
                "[child-a](children/child-a.md)",
                "[child-a](sequence.md)",
            )

        def weak_drift_evidence(workspace: Path) -> None:
            parent = self.parent_in_progress(workspace)
            self.set_milestone(parent, "M1", "Blocked")
            self.replace_once(
                parent,
                "## M1 - Child child-a\n\nExecute child-a only through its linked atomic goal contract.",
                "## M1 - Child child-a\n\n"
                "Runtime hard-stop evidence: n/a while this stage is not Blocked\n\n"
                "Execute child-a only through its linked atomic goal contract.",
            )

        def missing_transition(workspace: Path) -> None:
            self.first_child_executing(workspace)
            self.regex_replace_once(
                workspace / "sequence.md",
                r"^\| 2026-07-13T10:00:00\+08:00 \| child-a \|.*\n",
                "",
            )

        def duplicate_execution_table(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            duplicate = (
                "| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | Draft | n/a | n/a |\n\n"
                "| Order | Child ID | Parent milestone | Live goal | Closeout evidence | Depends on | State | Current milestone | Close revision |\n"
                "|---|---|---|---|---|---|---|---|---|\n"
                "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | Draft | n/a | n/a |\n"
                "| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | Draft | n/a | n/a |"
            )
            self.replace_once(
                parent,
                "| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | Draft | n/a | n/a |",
                duplicate,
            )

        def swapped_owning_headings(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            self.replace_once(parent, "## M1 - Child child-a", "## M1 - Child temporary")
            self.replace_once(parent, "## M2 - Child child-b", "## M2 - Child child-a")
            self.replace_once(parent, "## M1 - Child temporary", "## M1 - Child child-b")

        def draft_child_has_done_work(workspace: Path) -> None:
            self.set_milestone(
                workspace / "children" / "child-a.md",
                "M0",
                "Done",
                "Passed",
                "Done",
            )

        def commented_child_preflight(workspace: Path) -> None:
            child = workspace / "children" / "child-a.md"
            block = (
                "Planning preflight marker: preflight:demo-child-a:20260713-a\n\n"
                "Planning preflight status: Done\n\n"
                "Preflight source: grill-with-docs"
            )
            self.replace_once(child, block, "<!--\n" + block + "\n-->")

        def unclosed_comment_hides_child_contract(workspace: Path) -> None:
            child = workspace / "children" / "child-a.md"
            self.replace_once(
                child,
                "Planning preflight marker: preflight:demo-child-a:20260713-a",
                "<!--\nPlanning preflight marker: preflight:demo-child-a:20260713-a",
            )

        def copied_current_state(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            self.replace_once(
                parent,
                "Timestamped transitions record historical from/to states and revisions without restating a current child or milestone.",
                "Timestamped transitions record historical from/to states and revisions without restating a current child or milestone.\n\nCurrent child: child-b",
            )

        def manual_parent_harness(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "Execution mode: Loop-shaped execution",
                "Execution mode: Manual staged execution",
            )

        def invalid_transition_timestamp(workspace: Path) -> None:
            self.first_child_executing(workspace)
            self.replace_once(
                workspace / "sequence.md",
                "2026-07-13T10:00:00+08:00",
                "2026-99-99T99:99:00Z",
            )

        def negative_handoff_evidence(workspace: Path) -> None:
            self.first_child_executing(workspace)
            self.replace_once(
                workspace / "sequence.md",
                "Passed: handoff gate with atomic and sequence checks",
                "handoff gate did not pass after sequence checks",
            )

        def unresolved_child_boundary(workspace: Path) -> None:
            self.replace_once(
                workspace / "children" / "child-a.md",
                "Open decisions: None.",
                "Open decisions: Owner TBD.",
            )

        def unresolved_parent_boundary(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "Open decisions: None.",
                "Open decisions: Dependency order pending.",
            )

        def register_id_mismatch(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "| child-b | preflight:demo-child-b:20260713-b |",
                "| child-c | preflight:demo-child-b:20260713-b |",
            )

        def duplicate_child_target(workspace: Path) -> None:
            self.replace_once(
                workspace / "sequence.md",
                "[child-b](children/child-b.md)",
                "[child-b](children/child-a.md)",
            )

        def nonmonotonic_transition_time(workspace: Path) -> None:
            self.successor_executing(workspace)
            self.replace_once(
                workspace / "sequence.md",
                "2026-07-13T11:00:00+08:00",
                "2026-07-13T09:00:00+08:00",
            )

        def ready_transition_mismatch(workspace: Path) -> None:
            self.first_child_executing(workspace)
            child = workspace / "children" / "child-a.md"
            self.set_overall(child, "Ready")
            self.set_milestone(child, "M0", "Ready")
            self.replace_once(
                workspace / "sequence.md",
                "In Progress | M0 In Progress | n/a |",
                "Ready | M0 Ready | n/a |",
            )

        def draft_has_transition_history(workspace: Path) -> None:
            self.add_transition(
                workspace,
                "child-a",
                "Ready",
                "n/a",
                "2026-07-13T10:00:00+08:00",
            )

        def parent_ready_regression(workspace: Path) -> None:
            self.first_child_ready(workspace)
            self.set_overall(workspace / "sequence.md", "Ready")

        def executing_blocked_with_placeholder_evidence(workspace: Path) -> None:
            parent = self.parent_in_progress(workspace)
            self.set_milestone(parent, "M1", "Blocked")
            self.replace_once(
                parent,
                "## M1 - Child child-a\n\nExecute child-a only through its linked atomic goal contract.",
                "## M1 - Child child-a\n\n"
                "Runtime hard-stop evidence: n/a while this stage is not Blocked\n\n"
                "Execute child-a only through its linked atomic goal contract.",
            )
            child = workspace / "children" / "child-a.md"
            self.set_child_state(child, "In Progress", "Blocked")
            self.replace_once(
                child,
                "## M0 milestone\n\nImplement the bounded child-a outcome.",
                "## M0 milestone\n\n"
                "Runtime hard-stop evidence: n/a while this stage is not Blocked\n\n"
                "Implement the bounded child-a outcome.",
            )
            self.set_execution_row(
                workspace,
                "child-a",
                "| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | "
                "In Progress | M0 Blocked | n/a |",
            )
            self.add_transition(
                workspace,
                "child-a",
                "In Progress",
                "n/a",
                "2026-07-13T10:00:00+08:00",
            )

        def parent_stage_blocked_with_placeholder_evidence(workspace: Path) -> None:
            parent = workspace / "sequence.md"
            self.set_overall(parent, "In Progress")
            self.set_milestone(parent, "M0", "Blocked")
            self.replace_once(
                parent,
                "## M0 - Sequence Baseline And First Promotion\n\n"
                "The sequence baseline is frozen and ready for the one parent execution authorization.",
                "## M0 - Sequence Baseline And First Promotion\n\n"
                "Runtime hard-stop evidence: n/a while this stage is not Blocked\n\n"
                "The sequence baseline is frozen and ready for the one parent execution authorization.",
            )

        cases: list[tuple[str, Callable[[Path], None], str]] = [
            ("marker_mismatch", marker_mismatch, "preflight marker disagrees"),
            ("too_few_children", too_few_children, "requires at least two child goals"),
            ("duplicate_order", duplicate_order, "duplicate Order values"),
            ("forward_dependency", forward_dependency, "dependency must reference an earlier child"),
            ("multiple_current", multiple_current, "at most one Ready or In Progress child"),
            ("current_milestone_drift", current_milestone_drift, "Current milestone disagrees"),
            ("parent_mapping_error", parent_mapping_error, "status disagrees with child"),
            ("blocked_without_evidence", blocked_without_evidence, "requires exactly one section-local Runtime hard-stop evidence"),
            ("closed_missing_evidence", closed_missing_evidence, "must be a relative Markdown link"),
            ("early_integration", early_integration, "cannot start before every child is Closed"),
            ("early_close", early_close, "parent Close cannot start before every child is Closed"),
            ("unknown_policy", unknown_policy, "Promotion policy must be automatic-after-close"),
            ("missing_register", missing_register, "migrate narrative umbrella"),
            ("absolute_live_link", absolute_live_link, "must target a relative local Markdown file"),
            ("self_linked_child", self_linked_child, "must not share a planning preflight marker"),
            ("weak_drift_evidence", weak_drift_evidence, "evidence is missing"),
            ("missing_transition", missing_transition, "requires timestamped Transition Evidence"),
            ("duplicate_execution_table", duplicate_execution_table, "must contain exactly one canonical table"),
            ("swapped_owning_headings", swapped_owning_headings, "owning section heading disagrees with register"),
            ("draft_child_has_done_work", draft_child_has_done_work, "Draft requires every atomic milestone"),
            ("commented_child_preflight", commented_child_preflight, "is missing Planning preflight marker"),
            ("unclosed_comment_hides_child_contract", unclosed_comment_hides_child_contract, "is missing Planning preflight marker"),
            ("copied_current_state", copied_current_state, "sole current-state authority"),
            ("manual_parent_harness", manual_parent_harness, "Execution mode must be Loop-shaped execution"),
            ("invalid_transition_timestamp", invalid_transition_timestamp, "requires an RFC3339 timestamp"),
            ("negative_handoff_evidence", negative_handoff_evidence, "requires concrete passed handoff-gate evidence"),
            ("unresolved_child_boundary", unresolved_child_boundary, "Open decisions may contain only bounded runtime hard stops"),
            ("unresolved_parent_boundary", unresolved_parent_boundary, "Open decisions may contain only bounded runtime hard stops"),
            ("register_id_mismatch", register_id_mismatch, "Child ID sets disagree"),
            ("duplicate_child_target", duplicate_child_target, "must not share the same atomic goal target"),
            ("nonmonotonic_transition_time", nonmonotonic_transition_time, "timestamps must be non-decreasing"),
            ("ready_transition_mismatch", ready_transition_mismatch, "Ready requires promotion To Ready"),
            ("draft_has_transition_history", draft_has_transition_history, "must not have historical promotion Transition Evidence"),
            ("parent_ready_regression", parent_ready_regression, "Ready sequence parent is only valid at M0"),
            ("executing_blocked_with_placeholder_evidence", executing_blocked_with_placeholder_evidence, "evidence is missing"),
            ("parent_stage_blocked_with_placeholder_evidence", parent_stage_blocked_with_placeholder_evidence, "parent M0 Blocked evidence is missing"),
        ]
        for name, mutation, message in cases:
            with self.subTest(name=name):
                self.assert_sequence_error(mutation, message)

    def test_atomic_and_sequence_accept_consistent_explicit_skip(self) -> None:
        with self.sequence_workspace() as workspace:
            child = workspace / "children" / "child-a.md"
            parent = workspace / "sequence.md"
            self.replace_once(
                child,
                "preflight:demo-child-a:20260713-a",
                "preflight:demo-child-a:skip:20260713-a",
            )
            self.replace_once(child, "Planning preflight status: Done", "Planning preflight status: Skipped by explicit user instruction")
            self.replace_once(child, "Preflight source: grill-with-docs", "Preflight source: user skip")
            self.regex_replace_once(
                child, r"^Preflight evidence:.*$",
                "Preflight evidence: User skip: 2026-09-09 user turn 1 explicitly skipped child-a's interview while retaining its decisions and permissions.",
            )
            self.replace_once(
                parent,
                "| child-a | preflight:demo-child-a:20260713-a | Done | grill-with-docs |",
                "| child-a | preflight:demo-child-a:skip:20260713-a | Skipped by explicit user instruction | user skip |",
            )

            atomic = self.run_checker(GOAL_CHECKER, child, "--allow-draft")
            self.assertEqual(atomic.returncode, 0, atomic.stderr)
            sequence = self.run_sequence(workspace)
            self.assertEqual(sequence.returncode, 0, sequence.stderr)

    def test_sequence_preflight_register_matches_full_child_tuple(self) -> None:
        with self.sequence_workspace() as workspace:
            parent = workspace / "sequence.md"
            child = workspace / "children" / "child-a.md"
            self.replace_once(parent, "preflight:demo-sequence:20260713-parent", "preflight:demo-sequence:skip:20260713-parent")
            self.replace_once(parent, "Planning preflight status: Done", "Planning preflight status: Skipped by explicit user instruction")
            self.replace_once(parent, "Preflight source: grill-with-docs", "Preflight source: user skip (explicit instruction)")
            self.regex_replace_once(
                parent, r"^Preflight evidence:.*$",
                "Preflight evidence: User skip: 2026-09-09 user turn 1 explicitly skipped the parent interview while retaining frozen child boundaries.",
            )
            self.replace_once(child, "Preflight source: grill-with-docs", "Preflight source: existing decisions")
            self.regex_replace_once(
                child, r"^Preflight evidence:.*$",
                "Preflight evidence: Reused: preflight:demo-child-a:20260712-prior; 2026-09-09 user turn 1 verified the completed preflight and unchanged child-a permissions.",
            )
            mismatch = self.run_sequence(workspace)
            self.assertEqual(mismatch.returncode, 1)
            self.assertIn("preflight source disagrees with Child Preflight Register", mismatch.stderr)
            self.replace_once(parent, "| child-a | preflight:demo-child-a:20260713-a | Done | grill-with-docs |", "| child-a | preflight:demo-child-a:20260713-a | Done | existing decisions |")
            valid = self.run_sequence(workspace)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.replace_once(parent, "| Done | existing decisions |", "| Skipped by explicit user instruction | existing decisions |")
            invalid = self.run_sequence(workspace)
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("preflight status disagrees with Child Preflight Register", invalid.stderr)

    def test_sequence_requires_preflight_even_when_atomic_draft_omits_it(self) -> None:
        with self.sequence_workspace() as workspace:
            child = workspace / "children" / "child-a.md"
            for line in (
                "Planning preflight marker: preflight:demo-child-a:20260713-a\n\n",
                "Planning preflight status: Done\n\n",
                "Preflight source: grill-with-docs\n\n",
                "Preflight evidence: Completed: 2026-09-09 user turn 1 confirmed design, documentation ownership, and action permissions through Close.\n\n",
            ):
                self.replace_once(child, line, "")
            self.regex_replace_once(child, r"^Authorization evidence:.*$", "")

            atomic = self.run_checker(GOAL_CHECKER, child, "--allow-draft")
            self.assertEqual(atomic.returncode, 0, atomic.stderr)
            sequence = self.run_sequence(workspace)
            self.assertEqual(sequence.returncode, 1, sequence.stdout)
            self.assertIn("child child-a is missing Planning preflight marker", sequence.stderr)
            self.assertIn("child child-a is missing Planning preflight status", sequence.stderr)
            self.assertIn("child child-a is missing Preflight source", sequence.stderr)

    def test_parent_authority_cannot_supply_missing_child_preflight_or_approval_evidence(self) -> None:
        for field in ("Preflight evidence", "Authorization evidence"):
            with self.subTest(field=field), self.sequence_workspace() as workspace:
                child = workspace / "children" / "child-b.md"
                self.regex_replace_once(child, rf"^{re.escape(field)}:.*$", "")
                # Child-b remains Draft, but its declaration of completed preflight
                # must have evidence even before the automatic serial handoff.
                atomic = self.run_checker(GOAL_CHECKER, child, "--allow-draft")
                self.assertEqual(atomic.returncode, 1, atomic.stdout)
                self.assertIn(field, atomic.stderr)
                result = self.run_sequence(workspace)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("child-b", result.stderr)
                self.assertIn(field, result.stderr)

    def test_composed_child_preflight_requires_matching_register_and_resolvable_evidence(self) -> None:
        with self.sequence_workspace() as workspace:
            child = workspace / "children" / "child-a.md"
            parent = workspace / "sequence.md"
            self.replace_once(child, "Preflight source: grill-with-docs", "Preflight source: grilling + domain-modeling")
            mismatch = self.run_sequence(workspace)
            self.assertEqual(mismatch.returncode, 1, mismatch.stdout)
            self.assertIn("preflight source disagrees", mismatch.stderr)
            self.replace_once(
                parent,
                "| child-a | preflight:demo-child-a:20260713-a | Done | grill-with-docs |",
                "| child-a | preflight:demo-child-a:20260713-a | Done | grilling + domain-modeling |",
            )
            evidence = workspace / "children" / "child-a-decisions.md"
            evidence.write_text("# Child-a decisions\n\nChild-a scope, documentation, and permissions were confirmed.\n", encoding="utf-8")
            self.regex_replace_once(
                child, r"^Preflight evidence:.*$",
                "Preflight evidence: Completed: [child-a decisions](child-a-decisions.md) records design, documentation, and action permissions through Close.",
            )
            result = self.run_sequence(workspace)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence.unlink()
            result = self.run_sequence(workspace)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("child-a-decisions.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
