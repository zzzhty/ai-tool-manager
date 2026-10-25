from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import refresh_harness as refresh  # noqa: E402


class RefreshHarnessCliTests(unittest.TestCase):
    def run_main(self, arguments: list[str]) -> None:
        with mock.patch.object(sys, "argv", ["refresh_harness.py", *arguments]):
            refresh.main()

    def test_retired_prune_option_is_rejected_before_any_refresh_work(self) -> None:
        with mock.patch.object(refresh, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(["--prune-plugins", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)
        load_catalog.assert_not_called()

    def test_windows_auto_discovery_skips_an_unstartable_path_cli(self) -> None:
        path_cli = r"C:\Program Files\WindowsApps\OpenAI.Codex\codex.exe"
        managed_cli = r"C:\Users\tester\AppData\Local\OpenAI\Codex\bin\build\codex.exe"
        with (
            mock.patch.object(refresh.sys, "platform", "win32"),
            mock.patch.object(refresh.shutil, "which", return_value=path_cli),
            mock.patch.object(
                refresh,
                "codex_fallback_candidates",
                return_value=[managed_cli],
            ),
            mock.patch.object(
                refresh,
                "resolve_first_executable",
                side_effect=lambda candidates: candidates[0],
            ),
            mock.patch.object(
                refresh,
                "codex_executable_is_startable",
                side_effect=lambda candidate: candidate == managed_cli,
            ) as startable,
        ):
            resolved = refresh.resolve_codex_executable(
                None,
                codex_home=Path(r"C:\Users\tester\.codex"),
            )

        self.assertEqual(resolved, managed_cli)
        self.assertEqual(
            [call.args[0] for call in startable.call_args_list],
            [path_cli, managed_cli],
        )

    def test_codex_startability_probe_rejects_a_timeout(self) -> None:
        with mock.patch.object(
            refresh.subprocess,
            "run",
            side_effect=refresh.subprocess.TimeoutExpired("codex --version", 5),
        ):
            self.assertFalse(refresh.codex_executable_is_startable("codex"))

    def test_build_env_uses_repository_contract_even_with_system_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            scripts = codex_home / "skills" / ".system" / "plugin-creator" / "scripts"
            scripts.mkdir(parents=True)
            validator = scripts / "validate_plugin.py"
            validator.write_text("# validator fixture\n", encoding="utf-8")
            (scripts / "identifier_validation.py").write_text(
                "# identifier fixture\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                env = refresh.build_env(
                    codex_home=codex_home,
                    tooling_python=Path("/tooling/python"),
                )

        self.assertEqual(env["PLUGIN_VALIDATOR"], str(refresh.REPOSITORY_PLUGIN_VALIDATOR))

    def test_build_env_preserves_explicit_plugin_validator(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {"PLUGIN_VALIDATOR": "/custom/validate_plugin.py"},
                clear=True,
            ),
            mock.patch.object(
                refresh,
                "Path",
                side_effect=AssertionError(
                    "explicit PLUGIN_VALIDATOR must remain an opaque string"
                ),
            ),
        ):
            env = refresh.build_env(
                codex_home=Path("/codex-home"),
                tooling_python=Path("/tooling/python"),
            )

        self.assertEqual(env["PLUGIN_VALIDATOR"], "/custom/validate_plugin.py")

    def test_nonempty_codex_prune_plan_requires_confirmation_by_default(self) -> None:
        plan = refresh.CodexPrunePlan(
            configured=frozenset({"retired"}),
            cached=frozenset({"retired"}),
        )
        with mock.patch("builtins.input", return_value="no") as prompt:
            with self.assertRaisesRegex(SystemExit, "was not confirmed"):
                refresh.confirm_codex_prune(
                    plan,
                    marketplace_name="oh-my-harness",
                    confirmation="when-nonempty",
                    dry_run=False,
                    assume_yes=False,
                )
        prompt.assert_called_once()

    def test_yes_confirms_only_the_precomputed_codex_prune_plan(self) -> None:
        plan = refresh.CodexPrunePlan(
            configured=frozenset({"configured-only"}),
            cached=frozenset({"cache-only"}),
        )
        with mock.patch("builtins.input") as prompt:
            refresh.confirm_codex_prune(
                plan,
                marketplace_name="oh-my-harness",
                confirmation="when-nonempty",
                dry_run=False,
                assume_yes=True,
            )
        prompt.assert_not_called()

    def test_retired_marketplace_hint_uses_the_platform_wrapper_option(self) -> None:
        state = refresh.RetiredMarketplaceState(
            name="my-codex",
            configured_plugins=frozenset({"watcher"}),
            cached_plugins=frozenset({"watcher"}),
            source_config=(("source", "/repo"), ("source_type", "local")),
        )
        cases = (
            ("nt", "-MigrateMarketplace", "--migrate-marketplace"),
            ("posix", "--migrate-marketplace", "-MigrateMarketplace"),
        )
        for platform_name, expected_option, other_option in cases:
            with self.subTest(platform=platform_name):
                with (
                    mock.patch.object(refresh.os, "name", platform_name),
                    self.assertRaises(SystemExit) as raised,
                ):
                    refresh.confirm_retired_marketplace_migration(
                        (state,),
                        requested=False,
                        dry_run=False,
                        assume_yes=True,
                    )

                message = str(raised.exception)
                self.assertIn("action required:", message)
                self.assertIn(expected_option, message)
                self.assertNotIn(other_option, message)

    def test_cli_reports_action_required_without_a_traceback_in_redirected_output(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(
                refresh,
                "main",
                side_effect=SystemExit(
                    "action required: rerun with -MigrateMarketplace"
                ),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = refresh.cli()

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.getvalue(),
            "action required: rerun with -MigrateMarketplace\n",
        )
        self.assertNotIn("\x1b", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_retired_marketplace_migration_inventory_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp)
            codex_home.joinpath("config.toml").write_text(
                '[plugins."watcher@my-codex"]\n'
                "enabled = true\n\n"
                "[marketplaces.my-codex]\n"
                'source_type = "local"\n'
                'source = "/repo"\n',
                encoding="utf-8",
            )
            cache = codex_home / "plugins" / "cache" / "my-codex" / "watcher"
            cache.mkdir(parents=True)

            states = refresh.retired_marketplace_states(codex_home, ("my-codex",))

        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].configured_plugins, frozenset({"watcher"}))
        self.assertEqual(states[0].cached_plugins, frozenset({"watcher"}))
        self.assertEqual(dict(states[0].source_config)["source"], "/repo")

    def test_dry_run_marketplace_migration_uses_only_the_preflight_snapshot(self) -> None:
        state = refresh.RetiredMarketplaceState(
            name="my-codex",
            configured_plugins=frozenset({"watcher"}),
            cached_plugins=frozenset({"watcher"}),
            source_config=(("source", "/repo"), ("source_type", "local")),
        )
        with (
            mock.patch.object(
                refresh,
                "retired_marketplace_states",
                return_value=(state,),
            ),
            mock.patch.object(refresh, "run") as run,
            mock.patch.object(refresh, "remove_marketplace_source") as remove_marketplace,
        ):
            refresh.apply_retired_marketplace_migration(
                "codex",
                codex_home=Path("/codex"),
                states=(state,),
                env={},
                dry_run=True,
            )

        run.assert_called_once_with(
            ["codex", "plugin", "remove", "watcher@my-codex"],
            env={},
            dry_run=True,
        )
        remove_marketplace.assert_called_once_with(
            "codex",
            codex_home=Path("/codex"),
            marketplace_name="my-codex",
            env={},
            dry_run=True,
        )

    def test_missing_exact_relocated_marketplace_source_is_detached_before_discovery(self) -> None:
        state = refresh.RetiredMarketplaceState(
            name="my-codex",
            configured_plugins=frozenset({"watcher"}),
            cached_plugins=frozenset({"watcher"}),
            source_config=(("source", "/former/repo"), ("source_type", "local")),
        )
        detached = refresh.RetiredMarketplaceState(
            name="my-codex",
            configured_plugins=state.configured_plugins,
            cached_plugins=state.cached_plugins,
            source_config=(),
        )
        with (
            mock.patch.object(refresh, "remove_marketplace_source") as remove,
            mock.patch.object(
                refresh,
                "retired_marketplace_states",
                return_value=(detached,),
            ),
        ):
            current = refresh.detach_relocated_retired_marketplace_sources(
                "codex",
                codex_home=Path("/codex"),
                states=(state,),
                retired_repo=Path("/former/repo"),
                env={},
                dry_run=False,
            )

        self.assertEqual(current, (detached,))
        remove.assert_called_once_with(
            "codex",
            codex_home=Path("/codex"),
            marketplace_name="my-codex",
            env={},
            dry_run=False,
        )

    def test_relocated_source_detach_dry_run_stops_before_false_discovery(self) -> None:
        state = refresh.RetiredMarketplaceState(
            name="my-codex",
            configured_plugins=frozenset({"watcher"}),
            cached_plugins=frozenset({"watcher"}),
            source_config=(("source", "/former/repo"), ("source_type", "local")),
        )
        with self.assertRaisesRegex(SystemExit, "dry-run cannot simulate"):
            refresh.detach_relocated_retired_marketplace_sources(
                "codex",
                codex_home=Path("/codex"),
                states=(state,),
                retired_repo=Path("/former/repo"),
                env={},
                dry_run=True,
            )

    def test_legacy_discovery_profile_option_is_rejected(self) -> None:
        with mock.patch.object(refresh, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(["--discovery-profile", "universal", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)
        load_catalog.assert_not_called()

    def test_git_marketplace_install_is_pinned_to_validated_checkout_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git"),
                mock.patch.object(
                    refresh,
                    "git_remote_ref_status",
                    return_value=(True, "checkout matches ref"),
                ),
                mock.patch.object(refresh, "git_head_revision", return_value="abc123"),
                mock.patch.object(
                    refresh,
                    "ensure_git_marketplace_source",
                    return_value=0,
                ) as ensure_git,
            ):
                binding = refresh.ensure_marketplace_source(
                    "codex",
                    codex_home=Path(tmp) / "codex",
                    marketplace_name="oh-my-harness",
                    git_source="git@example/repo.git",
                    git_ref="main",
                    git_request_explicit=True,
                    local_source=str(REPO_ROOT),
                    env={},
                    dry_run=True,
                )

        self.assertEqual(
            binding,
            refresh.MarketplaceSourceBinding(
                "git",
                "git@example/repo.git",
                "abc123",
            ),
        )
        self.assertEqual(ensure_git.call_args.kwargs["ref"], "abc123")

    def test_explicit_git_ref_mismatch_never_falls_back_to_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git"),
                mock.patch.object(
                    refresh,
                    "git_remote_ref_status",
                    return_value=(False, "requested ref does not match HEAD"),
                ),
                mock.patch.object(refresh, "ensure_local_marketplace_source") as ensure_local,
            ):
                with self.assertRaisesRegex(
                    SystemExit,
                    "explicit Git marketplace ref is not the validated checkout",
                ):
                    refresh.ensure_marketplace_source(
                        "codex",
                        codex_home=Path(tmp) / "codex",
                        marketplace_name="oh-my-harness",
                        git_source="git@example/repo.git",
                        git_ref="release",
                        git_request_explicit=True,
                        local_source=str(REPO_ROOT),
                        env={},
                        dry_run=True,
                    )

        ensure_local.assert_not_called()

    def test_explicit_git_install_failure_never_falls_back_to_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git"),
                mock.patch.object(
                    refresh,
                    "git_remote_ref_status",
                    return_value=(True, "checkout matches ref"),
                ),
                mock.patch.object(refresh, "git_head_revision", return_value="abc123"),
                mock.patch.object(refresh, "ensure_git_marketplace_source", return_value=17),
                mock.patch.object(refresh, "ensure_local_marketplace_source") as ensure_local,
            ):
                with self.assertRaisesRegex(SystemExit, "failed with exit code 17"):
                    refresh.ensure_marketplace_source(
                        "codex",
                        codex_home=Path(tmp) / "codex",
                        marketplace_name="oh-my-harness",
                        git_source="git@example/repo.git",
                        git_ref="main",
                        git_request_explicit=True,
                        local_source=str(REPO_ROOT),
                        env={},
                        dry_run=True,
                    )

        ensure_local.assert_not_called()

    def test_automatic_source_reuses_checkout_without_git_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git"),
                mock.patch.object(
                    refresh,
                    "git_remote_ref_status",
                    return_value=(True, "checkout matches ref"),
                ),
                mock.patch.object(refresh, "git_head_revision", return_value="abc123"),
                mock.patch.object(refresh, "ensure_git_marketplace_source", return_value=17) as ensure_git,
                mock.patch.object(refresh, "ensure_local_marketplace_source") as ensure_local,
            ):
                binding = refresh.ensure_marketplace_source(
                    "codex",
                    codex_home=Path(tmp) / "codex",
                    marketplace_name="oh-my-harness",
                    git_source="git@example/repo.git",
                    git_ref="main",
                    git_request_explicit=False,
                    local_source=str(REPO_ROOT),
                    env={},
                    dry_run=True,
                )

        self.assertEqual(binding, refresh.MarketplaceSourceBinding("local", str(REPO_ROOT)))
        ensure_local.assert_called_once()
        ensure_git.assert_not_called()

    def test_cli_tracks_a_git_ref_as_an_explicit_codex_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = [
                "--git-ref",
                "release",
                "--codex-home",
                str(root / "codex"),
                "--dry-run",
                "--skip-bootstrap",
                "--skip-agents",
                "--skip-hooks",
                "--skip-doctor",
            ]
            with (
                mock.patch.object(refresh, "require_excluded_skill_roots_clear"),
                mock.patch.object(refresh, "prepare_instruction_sync"),
                mock.patch.object(refresh, "preflight_codex_distribution"),
                mock.patch.object(refresh, "resolve_codex_executable", return_value="/fake/codex"),
                mock.patch.object(refresh, "require_codex_plugin_commands"),
                mock.patch.object(refresh, "_enabled_codex_harness_plugins", return_value=set()),
                mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git"),
                mock.patch.object(
                    refresh,
                    "ensure_marketplace_source",
                    side_effect=SystemExit("stop after argument capture"),
                ) as ensure_marketplace,
            ):
                with self.assertRaisesRegex(SystemExit, "stop after argument capture"):
                    self.run_main(arguments)

        self.assertEqual(ensure_marketplace.call_args.kwargs["git_ref"], "release")
        self.assertTrue(ensure_marketplace.call_args.kwargs["git_request_explicit"])

    def test_invalid_marketplace_policy_fails_codex_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            skill = repo / "plugins" / "demo" / "skills" / "one"
            skill.mkdir(parents=True)
            skill.joinpath("SKILL.md").write_text(
                "---\nname: one\ndescription: fixture\n---\n",
                encoding="utf-8",
            )
            manifest = repo / "plugins" / "demo" / ".codex-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"name": "demo", "version": "1.0.0", "skills": "./skills/"}),
                encoding="utf-8",
            )
            metadata = repo / ".agents" / "plugins"
            metadata.mkdir(parents=True)
            metadata.joinpath("marketplace.json").write_text(
                json.dumps(
                    {
                        "name": "test",
                        "plugins": [
                            {
                                "name": "demo",
                                "source": {"source": "local", "path": "./plugins/demo"},
                                "policy": {"installation": "INSTALLED_BY_DEFAULT"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            metadata.joinpath("install-manifest.json").write_text(
                json.dumps(
                    {
                        "harness": "codex",
                        "marketplace": "test",
                        "plugins": [{"name": "demo", "install": True, "check": True}],
                    }
                ),
                encoding="utf-8",
            )
            catalog = refresh.load_repo_skill_catalog(repo)
            with self.assertRaisesRegex(SystemExit, "installation policy must be 'AVAILABLE'"):
                refresh.preflight_codex_distribution(
                    catalog,
                    codex_home=root / "codex",
                    marketplace_name="test",
                    marketplace_file=metadata / "marketplace.json",
                    manifest_file=metadata / "install-manifest.json",
                )

    def test_retired_skill_mode_option_is_rejected(self) -> None:
        with mock.patch.object(refresh, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(["--skill-mode", "mixed", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)
        load_catalog.assert_not_called()

    def test_unknown_harness_fails_before_catalog_load(self) -> None:
        with mock.patch.object(refresh, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaisesRegex(SystemExit, "unknown harness"):
                self.run_main(["--harness", "unknown", "--dry-run"])
        load_catalog.assert_not_called()

    def test_default_harness_is_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arguments = [
                "--codex-home",
                str(root / "codex"),
                "--dry-run",
                "--skip-bootstrap",
                "--skip-agents",
                "--skip-hooks",
                "--skip-doctor",
            ]
            with (
                mock.patch.object(refresh, "require_excluded_skill_roots_clear"),
                mock.patch.object(refresh, "prepare_instruction_sync"),
                mock.patch.object(refresh, "preflight_codex_distribution"),
                mock.patch.object(
                    refresh,
                    "resolve_codex_executable",
                    side_effect=SystemExit("resolved default Codex harness"),
                ) as resolve,
            ):
                with self.assertRaisesRegex(SystemExit, "resolved default Codex harness"):
                    self.run_main(arguments)
        resolve.assert_called_once()

    def test_default_tooling_venv_follows_the_manager_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "custom-codex"
            manager_home = Path(tmp) / "custom-manager"
            with mock.patch.object(
                refresh,
                "tooling_python_from_args",
                side_effect=SystemExit("captured venv"),
            ) as tooling:
                with self.assertRaisesRegex(SystemExit, "captured venv"):
                    self.run_main(
                        [
                            "--home",
                            str(manager_home),
                            "--codex-home",
                            str(codex_home),
                            "--dry-run",
                        ]
                    )

        self.assertEqual(tooling.call_args.args[1], manager_home / "venv")

    def test_removed_shared_harness_fails_before_catalog_load(self) -> None:
        with mock.patch.object(refresh, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaisesRegex(SystemExit, "unknown harness 'shared'"):
                self.run_main(["--harness", "shared", "--dry-run"])
        load_catalog.assert_not_called()

    def test_native_harness_does_not_read_codex_marketplace_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.dict(
                    refresh.os.environ,
                    {"PI_CODING_AGENT_DIR": str(Path(tmp) / "pi-agent")},
                ),
                mock.patch.object(refresh, "require_excluded_skill_roots_clear"),
                mock.patch.object(
                    refresh,
                    "load_install_manifest",
                    side_effect=AssertionError("Codex manifest must not be read"),
                ),
                mock.patch.object(refresh, "prepare_instruction_sync"),
                mock.patch.object(refresh, "sync_layer") as sync,
                mock.patch.object(refresh, "apply_instruction_sync"),
            ):
                self.run_main(
                    [
                        "--harness",
                        "pi-agent",
                        "--codex-home",
                        str(Path(tmp) / "codex"),
                        "--dry-run",
                        "--skip-bootstrap",
                    ]
                )
        sync.assert_called_once()

    def test_repo_relocation_migration_is_codex_only(self) -> None:
        with self.assertRaisesRegex(
            SystemExit,
            "Codex marketplace options require --harness codex: --migrate-from-repo",
        ):
            self.run_main(
                [
                    "--harness",
                    "zcode",
                    "--migrate-from-repo",
                    "/former/repo",
                    "--dry-run",
                ]
            )

    def test_codex_repo_relocation_passes_only_declared_former_instruction_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            former_repo = root / "former-repo"
            with (
                mock.patch.object(refresh, "require_excluded_skill_roots_clear"),
                mock.patch.object(
                    refresh,
                    "prepare_instruction_sync",
                    side_effect=SystemExit("captured instruction migration"),
                ) as prepare,
            ):
                with self.assertRaisesRegex(SystemExit, "captured instruction migration"):
                    self.run_main(
                        [
                            "--codex-home",
                            str(root / "codex"),
                            "--migrate-from-repo",
                            str(former_repo),
                            "--dry-run",
                        ]
                    )

        self.assertEqual(
            prepare.call_args.kwargs["explicit_former_sources"],
            (
                former_repo / "agents/global-instructions.md",
                former_repo / "AGENTS.md",
            ),
        )

    def test_operation_instruction_digests_require_matching_active_journal(self) -> None:
        home = Path("/manager")
        operation = {
            "operationId": "op-1",
            "command": "update",
            "before": {
                "revision": "a" * 40,
                "instructionsSource": {"sha256": "1" * 64},
            },
            "target": {
                "revision": "b" * 40,
                "instructionsSource": {"sha256": "2" * 64},
            },
        }
        with (
            mock.patch.object(refresh, "load_current_operation", return_value=operation),
            mock.patch.object(refresh, "git_head_revision", return_value="b" * 40),
        ):
            self.assertEqual(
                refresh.operation_instruction_digests(home, "op-1"),
                ("1" * 64, "2" * 64),
            )
            with self.assertRaisesRegex(SystemExit, "does not match refresh"):
                refresh.operation_instruction_digests(home, "other")

        with (
            mock.patch.object(refresh, "load_current_operation", return_value=operation),
            mock.patch.object(refresh, "git_head_revision", return_value="c" * 40),
            self.assertRaisesRegex(SystemExit, "does not match either journaled"),
        ):
            refresh.operation_instruction_digests(home, "op-1")

    def test_excluded_root_failure_precedes_instruction_preflight_and_bootstrap(self) -> None:
        with (
            mock.patch.object(
                refresh,
                "require_excluded_skill_roots_clear",
                side_effect=SystemExit("excluded skill root closure failed"),
            ),
            mock.patch.object(refresh, "prepare_instruction_sync") as prepare,
            mock.patch.object(refresh, "run_tooling_bootstrap") as bootstrap,
        ):
            with self.assertRaisesRegex(SystemExit, "excluded skill root closure failed"):
                self.run_main(["--harness", "zcode", "--dry-run"])
        prepare.assert_not_called()
        bootstrap.assert_not_called()

    def test_legacy_bypass_fails_before_bootstrap(self) -> None:
        with mock.patch.object(refresh, "run_tooling_bootstrap") as bootstrap:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(["--skip-agents-skills", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)
        bootstrap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
