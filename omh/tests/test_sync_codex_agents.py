from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_codex_agents  # noqa: E402


class CodexAgentSupportMigrationTests(unittest.TestCase):
    def test_retired_manager_marker_is_recognized_only_for_in_place_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "operating-principles.md"
            target.write_text(
                "# Managed by my-codex scripts/sync_codex_agents.py.\n"
                "# Source: agents/operating-principles.md\n"
                "# Do not edit this target file directly.\n\n"
                "old managed content\n",
                encoding="utf-8",
            )
            self.assertTrue(sync_codex_agents.is_managed(target))

            target.write_text("unmanaged content\n", encoding="utf-8")
            self.assertFalse(sync_codex_agents.is_managed(target))


if __name__ == "__main__":
    unittest.main()
