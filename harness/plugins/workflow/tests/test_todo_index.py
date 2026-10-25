from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "skills" / "long-running-goal" / "scripts" / "check_todo_index.py"


class TodoIndexCheckerTests(unittest.TestCase):
    def run_checker(self, *args: Path | str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), *(str(arg) for arg in args)],
            capture_output=True,
            check=False,
            text=True,
        )

    def test_active_mode_requires_an_exact_markdown_link_to_the_active_goal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "docs" / "todo" / "demo_goal.md"
            archived = active.parent / "archive" / active.name
            index = active.parent / "README.md"
            active.parent.mkdir(parents=True)
            archived.parent.mkdir()
            active.write_text("# Active goal\n", encoding="utf-8")
            archived.write_text("# Archived namesake\n", encoding="utf-8")
            index.write_text(
                "\n".join(
                    [
                        "Plain text demo_goal.md is not navigation.",
                        "```md",
                        "[code-only](demo_goal.md)",
                        "```",
                        "[archive](archive/demo_goal.md)",
                    ]
                ),
                encoding="utf-8",
            )

            completed = self.run_checker(active, index)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("missing exact Markdown link to active goal", completed.stderr)
        self.assertIn("same-name link resolves elsewhere", completed.stderr)

    def test_default_active_mode_keeps_backward_compatible_success_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal = root / "docs" / "todo" / "demo_goal.md"
            first = goal.parent / "README.md"
            second = root / "README.md"
            goal.parent.mkdir(parents=True)
            goal.write_text("# Active goal\n", encoding="utf-8")
            first.write_text("[goal](demo_goal.md)\n", encoding="utf-8")
            second.write_text("[goal](docs/todo/demo_goal.md)\n", encoding="utf-8")

            completed = self.run_checker(goal, first, second)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("referenced by 2 index file(s)", completed.stdout)

    def test_closed_mode_requires_old_path_absent_and_archive_linked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "docs" / "todo" / "demo_goal.md"
            archived = active.parent / "archive" / active.name
            active_index = active.parent / "README.md"
            archive_index = archived.parent / "README.md"
            archived.parent.mkdir(parents=True)
            archived.write_text("# Closed goal\n", encoding="utf-8")
            active_index.write_text(
                "[closed record](archive/demo_goal.md)\n",
                encoding="utf-8",
            )
            archive_index.write_text(
                "[record](demo_goal.md)\n",
                encoding="utf-8",
            )

            completed = self.run_checker(
                "--mode",
                "closed",
                "--archived-goal",
                archived,
                active,
                active_index,
                archive_index,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("closed goal removed from active indexes", completed.stdout)

    def test_closed_mode_rejects_stale_active_links_and_unlinked_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "docs" / "todo" / "demo_goal.md"
            archived = active.parent / "archive" / active.name
            index = active.parent / "README.md"
            archived.parent.mkdir(parents=True)
            archived.write_text("# Closed goal\n", encoding="utf-8")
            index.write_text("[stale](demo_goal.md)\n", encoding="utf-8")

            completed = self.run_checker(
                "--mode",
                "closed",
                "--archived-goal",
                archived,
                active,
                index,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("stale active-goal link", completed.stderr)
        self.assertIn("archived goal is not referenced", completed.stderr)

    def test_absent_mode_requires_both_goal_path_and_index_links_to_be_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal = root / "docs" / "todo" / "demo_goal.md"
            index = goal.parent / "README.md"
            goal.parent.mkdir(parents=True)
            index.write_text("No active goals.\n", encoding="utf-8")

            clean = self.run_checker("--mode", "absent", goal, index)
            self.assertEqual(clean.returncode, 0, clean.stderr)

            goal.write_text("# Still active\n", encoding="utf-8")
            existing = self.run_checker("--mode", "absent", goal, index)
            self.assertEqual(existing.returncode, 1)
            self.assertIn("absent: goal file still exists", existing.stderr)

            goal.unlink()
            index.write_text("[stale](demo_goal.md)\n", encoding="utf-8")
            stale = self.run_checker("--mode", "absent", goal, index)
            self.assertEqual(stale.returncode, 1)
            self.assertIn("stale active-goal link", stale.stderr)

    def test_mode_argument_contract_rejects_invalid_archive_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal = root / "goal.md"
            index = root / "README.md"
            archive = root / "archive" / "goal.md"
            index.write_text("No goals.\n", encoding="utf-8")

            missing_archive = self.run_checker("--mode", "closed", goal, index)
            active_with_archive = self.run_checker(
                "--archived-goal", archive, goal, index
            )

        self.assertEqual(missing_archive.returncode, 2)
        self.assertIn("--archived-goal is required", missing_archive.stderr)
        self.assertEqual(active_with_archive.returncode, 2)
        self.assertIn("--archived-goal is only valid", active_with_archive.stderr)

    def test_link_syntax_matrix_is_exact_in_active_and_absence_modes(self) -> None:
        cases = {
            "inline_title": ("demo_goal.md", '[goal](demo_goal.md "Goal title")'),
            "reference": (
                "demo_goal.md",
                '[goal][current]\n\n[current]: demo_goal.md "Goal title"',
            ),
            "shortcut_reference": (
                "demo_goal.md",
                "[goal]\n\n[goal]: demo_goal.md",
            ),
            "collapsed_reference": (
                "demo_goal.md",
                "[goal][]\n\n[goal]: demo_goal.md",
            ),
            "parentheses": ("demo(goal).md", "[goal](demo(goal).md)"),
            "percent_encoded": ("demo goal.md", "[goal](demo%20goal.md)"),
            "angle_wrapped": ("demo goal.md", "[goal](<demo goal.md>)"),
            "fragment": ("demo_goal.md", "[goal](demo_goal.md#status)"),
            "query_and_fragment": (
                "demo_goal.md",
                "[goal](demo_goal.md?view=compact#status)",
            ),
        }
        if sys.platform == "win32":
            cases["windows_backslash"] = (
                "subdir/demo_goal.md",
                r"[goal](subdir\demo_goal.md)",
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, (goal_name, markdown) in cases.items():
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    goal = case_root / goal_name
                    index = case_root / "README.md"
                    goal.parent.mkdir(parents=True, exist_ok=True)
                    goal.write_text("# Goal\n", encoding="utf-8")
                    index.write_text(markdown + "\n", encoding="utf-8")

                    active = self.run_checker(goal, index)
                    self.assertEqual(active.returncode, 0, active.stderr)

                    goal.unlink()
                    absent = self.run_checker("--mode", "absent", goal, index)
                    self.assertEqual(absent.returncode, 1)
                    self.assertIn("stale active-goal link", absent.stderr)

    def test_non_navigation_markdown_does_not_count_as_a_goal_link(self) -> None:
        cases = {
            "html_comment": "<!-- [goal](demo_goal.md) -->",
            "inline_code": "`[goal](demo_goal.md)`",
            "indented_code": "    [goal](demo_goal.md)",
            "image": "![goal](demo_goal.md)",
            "escaped_example": r"\[goal](demo_goal.md)",
            "external": "[external](<https://example.com/demo_goal.md>)",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, markdown in cases.items():
                with self.subTest(name=name):
                    case_root = root / name
                    case_root.mkdir()
                    goal = case_root / "demo_goal.md"
                    index = case_root / "README.md"
                    goal.write_text("# Goal\n", encoding="utf-8")
                    index.write_text(markdown + "\n", encoding="utf-8")

                    active = self.run_checker(goal, index)
                    self.assertEqual(active.returncode, 1)
                    self.assertIn("missing exact Markdown link", active.stderr)

                    goal.unlink()
                    absent = self.run_checker("--mode", "absent", goal, index)
                    self.assertEqual(absent.returncode, 0, absent.stderr)

    def test_filesystem_contract_reports_missing_goal_index_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            goal = root / "goal.md"
            index = root / "README.md"
            archive = root / "archive" / "goal.md"
            index.write_text("[goal](goal.md)\n", encoding="utf-8")

            missing_goal = self.run_checker(goal, index)
            self.assertEqual(missing_goal.returncode, 1)
            self.assertIn("active: missing goal file", missing_goal.stderr)

            goal.write_text("# Goal\n", encoding="utf-8")
            missing_index = self.run_checker(goal, root / "missing.md")
            self.assertEqual(missing_index.returncode, 1)
            self.assertIn("missing index", missing_index.stderr)

            goal.unlink()
            missing_archive = self.run_checker(
                "--mode",
                "closed",
                "--archived-goal",
                archive,
                goal,
                index,
            )
            self.assertEqual(missing_archive.returncode, 1)
            self.assertIn("closed: missing archived goal file", missing_archive.stderr)


if __name__ == "__main__":
    unittest.main()
