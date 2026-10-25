from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_harness  # noqa: E402
from check_skill_discovery import (  # noqa: E402
    PluginListRow,
    codex_plugin_rows,
    excluded_skill_root_issues,
    plugin_installation_issues,
    plugin_package_issues,
    codex_harness_issues,
)
from repo_skill_catalog import load_repo_skill_catalog  # noqa: E402
from sync_agents_skills import create_projection_link, sync_layer  # noqa: E402


def write_skill(root: Path, plugin: str, name: str) -> Path:
    skill = root / "plugins" / plugin / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: fixture\n---\n",
        encoding="utf-8",
    )
    return skill


class HarnessClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo = root / "repo"
        self.one = write_skill(self.repo, "alpha", "one")
        self.two = write_skill(self.repo, "beta", "two")
        self.catalog = load_repo_skill_catalog(self.repo)
        self.target = root / "agents" / "skills"
        self.addCleanup(self._tmp.cleanup)

    def test_excluded_root_allows_unrelated_user_skills(self) -> None:
        user_skill = self.target / "user-skill"
        user_skill.mkdir(parents=True)
        user_skill.joinpath("SKILL.md").write_text(
            "---\nname: user-skill\n---\n",
            encoding="utf-8",
        )
        self.assertEqual(
            excluded_skill_root_issues(
                self.catalog,
                roots=(self.target,),
            ),
            [],
        )

    def test_excluded_root_rejects_catalog_entries_and_stale_owned_links(self) -> None:
        self.target.mkdir(parents=True)
        create_projection_link(self.target / "one", self.two)
        unmanaged = self.target / "two"
        unmanaged.mkdir()
        (unmanaged / "keep.txt").write_text("user content", encoding="utf-8")
        create_projection_link(self.target / "stale", self.one)
        issues = excluded_skill_root_issues(
            self.catalog,
            roots=(self.target,),
        )
        report = "\n".join(issues)
        self.assertIn("excluded skill root contains catalog identity one", report)
        self.assertIn("excluded skill root contains catalog identity two", report)
        self.assertIn("stale repository-owned projection", report)

    def test_codex_requires_exact_plugins_and_clear_excluded_roots(self) -> None:
        self.assertEqual(
            codex_harness_issues(
                self.catalog,
                excluded_skill_roots=(self.target,),
                enabled_plugin_names={"alpha", "beta"},
            ),
            [],
        )
        sync_layer(self.catalog, target_root=self.target, dry_run=False, prune=True)
        issues = codex_harness_issues(
            self.catalog,
            excluded_skill_roots=(self.target,),
            enabled_plugin_names={"alpha", "adapter"},
        )
        report = "\n".join(issues)
        self.assertIn("not enabled: beta", report)
        self.assertIn("no canonical repository skills: adapter", report)
        self.assertIn("excluded skill root contains catalog identity", report)


