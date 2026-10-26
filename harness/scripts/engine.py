#!/usr/bin/env python3
"""Unified lifecycle manager for atm-harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from contextlib import nullcontext
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, Sequence

from harness_registry import (
    INSTRUCTIONS_MIGRATION_ORIENTATION,
    INSTRUCTIONS_MIGRATION_ID,
    INSTRUCTIONS_MIGRATION_STAGES,
    HarnessRegistry,
    HarnessRegistryError,
    load_harness_metadata,
)
from manager_paths import (
    PRODUCT_NAME,
    bin_path,
    expand_path,
    lexical_absolute,
    manager_home,
    repo_path,
    state_path,
    venv_path,
    venv_python,
)
from manager_state import (
    ManagerLock,
    begin_operation,
    desired_harnesses,
    finish_operation,
    load_current_operation,
    load_or_initialize,
    load_state_snapshot,
    remove_harness_receipt,
    translate_harness_receipts,
    validate_harness_receipts,
    update_operation,
    write_desired,
    write_harness_receipt,
    write_manager,
)
from plugin_package_identity import require_repository_identity
from embedded_identity import ALGORITHM, content_identity
from manager_environment import ensure_user_path

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_COMMANDS = {
    "machine",
    "install",
    "refresh",
    "remove",
    "update",
    "manager",
    "status",
    "check",
    "doctor",
    "recover",
    "repair",
    "version",
}
INTERNAL_COMMANDS = {
    "_resume-update",
    "_resume-rollback",
}
KNOWN_COMMANDS = PUBLIC_COMMANDS | INTERNAL_COMMANDS
SEMVER_TAG = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
INSTRUCTION_REGISTRY_PATH = ".agents/harnesses/registry.json"
INSTRUCTION_MIGRATION_STAGE_ORDER = {
    stage: index for index, stage in enumerate(INSTRUCTIONS_MIGRATION_STAGES)
}
GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _base_python() -> Path:
    return Path(getattr(sys, "_base_executable", None) or sys.executable).resolve(strict=True)


def _run(
    command: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(item) for item in command]
    print("+ " + subprocess.list2cmdline(rendered), file=sys.stderr, flush=True)
    return subprocess.run(
        rendered,
        cwd=cwd,
        text=True,
        capture_output=capture,
        check=check,
    )


def _git(repo: Path, *args: str, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", repo, *args], capture=capture, check=check)


def _git_text(repo: Path, *args: str) -> str:
    result = _git(repo, *args)
    return result.stdout.strip()


def _git_blob(repo: Path, revision: str, relative_path: str) -> bytes:
    object_name = f"{revision}:{relative_path}"
    try:
        tree = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", revision, "--", relative_path],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(f"cannot inspect update revision {revision[:12]}: {exc}") from exc
    if tree.returncode != 0:
        detail = tree.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(
            f"cannot inspect update revision {revision[:12]} at {relative_path}: {detail}"
        )
    try:
        mode = tree.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise SystemExit(
            f"update revision {revision[:12]} has a non-UTF-8 tree entry at {relative_path}"
        ) from exc
    if not mode or mode.split(maxsplit=1)[0] not in {"100644", "100755"}:
        raise SystemExit(
            f"update revision {revision[:12]} has no regular file at {relative_path}"
        )
    try:
        blob = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", object_name],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise SystemExit(
            f"cannot read update revision {revision[:12]} at {relative_path}: {exc}"
        ) from exc
    if blob.returncode != 0:
        detail = blob.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(
            f"cannot read update revision {revision[:12]} at {relative_path}: {detail}"
        )
    return blob.stdout


def _instruction_relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label} must be a non-empty relative path")
    raw = value.strip()
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    parts = raw.split("/")
    if (
        "\\" in raw
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise SystemExit(f"{label} must be a normalized repository-relative path")
    return raw


def _instruction_source_at_revision(repo: Path, revision: str) -> dict[str, object]:
    try:
        registry_text = _git_blob(
            repo,
            revision,
            INSTRUCTION_REGISTRY_PATH,
        ).decode("utf-8", errors="strict")
        payload = json.loads(registry_text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(
            f"update revision {revision[:12]} has an invalid harness registry: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SystemExit(
            f"update revision {revision[:12]} harness registry must be an object"
        )
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        raise SystemExit(
            f"update revision {revision[:12]} harness registry has no sources object"
        )
    instructions = sources.get("instructions")
    migration_record: dict[str, object] | None = None
    if isinstance(instructions, str):
        current = _instruction_relative_path(
            instructions,
            label="legacy registry instructions source",
        )
    elif isinstance(instructions, dict):
        if set(instructions) != {"current", "migration"}:
            raise SystemExit(
                f"update revision {revision[:12]} has unsupported instruction source fields"
            )
        current = _instruction_relative_path(
            instructions.get("current"),
            label="registry instructions current source",
        )
        migration = instructions.get("migration")
        if not isinstance(migration, dict):
            raise SystemExit("registry instruction migration must be an object")
        allowed = {"id", "stage", "peer", "requiredPredecessorRevision"}
        if set(migration) - allowed or not {"id", "stage", "peer"} <= set(migration):
            raise SystemExit("registry instruction migration fields are invalid")
        migration_id = migration.get("id")
        stage = migration.get("stage")
        if migration_id != INSTRUCTIONS_MIGRATION_ID:
            raise SystemExit(
                f"registry instruction migration id must be {INSTRUCTIONS_MIGRATION_ID!r}"
            )
        if stage not in INSTRUCTION_MIGRATION_STAGE_ORDER:
            raise SystemExit(f"registry instruction migration stage is invalid: {stage!r}")
        peer = _instruction_relative_path(
            migration.get("peer"),
            label="registry instruction migration peer",
        )
        if peer == current:
            raise SystemExit("registry instruction current source and peer must differ")
        expected_current, expected_peer = INSTRUCTIONS_MIGRATION_ORIENTATION[stage]
        if current != expected_current or peer != expected_peer:
            raise SystemExit(
                "registry instruction paths do not match the "
                f"{stage} migration orientation: current={expected_current!r}, "
                f"peer={expected_peer!r}"
            )
        predecessor = migration.get("requiredPredecessorRevision")
        if predecessor is not None and (
            not isinstance(predecessor, str) or not GIT_REVISION.fullmatch(predecessor)
        ):
            raise SystemExit(
                "registry instruction required predecessor must be a lowercase 40-character Git SHA"
            )
        if stage == "bridge-ready" and predecessor is not None:
            raise SystemExit("bridge-ready instruction migration cannot require a predecessor")
        if stage != "bridge-ready" and predecessor is None:
            raise SystemExit(f"{stage} instruction migration requires a predecessor")
        peer_blob = _git_blob(repo, revision, peer)
        current_blob = _git_blob(repo, revision, current)
        if stage in {"bridge-ready", "source-switched"} and current_blob != peer_blob:
            raise SystemExit(
                f"instruction sources are not byte-identical during {stage}"
            )
        migration_record = {
            "id": migration_id,
            "stage": stage,
            "peer": peer,
            "peerSha256": hashlib.sha256(peer_blob).hexdigest(),
        }
        if predecessor is not None:
            migration_record["requiredPredecessorRevision"] = predecessor
    else:
        raise SystemExit(
            f"update revision {revision[:12]} has an invalid instructions source"
        )
    source_blob = _git_blob(repo, revision, current)
    record: dict[str, object] = {
        "path": current,
        "sha256": hashlib.sha256(source_blob).hexdigest(),
    }
    if migration_record is not None:
        record["migration"] = migration_record
    return record


def _validate_instruction_transition(
    repo: Path,
    *,
    before_revision: str,
    target_revision: str,
    before_source: dict[str, object],
    target_source: dict[str, object],
) -> None:
    before_migration = before_source.get("migration")
    target_migration = target_source.get("migration")
    entering_target_stage = True
    if isinstance(before_migration, dict) and isinstance(target_migration, dict):
        if before_migration.get("id") != target_migration.get("id"):
            raise SystemExit("instruction source migration id changed across update")
        before_stage = before_migration.get("stage")
        target_stage = target_migration.get("stage")
        assert isinstance(before_stage, str) and isinstance(target_stage, str)
        entering_target_stage = before_stage != target_stage
        if abs(
            INSTRUCTION_MIGRATION_STAGE_ORDER[target_stage]
            - INSTRUCTION_MIGRATION_STAGE_ORDER[before_stage]
        ) > 1:
            raise SystemExit(
                "instruction source migration checkpoints must be traversed in order"
            )
    if isinstance(target_migration, dict) and entering_target_stage:
        predecessor = target_migration.get("requiredPredecessorRevision")
        if isinstance(predecessor, str):
            predecessor_source = _instruction_source_at_revision(repo, predecessor)
            predecessor_migration = predecessor_source.get("migration")
            if not isinstance(predecessor_migration, dict):
                raise SystemExit(
                    "instruction source migration predecessor has no migration contract"
                )
            if predecessor_migration.get("id") != target_migration.get("id"):
                raise SystemExit(
                    "instruction source migration predecessor has a different migration id"
                )
            target_stage = target_migration.get("stage")
            predecessor_stage = predecessor_migration.get("stage")
            assert isinstance(target_stage, str)
            expected_index = INSTRUCTION_MIGRATION_STAGE_ORDER[target_stage] - 1
            if expected_index < 0 or predecessor_stage != INSTRUCTIONS_MIGRATION_STAGES[expected_index]:
                raise SystemExit(
                    "instruction source migration predecessor is not the exact previous stage"
                )
            target_ancestry = _git(
                repo,
                "merge-base",
                "--is-ancestor",
                predecessor,
                target_revision,
                check=False,
            )
            if target_ancestry.returncode == 1:
                raise SystemExit(
                    "instruction source migration predecessor is not an ancestor "
                    "of the target revision"
                )
            if target_ancestry.returncode != 0:
                detail = (target_ancestry.stderr or target_ancestry.stdout).strip()
                raise SystemExit(
                    "cannot validate instruction source migration target ancestry: "
                    f"git exited {target_ancestry.returncode}: {detail or 'no detail'}"
                )
            current_ancestry = _git(
                repo,
                "merge-base",
                "--is-ancestor",
                predecessor,
                before_revision,
                check=False,
            )
            if current_ancestry.returncode == 1:
                raise SystemExit(
                    "instruction source migration requires the bridge checkpoint first; "
                    f"run `atm harness -- update --to {predecessor}`"
                )
            if current_ancestry.returncode != 0:
                detail = (current_ancestry.stderr or current_ancestry.stdout).strip()
                raise SystemExit(
                    "cannot validate instruction source migration current ancestry: "
                    f"git exited {current_ancestry.returncode}: {detail or 'no detail'}"
                )
    if isinstance(before_migration, dict) and not isinstance(target_migration, dict):
        before_stage = before_migration.get("stage")
        if (
            isinstance(before_stage, str)
            and INSTRUCTION_MIGRATION_STAGE_ORDER[before_stage]
            >= INSTRUCTION_MIGRATION_STAGE_ORDER["source-switched"]
        ):
            raise SystemExit(
                "cannot leave an active instruction source migration after source cutover"
            )


def _instruction_transition(
    repo: Path,
    before_revision: str,
    target_revision: str,
) -> tuple[dict[str, object], dict[str, object]]:
    before_source = _instruction_source_at_revision(repo, before_revision)
    target_source = _instruction_source_at_revision(repo, target_revision)
    _validate_instruction_transition(
        repo,
        before_revision=before_revision,
        target_revision=target_revision,
        before_source=before_source,
        target_source=target_source,
    )
    return before_source, target_source


def _journal_instruction_transition(
    home: Path,
    operation: dict,
) -> dict:
    before = operation.get("before")
    target = operation.get("target")
    if not isinstance(before, dict) or not isinstance(target, dict):
        raise SystemExit("update operation journal has invalid transition state")
    before_revision = before.get("revision")
    target_revision = target.get("revision")
    if not isinstance(before_revision, str) or not isinstance(target_revision, str):
        raise SystemExit("update operation journal has invalid transition revisions")
    before_source, target_source = _instruction_transition(
        REPO_ROOT,
        before_revision,
        target_revision,
    )
    for label, side, source in (
        ("before", before, before_source),
        ("target", target, target_source),
    ):
        recorded = side.get("instructionsSource")
        if recorded is not None and recorded != source:
            raise SystemExit(
                f"journaled {label} instruction source changed after update preflight"
            )
        side["instructionsSource"] = source
        from sync_harness_instructions import materialized_instruction_digest

        materialized = materialized_instruction_digest(
            REPO_ROOT, side["revision"], str(source["path"])
        )
        recorded_materialized = side.get("instructionsMaterializedSha256")
        if recorded_materialized is not None and recorded_materialized != materialized:
            raise SystemExit(
                f"journaled {label} instruction materialization changed after update preflight"
            )
        side["instructionsMaterializedSha256"] = materialized
    return update_operation(
        home,
        phase=str(operation.get("phase", "prepared")),
        before=before,
        target=target,
    )


def _repository(repo: Path) -> str:
    value = _git_text(repo, "config", "--get", "remote.origin.url")
    if not value:
        raise SystemExit(f"managed checkout has no remote.origin.url: {repo}")
    return value


def _revision(repo: Path) -> str:
    value = _git_text(repo, "rev-parse", "--verify", "HEAD")
    if not value:
        raise SystemExit(f"managed checkout HEAD is unavailable: {repo}")
    return value


def _worktree_clean(repo: Path) -> bool:
    return not _git_text(repo, "status", "--porcelain")


EMBEDDED_MARKER = ".atm-embedded.json"


def _embedded_source(repo: Path) -> dict | None:
    """The ATM-embedded engine marker, or None for standalone Git checkouts."""
    marker = repo / EMBEDDED_MARKER
    if not marker.exists():
        return None
    if not marker.is_file() or marker.is_symlink():
        raise SystemExit(f"embedded engine marker is invalid; run `atm harness sync`: {marker}")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit(f"embedded engine marker is unreadable; run `atm harness sync`: {marker}") from None
    if (not isinstance(payload, dict)
            or payload.get("sourceMode") != "atm-embedded"
            or not isinstance(payload.get("atmRepository"), str) or not payload["atmRepository"]
            or not isinstance(payload.get("embeddedVersion"), str) or not payload["embeddedVersion"]
            or not isinstance(payload.get("embeddedIdentity"), str) or not payload["embeddedIdentity"]):
        raise SystemExit(f"embedded engine marker is incomplete; run `atm harness sync`: {marker}")
    return payload


def _embedded_revision(payload: dict) -> str:
    """A stable 40-hex revision derived from the recorded embedded identity."""
    digest = hashlib.sha256(
        f"{payload.get('engineIdentity', payload['embeddedIdentity'])}|{payload['embeddedVersion']}".encode("utf-8")
    ).hexdigest()
    return digest[:40]


def _distribution(repo: Path) -> tuple[str, str]:
    payload = require_repository_identity(repo)
    release = payload.get("releaseVersion")
    bundle = payload.get("bundleIdentity")
    if not isinstance(release, str) or not release:
        raise SystemExit("distribution identity has no releaseVersion")
    if not isinstance(bundle, str) or not bundle:
        raise SystemExit("distribution identity has no bundleIdentity")
    return release, bundle


def _load_registry():
    from harness_registry import load_harness_registry

    return load_harness_registry(repo_root=REPO_ROOT)


def _resolve_plan(harness: str, *, codex_home: Path | None = None):
    from harness_registry import resolve_harness_plan

    environment = dict(os.environ)
    if codex_home is not None:
        environment["CODEX_HOME"] = str(codex_home)
    return resolve_harness_plan(
        _load_registry(),
        harness,
        repo_root=REPO_ROOT,
        environ=environment,
    )


def _state_context(
    home: Path,
    *,
    persist: bool,
    allow_manager_drift: bool = False,
    allow_degraded: bool = False,
    allow_active_operation: bool = False,
) -> tuple[dict, dict]:
    repo = repo_path(home)
    if repo.resolve(strict=False) != REPO_ROOT.resolve(strict=False):
        raise SystemExit(
            f"the engine must run from the managed checkout {repo}; found {REPO_ROOT}"
        )
    embedded = _embedded_source(repo)
    if embedded is not None:
        # Embedded installations ship with ATM releases: identity comes from the
        # recorded marker, and the content identity below is the drift check.
        if (embedded.get("engineIdentityAlgorithm") != ALGORITHM
                or embedded.get("engineIdentity") != content_identity(repo)):
            raise SystemExit("embedded engine identity differs; run `atm harness sync` to restore it")
        repository = embedded["atmRepository"]
        revision = _embedded_revision(embedded)
    else:
        repository = _repository(repo)
        revision = _revision(repo)
    release, bundle = _distribution(repo)
    manager, desired = load_or_initialize(
        home,
        repository=repository,
        revision=revision,
        release_version=release,
        bundle_identity=bundle,
        persist=persist,
    )
    active_operation = load_current_operation(home)
    if active_operation is not None and not allow_active_operation:
        raise SystemExit(
            "an interrupted manager operation is active; run `atm harness -- status` and "
            "`atm harness -- recover` before starting another lifecycle mutation: "
            f"{active_operation.get('command')} / {active_operation.get('phase')} "
            f"({active_operation.get('operationId')})"
        )
    if manager.get("status") == "degraded" and not allow_degraded:
        raise SystemExit(
            "manager lifecycle is degraded; run `atm harness -- status` and `atm harness -- recover` before "
            "starting another mutation"
        )
    if not allow_manager_drift:
        expected = {
            "repository": repository,
            "revision": revision,
            "releaseVersion": release,
            "bundleIdentity": bundle,
        }
        mismatched = [
            field for field, value in expected.items() if manager.get(field) != value
        ]
        if mismatched:
            if embedded is not None:
                raise SystemExit(
                    "embedded engine content differs from manager lifecycle state; "
                    "do not edit the materialized engine by hand: mismatched fields: "
                    + ", ".join(mismatched)
                    + "; run `atm harness sync` to restore the embedded distribution"
                )
            raise SystemExit(
                "managed checkout differs from manager lifecycle state; "
                "do not move the checkout outside `atm harness -- update`: mismatched fields: "
                + ", ".join(mismatched)
                + "; run `atm harness -- manager repair` to restore the recorded revision or "
                "`atm harness -- recover` if an update operation is active"
            )
    return manager, desired


def _validate_targets(targets: Iterable[str]) -> tuple[str, ...]:
    registry = _load_registry()
    try:
        return tuple(dict.fromkeys(registry.resolve_id(target) for target in targets))
    except HarnessRegistryError as exc:
        raise SystemExit(str(exc)) from exc


def _target_set(
    args: argparse.Namespace,
    *,
    desired: tuple[str, ...],
    mode: str,
) -> tuple[str, ...]:
    registry = _load_registry()
    explicit = list(getattr(args, "targets", []) or [])
    legacy = getattr(args, "harness", None)
    if legacy:
        explicit.append(legacy)
    if getattr(args, "all", False):
        if explicit:
            raise SystemExit("do not combine explicit harness targets with --all")
        if mode == "install":
            return registry.choices
        return _validate_targets(desired)
    if explicit:
        return _validate_targets(explicit)
    if mode == "install":
        return (registry.default_harness,)
    if mode == "remove":
        return ()
    return _validate_targets(desired)


def _common_refresh_args(args: argparse.Namespace, *, home: Path, harness: str) -> list[str]:
    command = [
        str(sys.executable),
        str(REPO_ROOT / "scripts" / "refresh_harness.py"),
        "--home",
        str(home),
        "--harness",
        harness,
        "--venv",
        str(venv_path(home)),
        "--python",
        str(sys.executable),
        "--skip-bootstrap",
    ]
    if getattr(args, "codex_home", None):
        command.extend(["--codex-home", str(Path(args.codex_home).expanduser())])
    if getattr(args, "codex", None):
        command.extend(["--codex", args.codex])
    if getattr(args, "machine_safe", False):
        command.append("--non-interactive")
    if getattr(args, "yes", False):
        command.append("--yes")
    if getattr(args, "dry_run", False):
        command.append("--dry-run")
    if getattr(args, "repair", False):
        command.append("--repair")
    if getattr(args, "migrate_marketplace", False):
        command.append("--migrate-marketplace")
    if getattr(args, "migrate_from_repo", None):
        command.extend(["--migrate-from-repo", args.migrate_from_repo])
    if getattr(args, "operation_id", None):
        command.extend(["--operation-id", args.operation_id])
    return command


def _check_args(args: argparse.Namespace, *, home: Path, harness: str, strict: bool = False) -> list[str]:
    command = [
        str(sys.executable),
        str(REPO_ROOT / "scripts" / "check_harness.py"),
        "--home",
        str(home),
        "--harness",
        harness,
        "--venv",
        str(venv_path(home)),
        "--python",
        str(sys.executable),
    ]
    if getattr(args, "codex_home", None):
        command.extend(["--codex-home", str(Path(args.codex_home).expanduser())])
    if getattr(args, "codex", None):
        command.extend(["--codex", args.codex])
    if strict:
        command.append("--strict-warnings")
    return command


def _refresh_one(
    args: argparse.Namespace,
    *,
    home: Path,
    harness: str,
    check_after: bool,
) -> None:
    _run(_common_refresh_args(args, home=home, harness=harness))
    if not getattr(args, "dry_run", False) and check_after:
        _run(_check_args(args, home=home, harness=harness))


def _write_harness_state(home: Path, harness: str, *, codex_home: str | Path | None = None) -> None:
    release, bundle = _distribution(REPO_ROOT)
    plan = _resolve_plan(harness, codex_home=expand_path(codex_home) if codex_home else None)
    embedded = _embedded_source(REPO_ROOT)
    revision = _embedded_revision(embedded) if embedded is not None else _revision(REPO_ROOT)
    write_harness_receipt(
        home,
        harness=harness,
        manager_revision=revision,
        release_version=release,
        bundle_identity=bundle,
        root=str(plan.root),
    )


def _machine_preflight(args: argparse.Namespace, home: Path, mode: str) -> None:
    """Check all selected instruction targets under the existing mutation lock."""
    if not getattr(args, "machine_safe", False):
        return
    from sync_harness_instructions import prepare_instruction_sync

    _, desired = _state_context(home, persist=False, allow_degraded=mode == "repair")
    installed = desired_harnesses(desired)
    targets = _target_set(args, desired=installed, mode="refresh" if mode == "repair" else mode)
    if mode == "repair" and not set(targets) <= set(installed):
        raise SystemExit("machine repair requires recorded installed harness targets; use install to add a harness")
    for harness in targets:
        prepare_instruction_sync(
            _resolve_plan(harness), dry_run=False, assume_yes=True,
            non_interactive=True,
        )


def command_install(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    with nullcontext() if args.dry_run else ManagerLock(home):
        _machine_preflight(args, home, "install")
        manager, desired_state = _state_context(home, persist=not args.dry_run)
        desired = list(desired_harnesses(desired_state))
        targets = _target_set(args, desired=tuple(desired), mode="install")
        for harness in targets:
            _refresh_one(
                args,
                home=home,
                harness=harness,
                check_after=not args.no_check,
            )
            if args.dry_run:
                continue
            if harness not in desired:
                desired.append(harness)
            write_desired(home, desired)
            _write_harness_state(home, harness, codex_home=getattr(args, "codex_home", None))
        if not targets:
            print("no harness distributions selected")
    return 0


def command_refresh(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    with nullcontext() if args.dry_run else ManagerLock(home):
        _machine_preflight(args, home, "refresh")
        _manager, desired_state = _state_context(home, persist=not args.dry_run)
        targets = _target_set(
            args,
            desired=desired_harnesses(desired_state),
            mode="refresh",
        )
        if not targets:
            print("no installed harness distributions to refresh")
            return 0
        for harness in targets:
            _refresh_one(
                args,
                home=home,
                harness=harness,
                check_after=not args.no_check,
            )
            if not args.dry_run:
                _write_harness_state(home, harness, codex_home=getattr(args, "codex_home", None))
                write_desired(home, desired_harnesses(desired_state))
    return 0


def _remove_one(args: argparse.Namespace, *, home: Path, harness: str) -> None:
    command = [
        str(sys.executable),
        str(REPO_ROOT / "scripts" / "remove_harness.py"),
        "--harness",
        harness,
        "--home",
        str(home),
        "--python",
        str(sys.executable),
    ]
    if getattr(args, "codex_home", None):
        command.extend(["--codex-home", args.codex_home])
    if getattr(args, "codex", None):
        command.extend(["--codex", args.codex])
    if getattr(args, "dry_run", False):
        command.append("--dry-run")
        for removed in getattr(args, "preview_removed", ()):
            command.extend(["--preview-removed", removed])
    if getattr(args, "yes", False):
        command.append("--yes")
    _run(command)


def command_remove(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    with nullcontext() if args.dry_run else ManagerLock(home):
        _manager, desired_state = _state_context(home, persist=not args.dry_run)
        desired = list(desired_harnesses(desired_state))
        targets = _target_set(args, desired=tuple(desired), mode="remove")
        if not targets:
            raise SystemExit("remove requires an installed harness target or --all")
        not_installed = sorted(set(targets) - set(desired))
        if not_installed:
            raise SystemExit(
                "harness target is not installed according to desired state: "
                + ", ".join(not_installed)
            )
        for harness in targets:
            validate_harness_receipts(home, harness)
        args.preview_removed = []
        for harness in targets:
            _remove_one(args, home=home, harness=harness)
            if args.dry_run:
                args.preview_removed.append(harness)
                continue
            desired.remove(harness)
            write_desired(home, desired)
            remove_harness_receipt(home, harness)
    return 0


def command_check(args: argparse.Namespace, *, strict: bool = False) -> int:
    home = lexical_absolute(manager_home(args.home))
    _manager, desired_state = _state_context(
        home,
        persist=False,
        allow_manager_drift=True,
        allow_degraded=True,
        allow_active_operation=True,
    )
    targets = _target_set(
        args,
        desired=desired_harnesses(desired_state),
        mode="check",
    )
    if not targets:
        print("no installed harness distributions to check")
        return 0
    for harness in targets:
        _run(_check_args(args, home=home, harness=harness, strict=strict))
    return 0


def _recorded_snapshot(home: Path) -> dict:
    try:
        registry = load_harness_metadata(repo_root=REPO_ROOT)
    except HarnessRegistryError:
        registry = None
    return load_state_snapshot(home, registry=registry)


def command_status(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    payload = {
        "product": PRODUCT_NAME, "home": str(home),
        **_recorded_snapshot(home),
        "worktreeClean": None,
        "observation": "recorded-state-only",
    }
    if getattr(args, "registry_error", None):
        payload["registryWarning"] = args.registry_error
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    manager = payload["manager"]
    print(f"{PRODUCT_NAME}: recorded state (not a live health check)")
    print(f"home: {home}")
    if manager:
        print(f"recorded version: {manager['releaseVersion']}")
        print(f"recorded revision: {manager['revision']}")
        print(f"recorded bundle: {manager['bundleIdentity']}")
        print(f"channel: {manager['channel']}")
        print(f"recorded status: {manager['status']}")
    else:
        print(f"state: {payload['stateKind']}; current version unknown; run atm harness -- repair")
    print("desired harnesses: " + (", ".join(payload["desiredHarnesses"]) or "<none recorded>"))
    print("worktree: unchecked; use atm harness -- check or atm harness -- doctor for live validation")
    current_op = payload["operation"]
    if current_op:
        print(f"operation: {current_op['command']} / {current_op['phase']} ({current_op['operationId']})")
    else:
        print("operation: none")
    if "registryWarning" in payload:
        print("registry warning: " + payload["registryWarning"])
    return 0


def command_version(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    snapshot = _recorded_snapshot(home)
    manager = snapshot["manager"]
    payload = {
        "product": PRODUCT_NAME,
        "releaseVersion": manager["releaseVersion"] if manager else None,
        "revision": manager["revision"] if manager else None,
        "bundleIdentity": manager["bundleIdentity"] if manager else None,
        "observation": "recorded-state-only", "stateKind": snapshot["stateKind"],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{PRODUCT_NAME} recorded version: {payload['releaseVersion'] or 'unknown'}")
        print(f"recorded revision: {payload['revision'] or 'unknown'}")
        print(f"recorded bundle: {payload['bundleIdentity'] or 'unknown'}")
    return 0


def _latest_stable_tag(repo: Path) -> str:
    result = _git_text(repo, "tag", "--list", "v*", "--sort=-v:refname")
    for line in result.splitlines():
        tag = line.strip()
        if SEMVER_TAG.fullmatch(tag):
            return tag
    raise SystemExit("no stable vX.Y.Z release tag is available from origin")


def _target_revision(repo: Path, *, channel: str, requested: str | None) -> tuple[str, str]:
    if requested:
        ref = requested
    elif channel == "main":
        ref = "origin/main"
    else:
        ref = _latest_stable_tag(repo)
    result = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"update target cannot be resolved: {ref}: {detail}")
    return ref, result.stdout.strip()


def _validate_update_target(repo: Path, target_revision: str) -> tuple[str, str]:
    staging = repo.parent / f".update-validate-{uuid.uuid4().hex}"
    _git(repo, "worktree", "add", "--detach", str(staging), target_revision, capture=False)
    try:
        checker = staging / "scripts" / "check_plugin_generations.py"
        if not checker.is_file():
            raise SystemExit(f"update target has no distribution identity checker: {checker}")
        _run([str(_base_python()), str(checker)], cwd=staging)
        version = (staging / "VERSION").read_text(encoding="utf-8").strip()
        identity = json.loads(
            (staging / ".agents" / "plugins" / "distribution-identity.json").read_text(
                encoding="utf-8"
            )
        )
        if identity.get("releaseVersion") != version:
            raise SystemExit(
                "update target VERSION and distribution identity disagree: "
                f"{version!r} vs {identity.get('releaseVersion')!r}"
            )
        bundle = identity.get("bundleIdentity")
        if not isinstance(bundle, str) or not bundle:
            raise SystemExit("update target distribution identity has no bundleIdentity")
        return version, bundle
    finally:
        _git(repo, "worktree", "remove", "--force", str(staging), capture=False, check=False)


def _bootstrap_tooling(home: Path) -> None:
    _run(
        [
            str(_base_python()),
            str(REPO_ROOT / "scripts" / "bootstrap_tooling_env.py"),
            "--venv",
            str(venv_path(home)),
        ]
    )


def _invoke_internal(repo: Path, home: Path, command: str, *extra: str) -> subprocess.CompletedProcess[str]:
    python = venv_python(venv_path(home))
    cli = repo / "scripts" / "engine.py"
    return _run(
        [
            str(python),
            str(cli),
            "--home",
            str(home),
            command,
            *extra,
        ],
        check=False,
    )


def _harness_names_at_revision(repo: Path, revision: str, harnesses: Iterable[str]) -> tuple[str, ...]:
    """Translate only registry-owned names before handing state to another version."""
    names = tuple(harnesses)
    if not names:
        return ()
    try:
        target = json.loads(_git_blob(repo, revision, INSTRUCTION_REGISTRY_PATH))["harnesses"]
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit("update target has an invalid harness registry") from exc
    if not isinstance(target, dict):
        raise SystemExit("update target has an invalid harness registry")
    registry = _load_registry()
    translated = set()
    for name in names:
        try:
            translated.add(registry.id_for_target(name, target))
        except HarnessRegistryError as exc:
            raise SystemExit(str(exc)) from exc
    return tuple(sorted(translated))


def _finish_harness_name_migration(home: Path, desired: dict) -> None:
    # Run only after closing the update journal: pre-alias managers must still be
    # able to roll back an interrupted upgrade using their original desired IDs.
    try:
        for harness in desired_harnesses(desired):
            _write_harness_state(home, harness)
        write_desired(home, desired_harnesses(desired))
    except (Exception, SystemExit) as exc:
        # The update is already committed and aliases remain valid in this
        # manager. Do not send an old caller into rollback with a closed journal.
        print(f"update completed; harness-name state migration deferred: {exc}; "
              "run `atm harness -- refresh` to retry", file=sys.stderr)


def command_update(args: argparse.Namespace) -> int:
    shortcut = getattr(args, "target", None)
    if shortcut:
        if args.channel or args.to:
            raise SystemExit("use one update target: positional TARGET, --channel, or --to")
        if shortcut in {"main", "stable"}:
            args.channel = shortcut
        else:
            args.to = shortcut
    home = lexical_absolute(manager_home(args.home))
    repo = repo_path(home)
    if _embedded_source(repo) is not None:
        raise SystemExit(
            "updates ship with ATM releases; this installation is embedded: "
            "upgrade ATM, then run `atm harness sync`"
        )
    with ManagerLock(home):
        manager, desired = _state_context(home, persist=not args.check)
        if not _worktree_clean(repo):
            raise SystemExit("managed checkout has uncommitted changes; refusing update")
        recorded_repository = manager["repository"]
        actual_repository = _repository(repo)
        if actual_repository != recorded_repository:
            raise SystemExit(
                "managed checkout remote differs from manager state; "
                f"expected {recorded_repository!r}, found {actual_repository!r}"
            )
        channel = args.channel or desired["updatePolicy"]["channel"]
        fetch_refs = ["+refs/heads/main:refs/remotes/origin/main"] if channel == "main" else []
        _git(repo, "fetch", "--prune", "--prune-tags", "--tags", "origin", *fetch_refs, capture=False)
        requested_ref, target = _target_revision(
            repo,
            channel=channel,
            requested=args.to,
        )
        old = _revision(repo)
        release, bundle = _validate_update_target(repo, target)
        print("Update plan:")
        print(f"  channel:  {manager['channel']} -> {channel}")
        print(f"  release:  {manager['releaseVersion']} -> {release}")
        print(f"  revision: {old} -> {target}")
        print(f"  bundle:   {manager['bundleIdentity']} -> {bundle}")
        if old == target:
            print("manager checkout is already at the selected update target")
            if args.check:
                return 0
            write_manager(
                home,
                repository=recorded_repository,
                revision=old,
                release_version=release,
                bundle_identity=bundle,
                channel=channel,
                requested_ref=requested_ref,
            )
            write_desired(home, desired_harnesses(desired), channel=channel)
            from install_engine import write_launchers

            write_launchers(home=home, repo=REPO_ROOT, dry_run=False)
            ensure_user_path(home)
            refresh_args = argparse.Namespace(**{**vars(args), "yes": True, "dry_run": False, "repair": False})
            for harness in desired_harnesses(desired):
                _refresh_one(refresh_args, home=home, harness=harness, check_after=True)
                _write_harness_state(home, harness)
            return 0

        if not args.allow_downgrade:
            ancestor = _git(
                repo,
                "merge-base",
                "--is-ancestor",
                old,
                target,
                check=False,
            )
            if ancestor.returncode != 0:
                raise SystemExit(
                    "update target is not a fast-forward descendant of the current revision; "
                    "use --allow-downgrade only after reviewing the requested transition"
                )
        before_source, target_source = _instruction_transition(repo, old, target)
        target_harnesses = _harness_names_at_revision(repo, target, desired_harnesses(desired))
        if args.check:
            return 0
        # Refuse unsafe receipt evidence before creating a rollback obligation.
        for harness in target_harnesses:
            validate_harness_receipts(home, harness)

        before = dict(manager)
        before["instructionsSource"] = before_source
        from sync_harness_instructions import materialized_instruction_digest

        before["instructionsMaterializedSha256"] = materialized_instruction_digest(
            repo, old, str(before_source["path"])
        )
        before["desiredHarnesses"] = desired["harnesses"]
        target_payload = {
            "repository": recorded_repository,
            "revision": target,
            "releaseVersion": release,
            "bundleIdentity": bundle,
            "channel": channel,
            "requestedRef": requested_ref,
            "instructionsSource": target_source,
            "instructionsMaterializedSha256": materialized_instruction_digest(
                repo, target, str(target_source["path"])
            ),
            "desiredHarnesses": list(target_harnesses),
        }
        operation = begin_operation(
            home,
            command="update",
            before=before,
            target=target_payload,
        )
        try:
            # Older target managers compare persisted IDs literally, even when
            # their CLI supports aliases. Journal before translating for them.
            if list(target_harnesses) != desired["harnesses"]:
                write_desired(home, target_harnesses, canonicalize=False)
            translate_harness_receipts(home, target_harnesses)
            _git(repo, "checkout", "--detach", target, capture=False)
            update_operation(home, phase="checkout-switched")
            _bootstrap_tooling(home)
            update_operation(home, phase="tooling-ready")
            result = _invoke_internal(
                repo,
                home,
                "_resume-update",
                "--operation-id",
                operation["operationId"],
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"new manager revision failed with exit code {result.returncode}"
                )
            return 0
        except BaseException as update_error:
            print(f"update failed; rolling back to {old}: {update_error}", file=sys.stderr)
            try:
                _git(repo, "checkout", "--detach", old, capture=False)
                _bootstrap_tooling(home)
                rollback = _invoke_internal(
                    repo,
                    home,
                    "_resume-rollback",
                    "--operation-id",
                    operation["operationId"],
                    "--detail",
                    str(update_error),
                )
                if rollback.returncode != 0:
                    raise RuntimeError(
                        f"rollback manager revision failed with exit code {rollback.returncode}"
                    )
            except BaseException as rollback_error:
                update_operation(
                    home,
                    phase="degraded",
                    updateError=str(update_error),
                    rollbackError=str(rollback_error),
                )
                write_manager(
                    home,
                    repository=manager["repository"],
                    revision=manager["revision"],
                    release_version=manager["releaseVersion"],
                    bundle_identity=manager["bundleIdentity"],
                    channel=manager["channel"],
                    requested_ref=manager.get("requestedRef", "main"),
                    status="degraded",
                )
                raise SystemExit(
                    f"update failed and rollback failed: {rollback_error}; run `atm harness -- recover`"
                ) from update_error
            raise SystemExit(f"update failed and was rolled back: {update_error}") from update_error


def command_resume_update(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    operation = load_current_operation(home)
    if operation is None or operation.get("operationId") != args.operation_id:
        raise SystemExit("update operation journal does not match the resume request")
    if operation.get("command") != "update":
        raise SystemExit("current operation is not an update")
    operation = _journal_instruction_transition(home, operation)
    target = operation["target"]
    if _revision(REPO_ROOT) != target["revision"]:
        raise SystemExit("managed checkout does not match the journaled update target")
    release, bundle = _distribution(REPO_ROOT)
    if release != target["releaseVersion"] or bundle != target["bundleIdentity"]:
        raise SystemExit("live update target identity changed after validation")

    try:
        return _complete_resumed_update(args, home, target, release, bundle)
    except BaseException as update_error:
        # An older caller will switch back and run its own rollback executable.
        # Restore copy bytes while this version still understands materialized
        # provenance; the old manager can then recognize its current source.
        try:
            _restore_update_instruction_copies(home, operation)
        except BaseException as restoration_error:
            raise RuntimeError(
                f"update failed: {update_error}; instruction copy restoration failed: "
                f"{restoration_error}"
            ) from update_error
        raise


def _restore_update_instruction_copies(home: Path, operation: dict) -> None:
    from harness_registry import load_harness_registry, resolve_harness_plan
    from sync_harness_instructions import (
        apply_instruction_sync,
        materialized_instruction_bytes,
        prepare_instruction_sync,
    )

    operation = _journal_instruction_transition(home, operation)
    before = operation["before"]
    target = operation["target"]
    if not before.get("desiredHarnesses"):
        return
    if target["instructionsMaterializedSha256"] in {
        before["instructionsMaterializedSha256"], target["instructionsSource"]["sha256"]
    }:
        # Old rollback already recognizes unchanged bytes or Git-blob copies.
        return
    source = before["instructionsSource"]
    migration = source.get("migration")
    # Pre-bridge registries cannot be loaded by this manager; never guess paths.
    if not isinstance(migration, dict):
        # A failed preflight may never have changed any instructions. Do not
        # introduce a new rollback block for legacy registries in that case.
        for harness in before["desiredHarnesses"]:
            plan = _resolve_plan(harness)
            destination = plan.instructions_target
            if (plan.instructions_materialization == "copy"
                    and not destination.is_symlink() and destination.is_file()
                    and hashlib.sha256(destination.read_bytes()).hexdigest()
                    == target["instructionsMaterializedSha256"]):
                raise SystemExit("cannot restore changed instruction copies without the old registry migration contract")
        return
    with tempfile.TemporaryDirectory(prefix="atm-harness-instruction-rollback-") as temporary:
        root = Path(temporary)
        paths = (INSTRUCTION_REGISTRY_PATH, source["path"], migration["peer"])
        for relative_path in paths:
            destination = root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(materialized_instruction_bytes(
                REPO_ROOT, before["revision"], relative_path
            ))
        if hashlib.sha256((root / source["path"]).read_bytes()).hexdigest() != before["instructionsMaterializedSha256"]:
            raise SystemExit("rollback instruction source changed after journal validation")
        registry = load_harness_registry(root / INSTRUCTION_REGISTRY_PATH, repo_root=root)
        prepared = {}
        for harness in before.get("desiredHarnesses", ()):
            old_plan = resolve_harness_plan(registry, harness, repo_root=root)
            new_plan = _resolve_plan(harness)
            if old_plan.instructions_target != new_plan.instructions_target:
                raise SystemExit("instruction target changed across update; refusing automatic copy rollback")
            if old_plan.instructions_materialization != "copy":
                continue
            if new_plan.instructions_materialization != "copy":
                raise SystemExit("instruction materialization changed across update; refusing automatic copy rollback")
            destination = old_plan.instructions_target
            if not os.path.lexists(destination):
                continue
            if destination.is_symlink() or not destination.is_file():
                raise SystemExit("refusing non-file instruction target during copy rollback")
            # Only these exact source bytes confer ownership. Do not use peer
            # provenance or a freshly captured user file as a rollback baseline.
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest not in {before["instructionsMaterializedSha256"], target["instructionsMaterializedSha256"]}:
                raise SystemExit("refusing changed or unmanaged instruction target during copy rollback")
            item = prepare_instruction_sync(
                old_plan, dry_run=False, assume_yes=True,
                operation_managed_digests=(target["instructionsMaterializedSha256"],),
                input_fn=lambda _prompt: "no",
            )
            if item.snapshot.kind != "file" or item.snapshot.digest != digest:
                raise SystemExit("instruction target changed during copy rollback preflight")
            key = os.path.normcase(str(lexical_absolute(destination)))
            previous = prepared.get(key)
            if previous is not None:
                if (
                    lexical_absolute(previous.plan.instructions_source)
                    != lexical_absolute(item.plan.instructions_source)
                    or previous.source_digest != item.source_digest
                    or previous.snapshot != item.snapshot
                ):
                    raise SystemExit("conflicting instruction rollback plans for shared target")
                continue
            prepared[key] = item
        for item in prepared.values():
            apply_instruction_sync(item, dry_run=False)


def _complete_resumed_update(
    args: argparse.Namespace, home: Path, target: dict, release: str, bundle: str,
) -> int:
    _manager, desired = _state_context(
        home,
        persist=True,
        allow_manager_drift=True,
        allow_active_operation=True,
    )
    write_manager(
        home,
        repository=target["repository"],
        revision=target["revision"],
        release_version=release,
        bundle_identity=bundle,
        channel=target["channel"],
        requested_ref=target["requestedRef"],
    )
    write_desired(
        home,
        desired["harnesses"],
        channel=target["channel"],
        canonicalize=False,
    )
    update_operation(home, phase="refreshing-harnesses")
    refresh_args = argparse.Namespace(
        home=str(home),
        targets=[],
        harness=None,
        all=True,
        repair=False,
        codex_home=None,
        codex=None,
        yes=True,
        dry_run=False,
        no_check=False,
        migrate_marketplace=False,
        migrate_from_repo=None,
        operation_id=args.operation_id,
    )
    targets = desired_harnesses(desired)
    for harness in targets:
        _refresh_one(refresh_args, home=home, harness=harness, check_after=True)
    from install_engine import write_launchers

    # Profile validation may fail; keep the old shim intact until it succeeds.
    # This also protects upgrades whose old rollback implementation predates
    # launcher restoration.
    ensure_user_path(home)
    write_launchers(home=home, repo=REPO_ROOT, dry_run=False)
    finish_operation(home, outcome="success")
    _finish_harness_name_migration(home, desired)
    print(f"updated atm-harness to {release} ({target['revision'][:12]})")
    return 0


def command_resume_rollback(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    operation = load_current_operation(home)
    if operation is None or operation.get("operationId") != args.operation_id:
        raise SystemExit("update operation journal does not match the rollback request")
    operation = _journal_instruction_transition(home, operation)
    before = operation["before"]
    if _revision(REPO_ROOT) != before["revision"]:
        raise SystemExit("managed checkout does not match the journaled rollback revision")
    release, bundle = _distribution(REPO_ROOT)
    write_manager(
        home,
        repository=before["repository"],
        revision=before["revision"],
        release_version=release,
        bundle_identity=bundle,
        channel=before["channel"],
        requested_ref=before.get("requestedRef", "main"),
    )
    _manager, desired = _state_context(
        home,
        persist=True,
        allow_active_operation=True,
    )
    refresh_args = argparse.Namespace(
        home=str(home),
        targets=[],
        harness=None,
        all=True,
        repair=False,
        codex_home=None,
        codex=None,
        yes=True,
        dry_run=False,
        no_check=False,
        migrate_marketplace=False,
        migrate_from_repo=None,
        operation_id=args.operation_id,
    )
    for harness in desired_harnesses(desired):
        _refresh_one(refresh_args, home=home, harness=harness, check_after=True)
        _write_harness_state(home, harness)
    from install_engine import write_launchers

    # A rollback restores the executable entry points as well as the checkout.
    # Do not retry PATH integration: that may be the update's original failure.
    write_launchers(home=home, repo=REPO_ROOT, dry_run=False)
    write_desired(home, desired_harnesses(desired), channel=before["channel"])
    finish_operation(home, outcome="rolled-back", detail=args.detail)
    print(f"restored atm-harness revision {before['revision'][:12]}")
    return 0


def command_recover(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    if _embedded_source(repo_path(home)) is not None:
        raise SystemExit(
            "update recovery does not apply to embedded installations; "
            "updates ship with ATM releases (run `atm harness sync`)"
        )
    with ManagerLock(home):
        operation = load_current_operation(home)
        if operation is None:
            print("no interrupted manager operation")
            return 0
        if operation.get("command") != "update":
            raise SystemExit(
                f"unsupported interrupted operation {operation.get('command')!r}; "
                "manual inspection is required"
            )
        before = operation.get("before")
        if not isinstance(before, dict) or not isinstance(before.get("revision"), str):
            raise SystemExit("update operation journal has no rollback revision")
        repo = repo_path(home)
        target = operation.get("target", {})
        if _revision(repo) == target.get("revision"):
            _restore_update_instruction_copies(home, operation)
        _git(repo, "checkout", "--detach", before["revision"], capture=False)
        _bootstrap_tooling(home)
        result = _invoke_internal(
            repo,
            home,
            "_resume-rollback",
            "--operation-id",
            str(operation["operationId"]),
            "--detail",
            "explicit recovery",
        )
        if result.returncode != 0:
            raise SystemExit(
                f"recovery rollback failed with exit code {result.returncode}"
            )
    return 0


def command_manager_repair(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    dry_run = bool(getattr(args, "dry_run", False))
    if getattr(args, "reclone", False) and _embedded_source(repo_path(home)) is not None:
        raise SystemExit(
            "checkout re-clone does not apply to embedded installations; "
            "run `atm harness sync` to restore the embedded distribution"
        )
    if not dry_run and (getattr(args, "rebuild", False) or getattr(args, "reclone", False)):
        if os.environ.get("ATM_REPAIR_BOOTSTRAPPED") != str(home):
            raise SystemExit(
                "runtime repair runs through the embedded bootstrap: "
                "run `atm harness bootstrap --rebuild`, then retry the repair"
            )
    if load_current_operation(home) is not None:
        if getattr(args, "machine_safe", False):
            raise SystemExit("machine repair cannot recover an active operation; inspect atm harness -- status and use standalone atm harness -- recover")
        if dry_run:
            print("would roll back the interrupted update before repairing harnesses")
            return 0
        command_recover(args)
    with nullcontext() if dry_run else ManagerLock(home):
        _machine_preflight(args, home, "repair")
        manager, desired = _state_context(home, persist=not dry_run, allow_degraded=True)
        installed = list(desired_harnesses(desired))
        targets = _target_set(args, desired=tuple(installed), mode="refresh")
        receipt_path = state_path(home) / "install.json"
        receipt = None
        if receipt_path.exists() or receipt_path.is_symlink():
            from manager_state import install_receipt

            receipt = install_receipt(home)
        if not targets and receipt and receipt.get("status") == "installing":
            targets = _validate_targets([receipt["harness"]])
        former_repo = getattr(args, "migrate_from_repo", None)
        if not former_repo and receipt and not getattr(args, "machine_safe", False):
            paths = receipt.get("paths")
            recorded = paths.get("repo") if isinstance(paths, dict) else None
            if isinstance(recorded, str) and Path(recorded).is_absolute() and Path(recorded) != REPO_ROOT:
                former_repo = recorded
        if not dry_run:
            if not getattr(args, "machine_safe", False):
                _bootstrap_tooling(home)
            from install_engine import write_launchers

            write_launchers(home=home, repo=REPO_ROOT, dry_run=False)
        if not getattr(args, "no_path", False) and not getattr(args, "machine_safe", False):
            ensure_user_path(home, dry_run=dry_run)
        for harness in targets:
            refresh_args = argparse.Namespace(
                home=str(home), targets=[harness], harness=None, all=False,
                repair=True, yes=True, dry_run=dry_run, no_check=False,
                codex_home=getattr(args, "codex_home", None) if harness == "codex" else None,
                codex=getattr(args, "codex", None) if harness == "codex" else None,
                migrate_marketplace=bool(getattr(args, "migrate_marketplace", False)) if harness == "codex" else False,
                migrate_from_repo=former_repo if harness == "codex" else None,
                operation_id=None,
                machine_safe=bool(getattr(args, "machine_safe", False)),
            )
            _refresh_one(refresh_args, home=home, harness=harness, check_after=True)
            if not dry_run:
                _write_harness_state(home, harness, codex_home=refresh_args.codex_home)
                if harness not in installed:
                    installed.append(harness)
                write_desired(home, installed)
        if not dry_run:
            write_manager(
                home, repository=manager["repository"], revision=manager["revision"],
                release_version=manager["releaseVersion"], bundle_identity=manager["bundleIdentity"],
                channel=manager["channel"], requested_ref=manager.get("requestedRef", "main"),
                status="ready",
            )
            if receipt is not None and receipt.get("status") == "installing":
                from install_engine import launcher_paths, write_install_state

                write_install_state(
                    home=home, repository=manager["repository"], ref=receipt.get("ref", "main"),
                    repo=REPO_ROOT, harness=receipt["harness"], launchers=launcher_paths(home),
                    status="ready", revision=receipt["revision"],
                )
        print("repair plan complete" if dry_run else "manager and selected harnesses repaired and checked")
    return 0


def _cleanup_helper_text() -> str:
    return textwrap.dedent(
        """\
        import os
        import shutil
        import sys
        import time
        from pathlib import Path

        pid = int(sys.argv[1])
        home = Path(sys.argv[2])
        for _ in range(600):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        for _ in range(600):
            if not home.exists():
                break
            try:
                shutil.rmtree(home)
            except OSError:
                time.sleep(0.1)
            else:
                break
        shutil.rmtree(Path(__file__).parent, ignore_errors=True)
        """
    )


def _schedule_self_delete(home: Path) -> None:
    helper_dir = Path(tempfile.mkdtemp(prefix="atm-harness-uninstall-"))
    helper = helper_dir / "cleanup.py"
    helper.write_text(_cleanup_helper_text(), encoding="utf-8")
    kwargs: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [str(_base_python()), str(helper), str(os.getpid()), str(home)],
        **kwargs,
    )


def command_manager_uninstall(args: argparse.Namespace) -> int:
    home = lexical_absolute(manager_home(args.home))
    with ManagerLock(home):
        _manager, desired = _state_context(home, persist=True)
        installed = list(desired_harnesses(desired))
        if installed and not args.with_harnesses:
            raise SystemExit(
                "manager uninstall requires an empty desired harness set; "
                "run `atm harness -- remove --all` first or pass --with-harnesses"
            )
        if installed:
            remove_args = argparse.Namespace(
                home=str(home),
                targets=[],
                harness=None,
                all=True,
                codex_home=None,
                codex=None,
                yes=True,
                dry_run=False,
            )
            for harness in installed:
                validate_harness_receipts(home, harness)
            for harness in list(installed):
                _remove_one(remove_args, home=home, harness=harness)
                installed.remove(harness)
                write_desired(home, installed)
                remove_harness_receipt(home, harness)
        if not args.yes:
            try:
                answer = input(f"Uninstall atm-harness manager at {home} [y/N] ")
            except (EOFError, OSError):
                answer = ""
            if answer.strip() not in {"y", "Y", "yes", "YES", "Yes"}:
                raise SystemExit("manager uninstall was not confirmed")
        allowed = {"repo", "venv", "bin", "state", "bootstrap"}
        unknown = sorted(
            path.name
            for path in home.iterdir()
            if path.name not in allowed
        )
        if unknown and not args.purge_unknown:
            raise SystemExit(
                "manager home contains unknown entries; refusing uninstall: "
                + ", ".join(unknown)
                + "; inspect them or pass --purge-unknown"
            )
        ensure_user_path(home, remove=True)
        _schedule_self_delete(home)
        print(f"manager uninstall scheduled after current process exits: {home}")
    return 0


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["refresh"]
    prefix: list[str] = []
    rest = list(argv)
    while rest:
        token = rest[0]
        if token == "--home" and len(rest) >= 2:
            prefix.extend(rest[:2])
            rest = rest[2:]
            continue
        if token.startswith("--home="):
            prefix.append(token)
            rest = rest[1:]
            continue
        break
    if rest and rest[0] == "-Help":
        rest[0] = "--help"
    if rest and rest[0] in {"-h", "--help"}:
        return [*prefix, *rest]
    if not rest or rest[0] not in KNOWN_COMMANDS:
        rest.insert(0, "refresh")
    return [*prefix, *rest]


def _selected_command(argv: Sequence[str]) -> str | None:
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--home" and index + 1 < len(argv):
            index += 2
            continue
        if token.startswith("--home="):
            index += 1
            continue
        return token
    return None


def _add_harness_common(
    parser: argparse.ArgumentParser,
    *,
    registry: HarnessRegistry | None,
    mode: str,
) -> None:
    def harness_name(value: str) -> str:
        if registry is None:
            return value
        try:
            return registry.resolve_id(value)
        except HarnessRegistryError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc

    default = (
        f"Default: {registry.default_harness if registry else 'registry unavailable'}." if mode == "install"
        else "Required unless --all is used." if mode == "remove"
        else "Default: all installed harnesses."
    )
    parser.add_argument(
        "targets", nargs="*", metavar="HARNESS", type=harness_name,
        help=f"One or more harness names or aliases. {default}",
    )
    parser.add_argument(
        "--all", action="store_true",
        help=(
            "Install every available harness once (aliases do not add targets)."
            if mode == "install" else "Select all installed harnesses."
        ),
    )
    parser.add_argument(
        "--harness", metavar="HARNESS", type=harness_name,
        help="Select one harness by name or alias; equivalent to a positional HARNESS.",
    )
    codex = parser.add_argument_group("Codex options")
    codex.add_argument("--codex-home", metavar="PATH", help="Override the Codex configuration directory.")
    codex.add_argument("--codex", metavar="PATH", help="Use this Codex CLI executable.")
    mutating = mode in {"install", "refresh", "remove", "repair"}
    parser.add_argument(
        "--yes", action="store_true",
        help=(
            "Confirm managed-resource removal." if mode == "remove" else
            "Confirm creation and managed cleanup; replacing existing instructions still requires a live prompt."
        ) if mutating else argparse.SUPPRESS,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without applying them." if mutating else argparse.SUPPRESS,
    )


def _add_install_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-check", action="store_true",
        help="Skip the final installation check (checks run by default).",
    )
    migration = parser.add_argument_group("One-time Codex migration options")
    migration.add_argument(
        "--migrate-marketplace", action="store_true",
        help="Migrate the retired marketplace after confirming its exact cleanup plan.",
    )
    migration.add_argument(
        "--migrate-from-repo", metavar="PATH",
        help="Recognize only this former checkout's managed instructions and broken marketplace source.",
    )


def _add_repair_options(parser: argparse.ArgumentParser, registry: HarnessRegistry | None) -> None:
    _add_harness_common(parser, registry=registry, mode="repair")
    parser.add_argument("--machine-safe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the tooling venv through the stable launcher.")
    parser.add_argument("--reclone", action="store_true", help="Restore the recorded checkout from its remote, keeping a backup.")
    parser.add_argument("--no-path", action="store_true", help="Do not change current-user shell/registry PATH settings.")
    parser.add_argument("--migrate-marketplace", action="store_true", help="Codex only: migrate the retired marketplace after confirming its cleanup plan.")
    parser.add_argument("--migrate-from-repo", metavar="PATH", help="Recognize this former checkout's managed instructions and broken marketplace source.")
    parser.set_defaults(func=command_manager_repair)


def build_parser() -> argparse.ArgumentParser:
    registry_error = None
    try:
        registry = load_harness_metadata(repo_root=REPO_ROOT)
    except HarnessRegistryError as exc:
        registry = None
        registry_error = str(exc)
    available = textwrap.fill(registry.selection_help(), width=78) if registry else (
        "Harness choices unavailable: " + str(registry_error)
    )
    parser = argparse.ArgumentParser(
        prog="atm harness --",
        description=(
            "Install and manage atm-harness skills and global instructions for your "
            "coding clients. Install each client application separately."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Common tasks:\n"
            "  atm harness -- install copilot --dry-run  Preview adding Copilot skills and instructions\n"
            "  atm harness -- install copilot           Install them (copilot-cli works too)\n"
            "  atm harness -- status                    See installed harnesses and the update channel\n"
            "  atm harness -- refresh                   Reapply the installed version; no remote fetch\n"
            "  atm harness -- update --check            Fetch and preview an available update\n"
            "  atm harness -- update                    Apply the update and refresh installed harnesses\n"
            "  atm harness -- check                     Validate installed harnesses\n"
            "  atm harness -- repair --dry-run          Preview repairing the manager and harnesses\n"
            "  atm harness -- remove copilot --dry-run  Preview removing managed Copilot resources\n\n"
            + available + "\n\n"
            "Running atm harness -- without a command is equivalent to atm harness -- refresh.\n"
            "First-time setup: ./install.sh or .\\install.ps1; then reopen your terminal.\n"
            "Run atm harness -- COMMAND --help for defaults, options and examples."
        ),
    )
    parser.set_defaults(registry_error=registry_error)
    parser.add_argument("--home", metavar="PATH", help="Manager home; place before COMMAND (default: ATM_HOME or ~/.atm).")
    sub = parser.add_subparsers(dest="command", required=True, title="commands", metavar="COMMAND")

    def command(name: str, summary: str, description: str, examples: str, *, harnesses: bool = False):
        epilog = "Examples:\n" + examples
        if harnesses:
            epilog += "\n\n" + available
        return sub.add_parser(
            name, help=summary, description=description,
            formatter_class=argparse.RawDescriptionHelpFormatter, epilog=epilog,
        )

    command("machine", "Versioned noninteractive client interface.",
            "JSON protocol for clients; see docs/machine-interface.md.",
            "  atm harness -- machine --protocol 1 capabilities")

    install = command(
        "install", "Add skills and instructions to coding clients.",
        f"Install one or more harness distributions and record them for future updates. "
        f"Default: {registry.default_harness if registry else 'registry unavailable'}. Existing targets are reapplied; this does not install the client app.",
        "  atm harness -- install copilot\n  atm harness -- install claude gemini --dry-run\n  atm harness -- install --all",
        harnesses=True,
    )
    _add_harness_common(install, registry=registry, mode="install")
    _add_install_options(install)
    install.add_argument("--machine-safe", action="store_true", help=argparse.SUPPRESS)
    install.set_defaults(func=command_install)

    refresh = command(
        "refresh", "Reapply the installed version without fetching updates.",
        "Reapply skills and instructions from the current managed checkout. No remote fetch. "
        "Default: all installed harnesses. Use install to add a harness to future updates.",
        "  atm harness -- refresh\n  atm harness -- refresh copilot --dry-run\n  atm harness -- refresh codex --repair",
        harnesses=True,
    )
    _add_harness_common(refresh, registry=registry, mode="refresh")
    refresh.add_argument(
        "--repair", action="store_true",
        help="Explicitly rebuild Codex plugin caches that have drifted at the current version.",
    )
    _add_install_options(refresh)
    refresh.add_argument("--machine-safe", action="store_true", help=argparse.SUPPRESS)
    refresh.set_defaults(func=command_refresh)

    update = command(
        "update", "Fetch a new manager version and refresh installed harnesses.",
        "Fetch remote source and update the manager plus all installed harnesses. "
        "Uses the saved update channel (main for new main installs, stable for release-tag installs). "
        "--check fetches and validates "
        "the target without switching the installed version or saving a channel change.",
        "  atm harness -- update --check\n  atm harness -- update\n  atm harness -- update main --check\n  atm harness -- update main",
    )
    update.add_argument("target", nargs="?", metavar="TARGET", help="main or stable selects and saves a channel; another Git ref selects only this update's target. Defaults to the saved channel.")
    update.add_argument("--check", action="store_true", help="Fetch and preview the update without applying it.")
    update.add_argument(
        "--channel", choices=("stable", "main"),
        help="stable: latest vX.Y.Z release; main: origin/main. Saved after a successful update, not with --check.",
    )
    update.add_argument("--to", metavar="REF", help="Use this Git ref/tag/commit for this update only.")
    update.add_argument("--allow-downgrade", action="store_true", help="Allow a target that is not a fast-forward descendant, including older releases.")
    update.set_defaults(func=command_update)

    status = command(
        "status", "Show installed harnesses, update channel and pending operations.",
        "Read manager state and the recorded harness set without changing them.",
        "  atm harness -- status\n  atm harness -- status --json",
    )
    status.add_argument("--json", action="store_true", help="Print structured JSON output.")
    status.set_defaults(func=command_status)

    for name, summary, description, strict in (
        ("check", "Check installed skills and instructions without changing them.",
         "Validate installed harnesses without changing them. Warnings are reported; errors fail the command.", False),
        ("doctor", "Run checks with warnings treated as failures.",
         "Run the same read-only checks as check, but also fail on warnings. This command does not repair files.", True),
    ):
        check = command(name, summary, description + " Default: all installed harnesses.",
                        f"  atm harness -- {name}\n  atm harness -- {name} copilot", harnesses=True)
        _add_harness_common(check, registry=registry, mode=name)
        check.set_defaults(func=lambda args, strict=strict: command_check(args, strict=strict))

    remove = command(
        "remove", "Remove a harness's managed skills and instructions.",
        "Remove only resources whose manager ownership is proven, then stop updating that harness. "
        "Specify HARNESS or --all; there is no default target. Unrelated user files are preserved.",
        "  atm harness -- remove copilot --dry-run\n  atm harness -- remove copilot\n  atm harness -- remove --all",
        harnesses=True,
    )
    _add_harness_common(remove, registry=registry, mode="remove")
    remove.set_defaults(func=command_remove)

    repair = command(
        "repair", "Repair the manager, user PATH and selected harnesses.",
        "Repair the recorded installation: reuse a healthy checkout, recover an interrupted "
        "update, restore runtime, launchers and user PATH, then repair and check selected "
        "harnesses. Default: all installed harnesses. Does not select a newer release.",
        "  atm harness -- repair --dry-run\n  atm harness -- repair copilot\n  atm harness -- repair --rebuild\n  atm harness -- repair --reclone",
        harnesses=True,
    )
    _add_repair_options(repair, registry)

    manager = command(
        "manager", "Repair or uninstall atm-harness itself.",
        "Manage the atm-harness installation. Use repair for the manager and harnesses, "
        "or recover to roll back only an interrupted update.",
        "  atm harness -- repair\n  atm harness -- manager uninstall --help",
    )
    manager_sub = manager.add_subparsers(dest="manager_command", required=True, metavar="COMMAND")
    repair = manager_sub.add_parser(
        "repair", help=f"Compatibility spelling of atm harness -- repair.",
        description=f"Equivalent to atm harness -- repair: repair the recorded manager, user PATH and selected harnesses. Default: all installed harnesses; no newer release is selected.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  atm harness -- manager repair copilot --dry-run\n  atm harness -- repair\n\n" + available,
    )
    _add_repair_options(repair, registry)
    uninstall = manager_sub.add_parser(
        "uninstall", help="Delete the manager installation.",
        description=f"Delete the manager home after confirmation. First remove harnesses with atm harness -- remove --all, or pass --with-harnesses. Unknown entries block deletion unless --purge-unknown is explicit.",
    )
    uninstall.add_argument("--with-harnesses", action="store_true", help="Remove all installed harness distributions before deleting the manager.")
    uninstall.add_argument("--purge-unknown", action="store_true", help="Also delete unrecognized files inside the manager home.")
    uninstall.add_argument("--yes", action="store_true", help="Confirm manager removal without prompting.")
    uninstall.set_defaults(func=command_manager_uninstall)

    recover = command(
        "recover", "Roll back an interrupted manager update.",
        "Use the active operation journal to roll back an interrupted update. Run status first; "
        "use repair for broader manager and harness repair.",
        "  atm harness -- status\n  atm harness -- recover",
    )
    recover.set_defaults(func=command_recover)

    version = command(
        "version", "Show manager version and package identity.",
        "Show the release version, source revision and distribution identity.",
        "  atm harness -- version\n  atm harness -- version --json",
    )
    version.add_argument("--json", action="store_true", help="Print structured JSON output.")
    version.set_defaults(func=command_version)
    return parser


def build_internal_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atm harness --",
        description="Continue an internal manager update transaction.",
    )
    parser.add_argument("--home")
    sub = parser.add_subparsers(dest="command", required=True)

    resume = sub.add_parser("_resume-update")
    resume.add_argument("--operation-id", required=True)
    resume.set_defaults(func=command_resume_update)

    rollback = sub.add_parser("_resume-rollback")
    rollback.add_argument("--operation-id", required=True)
    rollback.add_argument("--detail")
    rollback.set_defaults(func=command_resume_rollback)

    return parser


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    """One side-effect-free parser shared by the stable shim and direct CLI."""
    normalized = _normalize_argv(argv)
    command = _selected_command(normalized)
    if command == "machine":
        from machine import command_machine

        index = 0
        while normalized[index] != "machine":
            index += 2 if normalized[index] == "--home" else 1
        home_args = argparse.ArgumentParser(add_help=False)
        home_args.add_argument("--home")
        args = home_args.parse_args(normalized[:index])
        args.command = "machine"
        args.machine_arguments = normalized[index + 1:]
        args.func = command_machine
        return args
    parser = build_internal_parser() if command in INTERNAL_COMMANDS else build_parser()
    args = parser.parse_args(normalized)
    if getattr(args, "registry_error", None) and args.command not in {"status", "version"}:
        repair = args.command == "repair" or (args.command == "manager" and args.manager_command == "repair")
        if not repair or any(getattr(args, key, None) for key in (
                "targets", "harness", "all", "codex", "codex_home", "migrate_marketplace", "migrate_from_repo")):
            parser.error(args.registry_error + "; restore with plain atm harness -- repair before selecting harnesses")
    if getattr(args, "all", False) and (getattr(args, "targets", []) or getattr(args, "harness", None)):
        parser.error("do not combine explicit harness targets with --all")
    if args.command == "remove" and not (args.all or args.targets or args.harness):
        parser.error("remove requires HARNESS or --all")
    if args.command == "update" and getattr(args, "target", None) and (args.channel or args.to):
        parser.error("use one update target: positional TARGET, --channel, or --to")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(list(sys.argv[1:] if argv is None else argv))
    return int(args.func(args) or 0)


def cli() -> int:
    try:
        return main()
    except subprocess.CalledProcessError as exc:
        return exc.returncode if exc.returncode > 0 else 1
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        if exc.code:
            print(f"error: {exc.code}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
