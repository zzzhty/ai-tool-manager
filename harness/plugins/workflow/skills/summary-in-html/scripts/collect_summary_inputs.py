#!/usr/bin/env python3
"""Collect a deterministic inventory for a summary-in-html artifact."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

ENTRYPOINT_NAMES = {
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Makefile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "deno.json",
    "tsconfig.json",
    "vite.config.ts",
}


def run_git(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def relative_to_root(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def resolve_scope(root: Path, raw_scope: str) -> Path:
    candidate = Path(raw_scope)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"scope is outside root: {raw_scope}") from exc
    if not resolved.exists():
        raise SystemExit(f"scope does not exist: {raw_scope}")
    return resolved


def iter_paths(scope: Path, root: Path, max_depth: int) -> list[Path]:
    if scope.is_file():
        return [scope]

    paths: list[Path] = []
    for current_root, dirs, files in os.walk(scope):
        current = Path(current_root)
        rel_depth = len(current.relative_to(scope).parts)
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        files = sorted(files)
        if rel_depth >= max_depth:
            dirs[:] = []
        for dirname in dirs:
            path = current / dirname
            if not is_ignored(path.relative_to(root)):
                paths.append(path)
        for filename in files:
            path = current / filename
            if not is_ignored(path.relative_to(root)):
                paths.append(path)
    return paths


def summarize_scope(scope: Path, root: Path, max_depth: int, max_files: int) -> dict[str, object]:
    paths = iter_paths(scope, root, max_depth)
    directories: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    extensions: Counter[str] = Counter()
    entrypoints: list[str] = []

    for path in paths:
        rel = relative_to_root(path, root)
        try:
            stat = path.stat()
        except OSError:
            continue
        if path.is_dir():
            directories.append({"path": rel})
            continue
        suffix = path.suffix.lower() or "[no extension]"
        extensions[suffix] += 1
        if path.name in ENTRYPOINT_NAMES or path.name.endswith(".config.js"):
            entrypoints.append(rel)
        if len(files) < max_files:
            files.append(
                {
                    "path": rel,
                    "size_bytes": stat.st_size,
                    "extension": suffix,
                }
            )

    return {
        "scope": relative_to_root(scope, root),
        "type": "file" if scope.is_file() else "directory",
        "directories": directories[:max_files],
        "files": files,
        "file_count_seen": sum(1 for path in paths if path.is_file()),
        "directory_count_seen": sum(1 for path in paths if path.is_dir()),
        "extensions": dict(sorted(extensions.items())),
        "entrypoints": sorted(entrypoints),
        "truncated_files": len(files) >= max_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository or project root.")
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="Path to summarize, relative to --root. May be passed multiple times.",
    )
    parser.add_argument("--out", type=Path, help="Write inventory JSON to this path.")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--max-files", type=int, default=400)
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.exists():
        print(f"root does not exist: {root}", file=sys.stderr)
        return 1
    if not root.is_dir():
        print(f"root is not a directory: {root}", file=sys.stderr)
        return 1

    raw_scopes = args.scope or ["."]
    scopes = [resolve_scope(root, raw_scope) for raw_scope in raw_scopes]
    git_root = run_git(root, ["rev-parse", "--show-toplevel"])
    git_head = run_git(root, ["rev-parse", "--short", "HEAD"])
    git_status = run_git(root, ["status", "--short"])

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "git": {
            "root": git_root,
            "head": git_head,
            "dirty": bool(git_status),
        },
        "scopes": [
            summarize_scope(scope, root, max_depth=args.max_depth, max_files=args.max_files)
            for scope in scopes
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote inventory: {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
