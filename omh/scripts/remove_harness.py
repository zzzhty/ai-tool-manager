#!/usr/bin/env python3
"""Remove only resources proven to belong to one oh-my-harness distribution."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

from harness_registry import (
    REGISTRY_FILE,
    HarnessRegistryError,
    load_harness_registry,
    resolve_harness_plan,
    resolve_harness_root,
    configured_instruction_targets,
)
from manager_paths import lexical_absolute, manager_home, venv_path, venv_python
from manager_state import removal_consumers, recorded_harness_roots
from repo_skill_catalog import load_repo_skill_catalog
from sync_agents_skills import remove_all_managed_entries
from sync_codex_agents import is_managed as is_managed_agent_support
from sync_harness_instructions import remove_instruction_sync
from refresh_harness import (
    build_env,
    cached_plugin_names,
    configured_marketplace,
    configured_plugin_names,
    default_plugin_names,
    git_remote_source,
    load_install_manifest,
    remove_cached_plugin_dir,
    remove_marketplace_source,
    require_codex_plugin_commands,
    resolve_codex_executable,
    run,
    same_marketplace_source,
    same_path,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [y/N] ")
    except (EOFError, OSError):
        return False
    return answer.strip() in {"y", "Y", "yes", "YES", "Yes"}


def _remove_codex_agent_support(codex_home: Path, *, dry_run: bool) -> None:
    root = codex_home / "agents"
    if not root.is_dir():
        return
    managed = [
        path
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.is_file() and not path.is_symlink() and is_managed_agent_support(path)
    ]
    for path in managed:
        print(f"{'would remove' if dry_run else 'remove'} managed agent support: {path}")
        if not dry_run:
            path.unlink()


def _remove_watcher_hooks(
    tooling_python: Path,
    *,
    codex_home: Path,
    dry_run: bool,
) -> None:
    hooks = codex_home / "hooks.json"
    if not hooks.exists():
        return
    watcher = REPO_ROOT / "plugins" / "watcher" / "scripts" / "watcher"
    if not tooling_python.is_file():
        raise SystemExit(f"tooling Python does not exist: {tooling_python}")
    if not watcher.is_file():
        raise SystemExit(f"Watcher CLI does not exist: {watcher}")
    command = [
        str(tooling_python),
        str(watcher),
        "skill",
        "uninstall-hook",
        "--target",
        str(hooks),
    ]
    command.append("--dry-run" if dry_run else "--apply")
    run(command, env=os.environ.copy(), dry_run=False)


def _validate_owned_marketplace(codex_home: Path, marketplace_name: str) -> None:
    config = configured_marketplace(codex_home, marketplace_name)
    if config is None:
        return
    source_type = config.get("source_type")
    source = config.get("source")
    if source_type == "local" and source:
        if not same_path(source, REPO_ROOT):
            raise SystemExit(
                "refusing to remove Codex marketplace whose local source is not the "
                f"canonical checkout: {source}"
            )
        return
    if source_type == "git" and source:
        canonical = git_remote_source(REPO_ROOT)
        if canonical is None or not same_marketplace_source(source, canonical):
            raise SystemExit(
                "refusing to remove Codex marketplace whose Git source is not the "
                f"canonical checkout remote: {source}"
            )
        return
    raise SystemExit(
        f"refusing to remove Codex marketplace with unsupported source binding: {marketplace_name}"
    )


def _remove_codex(
    plan,
    *,
    home: Path,
    codex_path: str | None,
    tooling_python: Path,
    dry_run: bool,
) -> None:
    if plan.marketplace_path is None or plan.install_manifest_path is None:
        raise SystemExit("codex harness did not resolve marketplace metadata")
    manifest = load_install_manifest(plan.install_manifest_path)
    marketplace_name = manifest["marketplace"]
    desired_names = set(
        default_plugin_names(
            "install",
            marketplace_name=marketplace_name,
            manifest_file=plan.install_manifest_path,
            marketplace_file=plan.marketplace_path,
        )
    )
    configured = configured_plugin_names(plan.root, marketplace_name)
    cached = cached_plugin_names(plan.root, marketplace_name)
    unknown = sorted((configured | cached) - desired_names)
    if unknown:
        raise SystemExit(
            "refusing Codex removal because the oh-my-harness marketplace contains "
            "unclassified plugin state: " + ", ".join(unknown)
        )
    _validate_owned_marketplace(plan.root, marketplace_name)

    codex = resolve_codex_executable(codex_path, codex_home=plan.root)
    env = build_env(
        codex_home=plan.root,
        tooling_python=tooling_python,
        manager_home=home,
    )
    require_codex_plugin_commands(
        codex,
        env=env,
        require_marketplace=bool(configured_marketplace(plan.root, marketplace_name)),
        require_add=False,
        require_list=False,
        require_remove=bool(configured),
    )

    print(f"Codex removal plan for marketplace `{marketplace_name}`:")
    for name in sorted(configured | cached):
        locations = []
        if name in configured:
            locations.append("config")
        if name in cached:
            locations.append("cache")
        print(f"- {name} ({'+'.join(locations)})")
    if configured_marketplace(plan.root, marketplace_name):
        print(f"- marketplace source {marketplace_name}")

    for name in sorted(configured):
        run(
            [codex, "plugin", "remove", f"{name}@{marketplace_name}"],
            env=env,
            dry_run=dry_run,
        )
    for name in sorted(cached):
        remove_cached_plugin_dir(
            codex_home=plan.root,
            marketplace_name=marketplace_name,
            plugin_name=name,
            dry_run=dry_run,
        )
    if configured_marketplace(plan.root, marketplace_name):
        remove_marketplace_source(
            codex,
            codex_home=plan.root,
            marketplace_name=marketplace_name,
            env=env,
            dry_run=dry_run,
        )
    _remove_codex_agent_support(plan.root, dry_run=dry_run)
    _remove_watcher_hooks(tooling_python, codex_home=plan.root, dry_run=dry_run)


def _resource_path(path: Path) -> str:
    # Keep the final component lexical: instruction symlinks target source files.
    # Resolve parent aliases and normalize Windows case for resource identity.
    return os.path.normcase(str(path.parent.resolve(strict=False) / path.name))


def _directory_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _same_directory(left: Path, right: Path) -> bool:
    """Use the filesystem's case/alias rules, retaining absent-path fallback."""
    try:
        return os.path.samefile(left, right)
    except OSError:
        return _directory_path(left) == _directory_path(right)


