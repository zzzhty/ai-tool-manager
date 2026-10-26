#!/usr/bin/env python3
"""Verify Codex plugin generations and the repository distribution identity."""

from __future__ import annotations

from pathlib import Path

from plugin_package_identity import require_repository_identity


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    payload = require_repository_identity(REPO_ROOT)
    print(f"release: {payload['releaseVersion']}")
    print(f"bundle identity: {payload['bundleIdentity']}")
    for plugin in payload["plugins"]:
        print(f"{plugin['name']}: {plugin['version']}")


if __name__ == "__main__":
    main()
