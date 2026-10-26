#!/usr/bin/env python3
"""Read-only Codex hook diagnostics; Rust owns all hook configuration writes."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .runtime_paths import (
    CODEX_HOME,
    DEFAULT_HOOK_TARGET,
    expand_path,
)
from ..repository_source import resolve_repository_source


DEFAULT_TARGET = DEFAULT_HOOK_TARGET
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop")
STATUS_PREFIX = "Watcher skill:"
LEGACY_STATUS_PREFIX = "Skill Watcher:"
LEGACY_ADAPTER_NAME = "codex_hook_adapter.py"


def default_python() -> Path:
    # The runtime was launched with its explicit interpreter; never guess an
    # installer/shared/project environment or mutate one during diagnostics.
    return Path(sys.executable)


def adapter_path(repo_root: str | Path | None = None) -> Path:
    return resolve_repository_source(repo_root).watcher_cli


def skill_watcher_command(
    python_path: Path | None = None,
    adapter: Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> str:
    source = resolve_repository_source(repo_root)
    args = [
        str(python_path or default_python()),
        "-B",
        str(adapter or source.watcher_cli),
        "skill",
        "observe",
        "--repo-root",
        str(source.root),
    ]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return " ".join(shlex.quote(arg) for arg in args)


def desired_handler(
    event: str,
    *,
    python_path: Path | None = None,
    adapter: Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "type": "command",
        "async": False,
        "command": skill_watcher_command(
            python_path,
            adapter,
            repo_root=repo_root,
        ),
        "timeoutSec": 10,
        "statusMessage": f"{STATUS_PREFIX} observe {event}",
    }


def desired_group(
    event: str,
    *,
    python_path: Path | None = None,
    adapter: Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "hooks": [
            desired_handler(
                event,
                python_path=python_path,
                adapter=adapter,
                repo_root=repo_root,
            )
        ]
    }


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


def dump_config(config: dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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
