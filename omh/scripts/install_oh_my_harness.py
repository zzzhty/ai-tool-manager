#!/usr/bin/env python3
"""Initialize one managed oh-my-harness installation."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

# A dry run from the managed checkout must not create local import caches.
sys.dont_write_bytecode = True

from harness_registry import HarnessRegistryError, load_harness_registry
from manager_paths import (
    PRODUCT_NAME,
    bin_path,
    expand_path,
    manager_home,
    repo_path,
    state_path,
    venv_path,
    venv_python,
)
from terminal_output import write_stderr
from manager_environment import ensure_user_path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REF = "main"
_REPARSE_POINT_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
MINIMUM_PYTHON_VERSION = (3, 11)


def _require_supported_python() -> None:
    current = sys.version_info[:3]
    if current[:2] >= MINIMUM_PYTHON_VERSION:
        return
    required = ".".join(str(component) for component in MINIMUM_PYTHON_VERSION)
    found = ".".join(str(component) for component in current)
    executable = Path(sys.executable).expanduser().resolve(strict=False)
    raise SystemExit(
        f"Python {required} or newer is required; found Python {found} at {executable}. "
        "Use a supported interpreter directly, or set OH_MY_HARNESS_BOOTSTRAP_PYTHON "
        "for the installer and omh launchers."
    )


@dataclass(frozen=True)
class ValidatedRecovery:
    allowed_existing: frozenset[Path]
    revision: str


def command_text(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def run(command: list[str], *, dry_run: bool = False, cwd: Path | None = None) -> None:
    print("+ " + command_text(command), flush=True)
    if dry_run:
        return
    subprocess.run(command, cwd=cwd, check=True)


def bootstrap_python() -> Path:
    raw = getattr(sys, "_base_executable", None) or sys.executable
    try:
        resolved = Path(raw).expanduser().resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"bootstrap Python cannot be resolved: {raw}: {exc}") from exc
    if not resolved.is_file():
        raise SystemExit(f"bootstrap Python is not a file: {resolved}")
    return resolved


def repository_from_checkout(source_root: Path = SOURCE_ROOT) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
    )
    repository = result.stdout.strip() if result.returncode == 0 else ""
    if not repository:
        raise SystemExit(
            "repository source is required; pass --repository or run the installer "
            "from a checkout with remote.origin.url"
        )
    return repository


def resolve_owned_leaf(path: Path) -> Path:
    """Normalize the requested manager path without erasing link identity."""

    return Path(os.path.abspath(path))


def path_metadata(path: Path, *, label: str) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SystemExit(f"{label} cannot be inspected: {path}: {exc}") from exc


def metadata_is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(
        _REPARSE_POINT_FLAG
        and getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT_FLAG
    )


def is_ordinary_directory(path: Path, *, label: str = "path") -> bool:
    metadata = path_metadata(path, label=label)
    return bool(
        metadata is not None
        and stat.S_ISDIR(metadata.st_mode)
        and not metadata_is_reparse_point(metadata)
    )


def is_ordinary_file(path: Path, *, label: str = "path") -> bool:
    metadata = path_metadata(path, label=label)
    return bool(
        metadata is not None
        and stat.S_ISREG(metadata.st_mode)
        and not metadata_is_reparse_point(metadata)
    )


def path_exists_without_following(path: Path, *, label: str = "path") -> bool:
    return path_metadata(path, label=label) is not None


def require_ordinary_directory(path: Path, *, label: str) -> None:
    if not is_ordinary_directory(path, label=label):
        raise SystemExit(f"{label} must be an ordinary directory: {path}")


def validate_manager_home(home: Path) -> None:
    if not path_exists_without_following(home, label="manager home"):
        return
    require_ordinary_directory(home, label="manager home")


def validate_install_root(
    home: Path,
    *,
    adopted_repo: Path | None = None,
    allowed_existing: frozenset[Path] = frozenset(),
) -> None:
    validate_manager_home(home)
    managed_paths = (repo_path(home), venv_path(home), bin_path(home), state_path(home), home / "bootstrap")
    occupied = []
    for path in managed_paths:
        if not path_exists_without_following(path, label="manager-owned path"):
            continue
        if adopted_repo is not None and path == repo_path(home):
            require_ordinary_directory(path, label="managed repository root")
            try:
                same_repo = path.resolve(strict=True) == adopted_repo.resolve(strict=True)
            except OSError as exc:
                raise SystemExit(
                    f"managed repository root cannot be resolved: {path}: {exc}"
                ) from exc
            if same_repo:
                continue
        if path in allowed_existing:
            require_ordinary_directory(path, label="manager-owned recovery path")
            continue
        occupied.append(path)
    if occupied:
        raise SystemExit(
            "refusing to initialize over existing manager-owned paths: "
            + ", ".join(str(path) for path in occupied)
        )


def clone_repository(
    repository: str,
    *,
    ref: str,
    home: Path,
    dry_run: bool,
) -> Path:
    target = repo_path(home)
    temporary = home / f".repo.install-{uuid.uuid4().hex}"
    command = [
        "git",
        "clone",
        "--branch",
        ref,
        "--single-branch",
        "--",
        repository,
        str(temporary),
    ]
    if dry_run:
        run(command, dry_run=True)
        print(f"would activate managed checkout: {temporary} -> {target}")
        return target

    home.mkdir(parents=True, exist_ok=True)
    require_ordinary_directory(home, label="manager home")
    try:
        run(command)
        temporary.rename(target)
    except BaseException:
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    return target


def launcher_paths(home: Path) -> tuple[Path, Path]:
    root = bin_path(home)
    if os.name == "nt":
        return root / "oh-my-harness.cmd", root / "omh.cmd"
    return root / "oh-my-harness", root / "omh"


def launcher_help_invocation(platform_name: str) -> str:
    return "omh --help"


def _bootstrap_script_path(home: Path) -> Path:
    return home / "bootstrap" / "omh_bootstrap.py"


def write_bootstrap(*, home: Path, repo: Path, dry_run: bool) -> Path:
    source = repo / "scripts" / "omh_bootstrap.py"
    target = _bootstrap_script_path(home)
    print(f"{'would write' if dry_run else 'write'} bootstrap: {target}")
    if dry_run:
        return target
    if not source.is_file() or source.is_symlink():
        raise SystemExit(f"manager bootstrap source must be an ordinary file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    require_ordinary_directory(target.parent, label="manager bootstrap root")
    temporary = target.parent / f".{target.name}.install-{uuid.uuid4().hex}"
    temporary.write_bytes(source.read_bytes())
    os.replace(temporary, target)
    return target


def posix_launcher(*, home: Path, repo: Path) -> str:
    return r'''#!/usr/bin/env sh
set -eu
bootstrap_python=
if [ -n "${OH_MY_HARNESS_BOOTSTRAP_PYTHON:-}" ]; then
    bootstrap_python=$OH_MY_HARNESS_BOOTSTRAP_PYTHON
    "$bootstrap_python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
        echo "error: OH_MY_HARNESS_BOOTSTRAP_PYTHON must select Python 3.11 or newer" >&2
        exit 1
    }
else
    for candidate in python3 python python3.14 python3.13 python3.12 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
            bootstrap_python=$(command -v "$candidate")
            break
        fi
    done
fi
if [ -z "$bootstrap_python" ]; then
    echo "error: Python 3.11 or newer not found; set OH_MY_HARNESS_BOOTSTRAP_PYTHON" >&2
    exit 1
fi
omh_command=$0
case "$omh_command" in
    */*) ;;
    *) omh_command=$(command -v "$omh_command") ;;
esac
omh_home=$("$bootstrap_python" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parent.parent)' "$omh_command")
exec "$bootstrap_python" "$omh_home/bootstrap/omh_bootstrap.py" --home "$omh_home" "$@"
'''


def windows_launcher(*, home: Path, repo: Path) -> str:
    # CMD must parse the invocation and exit together before an update replaces
    # this file. CALL expands the child's status after it returns; arguments keep
    # delayed expansion disabled so literal exclamation marks survive.
    return r'''@echo off
setlocal DisableDelayedExpansion
for %%I in ("%~dp0..") do set "OMH_HOME=%%~fI"
if defined OH_MY_HARNESS_BOOTSTRAP_PYTHON (
  "%OH_MY_HARNESS_BOOTSTRAP_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
  if errorlevel 1 (
    echo error: OH_MY_HARNESS_BOOTSTRAP_PYTHON must select Python 3.11 or newer 1>&2
    exit /b 1
  )
  set "OHM_PY=%OH_MY_HARNESS_BOOTSTRAP_PYTHON%"
  goto :run
)
for %%P in (python py python3) do (
  %%P -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
  if not errorlevel 1 (
    set "OHM_PY=%%P"
    goto :run
  )
)
echo error: Python 3.11 or newer not found; set OH_MY_HARNESS_BOOTSTRAP_PYTHON 1>&2
exit /b 1
:run
(
"%OHM_PY%" "%OMH_HOME%\bootstrap\omh_bootstrap.py" --home "%OMH_HOME%" %*
call exit /b %%ERRORLEVEL%%
)
'''.replace("\n", "\r\n")


def expected_launcher_content(*, home: Path, repo: Path) -> str:
    if os.name == "nt":
        return windows_launcher(home=home, repo=repo)
    return posix_launcher(home=home, repo=repo)


def write_launchers(*, home: Path, repo: Path, dry_run: bool) -> tuple[Path, Path]:
    write_bootstrap(home=home, repo=repo, dry_run=dry_run)
    paths = launcher_paths(home)
    content = expected_launcher_content(home=home, repo=repo)
    for path in paths:
        print(f"{'would write' if dry_run else 'write'} launcher: {path}")
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        require_ordinary_directory(path.parent, label="managed launcher root")
        temporary = path.parent / f".{path.name}.install-{uuid.uuid4().hex}"
        temporary.write_text(content, encoding="utf-8", newline="")
        if os.name != "nt":
            temporary.chmod(
                temporary.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )
        os.replace(temporary, path)
    return paths


def installed_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"managed checkout revision is unavailable: {repo}")
    return result.stdout.strip()


def validate_checkout_clean_and_remote(
    *,
    repo: Path,
    repository: str,
    context: str,
) -> None:
    status = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise SystemExit(f"managed checkout status is unavailable for {context}")
    if status.stdout.strip():
        raise SystemExit(
            f"managed checkout has uncommitted changes; refusing {context}"
        )

    actual_repository = repository_from_checkout(repo)
    if actual_repository != repository:
        raise SystemExit(
            "managed checkout remote does not match the recorded installation repository"
        )


def assert_checkout_snapshot(
    *,
    repo: Path,
    repository: str,
    revision: str,
    phase: str,
) -> None:
    current_revision = installed_revision(repo)
    if current_revision != revision:
        raise SystemExit(
            f"managed checkout revision changed {phase}; "
            f"expected {revision}, found {current_revision}"
        )
    validate_checkout_clean_and_remote(
        repo=repo,
        repository=repository,
        context=f"installation recovery {phase}",
    )


def validate_revision_fast_forward(
    *,
    repo: Path,
    repository: str,
    ref: str,
    previous_revision: str,
    current_revision: str,
) -> None:
    for label, revision in (
        ("recorded", previous_revision),
        ("current", current_revision),
    ):
        if len(revision) not in {40, 64} or any(
            character not in "0123456789abcdefABCDEF" for character in revision
        ):
            raise SystemExit(
                f"incomplete installation {label} revision is not a full Git object id"
            )

    validate_checkout_clean_and_remote(
        repo=repo,
        repository=repository,
        context="fast-forward resume",
    )

    remote_ref = f"refs/remotes/origin/{ref}"
    remote = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", remote_ref],
        capture_output=True,
        text=True,
    )
    remote_revision = remote.stdout.strip() if remote.returncode == 0 else ""
    if not remote_revision:
        raise SystemExit(
            f"managed checkout remote tracking ref is unavailable: {remote_ref}"
        )
    if remote_revision != current_revision:
        raise SystemExit(
            "managed checkout HEAD is not the published requested ref; "
            f"expected {remote_ref} at {current_revision}, found {remote_revision}"
        )

    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "merge-base",
            "--is-ancestor",
            previous_revision,
            current_revision,
        ],
        capture_output=True,
        text=True,
    )
    if ancestor.returncode == 1:
        raise SystemExit(
            "managed checkout revision did not fast-forward from the incomplete "
            "installation revision"
        )
    if ancestor.returncode != 0:
        raise SystemExit(
            "managed checkout ancestry is unavailable for fast-forward resume"
        )


def validate_incomplete_adoption(
    *,
    home: Path,
    repo: Path,
    repository: str,
    ref: str,
    harness: str,
    resume_fast_forward: bool = False,
) -> ValidatedRecovery | None:
    state_root = state_path(home)
    require_ordinary_directory(state_root, label="managed state root")
    require_ordinary_directory(repo, label="managed repository root")
    target = state_root / "install.json"
    if not path_exists_without_following(target, label="incomplete installation state"):
        return None
    if not is_ordinary_file(target, label="incomplete installation state"):
        raise SystemExit(f"incomplete installation state must be a regular file: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"incomplete installation state is unreadable: {target}: {exc}") from exc
    expected_keys = {
        "product",
        "status",
        "repository",
        "ref",
        "revision",
        "harness",
        "paths",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise SystemExit(f"incomplete installation state has an unsupported shape: {target}")
    current_revision = installed_revision(repo)
    expected_paths = {
        "home": str(home),
        "repo": str(repo),
        "venv": str(venv_path(home)),
        "python": str(venv_python(venv_path(home))),
        "launchers": [str(path) for path in launcher_paths(home)],
    }
    expected = {
        "product": PRODUCT_NAME,
        "status": "installing",
        "repository": repository,
        "ref": ref,
        "revision": current_revision,
        "harness": harness,
        "paths": expected_paths,
    }
    observed = dict(payload)
    try:
        registry = load_harness_registry()
        observed["harness"] = registry.resolve_id(payload["harness"])
        expected["harness"] = registry.resolve_id(harness)
    except (HarnessRegistryError, TypeError) as exc:
        raise SystemExit(f"incomplete installation harness is invalid: {target}: {exc}") from exc
    mismatched = sorted(key for key in expected if observed[key] != expected[key])
    if mismatched:
        if mismatched == ["revision"] and resume_fast_forward:
            previous_revision = payload["revision"]
            if not isinstance(previous_revision, str):
                raise SystemExit(
                    "incomplete installation recorded revision must be a string"
                )
            validate_revision_fast_forward(
                repo=repo,
                repository=repository,
                ref=ref,
                previous_revision=previous_revision,
                current_revision=current_revision,
            )
            print(
                "validated incomplete installation fast-forward: "
                f"{previous_revision[:12]} -> {current_revision[:12]}"
            )
        else:
            mismatched_fields = ", ".join(mismatched)
            raise SystemExit(
                "refusing to resume installation because install.json does not match "
                "the exact current request; mismatched fields: "
                f"{mismatched_fields}: {target}"
            )
    else:
        validate_checkout_clean_and_remote(
            repo=repo,
            repository=repository,
            context="incomplete installation recovery",
        )

    state_entries = set(state_root.iterdir())
    allowed_state_names = {
        "install.json",
        "manager.json",
        "desired.json",
        "harnesses",
        "operations",
        "manager.lock",
        "environment.json",
        "repair-backups",
    }
    unexpected_state = sorted(
        path for path in state_entries if path.name not in allowed_state_names
    )
    if unexpected_state:
        raise SystemExit(
            "refusing to resume installation with unexpected state entries: "
            + ", ".join(str(path) for path in unexpected_state)
        )
    expected_launchers = set(launcher_paths(home))
    launcher_root = bin_path(home)
    require_ordinary_directory(launcher_root, label="managed launcher root")
    launcher_entries = set(launcher_root.iterdir())
    if launcher_entries != expected_launchers:
        raise SystemExit(
            "refusing to resume installation with unexpected launcher entries: "
            + ", ".join(str(path) for path in sorted(launcher_entries))
        )
    expected_content = expected_launcher_content(home=home, repo=repo)
    for launcher in expected_launchers:
        if not is_ordinary_file(launcher, label="managed launcher"):
            raise SystemExit(f"managed launcher is not an ordinary file: {launcher}")
        if launcher.read_bytes() != expected_content.encode("utf-8"):
            raise SystemExit(f"managed launcher content changed after failed install: {launcher}")

    managed_venv = venv_path(home)
    if path_exists_without_following(managed_venv, label="managed venv"):
        require_ordinary_directory(managed_venv, label="managed venv")
    print(f"resume exact incomplete installation: {target}")
    return ValidatedRecovery(
        allowed_existing=frozenset(
            {venv_path(home), bin_path(home), state_path(home), home / "bootstrap"}
        ),
        revision=current_revision,
    )


def write_install_state(
    *,
    home: Path,
    repository: str,
    ref: str,
    repo: Path,
    harness: str,
    launchers: tuple[Path, Path],
    status: str,
    revision: str | None = None,
) -> None:
    state_root = state_path(home)
    state_root.mkdir(parents=True, exist_ok=True)
    require_ordinary_directory(state_root, label="managed state root")
    target = state_root / "install.json"
    payload = {
        "product": PRODUCT_NAME,
        "status": status,
        "repository": repository,
        "ref": ref,
        "revision": revision if revision is not None else installed_revision(repo),
        "harness": harness,
        "paths": {
            "home": str(home),
            "repo": str(repo),
            "venv": str(venv_path(home)),
            "python": str(venv_python(venv_path(home))),
            "launchers": [str(path) for path in launchers],
        },
    }
    temporary = state_root / f".{target.name}.install-{uuid.uuid4().hex}"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def invoke_refresh(
    *,
    home: Path,
    repo: Path,
    harness: str,
    codex_home: Path | None,
    assume_yes: bool,
    migrate_marketplace: bool,
    migrate_from_repo: Path | None,
) -> None:
    command = [
        str(bootstrap_python()),
        str(_bootstrap_script_path(home)),
        "--home",
        str(home),
        "install",
        harness,
    ]
    if codex_home is not None:
        command.extend(["--codex-home", str(codex_home)])
    if assume_yes:
        command.append("--yes")
    if migrate_marketplace:
        command.append("--migrate-marketplace")
    if migrate_from_repo is not None:
        command.extend(["--migrate-from-repo", str(migrate_from_repo)])
    run(command)


def _lifecycle_state(home: Path) -> tuple[dict, dict] | None:
    """Validate existing lifecycle state without initializing or rewriting it."""
    from manager_state import _validate_desired_payload, _validate_manager_payload
    from omh_bootstrap import _load_json, _recorded_source

    manager = _load_json(state_path(home) / "manager.json")
    desired = _load_json(state_path(home) / "desired.json")
    if manager is None and desired is None:
        return None
    if manager is None or desired is None:
        raise SystemExit("manager lifecycle state is incomplete; restore both manager.json and desired.json")
    _validate_manager_payload(manager, path=state_path(home) / "manager.json")
    _validate_desired_payload(desired, path=state_path(home) / "desired.json")
    _recorded_source(home)  # Require a full revision before any recovery mutation.
    return manager, desired


def _ready_install_state(home: Path, receipt: dict) -> tuple[dict, dict]:
    """Legacy ready receipts describe initialization, not the current revision."""
    from manager_state import derive_initial_state
    from omh_bootstrap import _load_json, _ordinary
    from plugin_package_identity import require_repository_identity

    state = _lifecycle_state(home)
    if state is not None:
        if state[0]["repository"] != receipt["repository"]:
            raise SystemExit("manager and installation receipt repositories disagree")
        return state
    _ordinary(state_path(home) / "operations", directory=True)
    if _load_json(state_path(home) / "operations/current.json") is not None:
        raise SystemExit("legacy installation has an interrupted operation; restore lifecycle state first")
    repo = repo_path(home)
    require_ordinary_directory(repo, label="legacy managed repository")
    require_ordinary_directory(repo / ".git", label="legacy managed Git directory")
    validate_checkout_clean_and_remote(repo=repo, repository=receipt["repository"], context="legacy migration")
    revision = installed_revision(repo)
    identity = require_repository_identity(repo)
    return derive_initial_state(
        home, repository=receipt["repository"], revision=revision,
        release_version=str(identity["releaseVersion"]), bundle_identity=str(identity["bundleIdentity"]),
        persist=False, canonicalize=False,
    )


def _interactive_stdin() -> bool:
    if not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    # Windows CRT isatty() also accepts NUL. Only a real console can answer
    # recovery prompts; redirected input must retain the explicit-choice gate.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(sys.stdin.fileno()))
        mode = wintypes.DWORD()
        return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
    except (OSError, ValueError):
        return False


def _recovery_mode(args: argparse.Namespace) -> str:
    if args.repair:
        return "repair"
    if args.reinstall:
        return "reinstall"
    if not _interactive_stdin():
        raise SystemExit("installation already exists; choose --repair or --reinstall explicitly (--yes does not choose)")
    print("Existing installation: [1] Repair  [2] Reinstall managed components  [Enter] Cancel")
    try:
        choice = input("Choice [Cancel]: ").strip().lower()
    except EOFError:
        choice = ""
    if choice in {"1", "repair"}:
        return "repair"
    if choice in {"2", "reinstall"}:
        return "reinstall"
    if choice not in {"", "cancel", "3"}:
        raise SystemExit("unknown recovery choice; installation unchanged")
    print("installation cancelled; no changes made")
    return "cancel"


def _validate_recovery_paths(home: Path) -> None:
    from omh_bootstrap import _ordinary

    for path in (repo_path(home), repo_path(home) / ".git", venv_path(home),
                 bin_path(home), home / "bootstrap", state_path(home) / "repair-backups",
                 state_path(home) / "operations", state_path(home) / "harnesses"):
        _ordinary(path, directory=True)
    for path in (*launcher_paths(home), _bootstrap_script_path(home)):
        _ordinary(path)


def resume_managed_install(args: argparse.Namespace, home: Path) -> bool:
    """Route ready installs to explicit lifecycle recovery; keep incomplete recovery exact."""
    receipt_path = state_path(home) / "install.json"
    if path_exists_without_following(state_path(home)):
        require_ordinary_directory(state_path(home), label="managed state root")
    if not path_exists_without_following(receipt_path):
        if args.repair or args.reinstall:
            raise SystemExit("--repair/--reinstall requires an existing owned installation receipt")
        return False
    if path_exists_without_following(repo_path(home)):
        require_ordinary_directory(repo_path(home), label="managed repository root")
    if not is_ordinary_file(receipt_path):
        raise SystemExit(f"installation receipt must be an ordinary file: {receipt_path}")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"installation receipt is unreadable; preserved: {receipt_path}: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("product") != PRODUCT_NAME:
        raise SystemExit("refusing to repair an installation belonging to another product")
    if receipt.get("status") not in {"installing", "ready"}:
        raise SystemExit("unsupported installation state; no state was reset")
    if receipt["status"] == "installing":
        if args.repair or args.reinstall:
            raise SystemExit("incomplete installation: repeat the exact original request; --repair/--reinstall requires ready state")
        _lifecycle_state(home)
        from omh_bootstrap import _load_json, _ordinary
        _ordinary(state_path(home) / "operations", directory=True)
        if _load_json(state_path(home) / "operations/current.json") is not None:
            raise SystemExit("incomplete installation has an active operation; run omh recover first")
        return False
    if args.adopt_current_checkout or args.resume_fast_forward:
        raise SystemExit("adoption/fast-forward resume requires an incomplete installation, not ready state")
    repository = receipt.get("repository")
    ref = receipt.get("ref")
    initial_harness = receipt.get("harness")
    if not all(isinstance(value, str) and value.strip() for value in (repository, ref, initial_harness)):
        raise SystemExit("installation receipt is missing its source or initial harness")
    if args.repository and args.repository != repository:
        raise SystemExit("existing installation uses another repository; repair will not change its source")
    explicit_ref = any(arg == "--ref" or arg.startswith("--ref=") for arg in sys.argv[1:])
    explicit_harness = any(arg == "--harness" or arg.startswith("--harness=") for arg in sys.argv[1:])
    _validate_recovery_paths(home)
    state = _ready_install_state(home, receipt)
    manager, desired = state
    if explicit_ref and args.ref != manager.get("requestedRef", ref):
        raise SystemExit("use omh update to change an existing installation's ref")
    from manager_state import desired_harnesses

    if explicit_harness and args.harness not in desired_harnesses(desired):
        raise SystemExit("recovery preserves the installed harness set; use omh install to add a harness")
    expected_paths = {
        "home": str(home), "repo": str(repo_path(home)), "venv": str(venv_path(home)),
        "python": str(venv_python(venv_path(home))),
        "launchers": [str(path) for path in launcher_paths(home)],
    }
    if receipt.get("paths") != expected_paths:
        raise SystemExit("installation receipt does not prove ownership of this manager home's paths")
    mode = _recovery_mode(args)
    if mode == "cancel":
        return True
    print(f"{mode} existing installation: {home}")
    from contextlib import nullcontext
    from manager_state import atomic_write_json
    from omh_bootstrap import _load_json, _mutation_lock, _ordinary, _repair_checkout

    runtime_backup = None
    with nullcontext() if args.dry_run else _mutation_lock(home):
        # Revalidate under the common lifecycle lock before the first write.
        if _load_json(receipt_path) != receipt:
            raise SystemExit("installation receipt changed during recovery selection; retry")
        _validate_recovery_paths(home)
        current = _ready_install_state(home, receipt)
        # Legacy derivation includes a fresh timestamp; compare the owned fields.
        for previous, latest in zip(state, current):
            if ({k: v for k, v in previous.items() if k != "updatedAt"}
                    != {k: v for k, v in latest.items() if k != "updatedAt"}):
                raise SystemExit("installation state changed during recovery selection; retry")
        legacy = _lifecycle_state(home) is None
        if legacy:
            print(f"{'would migrate' if args.dry_run else 'migrate'} legacy state at current managed revision {manager['revision']}")
            if not args.dry_run:
                atomic_write_json(state_path(home) / "manager.json", manager)
                atomic_write_json(state_path(home) / "desired.json", desired)
        if not legacy or not args.dry_run:
            _repair_checkout(home, force=mode == "reinstall", dry_run=True)
        if args.dry_run:
            print(f"would {'reclone the exact recorded revision and rebuild tooling' if mode == 'reinstall' else 'repair the recorded checkout and tooling'}; repair and check installed harnesses")
            if not args.no_path:
                ensure_user_path(home, dry_run=True)
            print("dry-run only; no installation state written")
            return True
        # Keep these immutable across repair by older manager revisions too.
        receipt_bytes = receipt_path.read_bytes()
        # Journaled rollback owns any desired-state transition. Do not undo it.
        desired_path = state_path(home) / "desired.json"
        desired_bytes = (
            desired_path.read_bytes()
            if _load_json(state_path(home) / "operations/current.json") is None else None
        )
        write_launchers(home=home, repo=SOURCE_ROOT, dry_run=args.dry_run)
        if mode == "reinstall" and venv_path(home).exists():
            backups = state_path(home) / "repair-backups"
            _ordinary(backups, directory=True)
            backups.mkdir(parents=True, exist_ok=True)
            runtime_backup = backups / f"venv-{uuid.uuid4().hex}"
            venv_path(home).rename(runtime_backup)
            print(f"previous tooling venv preserved: {runtime_backup}")
    command = [str(bootstrap_python()), str(_bootstrap_script_path(home)), "--home", str(home), "repair"]
    if mode == "reinstall":
        command.extend(["--reclone", "--rebuild"])
    if args.no_path:
        command.append("--no-path")
    if args.codex_home:
        command.extend(["--codex-home", args.codex_home])
    if args.migrate_marketplace:
        command.append("--migrate-marketplace")
    if args.migrate_from_repo:
        command.extend(["--migrate-from-repo", args.migrate_from_repo])
    try:
        run(command)
    finally:
        # Legacy repair rewrote these files. Restore the immutable receipt and
        # desired policy, even when harness closure fails, using the same lock.
        with _mutation_lock(home):
            for path, original in ((receipt_path, receipt_bytes), (desired_path, desired_bytes)):
                if original is None:
                    continue
                _ordinary(path)
                if path.read_bytes() != original:
                    current_payload = _load_json(path)
                    if path == desired_path:
                        original_fields = {k: v for k, v in desired.items() if k != "updatedAt"}
                        legacy_fields = {
                            "schemaVersion": desired["schemaVersion"],
                            "harnesses": desired["harnesses"],
                            "updatePolicy": {"channel": desired["updatePolicy"]["channel"]},
                        }
                        current_fields = {k: v for k, v in current_payload.items() if k != "updatedAt"}
                        from manager_state import _validate_desired_payload

                        try:
                            _validate_desired_payload(current_payload, path=path)
                        except SystemExit as exc:
                            raise SystemExit(f"recovery desired state is invalid; preserved: {exc}") from exc
                        # Permit only identity-equivalent alias convergence by a
                        # newer child. Preserve policy extras and original bytes
                        # when an older child keeps the old spelling.
                        canonical = list(desired_harnesses(desired))
                        original_fields["harnesses"] = canonical
                        legacy_fields["harnesses"] = canonical
                        current_fields["harnesses"] = list(desired_harnesses(current_payload))
                        if current_fields != original_fields and current_fields != legacy_fields:
                            raise SystemExit("recovery unexpectedly changed desired state; preserved for inspection")
                        if current_payload["harnesses"] != desired["harnesses"]:
                            preserved = json.loads(original)
                            preserved["harnesses"] = current_payload["harnesses"]
                            original = (json.dumps(preserved, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
                    else:
                        # Only the known legacy writer's revision/path rewrite is
                        # reversible here. Never hide corrupt or foreign state.
                        original_fields = {k: v for k, v in receipt.items() if k not in {"revision", "paths"}}
                        current_fields = {k: v for k, v in current_payload.items() if k not in {"revision", "paths"}}
                        if current_fields != original_fields:
                            raise SystemExit("recovery unexpectedly changed the initial receipt; preserved for inspection")
                    temporary = path.with_name(f".{path.name}.preserve-{uuid.uuid4().hex}")
                    try:
                        temporary.write_bytes(original)
                        os.replace(temporary, path)
                    finally:
                        temporary.unlink(missing_ok=True)
            if runtime_backup is not None and not path_exists_without_following(venv_path(home)):
                runtime_backup.rename(venv_path(home))
                print("restored previous tooling venv after failed reinstall")
    print(f"installation {mode} completed: {home}")
    return True


def checkout_harness_name(repo: Path, harness: str) -> str:
    """Use the actual installed ref's canonical ID, including pre-alias releases."""
    path = repo / ".agents/harnesses/registry.json"
    if not is_ordinary_file(path):
        raise SystemExit(f"installed harness registry must be an ordinary file: {path}")
    try:
        target = json.loads(path.read_text(encoding="utf-8"))["harnesses"]
        if not isinstance(target, dict):
            raise ValueError("harnesses must be an object")
        return load_harness_registry().id_for_target(harness, target)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"installed harness selection is invalid: {exc}") from exc


