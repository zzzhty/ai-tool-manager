#!/usr/bin/env python3
"""Collect and append a redacted Watcher skill event."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from .redact_event import redact_event
from .runtime_paths import (
    CODEX_HOME,
    DEFAULT_STATE_DIR,
    ensure_runtime_dirs,
    expand_path,
    log_file_path,
    state_dir_from_env_or_arg,
    utc_now_text,
)


SCHEMA_VERSION = 2
DEFAULT_AGENT = "codex"
EVENT_FIELDS = [
    "schema_version",
    "event_id",
    "timestamp",
    "agent",
    "event_type",
    "workspace",
    "session_id",
    "trigger_reason",
    "tools_used",
    "files_touched",
    "outcome",
    "task_outcome",
    "failure_type",
    "skill_attribution",
    "user_feedback",
    "tests_or_checks",
    "notes",
]


def utc_now() -> str:
    return utc_now_text()


def read_event(path: str | None) -> dict[str, Any]:
    if path:
        try:
            raw = expand_path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"failed to read input path {path}: {exc}") from exc
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("no event JSON provided on stdin or --input")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        source = path or "stdin"
        raise SystemExit(f"invalid event JSON from {source}: line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("event JSON must be an object")
    return payload


def normalize_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def merge_flag(event: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        event[key] = value


def normalize_event(event: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    merge_flag(event, "agent", args.agent)
    merge_flag(event, "event_type", args.event_type)
    merge_flag(event, "workspace", args.workspace)
    merge_flag(event, "session_id", args.session_id)
    merge_flag(event, "trigger_reason", args.trigger_reason)
    merge_flag(event, "outcome", args.outcome)
    merge_flag(event, "failure_type", args.failure_type)
    merge_flag(event, "user_feedback", args.user_feedback)
    merge_flag(event, "notes", args.notes)
    if args.skill and "skill_attribution" not in event:
        event["skill_attribution"] = {
            "primary": {
                "name": args.skill,
                "source": "manual",
                "confidence": "unknown",
            },
            "supporting": [],
            "effective": [args.skill],
            "mentioned": [],
        }

    if args.tool:
        event["tools_used"] = normalize_list(event.get("tools_used")) + args.tool
    if args.file_touched:
        event["files_touched"] = normalize_list(event.get("files_touched")) + args.file_touched
    if args.check:
        event["tests_or_checks"] = normalize_list(event.get("tests_or_checks")) + args.check

    event.setdefault("schema_version", SCHEMA_VERSION)
    event.setdefault("event_id", str(uuid.uuid4()))
    event.setdefault("timestamp", utc_now())
    event.setdefault("agent", DEFAULT_AGENT)
    event.setdefault("event_type", "unknown")
    event.setdefault("workspace", "")
    event.setdefault("session_id", "")
    event.setdefault("trigger_reason", "")
    event.setdefault("tools_used", [])
    event.setdefault("files_touched", [])
    event.setdefault("outcome", "unknown")
    event.setdefault("task_outcome", "")
    event.setdefault("failure_type", "")
    event.setdefault("skill_attribution", {"primary": None, "supporting": [], "effective": [], "mentioned": []})
    event.setdefault("user_feedback", "")
    event.setdefault("tests_or_checks", [])
    event.setdefault("notes", "")

    for key in ("tools_used", "files_touched", "tests_or_checks"):
        event[key] = normalize_list(event.get(key))

    ordered = {key: event.get(key) for key in EVENT_FIELDS}
    extras = {key: value for key, value in event.items() if key not in ordered}
    ordered.update(extras)
    return ordered


def append_event(event: dict[str, Any], log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_file.open("a", encoding="utf-8") as handle:
            json.dump(event, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        raise SystemExit(f"failed to append event to {log_file}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="watcher skill collect-event", description="Append a redacted Watcher skill event.")
    parser.add_argument("--input", help="Path to event JSON. Defaults to stdin.")
    parser.add_argument("--state-dir", help="Runtime state directory. Defaults to $CODEX_HOME/watcher/skill.")
    parser.add_argument("--log-file", help="Explicit JSONL log path. Overrides --state-dir logs/events.jsonl.")
    parser.add_argument("--agent")
    parser.add_argument("--event-type")
    parser.add_argument("--workspace")
    parser.add_argument("--session-id")
    parser.add_argument("--skill", help="Primary skill name for manual v2 skill attribution.")
    parser.add_argument("--trigger-reason")
    parser.add_argument("--outcome")
    parser.add_argument("--failure-type")
    parser.add_argument("--user-feedback")
    parser.add_argument("--notes")
    parser.add_argument("--tool", action="append", help="Tool name to append to tools_used.")
    parser.add_argument("--file-touched", action="append", help="Path to append to files_touched.")
    parser.add_argument("--check", action="append", help="Validation check to append to tests_or_checks.")
    parser.add_argument("--dry-run", action="store_true", help="Print redacted event without appending.")
    args = parser.parse_args(argv)

    state_dir = state_dir_from_env_or_arg(args.state_dir)
    log_file = log_file_path(state_dir, args.log_file)
    event = normalize_event(read_event(args.input), args)
    event = redact_event(event)

    if args.dry_run:
        json.dump(event, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    ensure_runtime_dirs(state_dir)
    append_event(event, log_file)
    print(f"appended event {event['event_id']} to {log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
