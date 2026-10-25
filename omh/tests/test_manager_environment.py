"""User PATH ownership and idempotence tests; no real user profile is touched."""
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
import manager_environment as environment


class UserEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = Path(self.tmp.name) / "user"
        self.user.mkdir()
        self.home = self.user / ".oh-my-harness"
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(environment.Path, "home", return_value=self.user).start()
        mock.patch.dict(os.environ, {"HOME": str(self.user), "SHELL": "/bin/bash", "PATH": os.environ.get("PATH", "")}, clear=False).start()
        self.stdout = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.stdout)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def profile(self):
        return self.user / ".bashrc"

    def install(self, **kwargs):
        environment.ensure_user_path(self.home, **kwargs)

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_shell_registration_repeat_and_uninstall(self):
        cases = (
            ("/bin/bash", {}, self.profile(), "export PATH="),
            ("/bin/zsh", {"ZDOTDIR": str(self.user / "zsh")}, self.user / "zsh/.zshrc", "export PATH="),
            ("/bin/fish", {"XDG_CONFIG_HOME": str(self.user / "xdg")},
             self.user / "xdg/fish/conf.d/oh-my-harness.fish", "set -gx PATH "),
        )
        for shell, variables, path, assignment in cases:
            with self.subTest(shell=shell), mock.patch.dict(os.environ, {"SHELL": shell, **variables}):
                personal = "# personal shell settings\n"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(personal)
                self.install()
                installed = path.read_text()
                self.assertIn(assignment, installed)
                self.assertIn(str(self.home / "bin"), installed)
                receipt = self.home / "state" / environment.RECEIPT
                self.assertEqual(json.loads(receipt.read_text())["profiles"],
                                 [{"path": str(path), "fish": shell == "/bin/fish"}])
                self.install()
                self.assertEqual(path.read_text(), installed)
                path.write_text(installed + "# settings below\n")
                self.install(remove=True)
                self.assertEqual(path.read_text(), personal + "# settings below\n")
                self.assertFalse(receipt.exists())

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_dry_run_writes_nothing(self):
        self.install(dry_run=True)
        self.assertFalse(self.home.exists())
        self.assertFalse(self.profile().exists())

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_relocation_rewrites_owned_blocks(self):
        self.install()
        old_home = self.home
        self.home = self.user / "moved home"
        old_home.rename(self.home)
        self.install()
        text = self.profile().read_text()
        self.assertIn(str(self.home / "bin"), text)
        self.assertNotIn(str(old_home / "bin"), text)
        self.assertEqual(text.count(environment.START), 1)

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_copied_receipt_does_not_write_to_old_account(self):
        old_profile = Path(self.tmp.name) / "another-account" / ".bashrc"
        old_profile.parent.mkdir()
        old_profile.write_text("DO NOT TOUCH\n")
        state = self.home / "state"
        state.mkdir(parents=True)
        receipt = {"product": "oh-my-harness", "userHome": str(old_profile.parent),
                   "bin": str(old_profile.parent / ".oh-my-harness/bin"),
                   "profiles": [{"path": str(old_profile), "fish": False}]}
        (state / environment.RECEIPT).write_text(json.dumps(receipt))
        self.profile().write_text(environment._block(receipt["bin"]))
        self.install()
        self.assertEqual(old_profile.read_text(), "DO NOT TOUCH\n")
        self.assertIn(str(self.home / "bin"), self.profile().read_text())

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_registration_preserves_dotfile_link_and_permissions(self):
        target = self.user / "dotfiles/bashrc"
        target.parent.mkdir()
        target.write_text("# dotfiles\n")
        target.chmod(0o640)
        self.profile().symlink_to(target)
        self.install()
        self.assertTrue(self.profile().is_symlink())
        self.assertIn(environment.START, target.read_text())
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_all_profiles_are_preflighted_before_any_write(self):
        inactive = self.user / "other-config" / ".zshrc"
        inactive.parent.mkdir()
        inactive.write_text(environment.START + "\n")
        state = self.home / "state"
        state.mkdir(parents=True)
        receipt = state / environment.RECEIPT
        original = json.dumps({"product": "oh-my-harness", "userHome": str(self.user),
                               "bin": str(self.home / "bin"),
                               "profiles": [{"path": str(inactive), "fish": False}]})
        receipt.write_text(original)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.install()
        self.assertFalse(self.profile().exists())
        self.assertEqual(receipt.read_text(), original)
        self.assertEqual(inactive.read_text(), environment.START + "\n")

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_unsupported_shell_reports_registration_unavailable(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/sh"}):
            self.install()
        receipt = json.loads((self.home / "state" / environment.RECEIPT).read_text())
        self.assertEqual(receipt["profiles"], [])
        self.assertIn("PATH was not registered", self.stdout.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_linked_state_is_rejected(self):
        self.home.mkdir()
        other = self.user / "other"
        other.mkdir()
        (self.home / "state").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "ordinary"):
            self.install()
        self.assertEqual(list(other.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX profiles")
    def test_invalid_blocks_preserve_profile_and_receipt(self):
        self.install()
        entry = str(self.home / "bin")
        current = environment._block(entry)
        receipt = self.home / "state" / environment.RECEIPT
        before = receipt.read_bytes()
        for damaged in (current.replace("export PATH=", "export PATH=custom:"),
                        current + current,
                        current.replace("esac\n", "esac; export EXTRA=edited\n"),
                        environment.START + "\n"):
            with self.subTest(damaged=damaged):
                self.profile().write_text(damaged)
                with self.assertRaises(RuntimeError):
                    self.install()
                self.assertEqual(self.profile().read_text(), damaged)
                self.assertEqual(before, receipt.read_bytes())

    @unittest.skipUnless(os.name != "nt" and shutil.which("sh"), "needs POSIX sh")
    def test_shell_execution_quotes_paths_and_deduplicates_entries(self):
        entry = str(self.user / "space ' $ & [literal]" / "bin")
        code = environment._block(entry)
        for shell in ("sh", "bash", "zsh"):
            executable = shutil.which(shell)
            if executable is None:
                continue
            for existing in (None, "", ":", "/bin:/usr/bin", "/usr/bin:/bin",
                             "/usr/bin:" + entry + ":/bin"):
                with self.subTest(shell=shell, existing=existing):
                    # zsh's system zshenv may replace an empty inherited PATH even
                    # with -f. Set the block's input after shell startup, without
                    # interpolating literal path characters into shell source.
                    setup = "unset PATH\n" if existing is None else 'export PATH="$1"\n'
                    process = subprocess.run(
                        [executable, "-c", setup + code + code + '\nprintf "%s" "$PATH"',
                         "omh-path-test", existing or ""],
                        env={"PATH": existing or "", "HOME": str(self.user),
                             "ZDOTDIR": str(self.user)},
                        capture_output=True, text=True, check=True,
                    )
                    initial = existing or ""
                    expected = initial if entry in initial.split(":") else entry + (":" + initial if initial else "")
                    self.assertEqual(process.stdout, expected)

    def test_unsafe_posix_path_entries_rejected(self):
        for value in ("/tmp/part:other", "/tmp/line\nbreak", "/tmp/line\rbreak"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                environment._block(value)

    def test_windows_path_add_repeat_and_remove(self):
        original = r"C:\Windows;%USERPROFILE%\Tools;;D:\Other"
        entry = r"D:\My Harness\bin"
        updated, added = environment._windows_path(original, entry)
        self.assertTrue(added)
        repeated, added = environment._windows_path(updated, entry.lower())
        self.assertEqual(repeated, updated)
        self.assertFalse(added)
        restored, removed = environment._windows_path(updated, entry, remove=True)
        self.assertTrue(removed)
        self.assertEqual(restored, original)

    def test_unrecognized_receipt_not_overwritten(self):
        state = self.home / "state"
        state.mkdir(parents=True)
        path = state / environment.RECEIPT
        path.write_text('{"product":"other"}')
        with self.assertRaisesRegex(RuntimeError, "unrecognized"):
            self.install()
        self.assertEqual(path.read_text(), '{"product":"other"}')


if __name__ == "__main__":
    unittest.main()
