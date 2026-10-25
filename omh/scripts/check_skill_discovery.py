#!/usr/bin/env python3
"""Pure closure checks for registry-selected harness skill distributions."""

from __future__ import annotations

import json
import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from plugin_package_identity import (
    PluginDistributionIdentity,
    plugin_cache_identity_issues,
    repository_identity_issues,
)
from repo_skill_catalog import SkillCatalog, skill_frontmatter_name
from sync_agents_skills import (
    is_projection_link,
    managed_destination,
)


@dataclass(frozen=True)
class PluginListRow:
    status: str
    version: str


def codex_plugin_rows(
    output: str,
    *,
    marketplace_name: str | None = None,
    plugin_names: Collection[str] = (),
) -> dict[tuple[str, str], PluginListRow]:
    """Parse relevant rows from the JSON form of `codex plugin list`."""

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"plugin list output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("plugin list JSON must be an object")

    groups: list[tuple[str, object]] = [
        ("installed", payload.get("installed")),
        ("available", payload.get("available")),
    ]
    rows: dict[tuple[str, str], PluginListRow] = {}
    relevant_plugin_names = frozenset(plugin_names)
    scoped = marketplace_name is not None or bool(relevant_plugin_names)
    for group_name, entries in groups:
        if not isinstance(entries, list):
            raise ValueError(f"plugin list JSON {group_name!r} field must be an array")
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"plugin list JSON {group_name} entry #{index} must be an object"
                )
            plugin_name = entry.get("name")
            listed_marketplace = entry.get("marketplaceName")
            if not isinstance(plugin_name, str) or not plugin_name.strip():
                raise ValueError(
                    f"plugin list JSON {group_name} entry #{index} has no name"
                )
            if not isinstance(listed_marketplace, str) or not listed_marketplace.strip():
                raise ValueError(
                    f"plugin list JSON {group_name} entry #{index} has no marketplaceName"
                )
            plugin_name = plugin_name.strip()
            listed_marketplace = listed_marketplace.strip()
            if (
                scoped
                and listed_marketplace != marketplace_name
                and plugin_name not in relevant_plugin_names
            ):
                continue

            expected_selector = f"{plugin_name}@{listed_marketplace}"
            if entry.get("pluginId") != expected_selector:
                raise ValueError(
                    f"plugin list JSON selector mismatch for {expected_selector}"
                )
            installed = entry.get("installed")
            enabled = entry.get("enabled")
            expected_installed = group_name == "installed"
            if installed is not expected_installed or not isinstance(enabled, bool):
                raise ValueError(
                    f"plugin list JSON state is malformed for {expected_selector}"
                )
            if installed:
                raw_version = entry.get("version")
                if not isinstance(raw_version, str) or not raw_version.strip():
                    raise ValueError(
                        f"installed plugin row has no version: {expected_selector}"
                    )
                version = raw_version.strip()
                status = "installed, enabled" if enabled else "installed"
            else:
                if enabled:
                    raise ValueError(
                        f"uninstalled plugin row is enabled: {expected_selector}"
                    )
                version = ""
                status = "not installed"

            key = (listed_marketplace, plugin_name)
            if key in rows:
                raise ValueError(f"duplicate plugin list row: {expected_selector}")
            rows[key] = PluginListRow(status=status, version=version)
    return rows


def enabled_plugin_names(
    rows: dict[tuple[str, str], PluginListRow],
    *,
    marketplace_name: str,
) -> set[str]:
    return {
        plugin_name
        for (marketplace, plugin_name), row in rows.items()
        if marketplace == marketplace_name and row.status == "installed, enabled"
    }


def plugin_manifest_payload(manifest: Path, *, label: str) -> dict[str, object]:
    if not manifest.is_file():
        raise ValueError(f"{label} manifest missing: {manifest}")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} manifest is not valid readable JSON: {manifest}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} manifest must be an object: {manifest}")
    return payload


def _plugin_manifest_identity(
    payload: dict[str, object],
    manifest: Path,
    *,
    label: str,
) -> tuple[str, str]:
    identity: list[str] = []
    for field in ("name", "version"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} manifest {field} must be a non-empty string: {manifest}")
        identity.append(value.strip())
    return identity[0], identity[1]


def plugin_manifest_identity(manifest: Path, *, label: str) -> tuple[str, str]:
    payload = plugin_manifest_payload(manifest, label=label)
    return _plugin_manifest_identity(payload, manifest, label=label)


