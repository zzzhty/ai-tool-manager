from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


TEST_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TEST_ROOT.parents[1]
ROOT = REPO_ROOT / "plugins" / "watcher"
SCRIPTS = ROOT / "scripts"
ROOT_SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(ROOT_SCRIPTS))
sys.path.insert(0, str(SCRIPTS))

import refresh_harness  # noqa: E402
from watcher_runtime.skill.codex_hook_adapter import (  # noqa: E402
    HookRuntimePaths,
    discover_watcher_skill_identities,
    discover_skill_metadata,
    load_dynamic_monitored_skills,
    normalize_hook_payload,
    process_hook,
    write_hook_event,
)
from watcher_runtime.skill.codex_hook_config import (  # noqa: E402
    default_python,
    install_skill_watcher_hooks,
    remove_skill_watcher_hooks,
    skill_watcher_command,
)
from check_harness import CheckRunner, decode_subprocess_output  # noqa: E402
from watcher_runtime.skill.doctor import (  # noqa: E402
    find_managed_hook_issues,
    main as doctor_main,
    validator_path,
)
from watcher_runtime.skill.migrate_skill_watcher_schema import main as reset_schema_main  # noqa: E402
from watcher_runtime.skill.report_pipeline import (  # noqa: E402
    event_hash,
    load_report_state,
    report_state_key,
    save_report_state,
    state_since,
    skill_logical_groups,
    usage_rows,
    update_report_state,
)
from watcher_runtime.skill.propose_skill_patch import build_proposal, main as propose_main  # noqa: E402
from watcher_runtime.skill.redact_event import REDACTION, redact_event  # noqa: E402
from refresh_harness import (  # noqa: E402
    cached_plugin_names,
    codex_plugin_selectors,
    configured_plugin_names,
    default_plugin_names,
    marketplace_source_arg,
    resolve_codex_executable,
    stale_plugin_names,
)
from repo_skill_catalog import load_repo_skill_catalog  # noqa: E402
from watcher_runtime.skill.runtime_paths import (  # noqa: E402
    ensure_runtime_dirs as runtime_ensure_runtime_dirs,
    hook_backup_dir,
    log_file_path,
    report_state_path as runtime_report_state_path,
    reports_dir,
    safe_slug as runtime_safe_slug,
    state_dir_from_env_or_arg as runtime_state_dir_from_env_or_arg,
    turns_dir,
)
from watcher_runtime.skill.report_pipeline import (  # noqa: E402
    ReportOutputPolicy,
    ReportQuery,
    generate_report as run_report_pipeline,
)
from sync_codex_agents import load_sources  # noqa: E402
from watcher_runtime.skill.report_pipeline import parse_since, read_events_since  # noqa: E402
from watcher_runtime.skill.proposal_artifact import update_status  # noqa: E402
from watcher_runtime.skill.validate_candidate import (  # noqa: E402
    main as validate_candidate_main,
    validate_skill,
)


WINDOWS_PWSH_ENCODING_TEST = unittest.skipUnless(
    sys.platform == "win32",
    "Windows PowerShell encoding regression",
)


def initialize_catalog_repo(root: Path, skills: dict[str, tuple[str, ...]]) -> None:
    catalog_target = root / "scripts" / "repo_skill_catalog.py"
    catalog_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT_SCRIPTS / "repo_skill_catalog.py", catalog_target)
    watcher_cli = root / "plugins" / "watcher" / "scripts" / "watcher"
    watcher_cli.parent.mkdir(parents=True, exist_ok=True)
    watcher_cli.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    for plugin_name, callable_names in skills.items():
        for callable_name in callable_names:
            skill_file = root / "plugins" / plugin_name / "skills" / callable_name / "SKILL.md"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(
                f"---\nname: {callable_name}\ndescription: Test.\n---\n",
                encoding="utf-8",
            )


