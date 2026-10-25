#!/usr/bin/env python3
"""Update deterministic Codex plugin generations and the distribution identity ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from plugin_package_identity import update_repository_identity


REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive content-addressed Codex plugin versions and repository identity."
    )
    parser.add_argument(
        "--release-version",
        help="Set the canonical oh-my-harness release version before deriving identities.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete generated identity payload as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = update_repository_identity(
        REPO_ROOT,
        release=args.release_version,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"release: {payload['releaseVersion']}")
        print(f"bundle identity: {payload['bundleIdentity']}")
        for plugin in payload["plugins"]:
            print(f"{plugin['name']}: {plugin['version']} ({plugin['contentSha256']})")


if __name__ == "__main__":
    main()
