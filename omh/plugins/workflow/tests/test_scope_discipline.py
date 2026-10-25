from __future__ import annotations

import json
import unittest
from pathlib import Path


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
SCOPE_ROOT = WORKFLOW_ROOT / "skills" / "scope-discipline"
LONG_RUNNING_ROOT = WORKFLOW_ROOT / "skills" / "long-running-goal"
SCOPE_SKILL = SCOPE_ROOT / "SKILL.md"
NECESSITY_GATE = SCOPE_ROOT / "references" / "necessity-gate.md"
MILESTONE_GATE = LONG_RUNNING_ROOT / "components" / "milestone-scope-gate.md"
EXECUTE = LONG_RUNNING_ROOT / "references" / "execute-and-close.md"
WATCHER = WORKFLOW_ROOT / ".codex-plugin" / "skill-watcher.json"


class ScopeDisciplineTests(unittest.TestCase):
    def test_callable_skill_is_explicit_only_and_keeps_the_smallest_correct_result(self) -> None:
        skill = SCOPE_SKILL.read_text(encoding="utf-8")
        metadata = (SCOPE_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("user explicitly invokes `scope-discipline`", skill)
        self.assertIn("Ordinary coding", skill)
        self.assertIn("not itself a trigger", skill)
        self.assertIn("smallest correct result", skill)
        self.assertIn("references/necessity-gate.md", skill)
        self.assertIn("allow_implicit_invocation: false", metadata)
        self.assertIn("necessary consequences", metadata)

    def test_shared_necessity_gate_routes_expansion_without_fixed_budgets(self) -> None:
        gate = NECESSITY_GATE.read_text(encoding="utf-8")

        for semantic in (
            "already requested or authorized",
            "necessary consequence",
            "reachable code, data, caller, test, deployment state",
            "Would omitting it",
            "Later-stage or separately owned work",
            "Speculative expansion",
            "Semantic conflict",
            "Do not use fixed limits on files, lines, tests, tool calls, agents, or elapsed time",
            "Do not repeat a search, test, review, or audit with no new oracle",
        ):
            self.assertIn(semantic, gate)

    def test_long_running_goal_uses_a_stage_adapter_without_duplicating_goal_fields(self) -> None:
        skill = (LONG_RUNNING_ROOT / "SKILL.md").read_text(encoding="utf-8")
        execute = EXECUTE.read_text(encoding="utf-8")
        component = MILESTONE_GATE.read_text(encoding="utf-8")
        atomic_template = (
            LONG_RUNNING_ROOT / "templates" / "long_running_goal_template.md"
        ).read_text(encoding="utf-8")
        sequence_template = (
            LONG_RUNNING_ROOT / "templates" / "long_running_goal_sequence_template.md"
        ).read_text(encoding="utf-8")
        templates = (
            atomic_template,
            sequence_template,
        )

        self.assertIn("components/milestone-scope-gate.md", skill)
        self.assertIn("At each milestone entry", execute)
        self.assertIn("before material scope or validation expansion", execute)
        self.assertIn("milestone-scope exit gate", execute)
        self.assertLess(
            execute.index("Apply `../components/checkpoint.md`"),
            execute.index("Confirm the milestone-scope exit gate"),
        )
        self.assertIn("../../scope-discipline/references/necessity-gate.md", component)
        self.assertIn(
            "The checkpoint component has already recorded its evidence",
            component,
        )
        self.assertIn("later milestone work", component)
        self.assertIn("without another final scope audit", component)
        self.assertNotIn("## Decision Routing", component)

        self.assertIn("components/milestone-scope-gate.md", atomic_template)
        self.assertIn("components/milestone-scope-gate.md", sequence_template)

        for text in templates:
            self.assertNotIn("Scope budget", text)
            self.assertNotIn("Validation budget", text)
            self.assertNotIn("Maximum tool count", text)

    def test_watcher_records_scope_discipline_without_static_lrg_dependency(self) -> None:
        watcher = json.loads(WATCHER.read_text(encoding="utf-8"))
        scope = watcher["skills"]["workflow:scope-discipline"]
        long_running = watcher["skills"]["workflow:long-running-goal"]

        self.assertEqual(scope["role"], "discipline")
        self.assertEqual(scope["logical_group"], "explicit-workflows")
        self.assertEqual(scope["supporting_skills"], [])
        self.assertEqual(long_running["supporting_skills"], [])
        aliases = {item["value"] for item in scope["aliases"]}
        self.assertEqual(
            aliases,
            {"workflow:scope-discipline", "scope-discipline", "scope discipline"},
        )

    def test_third_party_design_attribution_is_preserved(self) -> None:
        notice = (SCOPE_ROOT / "NOTICE.md").read_text(encoding="utf-8")

        self.assertIn("Stop That Shit", notice)
        self.assertIn("MIT License", notice)
        self.assertIn("Copyright (c) 2026 Stop That Shit contributors", notice)


if __name__ == "__main__":
    unittest.main()
