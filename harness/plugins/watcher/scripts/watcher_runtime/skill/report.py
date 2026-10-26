#!/usr/bin/env python3
"""Generate a report-only Watcher skill usage report."""

from __future__ import annotations

import argparse
import sys

from .report_pipeline import (
    DEFAULT_OVERLAP_MINUTES,
    ReportOutputPolicy,
    ReportQuery,
    format_timestamp,
    generate_report as run_report,
)
from .runtime_paths import (
    expand_path,
    log_file_path,
    state_dir_from_env_or_arg,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill report",
        description="Write a Watcher skill usage report under state reports/.",
    )
    parser.add_argument("--skill", help="Filter by effective skill name. Defaults to all skills.")
    parser.add_argument("--since", default="1d", help="Evidence window such as 1d, 24h, or ISO timestamp.")
    parser.add_argument("--state-dir", help="Runtime state directory. Defaults to $CODEX_HOME/watcher/skill.")
    parser.add_argument("--log-file", help="Explicit JSONL log path. Overrides --state-dir logs/events.jsonl.")
    parser.add_argument("--output", help="Explicit report output path.")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Use and update report-state.json; --since is only the first-run fallback window.",
    )
    parser.add_argument(
        "--overlap-minutes",
        type=int,
        default=DEFAULT_OVERLAP_MINUTES,
        help="Incremental safety overlap for late-arriving events. Defaults to 5 minutes.",
    )
    parser.add_argument("--print-report", action="store_true", help="Also print the full report to stdout.")
    args = parser.parse_args(argv)

    state_dir = state_dir_from_env_or_arg(args.state_dir)
    log_file = log_file_path(state_dir, args.log_file)
    result = run_report(
        ReportQuery(
            state_dir=state_dir,
            log_file=log_file,
            skill=args.skill,
            since_raw=args.since,
            incremental=args.incremental,
            overlap_minutes=args.overlap_minutes,
        ),
        ReportOutputPolicy(
            output=expand_path(args.output) if args.output else None,
            write_output=True,
        ),
    )

    print(f"report: {result.output}")
    print(f"window_since: {format_timestamp(result.window_since) if result.window_since is not None else 'all'}")
    print(f"window_until: {format_timestamp(result.window_until)}")
    print(f"events: {result.event_count}")
    print(
        "outcomes: " + ", ".join(f"{name}={count}" for name, count in sorted(result.outcome_counts.items()))
        if result.outcome_counts
        else "outcomes: none"
    )
    if result.state_path is not None:
        print(f"state: {result.state_path}")

    if args.print_report:
        print("", file=sys.stdout)
        print(result.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