class PluginListParserTests(unittest.TestCase):
    def test_empty_marketplace_state_parses_as_no_rows(self) -> None:
        self.assertEqual(
            codex_plugin_rows(json.dumps({"installed": [], "available": []})),
            {},
        )

    def test_non_json_output_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            codex_plugin_rows("unexpected plugin output\n")

    def test_parses_installed_and_uninstalled_rows(self) -> None:
        output = json.dumps(
            {
                "installed": [
                    {
                        "pluginId": "alpha@oh-my-harness",
                        "name": "alpha",
                        "marketplaceName": "oh-my-harness",
                        "version": "1.2.3",
                        "installed": True,
                        "enabled": True,
                    },
                    {
                        "pluginId": "beta@oh-my-harness",
                        "name": "beta",
                        "marketplaceName": "oh-my-harness",
                        "version": "2.0.0",
                        "installed": True,
                        "enabled": False,
                    },
                ],
                "available": [
                    {
                        "pluginId": "gamma@oh-my-harness",
                        "name": "gamma",
                        "marketplaceName": "oh-my-harness",
                        "version": "3.0.0",
                        "installed": False,
                        "enabled": False,
                    }
                ],
            }
        )
        self.assertEqual(
            codex_plugin_rows(output),
            {
                ("oh-my-harness", "alpha"): PluginListRow("installed, enabled", "1.2.3"),
                ("oh-my-harness", "beta"): PluginListRow("installed", "2.0.0"),
                ("oh-my-harness", "gamma"): PluginListRow("not installed", ""),
            },
        )

    def test_scoped_parse_ignores_duplicate_unrelated_catalog_rows(self) -> None:
        own = {
            "pluginId": "alpha@oh-my-harness",
            "name": "alpha",
            "marketplaceName": "oh-my-harness",
            "version": "1.2.3",
            "installed": True,
            "enabled": True,
        }
        unrelated = {
            "pluginId": "conductor@openai-curated-remote",
            "name": "conductor",
            "marketplaceName": "openai-curated-remote",
            "installed": False,
            "enabled": False,
        }
        output = json.dumps(
            {
                "installed": [own],
                "available": [
                    {**unrelated, "version": "1.0.0"},
                    {**unrelated, "version": "1.6.6"},
                ],
            }
        )
        self.assertEqual(
            codex_plugin_rows(
                output,
                marketplace_name="oh-my-harness",
                plugin_names={"alpha"},
            ),
            {
                ("oh-my-harness", "alpha"): PluginListRow(
                    "installed, enabled", "1.2.3"
                ),
            },
        )

    def test_malformed_relevant_entry_fails_closed(self) -> None:
        output = json.dumps(
            {
                "installed": [
                    {
                        "pluginId": "alpha@oh-my-harness",
                        "name": "alpha",
                        "marketplaceName": "oh-my-harness",
                        "version": "",
                        "installed": True,
                        "enabled": True,
                    }
                ],
                "available": [],
            }
        )
        with self.assertRaisesRegex(ValueError, "installed plugin row has no version"):
            codex_plugin_rows(output)

    def test_checker_requests_machine_readable_available_rows(self) -> None:
        runner = check_harness.CheckRunner()
        result = mock.Mock(
            returncode=0,
            stdout=json.dumps({"installed": [], "available": []}),
            stderr="",
        )
        with mock.patch.object(runner, "run_command", return_value=result) as run:
            self.assertEqual(
                runner.read_plugin_rows(
                    "codex",
                    marketplace_name="oh-my-harness",
                    plugin_names={"alpha"},
                    env={"PATH": "/bin"},
                ),
                {},
            )
        run.assert_called_once_with(
            ["codex", "plugin", "list", "--json", "--available"],
            env={"PATH": "/bin"},
        )


