from __future__ import annotations

import io
import atexit
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
_CATALOG_HOME = tempfile.TemporaryDirectory(prefix="ATM_TEST_ONLY_catalog_")
atexit.register(_CATALOG_HOME.cleanup)
REPO_ROOT = Path(_CATALOG_HOME.name)
fixture = json.loads((ROOT / "tests/fixtures/catalog.json").read_text())
(REPO_ROOT / "canonical-catalog.json").write_text(json.dumps(fixture))
(REPO_ROOT / "runtimes/watcher/scripts").mkdir(parents=True)
(REPO_ROOT / "runtimes/watcher/scripts/watcher").write_text("# fixture runtime")
for entry in fixture["skills"]:
    (REPO_ROOT / entry["path"]).mkdir(parents=True)

from watcher_runtime.skill.catalog_metadata import discover_skill_metadata, write_dynamic_monitored_skills
from watcher_runtime.skill.doctor import main as doctor_main
from watcher_runtime.skill.migrate_skill_watcher_schema import main as reset_schema_main  # noqa: E402
from watcher_runtime.skill.report_pipeline import (  # noqa: E402
    event_hash,
    load_report_state,
    report_state_key,
    save_report_state,
    state_since,
    skill_logical_groups,
    usage_rows,
    update_report_state,
)
from watcher_runtime.skill.propose_skill_patch import build_proposal, main as propose_main  # noqa: E402
from watcher_runtime.skill.redact_event import REDACTION, redact_event  # noqa: E402
from watcher_runtime.repository_source import load_repository_skill_catalog, resolve_repository_source
from watcher_runtime.skill.runtime_paths import (  # noqa: E402
    ensure_runtime_dirs as runtime_ensure_runtime_dirs,
    hook_backup_dir,
    log_file_path,
    report_state_path as runtime_report_state_path,
    reports_dir,
    safe_slug as runtime_safe_slug,
    state_dir_from_env_or_arg as runtime_state_dir_from_env_or_arg,
    turns_dir,
)
from watcher_runtime.skill.report_pipeline import (  # noqa: E402
    ReportOutputPolicy,
    ReportQuery,
    generate_report as run_report_pipeline,
)
from watcher_runtime.skill.report_pipeline import parse_since, read_events_since  # noqa: E402
from watcher_runtime.skill.proposal_artifact import update_status  # noqa: E402
from watcher_runtime.skill.validate_candidate import (  # noqa: E402
    main as validate_candidate_main,
    validate_skill,
)


WINDOWS_PWSH_ENCODING_TEST = unittest.skipUnless(
    sys.platform == "win32",
    "Windows PowerShell encoding regression",
)


def initialize_catalog_repo(root: Path, skills: dict[str, tuple[str, ...]]) -> None:
    watcher_cli = root / "runtimes" / "watcher" / "scripts" / "watcher"
    watcher_cli.parent.mkdir(parents=True, exist_ok=True)
    watcher_cli.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    entries = []
    for plugin, names in skills.items():
        for name in names:
            entries.append({"id": f"{plugin}:{name}", "plugin": plugin,
                "name": name, "directoryName": name,
                "path": f"plugins/{plugin}/skills/{name}", "aliases": []})
    (root / "canonical-catalog.json").write_text(json.dumps({
        "schemaVersion": 1, "product": "atm-harness-catalog", "sourceIdentity": "0" * 64,
        "skills": entries, "attributionOverlays": [],
    }), encoding="utf-8")


def write_attribution_overlay(root: Path, plugin_name: str, payload: dict[str, object]) -> Path:
    path = root / "canonical-catalog.json"
    catalog = json.loads(path.read_text())
    catalog["attributionOverlays"].append({"plugin": plugin_name,
        "path": f"plugins/{plugin_name}/.codex-plugin/skill-watcher.json", "data": payload})
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


