from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from manager_paths import manager_home, venv_path, venv_python  # noqa: E402


class ManagerPathTests(unittest.TestCase):
    def test_default_home_and_venv_are_harness_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            user_home = Path(tmp) / "users" / "tester"
            home = manager_home(environ={}, user_home=user_home)

            self.assertEqual(home, user_home / ".oh-my-harness")
            self.assertEqual(venv_path(home), user_home / ".oh-my-harness" / "venv")

    def test_environment_override_is_the_manager_root_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp)
            configured_home = fixture_root / "srv" / "omh"
            home = manager_home(
                environ={"OH_MY_HARNESS_HOME": str(configured_home)},
                user_home=fixture_root / "ignored",
            )

            self.assertEqual(home, configured_home)

    def test_empty_environment_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "must not be empty"):
                manager_home(
                    environ={"OH_MY_HARNESS_HOME": "  "},
                    user_home=Path(tmp) / "users" / "tester",
                )

    def test_relative_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "must be an absolute path"):
                manager_home(
                    environ={"OH_MY_HARNESS_HOME": "relative/home"},
                    user_home=Path(tmp) / "users" / "tester",
                )

    def test_venv_interpreter_uses_the_platform_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "manager" / "venv"
            path = venv_python(venv)
            expected = (
                venv / "Scripts" / "python.exe"
                if sys.platform == "win32"
                else venv / "bin" / "python"
            )
            self.assertEqual(path, expected)


if __name__ == "__main__":
    unittest.main()
