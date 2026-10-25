#!/usr/bin/env python3
"""Load and resolve the repository-owned harness distribution registry."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

from manager_paths import lexical_absolute
from repo_skill_catalog import REPO_ROOT, SkillCatalog


REGISTRY_FILE = REPO_ROOT / ".agents" / "harnesses" / "registry.json"
REGISTRY_SCHEMA_VERSION = "2026-09-18"
HARNESS_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
INSTRUCTIONS_MIGRATION_ID = "split-global-project-instructions"
INSTRUCTIONS_MIGRATION_STAGES = (
    "bridge-ready",
    "source-switched",
    "semantic-split",
)
ROOT_INSTRUCTIONS_SOURCE = "AGENTS.md"
GLOBAL_INSTRUCTIONS_SOURCE = "agents/global-instructions.md"
INSTRUCTIONS_MIGRATION_ORIENTATION = {
    "bridge-ready": (ROOT_INSTRUCTIONS_SOURCE, GLOBAL_INSTRUCTIONS_SOURCE),
    "source-switched": (GLOBAL_INSTRUCTIONS_SOURCE, ROOT_INSTRUCTIONS_SOURCE),
    "semantic-split": (GLOBAL_INSTRUCTIONS_SOURCE, ROOT_INSTRUCTIONS_SOURCE),
}

SKILLS_DRIVERS = frozenset({"codex-marketplace", "directory-projection"})
INSTRUCTIONS_DRIVERS = frozenset({"managed-file", "settings-derived-file", "none"})
EXTRAS = frozenset(
    {"codex-agent-support", "watcher-hooks", "watcher-doctor"}
)


class HarnessRegistryError(ValueError):
    """Raised when the registry or a resolved harness plan is invalid."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise HarnessRegistryError(f"harness registry contains duplicate JSON key: {key!r}")
        payload[key] = value
    return payload


@dataclass(frozen=True)
class RootCandidate:
    source: str
    append: Path
    environment: str | None = None


@dataclass(frozen=True)
class ExcludedSkillRootSpec:
    root_id: str
    root_candidates: tuple[RootCandidate, ...]
    relative_path: Path


@dataclass(frozen=True)
class ReconciliationSpec:
    prune_policy: str
    confirmation: str


@dataclass(frozen=True)
class MarketplaceMigrationSpec:
    retired_marketplace_names: tuple[str, ...]
    confirmation: str


@dataclass(frozen=True)
class SkillsSpec:
    driver: str
    reconciliation: ReconciliationSpec
    relative_path: Path | None = None
    posix_materialization: str | None = None
    windows_materialization: str | None = None
    marketplace_path: Path | None = None
    install_manifest_path: Path | None = None
    marketplace_migration: MarketplaceMigrationSpec | None = None


@dataclass(frozen=True)
class InstructionsSpec:
    driver: str
    relative_path: Path | None = None
    settings_path: Path | None = None
    setting_path: tuple[str, ...] = ()
    default_relative_path: Path | None = None
    multiple_targets_policy: str | None = None
    posix_materialization: str | None = None
    windows_materialization: str | None = None
    create_confirmation: str | None = None
    replace_confirmation: str | None = None
    shadow_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class InstructionsMigrationSpec:
    migration_id: str
    stage: str
    peer_source: Path
    required_predecessor_revision: str | None = None


