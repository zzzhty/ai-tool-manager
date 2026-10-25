from __future__ import annotations

import collections
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_harness
import plugin_package_identity as identity
import refresh_harness as refresh
from check_skill_discovery import marketplace_plugin_sources, plugin_installation_issues
from test_refresh_harness_integration import HarnessFixture


class ClosurePhaseReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = HarnessFixture(Path(temporary.name))
        self.fixture.enabled.update(self.fixture.source_versions)
        for name in self.fixture.enabled:
            self.fixture._write_cache(name)
        self.marketplace, self.sources = marketplace_plugin_sources(self.fixture.repo)

    def closure(self) -> list[str]:
        return plugin_installation_issues(
            self.fixture.catalog, marketplace_name=self.marketplace,
            excluded_skill_roots=(), codex_home=self.fixture.codex_home,
            rows=self.fixture.rows("codex", marketplace_name=self.marketplace,
                                   plugin_names=set(self.sources), env={}),
            plugin_sources=self.sources,
        )

    def test_closure_hashes_each_source_and_cache_once(self) -> None:
        with mock.patch.object(identity, "canonical_plugin_package_digest",
                               wraps=identity.canonical_plugin_package_digest) as digest:
            self.assertEqual(self.closure(), [])
        paths = collections.Counter(call.args[0] for call in digest.call_args_list)
        self.assertEqual(len(paths), 4)
        self.assertEqual(set(paths.values()), {1})
        for source in self.sources.values():
            self.assertEqual(paths[source], 1)

    def test_next_closure_rereads_source_and_cache_defects(self) -> None:
        self.assertEqual(self.closure(), [])
        source = self.sources["alpha"] / "skills/one/SKILL.md"
        original = source.read_bytes()
        source.write_bytes(original + b"changed source\n")
        self.assertIn("source content identity requires version", "\n".join(self.closure()))
        source.write_bytes(original)
        self.assertEqual(self.closure(), [])
        cache = (self.fixture.codex_home / "plugins/cache/test/alpha"
                 / self.fixture.source_versions["alpha"] / "skills/one/SKILL.md")
        cache.write_bytes(original + b"changed cache\n")
        self.assertIn("cache content identity differs", "\n".join(self.closure()))

    def test_standalone_cache_check_still_hashes_both_inputs(self) -> None:
        source = self.sources["alpha"]
        cache = (self.fixture.codex_home / "plugins/cache/test/alpha"
                 / self.fixture.source_versions["alpha"])
        with mock.patch.object(identity, "canonical_plugin_package_digest",
                               wraps=identity.canonical_plugin_package_digest) as digest:
            self.assertEqual(identity.plugin_cache_identity_issues(
                source_root=source, cache_root=cache), [])
        self.assertEqual([call.args[0] for call in digest.call_args_list], [source, cache])

    def test_failed_validation_never_exports_source_identity(self) -> None:
        output = {"old": object()}
        source = self.sources["alpha"] / "skills/one/SKILL.md"
        source.write_bytes(source.read_bytes() + b"changed\n")
        self.assertTrue(identity.repository_identity_issues(
            self.fixture.repo, _validated_identities=output))
        self.assertEqual(output, {})

    def apply(self) -> None:
        refresh.apply_codex_harness(
            self.fixture.catalog, codex="codex", codex_home=self.fixture.codex_home,
            marketplace_name=self.marketplace, excluded_skill_roots=(),
            marketplace_source_binding=refresh.MarketplaceSourceBinding(
                "local", str(self.fixture.repo)), env={}, dry_run=False,
        )

    def test_activation_reads_one_baseline_and_fresh_closure(self) -> None:
        with mock.patch.object(refresh, "read_codex_plugin_rows",
                               side_effect=self.fixture.rows) as rows:
            self.apply()
        self.assertEqual(rows.call_count, 2)

    def test_activation_does_not_reuse_baseline_after_add(self) -> None:
        self.fixture.enabled.clear()
        observed = []

        def rows(*args, **kwargs):
            observed.append(set(self.fixture.enabled))
            return self.fixture.rows(*args, **kwargs)

        def add(codex, selector, *, env, dry_run, **kwargs):
            return self.fixture.run([codex, "plugin", "add", selector], env=env,
                                    dry_run=dry_run)

        with mock.patch.object(refresh, "read_codex_plugin_rows", side_effect=rows), \
                mock.patch.object(refresh, "add_codex_plugin", side_effect=add):
            self.apply()
        self.assertEqual(observed, [set(), {"alpha", "beta"}])

    def test_source_changed_during_add_fails_fresh_closure(self) -> None:
        self.fixture.enabled.clear()

        def add(codex, selector, *, env, dry_run, **kwargs):
            result = self.fixture.run([codex, "plugin", "add", selector], env=env,
                                      dry_run=dry_run)
            if selector.startswith("beta@"):
                source = self.sources["alpha"] / "skills/one/SKILL.md"
                source.write_bytes(source.read_bytes() + b"changed during add\n")
            return result

        with mock.patch.object(refresh, "read_codex_plugin_rows", side_effect=self.fixture.rows), \
                mock.patch.object(refresh, "add_codex_plugin", side_effect=add), \
                mock.patch.object(refresh, "run", side_effect=self.fixture.run):
            with self.assertRaisesRegex(SystemExit, "source content identity requires version"):
                self.apply()
        self.assertEqual(self.fixture.enabled, set())


