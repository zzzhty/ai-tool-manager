from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import refresh_harness as refresh  # noqa: E402
from check_skill_discovery import PluginListRow  # noqa: E402
from harness_registry import load_harness_registry, resolve_harness_plan  # noqa: E402
from plugin_package_identity import update_repository_identity  # noqa: E402
from repo_skill_catalog import load_repo_skill_catalog  # noqa: E402


def write_skill(root: Path, plugin: str, name: str) -> None:
    skill_root = root / "plugins" / plugin / "skills" / name
    skill_root.mkdir(parents=True)
    skill_root.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: fixture\n---\n",
        encoding="utf-8",
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


class HarnessFixture:
    def __init__(self, root: Path) -> None:
        self.repo = root / "repo"
        self.codex_home = root / "codex"
        self.target = root / "agents" / "skills"
        self.enabled: set[str] = set()
        self.versions: dict[str, str] = {}
        self.events: list[str] = []
        self.bad_cached_identity: str | None = None
        self.deny_reinstall: set[str] = set()
        self.repo.mkdir(parents=True)
        self.repo.joinpath("AGENTS.md").write_text("fixture instructions\n", encoding="utf-8")
        self.repo.joinpath("VERSION").write_text("1.0.0\n", encoding="utf-8")
        for plugin, skill in (("alpha", "one"), ("beta", "two")):
            write_skill(self.repo, plugin, skill)
            write_json(
                self.repo / "plugins" / plugin / ".codex-plugin" / "plugin.json",
                {"name": plugin, "version": "0.1.0+codex.bootstrap", "skills": "./skills/"},
            )
        write_json(
            self.repo / ".agents" / "plugins" / "marketplace.json",
            {
                "name": "test",
                "plugins": [
                    {
                        "name": plugin,
                        "source": {"source": "local", "path": f"./plugins/{plugin}"},
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                    }
                    for plugin in ("alpha", "beta")
                ],
            },
        )
        write_json(
            self.repo / ".agents" / "plugins" / "install-manifest.json",
            {
                "harness": "codex",
                "marketplace": "test",
                "plugins": [
                    {"name": plugin, "install": True, "check": True}
                    for plugin in ("alpha", "beta")
                ],
            },
        )
        update_repository_identity(self.repo)
        self.source_versions = {
            plugin: json.loads(
                (
                    self.repo
                    / "plugins"
                    / plugin
                    / ".codex-plugin"
                    / "plugin.json"
                ).read_text(encoding="utf-8")
            )["version"]
            for plugin in ("alpha", "beta")
        }
        self.catalog = load_repo_skill_catalog(self.repo)

    def configure_plugins(self) -> None:
        self.codex_home.mkdir(parents=True, exist_ok=True)
        self.codex_home.joinpath("config.toml").write_text(
            '\n'.join(
                f'[plugins."{name}@test"]\nenabled = true'
                for name in sorted(self.enabled)
            ),
            encoding="utf-8",
        )

    def rows(
        self,
        _codex: str,
        *,
        marketplace_name: str,
        plugin_names: set[str],
        env: dict[str, str],
    ) -> dict[tuple[str, str], PluginListRow]:
        del marketplace_name, plugin_names, env
        return {
            ("test", name): PluginListRow(
                "installed, enabled",
                self.versions.get(name, self.source_versions.get(name, "0.9.0")),
            )
            for name in self.enabled
        }

    def _write_cache(self, plugin: str) -> None:
        version = self.source_versions[plugin]
        version_root = self.codex_home / "plugins" / "cache" / "test" / plugin / version
        if version_root.exists():
            shutil.rmtree(version_root)
        shutil.copytree(self.repo / "plugins" / plugin, version_root)
        if self.bad_cached_identity == plugin:
            canonical = next(source for source in self.catalog.sources if source.plugin == plugin)
            cached_skill = version_root / "skills" / canonical.directory_name / "SKILL.md"
            cached_skill.write_text(
                "---\nname: wrong-identity\ndescription: cached fixture\n---\n",
                encoding="utf-8",
            )

    def run(self, command: list[str], *, env: dict[str, str], dry_run: bool, check: bool = True) -> int:
        del env, check
        selector = command[-1]
        plugin = selector.split("@", 1)[0]
        action = command[2]
        self.events.append(f"{action}:{plugin}")
        if dry_run:
            return 0
        if action == "add":
            if plugin in self.enabled and plugin in self.deny_reinstall:
                raise SystemExit("failed to copy plugin file: access denied")
            self.enabled.add(plugin)
            self.versions[plugin] = self.source_versions[plugin]
            self._write_cache(plugin)
        elif action == "remove":
            self.enabled.discard(plugin)
        else:  # pragma: no cover - fixture contract
            raise AssertionError(command)
        return 0


class RefreshHarnessIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fixture = HarnessFixture(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)
        # This fixture models Codex operations, not subprocess transport/retries.
        # Keep it platform independent; the Windows retry tests exercise transport.
        add_patch = mock.patch.object(
            refresh, "add_codex_plugin",
            side_effect=lambda codex, selector, *, env, dry_run, **kwargs:
                refresh.run([codex, "plugin", "add", selector], env=env, dry_run=dry_run),
        )
        add_patch.start()
        self.addCleanup(add_patch.stop)

    def patches(self):
        return (
            mock.patch.object(refresh, "read_codex_plugin_rows", side_effect=self.fixture.rows),
            mock.patch.object(refresh, "run", side_effect=self.fixture.run),
        )

    def run_pruning_main(self, *, dry_run: bool = True) -> None:
        arguments = [
            "refresh_harness.py",
            "--harness",
            "codex",
            "--marketplace-source",
            str(self.fixture.repo),
            "--codex-home",
            str(self.fixture.codex_home),
            "--skip-bootstrap",
            "--skip-agents",
            "--skip-hooks",
            "--skip-doctor",
            "--yes",
        ]
        if dry_run:
            arguments.append("--dry-run")
        registry = load_harness_registry()
        codex_plan = resolve_harness_plan(
            registry,
            "codex",
            environ={"CODEX_HOME": str(self.fixture.codex_home)},
            user_home=self.fixture.target.parents[1],
        )
        codex_plan = replace(
            codex_plan,
            repo_root=self.fixture.repo,
            root=self.fixture.codex_home,
            instructions_source=self.fixture.repo / "AGENTS.md",
            instructions_target=self.fixture.codex_home / "AGENTS.md",
            instruction_shadow_paths=(self.fixture.codex_home / "AGENTS.override.md",),
            excluded_skill_roots=(self.fixture.target,),
            marketplace_path=self.fixture.repo / ".agents/plugins/marketplace.json",
            install_manifest_path=self.fixture.repo / ".agents/plugins/install-manifest.json",
        )

        def resolved_plan(_registry, _harness_id, **_kwargs):
            return codex_plan

        rows_patch, run_patch = self.patches()
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(refresh, "load_repo_skill_catalog", return_value=self.fixture.catalog),
            mock.patch.object(refresh, "load_harness_registry", return_value=registry),
            mock.patch.object(refresh, "resolve_harness_plan", side_effect=resolved_plan),
            mock.patch.object(refresh, "resolve_codex_executable", return_value="codex"),
            mock.patch.object(refresh, "require_codex_plugin_commands"),
            mock.patch.object(
                refresh,
                "ensure_marketplace_source",
                return_value=refresh.MarketplaceSourceBinding(
                    "local",
                    str(self.fixture.repo),
                ),
            ),
            rows_patch,
            run_patch,
        ):
            refresh.main()

    def test_install_manifest_has_one_exact_repository_owned_shape(self) -> None:
        manifest = self.fixture.repo / ".agents" / "plugins" / "install-manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload.pop("harness")
        write_json(manifest, payload)

        with self.assertRaisesRegex(SystemExit, "missing required top-level fields: harness"):
            refresh.load_install_manifest(manifest)

        payload["harness"] = "codex"
        payload["schemaVersion"] = 4
        write_json(manifest, payload)
        with self.assertRaisesRegex(SystemExit, "unsupported top-level fields: schemaVersion"):
            refresh.load_install_manifest(manifest)

        payload.pop("schemaVersion")
        payload["skillMode"] = "plugin"
        write_json(manifest, payload)
        with self.assertRaisesRegex(SystemExit, "unsupported top-level fields: skillMode"):
            refresh.load_install_manifest(manifest)

        payload.pop("skillMode")
        payload["plugins"][0]["version"] = 1
        write_json(manifest, payload)
        with self.assertRaisesRegex(SystemExit, "plugin entry #1 has unsupported fields: version"):
            refresh.load_install_manifest(manifest)

        payload["plugins"][0].pop("version")
        payload["plugins"][0].pop("check")
        write_json(manifest, payload)
        with self.assertRaisesRegex(SystemExit, "plugin entry #1 is missing required fields: check"):
            refresh.load_install_manifest(manifest)

    def test_codex_apply_rejects_a_marketplace_source_other_than_the_validated_checkout(self) -> None:
        with self.assertRaisesRegex(
            SystemExit,
            "local marketplace source is not the validated canonical checkout",
        ):
            refresh.apply_codex_harness(
                self.fixture.catalog,
                codex="codex",
                codex_home=self.fixture.codex_home,
                marketplace_name="test",
                excluded_skill_roots=(self.fixture.target,),
                marketplace_source_binding=refresh.MarketplaceSourceBinding(
                    "local",
                    str(self.fixture.repo.parent / "alternate"),
                ),
                env={},
                dry_run=False,
            )

    @unittest.skipUnless(os.name == "nt", "Windows extended path syntax")
    def test_local_marketplace_binding_accepts_windows_extended_path_prefix(self) -> None:
        extended_repo = f"\\\\?\\{self.fixture.repo.resolve()}"

        self.assertEqual(
            refresh.marketplace_source_binding_issues(
                self.fixture.catalog,
                refresh.MarketplaceSourceBinding("local", extended_repo),
            ),
            [],
        )

    def test_git_marketplace_binding_requires_canonical_remote_and_exact_revision(self) -> None:
        with (
            mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git"),
            mock.patch.object(refresh, "git_worktree_clean", return_value=(True, "clean")),
            mock.patch.object(refresh, "git_head_revision", return_value="abc123"),
        ):
            self.assertEqual(
                refresh.marketplace_source_binding_issues(
                    self.fixture.catalog,
                    refresh.MarketplaceSourceBinding(
                        "git",
                        "git@example/repo.git",
                        "abc123",
                    ),
                ),
                [],
            )
            wrong_source = refresh.marketplace_source_binding_issues(
                self.fixture.catalog,
                refresh.MarketplaceSourceBinding(
                    "git",
                    "git@example/other.git",
                    "abc123",
                ),
            )
            wrong_revision = refresh.marketplace_source_binding_issues(
                self.fixture.catalog,
                refresh.MarketplaceSourceBinding(
                    "git",
                    "git@example/repo.git",
                    "different",
                ),
            )

        self.assertIn("not the canonical checkout remote", "\n".join(wrong_source))
        self.assertIn("not pinned to the validated checkout revision", "\n".join(wrong_revision))

    def test_codex_rejects_an_empty_interrupted_excluded_root_residue(self) -> None:
        interrupted = self.fixture.target / "one"
        interrupted.mkdir(parents=True)
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            with self.assertRaisesRegex(SystemExit, "excluded skill root closure failed"):
                refresh.apply_codex_harness(
                    self.fixture.catalog,
                    codex="codex",
                    codex_home=self.fixture.codex_home,
                    marketplace_name="test",
                    excluded_skill_roots=(self.fixture.target,),
                    marketplace_source_binding=refresh.MarketplaceSourceBinding(
                        "local",
                        str(self.fixture.repo),
                    ),
                    env={},
                    dry_run=False,
                )

        self.assertTrue(interrupted.is_dir())
        self.assertEqual(self.fixture.events, [])

    def test_codex_closure_failure_removes_partial_plugins(self) -> None:
        self.fixture.bad_cached_identity = "beta"
        rows_patch, run_patch = self.patches()
        with rows_patch, run_patch:
            with self.assertRaisesRegex(SystemExit, "cache content identity differs"):
                refresh.apply_codex_harness(
                    self.fixture.catalog,
                    codex="codex",
                    codex_home=self.fixture.codex_home,
                    marketplace_name="test",
                    excluded_skill_roots=(self.fixture.target,),
                    marketplace_source_binding=refresh.MarketplaceSourceBinding(
                        "local",
                        str(self.fixture.repo),
                    ),
                    env={},
                    dry_run=False,
                )

        self.assertEqual(self.fixture.enabled, set())
        self.assertFalse(self.fixture.target.exists())
        self.assertEqual(
            self.fixture.events,
            ["add:alpha", "add:beta", "remove:beta", "remove:alpha"],
        )

    def test_codex_apply_does_not_reinstall_an_enabled_current_plugin(self) -> None:
        self.fixture.enabled.add("alpha")
        self.fixture.configure_plugins()
        self.fixture._write_cache("alpha")
        self.fixture.deny_reinstall.add("alpha")
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            refresh.apply_codex_harness(
                self.fixture.catalog,
                codex="codex",
                codex_home=self.fixture.codex_home,
                marketplace_name="test",
                excluded_skill_roots=(self.fixture.target,),
                marketplace_source_binding=refresh.MarketplaceSourceBinding(
                    "local",
                    str(self.fixture.repo),
                ),
                env={},
                dry_run=False,
            )

        self.assertEqual(self.fixture.enabled, {"alpha", "beta"})
        self.assertEqual(self.fixture.events, ["add:beta"])

    def test_codex_repair_reinstalls_an_enabled_current_plugin(self) -> None:
        self.fixture.enabled.add("alpha")
        self.fixture.configure_plugins()
        self.fixture._write_cache("alpha")
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            refresh.apply_codex_harness(
                self.fixture.catalog,
                codex="codex",
                codex_home=self.fixture.codex_home,
                marketplace_name="test",
                excluded_skill_roots=(self.fixture.target,),
                marketplace_source_binding=refresh.MarketplaceSourceBinding(
                    "local",
                    str(self.fixture.repo),
                ),
                env={},
                dry_run=False,
                repair=True,
            )

        self.assertEqual(self.fixture.enabled, {"alpha", "beta"})
        self.assertEqual(self.fixture.events, ["add:alpha", "add:beta"])

    def test_codex_apply_rejects_same_version_cache_drift_before_mutation(self) -> None:
        self.fixture.enabled.add("alpha")
        self.fixture.configure_plugins()
        self.fixture._write_cache("alpha")
        cached_skill = next(
            (
                self.fixture.codex_home
                / "plugins"
                / "cache"
                / "test"
                / "alpha"
                / self.fixture.source_versions["alpha"]
                / "skills"
            ).rglob("SKILL.md")
        )
        cached_skill.write_text(
            cached_skill.read_text(encoding="utf-8") + "stale\\n",
            encoding="utf-8",
        )
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            with self.assertRaisesRegex(SystemExit, "cache content identity differs"):
                refresh.apply_codex_harness(
                    self.fixture.catalog,
                    codex="codex",
                    codex_home=self.fixture.codex_home,
                    marketplace_name="test",
                    excluded_skill_roots=(self.fixture.target,),
                    marketplace_source_binding=refresh.MarketplaceSourceBinding(
                        "local",
                        str(self.fixture.repo),
                    ),
                    env={},
                    dry_run=False,
                )

        self.assertEqual(self.fixture.events, [])

    def test_codex_apply_rejects_source_content_without_new_generation(self) -> None:
        source_skill = next((self.fixture.repo / "plugins" / "alpha" / "skills").rglob("SKILL.md"))
        source_skill.write_text(
            source_skill.read_text(encoding="utf-8") + "changed\\n",
            encoding="utf-8",
        )
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            with self.assertRaisesRegex(SystemExit, "source content identity requires version"):
                refresh.apply_codex_harness(
                    self.fixture.catalog,
                    codex="codex",
                    codex_home=self.fixture.codex_home,
                    marketplace_name="test",
                    excluded_skill_roots=(self.fixture.target,),
                    marketplace_source_binding=refresh.MarketplaceSourceBinding(
                        "local",
                        str(self.fixture.repo),
                    ),
                    env={},
                    dry_run=False,
                )

        self.assertEqual(self.fixture.events, [])

    def test_codex_apply_selects_exact_identity_after_base_version_decreases(self) -> None:
        self.fixture.enabled.add("alpha")
        self.fixture.versions["alpha"] = "1.2.3+codex.upstream"
        self.fixture.configure_plugins()
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            refresh.apply_codex_harness(
                self.fixture.catalog,
                codex="codex",
                codex_home=self.fixture.codex_home,
                marketplace_name="test",
                excluded_skill_roots=(self.fixture.target,),
                marketplace_source_binding=refresh.MarketplaceSourceBinding(
                    "local",
                    str(self.fixture.repo),
                ),
                env={},
                dry_run=False,
            )

        self.assertEqual(self.fixture.enabled, {"alpha", "beta"})
        self.assertEqual(self.fixture.versions, self.fixture.source_versions)
        self.assertEqual(self.fixture.events, ["add:alpha", "add:beta"])

    def test_unrelated_user_skill_in_excluded_root_does_not_block_codex(self) -> None:
        user_skill = self.fixture.target / "user-skill"
        user_skill.mkdir(parents=True)
        user_skill.joinpath("SKILL.md").write_text(
            "---\nname: user-skill\n---\n",
            encoding="utf-8",
        )
        rows_patch, run_patch = self.patches()

        with rows_patch, run_patch:
            refresh.apply_codex_harness(
                self.fixture.catalog,
                codex="codex",
                codex_home=self.fixture.codex_home,
                marketplace_name="test",
                excluded_skill_roots=(self.fixture.target,),
                marketplace_source_binding=refresh.MarketplaceSourceBinding(
                    "local",
                    str(self.fixture.repo),
                ),
                env={},
                dry_run=False,
            )

        self.assertEqual(self.fixture.enabled, {"alpha", "beta"})
        self.assertTrue(user_skill.is_dir())

    def test_prune_dry_run_reaches_cache_only_stale_plugin_before_full_closure(self) -> None:
        stale_cache = (
            self.fixture.codex_home
            / "plugins"
            / "cache"
            / "test"
            / "retired"
            / "0.9.0"
        )
        stale_cache.mkdir(parents=True)

        with self.assertRaisesRegex(
            SystemExit,
            "cached oh-my-harness plugins have no canonical repository skills: retired",
        ):
            refresh.preflight_codex_distribution(
                self.fixture.catalog,
                codex_home=self.fixture.codex_home,
                marketplace_name="test",
            )

        self.run_pruning_main()

        self.assertTrue(stale_cache.is_dir())
        self.assertEqual(self.fixture.events, ["add:alpha", "add:beta"])

    def test_prune_dry_run_reaches_enabled_stale_plugin_before_full_closure(self) -> None:
        self.fixture.enabled.add("retired")
        self.fixture.configure_plugins()

        self.run_pruning_main()

        self.assertEqual(
            self.fixture.events,
            ["remove:retired", "add:alpha", "add:beta"],
        )

    def test_prune_never_ignores_cli_only_uninventoried_plugin(self) -> None:
        self.fixture.enabled.add("retired")

        with self.assertRaisesRegex(
            SystemExit,
            "unclassified enabled oh-my-harness plugins.*retired",
        ):
            self.run_pruning_main()

        self.assertEqual(self.fixture.events, [])

    def test_prune_rejects_cli_enabled_cache_collision_before_real_mutation(self) -> None:
        stale_cache = (
            self.fixture.codex_home
            / "plugins"
            / "cache"
            / "test"
            / "retired"
            / "0.9.0"
        )
        stale_cache.mkdir(parents=True)
        self.fixture.enabled.add("retired")

        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                with self.assertRaisesRegex(
                    SystemExit,
                    "unclassified enabled oh-my-harness plugins.*retired",
                ):
                    self.run_pruning_main(dry_run=dry_run)

        self.assertTrue(stale_cache.is_dir())
        self.assertEqual(self.fixture.events, [])


if __name__ == "__main__":
    unittest.main()