@dataclass(frozen=True)
class HarnessSpec:
    harness_id: str
    display_name: str
    root_candidates: tuple[RootCandidate, ...]
    skills: SkillsSpec
    instructions: InstructionsSpec
    extras: tuple[str, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessRegistry:
    path: Path
    default_harness: str
    instructions_source: Path
    instructions_migration: InstructionsMigrationSpec
    excluded_skill_roots: Mapping[str, ExcludedSkillRootSpec]
    harnesses: Mapping[str, HarnessSpec]

    @property
    def choices(self) -> tuple[str, ...]:
        return tuple(sorted(self.harnesses))

    @property
    def aliases(self) -> dict[str, str]:
        return {
            alias: harness.harness_id
            for harness in self.harnesses.values()
            for alias in harness.aliases
        }

    def resolve_id(self, name: str) -> str:
        """Resolve CLI names before they reach plans, receipts or desired state."""
        if name in self.harnesses:
            return name
        if name in self.aliases:
            return self.aliases[name]
        raise HarnessRegistryError(f"unknown harness {name!r}; {self.selection_help()}")

    def id_for_target(self, name: str, target_ids: Iterable[str]) -> str:
        """Resolve a distribution into another revision's canonical vocabulary."""
        canonical = self.resolve_id(name)
        target_ids = set(target_ids)
        equivalents = (canonical, *self.harnesses[canonical].aliases)
        matches = [candidate for candidate in equivalents if candidate in target_ids]
        if len(matches) != 1:
            raise HarnessRegistryError(
                f"target registry cannot represent installed harness {canonical!r}"
            )
        return matches[0]

    def selection_help(self) -> str:
        result = f"Available harnesses: {', '.join(self.choices)}."
        if self.aliases:
            aliases = ", ".join(
                f"{alias} = {canonical}" for alias, canonical in sorted(self.aliases.items())
            )
            result += f" Aliases: {aliases}."
        return result


@dataclass(frozen=True)
class HarnessPlan:
    registry_path: Path
    repo_root: Path
    harness: HarnessSpec
    root: Path
    skills_root: Path | None
    skills_materialization: str | None
    instructions_source: Path
    instructions_migration: InstructionsMigrationSpec
    instructions_target: Path | None
    instructions_materialization: str | None
    instruction_shadow_paths: tuple[Path, ...]
    excluded_skill_roots: tuple[Path, ...]
    marketplace_path: Path | None
    install_manifest_path: Path | None

    @property
    def harness_id(self) -> str:
        return self.harness.harness_id


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise HarnessRegistryError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise HarnessRegistryError(f"{label} keys must be strings")
    return value


def _keys(
    value: dict[str, object],
    *,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    allowed = required | set(optional or ())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise HarnessRegistryError(f"{label} is missing required fields: {', '.join(missing)}")
    if extra:
        raise HarnessRegistryError(f"{label} has unsupported fields: {', '.join(extra)}")


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessRegistryError(f"{label} must be a non-empty string")
    return value.strip()


def _relative_path(value: object, *, label: str, allow_empty: bool = False) -> Path:
    if not isinstance(value, str):
        raise HarnessRegistryError(f"{label} must be a string")
    raw = value.strip()
    if not raw:
        if allow_empty:
            return Path()
        raise HarnessRegistryError(f"{label} must be a non-empty relative path")
    if "\\" in raw:
        raise HarnessRegistryError(f"{label} must use portable forward-slash separators: {raw!r}")
    posix_path = PurePosixPath(raw)
    windows_path = PureWindowsPath(raw)
    raw_parts = raw.split("/")
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in raw_parts
    ):
        raise HarnessRegistryError(f"{label} must not escape its owning root: {raw!r}")
    if any(part in {"", "."} for part in raw_parts):
        raise HarnessRegistryError(f"{label} must be normalized: {raw!r}")
    return Path(*posix_path.parts)


def _instruction_sources(
    value: object,
    *,
    label: str,
) -> tuple[Path, InstructionsMigrationSpec]:
    payload = _object(value, label=label)
    _keys(payload, label=label, required={"current", "migration"})
    current = _relative_path(payload["current"], label=f"{label}.current")
    migration_label = f"{label}.migration"
    migration = _object(payload["migration"], label=migration_label)
    _keys(
        migration,
        label=migration_label,
        required={"id", "stage", "peer"},
        optional={"requiredPredecessorRevision"},
    )
    migration_id = _string(migration["id"], label=f"{migration_label}.id")
    if migration_id != INSTRUCTIONS_MIGRATION_ID:
        raise HarnessRegistryError(
            f"{migration_label}.id must be {INSTRUCTIONS_MIGRATION_ID!r}"
        )
    stage = _string(migration["stage"], label=f"{migration_label}.stage")
    if stage not in INSTRUCTIONS_MIGRATION_STAGES:
        raise HarnessRegistryError(
            f"{migration_label}.stage is unsupported: {stage!r}"
        )
    peer = _relative_path(migration["peer"], label=f"{migration_label}.peer")
    if current == peer:
        raise HarnessRegistryError(
            f"{label}.current and {migration_label}.peer must be different paths"
        )
    expected_current, expected_peer = INSTRUCTIONS_MIGRATION_ORIENTATION[stage]
    if current.as_posix() != expected_current or peer.as_posix() != expected_peer:
        raise HarnessRegistryError(
            f"{label} paths do not match the {stage} migration orientation: "
            f"current={expected_current!r}, peer={expected_peer!r}"
        )
    raw_predecessor = migration.get("requiredPredecessorRevision")
    if raw_predecessor is None:
        predecessor = None
    else:
        predecessor = _string(
            raw_predecessor,
            label=f"{migration_label}.requiredPredecessorRevision",
        )
        if not REVISION_PATTERN.fullmatch(predecessor):
            raise HarnessRegistryError(
                f"{migration_label}.requiredPredecessorRevision must be a lowercase 40-character Git SHA"
            )
    if stage == "bridge-ready" and predecessor is not None:
        raise HarnessRegistryError(
            f"{migration_label}.requiredPredecessorRevision is not valid for bridge-ready"
        )
    if stage != "bridge-ready" and predecessor is None:
        raise HarnessRegistryError(
            f"{migration_label}.requiredPredecessorRevision is required for {stage}"
        )
    return current, InstructionsMigrationSpec(
        migration_id=migration_id,
        stage=stage,
        peer_source=peer,
        required_predecessor_revision=predecessor,
    )


def _root_candidate(value: object, *, label: str) -> RootCandidate:
    payload = _object(value, label=label)
    _keys(
        payload,
        label=label,
        required={"source", "append"},
        optional={"name"},
    )
    source = _string(payload["source"], label=f"{label}.source")
    append = _relative_path(payload["append"], label=f"{label}.append", allow_empty=True)
    if source == "environment":
        environment = _string(payload.get("name"), label=f"{label}.name")
        if not ENVIRONMENT_NAME_PATTERN.fullmatch(environment):
            raise HarnessRegistryError(f"{label}.name is not a valid environment variable")
        return RootCandidate(source=source, append=append, environment=environment)
    if source in {"user-home", "openclaw-state"}:
        if "name" in payload:
            raise HarnessRegistryError(f"{label}.name is valid only for environment roots")
        if source == "openclaw-state" and append != Path(".openclaw"):
            raise HarnessRegistryError(f"{label}.append must be '.openclaw' for openclaw-state")
        return RootCandidate(source=source, append=append)
    raise HarnessRegistryError(f"{label}.source is unsupported: {source!r}")


def _root_candidates(value: object, *, label: str) -> tuple[RootCandidate, ...]:
    payload = _object(value, label=label)
    _keys(payload, label=label, required={"candidates"})
    candidates_value = payload["candidates"]
    if not isinstance(candidates_value, list) or not candidates_value:
        raise HarnessRegistryError(f"{label}.candidates must be a non-empty array")
    return tuple(
        _root_candidate(entry, label=f"{label}.candidates[{index}]")
        for index, entry in enumerate(candidates_value)
    )


def _excluded_skill_root(root_id: str, value: object) -> ExcludedSkillRootSpec:
    label = f"excludedSkillRoots.{root_id}"
    if not HARNESS_ID_PATTERN.fullmatch(root_id):
        raise HarnessRegistryError(f"invalid excluded skill root id: {root_id!r}")
    payload = _object(value, label=label)
    _keys(payload, label=label, required={"root", "relativePath"})
    return ExcludedSkillRootSpec(
        root_id=root_id,
        root_candidates=_root_candidates(payload["root"], label=f"{label}.root"),
        relative_path=_relative_path(
            payload["relativePath"], label=f"{label}.relativePath"
        ),
    )


def _materialization(
    value: object,
    *,
    label: str,
    posix_allowed: set[str],
    windows_allowed: set[str],
) -> tuple[str, str]:
    payload = _object(value, label=label)
    _keys(payload, label=label, required={"posix", "windows"})
    posix = _string(payload["posix"], label=f"{label}.posix")
    windows = _string(payload["windows"], label=f"{label}.windows")
    if posix not in posix_allowed:
        raise HarnessRegistryError(f"{label}.posix is unsupported: {posix!r}")
    if windows not in windows_allowed:
        raise HarnessRegistryError(f"{label}.windows is unsupported: {windows!r}")
    return posix, windows


def _reconciliation(value: object, *, label: str) -> ReconciliationSpec:
    payload = _object(value, label=label)
    _keys(payload, label=label, required={"prunePolicy", "confirmation"})
    prune_policy = _string(payload["prunePolicy"], label=f"{label}.prunePolicy")
    confirmation = _string(payload["confirmation"], label=f"{label}.confirmation")
    if prune_policy != "managed-stale":
        raise HarnessRegistryError(f"{label}.prunePolicy is unsupported: {prune_policy!r}")
    if confirmation not in {"none", "when-nonempty"}:
        raise HarnessRegistryError(f"{label}.confirmation is unsupported: {confirmation!r}")
    return ReconciliationSpec(prune_policy=prune_policy, confirmation=confirmation)


def _marketplace_migration(value: object, *, label: str) -> MarketplaceMigrationSpec:
    payload = _object(value, label=label)
    _keys(
        payload,
        label=label,
        required={"retiredMarketplaceNames", "confirmation"},
    )
    raw_names = payload["retiredMarketplaceNames"]
    if not isinstance(raw_names, list) or not raw_names:
        raise HarnessRegistryError(
            f"{label}.retiredMarketplaceNames must be a non-empty array"
        )
    names = tuple(
        _string(name, label=f"{label}.retiredMarketplaceNames[{index}]")
        for index, name in enumerate(raw_names)
    )
    if len(set(names)) != len(names):
        raise HarnessRegistryError(
            f"{label}.retiredMarketplaceNames contains duplicate values"
        )
    if any(not HARNESS_ID_PATTERN.fullmatch(name) for name in names):
        raise HarnessRegistryError(
            f"{label}.retiredMarketplaceNames contains an invalid marketplace name"
        )
    confirmation = _string(payload["confirmation"], label=f"{label}.confirmation")
    if confirmation != "explicit-flag-and-bounded-confirmation":
        raise HarnessRegistryError(
            f"{label}.confirmation is unsupported: {confirmation!r}"
        )
    return MarketplaceMigrationSpec(
        retired_marketplace_names=names,
        confirmation=confirmation,
    )


def _skills(value: object, *, label: str) -> SkillsSpec:
    payload = _object(value, label=label)
    driver = _string(payload.get("driver"), label=f"{label}.driver")
    if driver not in SKILLS_DRIVERS:
        raise HarnessRegistryError(f"{label}.driver is unsupported: {driver!r}")
    if driver == "codex-marketplace":
        _keys(
            payload,
            label=label,
            required={
                "driver",
                "marketplacePath",
                "installManifestPath",
                "reconciliation",
                "migration",
            },
        )
        return SkillsSpec(
            driver=driver,
            marketplace_path=_relative_path(
                payload["marketplacePath"], label=f"{label}.marketplacePath"
            ),
            install_manifest_path=_relative_path(
                payload["installManifestPath"], label=f"{label}.installManifestPath"
            ),
            reconciliation=_reconciliation(
                payload["reconciliation"], label=f"{label}.reconciliation"
            ),
            marketplace_migration=_marketplace_migration(
                payload["migration"], label=f"{label}.migration"
            ),
        )

    _keys(
        payload,
        label=label,
        required={"driver", "relativePath", "materialization", "reconciliation"},
    )
    posix, windows = _materialization(
        payload["materialization"],
        label=f"{label}.materialization",
        posix_allowed={"directory-symlink"},
        windows_allowed={"directory-junction"},
    )
    reconciliation = _reconciliation(
        payload["reconciliation"], label=f"{label}.reconciliation"
    )
    if reconciliation.confirmation != "none":
        raise HarnessRegistryError(
            f"{label}.reconciliation.confirmation must be 'none' for directory projection"
        )
    return SkillsSpec(
        driver=driver,
        relative_path=_relative_path(payload["relativePath"], label=f"{label}.relativePath"),
        posix_materialization=posix,
        windows_materialization=windows,
        reconciliation=reconciliation,
    )


def _confirmation(value: object, *, label: str) -> tuple[str, str]:
    payload = _object(value, label=label)
    _keys(payload, label=label, required={"create", "replace"})
    create = _string(payload["create"], label=f"{label}.create")
    replace = _string(payload["replace"], label=f"{label}.replace")
    if create != "assume-yes-or-interactive":
        raise HarnessRegistryError(f"{label}.create is unsupported: {create!r}")
    if replace != "interactive":
        raise HarnessRegistryError(f"{label}.replace is unsupported: {replace!r}")
    return create, replace


def _shadow_paths(value: object, *, label: str) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise HarnessRegistryError(f"{label} must be an array")
    paths = tuple(
        _relative_path(entry, label=f"{label}[{index}]")
        for index, entry in enumerate(value)
    )
    if len(set(paths)) != len(paths):
        raise HarnessRegistryError(f"{label} contains duplicate paths")
    return paths


def _instructions(value: object, *, label: str) -> InstructionsSpec:
    payload = _object(value, label=label)
    driver = _string(payload.get("driver"), label=f"{label}.driver")
    if driver not in INSTRUCTIONS_DRIVERS:
        raise HarnessRegistryError(f"{label}.driver is unsupported: {driver!r}")
    if driver == "none":
        _keys(payload, label=label, required={"driver"})
        return InstructionsSpec(driver=driver)
    common_required = {"driver", "materialization", "confirmation", "shadowPaths"}
    if driver == "managed-file":
        _keys(payload, label=label, required=common_required | {"relativePath"})
        relative_path = _relative_path(
            payload["relativePath"], label=f"{label}.relativePath"
        )
        settings_path = None
        setting_path: tuple[str, ...] = ()
        default_relative_path = None
        multiple_targets_policy = None
    else:
        _keys(
            payload,
            label=label,
            required=common_required
            | {
                "settingsPath",
                "settingPath",
                "defaultRelativePath",
                "multipleTargetsPolicy",
            },
        )
        settings_path = _relative_path(payload["settingsPath"], label=f"{label}.settingsPath")
        raw_setting_path = payload["settingPath"]
        if not isinstance(raw_setting_path, list) or not raw_setting_path:
            raise HarnessRegistryError(f"{label}.settingPath must be a non-empty array")
        setting_path = tuple(
            _string(entry, label=f"{label}.settingPath[{index}]")
            for index, entry in enumerate(raw_setting_path)
        )
        default_relative_path = _relative_path(
            payload["defaultRelativePath"], label=f"{label}.defaultRelativePath"
        )
        multiple_targets_policy = _string(
            payload["multipleTargetsPolicy"], label=f"{label}.multipleTargetsPolicy"
        )
        if multiple_targets_policy != "reject":
            raise HarnessRegistryError(
                f"{label}.multipleTargetsPolicy is unsupported: {multiple_targets_policy!r}"
            )
        relative_path = None

    posix, windows = _materialization(
        payload["materialization"],
        label=f"{label}.materialization",
        posix_allowed={"copy", "symlink"},
        windows_allowed={"copy"},
    )
    create, replace = _confirmation(payload["confirmation"], label=f"{label}.confirmation")
    return InstructionsSpec(
        driver=driver,
        relative_path=relative_path,
        settings_path=settings_path,
        setting_path=setting_path,
        default_relative_path=default_relative_path,
        multiple_targets_policy=multiple_targets_policy,
        posix_materialization=posix,
        windows_materialization=windows,
        create_confirmation=create,
        replace_confirmation=replace,
        shadow_paths=_shadow_paths(payload["shadowPaths"], label=f"{label}.shadowPaths"),
    )


def _harness(harness_id: str, value: object) -> HarnessSpec:
    label = f"harnesses.{harness_id}"
    if not HARNESS_ID_PATTERN.fullmatch(harness_id):
        raise HarnessRegistryError(f"invalid harness id: {harness_id!r}")
    payload = _object(value, label=label)
    _keys(
        payload,
        label=label,
        required={
            "displayName",
            "root",
            "skills",
            "instructions",
            "extras",
        },
        optional={"aliases"},
    )
    aliases_value = payload.get("aliases", [])
    if not isinstance(aliases_value, list):
        raise HarnessRegistryError(f"{label}.aliases must be an array")
    for alias in aliases_value:
        if not isinstance(alias, str) or not HARNESS_ID_PATTERN.fullmatch(alias):
            raise HarnessRegistryError(f"{label}.aliases contains invalid harness alias: {alias!r}")
    if len(set(aliases_value)) != len(aliases_value):
        raise HarnessRegistryError(f"{label}.aliases contains duplicate values")
    candidates = _root_candidates(payload["root"], label=f"{label}.root")
    extras_value = payload["extras"]
    if not isinstance(extras_value, list):
        raise HarnessRegistryError(f"{label}.extras must be an array")
    extras = tuple(_string(entry, label=f"{label}.extras") for entry in extras_value)
    if len(set(extras)) != len(extras):
        raise HarnessRegistryError(f"{label}.extras contains duplicate values")
    unsupported_extras = sorted(set(extras) - EXTRAS)
    if unsupported_extras:
        raise HarnessRegistryError(
            f"{label}.extras contains unsupported values: {', '.join(unsupported_extras)}"
        )

    skills = _skills(payload["skills"], label=f"{label}.skills")
    instructions = _instructions(payload["instructions"], label=f"{label}.instructions")
    if instructions.driver == "none" and (skills.driver != "directory-projection" or extras):
        raise HarnessRegistryError(
            f"{label} skills-only distributions require directory projection and no extras"
        )
    if extras and harness_id != "codex":
        raise HarnessRegistryError(
            f"{label} cannot declare Codex-specific extras outside the codex harness"
        )
    if skills.driver == "codex-marketplace" and harness_id != "codex":
        raise HarnessRegistryError(
            f"{label} cannot use the Codex marketplace driver outside the codex harness"
        )
    return HarnessSpec(
        harness_id=harness_id,
        display_name=_string(payload["displayName"], label=f"{label}.displayName"),
        root_candidates=candidates,
        skills=skills,
        instructions=instructions,
        extras=extras,
        aliases=tuple(aliases_value),
    )


def _load_harness_registry(
    path: Path = REGISTRY_FILE,
    *,
    repo_root: Path = REPO_ROOT,
    validate_sources: bool,
) -> HarnessRegistry:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessRegistryError(f"harness registry is not valid readable JSON: {path}: {exc}") from exc
    root = _object(payload, label="registry")
    _keys(
        root,
        label="registry",
        required={
            "$schema",
            "schemaVersion",
            "defaults",
            "sources",
            "excludedSkillRoots",
            "harnesses",
        },
    )
    if root["$schema"] != "./registry.schema.json":
        raise HarnessRegistryError("registry.$schema must be './registry.schema.json'")
    if root["schemaVersion"] != REGISTRY_SCHEMA_VERSION:
        raise HarnessRegistryError(
            f"registry.schemaVersion must be {REGISTRY_SCHEMA_VERSION!r}"
        )
    defaults = _object(root["defaults"], label="registry.defaults")
    _keys(defaults, label="registry.defaults", required={"harness"})
    default_harness = _string(defaults["harness"], label="registry.defaults.harness")
    sources = _object(root["sources"], label="registry.sources")
    _keys(sources, label="registry.sources", required={"instructions"})
    instructions_source, instructions_migration = _instruction_sources(
        sources["instructions"], label="registry.sources.instructions"
    )
    excluded_payload = _object(
        root["excludedSkillRoots"], label="registry.excludedSkillRoots"
    )
    if not excluded_payload:
        raise HarnessRegistryError("registry.excludedSkillRoots must not be empty")
    excluded_skill_roots = {
        root_id: _excluded_skill_root(root_id, value)
        for root_id, value in excluded_payload.items()
    }
    harness_payload = _object(root["harnesses"], label="registry.harnesses")
    if not harness_payload:
        raise HarnessRegistryError("registry.harnesses must not be empty")
    harnesses = {
        harness_id: _harness(harness_id, value)
        for harness_id, value in harness_payload.items()
    }
    names = set(harnesses)
    for harness in harnesses.values():
        for alias in harness.aliases:
            if alias in names:
                raise HarnessRegistryError(
                    f"harness alias {alias!r} conflicts with another alias or canonical id"
                )
            names.add(alias)
    if default_harness not in harnesses:
        raise HarnessRegistryError(
            f"registry default harness does not exist: {default_harness!r}"
        )
    if "codex" not in harnesses or harnesses["codex"].skills.driver != "codex-marketplace":
        raise HarnessRegistryError("registry must define the codex marketplace harness")
    resolved_repo_root = repo_root.resolve(strict=False)
    path_resolver = _repo_owned_path if validate_sources else _join_within
    resolved_instructions_source = path_resolver(
        resolved_repo_root,
        instructions_source,
        label="registry instructions source",
    )
    resolved_peer_source = path_resolver(
        resolved_repo_root,
        instructions_migration.peer_source,
        label="registry instructions migration peer",
    )
    for label, source in (
        ("registry instructions source", resolved_instructions_source),
        ("registry instructions migration peer", resolved_peer_source),
    ):
        if validate_sources and (source.is_symlink() or not source.is_file()):
            raise HarnessRegistryError(f"{label} must be a regular file: {source}")
    if validate_sources and instructions_migration.stage in {"bridge-ready", "source-switched"}:
        try:
            sources_match = (
                resolved_instructions_source.read_bytes()
                == resolved_peer_source.read_bytes()
            )
        except OSError as exc:
            raise HarnessRegistryError(
                f"instruction migration sources are unreadable: {exc}"
            ) from exc
        if not sources_match:
            raise HarnessRegistryError(
                "instruction migration sources must be byte-identical during "
                f"{instructions_migration.stage}: {resolved_instructions_source}, "
                f"{resolved_peer_source}"
            )
    resolved_migration = InstructionsMigrationSpec(
        migration_id=instructions_migration.migration_id,
        stage=instructions_migration.stage,
        peer_source=resolved_peer_source,
        required_predecessor_revision=(
            instructions_migration.required_predecessor_revision
        ),
    )
    return HarnessRegistry(
        path=path.resolve(strict=False),
        default_harness=default_harness,
        instructions_source=resolved_instructions_source,
        instructions_migration=resolved_migration,
        excluded_skill_roots=excluded_skill_roots,
        harnesses=harnesses,
    )


def load_harness_registry(path: Path = REGISTRY_FILE, *, repo_root: Path = REPO_ROOT) -> HarnessRegistry:
    """Load strict runtime authority, including source-file integrity."""
    return _load_harness_registry(path, repo_root=repo_root, validate_sources=True)


def load_harness_metadata(path: Path = REGISTRY_FILE, *, repo_root: Path = REPO_ROOT) -> HarnessRegistry:
    """Parse registry structure for help/state display without inspecting resources."""
    return _load_harness_registry(path, repo_root=repo_root, validate_sources=False)


def _resolve_root(
    candidates: tuple[RootCandidate, ...],
    *,
    label: str,
    environ: Mapping[str, str],
    user_home: Path,
) -> Path:
    if not user_home.is_absolute():
        raise HarnessRegistryError(f"user home must be absolute: {user_home}")
    for candidate in candidates:
        if candidate.source == "openclaw-state":
            return _resolve_openclaw_state(candidate.append, environ=environ, user_home=user_home)
        if candidate.source == "environment":
            assert candidate.environment is not None
            raw_root = environ.get(candidate.environment, "").strip()
            if not raw_root:
                continue
            base = Path(raw_root).expanduser()
            if not base.is_absolute():
                raise HarnessRegistryError(
                    f"{candidate.environment} must be an absolute path: {raw_root!r}"
                )
        else:
            base = user_home
        return lexical_absolute(base / candidate.append)
    raise HarnessRegistryError(f"{label} has no usable root candidate")


def _openclaw_absolute_path(raw: str, *, name: str, home: Path) -> Path:
    # Expand against the explicitly resolved home, never the process's real HOME.
    if raw == "~":
        path = home
    elif raw.startswith(("~/", "~\\")):
        path = home / raw[2:]
    else:
        path = Path(raw)
    if not path.is_absolute():
        raise HarnessRegistryError(f"{name} must be an absolute path: {raw!r}")
    return lexical_absolute(path)


def _resolve_openclaw_state(default: Path, *, environ: Mapping[str, str], user_home: Path) -> Path:
    raw_home = environ.get("OPENCLAW_HOME", "").strip()
    home = (
        _openclaw_absolute_path(raw_home, name="OPENCLAW_HOME", home=user_home)
        if raw_home and raw_home not in {"undefined", "null"} else user_home
    )
    profile = environ.get("OPENCLAW_PROFILE", "").strip()
    if profile and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile):
        raise HarnessRegistryError(
            "OPENCLAW_PROFILE must be 1-64 letters, digits, underscores or hyphens, "
            "starting with a letter or digit"
        )
    raw_state = environ.get("OPENCLAW_STATE_DIR", "").strip()
    if raw_state:
        return _openclaw_absolute_path(raw_state, name="OPENCLAW_STATE_DIR", home=home)
    suffix = f"-{profile}" if profile and profile.lower() != "default" else ""
    return lexical_absolute(home / f"{default}{suffix}")