def _marketplace_payload(marketplace: Path) -> tuple[str, list[object]]:
    if not marketplace.is_file():
        raise ValueError(f"marketplace file missing: {marketplace}")
    try:
        payload = json.loads(marketplace.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"marketplace file is not valid readable JSON: {marketplace}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"marketplace must be an object: {marketplace}")
    marketplace_name = payload.get("name")
    if not isinstance(marketplace_name, str) or not marketplace_name.strip():
        raise ValueError(f"marketplace name must be a non-empty string: {marketplace}")
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError(f"marketplace plugins field is not a list: {marketplace}")
    return marketplace_name.strip(), plugins


def marketplace_plugin_names(marketplace: Path) -> set[str]:
    """Return unique package names from a validated marketplace document."""

    _, plugins = _marketplace_payload(marketplace)
    names: set[str] = set()
    for index, entry in enumerate(plugins, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"marketplace plugin entry #{index} must be an object: {marketplace}")
        plugin_name = entry.get("name")
        if not isinstance(plugin_name, str) or not plugin_name.strip():
            raise ValueError(f"marketplace plugin entry #{index} name missing: {marketplace}")
        plugin_name = plugin_name.strip()
        if plugin_name in names:
            raise ValueError(f"duplicate marketplace plugin name {plugin_name!r}: {marketplace}")
        names.add(plugin_name)
    return names


def marketplace_plugin_sources(
    source_root: Path,
    *,
    marketplace_file: Path | None = None,
) -> tuple[str, dict[str, Path]]:
    """Load exact local marketplace package owners beneath ``source_root``."""

    try:
        resolved_source_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"source root cannot be resolved: {source_root}: {exc}") from exc
    marketplace = (
        marketplace_file.resolve(strict=False)
        if marketplace_file is not None
        else resolved_source_root / ".agents" / "plugins" / "marketplace.json"
    )
    try:
        marketplace.relative_to(resolved_source_root)
    except ValueError as exc:
        raise ValueError(f"marketplace file escapes source root: {marketplace}") from exc
    marketplace_name, plugins = _marketplace_payload(marketplace)

    sources: dict[str, Path] = {}
    for index, entry in enumerate(plugins, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"marketplace plugin entry #{index} must be an object: {marketplace}")
        plugin_name = entry.get("name")
        if not isinstance(plugin_name, str) or not plugin_name.strip():
            raise ValueError(f"marketplace plugin entry #{index} name missing: {marketplace}")
        plugin_name = plugin_name.strip()
        if plugin_name in sources:
            raise ValueError(f"duplicate marketplace plugin name {plugin_name!r}: {marketplace}")
        source = entry.get("source")
        if not isinstance(source, dict):
            raise ValueError(
                f"marketplace plugin entry #{index} source must be an object: {marketplace}"
            )
        source_kind = source.get("source")
        if source_kind != "local":
            raise ValueError(
                f"unsupported marketplace source kind {source_kind!r} "
                f"for {plugin_name!r}: {marketplace}"
            )
        raw_path = source.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"marketplace local plugin entry #{index} path missing: {marketplace}")
        plugin_dir = Path(os.path.expandvars(raw_path.strip())).expanduser()
        if not plugin_dir.is_absolute():
            plugin_dir = resolved_source_root / plugin_dir
        try:
            plugin_dir = plugin_dir.resolve(strict=True)
            plugin_dir.relative_to(resolved_source_root)
        except OSError as exc:
            raise ValueError(f"marketplace local plugin path missing: {plugin_dir}: {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"marketplace plugin path escapes source root: {plugin_dir}") from exc
        manifest = plugin_dir / ".codex-plugin" / "plugin.json"
        manifest_name, _ = plugin_manifest_identity(manifest, label="source")
        if manifest_name != plugin_name:
            raise ValueError(
                f"marketplace/source manifest name mismatch for entry #{index}; "
                f"catalog has {plugin_name!r}, manifest has {manifest_name!r} at {manifest}"
            )
        policy = entry.get("policy")
        if not isinstance(policy, dict):
            raise ValueError(
                f"marketplace plugin policy must be an object for {plugin_name!r}: {marketplace}"
            )
        if policy.get("installation") != "AVAILABLE":
            raise ValueError(
                f"marketplace plugin installation policy must be 'AVAILABLE' for "
                f"optional package {plugin_name!r}: {marketplace}"
            )
        sources[plugin_name] = plugin_dir
    return marketplace_name, sources


def _source_package_authority_issues(plugin_name: str, package_root: Path) -> list[str]:
    """Reject unreadable or escaping descendants without following directory symlinks."""

    issues: list[str] = []
    pending = [package_root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            issues.append(
                f"{plugin_name}: source package directory is not readable: {directory}: {exc}"
            )
            continue
        for entry in entries:
            try:
                resolved_entry = entry.resolve(strict=True)
                resolved_entry.relative_to(package_root)
            except OSError as exc:
                issues.append(
                    f"{plugin_name}: source package entry cannot be resolved: {entry}: {exc}"
                )
                continue
            except ValueError:
                issues.append(
                    f"{plugin_name}: source package entry escapes package authority: {entry}"
                )
                continue
            if not entry.is_symlink() and resolved_entry.is_dir():
                pending.append(resolved_entry)
    return issues


def plugin_package_issues(
    catalog: SkillCatalog,
    *,
    plugin_sources: dict[str, Path],
    _validated_identities: dict[str, PluginDistributionIdentity] | None = None,
) -> list[str]:
    """Validate that plugin packages are the packaging projection of catalog owners."""

    if _validated_identities is not None:
        _validated_identities.clear()
    identities: dict[str, PluginDistributionIdentity] = {}
    issues: list[str] = []
    expected_plugins = set(catalog.plugin_names)
    missing = sorted(expected_plugins - set(plugin_sources))
    extra = sorted(set(plugin_sources) - expected_plugins)
    if missing:
        issues.append("marketplace is missing skills-bearing plugin packages: " + ", ".join(missing))
    if extra:
        issues.append("marketplace has plugin packages outside the callable catalog: " + ", ".join(extra))

    for plugin_name in sorted(expected_plugins & set(plugin_sources)):
        source_root = plugin_sources[plugin_name]
        expected_root = catalog.plugins_root / plugin_name
        try:
            source_resolved = source_root.resolve(strict=True)
            expected_resolved = expected_root.resolve(strict=True)
        except OSError as exc:
            issues.append(f"{plugin_name}: plugin package path cannot be resolved: {exc}")
            continue
        if source_resolved != expected_resolved:
            issues.append(
                f"{plugin_name}: marketplace package is not the canonical catalog owner; "
                f"expected {expected_resolved}, found {source_resolved}"
            )
            continue
        issues.extend(_source_package_authority_issues(plugin_name, source_resolved))
        manifest = source_resolved / ".codex-plugin" / "plugin.json"
        try:
            resolved_manifest = manifest.resolve(strict=True)
            resolved_manifest.relative_to(source_resolved)
        except OSError as exc:
            issues.append(f"{plugin_name}: source manifest cannot be resolved: {manifest}: {exc}")
            continue
        except ValueError:
            issues.append(f"{plugin_name}: source manifest escapes package authority: {manifest}")
            continue
        try:
            manifest_payload = plugin_manifest_payload(resolved_manifest, label="source")
            manifest_name, _ = _plugin_manifest_identity(
                manifest_payload,
                resolved_manifest,
                label="source",
            )
        except ValueError as exc:
            issues.append(f"{plugin_name}: {exc}")
            continue
        if manifest_name != plugin_name:
            issues.append(
                f"{plugin_name}: source manifest name mismatch; found {manifest_name!r}"
            )
        if manifest_payload.get("skills") != "./skills/":
            issues.append(
                f"{plugin_name}: source manifest skills must be exactly './skills/'; "
                f"found {manifest_payload.get('skills')!r}"
            )

        expected_skills = {
            source.directory_name: source
            for source in catalog.sources
            if source.plugin == plugin_name
        }
        skills_root = source_resolved / "skills"
        try:
            resolved_skills_root = skills_root.resolve(strict=True)
            resolved_skills_root.relative_to(source_resolved)
            entries = sorted(resolved_skills_root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            issues.append(
                f"{plugin_name}: source package skills tree is not readable: "
                f"{skills_root}: {exc}"
            )
            continue
        except ValueError:
            issues.append(
                f"{plugin_name}: source package skills tree escapes package authority: {skills_root}"
            )
            continue
        actual_directories = {entry.name for entry in entries if entry.is_dir()}
        malformed_entries = sorted(entry.name for entry in entries if not entry.is_dir())
        if malformed_entries:
            issues.append(
                f"{plugin_name}: source package skills tree has non-directory entries: "
                + ", ".join(malformed_entries)
            )
        missing_skills = sorted(set(expected_skills) - actual_directories)
        extra_skills = sorted(actual_directories - set(expected_skills))
        if missing_skills:
            issues.append(
                f"{plugin_name}: source package is missing catalog skill directories: "
                + ", ".join(missing_skills)
            )
        if extra_skills:
            issues.append(
                f"{plugin_name}: source package has skill directories outside the loaded catalog: "
                + ", ".join(extra_skills)
            )
        for directory_name in sorted(set(expected_skills) & actual_directories):
            expected_source = expected_skills[directory_name]
            skill_directory = resolved_skills_root / directory_name
            try:
                resolved_directory = skill_directory.resolve(strict=True)
                resolved_directory.relative_to(resolved_skills_root)
            except OSError as exc:
                issues.append(
                    f"{plugin_name}/{directory_name}: source skill directory cannot be resolved: {exc}"
                )
                continue
            except ValueError:
                issues.append(
                    f"{plugin_name}/{directory_name}: source skill directory escapes package authority"
                )
                continue
            if resolved_directory != expected_source.path:
                issues.append(
                    f"{plugin_name}/{directory_name}: source skill directory does not match "
                    f"loaded catalog source; expected {expected_source.path}, "
                    f"found {resolved_directory}"
                )
                continue
            skill_file = resolved_directory / "SKILL.md"
            try:
                resolved_skill_file = skill_file.resolve(strict=True)
                resolved_skill_file.relative_to(resolved_directory)
            except OSError as exc:
                issues.append(
                    f"{plugin_name}/{directory_name}: source skill file cannot be resolved: {exc}"
                )
                continue
            except ValueError:
                issues.append(
                    f"{plugin_name}/{directory_name}: source skill file escapes package authority"
                )
                continue
            try:
                actual_identity = skill_frontmatter_name(resolved_skill_file)
            except SystemExit as exc:
                issues.append(f"{plugin_name}/{directory_name}: {exc}")
                continue
            expected_identity = expected_source.name
            if actual_identity != expected_identity:
                issues.append(
                    f"{plugin_name}/{directory_name}: catalog skill name changed after catalog load; "
                    f"expected {expected_identity!r}, found {actual_identity!r}"
                )
    issues.extend(
        repository_identity_issues(
            catalog.repo_root,
            plugin_sources=plugin_sources,
            _validated_identities=identities,
        )
    )
    if not issues and _validated_identities is not None:
        _validated_identities.update(identities)
    return issues


def plugin_cache_shape_issues(
    *,
    codex_home: Path,
    marketplace_name: str,
) -> list[str]:
    """Reject cache shapes that cannot be safely inspected or targeted."""

    cache_root = codex_home / "plugins" / "cache" / marketplace_name
    if not cache_root.exists():
        return []
    if not cache_root.is_dir() or cache_root.is_symlink():
        return [f"plugin cache marketplace root is not an inspectable directory: {cache_root}"]
    try:
        resolved_cache_root = cache_root.resolve(strict=True)
    except OSError as exc:
        return [f"plugin cache marketplace root cannot be resolved: {cache_root}: {exc}"]

    issues: list[str] = []
    for plugin_root in sorted(cache_root.iterdir(), key=lambda path: path.name):
        if not plugin_root.is_dir() or plugin_root.is_symlink():
            issues.append(f"plugin cache package entry is not an inspectable directory: {plugin_root}")
            continue
        try:
            resolved_plugin = plugin_root.resolve(strict=True)
            resolved_plugin.relative_to(resolved_cache_root)
        except (OSError, ValueError) as exc:
            issues.append(f"plugin cache package escapes marketplace root: {plugin_root}: {exc}")
            continue
        for version_root in sorted(plugin_root.iterdir(), key=lambda path: path.name):
            if not version_root.is_dir() or version_root.is_symlink():
                issues.append(
                    f"plugin cache version entry is not an inspectable directory: {version_root}"
                )
                continue
            try:
                version_root.resolve(strict=True).relative_to(resolved_plugin)
            except (OSError, ValueError) as exc:
                issues.append(f"plugin cache version escapes package root: {version_root}: {exc}")
    return issues


def plugin_cache_harness_issues(
    catalog: SkillCatalog,
    *,
    codex_home: Path,
    marketplace_name: str,
    ignored_plugin_names: set[str] | None = None,
) -> list[str]:
    """Require cache names to match the active Codex harness package set."""

    issues = plugin_cache_shape_issues(
        codex_home=codex_home,
        marketplace_name=marketplace_name,
    )
    if issues:
        return issues
    cache_root = codex_home / "plugins" / "cache" / marketplace_name
    if not cache_root.exists():
        return []
    cached_plugins = {path.name for path in cache_root.iterdir() if path.is_dir()}
    allowed = set(catalog.plugin_names) | set(ignored_plugin_names or ())
    extra = sorted(cached_plugins - allowed)
    if extra:
        issues.append(
            "cached oh-my-harness plugins have no canonical repository skills: "
            + ", ".join(extra)
        )
    return issues


def _cached_skill_identities(version_root: Path) -> tuple[set[str], list[str]]:
    issues: list[str] = []
    skills_root = version_root / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        return set(), [f"cache skills directory missing or not inspectable: {skills_root}"]
    try:
        resolved_version = version_root.resolve(strict=True)
        resolved_skills = skills_root.resolve(strict=True)
        resolved_skills.relative_to(resolved_version)
    except (OSError, ValueError) as exc:
        return set(), [f"cache skills directory escapes version root: {skills_root}: {exc}"]

    identities: set[str] = set()
    for entry in sorted(skills_root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or entry.is_symlink():
            issues.append(f"cache skill entry is not an inspectable directory: {entry}")
            continue
        skill_file = entry / "SKILL.md"
        try:
            resolved_entry = entry.resolve(strict=True)
            resolved_file = skill_file.resolve(strict=True)
            resolved_entry.relative_to(resolved_skills)
            resolved_file.relative_to(resolved_entry)
        except (OSError, ValueError) as exc:
            issues.append(f"cache skill path escapes version root: {entry}: {exc}")
            continue
        try:
            identity = skill_frontmatter_name(resolved_file)
        except SystemExit as exc:
            issues.append(str(exc))
            continue
        if identity in identities:
            issues.append(f"duplicate cached catalog skill name {identity!r} under {skills_root}")
            continue
        identities.add(identity)
    return identities, issues


def plugin_installation_issues(
    catalog: SkillCatalog,
    *,
    marketplace_name: str,
    excluded_skill_roots: tuple[Path, ...],
    codex_home: Path,
    rows: dict[tuple[str, str], PluginListRow],
    plugin_sources: dict[str, Path],
    ignored_alternate_marketplaces: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Validate the complete active plugin projection against canonical source."""

    source_identities: dict[str, PluginDistributionIdentity] = {}
    issues = [
        *plugin_package_issues(
            catalog, plugin_sources=plugin_sources,
            _validated_identities=source_identities,
        ),
        *plugin_cache_harness_issues(
            catalog,
            codex_home=codex_home,
            marketplace_name=marketplace_name,
        ),
    ]
    enabled = enabled_plugin_names(rows, marketplace_name=marketplace_name)
    issues.extend(
        codex_harness_issues(
            catalog,
            excluded_skill_roots=excluded_skill_roots,
            enabled_plugin_names=enabled,
        )
    )
    alternate_enabled = sorted(
        f"{plugin_name}@{marketplace}"
        for (marketplace, plugin_name), row in rows.items()
        if marketplace != marketplace_name
        and marketplace not in set(ignored_alternate_marketplaces or ())
        and plugin_name in set(catalog.plugin_names)
        and row.status == "installed, enabled"
    )
    if alternate_enabled:
        issues.append(
            "canonical skill plugins are also enabled through another marketplace: "
            + ", ".join(alternate_enabled)
        )

    expected_by_plugin: dict[str, set[str]] = {}
    for source in catalog.sources:
        expected_by_plugin.setdefault(source.plugin, set()).add(source.name)

    cache_marketplace_root = codex_home / "plugins" / "cache" / marketplace_name

    for plugin_name in catalog.plugin_names:
        source_root = plugin_sources.get(plugin_name)
        if source_root is None:
            continue
        try:
            source_name, source_version = plugin_manifest_identity(
                source_root / ".codex-plugin" / "plugin.json",
                label="source",
            )
        except ValueError as exc:
            issues.append(f"{plugin_name}: {exc}")
            continue
        if source_name != plugin_name:
            issues.append(
                f"{plugin_name}: source manifest name mismatch; found {source_name!r}"
            )
            continue

        row = rows.get((marketplace_name, plugin_name))
        if row is None:
            issues.append(f"{plugin_name}@{marketplace_name}: missing from `codex plugin list`")
        else:
            if row.status != "installed, enabled":
                issues.append(
                    f"{plugin_name}@{marketplace_name}: expected status 'installed, enabled', "
                    f"found {row.status!r}"
                )
            if row.version != source_version:
                issues.append(
                    f"{plugin_name}@{marketplace_name}: installed version mismatch; "
                    f"expected {source_version!r}, found {row.version!r}"
                )

        plugin_cache_root = cache_marketplace_root / plugin_name
        versions = (
            sorted(path for path in plugin_cache_root.iterdir() if path.is_dir())
            if plugin_cache_root.is_dir()
            else []
        )
        if len(versions) != 1:
            found = ", ".join(path.name for path in versions) or "none"
            issues.append(
                f"{plugin_name}@{marketplace_name}: expected exactly one inspectable cache version "
                f"{source_version!r}; found {found}"
            )
            continue
        version_root = versions[0]
        if version_root.is_symlink() or version_root.name != source_version:
            issues.append(
                f"{plugin_name}@{marketplace_name}: cache version mismatch or symlink; "
                f"expected {source_version!r}, found {version_root.name!r}"
            )
            continue
        try:
            cache_name, cache_version = plugin_manifest_identity(
                version_root / ".codex-plugin" / "plugin.json",
                label="cache",
            )
        except ValueError as exc:
            issues.append(f"{plugin_name}: {exc}")
            continue
        if (cache_name, cache_version) != (source_name, source_version):
            issues.append(
                f"{plugin_name}@{marketplace_name}: cache manifest identity mismatch; "
                f"expected {(source_name, source_version)!r}, found {(cache_name, cache_version)!r}"
            )

        issues.extend(
            f"{plugin_name}@{marketplace_name}: {issue}"
            for issue in plugin_cache_identity_issues(
                source_root=source_root,
                cache_root=version_root,
                _source_identity=source_identities.get(plugin_name),
            )
        )

        cached_identities, cache_issues = _cached_skill_identities(version_root)
        issues.extend(f"{plugin_name}: {issue}" for issue in cache_issues)
        expected_identities = expected_by_plugin[plugin_name]
        missing_identities = sorted(expected_identities - cached_identities)
        extra_identities = sorted(cached_identities - expected_identities)
        if missing_identities or extra_identities:
            details: list[str] = []
            if missing_identities:
                details.append("missing " + ", ".join(missing_identities))
            if extra_identities:
                details.append("extra " + ", ".join(extra_identities))
            issues.append(
                f"{plugin_name}@{marketplace_name}: cached catalog skill names differ from "
                f"canonical source ({'; '.join(details)})"
            )
    return issues


def excluded_skill_root_issues(
    catalog: SkillCatalog,
    *,
    roots: tuple[Path, ...],
) -> list[str]:
    """Reject duplicate catalog identities in roots outside harness ownership."""

    issues: list[str] = []
    expected_names = set(catalog.by_name)
    for root in roots:
        for name in sorted(expected_names):
            target = root / name
            if is_projection_link(target):
                destination = managed_destination(target, catalog)
                suffix = f" -> {destination}" if destination is not None else ""
                issues.append(
                    f"excluded skill root contains catalog identity {name}: {target}{suffix}"
                )
            elif target.exists():
                issues.append(
                    f"excluded skill root contains catalog identity {name}: {target}"
                )

        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            issues.append(f"excluded skill root is not inspectable: {root}: {exc}")
            continue
        for target in entries:
            if target.name in expected_names or not is_projection_link(target):
                continue
            destination = managed_destination(target, catalog)
            if destination is not None:
                issues.append(
                    "excluded skill root contains stale repository-owned projection: "
                    f"{target} -> {destination}"
                )
    return issues


def codex_harness_issues(
    catalog: SkillCatalog,
    *,
    excluded_skill_roots: tuple[Path, ...],
    enabled_plugin_names: set[str],
) -> list[str]:
    issues: list[str] = []
    expected_plugins = set(catalog.plugin_names)
    missing_plugins = sorted(expected_plugins - enabled_plugin_names)
    extra_plugins = sorted(enabled_plugin_names - expected_plugins)
    if missing_plugins:
        issues.append("skills-bearing plugins are not enabled: " + ", ".join(missing_plugins))
    if extra_plugins:
        issues.append(
            "enabled oh-my-harness plugins have no canonical repository skills: "
            + ", ".join(extra_plugins)
        )

    issues.extend(excluded_skill_root_issues(catalog, roots=excluded_skill_roots))
    return issues


def require_harness_closure(harness: str, issues: list[str]) -> None:
    if issues:
        raise SystemExit(
            f"{harness} harness closure failed with {len(issues)} issue(s): "
            + "; ".join(issues)
        )
