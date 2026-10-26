#!/usr/bin/env python3
"""Read-only recognition of retired hooks; receipt-bound removal belongs to Rust."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .runtime_paths import DEFAULT_HOOK_TARGET

DEFAULT_TARGET = DEFAULT_HOOK_TARGET
STATUS_PREFIX = "Watcher skill:"
LEGACY_STATUS_PREFIX = "Skill Watcher:"
LEGACY_ADAPTER_NAME = "codex_hook_adapter.py"

def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to read hook config {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid hook config JSON {path}: line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"hook config {path} must contain a JSON object")
    return data


def validate_hook_shape(config: dict[str, Any]) -> None:
    hooks = config.get("hooks")
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise SystemExit("hook config field `hooks` must be an object")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise SystemExit(f"hook config event {event!r} must be a list")
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                raise SystemExit(f"hook config event {event!r} group {index} must be an object")
            handlers = group.get("hooks")
            if handlers is not None and not isinstance(handlers, list):
                raise SystemExit(f"hook config event {event!r} group {index} field `hooks` must be a list")


def is_skill_watcher_handler(handler: Any) -> bool:
    if not isinstance(handler, dict):
        return False
    command = str(handler.get("command") or "")
    status = str(handler.get("statusMessage") or "")
    return (
        status.startswith(STATUS_PREFIX)
        or status.startswith(LEGACY_STATUS_PREFIX)
        or (LEGACY_ADAPTER_NAME in command and ("skill-watcher" in command or "watcher" in command))
    )
