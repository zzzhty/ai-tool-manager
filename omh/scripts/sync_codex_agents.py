#!/usr/bin/env python3
"""Sync the oh-my-harness subagent support file into a Codex agents directory."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = REPO_ROOT / "agents"
DEFAULT_CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
MANAGED_MARKER = "Managed by oh-my-harness scripts/sync_codex_agents.py."
RETIRED_MANAGED_MARKERS = frozenset(
    {"Managed by my-codex scripts/sync_codex_agents.py."}
)
SUPPORT_SOURCE_NAMES = ("operating-principles.md",)


@dataclass(frozen=True)
class SourceFile:
    path: Path
    target_name: str
    text: str


def expand_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(str(raw))).expanduser()


def load_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"source file must be UTF-8 text: {path}: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"cannot read source file: {path}: {exc}") from exc


def load_sources(source_root: Path) -> list[SourceFile]:
    if not source_root.is_dir():
        raise SystemExit(f"agent support source directory does not exist: {source_root}")

    sources: list[SourceFile] = []
    for name in SUPPORT_SOURCE_NAMES:
        path = source_root / name
        if not path.is_file():
            continue
        sources.append(SourceFile(path=path, target_name=path.name, text=load_text_file(path)))
    if not sources:
        expected = ", ".join(SUPPORT_SOURCE_NAMES)
        raise SystemExit(f"agent support source directory contains no managed support files: {source_root}; expected one of: {expected}")
    return sorted(sources, key=lambda source: source.target_name)


def managed_text(source: SourceFile) -> str:
    body = source.text
    if not body.endswith("\n"):
        body += "\n"
    return "\n".join(managed_header(source.target_name)) + "\n\n" + body


def managed_header(source_name: str) -> list[str]:
    return [
        f"# {MANAGED_MARKER}",
        f"# Source: agents/{source_name}",
        "# Do not edit this target file directly.",
    ]


def is_managed(path: Path) -> bool:
    try:
        first_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:3]
    except OSError:
        return False
    if len(first_lines) < 3:
        return False
    return (
        first_lines[0]
        in {
            managed_header("<source>")[0],
            *(f"# {marker}" for marker in RETIRED_MANAGED_MARKERS),
        }
        and first_lines[1].startswith("# Source: ")
        and first_lines[2] == managed_header("<source>")[2]
    )


def target_root_from_args(args: argparse.Namespace) -> Path:
    if args.target_root:
        return expand_path(args.target_root)
    return expand_path(args.codex_home) / "agents"


def print_plan(action: str, path: Path) -> None:
    print(f"{action}: {path}")


def sync_sources(
    sources: list[SourceFile],
    *,
    target_root: Path,
    dry_run: bool,
    check: bool,
    prune: bool,
    force: bool,
) -> int:
    expected_names = {source.target_name for source in sources}
    failures = 0

    if check:
        for source in sources:
            target = target_root / source.target_name
            expected = managed_text(source)
            if not target.exists():
                print_plan("missing", target)
                failures += 1
                continue
            actual = target.read_text(encoding="utf-8", errors="replace")
            if actual != expected:
                if not is_managed(target):
                    print_plan("unmanaged-drift", target)
                else:
                    print_plan("drift", target)
                failures += 1
            else:
                print_plan("ok", target)

        if prune and target_root.exists():
            for target in sorted(target_root.iterdir()):
                if not target.is_file():
                    continue
                if target.name not in expected_names and is_managed(target):
                    print_plan("extra-managed", target)
                    failures += 1

        if failures:
            print(f"agent support sync check failed with {failures} issue(s)")
            return 1
        print("agent support sync check OK")
        return 0

    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    for source in sources:
        target = target_root / source.target_name
        expected = managed_text(source)
        if target.exists():
            actual = target.read_text(encoding="utf-8", errors="replace")
            if actual == expected:
                print_plan("up-to-date", target)
                continue
            if not is_managed(target) and not force:
                raise SystemExit(
                    f"refusing to overwrite unmanaged target file: {target}; "
                    "use --force only after reviewing the file"
                )
            print_plan("would update" if dry_run else "update", target)
        else:
            print_plan("would write" if dry_run else "write", target)

        if not dry_run:
            target.write_text(expected, encoding="utf-8")

    if prune and target_root.exists():
        for target in sorted(target_root.iterdir()):
            if not target.is_file():
                continue
            if target.name in expected_names:
                continue
            if not is_managed(target):
                print_plan("keep unmanaged", target)
                continue
            print_plan("would prune" if dry_run else "prune", target)
            if not dry_run:
                target.unlink()

    if dry_run:
        print("dry-run only; no agent support files written")
    else:
        print("agent support sync complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the repo-managed Codex subagent support file.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT), help="Source directory containing the support file.")
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME), help="Codex home directory; target is <codex-home>/agents.")
    parser.add_argument("--target-root", help="Override the target agents directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned writes without modifying the target.")
    parser.add_argument("--check", action="store_true", help="Fail if target managed files are missing or out of sync.")
    parser.add_argument("--prune", action="store_true", help="Remove managed target files that no longer have source files.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting unmanaged target files with matching names.")
    args = parser.parse_args()

    source_root = expand_path(args.source_root)
    target_root = target_root_from_args(args)
    sources = load_sources(source_root)
    return sync_sources(
        sources,
        target_root=target_root,
        dry_run=args.dry_run,
        check=args.check,
        prune=args.prune,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
