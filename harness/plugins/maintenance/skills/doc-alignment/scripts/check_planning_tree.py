#!/usr/bin/env python3
"""Lightweight checks for a TODO/goal planning tree."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def is_external(target: str) -> bool:
    lower = target.lower()
    return (
        not target
        or target.startswith("#")
        or lower.startswith(("http://", "https://", "mailto:", "tel:"))
        or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) is not None
    )


def check_links(root: Path) -> list[str]:
    errors: list[str] = []
    for file_path in root.rglob("*.md"):
        text = file_path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if is_external(target):
                continue
            path_only = target.split("#", 1)[0]
            if not path_only:
                continue
            if path_only.startswith("<") and path_only.endswith(">"):
                path_only = path_only[1:-1]
            resolved = (file_path.parent / path_only).resolve()
            ok = resolved.is_dir() if path_only.endswith(("/", "\\")) else resolved.exists()
            if not ok:
                line = text[: match.start()].count("\n") + 1
                errors.append(f"{file_path}:{line}: missing {target}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planning_root", type=Path)
    parser.add_argument(
        "--archive-dir",
        default="archive",
        help="Archive directory name relative to the planning root.",
    )
    parser.add_argument(
        "--index",
        action="append",
        default=None,
        help="Index file to check. Defaults to README.md and TODO.md when present.",
    )
    args = parser.parse_args()

    root = args.planning_root
    if not root.exists() or not root.is_dir():
        print(f"missing planning root: {root}", file=sys.stderr)
        return 1

    errors = check_links(root)

    archive_root = (root / args.archive_dir).resolve()
    markdown_files = sorted(root.rglob("*.md"))
    active_files = [
        path
        for path in markdown_files
        if archive_root not in path.resolve().parents and path.resolve() != archive_root
    ]
    archive_files = [path for path in markdown_files if archive_root in path.resolve().parents]

    if args.index is None:
        indexes = [path for path in (root / "README.md", root / "TODO.md") if path.exists()]
    else:
        indexes = [root / index for index in args.index]

    missing_indexes = [path for path in indexes if not path.exists()]
    for path in missing_indexes:
        errors.append(f"missing index: {path}")

    indexed_text = "\n".join(path.read_text(encoding="utf-8") for path in indexes if path.exists())
    for path in active_files:
        if path in indexes:
            continue
        if path.name not in indexed_text:
            errors.append(f"{path}: active file is not referenced by selected index files")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(
        f"{root}: planning tree OK "
        f"({len(active_files)} active md, {len(archive_files)} archive md, {len(indexes)} index md)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