class PluginInstallationClosureTests(unittest.TestCase):
    def test_cli_and_cache_version_drift_are_reported_by_installation_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            source = write_skill(repo, "alpha", "one")
            source_manifest = source.parents[1] / ".codex-plugin" / "plugin.json"
            source_manifest.parent.mkdir(parents=True, exist_ok=True)
            source_manifest.write_text(
                '{"name": "alpha", "version": "2.0.0", "skills": "./skills/"}\n',
                encoding="utf-8",
            )
            catalog = load_repo_skill_catalog(repo)
            codex_home = root / "codex"
            for version in ("1.0.0", "2.0.0"):
                (codex_home / "plugins" / "cache" / "test" / "alpha" / version).mkdir(
                    parents=True
                )

            issues = plugin_installation_issues(
                catalog,
                marketplace_name="test",
                excluded_skill_roots=(root / "agents" / "skills",),
                codex_home=codex_home,
                rows={
                    ("test", "alpha"): PluginListRow(
                        "installed, enabled",
                        "1.0.0",
                    )
                },
                plugin_sources={"alpha": source.parents[1]},
            )

        report = "\n".join(issues)
        self.assertIn("installed version mismatch", report)
        self.assertIn("expected exactly one inspectable cache version", report)

    def test_manifest_schema_and_identity_failures_are_reported_by_installation_closure(self) -> None:
        cases = (
            (
                "source-json",
                {"source_text": "{not-json\n"},
                "source manifest is not valid readable JSON",
            ),
            (
                "source-name",
                {"source_name": "other"},
                "source manifest name mismatch",
            ),
            (
                "cache-json",
                {"cache_text": "{not-json\n"},
                "cache manifest is not valid readable JSON",
            ),
            (
                "cache-name",
                {"cache_name": "other"},
                "found ('other', '2.0.0')",
            ),
            (
                "cache-version",
                {"cache_version": "9.9.9"},
                "found ('alpha', '9.9.9')",
            ),
        )
        for label, overrides, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                source = write_skill(repo, "alpha", "one")
                source_manifest = source.parents[1] / ".codex-plugin" / "plugin.json"
                source_manifest.parent.mkdir(parents=True, exist_ok=True)
                source_manifest.write_text(
                    str(overrides.get("source_text"))
                    if "source_text" in overrides
                    else json.dumps(
                        {
                            "name": overrides.get("source_name", "alpha"),
                            "version": "2.0.0",
                            "skills": "./skills/",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                catalog = load_repo_skill_catalog(repo)
                version_root = (
                    root / "codex" / "plugins" / "cache" / "test" / "alpha" / "2.0.0"
                )
                cache_manifest = version_root / ".codex-plugin" / "plugin.json"
                cache_manifest.parent.mkdir(parents=True, exist_ok=True)
                cache_manifest.write_text(
                    str(overrides.get("cache_text"))
                    if "cache_text" in overrides
                    else json.dumps(
                        {
                            "name": overrides.get("cache_name", "alpha"),
                            "version": overrides.get("cache_version", "2.0.0"),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                cached_skill = version_root / "skills" / "one"
                cached_skill.mkdir(parents=True)
                cached_skill.joinpath("SKILL.md").write_text(
                    "---\nname: one\ndescription: fixture\n---\n",
                    encoding="utf-8",
                )

                issues = plugin_installation_issues(
                    catalog,
                    marketplace_name="test",
                    excluded_skill_roots=(root / "agents" / "skills",),
                    codex_home=root / "codex",
                    rows={
                        ("test", "alpha"): PluginListRow(
                            "installed, enabled",
                            "2.0.0",
                        )
                    },
                    plugin_sources={"alpha": source.parents[1]},
                )

            self.assertIn(expected, "\n".join(issues))

    def test_source_package_contract_locks_manifest_and_loaded_skill_tree(self) -> None:
        cases = (
            (
                "manifest-skills",
                "manifest",
                "source manifest skills must be exactly './skills/'",
            ),
            ("extra-directory", "extra", "outside the loaded catalog"),
            ("identity-drift", "identity", "catalog skill name changed after catalog load"),
            (
                "symlink-escape",
                "symlink",
                "source skill directory escapes package authority",
            ),
            (
                "nested-file-symlink-escape",
                "nested-file-symlink",
                "source package entry escapes package authority",
            ),
            (
                "nested-directory-symlink-escape",
                "nested-directory-symlink",
                "source package entry escapes package authority",
            ),
        )
        for label, mutation, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = root / "repo"
                source = write_skill(repo, "alpha", "one")
                source_root = source.parents[1]
                manifest = source_root / ".codex-plugin" / "plugin.json"
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text(
                    '{"name": "alpha", "version": "2.0.0", "skills": "./skills/"}\n',
                    encoding="utf-8",
                )
                catalog = load_repo_skill_catalog(repo)
                if mutation == "manifest":
                    manifest.write_text(
                        '{"name": "alpha", "version": "2.0.0", "skills": "./other/"}\n',
                        encoding="utf-8",
                    )
                elif mutation == "extra":
                    write_skill(repo, "alpha", "late-added")
                elif mutation == "symlink":
                    external = root / "external-skill"
                    external.mkdir()
                    external.joinpath("SKILL.md").write_text(
                        "---\nname: one\ndescription: external fixture\n---\n",
                        encoding="utf-8",
                    )
                    source.joinpath("SKILL.md").unlink()
                    source.rmdir()
                    source.symlink_to(external, target_is_directory=True)
                elif mutation == "nested-file-symlink":
                    external = root / "external-tool.py"
                    external.write_text("print('external')\n", encoding="utf-8")
                    scripts = source / "scripts"
                    scripts.mkdir()
                    scripts.joinpath("tool.py").symlink_to(external)
                elif mutation == "nested-directory-symlink":
                    external = root / "external-resources"
                    external.mkdir()
                    external.joinpath("data.txt").write_text("external\n", encoding="utf-8")
                    source.joinpath("references").symlink_to(
                        external,
                        target_is_directory=True,
                    )
                else:
                    source.joinpath("SKILL.md").write_text(
                        "---\nname: changed\ndescription: fixture\n---\n",
                        encoding="utf-8",
                    )

                issues = plugin_package_issues(
                    catalog,
                    plugin_sources={"alpha": source_root},
                )

            self.assertIn(expected, "\n".join(issues))

    def test_plugin_installation_closure_rejects_excluded_root_links_with_valid_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            source = write_skill(repo, "alpha", "one")
            source_root = source.parents[1]
            source_manifest = source_root / ".codex-plugin" / "plugin.json"
            source_manifest.parent.mkdir(parents=True, exist_ok=True)
            source_manifest.write_text(
                '{"name": "alpha", "version": "2.0.0", "skills": "./skills/"}\n',
                encoding="utf-8",
            )
            catalog = load_repo_skill_catalog(repo)
            target = root / "agents" / "skills"
            sync_layer(catalog, target_root=target, dry_run=False, prune=True)
            version_root = root / "codex" / "plugins" / "cache" / "test" / "alpha" / "2.0.0"
            cache_manifest = version_root / ".codex-plugin" / "plugin.json"
            cache_manifest.parent.mkdir(parents=True, exist_ok=True)
            cache_manifest.write_text(
                '{"name": "alpha", "version": "2.0.0"}\n',
                encoding="utf-8",
            )
            cached_skill = version_root / "skills" / "one"
            cached_skill.mkdir(parents=True)
            cached_skill.joinpath("SKILL.md").write_text(
                "---\nname: one\ndescription: cached fixture\n---\n",
                encoding="utf-8",
            )

            issues = plugin_installation_issues(
                catalog,
                marketplace_name="test",
                excluded_skill_roots=(target,),
                codex_home=root / "codex",
                rows={
                    ("test", "alpha"): PluginListRow(
                        "installed, enabled",
                        "2.0.0",
                    )
                },
                plugin_sources={"alpha": source_root},
            )

        self.assertIn("excluded skill root contains catalog identity", "\n".join(issues))


class CheckHarnessCliTests(unittest.TestCase):
    def run_main(self, arguments: list[str]) -> None:
        with mock.patch.object(sys, "argv", ["check_harness.py", *arguments]):
            check_harness.main()

    def test_legacy_discovery_profile_option_is_rejected(self) -> None:
        with mock.patch.object(check_harness, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(["--discovery-profile", "universal"])
        self.assertEqual(raised.exception.code, 2)
        load_catalog.assert_not_called()

    def test_default_harness_is_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(
                    check_harness,
                    "resolve_codex_executable",
                    side_effect=SystemExit("resolved default Codex harness"),
                ) as resolve,
            ):
                with self.assertRaisesRegex(SystemExit, "resolved default Codex harness"):
                    self.run_main(["--codex-home", str(root / "codex")])
        resolve.assert_called_once()

    def test_removed_shared_harness_fails_before_catalog_load(self) -> None:
        with mock.patch.object(check_harness, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaisesRegex(SystemExit, "unknown harness 'shared'"):
                self.run_main(["--harness", "shared"])
        load_catalog.assert_not_called()

    def test_legacy_bypass_option_is_rejected_before_runtime_checks(self) -> None:
        with mock.patch.object(check_harness, "resolve_codex_executable") as resolve:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(["--skip-plugins"])
        self.assertEqual(raised.exception.code, 2)
        resolve.assert_not_called()

    def test_unknown_harness_fails_before_catalog_load(self) -> None:
        with mock.patch.object(check_harness, "load_repo_skill_catalog") as load_catalog:
            with self.assertRaisesRegex(SystemExit, "unknown harness"):
                self.run_main(["--harness", "unknown"])
        load_catalog.assert_not_called()

    def test_native_harness_does_not_read_codex_marketplace_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.dict(
                    check_harness.os.environ,
                    {"PI_CODING_AGENT_DIR": str(Path(tmp) / "pi-agent")},
                ),
                mock.patch.object(
                    check_harness,
                    "load_install_manifest",
                    side_effect=AssertionError("Codex manifest must not be read"),
                ),
                mock.patch.object(check_harness.CheckRunner, "check_tooling_python"),
                mock.patch.object(check_harness.CheckRunner, "check_excluded_skill_roots"),
                mock.patch.object(check_harness.CheckRunner, "check_skill_projection"),
                mock.patch.object(check_harness.CheckRunner, "check_harness_instructions"),
                mock.patch.object(check_harness.CheckRunner, "finish"),
            ):
                self.run_main(
                    [
                        "--harness",
                        "pi-agent",
                        "--codex-home",
                        str(Path(tmp) / "codex"),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
