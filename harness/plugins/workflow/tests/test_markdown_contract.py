from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "scripts"
sys.path.insert(0, str(SHARED))

from markdown_contract import (  # noqa: E402
    missing_relative_links,
    placeholder_errors,
    render_link_errors,
    strip_placeholder_example_blocks,
)


class MarkdownContractTests(unittest.TestCase):
    def test_strip_placeholder_examples_preserves_ordinary_fences(self) -> None:
        text = "\n".join(
            (
                "before",
                "```text placeholder-example",
                "<div>",
                "## Preflight Time Assessment",
                "```",
                "~~~text",
                "ordinary fenced contract evidence",
                "~~~",
                "after",
            )
        )

        self.assertEqual(
            strip_placeholder_example_blocks(text),
            "\n".join(
                (
                    "before",
                    "~~~text",
                    "ordinary fenced contract evidence",
                    "~~~",
                    "after",
                )
            ),
        )

    def test_placeholder_scan_checks_fences_except_explicit_examples(self) -> None:
        text = "\n".join(
            [
                "Visible <replace-me>",
                "```bash",
                "run <command-placeholder>",
                "```",
                "```text placeholder-example",
                "Shown <example-placeholder>",
                "```",
            ]
        )

        self.assertEqual(
            placeholder_errors(text),
            ["unresolved placeholders: <command-placeholder>, <replace-me>"],
        )

    def test_placeholder_example_fence_must_be_exact_and_closed(self) -> None:
        text = "\n".join(
            [
                "~~~text placeholder-example",
                "Shown <closed-example>",
                "~~~~",
                "~~~text not-placeholder-example",
                "Still unresolved <exact-token-required>",
                "~~~",
                "```text placeholder-example",
                "Unclosed <must-not-be-hidden>",
            ]
        )

        self.assertEqual(
            placeholder_errors(text),
            [
                "unclosed placeholder-example fence at line 7",
                "unresolved placeholders: <exact-token-required>, <must-not-be-hidden>",
            ],
        )

    def test_relative_link_scan_ignores_external_and_reports_missing_local_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exists.md").write_text("# Exists\n", encoding="utf-8")
            (root / "index.md").write_text(
                "\n".join(
                    [
                        "[ok](exists.md)",
                        "[anchor](#local)",
                        "[external](https://example.com)",
                        "[missing](missing.md)",
                    ]
                ),
                encoding="utf-8",
            )

            issues = missing_relative_links(root)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].line, 4)
        self.assertEqual(issues[0].target, "missing.md")

    def test_link_error_renderer_preserves_cli_message_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "index.md"
            file_path.write_text("[missing](missing.md)\n", encoding="utf-8")
            issues = missing_relative_links(root)

            stderr = io.StringIO()
            status = render_link_errors(issues, stderr=stderr)

        self.assertEqual(status, 1)
        self.assertIn(":1: missing missing.md", stderr.getvalue())

    def test_relative_link_scan_handles_reference_links_and_ignores_non_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "index.md"
            index.write_text(
                "\n".join(
                    [
                        "[reference][missing]",
                        "[missing]: missing.md \"Missing\"",
                        "[external](<https://example.com/path>)",
                        "`[inline-code](code-only.md)`",
                        "<!-- [comment](comment-only.md) -->",
                        "![image](image-only.md)",
                    ]
                ),
                encoding="utf-8",
            )

            issues = missing_relative_links(root)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].line, 1)
        self.assertEqual(issues[0].target, "missing.md")

if __name__ == "__main__":
    unittest.main()
