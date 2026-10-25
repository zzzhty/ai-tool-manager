#!/usr/bin/env python3
"""Validate a candidate SKILL.md file and optional explicit validation command."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from .runtime_paths import expand_path

TODO_PLACEHOLDER_RE = re.compile(r"\[TODO:[^]\r\n]*\]")


def load_yaml_module():
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyYAML is required for candidate validation. "
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


def validate_skill(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"candidate skill path does not exist: {path}")
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to read candidate skill {path}: {exc}") from exc
    if TODO_PLACEHOLDER_RE.search(contents):
        raise SystemExit(f"{path} contains a `[TODO: ...]` placeholder")

    frontmatter_text, body = split_frontmatter(contents, path)
    yaml = load_yaml_module()
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise SystemExit(f"{path} frontmatter is invalid YAML: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise SystemExit(f"{path} frontmatter must be a YAML object")
    for field in ("name", "description"):
        value = frontmatter.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SystemExit(f"{path} frontmatter field `{field}` must be non-empty")
    if not body.strip():
        raise SystemExit(f"{path} body must be non-empty")


def run_validation_command(command: str, cwd: Path | None) -> None:
    print(f"running explicit validation command: {command}")
    result = subprocess.run(command, shell=True, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        raise SystemExit(f"validation command failed with exit code {result.returncode}: {command}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill validate",
        description="Validate a candidate SKILL.md file.",
    )
    parser.add_argument("--candidate-skill", required=True, help="Path to candidate SKILL.md.")
    parser.add_argument(
        "--validation-command",
        action="append",
        help="Explicit command to run after static validation. May be provided more than once.",
    )
    parser.add_argument("--cwd", help="Working directory for validation commands.")
    args = parser.parse_args(argv)

    candidate_path = expand_path(args.candidate_skill).resolve()
    cwd = expand_path(args.cwd).resolve() if args.cwd else None
    validate_skill(candidate_path)
    validation_commands = args.validation_command or []
    for command in validation_commands:
        run_validation_command(command, cwd)
    if validation_commands:
        print(f"candidate validation passed: {candidate_path}")
    else:
        print(
            "candidate static checks passed; no explicit validation command was "
            f"provided, so human review is required: {candidate_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
