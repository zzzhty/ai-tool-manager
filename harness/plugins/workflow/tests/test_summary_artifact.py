from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "scripts"
RENDERER = ROOT / "skills" / "summary-in-html" / "scripts" / "render_summary_html.py"
CHECKER = ROOT / "skills" / "summary-in-html" / "scripts" / "check_summary_html.py"
SCHEMA_DOC = ROOT / "skills" / "summary-in-html" / "references" / "artifact-schema.md"
sys.path.insert(0, str(SHARED))

from summary_artifact import SummaryArtifactError, artifact_from_data, validate_summary_artifact  # noqa: E402


def minimal_artifact() -> dict[str, object]:
    return {"title": "Demo", "sections": [{"title": "Overview"}]}


def walkthrough_artifact(source_root: str = "/workspace") -> dict[str, object]:
    return {
        "title": "Request Path",
        "document_type": "source_walkthrough",
        "source_root": source_root,
        "source_revision": "HEAD abc1234; clean",
        "evidence": [
            {
                "label": "Current source",
                "path": "inventory.inputs.json",
                "role": "current_source",
            }
        ],
        "sections": [
            {
                "title": "Complete route",
                "code": [
                    {
                        "language": "call-tree",
                        "text": "handler\\n  -> service\\n  <- response",
                    }
                ],
            },
            {
                "title": "Enter the handler",
                "summary": "Open handle_request().",
                "entry_symbol": "handle_request()",
                "receives": ["A request."],
                "does": ["Binds the request to a command."],
                "hands_off_to": ["The service."],
                "returns": ["A response."],
                "files": [{"path": "src/handler.py", "note": "Public boundary"}],
                "completion_check": "I can locate the handler and its next call.",
            },
            {
                "title": "Follow-up",
                "summary": "Continue only after the route is clear.",
            },
        ],
    }


