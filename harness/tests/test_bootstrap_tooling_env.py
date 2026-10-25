from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))

import bootstrap_tooling_env as bootstrap  # noqa: E402
import refresh_harness as refresh  # noqa: E402


class ToolingBootstrapTests(unittest.TestCase):
    def test_unsupported_python_is_rejected_before_venv_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_path = root / "tooling"
            requirements = root / "requirements.txt"
            requirements.write_text("", encoding="utf-8")

            with (
                mock.patch.object(bootstrap.sys, "version_info", (3, 10, 13)),
                mock.patch.object(bootstrap, "canonical_base_python") as canonical_base,
                mock.patch.object(
                    bootstrap,
                    "venv_health",
                    return_value=(False, "venv Python missing"),
                ) as venv_health,
                mock.patch.object(bootstrap, "create_venv") as create_venv,
                mock.patch.object(bootstrap, "refresh_dependencies") as refresh_dependencies,
                self.assertRaisesRegex(SystemExit, "Python 3.11 or newer is required"),
            ):
                bootstrap.bootstrap_tooling_env(venv_path, requirements, dry_run=True)

            canonical_base.assert_not_called()
            venv_health.assert_not_called()
            create_venv.assert_not_called()
            refresh_dependencies.assert_not_called()
            self.assertFalse(venv_path.exists())

    def test_symlinked_base_python_rebuilds_a_broken_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actual_base = Path(sys._base_executable or sys.executable).resolve(strict=True)
            linked_base = root / "python-from-path"
            try:
                linked_base.symlink_to(actual_base)
            except OSError as exc:
                self.skipTest(f"Python executable symlinks are unavailable: {exc}")

            venv_path = root / "tooling"
            venv_path.mkdir()
            sentinel = venv_path / "broken-environment.txt"
            sentinel.write_text("keep only if rebuild fails\n", encoding="utf-8")
            requirements = root / "requirements.txt"
            requirements.write_text("", encoding="utf-8")

            with (
                mock.patch.object(bootstrap.sys, "_base_executable", str(linked_base)),
                mock.patch.object(bootstrap, "refresh_dependencies") as refresh_dependencies,
            ):
                bootstrap.bootstrap_tooling_env(venv_path, requirements, dry_run=False)

            healthy, detail = bootstrap.venv_health(venv_path, base_python=actual_base)
            self.assertTrue(healthy, detail)
            self.assertFalse(sentinel.exists())
            self.assertEqual(list(root.glob(".tooling.backup-*")), [])
            self.assertEqual(bootstrap.configured_base_python(venv_path), actual_base)
            self.assertNotIn(f"home = {linked_base.parent}\n", (venv_path / "pyvenv.cfg").read_text())
            refresh_dependencies.assert_called_once_with(
                bootstrap.venv_python(venv_path),
                requirements,
                dry_run=False,
            )

    def test_failed_rebuild_restores_the_previous_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_path = root / "tooling"
            venv_path.mkdir()
            sentinel = venv_path / "previous-state.txt"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            requirements = root / "requirements.txt"
            requirements.write_text("", encoding="utf-8")

            def fail_after_creating_partial_venv(
                base_python: Path,
                target: Path,
                *,
                dry_run: bool,
            ) -> None:
                self.assertFalse(dry_run)
                target.mkdir()
                (target / "partial-state.txt").write_text("partial\n", encoding="utf-8")
                raise subprocess.CalledProcessError(9, [str(base_python), "-m", "venv", str(target)])

            with (
                mock.patch.object(bootstrap, "create_venv", side_effect=fail_after_creating_partial_venv),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                bootstrap.bootstrap_tooling_env(venv_path, requirements, dry_run=False)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")
            self.assertFalse((venv_path / "partial-state.txt").exists())
            self.assertEqual(list(root.glob(".tooling.backup-*")), [])

    def test_dry_run_reports_rebuild_without_moving_the_broken_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_path = root / "tooling"
            venv_path.mkdir()
            sentinel = venv_path / "previous-state.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            requirements = root / "requirements.txt"
            requirements.write_text("", encoding="utf-8")

            bootstrap.bootstrap_tooling_env(venv_path, requirements, dry_run=True)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged\n")
            self.assertEqual(list(root.glob(".tooling.backup-*")), [])

    def test_refresh_dry_run_executes_the_bootstrap_preflight(self) -> None:
        venv_path = Path("/tmp/example-tooling-venv")
        env = {"CODEX_HOME": "/tmp/example-codex-home"}

        with mock.patch.object(refresh, "run") as run_command:
            refresh.run_tooling_bootstrap(venv_path=venv_path, env=env, dry_run=True)

        command = run_command.call_args.args[0]
        self.assertEqual(command[-1], "--dry-run")
        self.assertEqual(run_command.call_args.kwargs, {"env": env, "dry_run": False})


if __name__ == "__main__":
    unittest.main()
