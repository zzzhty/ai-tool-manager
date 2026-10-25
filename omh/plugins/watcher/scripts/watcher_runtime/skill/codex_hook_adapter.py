#!/usr/bin/env python3
"""Normalize Codex hook payloads into Watcher skill-domain JSONL events."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .collect_event import append_event, ensure_runtime_dirs, normalize_event, state_dir_from_env_or_arg
from .redact_event import redact_event, redact_string
from ..repository_source import (
    load_repository_skill_catalog,
    resolve_repository_path,
    resolve_repository_source,
)
from .runtime_paths import log_file_path, safe_slug as runtime_safe_slug, turns_dir, utc_now_text


SCHEMA_VERSION = 2
SKILL_METADATA_SCHEMA_VERSION = 1
SUPPORTED_HOOK_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"}
SUMMARY_LIMIT = 160
METADATA_CACHE_FILE = "skill-metadata-cache.json"
SCHEMA_VERSION_FILE = "schema-version.json"
DEFAULT_ROLE = "entrypoint"
VALID_ROLES = {"entrypoint", "wrapper", "discipline", "specialized"}
VALID_ALIAS_MATCHES = {"exact", "phrase", "token"}
FAILURE_TEXT_RE = re.compile(
    r"(?:exit(?:ed)?\s+(?:with\s+)?(?:code|status)\s+[1-9]\d*|"
    r"non[- ]zero\s+exit|traceback|exception|error)",
    re.IGNORECASE,
)
TOKEN_RE_TEMPLATE = r"(?<![a-z0-9_-]){alias}(?![a-z0-9_-])"
LOGICAL_GROUP_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class HookRuntimePaths:
    state_dir: Path
    log_file: Path


@dataclass(frozen=True)
class HookResult:
    event: dict[str, Any]
    persisted: bool
    hook_event_name: str


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("no Codex hook JSON provided on stdin")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid Codex hook JSON: line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Codex hook payload must be a JSON object")
    return payload


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compact_text(value: str, *, limit: int = SUMMARY_LIMIT) -> str:
    redacted = redact_string(value)
    compacted = " ".join(redacted.split())
    if not compacted:
        return ""
    if len(compacted) <= 12:
        return "[omitted]"
    if len(compacted) <= limit:
        prefix_length = min(len(compacted) - 1, max(12, len(compacted) // 2))
        return compacted[:prefix_length] + "..."
    return compacted[: limit - 3] + "..."


def summarize_text(value: str, *, limit: int = SUMMARY_LIMIT) -> dict[str, Any]:
    return {
        "type": "text",
        "length": len(value),
        "sha256": sha256_text(value),
        "summary": compact_text(value, limit=limit),
    }


def json_fingerprint(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        raw = repr(value)
    return raw


def summarize_json_value(value: Any, *, limit: int = SUMMARY_LIMIT) -> dict[str, Any]:
    if isinstance(value, str):
        return summarize_text(value, limit=limit)

    redacted = redact_event(value)
    raw = json_fingerprint(redacted)
    summary: dict[str, Any] = {
        "type": type(value).__name__,
        "length": len(raw),
        "sha256": sha256_text(raw),
        "summary": compact_text(raw, limit=limit),
    }
    if isinstance(value, dict):
        summary["keys"] = sorted(str(key) for key in value.keys())[:20]
    elif isinstance(value, list):
        summary["items"] = len(value)
    return summary


def utc_now() -> str:
    return utc_now_text()


def parse_env_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values = re.split(r"[,\n;]+", raw)
    return tuple(value.strip() for value in values if value.strip())


def watcher_skill_name(source: Any) -> str:
    return f"{source.plugin}:{source.name}"


def discover_watcher_skill_identities(repo_root: str | Path | None = None) -> tuple[str, ...]:
    """Return durable Watcher identities derived from the canonical callable catalog."""

    source = resolve_repository_source(repo_root)
    catalog = load_repository_skill_catalog(source)
    return tuple(sorted(watcher_skill_name(skill) for skill in catalog.sources))


def metadata_cache_path(state_dir: Path) -> Path:
    return state_dir / METADATA_CACHE_FILE


def schema_version_path(state_dir: Path) -> Path:
    return state_dir / SCHEMA_VERSION_FILE


def default_aliases_for_skill(skill_name: str) -> list[dict[str, str]]:
    aliases = [{"value": skill_name, "kind": "skill_name", "match": "phrase"}]
    if ":" in skill_name:
        aliases.append({"value": skill_name.rsplit(":", 1)[-1], "kind": "slug", "match": "token"})
    return aliases


def normalize_alias(raw_alias: Any, *, manifest_path: Path, skill_name: str) -> dict[str, str]:
    if isinstance(raw_alias, str):
        raw_alias = {"value": raw_alias, "kind": "phrase", "match": "phrase"}
    if not isinstance(raw_alias, dict):
        raise SystemExit(f"invalid alias for {skill_name} in {manifest_path}: expected object")
    value = raw_alias.get("value")
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"invalid alias for {skill_name} in {manifest_path}: missing value")
    kind = raw_alias.get("kind")
    match = raw_alias.get("match")
    kind_value = kind if isinstance(kind, str) and kind.strip() else "phrase"
    match_value = match if isinstance(match, str) and match.strip() else "phrase"
    if match_value not in VALID_ALIAS_MATCHES:
        raise SystemExit(f"invalid alias match for {skill_name} in {manifest_path}: {match_value}")
    return {
        "value": value.strip(),
        "kind": kind_value.strip(),
        "match": match_value,
    }


def normalize_manifest_skill(
    raw_skill: Any,
    *,
    manifest_path: Path,
    skill_name: str,
) -> dict[str, Any]:
    if raw_skill is None:
        raw_skill = {}
    if not isinstance(raw_skill, dict):
        raise SystemExit(f"invalid skill metadata for {skill_name} in {manifest_path}: expected object")
    role = raw_skill.get("role", DEFAULT_ROLE)
    if not isinstance(role, str) or role not in VALID_ROLES:
        raise SystemExit(f"invalid role for {skill_name} in {manifest_path}: {role!r}")
    raw_aliases = raw_skill.get("aliases", default_aliases_for_skill(skill_name))
    if not isinstance(raw_aliases, list):
        raise SystemExit(f"invalid aliases for {skill_name} in {manifest_path}: expected list")
    aliases = [normalize_alias(alias, manifest_path=manifest_path, skill_name=skill_name) for alias in raw_aliases]
    raw_supporting = raw_skill.get("supporting_skills", [])
    if not isinstance(raw_supporting, list):
        raise SystemExit(f"invalid supporting_skills for {skill_name} in {manifest_path}: expected list")
    supporting = []
    for item in raw_supporting:
        if not isinstance(item, str) or not item.strip():
            raise SystemExit(f"invalid supporting skill for {skill_name} in {manifest_path}: {item!r}")
        supporting.append(item.strip())
    logical_group = raw_skill.get("logical_group")
    if logical_group is not None:
        if not isinstance(logical_group, str) or not LOGICAL_GROUP_RE.fullmatch(logical_group):
            raise SystemExit(
                f"invalid logical_group for {skill_name} in {manifest_path}: {logical_group!r}; "
                "expected a lowercase kebab-case name"
            )
    normalized = {
        "role": role,
        "aliases": aliases,
        "supporting_skills": sorted(dict.fromkeys(supporting)),
    }
    if logical_group:
        normalized["logical_group"] = logical_group
    return normalized


def load_attribution_overlay(
    plugin_dir: Path,
    *,
    canonical_identities: set[str],
    repository_root: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Overlay non-callable Watcher attribution metadata onto catalog identities."""

    skills = {
        skill_name: normalize_manifest_skill(None, manifest_path=plugin_dir, skill_name=skill_name)
        for skill_name in sorted(canonical_identities)
    }
    legacy_names: dict[str, str] = {}
    manifest_path = plugin_dir / ".codex-plugin" / "skill-watcher.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return skills, legacy_names
    manifest_path = resolve_repository_path(
        manifest_path,
        root=repository_root,
        label="Watcher skill attribution overlay",
        kind="file",
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid skill metadata JSON {manifest_path}: line {exc.lineno}, column {exc.colno}") from exc
    except OSError as exc:
        raise SystemExit(f"failed to read skill metadata {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SystemExit(f"skill metadata manifest must be an object: {manifest_path}")
    schema_version = manifest.get("schema_version")
    if schema_version != SKILL_METADATA_SCHEMA_VERSION:
        raise SystemExit(
            f"unsupported skill metadata schema_version {schema_version!r} in {manifest_path}; "
            f"expected {SKILL_METADATA_SCHEMA_VERSION}"
        )
    raw_skills = manifest.get("skills", {})
    if not isinstance(raw_skills, dict):
        raise SystemExit(f"skill metadata skills must be an object: {manifest_path}")
    for skill_name, raw_skill in raw_skills.items():
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise SystemExit(f"invalid skill metadata key in {manifest_path}: {skill_name!r}")
        if skill_name not in canonical_identities:
            raise SystemExit(f"skill metadata references unknown canonical skill {skill_name} in {manifest_path}")
        skills[skill_name] = normalize_manifest_skill(raw_skill, manifest_path=manifest_path, skill_name=skill_name)
    raw_legacy = manifest.get("legacy_names", {})
    if not isinstance(raw_legacy, dict):
        raise SystemExit(f"skill metadata legacy_names must be an object: {manifest_path}")
    for old_name, new_name in raw_legacy.items():
        if not isinstance(old_name, str) or not isinstance(new_name, str):
            raise SystemExit(f"invalid legacy mapping in {manifest_path}: {old_name!r} -> {new_name!r}")
        if new_name not in canonical_identities:
            raise SystemExit(f"legacy mapping points to unknown canonical skill {new_name} in {manifest_path}")
        legacy_names[old_name] = new_name
    return skills, legacy_names


def discover_skill_metadata(repo_root: str | Path | None = None) -> dict[str, Any]:
    source = resolve_repository_source(repo_root)
    catalog = load_repository_skill_catalog(source)
    identities_by_plugin: dict[str, set[str]] = {}
    for catalog_skill in catalog.sources:
        identities_by_plugin.setdefault(catalog_skill.plugin, set()).add(watcher_skill_name(catalog_skill))

    skills: dict[str, Any] = {}
    legacy_names: dict[str, str] = {}
    for plugin_name, canonical_identities in sorted(identities_by_plugin.items()):
        plugin_dir = catalog.plugins_root / plugin_name
        plugin_skills, plugin_legacy = load_attribution_overlay(
            plugin_dir,
            canonical_identities=canonical_identities,
            repository_root=source.root,
        )
        overlap = set(skills).intersection(plugin_skills)
        if overlap:
            raise SystemExit(f"duplicate skill metadata entries: {', '.join(sorted(overlap))}")
        skills.update(plugin_skills)
        legacy_overlap = set(legacy_names).intersection(plugin_legacy)
        if legacy_overlap:
            raise SystemExit(f"duplicate legacy skill metadata entries: {', '.join(sorted(legacy_overlap))}")
        legacy_names.update(plugin_legacy)
    for skill_name, metadata in skills.items():
        for supporting in metadata.get("supporting_skills", []):
            if supporting not in skills:
                raise SystemExit(f"skill metadata for {skill_name} references missing supporting skill {supporting}")
    configured = parse_env_list(os.environ.get("WATCHER_SKILL_MONITORED_SKILLS"))
    if configured:
        configured_set = set(configured)
        skills = {name: data for name, data in skills.items() if name in configured_set}
        legacy_names = {old: new for old, new in legacy_names.items() if new in skills}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source_root": str(source.root),
        "skills": dict(sorted(skills.items())),
        "legacy_names": dict(sorted(legacy_names.items())),
    }


def write_schema_marker(state_dir: Path) -> None:
    path = schema_version_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "updated_at": utc_now()}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def require_runtime_schema(state_dir: Path) -> None:
    path = schema_version_path(state_dir)
    if not path.is_file():
        raise SystemExit(f"Watcher skill schema is not initialized at {path}; run migration or SessionStart first")
    cache_path = metadata_cache_path(state_dir)
    if not cache_path.is_file():
        raise SystemExit(f"Watcher skill metadata cache is missing at {cache_path}; run migration or SessionStart first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid Watcher skill schema marker {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Watcher skill schema mismatch at {path}; run migrate_skill_watcher_schema.py")


