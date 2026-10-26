#!/usr/bin/env python3
"""Read-only catalog/history diagnostics after retirement of skill-watcher hooks."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog_metadata import discover_skill_metadata, load_runtime_metadata
from .codex_hook_config import DEFAULT_TARGET, is_skill_watcher_handler, load_config, validate_hook_shape
from .runtime_paths import DEFAULT_STATE_DIR, expand_path
from ..repository_source import resolve_repository_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill doctor",
        description="Read-only catalog/history checks; skill-watcher hooks are retired. No sample events are collected.",
    )
    parser.add_argument("--repo-root", help="Verified payload with canonical-catalog.json; defaults to ATM_HARNESS_ROOT.")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--hook-target", default=str(DEFAULT_TARGET), help="Inspect retired entries without modifying them.")
    parser.add_argument("--python", dest="python_path", default=sys.executable, help="Interpreter to inspect; no installation or execution.")
    args = parser.parse_args(argv)
    source = resolve_repository_source(args.repo_root)
    if not expand_path(args.python_path).is_file():
        print("FAIL interpreter does not exist", file=sys.stderr)
        return 1
    metadata = discover_skill_metadata(source.root)
    print(f"OK   canonical catalog validated: {len(metadata['skills'])} identities")
    state = expand_path(args.state_dir)
    if state.exists() and not state.is_dir():
        print("FAIL history state is not a directory", file=sys.stderr)
        return 1
    # Cache validation is read-only and never discovers or rewrites old logs.
    load_runtime_metadata(state, allow_discovery=False)
    target = expand_path(args.hook_target)
    config = load_config(target)
    validate_hook_shape(config)
    retired = sum(
        is_skill_watcher_handler(handler)
        for groups in (config.get("hooks") or {}).values()
        for group in groups
        for handler in (group.get("hooks") or [])
    )
    if retired:
        print(f"WARN {retired} retired skill-watcher handlers remain at {target}; use atm uninstall hooks --harness codex only with proven ownership. Unowned entries are preserved.")
    print("doctor passed; skill-watcher collection is retired, no events written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