def _same_resource(left: Path, right: Path) -> bool:
    # Match directory entries, not the destinations of final-component symlinks.
    # Two instruction links to the same source in different roots are distinct.
    if not _same_directory(left.parent, right.parent):
        return False
    if left.name == right.name:
        return True
    try:
        return os.path.samestat(left.lstat(), right.lstat())
    except OSError:
        return _resource_path(left) == _resource_path(right)


def _resource_within_root(path: Path, root: Path, *, directory: bool = False) -> bool:
    if Path(_resource_path(path)).is_relative_to(Path(_directory_path(root))):
        return True
    if directory and _same_directory(path, root):
        return True
    # Walk only the selected path's ancestors, never scan a user's directory.
    parent = path.parent.resolve(strict=False)
    return any(_same_directory(root, ancestor) for ancestor in (parent, *parent.parents))


def shared_resources(plan, *, registry, home: Path, environment: dict,
                     preview_removed: tuple[str, ...] = ()) -> tuple[bool, bool]:
    """Protect each physical resource while another installed consumer needs it.

    Receipts are evidence of resolved roots, never arbitrary deletion targets.
    Resolve current plans and reject root drift before trusting shared ownership.
    """
    installed = removal_consumers(home, registry=registry)
    keep_skills = keep_instructions = False
    selected_paths = []
    if plan.instructions_target is not None:
        selected_paths.append(plan.instructions_target)
    if plan.skills_root is not None:
        selected_paths.append(plan.skills_root)

    def overlaps_root(root: Path) -> bool:
        return any(
            _resource_within_root(path, root, directory=path == plan.skills_root)
            for path in selected_paths
        )

    for name in dict.fromkeys((*installed, plan.harness_id)):
        if name != plan.harness_id and name in preview_removed:
            continue
        roots = recorded_harness_roots(home, name, registry=registry)
        current_root = resolve_harness_root(registry, name, environ=environment)
        spec = registry.harnesses[registry.resolve_id(name)].instructions
        if (plan.instructions_target is not None and name != plan.harness_id
                and spec.driver == "settings-derived-file"
                and any(not _same_directory(lexical_absolute(root), current_root) for root in roots)):
            # The old dynamic filename was not recorded; a nested alias may have
            # pointed outside that root. Current settings cannot prove it unused.
            keep_instructions = True
            print(f"warning: retain instructions because {name} recorded dynamic root has changed")
        recorded_overlap = any(overlaps_root(lexical_absolute(root)) for root in roots)
        try:
            other = resolve_harness_plan(registry, name, repo_root=REPO_ROOT, environ=environment)
        except HarnessRegistryError:
            # A disjoint client's broken dynamic settings are not a prerequisite
            # for this removal. Check current AND recorded roots before ignoring
            # the failure; environment drift may have moved it into this target.
            if (name != plan.harness_id and not recorded_overlap
                    and not overlaps_root(current_root) and spec.driver == "settings-derived-file"):
                try:
                    candidates = configured_instruction_targets(spec, root=current_root)
                except HarnessRegistryError:
                    # Without readable candidates, roots alone cannot exclude an
                    # intermediate directory alias into the selected file. Keep
                    # that file, but let unrelated skills/logical removal proceed.
                    if plan.instructions_target is not None:
                        keep_instructions = True
                        print(f"warning: retain instructions because {name} configured targets cannot be determined")
                else:
                    if plan.instructions_target is not None and any(
                        _same_resource(path, plan.instructions_target) for path in candidates
                    ):
                        keep_instructions = True
                        print(f"warning: retain instructions referenced by {name} multi-target settings")
                continue
            raise
        shares_skills = (plan.skills_root is not None and other.skills_root is not None
                         and _same_resource(plan.skills_root, other.skills_root))
        shares_instructions = (plan.instructions_target is not None
                               and other.instructions_target is not None
                               and _same_resource(plan.instructions_target, other.instructions_target))
        relevant = name == plan.harness_id or shares_skills or shares_instructions or recorded_overlap
        if not relevant:
            continue
        # Older Codex receipts ignored --codex-home. Allow removing that selected
        # Codex target through its existing ownership checks, but never disregard
        # an overlapping receipt for a Codex consumer that will remain installed.
        if (other.harness.skills.driver == "directory-projection"
                or (name != plan.harness_id and recorded_overlap)):
            for root in roots:
                if not _same_directory(lexical_absolute(root), other.root):
                    raise SystemExit(
                        f"recorded root for {name} differs from current resolution; "
                        "restore the recorded root configuration before removal"
                    )
        if name == plan.harness_id:
            continue
        if not roots and (shares_skills or shares_instructions):
            raise SystemExit(f"installed consumer {name} has no receipt; run omh refresh before removal")
        keep_skills |= shares_skills
        keep_instructions |= shares_instructions
    return keep_skills, keep_instructions


