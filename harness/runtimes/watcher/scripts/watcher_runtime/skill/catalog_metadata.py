#!/usr/bin/env python3
"""Versioned catalog metadata and historical cache readers; no hook collection."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..repository_source import load_repository_skill_catalog, resolve_repository_source
from .runtime_paths import utc_now_text

SCHEMA_VERSION = 2
SKILL_METADATA_SCHEMA_VERSION = 1
METADATA_CACHE_FILE = "skill-metadata-cache.json"
SCHEMA_VERSION_FILE = "schema-version.json"
DEFAULT_ROLE = "entrypoint"
VALID_ROLES = {"entrypoint", "wrapper", "discipline", "specialized"}
VALID_ALIAS_MATCHES = {"exact", "phrase", "token"}
LOGICAL_GROUP_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

def utc_now() -> str:
    return utc_now_text()


def parse_env_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values = re.split(r"[,\n;]+", raw)
    return tuple(value.strip() for value in values if value.strip())


def watcher_skill_name(source: Any) -> str:
    return source.id


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
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    canonical_identities: set[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Overlay non-callable Watcher attribution metadata onto catalog identities."""

    skills = {
        skill_name: normalize_manifest_skill(None, manifest_path=manifest_path, skill_name=skill_name)
        for skill_name in sorted(canonical_identities)
    }
    legacy_names: dict[str, str] = {}
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
    overlays = {overlay["plugin"]: overlay for overlay in catalog.attribution_overlays}
    if set(overlays) - set(identities_by_plugin):
        raise SystemExit("attribution overlay references unknown catalog plugin")
    for plugin_name, canonical_identities in sorted(identities_by_plugin.items()):
        overlay = overlays.get(plugin_name)
        manifest = overlay["data"] if overlay else {"schema_version": 1}
        manifest_path = source.catalog_snapshot
        plugin_skills, plugin_legacy = load_attribution_overlay(
            manifest,
            manifest_path,
            canonical_identities=canonical_identities,
        )
        skills.update(plugin_skills)
        legacy_overlap = set(legacy_names).intersection(plugin_legacy)
        if legacy_overlap:
            raise SystemExit(f"duplicate legacy skill metadata entries: {', '.join(sorted(legacy_overlap))}")
        legacy_names.update(plugin_legacy)
    for catalog_skill in catalog.sources:
        for alias in catalog_skill.aliases:
            if alias != catalog_skill.id:
                if alias in skills and alias != catalog_skill.id:
                    raise SystemExit(f"catalog alias collides with stable identity: {alias}")
                if alias in legacy_names and legacy_names[alias] != catalog_skill.id:
                    raise SystemExit(f"conflicting catalog alias: {alias}")
                legacy_names[alias] = catalog_skill.id
                record = {"value": alias, "kind": "skill_name", "match": "phrase"}
                if record not in skills[catalog_skill.id]["aliases"]:
                    skills[catalog_skill.id]["aliases"].append(record)
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
        "source_identity": catalog.source_identity,
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
