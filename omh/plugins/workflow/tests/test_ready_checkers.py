from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOAL_CHECKER = ROOT / "skills" / "long-running-goal" / "scripts" / "check_goal_ready.py"
SOP_CHECKER = ROOT / "skills" / "sop" / "scripts" / "check_sop_ready.py"
COMPLETED_PREFLIGHT = "Completed: 2026-09-09 user turn 1 confirmed design, documentation ownership, and action permissions through Close."
REUSED_PREFLIGHT = "Reused: preflight:demo:20260709-prior; 2026-09-09 user turn 1 verified the completed preflight and its unchanged design and permissions."
SKIPPED_PREFLIGHT = "User skip: 2026-09-09 user turn 1 explicitly skipped the interview while preserving the recorded decisions and permissions."
DEFERRAL_BASIS = "User decision: 2026-09-09 user turn 1 reserved approval until the reviewed release is available."
RELEASE_ACTION = "Publish the reviewed release to the demo production service"

CLOSE_EVIDENCE = """
## Close Gate

Close execution evidence:

Validation: all required checks passed.

Checkpoint evidence: close revision recorded.

8. Temporary cache / housekeeping evidence:

Recorded policy: Enabled
Exact roots:
- goal-owned: /tmp/demo-goal-cache
Action: `watcher:housekeeping` inventoried the exact root and removed only confirmed disposable candidates.
Removed size: 1 KiB
Preserved size: 2 KiB
Failed size: 0 B
Residual size: 2 KiB
"""

LOOP_HARNESS = """## Loop Blueprint / Harness

Execution mode: Loop-shaped execution

Trigger:
- Resume on an explicit user command.
Inputs:
- Read the goal file and validation logs.
Triage and orchestration:
- Convert findings into ordered milestone work.
Worktree and isolation:
- Serialize edits in the current checkout.
Skills and context:
- Read this skill and the project instructions.
Connector read/write boundaries:
- Not applicable: this loop has no connector access.
Independent verification:
- Run the owning checker and an independent review.
Runtime hard stops:
- Stop only after repeated technical failure with no in-plan next step.
Durable learning:
- Write validated results into the goal evidence.
"""


def replace_all(text: str, *pairs: tuple[str, str]) -> str:
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def remove_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[:start_index] + text[end_index:]


