"""Payload-only snapshot contracts; fixtures need no installer or skill tree."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME / "scripts"))
from watcher_runtime import cli
from watcher_runtime.repository_source import resolve_repository_source, load_repository_skill_catalog
from watcher_runtime.skill.catalog_metadata import discover_skill_metadata, write_dynamic_monitored_skills


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ATM_TEST_ONLY_快照 ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "runtimes/watcher/scripts").mkdir(parents=True)
        (self.root / "runtimes/watcher/scripts/watcher").write_text("# fixture runtime\n")
        self.catalog = {
            "schemaVersion": 1, "product": "atm-harness-catalog", "sourceIdentity": "a" * 64,
            "skills": [{"id": "watcher:doc-alignment", "plugin": "maintenance", "name": "doc-alignment",
                        "directoryName": "doc-alignment", "path": "plugins/maintenance/skills/doc-alignment",
                        "aliases": ["maintenance:doc-alignment"]}],
            "attributionOverlays": [{"plugin": "maintenance", "path": "plugins/maintenance/.codex-plugin/skill-watcher.json",
                 "data": {"schema_version": 1, "skills": {"watcher:doc-alignment": {"role": "discipline"}},
                          "legacy_names": {"doc-watcher:doc-alignment": "watcher:doc-alignment"}}}],
        }
        self.save()

    def save(self) -> None:
        (self.root / "canonical-catalog.json").write_text(json.dumps(self.catalog), encoding="utf-8")

    def test_snapshot_works_without_repository_or_plugin_tree(self) -> None:
        self.assertFalse((self.root / "plugins").exists())
        self.assertFalse((self.root / "scripts").exists())
        metadata = discover_skill_metadata(self.root)
        self.assertEqual(list(metadata["skills"]), ["watcher:doc-alignment"])
        self.assertEqual(metadata["source_identity"], "a" * 64)
        self.assertEqual(metadata["legacy_names"]["maintenance:doc-alignment"], "watcher:doc-alignment")
        self.assertEqual(metadata["legacy_names"]["doc-watcher:doc-alignment"], "watcher:doc-alignment")

    def test_installer_file_is_never_imported_and_missing_snapshot_has_no_fallback(self) -> None:
        scripts = self.root / "scripts"
        scripts.mkdir()
        marker = self.root / "unexpected-import"
        (scripts / "repo_skill_catalog.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\nraise RuntimeError('poison installer')\n",
            encoding="utf-8",
        )
        discover_skill_metadata(self.root)
        self.assertFalse(marker.exists())
        (self.root / "canonical-catalog.json").unlink()
        with self.assertRaises(SystemExit):
            discover_skill_metadata(self.root)
        self.assertFalse(marker.exists())

    def test_unsupported_versions_and_products_fail_without_runtime_writes(self) -> None:
        for key, value in (("schemaVersion", 2), ("schemaVersion", True), ("product", "other"), ("sourceIdentity", "not-a-hash")):
            with self.subTest(key=key, value=value):
                original = self.catalog[key]
                self.catalog[key] = value
                self.save()
                with self.assertRaises(SystemExit):
                    discover_skill_metadata(self.root)
                self.catalog[key] = original
        self.assertFalse((self.root / "state").exists())

    def test_paths_and_duplicate_identities_are_rejected(self) -> None:
        baseline = copy.deepcopy(self.catalog)
        for path in ("../outside", "/absolute", "C:\\outside", "plugins/other/skills/doc-alignment", "plugins/maintenance/skills/../doc-alignment"):
            self.catalog = copy.deepcopy(baseline)
            self.catalog["skills"][0]["path"] = path
            self.save()
            with self.subTest(path=path), self.assertRaises(SystemExit):
                discover_skill_metadata(self.root)
        self.catalog = baseline
        self.catalog["skills"].append(copy.deepcopy(self.catalog["skills"][0]))
        self.save()
        with self.assertRaises(SystemExit):
            discover_skill_metadata(self.root)

    def test_duplicate_json_fields_are_rejected(self) -> None:
        (self.root / "canonical-catalog.json").write_text('{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaisesRegex(SystemExit, "duplicate JSON key"):
            load_repository_skill_catalog(resolve_repository_source(self.root))

    def test_current_and_historical_names_keep_one_attribution_identity(self) -> None:
        for identity in ("watcher:doc-alignment", "maintenance:doc-alignment", "doc-watcher:doc-alignment"):
            with self.subTest(identity=identity):
                metadata = discover_skill_metadata(self.root)
                self.assertEqual(metadata["legacy_names"].get(identity, identity), "watcher:doc-alignment")

    def test_explicit_metadata_refresh_preserves_existing_logs(self) -> None:
        state = self.root / "state"
        log = state / "logs/events.jsonl"
        log.parent.mkdir(parents=True)
        history = b'{"event_type":"historical","skill_name":"doc-watcher:doc-alignment"}\n'
        log.write_bytes(history)
        write_dynamic_monitored_skills(state, discover_skill_metadata(self.root))
        self.assertEqual(log.read_bytes(), history)
        metadata = json.loads((state / "skill-metadata-cache.json").read_text())
        self.assertEqual(metadata["source_identity"], "a" * 64)
        self.assertFalse((self.root / "hooks.json").exists())

    def test_retired_observer_refuses_without_writing_state(self) -> None:
        env = os.environ.copy()
        env["HOME"] = str(self.root / "fake-home")
        env["USERPROFILE"] = env["HOME"]
        env["CODEX_HOME"] = str(self.root / "fake-codex")
        command = [sys.executable, "-S", "-B", str(RUNTIME / "scripts/watcher"), "skill", "observe", "--repo-root", str(self.root), "--dry-run"]
        result = subprocess.run(command, input=json.dumps({"hook_event_name": "UserPromptSubmit", "skill_name": "maintenance:doc-alignment"}), env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown skill command: observe", result.stderr)
        self.assertFalse(Path(env["CODEX_HOME"]).exists())

    def test_python_cli_has_no_hook_install_or_uninstall_entrypoints(self) -> None:
        self.assertNotIn("install-hook", cli.COMMAND_MODULES["skill"])
        self.assertNotIn("uninstall-hook", cli.COMMAND_MODULES["skill"])
        with mock.patch("sys.stderr"), mock.patch("sys.stdout"):
            for command in ("install-hook", "uninstall-hook", "observe"):
                self.assertNotEqual(cli.main(["skill", command, "--apply"]), 0)
        self.assertFalse((self.root / "hooks.json").exists())