def _settings_value(settings: object, path: tuple[str, ...]) -> object | None:
    current = settings
    for field in path:
        if not isinstance(current, dict) or field not in current:
            return None
        current = current[field]
    return current


def _join_within(root: Path, relative: Path, *, label: str) -> Path:
    """Join lexically so an existing target symlink does not replace its managed path."""

    root = lexical_absolute(root)
    target = lexical_absolute(root / relative)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HarnessRegistryError(f"{label} escapes harness root: {target}") from exc
    return target


def _repo_owned_path(root: Path, relative: Path, *, label: str) -> Path:
    """Keep repository metadata lexical while rejecting an existing symlink escape."""

    target = _join_within(root, relative, label=label)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HarnessRegistryError(f"{label} resolves outside repository root: {target}") from exc
    return target


def configured_instruction_targets(spec: InstructionsSpec, *, root: Path) -> tuple[Path, ...]:
    """Inspect declared candidates without accepting a multi-target distribution."""
    assert spec.settings_path is not None
    assert spec.default_relative_path is not None
    settings_file = root / spec.settings_path
    if settings_file.exists():
        if not settings_file.is_file() or settings_file.is_symlink():
            raise HarnessRegistryError(
                f"instructions settings path is not an inspectable file: {settings_file}"
            )
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HarnessRegistryError(
                f"instructions settings are not valid readable JSON: {settings_file}: {exc}"
            ) from exc
        raw_target = _settings_value(settings, spec.setting_path)
    else:
        raw_target = None

    if raw_target is None:
        relatives = (spec.default_relative_path,)
    elif isinstance(raw_target, str):
        relatives = (_relative_path(raw_target, label="configured instructions target"),)
    elif isinstance(raw_target, list):
        relatives = tuple(_relative_path(item, label="configured instructions target") for item in raw_target)
    else:
        raise HarnessRegistryError(
            "configured instructions target must be a string or a single-item string array"
        )
    return tuple(_join_within(root, relative, label="configured instructions target") for relative in relatives)


