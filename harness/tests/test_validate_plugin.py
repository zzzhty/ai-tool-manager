from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate_plugin.py"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class PluginValidatorTests(unittest.TestCase):
    def run_validator(self, plugin_root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(plugin_root)],
            text=True,
            capture_output=True,
        )

    def test_current_first_party_plugins_pass(self) -> None:
        for plugin_name in ("watcher", "workflow", "mattpocock-skills"):
            with self.subTest(plugin=plugin_name):
                result = self.run_validator(REPO_ROOT / "plugins" / plugin_name)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertIn("Plugin validation passed", result.stdout)

    def test_missing_required_manifest_value_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = Path(tmp) / "demo"
            write_json(
                plugin_root / ".codex-plugin" / "plugin.json",
                {"name": "demo", "version": "1.0.0"},
            )

            result = self.run_validator(plugin_root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("field `description` must be a non-empty string", result.stdout)

    def test_new_runtime_hook_path_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = Path(tmp) / "demo"
            write_json(plugin_root / "hooks" / "hooks.json", {"hooks": {}})
            write_json(
                plugin_root / ".codex-plugin" / "plugin.json",
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "description": "Demo plugin.",
                    "hooks": "./hooks/hooks.json",
                },
            )

            result = self.run_validator(plugin_root)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_component_path_cannot_escape_plugin_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "demo"
            (root / "outside").mkdir()
            write_json(
                plugin_root / ".codex-plugin" / "plugin.json",
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "description": "Demo plugin.",
                    "skills": "../outside",
                },
            )

            result = self.run_validator(plugin_root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("must stay inside the plugin root", result.stdout)

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_linked_plugin_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "demo"
            write_json(
                plugin_root / ".codex-plugin" / "plugin.json",
                {
                    "name": "demo",
                    "version": "1.0.0",
                    "description": "Demo plugin.",
                },
            )
            linked_root = root / "linked-demo"
            linked_root.symlink_to(plugin_root, target_is_directory=True)

            result = self.run_validator(linked_root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("plugin root must be an ordinary directory", result.stdout)


if __name__ == "__main__":
    unittest.main()
