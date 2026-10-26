from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKFLOW_ROOT.parents[1]
AGENTS = REPO_ROOT / "AGENTS.md"
GLOBAL_INSTRUCTIONS = REPO_ROOT / "agents" / "global-instructions.md"
SUPPORT = REPO_ROOT / "agents" / "operating-principles.md"
IDENTIFIER_POLICY = REPO_ROOT / "docs" / "agents" / "internal-identifier-evolution.md"
ORCHESTRATE = WORKFLOW_ROOT / "skills" / "orchestrate-subagents" / "SKILL.md"
ORCHESTRATE_REFERENCES = ORCHESTRATE.parent / "references"


class InstructionOwnershipTests(unittest.TestCase):
    def test_global_and_repository_instruction_owners_are_split(self) -> None:
        root = AGENTS.read_text(encoding="utf-8")
        global_instructions = GLOBAL_INSTRUCTIONS.read_text(encoding="utf-8")
        support = SUPPORT.read_text(encoding="utf-8")
        identifier_policy = IDENTIFIER_POLICY.read_text(encoding="utf-8")

        for semantic in (
            "Surface failures directly",
            "Keep tests focused on behavioral red lines",
            "Use subagents only when",
            "Treat subagent failures as first-class failures",
        ):
            self.assertIn(semantic, global_instructions)
            self.assertNotIn(semantic, root)

        self.assertIn("`agents/global-instructions.md` owns global authority", support)
        self.assertIn("owns only repository-local routing", root)
        self.assertIn("docs/agents/internal-identifier-evolution.md", root)
        self.assertIn("Classify every scoped match before editing", identifier_policy)
        self.assertIn("Completion requires every inventoried current consumer", identifier_policy)
        self.assertIn("Reusable workflow behavior", support)
        self.assertIn("does not invoke `$orchestrate-subagents` by itself", support)
        self.assertIn("scripts/sync_codex_agents.py", support)
        self.assertIn("preserve the user-visible local time", support)
        self.assertIn("verify the written automation state", support)
        self.assertIn("Do not write secrets, full private prompts, full tool responses", support)
        self.assertIn("Memory updates must remain reviewable", support)

    def test_active_assignment_docs_do_not_claim_unavailable_roles_or_old_recipe(self) -> None:
        active_docs = (
            AGENTS,
            GLOBAL_INSTRUCTIONS,
            SUPPORT,
            REPO_ROOT / "README.md",
            REPO_ROOT / "docs" / "codex-agent-support.md",
            REPO_ROOT / "docs" / "todo" / "subagent-orchestration-follow-up.md",
            ORCHESTRATE,
        )
        for path in active_docs:
            text = path.read_text(encoding="utf-8")
            for stale in (
                "built-in roles",
                "assignment labels",
                "`explorer`",
                "`worker`",
                "subagent-recipes.md",
            ):
                with self.subTest(path=path, stale=stale):
                    self.assertNotIn(stale, text)

    def test_orchestrate_routes_to_one_task_pattern_owner(self) -> None:
        skill = ORCHESTRATE.read_text(encoding="utf-8")
        references = list(ORCHESTRATE_REFERENCES.glob("*.md"))
        self.assertEqual([path.name for path in references], ["task-patterns.md"])
        self.assertIn("references/task-patterns.md", skill)
        patterns = references[0].read_text(encoding="utf-8")
        for task in ("PR or branch review", "Debugging triage", "Implementation planning", "Parallel implementation", "API/schema inspection", "Documentation alignment"):
            self.assertIn(task, patterns)
        for boundary in ("ban on edits and commits", "exact disjoint write scope", "shared and forbidden paths", "stopping condition", "parent independently reviewed", "partial"):
            self.assertIn(boundary, skill)
        self.assertNotIn("exactly one primary reference", skill)

    def test_global_authority_and_local_workflow_delta_are_both_reachable(self) -> None:
        global_instructions = GLOBAL_INSTRUCTIONS.read_text(encoding="utf-8")
        skill = ORCHESTRATE.read_text(encoding="utf-8")

        self.assertIn("Use subagents only when", global_instructions)
        self.assertIn("explicitly asks", skill)
        self.assertIn("active instruction chain or an approved plan", skill)
        self.assertNotIn("root instructions or an approved plan", skill)
        self.assertIn("exact disjoint write scope", skill)
        self.assertIn("Surface missing tools", skill)


if __name__ == "__main__":
    unittest.main()