def main() -> None:
    registry = load_harness_registry()

    def harness_name(value: str) -> str:
        try:
            return registry.resolve_id(value)
        except HarnessRegistryError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc

    parser = argparse.ArgumentParser(
        description=(
            "Set up the oh-my-harness manager, or explicitly repair/reinstall an existing "
            "installation. First-time setup installs skills and instructions for one client; "
            "install the client app separately."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            registry.selection_help() + "\n\n"
            "Examples (use .\\install.ps1 on Windows):\n"
            "  ./install.sh --harness copilot --dry-run\n"
            "  ./install.sh --harness copilot --yes\n\n"
            "  ./install.sh --repair --dry-run\n"
            "  ./install.sh --reinstall\n\n"
            "After setup, reopen your terminal to use the registered PATH, then run:\n"
            "  omh install claude        Add another harness\n"
            "  omh status                Show installed harnesses\n"
            "  omh --help                See the everyday commands\n"
            "Already installed? Use omh install to add harnesses, or omh repair to repair.\n"
            "Existing installs require --repair or --reinstall (interactive default: Cancel)."
        ),
    )
    parser.add_argument(
        "--home",
        help="Manager home (default: OH_MY_HARNESS_HOME or ~/.oh-my-harness).",
    )
    parser.add_argument(
        "--repository",
        help="Git repository source. Defaults to this checkout's remote.origin.url.",
    )
    parser.add_argument("--ref", default=DEFAULT_REF, help="Git branch or tag to install (default: main).")
    parser.add_argument(
        "--harness", default=registry.default_harness, type=harness_name,
        help=f"Initial harness name or alias (default: {registry.default_harness}).",
    )
    parser.add_argument("--codex-home", help="Explicit Codex harness home.")
    parser.add_argument(
        "--yes", action="store_true",
        help="Confirm creation and managed cleanup; replacing existing instructions still requires a live prompt.",
    )
    parser.add_argument(
        "--migrate-marketplace", action="store_true",
        help="Codex only: migrate the retired marketplace after confirming its exact cleanup plan.",
    )
    parser.add_argument(
        "--migrate-from-repo",
        help=(
            "Former checkout root used only to migrate its exact managed Codex "
            "AGENTS.md symlink."
        ),
    )
    parser.add_argument(
        "--adopt-current-checkout",
        action="store_true",
        help=(
            "Explicitly initialize manager-owned state after the current checkout "
            "has been moved to <home>/repo; exact interrupted installs auto-resume "
            "from the managed repo even when invoked from another checkout."
        ),
    )
    parser.add_argument(
        "--resume-fast-forward",
        action="store_true",
        help=(
            "Explicitly resume an incomplete installation after its clean managed "
            "checkout fast-forwards to the published requested ref."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview setup or repair without writing installation files; does not validate harness contents.",
    )
    recovery_mode = parser.add_mutually_exclusive_group()
    recovery_mode.add_argument("--repair", action="store_true", help="Repair an owned ready installation at its recorded version.")
    recovery_mode.add_argument("--reinstall", action="store_true", help="Reclone the recorded version and rebuild tooling; preserve state and user data.")
    parser.add_argument("--no-path", action="store_true", help="Skip current-user PATH registration.")
    args = parser.parse_args()
    if (args.repair or args.reinstall) and (args.adopt_current_checkout or args.resume_fast_forward):
        parser.error("--repair/--reinstall cannot be combined with adoption/fast-forward resume")

    _require_supported_python()
    try:
        home = resolve_owned_leaf(manager_home(args.home))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    validate_manager_home(home)
    if resume_managed_install(args, home):
        return
    repository = args.repository or repository_from_checkout()
    if not repository.strip():
        raise SystemExit("repository source must not be empty")
    if not args.ref.strip():
        raise SystemExit("Git ref must not be empty")
    if not args.harness.strip():
        raise SystemExit("harness must not be empty")
    migrate_from_repo: Path | None = None
    if args.migrate_from_repo:
        migrate_from_repo = expand_path(args.migrate_from_repo)
        if not migrate_from_repo.is_absolute():
            raise SystemExit(
                "--migrate-from-repo must be an absolute path: "
                f"{args.migrate_from_repo!r}"
            )
        migrate_from_repo = Path(os.path.abspath(migrate_from_repo))

    source_root = SOURCE_ROOT.resolve(strict=True)
    expected_repo = repo_path(home)
    state_root = state_path(home)
    if path_exists_without_following(state_root, label="managed state root"):
        require_ordinary_directory(state_root, label="managed state root")
    install_state = state_root / "install.json"
    resume_incomplete_install = path_exists_without_following(
        install_state,
        label="incomplete installation state",
    )
    if args.resume_fast_forward and not resume_incomplete_install:
        raise SystemExit(
            "--resume-fast-forward requires an incomplete installation state"
        )
    if args.adopt_current_checkout:
        require_ordinary_directory(expected_repo, label="managed repository root")
        try:
            resolved_expected_repo = expected_repo.resolve(strict=True)
        except OSError as exc:
            raise SystemExit(
                f"managed repository root cannot be resolved: {expected_repo}: {exc}"
            ) from exc
        if source_root != resolved_expected_repo:
            raise SystemExit(
                "--adopt-current-checkout requires this checkout to be located at "
                f"{expected_repo}; found {source_root}"
            )
    adopted_repo = (
        expected_repo
        if resume_incomplete_install
        else SOURCE_ROOT if args.adopt_current_checkout else None
    )
    recovery = (
        validate_incomplete_adoption(
            home=home,
            repo=adopted_repo,
            repository=repository,
            ref=args.ref,
            harness=args.harness,
            resume_fast_forward=args.resume_fast_forward,
        )
        if adopted_repo is not None and resume_incomplete_install
        else None
    )
    if resume_incomplete_install and recovery is None:
        raise SystemExit("incomplete installation state disappeared during validation")
    allowed_existing = recovery.allowed_existing if recovery is not None else frozenset()
    validate_install_root(
        home,
        adopted_repo=adopted_repo,
        allowed_existing=allowed_existing,
    )
    if adopted_repo is None:
        repo = clone_repository(
            repository,
            ref=args.ref,
            home=home,
            dry_run=args.dry_run,
        )
    else:
        repo = adopted_repo
        action = "resume" if resume_incomplete_install else "adopt"
        print(f"{action} managed checkout: {repo}")
    if not args.dry_run:
        args.harness = checkout_harness_name(repo, args.harness)
    launchers = write_launchers(home=home, repo=repo, dry_run=args.dry_run)
    if args.dry_run:
        print("dry-run only; no installation state written")
        return

    validated_revision = recovery.revision if recovery is not None else None
    write_install_state(
        home=home,
        repository=repository,
        ref=args.ref,
        repo=repo,
        harness=args.harness,
        launchers=launchers,
        status="installing",
        revision=validated_revision,
    )
    if not args.no_path:
        ensure_user_path(home)
    if validated_revision is not None:
        assert_checkout_snapshot(
            repo=repo,
            repository=repository,
            revision=validated_revision,
            phase="before refresh",
        )
    invoke_refresh(
        home=home,
        repo=repo,
        harness=args.harness,
        codex_home=(Path(args.codex_home).expanduser() if args.codex_home else None),
        assume_yes=args.yes,
        migrate_marketplace=args.migrate_marketplace,
        migrate_from_repo=migrate_from_repo,
    )
    if validated_revision is not None:
        assert_checkout_snapshot(
            repo=repo,
            repository=repository,
            revision=validated_revision,
            phase="after refresh",
        )
    write_install_state(
        home=home,
        repository=repository,
        ref=args.ref,
        repo=repo,
        harness=args.harness,
        launchers=launchers,
        status="ready",
        revision=validated_revision,
    )
    print(f"installation complete: {home}")
    if args.no_path:
        print(f"PATH registration skipped; launcher: {launchers[1]}")
    else:
        print(f"open a new terminal and run `{launcher_help_invocation(os.name)}`")


def cli() -> int:
    try:
        main()
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        write_stderr(f"error: {exc.code}")
        return 1
    except subprocess.CalledProcessError as exc:
        command = (
            command_text([str(part) for part in exc.cmd])
            if isinstance(exc.cmd, (list, tuple))
            else str(exc.cmd)
        )
        write_stderr(
            f"error: command failed with exit code {exc.returncode}: {command}"
        )
        return exc.returncode if exc.returncode > 0 else 1
    except OSError as exc:
        write_stderr(f"error: installation filesystem or process failure: {exc}")
        return 1
    except Exception as exc:
        write_stderr(
            f"error: unexpected installer failure ({type(exc).__name__}): {exc}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