class CommandPhaseSelectionTests(unittest.TestCase):
    def test_check_uses_one_source_validation_route_even_when_listing_fails(self) -> None:
        for rows in ({}, None):
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(check_harness, "resolve_codex_executable", return_value="codex"), \
                    mock.patch.object(check_harness, "CheckRunner", autospec=True) as runner_type, \
                    mock.patch.object(sys, "argv", ["check_harness.py", "--codex-home", tmp]):
                runner = runner_type.return_value
                runner.read_plugin_rows.return_value = rows
                runner.check_marketplace_file.return_value = {}
                check_harness.main()
                self.assertEqual(runner.check_plugin_packages.call_count, int(rows is None))
                self.assertEqual(runner.check_codex_harness.call_count, int(rows is not None))

    def test_default_refresh_does_not_lookup_remote_but_explicit_ref_does(self) -> None:
        for explicit in (False, True):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as tmp:
                arguments = ["refresh_harness.py", "--codex-home", tmp, "--dry-run",
                             "--skip-bootstrap", "--skip-agents", "--skip-hooks", "--skip-doctor"]
                if explicit:
                    arguments += ["--git-ref", "main"]
                with mock.patch.object(sys, "argv", arguments), \
                        mock.patch.object(refresh, "require_excluded_skill_roots_clear"), \
                        mock.patch.object(refresh, "prepare_instruction_sync"), \
                        mock.patch.object(refresh, "preflight_codex_distribution"), \
                        mock.patch.object(refresh, "resolve_codex_executable", return_value="codex"), \
                        mock.patch.object(refresh, "require_codex_plugin_commands"), \
                        mock.patch.object(refresh, "_enabled_codex_harness_plugins", return_value=set()), \
                        mock.patch.object(refresh, "git_remote_source", return_value="git@example/repo.git") as remote, \
                        mock.patch.object(refresh, "ensure_marketplace_source", side_effect=SystemExit("captured")) as ensure:
                    with self.assertRaisesRegex(SystemExit, "captured"):
                        refresh.main()
                self.assertEqual(remote.call_count, int(explicit))
                self.assertEqual(ensure.call_args.kwargs["git_request_explicit"], explicit)
                self.assertEqual(ensure.call_args.kwargs["git_source"],
                                 "git@example/repo.git" if explicit else None)


if __name__ == "__main__":
    unittest.main()
