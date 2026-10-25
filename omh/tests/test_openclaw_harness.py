"""OpenClaw lifecycle through the real CLI, local Git and isolated user homes."""
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_agents_skills as projection
from harness_registry import load_harness_registry, resolve_harness_plan
from repo_skill_catalog import load_repo_skill_catalog
from sync_harness_instructions import (
    apply_instruction_sync, check_instruction_sync, prepare_instruction_sync, remove_instruction_sync,
)


@unittest.skipUnless(shutil.which("git"), "requires local Git")
class OpenClawLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="omh-openclaw-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.user = self.root / "user"
        self.user.mkdir()
        self.home = self.user / "manager with spaces"
        self.origin = self.root / "local-origin"
        self.repo = self.home / "repo"
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("OPENCLAW_", "OH_MY_HARNESS_"))
            and key not in {"CODEX_HOME", "CLAUDE_CONFIG_DIR", "COPILOT_HOME", "GEMINI_CLI_HOME",
                           "PI_CODING_AGENT_DIR", "ZDOTDIR", "XDG_CONFIG_HOME", "PYTHONPATH"}
        }
        self.env.update(HOME=str(self.user), USERPROFILE=str(self.user),
                        OH_MY_HARNESS_HOME=str(self.home), CODEX_HOME=str(self.user / ".codex"),
                        OH_MY_HARNESS_BOOTSTRAP_PYTHON=sys.executable,
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
        self.commit("OpenClaw test fixture")
        self.git(self.origin, "clone", "--quiet", "--no-hardlinks", str(self.origin), str(self.repo))
        state = self.home / "state"
        state.mkdir()
        (state / "install.json").write_text(json.dumps({
            "product": "oh-my-harness", "status": "installing", "repository": str(self.origin),
            "revision": self.git(self.repo, "rev-parse", "HEAD").stdout.strip(),
            "ref": "main", "harness": "openclaw",
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
        result = subprocess.run([sys.executable, str(self.repo / "scripts/omh.py"),
                                 "--home", str(self.home), *arguments],
                                env=environment or self.env, text=True, capture_output=True, timeout=60)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def plan(self):
        registry = load_harness_registry(self.repo / ".agents/harnesses/registry.json", repo_root=self.repo)
        return resolve_harness_plan(registry, "openclaw", repo_root=self.repo,
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
        for relative in ("AGENTS.md", "SOUL.md", "AGENTS.override.md", "openclaw.json",
                         "workspace/AGENTS.md", "workspace/SOUL.md", "skills/.clawhub/lock.json",
                         "skills/user-skill/SKILL.md", "skills/user-skill/.clawhub/origin.json"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            content = b"{}\n" if path.suffix == ".json" else b"user-owned content\n"
            path.write_bytes(content)
            self.protected[path] = content

    def assert_protected(self):
        for path, content in self.protected.items():
            self.assertEqual(path.read_bytes(), content, path)
        self.assertEqual((self.home / "state/install.json").read_bytes(), self.initial)

    def test_install_refresh_check_dry_runs_and_remove_preserve_user_files(self):
        self.protect_user_files()
        before = self.snapshot()
        self.cli("install", "openclaw", "--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.cli("install", "openclaw")  # No instructions creation prompt, even without --yes.
        self.assertEqual(self.desired(), ["openclaw"])
        plan = self.plan()
        for source in self.catalog.sources:
            link = plan.skills_root / source.name
            self.assertTrue(projection.is_projection_link(link))
            self.assertEqual(link.resolve(), source.path.resolve())
            self.assertEqual((link / "SKILL.md").read_bytes(), (source.path / "SKILL.md").read_bytes())
        for command in (("status", "--json"), ("check",), ("doctor",),
                        ("refresh", "--dry-run"), ("remove", "openclaw", "--dry-run")):
            before = self.snapshot()
            self.cli(*command)
            self.assertEqual(self.snapshot(), before, command)
        removed = plan.skills_root / self.catalog.sources[0].name
        projection.remove_projection_link(removed, self.catalog, expected_destination=removed.resolve())
        self.cli("check", "openclaw", success=False)
        self.cli("refresh")
        self.assertTrue(projection.is_projection_link(removed))
        self.cli("remove", "openclaw", "--yes")
        self.assertEqual(self.desired(), [])
        self.assertFalse((self.home / "state/harnesses/openclaw.json").exists())
        for source in self.catalog.sources:
            self.assertFalse(os.path.lexists(plan.skills_root / source.name))
        self.assert_protected()

    def test_nondefault_state_is_recorded_and_root_drift_blocks_removal(self):
        self.env.update(OPENCLAW_STATE_DIR=str(self.user / "custom state"), OPENCLAW_PROFILE="work")
        self.protect_user_files()
        self.cli("install", "openclaw")
        receipt = json.loads((self.home / "state/harnesses/openclaw.json").read_text())
        self.assertEqual(receipt["root"], str(self.user / "custom state"))
        self.assertFalse((self.user / ".openclaw").exists())
        changed = dict(self.env, OPENCLAW_STATE_DIR=str(self.user / "other-state"))
        result = self.cli("remove", "openclaw", "--yes", environment=changed, success=False)
        self.assertIn("recorded root", result.stderr)
        self.assertEqual(self.desired(), ["openclaw"])
        self.cli("refresh")
        self.cli("check")
        self.cli("remove", "openclaw", "--yes")
        self.assert_protected()

    def test_named_profile_lifecycle_and_default_state_remain_separate(self):
        self.env.update(OPENCLAW_PROFILE="work", OPENCLAW_HOME=str(self.user / "service-home"))
        self.protect_user_files()
        self.cli("install", "openclaw")
        self.assertEqual(self.plan().root, self.user / "service-home/.openclaw-work")
        self.assertFalse((self.user / ".openclaw").exists())
        self.cli("refresh")
        self.cli("check")
        self.cli("remove", "openclaw", "--yes")
        self.assert_protected()

    def test_skills_only_shared_root_preserves_the_other_harness_consumer(self):
        self.protect_user_files()
        self.env["CLAUDE_CONFIG_DIR"] = str(self.plan().root)
        for first, second in (("openclaw", "claude"), ("claude", "openclaw")):
            with self.subTest(first=first):
                self.cli("install", "openclaw", "claude", "--yes")
                instructions = self.plan().root / "CLAUDE.md"
                link = self.plan().skills_root / self.catalog.sources[0].name
                self.cli("remove", first, "--yes")
                self.assertTrue(projection.is_projection_link(link))
                self.assertEqual(instructions.exists(), first == "openclaw")
                self.cli("remove", second, "--yes")
                self.assertFalse(os.path.lexists(link))
                self.assertFalse(instructions.exists())
                self.assertEqual(self.desired(), [])
                self.assert_protected()

    def test_excluded_personal_skill_root_still_blocks_before_projection(self):
        skill = self.user / ".agents/skills" / self.catalog.sources[0].name
        skill.mkdir(parents=True)
        content = f"---\nname: {self.catalog.sources[0].name}\ndescription: user copy\n---\n"
        (skill / "SKILL.md").write_text(content)
        result = self.cli("install", "openclaw", "--yes", success=False)
        self.assertIn("excluded skill root", result.stderr)
        self.assertFalse(self.plan().root.exists())
        self.assertEqual(self.desired(), [])
        self.assertEqual((skill / "SKILL.md").read_text(), content)

    def test_same_name_clawhub_skill_is_preserved_on_install_and_remove(self):
        self.protect_user_files()
        target = self.plan().skills_root / self.catalog.sources[0].name
        target.mkdir()
        (target / "SKILL.md").write_text("user-owned ClawHub skill\n")
        (target / ".clawhub").mkdir()
        (target / ".clawhub/origin.json").write_text("{}\n")
        result = self.cli("install", "openclaw", "--yes", success=False)
        self.assertIn("unmanaged", result.stderr)
        self.assertEqual(self.desired(), [])
        self.assertEqual((target / "SKILL.md").read_text(), "user-owned ClawHub skill\n")
        self.assertTrue((target / ".clawhub/origin.json").exists())
        # Replace only this fixture's known user skill to simulate a later successful install.
        shutil.rmtree(target)
        self.cli("install", "openclaw")
        projection.remove_projection_link(target, self.catalog, expected_destination=target.resolve())
        target.mkdir()
        (target / "SKILL.md").write_text("user replacement\n")
        self.cli("refresh", success=False)
        self.cli("remove", "openclaw", "--yes", success=False)
        self.assertEqual(self.desired(), ["openclaw"])
        self.assertEqual((target / "SKILL.md").read_text(), "user replacement\n")
        self.assert_protected()

    def test_update_reconciles_skills_and_old_targets_cannot_drop_openclaw(self):
        self.env["OPENCLAW_STATE_DIR"] = str(self.user / "custom state")
        self.protect_user_files()
        self.cli("install", "openclaw")
        before = self.git(self.repo, "rev-parse", "HEAD").stdout.strip()
        (self.origin / "fixture-update.txt").write_text("new local revision\n")
        self.git(self.origin, "add", "--all")
        self.commit("local update fixture")
        target = self.git(self.origin, "rev-parse", "HEAD").stdout.strip()
        self.cli("update", "--check", "--channel", "main")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD").stdout.strip(), before)
        link = self.plan().skills_root / self.catalog.sources[0].name
        projection.remove_projection_link(link, self.catalog, expected_destination=link.resolve())
        self.cli("update", "--channel", "main")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD").stdout.strip(), target)
        self.assertTrue(projection.is_projection_link(link))
        self.assertEqual(self.desired(), ["openclaw"])
        self.cli("check")
        # A target revision lacking this capability must fail before checkout or journaling.
        registry_path = self.origin / ".agents/harnesses/registry.json"
        data = json.loads(registry_path.read_text())
        del data["harnesses"]["openclaw"]
        registry_path.write_text(json.dumps(data))
        self.git(self.origin, "add", "--all")
        self.commit("fixture without OpenClaw")
        result = self.cli("update", "--channel", "main", success=False)
        self.assertIn("cannot represent installed harness 'openclaw'", result.stderr)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD").stdout.strip(), target)
        self.assertFalse((self.home / "state/operations/current.json").exists())
        self.assertEqual(self.desired(), ["openclaw"])
        self.assert_protected()


class OpenClawBoundaryTests(unittest.TestCase):
    def test_instruction_helpers_never_inspect_or_change_a_skills_only_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = resolve_harness_plan(load_harness_registry(), "openclaw", environ={}, user_home=Path(tmp))
            with mock.patch("sync_harness_instructions._inspect", side_effect=AssertionError("instruction inspection")):
                prepared = prepare_instruction_sync(plan, dry_run=False, assume_yes=False, output=lambda _: None)
                self.assertIsNone(prepared)
                apply_instruction_sync(prepared, dry_run=False)
                self.assertEqual(check_instruction_sync(plan), [])
                remove_instruction_sync(plan, dry_run=False)
            self.assertFalse(plan.root.exists())

    def test_openclaw_junction_paths_with_spaces_are_passed_as_data(self):
        with tempfile.TemporaryDirectory(prefix="openclaw link paths ") as tmp:
            home = Path(tmp)
            plan = resolve_harness_plan(load_harness_registry(), "openclaw", environ={}, user_home=home, os_name="nt")
            target = plan.skills_root / "fixture"
            source = home / "repo with spaces/plugins/fixture/skills/fixture"
            with mock.patch.object(projection.os, "name", "nt"), mock.patch.object(
                    projection.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
                projection.create_projection_link(target, source)
            self.assertEqual(run.call_args.kwargs["env"]["OH_MY_HARNESS_SKILL_LINK_PATH"], str(target))
            self.assertEqual(run.call_args.kwargs["env"]["OH_MY_HARNESS_SKILL_LINK_TARGET"], str(source))
            self.assertNotIn(str(target), run.call_args.args[0][-1])
            self.assertNotIn(str(source), run.call_args.args[0][-1])


if __name__ == "__main__":
    unittest.main()
