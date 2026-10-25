"""Recovery fault injection using local Git repositories, without network access."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import omh_bootstrap as bootstrap
import manager_state


@unittest.skipUnless(shutil.which("git"), "requires Git")
class CheckoutRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin"
        self.origin.mkdir()
        self.git(self.origin, "init", "-q")
        self.git(self.origin, "config", "user.name", "Local repair test")
        self.git(self.origin, "config", "user.email", "test@example.invalid")
        for name in bootstrap._REQUIRED_FILES:
            path = self.origin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# manager fixture\n")
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "-qm", "fixture")
        self.revision = self.git(self.origin, "rev-parse", "HEAD").stdout.strip()
        self.home = self.root / "manager with spaces"
        self.home.mkdir()
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.home / "repo")], check=True)
        (self.home / "state").mkdir()
        self.receipt = self.home / "state/manager.json"
        self.receipt.write_text(json.dumps({"product": "oh-my-harness", "repository": str(self.origin), "revision": self.revision}))
        self.out = contextlib.redirect_stdout(io.StringIO())
        self.out.__enter__()
        self.addCleanup(self.out.__exit__, None, None, None)

    @staticmethod
    def git(repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True)

    def backups(self):
        return list((self.home / "state/repair-backups").glob("repo-*"))

    def test_healthy_checkout_does_not_clone_or_require_remote(self):
        self.origin.rename(self.root / "offline")
        with mock.patch.object(bootstrap.shutil, "which", side_effect=AssertionError("should not need a restore")):
            bootstrap._repair_checkout(self.home)
        self.assertEqual(self.backups(), [])

    def test_dirty_checkout_restores_locally_and_preserves_edits(self):
        damaged = self.home / "repo/scripts/omh.py"
        damaged.write_text("# user's unpublished edits\n")
        (self.home / "repo/private-note.txt").write_text("keep this too")
        self.origin.rename(self.root / "offline")
        bootstrap._repair_checkout(self.home)
        self.assertEqual(damaged.read_text(), "# manager fixture\n")
        backup, = self.backups()
        self.assertEqual((backup / "scripts/omh.py").read_text(), "# user's unpublished edits\n")
        self.assertEqual((backup / "private-note.txt").read_text(), "keep this too")
        self.assertEqual(self.git(self.home / "repo", "config", "--get", "remote.origin.url").stdout.strip(), str(self.origin))

    def test_missing_checkout_restores_from_recorded_source(self):
        (self.home / "repo").rename(self.root / "removed-repo")
        self.assertFalse((self.home / "repo").exists())
        bootstrap._repair_checkout(self.home)
        self.assertEqual(self.git(self.home / "repo", "rev-parse", "HEAD").stdout.strip(), self.revision)

    def test_failed_clone_keeps_original_checkout(self):
        marker = self.home / "repo/keep.txt"
        marker.write_text("preserve")
        self.origin.rename(self.root / "offline")
        with self.assertRaises(subprocess.CalledProcessError):
            bootstrap._repair_checkout(self.home, force=True)
        self.assertEqual(marker.read_text(), "preserve")
        self.assertEqual(list(self.home.glob(".repo.repair-*")), [])

    def test_activation_failure_rolls_back_directory_move(self):
        marker = self.home / "repo/keep.txt"
        marker.write_text("preserve")
        real_rename = Path.rename
        def fail_activation(path, target):
            if path.name.startswith(".repo.repair-") and Path(target) == self.home / "repo":
                raise OSError("injected activation failure")
            return real_rename(path, target)
        with mock.patch.object(Path, "rename", fail_activation), self.assertRaisesRegex(OSError, "injected"):
            bootstrap._repair_checkout(self.home)
        self.assertEqual(marker.read_text(), "preserve")
        self.assertEqual(list(self.home.glob(".repo.repair-*")), [])

    def test_dry_run_preserves_every_existing_file(self):
        (self.home / "repo/dirty.txt").write_text("keep")
        before = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        bootstrap._repair_checkout(self.home, dry_run=True)
        after = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.home / "state/manager.lock").exists())

    def test_unknown_journal_is_preserved(self):
        path = self.home / "state/operations/current.json"
        path.parent.mkdir()
        path.write_text('{"command":"unknown-future-operation"}')
        original = path.read_bytes()
        with self.assertRaisesRegex(SystemExit, "unsupported interrupted"):
            bootstrap._repair_checkout(self.home)
        self.assertEqual(path.read_bytes(), original)

    def test_corrupt_state_is_not_reset(self):
        self.receipt.write_text("{ broken")
        with self.assertRaisesRegex(SystemExit, "preserved"):
            bootstrap._repair_checkout(self.home)
        self.assertEqual(self.receipt.read_text(), "{ broken")

    @unittest.skipIf(os.name == "nt", "POSIX link test")
    def test_linked_checkout_is_not_replaced(self):
        shutil.rmtree(self.home / "repo")
        (self.home / "repo").symlink_to(self.origin, target_is_directory=True)
        with self.assertRaisesRegex(SystemExit, "non-ordinary"):
            bootstrap._repair_checkout(self.home)
        self.assertTrue((self.home / "repo").is_symlink())

    def test_interrupted_update_can_keep_healthy_target_for_recover(self):
        (self.home / "repo/new.txt").write_text("new")
        repo = self.home / "repo"
        self.git(repo, "config", "user.name", "Local repair test")
        self.git(repo, "config", "user.email", "test@example.invalid")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-qm", "new")
        target = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        journal = self.home / "state/operations/current.json"
        journal.parent.mkdir()
        journal.write_text(json.dumps({"command": "update", "before": {"revision": self.revision}, "target": {"revision": target}}))
        bootstrap._repair_checkout(self.home)
        self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout.strip(), target)
        self.assertTrue(journal.exists())

    def test_second_mutation_cannot_enter_lock(self):
        code = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, sys.argv[1]); import omh_bootstrap as b, manager_state as m; "
            "{'bootstrap': b._mutation_lock, 'manager': m.ManagerLock}[sys.argv[3]]"
            "(Path(sys.argv[2])).__enter__()"
        )
        for name, lock in (("bootstrap", bootstrap._mutation_lock), ("manager", manager_state.ManagerLock)):
            with self.subTest(lock=name):
                with lock(self.home):
                    result = subprocess.run(
                        [sys.executable, "-c", code, str(Path(bootstrap.__file__).parent), str(self.home), name],
                        capture_output=True, text=True,
                    )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("already running", result.stderr)

    def test_lock_released_after_exception(self):
        with self.assertRaises(RuntimeError):
            with bootstrap._mutation_lock(self.home):
                raise RuntimeError("injected")
        with bootstrap._mutation_lock(self.home):
            pass


class BootstrapDispatchTests(unittest.TestCase):
    def test_help_does_not_bootstrap_missing_runtime(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bootstrap.subprocess, "run") as run:
            home = Path(tmp) / "not-yet-created"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bootstrap.main(["--home", str(home), "--help"]), 0)
            run.assert_not_called()
            self.assertFalse(home.exists())

    def test_all_repair_help_spellings_are_read_only(self):
        for args in (["repair", "--help"], ["manager", "repair", "--help"]):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "missing"
                with mock.patch.object(bootstrap, "_repair_checkout") as repair, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(bootstrap.main(["--home", str(home), *args]), 0)
                repair.assert_not_called()
                self.assertFalse(home.exists())

    def test_repair_dry_run_does_not_bootstrap_or_lock(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bootstrap, "_repair_checkout") as repair, \
             mock.patch.object(bootstrap, "_mutation_lock") as lock, \
             mock.patch.object(bootstrap.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["--home", tmp, "repair", "--dry-run"]), 0)
            repair.assert_called_once_with(Path(tmp), force=False, dry_run=True)
            lock.assert_not_called()
            run.assert_not_called()

    def test_plain_and_legacy_repair_detection(self):
        self.assertTrue(bootstrap._is_manager_repair(["repair"]))
        self.assertTrue(bootstrap._is_manager_repair(["manager", "repair"]))
        self.assertFalse(bootstrap._is_manager_repair(["manager", "uninstall"]))
        self.assertFalse(bootstrap._is_manager_repair([]))

    def test_missing_source_is_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(SystemExit, "source state is unavailable"):
            bootstrap._recorded_source(Path(tmp))


if __name__ == "__main__":
    unittest.main()
