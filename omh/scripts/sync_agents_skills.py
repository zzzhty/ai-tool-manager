#!/usr/bin/env python3
"""Manage a harness skill-directory projection from repository-authoritative skills."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
from pathlib import Path

from repo_skill_catalog import REPO_ROOT, SkillCatalog, load_repo_skill_catalog

_WINDOWS_MOUNT_POINT_REPARSE_TAG = getattr(
    stat,
    "IO_REPARSE_TAG_MOUNT_POINT",
    0xA0000003,
)
_WINDOWS_JUNCTION_COMMAND = (
    "$ErrorActionPreference = 'Stop'; "
    "New-Item -ItemType Junction "
    "-Path $env:OH_MY_HARNESS_SKILL_LINK_PATH "
    "-Target $env:OH_MY_HARNESS_SKILL_LINK_TARGET | Out-Null"
)


def expand_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(str(raw))).expanduser()


def is_junction(path: Path) -> bool:
    """Return whether path is a Windows directory junction."""

    check = getattr(path, "is_junction", None)
    if check is not None:
        return bool(check())
    if os.name != "nt":
        return False
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        getattr(metadata, "st_reparse_tag", None)
        == _WINDOWS_MOUNT_POINT_REPARSE_TAG
    )


def is_projection_link(path: Path) -> bool:
    """Return whether path is a supported harness skill projection link."""

    return path.is_symlink() or is_junction(path)


def path_comparison_key(path: str | Path) -> str:
    """Normalize path aliases for identity comparison without changing stored paths."""

    return os.path.normcase(os.path.realpath(os.fspath(path)))


def same_path(left: str | Path, right: str | Path) -> bool:
    """Return whether two existing or lexical paths identify the same location."""

    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError):
        return path_comparison_key(left) == path_comparison_key(right)


def is_plain_directory(path: Path) -> bool:
    """Recognize an ordinary directory, never a link, reparse point, or mount."""

    try:
        metadata = path.lstat()
    except OSError:
        return False
    if not stat.S_ISDIR(metadata.st_mode):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    if reparse_flag and file_attributes & reparse_flag:
        return False
    try:
        if os.path.ismount(path):
            return False
    except OSError:
        return False
    return True


def is_empty_plain_directory(path: Path) -> bool:
    """Recognize only empty ordinary directories."""

    if not is_plain_directory(path):
        return False
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
    return False


def create_projection_link(link: Path, destination: Path) -> None:
    """Create a POSIX directory symlink or a Windows directory junction."""

    if os.name != "nt":
        link.symlink_to(destination, target_is_directory=True)
        return

    env = os.environ.copy()
    env["OH_MY_HARNESS_SKILL_LINK_PATH"] = str(link)
    env["OH_MY_HARNESS_SKILL_LINK_TARGET"] = str(destination)
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _WINDOWS_JUNCTION_COMMAND,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except OSError as exc:
        raise SystemExit(
            f"failed to create Windows skill junction: {link} -> {destination}: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise SystemExit(
            "failed to create Windows skill junction "
            f"with exit code {completed.returncode}: {link} -> {destination}{suffix}"
        )


def managed_destination(link: Path, catalog: SkillCatalog) -> Path | None:
    """Return a canonical repository skill targeted by an owned projection link."""

    if not is_projection_link(link):
        return None
    destination = link.resolve(strict=False)
    try:
        relative = destination.relative_to(catalog.plugins_root)
    except ValueError:
        return None
    if len(relative.parts) != 3 or relative.parts[1] != "skills":
        return None
    return destination


def remove_projection_link(
    link: Path,
    catalog: SkillCatalog,
    *,
    expected_destination: Path,
) -> None:
    """Remove one projection link only after revalidating its exact destination."""

    destination = managed_destination(link, catalog)
    if destination is None or not same_path(destination, expected_destination):
        raise SystemExit(
            "refusing to remove changed or unmanaged skill projection link: "
            f"expected {link} -> {expected_destination}, found {destination}"
        )
    if is_junction(link):
        link.rmdir()
    elif link.is_symlink():
        link.unlink()
    else:  # pragma: no cover - guarded by managed_destination
        raise SystemExit(f"refusing to remove non-link skill projection entry: {link}")


def remove_interrupted_empty_directory(
    target: Path,
    *,
    target_root: Path,
    catalog_name: str,
) -> None:
    """Remove only an exact canonical empty ordinary-directory residue."""

    expected = target_root / catalog_name
    if target != expected or not is_empty_plain_directory(target):
        raise SystemExit(
            "refusing to remove skill projection entry that is not the exact empty "
            f"interrupted directory: {target}"
        )
    try:
        target.rmdir()
    except OSError as exc:
        raise SystemExit(
            "failed to remove empty interrupted skill projection directory; "
            f"the entry may have changed: {target}: {exc}"
        ) from exc


def preflight_layer(catalog: SkillCatalog, *, target_root: Path) -> None:
    """Fail before mutation when a canonical destination is owned by another source."""

    if os.path.lexists(target_root) and not is_plain_directory(target_root):
        raise SystemExit(
            f"refusing skill projection root that is not an ordinary directory: {target_root}"
        )
    for source in catalog.sources:
        target = target_root / source.name
        if is_projection_link(target):
            destination = managed_destination(target, catalog)
            if destination is None:
                raise SystemExit(f"refusing unmanaged skill projection link: {target}")
        elif target.exists():
            if not is_empty_plain_directory(target):
                raise SystemExit(f"refusing unmanaged skill projection entry: {target}")


def remove_all_managed_entries(
    catalog: SkillCatalog,
    *,
    target_root: Path,
    dry_run: bool,
) -> int:
    """Remove all repository-owned links and exact interrupted empty residues."""

    preflight_layer(catalog, target_root=target_root)
    if not target_root.is_dir():
        print(f"skill projection cleanup already clear: {target_root}")
        return 0

    managed_links: list[tuple[Path, Path]] = []
    interrupted_directories: list[Path] = []
    for target in sorted(target_root.iterdir(), key=lambda path: path.name):
        destination = managed_destination(target, catalog)
        if destination is not None:
            managed_links.append((target, destination))
        elif target.name in catalog.by_name and is_empty_plain_directory(target):
            interrupted_directories.append(target)

    for target, destination in managed_links:
        print_plan("would unlink" if dry_run else "unlink", target, destination)
        if not dry_run:
            remove_projection_link(
                target,
                catalog,
                expected_destination=destination,
            )
    for target in interrupted_directories:
        print_plan(
            "would remove interrupted empty directory"
            if dry_run
            else "remove interrupted empty directory",
            target,
        )
        if not dry_run:
            remove_interrupted_empty_directory(
                target,
                target_root=target_root,
                catalog_name=target.name,
            )

    action_count = len(managed_links) + len(interrupted_directories)
    if dry_run:
        print(f"dry-run only; would remove {action_count} managed projection entry(s)")
    else:
        print(f"skill projection cleanup complete: removed {action_count} entry(s)")
    return 0


def print_plan(action: str, target: Path, source: Path | None = None) -> None:
    suffix = f" -> {source}" if source is not None else ""
    print(f"{action}: {target}{suffix}")


def check_layer(
    catalog: SkillCatalog,
    *,
    target_root: Path,
    prune: bool,
) -> int:
    sources = catalog.sources
    expected = {source.name: source for source in sources}
    failures = 0

    if os.path.lexists(target_root) and not is_plain_directory(target_root):
        print_plan("unmanaged-root", target_root)
        print("skills projection check failed with 1 issue(s)")
        return 1

    for source in sources:
        target = target_root / source.name
        if is_projection_link(target):
            destination = managed_destination(target, catalog)
            if destination is None:
                print_plan("unmanaged-link", target)
                failures += 1
            elif destination != source.path:
                if destination.is_dir():
                    print_plan("drift", target, destination)
                else:
                    print_plan("dangling", target, destination)
                failures += 1
            else:
                print_plan("ok", target, destination)
        elif is_empty_plain_directory(target):
            print_plan("interrupted-empty-entry", target, source.path)
            failures += 1
        elif target.exists():
            print_plan("unmanaged-entry", target)
            failures += 1
        else:
            print_plan("missing", target, source.path)
            failures += 1

    if prune and target_root.is_dir():
        for target in sorted(target_root.iterdir()):
            if target.name in expected or not is_projection_link(target):
                continue
            destination = managed_destination(target, catalog)
            if destination is not None:
                print_plan("extra-managed", target, destination)
                failures += 1

    if failures:
        print(f"skills projection check failed with {failures} issue(s)")
        return 1
    print(f"skills projection check OK: {len(sources)} skill(s)")
    return 0


def sync_layer(
    catalog: SkillCatalog,
    *,
    target_root: Path,
    dry_run: bool,
    prune: bool,
) -> int:
    sources = catalog.sources
    expected = {source.name: source for source in sources}

    preflight_layer(catalog, target_root=target_root)

    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    for source in sources:
        target = target_root / source.name
        interrupted_empty = False
        destination: Path | None = None
        if is_projection_link(target):
            destination = managed_destination(target, catalog)
            if destination == source.path:
                print_plan("up-to-date", target, destination)
                continue
            if destination is None:
                raise SystemExit(f"refusing to replace unmanaged projection link: {target}")
            print_plan("would relink" if dry_run else "relink", target, source.path)
        elif is_empty_plain_directory(target):
            interrupted_empty = True
            print_plan(
                "would recover interrupted empty directory"
                if dry_run
                else "recover interrupted empty directory",
                target,
                source.path,
            )
        elif target.exists():
            raise SystemExit(f"refusing to replace unmanaged target: {target}")
        else:
            print_plan("would link" if dry_run else "link", target, source.path)

        if not dry_run:
            if destination is not None:
                remove_projection_link(
                    target,
                    catalog,
                    expected_destination=destination,
                )
            elif interrupted_empty:
                remove_interrupted_empty_directory(
                    target,
                    target_root=target_root,
                    catalog_name=source.name,
                )
            create_projection_link(target, source.path)

    if prune and target_root.is_dir():
        for target in sorted(target_root.iterdir()):
            if target.name in expected or not is_projection_link(target):
                continue
            destination = managed_destination(target, catalog)
            if destination is None:
                print_plan("keep unmanaged", target)
                continue
            print_plan("would prune" if dry_run else "prune", target, destination)
            if not dry_run:
                remove_projection_link(
                    target,
                    catalog,
                    expected_destination=destination,
                )

    if dry_run:
        print("dry-run only; no skills projection links written")
    else:
        print(f"skills projection sync complete: {len(sources)} skill(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage repository-authoritative skill projection links for one harness."
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root containing plugins/*/skills source.",
    )
    parser.add_argument(
        "--target-root",
        required=True,
        help="Exact harness projection root to manage.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned links without modifying the target.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Fail if exposed skills are missing or out of sync.")
    action.add_argument(
        "--remove-managed",
        action="store_true",
        help="Remove only repository-owned projection links and exact empty residues.",
    )
    parser.add_argument("--prune", action="store_true", help="Remove managed links for skills that no longer exist.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm --remove-managed mutation; not required for --dry-run.",
    )
    args = parser.parse_args()

    if args.remove_managed and args.prune:
        parser.error("--remove-managed already covers stale links; do not combine it with --prune")
    if args.remove_managed and not args.dry_run and not args.yes:
        parser.error("--remove-managed requires --yes unless --dry-run is set")

    repo_root = expand_path(args.repo_root)
    target_root = expand_path(args.target_root)
    catalog = load_repo_skill_catalog(repo_root)

    if args.check:
        return check_layer(catalog, target_root=target_root, prune=args.prune)
    if args.remove_managed:
        return remove_all_managed_entries(
            catalog,
            target_root=target_root,
            dry_run=args.dry_run,
        )
    return sync_layer(
        catalog,
        target_root=target_root,
        dry_run=args.dry_run,
        prune=args.prune,
    )


if __name__ == "__main__":
    raise SystemExit(main())