class SummaryArtifactTests(unittest.TestCase):
    def test_walkthrough_contract_errors_are_deterministic(self) -> None:
        invalid_type = {
            "title": "Demo",
            "document_type": "unknown",
            "sections": [{"title": "Overview"}],
        }
        missing_root = walkthrough_artifact()
        del missing_root["source_root"]
        missing_revision = walkthrough_artifact()
        del missing_revision["source_revision"]
        missing_current_source = walkthrough_artifact()
        missing_current_source["evidence"] = [
            {
                "label": "Historical note",
                "path": "history.md",
                "role": "historical_context",
            }
        ]
        completion_in_summary = {
            "title": "Demo",
            "sections": [{"title": "Entry", "completion_check": "I can find it."}],
        }
        blank_completion = walkthrough_artifact()
        blank_completion["sections"][1]["completion_check"] = " "  # type: ignore[index]
        missing_route = walkthrough_artifact()
        missing_route["sections"] = missing_route["sections"][1:]  # type: ignore[index]
        late_route = walkthrough_artifact()
        late_route["sections"][0], late_route["sections"][1] = (  # type: ignore[index]
            late_route["sections"][1],  # type: ignore[index]
            late_route["sections"][0],  # type: ignore[index]
        )
        cases = [
            (invalid_type, ["root.document_type must be one of: source_walkthrough, summary"]),
            (missing_root, ["root.source_root must be a non-empty string"]),
            (missing_revision, ["root.source_revision must be a non-empty string"]),
            (
                missing_current_source,
                ["source_walkthrough must include current_source evidence"],
            ),
            (
                completion_in_summary,
                ["section completion_check requires root.document_type source_walkthrough"],
            ),
            (
                blank_completion,
                ["sections[2].completion_check must be a non-empty string"],
            ),
            (
                missing_route,
                [
                    "source_walkthrough must include a call-tree code block "
                    "before the first completion_check"
                ],
            ),
            (
                late_route,
                [
                    "source_walkthrough must include a call-tree code block "
                    "before the first completion_check"
                ],
            ),
        ]
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(validate_summary_artifact(data), expected)

    def test_walkthrough_step_title_rejects_manual_ordinals(self) -> None:
        for title in [
            "1. Enter the handler",
            "Step 1. Enter the handler",
            "Step 1: Enter the handler",
            "Step 1 Enter the handler",
        ]:
            with self.subTest(title=title):
                data = walkthrough_artifact()
                data["sections"][1]["title"] = title  # type: ignore[index]
                self.assertEqual(
                    validate_summary_artifact(data),
                    ["sections[2].title must not start with a step ordinal"],
                )

    def test_walkthrough_step_requires_complete_handoff_fields(self) -> None:
        cases = [
            ("title", "sections[2].title must be a non-empty string"),
            ("entry_symbol", "sections[2].entry_symbol must be a non-empty string"),
            ("receives", "sections[2].receives must be a non-empty list"),
            ("does", "sections[2].does must be a non-empty list"),
            ("hands_off_to", "sections[2].hands_off_to must be a non-empty list"),
            ("returns", "sections[2].returns must be a non-empty list"),
            ("files", "sections[2].files must be a non-empty list"),
        ]
        for field, expected in cases:
            with self.subTest(field=field):
                data = walkthrough_artifact()
                del data["sections"][1][field]  # type: ignore[index]
                self.assertEqual(validate_summary_artifact(data), [expected])

    def test_walkthrough_entry_does_not_require_a_cli(self) -> None:
        data = walkthrough_artifact()
        data["sections"][0]["code"][0]["text"] = (  # type: ignore[index]
            "framework caller\\n  -> exported Client.send()\\n  <- result"
        )
        data["sections"][1]["entry_symbol"] = "Client.send()"  # type: ignore[index]
        data["sections"][1]["hands_off_to"] = ["The transport adapter."]  # type: ignore[index]

        self.assertEqual(validate_summary_artifact(data), [])

    def test_record_lists_reject_non_object_members(self) -> None:
        cases = [
            ("files", "sections[1].files[1] must be an object"),
            ("code", "sections[1].code[1] must be an object"),
            ("evidence", "root.evidence[1] must be an object"),
            ("assets", "root.assets[1] must be an object"),
        ]
        for field, expected in cases:
            with self.subTest(field=field):
                data = minimal_artifact()
                if field in {"files", "code"}:
                    data["sections"][0][field] = ["invalid"]  # type: ignore[index]
                else:
                    data[field] = ["invalid"]

                self.assertEqual(validate_summary_artifact(data), [expected])
                with self.assertRaises(SummaryArtifactError) as raised:
                    artifact_from_data(data)
                self.assertEqual(str(raised.exception), expected)

    def test_root_and_section_shape_errors_remain_deterministic(self) -> None:
        self.assertEqual(
            validate_summary_artifact({"title": "Demo"}),
            ["summary JSON must include a non-empty sections list"],
        )
        self.assertEqual(
            validate_summary_artifact({"sections": [{"title": ["not", "text"]}]}),
            ["sections[1].title must be a string"],
        )

    def test_nested_errors_are_aggregated_in_schema_order(self) -> None:
        data = {
            "sections": [
                {
                    "paragraphs": ["valid", 2],
                    "bullets": [{}],
                    "files": [{}, {"path": "README.md", "note": 3}],
                    "code": [{}, {"text": "print('ok')", "language": 4}],
                }
            ],
            "evidence": [{}, {"path": "report.json", "label": 5}],
            "assets": [{}],
            "blind_spots": [False],
        }

        self.assertEqual(
            validate_summary_artifact(data),
            [
                "sections[1].paragraphs[2] must be a string",
                "sections[1].bullets[1] must be a string",
                "sections[1].files[1].path must be a non-empty string",
                "sections[1].files[2].note must be a string",
                "sections[1].code[1].text must be a string",
                "sections[1].code[2].language must be a string",
                "root.evidence[1].path must be a non-empty string",
                "root.evidence[2].label must be a string",
                "root.assets[1].path must be a non-empty string",
                "root.assets[1].alt must be a non-empty string",
                "root.assets[1].caption must be a non-empty string",
                "root.blind_spots[1] must be a string",
            ],
        )

    def test_visual_fields_must_be_present_and_non_empty(self) -> None:
        data = minimal_artifact()
        data["assets"] = [{"path": " ", "alt": "", "caption": None}]

        self.assertEqual(
            validate_summary_artifact(data),
            [
                "root.assets[1].path must be a non-empty string",
                "root.assets[1].alt must be a non-empty string",
                "root.assets[1].caption must be a non-empty string",
            ],
        )

    def test_documented_nested_artifact_renders_compatibly(self) -> None:
        documented = SCHEMA_DOC.read_text(encoding="utf-8")
        match = re.search(
            r"A minimal summary input is:\n\n```json\n(?P<payload>.*?)\n```",
            documented,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group("payload"))

        artifact = artifact_from_data(data)
        self.assertEqual(artifact.title, "Workflow Plugin Summary")

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "summary.json"
            output_path = Path(tmp) / "summary.html"
            input_path.write_text(json.dumps(data), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(RENDERER), "--input", str(input_path), "--out", str(output_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            checked = subprocess.run(
                [sys.executable, str(CHECKER), str(output_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            html = output_path.read_text(encoding="utf-8") if output_path.exists() else ""

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("Workflow Plugin Summary", html)
        self.assertNotIn("<img", html)
        self.assertIn("plugins/workflow/README.md", html)
        self.assertIn("python -m unittest", html)
        self.assertIn('<body class="reference-summary">', html)
        self.assertNotIn("data-progress-check", html)
        self.assertNotIn("walkthrough-progress", html)
        self.assertNotIn(".file-list a", html)
        self.assertNotIn(".call-tree", html)
        self.assertNotIn("<script>", html)

    def test_documented_explicit_visual_asset_renders_and_passes_checker(self) -> None:
        documented = SCHEMA_DOC.read_text(encoding="utf-8")
        minimal_match = re.search(
            r"A minimal summary input is:\n\n```json\n(?P<payload>.*?)\n```",
            documented,
            flags=re.DOTALL,
        )
        visual_match = re.search(
            r"After an explicit visual request.*?```json\n(?P<payload>.*?)\n```",
            documented,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(minimal_match)
        self.assertIsNotNone(visual_match)
        data = json.loads(minimal_match.group("payload"))
        data.update(json.loads(visual_match.group("payload")))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asset = root / "assets" / "architecture.png"
            asset.parent.mkdir()
            asset.write_bytes(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                )
            )
            input_path = root / "summary.json"
            output_path = root / "summary.html"
            input_path.write_text(json.dumps(data), encoding="utf-8")
            rendered = subprocess.run(
                [sys.executable, str(RENDERER), "--input", str(input_path), "--out", str(output_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            checked = subprocess.run(
                [sys.executable, str(CHECKER), str(output_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            html = output_path.read_text(encoding="utf-8") if output_path.exists() else ""

        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('<img src="assets/architecture.png" alt="Workflow architecture">', html)
        self.assertIn("Validated workflow structure", html)

    def test_explicit_summary_matches_default_rendering(self) -> None:
        data = {
            "title": "Compatibility",
            "generated_at": "2026-07-30T00:00:00+00:00",
            "sections": [{"title": "Overview", "summary": "Existing summary behavior."}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default_input = root / "default.json"
            explicit_input = root / "explicit.json"
            default_output = root / "default.html"
            explicit_output = root / "explicit.html"
            default_input.write_text(json.dumps(data), encoding="utf-8")
            explicit_input.write_text(
                json.dumps({**data, "document_type": "summary"}),
                encoding="utf-8",
            )
            default = subprocess.run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--input",
                    str(default_input),
                    "--out",
                    str(default_output),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            explicit = subprocess.run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--input",
                    str(explicit_input),
                    "--out",
                    str(explicit_output),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            default_html = default_output.read_text(encoding="utf-8")
            explicit_html = explicit_output.read_text(encoding="utf-8")

        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual(default_html, explicit_html)

    def test_source_walkthrough_renders_linked_steps_and_static_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "handler.py"
            source.parent.mkdir()
            source.write_text("def handle_request():\\n    return 'ok'\\n", encoding="utf-8")
            output = root / "docs" / "walkthrough.html"
            input_path = root / "walkthrough.json"
            data = walkthrough_artifact(str(root))
            input_path.write_text(json.dumps(data), encoding="utf-8")
            rendered = subprocess.run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--input",
                    str(input_path),
                    "--out",
                    str(output),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            checked = subprocess.run(
                [sys.executable, str(CHECKER), str(output)],
                capture_output=True,
                check=False,
                text=True,
            )
            html = output.read_text(encoding="utf-8") if output.exists() else ""

        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('<body class="source-walkthrough">', html)
        self.assertIn("data-progress-count>0 / 1", html)
        self.assertIn('max="1">0 / 1</progress>', html)
        self.assertIn("<noscript>", html)
        self.assertEqual(html.count('class="walkthrough-step"'), 1)
        self.assertEqual(html.count('class="step-number"'), 1)
        self.assertIn(">Step 1</span>", html)
        self.assertIn('href="../src/handler.py"', html)
        self.assertIn('class="call-tree"', html)
        self.assertIn('class="handoff-ledger"', html)
        self.assertIn("<dt>Enter</dt><dd><code>handle_request()</code></dd>", html)
        self.assertIn("<dt>Does</dt>", html)
        self.assertIn("<dt>Hands off to</dt>", html)
        self.assertIn("<dt>Returns</dt>", html)
        self.assertIn("Source revision:", html)
        self.assertIn("current source", html)
        self.assertLess(html.index("Complete route"), html.index("Step 1"))
        self.assertIn("<script>", html)
        self.assertNotIn("<script src", html)

    def test_source_walkthrough_rejects_missing_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "walkthrough.json"
            output_path = root / "walkthrough.html"
            data = walkthrough_artifact(str(root))
            data["title"] = "Missing source"
            data["sections"][1]["files"] = [{"path": "src/missing.py"}]  # type: ignore[index]
            input_path.write_text(json.dumps(data), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--input",
                    str(input_path),
                    "--out",
                    str(output_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            output_exists = output_path.exists()

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr.strip(), "source file does not exist: src/missing.py")
        self.assertFalse(output_exists)

    def test_checker_rejects_broken_structure_and_remote_dependencies(self) -> None:
        html = """<!doctype html>
<html>
<head>
  <link rel="stylesheet" href="theme.css">
  <style>@import "remote.css"; .x { background: url(https://example.com/x.png); }</style>
</head>
<body>
  <main>
    <h1>Demo</h1>
    <section id="same"><a href="#missing">Broken</a></section>
    <section id="same"><img src="https://example.com/image.png" alt=""></section>
  </main>
  <script src="app.js"></script>
</body>
</html>
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.html"
            path.write_text(html, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(CHECKER), str(path)],
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        for expected in [
            "duplicate id: same",
            "external script dependency is not allowed: app.js",
            "external stylesheet dependency is not allowed: theme.css",
            "CSS @import dependency is not allowed",
            "remote CSS url dependency is not allowed",
            "remote image asset is not allowed: https://example.com/image.png",
            "missing local fragment target: #missing",
        ]:
            self.assertIn(expected, completed.stderr)

    def test_renderer_reports_contract_error_without_traceback(self) -> None:
        data = minimal_artifact()
        data["sections"][0]["files"] = ["README.md"]  # type: ignore[index]

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "invalid.json"
            output_path = Path(tmp) / "summary.html"
            input_path.write_text(json.dumps(data), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(RENDERER), "--input", str(input_path), "--out", str(output_path)],
                capture_output=True,
                check=False,
                text=True,
            )
            output_exists = output_path.exists()

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr.strip(), "sections[1].files[1] must be an object")
        self.assertNotIn("Traceback", completed.stderr)
        self.assertFalse(output_exists)


if __name__ == "__main__":
    unittest.main()
