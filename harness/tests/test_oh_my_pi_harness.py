"""Oh My Pi agent lifecycle through the real CLI, local Git and isolated user homes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_agents_skills as projection
from harness_registry import load_harness_registry, resolve_harness_plan
from repo_skill_catalog import load_repo_skill_catalog


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class OhMyPiLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="atm-oh-my-pi-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.user = self.root / "user"
        self.user.mkdir()
        self.home = self.user / "manager with spaces"
        self.origin = self.root / "local-origin"
        self.repo = self.home / "repo"
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("OPENCLAW_", "ATM_", "OMP_", "PI_"))
            and key not in {"CODEX_HOME", "CLAUDE_CONFIG_DIR", "COPILOT_HOME", "GEMINI_CLI_HOME",
                           "ZDOTDIR", "XDG_CONFIG_HOME", "PYTHONPATH"}
        }
        self.env.update(HOME=str(self.user), USERPROFILE=str(self.user),
                        ATM_HOME=str(self.home), CODEX_HOME=str(self.user / ".codex"),
                        ATM_BOOTSTRAP_PYTHON=sys.executable,
                        PYTHONPATH=os.pathsep.join(site.getsitepackages()), PYTHONDONTWRITEBYTECODE="1",
                        SHELL="/bin/bash", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
        # The vendored engine tree is not itself a Git checkout; build the
        # disposable origin directly from the current working tree. Updates
        # follow this origin's main, regardless of the runner's branch.
        self.origin.mkdir()
        self.git(self.origin, "init", "--quiet", "-b", "main")
        shutil.copytree(ROOT, self.origin, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
        # Substitute only dependency acquisition. No network or package installs.
        (self.origin / "scripts/bootstrap_tooling_env.py").write_text(
            "import argparse, pathlib, venv\n"
            "p = argparse.ArgumentParser(); p.add_argument('--venv', required=True)\n"
            "a = p.parse_args(); root = pathlib.Path(a.venv)\n"
            "if not root.exists(): venv.EnvBuilder(with_pip=False).create(root)\n",
            encoding="utf-8",
        )
        self.git(self.origin, "add", "--all")
        self.commit("Oh My Pi test fixture")
        self.git(self.origin, "clone", "--quiet", "--no-hardlinks", str(self.origin), str(self.repo))
        state = self.home / "state"
        state.mkdir()
        (state / "install.json").write_text(json.dumps({
            "product": "atm-harness", "status": "installing", "repository": str(self.origin),
            "revision": self.git(self.repo, "rev-parse", "HEAD").stdout.strip(),
            "ref": "main", "harness": "oh-my-pi",
        }), encoding="utf-8")
        self.initial = (state / "install.json").read_bytes()
        self.catalog = load_repo_skill_catalog(self.repo)

    def git(self, cwd, *arguments):
        result = subprocess.run(["git", "-C", str(cwd), *arguments], env=self.env,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def commit(self, message):
        self.git(self.origin, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--quiet", "-m", message)

    def cli(self, *arguments, success=True, environment=None):
        result = subprocess.run([sys.executable, str(self.repo / "scripts/engine.py"),
                                 "--home", str(self.home), *arguments],
                                env=environment or self.env, text=True, capture_output=True, timeout=60)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def plan(self):
        registry = load_harness_registry(self.repo / ".agents/harnesses/registry.json", repo_root=self.repo)
        return resolve_harness_plan(registry, "oh-my-pi", repo_root=self.repo,
                                    environ=self.env, user_home=self.user)

    def desired(self):
        return json.loads((self.home / "state/desired.json").read_text())["harnesses"]

    def snapshot(self):
        # Include timestamps and bytes so read-only commands cannot hide rewrites.
        result = {}
        for path in self.user.rglob("*"):
            if ".git" in path.parts:
                continue
            stat = path.lstat()
            content = (str(path.resolve()) if projection.is_projection_link(path) else
                       hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "directory")
            result[str(path.relative_to(self.user))] = (stat.st_mode, stat.st_mtime_ns, content)
        return result

    def protect_user_files(self):
        root = self.plan().root
        root.mkdir(parents=True, exist_ok=True)
        self.protected = {}
        for relative in ("config.yml", "RULES.md", ".env", "managed-skills/user-note/SKILL.md",
                         "skills/user-skill/SKILL.md"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = b"user-owned content\n"
            path.write_bytes(content)
            self.protected[path] = content

    def assert_protected(self):
        for path, content in self.protected.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assertEqual((self.home / "state/install.json").read_bytes(), self.initial)

    def test_install_refresh_check_dry_runs_and_remove_preserve_user_files(self):
        self.protect_user_files()
        before = self.snapshot()
        self.cli("install", "omp", "--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.cli("install", "omp", "--yes")
        self.assertEqual(self.desired(), ["oh-my-pi"])
        self.assertTrue((self.home / "state/harnesses/oh-my-pi.json").exists())
        self.assertFalse((self.home / "state/harnesses/omp.json").exists())
        plan = self.plan()
        self.assertEqual(
            (plan.root / "AGENTS.md").read_bytes(),
            (self.repo / "agents/global-instructions.md").read_bytes(),
        )
        for source in self.catalog.sources:
            link = plan.skills_root / source.name
            self.assertTrue(projection.is_projection_link(link))
            self.assertEqual(link.resolve(), source.path.resolve())
            self.assertEqual((link / "SKILL.md").read_bytes(), (source.path / "SKILL.md").read_bytes())
        for command in (("status", "--json"), ("check",), ("doctor",),
                        ("refresh", "--dry-run"), ("remove", "omp", "--dry-run")):
            before = self.snapshot()
            self.cli(*command)
            self.assertEqual(self.snapshot(), before, command)
        removed = plan.skills_root / self.catalog.sources[0].name
        projection.remove_projection_link(removed, self.catalog, expected_destination=removed.resolve())
        self.cli("check", "omp", success=False)
        self.cli("refresh")
        self.assertTrue(projection.is_projection_link(removed))
        self.cli("remove", "omp", "--yes")
        self.assertEqual(self.desired(), [])
        self.assertFalse((self.home / "state/harnesses/oh-my-pi.json").exists())
        self.assertFalse(os.path.lexists(plan.root / "AGENTS.md"))
        for source in self.catalog.sources:
            self.assertFalse(os.path.lexists(plan.skills_root / source.name))
        self.assert_protected()

    def test_pi_coding_agent_dir_relocation_is_recorded_and_drift_blocks_removal(self):
        self.env["PI_CODING_AGENT_DIR"] = str(self.user / "relocated agent")
        self.protect_user_files()
        self.cli("install", "omp", "--yes")
        receipt = json.loads((self.home / "state/harnesses/oh-my-pi.json").read_text())
        self.assertEqual(receipt["root"], str(self.user / "relocated agent"))
        self.assertFalse((self.user / ".omp").exists())
        changed = dict(self.env, PI_CODING_AGENT_DIR=str(self.user / "other-agent"))
        result = self.cli("remove", "omp", "--yes", environment=changed, success=False)
        self.assertIn("recorded root", result.stderr)
        self.assertEqual(self.desired(), ["oh-my-pi"])
        self.cli("refresh")
        self.cli("check")
        self.cli("remove", "omp", "--yes")
        self.assert_protected()

    def test_shared_relocated_agent_directory_with_pi_agent_keeps_last_consumer_resources(self):
        self.env["PI_CODING_AGENT_DIR"] = str(self.user / "shared agent")
        self.protect_user_files()
        for first, second in (("oh-my-pi", "pi-agent"), ("pi-agent", "oh-my-pi")):
            with self.subTest(first=first):
                self.cli("install", "omp", "pi-agent", "--yes")
                plan = self.plan()
                instructions = plan.root / "AGENTS.md"
                self.assertEqual(
                    instructions.read_bytes(),
                    (self.repo / "agents/global-instructions.md").read_bytes(),
                )
                link = plan.skills_root / self.catalog.sources[0].name
                self.cli("remove", first, "--yes")
                self.assertTrue(projection.is_projection_link(link))
                self.assertTrue(instructions.exists())
                self.assertEqual(self.desired(), [second])
                self.cli("remove", second, "--yes")
                self.assertFalse(os.path.lexists(link))
                self.assertFalse(instructions.exists())
                self.assertEqual(self.desired(), [])
                self.assert_protected()


if __name__ == "__main__":
    unittest.main()
