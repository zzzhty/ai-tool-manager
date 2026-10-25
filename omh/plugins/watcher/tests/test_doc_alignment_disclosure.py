from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "doc-alignment"
SKILL = SKILL_DIR / "SKILL.md"
ALIGNMENT = SKILL_DIR / "references" / "alignment-reference.md"
WATCHER_AUDIT = SKILL_DIR / "references" / "watcher-audit.md"
WATCHER = SKILL_DIR.parents[1] / ".codex-plugin" / "skill-watcher.json"
WATCHER_README = SKILL_DIR.parents[1] / "README.md"
WATCHER_SKILLS = SKILL_DIR.parent
MAINTAINER = WATCHER_SKILLS / "skill-maintainer" / "SKILL.md"
MAINTAINER_REFERENCES = WATCHER_SKILLS / "skill-maintainer" / "references"
COMPRESSOR = WATCHER_SKILLS / "skill-compressor" / "SKILL.md"
HOUSEKEEPING = WATCHER_SKILLS / "housekeeping" / "SKILL.md"


class DocAlignmentDisclosureTests(unittest.TestCase):
    def test_entry_interface_keeps_mode_safety_and_one_level_pointers(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn(
            "In implementation mode, update every active path",
            text,
        )
        self.assertIn(
            "In report-only and scheduled modes, inventory drift, collect evidence, "
            "propose bounded fixes",
            text,
        )
        self.assertIn("under `$CODEX_HOME/watcher/doc/` or an explicit output path", text)
        self.assertIn("target repositories remain read-only", text)
        self.assertIn(
            "run only non-mutating commands against target repositories",
            text,
        )
        self.assertIn(
            "The only permitted writes are Watcher-owned report or runtime state",
            text,
        )
        self.assertIn("Only implementation mode repairs root causes", text)
        self.assertIn("Use implementation mode when the user asks", text)
        self.assertIn("references/watcher-audit.md", text)
        self.assertIn("references/alignment-reference.md", text)
        self.assertIn("unresolved target drift does not prevent completing the audit", text)
        self.assertIn("Leave target repositories unchanged", text)

    def test_watcher_audit_reference_is_complete_for_operations_branch(self) -> None:
        text = WATCHER_AUDIT.read_text(encoding="utf-8")

        self.assertIn("Trigger:", text)
        self.assertIn("scripts/watcher doc doctor", text)
        self.assertIn("scripts/watcher doc commit-counter", text)
        self.assertIn("scripts/watcher doc report", text)
        self.assertIn("scripts/watcher doc audit", text)
        self.assertIn("owner-command", text)
        self.assertIn("authority_paths", text)
        self.assertIn("commit-dependent", text)
        self.assertIn("Completion criterion:", text)
        routing = text.split("## Select The Evidence Branch", 1)[1].split("## Fresh Audit", 1)[0]
        self.assertIn("no fresh audit was requested", routing)
        self.assertIn("do not generate or run fresh audit commands", routing)
        completion = text.split("Completion criterion:", 1)[1]
        review, fresh = completion.split("**Fresh audit:**", 1)
        self.assertIn("report source, applicability, findings, and coverage gaps", review)
        self.assertIn("No new doctor or audit run is required", review)
        self.assertIn("doctor and the selected audit/report command", fresh)
        self.assertIn("exact failures", fresh)

    def test_alignment_reference_owns_classification_surfaces_and_validation(self) -> None:
        text = ALIGNMENT.read_text(encoding="utf-8")

        for role in (
            "**Overview**",
            "**Guide**",
            "**Architecture / Contract**",
            "**Archive**",
            "**Script / Runner**",
            "**Skill**",
        ):
            self.assertIn(role, text)
        for severity in ("`High`", "`Medium`", "`Low`"):
            self.assertIn(severity, text)
        for semantic in (
            "runtime checks: `check_<target>`",
            "Root docs are current overview and execution entry points only",
            "Active index files are navigation and execution posture",
            "Preserve the target skill's current invocation mode",
            "For a model-invoked skill",
            "For a user-invoked skill",
            "preserve `disable-model-invocation: true`",
            "human-facing one-line summary",
            "Match validation to the changed surface",
        ):
            self.assertIn(semantic, text)
        self.assertNotIn("compileall", text)
        self.assertIn('omh_tooling_python="${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}/venv/bin/python"', text)
        self.assertNotRegex(text, r'"\$omh_tooling_python" (?!-B\b)')
        self.assertIn('compile(source.read_bytes(), str(source), "exec")', text)
        self.assertIn("In report-only mode, use the alignment rules as audit criteria", text)

    def test_documented_python_syntax_check_does_not_write_bytecode(self) -> None:
        text = ALIGNMENT.read_text(encoding="utf-8")
        match = re.search(
            r'"\$omh_tooling_python" -B - <<\'PY\'\n(?P<program>.*?)\nPY',
            text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "scripts" / "watcher_runtime"
            package.mkdir(parents=True)
            source = package / "example.py"
            source.write_text("value = 1\n", encoding="utf-8")
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            completed = subprocess.run(
                [sys.executable, "-c", match.group("program")],
                cwd=root,
                capture_output=True,
                check=False,
                text=True,
            )
            after = sorted(path.relative_to(root) for path in root.rglob("*"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(after, before)

    def test_watcher_entry_with_documented_no_bytecode_flag_writes_no_cache(self) -> None:
        alignment = ALIGNMENT.read_text(encoding="utf-8")
        audit = WATCHER_AUDIT.read_text(encoding="utf-8")
        self.assertIn('"$omh_tooling_python" -B scripts/watcher', alignment)
        self.assertNotRegex(audit, r'"\$omh_tooling_python" (?!-B\b)')

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(SKILL_DIR.parents[1] / "scripts" / "watcher", scripts / "watcher")
            shutil.copytree(
                SKILL_DIR.parents[1] / "scripts" / "watcher_runtime",
                scripts / "watcher_runtime",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            completed = subprocess.run(
                [sys.executable, "-B", str(scripts / "watcher"), "--help"],
                cwd=root,
                capture_output=True,
                check=False,
                text=True,
            )
            cache_paths = [
                path for path in root.rglob("*") if path.name == "__pycache__" or path.suffix == ".pyc"
            ]

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(cache_paths, [])

    def test_callable_and_watcher_identities_remain_unchanged(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        watcher = json.loads(WATCHER.read_text(encoding="utf-8"))

        self.assertIn("name: doc-alignment", skill)
        self.assertNotIn("disable-model-invocation", skill)
        self.assertIn("watcher:doc-alignment", watcher["skills"])
        aliases = {
            item["value"]
            for item in watcher["skills"]["watcher:doc-alignment"]["aliases"]
        }
        self.assertIn("doc-alignment", aliases)
        self.assertIn("documentation alignment", aliases)


class WatcherSkillInstructionContractTests(unittest.TestCase):
    def test_skill_maintainer_completion_is_reviewable_and_source_preserving(self) -> None:
        skill = MAINTAINER.read_text(encoding="utf-8")

        for requirement in (
            "target skill",
            "evidence window and event counts",
            "snapshot and proposal paths",
            "exact bounded edit or explicit no-change decision",
            "validation commands and results",
            "human-review boundary",
            "blockers and assumptions",
            "source `SKILL.md` remained unchanged",
        ):
            self.assertIn(requirement, skill)
        self.assertIn("separate candidate path", skill)
        self.assertIn("validation as pending", skill)
        self.assertIn("## Candidate Validation", skill)
        self.assertIn("route candidates that change invocation", skill.casefold())
        self.assertFalse((MAINTAINER_REFERENCES / "patch-policy.md").exists())
        self.assertFalse((MAINTAINER_REFERENCES / "validation-policy.md").exists())

    def test_skill_compressor_delegates_meaning_changes_to_one_review_owner(self) -> None:
        text = COMPRESSOR.read_text(encoding="utf-8")

        self.assertIn("stop this behavior-preserving workflow", text)
        self.assertIn("route the candidate through `workflow:prompt-strategy-loop`", text)
        self.assertIn("Core Rule is the single owner", text)
        self.assertIn("keep the candidate explicitly unverified", text)
        self.assertIn("Before mutation, ensure a recoverable baseline", text)
        self.assertIn("may continue without creating a backup", text)
        self.assertIn("plugin guidance", text.split("---", 2)[1])
        self.assertIn("freeze this affected-meaning inventory as the equivalence oracle", text)
        self.assertNotIn("independent evaluation is required when compression changes", text)

    def test_watcher_skills_keep_distinct_seams_and_ui_metadata(self) -> None:
        housekeeping = HOUSEKEEPING.read_text(encoding="utf-8")
        maintainer = MAINTAINER.read_text(encoding="utf-8")
        readme = WATCHER_README.read_text(encoding="utf-8")
        self.assertIn("removal of physical disposable artifacts", housekeeping)
        self.assertIn("Keep it unchanged in this workflow", housekeeping)
        self.assertNotIn("Repair active semantic drift", housekeeping)
        self.assertIn("/venv/bin/python -B", maintainer)
        self.assertIn('"$omh_tooling_python" -B scripts/watcher', readme)

        watcher = json.loads(WATCHER.read_text(encoding="utf-8"))
        housekeeping_metadata = watcher["skills"]["watcher:housekeeping"]
        self.assertEqual(housekeeping_metadata["supporting_skills"], [])
        housekeeping_aliases = {
            alias["value"] for alias in housekeeping_metadata["aliases"]
        }
        for generic_alias in ("cleanup", "clean up", "repo cleanup"):
            self.assertNotIn(generic_alias, housekeeping_aliases)
        self.assertIn("remove disposable artifacts", housekeeping_aliases)
        self.assertIn("clear generated caches", housekeeping_aliases)

        doc_alignment_metadata = (
            WATCHER_SKILLS / "doc-alignment" / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("report-only audit mode", doc_alignment_metadata)
        self.assertIn("Do not modify target files", doc_alignment_metadata)

        for skill_name in (
            "doc-alignment",
            "housekeeping",
            "skill-compressor",
            "skill-maintainer",
        ):
            metadata = WATCHER_SKILLS / skill_name / "agents" / "openai.yaml"
            self.assertTrue(metadata.is_file(), metadata)
            self.assertIn(f"${skill_name}", metadata.read_text(encoding="utf-8"))

    @unittest.skipIf(os.name == "nt", "POSIX Bash housekeeping example")
    def test_housekeeping_inventory_example_is_executable_bounded_and_read_only(self) -> None:
        text = HOUSEKEEPING.read_text(encoding="utf-8")
        match = re.search(r"```bash\n(?P<script>.*?)\n```", text, flags=re.DOTALL)
        self.assertIsNotNone(match)
        script = match.group("script")

        self.assertNotIn("<target>", script)
        self.assertIn('git -C "$housekeeping_target" status --short -- .', script)
        self.assertIn('git -C "$housekeeping_target" status --ignored --short -- .', script)
        self.assertIn('find "$housekeeping_target"', script)
        self.assertNotIn("stale_pattern", script)
        self.assertNotIn("grep", script)
        self.assertNotIn("rg ", script)

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            repo = Path(temp_dir).resolve()
            target = repo / "scope"
            target.mkdir()
            outside = Path(outside_dir).resolve()
            subprocess.run(
                ["git", "init", "-q", str(repo)],
                check=True,
                capture_output=True,
                text=True,
            )
            (repo / ".gitignore").write_text(
                "__pycache__/\n.pytest_cache/\nnode_modules/\n.venv/\n",
                encoding="utf-8",
            )
            (repo / "outside.txt").write_text("outside-scope\n", encoding="utf-8")
            for relative in (
                "src/__pycache__",
                ".pytest_cache",
                "node_modules/pkg/__pycache__",
                ".venv/lib/__pycache__",
            ):
                (target / relative).mkdir(parents=True)
            (target / "guidance.md").write_text("semantic guidance\n", encoding="utf-8")
            outside_marker = "outside-target"
            (outside / "outside.md").write_text(
                outside_marker + "\n",
                encoding="utf-8",
            )
            outside_link = target / "outside-link"
            try:
                outside_link.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError):
                outside_link = None

            def target_state() -> list[tuple[str, bool, bytes | None]]:
                return sorted(
                    (
                        str(path.relative_to(target)),
                        path.is_dir(),
                        None if path.is_dir() else path.read_bytes(),
                    )
                    for path in target.rglob("*")
                    if ".git" not in path.relative_to(target).parts
                )

            before = target_state()

            env = os.environ.copy()
            env["HOUSEKEEPING_TARGET"] = str(target)
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=target,
                env=env,
                capture_output=True,
                text=True,
            )

            env["HOUSEKEEPING_TARGET_KIND"] = "git"
            failed = subprocess.run(
                ["bash", "-c", "git() { printf 'Git inventory unavailable\\n' >&2; return 77; }\n" + script],
                cwd=target, env=env, capture_output=True, text=True,
            )
            self.assertEqual(failed.returncode, 77)
            self.assertIn("Git inventory unavailable", failed.stderr)
            self.assertNotIn(str(target / "src" / "__pycache__"), failed.stdout)

            after = target_state()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(after, before)
        self.assertIn(str(target / "src" / "__pycache__"), result.stdout)
        self.assertIn(str(target / ".pytest_cache"), result.stdout)
        self.assertNotIn(str(target / "node_modules" / "pkg" / "__pycache__"), result.stdout)
        self.assertNotIn(str(target / ".venv" / "lib" / "__pycache__"), result.stdout)
        self.assertNotIn("semantic guidance", result.stdout)
        self.assertNotIn("../outside.txt", result.stdout)
        self.assertNotIn("outside-scope", result.stdout)
        if outside_link is not None:
            self.assertNotIn(outside_marker, result.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX Bash housekeeping example")
    def test_housekeeping_inventory_reads_a_non_git_cache_without_mutation(self) -> None:
        text = HOUSEKEEPING.read_text(encoding="utf-8")
        match = re.search(r"```bash\n(?P<script>.*?)\n```", text, flags=re.DOTALL)
        self.assertIsNotNone(match)
        script = match.group("script")

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir).resolve()
            cache = target / "__pycache__"
            cache.mkdir()
            marker = cache / "generated.pyc"
            marker.write_bytes(b"cache")
            env = os.environ.copy()
            env["HOUSEKEEPING_TARGET"] = str(target)
            env["HOUSEKEEPING_TARGET_KIND"] = "cache"
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=target,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(marker.read_bytes(), b"cache")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(cache), result.stdout)
        self.assertNotIn("fatal:", result.stderr)


if __name__ == "__main__":
    unittest.main()
