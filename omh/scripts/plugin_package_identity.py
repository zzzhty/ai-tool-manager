#!/usr/bin/env python3
"""Derive and verify deterministic Codex plugin distribution identities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


IDENTITY_SCHEMA_VERSION = 1
IDENTITY_ALGORITHM = "sha256-canonical-plugin-tree-v1"
GENERATION_LENGTH = 16
VERSION_FILE = Path("VERSION")
MARKETPLACE_FILE = Path(".agents/plugins/marketplace.json")
IDENTITY_FILE = Path(".agents/plugins/distribution-identity.json")
PLUGIN_MANIFEST = Path(".codex-plugin/plugin.json")
CODEX_VERSION_PATTERN = re.compile(
    rf"^(?P<base>.+)\+codex\.(?P<generation>[0-9a-f]{{{GENERATION_LENGTH}}})$"
)
RELEASE_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
FULL_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_TRANSIENT_DIRECTORY_NAMES = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
_TRANSIENT_FILE_NAMES = frozenset({".DS_Store"})
_TRANSIENT_FILE_SUFFIXES = (".pyc", ".pyo")


class PluginIdentityError(ValueError):
    """Raised when a plugin package cannot produce a deterministic identity."""


@dataclass(frozen=True)
class PluginDistributionIdentity:
    name: str
    version_authority: str
    base_version: str
    version: str
    generation: str
    content_sha256: str

    def as_payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "versionAuthority": self.version_authority,
            "version": self.version,
            "generation": self.generation,
            "contentSha256": self.content_sha256,
        }


def _update_digest_record(digest: "hashlib._Hash", value: bytes) -> None:
    digest.update(len(value).to_bytes(8, byteorder="big"))
    digest.update(value)


def _canonical_text_payload(payload: bytes) -> bytes:
    if b"\0" in payload:
        return payload
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload
    return payload.replace(b"\r\n", b"\n")


def _metadata_is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(
        _REPARSE_POINT_FLAG
        and getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT_FLAG
    )


def _is_transient(relative: Path, *, is_directory: bool) -> bool:
    name = relative.name
    if is_directory:
        return name in _TRANSIENT_DIRECTORY_NAMES
    return name in _TRANSIENT_FILE_NAMES or name.endswith(_TRANSIENT_FILE_SUFFIXES)


def _canonical_manifest_payload(path: Path, *, base_version: str) -> bytes:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginIdentityError(f"plugin manifest is not valid readable JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PluginIdentityError(f"plugin manifest must be an object: {path}")
    payload["version"] = f"{base_version}+codex.<content-identity>"
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_plugin_package_digest(plugin_root: Path, *, base_version: str) -> str:
    """Hash the cross-platform canonical payload copied into the Codex plugin cache."""

    try:
        root_metadata = plugin_root.lstat()
    except OSError as exc:
        raise PluginIdentityError(f"plugin package root cannot be inspected: {plugin_root}: {exc}") from exc
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or _metadata_is_reparse_point(root_metadata)
        or plugin_root.is_symlink()
    ):
        raise PluginIdentityError(f"plugin package root must be an ordinary directory: {plugin_root}")

    entries: list[tuple[Path, str, Path]] = []
    pending = [plugin_root]
    casefolded: dict[str, str] = {}
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise PluginIdentityError(f"plugin package directory is unreadable: {directory}: {exc}") from exc
        for child in children:
            relative = child.relative_to(plugin_root)
            try:
                metadata = child.lstat()
            except OSError as exc:
                raise PluginIdentityError(f"plugin package entry cannot be inspected: {child}: {exc}") from exc
            is_directory = stat.S_ISDIR(metadata.st_mode)
            if _is_transient(relative, is_directory=is_directory):
                continue
            if child.is_symlink() or _metadata_is_reparse_point(metadata):
                raise PluginIdentityError(
                    f"plugin package contains a link or reparse point: {child}"
                )
            if is_directory:
                kind = "directory"
                pending.append(child)
            elif stat.S_ISREG(metadata.st_mode):
                kind = "file"
            else:
                raise PluginIdentityError(
                    f"plugin package contains an unsupported entry type: {child}"
                )

            portable_path = relative.as_posix()
            folded = portable_path.casefold()
            previous = casefolded.get(folded)
            if previous is not None and previous != portable_path:
                raise PluginIdentityError(
                    "plugin package contains case-colliding paths: "
                    f"{previous!r} and {portable_path!r}"
                )
            casefolded[folded] = portable_path
            entries.append((relative, kind, child))

    digest = hashlib.sha256()
    digest.update((IDENTITY_ALGORITHM + "\0").encode("ascii"))
    for relative, kind, path in sorted(entries, key=lambda item: item[0].as_posix()):
        _update_digest_record(digest, relative.as_posix().encode("utf-8"))
        _update_digest_record(digest, kind.encode("ascii"))
        if kind == "directory":
            payload = b""
        elif relative == PLUGIN_MANIFEST:
            payload = _canonical_manifest_payload(path, base_version=base_version)
        else:
            try:
                payload = _canonical_text_payload(path.read_bytes())
            except OSError as exc:
                raise PluginIdentityError(f"plugin package file is unreadable: {path}: {exc}") from exc
        _update_digest_record(digest, payload)
    return digest.hexdigest()


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginIdentityError(f"{label} is not valid readable JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PluginIdentityError(f"{label} must be an object: {path}")
    return payload


def release_version(repo_root: Path) -> str:
    path = repo_root / VERSION_FILE
    try:
        version = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PluginIdentityError(f"release version is unreadable: {path}: {exc}") from exc
    if RELEASE_VERSION_PATTERN.fullmatch(version) is None:
        raise PluginIdentityError(f"release version must be semantic x.y.z: {path}: {version!r}")
    return version


def _manifest_name_and_version(plugin_root: Path) -> tuple[str, str, dict[str, object]]:
    path = plugin_root / PLUGIN_MANIFEST
    payload = _load_json_object(path, label="plugin manifest")
    name = payload.get("name")
    version = payload.get("version")
    if not isinstance(name, str) or not name.strip():
        raise PluginIdentityError(f"plugin manifest name must be a non-empty string: {path}")
    if not isinstance(version, str) or not version.strip():
        raise PluginIdentityError(f"plugin manifest version must be a non-empty string: {path}")
    return name.strip(), version.strip(), payload


def expected_plugin_identity(
    repo_root: Path,
    plugin_root: Path,
    *,
    expected_name: str | None = None,
) -> PluginDistributionIdentity:
    name, _current_version, _payload = _manifest_name_and_version(plugin_root)
    if expected_name is not None and name != expected_name:
        raise PluginIdentityError(
            f"plugin manifest name mismatch; expected {expected_name!r}, found {name!r}: {plugin_root}"
        )
    base_version = release_version(repo_root)
    content_sha256 = canonical_plugin_package_digest(
        plugin_root,
        base_version=base_version,
    )
    generation = content_sha256[:GENERATION_LENGTH]
    return PluginDistributionIdentity(
        name=name,
        version_authority="release",
        base_version=base_version,
        version=f"{base_version}+codex.{generation}",
        generation=generation,
        content_sha256=content_sha256,
    )


def marketplace_plugin_roots(repo_root: Path) -> dict[str, Path]:
    path = repo_root / MARKETPLACE_FILE
    payload = _load_json_object(path, label="plugin marketplace")
    raw_plugins = payload.get("plugins")
    if not isinstance(raw_plugins, list):
        raise PluginIdentityError(f"plugin marketplace plugins must be an array: {path}")
    roots: dict[str, Path] = {}
    resolved_repo = repo_root.resolve(strict=True)
    for index, entry in enumerate(raw_plugins, start=1):
        if not isinstance(entry, dict):
            raise PluginIdentityError(f"plugin marketplace entry #{index} must be an object: {path}")
        name = entry.get("name")
        source = entry.get("source")
        if not isinstance(name, str) or not name.strip():
            raise PluginIdentityError(f"plugin marketplace entry #{index} has no name: {path}")
        if not isinstance(source, dict) or source.get("source") != "local":
            raise PluginIdentityError(
                f"plugin marketplace entry {name!r} must use a local source: {path}"
            )
        raw_source = source.get("path")
        if not isinstance(raw_source, str) or not raw_source.strip():
            raise PluginIdentityError(f"plugin marketplace entry {name!r} has no path: {path}")
        root = Path(os.path.expandvars(raw_source.strip())).expanduser()
        if not root.is_absolute():
            root = resolved_repo / root
        try:
            root = root.resolve(strict=True)
            root.relative_to(resolved_repo)
        except (OSError, ValueError) as exc:
            raise PluginIdentityError(
                f"plugin marketplace entry {name!r} escapes or is missing: {root}: {exc}"
            ) from exc
        plugin_name, _, _ = _manifest_name_and_version(root)
        if plugin_name != name.strip():
            raise PluginIdentityError(
                f"plugin marketplace/source name mismatch; expected {name!r}, found {plugin_name!r}"
            )
        if plugin_name in roots:
            raise PluginIdentityError(f"duplicate plugin marketplace name: {plugin_name!r}")
        roots[plugin_name] = root
    return roots


def _bundle_identity(release: str, identities: Iterable[PluginDistributionIdentity]) -> str:
    payload = {
        "algorithm": IDENTITY_ALGORITHM,
        "releaseVersion": release,
        "plugins": [
            {
                "name": identity.name,
                "version": identity.version,
                "contentSha256": identity.content_sha256,
            }
            for identity in sorted(identities, key=lambda item: item.name)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def distribution_identity_payload(
    release: str,
    identities: Iterable[PluginDistributionIdentity],
) -> dict[str, object]:
    ordered = tuple(sorted(identities, key=lambda item: item.name))
    return {
        "schemaVersion": IDENTITY_SCHEMA_VERSION,
        "algorithm": IDENTITY_ALGORITHM,
        "generationLength": GENERATION_LENGTH,
        "releaseVersion": release,
        "bundleIdentity": _bundle_identity(release, ordered),
        "plugins": [identity.as_payload() for identity in ordered],
    }


def _identity_file_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def repository_identity_issues(
    repo_root: Path,
    *,
    plugin_sources: Mapping[str, Path] | None = None,
    _validated_identities: dict[str, PluginDistributionIdentity] | None = None,
) -> list[str]:
    # Output only: computed identities may be reused within this read phase.
    if _validated_identities is not None:
        _validated_identities.clear()
    issues: list[str] = []
    try:
        release = release_version(repo_root)
        roots = dict(plugin_sources or marketplace_plugin_roots(repo_root))
        identities = []
        for name, root in sorted(roots.items()):
            identity = expected_plugin_identity(repo_root, root, expected_name=name)
            identities.append(identity)
            _, current_version, _ = _manifest_name_and_version(root)
            if current_version != identity.version:
                issues.append(
                    f"{name}: source content identity requires version {identity.version!r}; "
                    f"found {current_version!r}"
                )
        expected_payload = distribution_identity_payload(release, identities)
        identity_path = repo_root / IDENTITY_FILE
        try:
            actual_payload = _load_json_object(
                identity_path,
                label="plugin distribution identity",
            )
        except PluginIdentityError as exc:
            issues.append(str(exc))
        else:
            if actual_payload != expected_payload:
                issues.append(
                    "plugin distribution identity does not match the canonical plugin packages: "
                    f"{identity_path}"
                )
    except PluginIdentityError as exc:
        issues.append(str(exc))
    if not issues and _validated_identities is not None:
        _validated_identities.update((identity.name, identity) for identity in identities)
    return issues


def plugin_cache_identity_issues(
    *,
    source_root: Path,
    cache_root: Path,
    _source_identity: PluginDistributionIdentity | None = None,
) -> list[str]:
    """Compare cache bytes; standalone callers always hash the source too.

    The private identity is only for the enclosing closure read phase, never
    for reuse across a mutation, command, or checkout transition.
    """
    try:
        source_name, source_version, _ = _manifest_name_and_version(source_root)
        match = CODEX_VERSION_PATTERN.fullmatch(source_version)
        if match is None:
            return [
                f"source plugin version is not a content-derived Codex identity: {source_version!r}"
            ]
        base_version = match.group("base")
        if _source_identity is None:
            source_digest = canonical_plugin_package_digest(
                source_root, base_version=base_version,
            )
        else:
            if (source_name, source_version, base_version) != (
                _source_identity.name, _source_identity.version, _source_identity.base_version,
            ):
                return ["source manifest changed during closure validation"]
            source_digest = _source_identity.content_sha256
        cache_name, cache_version, _ = _manifest_name_and_version(cache_root)
        cache_digest = canonical_plugin_package_digest(
            cache_root,
            base_version=base_version,
        )
    except PluginIdentityError as exc:
        return [str(exc)]

    issues: list[str] = []
    if cache_name != source_name:
        issues.append(
            f"cache plugin name differs from source; expected {source_name!r}, found {cache_name!r}"
        )
    if cache_version != source_version:
        issues.append(
            f"cache plugin version differs from source; expected {source_version!r}, found {cache_version!r}"
        )
    if source_digest != cache_digest:
        issues.append(
            "cache content identity differs from canonical source; "
            f"expected {source_digest}, found {cache_digest}"
        )
    return issues


def _replace_text_file_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def update_repository_identity(
    repo_root: Path,
    *,
    release: str | None = None,
) -> dict[str, object]:
    """Update release-aligned versions and the repository identity ledger transactionally."""

    repo_root = repo_root.resolve(strict=True)
    version_path = repo_root / VERSION_FILE
    original_files: dict[Path, bytes | None] = {}

    def remember(path: Path) -> None:
        if path not in original_files:
            original_files[path] = path.read_bytes() if path.exists() else None

    if release is not None:
        if RELEASE_VERSION_PATTERN.fullmatch(release) is None:
            raise PluginIdentityError(f"release version must be semantic x.y.z: {release!r}")
        remember(version_path)
        _replace_text_file_atomically(version_path, (release + "\n").encode("utf-8"))

    try:
        current_release = release_version(repo_root)
        roots = marketplace_plugin_roots(repo_root)
        identities: list[PluginDistributionIdentity] = []
        for name, root in sorted(roots.items()):
            identity = expected_plugin_identity(repo_root, root, expected_name=name)
            manifest_path = root / PLUGIN_MANIFEST
            _, current_version, manifest_payload = _manifest_name_and_version(root)
            if current_version != identity.version:
                remember(manifest_path)
                manifest_payload["version"] = identity.version
                _replace_text_file_atomically(
                    manifest_path,
                    (
                        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n"
                    ).encode("utf-8"),
                )
            identities.append(identity)

        # Recompute after writes to prove the version-normalized digest is stable.
        identities = [
            expected_plugin_identity(repo_root, root, expected_name=name)
            for name, root in sorted(roots.items())
        ]
        payload = distribution_identity_payload(current_release, identities)
        identity_path = repo_root / IDENTITY_FILE
        remember(identity_path)
        _replace_text_file_atomically(identity_path, _identity_file_bytes(payload))
        issues = repository_identity_issues(repo_root, plugin_sources=roots)
        if issues:
            raise PluginIdentityError("; ".join(issues))
        return payload
    except BaseException:
        for path, original in reversed(tuple(original_files.items())):
            if original is None:
                if path.exists():
                    path.unlink()
            else:
                _replace_text_file_atomically(path, original)
        raise


def require_repository_identity(repo_root: Path) -> dict[str, object]:
    issues = repository_identity_issues(repo_root)
    if issues:
        raise SystemExit(
            f"plugin distribution identity failed with {len(issues)} issue(s): "
            + "; ".join(issues)
        )
    return _load_json_object(
        repo_root / IDENTITY_FILE,
        label="plugin distribution identity",
    )