def write_attribution_overlay(root: Path, plugin_name: str, payload: dict[str, object]) -> Path:
    path = root / "plugins" / plugin_name / ".codex-plugin" / "skill-watcher.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class SkillWatcherTests(unittest.TestCase):
    class StrictAsciiStdout:
        encoding = "ascii"

        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, text: str) -> int:
            text.encode("ascii")
            self.writes.append(text)
            return len(text)

        def flush(self) -> None:
            return None

    def test_skill_doctor_prefers_complete_system_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            scripts = codex_home / "skills" / ".system" / "plugin-creator" / "scripts"
            scripts.mkdir(parents=True)
            expected = scripts / "validate_plugin.py"
            expected.write_text("# validator fixture\n", encoding="utf-8")
            (scripts / "identifier_validation.py").write_text(
                "# identifier fixture\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                validator = validator_path(REPO_ROOT, codex_home=codex_home)

        self.assertEqual(validator, expected)

    def test_skill_doctor_falls_back_for_incomplete_system_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            scripts = codex_home / "skills" / ".system" / "plugin-creator" / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "validate_plugin.py").write_text(
                "# validator fixture\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                validator = validator_path(REPO_ROOT, codex_home=codex_home)

        self.assertEqual(validator, REPO_ROOT / "scripts" / "validate_plugin.py")

    def test_skill_doctor_preserves_explicit_validator_override(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"PLUGIN_VALIDATOR": "/custom/validate_plugin.py"},
            clear=True,
        ):
            validator = validator_path(REPO_ROOT)

        self.assertEqual(validator, Path("/custom/validate_plugin.py"))

    @WINDOWS_PWSH_ENCODING_TEST
    def test_check_runner_tolerates_non_utf8_subprocess_output(self) -> None:
        runner = CheckRunner()

        result = runner.run_command(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\x82')"],
            env={},
        )

        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout)

    @WINDOWS_PWSH_ENCODING_TEST
    def test_subprocess_output_prefers_utf8_with_replacement(self) -> None:
        raw = "▶ 系统找不到指定的文件。".encode("utf-8") + b"\x82"

        decoded = decode_subprocess_output(raw)

        self.assertIn("▶ 系统找不到指定的文件。", decoded)
        self.assertIn("\ufffd", decoded)

    @WINDOWS_PWSH_ENCODING_TEST
    def test_check_runner_prints_unencodable_failures_safely(self) -> None:
        runner = CheckRunner()
        stdout = self.StrictAsciiStdout()

        with mock.patch("sys.stdout", stdout):
            runner.fail("plugin output contains ▶")

        self.assertIn(r"\u25b6", "".join(stdout.writes))

    def test_check_runner_reports_permission_error_without_traceback(self) -> None:
        runner = CheckRunner()

        def denied_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            raise PermissionError("denied")

        with mock.patch("check_harness.subprocess.run", denied_run):
            result = runner.run_command(["codex", "plugin", "list"], env={})

        self.assertEqual(result.returncode, 126)
        self.assertIn("command not executable: codex", result.stderr)

    @mock.patch("refresh_harness.codex_executable_is_startable", return_value=True)
    def test_windows_codex_resolution_uses_path_then_managed_fallbacks(
        self, _startable: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_home = root / "UserProfile"
            local_app_data = root / "LocalAppData"
            codex_home = user_home / ".codex"
            visible_cli = local_app_data / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
            standalone_cli = codex_home / "packages" / "standalone" / "current" / "bin" / "codex.exe"
            legacy_standalone_cli = codex_home / "packages" / "standalone" / "current" / "codex.exe"
            desktop_cli = local_app_data / "OpenAI" / "Codex" / "bin" / "abc123" / "codex.exe"
            extension_cli = (
                user_home
                / ".vscode"
                / "extensions"
                / "openai.chatgpt-1.2.3"
                / "bin"
                / "windows-x86_64"
                / "codex.exe"
            )
            for candidate in (visible_cli, standalone_cli, legacy_standalone_cli, desktop_cli, extension_cli):
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("", encoding="utf-8")
            path_cli = root / "WindowsApps" / "OpenAI.Codex" / "codex.exe"

            with mock.patch.object(refresh_harness.sys, "platform", "win32"):
                with mock.patch("refresh_harness.platform.machine", return_value="AMD64"):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "HOME": str(user_home),
                            "LOCALAPPDATA": str(local_app_data),
                            "USERPROFILE": str(user_home),
                        },
                        clear=True,
                    ):
                        with mock.patch("refresh_harness.shutil.which", return_value=str(path_cli)):
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(path_cli),
                            )

                        with mock.patch("refresh_harness.shutil.which", return_value=None):
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(visible_cli),
                            )
                            visible_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(standalone_cli),
                            )
                            standalone_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(legacy_standalone_cli),
                            )
                            legacy_standalone_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(desktop_cli),
                            )
                            desktop_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(extension_cli),
                            )

    def test_unix_codex_resolution_uses_path_then_standalone_then_vscode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_home = root / "home"
            codex_home = user_home / ".codex"
            custom_visible_cli = root / "custom-install" / "codex"
            visible_cli = user_home / ".local" / "bin" / "codex"
            standalone_cli = codex_home / "packages" / "standalone" / "current" / "bin" / "codex"
            legacy_standalone_cli = codex_home / "packages" / "standalone" / "current" / "codex"
            extension_cli = (
                user_home
                / ".vscode-server"
                / "extensions"
                / "openai.chatgpt-1.2.3"
                / "bin"
                / "linux-x86_64"
                / "codex"
            )
            for candidate in (custom_visible_cli, visible_cli, standalone_cli, legacy_standalone_cli, extension_cli):
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text("", encoding="utf-8")
            path_cli = root / "path" / "codex"

            with mock.patch.object(refresh_harness.sys, "platform", "linux"):
                with mock.patch("refresh_harness.platform.machine", return_value="x86_64"):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "CODEX_INSTALL_DIR": str(custom_visible_cli.parent),
                            "HOME": str(user_home),
                        },
                        clear=True,
                    ):
                        with mock.patch("refresh_harness.shutil.which", return_value=str(path_cli)):
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(path_cli),
                            )

                        with mock.patch("refresh_harness.shutil.which", return_value=None):
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(custom_visible_cli),
                            )
                            custom_visible_cli.unlink()
                            os.environ.pop("CODEX_INSTALL_DIR")
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(visible_cli),
                            )
                            visible_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(standalone_cli),
                            )
                            standalone_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(legacy_standalone_cli),
                            )
                            legacy_standalone_cli.unlink()
                            self.assertEqual(
                                resolve_codex_executable(None, codex_home=codex_home),
                                str(extension_cli),
                            )

    def test_codex_resolution_treats_explicit_sources_as_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / ".codex"
            configured_cli = root / "configured" / "codex"
            configured_cli.parent.mkdir(parents=True)
            configured_cli.write_text("", encoding="utf-8")
            explicit_cli = root / "explicit" / "codex"
            explicit_cli.parent.mkdir(parents=True)
            explicit_cli.write_text("", encoding="utf-8")

            with mock.patch.dict(os.environ, {"CODEX_BIN": str(configured_cli)}, clear=True):
                self.assertEqual(
                    resolve_codex_executable(str(explicit_cli), codex_home=codex_home),
                    str(explicit_cli),
                )

                with self.assertRaisesRegex(SystemExit, "missing-explicit"):
                    resolve_codex_executable(str(root / "missing-explicit" / "codex"), codex_home=codex_home)

            with mock.patch.dict(
                os.environ,
                {"CODEX_BIN": str(root / "missing-configured" / "codex")},
                clear=True,
            ):
                with self.assertRaisesRegex(SystemExit, "missing-configured"):
                    resolve_codex_executable(None, codex_home=codex_home)

    def test_watcher_plugin_validation_uses_tooling_python(self) -> None:
        runner = CheckRunner()
        calls = []

        def fake_run_command(command, *, env, cwd=None):  # type: ignore[no-untyped-def]
            calls.append((command, cwd))
            return subprocess.CompletedProcess(command, 0, "ok", "")

        runner.run_command = fake_run_command  # type: ignore[method-assign]
        tooling_python = Path("C:/tooling/python.exe")
        validator = Path(__file__)

        runner.check_plugin_validation(
            tooling_python,
            ["watcher@oh-my-harness"],
            env={},
            validator=validator,
        )

        self.assertEqual(calls[0][0][0], str(tooling_python))
        self.assertEqual(calls[0][0][1], str(validator))
        self.assertIsNone(calls[0][1])

    def test_check_runner_uses_canonical_watcher_doctor_entrypoint(self) -> None:
        runner = CheckRunner()
        calls: list[list[str]] = []

        def fake_run_command(command, *, env, cwd=None):  # type: ignore[no-untyped-def]
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        runner.run_command = fake_run_command  # type: ignore[method-assign]
        tooling_python = Path("C:/tooling/python.exe")

        runner.check_doctor(tooling_python, env={})

        self.assertEqual(
            calls,
            [
                [
                    str(tooling_python),
                    str(ROOT / "scripts" / "watcher"),
                    "skill",
                    "doctor",
                    "--repo-root",
                    str(REPO_ROOT),
                ]
            ],
        )

    def test_skill_doctor_runs_entirely_in_temporary_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "watcher" / "skill"
            hook_target = root / "hooks.json"
            validator = root / "validate_plugin.py"
            validator.write_text("raise SystemExit(0)\n", encoding="utf-8")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                result = doctor_main(
                    [
                        "--repo-root",
                        str(REPO_ROOT),
                        "--state-dir",
                        str(state_dir),
                        "--hook-target",
                        str(hook_target),
                        "--python",
                        sys.executable,
                        "--validator",
                        str(validator),
                    ]
                )

            self.assertEqual(result, 0, output.getvalue())
            self.assertTrue((state_dir / "logs").is_dir())
            self.assertTrue((state_dir / "reports").is_dir())
            self.assertIn("doctor passed with 1 warning(s)", output.getvalue())

    def test_install_manifest_drives_default_plugin_selection(self) -> None:
        expected = [
            "watcher",
            "workflow",
            "mattpocock-skills",
        ]

        self.assertEqual(
            default_plugin_names("install", marketplace_name="oh-my-harness"),
            expected,
        )
        self.assertEqual(
            codex_plugin_selectors("oh-my-harness", action="install"),
            [f"{plugin}@oh-my-harness" for plugin in expected],
        )

    def test_install_manifest_fails_when_selected_plugin_is_missing_from_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = tmp_path / "install-manifest.json"
            marketplace = tmp_path / "marketplace.json"
            manifest.write_text(
                json.dumps(
                    {
                        "harness": "codex",
                        "marketplace": "oh-my-harness",
                        "plugins": [
                            {"name": "missing-plugin", "install": True, "check": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            marketplace.write_text(
                json.dumps({"name": "oh-my-harness", "plugins": [{"name": "skill-watcher"}]}),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit) as raised:
                codex_plugin_selectors(
                    "oh-my-harness",
                    action="install",
                    manifest_file=manifest,
                    marketplace_file=marketplace,
                )

        self.assertIn("missing-plugin", str(raised.exception))

    def test_stale_plugin_detection_includes_config_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            config = codex_home / "config.toml"
            config.write_text(
                "\n".join(
                    [
                        '[plugins."workflow@oh-my-harness"]',
                        "enabled = true",
                        '[plugins."old-plugin@oh-my-harness"]',
                        "enabled = true",
                        '[plugins."github@openai-curated"]',
                        "enabled = true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cache_root = codex_home / "plugins" / "cache" / "oh-my-harness"
            (cache_root / "workflow" / "0.1.0").mkdir(parents=True)
            (cache_root / "cached-old" / "0.1.0").mkdir(parents=True)

            self.assertEqual(configured_plugin_names(codex_home, "oh-my-harness"), {"workflow", "old-plugin"})
            self.assertEqual(cached_plugin_names(codex_home, "oh-my-harness"), {"workflow", "cached-old"})
            self.assertEqual(
                stale_plugin_names(
                    codex_home=codex_home,
                    marketplace_name="oh-my-harness",
                    desired_plugin_names=["workflow"],
                ),
                ["cached-old", "old-plugin"],
            )

    def test_agent_sync_ignores_legacy_custom_agent_toml_presets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp)
            (source_root / "operating-principles.md").write_text("support note\n", encoding="utf-8")
            (source_root / "reviewer.toml").write_text('name = "reviewer"\n', encoding="utf-8")

            sources = load_sources(source_root)

        self.assertEqual([source.target_name for source in sources], ["operating-principles.md"])

    def test_redacts_secret_keys_and_values(self) -> None:
        payload = {
            "api_key": "plain-secret",
            "notes": "Bearer abcdefghijklmnop and sk-testsecret123",
            "nested": {"refresh_token": "another-secret"},
        }

        redacted = redact_event(payload)

        self.assertEqual(redacted["api_key"], REDACTION)
        self.assertEqual(redacted["nested"]["refresh_token"], REDACTION)
        self.assertNotIn("sk-testsecret123", json.dumps(redacted))
        self.assertNotIn("abcdefghijklmnop", json.dumps(redacted))

    def test_matt_selection_preserves_invocation_and_historical_attribution(self) -> None:
        metadata = discover_skill_metadata(REPO_ROOT)
        watcher_identities = set(metadata["skills"])
        selected = {
            "ask-matt", "code-review", "codebase-design", "diagnosing-bugs",
            "domain-modeling", "grill-me", "grill-with-docs", "grilling", "handoff",
            "implement", "improve-codebase-architecture", "pr", "prototype", "research",
            "retro", "tdd", "teach",
            "to-spec", "triage", "writing-for-agents",
        }
        self.assertEqual(len(watcher_identities), 30)
        self.assertEqual(
            {name.split(":", 1)[1] for name in watcher_identities if name.startswith("mattpocock-skills:")},
            selected,
        )
        for skill_name in selected:
            full_name = f"mattpocock-skills:{skill_name}"
            aliases = metadata["skills"][full_name]["aliases"]
            self.assertIn(
                {"value": full_name, "kind": "skill_name", "match": "phrase"},
                aliases,
            )
            if skill_name in {"code-review", "implement", "research", "to-spec", "writing-for-agents"}:
                self.assertIn(
                    {"value": skill_name, "kind": "slug", "match": "token"},
                    aliases,
                )

        pr_aliases = metadata["skills"]["mattpocock-skills:pr"]["aliases"]
        self.assertNotIn("pr", {alias["value"] for alias in pr_aliases})
        self.assertIn(
            {"value": "pull request body", "kind": "phrase", "match": "phrase"},
            pr_aliases,
        )

        explicit_workflows = {
            "ask-matt",
            "grill-me",
            "grill-with-docs",
            "handoff",
            "implement",
            "improve-codebase-architecture",
            "retro",
            "teach",
            "to-spec",
            "triage",
        }
        for full_name, values in metadata["skills"].items():
            if not full_name.startswith("mattpocock-skills:"):
                continue
            skill_name = full_name.split(":", 1)[1]
            expected_group = (
                "explicit-workflows"
                if skill_name in explicit_workflows
                else "implicit-primitives"
            )
            self.assertEqual(values["logical_group"], expected_group)

        local_groups = {
            "watcher:doc-alignment": "implicit-primitives",
            "watcher:housekeeping": "implicit-primitives",
            "watcher:skill-compressor": "implicit-primitives",
            "watcher:skill-maintainer": "implicit-primitives",
            "workflow:long-running-goal": "explicit-workflows",
            "workflow:orchestrate-subagents": "explicit-workflows",
            "workflow:prompt-strategy-loop": "implicit-primitives",
            "workflow:scope-discipline": "explicit-workflows",
            "workflow:sop": "implicit-primitives",
            "workflow:summary-in-html": "implicit-primitives",
        }
        for skill_name, expected_group in local_groups.items():
            self.assertEqual(metadata["skills"][skill_name]["logical_group"], expected_group)
        self.assertEqual(
            metadata["skills"]["watcher:housekeeping"]["supporting_skills"],
            [],
        )

        self.assertNotIn("mattpocock-skills:to-prd", watcher_identities)
        self.assertNotIn("mattpocock-skills:to-issues", watcher_identities)
        self.assertNotIn("mattpocock-skills:writing-great-skills", watcher_identities)
        self.assertEqual(
            set(metadata["skills"]["mattpocock-skills:implement"]["supporting_skills"]),
            {
                "mattpocock-skills:code-review",
            },
        )

        renamed = (
            ("mattpocock-skills:to-prd", "to-prd", "mattpocock-skills:to-spec"),
            (
                "mattpocock-skills:write-a-skill",
                "write-a-skill",
                "mattpocock-skills:writing-for-agents",
            ),
            (
                "mattpocock-skills:writing-great-skills",
                "writing-great-skills",
                "mattpocock-skills:writing-for-agents",
            ),
        )
        for legacy_full_name, legacy_slug, current_name in renamed:
            with self.subTest(legacy_full_name=legacy_full_name, source="provided"):
                provided = normalize_hook_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "skill_name": legacy_full_name,
                    },
                    repo_root=REPO_ROOT,
                )
                self.assertEqual(provided["skill_attribution"]["primary"]["name"], current_name)
                self.assertEqual(provided["skill_attribution"]["primary"]["source"], "provided")

            for prompt_alias in (legacy_full_name, legacy_slug):
                with self.subTest(prompt_alias=prompt_alias, source="prompt_mention"):
                    prompt = normalize_hook_payload(
                        {
                            "hook_event_name": "UserPromptSubmit",
                            "prompt": f"Use ${prompt_alias} for this work",
                        },
                        repo_root=REPO_ROOT,
                    )
                    primary = prompt["skill_attribution"]["primary"]
                    self.assertEqual(primary["name"], current_name)
                    self.assertEqual(primary["source"], "prompt_mention")
                    self.assertEqual(primary["alias_kind"], "legacy")

        retired_names = {
            f"mattpocock-skills:{name}"
            for name in (
                "to-questionnaire", "to-tickets", "wait-what", "wayfinder", "wizard",
                "to-issues", "setup-matt-pocock-skills",
                "resolving-merge-conflicts",
            )
        }
        self.assertTrue(retired_names.isdisjoint(watcher_identities))
        self.assertTrue(retired_names.isdisjoint(metadata["legacy_names"]))
        self.assertTrue(retired_names.isdisjoint(metadata["legacy_names"].values()))
        events = [
            {
                "event_type": "turn_summary",
                "session_id": "historical",
                "event_id": f"turn-{number}",
                "skill_attribution": {
                    "primary": {"name": name, "role": "specialized"},
                    "supporting": [{"name": "mattpocock-skills:code-review", "role": "discipline"}],
                },
            }
            for number, name in enumerate(sorted(retired_names))
        ]
        original_events = json.loads(json.dumps(events))
        rows = {row["skill"]: row for row in usage_rows(events, skill_logical_groups(metadata))}
        for name in retired_names:
            self.assertEqual(rows[name]["primary_turns"], 1)
            self.assertEqual(rows[name]["effective_turns"], 1)
            self.assertEqual(rows[name]["logical_group"], "")
        self.assertEqual(rows["mattpocock-skills:code-review"]["supporting_turns"], len(events))
        self.assertEqual(events, original_events)

    def test_retro_attribution_is_narrow_and_does_not_compose_other_workflows(self) -> None:
        metadata = discover_skill_metadata(REPO_ROOT)
        retro = "mattpocock-skills:retro"
        self.assertEqual(metadata["skills"][retro]["logical_group"], "explicit-workflows")
        self.assertEqual(metadata["skills"][retro]["supporting_skills"], [])
        for name, skill in metadata["skills"].items():
            self.assertNotIn(retro, skill["supporting_skills"], name)
        for prompt in ("Use $mattpocock-skills:retro for this session", "/retro", "Run /retro on this session"):
            with self.subTest(prompt=prompt):
                event = normalize_hook_payload(
                    {"hook_event_name": "UserPromptSubmit", "prompt": prompt},
                    repo_root=REPO_ROOT,
                )
                self.assertEqual(event["skill_attribution"]["primary"]["name"], retro)
        # These checks cover attribution, not a model's decision to invoke a skill.
        for prompt in (
            "The task is complete", "The test failed again", "I like retro games",
            "Review this coding session", "Open /retrospective or /retrofit",
        ):
            with self.subTest(prompt=prompt):
                event = normalize_hook_payload(
                    {"hook_event_name": "UserPromptSubmit", "prompt": prompt},
                    repo_root=REPO_ROOT,
                )
                self.assertNotEqual((event["skill_attribution"]["primary"] or {}).get("name"), retro)

    def test_codex_hook_lifecycle_filters_summarizes_and_guards_skill_list(self) -> None:
        catalog = load_repo_skill_catalog(REPO_ROOT)
        watcher_identities = sorted(
            f"{source.plugin}:{source.name}"
            for source in catalog.sources
        )
        self.assertIn("mattpocock-skills:ask-matt", watcher_identities)
        self.assertEqual(
            discover_watcher_skill_identities(REPO_ROOT),
            tuple(watcher_identities),
        )
        metadata = discover_skill_metadata(REPO_ROOT)
        self.assertEqual(set(metadata["skills"]), set(watcher_identities))
        self.assertEqual(
            metadata["legacy_names"]["mattpocock-skills:diagnose"],
            "mattpocock-skills:diagnosing-bugs",
        )
        self.assertEqual(
            metadata["skills"]["mattpocock-skills:grill-with-docs"]["supporting_skills"],
            ["mattpocock-skills:domain-modeling", "mattpocock-skills:grilling"],
        )

        normalized = normalize_hook_payload(
            {
                "hook_event_name": "PostToolUse",
                "cwd": "/tmp/workspace",
                "session_id": "session-1",
                "turn_id": "turn-1",
                "tool_name": "Bash",
                "tool_input": {"command": "printf sk-testsecret123456789"},
                "tool_response": {"exit_code": 1, "stderr": "error token sk-testsecret123456789"},
            },
            repo_root=REPO_ROOT,
        )
        serialized = json.dumps(normalized, sort_keys=True)
        self.assertEqual(normalized["event_type"], "post_tool_use")
        self.assertNotIn("skill_name", normalized)
        self.assertIsNone(normalized["skill_attribution"]["primary"])
        self.assertEqual(normalized["outcome"], "failure")
        self.assertEqual(normalized["failure_type"], "tool_error")
        self.assertIn("tool_input_summary", normalized["codex"])
        self.assertNotIn("printf sk-testsecret123456789", serialized)
        self.assertNotIn("sk-testsecret123456789", serialized)

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            session_start = write_hook_event(
                {
                    "hook_event_name": "SessionStart",
                    "cwd": "/tmp/workspace",
                    "session_id": "session-start",
                    "turn_id": "turn-start",
                },
                state_dir=state_dir,
                repo_root=REPO_ROOT,
            )
            unknown = write_hook_event(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "cwd": "/tmp/workspace",
                    "session_id": "session-unknown",
                    "turn_id": "turn-unknown",
                    "prompt": "ordinary task without a monitored skill",
                },
                state_dir=state_dir,
                repo_root=REPO_ROOT,
            )
            base = {
                "cwd": "/tmp/workspace",
                "session_id": "session-2",
                "turn_id": "turn-2",
            }
            prompt = write_hook_event(
                {
                    **base,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Use diagnose on flaky tests with sk-testsecret123456789",
                },
                state_dir=state_dir,
                repo_root=REPO_ROOT,
            )
            success = write_hook_event(
                {
                    **base,
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_response": {"exit_code": 0, "stdout": "ok"},
                },
                state_dir=state_dir,
                repo_root=REPO_ROOT,
            )
            failure = write_hook_event(
                {
                    **base,
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_response": {"exit_code": 1, "stderr": "error"},
                },
                state_dir=state_dir,
                repo_root=REPO_ROOT,
            )
            summary = write_hook_event(
                {**base, "hook_event_name": "Stop"},
                state_dir=state_dir,
                repo_root=REPO_ROOT,
            )
            lines = log_file_path(state_dir).read_text(encoding="utf-8").splitlines()
            dynamic_skills = load_dynamic_monitored_skills(state_dir)

        self.assertFalse(session_start["codex"]["persisted"])
        self.assertEqual(
            session_start["codex"]["metadata_update"]["skill_count"],
            len(watcher_identities),
        )
        self.assertEqual(dynamic_skills, tuple(watcher_identities))
        self.assertFalse(unknown["codex"]["persisted"])
        self.assertEqual(prompt["skill_attribution"]["primary"]["name"], "mattpocock-skills:diagnosing-bugs")
        self.assertEqual(prompt["skill_attribution"]["primary"]["source"], "prompt_mention")
        self.assertTrue(prompt["codex"]["persisted"])
        self.assertIn("user_skill_context", prompt["codex"])
        self.assertFalse(success["codex"]["persisted"])
        self.assertTrue(failure["codex"]["persisted"])
        self.assertEqual(summary["event_type"], "turn_summary")
        self.assertEqual(summary["codex"]["turn_summary"]["tool_count"], 2)
        self.assertEqual(summary["codex"]["turn_summary"]["tool_failure_count"], 1)
        self.assertEqual(summary["codex"]["turn_summary"]["task_outcome"], "unknown")
        self.assertEqual(summary["outcome"], "unknown")
        self.assertIn("user_skill_context", summary["codex"]["turn_summary"])
        self.assertEqual(len(lines), 3)
        self.assertNotIn("sk-testsecret123456789", "\n".join(lines))

        sop_prompt = normalize_hook_payload(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "请使用标准流程整理这次重复任务。",
            },
            repo_root=REPO_ROOT,
        )
        self.assertEqual(sop_prompt["skill_attribution"]["primary"]["name"], "workflow:sop")
        self.assertEqual(sop_prompt["skill_attribution"]["primary"]["source"], "prompt_mention")
        self.assertEqual(sop_prompt["skill_attribution"]["primary"]["matched_alias"], "标准流程")

        sop_assistant = normalize_hook_payload(
            {
                "hook_event_name": "Stop",
                "last_assistant_message": "I will use $sop for this recurring procedure.",
            },
            repo_root=REPO_ROOT,
        )
        self.assertEqual(sop_assistant["skill_attribution"]["primary"]["name"], "workflow:sop")
        self.assertEqual(sop_assistant["skill_attribution"]["primary"]["source"], "assistant_announcement")
        self.assertEqual(sop_assistant["skill_attribution"]["primary"]["matched_alias"], "sop")

        for ordinary_cleanup in (
            "Please clean up this parser implementation.",
            "Please do a repo cleanup of stale abstractions.",
        ):
            with self.subTest(ordinary_cleanup=ordinary_cleanup):
                cleanup_event = normalize_hook_payload(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": ordinary_cleanup,
                    },
                    repo_root=REPO_ROOT,
                )
                self.assertIsNone(cleanup_event["skill_attribution"]["primary"])

        disposable_cleanup = normalize_hook_payload(
            {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Remove disposable artifacts after validation.",
            },
            repo_root=REPO_ROOT,
        )
        self.assertEqual(
            disposable_cleanup["skill_attribution"]["primary"]["name"],
            "watcher:housekeeping",
        )

    def test_metadata_discovery_ignores_marketplace_and_plugin_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(root, {"demo": ("foo",)})
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text("{not-json\n", encoding="utf-8")
            plugin_manifest = root / "plugins" / "demo" / ".codex-plugin" / "plugin.json"
            plugin_manifest.parent.mkdir(parents=True)
            plugin_manifest.write_text("{not-json\n", encoding="utf-8")

            metadata = discover_skill_metadata(root)

        self.assertEqual(tuple(metadata["skills"]), ("demo:foo",))
        self.assertEqual(metadata["source_root"], str(root.resolve()))

    def test_metadata_discovery_requires_explicit_repository_root(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata()

        self.assertIn("pass --repo-root or set OH_MY_HARNESS_ROOT", str(raised.exception))

    def test_metadata_discovery_rejects_catalog_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            root = temporary_root / "source"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            catalog = root / "scripts" / "repo_skill_catalog.py"
            external_catalog = temporary_root / "outside-catalog.py"
            shutil.copyfile(catalog, external_catalog)
            catalog.unlink()
            try:
                catalog.symlink_to(external_catalog)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("canonical repository skill catalog escapes explicit repository root", str(raised.exception))

    def test_metadata_discovery_rejects_overlay_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            root = temporary_root / "source"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            external_overlay = temporary_root / "outside-overlay.json"
            external_overlay.write_text(
                json.dumps({"schema_version": 1, "skills": {}, "legacy_names": {}}),
                encoding="utf-8",
            )
            overlay = root / "plugins" / "demo" / ".codex-plugin" / "skill-watcher.json"
            overlay.parent.mkdir(parents=True)
            try:
                overlay.symlink_to(external_overlay)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("Watcher skill attribution overlay escapes explicit repository root", str(raised.exception))

    def test_metadata_discovery_rejects_unknown_overlay_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(root, {"demo": ("entry",)})
            write_attribution_overlay(
                root,
                "demo",
                {
                    "schema_version": 1,
                    "skills": {"demo:missing": {}},
                    "legacy_names": {},
                },
            )

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("unknown canonical skill demo:missing", str(raised.exception))

    def test_metadata_discovery_requires_known_overlay_schema(self) -> None:
        for schema_version in (None, 999):
            with self.subTest(schema_version=schema_version), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                initialize_catalog_repo(root, {"demo": ("foo",)})
                metadata: dict[str, object] = {"skills": {}, "legacy_names": {}}
                if schema_version is not None:
                    metadata["schema_version"] = schema_version
                write_attribution_overlay(root, "demo", metadata)

                with self.assertRaises(SystemExit) as raised:
                    discover_skill_metadata(root)

                self.assertIn("unsupported skill metadata schema_version", str(raised.exception))

    def test_metadata_discovery_rejects_duplicate_legacy_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(
                root,
                {"alpha": ("alpha-entry",), "beta": ("beta-entry",)},
            )
            for plugin_name, callable_name in (
                ("alpha", "alpha-entry"),
                ("beta", "beta-entry"),
            ):
                write_attribution_overlay(
                    root,
                    plugin_name,
                    {
                        "schema_version": 1,
                        "skills": {},
                        "legacy_names": {
                            "legacy:shared": f"{plugin_name}:{callable_name}"
                        },
                    },
                )

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("duplicate legacy skill metadata entries", str(raised.exception))

    def test_metadata_discovery_rejects_invalid_logical_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initialize_catalog_repo(root, {"demo": ("entry",)})
            write_attribution_overlay(
                root,
                "demo",
                {
                    "schema_version": 1,
                    "skills": {"demo:entry": {"logical_group": "Not Valid"}},
                    "legacy_names": {},
                },
            )

            with self.assertRaises(SystemExit) as raised:
                discover_skill_metadata(root)

        self.assertIn("invalid logical_group", str(raised.exception))

    def test_session_start_surfaces_metadata_discovery_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            state_dir = Path(tmp) / "state"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            overlay = root / "plugins" / "demo" / ".codex-plugin" / "skill-watcher.json"
            overlay.parent.mkdir(parents=True)
            overlay.write_text("{not-json\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as raised:
                process_hook(
                    {
                        "hook_event_name": "SessionStart",
                        "session_id": "metadata-failure",
                    },
                    HookRuntimePaths(state_dir=state_dir, log_file=log_file_path(state_dir)),
                    repo_root=root,
                )

            self.assertFalse((state_dir / "skill-metadata-cache.json").exists())

        self.assertIn("invalid skill metadata JSON", str(raised.exception))

    def test_hook_runtime_dry_run_normalizes_without_writing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            result = process_hook(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "cwd": "/tmp/workspace",
                    "session_id": "session-dry-run",
                    "turn_id": "turn-dry-run",
                    "prompt": "Use diagnose on flaky tests",
                },
                HookRuntimePaths(state_dir=state_dir, log_file=log_file_path(state_dir)),
                persist=False,
                repo_root=REPO_ROOT,
            )

            self.assertFalse(log_file_path(state_dir).exists())
            self.assertEqual(list((state_dir / "turns").glob("*.json")), [])

        self.assertTrue(result.persisted)
        self.assertEqual(result.hook_event_name, "UserPromptSubmit")
        self.assertEqual(result.event["skill_attribution"]["primary"]["name"], "mattpocock-skills:diagnosing-bugs")

    def test_explicit_repo_root_resolves_runtime_from_agents_skill_symlink(self) -> None:
        payload = json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "runtime-locator",
                "prompt": "Use diagnose on this failure",
            }
        )
        watcher = ROOT / "scripts" / "watcher"
        with tempfile.TemporaryDirectory() as tmp:
            agents_skill = Path(tmp) / "agents" / "skills" / "diagnosing-bugs"
            agents_skill.parent.mkdir(parents=True)
            try:
                agents_skill.symlink_to(
                    REPO_ROOT / "plugins" / "mattpocock-skills" / "skills" / "diagnosing-bugs",
                    target_is_directory=True,
                )
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            events = []
            for cwd in (REPO_ROOT, agents_skill):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(watcher),
                        "skill",
                        "observe",
                        "--repo-root",
                        str(REPO_ROOT),
                        "--dry-run",
                    ],
                    cwd=cwd,
                    input=payload,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                events.append(json.loads(result.stdout))

        self.assertEqual(
            events[0]["skill_attribution"],
            events[1]["skill_attribution"],
        )
        self.assertEqual(
            events[0]["skill_attribution"]["primary"]["name"],
            "mattpocock-skills:diagnosing-bugs",
        )

    def test_hook_command_quotes_space_paths_for_posix_and_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            root = temporary_root / "repo with spaces"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            python = temporary_root / "tooling python" / "python"
            adapter = root / "plugins" / "watcher" / "scripts" / "watcher"
            expected_argv = [
                str(python),
                "-B",
                str(adapter),
                "skill",
                "observe",
                "--repo-root",
                str(root.resolve()),
            ]

            with mock.patch("watcher_runtime.skill.codex_hook_config.os.name", "posix"):
                posix_command = skill_watcher_command(python, adapter, repo_root=root)
            with mock.patch("watcher_runtime.skill.codex_hook_config.os.name", "nt"):
                windows_command = skill_watcher_command(python, adapter, repo_root=root)

        self.assertEqual(shlex.split(posix_command, posix=True), expected_argv)
        self.assertEqual(windows_command, subprocess.list2cmdline(expected_argv))

    def test_reset_schema_validates_repository_before_runtime_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            log_file = log_file_path(state_dir)
            turn_file = turns_dir(state_dir) / "turn.json"
            log_file.parent.mkdir(parents=True)
            turn_file.parent.mkdir(parents=True)
            log_file.write_text("preserve-event\n", encoding="utf-8")
            turn_file.write_text('{"preserve": true}\n', encoding="utf-8")

            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit) as raised:
                    reset_schema_main(
                        [
                            "--state-dir",
                            str(state_dir),
                            "--reset-runtime-state",
                        ]
                    )

            self.assertEqual(log_file.read_text(encoding="utf-8"), "preserve-event\n")
            self.assertEqual(turn_file.read_text(encoding="utf-8"), '{"preserve": true}\n')
            self.assertFalse((state_dir / "archives").exists())
            self.assertFalse((state_dir / "skill-metadata-cache.json").exists())
            self.assertFalse((state_dir / "schema-version.json").exists())

        self.assertIn("pass --repo-root or set OH_MY_HARNESS_ROOT", str(raised.exception))

    def test_reset_schema_uses_prevalidated_explicit_repository_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temporary_root = Path(tmp)
            root = temporary_root / "repo with spaces"
            state_dir = temporary_root / "state"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            log_file = log_file_path(state_dir)
            turn_file = turns_dir(state_dir) / "turn.json"
            log_file.parent.mkdir(parents=True)
            turn_file.parent.mkdir(parents=True)
            log_file.write_text("old-event\n", encoding="utf-8")
            turn_file.write_text("{}\n", encoding="utf-8")

            with mock.patch("sys.stdout", io.StringIO()):
                result = reset_schema_main(
                    [
                        "--state-dir",
                        str(state_dir),
                        "--repo-root",
                        str(root),
                        "--reset-runtime-state",
                    ]
                )

            archives = tuple((state_dir / "archives" / "pre-schema-v2").glob("events-*.jsonl"))
            metadata = json.loads((state_dir / "skill-metadata-cache.json").read_text(encoding="utf-8"))
            new_log = log_file.read_text(encoding="utf-8")
            turn_exists = turn_file.exists()
            archive_contents = tuple(path.read_text(encoding="utf-8") for path in archives)
            source_root = str(root.resolve())

        self.assertEqual(result, 0)
        self.assertEqual(new_log, "")
        self.assertFalse(turn_exists)
        self.assertEqual(len(archives), 1)
        self.assertEqual(archive_contents, ("old-event\n",))
        self.assertEqual(tuple(metadata["skills"]), ("demo:entry",))
        self.assertEqual(metadata["source_root"], source_root)

    def test_hook_config_runtime_helpers_and_stale_schema_detection(self) -> None:
        with mock.patch.dict("os.environ", {"OH_MY_HARNESS_PYTHON": "/tmp/shared-python"}, clear=True):
            self.assertEqual(default_python(), Path("/tmp/shared-python"))
        with mock.patch.dict(
            "os.environ",
            {
                "OH_MY_HARNESS_PYTHON": "/tmp/shared-python",
                "OH_MY_HARNESS_TOOLING_PYTHON": "/tmp/tooling-python",
            },
            clear=True,
        ):
            self.assertEqual(default_python(), Path("/tmp/tooling-python"))

        python = Path(r"C:\Users\Fixture Smith\.oh-my-harness\venv\Scripts\python.exe")
        adapter = Path(r"C:\Users\Fixture Smith\Projects\oh-my-harness\plugins\watcher\scripts\watcher")
        with mock.patch("watcher_runtime.skill.codex_hook_config.os.name", "nt"):
            self.assertEqual(
                skill_watcher_command(python, adapter, repo_root=REPO_ROOT),
                r'"C:\Users\Fixture Smith\.oh-my-harness\venv\Scripts\python.exe" -B '
                r'"C:\Users\Fixture Smith\Projects\oh-my-harness\plugins\watcher\scripts\watcher" skill observe '
                f'--repo-root {REPO_ROOT}',
            )

        self.assertEqual(marketplace_source_arg("https://github.com/example/oh-my-harness"), "https://github.com/example/oh-my-harness")
        self.assertEqual(marketplace_source_arg("example/oh-my-harness"), "example/oh-my-harness")

        existing = {
            "hooks": {
                "PostToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/bin/true"}]}
                ]
            }
        }
        installed, _ = install_skill_watcher_hooks(
            existing,
            python_path=Path("/tmp/python"),
            adapter=Path("/tmp/watcher/scripts/watcher"),
            repo_root=REPO_ROOT,
        )
        installed_again, removed = install_skill_watcher_hooks(
            installed,
            python_path=Path("/tmp/python"),
            adapter=Path("/tmp/watcher/scripts/watcher"),
            repo_root=REPO_ROOT,
        )
        uninstalled, removed_on_uninstall = remove_skill_watcher_hooks(installed)

        self.assertEqual(installed, installed_again)
        self.assertEqual(removed, 4)
        self.assertEqual(removed_on_uninstall, 4)
        self.assertEqual(installed["hooks"]["PostToolUse"][0]["hooks"][0]["command"], "/usr/bin/true")
        self.assertIn("SessionStart", installed["hooks"])
        self.assertEqual(uninstalled["hooks"], {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/usr/bin/true"}]}]})
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
            handlers = [handler for group in installed["hooks"][event] for handler in group["hooks"]]
            managed = [handler for handler in handlers if "skill observe" in handler["command"]]
            self.assertTrue(managed)
            for handler in managed:
                self.assertIs(handler["async"], False)
                self.assertEqual(handler["timeoutSec"], 10)
                self.assertNotIn("timeout", handler)

        old_handler = {
            "type": "command",
            "command": "/tmp/python /tmp/watcher/scripts/skill/codex_hook_adapter.py",
            "timeout": 10,
            "statusMessage": "Skill Watcher: observe UserPromptSubmit",
        }
        matched_events, issues = find_managed_hook_issues(
            {
                "hooks": {
                    "UserPromptSubmit": [{"hooks": [old_handler]}],
                    "SessionStart": [{"hooks": [{**old_handler, "statusMessage": "Skill Watcher: observe SessionStart"}]}],
                }
            },
            python_path=Path("/tmp/python"),
            adapter=Path("/tmp/watcher/scripts/watcher"),
            repo_root=REPO_ROOT,
        )

        self.assertEqual(matched_events, {"SessionStart", "UserPromptSubmit"})
        self.assertTrue(any("timeoutSec" in issue for issue in issues))
        self.assertTrue(any("unexpected keys: timeout" in issue for issue in issues))
        self.assertTrue(any("SessionStart" in issue for issue in issues))

    def test_runtime_paths_centralize_state_layout_and_env_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            custom_log = Path(tmp) / "custom-events.jsonl"

            runtime_ensure_runtime_dirs(state_dir)

            self.assertEqual(log_file_path(state_dir), state_dir / "logs" / "events.jsonl")
            self.assertEqual(log_file_path(state_dir, str(custom_log)), custom_log)
            self.assertEqual(runtime_report_state_path(state_dir), state_dir / "report-state.json")
            self.assertEqual(reports_dir(state_dir), state_dir / "reports")
            self.assertEqual(hook_backup_dir(state_dir), state_dir / "backups" / "hooks-json")
            self.assertEqual(turns_dir(state_dir), state_dir / "turns")
            for dirname in ("logs", "reports", "proposals", "snapshots", "rejected", "backups", "turns"):
                self.assertTrue((state_dir / dirname).is_dir())

            with mock.patch.dict("os.environ", {"WATCHER_SKILL_STATE_DIR": str(state_dir)}, clear=False):
                self.assertEqual(runtime_state_dir_from_env_or_arg(None), state_dir)
            self.assertEqual(runtime_state_dir_from_env_or_arg(str(state_dir / "explicit")), state_dir / "explicit")
            self.assertEqual(runtime_safe_slug("skill watcher:demo", fallback="x"), "skill-watcher-demo")
            self.assertEqual(runtime_safe_slug("!!!", fallback="x"), "x")

    def test_proposal_filters_identity_and_validates_only_materialized_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "doc-alignment"
            skill_dir.mkdir()
            source = skill_dir / "SKILL.md"
            contents = "---\nname: doc-alignment\ndescription: Audit current docs.\n---\n\n# Audit\nRead current docs.\n"
            source.write_text(contents, encoding="utf-8")
            state = root / "state"
            args = ["--skill-dir", str(skill_dir), "--state-dir", str(state)]
            for identity_args in ([], ["--skill", ""], ["--skill", "   "]):
                with self.subTest(identity_args=identity_args):
                    with mock.patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit) as error:
                        propose_main(args + identity_args)
                    self.assertEqual(error.exception.code, 2)
                    self.assertFalse(state.exists())
            log = root / "events.jsonl"
            events = [
                {
                    "timestamp": timestamp,
                    "event_type": "turn_summary",
                    "skill_attribution": {
                        "primary": {"name": identity, "role": "entrypoint"},
                        "supporting": [], "effective": [identity], "mentioned": [],
                    },
                    "user_feedback": feedback,
                }
                for identity, timestamp, feedback in (
                    ("watcher:doc-alignment", "2026-06-01T00:00:00Z", "outside-window"),
                    ("watcher:doc-alignment", "2026-06-06T00:00:00Z", "selected-evidence"),
                    ("other:doc-alignment", "2026-06-06T00:00:00Z", "wrong-identity"),
                )
            ]
            log.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
            with mock.patch("sys.stdout", new=io.StringIO()):
                result = propose_main(args + ["--skill", "watcher:doc-alignment", "--since", "2026-06-05T00:00:00Z", "--log-file", str(log)])
            self.assertEqual(result, 0)
            proposal_path, = (state / "proposals").glob("*-proposal.md")
            proposal = proposal_path.read_text(encoding="utf-8")
            self.assertIn("selected-evidence", proposal)
            self.assertNotIn("wrong-identity", proposal)
            self.assertNotIn("outside-window", proposal)
            command = next(line for line in proposal.splitlines() if line.startswith('"$omh_tooling_python" -B scripts/watcher skill validate'))
            argv = shlex.split(command)
            candidate = Path(argv[argv.index("--candidate-skill") + 1])
            self.assertNotEqual(candidate, source)
            self.assertFalse(candidate.exists())
            with self.assertRaises(SystemExit):
                validate_skill(candidate)
            candidate.parent.mkdir()
            candidate.write_text("invalid candidate", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_skill(candidate)
            candidate.write_text(contents.replace("Read current docs.", "Compare current docs with source evidence."), encoding="utf-8")
            validate_skill(candidate)
            self.assertEqual(source.read_text(encoding="utf-8"), contents)
            snapshot, = (state / "snapshots").glob("*-SKILL.md")
            self.assertEqual(snapshot.read_text(encoding="utf-8"), contents)

    def test_proposal_frontmatter_and_status_transitions(self) -> None:
        skill_dir = Path("/tmp/Skill Dir")
        candidate_path = Path("/tmp/Proposals Dir/proposal-1-candidate/SKILL.md")
        proposal = build_proposal(
            proposal_id="proposal-1",
            skill_name="demo",
            skill_dir=skill_dir,
            skill_contents="line\n",
            report="# Report\n",
            snapshot_path=Path("/tmp/snapshots/source-SKILL.md"),
            candidate_path=candidate_path,
            timestamp="20260528T000000Z",
        )

        self.assertTrue(proposal.startswith("---\n"))
        self.assertIn('status: "draft"', proposal)
        self.assertIn('skill_name: "demo"', proposal)
        self.assertIn("generated draft is a worksheet, not yet a reviewable proposal", proposal)
        self.assertIn("- Decision: Undecided", proposal)
        self.assertIn("- Exact edit:", proposal)
        self.assertIn("Do not modify the source skill", proposal)
        self.assertIn('/venv/bin/python"', proposal)
        self.assertIn(r"venv\Scripts\python.exe", proposal)
        self.assertIn("Windows PowerShell:", proposal)
        self.assertGreaterEqual(proposal.count(" -B scripts/watcher skill validate "), 2)
        unix_command = next(
            line
            for line in proposal.splitlines()
            if line.startswith('"$omh_tooling_python" -B scripts/watcher skill validate')
        )
        unix_argv = shlex.split(unix_command)
        candidate_index = unix_argv.index("--candidate-skill")
        self.assertEqual(unix_argv[candidate_index + 1], str(candidate_path))
        self.assertNotEqual(candidate_path, skill_dir / "SKILL.md")
        self.assertIn("Validation has not run", proposal)

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            proposal_path = Path(tmp) / "proposal.md"
            proposal_path.write_text(
                "---\n"
                "proposal_id: proposal-1\n"
                "status: draft\n"
                "skill_name: demo\n"
                "---\n"
                "# Proposal\n",
                encoding="utf-8",
            )

            previous, _ = update_status(
                proposal_path,
                "needs-validation",
                state_dir=state_dir,
                reason="needs checks",
            )
            previous_rejected, rejected_path = update_status(
                proposal_path,
                "rejected",
                state_dir=state_dir,
                reason="bad evidence",
            )
            updated = proposal_path.read_text(encoding="utf-8")
            rejected_text = rejected_path.read_text(encoding="utf-8") if rejected_path is not None else ""
            rejected_exists = rejected_path.is_file() if rejected_path is not None else False

        self.assertEqual(previous, "draft")
        self.assertEqual(previous_rejected, "needs-validation")
        self.assertIsNotNone(rejected_path)
        self.assertTrue(rejected_exists)
        self.assertIn("status: rejected", updated)
        self.assertIn("bad evidence", rejected_text)

    def test_candidate_validator_distinguishes_documented_marker_from_placeholder(self) -> None:
        maintainer = ROOT / "skills" / "skill-maintainer" / "SKILL.md"
        validate_skill(maintainer)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documented = root / "documented.md"
            documented.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n"
                "Explain that `[TODO:` starts an unfinished placeholder.\n",
                encoding="utf-8",
            )
            unresolved = root / "unresolved.md"
            unresolved.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\n"
                "[TODO: replace this guidance]\n",
                encoding="utf-8",
            )

            validate_skill(documented)
            with self.assertRaises(SystemExit) as raised:
                validate_skill(unresolved)

        self.assertIn("contains a `[TODO: ...]` placeholder", str(raised.exception))

    def test_candidate_validator_marks_static_only_result_for_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "SKILL.md"
            candidate.write_text(
                "---\nname: demo\ndescription: Demo skill.\n---\nBody.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with mock.patch("sys.stdout", stdout):
                result = validate_candidate_main(["--candidate-skill", str(candidate)])

        self.assertEqual(result, 0)
        self.assertIn("candidate static checks passed", stdout.getvalue())
        self.assertIn("human review is required", stdout.getvalue())

    def test_report_reader_and_state_support_incremental_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            log_file = state_dir / "logs" / "events.jsonl"
            log_file.parent.mkdir(parents=True)
            events = [
                {"timestamp": "2026-06-01T00:00:00Z", "skill_name": "demo", "outcome": "success"},
                {"timestamp": "2026-06-05T00:00:00Z", "skill_name": "demo", "outcome": "failure"},
                {"timestamp": "2026-06-06T00:00:00Z", "skill_name": "demo", "outcome": "success"},
            ]
            log_file.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            recent = read_events_since(log_file, parse_since("2026-06-05T00:00:00Z"), block_size=48)
            state = load_report_state(state_dir)
            key = report_state_key("demo")
            update_report_state(
                state,
                key=key,
                since=parse_since("2026-06-05T00:00:00Z"),
                until=datetime(2026, 6, 6, tzinfo=timezone.utc),
                event_count=len(recent),
                output=state_dir / "reports" / "demo.md",
                recent_hashes=[event_hash(event) for event in recent],
            )
            save_report_state(state_dir, state)
            loaded = load_report_state(state_dir)

        self.assertEqual([event["timestamp"] for event in recent], ["2026-06-05T00:00:00Z", "2026-06-06T00:00:00Z"])
        self.assertEqual(state_since(loaded, key), datetime(2026, 6, 6, tzinfo=timezone.utc))
        self.assertEqual(loaded["reports"][key]["last_event_count"], 2)
        self.assertEqual(len(loaded["reports"][key]["recent_event_hashes"]), 2)

    def test_report_uses_catalog_and_overlay_cache_without_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            state_dir = Path(tmp) / "state"
            initialize_catalog_repo(root, {"demo": ("entry",)})
            write_attribution_overlay(
                root,
                "demo",
                {
                    "schema_version": 1,
                    "skills": {
                        "demo:entry": {
                            "role": "entrypoint",
                            "logical_group": "explicit-workflows",
                        }
                    },
                    "legacy_names": {"legacy:entry": "demo:entry"},
                },
            )
            marketplace = root / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text("{not-json\n", encoding="utf-8")
            base = {"session_id": "catalog-report", "turn_id": "turn-1"}
            write_hook_event(
                {**base, "hook_event_name": "SessionStart"},
                state_dir=state_dir,
                repo_root=root,
            )
            write_hook_event(
                {
                    **base,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Use entry for this task",
                },
                state_dir=state_dir,
                repo_root=root,
            )
            write_hook_event(
                {**base, "hook_event_name": "Stop"},
                state_dir=state_dir,
                repo_root=root,
            )

            result = run_report_pipeline(
                ReportQuery(
                    state_dir=state_dir,
                    log_file=log_file_path(state_dir),
                ),
                ReportOutputPolicy(write_output=False),
            )

        self.assertIn("`demo:entry`", result.report)
        self.assertIn("explicit-workflows", result.report)
        self.assertEqual(result.event_count, 2)

    def test_report_pipeline_writes_report_state_and_counts_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            log_file = log_file_path(state_dir)
            log_file.parent.mkdir(parents=True)
            events = [
                {
                    "timestamp": "2026-06-05T00:00:00Z",
                    "event_type": "turn_summary",
                    "session_id": "s1",
                    "outcome": "unknown",
                    "task_outcome": "failure",
                    "skill_attribution": {
                        "primary": {"name": "demo", "role": "entrypoint"},
                        "supporting": [{"name": "support", "role": "discipline"}],
                        "effective": ["demo", "support"],
                        "mentioned": [],
                    },
                    "codex": {
                        "turn_id": "t1",
                        "turn_summary": {"task_outcome": "failure", "tool_failure_count": 2},
                    },
                },
                {
                    "timestamp": "2026-06-06T00:00:00Z",
                    "event_type": "turn_summary",
                    "session_id": "s2",
                    "outcome": "unknown",
                    "task_outcome": "success",
                    "skill_attribution": {
                        "primary": {"name": "demo", "role": "entrypoint"},
                        "supporting": [],
                        "effective": ["demo"],
                        "mentioned": [],
                    },
                    "codex": {
                        "turn_id": "t2",
                        "turn_summary": {"task_outcome": "success", "tool_failure_count": 0},
                    },
                },
            ]
            log_file.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
            (state_dir / "skill-metadata-cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "skills": {
                            "demo": {"logical_group": "explicit-workflows"},
                            "support": {"logical_group": "implicit-primitives"},
                        },
                        "legacy_names": {},
                    }
                ),
                encoding="utf-8",
            )

            result = run_report_pipeline(
                ReportQuery(
                    state_dir=state_dir,
                    log_file=log_file,
                    skill="demo",
                    since_raw="2026-06-05T00:00:00Z",
                    incremental=True,
                ),
                ReportOutputPolicy(write_output=True),
            )
            loaded = load_report_state(state_dir)
            output_exists = result.output.is_file() if result.output is not None else False

        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.outcome_counts["failure"], 1)
        self.assertEqual(result.outcome_counts["success"], 1)
        self.assertIn("supporting-only", result.report)
        self.assertIn("`support`", result.report)
        self.assertIn("## Usage By Logical Group", result.report)
        self.assertIn("| explicit-workflows | 2 | 2 | 0 | `demo` |", result.report)
        self.assertIn("| implicit-primitives | 1 | 0 | 1 | `support` |", result.report)
        self.assertIn("| `demo` | entrypoint | explicit-workflows |", result.report)
        self.assertIsNotNone(result.output)
        self.assertTrue(output_exists)
        self.assertEqual(result.state_path, state_dir / "report-state.json")
        self.assertEqual(loaded["reports"]["demo"]["last_event_count"], 2)


if __name__ == "__main__":
    unittest.main()
