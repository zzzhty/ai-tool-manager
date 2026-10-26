#!/usr/bin/env python3
"""Summarize Watcher skill-domain JSONL logs as Markdown."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .report_pipeline import (
    ReportOutputPolicy,
    ReportQuery,
    generate_report as run_report,
)
from .runtime_paths import expand_path, log_file_path, state_dir_from_env_or_arg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill summarize",
        description="Summarize Watcher skill-domain JSONL logs.",
    )
    parser.add_argument("--skill", help="Filter by effective skill name.")
    parser.add_argument("--since", help="Filter by relative time such as 1d or ISO timestamp.")
    parser.add_argument("--state-dir", help="Runtime state directory. Defaults to $CODEX_HOME/watcher/skill.")
    parser.add_argument("--log-file", help="Explicit JSONL log path. Overrides --state-dir logs/events.jsonl.")
    parser.add_argument("--output", help="Write Markdown report to this path.")
    parser.add_argument("--write-report", action="store_true", help="Also write a timestamped report under state reports/.")
    args = parser.parse_args(argv)

    state_dir = state_dir_from_env_or_arg(args.state_dir)
    log_file = log_file_path(state_dir, args.log_file)
    output_path: Path | None = expand_path(args.output) if args.output else None
    result = run_report(
        ReportQuery(
            state_dir=state_dir,
            log_file=log_file,
            skill=args.skill,
            since_raw=args.since,
            display_since_raw=True,
        ),
        ReportOutputPolicy(
            output=output_path,
            write_output=output_path is not None or args.write_report,
        ),
    )

    if result.output is not None:
        print(f"wrote report to {result.output}", file=sys.stderr)
    print(result.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