class SkillWatcherTests(unittest.TestCase):
    class StrictAsciiStdout:
        encoding = "ascii"

        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, text: str) -> int:
            text.encode("ascii")
            self.writes.append(text)
            return len(text)

        def flush(self) -> None:
            return None


    def test_skill_doctor_reports_retired_hooks_without_writing_config_or_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "watcher" / "skill"
            hook_target = root / "hooks.json"
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                result = doctor_main(
                    [
                        "--repo-root",
                        str(REPO_ROOT),
                        "--state-dir",
                        str(state_dir),
                        "--hook-target",
                        str(hook_target),
                        "--python",
                        sys.executable,
                    ]
                )

            self.assertEqual(result, 0, output.getvalue())
            self.assertFalse(state_dir.exists())
            self.assertFalse(hook_target.exists())
            self.assertIn("no events written", output.getvalue())

            log = state_dir / "logs/events.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text('{"event_type":"historical"}\n', encoding="utf-8")
            for config in (
                {"hooks": {"Stop": [{"hooks": [{"command": "TEST_ONLY old", "statusMessage": "Watcher skill: observe Stop"}]}, {"hooks": [{"command": "TEST_ONLY user"}]}]}},
                {"hooks": None},
                {"hooks": {"Stop": [{"hooks": None}]}},
            ):
                hook_target.write_text(json.dumps(config), encoding="utf-8")
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                output = io.StringIO()
                with mock.patch("sys.stdout", output):
                    result = doctor_main(["--repo-root", str(REPO_ROOT), "--state-dir", str(state_dir), "--hook-target", str(hook_target)])
                self.assertEqual(result, 0)
                self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)
                if "TEST_ONLY old" in json.dumps(config):
                    self.assertIn("1 retired skill-watcher handlers", output.getvalue())


    def test_redacts_secret_keys_and_values(self) -> None:
        payload = {
            "api_key": "plain-secret",
            "notes": "Bearer abcdefghijklmnop and sk-testsecret123",
            "nested": {"refresh_token": "another-secret"},
        }

        redacted = redact_event(payload)

        self.assertEqual(redacted["api_key"], REDACTION)
        self.assertEqual(redacted["nested"]["refresh_token"], REDACTION)
        self.assertNotIn("sk-testsecret123", json.dumps(redacted))
        self.assertNotIn("abcdefghijklmnop", json.dumps(redacted))

    def test_matt_selection_preserves_invocation_and_historical_attribution(self) -> None:
        metadata = discover_skill_metadata(REPO_ROOT)
        watcher_identities = set(metadata["skills"])
        selected = {
            "ask-matt", "code-review", "codebase-design", "diagnosing-bugs",
            "domain-modeling", "grill-me", "grill-with-docs", "grilling", "handoff",
            "implement", "improve-codebase-architecture", "pr", "prototype", "research",
            "retro", "tdd", "teach",
            "to-spec", "triage", "writing-for-agents",
        }
        self.assertEqual(len(watcher_identities), 30)
        self.assertEqual(
            {name.split(":", 1)[1] for name in watcher_identities if name.startswith("mattpocock-skills:")},
            selected,
        )
        for skill_name in selected:
            full_name = f"mattpocock-skills:{skill_name}"
            aliases = metadata["skills"][full_name]["aliases"]
            self.assertIn(
                {"value": full_name, "kind": "skill_name", "match": "phrase"},
                aliases,
            )
            if skill_name in {"code-review", "implement", "research", "to-spec", "writing-for-agents"}:
                self.assertIn(
                    {"value": skill_name, "kind": "slug", "match": "token"},
                    aliases,
                )

        pr_aliases = metadata["skills"]["mattpocock-skills:pr"]["aliases"]
        self.assertNotIn("pr", {alias["value"] for alias in pr_aliases})
        self.assertIn(
            {"value": "pull request body", "kind": "phrase", "match": "phrase"},
            pr_aliases,
        )

        explicit_workflows = {
            "ask-matt",
            "grill-me",
            "grill-with-docs",
            "handoff",
            "implement",
            "improve-codebase-architecture",
            "retro",
            "teach",
            "to-spec",
            "triage",
        }
        for full_name, values in metadata["skills"].items():
            if not full_name.startswith("mattpocock-skills:"):
                continue
            skill_name = full_name.split(":", 1)[1]
            expected_group = (
                "explicit-workflows"
                if skill_name in explicit_workflows
                else "implicit-primitives"
            )
            self.assertEqual(values["logical_group"], expected_group)

        local_groups = {
            "watcher:doc-alignment": "implicit-primitives",
            "watcher:housekeeping": "implicit-primitives",
            "watcher:skill-compressor": "implicit-primitives",
            "watcher:skill-maintainer": "implicit-primitives",
            "workflow:long-running-goal": "explicit-workflows",
            "workflow:orchestrate-subagents": "explicit-workflows",
            "workflow:prompt-strategy-loop": "implicit-primitives",
            "workflow:scope-discipline": "explicit-workflows",
            "workflow:sop": "implicit-primitives",
            "workflow:summary-in-html": "implicit-primitives",
        }
        for skill_name, expected_group in local_groups.items():
            self.assertEqual(metadata["skills"][skill_name]["logical_group"], expected_group)
        self.assertEqual(
            metadata["skills"]["watcher:housekeeping"]["supporting_skills"],
            [],
        )

        self.assertNotIn("mattpocock-skills:to-prd", watcher_identities)
        self.assertNotIn("mattpocock-skills:to-issues", watcher_identities)
        self.assertNotIn("mattpocock-skills:writing-great-skills", watcher_identities)
        self.assertEqual(
            set(metadata["skills"]["mattpocock-skills:implement"]["supporting_skills"]),
            {
                "mattpocock-skills:code-review",
            },
        )

        renamed = (
            ("mattpocock-skills:to-prd", "to-prd", "mattpocock-skills:to-spec"),
            (
                "mattpocock-skills:write-a-skill",
                "write-a-skill",
                "mattpocock-skills:writing-for-agents",
            ),
            (
                "mattpocock-skills:writing-great-skills",
                "writing-great-skills",
                "mattpocock-skills:writing-for-agents",
            ),
        )
        for legacy_full_name, _legacy_slug, current_name in renamed:
            self.assertEqual(metadata["legacy_names"][legacy_full_name], current_name)

        retired_names = {
            f"mattpocock-skills:{name}"
            for name in (
                "to-questionnaire", "to-tickets", "wait-what", "wayfinder", "wizard",
                "to-issues", "setup-matt-pocock-skills",
                "resolving-merge-conflicts",
            )
        }
        self.assertTrue(retired_names.isdisjoint(watcher_identities))
        self.assertTrue(retired_names.isdisjoint(metadata["legacy_names"]))
        self.assertTrue(retired_names.isdisjoint(metadata["legacy_names"].values()))
        events = [
            {
                "event_type": "turn_summary",
                "session_id": "historical",
                "event_id": f"turn-{number}",
                "skill_attribution": {
                    "primary": {"name": name, "role": "specialized"},
                    "supporting": [{"name": "mattpocock-skills:code-review", "role": "discipline"}],
                },
            }
            for number, name in enumerate(sorted(retired_names))
        ]
        original_events = json.loads(json.dumps(events))
        rows = {row["skill"]: row for row in usage_rows(events, skill_logical_groups(metadata))}
        for name in retired_names:
            self.assertEqual(rows[name]["primary_turns"], 1)
            self.assertEqual(rows[name]["effective_turns"], 1)
            self.assertEqual(rows[name]["logical_group"], "")
        self.assertEqual(rows["mattpocock-skills:code-review"]["supporting_turns"], len(events))
        self.assertEqual(events, original_events)

    def test_retro_attribution_is_narrow_and_does_not_compose_other_workflows(self) -> None:
        metadata = discover_skill_metadata(REPO_ROOT)
        retro = "mattpocock-skills:retro"
        self.assertEqual(metadata["skills"][retro]["logical_group"], "explicit-workflows")
        self.assertEqual(metadata["skills"][retro]["supporting_skills"], [])
        for name, skill in metadata["skills"].items():
            self.assertNotIn(retro, skill["supporting_skills"], name)

    def test_metadata_discovery_ignores_marketplace_and_plugin_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(root, {"demo": ("foo",)})
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text("{not-json\n", encoding="utf-8")
            plugin_manifest = root / "plugins" / "demo" / ".codex-plugin" / "plugin.json"
            plugin_manifest.parent.mkdir(parents=True)
            plugin_manifest.write_text("{not-json\n", encoding="utf-8")

            metadata = discover_skill_metadata(root)

        self.assertEqual(tuple(metadata["skills"]), ("demo:foo",))
        self.assertEqual(metadata["source_root"], str(root.resolve()))

    def test_metadata_discovery_requires_explicit_repository_root(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata()

        self.assertIn("pass --repo-root or set ATM_HARNESS_ROOT", str(raised.exception))

    def test_metadata_discovery_rejects_catalog_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            root = temporary_root / "source"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            catalog = root / "canonical-catalog.json"
            external_catalog = temporary_root / "outside-catalog.json"
            shutil.copyfile(catalog, external_catalog)
            catalog.unlink()
            try:
                catalog.symlink_to(external_catalog)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("canonical catalog snapshot contains a link", str(raised.exception))


    def test_metadata_discovery_rejects_unknown_overlay_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(root, {"demo": ("entry",)})
            write_attribution_overlay(
                root,
                "demo",
                {
                    "schema_version": 1,
                    "skills": {"demo:missing": {}},
                    "legacy_names": {},
                },
            )

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("unknown canonical skill demo:missing", str(raised.exception))

    def test_metadata_discovery_requires_known_overlay_schema(self) -> None:
        for schema_version in (None, 999):
            with self.subTest(schema_version=schema_version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                initialize_catalog_repo(root, {"demo": ("foo",)})
                metadata: dict[str, object] = {"skills": {}, "legacy_names": {}}
                if schema_version is not None:
                    metadata["schema_version"] = schema_version
                write_attribution_overlay(root, "demo", metadata)

                with self.assertRaises(SystemExit) as raised:
                    discover_skill_metadata(root)

                self.assertIn("unsupported skill metadata schema_version", str(raised.exception))

    def test_metadata_discovery_rejects_duplicate_legacy_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(
                root,
                {"alpha": ("alpha-entry",), "beta": ("beta-entry",)},
            )
            for plugin_name, callable_name in (
                ("alpha", "alpha-entry"),
                ("beta", "beta-entry"),
            ):
                write_attribution_overlay(
                    root,
                    plugin_name,
                    {
                        "schema_version": 1,
                        "skills": {},
                        "legacy_names": {
                            "legacy:shared": f"{plugin_name}:{callable_name}"
                        },
                    },
                )

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("duplicate legacy skill metadata entries", str(raised.exception))

    def test_metadata_discovery_rejects_invalid_logical_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(root, {"demo": ("entry",)})
            write_attribution_overlay(
                root,
                "demo",
                {
                    "schema_version": 1,
                    "skills": {"demo:entry": {"logical_group": "Not Valid"}},
                    "legacy_names": {},
                },
            )

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("invalid logical_group", str(raised.exception))





    def test_reset_schema_validates_repository_before_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            log_file = log_file_path(state_dir)
            turn_file = turns_dir(state_dir) / "turn.json"
            log_file.parent.mkdir(parents=True)
            turn_file.parent.mkdir(parents=True)
            log_file.write_text("preserve-event\n", encoding="utf-8")
            turn_file.write_text('{"preserve": true}\n', encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as raised:
                    reset_schema_main(
                        [
                            "--state-dir",
                            str(state_dir),
                            "--reset-runtime-state",
                        ]
                    )

            self.assertEqual(log_file.read_text(encoding="utf-8"), "preserve-event\n")
            self.assertEqual(turn_file.read_text(encoding="utf-8"), '{"preserve": true}\n')
            self.assertFalse((state_dir / "archives").exists())
            self.assertFalse((state_dir / "skill-metadata-cache.json").exists())
            self.assertFalse((state_dir / "schema-version.json").exists())

        self.assertIn("pass --repo-root or set ATM_HARNESS_ROOT", str(raised.exception))

    def test_reset_schema_uses_prevalidated_explicit_repository_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            root = temporary_root / "repo with spaces"
            state_dir = temporary_root / "state"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            log_file = log_file_path(state_dir)
            turn_file = turns_dir(state_dir) / "turn.json"
            log_file.parent.mkdir(parents=True)
            turn_file.parent.mkdir(parents=True)
            log_file.write_text("old-event\n", encoding="utf-8")
            turn_file.write_text("{}\n", encoding="utf-8")

            with mock.patch("sys.stdout", io.StringIO()):
                result = reset_schema_main(
                    [
                        "--state-dir",
                        str(state_dir),
                        "--repo-root",
                        str(root),
                        "--reset-runtime-state",
                    ]
                )

            archives = tuple((state_dir / "archives" / "pre-schema-v2").glob("events-*.jsonl"))
            metadata = json.loads((state_dir / "skill-metadata-cache.json").read_text(encoding="utf-8"))
            new_log = log_file.read_text(encoding="utf-8")
            turn_exists = turn_file.exists()
            archive_contents = tuple(path.read_text(encoding="utf-8") for path in archives)
            source_root = str(root.resolve())

        self.assertEqual(result, 0)
        self.assertEqual(new_log, "")
        self.assertFalse(turn_exists)
        self.assertEqual(len(archives), 1)
        self.assertEqual(archive_contents, ("old-event\n",))
        self.assertEqual(tuple(metadata["skills"]), ("demo:entry",))
        self.assertEqual(metadata["source_root"], source_root)


    def test_runtime_paths_centralize_state_layout_and_env_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            custom_log = Path(tmp) / "custom-events.jsonl"

            runtime_ensure_runtime_dirs(state_dir)

            self.assertEqual(log_file_path(state_dir), state_dir / "logs" / "events.jsonl")
            self.assertEqual(log_file_path(state_dir, str(custom_log)), custom_log)
            self.assertEqual(runtime_report_state_path(state_dir), state_dir / "report-state.json")
            self.assertEqual(reports_dir(state_dir), state_dir / "reports")
            self.assertEqual(hook_backup_dir(state_dir), state_dir / "backups" / "hooks-json")
            self.assertEqual(turns_dir(state_dir), state_dir / "turns")
            for dirname in ("logs", "reports", "proposals", "snapshots", "rejected", "backups", "turns"):
                self.assertTrue((state_dir / dirname).is_dir())

            with mock.patch.dict("os.environ", {"WATCHER_SKILL_STATE_DIR": str(state_dir)}, clear=False):
                self.assertEqual(runtime_state_dir_from_env_or_arg(None), state_dir)
            self.assertEqual(runtime_state_dir_from_env_or_arg(str(state_dir / "explicit")), state_dir / "explicit")
            self.assertEqual(runtime_safe_slug("skill watcher:demo", fallback="x"), "skill-watcher-demo")
            self.assertEqual(runtime_safe_slug("!!!", fallback="x"), "x")

    def test_proposal_filters_identity_and_validates_only_materialized_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "doc-alignment"
            skill_dir.mkdir()
            source = skill_dir / "SKILL.md"
            contents = "---\nname: doc-alignment\ndescription: Audit current docs.\n---\n\n# Audit\nRead current docs.\n"
            source.write_text(contents, encoding="utf-8")
            state = root / "state"
            args = ["--skill-dir", str(skill_dir), "--state-dir", str(state)]
            for identity_args in ([], ["--skill", ""], ["--skill", "   "]):
                with self.subTest(identity_args=identity_args):
                    with mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                        propose_main(args + identity_args)
                    self.assertEqual(error.exception.code, 2)
                    self.assertFalse(state.exists())
            log = root / "events.jsonl"
            events = [
                {
                    "timestamp": timestamp,
                    "event_type": "turn_summary",
                    "skill_attribution": {
                        "primary": {"name": identity, "role": "entrypoint"},
                        "supporting": [], "effective": [identity], "mentioned": [],
                    },
                    "user_feedback": feedback,
                }
                for identity, timestamp, feedback in (
                    ("watcher:doc-alignment", "2026-06-01T00:00:00Z", "outside-window"),
                    ("watcher:doc-alignment", "2026-06-06T00:00:00Z", "selected-evidence"),
                    ("other:doc-alignment", "2026-06-06T00:00:00Z", "wrong-identity"),
                )
            ]
            log.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            with mock.patch("sys.stdout", new=io.StringIO()):
                result = propose_main(args + ["--skill", "watcher:doc-alignment", "--since", "2026-06-05T00:00:00Z", "--log-file", str(log)])
            self.assertEqual(result, 0)
            proposal_path, = (state / "proposals").glob("*-proposal.md")
            proposal = proposal_path.read_text(encoding="utf-8")
            self.assertIn("selected-evidence", proposal)
            self.assertNotIn("wrong-identity", proposal)
            self.assertNotIn("outside-window", proposal)
            command = next(line for line in proposal.splitlines() if line.startswith('"$atm_tooling_python" -B scripts/watcher skill validate'))
            argv = shlex.split(command)
            candidate = Path(argv[argv.index("--candidate-skill") + 1])
            self.assertNotEqual(candidate, source)
            self.assertFalse(candidate.exists())
            with self.assertRaises(SystemExit):
                validate_skill(candidate)
            candidate.parent.mkdir()
            candidate.write_text("invalid candidate", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_skill(candidate)
            candidate.write_text(contents.replace("Read current docs.", "Compare current docs with source evidence."), encoding="utf-8")
            validate_skill(candidate)
            self.assertEqual(source.read_text(encoding="utf-8"), contents)
            snapshot, = (state / "snapshots").glob("*-SKILL.md")
            self.assertEqual(snapshot.read_text(encoding="utf-8"), contents)

    def test_proposal_frontmatter_and_status_transitions(self) -> None:
        skill_dir = Path("/tmp/Skill Dir")
        candidate_path = Path("/tmp/Proposals Dir/proposal-1-candidate/SKILL.md")
        proposal = build_proposal(
            proposal_id="proposal-1",
            skill_name="demo",
            skill_dir=skill_dir,
            skill_contents="line\n",
            report="# Report\n",
            snapshot_path=Path("/tmp/snapshots/source-SKILL.md"),
            candidate_path=candidate_path,
            timestamp="20260528T000000Z",
        )

        self.assertTrue(proposal.startswith("---\n"))
        self.assertIn('status: "draft"', proposal)
        self.assertIn('skill_name: "demo"', proposal)
        self.assertIn("generated draft is a worksheet, not yet a reviewable proposal", proposal)
        self.assertIn("- Decision: Undecided", proposal)
        self.assertIn("- Exact edit:", proposal)
        self.assertIn("Do not modify the source skill", proposal)
        self.assertIn("ATM_PAYLOAD_PYTHON:?set explicit prepared payload interpreter", proposal)
        self.assertIn("& $env:ATM_PAYLOAD_PYTHON -B", proposal)
        self.assertIn("Windows PowerShell:", proposal)
        self.assertGreaterEqual(proposal.count(" -B scripts/watcher skill validate "), 2)
        unix_command = next(
            line
            for line in proposal.splitlines()
            if line.startswith('"$atm_tooling_python" -B scripts/watcher skill validate')
        )
        unix_argv = shlex.split(unix_command)
        candidate_index = unix_argv.index("--candidate-skill")
        self.assertEqual(unix_argv[candidate_index + 1], str(candidate_path))
        self.assertNotEqual(candidate_path, skill_dir / "SKILL.md")
        self.assertIn("Validation has not run", proposal)

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            proposal_path = Path(tmp) / "proposal.md"
            proposal_path.write_text(
                "---\n"
                "proposal_id: proposal-1\n"
                "status: draft\n"
                "skill_name: demo\n"
                "---\n"
                "# Proposal\n",
                encoding="utf-8",
            )

            previous, _ = update_status(
                proposal_path,
                "needs-validation",
                state_dir=state_dir,
                reason="needs checks",
            )
            previous_rejected, rejected_path = update_status(
                proposal_path,
                "rejected",
                state_dir=state_dir,
                reason="bad evidence",
            )
            updated = proposal_path.read_text(encoding="utf-8")
            rejected_text = rejected_path.read_text(encoding="utf-8") if rejected_path is not None else ""
            rejected_exists = rejected_path.is_file() if rejected_path is not None else False

        self.assertEqual(previous, "draft")
        self.assertEqual(previous_rejected, "needs-validation")
        self.assertIsNotNone(rejected_path)
        self.assertTrue(rejected_exists)
        self.assertIn("status: rejected", updated)
        self.assertIn("bad evidence", rejected_text)

    def test_candidate_validator_distinguishes_documented_marker_from_placeholder(self) -> None:
        maintainer = ROOT.parents[1] / "plugins" / "maintenance" / "skills" / "skill-maintainer" / "SKILL.md"
        validate_skill(maintainer)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documented = root / "documented.md"
            documented.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n"
                "Explain that `[TODO:` starts an unfinished placeholder.\n",
                encoding="utf-8",
            )
            unresolved = root / "unresolved.md"
            unresolved.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n"
                "[TODO: replace this guidance]\n",
                encoding="utf-8",
            )

            validate_skill(documented)
            with self.assertRaises(SystemExit) as raised:
                validate_skill(unresolved)

        self.assertIn("contains a `[TODO: ...]` placeholder", str(raised.exception))

    def test_candidate_validator_marks_static_only_result_for_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "SKILL.md"
            candidate.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\nBody.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                result = validate_candidate_main(["--candidate-skill", str(candidate)])

        self.assertEqual(result, 0)
        self.assertIn("candidate static checks passed", stdout.getvalue())
        self.assertIn("human review is required", stdout.getvalue())

    def test_report_reader_and_state_support_incremental_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            log_file = state_dir / "logs" / "events.jsonl"
            log_file.parent.mkdir(parents=True)
            events = [
                {"timestamp": "2026-06-01T00:00:00Z", "skill_name": "demo", "outcome": "success"},
                {"timestamp": "2026-06-05T00:00:00Z", "skill_name": "demo", "outcome": "failure"},
                {"timestamp": "2026-06-06T00:00:00Z", "skill_name": "demo", "outcome": "success"},
            ]
            log_file.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            recent = read_events_since(log_file, parse_since("2026-06-05T00:00:00Z"), block_size=48)
            state = load_report_state(state_dir)
            key = report_state_key("demo")
            update_report_state(
                state,
                key=key,
                since=parse_since("2026-06-05T00:00:00Z"),
                until=datetime(2026, 6, 6, tzinfo=timezone.utc),
                event_count=len(recent),
                output=state_dir / "reports" / "demo.md",
                recent_hashes=[event_hash(event) for event in recent],
            )
            save_report_state(state_dir, state)
            loaded = load_report_state(state_dir)

        self.assertEqual([event["timestamp"] for event in recent], ["2026-06-05T00:00:00Z", "2026-06-06T00:00:00Z"])
        self.assertEqual(state_since(loaded, key), datetime(2026, 6, 6, tzinfo=timezone.utc))
        self.assertEqual(loaded["reports"][key]["last_event_count"], 2)
        self.assertEqual(len(loaded["reports"][key]["recent_event_hashes"]), 2)

    def test_report_uses_catalog_and_overlay_cache_without_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            state_dir = Path(tmp) / "state"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            write_attribution_overlay(
                root,
                "demo",
                {
                    "schema_version": 1,
                    "skills": {
                        "demo:entry": {
                            "role": "entrypoint",
                            "logical_group": "explicit-workflows",
                        }
                    },
                    "legacy_names": {"legacy:entry": "demo:entry"},
                },
            )
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text("{not-json\n", encoding="utf-8")
            write_dynamic_monitored_skills(state_dir, discover_skill_metadata(root))
            history = [
                {"timestamp": "2026-06-05T00:00:00Z", "event_type": kind,
                 "session_id": "historical", "skill_name": "demo:entry",
                 "skill_attribution": {"primary": {"name": "demo:entry", "role": "entrypoint"},
                                       "supporting": [], "effective": ["demo:entry"], "mentioned": []}}
                for kind in ("user_prompt_submit", "turn_summary")
            ]
            log_file = log_file_path(state_dir)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            original = "\n".join(json.dumps(event) for event in history) + "\n"
            log_file.write_text(original, encoding="utf-8")

            result = run_report_pipeline(
                ReportQuery(
                    state_dir=state_dir,
                    log_file=log_file_path(state_dir),
                ),
                ReportOutputPolicy(write_output=False),
            )

            self.assertEqual(log_file.read_text(encoding="utf-8"), original)

        self.assertIn("`demo:entry`", result.report)
        self.assertIn("explicit-workflows", result.report)
        self.assertEqual(result.event_count, 2)

    def test_report_pipeline_writes_report_state_and_counts_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            log_file = log_file_path(state_dir)
            log_file.parent.mkdir(parents=True)
            events = [
                {
                    "timestamp": "2026-06-05T00:00:00Z",
                    "event_type": "turn_summary",
                    "session_id": "s1",
                    "outcome": "unknown",
                    "task_outcome": "failure",
                    "skill_attribution": {
                        "primary": {"name": "demo", "role": "entrypoint"},
                        "supporting": [{"name": "support", "role": "discipline"}],
                        "effective": ["demo", "support"],
                        "mentioned": [],
                    },
                    "codex": {
                        "turn_id": "t1",
                        "turn_summary": {"task_outcome": "failure", "tool_failure_count": 2},
                    },
                },
                {
                    "timestamp": "2026-06-06T00:00:00Z",
                    "event_type": "turn_summary",
                    "session_id": "s2",
                    "outcome": "unknown",
                    "task_outcome": "success",
                    "skill_attribution": {
                        "primary": {"name": "demo", "role": "entrypoint"},
                        "supporting": [],
                        "effective": ["demo"],
                        "mentioned": [],
                    },
                    "codex": {
                        "turn_id": "t2",
                        "turn_summary": {"task_outcome": "success", "tool_failure_count": 0},
                    },
                },
            ]
            log_file.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            (state_dir / "skill-metadata-cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "skills": {
                            "demo": {"logical_group": "explicit-workflows"},
                            "support": {"logical_group": "implicit-primitives"},
                        },
                        "legacy_names": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_report_pipeline(
                ReportQuery(
                    state_dir=state_dir,
                    log_file=log_file,
                    skill="demo",
                    since_raw="2026-06-05T00:00:00Z",
                    incremental=True,
                ),
                ReportOutputPolicy(write_output=True),
            )
            loaded = load_report_state(state_dir)
            output_exists = result.output.is_file() if result.output is not None else False

        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.outcome_counts["failure"], 1)
        self.assertEqual(result.outcome_counts["success"], 1)
        self.assertIn("supporting-only", result.report)
        self.assertIn("`support`", result.report)
        self.assertIn("## Usage By Logical Group", result.report)
        self.assertIn("| explicit-workflows | 2 | 2 | 0 | `demo` |", result.report)
        self.assertIn("| implicit-primitives | 1 | 0 | 1 | `support` |", result.report)
        self.assertIn("| `demo` | entrypoint | explicit-workflows |", result.report)
        self.assertIsNotNone(result.output)
        self.assertTrue(output_exists)
        self.assertEqual(result.state_path, state_dir / "report-state.json")
        self.assertEqual(loaded["reports"]["demo"]["last_event_count"], 2)


if __name__ == "__main__":
    unittest.main()
