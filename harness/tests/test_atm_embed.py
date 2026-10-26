"""Embedded engine materialization, sync/adoption and git-free operation."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import atm_embed
from manager_state import atomic_write_json, desired_file, manager_file, state_path

_COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv")
_MARKER = atm_embed.MARKER_NAME


def _git_env(home: Path, user: Path, empty_bin: Path | None = None) -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("ATM_")
    }
    environment.update(
        HOME=str(user), USERPROFILE=str(user), ATM_HOME=str(home),
        PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
    )
    if empty_bin is not None:
        environment["PATH"] = str(empty_bin)
    return environment


class EmbeddedMaterializationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="atm-embed-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        shutil.copytree(ROOT, self.source, ignore=_COPY_IGNORE)
        self.home = self.root / "manager"
        self.user = self.root / "user"

    def embed(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/atm_embed.py"), *arguments],
            capture_output=True, text=True, timeout=120,
        )

    def identity(self) -> tuple[str, str]:
        from plugin_package_identity import require_repository_identity

        payload = require_repository_identity(self.source)
        return payload["releaseVersion"], payload["bundleIdentity"]

    def test_materialize_creates_marker_state_and_launchers(self):
        release, bundle = self.identity()
        result = self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        marker = json.loads((self.home / "repo" / _MARKER).read_text(encoding="utf-8"))
        self.assertEqual(marker["sourceMode"], "atm-embedded")
        self.assertEqual(marker["embeddedIdentity"], bundle)
        self.assertEqual(marker["embeddedVersion"], release)
        manager = json.loads(manager_file(self.home).read_text(encoding="utf-8"))
        expected_revision = hashlib.sha256(
            f"{bundle}|{release}".encode("utf-8")
        ).hexdigest()[:40]
        self.assertEqual(manager["revision"], expected_revision)
        self.assertEqual(manager["channel"], "embedded")
        self.assertEqual(manager["repository"], atm_embed.ATM_REPOSITORY)
        desired = json.loads(desired_file(self.home).read_text(encoding="utf-8"))
        self.assertEqual(desired["harnesses"], [])
        self.assertIn(desired["updatePolicy"]["channel"], {"stable", "main"})
        # Embedded homes ship no launcher shims: `atm` is the only CLI entry.
        self.assertFalse((self.home / "bin").exists())
        self.assertFalse((self.home / "bootstrap").exists())
        # The materialized tree ships the engine entry the runtime contract needs.
        self.assertTrue((self.home / "repo/scripts/engine.py").is_file())
        self.assertTrue((self.home / "repo/VERSION").is_file())

    def test_materialize_refuses_when_home_already_has_a_checkout(self):
        self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        again = self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        self.assertNotEqual(again.returncode, 0, again.stdout)
        self.assertIn("sync", again.stderr)

    def test_sync_is_an_identity_noop(self):
        self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        before = manager_file(self.home).read_bytes()
        result = self.embed("sync", "--source", str(self.source), "--home", str(self.home))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(manager_file(self.home).read_bytes(), before)

    def test_sync_swaps_tree_and_rewrites_state(self):
        self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        # Simulate an ATM upgrade: change plugin content and regenerate the ledger.
        workflow = self.source / "plugins/workflow/README.md"
        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nembedded-sync-test\n", encoding="utf-8")
        from plugin_package_identity import update_repository_identity

        update_repository_identity(self.source)
        result = self.embed("sync", "--source", str(self.source), "--home", str(self.home))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        marker = json.loads((self.home / "repo" / _MARKER).read_text(encoding="utf-8"))
        _, bundle = self.identity()
        self.assertEqual(marker["embeddedIdentity"], bundle)
        manager = json.loads(manager_file(self.home).read_text(encoding="utf-8"))
        self.assertEqual(manager["bundleIdentity"], bundle)
        backups = self.home / "state/repair-backups"
        self.assertTrue(any(backups.iterdir()))

    def test_sync_preserves_desired_harnesses_from_legacy_state(self):
        self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        desired = json.loads(desired_file(self.home).read_text(encoding="utf-8"))
        desired["harnesses"] = ["codex", "zcode"]
        atomic_write_json(desired_file(self.home), desired)
        result = self.embed("sync", "--source", str(self.source), "--home", str(self.home))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = json.loads(desired_file(self.home).read_text(encoding="utf-8"))
        self.assertEqual(after["harnesses"], ["codex", "zcode"])

    def test_sync_refuses_under_active_operation_and_degraded_state(self):
        self.embed("materialize", "--source", str(self.source), "--home", str(self.home))
        operations = state_path(self.home) / "operations"
        operations.mkdir(parents=True, exist_ok=True)
        atomic_write_json(operations / "current.json", {
            "schemaVersion": "2026-08-24", "operationId": "test", "command": "update",
            "phase": "prepared", "before": {"revision": "0" * 40}, "target": {"revision": "1" * 40},
        })
        blocked = self.embed("sync", "--source", str(self.source), "--home", str(self.home))
        self.assertNotEqual(blocked.returncode, 0, blocked.stdout)
        self.assertIn("operation", blocked.stderr)
        (operations / "current.json").unlink()
        manager = json.loads(manager_file(self.home).read_text(encoding="utf-8"))
        manager["status"] = "degraded"
        atomic_write_json(manager_file(self.home), manager)
        degraded = self.embed("sync", "--source", str(self.source), "--home", str(self.home))
        self.assertNotEqual(degraded.returncode, 0, degraded.stdout)
        self.assertIn("degraded", degraded.stderr)

    def test_sync_adopts_a_legacy_git_checkout(self):
        legacy = self.root / "legacy-source"
        legacy.mkdir()
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(legacy)], check=True)
        shutil.copytree(ROOT, legacy, dirs_exist_ok=True, ignore=_COPY_IGNORE)
        subprocess.run(["git", "-C", str(legacy), "remote", "add", "origin",
                        "https://example.invalid/atm-harness.git"], check=True)
        for arguments in (("add", "--all"),):
            subprocess.run(["git", "-C", str(legacy), "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@example.invalid", *arguments], check=True)
        subprocess.run(["git", "-C", str(legacy), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid",
                        "commit", "--quiet", "-m", "fixture"], check=True)
        from plugin_package_identity import require_repository_identity

        home = self.root / "legacy-home"
        subprocess.run(["git", "clone", "--quiet", str(legacy), str(home / "repo")], check=True)
        self.assertTrue((home / "repo/.git").is_dir())
        (home / "state").mkdir(parents=True)
        revision = subprocess.run(["git", "-C", str(legacy), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        legacy_identity = require_repository_identity(legacy)
        (home / "state/install.json").write_text(json.dumps({
            "product": "atm-harness", "status": "ready",
            "repository": "https://example.invalid/atm-harness.git",
            "revision": revision, "ref": "main", "harness": "codex",
        }), encoding="utf-8")
        (home / "state/manager.json").write_text(json.dumps({
            "schemaVersion": "2026-08-24", "product": "atm-harness", "status": "ready",
            "repository": "https://example.invalid/atm-harness.git",
            "channel": "main", "requestedRef": "origin/main", "revision": revision,
            "releaseVersion": legacy_identity["releaseVersion"],
            "bundleIdentity": legacy_identity["bundleIdentity"], "updatedAt": "test",
        }), encoding="utf-8")
        desired_file(home).write_text(json.dumps({
            "schemaVersion": "2026-08-24", "harnesses": ["codex"],
            "updatePolicy": {"channel": "main"}, "updatedAt": "test",
        }), encoding="utf-8")
        result = self.embed("sync", "--source", str(self.source), "--home", str(home))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((home / "repo" / _MARKER).is_file())
        self.assertFalse((home / "repo/.git").exists())
        manager = json.loads(manager_file(home).read_text(encoding="utf-8"))
        self.assertEqual(manager["channel"], "embedded")
        self.assertNotEqual(manager["revision"], revision)
        desired = json.loads(desired_file(home).read_text(encoding="utf-8"))
        self.assertEqual(desired["harnesses"], ["codex"])
        backups = home / "state/repair-backups"
        self.assertTrue(any(backups.iterdir()))

    def test_bootstrap_materializes_then_builds_venv(self):
        fake = self.source / "scripts/bootstrap_tooling_env.py"
        fake.write_text(
            "import argparse, pathlib\n"
            "p = argparse.ArgumentParser(); p.add_argument('--venv', required=True)\n"
            "a = p.parse_args()\n"
            "import pathlib as _p; _p.Path(a.venv).mkdir(parents=True, exist_ok=True)\n"
            "_p.Path(a.venv, '.test-venv-marker').write_text('ok')\n",
            encoding="utf-8",
        )
        result = self.embed("bootstrap", "--source", str(self.source), "--home", str(self.home))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.home / "venv/.test-venv-marker").is_file())
        self.assertTrue((self.home / "repo" / _MARKER).is_file())
        # Bootstrap on a fresh home must leave complete, readable state.
        desired = json.loads(desired_file(self.home).read_text(encoding="utf-8"))
        self.assertEqual(desired["harnesses"], [])


class EmbeddedEngineBehaviorTests(unittest.TestCase):
    """The materialized engine works without Git and refuses retired flows."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="atm-embed-engine-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        shutil.copytree(ROOT, self.source, ignore=_COPY_IGNORE)
        self.home = self.root / "manager"
        self.user = self.root / "user"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/atm_embed.py"),
             "materialize", "--source", str(self.source), "--home", str(self.home)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.nogit_bin = Path(tempfile.mkdtemp(prefix="atm-nogit-bin-"))
        self.addCleanup(shutil.rmtree, self.nogit_bin, ignore_errors=True)

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = _git_env(self.home, self.user, empty_bin=self.nogit_bin)
        return subprocess.run(
            [sys.executable, "-B", str(self.home / "repo/scripts/engine.py"),
             "--home", str(self.home), *arguments],
            env=environment, capture_output=True, text=True, timeout=60,
        )

    def test_status_and_machine_protocol_run_without_git(self):
        status = self.cli("status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        payload = json.loads(status.stdout)
        self.assertEqual(payload["product"], "atm-harness")
        self.assertEqual(payload["manager"]["channel"], "embedded")
        self.assertIsNone(payload["worktreeClean"])
        machine = self.cli("machine", "--protocol", "1", "status")
        self.assertEqual(machine.returncode, 0, machine.stdout + machine.stderr)
        envelope = json.loads(machine.stdout)
        self.assertEqual(envelope["ok"], True)
        self.assertEqual(envelope["result"]["manager"]["channel"], "embedded")

    def test_update_and_recover_refuse_with_release_guidance(self):
        update = self.cli("update")
        self.assertNotEqual(update.returncode, 0)
        self.assertIn("atm harness sync", update.stderr)
        recover = self.cli("recover")
        self.assertNotEqual(recover.returncode, 0)
        self.assertIn("embedded", recover.stderr)
        reclone = self.cli("repair", "--reclone", "--dry-run")
        self.assertNotEqual(reclone.returncode, 0)
        self.assertIn("embedded", reclone.stderr)

    def test_drift_blocks_mutations_until_sync(self):
        plugin = self.home / "repo/plugins/workflow/README.md"
        plugin.write_text(plugin.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
        refresh = self.cli("refresh", "--dry-run")
        self.assertNotEqual(refresh.returncode, 0)
        self.assertIn("identity", refresh.stderr)
        status = self.cli("status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)

    def test_stable_revision_is_derived_from_identity(self):
        status = self.cli("status", "--json")
        payload = json.loads(status.stdout)
        marker = json.loads((self.home / "repo" / _MARKER).read_text(encoding="utf-8"))
        expected = hashlib.sha256(
            f"{marker['embeddedIdentity']}|{marker['embeddedVersion']}".encode("utf-8")
        ).hexdigest()[:40]
        self.assertEqual(payload["manager"]["revision"], expected)
        self.assertRegex(expected, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
