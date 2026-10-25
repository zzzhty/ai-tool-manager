"""Behavioral lightweight command contracts; no timing thresholds."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import harness_registry
import manager_state
import omh
import omh_bootstrap as bootstrap


class LightweightCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'manager'
        self.state = self.home / 'state'
        self.state.mkdir(parents=True)
        self.manager = dict(schemaVersion=manager_state.STATE_SCHEMA_VERSION,
                            product='oh-my-harness', status='ready', repository='recorded-remote',
                            revision='a' * 40, releaseVersion='1.2.3', bundleIdentity='b' * 64,
                            channel='main')
        self.desired = dict(schemaVersion=manager_state.STATE_SCHEMA_VERSION,
                            harnesses=['copilot', 'unknown-client'], updatePolicy={'channel': 'main'})
        self.write_state()

    def write_state(self):
        for name, value in [('manager.json', self.manager), ('desired.json', self.desired)]:
            (self.state / name).write_text(json.dumps(value))

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}

    def test_status_and_version_are_recorded_only(self):
        before = self.snapshot()
        for command in ('status', 'version'):
            output = io.StringIO()
            with mock.patch.object(omh, '_distribution', side_effect=AssertionError('no hashes')), \
                 mock.patch.object(omh.subprocess, 'run', side_effect=AssertionError('no process')), \
                 mock.patch.object(omh, '_state_context', side_effect=AssertionError('no mutation context')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(omh.main(['--home', str(self.home), command, '--json']), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['observation'], 'recorded-state-only')
            if command == 'status':
                self.assertIsNone(result['worktreeClean'])
                self.assertEqual(result['desiredHarnesses'], ['copilot-cli', 'unknown-client'])
                self.assertEqual(result['manager']['revision'], 'a' * 40)
            self.assertEqual(before, self.snapshot())

    def test_legacy_receipt_is_not_current_revision(self):
        (self.state / 'manager.json').unlink()
        (self.state / 'desired.json').unlink()
        (self.state / 'install.json').write_text(json.dumps(dict(product='oh-my-harness', status='ready', revision='old')))
        snapshot = omh._recorded_snapshot(self.home)
        self.assertEqual(snapshot['stateKind'], 'legacy-receipt-only')
        self.assertIsNone(snapshot['manager'])
        self.assertEqual(snapshot['desiredHarnesses'], [])
        self.assertFalse((self.state / 'manager.json').exists())

    def test_missing_partial_and_corrupt_state_are_not_initialized(self):
        (self.state / 'desired.json').unlink()
        with self.assertRaisesRegex(SystemExit, 'incomplete'):
            omh._recorded_snapshot(self.home)
        (self.state / 'desired.json').write_text('{broken')
        with self.assertRaisesRegex(SystemExit, 'unreadable'):
            omh._recorded_snapshot(self.home)

    def test_pending_degraded_operation_visible(self):
        self.manager['status'] = 'degraded'
        self.write_state()
        operation = dict(schemaVersion=manager_state.STATE_SCHEMA_VERSION, operationId='op',
                         command='update', phase='rollback-failed', before={}, target={})
        (self.state / 'operations').mkdir()
        (self.state / 'operations/current.json').write_text(json.dumps(operation))
        snapshot = omh._recorded_snapshot(self.home)
        self.assertEqual(snapshot['operation'], operation)
        self.assertEqual(snapshot['manager']['status'], 'degraded')

    def test_metadata_does_not_check_instruction_files_but_runtime_does(self):
        registry = self.home / 'registry.json'
        shutil.copyfile(ROOT / '.agents/harnesses/registry.json', registry)
        metadata = harness_registry.load_harness_metadata(registry, repo_root=self.home)
        self.assertEqual(metadata.resolve_id('copilot'), 'copilot-cli')
        with self.assertRaises(harness_registry.HarnessRegistryError):
            harness_registry.load_harness_registry(registry, repo_root=self.home)

    def test_corrupt_registry_help_available_execution_errors(self):
        with mock.patch.object(omh, 'load_harness_metadata', side_effect=harness_registry.HarnessRegistryError('broken registry')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
                omh.parse_arguments(['install', '--help'])
            self.assertEqual(caught.exception.code, 0)
            self.assertIn('broken registry', output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                omh.parse_arguments(['install', 'codex'])
            self.assertEqual(caught.exception.code, 2)

    def test_bad_arguments_precede_bootstrap_lock_and_repair(self):
        # Use the actual shared parser with the real source; no fixture bootstrap runs.
        (self.home / 'repo/scripts').mkdir(parents=True)
        (self.home / 'repo/scripts/omh.py').write_text('# CLI location marker')
        invalid = [['update', '--nonsense'], ['manager'], ['remove'], ['not-a-harness'],
                   ['repair', '--dry-run', '--nonsense'], ['update', 'main', '--to', 'HEAD'],
                   ['install', 'copilot', '--all']]
        for args in invalid:
            with self.subTest(args=args), \
                 mock.patch.object(bootstrap, '_parse_cli', side_effect=lambda c, h, a: omh.parse_arguments(['--home', str(h), *a])), \
                 mock.patch.object(bootstrap, '_mutation_lock', side_effect=AssertionError('no lock')), \
                 mock.patch.object(bootstrap, '_repair_checkout', side_effect=AssertionError('no repair')), \
                 mock.patch.object(bootstrap.subprocess, 'run', side_effect=AssertionError('no process')), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bootstrap.main(['--home', str(self.home), *args]), 2)

    def test_shorthand_and_delimiter_are_preserved(self):
        self.assertEqual(omh.parse_arguments([]).command, 'refresh')
        self.assertEqual(omh.parse_arguments(['copilot']).targets, ['copilot-cli'])
        self.assertEqual(omh.parse_arguments(['refresh', '--', 'vscode']).targets, ['vscode'])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            omh.parse_arguments(['refresh', '--', '--help'])

    def test_stable_shim_accepts_older_parser_api(self):
        namespace = {"_normalize_argv": omh._normalize_argv,
                     "_selected_command": omh._selected_command,
                     "INTERNAL_COMMANDS": omh.INTERNAL_COMMANDS,
                     "build_parser": omh.build_parser,
                     "build_internal_parser": omh.build_internal_parser}
        with mock.patch.object(bootstrap.runpy, 'run_path', return_value=namespace):
            for command in ('status', 'version'):
                args = bootstrap._parse_cli(ROOT / 'scripts/omh.py', self.home, [command, '--json'])
                self.assertEqual(args.command, command)
            args = bootstrap._parse_cli(ROOT / 'scripts/omh.py', self.home,
                                        ['_resume-rollback', '--operation-id', 'recorded'])
            self.assertEqual(args.operation_id, 'recorded')

    def test_missing_checkout_repair_rejects_bad_flags_without_writes(self):
        with contextlib.redirect_stderr(io.StringIO()), \
             mock.patch.object(bootstrap, '_mutation_lock', side_effect=AssertionError('no lock')), \
             mock.patch.object(bootstrap, '_repair_checkout', side_effect=AssertionError('no restore')):
            with self.assertRaises(SystemExit) as caught:
                bootstrap.main(['--home', str(self.home), 'repair', '--dry-run', '--nonsense'])
            self.assertEqual(caught.exception.code, 2)

    def test_stdlib_only_help_and_status(self):
        for args in (['--help'], ['--home', str(self.home), 'status', '--json']):
            result = subprocess.run([sys.executable, '-B', '-S', str(ROOT / 'scripts/omh.py'), *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
