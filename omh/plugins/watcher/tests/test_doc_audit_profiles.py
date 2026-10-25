from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from watcher_runtime.doc.audit_repo import (  # noqa: E402
    AuditFailure,
    audit_repository,
    render_report,
)
from watcher_runtime.doc.report import (  # noqa: E402
    audit_repo_from_config,
    run_generate_report,
)


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def initialize_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    run(["git", "init"], repo)
    run(["git", "config", "user.email", "test@example.com"], repo)
    run(["git", "config", "user.name", "Test User"], repo)
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    run(["git", "add", "README.md"], repo)
    run(["git", "commit", "-m", "init"], repo)
    return repo


class WatcherDocAuditProfileTests(unittest.TestCase):
    def test_default_discovery_includes_dev_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            dev_docs = repo / "dev_docs"
            dev_docs.mkdir()
            (dev_docs / "README.md").write_text("# Current docs\n", encoding="utf-8")

            result = audit_repository(repo=repo, name="demo")

        self.assertIn("dev_docs/README.md", result["doc_files"])

    def test_default_skill_root_prefers_agents_and_reports_shadowed_codex(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            agents_skill = repo / ".agents" / "skills" / "current"
            codex_skill = repo / ".codex" / "skills" / "legacy"
            agents_skill.mkdir(parents=True)
            codex_skill.mkdir(parents=True)
            (agents_skill / "SKILL.md").write_text("# Current\n", encoding="utf-8")
            (codex_skill / "SKILL.md").write_text("# Legacy\n", encoding="utf-8")

            result = audit_repository(repo=repo, name="demo")

        self.assertEqual(result["skill_root"]["selected"], ".agents/skills")
        self.assertEqual(result["skill_root"]["shadowed"], [".codex/skills"])
        self.assertIn(".agents/skills/current/SKILL.md", result["doc_files"])
        self.assertNotIn(".codex/skills/legacy/SKILL.md", result["doc_files"])
        self.assertIn(
            "Additional repository skill roots are shadowed",
            [finding["title"] for finding in result["findings"]],
        )

    def test_empty_agents_parent_does_not_shadow_codex_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            (repo / ".agents").mkdir()
            codex_skill = repo / ".codex" / "skills" / "legacy"
            codex_skill.mkdir(parents=True)
            (codex_skill / "SKILL.md").write_text("# Legacy\n", encoding="utf-8")

            result = audit_repository(repo=repo, name="demo")

        self.assertEqual(result["skill_root"]["selected"], ".codex/skills")
        self.assertIn(".codex/skills/legacy/SKILL.md", result["doc_files"])

    def test_repo_skills_token_resolves_docs_and_authority_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            skill_root = repo / ".agents" / "skills"
            skill_root.mkdir(parents=True)
            (skill_root / "README.md").write_text("# Skills\n", encoding="utf-8")

            result = audit_repository(
                repo=repo,
                name="demo-current",
                docs=["@repo-skills"],
                authority_paths=["@repo-skills/README.md"],
            )

        self.assertEqual(result["skill_root"]["selected"], ".agents/skills")
        self.assertIn(".agents/skills/README.md", result["doc_files"])
        self.assertEqual(
            result["authority_paths"][0]["resolved_path"],
            ".agents/skills/README.md",
        )
        self.assertTrue(result["authority_paths"][0]["exists"])

    def test_repo_skills_token_is_fail_closed_when_no_root_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))

            result = audit_repository(
                repo=repo,
                name="demo-current",
                docs=["@repo-skills"],
                authority_paths=["@repo-skills/README.md"],
            )

        self.assertEqual(
            [finding["title"] for finding in result["findings"]],
            [
                "Configured documentation path is missing",
                "Configured authority path is missing",
            ],
        )

    def test_skill_root_candidate_cannot_escape_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))

            with self.assertRaisesRegex(
                AuditFailure, "skill root candidate must stay relative to the repo"
            ):
                audit_repository(
                    repo=repo,
                    name="demo-current",
                    skill_root_candidates=["../shared-skills"],
                )

    def test_explicit_stale_skill_path_does_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            skill_root = repo / ".agents" / "skills"
            skill_root.mkdir(parents=True)
            (skill_root / "README.md").write_text("# Skills\n", encoding="utf-8")

            result = audit_repository(
                repo=repo,
                name="demo-current",
                docs=[".codex/skills"],
            )

        self.assertEqual(result["skill_root"]["selected"], ".agents/skills")
        self.assertEqual(
            result["findings"][0]["title"],
            "Configured documentation path is missing",
        )
        self.assertEqual(result["findings"][0]["evidence"], ".codex/skills")

    def test_selected_skill_root_classifies_scripts_as_doc_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            skill_root = repo / ".agents" / "skills" / "demo" / "scripts"
            skill_root.mkdir(parents=True)
            (skill_root / "check.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            run(["git", "add", ".agents/skills/demo/scripts/check.sh"], repo)
            run(["git", "commit", "-m", "add skill script"], repo)

            result = audit_repository(repo=repo, name="demo")
            report = render_report(result)

        self.assertNotIn(
            "Recent code or runtime changes have no matching doc changes",
            [finding["title"] for finding in result["findings"]],
        )
        self.assertIn("- Changed doc files: 1", report)

    def test_profile_can_override_skill_root_candidate_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            agents_skill = repo / ".agents" / "skills" / "agents"
            grok_skill = repo / ".grok" / "skills" / "grok"
            agents_skill.mkdir(parents=True)
            grok_skill.mkdir(parents=True)
            (agents_skill / "SKILL.md").write_text("# Agents\n", encoding="utf-8")
            (grok_skill / "SKILL.md").write_text("# Grok\n", encoding="utf-8")

            result = audit_repo_from_config(
                {
                    "name": "demo-current",
                    "path": str(repo),
                    "docs": ["@repo-skills"],
                    "skill_root_candidates": [
                        ".grok/skills",
                        ".agents/skills",
                    ],
                }
            )

        self.assertEqual(result["skill_root"]["selected"], ".grok/skills")
        self.assertIn(".grok/skills/grok/SKILL.md", result["doc_files"])
        self.assertNotIn(".agents/skills/agents/SKILL.md", result["doc_files"])

    def test_owner_command_profile_skips_generic_markdown_link_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            source = repo / "docs" / "source"
            source.mkdir(parents=True)
            (source / "index.md").write_text(
                "[Theme asset](/images/example.png)\n", encoding="utf-8"
            )

            result = audit_repository(
                repo=repo,
                name="demo-upstream",
                profile="upstream-site",
                docs=["docs/source"],
                link_validation={
                    "mode": "owner-command",
                    "command": [sys.executable, "-c", "raise SystemExit(0)"],
                    "cwd": ".",
                },
                check_change_alignment=False,
            )

        self.assertEqual(result["broken_links"], [])
        self.assertEqual(result["link_validation"]["status"], "passed")
        self.assertEqual(result["findings"], [])

    def test_owner_command_failure_is_classified_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))

            result = audit_repository(
                repo=repo,
                name="demo-upstream",
                profile="upstream-site",
                docs=["README.md"],
                link_validation={
                    "mode": "owner-command",
                    "command": [sys.executable, "-c", "raise SystemExit(7)"],
                    "cwd": ".",
                },
                check_change_alignment=False,
            )

        self.assertEqual(result["link_validation"]["status"], "failed")
        self.assertEqual(result["findings"][0]["classification"], "owner-validator")
        self.assertIn("### Owner Validator", render_report(result))

    def test_history_profile_keeps_findings_report_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))
            archive = repo / "dev_docs" / "archive"
            archive.mkdir(parents=True)
            (archive / "old.md").write_text("[Missing](gone.md)\n", encoding="utf-8")

            result = audit_repository(
                repo=repo,
                name="demo-history",
                profile="history",
                docs=["dev_docs/archive"],
                finding_policy="report-only",
                check_change_alignment=False,
            )

        self.assertEqual(result["findings"][0]["classification"], "report-only")
        self.assertIn("### Report-Only", render_report(result))

    def test_authority_paths_are_presence_checks_and_missing_path_is_actionable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = initialize_repo(Path(tmp))

            result = audit_repository(
                repo=repo,
                name="demo-current",
                profile="current-authority",
                docs=["README.md"],
                authority_paths=["README.md", "dev_docs/current.md"],
            )
            report = render_report(result)

        self.assertEqual(result["authority_paths"][0]["kind"], "file")
        self.assertEqual(result["authority_paths"][1]["kind"], "missing")
        self.assertEqual(
            result["findings"][0]["title"], "Configured authority path is missing"
        )
        self.assertIn("Configured Authority Path Presence", report)
        self.assertIn("does not prove semantic equality", report)

    def test_report_rejects_duplicate_repo_profile_names_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = initialize_repo(root)
            config_path = root / "repos.json"
            state_dir = root / "state"
            output_path = root / "report.md"
            config_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "demo-current",
                                "path": str(repo),
                                "docs": ["README.md"],
                            },
                            {
                                "name": "demo-current",
                                "path": str(repo),
                                "docs": ["README.md"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                AuditFailure, "duplicate repo/profile name: demo-current"
            ):
                run_generate_report(
                    config_path=config_path,
                    state_dir=state_dir,
                    mark_audited=True,
                    output_path=output_path,
                )

            self.assertFalse(output_path.exists())
            self.assertFalse((state_dir / "repo-state.json").exists())


if __name__ == "__main__":
    unittest.main()
