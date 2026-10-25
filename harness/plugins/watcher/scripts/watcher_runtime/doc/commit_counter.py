#!/usr/bin/env python3
"""Report commit-threshold trigger status for configured Watcher doc repos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit_repo import AuditFailure, expand_path, resolve_state_dir
from .audit_runtime import (
    DEFAULT_CONFIG,
    load_config,
    load_state,
    mark_current,
    repo_status,
    state_path,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watcher doc commit-counter",
        description="Show commit-threshold trigger status for configured repos.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Repo config JSON path.")
    parser.add_argument("--state-dir", help="Runtime state directory. Defaults to $CODEX_HOME/watcher/doc.")
    parser.add_argument("--mark-current", action="store_true", help="Mark current HEAD as audited for all configured repos.")
    return parser.parse_args(argv)


def render_commit_counter(statuses: list[dict[str, object]]) -> str:
    lines = ["# Watcher Doc Commit Counter", ""]
    for item in statuses:
        due = "due" if item["due"] else "skip"
        lines.append(
            f"- {item['name']}: {due}; commits_since_audit={item['commits_since_audit']}; "
            f"threshold={item['commit_threshold']}; config_changed={item['config_changed']}; "
            f"head={str(item['head'])[:12]}"
        )
    return "\n".join(lines) + "\n"


def run_commit_counter(
    *,
    config_path: Path,
    state_dir: Path,
    mark: bool = False,
) -> tuple[str, list[dict[str, object]]]:
    config = load_config(config_path)
    state = load_state(state_dir)
    statuses = [repo_status(repo, state) for repo in config["repos"]]
    output = render_commit_counter(statuses)
    if mark:
        mark_current(state_dir, state, statuses)
        output += f"\nupdated state: {state_path(state_dir)}\n"
    return output, statuses


def _run_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state_dir = resolve_state_dir(args.state_dir)
    output, _statuses = run_commit_counter(
        config_path=expand_path(args.config),
        state_dir=state_dir,
        mark=args.mark_current,
    )
    print(output, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run_main(argv)
    except AuditFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
