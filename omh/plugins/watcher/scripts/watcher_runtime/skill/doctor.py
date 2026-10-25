#!/usr/bin/env python3
"""Run Watcher skill-domain environment diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .codex_hook_adapter import write_hook_event
from .codex_hook_config import (
    CODEX_HOME,
    DEFAULT_TARGET,
    HOOK_EVENTS,
    default_python,
    desired_handler,
    expand_path,
    is_skill_watcher_handler,
    load_config,
    validate_hook_shape,
)
from .collect_event import DEFAULT_STATE_DIR, ensure_runtime_dirs
from .runtime_paths import log_file_path
from ..repository_source import RepositorySource, resolve_repository_source


def describe_handler_mismatch(handler: dict[str, object], expected: dict[str, object]) -> list[str]:
    mismatches = []
    for key, expected_value in expected.items():
        if handler.get(key) != expected_value:
            mismatches.append(f"{key} expected {expected_value!r}, found {handler.get(key)!r}")
    extra_keys = sorted(set(handler) - set(expected))
    if extra_keys:
        mismatches.append(f"unexpected keys: {', '.join(extra_keys)}")
    return mismatches


def find_managed_hook_issues(
    config: dict[str, object],
    *,
    python_path: Path,
    adapter: Path,
    repo_root: Path,
) -> tuple[set[str], list[str]]:
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return set(), ["hook config field `hooks` is not an object"]

    matched_events: set[str] = set()
    issues: list[str] = []
    expected_events = set(HOOK_EVENTS)
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks", [])
            if not isinstance(handlers, list):
                continue
            for handler_index, handler in enumerate(handlers):
                if not is_skill_watcher_handler(handler):
                    continue
                location = f"{event}[{group_index}].hooks[{handler_index}]"
                if event not in expected_events:
                    issues.append(f"{location} is a stale Watcher skill event; default install no longer uses {event}")
                    continue
                matched_events.add(str(event))
                expected = desired_handler(
                    str(event),
                    python_path=python_path,
                    adapter=adapter,
                    repo_root=repo_root,
                )
                mismatches = describe_handler_mismatch(handler, expected)
                if mismatches:
                    issues.append(f"{location} does not match desired handler schema: {'; '.join(mismatches)}")
    return matched_events, issues


def validator_path(repo_root: Path, *, codex_home: Path = CODEX_HOME) -> Path:
    override = os.environ.get("PLUGIN_VALIDATOR") or os.environ.get("CODEX_PLUGIN_VALIDATOR")
    if override:
        return expand_path(override)
    system_validator = (
        codex_home
        / "skills"
        / ".system"
        / "plugin-creator"
        / "scripts"
        / "validate_plugin.py"
    )
    if system_validator.is_file() and (
        system_validator.parent / "identifier_validation.py"
    ).is_file():
        return system_validator
    return repo_root / "scripts" / "validate_plugin.py"


class Doctor:
    def __init__(
        self,
        *,
        source: RepositorySource,
        python_path: Path,
        state_dir: Path,
        hook_target: Path,
        validator: Path,
    ) -> None:
        self.source = source
        self.python_path = python_path
        self.state_dir = state_dir
        self.hook_target = hook_target
        self.validator = validator
        self.failures = 0
        self.warnings = 0

    def ok(self, message: str) -> None:
        print(f"OK   {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print(f"WARN {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        print(f"FAIL {message}")

    def run(self) -> None:
        if self.python_path.is_file():
            self.ok(f"tooling python exists: {self.python_path}")
        else:
            self.fail(f"tooling python missing: {self.python_path}")
            return

        self.check_pyyaml()
        self.check_plugin_validation()
        self.check_state_dir()
        self.check_hook_config()
        self.check_sample_event()

        if self.failures:
            print(
                f"doctor failed with {self.failures} failure(s), {self.warnings} warning(s)",
                file=sys.stderr,
            )
            return
        print(f"doctor passed with {self.warnings} warning(s)")

    def check_pyyaml(self) -> None:
        result = subprocess.run(
            [str(self.python_path), "-c", "import yaml; print(yaml.__version__)"],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            self.ok(f"PyYAML import works: {result.stdout.strip()}")
        else:
            self.fail(f"PyYAML import failed: {result.stderr.strip() or result.stdout.strip()}")

    def check_plugin_validation(self) -> None:
        if not self.validator.is_file():
            self.fail(f"plugin validator missing: {self.validator}")
            return
        result = subprocess.run(
            [
                str(self.python_path),
                str(self.validator),
                str(self.source.watcher_plugin),
            ],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            self.ok("plugin validation passed")
        else:
            output = (result.stderr or result.stdout).strip()
            self.fail(f"plugin validation failed: {output}")

    def check_state_dir(self) -> None:
        try:
            ensure_runtime_dirs(self.state_dir)
        except OSError as exc:
            self.fail(f"state directory is not writable: {self.state_dir}: {exc}")
            return
        self.ok(f"state directory writable: {self.state_dir}")

    def check_hook_config(self) -> None:
        if not self.hook_target.exists():
            self.warn(f"hook config not installed yet: {self.hook_target}")
            return
        try:
            config = load_config(self.hook_target)
        except SystemExit as exc:
            self.fail(str(exc))
            return
        try:
            validate_hook_shape(config)
        except SystemExit as exc:
            self.fail(str(exc))
            return

        matched_events, issues = find_managed_hook_issues(
            config,
            python_path=self.python_path,
            adapter=self.source.watcher_cli,
            repo_root=self.source.root,
        )
        if set(matched_events) == set(HOOK_EVENTS):
            self.ok(f"Watcher skill hook handlers installed: {self.hook_target}")
        else:
            missing = sorted(set(HOOK_EVENTS) - set(matched_events))
            self.warn(
                f"Watcher skill hook config incomplete at {self.hook_target}; "
                f"missing: {', '.join(missing)}"
            )

        if issues:
            self.fail(
                "Watcher skill hook config has stale managed handlers at "
                f"{self.hook_target}. Run scripts/watcher skill install-hook --apply to refresh. Issues: {issues}"
            )

    def check_sample_event(self) -> None:
        sample = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.source.watcher_plugin),
            "session_id": "doctor-session",
            "turn_id": "doctor-turn",
            "model": "doctor-model",
            "prompt": "Use diagnose on this sample prompt containing token sk-doctorsecret1234567890",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            write_hook_event(
                {**sample, "hook_event_name": "SessionStart"},
                state_dir=state_dir,
                repo_root=self.source.root,
            )
            event = write_hook_event(
                sample,
                state_dir=state_dir,
                repo_root=self.source.root,
            )
            log_file = log_file_path(state_dir)
            raw = log_file.read_text(encoding="utf-8")
        if "sk-doctorsecret" in raw:
            self.fail("sample event leaked a secret-like token")
            return
        primary = event.get("skill_attribution", {}).get("primary", {})
        if primary.get("name") != "mattpocock-skills:diagnosing-bugs":
            self.fail("sample event did not infer the monitored diagnosing-bugs skill")
            return
        parsed = json.loads(raw.strip())
        if parsed.get("codex", {}).get("prompt_summary"):
            self.ok("sample hook event appended and redacted")
        else:
            self.fail("sample hook event missing prompt summary")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill doctor",
        description="Check Watcher skill-domain plugin, hooks, and runtime basics.",
    )
    parser.add_argument(
        "--repo-root",
        help="Canonical oh-my-harness repository root. Defaults to $OH_MY_HARNESS_ROOT.",
    )
    parser.add_argument(
        "--state-dir",
        default=str(DEFAULT_STATE_DIR),
        help="Watcher skill state directory. Defaults to $CODEX_HOME/watcher/skill.",
    )
    parser.add_argument(
        "--hook-target",
        default=str(DEFAULT_TARGET),
        help="Hook configuration to inspect. Defaults to $CODEX_HOME/hooks.json.",
    )
    parser.add_argument(
        "--python",
        dest="python_path",
        default=str(default_python()),
        help="Tooling Python used by Watcher hooks.",
    )
    parser.add_argument(
        "--validator",
        help=(
            "Plugin validator script. Defaults to $PLUGIN_VALIDATOR, "
            "$CODEX_PLUGIN_VALIDATOR, a complete Codex system validator, "
            "or <repo-root>/scripts/validate_plugin.py."
        ),
    )
    args = parser.parse_args(argv)
    source = resolve_repository_source(args.repo_root)
    doctor = Doctor(
        source=source,
        python_path=expand_path(args.python_path),
        state_dir=expand_path(args.state_dir),
        hook_target=expand_path(args.hook_target),
        validator=(
            expand_path(args.validator)
            if args.validator is not None
            else validator_path(source.root)
        ),
    )
    doctor.run()
    return 1 if doctor.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