def _settings_instruction_path(spec: InstructionsSpec, *, root: Path) -> Path:
    targets = configured_instruction_targets(spec, root=root)
    if len(targets) != 1:
        raise HarnessRegistryError(
            "configured instructions target lists multiple filenames; registry policy rejects duplicate distribution"
        )
    return targets[0]


def resolve_harness_root(
    registry: HarnessRegistry,
    harness_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> Path:
    """Resolve a client's resource boundary without reading dynamic settings."""
    harness = registry.harnesses[registry.resolve_id(harness_id)]
    return _resolve_root(
        harness.root_candidates,
        label=f"harness {harness.harness_id!r}",
        environ=environ if environ is not None else os.environ,
        user_home=lexical_absolute(user_home or Path.home()),
    )


def resolve_harness_plan(
    registry: HarnessRegistry,
    harness_id: str | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    environ: Mapping[str, str] | None = None,
    user_home: Path | None = None,
    os_name: str = os.name,
) -> HarnessPlan:
    selected = registry.resolve_id(registry.default_harness if harness_id is None else harness_id)
    harness = registry.harnesses[selected]
    environment = environ if environ is not None else os.environ
    home = lexical_absolute(user_home or Path.home())
    root = resolve_harness_root(
        registry, selected, environ=environment, user_home=home,
    )
    platform_materialization = "windows" if os_name == "nt" else "posix"

    skills = harness.skills
    if skills.driver == "directory-projection":
        assert skills.relative_path is not None
        skills_root = _join_within(
            root,
            skills.relative_path,
            label="resolved skills target",
        )
        skills_materialization = (
            skills.windows_materialization
            if platform_materialization == "windows"
            else skills.posix_materialization
        )
    else:
        skills_root = None
        skills_materialization = None

    instructions = harness.instructions
    if instructions.driver == "none":
        instructions_target = None
    elif instructions.driver == "settings-derived-file":
        instructions_target = _settings_instruction_path(instructions, root=root)
    else:
        assert instructions.relative_path is not None
        instructions_target = _join_within(
            root,
            instructions.relative_path,
            label="resolved instructions target",
        )
    instructions_materialization = (
        instructions.windows_materialization
        if platform_materialization == "windows"
        else instructions.posix_materialization
    )
    if instructions.driver != "none":
        assert instructions_materialization is not None
    shadow_paths = tuple(
        _join_within(root, path, label="resolved instruction shadow path")
        for path in instructions.shadow_paths
    )

    excluded_skill_roots = tuple(
        _join_within(
            _resolve_root(
                spec.root_candidates,
                label=f"excluded skill root {spec.root_id!r}",
                environ=environment,
                user_home=home,
            ),
            spec.relative_path,
            label=f"excluded skill root {spec.root_id!r}",
        )
        for spec in registry.excluded_skill_roots.values()
    )
    if len(set(excluded_skill_roots)) != len(excluded_skill_roots):
        raise HarnessRegistryError("excluded skill roots resolve to duplicate paths")
    if skills_root is not None and skills_root in excluded_skill_roots:
        raise HarnessRegistryError(
            f"harness {harness.harness_id!r} skills root is also excluded: {skills_root}"
        )

    resolved_repo_root = repo_root.resolve(strict=False)
    marketplace_path = (
        _repo_owned_path(
            resolved_repo_root,
            skills.marketplace_path,
            label="resolved marketplace metadata",
        )
        if skills.marketplace_path is not None
        else None
    )
    install_manifest_path = (
        _repo_owned_path(
            resolved_repo_root,
            skills.install_manifest_path,
            label="resolved install manifest",
        )
        if skills.install_manifest_path is not None
        else None
    )
    return HarnessPlan(
        registry_path=registry.path,
        repo_root=resolved_repo_root,
        harness=harness,
        root=root,
        skills_root=skills_root,
        skills_materialization=skills_materialization,
        instructions_source=registry.instructions_source,
        instructions_migration=registry.instructions_migration,
        instructions_target=instructions_target,
        instructions_materialization=instructions_materialization,
        instruction_shadow_paths=shadow_paths,
        excluded_skill_roots=excluded_skill_roots,
        marketplace_path=marketplace_path,
        install_manifest_path=install_manifest_path,
    )


def ensure_codex_harness_covers_catalog(
    catalog: SkillCatalog,
    selectors: list[str] | tuple[str, ...],
    *,
    marketplace_name: str,
) -> None:
    selected_names: set[str] = set()
    for selector in selectors:
        name, separator, marketplace = selector.partition("@")
        if not separator or not name or marketplace != marketplace_name:
            raise SystemExit(
                f"Codex harness selector must target {marketplace_name!r}: {selector!r}"
            )
        selected_names.add(name)
    expected_names = set(catalog.plugin_names)
    missing = sorted(expected_names - selected_names)
    extra = sorted(selected_names - expected_names)
    if missing or extra:
        details = []
        if missing:
            details.append("missing skills-bearing plugins: " + ", ".join(missing))
        if extra:
            details.append("selected plugins without canonical skills: " + ", ".join(extra))
        raise SystemExit("Codex harness does not match repository catalog: " + "; ".join(details))