class ReadyCheckerTests(unittest.TestCase):
    def run_checker(
        self,
        checker: Path,
        document: Path,
        *extra_args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(checker), str(document), *extra_args],
            capture_output=True,
            check=False,
            text=True,
        )

    def run_goal(self, text: str, *args: str, name: str = "goal.md") -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            document = Path(tmp) / name
            document.write_text(text, encoding="utf-8")
            return self.run_checker(GOAL_CHECKER, document, *args)

    def assert_goal_error(self, text: str, message: str, *args: str) -> None:
        completed = self.run_goal(text, *args)
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn(message, completed.stderr)

    def with_harness(self, text: str, harness: str) -> str:
        return (
            text[: text.index("## Loop Blueprint / Harness")]
            + harness.rstrip()
            + "\n\n"
            + text[text.index("## Rollback path") :]
        )

    def close_goal(
        self,
        text: str,
        *,
        recorded_roots: str,
        evidence: str,
    ) -> str:
        return replace_all(
            text,
            ("Overall status: Ready", "Overall status: Closed"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            ("| Close | Not Started | Pending | Pending |", "| Close | Done | Passed | Done |"),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                f"Recorded task temporary cache roots: {recorded_roots}",
            ),
        ) + evidence

    def with_release_gate(self) -> str:
        return replace_all(
            self.with_harness(self.ready, LOOP_HARNESS),
            ("## Milestone status table", "## M1 milestone\n\nPublish the prepared release.\n\n## Milestone status table"),
            ("| Close | Not Started", "| M1 | Not Started | Pending | Pending |\n| Close | Not Started"),
        ) + (
            "\n## Deferred approval gates\n\n"
            "| Milestone | Action | Status | Approval evidence | Deferral basis |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"| M1 | {RELEASE_ACTION} | Pending | None | {DEFERRAL_BASIS} |\n"
        )

    @property
    def ready(self) -> str:
        return (FIXTURES / "ready_goal.md").read_text(encoding="utf-8")

    def assert_checker_contract(self, checker: Path, fixture: Path) -> None:
        completed = self.run_checker(checker, fixture)
        self.assertEqual(completed.returncode, 0, completed.stderr)

        incomplete = fixture.read_text(encoding="utf-8")
        incomplete += "\n```bash\nrun <unfinished-command>\n```\n"
        failed = self.run_goal(incomplete) if checker == GOAL_CHECKER else None
        if checker != GOAL_CHECKER:
            with tempfile.TemporaryDirectory() as tmp:
                document = Path(tmp) / fixture.name
                document.write_text(incomplete, encoding="utf-8")
                failed = self.run_checker(checker, document)

        assert failed is not None
        self.assertEqual(failed.returncode, 1)
        self.assertIn("unresolved placeholders: <unfinished-command>", failed.stderr)

    def test_long_running_goal_checker_validates_placeholders_inside_fences(self) -> None:
        self.assert_checker_contract(GOAL_CHECKER, FIXTURES / "ready_goal.md")

    def test_goal_lifecycle_rejection_matrix(self) -> None:
        ready = self.ready
        closed_incomplete = ready.replace("Overall status: Ready", "Overall status: Closed")
        done_without_evidence = ready.replace(
            "| M0 | Ready | Pending | Pending |",
            "| M0 | Done | Pending | Pending |",
        )
        out_of_order = replace_all(
            ready,
            (
                "## Milestone status table",
                "## M1 milestone\n\nFuture work.\n\n## Milestone status table",
            ),
            (
                "| Close | Not Started | Pending | Pending |",
                "| M1 | Done | Passed | Done |\n| Close | Not Started | Pending | Pending |",
            ),
        )
        current_after_not_started = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: In Progress"),
            (
                "## Milestone status table",
                "## M1 milestone\n\nStatus: In Progress\n\nCurrent work.\n\n"
                "## Milestone status table",
            ),
            (
                "| M0 | Ready | Pending | Pending |",
                "| M0 | Not Started | Pending | Pending |\n"
                "| M1 | In Progress | Pending | Pending |",
            ),
        )
        multiple_current = replace_all(
            ready,
            (
                "## Milestone status table",
                "## M1 milestone\n\nStatus: In Progress\n\nCurrent work.\n\n"
                "## Milestone status table",
            ),
            (
                "| Close | Not Started | Pending | Pending |",
                "| M1 | In Progress | Pending | Pending |\n"
                "| Close | Not Started | Pending | Pending |",
            ),
        )
        non_contiguous = replace_all(
            ready,
            (
                "## Milestone status table",
                "## M2 milestone\n\nFuture work.\n\n## Milestone status table",
            ),
            (
                "| Close | Not Started | Pending | Pending |",
                "| M2 | Not Started | Pending | Pending |\n"
                "| Close | Not Started | Pending | Pending |",
            ),
        )
        close_done_not_closed = replace_all(
            ready,
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            (
                "| Close | Not Started | Pending | Pending |",
                "| Close | Done | Passed | Done |",
            ),
        )
        closed_without_evidence = close_done_not_closed.replace(
            "Overall status: Ready", "Overall status: Closed"
        )
        blocked_without_evidence = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Blocked | Pending | Pending |"),
        )
        missing_section = ready.replace("## M0 milestone\n\nBaseline recorded.\n\n", "")
        extra_section = ready.replace(
            "## Milestone status table",
            "## M1 milestone\n\nFuture work.\n\n## Milestone status table",
        )
        duplicate_section = ready.replace(
            "## Milestone status table",
            "## M0 duplicate\n\nDuplicate work.\n\n## Milestone status table",
        )
        missing_m0_row = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: Closed"),
            ("| M0 | Ready | Pending | Pending |\n", ""),
            (
                "| Close | Not Started | Pending | Pending |",
                "| Close | Done | Passed | Done |",
            ),
        ) + CLOSE_EVIDENCE

        cases = [
            ("draft", ready.replace("Overall status: Ready", "Overall status: Draft"), "overall goal status must be Ready", ()),
            ("missing_table", remove_between(ready, "## Milestone status table", "## Review gate"), "missing milestone status table", ()),
            ("closed_incomplete", closed_incomplete, "Closed goal requires every milestone", ()),
            ("done_without_evidence", done_without_evidence, "M0 status Done requires Review Passed", ()),
            ("done_after_incomplete", out_of_order, "Done milestone M1 follows incomplete M0", ()),
            ("current_after_not_started", current_after_not_started, "M1 In Progress requires M0 Done", ()),
            ("multiple_current", multiple_current, "multiple current milestones", ()),
            ("overall_current_mismatch", ready.replace("| M0 | Ready | Pending | Pending |", "| M0 | In Progress | Pending | Pending |"), "overall Ready requires current milestone Ready", ()),
            ("unknown_status", ready.replace("| M0 | Ready | Pending | Pending |", "| M0 | Waiting | Pending | Pending |"), "M0 has invalid milestone status Waiting", ()),
            ("premature_completion", ready.replace("| M0 | Ready | Pending | Pending |", "| M0 | Ready | Passed | Done |"), "Review/Checkpoint completion requires", ()),
            ("failed_review", ready.replace("| M0 | Ready | Pending | Pending |", "| M0 | Ready | Failed | Pending |"), "Review Failed requires milestone status", ()),
            ("non_contiguous", non_contiguous, "milestone sequence must be contiguous", ()),
            ("missing_close", ready.replace("| Close | Not Started | Pending | Pending |\n", ""), "exactly one Close row", ()),
            ("conflicting_draft", ready.replace("Overall status: Ready", "Overall status: Draft") + "\nGoal status: Ready\n", "overall goal statuses disagree", ("--allow-draft",)),
            ("section_status_mismatch", ready.replace("## M0 milestone\n\nBaseline recorded.", "### M0 - Baseline\n\nStatus: In Progress\n\nBaseline recorded."), "status disagrees between section and milestone table", ()),
            ("close_done_not_closed", close_done_not_closed, "Close is Done/Passed/Done but overall goal status is Ready", ()),
            ("closed_without_evidence", closed_without_evidence, "Closed goal requires Close execution evidence", ()),
            ("ready_without_current", ready.replace("| M0 | Ready | Pending | Pending |", "| M0 | Not Started | Pending | Pending |"), "overall Ready requires exactly one Ready milestone", ()),
            ("blocked_without_evidence", blocked_without_evidence, "Blocked requires section-local runtime hard-stop evidence", ()),
            ("missing_section", missing_section, "milestone table has no matching section: M0", ()),
            ("extra_section", extra_section, "milestone section has no matching table row: M1", ()),
            ("duplicate_section", duplicate_section, "duplicate milestone sections: M0", ()),
            ("missing_m0_row", missing_m0_row, "milestone status table must include M0", ()),
        ]
        for name, text, message, args in cases:
            with self.subTest(name=name):
                self.assert_goal_error(text, message, *args)

    def test_preflight_rejection_matrix(self) -> None:
        ready = self.ready
        skip_mismatch = ready.replace(
            "preflight:demo:20260710-ready",
            "preflight:demo:skip:20260710-ready",
        )
        missing_source = ready.replace("\nPreflight source: grill-with-docs\n", "\n")
        partial_draft = missing_source.replace("Overall status: Ready", "Overall status: Draft")
        cases = [
            ("skip_mismatch", skip_mismatch, "preflight skip marker requires status", ()),
            ("missing_source", missing_source, "missing planning preflight source field", ()),
            ("partial_draft", partial_draft, "missing planning preflight source field", ("--allow-draft",)),
        ]
        for name, text, message, args in cases:
            with self.subTest(name=name):
                self.assert_goal_error(text, message, *args)

    def test_preflight_reuses_decisions_and_timing_is_optional(self) -> None:
        ready = replace_all(
            self.ready,
            ("Preflight source: grill-with-docs", "Preflight source: existing decisions"),
            (COMPLETED_PREFLIGHT, REUSED_PREFLIGHT),
        )
        for note in (
            "",
            "## Preflight Time Assessment\n\nAbout 2-4 hours, based on the local validation run; excludes CI queue time.\n\n",
            "## Preflight Time Assessment\n\nUnknown: CI queue duration is unavailable.\n\n",
        ):
            with self.subTest(note=note):
                text = re.sub(
                    r"(?ms)^## Preflight Time Assessment\n.*?(?=^## Task Temporary Cache)", note, ready
                )
                result = self.run_goal(text)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_disabled_housekeeping_needs_no_user_confirmation(self) -> None:
        text = self.ready.replace("Close housekeeping policy: Enabled", "Close housekeeping policy: Disabled")
        text = re.sub(r"(?m)^Housekeeping decision source:.*\n", "", text)
        text = re.sub(
            r"(?ms)^Housekeeping boundary:.*?(?=^## Loop Blueprint)",
            "Housekeeping boundary: Preserve and report all recorded task-owned roots; no cleanup.\n\n", text,
        )
        result = self.run_goal(text)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_sources_require_matching_traceable_decision_evidence(self) -> None:
        variants = {
            "explicit_wrapper": self.ready,
            "composed_workflow": self.ready.replace(
                "Preflight source: grill-with-docs", "Preflight source: grilling + domain-modeling"
            ),
            "completed_reuse": replace_all(
                self.ready,
                ("Preflight source: grill-with-docs", "Preflight source: existing decisions"),
                (COMPLETED_PREFLIGHT, REUSED_PREFLIGHT),
            ),
            "explicit_skip": replace_all(
                self.ready,
                ("preflight:demo:20260710-ready", "preflight:demo:skip:20260710-ready"),
                ("Planning preflight status: Done", "Planning preflight status: Skipped by explicit user instruction"),
                ("Preflight source: grill-with-docs", "Preflight source: user skip"),
                (COMPLETED_PREFLIGHT, SKIPPED_PREFLIGHT),
            ),
            "conversation_reference": self.ready.replace(
                "2026-09-09 user turn 1", "conversation:demo-session turn:42"
            ),
        }
        for name, document in variants.items():
            with self.subTest(name=name):
                result = self.run_goal(document)
                self.assertEqual(result.returncode, 0, result.stderr)

        invalid = {
            "marker_only": (
                re.sub(r"(?m)^Preflight evidence:.*\n", "", self.ready), "Preflight evidence"
            ),
            "untraceable_completion": (
                self.ready.replace(COMPLETED_PREFLIGHT, "Completed: the plan looks complete."), "Preflight evidence"
            ),
            "reuse_without_completed_source": (
                variants["completed_reuse"].replace(REUSED_PREFLIGHT, "Reused: all answers were settled."), "Preflight evidence"
            ),
            "skip_without_user_source": (
                variants["explicit_skip"].replace(SKIPPED_PREFLIGHT, "User skip: urgent work."), "Preflight evidence"
            ),
            "completed_source_claims_reuse": (
                self.ready.replace(COMPLETED_PREFLIGHT, REUSED_PREFLIGHT), "Preflight evidence"
            ),
            "reuse_source_claims_completed": (
                variants["completed_reuse"].replace(REUSED_PREFLIGHT, COMPLETED_PREFLIGHT), "Preflight evidence"
            ),
            "skip_source_claims_completed": (
                variants["explicit_skip"].replace(SKIPPED_PREFLIGHT, COMPLETED_PREFLIGHT), "Preflight evidence"
            ),
            "hidden_preflight_evidence": (
                self.ready.replace(f"Preflight evidence: {COMPLETED_PREFLIGHT}", f"<!-- Preflight evidence: {COMPLETED_PREFLIGHT} -->"), "Preflight evidence"
            ),
            "empty_resolved_decisions": (
                re.sub(r"(?m)^Resolved decisions:.*$", "Resolved decisions: None", self.ready), "Resolved decisions"
            ),
            "unresolved_required_decisions": (
                self.ready.replace("Open decisions: None.", "Open decisions: TBD"), "Open decisions"
            ),
            "unexplained_no_docs": (
                re.sub(r"(?m)^Docs written:.*$", "Docs written: Not applicable", self.ready), "Docs written"
            ),
        }
        for field in ("Resolved decisions", "Open decisions", "Docs written", "Authorization evidence"):
            invalid[f"missing_{field}"] = (
                re.sub(rf"(?m)^{re.escape(field)}:.*\n", "", self.ready), field
            )
        for name, (document, diagnostic) in invalid.items():
            with self.subTest(name=name):
                self.assert_goal_error(document, diagnostic)

    def test_preflight_links_are_resolved_relative_to_the_goal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / "decisions.md"
            source.write_text("# Confirmed decisions\n\nThe user confirmed the demo scope and permissions.\n", encoding="utf-8")
            document = directory / "goal.md"
            link = "[confirmed decisions](decisions.md)"
            variants = {"plain": self.ready.replace("2026-09-09 user turn 1", link)}
            for field in ("Preflight evidence", "Authorization evidence"):
                variants[f"wrapped_{field}"] = re.sub(
                    rf"(?m)^{re.escape(field)}: (.+)$",
                    lambda match: f"{field}: `" + match.group(1).replace("2026-09-09 user turn 1", link) + "`",
                    self.ready,
                )
            variants["wrapped_deferral_basis"] = self.with_release_gate().replace(
                DEFERRAL_BASIS, "`" + DEFERRAL_BASIS.replace("2026-09-09 user turn 1", link) + "`"
            )
            variants["wrapped_approval_evidence"] = self.with_release_gate().replace(
                "| Pending | None |", f"| Approved | `{link} records user approval of the reviewed release` |"
            )
            for source_exists in (True, False):
                if not source_exists:
                    source.unlink()
                for name, text in variants.items():
                    with self.subTest(name=name, source_exists=source_exists):
                        document.write_text(text, encoding="utf-8")
                        result = self.run_checker(GOAL_CHECKER, document)
                        self.assertEqual(result.returncode, 0 if source_exists else 1, result.stderr)
                        if not source_exists:
                            self.assertIn("decisions.md", result.stderr)

    def test_only_uncompleted_draft_and_historical_closed_allow_absent_new_evidence(self) -> None:
        legacy = re.sub(
            r"(?m)^(?:Preflight evidence|Authorization evidence|Resolved decisions|Open decisions|Docs written):.*\n",
            "", self.ready,
        )
        self.assert_goal_error(legacy, "Preflight evidence")
        closed = self.close_goal(
            legacy, recorded_roots="goal-owned: /tmp/demo-goal-cache", evidence=CLOSE_EVIDENCE
        )
        result = self.run_goal(closed)
        self.assertEqual(result.returncode, 0, result.stderr)
        partial_closed = closed.replace(
            "Preflight source: grill-with-docs", f"Preflight source: grill-with-docs\n\nPreflight evidence: {COMPLETED_PREFLIGHT}"
        )
        self.assert_goal_error(partial_closed, "Authorization evidence")
        draft = replace_all(
            legacy,
            ("Overall status: Ready", "Overall status: Draft"),
            ("| M0 | Ready |", "| M0 | Not Started |"),
        )
        self.assert_goal_error(draft, "Preflight evidence", "--allow-draft")
        draft = re.sub(
            r"(?m)^(?:Planning preflight marker|Planning preflight status|Preflight source):.*\n", "", draft
        )
        result = self.run_goal(draft, "--allow-draft")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_temporary_cache_housekeeping_rejection_matrix(self) -> None:
        ready = self.ready
        missing_boundary = re.sub(
            r"\nHousekeeping boundary:.*?(?=\n\n## Loop Blueprint / Harness)",
            "",
            ready,
            flags=re.DOTALL,
        )
        invalid_policy = ready.replace(
            "Close housekeeping policy: Enabled",
            "Close housekeeping policy: Pending",
        )
        implicit_source = ready.replace(
            "Explicit user confirmation recorded for this demo.",
            "Derived from the default Close behavior.",
        )
        missing_watcher = ready.replace(
            "Use `watcher:housekeeping` only for",
            "Clean only",
        )
        hardcoded_root = ready.replace(
            "Resolve the host platform/runtime standard temporary root, allocate a goal-owned namespace beneath the resolved root, and record the exact owner root before first use.",
            "Use /tmp/demo-cache.",
        )
        invalid_not_applicable = ready.replace(
            "Close housekeeping policy: Enabled",
            "Close housekeeping policy: Not applicable",
        )
        not_applicable_with_n_a_roots = replace_all(
            ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                "Recorded task temporary cache roots: n/a",
            ),
        )
        not_applicable_with_hidden_root = replace_all(
            ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                "Recorded task temporary cache roots: Not applicable; "
                "goal-owned: /tmp/hidden-goal-cache",
            ),
        )
        none_created_with_hidden_root = ready.replace(
            "Recorded task temporary cache roots: Resolve and record before first use.",
            "Recorded task temporary cache roots: None created; "
            "goal-owned: /tmp/hidden-goal-cache",
        )
        closed_without_housekeeping_evidence = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: Closed"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            ("| Close | Not Started | Pending | Pending |", "| Close | Done | Passed | Done |"),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                "Recorded task temporary cache roots: goal-owned: /tmp/demo-goal-cache",
            ),
        ) + CLOSE_EVIDENCE.split("\n8. Temporary cache / housekeeping evidence:", 1)[0]

        cases = [
            (
                "missing_boundary",
                missing_boundary,
                "missing Task Temporary Cache / Housekeeping field: Housekeeping boundary",
            ),
            (
                "invalid_policy",
                invalid_policy,
                "Close housekeeping policy must be Enabled, Disabled, or Not applicable",
            ),
            (
                "implicit_source",
                implicit_source,
                "Housekeeping decision source must record non-negated explicit user confirmation",
            ),
            (
                "missing_watcher",
                missing_watcher,
                "Enabled housekeeping requires watcher:housekeeping in the boundary",
            ),
            (
                "hardcoded_root",
                hardcoded_root,
                "root strategy must use a host platform/runtime resolver",
            ),
            (
                "invalid_not_applicable",
                invalid_not_applicable,
                "Not applicable housekeeping requires recorded roots to be Not applicable",
            ),
            (
                "not_applicable_with_n_a_roots",
                not_applicable_with_n_a_roots,
                "Not applicable housekeeping requires recorded roots to be Not applicable",
            ),
            (
                "not_applicable_with_hidden_root",
                not_applicable_with_hidden_root,
                "Not applicable housekeeping requires recorded roots to be Not applicable",
            ),
            (
                "none_created_with_hidden_root",
                none_created_with_hidden_root,
                "recorded roots state values must not include additional text or paths",
            ),
            (
                "closed_without_housekeeping_evidence",
                closed_without_housekeeping_evidence,
                "requires temporary cache / housekeeping evidence",
            ),
        ]
        for name, text, message in cases:
            with self.subTest(name=name):
                self.assert_goal_error(text, message)

    def test_concrete_owner_root_matrix_is_cross_platform(self) -> None:
        cases = {
            "posix_child": "goal-owned: /tmp/demo-goal-cache",
            "posix_child_with_spaces": 'goal-owned: "/tmp/demo goal cache"',
            "windows_child": "goal-owned: C:\\Windows\\Temp\\demo-goal-cache",
            "multiple_owner_labeled_children": (
                "goal-owned: /tmp/demo-goal-cache\n"
                "- goal-owned: /var/tmp/demo-goal-cache-2"
            ),
        }
        for name, recorded_roots in cases.items():
            with self.subTest(name=name):
                text = self.ready.replace(
                    "Recorded task temporary cache roots: Resolve and record before first use.",
                    f"Recorded task temporary cache roots: {recorded_roots}",
                )
                completed = self.run_goal(text, name=f"{name}.md")
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_shared_or_unresolved_temp_roots_are_rejected(self) -> None:
        strategy = (
            "Resolve the host platform/runtime standard temporary root, allocate a "
            "goal-owned namespace beneath the resolved root, and record the exact owner "
            "root before first use."
        )
        cases = {
            "posix_shared_root": (
                "Recorded task temporary cache roots: goal-owned: /tmp",
                "must not name a shared or generic temporary/cache root",
            ),
            "windows_shared_root": (
                "Recorded task temporary cache roots: goal-owned: C:\\Windows\\Temp",
                "must not name a shared or generic temporary/cache root",
            ),
            "posix_shared_root_via_dot_segments": (
                "Recorded task temporary cache roots: goal-owned: /tmp/demo/..",
                "must not name a shared or generic temporary/cache root",
            ),
            "posix_escape_via_dot_segments": (
                "Recorded task temporary cache roots: goal-owned: /tmp/demo/../../etc",
                "must be fully resolved",
            ),
            "windows_shared_root_via_dot_segments": (
                "Recorded task temporary cache roots: goal-owned: "
                "C:\\Windows\\Temp\\demo-goal-cache\\..",
                "must not name a shared or generic temporary/cache root",
            ),
            "windows_drive_root": (
                "Recorded task temporary cache roots: goal-owned: C:\\",
                "must not name a shared or generic temporary/cache root",
            ),
            "second_root_without_owner_label": (
                "Recorded task temporary cache roots: goal-owned: /tmp/demo-goal-cache\n"
                "- /var/tmp/unlabelled-goal-cache",
                "require an owner marker and an absolute owner-specific path",
            ),
            "windows_unresolved": (
                "Recorded task temporary cache roots: goal-owned: %TEMP%\\demo-goal-cache",
                "must be fully resolved",
            ),
            "posix_unresolved": (
                "Recorded task temporary cache roots: goal-owned: $TMPDIR/demo-goal-cache",
                "must be fully resolved",
            ),
            "posix_root_masquerade": (
                "Task temporary cache root strategy: Use the host /tmp itself as the "
                "goal-owned namespace beneath the resolved root.",
                "root strategy must use a host platform/runtime resolver",
            ),
            "windows_root_masquerade": (
                "Task temporary cache root strategy: Use the host C:\\Windows\\Temp itself "
                "as the goal-owned namespace beneath the resolved root.",
                "root strategy must use a host platform/runtime resolver",
            ),
            "posix_root_masquerade_without_itself": (
                "Task temporary cache root strategy: Use the host platform temporary root "
                "/tmp as the goal-owned namespace beneath the resolved root.",
                "root strategy must use a host platform/runtime resolver",
            ),
            "custom_runtime_root_masquerade": (
                "Task temporary cache root strategy: Resolve the host platform/runtime "
                "temporary root at /srv/scratch, use /srv/scratch itself while describing "
                "it as a goal-owned namespace beneath the resolved root.",
                "root strategy must use a host platform/runtime resolver",
            ),
            "generic_namespace": (
                "Task temporary cache root strategy: Resolve the host platform/runtime "
                "temporary root, allocate a namespace beneath the resolved root, and record it.",
                "root strategy must use a host platform/runtime resolver",
            ),
        }
        for name, (replacement, message) in cases.items():
            with self.subTest(name=name):
                if replacement.startswith("Recorded task temporary cache roots:"):
                    text = self.ready.replace(
                        "Recorded task temporary cache roots: Resolve and record before first use.",
                        replacement,
                    )
                else:
                    text = self.ready.replace(
                        f"Task temporary cache root strategy: {strategy}",
                        replacement,
                    )
                self.assert_goal_error(text, message)

    def test_negated_or_inferred_confirmation_never_authorizes_cleanup(self) -> None:
        cases = {
            "exact_reported_counterexample": (
                "No explicit user confirmation was obtained; Enabled was inferred."
            ),
            "postposed_negation": "Explicit user confirmation was not obtained.",
            "without_confirmation": "Enabled was selected without explicit user confirmation.",
            "defaulted_choice": "The housekeeping choice was defaulted to Enabled.",
            "contracted_postposed_negation": (
                "Explicit user confirmation wasn't obtained."
            ),
            "not_explicit_confirmation": "Not explicit user confirmation was obtained.",
            "could_not_obtain": "Explicit user confirmation could not be obtained.",
            "has_not_obtained": "Explicit user confirmation has not been obtained.",
            "confirmation_absent": "Explicit user confirmation was absent.",
            "never_received": "Never received explicit user confirmation.",
            "did_not_obtain": "We did not obtain explicit user confirmation.",
            "did_not_receive": "We did not receive explicit user confirmation.",
            "declined": "Explicit user confirmation was declined.",
            "refused": "Explicit user confirmation was refused.",
            "withdrawn": "Explicit user confirmation was withdrawn.",
            "revoked": "Explicit user confirmation was revoked.",
            "future_confirmation": (
                "Explicit user confirmation will be recorded after Close."
            ),
        }
        for name, decision_source in cases.items():
            with self.subTest(name=name):
                text = self.ready.replace(
                    "Explicit user confirmation recorded for this demo.",
                    decision_source,
                )
                self.assert_goal_error(
                    text,
                    "Housekeeping decision source must record non-negated explicit user confirmation",
                )

    def test_closed_enabled_housekeeping_requires_exact_structured_evidence(self) -> None:
        closed = self.close_goal(
            self.ready,
            recorded_roots="goal-owned: /tmp/demo-goal-cache",
            evidence=CLOSE_EVIDENCE,
        )
        completed = self.run_goal(closed, name="numbered-template-evidence.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)

        cases = {
            "deferred_roots": (
                self.close_goal(
                    self.ready,
                    recorded_roots="Resolve and record before first use.",
                    evidence=CLOSE_EVIDENCE,
                ),
                "requires concrete recorded roots or an explicit None created outcome",
            ),
            "n_a_evidence": (
                self.close_goal(
                    self.ready,
                    recorded_roots="goal-owned: /tmp/demo-goal-cache",
                    evidence=CLOSE_EVIDENCE.split(
                        "8. Temporary cache / housekeeping evidence:", 1
                    )[0]
                    + "8. Temporary cache / housekeeping evidence: n/a\n",
                ),
                "must record the recorded policy",
            ),
            "wrong_root": (
                closed.replace(
                    "- goal-owned: /tmp/demo-goal-cache\nAction:",
                    "- goal-owned: /tmp/another-goal-cache\nAction:",
                ),
                "must repeat every exact recorded root",
            ),
            "recorded_root_is_only_a_prefix": (
                closed.replace(
                    "- goal-owned: /tmp/demo-goal-cache\nAction:",
                    "- goal-owned: /tmp/demo-goal-cache-extra\nAction:",
                ),
                "must repeat every exact recorded root",
            ),
            "missing_watcher_action": (
                closed.replace(
                    "Action: `watcher:housekeeping` inventoried the exact root and removed only confirmed disposable candidates.",
                    "Action: Confirmed disposable candidates were processed.",
                ),
                "must record an affirmative watcher:housekeeping action",
            ),
        }
        for metric in ("Removed", "Preserved", "Failed", "Residual"):
            cases[f"missing_{metric.casefold()}_size"] = (
                re.sub(rf"^{metric} size:.*\n", "", closed, flags=re.MULTILINE),
                f"must record {metric.casefold()} size",
            )

        for name, (text, message) in cases.items():
            with self.subTest(name=name):
                self.assert_goal_error(text, message)

    def test_closed_disabled_and_no_root_outcomes_are_explicit(self) -> None:
        disabled_ready = replace_all(
            self.ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Disabled"),
            (
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: Preserve and report every recorded root; keep durable evidence outside the cache root.",
            ),
        )
        disabled_evidence = """
## Close Gate

Close execution evidence:

Validation: all required checks passed.

Checkpoint evidence: close revision recorded.

8. Temporary cache / housekeeping evidence:

Recorded policy: Disabled
Exact retained roots:
- goal-owned: /tmp/demo-goal-cache
Action: Preserved the exact retained roots without cleanup.
Removed size: 0 B
Preserved size: 3 KiB
Failed size: 0 B
Residual size: 3 KiB
"""
        disabled_closed = self.close_goal(
            disabled_ready,
            recorded_roots="goal-owned: /tmp/demo-goal-cache",
            evidence=disabled_evidence,
        )
        completed = self.run_goal(disabled_closed, name="disabled-closed.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)

        without_sizes = re.sub(
            r"^(?:Removed|Preserved|Failed|Residual) size:.*\n", "", disabled_closed,
            flags=re.MULTILINE,
        )
        for label, document in (
            ("omitted", without_sizes),
            ("unknown", without_sizes + "Residual size: unknown; inventory is unavailable.\n"),
        ):
            with self.subTest(disabled_sizes=label):
                completed = self.run_goal(document)
                self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assert_goal_error(
            without_sizes.replace("Action: Preserved the exact retained roots without cleanup.", ""),
            "must record the preserved or retained action",
        )
        self.assert_goal_error(
            without_sizes.replace("- goal-owned: /tmp/demo-goal-cache", ""),
            "must repeat every exact recorded root",
        )

        enabled_none_created = self.close_goal(
            self.ready,
            recorded_roots="None created",
            evidence="""
## Close Gate

Close execution evidence:

Validation: all required checks passed.

Checkpoint evidence: close revision recorded.

8. Temporary cache / housekeeping evidence:

Recorded policy: Enabled
Roots outcome: None created; no task temporary cache roots were created.
Action: No housekeeping action was needed because no roots were created.
""",
        )
        completed = self.run_goal(enabled_none_created, name="enabled-none-created.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)

        not_applicable_ready = replace_all(
            self.ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
            (
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: No task temporary cache root will be created; durable evidence remains outside temporary storage.",
            ),
        )
        not_applicable_evidence = """
## Close Gate

Close execution evidence:

Validation: all required checks passed.

Checkpoint evidence: close revision recorded.

8. Temporary cache / housekeeping evidence:

Recorded policy: Not applicable
Roots outcome: None created; no task temporary cache roots were created.
Action: No housekeeping action was needed because no roots were created.
"""
        not_applicable_closed = self.close_goal(
            not_applicable_ready,
            recorded_roots="Not applicable",
            evidence=not_applicable_evidence,
        )
        completed = self.run_goal(not_applicable_closed, name="not-applicable-closed.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)

        cases = {
            "disabled_missing_retained_action": (
                disabled_closed.replace(
                    "Action: Preserved the exact retained roots without cleanup.",
                    "Action: No disposition was recorded.",
                ),
                "must record the preserved or retained action",
            ),
            "disabled_negated_retained_action": (
                disabled_closed.replace(
                    "Action: Preserved the exact retained roots without cleanup.",
                    "Action: The exact roots were not preserved or retained.",
                ),
                "must record an affirmative preserved or retained action",
            ),
            "disabled_missing_retained_root": (
                disabled_closed.replace(
                    "- goal-owned: /tmp/demo-goal-cache\nAction:",
                    "Action:",
                ),
                "must repeat every exact recorded root",
            ),
            "not_applicable_n_a_only": (
                not_applicable_closed.replace(
                    "Roots outcome: None created; no task temporary cache roots were created.\n"
                    "Action: No housekeeping action was needed because no roots were created.",
                    "Roots outcome: n/a\nAction: n/a",
                ),
                "requires explicit no-roots Close evidence",
            ),
        }
        for name, (text, message) in cases.items():
            with self.subTest(name=name):
                self.assert_goal_error(text, message)

    def test_enabled_close_cannot_fallback_when_watcher_is_unavailable(self) -> None:
        closed = self.close_goal(
            self.ready,
            recorded_roots="goal-owned: /tmp/demo-goal-cache",
            evidence=CLOSE_EVIDENCE,
        )
        no_watcher_failures = closed.replace(
            "Failed size: 0 B",
            "No `watcher:housekeeping` failures occurred.\nFailed size: 0 B",
        )
        completed = self.run_goal(
            no_watcher_failures,
            name="enabled-no-watcher-failures.md",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        action = (
            "Action: `watcher:housekeeping` inventoried the exact root and removed only "
            "confirmed disposable candidates."
        )
        cases = {
            "unavailable": (
                "Action: `watcher:housekeeping` was unavailable and was not invoked; "
                "the root was left untouched."
            ),
            "posix_recursive_fallback": (
                "Action: `watcher:housekeeping` was unavailable, so `rm -rf` removed the root."
            ),
            "powershell_recursive_fallback": (
                "Action: `watcher:housekeeping` failed; `Remove-Item -Recurse -Force` "
                "removed the root."
            ),
            "not_run": "Action: `watcher:housekeeping` was not run; the root was retained.",
            "skipped": (
                "Action: `watcher:housekeeping` was skipped; another bounded tool "
                "processed candidates."
            ),
            "no_action_occurred": (
                "Action: No `watcher:housekeeping` action occurred; the root was retained."
            ),
            "did_not_run": (
                "Action: `watcher:housekeeping` did not run; the root was retained."
            ),
            "contracted_not_invoked": (
                "Action: `watcher:housekeeping` wasn't invoked; the root was retained."
            ),
            "bypassed_with_unrelated_completion": (
                "Action: `watcher:housekeeping` was bypassed; alternate cleanup completed."
            ),
            "omitted_with_unrelated_completion": (
                "Action: `watcher:housekeeping` was omitted; alternate cleanup completed."
            ),
            "replaced_with_unrelated_completion": (
                "Action: `watcher:housekeeping` was replaced; alternate cleanup completed."
            ),
            "only_planned": (
                "Action: `watcher:housekeeping` was only planned; status remained unknown."
            ),
            "ran_but_failed": (
                "Action: `watcher:housekeeping` ran but failed."
            ),
            "executed_then_failed": (
                "Action: `watcher:housekeeping` executed; it failed."
            ),
            "invoked_returned_failure": (
                "Action: `watcher:housekeeping` was invoked and returned failure."
            ),
        }
        for name, replacement in cases.items():
            with self.subTest(name=name):
                self.assert_goal_error(
                    closed.replace(action, replacement),
                    "cannot close while watcher:housekeeping is unavailable or a raw recursive fallback is recorded",
                )

        fallback_outside_action = closed.replace(
            "Removed size: 1 KiB",
            "Fallback: `rm -rf /tmp/demo-goal-cache`\nRemoved size: 1 KiB",
        )
        self.assert_goal_error(
            fallback_outside_action,
            "cannot close while watcher:housekeeping is unavailable or a raw recursive fallback is recorded",
        )

        unavailable_outside_action = closed.replace(
            "Removed size: 1 KiB",
            "Watcher availability: `watcher:housekeeping` unavailable.\n"
            "Removed size: 1 KiB",
        )
        self.assert_goal_error(
            unavailable_outside_action,
            "cannot close while watcher:housekeeping is unavailable or a raw recursive fallback is recorded",
        )

        powershell_outside_action = closed.replace(
            "Removed size: 1 KiB",
            "Cleanup command: `Remove-Item -Recurse -Force /tmp/demo-goal-cache`\n"
            "Removed size: 1 KiB",
        )
        self.assert_goal_error(
            powershell_outside_action,
            "raw recursive fallback is recorded",
        )

        fenced_recursive_delete = closed.replace(
            "Removed size: 1 KiB",
            "```bash\nrm -rf /tmp/demo-goal-cache\n```\nRemoved size: 1 KiB",
        )
        self.assert_goal_error(
            fenced_recursive_delete,
            "raw recursive fallback is recorded",
        )

        fenced_before_housekeeping = closed.replace(
            "8. Temporary cache / housekeeping evidence:",
            "```bash\nrm -rf /tmp/demo-goal-cache\n```\n\n"
            "8. Temporary cache / housekeeping evidence:",
        )
        self.assert_goal_error(
            fenced_before_housekeeping,
            "raw recursive fallback is recorded",
        )

    def test_policy_boundaries_and_disabled_close_cannot_expand_cleanup(self) -> None:
        disabled_ready = replace_all(
            self.ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Disabled"),
            (
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: Preserve and report every recorded root; keep durable evidence outside the cache root.",
            ),
        )
        disabled_evidence = """
## Close Gate

Close execution evidence:

Validation: all required checks passed.

Checkpoint evidence: close revision recorded.

8. Temporary cache / housekeeping evidence:

Recorded policy: Disabled
Exact retained roots:
- goal-owned: /tmp/demo-goal-cache
Action: Preserved the exact retained roots, then `rm -rf` deleted them.
Removed size: 3 KiB
Preserved size: 0 B
Failed size: 0 B
Residual size: 0 B
"""
        disabled_closed = self.close_goal(
            disabled_ready,
            recorded_roots="goal-owned: /tmp/demo-goal-cache",
            evidence=disabled_evidence,
        )
        disabled_negates_watcher = disabled_ready.replace(
            "Housekeeping boundary: Preserve and report every recorded root; keep durable evidence outside the cache root.",
            "Housekeeping boundary: `watcher:housekeeping` must not run; retain and report every recorded root.",
        )
        completed = self.run_goal(
            disabled_negates_watcher,
            name="disabled-negated-watcher-boundary.md",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        cases = {
            "disabled_boundary_still_enables_watcher": disabled_ready.replace(
                "Housekeeping boundary: Preserve and report every recorded root; keep durable evidence outside the cache root.",
                "Housekeeping boundary: Use `watcher:housekeeping` for inventoried goal-owned disposable cache candidates.",
            ),
            "not_applicable_boundary_still_enables_watcher": replace_all(
                self.ready,
                ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
                (
                    "Recorded task temporary cache roots: Resolve and record before first use.",
                    "Recorded task temporary cache roots: Not applicable",
                ),
            ),
            "disabled_raw_recursive_delete": disabled_closed,
            "disabled_direct_delete": disabled_closed.replace(
                "then `rm -rf` deleted them",
                "then a helper deleted them",
            ),
            "disabled_boundary_permits_delete": disabled_ready.replace(
                "Housekeeping boundary: Preserve and report every recorded root; keep durable evidence outside the cache root.",
                "Housekeeping boundary: Preserve every root; direct deletion is permitted.",
            ),
            "not_applicable_boundary_permits_child_delete": replace_all(
                self.ready,
                ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
                (
                    "Recorded task temporary cache roots: Resolve and record before first use.",
                    "Recorded task temporary cache roots: Not applicable",
                ),
                (
                    "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                    "Housekeeping boundary: No task temporary cache root is created; child roots may still be deleted.",
                ),
            ),
            "enabled_boundary_permits_raw_recursive_delete": self.ready.replace(
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates; raw recursive deletion is permitted.",
            ),
            "enabled_negation_does_not_mask_raw_delete_permission": self.ready.replace(
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, do not remove durable evidence, and raw recursive deletion is permitted.",
            ),
        }
        messages = {
            "disabled_boundary_still_enables_watcher": (
                "Disabled housekeeping boundary must retain recorded roots without cleanup"
            ),
            "not_applicable_boundary_still_enables_watcher": (
                "Not applicable housekeeping boundary must record that no roots are created"
            ),
            "disabled_raw_recursive_delete": "raw recursive fallback is recorded",
            "disabled_direct_delete": "must not record a cleanup or deletion action",
            "disabled_boundary_permits_delete": "must not permit raw, unbounded, or policy-conflicting deletion",
            "not_applicable_boundary_permits_child_delete": "must not permit raw, unbounded, or policy-conflicting deletion",
            "enabled_boundary_permits_raw_recursive_delete": "must not permit raw, unbounded, or policy-conflicting deletion",
            "enabled_negation_does_not_mask_raw_delete_permission": "must not permit raw, unbounded, or policy-conflicting deletion",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.assert_goal_error(text, messages[name])

        raw_delete_variants = {
            "gnu_long_flags": "rm --recursive --force /tmp/demo-goal-cache",
            "gnu_split_flags": "rm -r -f /tmp/demo-goal-cache",
            "powershell_alias": "rm -Recurse -Force C:\\Temp\\demo-goal-cache",
            "powershell_remove_item": (
                "Remove-Item -Recurse -Force C:\\Temp\\demo-goal-cache"
            ),
            "python_rmtree": "shutil.rmtree('/tmp/demo-goal-cache')",
            "go_remove_all": "os.RemoveAll('/tmp/demo-goal-cache')",
            "node_recursive_rm": (
                "fs.rm('/tmp/demo-goal-cache', { recursive: true, force: true })"
            ),
        }
        for name, command in raw_delete_variants.items():
            with self.subTest(name=name):
                text = disabled_closed.replace(
                    "then `rm -rf` deleted them",
                    f"then `{command}` deleted them",
                )
                self.assert_goal_error(text, "raw recursive fallback is recorded")

        disabled_fenced_delete = disabled_closed.replace(
            "Action: Preserved the exact retained roots, then `rm -rf` deleted them.",
            "Action: Preserved the exact retained roots without cleanup.",
        ).replace(
            "Removed size: 3 KiB",
            "```powershell\nRemove-Item -Recurse -Force /tmp/demo-goal-cache\n```\n"
            "Removed size: 3 KiB",
        )
        self.assert_goal_error(
            disabled_fenced_delete,
            "raw recursive fallback is recorded",
        )

        disabled_fenced_before_housekeeping = disabled_closed.replace(
            "Action: Preserved the exact retained roots, then `rm -rf` deleted them.",
            "Action: Preserved the exact retained roots without cleanup.",
        ).replace(
            "8. Temporary cache / housekeeping evidence:",
            "```powershell\nRemove-Item -Recurse -Force /tmp/demo-goal-cache\n```\n\n"
            "8. Temporary cache / housekeeping evidence:",
        )
        self.assert_goal_error(
            disabled_fenced_before_housekeeping,
            "raw recursive fallback is recorded",
        )

    def test_not_applicable_accepts_a_direct_no_root_strategy(self) -> None:
        text = replace_all(
            self.ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
            (
                "Task temporary cache root strategy: Resolve the host platform/runtime standard temporary root, allocate a goal-owned namespace beneath the resolved root, and record the exact owner root before first use.",
                "Task temporary cache root strategy: Not applicable: no task temporary cache root will be created.",
            ),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                "Recorded task temporary cache roots: Not applicable",
            ),
            (
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: No task temporary cache root will be created; durable evidence remains outside temporary storage.",
            ),
        )
        completed = self.run_goal(text, name="not-applicable-direct-strategy.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_closed_atomic_template_evidence_shape_is_accepted(self) -> None:
        template_shaped_evidence = """
## Close Gate

Close 执行证据：

3. 测试证据：
   - Validation: all required checks passed.
8. Temporary cache / housekeeping evidence：
   - Recorded policy：Enabled
   - Exact roots / Roots outcome：
     - goal-owned: /tmp/demo-goal-cache
   - Action：`watcher:housekeeping` inventoried the exact root and removed only confirmed disposable candidates.
   - Removed size：1 KiB
   - Preserved size：2 KiB
   - Failed size：0 B
   - Residual size：2 KiB

Checkpoint evidence：close revision recorded.
"""
        closed = self.close_goal(
            self.ready,
            recorded_roots="goal-owned: /tmp/demo-goal-cache",
            evidence=template_shaped_evidence,
        )
        completed = self.run_goal(closed, name="atomic-template-closed.md")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_harness_and_permission_rejection_matrix(self) -> None:
        ready = self.ready
        missing_harness = remove_between(ready, "## Loop Blueprint / Harness", "## Rollback path")
        no_reason = re.sub(
            r"Not applicable: manual staged execution because.*?external side effect\.",
            "Not applicable: manual staged execution",
            ready,
            flags=re.DOTALL,
        )
        incomplete_loop = ready.replace(
            "Execution mode: Manual staged execution", "Execution mode: Loop-shaped execution"
        )
        empty_loop = self.with_harness(
            ready,
            LOOP_HARNESS.replace(
                "Connector read/write boundaries:\n- Not applicable: this loop has no connector access.",
                "Connector read/write boundaries:",
            ),
        )
        unsafe_local = ready.replace(
            "Planned non-destructive local code and documentation edits, tests, and validation.",
            "Delete production data, publish a release, and send external messages.",
        )

        def hard_stop(value: str) -> str:
            return re.sub(
                r"Stop only when repeated local diagnostics.*?externally visible\.",
                value,
                ready,
                flags=re.DOTALL,
            )

        cases = [
            ("missing_harness", missing_harness, "missing Loop Blueprint / Harness section"),
            ("manual_without_reason", no_reason, "manual harness opt-out requires a reason"),
            ("incomplete_loop", incomplete_loop, "missing harness field: Connector read/write boundaries"),
            ("empty_loop", empty_loop, "empty harness field: Connector read/write boundaries"),
            ("unsafe_local", unsafe_local, "YOLO local operations must be non-destructive and local"),
            ("first_failure", hard_stop("Stop at the first validation failure, any milestone boundary, or checkpoint."), "runtime hard stop misclassifies recoverable work"),
            ("negation_semicolon", hard_stop("Do not stop at checkpoints; stop at the first validation failure."), "runtime hard stop misclassifies recoverable work"),
            ("negation_comma", hard_stop("Do not stop at checkpoints, but stop at the first validation failure."), "runtime hard stop misclassifies recoverable work"),
            ("pending_approval", ready.replace("Not applicable: this demo does not access external systems.", "GitHub release write: pending approval."), "unresolved external write approval keeps the goal Draft"),
            ("awaiting_approval", ready.replace("Not applicable: this demo does not access external systems.", "GitHub release write is awaiting user approval."), "unresolved external write approval keeps the goal Draft"),
            ("manual_connector", ready + "\nThis goal uses the GitHub connector to create release issues.\n", "goal declares connector use but Loop harness is Not applicable"),
            ("manual_parallel", ready + "\nThis goal uses parallel worktrees and multiple subagents.\n", "goal declares Loop-shaped orchestration but harness is Not applicable"),
        ]
        for name, text, message in cases:
            with self.subTest(name=name):
                self.assert_goal_error(text, message)

    def test_deferred_approval_allows_preparation_but_gates_execution_and_close(self) -> None:
        ready = self.with_release_gate()
        gate = "\n## Deferred approval gates" + ready.split("## Deferred approval gates", 1)[1]
        preparing = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("| M0 | Ready |", "| M0 | In Progress |"),
        )
        at_gate = replace_all(
            ready,
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            ("| M1 | Not Started |", "| M1 | Ready |"),
        )
        blocked = replace_all(
            at_gate,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("| M1 | Ready |", "| M1 | Blocked |"),
            ("## M1 milestone", "## M1 milestone\n\nRuntime hard-stop evidence: awaiting the user's release authorization."),
        )
        for document in (ready, preparing, at_gate, blocked):
            completed = self.run_goal(document)
            self.assertEqual(completed.returncode, 0, completed.stderr)

        running = replace_all(
            at_gate,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("| M1 | Ready |", "| M1 | In Progress |"),
        )
        self.assert_goal_error(running, "M1 cannot be In Progress with a Pending approval gate")
        approved = running.replace("| Pending | None |", "| Approved | User release authorization, 2026-09-08 task message |")
        completed = self.run_goal(approved)
        self.assertEqual(completed.returncode, 0, completed.stderr)

        closed = self.close_goal(
            at_gate.replace("| M1 | Ready | Pending | Pending |", "| M1 | Done | Passed | Done |"),
            recorded_roots="goal-owned: /tmp/demo-goal-cache", evidence=CLOSE_EVIDENCE,
        )
        self.assert_goal_error(closed, "M1 cannot be Done with a Pending approval gate")
        close_gate = closed.replace(
            "| M1 | Publish the reviewed release", "| Close | Publish the reviewed release"
        )
        self.assert_goal_error(close_gate, "Close cannot be Done with a Pending approval gate")
        completed = self.run_goal(closed.replace(
            "| Pending | None |", "| Approved | User release authorization, 2026-09-08 task message |"
        ))
        self.assertEqual(completed.returncode, 0, completed.stderr)

        for old, new, error in (
            ("| M1 | Publish", "| M9 | Publish", "unknown milestone: M9"),
            ("Publish the reviewed release to the demo production service", "", "requires a concrete action"),
            ("Publish the reviewed release to the demo production service", "unknown", "requires a concrete action"),
            ("| Pending | None |", "| Denied | User denied |", "must be Pending or Approved"),
            ("| Pending | None |", "| Approved | None |", "requires actual user approval evidence"),
            ("| Pending | None |", "| Approved | awaiting user approval |", "requires actual user approval evidence"),
            ("| Pending | None |", "| Approved | User has not approved this action yet |", "requires actual user approval evidence"),
            ("| Pending | None |", "| Approved | User approval is denied |", "requires actual user approval evidence"),
            ("| Status | Approval evidence |", "| Approval | Evidence |", "requires a Milestone / Action / Status"),
        ):
            with self.subTest(error=error, replacement=new):
                self.assert_goal_error(ready.replace(old, new), error)
        self.assert_goal_error(ready + gate, "duplicate Deferred approval gates sections")
        # Declaring a future gate never converts unresolved pre-approval into permission.
        self.assert_goal_error(
            ready.replace("Not applicable: this demo does not access external systems.", "Release write: pending approval."),
            "unresolved external write approval keeps the goal Draft",
        )

    def test_deferred_gates_require_a_reason_and_do_not_reask_recorded_approval(self) -> None:
        ready = self.with_release_gate()
        for reason in (
            DEFERRAL_BASIS,
            "Required review: 2026-09-09 user turn 1 requires final release artifact review before production publication.",
        ):
            result = self.run_goal(ready.replace(DEFERRAL_BASIS, reason))
            self.assertEqual(result.returncode, 0, result.stderr)

        active_four_column = replace_all(
            ready,
            ("| Approval evidence | Deferral basis |", "| Approval evidence |"),
            ("| --- | --- | --- | --- | --- |", "| --- | --- | --- | --- |"),
            (f"| {DEFERRAL_BASIS} |", "|"),
        )
        cases = {
            "old_active_gate": (active_four_column, "Deferral basis"),
            "no_reason": (ready.replace(DEFERRAL_BASIS, ""), "Deferral basis"),
            "agent_deferred": (ready.replace(DEFERRAL_BASIS, "User decision: ask later because release is in a future milestone."), "Deferral basis"),
            "approved_without_traceable_source": (
                ready.replace("| Pending | None |", "| Approved | User approved |"), "approval evidence"
            ),
            "duplicate_action": (
                ready + f"| M1 | {RELEASE_ACTION} | Approved | 2026-09-09 user turn 2 approved the release | {DEFERRAL_BASIS} |\n",
                "duplicate",
            ),
            "normalized_duplicate_action": (
                ready + f"| M1 | {RELEASE_ACTION.upper().replace(' ', '  ')} | Approved | 2026-09-09 user turn 2 approved the release | {DEFERRAL_BASIS} |\n",
                "duplicate",
            ),
            "approved_in_prior_milestone": (
                ready + f"| M0 | {RELEASE_ACTION} | Approved | 2026-09-09 user turn 2 approved the release | {DEFERRAL_BASIS} |\n",
                "duplicate",
            ),
            "pending_but_already_preapproved": (
                ready.replace("Not applicable: this demo does not access external systems.", RELEASE_ACTION),
                "Pending",
            ),
        }
        for name, (document, message) in cases.items():
            with self.subTest(name=name):
                result = self.run_goal(document)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(message.casefold(), result.stderr.casefold())

        action = "Publish reviewed release v1 to prod"
        for approved_action, pending_action in (
            (action + "-preview", action),
            (action + " after preview validation", action + " after production review"),
        ):
            with self.subTest(approved_action=approved_action, pending_action=pending_action):
                separate_authority = replace_all(
                    ready,
                    (RELEASE_ACTION, pending_action),
                    ("Not applicable: this demo does not access external systems.", approved_action),
                )
                result = self.run_goal(separate_authority)
                self.assertEqual(result.returncode, 0, result.stderr)
                distinct_gates = separate_authority + (
                    f"| M0 | {approved_action} | Approved | 2026-09-09 user turn 2 approved this exact action | {DEFERRAL_BASIS} |\n"
                )
                result = self.run_goal(distinct_gates)
                self.assertEqual(result.returncode, 0, result.stderr)

        # A historical Closed four-column gate remains readable; it grants no new action.
        historical = self.close_goal(
            replace_all(
                active_four_column,
                ("| M1 | Not Started | Pending | Pending |", "| M1 | Done | Passed | Done |"),
                ("| Pending | None |", "| Approved | User approved the reviewed release |"),
            ),
            recorded_roots="goal-owned: /tmp/demo-goal-cache", evidence=CLOSE_EVIDENCE,
        )
        historical = re.sub(r"(?m)^(?:Preflight evidence|Authorization evidence):.*\n", "", historical)
        result = self.run_goal(historical)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_authorization_remains_valid_across_later_milestone_states(self) -> None:
        prepared = replace_all(
            self.ready,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("## Milestone status table", "## M1 milestone\n\nComplete the authorized local documentation and validation.\n\n## Milestone status table"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            ("| Close | Not Started", "| M1 | In Progress | Pending | Pending |\n| Close | Not Started"),
        )
        closing = replace_all(
            prepared,
            ("| M1 | In Progress | Pending | Pending |", "| M1 | Done | Passed | Done |"),
            ("| Close | Not Started |", "| Close | In Progress |"),
        )
        for document in (self.ready, prepared, closing):
            result = self.run_goal(document)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_hard_stop_resource_failures_are_not_keyword_stops(self) -> None:
        for reason in (
            "Stop if required checkpoint signing credentials cannot be obtained through authorized recovery.",
            "Stop when the rebuild tool is unavailable after authorized restore attempts.",
            "Stop at checkpoint if required signing credentials remain unavailable after authorized recovery.",
            "A required review gate verifier failed and no meaningful in-plan step remains.",
        ):
            with self.subTest(reason=reason):
                document = re.sub(
                    r"Stop only when repeated local diagnostics.*?externally visible\.",
                    reason, self.ready, flags=re.DOTALL,
                )
                completed = self.run_goal(document)
                self.assertEqual(completed.returncode, 0, completed.stderr)
        for reason in (
            "Stop at every checkpoint.", "Checkpoints are hard stops.", "Pause after each rebuild.",
            "Stop at every checkpoint and ask the user for permission before continuing.",
            "Stop at the first validation failure and wait for user instructions.",
        ):
            document = re.sub(
                r"Stop only when repeated local diagnostics.*?externally visible\.",
                reason, self.ready, flags=re.DOTALL,
            )
            self.assert_goal_error(document, "runtime hard stop misclassifies recoverable work")

    def test_goal_checker_accepts_valid_contract_matrix(self) -> None:
        ready = self.ready
        draft = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: Draft"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Not Started | Pending | Pending |"),
        )
        draft_pending = draft + "\nGoal status: Draft\n"
        draft_pending = draft_pending.replace(
            "Not applicable: this demo does not access external systems.",
            "GitHub release write: pending approval.",
        )
        in_progress = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | In Progress | Pending | Pending |"),
        )
        blocked = replace_all(
            in_progress,
            ("| M0 | In Progress | Pending | Pending |", "| M0 | Blocked | Pending | Pending |"),
            (
                "## M0 milestone\n\nBaseline recorded.",
                "### M0 - Baseline\n\nStatus: Blocked\n\n"
                "Runtime hard-stop evidence: required credentials are unavailable.\n\n"
                "Baseline recorded.",
            ),
        )
        closed = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: Closed"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            ("| Close | Not Started | Pending | Pending |", "| Close | Done | Passed | Done |"),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                "Recorded task temporary cache roots: goal-owned: /tmp/demo-goal-cache",
            ),
        ) + CLOSE_EVIDENCE
        skipped = replace_all(
            ready,
            ("preflight:demo:20260710-ready", "preflight:demo:skip:20260710-ready"),
            ("Planning preflight status: Done", "Planning preflight status: Skipped by explicit user instruction"),
            ("Preflight source: grill-with-docs", "Preflight source: user skip"),
            (COMPLETED_PREFLIGHT, SKIPPED_PREFLIGHT),
        )
        loop_shaped = self.with_harness(ready, LOOP_HARNESS)
        close_in_progress = replace_all(
            ready,
            ("Overall status: Ready", "Overall status: In Progress"),
            ("| M0 | Ready | Pending | Pending |", "| M0 | Done | Passed | Done |"),
            ("| Close | Not Started | Pending | Pending |", "| Close | In Progress | Pending | Pending |"),
        )
        close_blocked = replace_all(
            close_in_progress,
            ("| Close | In Progress | Pending | Pending |", "| Close | Blocked | Pending | Pending |"),
        ) + "\n## Close Gate\n\nRuntime hard-stop evidence: required credentials are unavailable.\n"
        named_milestone = ready.replace(
            "| M0 | Ready | Pending | Pending |",
            "| M0 `Baseline` | Ready | Pending | Pending |",
        )
        safe_release = ready.replace(
            "Planned non-destructive local code and documentation edits, tests, and validation.",
            "Planned non-destructive local Release builds, tests, and validation.",
        )
        legacy_without_housekeeping = remove_between(
            ready,
            "## Task Temporary Cache / Housekeeping",
            "## Loop Blueprint / Harness",
        )
        disabled_housekeeping = replace_all(
            ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Disabled"),
            (
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: Preserve and report every recorded root; keep durable evidence outside the cache root.",
            ),
        )
        not_applicable_housekeeping = replace_all(
            ready,
            ("Close housekeeping policy: Enabled", "Close housekeeping policy: Not applicable"),
            (
                "Recorded task temporary cache roots: Resolve and record before first use.",
                "Recorded task temporary cache roots: Not applicable",
            ),
            (
                "Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.",
                "Housekeeping boundary: No task temporary cache root will be created; durable evidence remains outside temporary storage.",
            ),
        )
        confirmation_has_been_recorded = ready.replace(
            "Explicit user confirmation recorded for this demo.",
            "Explicit user confirmation has been recorded for this demo.",
        )
        user_explicitly_selected = ready.replace(
            "Explicit user confirmation recorded for this demo.",
            "User explicitly selected Enabled for this demo.",
        )
        user_explicitly_chose = ready.replace(
            "Explicit user confirmation recorded for this demo.",
            "User explicitly chose Enabled for this demo.",
        )

        cases = {
            "ready": (ready, ()),
            "draft": (draft, ("--allow-draft",)),
            "draft_pending": (draft_pending, ("--allow-draft",)),
            "in_progress": (in_progress, ()),
            "blocked": (blocked, ()),
            "closed": (closed, ()),
            "skipped_preflight": (skipped, ()),
            "loop_shaped": (loop_shaped, ()),
            "close_in_progress": (close_in_progress, ()),
            "close_blocked": (close_blocked, ()),
            "named_milestone": (named_milestone, ()),
            "safe_release": (safe_release, ()),
            "legacy_without_housekeeping": (legacy_without_housekeeping, ()),
            "disabled_housekeeping": (disabled_housekeeping, ()),
            "not_applicable_housekeeping": (not_applicable_housekeeping, ()),
            "confirmation_has_been_recorded": (confirmation_has_been_recorded, ()),
            "user_explicitly_selected": (user_explicitly_selected, ()),
            "user_explicitly_chose": (user_explicitly_chose, ()),
        }
        for name, (text, args) in cases.items():
            with self.subTest(name=name):
                completed = self.run_goal(text, *args, name=f"{name}.md")
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_sop_checker_validates_placeholders_inside_fences(self) -> None:
        self.assert_checker_contract(SOP_CHECKER, FIXTURES / "ready_sop.md")

    def test_sop_recovery_contracts_keep_existing_readiness_and_required_fields(self) -> None:
        # Document structure only: model recovery decisions are reviewed separately.
        for fixture in ("ready_sop.md", "ready_sop_with_recovery.md"):
            ready = (FIXTURES / fixture).read_text(encoding="utf-8")
            draft = ready.replace("Status: Ready", "Status: Draft")
            variants = (
                ("ready", ready, (), 0, None),
                ("draft", draft, (), 1, "SOP status must be Ready"),
                ("draft-preview", draft, ("--allow-draft",), 0, None),
                (
                    "missing-actions",
                    re.sub(r"(?ms)^## Allowed Actions\n.*?(?=^## )", "", ready),
                    (), 1, "missing required section: allowed actions",
                ),
                (
                    "missing-validation",
                    re.sub(r"(?ms)^## Validation\n.*?(?=^## )", "", ready),
                    (), 1, "missing required section: validation",
                ),
                (
                    "missing-step-output",
                    re.sub(r"(?ms)^Expected Output:.*?(?=^Failure Handling:)", "", ready, count=1),
                    (), 1, "Step 1 missing required field: expected output",
                ),
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / fixture
                for name, document, args, expected, diagnostic in variants:
                    with self.subTest(fixture=fixture, variant=name):
                        path.write_text(document, encoding="utf-8")
                        result = self.run_checker(SOP_CHECKER, path, *args)
                        self.assertEqual(result.returncode, expected, result.stderr)
                        if diagnostic:
                            self.assertIn(diagnostic, result.stderr)

    def test_sop_checker_enforces_ready_lifecycle_and_step_contract(self) -> None:
        ready = (FIXTURES / "ready_sop.md").read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run(name: str, text: str, *args: str) -> subprocess.CompletedProcess[str]:
                document = root / name
                document.write_text(text, encoding="utf-8")
                return self.run_checker(SOP_CHECKER, document, *args)

            draft = ready.replace("Status: Ready", "Status: Draft")
            draft_default = run("draft-default.md", draft)
            draft_allowed = run("draft-allowed.md", draft, "--allow-draft")
            invalid_status = run(
                "in-progress.md",
                ready.replace("Status: Ready", "Status: In Progress"),
            )
            empty_shell = run(
                "empty-shell.md",
                "Status: Ready\n\n"
                + "\n\n".join(
                    f"## {heading}"
                    for heading in (
                        "Summary",
                        "Trigger",
                        "Preconditions",
                        "Working Directory",
                        "Inputs",
                        "Execution Harness",
                        "Allowed Actions",
                        "Forbidden Actions",
                        "Steps",
                        "Validation",
                        "Output Contract",
                        "Stop Conditions",
                        "Update Rules",
                        "Reuse Prompt",
                    )
                )
                + "\n",
            )
            missing_completion = run(
                "missing-completion.md",
                re.sub(
                    r"(?ms)^Completion Criterion:\n\n.*?(?=^## Validation)",
                    "",
                    ready,
                ),
            )
            fenced_step_text, replacement_count = re.subn(
                r"(?ms)^### Step 1\b.*?(?=^## Validation)",
                "```markdown\n"
                "### Step 1: Fake\n\n"
                "Action:\nRun it.\n\n"
                "Expected Output:\nOutput exists.\n\n"
                "Failure Handling:\nStop.\n\n"
                "Completion Criterion:\nCheck passes.\n"
                "```\n\n",
                ready,
            )
            self.assertEqual(replacement_count, 1)
            fenced_step = run("fenced-step.md", fenced_step_text)
            fenced_values = run(
                "fenced-values.md",
                replace_all(
                    ready,
                    (
                        "Action:\n\nRun the demo command.",
                        "Action:\n\n```bash\nrun-demo\n```",
                    ),
                    (
                        "Expected Output:\n\nThe command exits with status zero.",
                        "Expected Output:\n\n```text\nExit status: 0\n```",
                    ),
                    (
                        "Failure Handling:\n\nStop and report the failing command.",
                        "Failure Handling:\n\n```text\nStop and report the failing command.\n```",
                    ),
                    (
                        "Completion Criterion:\n\nThe zero exit status is recorded in the result.",
                        "Completion Criterion:\n\n```text\nThe zero exit status is recorded.\n```",
                    ),
                ),
            )

        self.assertEqual(draft_default.returncode, 1)
        self.assertIn("SOP status must be Ready; found Draft", draft_default.stderr)
        self.assertEqual(draft_allowed.returncode, 0, draft_allowed.stderr)
        self.assertEqual(invalid_status.returncode, 1)
        self.assertIn(
            "invalid top-level SOP status; expected Draft or Ready; found In Progress",
            invalid_status.stderr,
        )
        self.assertEqual(empty_shell.returncode, 1)
        self.assertIn("required section has no substantive content: summary", empty_shell.stderr)
        self.assertEqual(missing_completion.returncode, 0, missing_completion.stderr)
        self.assertEqual(fenced_step.returncode, 1)
        self.assertIn("steps section must include at least one `### Step` entry", fenced_step.stderr)
        self.assertEqual(fenced_values.returncode, 0, fenced_values.stderr)

    def test_compact_sop_retains_permissions_and_observable_steps(self) -> None:
        ready = (FIXTURES / "ready_sop.md").read_text(encoding="utf-8")
        for heading in ("Summary", "Preconditions", "Working Directory", "Forbidden Actions", "Update Rules", "Reuse Prompt"):
            ready = re.sub(rf"(?ms)^## {heading}\n.*?(?=^## |\Z)", "", ready)
        ready = re.sub(r"(?ms)^Failure Handling:\n.*?(?=^## Validation)", "", ready)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compact.md"
            for variant, expected in (
                (ready, 0),
                (re.sub(r"(?ms)^## Allowed Actions\n.*?(?=^## )", "", ready), 1),
                (re.sub(r"(?ms)^## Stop Conditions\n.*?(?=^## |\Z)", "", ready), 1),
                (re.sub(r"(?ms)^Expected Output:\n.*?(?=^## Validation)", "", ready), 1),
            ):
                with self.subTest(variant=variant):
                    path.write_text(variant, encoding="utf-8")
                    result = self.run_checker(SOP_CHECKER, path)
                    self.assertEqual(result.returncode, expected, result.stderr)

    def test_goal_draft_requires_all_milestones_not_started(self) -> None:
        ready = self.ready
        invalid_draft = ready.replace("Overall status: Ready", "Overall status: Draft")
        valid_draft = replace_all(
            invalid_draft,
            ("| M0 | Ready | Pending | Pending |", "| M0 | Not Started | Pending | Pending |"),
        )

        invalid = self.run_goal(invalid_draft, "--allow-draft", name="invalid-draft.md")
        valid = self.run_goal(valid_draft, "--allow-draft", name="valid-draft.md")

        self.assertEqual(invalid.returncode, 1)
        self.assertIn(
            "overall Draft requires every milestone Not Started/Pending/Pending; found M0",
            invalid.stderr,
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)

    def test_goal_template_marks_only_documentation_examples(self) -> None:
        template = (
            ROOT
            / "skills"
            / "long-running-goal"
            / "templates"
            / "long_running_goal_template.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "```text placeholder-example\nCheckpoint component: <Pending / Done>",
            template,
        )
        self.assertEqual(template.count("placeholder-example"), 1)
        self.assertNotIn("状态：`Not Started`", template)
        self.assertIn("| M0 `<阶段名称>` | Not Started | Pending | Pending |", template)
        self.assertNotIn("状态：`Ready`", template)
        headings = re.findall(r"(?m)^#{2,3}\s+(M\d+)\b", template)
        self.assertEqual(len(headings), len(set(headings)), "template must not define a milestone twice")
        overall = re.findall(r"(?m)^(?:整体状态|目标状态|Overall status|Goal status)[:：]", template)
        self.assertEqual(len(overall), 1, "atomic template must also work as a sequence child")



if __name__ == "__main__":
    unittest.main()
