#!/usr/bin/env python3
"""Check relative Markdown links under an SOP directory or in one SOP file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SHARED))

from markdown_contract import missing_relative_links, render_link_errors  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    root = args.path
    if not root.exists():
        print(f"missing path: {root}", file=sys.stderr)
        return 1

    missing = missing_relative_links(root)
    if missing:
        return render_link_errors(missing)

    print(f"{root}: SOP markdown relative links OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
