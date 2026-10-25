#!/usr/bin/env python3
"""Shared Watcher skill proposal artifact helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime_paths import rejected_dir, safe_slug, utc_now as runtime_utc_now, utc_now_text


ALLOWED_STATUSES = {"draft", "needs-validation", "accepted", "rejected"}


def utc_now() -> str:
    return utc_now_text()


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def proposal_id_for(timestamp: str, skill_name: str) -> str:
    return f"{timestamp}-{safe_slug(skill_name, fallback='skill')}"


def render_frontmatter(
    *,
    proposal_id: str,
    skill_name: str,
    skill_dir: Path,
    snapshot_path: Path,
    timestamp: str,
) -> list[str]:
    return [
        "---",
        "schema_version: 1",
        'proposal_type: "skill-maintenance"',
        f"proposal_id: {yaml_string(proposal_id)}",
        'status: "draft"',
        f"generated_at: {yaml_string(timestamp)}",
        f"skill_name: {yaml_string(skill_name)}",
        f"skill_dir: {yaml_string(str(skill_dir))}",
        f"snapshot_path: {yaml_string(str(snapshot_path))}",
        "---",
        "",
    ]


def load_yaml_module():
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyYAML is required for proposal artifact updates. "
            "Run `python3 scripts/bootstrap_tooling_env.py` on Unix or "
            "`py scripts\\bootstrap_tooling_env.py` on Windows from the oh-my-harness repo root, "
            "then invoke Watcher with the manager tooling Python."
        ) from exc
    return yaml


def split_frontmatter(contents: str, path: Path) -> tuple[str, str]:
    if not contents.startswith("---\n"):
        raise SystemExit(f"{path} must start with YAML frontmatter")
    end = contents.find("\n---", 4)
    if end == -1:
        raise SystemExit(f"{path} frontmatter is not closed")
    return contents[4:end], contents[end + 4 :]


def load_proposal(path: Path) -> tuple[dict[str, Any], str]:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to read proposal {path}: {exc}") from exc
    frontmatter_text, body = split_frontmatter(contents, path)
    yaml = load_yaml_module()
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise SystemExit(f"{path} frontmatter is invalid YAML: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise SystemExit(f"{path} frontmatter must be a YAML object")
    return frontmatter, body


def write_proposal(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    yaml = load_yaml_module()
    rendered = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True) + "---" + body
    try:
        path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to write proposal {path}: {exc}") from exc


def validate_status(status: str) -> None:
    if status in ALLOWED_STATUSES:
        return
    allowed = ", ".join(sorted(ALLOWED_STATUSES))
    raise SystemExit(f"invalid status {status!r}; expected one of: {allowed}")


def record_rejected(path: Path, frontmatter: dict[str, Any], state_dir: Path, previous_status: str, reason: str) -> Path:
    output_dir = rejected_dir(state_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = runtime_utc_now().strftime("%Y%m%dT%H%M%SZ")
    proposal_id = str(frontmatter.get("proposal_id") or path.stem)
    safe_id = safe_slug(proposal_id, fallback="proposal")
    output = output_dir / f"{timestamp}-{safe_id}.json"
    payload = {
        "timestamp": utc_now(),
        "proposal": str(path),
        "proposal_id": proposal_id,
        "skill_name": frontmatter.get("skill_name"),
        "previous_status": previous_status,
        "status": "rejected",
        "reason": reason,
    }
    try:
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to write rejected proposal buffer {output}: {exc}") from exc
    return output


def update_status(path: Path, status: str, *, state_dir: Path, reason: str = "") -> tuple[str, Path | None]:
    validate_status(status)
    frontmatter, body = load_proposal(path)
    previous_status = str(frontmatter.get("status") or "")
    frontmatter["status"] = status
    frontmatter["status_updated_at"] = utc_now()
    if reason:
        frontmatter["status_reason"] = reason
    rejected_path = None
    if status == "rejected":
        rejected_path = record_rejected(path, frontmatter, state_dir, previous_status, reason)
    write_proposal(path, frontmatter, body)
    return previous_status, rejected_path
