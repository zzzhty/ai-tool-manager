from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import terminal_output  # noqa: E402


class InteractiveStream(io.StringIO):
    def isatty(self) -> bool:
        return True


class TerminalOutputTests(unittest.TestCase):
    def test_emphasis_is_interactive_and_respects_plain_output_controls(self) -> None:
        interactive = InteractiveStream()
        redirected = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            os.environ.pop("TERM", None)
            self.assertEqual(
                terminal_output.emphasize(
                    "error: failed with exit code 23",
                    color="red",
                    stream=interactive,
                ),
                "\x1b[1;31merror: failed with exit code 23\x1b[0m",
            )
            self.assertEqual(
                terminal_output.emphasize(
                    "action required: rerun with --migrate-marketplace",
                    color="yellow",
                    stream=interactive,
                ),
                "\x1b[1;33maction required: rerun with --migrate-marketplace\x1b[0m",
            )
            self.assertEqual(
                terminal_output.emphasize("error: plain log", color="red", stream=redirected),
                "error: plain log",
            )

            os.environ["NO_COLOR"] = "1"
            self.assertEqual(
                terminal_output.emphasize(
                    "error: explicitly plain",
                    color="red",
                    stream=interactive,
                ),
                "error: explicitly plain",
            )


if __name__ == "__main__":
    unittest.main()
