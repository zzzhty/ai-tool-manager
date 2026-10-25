#!/usr/bin/env python3
"""Install the user-level Watcher skill Codex hook handlers."""

from __future__ import annotations

import argparse

from .codex_hook_config import (
    DEFAULT_STATE_DIR,
    DEFAULT_TARGET,
    adapter_path,
    backup_existing_file,
    default_python,
    expand_path,
    install_skill_watcher_hooks,
    load_config,
    render_diff,
    write_config,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill install-hook",
        description="Install Watcher skill handlers into $CODEX_HOME/hooks.json.",
    )
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="Hook config path. Defaults to $CODEX_HOME/hooks.json.")
    parser.add_argument("--python", dest="python_path", default=str(default_python()), help="Python interpreter for the hook command.")
    parser.add_argument(
        "--repo-root",
        help="Canonical oh-my-harness repository root embedded in hook commands. Defaults to $OH_MY_HARNESS_ROOT.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the diff without writing.")
    parser.add_argument("--apply", action="store_true", help="Write the hook config.")
    args = parser.parse_args(argv)

    if args.dry_run and args.apply:
        raise SystemExit("choose only one of --dry-run or --apply")

    target = expand_path(args.target)
    python_path = expand_path(args.python_path)
    adapter = adapter_path(args.repo_root)

    if args.apply:
        if not python_path.is_file():
            raise SystemExit(f"hook Python interpreter does not exist: {python_path}")
        if not adapter.is_file():
            raise SystemExit(f"hook adapter does not exist: {adapter}")

    before = load_config(target)
    after, removed = install_skill_watcher_hooks(
        before,
        python_path=python_path,
        adapter=adapter,
        repo_root=args.repo_root,
    )

    print(f"target: {target}")
    print(f"handler: {python_path} {adapter}")
    if removed:
        print(f"replaced existing Watcher skill handlers: {removed}")
    print(render_diff(before if target.exists() else None, after, target), end="")

    if not args.apply:
        print("dry-run only; no changes written")
        return 0

    backup_path = backup_existing_file(target, state_dir=DEFAULT_STATE_DIR)
    write_config(target, after)
    if backup_path is not None:
        print(f"backup: {backup_path}")
    print(f"wrote Watcher skill hooks to {target}")
    print("open /hooks in Codex to review and trust the new command hook definitions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
