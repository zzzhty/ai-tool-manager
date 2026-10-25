from __future__ import annotations

import contextlib
import importlib
import inspect
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
ROOT_SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SCRIPTS))

from watcher_runtime import cli as watcher_cli  # noqa: E402
from watcher_runtime.doc import audit_repo, audit_runtime, doctor  # noqa: E402
from refresh_harness import (  # noqa: E402
    cached_plugin_names,
    plugin_prune_plan,
    prune_stale_plugins,
)


class WatcherRuntimeCliTests(unittest.TestCase):
    def test_named_runtime_domains_do_not_share_bare_module_identity(self) -> None:
        doc_report = importlib.import_module("watcher_runtime.doc.report")
        skill_report = importlib.import_module("watcher_runtime.skill.report")

        self.assertIsNot(doc_report, skill_report)
        self.assertTrue(hasattr(doc_report, "finding_delta"))
        self.assertFalse(hasattr(skill_report, "finding_delta"))

    def test_cli_dispatches_skill_report_to_named_handler(self) -> None:
        with mock.patch("watcher_runtime.skill.report.main", return_value=0) as handler:
            exit_code = watcher_cli.main(["skill", "report", "--since", "7d"])

        self.assertEqual(exit_code, 0)
        handler.assert_called_once_with(["--since", "7d"])

    def test_cli_dispatches_doc_report_to_named_handler(self) -> None:
        with mock.patch("watcher_runtime.doc.report.main", return_value=0) as handler:
            exit_code = watcher_cli.main(["doc", "report", "--digest"])

        self.assertEqual(exit_code, 0)
        handler.assert_called_once_with(["--digest"])

    def test_command_registry_exposes_one_argv_handler_interface(self) -> None:
        for domain, commands in watcher_cli.COMMAND_MODULES.items():
            for command, module_name in commands.items():
                with self.subTest(domain=domain, command=command):
                    handler = importlib.import_module(module_name).main
                    self.assertEqual(list(inspect.signature(handler).parameters), ["argv"])

    def test_every_registered_command_owns_canonical_help(self) -> None:
        for domain, commands in watcher_cli.COMMAND_MODULES.items():
            for command in commands:
                with self.subTest(domain=domain, command=command):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
                        watcher_cli.main([domain, command, "--help"])
                    self.assertEqual(raised.exception.code, 0)
                    self.assertTrue(stdout.getvalue().startswith(f"usage: watcher {domain} {command}"))

    def test_os_cli_help_uses_canonical_command_names(self) -> None:
        watcher = SCRIPTS / "watcher"
        for domain in ("skill", "doc"):
            with self.subTest(domain=domain):
                completed = subprocess.run(
                    [sys.executable, "-B", str(watcher), domain, "report", "--help"],
                    capture_output=True,
                    check=False,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.startswith(f"usage: watcher {domain} report"))
                self.assertNotIn("generate_report.py", completed.stdout)

    def test_migrate_state_defaults_to_dry_run_without_moving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            source = codex_home / "skill-watcher"
            source.mkdir()
            (source / "logs").mkdir()

            exit_code = watcher_cli.run_migrate_state(["--domain", "skill", "--codex-home", str(codex_home)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(source.is_dir())
            self.assertFalse((codex_home / "watcher" / "skill").exists())

    def test_migrate_state_apply_moves_without_copy_or_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            source = codex_home / "skill-watcher"
            source.mkdir()
            (source / "logs").mkdir()

            exit_code = watcher_cli.run_migrate_state(
                ["--domain", "skill", "--codex-home", str(codex_home), "--apply"]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(source.exists())
            self.assertTrue((codex_home / "watcher" / "skill" / "logs").is_dir())

    def test_migrate_state_fails_when_target_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            source = codex_home / "doc-watcher"
            target = codex_home / "watcher" / "doc"
            source.mkdir()
            target.mkdir(parents=True)

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = watcher_cli.run_migrate_state(
                    ["--domain", "doc", "--codex-home", str(codex_home), "--apply"]
                )

            self.assertEqual(exit_code, 1)
            self.assertTrue(source.is_dir())
            self.assertTrue(target.is_dir())
            self.assertIn("refusing to merge", stderr.getvalue())

    def test_migrate_state_rejects_dry_run_and_apply_together(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            watcher_cli.run_migrate_state(["--dry-run", "--apply"])

        self.assertIn("choose only one", str(raised.exception))

    def test_doc_runtime_uses_watcher_doc_env_and_ignores_old_doc_watcher_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "current-doc-state"
            legacy = root / "legacy-doc-state"
            default = root / "default-doc-state"

            with mock.patch.dict(
                "os.environ",
                {
                    "WATCHER_DOC_STATE_DIR": str(current),
                    "DOC_WATCHER_STATE_DIR": str(legacy),
                },
                clear=True,
            ):
                self.assertEqual(audit_repo.resolve_state_dir(None), current)
                self.assertEqual(audit_runtime.resolve_audit_state_dir(), current)

            with mock.patch.dict("os.environ", {"DOC_WATCHER_STATE_DIR": str(legacy)}, clear=True):
                with mock.patch("watcher_runtime.doc.audit_repo.DEFAULT_STATE_DIR", default):
                    self.assertEqual(audit_repo.resolve_state_dir(None), default)

    def test_doc_doctor_example_config_uses_explicit_repository_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = (
                root
                / "cache"
                / "oh-my-harness"
                / "watcher"
                / "version"
                / "config"
                / "repos.example.json"
            )
            config.parent.mkdir(parents=True)
            config.write_text(
                (PLUGIN_ROOT / "config" / "repos.example.json").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {"OH_MY_HARNESS_ROOT": str(REPO_ROOT)},
                    clear=False,
                ),
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = doctor.main(
                    ["--config", str(config), "--state-dir", str(root / "state")]
                )

        self.assertEqual(exit_code, 0, stdout.getvalue())
        self.assertIn(f"ok: repo oh-my-harness: {REPO_ROOT}", stdout.getvalue())

    def test_prune_stale_plugins_removes_cache_only_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            config = codex_home / "config.toml"
            config.write_text(
                "\n".join(
                    [
                        '[plugins."old-plugin@oh-my-harness"]',
                        "enabled = true",
                        '[plugins."workflow@oh-my-harness"]',
                        "enabled = true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cache_root = codex_home / "plugins" / "cache" / "oh-my-harness"
            (cache_root / "cached-only" / "0.1.0").mkdir(parents=True)
            calls: list[list[str]] = []

            def fake_run(command, *, env, dry_run, check=True):  # type: ignore[no-untyped-def]
                calls.append(command)
                return 0

            with mock.patch("refresh_harness.run", fake_run):
                prune_stale_plugins(
                    "codex",
                    codex_home=codex_home,
                    marketplace_name="oh-my-harness",
                    plan=plugin_prune_plan(
                        codex_home=codex_home,
                        marketplace_name="oh-my-harness",
                        desired_plugin_names=["workflow"],
                    ),
                    env={},
                    dry_run=False,
                )

            self.assertEqual(calls, [["codex", "plugin", "remove", "old-plugin@oh-my-harness"]])
            self.assertEqual(cached_plugin_names(codex_home, "oh-my-harness"), set())


if __name__ == "__main__":
    unittest.main()
