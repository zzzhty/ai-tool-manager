#!/usr/bin/env python3
"""Shared Watcher doc audit runtime primitives.

The CLI scripts and audit cockpit are adapters over this module. Keep file
format, config, state, and report metadata rules here so those rules have one
test surface.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .audit_repo import (
    AuditFailure,
    expand_path,
    normalize_skill_root_candidates,
    paths_use_repo_skill_root,
    require_git_repo,
    resolve_repo_skill_root,
    run_git,
)

DEFAULT_CONFIG = Path("config/repos.json")
CONFIG_HASH_KEYS = (
    "path",
    "profile",
    "docs",
    "skill_root_candidates",
    "authority_paths",
    "watch_terms",
    "link_validation",
    "finding_policy",
    "check_change_alignment",
    "recent_limit",
    "since_ref",
    "commit_threshold",
)


def resolve_config_path(
    *,
    plugin_root: Path,
    raw: str | None = None,
    configured: str | None = None,
) -> Path:
    selected = raw or configured
    if selected:
        path = expand_path(selected)
        if not path.is_absolute():
            path = (plugin_root / path).resolve()
        return path

    private_config = plugin_root / "config" / "repos.json"
    if private_config.exists():
        return private_config
    return plugin_root / "config" / "repos.example.json"


def resolve_audit_state_dir(
    raw: str | None = None, configured: str | None = None
) -> Path:
    selected = raw or configured
    if selected:
        return expand_path(selected)
    env_state_dir = os.environ.get("WATCHER_DOC_STATE_DIR")
    if env_state_dir:
        return expand_path(env_state_dir)
    codex_home = expand_path(os.environ.get("CODEX_HOME", "~/.codex"))
    return codex_home / "watcher" / "doc"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AuditFailure(f"config file does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditFailure(
            f"invalid JSON config {path}: line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
        raise AuditFailure(f"config {path} must contain a top-level repos array")

    config_dir = path.parent.resolve()
    resolved_repos: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in data["repos"]:
        if not isinstance(item, dict):
            raise AuditFailure(f"config {path} repos entries must be objects")
        repo = dict(item)
        raw_path = repo.get("path")
        if isinstance(raw_path, str):
            repo_path = expand_path(raw_path)
            if not repo_path.is_absolute():
                repo_path = (config_dir / repo_path).resolve()
            repo["path"] = str(repo_path)
        name = repo_name(repo)
        if name in seen_names:
            raise AuditFailure(f"duplicate repo/profile name: {name}")
        seen_names.add(name)
        resolved_repos.append(repo)
    data["repos"] = resolved_repos
    return data


def state_path(state_dir: Path) -> Path:
    return state_dir / "repo-state.json"


def load_state(state_dir: Path) -> dict[str, Any]:
    path = state_path(state_dir)
    if not path.exists():
        return {"repos": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuditFailure(
            f"invalid state JSON {path}: line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(data, dict):
        raise AuditFailure(f"state file must contain an object: {path}")
    repos = data.setdefault("repos", {})
    if not isinstance(repos, dict):
        raise AuditFailure(f"state repos must contain an object: {path}")
    return data


def save_state(state_dir: Path, state: dict[str, Any]) -> None:
    path = state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise AuditFailure(f"failed to write state file {path}: {exc}") from exc


def repo_name(repo_config: dict[str, Any]) -> str:
    return str(repo_config.get("name") or Path(str(repo_config.get("path", ""))).name)


def authority_paths(repo_config: dict[str, Any]) -> list[str]:
    canonical = repo_config.get("authority_paths")
    legacy = repo_config.get("source_of_truth")
    if canonical is not None and legacy is not None:
        name = repo_name(repo_config)
        raise AuditFailure(
            f"repo {name} config must not combine authority_paths with legacy source_of_truth"
        )
    selected = canonical if canonical is not None else legacy
    if selected is None:
        return []
    if not isinstance(selected, list) or not all(
        isinstance(item, str) and item for item in selected
    ):
        name = repo_name(repo_config)
        raise AuditFailure(f"repo {name} authority_paths must be a string list")
    return list(selected)


def docs_paths(repo_config: dict[str, Any]) -> list[str]:
    selected = repo_config.get("docs")
    if selected is None:
        return []
    if not isinstance(selected, list) or not all(
        isinstance(item, str) and item for item in selected
    ):
        name = repo_name(repo_config)
        raise AuditFailure(f"repo {name} docs must be a string list")
    return list(selected)


def skill_root_candidates(repo_config: dict[str, Any]) -> list[str]:
    selected = repo_config.get("skill_root_candidates")
    try:
        return list(normalize_skill_root_candidates(selected))
    except AuditFailure as exc:
        name = repo_name(repo_config)
        raise AuditFailure(f"repo {name} invalid skill root candidates: {exc}") from exc


def repo_uses_resolved_skill_root(repo_config: dict[str, Any]) -> bool:
    configured_docs = docs_paths(repo_config)
    configured_authority_paths = authority_paths(repo_config)
    return (
        not configured_docs
        or paths_use_repo_skill_root(configured_docs)
        or paths_use_repo_skill_root(configured_authority_paths)
    )


def repo_state(state: dict[str, Any], name: str) -> dict[str, Any]:
    repos = state.get("repos", {})
    if not isinstance(repos, dict):
        return {}
    item = repos.get(name, {})
    return item if isinstance(item, dict) else {}


def normalized_repo_config(
    repo_config: dict[str, Any], *, repo: Path | None = None
) -> dict[str, Any]:
    normalized = {
        key: repo_config.get(key) for key in CONFIG_HASH_KEYS if key in repo_config
    }
    configured_authority_paths = authority_paths(repo_config)
    if configured_authority_paths:
        normalized["authority_paths"] = configured_authority_paths
    if repo is not None and repo_uses_resolved_skill_root(repo_config):
        resolution = resolve_repo_skill_root(repo, skill_root_candidates(repo_config))
        normalized["resolved_skill_root"] = resolution["selected"]
    return normalized


def repo_config_hash(repo_config: dict[str, Any], *, repo: Path | None = None) -> str:
    payload = json.dumps(
        normalized_repo_config(repo_config, repo=repo),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def count_since(repo: Path, last_revision: str | None) -> int:
    if not last_revision:
        output = run_git(repo, ["rev-list", "--count", "HEAD"])
        return int(output or "0")
    output = run_git(
        repo, ["rev-list", "--count", f"{last_revision}..HEAD"], allow_failure=True
    )
    if output.strip().isdigit():
        return int(output)
    total = run_git(repo, ["rev-list", "--count", "HEAD"])
    return int(total or "0")


def repo_status(repo_config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    name = repo_name(repo_config)
    path_raw = repo_config.get("path")
    if not path_raw:
        raise AuditFailure(f"repo {name} is missing required path")
    repo = require_git_repo(expand_path(str(path_raw)))
    head = run_git(repo, ["rev-parse", "HEAD"])
    threshold = int(repo_config.get("commit_threshold") or 0)
    current_state = repo_state(state, name)
    last = current_state.get("last_audited_revision")
    current_config_hash = repo_config_hash(repo_config, repo=repo)
    last_config_hash = current_state.get("config_hash")
    config_changed = last_config_hash != current_config_hash
    count = count_since(repo, last if isinstance(last, str) else None)
    due = threshold <= 0 or count >= threshold or not last or config_changed
    return {
        "name": name,
        "path": str(repo),
        "head": head,
        "last_audited_revision": last,
        "config_hash": current_config_hash,
        "last_config_hash": last_config_hash,
        "config_changed": config_changed,
        "commit_threshold": threshold,
        "commits_since_audit": count,
        "due": due,
        "skill_root": (
            resolve_repo_skill_root(repo, skill_root_candidates(repo_config))[
                "selected"
            ]
            if repo_uses_resolved_skill_root(repo_config)
            else None
        ),
    }


def finding_records(current_state: dict[str, Any]) -> list[dict[str, str]]:
    findings = current_state.get("findings")
    if not isinstance(findings, list):
        return []
    records: list[dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "fingerprint": str(item.get("fingerprint") or ""),
                "classification": str(item.get("classification") or "actionable"),
                "severity": str(item.get("severity") or "Unknown"),
                "title": str(item.get("title") or "Untitled finding"),
                "evidence": str(item.get("evidence") or ""),
            }
        )
    return records


def repo_read_status(
    repo_config: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    name = repo_name(repo_config)
    raw_path = repo_config.get("path")
    current_state = repo_state(state, name)
    current_config_hash = repo_config_hash(repo_config)
    base: dict[str, Any] = {
        "name": name,
        "configured_path": str(raw_path or ""),
        "profile": str(repo_config.get("profile") or "default"),
        "docs": docs_paths(repo_config),
        "skill_root_candidates": skill_root_candidates(repo_config),
        "authority_paths": authority_paths(repo_config),
        "watch_terms": list(repo_config.get("watch_terms") or []),
        "link_validation": repo_config.get("link_validation") or "markdown-relative",
        "finding_policy": str(repo_config.get("finding_policy") or "actionable"),
        "check_change_alignment": bool(repo_config.get("check_change_alignment", True)),
        "recent_limit": int(repo_config.get("recent_limit") or 5),
        "commit_threshold": int(repo_config.get("commit_threshold") or 0),
        "state": current_state,
        "findings": finding_records(current_state),
        "config_hash": current_config_hash,
        "last_config_hash": current_state.get("config_hash"),
    }
    if not raw_path:
        return {
            **base,
            "status": "error",
            "error": f"repo {name} is missing required path",
        }
    try:
        status = repo_status(repo_config, state)
    except AuditFailure as exc:
        return {
            **base,
            "status": "error",
            "error": str(exc),
            "due": True,
        }
    return {
        **base,
        "status": "ok",
        "path": status["path"],
        "head": status["head"],
        "last_audited_revision": status["last_audited_revision"],
        "config_changed": status["config_changed"],
        "commits_since_audit": status["commits_since_audit"],
        "due": status["due"],
        "config_hash": status["config_hash"],
        "skill_root": status["skill_root"],
    }


def repo_statuses(
    config: dict[str, Any], state: dict[str, Any]
) -> list[dict[str, Any]]:
    return [repo_read_status(repo_config, state) for repo_config in config["repos"]]


def mark_current(
    state_dir: Path,
    state: dict[str, Any],
    statuses: list[dict[str, Any]],
    findings_by_name: dict[str, list[dict[str, str]]] | None = None,
) -> None:
    repos = state.setdefault("repos", {})
    timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    for item in statuses:
        previous = repos.get(item["name"], {})
        repos[item["name"]] = {
            "path": item["path"],
            "last_audited_revision": item["head"],
            "config_hash": item.get("config_hash"),
            "updated_at": timestamp,
        }
        if findings_by_name is not None and item["name"] in findings_by_name:
            repos[item["name"]]["findings"] = findings_by_name[item["name"]]
        elif isinstance(previous, dict) and "findings" in previous:
            repos[item["name"]]["findings"] = previous["findings"]
    save_state(state_dir, state)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AuditFailure(f"failed to read {path}: {exc}") from exc


def parse_int_suffix(line: str) -> int | None:
    match = re.search(r":\s*(\d+)\s*$", line)
    return int(match.group(1)) if match else None


def parse_report_lines(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "generated_at": None,
        "config_path": None,
        "audited_repos": None,
        "skipped_repos": None,
        "failed_repos": None,
        "repo_sections": [],
    }
    for line in lines:
        if line.startswith("- Generated:"):
            metadata["generated_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Config:"):
            metadata["config_path"] = line.split(":", 1)[1].strip().strip("`")
        elif line.startswith("- Audited repos:"):
            metadata["audited_repos"] = parse_int_suffix(line)
        elif line.startswith("- Skipped repos:"):
            metadata["skipped_repos"] = parse_int_suffix(line)
        elif line.startswith("- Failed repos:"):
            metadata["failed_repos"] = parse_int_suffix(line)
        elif line.startswith("## Repo:"):
            metadata["repo_sections"].append(line.split(":", 1)[1].strip())
    return metadata


def report_metadata(path: Path) -> dict[str, Any]:
    text = read_text(path)
    lines = text.splitlines()
    title = next(
        (line.removeprefix("# ").strip() for line in lines if line.startswith("# ")),
        path.name,
    )
    stat = path.stat()
    return {
        "id": path.name,
        "path": str(path),
        "title": title,
        "modified_at": dt.datetime.fromtimestamp(stat.st_mtime)
        .astimezone()
        .isoformat(timespec="seconds"),
        "size_bytes": stat.st_size,
        **parse_report_lines(lines[:200]),
    }


def list_reports(reports_dir: Path) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []
    reports = [
        report_metadata(path) for path in reports_dir.glob("*.md") if path.is_file()
    ]
    return sorted(reports, key=lambda item: item["modified_at"], reverse=True)


def safe_child_path(root: Path, name: str, *, label: str) -> Path:
    if "/" in name or "\\" in name or not name:
        raise AuditFailure(f"invalid {label}: {name}")
    path = (root / name).resolve()
    resolved_root = root.resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as exc:
        raise AuditFailure(f"invalid {label}: {name}") from exc
    return path
