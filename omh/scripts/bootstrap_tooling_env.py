#!/usr/bin/env python3
"""Bootstrap the shared oh-my-harness tooling Python environment."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from manager_paths import manager_home, venv_path, venv_python


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANAGER_HOME = manager_home()
DEFAULT_VENV = venv_path(DEFAULT_MANAGER_HOME)
DEFAULT_REQUIREMENTS = REPO_ROOT / "requirements.txt"
MINIMUM_PYTHON_VERSION = (3, 11)


def require_supported_python() -> None:
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


def run(command: list[str], *, dry_run: bool = False) -> None:
    print("+ " + " ".join(command), flush=True)
    if dry_run:
        return
    subprocess.run(command, check=True)


def canonical_base_python() -> Path:
    """Return the real base interpreter, not a PATH or venv symlink."""
    raw = getattr(sys, "_base_executable", None) or sys.executable
    try:
        resolved = Path(raw).expanduser().resolve(strict=True)
    except OSError as exc:
        raise SystemExit(f"bootstrap Python cannot be resolved: {raw}: {exc}") from exc
    if not resolved.is_file():
        raise SystemExit(f"bootstrap Python is not a file: {resolved}")
    return resolved


def configured_base_python(venv_path: Path) -> Path | None:
    config = venv_path / "pyvenv.cfg"
    if not config.is_file():
        return None
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key.strip() == "executable" and value.strip():
            return Path(value.strip()).expanduser().resolve(strict=False)
    return None


def venv_health(venv_path: Path, *, base_python: Path) -> tuple[bool, str]:
    python = venv_python(venv_path)
    if not python.is_file():
        return False, f"venv Python missing: {python}"

    configured_base = configured_base_python(venv_path)
    if configured_base is None:
        return False, f"venv base interpreter missing from {venv_path / 'pyvenv.cfg'}"
    if configured_base != base_python:
        return False, f"venv base interpreter changed: configured {configured_base}, selected {base_python}"

    try:
        result = subprocess.run(
            [str(python), "-c", "import encodings, pip, sys; print(sys.prefix)"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return False, f"venv Python cannot start: {python}: {exc}"
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        detail = next(
            (line.strip() for line in output.splitlines() if "Error" in line or "error" in line),
            output.splitlines()[-1].strip() if output else "no error output",
        )
        return False, f"venv Python exited with {result.returncode}: {detail}"

    reported_prefix = result.stdout.strip()
    try:
        prefix = Path(reported_prefix).expanduser().resolve(strict=True)
        expected_prefix = venv_path.resolve(strict=True)
    except OSError as exc:
        return False, f"venv prefix cannot be resolved: {reported_prefix or '<empty>'}: {exc}"
    if prefix != expected_prefix:
        return False, f"venv Python reports the wrong prefix: expected {expected_prefix}, found {prefix}"
    return True, f"venv Python is healthy: {python}"


def create_venv(base_python: Path, venv_path: Path, *, dry_run: bool) -> None:
    run([str(base_python), "-m", "venv", str(venv_path)], dry_run=dry_run)


def refresh_dependencies(python: Path, requirements: Path, *, dry_run: bool) -> None:
    run([str(python), "-m", "pip", "--disable-pip-version-check", "install", "-r", str(requirements)], dry_run=dry_run)
    run(
        [
            str(python),
            "-c",
            "import jsonschema, yaml; from importlib.metadata import version; "
            "print('PyYAML', yaml.__version__); "
            "print('jsonschema', version('jsonschema'))",
        ],
        dry_run=dry_run,
    )


def remove_venv_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise OSError(f"refusing to remove non-directory venv path: {path}")
    shutil.rmtree(path)


def rollback_rebuild(venv_path: Path, backup_path: Path | None) -> None:
    if venv_path.exists() or venv_path.is_symlink():
        remove_venv_directory(venv_path)
    if backup_path is not None:
        backup_path.rename(venv_path)
        print(f"restored previous tooling venv after bootstrap failure: {venv_path}", flush=True)


def _dependencies_ready(venv_path: Path, requirements: Path) -> bool:
    receipt = venv_path / ".omh-requirements.txt"
    try:
        if receipt.is_symlink() or receipt.read_text(encoding="utf-8") != requirements.read_text(encoding="utf-8"):
            return False
        result = subprocess.run(
            [str(venv_python(venv_path)), "-c", "import jsonschema, yaml"],
            capture_output=True,
        )
        return result.returncode == 0
    except (OSError, UnicodeError):
        return False


def _record_requirements(venv_path: Path, requirements: Path) -> None:
    target = venv_path / ".omh-requirements.txt"
    temporary = venv_path / f".omh-requirements-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(requirements.read_text(encoding="utf-8"), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def bootstrap_tooling_env(
    venv_path: Path, requirements: Path, *, dry_run: bool, rebuild: bool = False
) -> None:
    require_supported_python()
    base_python = canonical_base_python()
    print(f"Bootstrap base Python: {base_python}")

    path_exists = venv_path.exists() or venv_path.is_symlink()
    if path_exists and (venv_path.is_symlink() or not venv_path.is_dir()):
        raise SystemExit(f"refusing to replace non-directory venv path: {venv_path}")

    healthy, health_detail = venv_health(venv_path, base_python=base_python)
    if healthy and not rebuild:
        print(health_detail)
        if _dependencies_ready(venv_path, requirements):
            print("tooling dependencies are ready; no pip installation required")
            return
        refresh_dependencies(venv_python(venv_path), requirements, dry_run=dry_run)
        if not dry_run:
            _record_requirements(venv_path, requirements)
        return

    print(f"Tooling venv rebuild required: {health_detail}")
    backup_path: Path | None = None
    if path_exists:
        backup_path = venv_path.with_name(f".{venv_path.name}.backup-{uuid.uuid4().hex}")
        if dry_run:
            print(f"Would move unhealthy tooling venv to backup: {venv_path} -> {backup_path}")
        else:
            venv_path.rename(backup_path)

    if dry_run:
        create_venv(base_python, venv_path, dry_run=True)
        refresh_dependencies(venv_python(venv_path), requirements, dry_run=True)
        print("dry-run only; no tooling venv changes written")
        return

    venv_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        create_venv(base_python, venv_path, dry_run=False)
        created_healthy, created_detail = venv_health(venv_path, base_python=base_python)
        if not created_healthy:
            raise RuntimeError(f"new tooling venv is unhealthy: {created_detail}")
        refresh_dependencies(venv_python(venv_path), requirements, dry_run=False)
        _record_requirements(venv_path, requirements)
    except BaseException as bootstrap_error:
        try:
            rollback_rebuild(venv_path, backup_path)
        except OSError as rollback_error:
            backup = str(backup_path) if backup_path is not None else "<none>"
            raise RuntimeError(
                f"tooling venv bootstrap failed and rollback failed: {rollback_error}; "
                f"preserved backup: {backup}"
            ) from bootstrap_error
        raise

    if backup_path is not None:
        remove_venv_directory(backup_path)
    print(f"oh-my-harness tooling Python: {venv_python(venv_path)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or refresh the shared oh-my-harness tooling venv.")
    parser.add_argument(
        "--venv",
        default=str(DEFAULT_VENV),
        help="Target venv path. Defaults to ${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}/venv.",
    )
    parser.add_argument(
        "--requirements",
        default=str(DEFAULT_REQUIREMENTS),
        help="Requirements file for oh-my-harness tooling dependencies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and print the bootstrap plan without writing.",
    )
    parser.add_argument("--rebuild", action="store_true", help="Rebuild even a healthy tooling venv.")
    args = parser.parse_args()

    venv_path = Path(args.venv).expanduser()
    requirements = Path(args.requirements).expanduser()
    if not requirements.is_file():
        raise SystemExit(f"requirements file does not exist: {requirements}")

    bootstrap_tooling_env(venv_path, requirements, dry_run=args.dry_run, rebuild=args.rebuild)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except (OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
