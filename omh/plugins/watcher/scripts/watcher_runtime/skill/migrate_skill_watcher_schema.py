#!/usr/bin/env python3
"""Reset Watcher skill runtime state for the current event schema."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .codex_hook_adapter import (
    SCHEMA_VERSION,
    discover_skill_metadata,
    write_dynamic_monitored_skills,
)
from .runtime_paths import ensure_runtime_dirs, log_file_path, state_dir_from_env_or_arg, turns_dir


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def archive_log(state_dir: Path, log_file: Path) -> Path | None:
    if not log_file.is_file() or log_file.stat().st_size == 0:
        return None
    archive_dir = state_dir / "archives" / f"pre-schema-v{SCHEMA_VERSION}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / f"events-{timestamp()}.jsonl"
    shutil.move(str(log_file), str(destination))
    return destination


def reset_turn_state(state_dir: Path) -> int:
    directory = turns_dir(state_dir)
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob("*.json"):
        path.unlink()
        removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill reset-schema",
        description="Reset Watcher skill runtime state for schema v2.",
    )
    parser.add_argument("--state-dir", help="Runtime state directory. Defaults to $CODEX_HOME/watcher/skill.")
    parser.add_argument("--log-file", help="Explicit JSONL log path. Overrides --state-dir logs/events.jsonl.")
    parser.add_argument(
        "--repo-root",
        help="Canonical oh-my-harness repository root. Defaults to $OH_MY_HARNESS_ROOT.",
    )
    parser.add_argument(
        "--reset-runtime-state",
        action="store_true",
        help="Required acknowledgement that old events and turn state should be archived/reset.",
    )
    args = parser.parse_args(argv)
    if not args.reset_runtime_state:
        raise SystemExit("refusing to migrate without --reset-runtime-state")

    metadata = discover_skill_metadata(args.repo_root)
    state_dir = state_dir_from_env_or_arg(args.state_dir)
    log_file = log_file_path(state_dir, args.log_file)
    ensure_runtime_dirs(state_dir)
    archived = archive_log(state_dir, log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("", encoding="utf-8")
    removed_turns = reset_turn_state(state_dir)
    metadata_update = write_dynamic_monitored_skills(state_dir, metadata)

    print(f"schema_version: {SCHEMA_VERSION}")
    print(f"state_dir: {state_dir}")
    print(f"archived_events: {archived or 'none'}")
    print(f"reset_turn_state_files: {removed_turns}")
    print(f"metadata_cache: {metadata_update['path']}")
    print(f"metadata_skills: {metadata_update['skill_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
