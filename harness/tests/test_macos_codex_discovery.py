from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import refresh_harness  # noqa: E402


class MacOSCodexDiscoveryTests(unittest.TestCase):
    def test_macos_app_bundle_is_managed_fallback_before_vscode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_home = root / "home"
            codex_home = user_home / ".codex"
            applications = root / "Applications"
            app_cli = applications / "ChatGPT.app" / "Contents" / "Resources" / "codex"
            extension_cli = (
                user_home
                / ".vscode"
                / "extensions"
                / "openai.chatgpt-1.2.3"
                / "bin"
                / "macos-aarch64"
                / "codex"
            )
            for candidate in (app_cli, extension_cli):
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("", encoding="utf-8")

            with mock.patch.object(refresh_harness.sys, "platform", "darwin"):
                with mock.patch("refresh_harness.platform.machine", return_value="arm64"):
                    with mock.patch.object(
                        refresh_harness,
                        "MACOS_APPLICATION_DIRS",
                        (applications,),
                    ):
                        with mock.patch.dict(os.environ, {"HOME": str(user_home)}, clear=True):
                            with mock.patch("refresh_harness.shutil.which", return_value=None):
                                self.assertEqual(
                                    refresh_harness.resolve_codex_executable(None, codex_home=codex_home),
                                    str(app_cli),
                                )
                                app_cli.unlink()
                                self.assertEqual(
                                    refresh_harness.resolve_codex_executable(None, codex_home=codex_home),
                                    str(extension_cli),
                                )

    def test_path_still_precedes_macos_app_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_home = root / "home"
            codex_home = user_home / ".codex"
            applications = root / "Applications"
            app_cli = applications / "ChatGPT.app" / "Contents" / "Resources" / "codex"
            app_cli.parent.mkdir(parents=True, exist_ok=True)
            app_cli.write_text("", encoding="utf-8")
            path_cli = root / "path" / "codex"

            with mock.patch.object(refresh_harness.sys, "platform", "darwin"):
                with mock.patch.object(
                    refresh_harness,
                    "MACOS_APPLICATION_DIRS",
                    (applications,),
                ):
                    with mock.patch.dict(os.environ, {"HOME": str(user_home)}, clear=True):
                        with mock.patch("refresh_harness.shutil.which", return_value=str(path_cli)):
                            self.assertEqual(
                                refresh_harness.resolve_codex_executable(None, codex_home=codex_home),
                                str(path_cli),
                            )


if __name__ == "__main__":
    unittest.main()
