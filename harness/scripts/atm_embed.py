#!/usr/bin/env python3
"""Materialize the ATM-embedded harness engine into a manager home.

Runs under the base Python (stdlib only) before any tooling venv exists.
The embedded source tree is copied into ``<home>/repo`` as a non-Git
"materialized" distribution whose identity is its content hash; manager
state records that identity, and Git-based update flows never run.

Subcommands:
  materialize --source S --home H   fresh home only: stage, swap, init state
  sync         --source S --home H  re-materialize, or adopt a legacy Git home
  bootstrap    --source S --home H  materialize (idempotent) + tooling venv
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))


def validate_manager_home(home: Path) -> None:
    """The manager home must be absent or an ordinary directory."""
    if home.exists() and (home.is_symlink() or not home.is_dir()):
        raise SystemExit(f"manager home must be an ordinary directory: {home}")


from manager_state import (
    STATE_SCHEMA_VERSION,
    ManagerLock,
    atomic_write_json,
    desired_file,
    load_current_operation,
    load_state_snapshot,
    manager_file,
    write_manager,
)
from plugin_package_identity import require_repository_identity

ATM_REPOSITORY = "https://github.com/zzzhty/ai-tool-manager"
MARKER_NAME = ".atm-embedded.json"
_COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo", ".venv")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _embedded_revision(payload: dict) -> str:
    import hashlib

    digest = hashlib.sha256(
        f"{payload['embeddedIdentity']}|{payload['embeddedVersion']}".encode("utf-8")
    ).hexdigest()
    return digest[:40]


def _read_marker(repo: Path) -> dict | None:
    marker = repo / MARKER_NAME
    if not marker.exists():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit(f"embedded engine marker is unreadable: {marker}") from None
    if not isinstance(payload, dict) or payload.get("sourceMode") != "atm-embedded":
        raise SystemExit(f"embedded engine marker is invalid: {marker}")
    return payload


def _write_state(home: Path, release: str, bundle: str, *, fresh: bool) -> None:
    marker_values = {
        "repository": ATM_REPOSITORY,
        "revision": _embedded_revision(
            {"embeddedIdentity": bundle, "embeddedVersion": release}
        ),
        "release_version": release,
        "bundle_identity": bundle,
        "channel": "embedded",
        "requested_ref": "embedded",
    }
    if fresh and not desired_file(home).is_file():
        # write_desired only updates an existing file; seed the initial payload
        # in the schema _validate_desired_payload accepts.
        atomic_write_json(
            desired_file(home),
            {
                "schemaVersion": STATE_SCHEMA_VERSION,
                "harnesses": [],
                "updatePolicy": {"channel": "stable"},
                "updatedAt": _now(),
            },
        )
    write_manager(home, status="ready", **marker_values)


def _stage_and_swap(source: Path, home: Path, release: str, bundle: str) -> None:
    repo = home / "repo"
    staging = home / f".repo.materialize-{uuid.uuid4().hex}"
    backups = home / "state" / "repair-backups"
    try:
        shutil.copytree(source, staging, ignore=_COPY_IGNORE)
        marker = {
            "sourceMode": "atm-embedded",
            "atmRepository": ATM_REPOSITORY,
            "embeddedVersion": release,
            "embeddedIdentity": bundle,
            "materializedAt": _now(),
        }
        (staging / MARKER_NAME).write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8"
        )
        if repo.exists():
            backups.mkdir(parents=True, exist_ok=True)
            preserved = backups / f"repo-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
            os.replace(repo, preserved)
            print(f"preserved previous checkout: {preserved}")
        os.replace(staging, repo)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _source_identity(source: Path) -> tuple[str, str]:
    payload = require_repository_identity(source)
    release = payload.get("releaseVersion")
    bundle = payload.get("bundleIdentity")
    if not isinstance(release, str) or not release:
        raise SystemExit("embedded source has no releaseVersion")
    if not isinstance(bundle, str) or not bundle:
        raise SystemExit("embedded source has no bundleIdentity")
    return release, bundle


def command_materialize(source: Path, home: Path) -> int:
    validate_manager_home(home)
    release, bundle = _source_identity(source)
    with ManagerLock(home):
        repo = home / "repo"
        if repo.exists():
            raise SystemExit(
                "manager home already has a checkout; run `atm harness sync` instead"
            )
        if manager_file(home).is_file():
            raise SystemExit(
                "manager home already has lifecycle state; run `atm harness sync` instead"
            )
        _stage_and_swap(source, home, release, bundle)
        _write_state(home, release, bundle, fresh=True)
    print(f"materialized embedded engine {release} ({bundle}) into {home / 'repo'}")
    return 0


def command_sync(source: Path, home: Path) -> int:
    validate_manager_home(home)
    release, bundle = _source_identity(source)
    with ManagerLock(home):
        if load_current_operation(home) is not None:
            raise SystemExit(
                "an interrupted manager operation is active; resolve it with "
                "`atm harness status` before syncing"
            )
        snapshot = load_state_snapshot(home)
        manager = snapshot.get("manager")
        if isinstance(manager, dict) and manager.get("status") == "degraded":
            raise SystemExit(
                "manager lifecycle is degraded; inspect `atm harness status` before syncing"
            )
        existing = _read_marker(home / "repo")
        if existing is not None and existing.get("embeddedIdentity") == bundle:
            print(f"embedded engine already materialized at {release}")
            return 0
        had_state = manager_file(home).is_file()
        _stage_and_swap(source, home, release, bundle)
        _write_state(home, release, bundle, fresh=not had_state)
        if had_state and snapshot.get("desiredHarnesses"):
            print(
                "recorded harnesses were kept; run `atm update skills --harness <ID>` "
                "to reapply them from the new embedded distribution"
            )
    print(f"synced embedded engine {release} ({bundle}) into {home / 'repo'}")
    return 0


def command_bootstrap(source: Path, home: Path, *, rebuild: bool = False) -> int:
    validate_manager_home(home)
    release, bundle = _source_identity(source)
    existing = _read_marker(home / "repo")
    if existing is None or existing.get("embeddedIdentity") != bundle or not manager_file(home).is_file():
        command_sync(source, home)
    else:
        print(f"embedded engine already materialized at {release}")
    command_line = [
        sys.executable,
        str(source / "scripts" / "bootstrap_tooling_env.py"),
        "--venv",
        str(home / "venv"),
    ]
    if rebuild:
        command_line.append("--rebuild")
    result = subprocess.run(command_line)
    if result.returncode != 0:
        raise SystemExit(f"tooling venv bootstrap failed with exit code {result.returncode}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("materialize", "copy the embedded source into a fresh manager home"),
        ("sync", "re-materialize, or adopt a legacy Git checkout"),
        ("bootstrap", "materialize (idempotent) and build the tooling venv"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--source", required=True, help="ATM's embedded engine source tree")
        child.add_argument("--home", required=True, help="manager home (ATM_HOME)")
        if name == "bootstrap":
            child.add_argument("--rebuild", action="store_true", help="Rebuild even a healthy tooling venv.")
    args = parser.parse_args()
    if getattr(args, "rebuild", False) and args.command != "bootstrap":
        parser.error("--rebuild only applies to bootstrap")
    return args


def main() -> int:
    args = parse_args()
    source = Path(args.source)
    home = Path(args.home)
    if not source.is_absolute() or not home.is_absolute():
        raise SystemExit("--source and --home must be absolute paths")
    if args.command == "bootstrap":
        return int(command_bootstrap(source, home, rebuild=args.rebuild) or 0)
    handlers = {
        "materialize": command_materialize,
        "sync": command_sync,
    }
    return int(handlers[args.command](source, home) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