def load_runtime_metadata(
    state_dir: Path | None = None,
    *,
    allow_discovery: bool = True,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    if state_dir is not None:
        path = metadata_cache_path(state_dir)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"invalid runtime metadata cache {path}: {exc}") from exc
            if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION and isinstance(data.get("skills"), dict):
                return data
            raise SystemExit(f"runtime metadata cache schema mismatch at {path}; run migrate_skill_watcher_schema.py")
    if allow_discovery:
        return discover_skill_metadata(repo_root)
    return {"schema_version": SCHEMA_VERSION, "skills": {}, "legacy_names": {}}


def load_dynamic_monitored_skills(
    state_dir: Path | None = None,
    *,
    repo_root: str | Path | None = None,
) -> tuple[str, ...]:
    if state_dir is None:
        return tuple(load_runtime_metadata(None, repo_root=repo_root).get("skills", {}).keys())
    path = metadata_cache_path(state_dir)
    if not path.is_file():
        return ()
    data = load_runtime_metadata(state_dir, allow_discovery=False)
    skills = data.get("skills")
    return tuple(sorted(skills)) if isinstance(skills, dict) else ()


def write_dynamic_monitored_skills(state_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Persist metadata that was fully discovered and validated before mutation."""

    path = metadata_cache_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_schema_marker(state_dir)
    skills = metadata.get("skills") if isinstance(metadata.get("skills"), dict) else {}
    legacy_names = metadata.get("legacy_names") if isinstance(metadata.get("legacy_names"), dict) else {}
    return {
        "path": str(path),
        "skill_count": len(skills),
        "legacy_name_count": len(legacy_names),
        "source_root": str(metadata.get("source_root") or ""),
        "updated": bool(skills),
    }


def refresh_dynamic_monitored_skills(
    state_dir: Path,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    metadata = discover_skill_metadata(repo_root)
    return write_dynamic_monitored_skills(state_dir, metadata)


def text_for_matching(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json_fingerprint(value)


def alias_matches(text: str, alias: str, match_strategy: str = "phrase") -> bool:
    normalized_text = text.lower()
    normalized_alias = alias.lower().strip()
    if not normalized_text or not normalized_alias:
        return False
    if match_strategy == "exact":
        return normalized_text.strip() == normalized_alias
    escaped = re.escape(normalized_alias)
    if match_strategy == "token":
        return re.search(TOKEN_RE_TEMPLATE.format(alias=escaped), normalized_text) is not None
    if re.fullmatch(r"[a-z0-9_ -]+", normalized_alias):
        return re.search(TOKEN_RE_TEMPLATE.format(alias=escaped), normalized_text) is not None
    return normalized_alias in normalized_text


def canonical_skill_name(value: Any, metadata: dict[str, Any]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    skills = metadata.get("skills") if isinstance(metadata.get("skills"), dict) else {}
    legacy_names = metadata.get("legacy_names") if isinstance(metadata.get("legacy_names"), dict) else {}
    if raw in skills:
        return raw
    mapped = legacy_names.get(raw)
    return mapped if isinstance(mapped, str) and mapped in skills else None


def match_all_monitored_skills(
    value: Any,
    *,
    state_dir: Path | None = None,
    metadata: dict[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> list[dict[str, str]]:
    text = text_for_matching(value)
    if not text:
        return []
    resolved_metadata = metadata or load_runtime_metadata(state_dir, repo_root=repo_root)
    skills = resolved_metadata.get("skills") if isinstance(resolved_metadata.get("skills"), dict) else {}
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for skill_name, skill_data in skills.items():
        aliases = skill_data.get("aliases") if isinstance(skill_data, dict) else []
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if not isinstance(alias, dict):
                continue
            value = alias.get("value")
            match_strategy = alias.get("match", "phrase")
            if not isinstance(value, str) or not isinstance(match_strategy, str):
                continue
            if alias_matches(text, value, match_strategy):
                if skill_name not in seen:
                    matches.append(
                        {
                            "name": skill_name,
                            "matched_alias": value,
                            "alias_kind": str(alias.get("kind") or ""),
                            "match": match_strategy,
                        }
                    )
                    seen.add(skill_name)
                break
    return matches


def match_monitored_skill(
    value: Any,
    *,
    state_dir: Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, str] | None:
    matches = match_all_monitored_skills(value, state_dir=state_dir, repo_root=repo_root)
    return matches[0] if matches else None


def supporting_skill_entries(primary_name: str, metadata: dict[str, Any]) -> list[dict[str, str]]:
    skills = metadata.get("skills") if isinstance(metadata.get("skills"), dict) else {}
    primary = skills.get(primary_name) if isinstance(skills.get(primary_name), dict) else {}
    supporting = primary.get("supporting_skills") if isinstance(primary, dict) else []
    if not isinstance(supporting, list):
        return []
    return [
        {
            "name": str(name),
            "role": skill_role(str(name), metadata),
            "source": "manifest_dependency",
            "via": primary_name,
        }
        for name in supporting
        if isinstance(name, str) and name in skills
    ]


def skill_role(skill_name: str, metadata: dict[str, Any]) -> str:
    skills = metadata.get("skills") if isinstance(metadata.get("skills"), dict) else {}
    skill = skills.get(skill_name) if isinstance(skills.get(skill_name), dict) else {}
    role = skill.get("role") if isinstance(skill, dict) else None
    return role if isinstance(role, str) and role else DEFAULT_ROLE


def attribution_from_primary(
    primary_match: dict[str, str],
    *,
    source: str,
    confidence: str,
    metadata: dict[str, Any],
    mentioned_matches: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    primary_name = primary_match["name"]
    primary = {
        "name": primary_name,
        "role": skill_role(primary_name, metadata),
        "source": source,
        "matched_alias": primary_match.get("matched_alias", ""),
        "alias_kind": primary_match.get("alias_kind", ""),
        "match": primary_match.get("match", ""),
        "confidence": confidence,
    }
    supporting = supporting_skill_entries(primary_name, metadata)
    effective = [primary_name] + [entry["name"] for entry in supporting]
    mentioned = []
    for match in mentioned_matches or []:
        name = match["name"]
        if name == primary_name:
            continue
        mentioned.append(
            {
                "name": name,
                "source": source,
                "matched_alias": match.get("matched_alias", ""),
                "alias_kind": match.get("alias_kind", ""),
                "match": match.get("match", ""),
            }
        )
    return {
        "primary": primary,
        "supporting": supporting,
        "effective": sorted(dict.fromkeys(effective)),
        "mentioned": mentioned,
    }


def empty_attribution() -> dict[str, Any]:
    return {
        "primary": None,
        "supporting": [],
        "effective": [],
        "mentioned": [],
    }


def infer_skill_attribution(
    payload: dict[str, Any],
    *,
    state_dir: Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any] | None:
    metadata = load_runtime_metadata(state_dir, repo_root=repo_root)
    provided = payload.get("skill_name") or payload.get("skill")
    canonical = canonical_skill_name(provided, metadata)
    if canonical:
        return attribution_from_primary(
            {"name": canonical, "matched_alias": str(provided), "alias_kind": "skill_name", "match": "exact"},
            source="provided",
            confidence="high",
            metadata=metadata,
        )

    if "prompt" in payload:
        matches = match_all_monitored_skills(payload.get("prompt"), metadata=metadata)
        if matches:
            return attribution_from_primary(
                matches[0],
                source="prompt_mention",
                confidence="high",
                metadata=metadata,
                mentioned_matches=matches,
            )

    if "last_assistant_message" in payload:
        matches = match_all_monitored_skills(payload.get("last_assistant_message"), metadata=metadata)
        if matches:
            return attribution_from_primary(
                matches[0],
                source="assistant_announcement",
                confidence="medium",
                metadata=metadata,
                mentioned_matches=matches,
            )

    return None


def user_skill_context(payload: dict[str, Any], attribution: dict[str, Any] | None) -> dict[str, Any] | None:
    primary = attribution.get("primary") if isinstance(attribution, dict) else None
    if not isinstance(primary, dict) or primary.get("source") != "prompt_mention" or "prompt" not in payload:
        return None
    summary = summarize_json_value(payload.get("prompt"), limit=240)
    summary["matched_alias"] = primary.get("matched_alias", "")
    summary["source"] = "prompt"
    return summary


def safe_slug(value: str) -> str:
    return runtime_safe_slug(value, fallback="unknown", allowed="-_.")


def turn_state_path(state_dir: Path, payload: dict[str, Any]) -> Path | None:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        return None
    return turns_dir(state_dir) / f"{safe_slug(session_id)}.json"


def load_turn_state(state_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = turn_state_path(state_dir, payload)
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION else {}


def write_turn_state(state_dir: Path, payload: dict[str, Any], state: dict[str, Any]) -> None:
    path = turn_state_path(state_dir, payload)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clear_turn_state(state_dir: Path, payload: dict[str, Any]) -> None:
    path = turn_state_path(state_dir, payload)
    if path is None or not path.exists():
        return
    try:
        path.unlink()
    except OSError:
        return


def state_skill_attribution(state: dict[str, Any]) -> dict[str, Any] | None:
    attribution = state.get("skill_attribution")
    if not isinstance(attribution, dict) or not isinstance(attribution.get("primary"), dict):
        return None
    return attribution


def initial_turn_state(
    payload: dict[str, Any],
    attribution: dict[str, Any],
    usage_context: dict[str, Any] | None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": str(payload.get("session_id") or ""),
        "turn_id": str(payload.get("turn_id") or ""),
        "skill_attribution": attribution,
        "tool_count": 0,
        "tool_failure_count": 0,
        "tools_used": {},
        "started_at": utc_now(),
        "updated_at": utc_now(),
    }
    if usage_context is not None:
        state["user_skill_context"] = usage_context
    return state


def update_tool_stats(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    state["tool_count"] = int(state.get("tool_count") or 0) + 1
    if event.get("outcome") == "failure":
        state["tool_failure_count"] = int(state.get("tool_failure_count") or 0) + 1
    tools = state.get("tools_used")
    if not isinstance(tools, dict):
        tools = {}
    for tool in event.get("tools_used", []):
        name = str(tool)
        tools[name] = int(tools.get(name) or 0) + 1
    state["tools_used"] = tools
    state["updated_at"] = utc_now()
    return state


def camel_to_snake(value: str) -> str:
    first = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def truthy_error_value(value: Any) -> bool:
    if value in (None, False, "", [], {}):
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered not in {"0", "false", "none", "null", "ok", "success"}
    return True


def has_failure_marker(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"exit_code", "exitcode", "return_code", "returncode", "status_code"}:
                try:
                    if int(item) != 0:
                        return True
                except (TypeError, ValueError):
                    if truthy_error_value(item):
                        return True
            if lowered in {"error", "errors", "exception", "failure", "failed", "is_error"} and truthy_error_value(item):
                return True
            if has_failure_marker(item):
                return True
        return False
    if isinstance(value, list):
        return any(has_failure_marker(item) for item in value)
    if isinstance(value, str):
        return FAILURE_TEXT_RE.search(value) is not None
    return False


def detect_post_tool_outcome(tool_response: Any) -> tuple[str, str]:
    if tool_response in (None, "", [], {}):
        return "unknown", ""
    if has_failure_marker(tool_response):
        return "failure", "tool_error"
    return "success", ""


def normalize_hook_payload(
    payload: dict[str, Any],
    *,
    skill_attribution: dict[str, Any] | None = None,
    state_dir: Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    hook_event_name = str(payload.get("hook_event_name") or payload.get("event") or "unknown")
    event_type = camel_to_snake(hook_event_name)
    attribution = (
        skill_attribution
        or infer_skill_attribution(payload, state_dir=state_dir, repo_root=repo_root)
        or empty_attribution()
    )
    tool_name = payload.get("tool_name")

    outcome = "unknown"
    failure_type = ""
    if hook_event_name == "PostToolUse":
        outcome, failure_type = detect_post_tool_outcome(payload.get("tool_response"))
    elif hook_event_name == "UserPromptSubmit" and attribution.get("primary"):
        outcome = "success"

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "agent": "codex",
        "event_type": event_type,
        "workspace": str(payload.get("cwd") or ""),
        "session_id": str(payload.get("session_id") or ""),
        "trigger_reason": f"Codex hook {hook_event_name}",
        "tools_used": [str(tool_name)] if tool_name else [],
        "outcome": outcome,
        "failure_type": failure_type,
        "skill_attribution": attribution,
        "notes": f"Observed Codex {hook_event_name} event.",
        "codex": {
            "hook_event_name": hook_event_name,
            "model": payload.get("model"),
            "turn_id": payload.get("turn_id"),
            "permission_mode": payload.get("permission_mode"),
            "transcript_path": payload.get("transcript_path"),
            "tool_use_id": payload.get("tool_use_id"),
        },
    }

    usage_context = user_skill_context(payload, attribution)
    if usage_context is not None:
        event["codex"]["user_skill_context"] = usage_context

    if hook_event_name not in SUPPORTED_HOOK_EVENTS:
        event["notes"] = f"Observed unsupported Codex hook event {hook_event_name}."

    if "prompt" in payload:
        event["codex"]["prompt_summary"] = summarize_json_value(payload.get("prompt"))
    if "last_assistant_message" in payload:
        event["codex"]["last_assistant_message_summary"] = summarize_json_value(payload.get("last_assistant_message"))
    if "tool_input" in payload:
        event["codex"]["tool_input_summary"] = summarize_json_value(payload.get("tool_input"))
    if "tool_response" in payload:
        event["codex"]["tool_response_summary"] = summarize_json_value(payload.get("tool_response"))

    args = argparse.Namespace(
        agent=None,
        event_type=None,
        workspace=None,
        session_id=None,
        skill=None,
        skill_version=None,
        trigger_reason=None,
        outcome=None,
        failure_type=None,
        user_feedback=None,
        notes=None,
        tool=None,
        file_touched=None,
        check=None,
    )
    normalized = normalize_event(redact_event(event), args)
    normalized.pop("skill_name", None)
    normalized.pop("skill_version", None)
    return normalized


def has_primary_attribution(event: dict[str, Any]) -> bool:
    attribution = event.get("skill_attribution")
    return isinstance(attribution, dict) and isinstance(attribution.get("primary"), dict)


def should_persist_event(event: dict[str, Any]) -> bool:
    if os.environ.get("WATCHER_SKILL_DEBUG_ALL_EVENTS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True

    if not has_primary_attribution(event):
        return False

    event_type = event.get("event_type")
    if event_type == "user_prompt_submit":
        return True
    if event_type == "post_tool_use":
        return event.get("outcome") == "failure"
    if event_type == "turn_summary":
        return True
    return False


def apply_turn_summary(event: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    tool_count = int(state.get("tool_count") or 0)
    tool_failure_count = int(state.get("tool_failure_count") or 0)
    tools_used = state.get("tools_used") if isinstance(state.get("tools_used"), dict) else {}

    event["event_type"] = "turn_summary"
    event["outcome"] = "unknown"
    event["failure_type"] = ""
    event["task_outcome"] = "unknown"
    event["notes"] = "Observed monitored Codex turn summary."
    event["tools_used"] = sorted(str(tool) for tool in tools_used.keys())
    event["codex"]["turn_summary"] = {
        "task_outcome": "unknown",
        "tool_count": tool_count,
        "tool_failure_count": tool_failure_count,
        "tools_used": tools_used,
    }
    if isinstance(state.get("user_skill_context"), dict):
        event["codex"]["turn_summary"]["user_skill_context"] = state["user_skill_context"]
    return event


def process_hook(
    payload: dict[str, Any],
    runtime_paths: HookRuntimePaths,
    *,
    persist: bool = True,
    repo_root: str | Path | None = None,
) -> HookResult:
    target_state_dir = runtime_paths.state_dir
    if persist:
        ensure_runtime_dirs(target_state_dir)
    hook_event_name = str(payload.get("hook_event_name") or payload.get("event") or "unknown")
    metadata_update = None
    if persist and hook_event_name == "SessionStart":
        metadata_update = refresh_dynamic_monitored_skills(
            target_state_dir,
            repo_root=repo_root,
        )
    elif persist:
        require_runtime_schema(target_state_dir)

    direct_attribution = infer_skill_attribution(
        payload,
        state_dir=target_state_dir,
        repo_root=repo_root,
    )
    state = load_turn_state(target_state_dir, payload)
    attribution = direct_attribution or state_skill_attribution(state)
    event = normalize_hook_payload(
        payload,
        skill_attribution=attribution,
        state_dir=target_state_dir,
        repo_root=repo_root,
    )
    if metadata_update is not None:
        event["codex"]["metadata_update"] = metadata_update

    if hook_event_name == "UserPromptSubmit":
        if persist and direct_attribution:
            usage_context = event.get("codex", {}).get("user_skill_context")
            write_turn_state(target_state_dir, payload, initial_turn_state(payload, direct_attribution, usage_context))
        elif persist:
            clear_turn_state(target_state_dir, payload)
    elif persist and hook_event_name == "PostToolUse" and attribution:
        if not state:
            state = initial_turn_state(payload, attribution, None)
        state = update_tool_stats(state, event)
        write_turn_state(target_state_dir, payload, state)
    elif hook_event_name == "Stop" and attribution:
        event = apply_turn_summary(event, state)

    persisted = should_persist_event(event)
    event["codex"]["persisted"] = persisted
    if persist and persisted:
        append_event(event, runtime_paths.log_file)
    if persist and hook_event_name == "Stop":
        clear_turn_state(target_state_dir, payload)
    return HookResult(event=event, persisted=persisted, hook_event_name=hook_event_name)


def write_hook_event(
    payload: dict[str, Any],
    *,
    state_dir: Path | None = None,
    log_file: Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    target_state_dir = state_dir or state_dir_from_env_or_arg(None)
    target_log_file = log_file or log_file_path(target_state_dir)
    result = process_hook(
        payload,
        HookRuntimePaths(state_dir=target_state_dir, log_file=target_log_file),
        repo_root=repo_root,
    )
    return result.event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill observe",
        description="Collect a Codex hook event for Watcher skill-domain logs.",
    )
    parser.add_argument("--state-dir", help="Runtime state directory. Defaults to $CODEX_HOME/watcher/skill.")
    parser.add_argument("--log-file", help="Explicit JSONL log path. Overrides --state-dir logs/events.jsonl.")
    parser.add_argument(
        "--repo-root",
        help="Canonical oh-my-harness repository root. Defaults to $OH_MY_HARNESS_ROOT.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Normalize and print the event without appending.")
    parser.add_argument("--print-event", action="store_true", help="Print the normalized event JSON. Not for hook config use.")
    args = parser.parse_args(argv)

    payload = read_payload()
    state_dir = state_dir_from_env_or_arg(args.state_dir)
    log_file = log_file_path(state_dir, args.log_file)
    runtime_paths = HookRuntimePaths(state_dir=state_dir, log_file=log_file)
    if args.dry_run:
        result = process_hook(
            payload,
            runtime_paths,
            persist=False,
            repo_root=args.repo_root,
        )
        json.dump(result.event, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    result = process_hook(payload, runtime_paths, repo_root=args.repo_root)

    if args.print_event:
        json.dump(result.event, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
    elif payload.get("hook_event_name") == "Stop":
        json.dump({"continue": True, "suppressOutput": True}, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