def remove_harness(
    harness: str,
    *,
    registry_path: Path,
    home: Path,
    codex_home: Path | None,
    codex_path: str | None,
    tooling_python: Path,
    dry_run: bool,
    assume_yes: bool,
    preview_removed: tuple[str, ...] = (),
) -> None:
    environment = dict(os.environ)
    if codex_home is not None:
        environment["CODEX_HOME"] = str(codex_home)
    try:
        registry = load_harness_registry(registry_path, repo_root=REPO_ROOT)
        plan = resolve_harness_plan(
            registry,
            harness,
            repo_root=REPO_ROOT,
            environ=environment,
        )
    except HarnessRegistryError as exc:
        raise SystemExit(str(exc)) from exc

    if preview_removed and not dry_run:
        raise SystemExit("preview-removed is only valid with --dry-run")
    keep_skills, keep_instructions = shared_resources(
        plan, registry=registry, home=home, environment=environment,
        preview_removed=preview_removed,
    )
    # Even retained resources must pass the existing ownership checks. Preflight
    # both before deleting either, so edited instructions cannot cause half-removal.
    catalog = load_repo_skill_catalog()
    with contextlib.redirect_stdout(io.StringIO()):
        if plan.skills_root is not None:
            remove_all_managed_entries(catalog, target_root=plan.skills_root, dry_run=True)
        remove_instruction_sync(plan, dry_run=True)
    if keep_skills:
        print(f"retain shared skills for another installed harness: {plan.skills_root}")
    if keep_instructions:
        print(f"retain shared instructions for another installed harness: {plan.instructions_target}")

    print(f"Remove oh-my-harness distribution from {plan.harness.display_name}:")
    if plan.skills_root is not None:
        print(f"- managed skill projections under {plan.skills_root}")
    if plan.instructions_target is not None:
        print(f"- managed instructions at {plan.instructions_target}")
    if plan.harness_id == "codex":
        print("- managed Codex marketplace/plugins, Watcher hooks, and agent support")

    if not dry_run and not assume_yes and not _confirm(f"Remove {plan.harness_id} distribution"):
        raise SystemExit(f"{plan.harness_id} removal was not confirmed")

    if plan.harness_id == "codex":
        _remove_codex(
            plan,
            home=home,
            codex_path=codex_path,
            tooling_python=tooling_python,
            dry_run=dry_run,
        )
    elif not keep_skills:
        if plan.skills_root is None:
            raise SystemExit(f"harness {plan.harness_id} has no skill projection root")
        remove_all_managed_entries(
            catalog,
            target_root=plan.skills_root,
            dry_run=dry_run,
        )

    if not keep_instructions:
        remove_instruction_sync(plan, dry_run=dry_run)

    if dry_run:
        print(f"dry-run only; {plan.harness_id} distribution was not removed")
    elif keep_skills or keep_instructions:
        print(f"finished {plan.harness_id} removal; shared or uncertain resources retained")
    else:
        print(f"removed oh-my-harness distribution from {plan.harness_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--registry", default=str(REGISTRY_FILE))
    parser.add_argument("--home")
    parser.add_argument("--codex-home")
    parser.add_argument("--codex")
    parser.add_argument("--python")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--preview-removed", action="append", default=[], help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    home = manager_home(args.home).resolve(strict=False)
    tooling_python = (
        Path(args.python).expanduser()
        if args.python
        else venv_python(venv_path(home))
    )
    remove_harness(
        args.harness,
        registry_path=Path(args.registry).expanduser(),
        home=home,
        codex_home=Path(args.codex_home).expanduser() if args.codex_home else None,
        codex_path=args.codex,
        tooling_python=tooling_python,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        preview_removed=tuple(args.preview_removed),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
