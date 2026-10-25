#!/usr/bin/env python3
"""Build the canonical skill catalog directly from repository source."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
_FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(?P<body>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
_CALLABLE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _require_yaml() -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised by the bootstrap contract
        raise SystemExit(
            "PyYAML is required. Run `python3 scripts/bootstrap_tooling_env.py`, then invoke "
            "this script with the oh-my-harness tooling Python."
        ) from exc
    return yaml


@dataclass(frozen=True)
class SkillSource:
    plugin: str
    name: str
    path: Path
    directory_name: str


@dataclass(frozen=True)
class SkillCatalog:
    sources: tuple[SkillSource, ...]
    repo_root: Path
    plugins_root: Path

    @property
    def by_name(self) -> dict[str, SkillSource]:
        return {source.name: source for source in self.sources}

    @property
    def plugin_names(self) -> tuple[str, ...]:
        return tuple(sorted({source.plugin for source in self.sources}))


def _resolved_within(path: Path, root: Path, *, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"cannot resolve {label}: {path}: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"{label} escapes repository authority: {path} -> {resolved}") from exc
    return resolved


def skill_frontmatter_name(skill_file: Path) -> str:
    """Return the validated bare catalog skill name from one SKILL.md file."""

    yaml = _require_yaml()
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read skill file: {skill_file}: {exc}") from exc
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SystemExit(f"skill file has no YAML frontmatter: {skill_file}")
    try:
        payload = yaml.safe_load(match.group("body"))
    except yaml.YAMLError as exc:
        raise SystemExit(f"skill frontmatter is invalid YAML: {skill_file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"skill frontmatter must be a mapping: {skill_file}")
    name = payload.get("name")
    if not isinstance(name, str) or not name or name != name.strip():
        raise SystemExit(f"skill frontmatter name must be a non-empty trimmed string: {skill_file}")
    if _CALLABLE_NAME.fullmatch(name) is None:
        raise SystemExit(f"skill frontmatter name is not a portable bare catalog skill name: {name!r}: {skill_file}")
    validate_skill_invocation(skill_file, payload)
    return name


def validate_skill_invocation(skill_file: Path, frontmatter: dict[str, Any]) -> None:
    """Keep declared cross-harness invocation policies consistent at discovery."""

    flags = [
        frontmatter[key]
        for key in ("disable-model-invocation", "disable_model_invocation")
        if key in frontmatter
    ]
    if any(not isinstance(value, bool) for value in flags):
        raise SystemExit(f"model-invocation flag must be a boolean: {skill_file}")
    if len(set(flags)) > 1:
        raise SystemExit(f"conflicting model-invocation flags: {skill_file}")

    agent_file = skill_file.parent / "agents" / "openai.yaml"
    if not agent_file.exists():
        if flags and flags[0]:
            raise SystemExit(f"explicit-only skill is missing Codex invocation metadata: {agent_file}")
        return
    yaml = _require_yaml()
    try:
        agent = yaml.safe_load(agent_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SystemExit(f"invalid Codex skill metadata: {agent_file}: {exc}") from exc
    if not isinstance(agent, dict):
        raise SystemExit(f"Codex skill metadata must be a mapping: {agent_file}")
    interface = agent.get("interface")
    policy = agent.get("policy", {})
    dependencies = agent.get("dependencies", {})
    sections = (
        ("metadata", agent, {"interface", "policy", "dependencies"}),
        ("interface", interface, {"display_name", "short_description", "icon_small", "icon_large", "brand_color", "default_prompt"}),
        ("policy", policy, {"allow_implicit_invocation"}),
        ("dependencies", dependencies, {"tools"}),
    )
    for label, values, allowed in sections:
        if not isinstance(values, dict):
            raise SystemExit(f"Codex {label} must be a mapping: {agent_file}")
        unknown = set(values) - allowed
        if unknown:
            raise SystemExit(f"unknown Codex {label} fields {sorted(map(str, unknown))}: {agent_file}")
    allow_implicit = policy.get("allow_implicit_invocation", True)
    if not isinstance(allow_implicit, bool):
        raise SystemExit(f"allow_implicit_invocation must be a boolean: {agent_file}")
    if flags and flags[0] == allow_implicit:
        raise SystemExit(f"Claude and Codex invocation policies disagree: {skill_file}")
    for key in ("display_name", "short_description"):
        value = interface.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"Codex {key} must be non-empty: {agent_file}")
    prompt = interface.get("default_prompt")
    if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
        raise SystemExit(f"Codex default_prompt must be non-empty: {agent_file}")
    color = interface.get("brand_color")
    if color is not None and (not isinstance(color, str) or re.fullmatch(r"#[0-9A-Fa-f]{6}", color) is None):
        raise SystemExit(f"Codex brand_color must use #RRGGBB: {agent_file}")
    for key in ("icon_small", "icon_large"):
        raw = interface.get(key)
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw.strip():
            raise SystemExit(f"Codex {key} must be a non-empty relative path: {agent_file}")
        relative = PurePosixPath(raw.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts or re.match(r"^[A-Za-z]:", raw):
            raise SystemExit(f"Codex {key} must stay inside the plugin archive: {agent_file}")
        asset = _resolved_within(skill_file.parent / relative, skill_file.parents[2].resolve(), label=f"Codex {key}")
        if not asset.is_file():
            raise SystemExit(f"Codex {key} must point to a file: {agent_file}")


def load_repo_skill_catalog(repo_root: Path = REPO_ROOT) -> SkillCatalog:
    """Return the repository-authoritative skill catalog without marketplace reads."""

    try:
        resolved_repo = repo_root.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"cannot resolve repository root: {repo_root}: {exc}") from exc
    plugins_root_path = resolved_repo / "plugins"
    if not plugins_root_path.is_dir():
        raise SystemExit(f"repository plugins directory does not exist: {plugins_root_path}")
    plugins_root = _resolved_within(plugins_root_path, resolved_repo, label="plugins directory")

    sources: list[SkillSource] = []
    for plugin_entry in sorted(plugins_root_path.iterdir(), key=lambda path: path.name):
        if not plugin_entry.is_dir():
            continue
        plugin_root = _resolved_within(plugin_entry, resolved_repo, label="plugin directory")
        skills_path = plugin_entry / "skills"
        if not skills_path.exists():
            continue
        if not skills_path.is_dir():
            raise SystemExit(f"plugin skills path is not a directory: {skills_path}")
        _resolved_within(skills_path, resolved_repo, label="plugin skills directory")

        for skill_entry in sorted(skills_path.iterdir(), key=lambda path: path.name):
            if skill_entry.name.startswith(".") and not skill_entry.is_dir():
                continue
            if not skill_entry.is_dir():
                raise SystemExit(f"malformed plugin skills entry is not a directory: {skill_entry}")
            skill_root = _resolved_within(skill_entry, resolved_repo, label="skill directory")
            skill_file_path = skill_entry / "SKILL.md"
            if not skill_file_path.is_file():
                raise SystemExit(f"malformed plugin skill directory (SKILL.md missing): {skill_entry}")
            skill_file = _resolved_within(skill_file_path, resolved_repo, label="skill file")
            name = skill_frontmatter_name(skill_file)
            sources.append(
                SkillSource(
                    plugin=plugin_root.name,
                    name=name,
                    path=skill_root,
                    directory_name=skill_entry.name,
                )
            )

    if not sources:
        raise SystemExit(f"no repository skills found under {plugins_root_path}/*/skills")

    owners: dict[str, list[SkillSource]] = {}
    for source in sources:
        owners.setdefault(source.name, []).append(source)
    collisions = {name: entries for name, entries in owners.items() if len(entries) > 1}
    if collisions:
        details = "; ".join(
            f"{name}: {', '.join(f'{entry.plugin}/{entry.directory_name}' for entry in entries)}"
            for name, entries in sorted(collisions.items())
        )
        raise SystemExit(f"duplicate catalog skill names in repository source: {details}")

    return SkillCatalog(
        sources=tuple(sorted(sources, key=lambda source: (source.name, source.plugin, source.directory_name))),
        repo_root=resolved_repo,
        plugins_root=plugins_root,
    )
