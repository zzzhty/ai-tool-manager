#!/usr/bin/env python3
"""Validate a Codex plugin without depending on a bundled system skill."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import yaml

from repo_skill_catalog import validate_skill_invocation

TODO_MARKER = "[TODO:"
PLUGIN_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\."
    r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
HEX_COLOR_RE = re.compile(r"^#[0-9A-F]{6}$", re.IGNORECASE)
ALLOWED_MANIFEST_FIELDS = {
    "id",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "skills",
    "hooks",
    "mcpServers",
    "apps",
    "interface",
}
ALLOWED_INTERFACE_FIELDS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
    "websiteURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "defaultPrompt",
    "default_prompt",
    "brandColor",
    "composerIcon",
    "logo",
    "logoDark",
    "screenshots",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a local Codex plugin.")
    parser.add_argument("plugin_path", help="Path to the plugin root directory")
    return parser.parse_args(argv)


def load_json_object(path: Path, *, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing {label}: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"unable to read {label}: {path}: {exc}")
        return None
    except json.JSONDecodeError as exc:
        errors.append(f"{label} must contain valid JSON: {path}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} must contain a JSON object: {path}")
        return None
    return payload


def reject_todo_markers(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, str):
        if TODO_MARKER in value:
            errors.append(f"{path} still contains a `[TODO: ...]` placeholder")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_todo_markers(item, f"{path}[{index}]", errors)
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_todo_markers(item, f"{path}.{key}", errors)


def require_non_empty_string(
    payload: dict[str, Any],
    field: str,
    errors: list[str],
    *,
    prefix: str | None = None,
) -> str | None:
    value = payload.get(field)
    label = f"{prefix}.{field}" if prefix else field
    if not isinstance(value, str) or not value.strip():
        errors.append(f"plugin.json field `{label}` must be a non-empty string")
        return None
    return value.strip()


def validate_optional_string(
    payload: dict[str, Any], field: str, errors: list[str], *, prefix: str | None = None
) -> None:
    if field not in payload:
        return
    require_non_empty_string(payload, field, errors, prefix=prefix)


def validate_https_url(
    payload: dict[str, Any], field: str, errors: list[str], *, prefix: str | None = None
) -> None:
    value = payload.get(field)
    if value is None:
        return
    parsed = urlparse(value) if isinstance(value, str) else None
    label = f"{prefix}.{field}" if prefix else field
    if parsed is None or parsed.scheme != "https" or not parsed.netloc:
        errors.append(f"plugin.json field `{label}` must be an absolute `https://` URL")


def component_path(
    plugin_root: Path,
    raw_path: Any,
    *,
    field: str,
    expected_kind: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        errors.append(f"plugin.json field `{field}` must be a non-empty relative path")
        return None
    portable = raw_path.replace("\\", "/")
    candidate = PurePosixPath(portable)
    if (
        not portable.startswith("./")
        or candidate.is_absolute()
        or any(part in {"", ".."} for part in candidate.parts)
    ):
        errors.append(f"plugin.json field `{field}` must stay inside the plugin root")
        return None
    resolved_root = plugin_root.resolve()
    resolved = (plugin_root / portable).resolve()
    if not resolved.is_relative_to(resolved_root):
        errors.append(f"plugin.json field `{field}` must stay inside the plugin root")
        return None
    exists = resolved.is_dir() if expected_kind == "directory" else resolved.is_file()
    if not exists:
        errors.append(f"plugin.json field `{field}` points to a missing {expected_kind}: {raw_path}")
        return None
    return resolved


def component_paths(
    plugin_root: Path,
    value: Any,
    *,
    field: str,
    expected_kind: str,
    errors: list[str],
) -> list[Path]:
    raw_paths = value if isinstance(value, list) else [value]
    if not raw_paths or not all(isinstance(item, str) for item in raw_paths):
        errors.append(f"plugin.json field `{field}` must be a path or array of paths")
        return []
    paths: list[Path] = []
    for index, raw_path in enumerate(raw_paths):
        label = f"{field}[{index}]" if isinstance(value, list) else field
        resolved = component_path(
            plugin_root,
            raw_path,
            field=label,
            expected_kind=expected_kind,
            errors=errors,
        )
        if resolved is not None:
            paths.append(resolved)
    return paths


def validate_skill_root(skill_root: Path, errors: list[str]) -> None:
    for entry in sorted(skill_root.iterdir(), key=lambda path: path.name):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            errors.append(f"skills entry must be a directory: {entry}")
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"skill `{entry.name}` is missing `SKILL.md`")
            continue
        try:
            contents = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"unable to read skill `{entry.name}`: {exc}")
            continue
        if not contents.startswith("---\n"):
            errors.append(f"skill `{entry.name}` must start with YAML frontmatter")
            continue
        frontmatter_end = contents.find("\n---", 4)
        if frontmatter_end == -1:
            errors.append(f"skill `{entry.name}` frontmatter is not closed")
            continue
        try:
            frontmatter = yaml.safe_load(contents[4:frontmatter_end])
        except yaml.YAMLError as exc:
            errors.append(f"skill `{entry.name}` frontmatter must be valid YAML: {exc}")
            continue
        if not isinstance(frontmatter, dict):
            errors.append(f"skill `{entry.name}` frontmatter must be an object")
            continue
        for field in ("name", "description"):
            value = frontmatter.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"skill `{entry.name}` frontmatter field `{field}` must be non-empty"
                )
        try:
            validate_skill_invocation(skill_file, frontmatter)
        except SystemExit as exc:
            errors.append(str(exc))


def validate_hooks(plugin_root: Path, value: Any, errors: list[str]) -> None:
    if isinstance(value, dict):
        return
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return
    paths = component_paths(
        plugin_root,
        value,
        field="hooks",
        expected_kind="file",
        errors=errors,
    )
    for path in paths:
        load_json_object(path, label="hook manifest", errors=errors)


def validate_interface(plugin_root: Path, value: Any, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append("plugin.json field `interface` must be an object")
        return
    for field in sorted(set(value) - ALLOWED_INTERFACE_FIELDS):
        errors.append(f"plugin.json field `interface.{field}` is not supported")
    for field in (
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
    ):
        validate_optional_string(value, field, errors, prefix="interface")
    capabilities = value.get("capabilities")
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or not all(isinstance(item, str) and item.strip() for item in capabilities)
    ):
        errors.append("plugin.json field `interface.capabilities` must be an array of strings")
    for field in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
        validate_https_url(value, field, errors, prefix="interface")
    brand_color = value.get("brandColor")
    if brand_color is not None and (
        not isinstance(brand_color, str) or HEX_COLOR_RE.fullmatch(brand_color) is None
    ):
        errors.append("plugin.json field `interface.brandColor` must use `#RRGGBB`")
    prompt = value.get("defaultPrompt", value.get("default_prompt"))
    if prompt is not None:
        prompts = prompt if isinstance(prompt, list) else [prompt]
        if (
            not prompts
            or len(prompts) > 3
            or not all(isinstance(item, str) and item.strip() and len(item) <= 128 for item in prompts)
        ):
            errors.append(
                "plugin.json field `interface.defaultPrompt` must be a string or up to 3 strings of at most 128 characters"
            )
    for field in ("composerIcon", "logo", "logoDark"):
        if field in value:
            component_path(
                plugin_root,
                value[field],
                field=f"interface.{field}",
                expected_kind="file",
                errors=errors,
            )
    screenshots = value.get("screenshots")
    if screenshots is not None:
        component_paths(
            plugin_root,
            screenshots,
            field="interface.screenshots",
            expected_kind="file",
            errors=errors,
        )


def validate_plugin(plugin_root: Path) -> list[str]:
    errors: list[str] = []
    if not plugin_root.is_dir() or plugin_root.is_symlink():
        return [f"plugin root must be an ordinary directory: {plugin_root}"]
    manifest = load_json_object(
        plugin_root / ".codex-plugin" / "plugin.json",
        label="`.codex-plugin/plugin.json`",
        errors=errors,
    )
    if manifest is None:
        return errors
    reject_todo_markers(manifest, "$", errors)
    for field in sorted(set(manifest) - ALLOWED_MANIFEST_FIELDS):
        errors.append(f"plugin.json field `{field}` is not supported")
    name = require_non_empty_string(manifest, "name", errors)
    if name is not None and (len(name) > 64 or PLUGIN_NAME_RE.fullmatch(name) is None):
        errors.append("plugin.json field `name` must be lowercase hyphen-case with at most 64 characters")
    version = require_non_empty_string(manifest, "version", errors)
    if version is not None and SEMVER_RE.fullmatch(version) is None:
        errors.append("plugin.json field `version` must be strict semver")
    require_non_empty_string(manifest, "description", errors)
    for field in ("id", "homepage", "repository", "license"):
        validate_optional_string(manifest, field, errors)
    keywords = manifest.get("keywords")
    if keywords is not None and (
        not isinstance(keywords, list)
        or not all(isinstance(item, str) and item.strip() for item in keywords)
    ):
        errors.append("plugin.json field `keywords` must be an array of strings")
    author = manifest.get("author")
    if author is not None:
        if not isinstance(author, dict):
            errors.append("plugin.json field `author` must be an object")
        else:
            for field in sorted(set(author) - {"name", "email", "url"}):
                errors.append(f"plugin.json field `author.{field}` is not supported")
            require_non_empty_string(author, "name", errors, prefix="author")
            validate_optional_string(author, "email", errors, prefix="author")
            validate_https_url(author, "url", errors, prefix="author")

    skill_roots: list[Path] = []
    if "skills" in manifest:
        skill_roots = component_paths(
            plugin_root,
            manifest["skills"],
            field="skills",
            expected_kind="directory",
            errors=errors,
        )
    elif (plugin_root / "skills").is_dir():
        skill_roots = [(plugin_root / "skills").resolve()]
    for skill_root in skill_roots:
        validate_skill_root(skill_root, errors)

    if "hooks" in manifest:
        validate_hooks(plugin_root, manifest["hooks"], errors)
    if "apps" in manifest:
        app_path = component_path(
            plugin_root,
            manifest["apps"],
            field="apps",
            expected_kind="file",
            errors=errors,
        )
        if app_path is not None:
            load_json_object(app_path, label="app manifest", errors=errors)
    if "mcpServers" in manifest and isinstance(manifest["mcpServers"], str):
        mcp_path = component_path(
            plugin_root,
            manifest["mcpServers"],
            field="mcpServers",
            expected_kind="file",
            errors=errors,
        )
        if mcp_path is not None:
            load_json_object(mcp_path, label="MCP manifest", errors=errors)
    elif "mcpServers" in manifest and not isinstance(manifest["mcpServers"], dict):
        errors.append("plugin.json field `mcpServers` must be a path or object")
    validate_interface(plugin_root, manifest.get("interface"), errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    expanded_root = Path(args.plugin_path).expanduser()
    if not expanded_root.is_absolute():
        expanded_root = Path.cwd() / expanded_root
    plugin_root = Path(os.path.abspath(expanded_root))
    errors = validate_plugin(plugin_root)
    if errors:
        print("Plugin validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Plugin validation passed: {plugin_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
