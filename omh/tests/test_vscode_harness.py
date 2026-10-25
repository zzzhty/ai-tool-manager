from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import manager_state
import remove_harness
from harness_registry import load_harness_registry, resolve_harness_plan, HarnessRegistryError
from repo_skill_catalog import load_repo_skill_catalog
from sync_agents_skills import create_projection_link, remove_projection_link


class VSCodeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = Path(self.tmp.name)
        self.home = self.user / 'manager'
        self.env = {**os.environ, 'HOME': str(self.user), 'USERPROFILE': str(self.user)}
        self.env.pop('COPILOT_HOME', None)
        self.patch = mock.patch.dict(os.environ, self.env, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.registry = load_harness_registry()

    def plan(self, name):
        return resolve_harness_plan(self.registry, name, repo_root=ROOT)

    def install(self, *names):
        self.home.joinpath('state').mkdir(parents=True, exist_ok=True)
        manager_state.atomic_write_json(manager_state.desired_file(self.home), {
            'schemaVersion': manager_state.STATE_SCHEMA_VERSION,
            'harnesses': sorted(names), 'updatePolicy': {'channel': 'main'},
        })
        for name in names:
            plan = self.plan(name)
            plan.skills_root.mkdir(parents=True, exist_ok=True)
            for skill in load_repo_skill_catalog().sources[:1]:
                target = plan.skills_root / skill.name
                if not target.exists():
                    create_projection_link(target, skill.path)
            plan.instructions_target.write_bytes(plan.instructions_source.read_bytes())
            manager_state.write_harness_receipt(
                self.home, harness=name, manager_revision='a'*40,
                release_version='1.0.0', bundle_identity='fixture', root=str(plan.root))

    def remove(self, name, *, dry=False, preview=()):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            remove_harness.remove_harness(
                name, registry_path=self.registry.path, home=self.home,
                codex_home=None, codex_path=None, tooling_python=Path(sys.executable),
                dry_run=dry, assume_yes=True, preview_removed=preview)
        return output.getvalue()

    def test_identity_default_paths_and_override_are_independent(self):
        self.assertNotEqual(self.plan('vscode').harness_id, self.plan('copilot-cli').harness_id)
        self.assertEqual(self.plan('vscode').root, self.plan('copilot').root)
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / 'cli')}):
            self.assertEqual(self.plan('vscode').root, self.user / '.copilot')
            self.assertEqual(self.plan('copilot').root, self.user / 'cli')
        with self.assertRaisesRegex(HarnessRegistryError, 'cannot represent'):
            self.registry.id_for_target('vscode', ['copilot', 'codex'])

    def test_shared_then_last_consumer_removal_both_orders(self):
        for first, second in [('vscode', 'copilot'), ('copilot', 'vscode')]:
            with self.subTest(first=first):
                self.install(first, second)
                plan = self.plan(first)
                self.assertIn('retain shared', self.remove(first))
                self.assertTrue(plan.instructions_target.exists())
                self.assertTrue(any(plan.skills_root.iterdir()))
                manager_state.write_desired(self.home, [second])
                manager_state.remove_harness_receipt(self.home, first)
                self.remove(second)
                self.assertFalse(plan.instructions_target.exists())
                self.assertFalse(any(plan.skills_root.iterdir()))

    def test_dry_run_bulk_simulates_last_consumer_without_writes(self):
        self.install('vscode', 'copilot')
        before = manager_state.desired_file(self.home).read_bytes()
        self.assertIn('retain shared', self.remove('vscode', dry=True))
        output = self.remove('copilot', dry=True, preview=('vscode',))
        self.assertNotIn('retain shared', output)
        self.assertIn('would remove', output)
        self.assertEqual(before, manager_state.desired_file(self.home).read_bytes())
        self.assertTrue(self.plan('vscode').instructions_target.exists())
        with self.assertRaisesRegex(SystemExit, 'only valid'):
            self.remove('copilot', preview=('vscode',))

    def test_separate_roots_remove_only_selected(self):
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / 'cli')}):
            self.install('vscode', 'copilot')
            self.remove('vscode')
            self.assertFalse(self.plan('vscode').instructions_target.exists())
            self.assertTrue(self.plan('copilot').instructions_target.exists())

    def test_changed_shared_instructions_preserved_and_state_not_removed(self):
        self.install('vscode', 'copilot')
        plan = self.plan('vscode')
        plan.instructions_target.write_text('user edit')
        with self.assertRaisesRegex(SystemExit, 'changed or unmanaged'):
            self.remove('vscode')
        self.assertEqual(plan.instructions_target.read_text(), 'user edit')
        self.assertTrue(any(plan.skills_root.iterdir()))

    def test_changed_shared_skills_fail_before_mutation(self):
        self.install('vscode', 'copilot')
        target = next(self.plan('vscode').skills_root.iterdir())
        remove_projection_link(target, load_repo_skill_catalog(), expected_destination=target.resolve())
        target.mkdir()
        target.joinpath('user').write_text('keep')
        with self.assertRaises(SystemExit):
            self.remove('copilot')
        self.assertTrue(self.plan('copilot').instructions_target.exists())

    def test_receipt_root_drift_fails_even_if_environment_now_shares(self):
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / 'cli')}):
            self.install('copilot')
        self.install('vscode')
        manager_state.write_desired(self.home, ['vscode', 'copilot'])
        with self.assertRaisesRegex(SystemExit, 'recorded root'):
            self.remove('vscode')
        self.assertTrue(self.plan('vscode').instructions_target.exists())

    def test_missing_consumer_receipt_fails_safe(self):
        self.install('vscode', 'copilot')
        manager_state.harness_file(self.home, 'copilot-cli').unlink()
        with self.assertRaisesRegex(SystemExit, 'no receipt'):
            self.remove('vscode')

    def test_legacy_alias_receipt_retains_shared_resources_in_both_removal_orders(self):
        for first, second in [('vscode', 'copilot'), ('copilot', 'vscode')]:
            with self.subTest(first=first):
                self.install('vscode', 'copilot-cli')
                path = manager_state.harness_file(self.home, 'copilot-cli')
                payload = json.loads(path.read_text())
                payload['harness'] = 'copilot'
                path.rename(manager_state.harness_file(self.home, 'copilot'))
                manager_state.harness_file(self.home, 'copilot').write_text(json.dumps(payload))
                manager_state.write_desired(self.home, ['vscode', 'copilot'], canonicalize=False)
                plan = self.plan(first)
                self.assertIn('retain shared', self.remove(first))
                self.assertTrue(plan.instructions_target.exists())
                self.assertTrue(any(plan.skills_root.iterdir()))
                manager_state.remove_harness_receipt(self.home, first)
                manager_state.write_desired(self.home, [second], canonicalize=False)
                self.remove(second)
                manager_state.remove_harness_receipt(self.home, second)
                self.assertFalse(plan.instructions_target.exists())
                self.assertFalse(any(plan.skills_root.iterdir()))
                self.assertFalse(manager_state.harness_file(self.home, 'copilot').exists())
                self.assertFalse(manager_state.harness_file(self.home, 'copilot-cli').exists())

    def test_resource_matching_is_per_path_not_whole_root(self):
        self.install('vscode', 'copilot')
        from dataclasses import replace
        plan = self.plan('vscode')
        other = replace(self.plan('copilot'), instructions_target=self.user / 'other.md')
        with mock.patch.object(remove_harness, 'resolve_harness_plan', side_effect=lambda reg, name, **kw: other if name == 'copilot-cli' else plan):
            self.assertEqual(remove_harness.shared_resources(plan, registry=self.registry,
                home=self.home, environment=dict(os.environ)), (True, False))

    def test_legacy_codex_override_receipt_does_not_block_removal(self):
        self.install()
        manager_state.write_desired(self.home, ['codex'])
        manager_state.write_harness_receipt(self.home, harness='codex',
            manager_revision='a'*40, release_version='1.0.0', bundle_identity='fixture',
            root=str(self.user / '.codex'))
        custom = self.user / 'custom-codex'
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(custom)}):
            plan = self.plan('codex')
            self.assertEqual(remove_harness.shared_resources(plan, registry=self.registry,
                home=self.home, environment=dict(os.environ)), (False, False))

    def test_unrelated_missing_or_drifted_receipts_do_not_block_removal(self):
        self.install('vscode')
        manager_state.write_desired(self.home, ['codex', 'vscode'])
        self.remove('vscode')
        self.install('vscode', 'copilot')
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / 'unrelated')}):
            # Both recorded/current CLI roots are disjoint from a third harness.
            self.install('zcode')
            manager_state.write_desired(self.home, ['copilot', 'zcode'])
            self.remove('zcode')

    def test_recorded_shared_root_still_protects_after_environment_drift(self):
        self.install('vscode', 'copilot')
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / 'new-cli')}):
            with self.assertRaisesRegex(SystemExit, 'recorded root'):
                self.remove('vscode')
        self.assertTrue(self.plan('vscode').instructions_target.exists())

    def test_recorded_root_alias_cannot_hide_shared_resources_after_drift(self):
        self.install('vscode')
        alias = self.user / 'cli-alias'
        create_projection_link(alias, self.user / '.copilot')
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(alias)}):
            self.install('copilot', 'vscode')
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / 'new-cli')}):
            with self.assertRaisesRegex(SystemExit, 'recorded root'):
                self.remove('vscode')
        self.assertTrue(self.plan('vscode').instructions_target.exists())

    def test_remaining_codex_recorded_overlap_blocks_root_drift(self):
        self.install('zcode')
        manager_state.write_desired(self.home, ['codex', 'zcode'])
        manager_state.write_harness_receipt(self.home, harness='codex',
            manager_revision='a'*40, release_version='1.0.0', bundle_identity='fixture',
            root=str(self.plan('zcode').root))
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(self.user / 'new-codex')}):
            with self.assertRaisesRegex(SystemExit, 'recorded root for codex'):
                self.remove('zcode')
        self.assertTrue(self.plan('zcode').instructions_target.exists())

    def test_disjoint_invalid_gemini_settings_do_not_block_removal(self):
        self.install('gemini', 'vscode')
        gemini = self.plan('gemini')
        gemini.root.joinpath('settings.json').write_text(json.dumps({
            'context': {'fileName': ['GEMINI.md', 'OTHER.md']}}))
        self.remove('vscode')
        self.assertFalse(self.plan('vscode').instructions_target.exists())
        self.assertTrue(gemini.instructions_target.exists())

    def test_overlapping_invalid_gemini_settings_still_block_removal(self):
        self.install('gemini', 'vscode')
        gemini = self.plan('gemini')
        gemini.root.joinpath('settings.json').write_text(json.dumps({
            'context': {'fileName': ['GEMINI.md', 'OTHER.md']}}))
        manager_state.write_harness_receipt(self.home, harness='gemini',
            manager_revision='a'*40, release_version='1.0.0', bundle_identity='fixture',
            root=str(self.plan('vscode').root))
        with self.assertRaises(HarnessRegistryError):
            self.remove('vscode')
        self.assertTrue(self.plan('vscode').instructions_target.exists())

    def test_current_gemini_root_drift_into_target_does_not_ignore_settings_error(self):
        new_home = self.user / 'new-home'
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(new_home / '.gemini')}):
            self.install('gemini', 'copilot')
            self.plan('copilot').root.joinpath('settings.json').write_text(json.dumps({
                'context': {'fileName': ['GEMINI.md', 'OTHER.md']}}))
            with mock.patch.dict(os.environ, {'GEMINI_CLI_HOME': str(new_home)}):
                with self.assertRaises(HarnessRegistryError):
                    self.remove('copilot')
            self.assertTrue(self.plan('copilot').instructions_target.exists())

    def test_valid_dynamic_parent_alias_still_preserves_shared_instructions(self):
        self.install('gemini', 'vscode')
        gemini = self.plan('gemini')
        create_projection_link(gemini.root / 'linked', self.plan('vscode').root)
        gemini.root.joinpath('settings.json').write_text(json.dumps({
            'context': {'fileName': 'linked/copilot-instructions.md'}}))
        self.assertIn('retain shared instructions', self.remove('vscode'))
        self.assertTrue(self.plan('vscode').instructions_target.exists())

    def test_bulk_preview_skips_already_removed_legacy_codex_consumer(self):
        self.install('zcode')
        manager_state.write_desired(self.home, ['codex', 'zcode'])
        manager_state.write_harness_receipt(self.home, harness='codex',
            manager_revision='a'*40, release_version='1.0.0', bundle_identity='fixture',
            root=str(self.plan('zcode').root))
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(self.user / 'new-codex')}):
            output = self.remove('zcode', dry=True, preview=('codex',))
            self.assertIn('would remove', output)
            self.assertNotIn('retain shared', output)
        self.assertTrue(self.plan('zcode').instructions_target.exists())

    def test_multi_target_parent_alias_preserves_previously_shared_instructions(self):
        self.install('gemini', 'zcode')
        gemini = self.plan('gemini')
        create_projection_link(gemini.root / 'linked', self.plan('zcode').root)
        settings = gemini.root / 'settings.json'
        settings.write_text(json.dumps({'context': {'fileName': 'linked/AGENTS.md'}}))
        self.assertEqual(self.plan('gemini').instructions_target.resolve(), self.plan('zcode').instructions_target.resolve())
        settings.write_text(json.dumps({'context': {'fileName': ['linked/AGENTS.md', 'OTHER.md']}}))
        self.assertIn('retain instructions', self.remove('zcode'))
        self.assertTrue(self.plan('zcode').instructions_target.exists())
        self.assertFalse(any(self.plan('zcode').skills_root.iterdir()))

    def test_unreadable_dynamic_targets_preserve_instructions_without_blocking_skills(self):
        self.install('gemini', 'vscode')
        self.plan('gemini').root.joinpath('settings.json').write_text('{invalid json')
        self.assertIn('cannot be determined', self.remove('vscode'))
        self.assertTrue(self.plan('vscode').instructions_target.exists())
        self.assertFalse(any(self.plan('vscode').skills_root.iterdir()))

    def test_changed_dynamic_root_preserves_unknown_recorded_alias_target(self):
        self.install('gemini', 'zcode')
        gemini = self.plan('gemini')
        create_projection_link(gemini.root / 'linked', self.plan('zcode').root)
        gemini.root.joinpath('settings.json').write_text(json.dumps({
            'context': {'fileName': 'linked/AGENTS.md'}}))
        with mock.patch.dict(os.environ, {'GEMINI_CLI_HOME': str(self.user / 'new-home')}):
            self.assertIn('recorded dynamic root has changed', self.remove('zcode'))
        self.assertTrue(self.plan('zcode').instructions_target.exists())
        self.assertFalse(any(self.plan('zcode').skills_root.iterdir()))

    def test_install_refresh_repair_receipts_use_explicit_codex_home(self):
        import omh
        import install_oh_my_harness as installer
        self.install('zcode')
        custom_root = self.plan('zcode').root
        manager = dict(repository='origin', revision='a'*40, releaseVersion='1.0.0',
                       bundleIdentity='fixture', channel='main')
        for command in ('install', 'refresh', 'repair'):
            with self.subTest(command=command):
                # Give refresh/repair an old, incorrectly recorded receipt to
                # prove an authorized reapplication writes its effective root.
                if command != 'install':
                    manager_state.write_harness_receipt(self.home, harness='codex',
                        manager_revision='a'*40, release_version='1.0.0', bundle_identity='fixture',
                        root=str(self.user / '.codex'))
                desired = json.loads(manager_state.desired_file(self.home).read_text())
                args = omh.build_parser().parse_args(['--home', str(self.home), command,
                    'codex', '--codex-home', str(custom_root), '--yes'])
                with mock.patch.object(omh, '_state_context', return_value=(manager, desired)), \
                     mock.patch.object(omh, '_refresh_one') as refresh, \
                     mock.patch.object(omh, '_bootstrap_tooling'), \
                     mock.patch.object(installer, 'write_launchers'), \
                     mock.patch.object(omh, 'ensure_user_path'), \
                     mock.patch.object(omh, 'write_manager'):
                    args.func(args)
                self.assertEqual(refresh.call_args.args[0].codex_home, str(custom_root))
                receipt = json.loads(manager_state.harness_file(self.home, 'codex').read_text())
                self.assertEqual(Path(receipt['root']), custom_root)
                # A later command omitting the override cannot silently delete
                # the file that the explicit Codex installation actually used.
                with self.assertRaisesRegex(SystemExit, 'recorded root for codex'):
                    self.remove('zcode')
                self.assertTrue(self.plan('zcode').instructions_target.exists())

    def test_receipt_override_matches_materialization_path_expansion(self):
        import omh
        import refresh_harness
        self.install()
        expected = self.user / '.zcode'
        with mock.patch.dict(os.environ, {'OMH_FIXTURE_CODEX': str(expected), 'OMH_FIXTURE_SUBDIR': '.zcode'}):
            for value in ('$OMH_FIXTURE_CODEX', str(self.user / '$OMH_FIXTURE_SUBDIR'), '~/.zcode'):
                with self.subTest(value=value):
                    self.assertEqual(refresh_harness.expand_path(value), expected)
                    omh._write_harness_state(self.home, 'codex', codex_home=value)
                    receipt = json.loads(manager_state.harness_file(self.home, 'codex').read_text())
                    self.assertEqual(Path(receipt['root']), expected)

    def custom_registry(self):
        import copy
        payload = json.loads(self.registry.path.read_text())
        custom = copy.deepcopy(payload['harnesses']['vscode'])
        custom['displayName'] = 'Fixture Editor'
        custom['aliases'] = ['editor-old']
        payload['harnesses']['editor-x'] = custom
        path = self.user / 'custom-registry.json'
        path.write_text(json.dumps(payload))
        return load_harness_registry(path, repo_root=ROOT)

    def test_custom_registry_unknown_default_id_can_remove_without_state(self):
        self.registry = self.custom_registry()
        plan = self.plan('editor-x')
        plan.skills_root.mkdir(parents=True)
        plan.instructions_target.write_bytes(plan.instructions_source.read_bytes())
        self.remove('editor-old')
        self.assertFalse(plan.instructions_target.exists())

    def test_custom_registry_alias_consumers_and_receipts_protect_shared_files(self):
        self.install('vscode')
        self.registry = self.custom_registry()
        desired = json.loads(manager_state.desired_file(self.home).read_text())
        desired['harnesses'] = ['editor-old', 'vscode']
        manager_state.atomic_write_json(manager_state.desired_file(self.home), desired)
        manager_state.atomic_write_json(manager_state.harness_file(self.home, 'editor-old'), {
            'schemaVersion': manager_state.STATE_SCHEMA_VERSION, 'harness': 'editor-old',
            'status': 'ready', 'root': str(self.plan('editor-x').root),
        })
        self.assertEqual(manager_state.removal_consumers(self.home, registry=self.registry), ('editor-x', 'vscode'))
        self.assertIn('retain shared', self.remove('vscode'))
        self.assertTrue(self.plan('vscode').instructions_target.exists())

    def test_custom_registry_still_validates_receipt_identity(self):
        self.registry = self.custom_registry()
        manager_state.atomic_write_json(manager_state.harness_file(self.home, 'editor-x'), {
            'schemaVersion': manager_state.STATE_SCHEMA_VERSION, 'harness': 'wrong-editor',
            'status': 'ready', 'root': str(self.plan('editor-x').root),
        })
        with self.assertRaisesRegex(SystemExit, 'receipt identity is invalid'):
            self.remove('editor-x')

    def test_case_insensitive_parent_identity_simulation_retains_shared_files(self):
        # Linux CI cannot create native APFS case aliases. Simulate only the
        # samefile answers for one case-variant directory; leave path spelling
        # untouched so the old POSIX normcase comparison would miss the share.
        self.install('vscode', 'copilot')
        alias = self.user / '.CoPiLoT'
        original_samefile = os.path.samefile
        def case_alias(left, right):
            def actual(path):
                return Path(str(path).replace('.CoPiLoT', '.copilot'))
            return original_samefile(actual(left), actual(right))
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(alias)}), \
             mock.patch.object(os.path, 'samefile', side_effect=case_alias):
            self.assertIn('retain shared', self.remove('vscode'))
        self.assertTrue(self.plan('vscode').instructions_target.exists())
        self.assertTrue(any(self.plan('vscode').skills_root.iterdir()))

    def test_native_case_insensitive_alias_lifecycle(self):
        self.install('vscode', 'copilot')
        alias = self.user / '.CoPiLoT'
        if not alias.is_dir():
            self.skipTest('temporary filesystem is case-sensitive; native alias exercised on macOS/Windows CI')
        target = self.plan('vscode').instructions_target
        self.assertTrue(remove_harness._same_resource(target, target.with_name(target.name.upper())))
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(alias)}):
            self.assertIn('retain shared', self.remove('vscode'))
            manager_state.write_desired(self.home, ['copilot'])
            manager_state.remove_harness_receipt(self.home, 'vscode')
            self.remove('copilot')
        self.assertFalse(self.plan('vscode').instructions_target.exists())
        self.assertFalse(any(self.plan('vscode').skills_root.iterdir()))

    def test_case_sensitive_distinct_directories_are_not_shared(self):
        first, second = self.user / 'CaseSensitive', self.user / 'casesensitive'
        first.mkdir()
        if second.exists():
            self.skipTest('temporary filesystem is case-insensitive')
        second.mkdir()
        for root in (first, second):
            root.joinpath('instructions.md').write_text('same bytes')
        self.assertFalse(remove_harness._same_directory(first, second))
        self.assertFalse(remove_harness._same_resource(first / 'instructions.md', second / 'instructions.md'))

    def test_distinct_final_symlinks_to_one_source_are_not_one_resource(self):
        source = self.user / 'source.md'
        source.write_text('instructions')
        first, second = self.user / 'one', self.user / 'two'
        first.mkdir(); second.mkdir()
        try:
            (first / 'AGENTS.md').symlink_to(source)
            (second / 'AGENTS.md').symlink_to(source)
            (first / 'OTHER.md').symlink_to(source)
        except OSError:
            self.skipTest('file symlinks unavailable on this test host')
        self.assertTrue(os.path.samefile(first / 'AGENTS.md', second / 'AGENTS.md'))
        self.assertFalse(remove_harness._same_resource(first / 'AGENTS.md', second / 'AGENTS.md'))
        self.assertFalse(remove_harness._same_resource(first / 'AGENTS.md', first / 'OTHER.md'))

    def test_public_install_records_two_identities_and_refreshes_them(self):
        import omh
        self.install()
        desired = json.loads(manager_state.desired_file(self.home).read_text())
        args = omh.build_parser().parse_args(['--home', str(self.home), 'install', 'vscode', 'copilot-cli', '--yes'])
        with mock.patch.object(omh, '_state_context', return_value=({}, desired)), \
             mock.patch.object(omh, '_refresh_one') as refresh:
            omh.command_install(args)
        self.assertEqual([call.kwargs['harness'] for call in refresh.call_args_list], ['vscode', 'copilot-cli'])
        desired = json.loads(manager_state.desired_file(self.home).read_text())
        self.assertEqual(desired['harnesses'], ['copilot-cli', 'vscode'])
        for name in desired['harnesses']:
            self.assertEqual(json.loads(manager_state.harness_file(self.home, name).read_text())['harness'], name)
        args = omh.build_parser().parse_args(['--home', str(self.home), 'refresh', '--all', '--yes'])
        with mock.patch.object(omh, '_state_context', return_value=({}, desired)), \
             mock.patch.object(omh, '_refresh_one') as refresh:
            omh.command_refresh(args)
        self.assertEqual([call.kwargs['harness'] for call in refresh.call_args_list], ['copilot-cli', 'vscode'])

    def test_public_remove_all_and_dry_run_use_shared_lifecycle(self):
        import omh
        for dry in (True, False):
            with self.subTest(dry=dry):
                self.install('copilot', 'vscode')
                desired = json.loads(manager_state.desired_file(self.home).read_text())
                args = omh.build_parser().parse_args(['--home', str(self.home), 'remove', '--all', '--yes'] + (['--dry-run'] if dry else []))
                with mock.patch.object(omh, '_state_context', return_value=({}, desired)):
                    omh.command_remove(args)
                after = json.loads(manager_state.desired_file(self.home).read_text())
                self.assertEqual(after['harnesses'], ['copilot', 'vscode'] if dry else [])
                self.assertEqual(self.plan('vscode').instructions_target.exists(), dry)

    def test_manager_uninstall_removes_last_consumer(self):
        import omh
        self.install('copilot', 'vscode')
        desired = json.loads(manager_state.desired_file(self.home).read_text())
        args = omh.build_parser().parse_args(['--home', str(self.home), 'manager', 'uninstall', '--with-harnesses', '--yes'])
        with mock.patch.object(omh, '_state_context', return_value=({}, desired)), \
             mock.patch.object(omh, 'ensure_user_path'), \
             mock.patch.object(omh, '_schedule_self_delete') as delete:
            omh.command_manager_uninstall(args)
        delete.assert_called_once()
        self.assertFalse(self.plan('vscode').instructions_target.exists())
        self.assertEqual(json.loads(manager_state.desired_file(self.home).read_text())['harnesses'], [])

    def test_path_normalization_preserves_shared_resources(self):
        self.install('vscode', 'copilot')
        with mock.patch.dict(os.environ, {'COPILOT_HOME': str(self.user / '.copilot' / '..' / '.copilot')}):
            self.assertIn('retain shared', self.remove('vscode'))


if __name__ == '__main__':
    unittest.main()
