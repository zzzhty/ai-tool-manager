#!/usr/bin/env python3
"""Shared Watcher skill-domain runtime path helpers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

RUNTIME_DIRS = ("logs", "reports", "proposals", "snapshots", "rejected", "backups", "turns")


def expand_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(str(raw))).expanduser()


CODEX_HOME = expand_path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
MANAGER_HOME = expand_path(
    os.environ.get("OH_MY_HARNESS_HOME", Path.home() / ".oh-my-harness")
)
DEFAULT_STATE_DIR = CODEX_HOME / "watcher" / "skill"
DEFAULT_TOOLING_VENV = MANAGER_HOME / "venv"
DEFAULT_HOOK_TARGET = CODEX_HOME / "hooks.json"


def state_dir_from_env_or_arg(raw_state_dir: str | None) -> Path:
    return expand_path(raw_state_dir or os.environ.get("WATCHER_SKILL_STATE_DIR") or DEFAULT_STATE_DIR)


def ensure_runtime_dirs(state_dir: Path) -> None:
    for name in RUNTIME_DIRS:
        (state_dir / name).mkdir(parents=True, exist_ok=True)


def log_file_path(state_dir: Path, raw_log_file: str | None = None) -> Path:
    return expand_path(raw_log_file) if raw_log_file else state_dir / "logs" / "events.jsonl"


def reports_dir(state_dir: Path) -> Path:
    return state_dir / "reports"


def proposals_dir(state_dir: Path) -> Path:
    return state_dir / "proposals"


def snapshots_dir(state_dir: Path) -> Path:
    return state_dir / "snapshots"


def rejected_dir(state_dir: Path) -> Path:
    return state_dir / "rejected"


def turns_dir(state_dir: Path) -> Path:
    return state_dir / "turns"


def hook_backup_dir(state_dir: Path) -> Path:
    return state_dir / "backups" / "hooks-json"


def report_state_path(state_dir: Path) -> Path:
    return state_dir / "report-state.json"


def safe_slug(value: str, *, fallback: str = "unknown", allowed: str = "-_") -> str:
    slug = "".join(char if char.isalnum() or char in allowed else "-" for char in value).strip("-")
    return slug or fallback


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_text() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")
