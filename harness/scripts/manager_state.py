#!/usr/bin/env python3
"""Persistent manager lifecycle state and cross-process mutation locking."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from harness_registry import HarnessRegistry, load_harness_registry
from manager_paths import PRODUCT_NAME, state_path

STATE_SCHEMA_VERSION = "2026-08-24"
MANAGER_FILE = "manager.json"
DESIRED_FILE = "desired.json"
HARNESS_STATE_DIR = "harnesses"
OPERATIONS_DIR = "operations"
CURRENT_OPERATION_FILE = "current.json"
HISTORY_DIR = "history"
LOCK_FILE = "manager.lock"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_object(path: Path, *, label: str, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise SystemExit(f"{label} is missing: {path}")
        return None
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{label} must be an ordinary file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must contain a JSON object: {path}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise SystemExit(f"state parent must be an ordinary directory: {path.parent}")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def install_receipt(home: Path) -> dict[str, Any]:
    path = state_path(home) / "install.json"
    payload = _load_object(path, label="initial installation receipt")
    assert payload is not None
    if payload.get("product") != PRODUCT_NAME:
        raise SystemExit(f"initial installation receipt belongs to another product: {path}")
    if payload.get("status") not in {"installing", "ready"}:
        raise SystemExit(f"initial installation receipt has unsupported status: {path}")
    return payload


def state_root(home: Path) -> Path:
    return state_path(home)


def manager_file(home: Path) -> Path:
    return state_root(home) / MANAGER_FILE


def desired_file(home: Path) -> Path:
    return state_root(home) / DESIRED_FILE


def harness_file(home: Path, harness: str) -> Path:
    return state_root(home) / HARNESS_STATE_DIR / f"{harness}.json"


def current_operation_file(home: Path) -> Path:
    return state_root(home) / OPERATIONS_DIR / CURRENT_OPERATION_FILE


def operation_history_dir(home: Path) -> Path:
    return state_root(home) / OPERATIONS_DIR / HISTORY_DIR


def _validate_manager_payload(payload: dict[str, Any], *, path: Path) -> None:
    if payload.get("schemaVersion") != STATE_SCHEMA_VERSION:
        raise SystemExit(f"manager state schema is unsupported: {path}")
    if payload.get("product") != PRODUCT_NAME:
        raise SystemExit(f"manager state belongs to another product: {path}")
    if payload.get("status") not in {"ready", "degraded"}:
        raise SystemExit(f"manager state status is unsupported: {path}")
    for field in ("repository", "revision", "releaseVersion", "bundleIdentity", "channel"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise SystemExit(f"manager state field {field!r} is invalid: {path}")


def _validate_desired_payload(payload: dict[str, Any], *, path: Path) -> None:
    if payload.get("schemaVersion") != STATE_SCHEMA_VERSION:
        raise SystemExit(f"desired state schema is unsupported: {path}")
    harnesses = payload.get("harnesses")
    if (
        not isinstance(harnesses, list)
        or not all(isinstance(item, str) and item for item in harnesses)
        or harnesses != sorted(set(harnesses))
    ):
        raise SystemExit(f"desired harness set is invalid: {path}")
    policy = payload.get("updatePolicy")
    if not isinstance(policy, dict) or policy.get("channel") not in {"stable", "main"}:
        raise SystemExit(f"desired update policy is invalid: {path}")


def derive_initial_state(
    home: Path,
    *,
    repository: str,
    revision: str,
    release_version: str,
    bundle_identity: str,
    persist: bool,
    canonicalize: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = install_receipt(home)
    recorded_repository = receipt.get("repository")
    if isinstance(recorded_repository, str) and recorded_repository:
        repository = recorded_repository
    initial_harness = receipt.get("harness")
    harnesses: list[str] = []
    if receipt.get("status") == "ready" and isinstance(initial_harness, str) and initial_harness:
        harnesses = [initial_harness]
    channel = "main" if receipt.get("ref") == "main" else "stable"
    manager = {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "status": "ready",
        "repository": repository,
        "channel": channel,
        "requestedRef": receipt.get("ref") if isinstance(receipt.get("ref"), str) else "main",
        "revision": revision,
        "releaseVersion": release_version,
        "bundleIdentity": bundle_identity,
        "updatedAt": _now(),
    }
    desired = {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "harnesses": list(canonical_harnesses(harnesses)) if canonicalize else sorted(set(harnesses)),
        "updatePolicy": {"channel": channel},
        "updatedAt": _now(),
    }
    if persist:
        atomic_write_json(manager_file(home), manager)
        atomic_write_json(desired_file(home), desired)
    return manager, desired


def load_or_initialize(
    home: Path,
    *,
    repository: str,
    revision: str,
    release_version: str,
    bundle_identity: str,
    persist: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manager_path = manager_file(home)
    desired_path = desired_file(home)
    manager = _load_object(manager_path, label="manager state", required=False)
    desired = _load_object(desired_path, label="desired harness state", required=False)
    if manager is None and desired is None:
        return derive_initial_state(
            home,
            repository=repository,
            revision=revision,
            release_version=release_version,
            bundle_identity=bundle_identity,
            persist=persist,
        )
    if manager is None or desired is None:
        raise SystemExit(
            "manager lifecycle state is incomplete; both manager.json and desired.json "
            "must exist or both must be absent"
        )
    _validate_manager_payload(manager, path=manager_path)
    _validate_desired_payload(desired, path=desired_path)
    return manager, desired


def load_state_snapshot(home: Path, *, registry: HarnessRegistry | None = None) -> dict[str, Any]:
    """Read recorded state only: never initialize, hash sources or inspect Git."""
    manager = _load_object(manager_file(home), label="manager state", required=False)
    desired = _load_object(desired_file(home), label="desired harness state", required=False)
    if (manager is None) != (desired is None):
        raise SystemExit("manager lifecycle state is incomplete; both manager.json and desired.json "
                         "must exist or both must be absent")
    initial = None
    if manager is not None:
        _validate_manager_payload(manager, path=manager_file(home))
        assert desired is not None
        _validate_desired_payload(desired, path=desired_file(home))
        names = desired["harnesses"]
        harnesses = list(canonical_harnesses(names, registry=registry)) if registry else list(names)
    else:
        initial_path = state_root(home) / "install.json"
        if initial_path.exists():
            initial = install_receipt(home)
        harnesses = []
    operation = load_current_operation(home)
    if operation is not None:
        if operation.get("schemaVersion") != STATE_SCHEMA_VERSION:
            raise SystemExit("current manager operation schema is unsupported")
        for field in ("operationId", "command", "phase"):
            if not isinstance(operation.get(field), str) or not operation[field]:
                raise SystemExit(f"current manager operation field {field!r} is invalid")
        if not isinstance(operation.get("before"), dict) or not isinstance(operation.get("target"), dict):
            raise SystemExit("current manager operation transition state is invalid")
    receipts = {}
    if registry is not None:
        for harness in harnesses:
            if harness not in registry.harnesses:
                continue  # Unknown recorded IDs remain visible; never resolve them as paths.
            entries = []
            for path in _harness_receipts(home, harness, registry=registry):
                receipt = _load_object(path, label="harness receipt")
                assert receipt is not None
                if receipt.get("status") != "ready":
                    raise SystemExit(f"harness receipt status is invalid: {path}")
                for field in ("managerRevision", "releaseVersion", "bundleIdentity", "root", "updatedAt"):
                    if not isinstance(receipt.get(field), str) or not receipt[field]:
                        raise SystemExit(f"harness receipt field {field!r} is invalid: {path}")
                entries.append(receipt)
            receipts[harness] = entries
    return {"manager": manager, "desiredHarnesses": harnesses,
            "operation": operation, "harnessReceipts": receipts,
            "stateKind": "recorded" if manager else "legacy-receipt-only" if initial else "unknown",
            "initialReceipt": initial}


def canonical_harnesses(harnesses: Iterable[str], *, registry: HarnessRegistry | None = None) -> tuple[str, ...]:
    """Normalize persisted aliases in memory; unknown IDs remain visible to status."""
    aliases = (registry or load_harness_registry()).aliases
    return tuple(sorted({aliases.get(name, name) for name in harnesses}))


def desired_harnesses(desired: dict[str, Any], *, registry: HarnessRegistry | None = None) -> tuple[str, ...]:
    return canonical_harnesses(desired["harnesses"], registry=registry)


def write_desired(
    home: Path, harnesses: Iterable[str], *, channel: str | None = None,
    canonicalize: bool = True,
) -> dict[str, Any]:
    current = _load_object(desired_file(home), label="desired harness state")
    assert current is not None
    _validate_desired_payload(current, path=desired_file(home))
    selected_channel = channel or current["updatePolicy"]["channel"]
    if selected_channel not in {"stable", "main"}:
        raise SystemExit(f"unsupported update channel: {selected_channel}")
    payload = {
        **current,
        "schemaVersion": STATE_SCHEMA_VERSION,
        "harnesses": list(canonical_harnesses(harnesses)) if canonicalize else sorted(set(harnesses)),
        "updatePolicy": {**current["updatePolicy"], "channel": selected_channel},
        "updatedAt": _now(),
    }
    atomic_write_json(desired_file(home), payload)
    return payload


def write_manager(
    home: Path,
    *,
    repository: str,
    revision: str,
    release_version: str,
    bundle_identity: str,
    channel: str,
    requested_ref: str,
    status: str = "ready",
) -> dict[str, Any]:
    if channel not in {"stable", "main", "embedded"}:
        raise SystemExit(f"unsupported update channel: {channel}")
    if status not in {"ready", "degraded"}:
        raise SystemExit(f"unsupported manager status: {status}")
    payload = {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "product": PRODUCT_NAME,
        "status": status,
        "repository": repository,
        "channel": channel,
        "requestedRef": requested_ref,
        "revision": revision,
        "releaseVersion": release_version,
        "bundleIdentity": bundle_identity,
        "updatedAt": _now(),
    }
    atomic_write_json(manager_file(home), payload)
    return payload


def write_harness_receipt(
    home: Path,
    *,
    harness: str,
    manager_revision: str,
    release_version: str,
    bundle_identity: str,
    root: str,
) -> None:
    registry = load_harness_registry()
    harness = registry.resolve_id(harness)
    receipts = _harness_receipts(home, harness)
    payload = {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "harness": harness,
        "status": "ready",
        "managerRevision": manager_revision,
        "releaseVersion": release_version,
        "bundleIdentity": bundle_identity,
        "root": root,
        "updatedAt": _now(),
    }
    target = harness_file(home, harness)
    atomic_write_json(target, payload)
    for path in receipts:
        if path != target:
            path.unlink()


def _harness_receipts(home: Path, harness: str, *, registry: HarnessRegistry | None = None) -> tuple[Path, ...]:
    """Validate every current/legacy receipt before replacing or deleting any."""
    registry = registry or load_harness_registry()
    canonical = registry.resolve_id(harness)
    parent = state_root(home) / HARNESS_STATE_DIR
    if parent.exists() or parent.is_symlink():
        metadata = parent.lstat()
        if (not stat.S_ISDIR(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise SystemExit(f"harness receipt parent must be an ordinary directory: {parent}")
    paths = []
    for name in (canonical, *registry.harnesses[canonical].aliases):
        path = harness_file(home, name)
        if not path.exists() and not path.is_symlink():
            continue
        metadata = path.lstat()
        if (not stat.S_ISREG(metadata.st_mode)
                or getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise SystemExit(f"harness receipt is not an ordinary file: {path}")
        payload = _load_object(path, label="harness receipt")
        assert payload is not None
        if (payload.get("schemaVersion") != STATE_SCHEMA_VERSION
                or payload.get("harness") not in (canonical, *registry.harnesses[canonical].aliases)):
            raise SystemExit(f"harness receipt identity is invalid; preserved: {path}")
        paths.append(path)
    return tuple(paths)


def validate_harness_receipts(home: Path, harness: str) -> None:
    _harness_receipts(home, harness)


def removal_consumers(home: Path, *, registry: HarnessRegistry | None = None) -> tuple[str, ...]:
    """Read the installed set without initializing or migrating manager state."""
    path = desired_file(home)
    payload = _load_object(path, label="desired harness state", required=False)
    if payload is not None:
        _validate_desired_payload(payload, path=path)
        return desired_harnesses(payload, registry=registry)
    initial = state_path(home) / "install.json"
    if initial.exists() or initial.is_symlink():
        receipt = install_receipt(home)
        if receipt.get("status") == "ready":
            return canonical_harnesses([receipt["harness"]], registry=registry)
    return ()


def recorded_harness_roots(home: Path, harness: str, *, registry: HarnessRegistry | None = None) -> tuple[str, ...]:
    roots = []
    for path in _harness_receipts(home, harness, registry=registry):
        payload = _load_object(path, label="harness receipt")
        root = payload.get("root")
        if payload.get("status") != "ready" or not isinstance(root, str) or not Path(root).is_absolute():
            raise SystemExit(f"harness receipt root/status is invalid; preserved: {path}")
        roots.append(root)
    return tuple(roots)


def translate_harness_receipts(home: Path, target_names: Iterable[str]) -> None:
    """Prepare equivalent receipt names for a journaled handoff to an older CLI."""
    registry = load_harness_registry()
    for target_name in target_names:
        canonical = registry.resolve_id(target_name)
        if target_name == canonical:
            continue
        receipts = _harness_receipts(home, canonical)
        if not receipts:
            continue
        payload = _load_object(receipts[0], label="harness receipt")
        assert payload is not None
        target = harness_file(home, target_name)
        atomic_write_json(target, {**payload, "harness": target_name})
        for path in receipts:
            if path != target:
                path.unlink()


def remove_harness_receipt(home: Path, harness: str) -> None:
    for path in _harness_receipts(home, harness):
        path.unlink()


def load_current_operation(home: Path) -> dict[str, Any] | None:
    return _load_object(
        current_operation_file(home),
        label="current manager operation",
        required=False,
    )


def begin_operation(home: Path, *, command: str, before: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    path = current_operation_file(home)
    if path.exists():
        raise SystemExit(
            f"an interrupted manager operation already exists: {path}; run `atm harness -- recover`"
        )
    operation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    payload = {
        "schemaVersion": STATE_SCHEMA_VERSION,
        "operationId": operation_id,
        "command": command,
        "phase": "prepared",
        "before": before,
        "target": target,
        "startedAt": _now(),
    }
    atomic_write_json(path, payload)
    return payload


def update_operation(home: Path, *, phase: str, **fields: Any) -> dict[str, Any]:
    path = current_operation_file(home)
    payload = _load_object(path, label="current manager operation")
    assert payload is not None
    payload["phase"] = phase
    payload["updatedAt"] = _now()
    payload.update(fields)
    atomic_write_json(path, payload)
    return payload


def finish_operation(home: Path, *, outcome: str, detail: str | None = None) -> None:
    path = current_operation_file(home)
    payload = _load_object(path, label="current manager operation")
    assert payload is not None
    payload["outcome"] = outcome
    payload["finishedAt"] = _now()
    if detail:
        payload["detail"] = detail
    history = operation_history_dir(home)
    history.mkdir(parents=True, exist_ok=True)
    target = history / f"{payload['operationId']}.json"
    atomic_write_json(target, payload)
    path.unlink()


class ManagerLock(AbstractContextManager["ManagerLock"]):
    """Exclusive mutation lock shared by all lifecycle commands."""

    def __init__(self, home: Path) -> None:
        self.path = state_root(home) / LOCK_FILE
        self.handle: Any | None = None

    def __enter__(self) -> "ManagerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        self.handle.write(b"\0")
        self.handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.handle.close()
            self.handle = None
            raise SystemExit(
                f"another atm-harness mutation is already running: {self.path}"
            ) from exc
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
