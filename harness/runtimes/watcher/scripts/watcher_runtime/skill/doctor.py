#!/usr/bin/env python3
"""Run Watcher skill-domain environment diagnostics."""

from __future__ import annotations

import argparse
import json
import os
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
from .collect_event import DEFAULT_STATE_DIR
from .runtime_paths import log_file_path
from ..repository_source import RepositorySource, resolve_repository_source
from .codex_hook_adapter import discover_skill_metadata


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




class Doctor:
    def __init__(
        self,
        *,
        source: RepositorySource,
        python_path: Path,
        state_dir: Path,
        hook_target: Path,
    ) -> None:
        self.source = source
        self.python_path = python_path
        self.state_dir = state_dir
        self.hook_target = hook_target
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

        self.check_catalog()
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

    def check_catalog(self) -> None:
        try:
            metadata = discover_skill_metadata(self.source.root)
        except SystemExit as exc:
            self.fail(str(exc))
            return
        self.ok(f"canonical catalog validated: {len(metadata['skills'])} identities")

    def check_state_dir(self) -> None:
        if self.state_dir.exists() and not self.state_dir.is_dir():
            self.fail(f"state path is not a directory: {self.state_dir}")
        elif self.state_dir.is_dir():
            self.ok(f"state directory exists: {self.state_dir}")
        else:
            self.warn(f"state has not been initialized: {self.state_dir}")

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
                f"{self.hook_target}. Run atm install hooks --harness codex to reconcile owned handlers. Issues: {issues}"
            )

    def check_sample_event(self) -> None:
        sample = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.source.watcher_runtime),
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
        description="Read-only checks of the Watcher catalog, hooks, and runtime; smoke events use temporary state only.",
    )
    parser.add_argument(
        "--repo-root",
        help="ATM verified payload root containing canonical-catalog.json. Defaults to $ATM_HARNESS_ROOT.",
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
    args = parser.parse_args(argv)
    source = resolve_repository_source(args.repo_root)
    doctor = Doctor(
        source=source,
        python_path=expand_path(args.python_path),
        state_dir=expand_path(args.state_dir),
        hook_target=expand_path(args.hook_target),
    )
    doctor.run()
    return 1 if doctor.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
