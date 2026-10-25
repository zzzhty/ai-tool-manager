from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "long-running-goal"
SKILL = SKILL_DIR / "SKILL.md"
REFERENCES = {
    "create": SKILL_DIR / "references" / "create-and-loop.md",
    "sequence": SKILL_DIR / "references" / "sequence-child-goals.md",
    "cutover": SKILL_DIR / "references" / "production-cutover.md",
    "execute": SKILL_DIR / "references" / "execute-and-close.md",
    "close": SKILL_DIR / "references" / "close.md",
}
PREFLIGHT = SKILL_DIR / "components" / "planning-preflight.md"
ATOMIC_TEMPLATE = SKILL_DIR / "templates" / "long_running_goal_template.md"
SEQUENCE_TEMPLATE = SKILL_DIR / "templates" / "long_running_goal_sequence_template.md"
WATCHER = SKILL_DIR.parents[1] / ".codex-plugin" / "skill-watcher.json"
sys.path.insert(0, str(SKILL_DIR.parents[1] / "scripts"))

from markdown_contract import missing_relative_links  # noqa: E402


class LongRunningGoalDisclosureTests(unittest.TestCase):
    def test_entry_interface_keeps_lifecycle_authority_and_goal_tool_contracts(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        # Disclosure checks locate guardrails; semantic equivalence needs review.
        for semantic in (
            "Only `Ready` pre-approves frozen non-destructive local work",
            "keep a goal `Draft`",
            "explicit request naming this skill or one of its lifecycle actions",
            "task size or duration alone is not a trigger",
            "Otherwise use system planning",
            "suggesting this skill does not authorize creating its contract",
            "Explicit pause, stop, redirect or scope change overrides every continuation case",
            "without milestone commands, goal-evidence edits or native goal-status updates",
            "The third runtime-reported native Goal failure reaches the native Codex Goal hard stop",
            "Ask only at a runtime hard stop",
            "Never infer cleanup consent",
            "Use native goal tools only on an explicit active-conversation request",
            "check_goal_ready.py [--allow-draft] <goal-file>",
        ):
            self.assertIn(semantic, text)
        create = REFERENCES["create"].read_text(encoding="utf-8")
        for semantic in (
            "non-executable `Draft` with known facts and unresolved decisions",
            "never invent design or authority",
            "Templates and readiness checkers own field shape and structural completeness",
        ):
            self.assertIn(semantic, create)

    def test_adaptive_recovery_preserves_native_stop_and_authority_boundaries(self) -> None:
        # Instruction-contract regressions, not a simulation of native Goal counting.
        skill = SKILL.read_text(encoding="utf-8")
        execute = REFERENCES["execute"].read_text(encoding="utf-8")
        for clause in (
            "After the first runtime-reported native Goal failure:", "After the second runtime-reported native Goal failure:",
            "At the third runtime-reported native Goal failure/stop:", "Once that native boundary occurs, do not launch another recovery attempt",
            "Keep the first two recoverable native Goal failures `In Progress`",
            "Three ordinary failed commands alone do not establish this boundary",
            "if its count is unavailable", "not automatically one native Goal failure",
            "not a new ledger or mandatory schema", "Read it on resume",
            "cause has changed", "stops the affected action immediately",
            "without pointless attempts", "do not skip a child",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, execute)
        self.assertIn("neither implements a second counter", skill)
        self.assertIn("Native stop signals take precedence", skill)
        self.assertNotIn("at least three attempts or distinct approaches", skill)
        for template in (ATOMIC_TEMPLATE, SEQUENCE_TEMPLATE):
            self.assertIn("adaptive recovery", template.read_text(encoding="utf-8"))
        self.assertIn("first two recoverable native Goal failures do not block", REFERENCES["sequence"].read_text(encoding="utf-8"))

    def test_each_conditional_branch_has_a_strong_pointer_and_completion_criterion(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")

        for relative_path in (
            "references/create-and-loop.md",
            "references/sequence-child-goals.md",
            "references/production-cutover.md",
            "references/execute-and-close.md",
            "references/close.md",
        ):
            self.assertIn(relative_path, skill)
        for trigger in (
            "Create/upgrade",
            "Loop-shaped",
            "Sequence Child Goals",
            "Production cutover",
            "Execute, resume, continue, advance or evolve",
            "Enter Close",
        ):
            self.assertIn(trigger, skill)
        for reference in REFERENCES.values():
            text = reference.read_text(encoding="utf-8")
            self.assertIn("Completion criterion:", text)

        create = REFERENCES["create"].read_text(encoding="utf-8")
        self.assertIn("Trigger:", create)
        self.assertIn("Connector read/write boundaries:", create)
        execute = REFERENCES["execute"].read_text(encoding="utf-8")
        self.assertIn("Apply `../components/checkpoint.md`", execute)
        close = REFERENCES["close"].read_text(encoding="utf-8")
        self.assertIn("[close.md](close.md)", execute)
        self.assertIn("Remove closed goals from active navigation", close)
        self.assertIn("readiness and authorization checks in `execute-and-close.md`", close)
        self.assertIn("For direct or resumed Close, apply the matching", close)
        self.assertIn("recorded-root binding rule before any producer writes", close)
        self.assertIn("[the checkpoint component](../components/checkpoint.md) in full", close)
        self.assertLess(close.index("../components/checkpoint.md"), close.index("set the Close row to"))
        cutover = REFERENCES["cutover"].read_text(encoding="utf-8")
        self.assertIn("default/full-shadow/production comparison matrix", cutover)

    def test_sequence_branch_discloses_canonical_contract_and_aliases(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        reference = REFERENCES["sequence"].read_text(encoding="utf-8")
        template = SEQUENCE_TEMPLATE.read_text(encoding="utf-8")
        watcher = json.loads(WATCHER.read_text(encoding="utf-8"))

        self.assertIn(
            "scripts/check_goal_sequence.py <sequence-file> [--allow-draft]",
            skill,
        )
        self.assertIn("Long-Running Goal Sequence", reference)
        self.assertIn("one active harness system goal", reference)
        self.assertIn("Completion criterion:", reference)
        self.assertIn("exact marker, status, and source", reference)
        self.assertIn("never returns to `Ready` for a per-child authorization", reference)

        self.assertIn("Promotion policy: `automatic-after-close`", template)
        self.assertIn("## Child Preflight Register", template)
        self.assertIn("| Child ID | Marker | Status | Source |", template)
        self.assertIn("## Child Execution Register", template)
        self.assertIn(
            "| Order | Child ID | Parent milestone | Live goal | Closeout evidence | Depends on | State | Current milestone | Close revision |",
            template,
        )
        self.assertIn("sole child current-state authority", template)
        self.assertIn("Transition evidence is historical", template)
        resume = template.split("## Reusable Resume Prompt", 1)[1].split(
            "## Related Documents", 1
        )[0]
        self.assertIn("Child Execution Register", resume)
        self.assertNotIn("<child-a>", resume)
        self.assertNotIn("<child-b>", resume)

        aliases = {
            item["value"]
            for item in watcher["skills"]["workflow:long-running-goal"]["aliases"]
        }
        self.assertIn("long-running goal sequence", aliases)
        self.assertIn("umbrella long-running goal", aliases)

    def test_sequence_template_link_examples_are_inert_until_instantiated(self) -> None:
        template = SEQUENCE_TEMPLATE.read_text(encoding="utf-8")

        self.assertEqual(missing_relative_links(SEQUENCE_TEMPLATE), [])
        self.assertIn(
            "Use relative Markdown links, replacing the backticked examples with actual links",
            template,
        )
        self.assertIn(
            "`[<child-a>](./<child-a>_long_running_goal_plan.md)`",
            template,
        )

    def test_task_temporary_cache_policy_is_explicit_cross_platform_and_bounded(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        execute = REFERENCES["execute"].read_text(encoding="utf-8")
        sequence = REFERENCES["sequence"].read_text(encoding="utf-8")
        atomic_template = ATOMIC_TEMPLATE.read_text(encoding="utf-8")
        sequence_template = SEQUENCE_TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("Temporary-cache housekeeping uses only preflight's recorded policy and owner paths", skill)
        self.assertIn("Close housekeeping policy", preflight)
        self.assertIn("host platform or runtime's standard temporary-directory resolver", preflight)
        self.assertIn("Default to `Disabled`", preflight)
        self.assertIn("not unconditional recursive deletion", preflight)
        close = REFERENCES["close"].read_text(encoding="utf-8")
        self.assertIn("If `watcher:housekeeping` is unavailable", close)
        self.assertIn("Before any command may write task-temporary data", execute)
        self.assertIn("bind every task-temporary producer", execute)
        self.assertIn("missing legacy field", close)
        self.assertIn("never inherits, widens, or overrides a child's policy", sequence)

        for template in (atomic_template, sequence_template):
            self.assertIn("## Task Temporary Cache / Housekeeping", template)
            self.assertIn("Close housekeeping policy", template)
            self.assertIn("Housekeeping decision source", template)
            self.assertIn("Task temporary cache root strategy", template)
            self.assertIn("Recorded task temporary cache roots", template)
            self.assertIn("Housekeeping boundary", template)
            self.assertIn("watcher:housekeeping", template)

        self.assertIn("every child records and honors its own policy", sequence_template)
        self.assertNotIn("| Housekeeping |", sequence_template)

    def test_preflight_reuses_decisions_and_keeps_estimates_optional(self) -> None:
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("Reuse confirmed answers", preflight)
        self.assertIn("no distribution, fixed sentinel, or driver count is required", preflight)
        self.assertIn("Skip never supplies missing authority", preflight)
        for template in (ATOMIC_TEMPLATE, SEQUENCE_TEMPLATE):
            text = template.read_text(encoding="utf-8")
            self.assertIn("existing decisions", text)
            for field in ("Preflight evidence", "Authorization evidence", "Deferral basis"):
                self.assertIn(field, text)
            self.assertNotIn("Assessment mode", text)
            self.assertNotIn("Critical-path time-cost distribution", text)
        self.assertIn("Change a reusable skill or template only when source mutation is authorized", REFERENCES["execute"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
