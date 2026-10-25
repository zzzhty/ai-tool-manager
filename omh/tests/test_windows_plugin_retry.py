from __future__ import annotations

import argparse
import contextlib
import json
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import refresh_harness as refresh  # noqa: E402
import omh  # noqa: E402
import install_oh_my_harness as installer  # noqa: E402
import sync_harness_instructions as instructions  # noqa: E402
from manager_state import manager_file  # noqa: E402
from test_refresh_harness_integration import HarnessFixture  # noqa: E402


COPY_DENIED = "Failed to copy plugin file: Access is denied. (os error 5)"
COMMAND = ["codex", "plugin", "add", "alpha@test"]


def result(code: int, *, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(COMMAND, code, stdout=stdout, stderr=stderr)


def write_staged_copy(fixture: HarnessFixture, name: str, *, plugin: str = "alpha",
                      version: str | None = None) -> Path:
    staging = fixture.codex_home / "plugins" / "cache" / "test" / name
    manifest = staging / plugin / (version or fixture.source_versions[plugin]) / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b"")
    return staging


class WindowsPluginRetryTests(unittest.TestCase):
    def test_transient_copy_denial_retries_same_command_and_environment(self) -> None:
        env = {"CODEX_HOME": "fixture-home"}
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run", side_effect=[
                result(1, stderr=COPY_DENIED), result(1, stderr=COPY_DENIED), result(0),
            ]) as run,
            mock.patch.object(refresh.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertIsNone(refresh.add_codex_plugin("codex", "alpha@test", env=env, dry_run=False))
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            self.assertEqual(call.args[0], COMMAND)
            self.assertEqual(call.kwargs["env"], env)
            self.assertTrue(call.kwargs["capture_output"])
            self.assertTrue(call.kwargs["text"])
        self.assertEqual(sleep.call_args_list, [mock.call(0.5), mock.call(1.0)])

    def test_exhausted_copy_denial_preserves_final_error_and_stops(self) -> None:
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run", side_effect=[
                result(1, stderr=COPY_DENIED), result(2, stderr=COPY_DENIED),
                result(7, stdout="last stdout", stderr="last: " + COPY_DENIED),
            ]) as run,
            mock.patch.object(refresh.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_args_list, [mock.call(0.5), mock.call(1.0)])
        self.assertEqual(raised.exception.returncode, 7)
        self.assertEqual(raised.exception.cmd, COMMAND)
        self.assertEqual(raised.exception.output, "last stdout")
        self.assertEqual(raised.exception.stderr, "last: " + COPY_DENIED)

    def test_matching_is_case_insensitive_and_reads_stdout(self) -> None:
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run", side_effect=[
                result(1, stdout=COPY_DENIED.upper()), result(0),
            ]) as run,
            mock.patch.object(refresh.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_other_failures_do_not_retry(self) -> None:
        for stderr in (
            "failed to copy plugin file: sharing violation (os error 32)",
            "failed to copy plugin file: file not found (os error 2)",
            "failed to remove plugin file: access denied (os error 5)",
            "failed to copy plugin file: access denied",
            "authentication failed",
        ):
            with (
                self.subTest(stderr=stderr),
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", return_value=result(1, stderr=stderr)) as run,
                mock.patch.object(refresh.time, "sleep") as sleep,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)
                run.assert_called_once()
                sleep.assert_not_called()

    def test_each_failed_attempt_must_itself_match(self) -> None:
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run", side_effect=[
                result(1, stderr=COPY_DENIED), result(2, stderr="authentication failed"),
            ]) as run,
            mock.patch.object(refresh.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(0.5)
        self.assertEqual(raised.exception.stderr, "authentication failed")

    def test_non_windows_uses_existing_runner_without_retry(self) -> None:
        for platform in ("linux", "darwin"):
            with (
                self.subTest(platform=platform),
                mock.patch.object(refresh.sys, "platform", platform),
                mock.patch.object(refresh, "run", side_effect=SystemExit(COPY_DENIED)) as run,
                mock.patch.object(refresh.time, "sleep") as sleep,
            ):
                with self.assertRaises(SystemExit):
                    refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)
                run.assert_called_once_with(COMMAND, env={}, dry_run=False)
                sleep.assert_not_called()

    def test_dry_run_prints_command_without_execution_or_sleep(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run") as run,
            mock.patch.object(refresh.time, "sleep") as sleep,
            contextlib.redirect_stdout(output),
        ):
            refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=True)
        self.assertIn("plugin add alpha@test", output.getvalue())
        run.assert_not_called()
        sleep.assert_not_called()

    def test_success_does_not_retry_even_if_output_mentions_copy_denial(self) -> None:
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run", return_value=result(0, stdout=COPY_DENIED)) as run,
            mock.patch.object(refresh.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)
        run.assert_called_once()
        sleep.assert_not_called()

    def test_failed_attempt_diagnostics_retain_operation_context_and_cli_output(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()
        source = Path("validated-checkout") / "plugins" / "alpha"
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.subprocess, "run", side_effect=[
                result(5, stdout="copy progress", stderr=COPY_DENIED), result(0),
            ]),
            mock.patch.object(refresh.time, "sleep"),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            refresh.add_codex_plugin(
                "codex", "alpha@test", env={}, dry_run=False,
                version="1.2.3+codex.test", source_root=source, stage="retired-restore",
            )
        for expected in (
            "stage=retired-restore", "plugin=alpha@test", "version=1.2.3+codex.test",
            f"validated-source={source}", "attempt=1/3", "attempt=2/3", "copy progress",
        ):
            self.assertIn(expected, output.getvalue())
        for expected in (COPY_DENIED, "exit=5", "attempt=1/3", "stage=retired-restore"):
            self.assertIn(expected, errors.getvalue())

    def test_transient_copy_denial_then_valid_closure_completes_activation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            attempts = 0

            def add_after_transient_denial(command, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    write_staged_copy(fixture, "plugin-install-abc123")
                    return result(1, stderr=COPY_DENIED)
                fixture.run(command, env={}, dry_run=False)
                return result(0)

            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh, "read_codex_plugin_rows", side_effect=fixture.rows),
                mock.patch.object(refresh, "run", side_effect=fixture.run),
                mock.patch.object(refresh.subprocess, "run", side_effect=add_after_transient_denial),
                mock.patch.object(refresh.time, "sleep") as sleep,
                mock.patch.object(refresh, "plugin_installation_issues", wraps=refresh.plugin_installation_issues) as closure,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertIsNone(refresh.apply_codex_harness(
                    fixture.catalog, codex="codex", codex_home=fixture.codex_home,
                    marketplace_name="test", excluded_skill_roots=(fixture.target,),
                    marketplace_source_binding=refresh.MarketplaceSourceBinding("local", str(fixture.repo)),
                    env={"CODEX_HOME": str(fixture.codex_home)}, dry_run=False,
                ))
            self.assertEqual(attempts, 3)
            sleep.assert_called_once_with(0.5)
            closure.assert_called_once()
            self.assertEqual(fixture.enabled, {"alpha", "beta"})
            self.assertEqual(fixture.events, ["add:alpha", "add:beta"])
            cache = fixture.codex_home / "plugins" / "cache" / "test"
            self.assertEqual({path.name for path in cache.iterdir()}, {"alpha", "beta"})
            kept = fixture.codex_home / "plugins" / "omh-install-residue" / "test" / "plugin-install-abc123"
            self.assertEqual((kept / "cache-entry" / "alpha" / fixture.source_versions["alpha"] / ".codex-plugin" / "plugin.json").read_bytes(), b"")
            context = json.loads((kept / "context.json").read_text(encoding="utf-8"))
            self.assertEqual((context["plugin"], context["failedAttempt"]), ("alpha@test", 1))

    def test_residue_quarantine_preserves_existing_foreign_and_unrecognized_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            previous = write_staged_copy(fixture, "plugin-install-old123")
            fixture._write_cache("alpha")
            cache_manifest = fixture.codex_home / "plugins" / "cache" / "test" / "alpha" / fixture.source_versions["alpha"] / ".codex-plugin" / "plugin.json"
            installed_bytes = cache_manifest.read_bytes()
            attempts = 0

            def add_with_residue(command, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    write_staged_copy(fixture, "plugin-install-abc123")
                    write_staged_copy(fixture, "plugin-install-other1", plugin="beta")
                    write_staged_copy(fixture, "plugin-install-other2", version="0.0.0")
                    unknown = write_staged_copy(fixture, "plugin-install-other3")
                    (unknown / "user.txt").write_text("keep", encoding="utf-8")
                    write_staged_copy(fixture, "plugin-backup-old123")
                    return result(1, stderr=COPY_DENIED)
                return result(0)

            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", side_effect=add_with_residue),
                mock.patch.object(refresh.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                refresh.add_codex_plugin(
                    "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                    dry_run=False, version=fixture.source_versions["alpha"],
                    source_root=fixture.repo / "plugins" / "alpha",
                )
            self.assertEqual(cache_manifest.read_bytes(), installed_bytes)
            self.assertTrue(previous.is_dir())
            cache = fixture.codex_home / "plugins" / "cache" / "test"
            self.assertEqual({path.name for path in cache.iterdir()}, {
                "alpha", "plugin-install-old123", "plugin-install-other1",
                "plugin-install-other2", "plugin-install-other3", "plugin-backup-old123",
            })
            self.assertEqual((cache / "plugin-install-other3" / "user.txt").read_text(encoding="utf-8"), "keep")

    def test_staging_reparse_points_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            outside = Path(tmp) / "outside"
            outside.mkdir()
            outside.joinpath("user.txt").write_text("keep", encoding="utf-8")
            staging = fixture.codex_home / "plugins" / "cache" / "test" / "plugin-install-abc123"
            attempts = 0

            def add_with_link(command, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    version = write_staged_copy(fixture, staging.name) / "alpha" / fixture.source_versions["alpha"]
                    link = version / "skills"
                    if os.name == "nt":
                        # Use the original runner while the Codex transport is mocked.
                        linked = native_run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
                        self.assertEqual(linked.returncode, 0, linked.stderr)
                    else:
                        link.symlink_to(outside, target_is_directory=True)
                    return result(1, stderr=COPY_DENIED)
                return result(0)

            native_run = subprocess.run
            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", side_effect=add_with_link),
                mock.patch.object(refresh.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                refresh.add_codex_plugin(
                    "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                    dry_run=False, version=fixture.source_versions["alpha"],
                    source_root=fixture.repo / "plugins" / "alpha",
                )
            self.assertTrue(staging.is_dir())
            self.assertEqual(outside.joinpath("user.txt").read_text(encoding="utf-8"), "keep")

    def test_quarantine_failure_stops_success_and_preserves_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            attempts = 0

            def add_with_residue(command, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    write_staged_copy(fixture, "plugin-install-abc123")
                    return result(1, stderr=COPY_DENIED)
                return result(0)

            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", side_effect=add_with_residue),
                mock.patch.object(refresh.time, "sleep"),
                mock.patch.object(Path, "rename", side_effect=PermissionError("still locked")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaisesRegex(SystemExit, "failed to quarantine.*still locked"):
                    refresh.add_codex_plugin(
                        "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                        dry_run=False, version=fixture.source_versions["alpha"],
                        source_root=fixture.repo / "plugins" / "alpha",
                    )
            self.assertEqual(attempts, 2)
            self.assertTrue((fixture.codex_home / "plugins" / "cache" / "test" / "plugin-install-abc123").is_dir())

    def test_multiple_matching_candidates_are_ambiguous_and_not_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            def failed_add(*args, **kwargs):
                for name in ("plugin-install-ours", "plugin-install-external"):
                    write_staged_copy(fixture, name)
                return result(7, stdout="original stdout", stderr=COPY_DENIED)
            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", side_effect=failed_add) as run,
                mock.patch.object(refresh.time, "sleep") as sleep,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()) as diagnostic,
            ):
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    refresh.add_codex_plugin(
                        "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                        dry_run=False, version=fixture.source_versions["alpha"],
                        source_root=fixture.repo / "plugins" / "alpha",
                    )
            run.assert_called_once()
            sleep.assert_not_called()
            self.assertEqual(raised.exception.returncode, 7)
            self.assertEqual(raised.exception.output, "original stdout")
            self.assertIn("ambiguous", diagnostic.getvalue())
            self.assertEqual(len(list((fixture.codex_home / "plugins/cache/test").iterdir())), 2)
            self.assertFalse((fixture.codex_home / "plugins/omh-install-residue").exists())

    def test_later_ambiguity_preserves_earlier_candidate_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            attempts = 0
            def add(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                names = ("first",) if attempts == 1 else ("second", "external")
                for name in names:
                    write_staged_copy(fixture, f"plugin-install-{name}")
                return result(7, stderr=COPY_DENIED)
            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", side_effect=add),
                mock.patch.object(refresh.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    refresh.add_codex_plugin(
                        "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                        dry_run=False, version=fixture.source_versions["alpha"],
                        source_root=fixture.repo / "plugins/alpha",
                    )
            self.assertEqual(attempts, 2)
            self.assertEqual(len(list((fixture.codex_home / "plugins/cache/test").iterdir())), 3)
            self.assertFalse((fixture.codex_home / "plugins/omh-install-residue").exists())

    def test_changed_residue_after_retry_is_preserved_and_stops_success(self) -> None:
        for mutation in ("content", "replacement", "layout"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                fixture = HarnessFixture(Path(tmp))
                staging = fixture.codex_home / "plugins/cache/test/plugin-install-changed"
                attempts = 0
                def add(*args, **kwargs):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        write_staged_copy(fixture, staging.name)
                        return result(1, stderr=COPY_DENIED)
                    if mutation == "content":
                        (staging / "alpha" / fixture.source_versions["alpha"] / ".codex-plugin/plugin.json").write_bytes(b"changed")
                    elif mutation == "replacement":
                        staging.rename(staging.with_name("saved-original"))
                        write_staged_copy(fixture, staging.name)
                    else:
                        (staging / "user.txt").write_text("keep", encoding="utf-8")
                    return result(0)
                with (
                    mock.patch.object(refresh.sys, "platform", "win32"),
                    mock.patch.object(refresh.subprocess, "run", side_effect=add),
                    mock.patch.object(refresh.time, "sleep"),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    with self.assertRaisesRegex(SystemExit, "residue changed"):
                        refresh.add_codex_plugin(
                            "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                            dry_run=False, version=fixture.source_versions["alpha"],
                            source_root=fixture.repo / "plugins" / "alpha",
                        )
                self.assertTrue(staging.is_dir())
                self.assertFalse((fixture.codex_home / "plugins/omh-install-residue").exists())

    def test_version_root_reparse_point_is_not_a_staging_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "user.txt").write_text("keep", encoding="utf-8")
            staging = fixture.codex_home / "plugins/cache/test/plugin-install-junction"
            plugin = staging / "alpha"
            plugin.mkdir(parents=True)
            version = plugin / fixture.source_versions["alpha"]
            if os.name == "nt":
                linked = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(version), str(outside)], capture_output=True)
                self.assertEqual(linked.returncode, 0, linked.stderr)
            else:
                version.symlink_to(outside, target_is_directory=True)
            self.assertIsNone(refresh._expected_staging_tree(
                staging, plugin="alpha", version=version.name,
                source_root=fixture.repo / "plugins/alpha",
            ))
            self.assertEqual((outside / "user.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue(version.is_dir())

    def test_observation_failures_preserve_original_cli_failure(self) -> None:
        # Before first add, after failure, before retry, and final quarantine
        # observations are distinct failure boundaries.
        for failing_scan in (2, 3, 4):
            with self.subTest(failing_scan=failing_scan), tempfile.TemporaryDirectory() as tmp:
                fixture = HarnessFixture(Path(tmp))
                attempts = 0
                scans = 0
                original_scan = refresh._staging_entries
                def scan(root):
                    nonlocal scans
                    scans += 1
                    if scans == failing_scan:
                        raise PermissionError("scan blocked")
                    return original_scan(root)
                def add(*args, **kwargs):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        write_staged_copy(fixture, "plugin-install-scan")
                    return result(7, stdout="original stdout", stderr=COPY_DENIED if attempts == 1 else "other failure")
                with (
                    mock.patch.object(refresh.sys, "platform", "win32"),
                    mock.patch.object(refresh.subprocess, "run", side_effect=add),
                    mock.patch.object(refresh, "_staging_entries", side_effect=scan),
                    mock.patch.object(refresh.time, "sleep"),
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()) as diagnostic,
                ):
                    with self.assertRaises(subprocess.CalledProcessError) as raised:
                        refresh.add_codex_plugin(
                            "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                            dry_run=False, version=fixture.source_versions["alpha"],
                            source_root=fixture.repo / "plugins/alpha",
                        )
                self.assertEqual(raised.exception.returncode, 7)
                self.assertEqual(raised.exception.output, "original stdout")
                self.assertEqual(raised.exception.stderr, COPY_DENIED if attempts == 1 else "other failure")
                self.assertIn("scan blocked", diagnostic.getvalue())

    def test_quarantine_never_overwrites_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            retained = fixture.codex_home / "plugins/omh-install-residue/test/plugin-install-collision"
            retained.mkdir(parents=True)
            (retained / "context.json").write_text("existing evidence", encoding="utf-8")
            attempts = 0
            def add(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    write_staged_copy(fixture, retained.name)
                    return result(1, stderr=COPY_DENIED)
                return result(0)
            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh.subprocess, "run", side_effect=add),
                mock.patch.object(refresh.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaisesRegex(SystemExit, "failed to quarantine"):
                    refresh.add_codex_plugin(
                        "codex", "alpha@test", env={"CODEX_HOME": str(fixture.codex_home)},
                        dry_run=False, version=fixture.source_versions["alpha"],
                        source_root=fixture.repo / "plugins/alpha",
                    )
            self.assertEqual((retained / "context.json").read_text(encoding="utf-8"), "existing evidence")
            self.assertTrue((fixture.codex_home / "plugins/cache/test" / retained.name).is_dir())

    def test_exhausted_add_rolls_back_newly_activated_plugins_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            fixture.enabled.add("alpha")
            fixture.configure_plugins()
            fixture._write_cache("alpha")
            source_cache = fixture.codex_home / "plugins" / "cache" / "test" / "alpha"
            attempts = 0

            def fail_after_partial_activation(command, **kwargs):
                nonlocal attempts
                attempts += 1
                self.assertEqual(command, ["codex", "plugin", "add", "beta@test"])
                fixture.enabled.add("beta")
                fixture.events.append("add:beta")
                write_staged_copy(fixture, f"plugin-install-fail{attempts}", plugin="beta")
                return result(1, stderr=COPY_DENIED)

            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh, "read_codex_plugin_rows", side_effect=fixture.rows),
                mock.patch.object(refresh, "run", side_effect=fixture.run),
                mock.patch.object(refresh.subprocess, "run", side_effect=fail_after_partial_activation) as run,
                mock.patch.object(refresh.time, "sleep") as sleep,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    refresh.apply_codex_harness(
                        fixture.catalog,
                        codex="codex",
                        codex_home=fixture.codex_home,
                        marketplace_name="test",
                        excluded_skill_roots=(fixture.target,),
                        marketplace_source_binding=refresh.MarketplaceSourceBinding("local", str(fixture.repo)),
                        env={"CODEX_HOME": str(fixture.codex_home)},
                        dry_run=False,
                    )
            self.assertEqual(run.call_count, 3)
            self.assertEqual(sleep.call_args_list, [mock.call(0.5), mock.call(1.0)])
            self.assertEqual(fixture.enabled, {"alpha"})
            self.assertTrue(source_cache.is_dir())
            self.assertEqual(fixture.events, ["add:beta", "add:beta", "add:beta", "remove:beta"])
            cache = fixture.codex_home / "plugins" / "cache" / "test"
            self.assertEqual({path.name for path in cache.iterdir()}, {"alpha"})
            retained = fixture.codex_home / "plugins" / "omh-install-residue" / "test"
            self.assertEqual(len(list(retained.iterdir())), 3)


    def test_closure_failure_after_retry_success_still_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = HarnessFixture(Path(tmp))
            fixture.bad_cached_identity = "beta"
            attempts = 0

            def add_after_transient_denial(command, **kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    write_staged_copy(fixture, "plugin-install-abc123")
                    return result(1, stderr=COPY_DENIED)
                fixture.run(command, env={}, dry_run=False)
                return result(0)

            with (
                mock.patch.object(refresh.sys, "platform", "win32"),
                mock.patch.object(refresh, "read_codex_plugin_rows", side_effect=fixture.rows),
                mock.patch.object(refresh, "run", side_effect=fixture.run),
                mock.patch.object(refresh.subprocess, "run", side_effect=add_after_transient_denial),
                mock.patch.object(refresh.time, "sleep") as sleep,
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaisesRegex(SystemExit, "cache content identity differs"):
                    refresh.apply_codex_harness(
                        fixture.catalog, codex="codex", codex_home=fixture.codex_home,
                        marketplace_name="test", excluded_skill_roots=(fixture.target,),
                        marketplace_source_binding=refresh.MarketplaceSourceBinding("local", str(fixture.repo)),
                        env={"CODEX_HOME": str(fixture.codex_home)}, dry_run=False,
                    )
            self.assertEqual(attempts, 3)
            sleep.assert_called_once_with(0.5)
            self.assertEqual(fixture.enabled, set())
            self.assertEqual(fixture.events, ["add:alpha", "add:beta", "remove:beta", "remove:alpha"])

    def test_mocked_update_transaction_restores_checkout_and_recorded_revision(self) -> None:
        """Exercise real update/resume/rollback orchestration with fake Git/CLI transports."""
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            home = Path(tmp)
            repo = home / "repo"
            repo.mkdir()
            args = omh.build_parser().parse_args(["--home", tmp, "update", "main"])
            manager = dict(repository="fixture-origin", revision="old", releaseVersion="1.0.0",
                           bundleIdentity="old-bundle", channel="main", requestedRef="main")
            desired = {"harnesses": ["codex"], "updatePolicy": {"channel": "main"}}
            state = {"revision": "old"}
            operation = {}
            checkouts = []
            invoked = []
            child_errors = []

            def git(_repo, *args, **kwargs):
                if args[0] == "checkout":
                    state["revision"] = args[-1]
                    checkouts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            def begin(_home, **kwargs):
                operation.update(operationId="retry-transaction", **kwargs)
                return operation

            def refresh_one(*args, **kwargs):
                if state["revision"] == "new":
                    recorded = json.loads(manager_file(home).read_text(encoding="utf-8"))
                    self.assertEqual(recorded["revision"], "new")
                    refresh.add_codex_plugin("codex", "alpha@test", env={}, dry_run=False)

            def invoke(_repo, _home, command, *args):
                invoked.append(command)
                resume = argparse.Namespace(home=tmp, operation_id=operation["operationId"], detail="copy denied")
                try:
                    code = (omh.command_resume_update(resume) if command == "_resume-update"
                            else omh.command_resume_rollback(resume))
                except (Exception, SystemExit) as exc:
                    child_errors.append(exc)
                    code = 1
                return subprocess.CompletedProcess([command], code)

            patches = {
                "REPO_ROOT": repo,
                "ManagerLock": mock.Mock(return_value=contextlib.nullcontext()),
                "_state_context": mock.Mock(return_value=(manager, desired)),
                "_worktree_clean": mock.Mock(return_value=True),
                "_repository": mock.Mock(return_value="fixture-origin"),
                "_git": mock.Mock(side_effect=git),
                "_target_revision": mock.Mock(return_value=("main", "new")),
                "_revision": mock.Mock(side_effect=lambda *_: state["revision"]),
                "_validate_update_target": mock.Mock(return_value=("2.0.0", "new-bundle")),
                "_instruction_transition": mock.Mock(return_value=({"path": "AGENTS.md"}, {"path": "AGENTS.md"})),
                "_harness_names_at_revision": mock.Mock(return_value=("codex",)),
                "validate_harness_receipts": mock.Mock(),
                "translate_harness_receipts": mock.Mock(),
                "begin_operation": mock.Mock(side_effect=begin),
                "load_current_operation": mock.Mock(return_value=operation),
                "_journal_instruction_transition": mock.Mock(side_effect=lambda _home, op: op),
                "update_operation": mock.Mock(),
                "_bootstrap_tooling": mock.Mock(),
                "_invoke_internal": mock.Mock(side_effect=invoke),
                "_distribution": mock.Mock(side_effect=lambda *_: ("2.0.0", "new-bundle") if state["revision"] == "new" else ("1.0.0", "old-bundle")),
                "_refresh_one": mock.Mock(side_effect=refresh_one),
                "_write_harness_state": mock.Mock(),
                "_restore_update_instruction_copies": mock.Mock(),
                "write_desired": mock.Mock(),
                "finish_operation": mock.Mock(),
            }
            for name, value in patches.items():
                stack.enter_context(mock.patch.object(omh, name, value))
            stack.enter_context(mock.patch.object(instructions, "materialized_instruction_digest", return_value="fixture-digest"))
            stack.enter_context(mock.patch.object(installer, "write_launchers"))
            stack.enter_context(mock.patch.object(refresh.sys, "platform", "win32"))
            run = stack.enter_context(mock.patch.object(refresh.subprocess, "run", return_value=result(1, stderr=COPY_DENIED)))
            sleep = stack.enter_context(mock.patch.object(refresh.time, "sleep"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            with self.assertRaisesRegex(SystemExit, "update failed and was rolled back"):
                omh.command_update(args)
            self.assertEqual(run.call_count, 3)
            self.assertEqual(sleep.call_args_list, [mock.call(0.5), mock.call(1.0)])
            self.assertEqual(len(child_errors), 1)
            self.assertIsInstance(child_errors[0], subprocess.CalledProcessError)
            self.assertEqual(child_errors[0].stderr, COPY_DENIED)
            self.assertEqual(invoked, ["_resume-update", "_resume-rollback"])
            self.assertEqual(checkouts, ["new", "old"])
            self.assertEqual(state["revision"], "old")
            recorded = json.loads(manager_file(home).read_text(encoding="utf-8"))
            self.assertEqual(recorded["revision"], "old")
            self.assertEqual(recorded["status"], "ready")
            patches["finish_operation"].assert_called_once_with(home, outcome="rolled-back", detail="copy denied")


if __name__ == "__main__":
    unittest.main()
