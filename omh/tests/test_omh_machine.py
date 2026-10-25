"""Protocol compatibility, read-only behavior and bounded lifecycle delegation."""
from __future__ import annotations

import argparse
import contextlib
import io
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
import omh_machine as machine
import omh_bootstrap as bootstrap
import manager_state
import sync_harness_instructions as instructions
from harness_registry import load_harness_registry, resolve_harness_plan


class MachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'manager'
        self.runtime_check = mock.patch.object(machine, 'runtime_unavailable_reason', return_value=None)
        self.runtime_check.start()
        self.addCleanup(self.runtime_check.stop)
        python_patch = mock.patch.object(machine, 'venv_python', return_value=Path(sys.executable))
        python_patch.start()
        self.addCleanup(python_patch.stop)

    def call(self, *arguments):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = omh.main(['--home', str(self.home), 'machine', *arguments])
        return code, json.loads(out.getvalue())

    def test_capabilities_and_status_do_not_create_home_or_spawn(self):
        with mock.patch.object(machine.subprocess, 'run', side_effect=AssertionError('no subprocess')):
            for op in ('capabilities', 'status'):
                code, payload = self.call('--protocol', '1', op)
                self.assertEqual(code, 0)
                self.assertTrue(payload['ok'])
                self.assertEqual(payload['protocolVersion'], 1)
                self.assertFalse(self.home.exists())
            self.assertEqual(payload['result']['observation'], 'recorded-state-only')
            self.assertIsNone(payload['result']['worktreeClean'])

    def test_capabilities_do_not_gate_on_product_version(self):
        code, payload = self.call('--protocol', '1', 'capabilities')
        result = payload['result']
        self.assertIn('vscode', result['harnesses'])
        for op in machine.MUTATIONS:
            self.assertTrue(result['operations'][op]['supported'])
            self.assertTrue(result['operations'][op]['explicitHarnesses'])
        for op in machine.INTERACTIVE:
            self.assertFalse(result['operations'][op]['supported'])
        self.assertEqual(result['instructionReplacement'], 'interactive-only')

    def test_invalid_inputs_are_json_and_never_mutate(self):
        cases = [[], ['--protocol', '2', 'status'], ['--protocol', '1', 'remove'],
                 ['--protocol', '1', 'remove', '--all', '--confirm'],
                 ['--protocol', '1', 'status', '--confirm'],
                 ['--protocol', '1', 'install', '--harness', 'unknown', '--confirm'],
                 ['--protocol', '1', 'install', '--harness', 'codex', '--yes'],
                 ['--protocol', '1', 'remove', '--harness', 'codex', '--purge-unknown']]
        with mock.patch.object(machine.subprocess, 'run', side_effect=AssertionError('no mutation')):
            for args in cases:
                with self.subTest(args=args):
                    code, payload = self.call(*args)
                    self.assertEqual(code, 2)
                    self.assertFalse(payload['ok'])
                    self.assertIn(payload['error']['code'], ('invalid_request', 'unsupported_protocol'))
                    self.assertFalse(self.home.exists())

    def test_no_confirmation_and_interactive_operations_never_spawn(self):
        with mock.patch.object(machine.subprocess, 'run', side_effect=AssertionError('no mutation')):
            for op in machine.MUTATIONS:
                code, payload = self.call('--protocol', '1', op, '--harness', 'vscode')
                self.assertEqual(code, 3)
                self.assertEqual(payload['error']['code'], 'confirmation_required')
            for op in machine.INTERACTIVE:
                code, payload = self.call('--protocol', '1', op, '--confirm')
                self.assertEqual(code, 3)
                self.assertFalse(self.home.exists())

    def test_bounded_delegation_logs_and_no_shell(self):
        for op in machine.MUTATIONS:
            with self.subTest(operation=op), mock.patch.object(machine, '_run_lifecycle', return_value=subprocess.CompletedProcess([], 0, 'done\n', 'diagnostic\n')) as run:
                code, payload = self.call('--protocol', '1', op, '--harness', 'copilot', '--harness', 'copilot-cli', '--confirm')
                self.assertEqual(code, 0)
                command = run.call_args.args[0]
                self.assertEqual(command[-1], '--yes' if op == 'remove' else '--no-path' if op == 'repair' else '--machine-safe')
                self.assertEqual(command.count('copilot-cli'), 1)
                self.assertNotIn('--all', command)
                self.assertEqual(run.call_args.args[1]['PYTHONDONTWRITEBYTECODE'], '1')
                self.assertEqual(payload['result']['stdout'], 'done\n')

    def test_error_and_busy_contract(self):
        for detail, expected, code in [
                ('error: another oh-my-harness mutation is already running: x', 'busy', 4),
                ('confirmation_required: existing instructions', 'confirmation_required', 3),
                ('an interrupted manager operation is active; run omh recover', 'operation_failed', 1)]:
            with mock.patch.object(machine, '_run_lifecycle', return_value=subprocess.CompletedProcess([], 1, '', detail)):
                result_code, payload = self.call('--protocol', '1', 'remove', '--harness', 'vscode', '--confirm')
                self.assertEqual(result_code, code)
                self.assertEqual(payload['error']['code'], expected)
                self.assertEqual(payload['result']['exitCode'], 1)

    def test_unavailable_runtime_fails_without_bootstrapping(self):
        with mock.patch.object(machine, "runtime_unavailable_reason", return_value="tooling Python is unavailable"), \
             mock.patch.object(machine.subprocess, "run", side_effect=AssertionError("no bootstrap")):
            code, payload = self.call("--protocol", "1", "install", "--harness", "vscode", "--confirm")
        self.assertEqual(code, 1)
        self.assertIn("No runtime repair", payload["error"]["message"])
        self.assertFalse(self.home.exists())

    def test_real_busy_uses_existing_lock(self):
        with manager_state.ManagerLock(self.home):
            code, payload = self.call('--protocol', '1', 'remove', '--harness', 'vscode', '--confirm')
        self.assertEqual(code, 4)
        self.assertEqual(payload['error']['code'], 'busy')
        self.assertFalse((self.home / 'state/manager.json').exists())

    def test_corrupt_state_structured_and_untouched(self):
        state = self.home / 'state'
        state.mkdir(parents=True)
        bad = state / 'manager.json'
        bad.write_text('{broken')
        code, payload = self.call('--protocol', '1', 'status')
        self.assertEqual(code, 1)
        self.assertEqual(payload['error']['code'], 'operation_failed')
        self.assertEqual(bad.read_text(), '{broken')

    def test_stable_shim_machine_does_not_bootstrap(self):
        # Actual source copied to a disposable managed checkout, no runtime exists.
        import shutil
        shutil.copytree(ROOT / 'scripts', self.home / 'repo/scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / '.agents/harnesses', self.home / 'repo/.agents/harnesses')
        with mock.patch.object(bootstrap, '_mutation_lock', side_effect=AssertionError('no outer lock')), \
             mock.patch.object(bootstrap, '_repair_checkout', side_effect=AssertionError('no repair')), \
             mock.patch.object(bootstrap.subprocess, 'run', side_effect=AssertionError('no bootstrap')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(bootstrap.main(['--home', str(self.home), 'machine', '--protocol', '1', 'status']), 0)
        self.assertEqual(json.loads(output.getvalue())['result']['observation'], 'recorded-state-only')
        self.assertFalse((self.home / 'venv').exists())
        self.assertFalse((self.home / 'state').exists())

    def test_read_checks_delegate_without_confirmation_or_bootstrap(self):
        for op in ('check', 'doctor'):
            with mock.patch.object(machine, '_run_lifecycle', return_value=subprocess.CompletedProcess([], 0, 'checked', '')) as run:
                self.assertEqual(self.call('--protocol', '1', op)[0], 0)
                command = run.call_args.args[0]
                self.assertNotIn('--yes', command)
                self.assertNotIn('--machine-safe', command)
                self.assertEqual(command[-1], op)

    def test_bounded_log_runner_drains_both_pipes(self):
        child = machine._run_lifecycle([sys.executable, "-c", "import sys; sys.stdout.write(\"x\"*200000); sys.stderr.write(\"y\"*200000)"], dict(os.environ))
        self.assertEqual(child.returncode, 0)
        self.assertEqual(len(child.stdout), machine.LOG_LIMIT)
        self.assertEqual(len(child.stderr), machine.LOG_LIMIT)
        self.assertTrue(child.stdout_truncated)
        self.assertTrue(child.stderr_truncated)

    def test_home_named_machine_does_not_confuse_command_selection(self):
        args = omh.parse_arguments(["--home", "machine", "machine", "--protocol", "1", "status"])
        self.assertEqual(args.home, "machine")
        self.assertEqual(args.machine_arguments, ["--protocol", "1", "status"])

    def test_legacy_cli_defaults_and_yes_unchanged(self):
        self.assertEqual(omh.parse_arguments([]).command, 'refresh')
        self.assertEqual(omh.parse_arguments(['copilot']).targets, ['copilot-cli'])
        args = omh.parse_arguments(['install', 'vscode', '--yes'])
        self.assertTrue(args.yes)
        self.assertFalse(args.machine_safe)


class MachineInstructionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = resolve_harness_plan(load_harness_registry(), 'zcode', user_home=self.root, os_name='posix')
        self.plan.instructions_target.parent.mkdir(parents=True)

    def test_noninteractive_guard_preserves_existing_user_instructions(self):
        target = self.plan.instructions_target
        target.write_text('my instructions')
        with self.assertRaisesRegex(SystemExit, 'confirmation_required'), \
             mock.patch.object(instructions, '_confirm', side_effect=AssertionError('no prompt')):
            instructions.prepare_instruction_sync(self.plan, dry_run=False, assume_yes=True, non_interactive=True, output=lambda _: None)
        self.assertEqual(target.read_text(), 'my instructions')

    def test_exact_managed_provenance_remains_authorized(self):
        self.plan.instructions_target.write_text("managed old content")
        prepared = instructions._inspect(self.plan)
        prepared = replace(prepared, provenance="registry-peer")
        with mock.patch.object(instructions, "_inspect", return_value=prepared), \
             mock.patch.object(instructions, "_confirm", side_effect=AssertionError("managed provenance needs no live prompt")):
            result = instructions.prepare_instruction_sync(self.plan, dry_run=False, assume_yes=True, non_interactive=True, output=lambda _: None)
        self.assertTrue(result.approved)
        self.assertEqual(result.provenance, "registry-peer")

    def test_noninteractive_creation_revalidates_before_apply(self):
        prepared = instructions.prepare_instruction_sync(self.plan, dry_run=False, assume_yes=True, non_interactive=True, output=lambda _: None)
        self.plan.instructions_target.write_text('racing user edit')
        with self.assertRaisesRegex(SystemExit, 'changed after preflight'):
            instructions.apply_instruction_sync(prepared, dry_run=False)
        self.assertEqual(self.plan.instructions_target.read_text(), 'racing user edit')

    def test_all_instruction_targets_preflight_before_any_lifecycle_write(self):
        target = self.plan.instructions_target
        target.write_text('user owned')
        for op in ('install', 'refresh'):
            args = omh.parse_arguments([op, 'vscode', 'zcode', '--yes', '--machine-safe'])
            args.home = str(self.root / 'manager')
            first = replace(self.plan, instructions_target=self.root / 'new.md')
            with mock.patch.object(omh, '_state_context', return_value=({}, {'harnesses':['vscode','zcode']})) as state, \
                 mock.patch.object(omh, '_resolve_plan', side_effect=[first, self.plan]), \
                 mock.patch.object(omh, '_refresh_one', side_effect=AssertionError('no partial apply')), \
                 mock.patch.object(omh, 'write_desired', side_effect=AssertionError('no state write')), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 self.assertRaisesRegex(SystemExit, 'confirmation_required'):
                args.func(args)
            self.assertEqual(state.call_args.kwargs['persist'], False)
            self.assertEqual(state.call_count, 1)
            self.assertFalse(first.instructions_target.exists())
            self.assertEqual(target.read_text(), 'user owned')

    def test_machine_repair_rejects_active_journal_before_recovery(self):
        args = omh.parse_arguments(['repair', 'zcode', '--yes', '--machine-safe'])
        args.home = str(self.root / 'manager')
        with mock.patch.object(omh, 'load_current_operation', return_value={'operationId': 'pending'}), \
             mock.patch.object(omh, 'command_recover', side_effect=AssertionError('no automatic recovery')), \
             mock.patch.object(omh, '_bootstrap_tooling', side_effect=AssertionError('no bootstrap')), \
             self.assertRaisesRegex(SystemExit, 'cannot recover an active operation'):
            args.func(args)
        self.assertFalse(Path(args.home).exists())

    def test_machine_repair_preflights_before_manager_writes(self):
        self.plan.instructions_target.write_text('user owned')
        args = omh.parse_arguments(['repair', 'zcode', '--yes', '--machine-safe'])
        args.home = str(self.root / 'manager')
        with mock.patch.object(omh, 'load_current_operation', return_value=None), \
             mock.patch.object(omh, '_state_context', return_value=({}, {'harnesses':['zcode']})), \
             mock.patch.object(omh, '_resolve_plan', return_value=self.plan), \
             mock.patch.object(omh, '_bootstrap_tooling', side_effect=AssertionError('no bootstrap')), \
             mock.patch.object(omh, 'ensure_user_path', side_effect=AssertionError('no PATH')), \
             mock.patch.object(omh, '_refresh_one', side_effect=AssertionError('no apply')), \
             mock.patch('install_oh_my_harness.write_launchers', side_effect=AssertionError('no launcher writes')), \
             contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(SystemExit, 'confirmation_required'):
            args.func(args)
        self.assertEqual(self.plan.instructions_target.read_text(), 'user owned')

    def test_machine_repair_keeps_narrow_scope_and_existing_authority(self):
        args = omh.parse_arguments(['repair', 'zcode', '--yes', '--machine-safe'])
        home = self.root / 'manager'
        args.home = str(home)
        (home / 'state').mkdir(parents=True)
        (home / 'state/install.json').write_text(json.dumps({
            'product': 'oh-my-harness', 'status': 'ready',
            'paths': {'repo': str(self.root / 'former-repo')},
        }))
        manager = dict(repository='repo', revision='a'*40, releaseVersion='1.0',
                       bundleIdentity='bundle', channel='main')
        with mock.patch.object(omh, 'load_current_operation', return_value=None), \
             mock.patch.object(omh, '_state_context', return_value=(manager, {'harnesses':['zcode']})), \
             mock.patch.object(omh, '_resolve_plan', return_value=self.plan), \
             mock.patch.object(omh, '_bootstrap_tooling', side_effect=AssertionError('no bootstrap')), \
             mock.patch.object(omh, 'ensure_user_path', side_effect=AssertionError('no PATH')), \
             mock.patch.object(omh, '_refresh_one') as refresh, \
             mock.patch.object(omh, '_write_harness_state'), \
             mock.patch.object(omh, 'write_desired'), \
             mock.patch.object(omh, 'write_manager'), \
             mock.patch('install_oh_my_harness.write_launchers') as launchers, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(args.func(args), 0)
        launchers.assert_called_once()
        self.assertTrue(refresh.call_args.args[0].machine_safe)
        self.assertIsNone(refresh.call_args.args[0].migrate_from_repo)
        self.assertEqual(refresh.call_args.kwargs['harness'], 'zcode')

    def test_machine_repair_does_not_add_targets(self):
        args = omh.parse_arguments(['repair', 'zcode', '--yes', '--machine-safe'])
        with mock.patch.object(omh, '_state_context', return_value=({}, {'harnesses':[]})), \
             self.assertRaisesRegex(SystemExit, 'requires recorded installed'):
            omh._machine_preflight(args, self.root, 'repair')

    def test_legacy_yes_still_requires_live_replacement_confirmation(self):
        self.plan.instructions_target.write_text('user owned')
        with self.assertRaisesRegex(SystemExit, 'was not confirmed'):
            instructions.prepare_instruction_sync(self.plan, dry_run=False, assume_yes=True, input_fn=lambda _: 'no', output=lambda _: None)


class MachineLifecycleIntegrationTests(unittest.TestCase):
    def test_real_lifecycle_and_conflict_preflight_in_disposable_home(self):
        import shutil
        import venv
        if shutil.which('git') is None:
            self.skipTest('git unavailable')
        try:
            import yaml
            import jsonschema
        except ImportError:
            self.skipTest('tooling dependencies unavailable')
        with tempfile.TemporaryDirectory(prefix='omh-machine-integration-') as name:
            root = Path(name)
            home, user = root / 'manager', root / 'user'
            repo = home / 'repo'
            user.mkdir()
            # The vendored engine tree is not itself a Git checkout; build a
            # fresh fixture repository from the current working tree.
            subprocess.run(['git', 'init', '--quiet', '-b', 'main', str(repo)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            shutil.copytree(ROOT, repo, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '.venv'))
            subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', str(ROOT)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'add', '--all'],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid',
                            'commit', '--quiet', '-m', 'fixture'],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            venv.EnvBuilder(system_site_packages=True, with_pip=False).create(home / 'venv')
            # A nested system-site venv inherits the BASE interpreter's packages,
            # not the runner venv's; skip when the base lacks the tooling deps.
            fixture_python = home / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
            probe = subprocess.run([str(fixture_python), '-B', '-c', 'import yaml, jsonschema'],
                                   capture_output=True, text=True)
            if probe.returncode != 0:
                self.skipTest('nested system-site interpreter lacks tooling dependencies')
            state = home / 'state'
            state.mkdir()
            receipt = {'product':'oh-my-harness', 'status':'ready',
                       'repository':str(ROOT), 'ref':'main'}
            (state / 'install.json').write_text(json.dumps(receipt))
            env = dict(os.environ, HOME=str(user), USERPROFILE=str(user),
                       OH_MY_HARNESS_HOME=str(home), CODEX_HOME=str(user / '.codex'),
                       PYTHONDONTWRITEBYTECODE='1')

            def call(operation, *arguments):
                child = subprocess.run(
                    [sys.executable, '-B', str(repo / 'scripts/omh.py'), '--home', str(home),
                     'machine', '--protocol', '1', operation, *arguments],
                    env=env, text=True, capture_output=True, timeout=60)
                return child.returncode, json.loads(child.stdout)

            foreign = user / '.zcode/AGENTS.md'
            foreign.parent.mkdir(parents=True)
            foreign.write_text('user instructions must survive')
            code, result = call('install', '--harness', 'vscode', '--harness', 'zcode', '--confirm')
            self.assertEqual(code, 3, result)
            self.assertEqual(result['error']['code'], 'confirmation_required')
            self.assertEqual(foreign.read_text(), 'user instructions must survive')
            self.assertFalse((state / 'manager.json').exists())
            self.assertFalse((state / 'desired.json').exists())
            self.assertFalse((user / '.copilot').exists())
            foreign.unlink()
            for operation in ('install', 'check', 'refresh', 'repair', 'remove'):
                arguments = ['--harness', 'zcode']
                if operation != 'check':
                    arguments.append('--confirm')
                code, result = call(operation, *arguments)
                self.assertEqual(code, 0, result)
                self.assertTrue(result['ok'])
            code, result = call('status')
            self.assertEqual(code, 0)
            self.assertEqual(result['result']['desiredHarnesses'], [])
            self.assertFalse(foreign.exists())
            self.assertFalse((user / '.bashrc').exists())


if __name__ == '__main__':
    unittest.main()
