#!/usr/bin/env python3
"""Preflight, materialize, and check one harness's global instructions file."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from harness_registry import (
    REGISTRY_FILE,
    HarnessPlan,
    HarnessRegistryError,
    load_harness_registry,
    resolve_harness_plan,
)
from repo_skill_catalog import REPO_ROOT
from sync_agents_skills import is_junction, same_path


Input = Callable[[str], str]
Output = Callable[[str], None]
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
AUTO_MIGRATION_PROVENANCE = frozenset({"registry-peer", "operation-journal"})


@dataclass(frozen=True)
class TargetSnapshot:
    kind: str
    digest: str | None = None
    link_target: Path | None = None


@dataclass(frozen=True)
class PreparedInstructionSync:
    plan: HarnessPlan
    action: str
    snapshot: TargetSnapshot
    source_digest: str | None
    provenance: str
    approved: bool


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def materialized_instruction_bytes(repo: Path, revision: str, relative_path: str) -> bytes:
    """Read Git's exact checkout bytes, using the revision's own attributes.

    A private index and empty worktree avoid both the live checkout's attributes
    and its file contents. Git applies core.autocrlf, eol attributes, and filters
    exactly as it does when the manager switches revisions.
    """
    with tempfile.TemporaryDirectory(prefix="atm-harness-instructions-") as temporary:
        root = Path(temporary)
        worktree = root / "worktree"
        worktree.mkdir()
        environment = {
            **os.environ,
            "GIT_INDEX_FILE": str(root / "index"),
            "GIT_WORK_TREE": str(worktree),
        }
        for arguments in (
            ["read-tree", revision],
            ["checkout-index", "--prefix=" + worktree.as_posix() + "/", "--", relative_path],
        ):
            try:
                result = subprocess.run(
                    ["git", "-C", str(repo), *arguments],
                    env=environment, capture_output=True, check=False,
                )
            except OSError as exc:
                raise SystemExit(f"cannot materialize journaled instructions: {exc}") from exc
            if result.returncode:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise SystemExit(f"cannot materialize journaled instructions: {detail}")
        source = worktree / relative_path
        _validate_regular_source(source, label="journaled instructions source")
        return source.read_bytes()


def materialized_instruction_digest(repo: Path, revision: str, relative_path: str) -> str:
    return hashlib.sha256(materialized_instruction_bytes(repo, revision, relative_path)).hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(flag and attributes & flag)


def _snapshot(path: Path) -> TargetSnapshot:
    if path.is_symlink():
        return TargetSnapshot(
            kind="symlink",
            link_target=path.resolve(strict=False),
        )
    if is_junction(path):
        return TargetSnapshot(kind="junction", link_target=path.resolve(strict=False))
    if not _lexists(path):
        return TargetSnapshot(kind="missing")
    if _is_reparse_point(path):
        return TargetSnapshot(kind="reparse-point")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SystemExit(f"cannot inspect instructions target: {path}: {exc}") from exc
    if stat.S_ISDIR(metadata.st_mode):
        return TargetSnapshot(kind="directory")
    if not stat.S_ISREG(metadata.st_mode):
        return TargetSnapshot(kind="non-file")
    try:
        digest = _digest(path)
    except OSError as exc:
        raise SystemExit(f"cannot read instructions target: {path}: {exc}") from exc
    return TargetSnapshot(kind="file", digest=digest)


def _validate_regular_source(source: Path, *, label: str) -> None:
    if source.is_symlink() or not source.is_file():
        raise SystemExit(f"{label} must be a regular file: {source}")


def _validate_source(plan: HarnessPlan) -> None:
    _validate_regular_source(
        plan.instructions_source,
        label="canonical instructions source",
    )


def _validated_source_digest(plan: HarnessPlan) -> str:
    _validate_source(plan)
    try:
        return _digest(plan.instructions_source)
    except OSError as exc:
        raise SystemExit(
            f"cannot read canonical instructions source: {plan.instructions_source}: {exc}"
        ) from exc


def _validated_peer_digest(plan: HarnessPlan) -> tuple[Path, str]:
    peer = plan.instructions_migration.peer_source
    _validate_regular_source(peer, label="registry instruction migration peer")
    try:
        return peer, _digest(peer)
    except OSError as exc:
        raise SystemExit(
            f"cannot read registry instruction migration peer: {peer}: {exc}"
        ) from exc


def _validated_operation_digests(values: tuple[str, ...]) -> frozenset[str]:
    invalid = sorted({value for value in values if not DIGEST_PATTERN.fullmatch(value)})
    if invalid:
        raise SystemExit(
            "operation journal contains invalid instruction digest(s): "
            + ", ".join(invalid)
        )
    return frozenset(values)


def _former_source_digests(sources: tuple[Path, ...]) -> frozenset[str]:
    digests: set[str] = set()
    for source in sources:
        if source.is_symlink() or not source.is_file():
            continue
        try:
            digests.add(_digest(source))
        except OSError as exc:
            raise SystemExit(
                f"cannot read explicit former-repo instructions source: {source}: {exc}"
            ) from exc
    return frozenset(digests)


def _classify_target(
    plan: HarnessPlan,
    snapshot: TargetSnapshot,
    *,
    explicit_former_sources: tuple[Path, ...] = (),
    operation_managed_digests: tuple[str, ...] = (),
) -> tuple[str, str]:
    """Return the action and the single evidence source that owns the target."""

    source_digest = _validated_source_digest(plan)
    peer_source, peer_digest = _validated_peer_digest(plan)
    operation_digests = _validated_operation_digests(operation_managed_digests)
    former_digests = _former_source_digests(explicit_former_sources)
    materialization = plan.instructions_materialization
    assert materialization in {"copy", "symlink"}

    if snapshot.kind in {"junction", "reparse-point", "directory", "non-file"}:
        raise SystemExit(
            "refusing unsupported instructions target type "
            f"{snapshot.kind}: {plan.instructions_target}"
        )
    if snapshot.kind == "missing":
        return "create", "unmanaged"
    if snapshot.kind == "symlink":
        assert snapshot.link_target is not None
        if same_path(snapshot.link_target, plan.instructions_source):
            provenance = "current"
        elif peer_source is not None and same_path(snapshot.link_target, peer_source):
            provenance = "registry-peer"
        elif any(
            same_path(snapshot.link_target, source)
            for source in explicit_former_sources
        ):
            provenance = "explicit-former-repo"
        else:
            provenance = "unmanaged"
        if provenance == "unmanaged":
            raise SystemExit(
                "refusing unmanaged instructions symlink: "
                f"{plan.instructions_target} -> {snapshot.link_target}"
            )
        if provenance == "current" and materialization == "symlink":
            return "current", provenance
        return "replace", provenance

    assert snapshot.kind == "file"
    if snapshot.digest == source_digest:
        provenance = "current"
    elif peer_digest is not None and snapshot.digest == peer_digest:
        provenance = "registry-peer"
    elif snapshot.digest in operation_digests:
        provenance = "operation-journal"
    elif snapshot.digest in former_digests:
        provenance = "explicit-former-repo"
    else:
        provenance = "unmanaged"
    if provenance == "current" and materialization == "copy":
        return "current", provenance
    return "replace", provenance


def _inspect(
    plan: HarnessPlan,
    *,
    explicit_former_sources: tuple[Path, ...] = (),
    operation_managed_digests: tuple[str, ...] = (),
) -> PreparedInstructionSync:
    source_digest = _validated_source_digest(plan)
    for shadow in plan.instruction_shadow_paths:
        if _lexists(shadow):
            raise SystemExit(
                f"managed instructions would be shadowed for harness {plan.harness_id}: {shadow}"
            )

    target = plan.instructions_target
    snapshot = _snapshot(target)
    action, provenance = _classify_target(
        plan,
        snapshot,
        explicit_former_sources=explicit_former_sources,
        operation_managed_digests=operation_managed_digests,
    )
    return PreparedInstructionSync(
        plan,
        action,
        snapshot,
        source_digest,
        provenance,
        action == "current",
    )


def _confirm(prompt: str, *, input_fn: Input) -> bool:
    try:
        answer = input_fn(f"{prompt} [y/N] ")
    except (EOFError, OSError):
        return False
    return answer.strip() in {"y", "Y", "yes", "YES", "Yes"}


def prepare_instruction_sync(
    plan: HarnessPlan,
    *,
    dry_run: bool,
    assume_yes: bool,
    explicit_former_sources: tuple[Path, ...] = (),
    operation_managed_digests: tuple[str, ...] = (),
    non_interactive: bool = False,
    input_fn: Input = input,
    output: Output = print,
) -> PreparedInstructionSync | None:
    if plan.instructions_target is None:
        output(f"harness {plan.harness_id} manages skills only; no global instructions target")
        return None
    prepared = _inspect(
        plan,
        explicit_former_sources=explicit_former_sources,
        operation_managed_digests=operation_managed_digests,
    )
    target = plan.instructions_target
    if prepared.action == "current":
        output(f"instructions already current: {target}")
        return prepared

    output(f"InstructionsHarness={plan.harness_id}")
    output(f"InstructionsSource={plan.instructions_source}")
    output(f"InstructionsTarget={target}")
    output(f"InstructionsTargetType={prepared.snapshot.kind}")
    output(f"InstructionsMaterialization={plan.instructions_materialization}")
    output(f"InstructionsProvenance={prepared.provenance}")
    if prepared.snapshot.digest is not None:
        output(f"InstructionsTargetSHA256={prepared.snapshot.digest}")
        output(f"InstructionsSourceSHA256={prepared.source_digest}")
    if prepared.provenance == "explicit-former-repo":
        output(
            "InstructionsExplicitFormerRepoSource="
            f"{prepared.snapshot.link_target or 'content-digest'}"
        )
    if dry_run:
        output(f"would {prepared.action} harness instructions: {target}")
        return PreparedInstructionSync(
            plan,
            prepared.action,
            prepared.snapshot,
            prepared.source_digest,
            prepared.provenance,
            True,
        )

    if prepared.provenance in AUTO_MIGRATION_PROVENANCE:
        approved = True
        output(
            "Existing instructions replacement authorized by exact managed "
            f"provenance: {prepared.provenance}"
        )
    elif prepared.action == "create":
        approved = assume_yes or _confirm(
            f"Create {plan.harness_id} global instructions",
            input_fn=input_fn,
        )
        if assume_yes:
            output(f"Create {plan.harness_id} global instructions [auto-confirmed]")
    else:
        if non_interactive:
            raise SystemExit(
                "confirmation_required: existing instructions replacement requires "
                "a live confirmation: " + str(target)
            )
        output(
            "Existing instructions replacement requires a live confirmation; "
            "--yes does not authorize replacement."
        )
        approved = _confirm(
            f"Replace existing {plan.harness_id} global instructions",
            input_fn=input_fn,
        )
    if not approved:
        raise SystemExit(f"{plan.harness_id} instructions sync was not confirmed")
    return PreparedInstructionSync(
        plan,
        prepared.action,
        prepared.snapshot,
        prepared.source_digest,
        prepared.provenance,
        True,
    )


def _revalidate(prepared: PreparedInstructionSync) -> None:
    source_digest = _validated_source_digest(prepared.plan)
    if source_digest != prepared.source_digest:
        raise SystemExit(
            "canonical instructions source changed after preflight; refusing write: "
            f"{prepared.plan.instructions_source}"
        )
    target = prepared.plan.instructions_target
    current = _snapshot(target)
    if current != prepared.snapshot:
        raise SystemExit(
            "instructions target changed after preflight; refusing replacement: "
            f"{target}: expected {prepared.snapshot}, found {current}"
        )


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.atm-",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        shutil.copymode(source, temporary)
        os.replace(temporary, target)
    finally:
        if _lexists(temporary):
            temporary.unlink()


def _atomic_symlink(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.atm-{os.getpid()}"
    if _lexists(temporary):
        raise SystemExit(f"temporary instructions link already exists: {temporary}")
    try:
        temporary.symlink_to(source)
        os.replace(temporary, target)
    finally:
        if _lexists(temporary):
            temporary.unlink()


def apply_instruction_sync(prepared: PreparedInstructionSync | None, *, dry_run: bool) -> None:
    if prepared is None or prepared.action == "current" or dry_run:
        return
    if not prepared.approved:
        raise SystemExit("instructions mutation was not approved during preflight")
    _revalidate(prepared)
    plan = prepared.plan
    target = plan.instructions_target
    if plan.instructions_materialization == "copy":
        _atomic_copy(plan.instructions_source, target)
    elif plan.instructions_materialization == "symlink":
        _atomic_symlink(plan.instructions_source, target)
    else:  # pragma: no cover - registry validation owns this branch
        raise SystemExit(
            f"unsupported instructions materialization: {plan.instructions_materialization!r}"
        )
    issues = check_instruction_sync(plan)
    if issues:
        raise SystemExit("instructions closure failed after sync: " + "; ".join(issues))
    print(f"instructions synced for {plan.harness_id}: {target}")


def check_instruction_sync(plan: HarnessPlan) -> list[str]:
    if plan.instructions_target is None:
        return []
    try:
        prepared = _inspect(plan)
    except SystemExit as exc:
        return [str(exc)]
    if prepared.action == "current":
        return []
    target = plan.instructions_target
    if prepared.action == "create":
        return [f"global instructions are missing for {plan.harness_id}: {target}"]
    if prepared.provenance == "registry-peer":
        return [
            f"managed instructions migration is pending for {plan.harness_id}: "
            f"{target} ({prepared.snapshot.kind})"
        ]
    return [
        f"global instructions differ for {plan.harness_id}: "
        f"{target} ({prepared.snapshot.kind})"
    ]


def remove_instruction_sync(plan: HarnessPlan, *, dry_run: bool) -> None:
    """Remove only instructions proven to match current or registry-peer state."""

    target = plan.instructions_target
    if target is None:
        return
    snapshot = _snapshot(target)
    if snapshot.kind == "missing":
        print(f"instructions already clear for {plan.harness_id}: {target}")
        return

    try:
        _action, provenance = _classify_target(plan, snapshot)
    except SystemExit as exc:
        raise SystemExit(
            "refusing to remove changed or unmanaged instructions target: "
            f"{target} ({snapshot.kind}): {exc}"
        ) from exc
    if provenance not in {"current", "registry-peer"}:
        raise SystemExit(
            "refusing to remove changed or unmanaged instructions target: "
            f"{target} ({snapshot.kind})"
        )

    print(f"{'would remove' if dry_run else 'remove'} managed instructions: {target}")
    if dry_run:
        return
    current = _snapshot(target)
    if current != snapshot:
        raise SystemExit(
            "instructions target changed after removal preflight; refusing deletion: "
            f"{target}"
        )
    target.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage global instructions for one harness.")
    parser.add_argument(
        "--harness",
        help="Registry harness id (default: registry-owned).",
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--registry", default=str(REGISTRY_FILE))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve(strict=False)
    registry_path = Path(args.registry).expanduser().resolve(strict=False)
    try:
        registry = load_harness_registry(registry_path, repo_root=repo_root)
        plan = resolve_harness_plan(registry, args.harness, repo_root=repo_root)
    except HarnessRegistryError as exc:
        raise SystemExit(str(exc)) from exc
    if plan.instructions_target is None:
        print(f"harness {plan.harness_id} manages skills only; no global instructions target")
        return 0
    if args.check:
        issues = check_instruction_sync(plan)
        if issues:
            for issue in issues:
                print(f"FAIL {issue}")
            return 1
        print(f"OK instructions are current for {plan.harness_id}")
        return 0
    prepared = prepare_instruction_sync(
        plan,
        dry_run=args.dry_run,
        assume_yes=args.yes,
    )
    apply_instruction_sync(prepared, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
