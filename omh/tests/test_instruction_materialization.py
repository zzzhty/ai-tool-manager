from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import omh
import refresh_harness as refresh
import sync_harness_instructions as instructions
from harness_registry import load_harness_registry, resolve_harness_plan


class InstructionMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'core.autocrlf', 'true')
        self.git('config', 'core.safecrlf', 'false')
        registry = self.repo / '.agents/harnesses/registry.json'
        registry.parent.mkdir(parents=True)
        payload = json.loads((ROOT / '.agents/harnesses/registry.json').read_text())
        payload['sources']['instructions'] = {
            'current': 'AGENTS.md', 'migration': {
                'id': omh.INSTRUCTIONS_MIGRATION_ID, 'stage': 'bridge-ready',
                'peer': 'agents/global-instructions.md',
            },
        }
        registry.write_text(json.dumps(payload))
        self.registry_peer = self.repo / 'agents/global-instructions.md'
        self.registry_peer.parent.mkdir()
        self.source = self.repo / 'AGENTS.md'
        self.source.write_bytes(b'old instructions\nsecond line\n')
        self.registry_peer.write_bytes(self.source.read_bytes())
        self.git('add', '.')
        self.git('commit', '-qm', 'old')
        self.old = self.git('rev-parse', 'HEAD').strip().decode()
        self.source.write_bytes(b'new instructions\nsecond line\n')
        self.registry_peer.write_bytes(self.source.read_bytes())
        self.git('add', '.')
        self.git('commit', '-qm', 'new')
        self.new = self.git('rev-parse', 'HEAD').strip().decode()
        self.git('checkout', '-q', self.old)
        plan = resolve_harness_plan(load_harness_registry(), 'zcode', user_home=self.root/'user', os_name='posix')
        peer = self.root / 'peer.md'
        peer.write_bytes(b'unrelated peer\n')
        self.plan = replace(plan, instructions_source=self.source, instructions_migration=replace(plan.instructions_migration, peer_source=peer))
        self.plan.instructions_target.parent.mkdir(parents=True)
        self.plan.instructions_target.write_bytes(self.source.read_bytes())

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.PIPE)

    def journal(self):
        return {'operationId': 'test-op', 'command': 'update', 'phase': 'degraded',
                'before': {'revision': self.old, 'desiredHarnesses': ['zcode'], 'instructionsSource': omh._instruction_source_at_revision(self.repo, self.old)},
                'target': {'revision': self.new, 'instructionsSource': omh._instruction_source_at_revision(self.repo, self.new)}}

    def enrich(self, operation):
        def update(_home, **fields):
            operation.update(fields)
            return operation
        with mock.patch.object(omh, 'REPO_ROOT', self.repo), mock.patch.object(omh, 'update_operation', side_effect=update):
            return omh._journal_instruction_transition(self.root, operation)

    def sync(self, operation, *, approve=False):
        with mock.patch.object(refresh, 'REPO_ROOT', self.repo), mock.patch.object(refresh, 'load_current_operation', return_value=operation):
            digests = refresh.operation_instruction_digests(self.root, 'test-op')
        prepared = instructions.prepare_instruction_sync(self.plan, dry_run=False, assume_yes=True, operation_managed_digests=digests, input_fn=lambda _: 'yes' if approve else 'no', output=lambda _: None)
        instructions.apply_instruction_sync(prepared, dry_run=False)
        return prepared

    def test_real_autocrlf_update_and_recovery_rollback(self):
        self.assertIn(b'\r\n', self.source.read_bytes())
        operation = self.enrich(self.journal())
        self.git('checkout', '-q', self.new)
        self.assertEqual(self.sync(operation).provenance, 'operation-journal')
        self.assertEqual(self.plan.instructions_target.read_bytes(), self.source.read_bytes())
        self.git('checkout', '-q', self.old)
        operation = self.enrich(operation)
        self.assertEqual(self.sync(operation).provenance, 'operation-journal')
        self.assertEqual(self.plan.instructions_target.read_bytes(), self.source.read_bytes())

    def test_user_edits_including_eol_only_remain_unmanaged(self):
        operation = self.enrich(self.journal())
        old_bytes = self.plan.instructions_target.read_bytes()
        self.git('checkout', '-q', self.new)
        for edited in (old_bytes + b'user change\r\n', old_bytes.replace(b'\r\n', b'\n')):
            with self.subTest(edited=edited):
                self.plan.instructions_target.write_bytes(edited)
                with self.assertRaisesRegex(SystemExit, 'was not confirmed'):
                    self.sync(operation)
                self.assertEqual(self.plan.instructions_target.read_bytes(), edited)

    def test_old_updater_journal_keeps_immutable_source_records(self):
        operation = self.journal()
        original = json.loads(json.dumps(operation))
        self.git('checkout', '-q', self.new)
        self.enrich(operation)
        for side in ('before', 'target'):
            self.assertEqual(operation[side]['instructionsSource'], original[side]['instructionsSource'])
            self.assertNotEqual(operation[side]['instructionsMaterializedSha256'], original[side]['instructionsSource']['sha256'])
        self.sync(operation)

    def test_recorded_evidence_cannot_be_rebaselined(self):
        operation = self.enrich(self.journal())
        operation['before']['instructionsMaterializedSha256'] = '0' * 64
        with self.assertRaisesRegex(SystemExit, 'materialization changed'):
            self.enrich(operation)

    def bridge(self, operation):
        with (
            mock.patch.object(omh, 'REPO_ROOT', self.repo),
            mock.patch.object(omh, '_resolve_plan', return_value=self.plan),
            mock.patch.object(omh, 'update_operation', side_effect=lambda _home, **fields: {**operation, **fields}),
            mock.patch.dict(os.environ, {'HOME': str(self.root / 'user'), 'USERPROFILE': str(self.root / 'user')}),
        ):
            omh._restore_update_instruction_copies(self.root, operation)

    def test_failed_resume_restores_copy_for_old_rollback_and_preserves_original_error(self):
        operation = self.enrich(self.journal())
        old_bytes = self.source.read_bytes()
        self.git('checkout', '-q', self.new)
        def fail(*_args):
            self.sync(operation)
            raise RuntimeError('original plugin failure')
        with (
            mock.patch.object(omh, 'REPO_ROOT', self.repo),
            mock.patch.object(omh, 'load_current_operation', return_value=operation),
            mock.patch.object(omh, 'update_operation', side_effect=lambda _home, **fields: {**operation, **fields}),
            mock.patch.object(omh, '_distribution', return_value=('release', 'bundle')),
            mock.patch.object(omh, '_complete_resumed_update', side_effect=fail),
            mock.patch.object(omh, '_resolve_plan', return_value=self.plan),
            mock.patch.dict(os.environ, {'HOME': str(self.root / 'user'), 'USERPROFILE': str(self.root / 'user')}),
        ):
            operation['target'].update(releaseVersion='release', bundleIdentity='bundle')
            with self.assertRaisesRegex(RuntimeError, 'original plugin failure'):
                omh.command_resume_update(argparse.Namespace(home=str(self.root), operation_id='test-op'))
        self.assertEqual(self.plan.instructions_target.read_bytes(), old_bytes)
        self.git('checkout', '-q', self.old)
        # The old rollback's ordinary exact-source check now closes without
        # knowing the new journal field or normalizing either file.
        self.assertEqual(instructions.check_instruction_sync(self.plan), [])

    def test_failed_resume_reports_original_and_restoration_errors(self):
        operation = self.enrich(self.journal())
        self.git('checkout', '-q', self.new)
        operation['target'].update(releaseVersion='release', bundleIdentity='bundle')
        with (
            mock.patch.object(omh, 'REPO_ROOT', self.repo),
            mock.patch.object(omh, 'load_current_operation', return_value=operation),
            mock.patch.object(omh, 'update_operation', side_effect=lambda _home, **fields: {**operation, **fields}),
            mock.patch.object(omh, '_distribution', return_value=('release', 'bundle')),
            mock.patch.object(omh, '_complete_resumed_update', side_effect=RuntimeError('original plugin failure')),
            mock.patch.object(omh, '_restore_update_instruction_copies', side_effect=SystemExit('user edit preserved')),
            self.assertRaisesRegex(RuntimeError, 'original plugin failure; instruction copy restoration failed: user edit preserved'),
        ):
            omh.command_resume_update(argparse.Namespace(home=str(self.root), operation_id='test-op'))

    def test_new_recover_restores_copy_before_entering_old_executable(self):
        operation = self.enrich(self.journal())
        old_bytes = self.source.read_bytes()
        self.git('checkout', '-q', self.new)
        self.sync(operation)
        def old_rollback(_repo, _home, command, *args):
            self.assertEqual(command, '_resume-rollback')
            self.assertEqual(self.git('rev-parse', 'HEAD').strip().decode(), self.old)
            self.assertEqual(self.plan.instructions_target.read_bytes(), old_bytes)
            self.assertEqual(instructions.check_instruction_sync(self.plan), [])
            return subprocess.CompletedProcess([], 0)
        with (
            mock.patch.object(omh, 'REPO_ROOT', self.repo),
            mock.patch.object(omh, 'load_current_operation', return_value=operation),
            mock.patch.object(omh, 'update_operation', side_effect=lambda _home, **fields: {**operation, **fields}),
            mock.patch.object(omh, '_resolve_plan', return_value=self.plan),
            mock.patch.object(omh, '_bootstrap_tooling'),
            mock.patch.object(omh, '_invoke_internal', side_effect=old_rollback),
            mock.patch.dict(os.environ, {'HOME': str(self.root / 'user'), 'USERPROFILE': str(self.root / 'user')}),
        ):
            self.assertEqual(omh.command_recover(argparse.Namespace(home=str(self.root))), 0)

    def test_bridge_preserves_user_edits(self):
        operation = self.enrich(self.journal())
        self.git('checkout', '-q', self.new)
        edited = b'user instructions\r\n'
        self.plan.instructions_target.write_bytes(edited)
        with self.assertRaisesRegex(SystemExit, 'changed or unmanaged'):
            self.bridge(operation)
        self.assertEqual(self.plan.instructions_target.read_bytes(), edited)

    def test_bridge_rejects_race_to_independent_semantic_split_peer(self):
        registry_path = self.repo / '.agents/harnesses/registry.json'
        payload = json.loads(registry_path.read_text())
        payload['sources']['instructions'] = {
            'current': 'agents/global-instructions.md', 'migration': {
                'id': omh.INSTRUCTIONS_MIGRATION_ID, 'stage': 'semantic-split',
                'peer': 'AGENTS.md', 'requiredPredecessorRevision': '0' * 40,
            },
        }
        registry_path.write_text(json.dumps(payload))
        self.source, self.registry_peer = self.registry_peer, self.source
        self.registry_peer.write_bytes(b'independent project instructions\n')
        self.source.write_bytes(b'old global instructions\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'old semantic split')
        self.old = self.git('rev-parse', 'HEAD').strip().decode()
        self.source.write_bytes(b'new global instructions\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'new semantic split')
        self.new = self.git('rev-parse', 'HEAD').strip().decode()
        self.git('checkout', '-q', self.old)
        self.plan = replace(self.plan, instructions_source=self.source)
        self.plan.instructions_target.write_bytes(self.source.read_bytes())
        operation = self.enrich(self.journal())
        self.git('checkout', '-q', self.new)
        self.sync(operation)
        original_prepare = instructions.prepare_instruction_sync
        edited_bytes = instructions.materialized_instruction_bytes(self.repo, self.old, 'AGENTS.md')
        def race_to_peer(*args, **kwargs):
            # The bridge already read an exact journal-owned target. Change it
            # before prepare takes its own snapshot to separately-owned peer
            # bytes, which ordinary migration legitimately recognizes.
            self.plan.instructions_target.write_bytes(edited_bytes)
            prepared = original_prepare(*args, **kwargs)
            self.assertEqual(prepared.provenance, 'registry-peer')
            return prepared
        with mock.patch.object(instructions, 'prepare_instruction_sync', side_effect=race_to_peer):
            with self.assertRaisesRegex(SystemExit, 'changed during copy rollback preflight'):
                self.bridge(operation)
        self.assertEqual(self.plan.instructions_target.read_bytes(), edited_bytes)

    def test_bridge_preflights_all_targets_before_restoring_any(self):
        operation = self.enrich(self.journal())
        self.git('checkout', '-q', self.new)
        self.sync(operation)
        new_bytes = self.plan.instructions_target.read_bytes()
        operation['before']['desiredHarnesses'].append('claude-code')
        edited_target = self.root / 'user/.claude/CLAUDE.md'
        edited_target.parent.mkdir(parents=True)
        edited_target.write_bytes(b'user edited\r\n')
        second_plan = replace(self.plan, instructions_target=edited_target)
        with mock.patch.object(omh, '_resolve_plan', side_effect=[self.plan, second_plan]):
            with (
                mock.patch.object(omh, 'REPO_ROOT', self.repo),
                mock.patch.object(omh, 'update_operation', side_effect=lambda _home, **fields: {**operation, **fields}),
                mock.patch.dict(os.environ, {'HOME': str(self.root / 'user'), 'USERPROFILE': str(self.root / 'user'), 'CLAUDE_CONFIG_DIR': str(edited_target.parent)}),
                self.assertRaisesRegex(SystemExit, 'changed or unmanaged'),
            ):
                omh._restore_update_instruction_copies(self.root, operation)
        self.assertEqual(self.plan.instructions_target.read_bytes(), new_bytes)
        self.assertEqual(edited_target.read_bytes(), b'user edited\r\n')

    def test_bridge_restores_shared_copy_once_and_rejects_conflicting_sources(self):
        operation = self.enrich(self.journal())
        old_bytes = self.source.read_bytes()
        self.git('checkout', '-q', self.new)
        self.sync(operation)
        new_bytes = self.plan.instructions_target.read_bytes()
        operation['before']['desiredHarnesses'].append('claude-code')
        for conflict in (False, True):
            with self.subTest(conflict=conflict):
                self.plan.instructions_target.write_bytes(new_bytes)
                def shared_plan(registry, harness, **kwargs):
                    plan = resolve_harness_plan(registry, harness, **kwargs)
                    plan = replace(plan, instructions_target=self.plan.instructions_target,
                                   instructions_materialization='copy')
                    if conflict and harness == 'claude-code':
                        different_source = plan.repo_root / 'different-instructions.md'
                        different_source.write_bytes(b'conflicting old instructions\r\n')
                        plan = replace(plan, instructions_source=different_source)
                    return plan
                with (
                    mock.patch('harness_registry.resolve_harness_plan', side_effect=shared_plan),
                    mock.patch.object(instructions, 'apply_instruction_sync', wraps=instructions.apply_instruction_sync) as apply,
                ):
                    if conflict:
                        with self.assertRaisesRegex(SystemExit, 'conflicting instruction rollback plans'):
                            self.bridge(operation)
                        apply.assert_not_called()
                        self.assertEqual(self.plan.instructions_target.read_bytes(), new_bytes)
                    else:
                        self.bridge(operation)
                        apply.assert_called_once()
                        self.assertEqual(self.plan.instructions_target.read_bytes(), old_bytes)

    def test_real_vscode_copilot_registry_restores_shared_copy_once(self):
        operation = self.enrich(self.journal())
        operation['before']['desiredHarnesses'] = ['copilot', 'vscode']
        registry = load_harness_registry(
            self.repo / '.agents/harnesses/registry.json', repo_root=self.repo,
        )
        def current_plan(harness):
            return resolve_harness_plan(
                registry, harness, repo_root=self.repo,
                user_home=self.root / 'user', os_name=os.name, environ={},
            )
        copilot = current_plan('copilot')
        vscode = current_plan('vscode')
        self.assertEqual(copilot.instructions_target, vscode.instructions_target)
        self.assertEqual(copilot.instructions_materialization, 'copy')
        destination = copilot.instructions_target
        destination.parent.mkdir(parents=True, exist_ok=True)
        old_bytes = self.source.read_bytes()
        self.git('checkout', '-q', self.new)
        destination.write_bytes(self.source.read_bytes())
        with (
            mock.patch.object(omh, 'REPO_ROOT', self.repo),
            mock.patch.object(omh, '_resolve_plan', side_effect=current_plan),
            mock.patch.object(omh, 'update_operation', side_effect=lambda _home, **fields: {**operation, **fields}),
            mock.patch.dict(os.environ, {'HOME': str(self.root / 'user'), 'USERPROFILE': str(self.root / 'user'), 'COPILOT_HOME': ''}),
            mock.patch.object(instructions, 'apply_instruction_sync', wraps=instructions.apply_instruction_sync) as apply,
        ):
            omh._restore_update_instruction_copies(self.root, operation)
        apply.assert_called_once()
        self.assertEqual(destination.read_bytes(), old_bytes)

    def test_revision_attributes_override_current_checkout(self):
        (self.repo / '.gitattributes').write_text('AGENTS.md text eol=lf\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'force LF')
        lf_revision = self.git('rev-parse', 'HEAD').strip().decode()
        self.git('checkout', '-q', self.new)
        source = omh._instruction_source_at_revision(self.repo, lf_revision)
        digest = instructions.materialized_instruction_digest(self.repo, lf_revision, source['path'])
        self.assertEqual(digest, source['sha256'])
        self.assertIn(b'\r\n', self.source.read_bytes())
        self.assertEqual(self.git('status', '--porcelain'), b'')


if __name__ == '__main__':
    unittest.main()
