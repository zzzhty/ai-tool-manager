"""Real public wrappers and manager closure with offline dependency provisioning.

Only dependency acquisition is substituted: disposable real venvs import the
test runner's installed dependencies through a .pth file instead of using pip.
No real manager home, client configuration or network source is used.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git"), "requires Git")
class PublicInstallerRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.user = self.root / "isolated user"
        self.user.mkdir()
        self.home = self.user / ".atm"
        self.origin = self.root / "local origin"
        self.origin.mkdir()
        for name in ("scripts", "plugins", "agents", ".agents"):
            shutil.copytree(ROOT / name, self.origin / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        for name in ("VERSION", "requirements.txt", "AGENTS.md"):
            shutil.copy2(ROOT / name, self.origin / name)
        dependencies = [path for path in sys.path if "site-packages" in path]
        (self.origin / "scripts/bootstrap_tooling_env.py").write_text(
            "import argparse, os, pathlib, venv\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--venv', required=True)\n"
            "p.add_argument('--rebuild', action='store_true')\n"
            "a = p.parse_args()\n"
            "root = pathlib.Path(a.venv)\n"
            "if not root.exists():\n"
            "    venv.EnvBuilder(with_pip=False).create(root)\n"
            "site = root / 'Lib/site-packages' if os.name == 'nt' else next((root / 'lib').glob('python*/site-packages'))\n"
            f"(site / 'offline-fixture.pth').write_text({chr(10).join(dependencies) + chr(10)!r}, encoding='utf-8')\n",
            encoding="utf-8",
        )
        self.environment = {
            **os.environ, "HOME": str(self.user), "USERPROFILE": str(self.user),
            "XDG_CONFIG_HOME": str(self.user / ".config"),
            "CODEX_HOME": str(self.user / ".codex"), "COPILOT_HOME": str(self.user / ".copilot"),
            "CLAUDE_CONFIG_DIR": str(self.user / ".claude"), "GEMINI_CLI_HOME": str(self.user),
            "PI_CODING_AGENT_DIR": str(self.user / ".pi/agent"),
            "ATM_HOME": str(self.home), "ATM_BOOTSTRAP_PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1", "PLUGIN_VALIDATOR": str(self.origin / "scripts/validate_plugin.py"),
        }
        for args in (("init", "-b", "main"), ("config", "user.name", "Integration Test"),
                     ("config", "user.email", "test@example.invalid"), ("add", "."), ("commit", "-m", "fixture")):
            self.git(self.origin, *args)
        self.initial = self.git(self.origin, "rev-parse", "HEAD")
        # Exercise Git's normal transport without network access. A path source
        # uses loose-object copying, which failed in the Linux CI fixture.
        self.install("--repository", self.origin.as_uri(), "--harness", "copilot", "--yes")
        self.receipt = (self.home / "state/install.json").read_bytes()

    def git(self, repo, *args):
        result = subprocess.run(["git", "-C", str(repo), *args], env=self.environment,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def install(self, *args, expected=0, installer_root=ROOT):
        # The retired install.sh checkout mode exec'd the Python installer with
        # the caller's arguments; invoke that installer directly.
        command = [sys.executable, str(installer_root / "scripts/install_engine.py")]
        result = subprocess.run([*command, "--home", str(self.home), "--no-path", *args],
                                env=self.environment, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def check(self):
        launcher = self.home / "bin" / ("omh.cmd" if os.name == "nt" else "omh")
        result = subprocess.run([str(launcher), "check"], env=self.environment,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_repair_and_reinstall_keep_exact_version_state_and_user_data(self):
        self.install("--yes", expected=1)
        result = self.install("--repair", "--reinstall", expected=2)
        self.assertIn("not allowed", result.stderr)
        desired_path = self.home / "state/desired.json"
        desired = json.loads(desired_path.read_text())
        desired["updatePolicy"]["channel"] = "stable"
        desired["updatePolicy"]["extraPolicy"] = "keep"
        desired_path.write_text(json.dumps(desired))
        desired_bytes = desired_path.read_bytes()
        # Exercise the actual managed source without a test-only bytecode guard.
        del self.environment["PYTHONDONTWRITEBYTECODE"]
        try:
            for mode in ("--repair", "--reinstall"):
                self.install(mode, "--dry-run", installer_root=self.home / "repo")
                self.assertEqual(desired_path.read_bytes(), desired_bytes)
                self.assertEqual(list((self.home / "repo").rglob("__pycache__")), [])
        finally:
            self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        (self.home / "repo/unpublished-note").write_text("keep checkout data")
        (self.home / "venv/user-note").write_text("keep runtime data")
        (self.home / "notes").write_text("keep manager data")
        unrelated = self.user / ".copilot/skills/user-skill"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_text("user skill")
        launcher = self.home / "bin" / ("omh.cmd" if os.name == "nt" else "omh")
        launcher.write_text("damaged launcher")
        self.install("--repair")
        self.check()
        (self.origin / "new-release").write_text("remote advanced")
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "-m", "advance remote")
        self.install("--reinstall")
        self.check()
        self.assertEqual(self.git(self.home / "repo", "rev-parse", "HEAD"), self.initial)
        self.assertEqual((self.home / "state/install.json").read_bytes(), self.receipt)
        self.assertEqual(desired_path.read_bytes(), desired_bytes)
        self.assertEqual((self.home / "notes").read_text(), "keep manager data")
        self.assertEqual((unrelated / "SKILL.md").read_text(), "user skill")
        backups = self.home / "state/repair-backups"
        self.assertTrue(any((path / "unpublished-note").is_file() for path in backups.glob("repo-*")))
        self.assertTrue(any((path / "user-note").is_file() for path in backups.glob("venv-*")))

    def test_legacy_migration_tracks_current_checkout_and_missing_repo_can_recover(self):
        (self.origin / "later-version").write_text("legacy ready checkout advanced")
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "-m", "later legacy version")
        current = self.git(self.origin, "rev-parse", "HEAD")
        self.git(self.home / "repo", "fetch", "origin")
        self.git(self.home / "repo", "checkout", "--detach", current)
        (self.home / "state/manager.json").unlink()
        (self.home / "state/desired.json").unlink()
        self.install("--repair", "--dry-run")
        self.assertFalse((self.home / "state/manager.json").exists())
        self.install("--repair")
        manager = json.loads((self.home / "state/manager.json").read_text())
        self.assertEqual(manager["revision"], current)
        self.assertNotEqual(current, self.initial)
        self.assertEqual((self.home / "state/install.json").read_bytes(), self.receipt)
        (self.home / "repo").rename(self.root / "removed checkout")
        self.install("--repair")
        self.assertEqual(self.git(self.home / "repo", "rev-parse", "HEAD"), current)
        self.assertEqual((self.home / "state/install.json").read_bytes(), self.receipt)
        self.check()


if __name__ == "__main__":
    unittest.main()
