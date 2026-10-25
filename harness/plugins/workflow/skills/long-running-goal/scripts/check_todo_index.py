#!/usr/bin/env python3
"""Verify active, closed, or absent goal topology in TODO/README indexes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SHARED))

from markdown_contract import relative_markdown_links  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("active", "closed", "absent"),
        default="active",
        help="Expected goal/index topology (default: active).",
    )
    parser.add_argument(
        "--archived-goal",
        type=Path,
        help="Archived goal path; required only in closed mode.",
    )
    parser.add_argument("goal_file", type=Path)
    parser.add_argument("indexes", nargs="+", type=Path)
    args = parser.parse_args()

    goal = args.goal_file
    if args.mode == "closed" and args.archived_goal is None:
        parser.error("--archived-goal is required in closed mode")
    if args.mode != "closed" and args.archived_goal is not None:
        parser.error("--archived-goal is only valid in closed mode")

    goal_name = goal.name
    resolved_goal = goal.resolve()
    errors: list[str] = []
    index_links = {}
    for index in args.indexes:
        if not index.is_file():
            errors.append(f"missing index: {index}")
            continue
        index_links[index] = relative_markdown_links(index)

    if args.mode == "active":
        if not goal.is_file():
            errors.append(f"active: missing goal file: {goal}")
        for index, links in index_links.items():
            if not any(link.resolved == resolved_goal for link in links):
                errors.append(
                    f"{index}: missing exact Markdown link to active goal: {goal}"
                )
                for link in links:
                    if (
                        link.resolved.name.casefold() == goal_name.casefold()
                        and link.resolved != resolved_goal
                    ):
                        errors.append(
                            f"{index}: same-name link resolves elsewhere at line "
                            f"{link.line}: {link.target} -> {link.resolved}"
                        )
    else:
        if goal.exists():
            errors.append(f"{args.mode}: goal file still exists: {goal}")
        for index, links in index_links.items():
            for link in links:
                if link.resolved == resolved_goal:
                    errors.append(
                        f"{index}: stale active-goal link at line {link.line}: "
                        f"{link.target} -> {link.resolved}"
                    )

        if args.mode == "closed":
            archived_goal = args.archived_goal
            assert archived_goal is not None
            if not archived_goal.is_file():
                errors.append(f"closed: missing archived goal file: {archived_goal}")
            else:
                resolved_archive = archived_goal.resolve()
                if not any(
                    link.resolved == resolved_archive
                    for links in index_links.values()
                    for link in links
                ):
                    errors.append(
                        "closed: archived goal is not referenced by any selected index: "
                        f"{archived_goal}"
                    )

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    if args.mode == "active":
        print(f"{goal_name}: referenced by {len(args.indexes)} index file(s)")
    elif args.mode == "closed":
        print(
            f"{goal_name}: closed goal removed from active indexes and archive referenced"
        )
    else:
        print(f"{goal_name}: absent from goal path and selected indexes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
