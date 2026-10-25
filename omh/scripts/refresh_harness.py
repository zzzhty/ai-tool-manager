#!/usr/bin/env python3
"""Refresh one registry-selected oh-my-harness distribution."""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from check_skill_discovery import (
    PluginListRow,
    codex_plugin_rows,
    enabled_plugin_names,
    excluded_skill_root_issues,
    marketplace_plugin_names,
    marketplace_plugin_sources,
    plugin_cache_harness_issues,
    plugin_installation_issues,
    plugin_manifest_identity,
    plugin_package_issues,
    require_harness_closure,
)
from harness_registry import (
    REGISTRY_FILE,
    HarnessPlan,
    HarnessRegistryError,
    ensure_codex_harness_covers_catalog,
    load_harness_registry,
    resolve_harness_plan,
)
from plugin_package_identity import plugin_cache_identity_issues
from manager_paths import (
    MANAGER_PYTHON_ENV,
    MANAGER_ROOT_ENV,
    MANAGER_TOOLING_PYTHON_ENV,
    manager_home as resolve_manager_home,
    venv_path as manager_venv_path,
    venv_python,
)
from manager_state import load_current_operation
from repo_skill_catalog import SkillCatalog, load_repo_skill_catalog
from sync_agents_skills import sync_layer
from sync_harness_instructions import apply_instruction_sync, prepare_instruction_sync
from terminal_output import emphasize, write_stderr


REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_FILE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
INSTALL_MANIFEST_FILE = REPO_ROOT / ".agents" / "plugins" / "install-manifest.json"
REPOSITORY_PLUGIN_VALIDATOR = REPO_ROOT / "scripts" / "validate_plugin.py"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
MANAGER_HOME = resolve_manager_home()
MACOS_APPLICATION_DIRS = (Path("/Applications"), Path.home() / "Applications")


@dataclass(frozen=True)
class MarketplaceSourceBinding:
    source_type: str
    source: str
    revision: str | None = None


@dataclass(frozen=True)
class CodexPrunePlan:
    configured: frozenset[str]
    cached: frozenset[str]

    @property
    def names(self) -> frozenset[str]:
        return self.configured | self.cached


@dataclass(frozen=True)
class RetiredMarketplaceState:
    name: str
    configured_plugins: frozenset[str]
    cached_plugins: frozenset[str]
    source_config: tuple[tuple[str, str], ...]

    @property
    def present(self) -> bool:
        return bool(
            self.configured_plugins
            or self.cached_plugins
            or self.source_config
        )


def operation_instruction_digests(
    home: Path,
    operation_id: str | None,
) -> tuple[str, ...]:
    """Resolve copy ownership only from the active, revision-matched update journal."""

    if operation_id is None:
        return ()
    operation = load_current_operation(home)
    if operation is None or operation.get("operationId") != operation_id:
        raise SystemExit("instruction migration operation journal does not match refresh")
    if operation.get("command") != "update":
        raise SystemExit("instruction migration provenance requires an update operation")
    current_revision = git_head_revision(REPO_ROOT)
    revisions: set[str] = set()
    digests: set[str] = set()
    for side_name in ("before", "target"):
        side = operation.get(side_name)
        if not isinstance(side, dict):
            raise SystemExit(
                f"update operation journal has no valid {side_name} instruction provenance"
            )
        revision = side.get("revision")
        if isinstance(revision, str):
            revisions.add(revision)
        source = side.get("instructionsSource")
        if not isinstance(source, dict):
            raise SystemExit(
                f"update operation journal has no {side_name} instruction source"
            )
        # Blob digests remain immutable migration identities for older managers;
        # copies must match the exact checkout bytes, never EOL-normalized bytes.
        digest = side.get("instructionsMaterializedSha256", source.get("sha256"))
        if not isinstance(digest, str):
            raise SystemExit(
                f"update operation journal has no {side_name} instruction digest"
            )
        digests.add(digest)
    if current_revision not in revisions:
        raise SystemExit(
            "managed checkout does not match either journaled instruction revision"
        )
    return tuple(sorted(digests))


def expand_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(str(raw))).expanduser()


def command_text(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def latest_files(root: Path, pattern: str) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.rglob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)


def macos_app_codex_candidates() -> list[str]:
    if sys.platform != "darwin":
        return []
    candidates = [
        candidate
        for root in MACOS_APPLICATION_DIRS
        if root.is_dir()
        for candidate in root.glob("*.app/Contents/Resources/codex")
        if candidate.is_file()
    ]
    return [str(path) for path in sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)]


def codex_extension_platform_dir() -> str | None:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        architecture = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        architecture = "aarch64"
    else:
        return None

    if sys.platform == "win32":
        system = "windows"
    elif sys.platform == "darwin":
        system = "macos"
    elif sys.platform.startswith("linux"):
        system = "linux"
    else:
        return None
    return f"{system}-{architecture}"


def codex_extension_candidates(user_home: Path) -> list[str]:
    platform_dir = codex_extension_platform_dir()
    if platform_dir is None:
        return []

    if sys.platform == "win32":
        extension_roots = [
            user_home / ".vscode" / "extensions",
            user_home / ".vscode-insiders" / "extensions",
        ]
        executable_name = "codex.exe"
    else:
        extension_roots = [
            user_home / ".vscode-server" / "extensions",
            user_home / ".vscode-server-insiders" / "extensions",
            user_home / ".vscode" / "extensions",
            user_home / ".vscode-insiders" / "extensions",
        ]
        executable_name = "codex"

    candidates: list[Path] = []
    for extension_root in extension_roots:
        if not extension_root.is_dir():
            continue
        for extension in extension_root.glob("openai.chatgpt-*"):
            candidate = extension / "bin" / platform_dir / executable_name
            if candidate.is_file():
                candidates.append(candidate)
    return [str(path) for path in sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)]


def codex_fallback_candidates(codex_home: Path) -> list[str]:
    is_windows = sys.platform == "win32"
    executable_name = "codex.exe" if is_windows else "codex"

    if is_windows:
        user_home = expand_path(os.environ.get("USERPROFILE") or Path.home())
        local_app_data = os.environ.get("LOCALAPPDATA")
        default_install_dir = (
            expand_path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin"
            if local_app_data
            else None
        )
    else:
        user_home = expand_path(os.environ.get("HOME") or Path.home())
        local_app_data = None
        default_install_dir = user_home / ".local" / "bin"

    install_dir_raw = os.environ.get("CODEX_INSTALL_DIR")
    install_dir = expand_path(install_dir_raw) if install_dir_raw else default_install_dir

    candidates: list[str] = []
    if install_dir is not None:
        candidates.append(str(install_dir / executable_name))

    standalone_current = codex_home / "packages" / "standalone" / "current"
    candidates.extend(
        [
            str(standalone_current / "bin" / executable_name),
            str(standalone_current / executable_name),
        ]
    )

    if local_app_data:
        desktop_bin_root = expand_path(local_app_data) / "OpenAI" / "Codex" / "bin"
        candidates.extend(str(path) for path in latest_files(desktop_bin_root, executable_name))

    candidates.extend(macos_app_codex_candidates())
    candidates.extend(codex_extension_candidates(user_home))
    return list(dict.fromkeys(candidates))


def resolve_first_executable(candidates: list[str]) -> str:
    checked: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        expanded = os.path.expandvars(os.path.expanduser(candidate))
        checked.append(candidate)
        if any(separator in expanded for separator in (os.sep, os.altsep) if separator):
            path = Path(expanded)
            if path.is_file():
                return str(path)
            continue
        resolved = shutil.which(expanded)
        if resolved is not None:
            return resolved
    raise SystemExit("executable not found. Checked:\n" + "\n".join(checked))


def resolve_executable(raw: str) -> str:
    return resolve_first_executable([raw])


def codex_executable_is_startable(candidate: str) -> bool:
    try:
        subprocess.run(
            [candidate, "--version"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def resolve_codex_executable(raw: str | None, *, codex_home: Path) -> str:
    if raw is not None:
        return resolve_executable(raw)

    configured = os.environ.get("CODEX_BIN")
    if configured:
        return resolve_executable(configured)

    path_codex = shutil.which("codex")
    if path_codex is not None and (
        sys.platform != "win32" or codex_executable_is_startable(path_codex)
    ):
        return path_codex

    fallbacks = codex_fallback_candidates(codex_home)
    if sys.platform == "win32":
        for candidate in fallbacks:
            try:
                resolved = resolve_first_executable([candidate])
            except SystemExit:
                continue
            if codex_executable_is_startable(resolved):
                return resolved
        raise SystemExit(
            "startable executable not found. Checked:\n"
            "codex on PATH\n"
            + "\n".join(fallbacks)
        )
    try:
        return resolve_first_executable(fallbacks)
    except SystemExit:
        raise SystemExit(
            "executable not found. Checked:\n"
            "codex on PATH\n"
            + "\n".join(fallbacks)
        ) from None


def marketplace_source_arg(raw: str) -> str:
    if "://" in raw or raw.startswith("git@"):
        return raw
    expanded = os.path.expandvars(os.path.expanduser(raw))
    path_like = (
        raw.startswith((".", "~", "/", "\\"))
        or (len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"})
        or Path(expanded).exists()
    )
    if path_like:
        return str(Path(expanded))
    return raw


def run(command: list[str], *, env: dict[str, str], dry_run: bool, check: bool = True) -> int:
    print("+ " + command_text(command), flush=True)
    if dry_run:
        return 0
    try:
        result = subprocess.run(command, check=check, env=env)
    except FileNotFoundError as exc:
        raise SystemExit(f"command not found: {command[0]}") from exc
    except PermissionError as exc:
        raise SystemExit(f"command not executable: {command[0]}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"command failed with exit code {exc.returncode}: {command_text(command)}") from exc
    return result.returncode


def _ordinary_kind(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        return None
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return None


def _staging_entries(cache_root: Path) -> dict[str, os.stat_result]:
    # Inspect ancestors lexically: resolving a junction would conceal an escape.
    for path in (cache_root.parents[2], cache_root.parents[1], cache_root.parent, cache_root):
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        if _ordinary_kind(path) != "directory":
            raise SystemExit(f"refusing Codex residue handling through non-ordinary directory: {path}")
    if not cache_root.exists():
        return {}
    return {path.name: path.lstat() for path in cache_root.iterdir()}


def _expected_staging_tree(
    path: Path, *, plugin: str, version: str, source_root: Path,
) -> dict[str, tuple[int, ...]] | None:
    """Snapshot a source-compatible partial tree, not a proof of creator PID."""
    if not path.name.startswith("plugin-install-") or _ordinary_kind(path) != "directory":
        return None
    plugin_root = path / plugin
    version_root = plugin_root / version
    try:
        if {child.name for child in path.iterdir()} != {plugin}:
            return None
        if _ordinary_kind(plugin_root) != "directory":
            return None
        if {child.name for child in plugin_root.iterdir()} != {version}:
            return None
        if _ordinary_kind(version_root) != "directory" or _ordinary_kind(source_root) != "directory":
            return None
        snapshot = {}

        def record(item: Path) -> None:
            metadata = item.lstat()
            snapshot[str(item.relative_to(path))] = (
                metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
                metadata.st_mtime_ns, metadata.st_ctime_ns,
            )

        for item in (path, plugin_root, version_root):
            record(item)
        pending = [(version_root, source_root)]
        while pending:
            staged, source = pending.pop()
            for child in staged.iterdir():
                kind = _ordinary_kind(child)
                if kind is None or kind != _ordinary_kind(source / child.name):
                    return None
                record(child)
                if kind == "directory":
                    pending.append((child, source / child.name))
        return snapshot
    except OSError:
        return None


def _quarantine_install_residue(
    cache_root: Path,
    residue: dict[Path, tuple[dict[str, tuple[int, ...]], int]],
    *,
    plugin: str,
    version: str,
    source_root: Path,
    stage: str,
) -> None:
    """Move only newly observed failed-copy staging; never delete cache data."""
    for path, (observed, attempt) in residue.items():
        try:
            if path.name not in _staging_entries(cache_root):
                continue  # Codex may have completed its own cleanup.
            current = _expected_staging_tree(path, plugin=plugin, version=version, source_root=source_root)
            if current != observed:
                raise SystemExit(f"Codex install residue changed before quarantine: {path}")
            quarantine = cache_root.parents[1] / "omh-install-residue" / cache_root.name
            for directory in (quarantine.parent, quarantine):
                directory.mkdir(exist_ok=True)
                if _ordinary_kind(directory) != "directory":
                    raise OSError(f"non-ordinary quarantine directory: {directory}")
            # Reserve an empty owner directory; rename never overwrites an entry.
            destination = quarantine / path.name
            destination.mkdir()
            kept = destination / "cache-entry"
            path.resolve().relative_to(cache_root.resolve())
            kept.resolve().relative_to(cache_root.parents[2].resolve())
            path.rename(kept)
            context = {
                "source": str(path), "retainedAt": str(kept),
                "plugin": f"{plugin}@{cache_root.name}", "version": version,
                "stage": stage, "failedAttempt": attempt,
            }
            with (destination / "context.json").open("x", encoding="utf-8") as handle:
                json.dump(context, handle, indent=2)
                handle.write("\n")
        except (OSError, ValueError) as exc:
            raise SystemExit(f"failed to quarantine Codex install residue {path}: {exc}") from exc
        print(f"+ quarantine Codex install residue {path} -> {kept}", flush=True)


def add_codex_plugin(
    codex: str,
    selector: str,
    *,
    env: dict[str, str],
    dry_run: bool,
    version: str | None = None,
    source_root: Path | None = None,
    stage: str = "plugin-add",
) -> None:
    """Retry only Codex's specific Windows copy/access-denied failure.

    Reissue the same plugin command, never the enclosing transaction. Codex owns
    its temporary copy paths. Observe each failed attempt's new staging entries
    and retain only uniquely matching residue outside the active cache; never delete
    caches. Successful exit still requires normal closure validation.
    """
    command = [codex, "plugin", "add", selector]
    if dry_run or sys.platform != "win32":
        run(command, env=env, dry_run=dry_run)
        return
    cache_root = None
    residue: dict[Path, tuple[dict[str, tuple[int, ...]], int]] = {}
    plugin, separator, marketplace = selector.rpartition("@")
    if version and source_root is not None and env.get("CODEX_HOME") and separator:
        for component in (plugin, marketplace, version):
            if component in {"", ".", ".."} or any(char in component for char in "/\\:"):
                raise SystemExit(f"invalid Codex residue path component: {component!r}")
        cache_root = expand_path(env["CODEX_HOME"]) / "plugins" / "cache" / marketplace

    def retain_residue() -> None:
        if cache_root is not None and residue:
            assert version is not None and source_root is not None
            _quarantine_install_residue(
                cache_root, residue, plugin=plugin, version=version,
                source_root=source_root, stage=stage,
            )

    delays = (0.5, 1.0)
    last_failure = None
    for attempt in range(1, len(delays) + 2):
        try:
            before = _staging_entries(cache_root) if cache_root is not None else {}
        except (OSError, SystemExit) as exc:
            if last_failure is None:
                raise SystemExit(f"cannot observe Codex install residue: {exc}") from exc
            write_stderr(f"cannot observe Codex install residue before retry: {exc}")
            raise subprocess.CalledProcessError(
                last_failure.returncode, command, output=last_failure.stdout, stderr=last_failure.stderr,
            ) from exc
        print("+ " + command_text(command), flush=True)
        print(
            f"Codex stage={stage} plugin={selector} version={version or 'unknown'} "
            f"attempt={attempt}/{len(delays) + 1} "
            f"validated-source={source_root or 'unknown'} "
            "copy-target=reported-by-Codex-if-available",
            flush=True,
        )
        try:
            result = subprocess.run(
                command, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
        except FileNotFoundError as exc:
            raise SystemExit(f"command not found: {codex}") from exc
        except PermissionError as exc:
            raise SystemExit(f"command not executable: {codex}: {exc}") from exc
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
        if result.stderr:
            print(result.stderr, file=sys.stderr,
                  end="" if result.stderr.endswith("\n") else "\n", flush=True)
        if result.returncode == 0:
            retain_residue()
            return
        output = f"{result.stdout or ''}\n{result.stderr or ''}".casefold()
        retryable = "failed to copy plugin file" in output and "(os error 5)" in output
        last_failure = result
        observation_failed = False
        if retryable and cache_root is not None:
            assert version is not None and source_root is not None
            try:
                candidates = {}
                for name in _staging_entries(cache_root):
                    path = cache_root / name
                    if name not in before:
                        snapshot = _expected_staging_tree(
                            path, plugin=plugin, version=version, source_root=source_root,
                        )
                        if snapshot is not None:
                            candidates[path] = (snapshot, attempt)
                if len(candidates) > 1:
                    raise SystemExit(
                        "ambiguous Codex install residue; preserving entries: "
                        + ", ".join(str(path) for path in candidates)
                    )
                if candidates:
                    write_stderr(
                        "Codex residue matches this failed attempt's observation window; "
                        "preservation requires no concurrent Codex install/update against "
                        "this CODEX_HOME (the OMH lock does not enforce that boundary)."
                    )
                residue.update(candidates)
            except (OSError, SystemExit) as exc:
                observation_failed = True
                write_stderr(f"cannot collect Codex install residue: {exc}")
        retry = retryable and not observation_failed and attempt <= len(delays)
        write_stderr(
            f"Codex stage={stage} plugin={selector} version={version or 'unknown'} "
            f"exit={result.returncode} attempt={attempt}/{len(delays) + 1}; "
            + (f"copy access denied; retrying in {delays[attempt - 1]}s."
               if retry else "plugin add failed; returning to transaction rollback.")
        )
        if not retry:
            try:
                if not observation_failed:
                    retain_residue()
            except (OSError, SystemExit) as exc:
                # Preservation failure must not erase the final Codex failure evidence.
                write_stderr(str(exc))
            raise subprocess.CalledProcessError(
                result.returncode, command, output=result.stdout, stderr=result.stderr,
            )
        time.sleep(delays[attempt - 1])


def codex_version(codex: str, *, env: dict[str, str]) -> str:
    try:
        result = subprocess.run([codex, "--version"], env=env, capture_output=True, text=True)
    except (FileNotFoundError, PermissionError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return (result.stdout or result.stderr).strip() or "unknown"


def read_codex_plugin_rows(
    codex: str,
    *,
    marketplace_name: str,
    plugin_names: set[str],
    env: dict[str, str],
) -> dict[tuple[str, str], PluginListRow]:
    command = [codex, "plugin", "list", "--json", "--available"]
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit(f"command not found: {command[0]}") from exc
    except PermissionError as exc:
        raise SystemExit(f"command not executable: {command[0]}: {exc}") from exc
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise SystemExit(
            f"failed to inspect active discovery state with `{command_text(command)}`: {output}"
        )
    try:
        return codex_plugin_rows(
            result.stdout,
            marketplace_name=marketplace_name,
            plugin_names=plugin_names,
        )
    except ValueError as exc:
        raise SystemExit(f"failed to parse `{command_text(command)}` output: {exc}") from exc


def require_codex_subcommand(codex: str, label: str, args: list[str], *, env: dict[str, str]) -> None:
    command = [codex, *args, "--help"]
    try:
        result = subprocess.run(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise SystemExit(f"command not found: {command[0]}") from exc
    except PermissionError as exc:
        raise SystemExit(f"command not executable: {command[0]}: {exc}") from exc
    if result.returncode == 0:
        return

    raise SystemExit(
        "\n".join(
            [
                f"required Codex CLI command is unavailable: codex {label}",
                f"CodexPath={codex}",
                f"CodexVersion={codex_version(codex, env=env)}",
                f"FailedCommand={command_text(command)}",
                "Breakpoint=before marketplace refresh in scripts/refresh_harness.py",
                "Upgrade Codex CLI; this refresh flow requires non-interactive plugin marketplace/add/list commands and pruning also requires plugin remove.",
            ]
        )
    )


def require_codex_plugin_commands(
    codex: str,
    *,
    env: dict[str, str],
    require_marketplace: bool = True,
    require_add: bool = True,
    require_list: bool = True,
    require_remove: bool = False,
) -> None:
    if require_marketplace:
        require_codex_subcommand(codex, "plugin marketplace add", ["plugin", "marketplace", "add"], env=env)
    if require_add:
        require_codex_subcommand(codex, "plugin add", ["plugin", "add"], env=env)
    if require_list:
        require_codex_subcommand(codex, "plugin list", ["plugin", "list"], env=env)
    if require_remove:
        require_codex_subcommand(codex, "plugin remove", ["plugin", "remove"], env=env)


def run_agent_sync(*, codex_home: Path, env: dict[str, str], dry_run: bool) -> None:
    sync_script = REPO_ROOT / "scripts" / "sync_codex_agents.py"
    if not sync_script.is_file():
        raise SystemExit(f"agent sync script does not exist: {sync_script}")
    command = [sys.executable, str(sync_script), "--codex-home", str(codex_home), "--prune"]
    if dry_run:
        command.append("--dry-run")
    run(command, env=env, dry_run=False)


def run_tooling_bootstrap(*, venv_path: Path, env: dict[str, str], dry_run: bool) -> None:
    bootstrap_script = REPO_ROOT / "scripts" / "bootstrap_tooling_env.py"
    if not bootstrap_script.is_file():
        raise SystemExit(f"tooling bootstrap script does not exist: {bootstrap_script}")
    command = [sys.executable, str(bootstrap_script), "--venv", str(venv_path)]
    if dry_run:
        command.append("--dry-run")
    run(command, env=env, dry_run=False)


def load_json_object(path: Path, *, label: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"{label} file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{label} file must contain a JSON object: {path}")
    return data


def load_install_manifest(manifest_file: Path = INSTALL_MANIFEST_FILE) -> dict:
    data = load_json_object(manifest_file, label="install manifest")
    required_fields = {"harness", "marketplace", "plugins"}
    missing_fields = sorted(required_fields - set(data))
    if missing_fields:
        raise SystemExit(
            "install manifest is missing required top-level fields: "
            + ", ".join(missing_fields)
            + f": {manifest_file}"
        )
    unexpected_fields = sorted(set(data) - required_fields)
    if unexpected_fields:
        raise SystemExit(
            "install manifest has unsupported top-level fields: "
            + ", ".join(unexpected_fields)
            + f": {manifest_file}"
        )
    if data.get("harness") != "codex":
        raise SystemExit(f"install manifest harness must be 'codex': {manifest_file}")
    marketplace = data.get("marketplace")
    if not isinstance(marketplace, str) or not marketplace.strip():
        raise SystemExit(f"install manifest marketplace must be a non-empty string: {manifest_file}")

    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        raise SystemExit(f"install manifest plugins field is not a list: {manifest_file}")

    seen: set[str] = set()
    required_plugin_fields = {"name", "install", "check"}
    for index, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            raise SystemExit(f"install manifest plugin entry #{index + 1} is not an object: {manifest_file}")
        missing_plugin_fields = sorted(required_plugin_fields - set(plugin))
        if missing_plugin_fields:
            raise SystemExit(
                f"install manifest plugin entry #{index + 1} is missing required fields: "
                + ", ".join(missing_plugin_fields)
                + f": {manifest_file}"
            )
        unexpected_plugin_fields = sorted(set(plugin) - required_plugin_fields)
        if unexpected_plugin_fields:
            raise SystemExit(
                f"install manifest plugin entry #{index + 1} has unsupported fields: "
                + ", ".join(unexpected_plugin_fields)
                + f": {manifest_file}"
            )
        name = plugin.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SystemExit(f"install manifest plugin entry #{index + 1} has no valid name: {manifest_file}")
        if name in seen:
            raise SystemExit(f"install manifest contains duplicate plugin: {name}")
        seen.add(name)
        for flag in ("install", "check"):
            if not isinstance(plugin.get(flag), bool):
                raise SystemExit(f"install manifest plugin `{name}` has non-boolean `{flag}`")
    return data


def ensure_plugins_in_marketplace(plugin_names: list[str], *, marketplace_file: Path = MARKETPLACE_FILE) -> None:
    try:
        present = marketplace_plugin_names(marketplace_file)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    missing = sorted(set(plugin_names) - present)
    if missing:
        raise SystemExit(
            "install manifest selected plugins are missing from marketplace: " + ", ".join(missing)
        )


def default_plugin_names(
    action: str,
    *,
    marketplace_name: str,
    manifest_file: Path = INSTALL_MANIFEST_FILE,
    marketplace_file: Path = MARKETPLACE_FILE,
) -> list[str]:
    if action not in {"install", "check"}:
        raise ValueError(f"unsupported plugin selection action: {action}")

    manifest = load_install_manifest(manifest_file)
    configured_marketplace = manifest.get("marketplace")
    if configured_marketplace != marketplace_name:
        raise SystemExit(
            f"install manifest marketplace mismatch: expected {marketplace_name!r}, "
            f"found {configured_marketplace!r}"
        )

    plugins = manifest["plugins"]
    names = [plugin["name"] for plugin in plugins if plugin[action]]
    if not names:
        raise SystemExit(f"install manifest selects no plugins for `{action}`")
    ensure_plugins_in_marketplace(names, marketplace_file=marketplace_file)
    return names


def codex_plugin_selectors(
    marketplace_name: str,
    *,
    action: str,
    manifest_file: Path = INSTALL_MANIFEST_FILE,
    marketplace_file: Path = MARKETPLACE_FILE,
) -> list[str]:
    plugin_names = default_plugin_names(
        action,
        marketplace_name=marketplace_name,
        manifest_file=manifest_file,
        marketplace_file=marketplace_file,
    )
    return [f"{name}@{marketplace_name}" for name in plugin_names]


def configured_plugin_settings(
    codex_home: Path,
) -> dict[tuple[str, str], dict[str, object]]:
    config_path = codex_home / "config.toml"
    if not config_path.is_file():
        return {}
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"Codex config is not valid readable TOML: {config_path}: {exc}") from exc
    plugins = payload.get("plugins", {})
    if not isinstance(plugins, dict):
        raise SystemExit(f"Codex config plugins table must be a mapping: {config_path}")
    selectors: dict[tuple[str, str], dict[str, object]] = {}
    for raw_selector, settings in plugins.items():
        if not isinstance(raw_selector, str) or not isinstance(settings, dict):
            raise SystemExit(f"Codex config plugin entry is malformed: {raw_selector!r}: {config_path}")
        plugin_name, separator, marketplace = raw_selector.rpartition("@")
        if not separator or not plugin_name or not marketplace:
            raise SystemExit(f"Codex config plugin selector is malformed: {raw_selector!r}: {config_path}")
        selectors[(marketplace, plugin_name)] = settings
    return selectors


def configured_plugin_selectors(codex_home: Path) -> set[tuple[str, str]]:
    return set(configured_plugin_settings(codex_home))


def configured_plugin_names(codex_home: Path, marketplace_name: str) -> set[str]:
    return {
        plugin_name
        for marketplace, plugin_name in configured_plugin_selectors(codex_home)
        if marketplace == marketplace_name
    }


def _enabled_codex_harness_plugins(
    catalog: SkillCatalog,
    *,
    codex: str,
    marketplace_name: str,
    env: dict[str, str],
    ignored_unclassified: set[str] | None = None,
    ignored_alternate_marketplaces: set[str] | None = None,
    rows: dict[tuple[str, str], PluginListRow] | None = None,
) -> set[str]:
    selectors = _enabled_catalog_plugin_selectors(
        catalog,
        codex=codex,
        marketplace_name=marketplace_name,
        env=env,
        ignored_unclassified=ignored_unclassified,
        rows=rows,
    )
    alternate = sorted(
        f"{plugin_name}@{marketplace}"
        for marketplace, plugin_name in selectors
        if marketplace != marketplace_name
        and marketplace not in set(ignored_alternate_marketplaces or ())
    )
    if alternate:
        raise SystemExit(
            "canonical skill plugins are enabled through another marketplace: "
            + ", ".join(alternate)
        )
    return {
        plugin_name
        for marketplace, plugin_name in selectors
        if marketplace == marketplace_name
    }


def _enabled_catalog_plugin_selectors(
    catalog: SkillCatalog,
    *,
    codex: str,
    marketplace_name: str,
    env: dict[str, str],
    ignored_unclassified: set[str] | None = None,
    rows: dict[tuple[str, str], PluginListRow] | None = None,
) -> set[tuple[str, str]]:
    expected = set(catalog.plugin_names)
    if rows is None:
        rows = read_codex_plugin_rows(
            codex,
            marketplace_name=marketplace_name,
            plugin_names=expected,
            env=env,
        )
    enabled = {
        (marketplace, plugin_name)
        for (marketplace, plugin_name), row in rows.items()
        if row.status == "installed, enabled"
    }
    ignored = set(ignored_unclassified or ())
    unclassified = sorted(
        plugin_name
        for marketplace, plugin_name in enabled
        if marketplace == marketplace_name
        and plugin_name not in expected
        and plugin_name not in ignored
    )
    if unclassified:
        raise SystemExit(
            "unclassified enabled oh-my-harness plugins are outside the Codex harness plan: "
            + ", ".join(unclassified)
        )
    return {
        (marketplace, plugin_name)
        for marketplace, plugin_name in enabled
        if plugin_name in expected
    }


def require_excluded_skill_roots_clear(
    catalog: SkillCatalog,
    roots: tuple[Path, ...],
) -> None:
    issues = excluded_skill_root_issues(catalog, roots=roots)
    if not issues:
        return

    cleanup_script = REPO_ROOT / "scripts" / "sync_agents_skills.py"
    commands: list[str] = []
    for root in roots:
        base = [
            sys.executable,
            str(cleanup_script),
            "--repo-root",
            str(catalog.repo_root),
            "--target-root",
            str(root),
            "--remove-managed",
        ]
        commands.append("preview: " + command_text([*base, "--dry-run"]))
        commands.append("apply after review: " + command_text([*base, "--yes"]))
    raise SystemExit(
        f"excluded skill root closure failed with {len(issues)} issue(s): "
        + "; ".join(issues)
        + "\nRepository-owned entries can be cleaned explicitly; unmanaged conflicts "
        "must be moved or removed manually.\n"
        + "\n".join(commands)
    )


def preflight_codex_distribution(
    catalog: SkillCatalog,
    *,
    codex_home: Path,
    marketplace_name: str,
    marketplace_file: Path | None = None,
    manifest_file: Path | None = None,
    ignored_stale_cache_plugins: set[str] | frozenset[str] | None = None,
) -> tuple[list[str], dict[str, Path]]:
    """Validate every canonical plugin input before Codex harness mutation."""

    marketplace_file = marketplace_file or (
        catalog.repo_root / ".agents" / "plugins" / "marketplace.json"
    )
    manifest_file = manifest_file or (
        catalog.repo_root / ".agents" / "plugins" / "install-manifest.json"
    )
    all_selectors = codex_plugin_selectors(
        marketplace_name,
        action="install",
        manifest_file=manifest_file,
        marketplace_file=marketplace_file,
    )
    ensure_codex_harness_covers_catalog(
        catalog,
        all_selectors,
        marketplace_name=marketplace_name,
    )
    try:
        marketplace_identity, plugin_sources = marketplace_plugin_sources(
            catalog.repo_root,
            marketplace_file=marketplace_file,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if marketplace_identity != marketplace_name:
        raise SystemExit(
            f"marketplace identity mismatch: expected {marketplace_name!r}, "
            f"found {marketplace_identity!r}"
        )
    require_harness_closure(
        "Codex package preflight",
        [
            *plugin_package_issues(catalog, plugin_sources=plugin_sources),
            *plugin_cache_harness_issues(
                catalog,
                codex_home=codex_home,
                marketplace_name=marketplace_name,
                ignored_plugin_names=set(ignored_stale_cache_plugins or ()),
            ),
        ],
    )
    return all_selectors, plugin_sources


def apply_codex_harness(
    catalog: SkillCatalog,
    *,
    codex: str,
    codex_home: Path,
    marketplace_name: str,
    excluded_skill_roots: tuple[Path, ...],
    marketplace_file: Path | None = None,
    manifest_file: Path | None = None,
    marketplace_source_binding: MarketplaceSourceBinding,
    env: dict[str, str],
    dry_run: bool,
    repair: bool = False,
    ignored_stale_cache_plugins: set[str] | frozenset[str] | None = None,
    ignored_stale_enabled_plugins: set[str] | frozenset[str] | None = None,
    ignored_alternate_marketplaces: set[str] | frozenset[str] | None = None,
) -> None:
    require_harness_closure(
        "Codex marketplace source binding",
        marketplace_source_binding_issues(catalog, marketplace_source_binding),
    )
    all_selectors, plugin_sources = preflight_codex_distribution(
        catalog,
        codex_home=codex_home,
        marketplace_name=marketplace_name,
        marketplace_file=marketplace_file,
        manifest_file=manifest_file,
        ignored_stale_cache_plugins=ignored_stale_cache_plugins,
    )

    require_excluded_skill_roots_clear(catalog, excluded_skill_roots)
    expected_names = set(catalog.plugin_names)
    rows_before = read_codex_plugin_rows(
        codex, marketplace_name=marketplace_name,
        plugin_names=expected_names, env=env,
    )
    enabled_before = _enabled_codex_harness_plugins(
        catalog,
        codex=codex,
        marketplace_name=marketplace_name,
        env=env,
        ignored_unclassified=set(ignored_stale_enabled_plugins or ()),
        ignored_alternate_marketplaces=set(ignored_alternate_marketplaces or ()),
        rows=rows_before,
    )
    transition_selectors = all_selectors

    def current_rows() -> dict[tuple[str, str], PluginListRow]:
        return read_codex_plugin_rows(
            codex,
            marketplace_name=marketplace_name,
            plugin_names=expected_names,
            env=env,
        )

    def current_enabled() -> set[str]:
        rows = current_rows()
        enabled = enabled_plugin_names(rows, marketplace_name=marketplace_name)
        ignored = set(ignored_stale_enabled_plugins or ())
        unclassified = sorted(enabled - expected_names - ignored)
        if unclassified:
            raise SystemExit(
                "unclassified enabled oh-my-harness plugins are outside the Codex harness plan: "
                + ", ".join(unclassified)
            )
        return enabled - ignored

    source_versions: dict[str, str] = {}
    for plugin_name, source_root in plugin_sources.items():
        try:
            source_name, source_version = plugin_manifest_identity(
                source_root / ".codex-plugin" / "plugin.json",
                label="source",
            )
        except ValueError as exc:
            raise SystemExit(f"{plugin_name}: {exc}") from exc
        if source_name != plugin_name:
            raise SystemExit(
                f"{plugin_name}: source manifest name mismatch; found {source_name!r}"
            )
        source_versions[plugin_name] = source_version

    if not repair:
        cache_identity_issues: list[str] = []
        for plugin_name, source_root in plugin_sources.items():
            row_before = rows_before.get((marketplace_name, plugin_name))
            if (
                row_before is None
                or row_before.status != "installed, enabled"
                or row_before.version != source_versions[plugin_name]
            ):
                continue
            cache_root = (
                codex_home
                / "plugins"
                / "cache"
                / marketplace_name
                / plugin_name
                / source_versions[plugin_name]
            )
            cache_identity_issues.extend(
                f"{plugin_name}@{marketplace_name}: {issue}"
                for issue in plugin_cache_identity_issues(
                    source_root=source_root,
                    cache_root=cache_root,
                )
            )
        require_harness_closure(
            "Codex plugin cache identity preflight",
            cache_identity_issues,
        )
    else:
        print(
            "Codex repair mode: same-version cache identity preflight is "
            "replaced by forced re-materialization."
        )

    def verify_codex() -> None:
        if dry_run:
            return
        require_harness_closure(
            "codex",
            plugin_installation_issues(
                catalog,
                marketplace_name=marketplace_name,
                excluded_skill_roots=excluded_skill_roots,
                codex_home=codex_home,
                rows=current_rows(),
                plugin_sources=plugin_sources,
                ignored_alternate_marketplaces=set(
                    ignored_alternate_marketplaces or ()
                ),
            ),
        )

    def deactivate_codex_plugin(selector: str) -> None:
        plugin_name, _, selector_marketplace = selector.partition("@")
        if not dry_run:
            row = current_rows().get((selector_marketplace, plugin_name))
            configured = (
                selector_marketplace,
                plugin_name,
            ) in configured_plugin_selectors(codex_home)
            if (row is None or row.status == "not installed") and not configured:
                return
        run(
            [codex, "plugin", "remove", selector],
            env=env,
            dry_run=dry_run,
        )

    attempted_new: list[str] = []
    try:
        for selector in transition_selectors:
            plugin_name, _, selector_marketplace = selector.partition("@")
            row_before = rows_before.get((selector_marketplace, plugin_name))
            if (
                row_before is not None
                and row_before.status == "installed, enabled"
                and row_before.version == source_versions[plugin_name]
                and not repair
            ):
                print(
                    f"Plugin `{selector}` is already installed at current version "
                    f"{row_before.version}; skipping add."
                )
                continue
            if selector.partition("@")[0] not in enabled_before:
                attempted_new.append(selector)
            add_codex_plugin(
                codex, selector, env=env, dry_run=dry_run,
                version=source_versions[plugin_name],
                source_root=plugin_sources[plugin_name],
            )
        verify_codex()
    except (Exception, SystemExit) as exc:
        try:
            for selector in reversed(attempted_new):
                deactivate_codex_plugin(selector)
            restored = current_enabled()
            if restored != enabled_before:
                raise SystemExit(
                    "plugin refresh rollback did not restore the prior enabled set: "
                    f"expected {sorted(enabled_before)}, found {sorted(restored)}"
                )
        except (Exception, SystemExit) as rollback_exc:
            raise SystemExit(
                f"Codex harness activation failed: {exc}; rollback failed: {rollback_exc}"
            ) from exc
        raise


def cached_plugin_names(codex_home: Path, marketplace_name: str) -> set[str]:
    cache_root = codex_home / "plugins" / "cache" / marketplace_name
    if not cache_root.is_dir():
        return set()
    return {path.name for path in cache_root.iterdir() if path.is_dir()}


def retired_marketplace_states(
    codex_home: Path,
    retired_names: tuple[str, ...],
) -> tuple[RetiredMarketplaceState, ...]:
    states: list[RetiredMarketplaceState] = []
    for name in retired_names:
        config = configured_marketplace(codex_home, name) or {}
        state = RetiredMarketplaceState(
            name=name,
            configured_plugins=frozenset(configured_plugin_names(codex_home, name)),
            cached_plugins=frozenset(cached_plugin_names(codex_home, name)),
            source_config=tuple(sorted(config.items())),
        )
        if state.present:
            states.append(state)
    return tuple(states)


def marketplace_migration_option() -> str:
    return "-MigrateMarketplace" if os.name == "nt" else "--migrate-marketplace"


def confirm_retired_marketplace_migration(
    states: tuple[RetiredMarketplaceState, ...],
    *,
    requested: bool,
    dry_run: bool,
    assume_yes: bool,
) -> None:
    if not states:
        if requested:
            print("no retired marketplace state requires migration")
        return

    print("Retired Codex marketplace migration plan:")
    for state in states:
        source = dict(state.source_config).get("source", "<none>")
        print(f"- marketplace {state.name} (source: {source})")
        for plugin_name in sorted(state.configured_plugins | state.cached_plugins):
            locations: list[str] = []
            if plugin_name in state.configured_plugins:
                locations.append("config")
            if plugin_name in state.cached_plugins:
                locations.append("cache")
            print(f"  - {plugin_name} ({'+'.join(locations)})")

    if not requested:
        raise SystemExit(
            "action required: retired marketplace state requires an explicit migration; "
            f"rerun with {marketplace_migration_option()} after reviewing the bounded plan"
        )
    if dry_run:
        return
    if assume_yes:
        print("Retired marketplace migration [auto-confirmed]")
        return
    try:
        answer = input(
            emphasize(
                "Migrate the listed retired marketplace state [y/N] ",
                color="yellow",
                stream=sys.stdout,
            )
        )
    except (EOFError, OSError):
        answer = ""
    if answer.strip() not in {"y", "Y", "yes", "YES", "Yes"}:
        raise SystemExit("retired marketplace migration was not confirmed")


def detach_relocated_retired_marketplace_sources(
    codex: str,
    *,
    codex_home: Path,
    states: tuple[RetiredMarketplaceState, ...],
    retired_repo: Path | None,
    env: dict[str, str],
    dry_run: bool,
) -> tuple[RetiredMarketplaceState, ...]:
    """Detach an exact local source made unreadable by checkout relocation."""

    if retired_repo is None:
        return states
    detached_names: list[str] = []
    for state in states:
        config = dict(state.source_config)
        source = config.get("source")
        if config.get("source_type") != "local" or not source:
            continue
        source_path = expand_path(source)
        if not same_path(source_path, retired_repo) or source_path.exists():
            continue
        print(
            "Relocated retired marketplace source is unavailable; detaching only "
            f"its source registration before discovery: {state.name} -> {source_path}"
        )
        if dry_run:
            raise SystemExit(
                "dry-run cannot simulate Codex discovery after detaching a missing "
                "retired marketplace source; rerun without --dry-run after reviewing "
                "the exact migration plan"
            )
        remove_marketplace_source(
            codex,
            codex_home=codex_home,
            marketplace_name=state.name,
            env=env,
            dry_run=False,
        )
        detached_names.append(state.name)

    if not detached_names:
        return states
    current = retired_marketplace_states(
        codex_home,
        tuple(state.name for state in states),
    )
    before = {state.name: state for state in states}
    after = {state.name: state for state in current}
    for name in detached_names:
        previous = before[name]
        updated = after.get(name)
        if updated is None:
            raise SystemExit(
                "retired marketplace selectors or cache disappeared while detaching "
                f"the relocated source: {name}"
            )
        if (
            updated.configured_plugins != previous.configured_plugins
            or updated.cached_plugins != previous.cached_plugins
            or updated.source_config
        ):
            raise SystemExit(
                "retired marketplace state changed outside the exact source "
                f"registration while detaching relocation: {name}"
            )
    return current


def apply_retired_marketplace_migration(
    codex: str,
    *,
    codex_home: Path,
    states: tuple[RetiredMarketplaceState, ...],
    env: dict[str, str],
    dry_run: bool,
) -> None:
    if not states:
        return
    current = retired_marketplace_states(
        codex_home,
        tuple(state.name for state in states),
    )
    if current != states:
        raise SystemExit(
            "retired marketplace state changed after preflight; refusing migration"
        )

    removed_selectors: list[str] = []
    try:
        for state in states:
            for plugin_name in sorted(state.configured_plugins):
                selector = f"{plugin_name}@{state.name}"
                run(
                    [codex, "plugin", "remove", selector],
                    env=env,
                    dry_run=dry_run,
                )
                if not dry_run:
                    removed_selectors.append(selector)
            remove_marketplace_source(
                codex,
                codex_home=codex_home,
                marketplace_name=state.name,
                env=env,
                dry_run=dry_run,
            )
    except (Exception, SystemExit) as migration_error:
        rollback_errors: list[str] = []
        for selector in reversed(removed_selectors):
            try:
                add_codex_plugin(codex, selector, env=env, dry_run=False, stage="migration-rollback")
            except (Exception, SystemExit) as rollback_error:
                rollback_errors.append(f"{selector}: {rollback_error}")
        if rollback_errors:
            raise SystemExit(
                f"retired marketplace migration failed: {migration_error}; "
                "rollback failed: " + "; ".join(rollback_errors)
            ) from migration_error
        raise

    if dry_run:
        return
    for state in states:
        for plugin_name in sorted(cached_plugin_names(codex_home, state.name)):
            remove_cached_plugin_dir(
                codex_home=codex_home,
                marketplace_name=state.name,
                plugin_name=plugin_name,
                dry_run=False,
            )
        cache_root = codex_home / "plugins" / "cache" / state.name
        if cache_root.is_dir():
            try:
                cache_root.rmdir()
            except OSError as exc:
                raise SystemExit(
                    f"retired marketplace cache root is not empty after migration: {cache_root}: {exc}"
                ) from exc

    remaining = retired_marketplace_states(
        codex_home,
        tuple(state.name for state in states),
    )
    if remaining:
        raise SystemExit(
            "retired marketplace state remains after migration: "
            + ", ".join(state.name for state in remaining)
        )
    print("retired Codex marketplace migration complete")


def plugin_cache_dir(codex_home: Path, marketplace_name: str, plugin_name: str) -> Path:
    return codex_home / "plugins" / "cache" / marketplace_name / plugin_name


def plugin_prune_plan(
    *,
    codex_home: Path,
    marketplace_name: str,
    desired_plugin_names: list[str],
) -> CodexPrunePlan:
    desired = set(desired_plugin_names)
    return CodexPrunePlan(
        configured=frozenset(
            configured_plugin_names(codex_home, marketplace_name) - desired
        ),
        cached=frozenset(cached_plugin_names(codex_home, marketplace_name) - desired),
    )


def stale_plugin_names(
    *,
    codex_home: Path,
    marketplace_name: str,
    desired_plugin_names: list[str],
) -> list[str]:
    return sorted(
        plugin_prune_plan(
            codex_home=codex_home,
            marketplace_name=marketplace_name,
            desired_plugin_names=desired_plugin_names,
        ).names
    )


def remove_cached_plugin_dir(
    *,
    codex_home: Path,
    marketplace_name: str,
    plugin_name: str,
    dry_run: bool,
) -> None:
    cache_root = codex_home / "plugins" / "cache" / marketplace_name
    plugin_dir = plugin_cache_dir(codex_home, marketplace_name, plugin_name)
    if not plugin_dir.exists():
        return
    try:
        plugin_dir.resolve().relative_to(cache_root.resolve())
    except ValueError as exc:
        raise SystemExit(f"refusing to remove plugin cache outside marketplace cache root: {plugin_dir}") from exc
    print(f"+ remove plugin cache {plugin_dir}", flush=True)
    if dry_run:
        return
    clear_readonly_attributes(plugin_dir)
    try:
        shutil.rmtree(plugin_dir)
    except OSError as exc:
        raise SystemExit(f"failed to remove plugin cache {plugin_dir}: {exc}") from exc


def prune_stale_plugins(
    codex: str,
    *,
    codex_home: Path,
    marketplace_name: str,
    plan: CodexPrunePlan,
    env: dict[str, str],
    dry_run: bool,
) -> None:
    stale = sorted(plan.names)
    if not stale:
        print(f"No stale plugins to prune for marketplace `{marketplace_name}`.")
        return

    print(f"Applying confirmed Codex managed-stale prune plan for `{marketplace_name}`.")
    for name in sorted(plan.configured):
        run(
            [codex, "plugin", "remove", f"{name}@{marketplace_name}"],
            env=env,
            dry_run=dry_run,
        )
    for name in sorted(plan.cached):
        remove_cached_plugin_dir(
            codex_home=codex_home,
            marketplace_name=marketplace_name,
            plugin_name=name,
            dry_run=dry_run,
        )


def confirm_codex_prune(
    plan: CodexPrunePlan,
    *,
    marketplace_name: str,
    confirmation: str,
    dry_run: bool,
    assume_yes: bool,
) -> None:
    if confirmation not in {"none", "when-nonempty"}:
        raise SystemExit(f"unsupported Codex prune confirmation policy: {confirmation!r}")
    if not plan.names:
        print(f"no stale managed plugins to prune for marketplace `{marketplace_name}`")
        return
    print(f"Codex managed-stale prune plan for marketplace `{marketplace_name}`:")
    for name in sorted(plan.names):
        locations: list[str] = []
        if name in plan.configured:
            locations.append("config")
        if name in plan.cached:
            locations.append("cache")
        print(f"- {name} ({'+'.join(locations)})")
    if dry_run or confirmation == "none":
        return
    if assume_yes:
        print("Prune listed managed-stale Codex plugins [auto-confirmed]")
        return
    try:
        answer = input(
            emphasize(
                "Prune listed managed-stale Codex plugins [y/N] ",
                color="yellow",
                stream=sys.stdout,
            )
        )
    except (EOFError, OSError):
        answer = ""
    if answer.strip() not in {"y", "Y", "yes", "YES", "Yes"}:
        raise SystemExit("Codex managed-stale plugin prune was not confirmed")


def tooling_python_from_args(args: argparse.Namespace, venv_path: Path) -> Path:
    override = (
        args.python
        or os.environ.get(MANAGER_TOOLING_PYTHON_ENV)
        or os.environ.get(MANAGER_PYTHON_ENV)
    )
    if override:
        return expand_path(override)
    return venv_python(venv_path)


def resolve_plugin_validator(
    *,
    environ: dict[str, str] | None = None,
) -> str:
    active_environ = os.environ if environ is None else environ
    override = active_environ.get("PLUGIN_VALIDATOR")
    if override:
        return override
    return str(REPOSITORY_PLUGIN_VALIDATOR)


def build_env(
    *,
    codex_home: Path,
    tooling_python: Path,
    manager_home: Path | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    resolved_manager_home = manager_home or MANAGER_HOME
    env["CODEX_HOME"] = str(codex_home)
    env["OH_MY_HARNESS_HOME"] = str(resolved_manager_home)
    env[MANAGER_ROOT_ENV] = str(REPO_ROOT)
    env[MANAGER_PYTHON_ENV] = str(tooling_python)
    env[MANAGER_TOOLING_PYTHON_ENV] = str(tooling_python)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PLUGIN_VALIDATOR"] = resolve_plugin_validator(environ=env)
    return env


def decode_text(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")


def git_remote_source(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "config", "--get", "remote.origin.url"],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    source = decode_text(result.stdout).strip()
    return source or None


def git_head_revision(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
    )
    if result.returncode != 0:
        output = decode_text(result.stderr or result.stdout).strip()
        raise SystemExit(f"repository HEAD is unavailable for marketplace binding: {output}")
    revision = decode_text(result.stdout).strip()
    if not revision:
        raise SystemExit("repository HEAD is empty for marketplace binding")
    return revision


def git_worktree_clean(repo_root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
    )
    if result.returncode != 0:
        return False, "local worktree status is unavailable"
    if decode_text(result.stdout).strip():
        return False, "local worktree has uncommitted changes"
    return True, "local worktree is clean"


def git_remote_ref_status(repo_root: Path, ref: str) -> tuple[bool, str]:
    clean, reason = git_worktree_clean(repo_root)
    if not clean:
        return False, reason

    remote_ref = f"refs/remotes/origin/{ref}"
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
    )
    if head.returncode != 0:
        return False, "local HEAD is unavailable"

    remote = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", remote_ref],
        capture_output=True,
    )
    if remote.returncode != 0:
        return False, f"remote tracking ref {remote_ref} is unavailable"

    head_sha = decode_text(head.stdout).strip()
    remote_sha = decode_text(remote.stdout).strip()
    if head_sha != remote_sha:
        return False, f"local HEAD {head_sha[:12]} differs from {remote_ref} {remote_sha[:12]}"

    return True, f"local HEAD matches {remote_ref}"


def toml_string_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def configured_marketplace(codex_home: Path, marketplace_name: str) -> dict[str, str] | None:
    config_path = codex_home / "config.toml"
    if not config_path.is_file():
        return None

    section = f"[marketplaces.{marketplace_name}]"
    in_section = False
    values: dict[str, str] = {}
    for line in config_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped == section:
            in_section = True
            continue
        if in_section and stripped.startswith("[") and stripped.endswith("]"):
            break
        if not in_section or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in {"source_type", "source", "ref"}:
            values[key] = toml_string_value(value)

    return values or None


def configured_marketplace_source_binding(
    codex_home: Path,
    marketplace_name: str,
) -> MarketplaceSourceBinding:
    config = configured_marketplace(codex_home, marketplace_name)
    if config is None:
        raise ValueError(f"configured marketplace is missing: {marketplace_name}")
    source_type = config.get("source_type")
    source = config.get("source")
    if source_type not in {"local", "git"}:
        raise ValueError(
            f"configured marketplace source_type must be local or git: {marketplace_name}"
        )
    if not source:
        raise ValueError(f"configured marketplace source is missing: {marketplace_name}")
    revision = config.get("ref") if source_type == "git" else None
    if source_type == "git" and not revision:
        raise ValueError(f"configured Git marketplace ref is missing: {marketplace_name}")
    return MarketplaceSourceBinding(
        source_type=source_type,
        source=source,
        revision=revision,
    )


def clear_readonly_attributes(root: Path) -> None:
    if not root.exists():
        return
    items = [root, *root.rglob("*")]
    for item in items:
        try:
            mode = item.stat().st_mode
            item.chmod(mode | stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            continue


def remove_marketplace_source(
    codex: str,
    *,
    codex_home: Path,
    marketplace_name: str,
    env: dict[str, str],
    dry_run: bool,
) -> None:
    config = configured_marketplace(codex_home, marketplace_name)
    if config is None:
        return

    if dry_run:
        print(f"Would clear read-only attributes before removing marketplace `{marketplace_name}`.")
    else:
        source = config.get("source")
        if config.get("source_type") == "local" and source:
            clear_readonly_attributes(expand_path(source))
        clear_readonly_attributes(codex_home / ".tmp" / "marketplaces" / marketplace_name)

    run([codex, "plugin", "marketplace", "remove", marketplace_name], env=env, dry_run=dry_run)


def windows_path_comparison_key(path: str | Path) -> str:
    """Normalize equivalent Win32 and extended-length path spellings."""
    value = str(path).replace("/", "\\")
    folded = value.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        value = "\\\\" + value[8:]
    elif (
        folded.startswith("\\\\?\\")
        and len(value) >= 7
        and value[4].isalpha()
        and value[5:7] == ":\\"
    ):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


def same_path(left: str | Path, right: str | Path) -> bool:
    left_path = expand_path(left)
    right_path = expand_path(right)
    try:
        left_path = left_path.resolve()
        right_path = right_path.resolve()
    except OSError:
        pass

    if os.name == "nt":
        return windows_path_comparison_key(left_path) == windows_path_comparison_key(right_path)
    return left_path == right_path


def source_is_path_like(raw: str) -> bool:
    if "://" in raw or raw.startswith("git@"):
        return False
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return (
        raw.startswith((".", "~", "/", "\\"))
        or (len(raw) >= 3 and raw[1] == ":" and raw[2] in {"\\", "/"})
        or Path(expanded).exists()
    )


def same_marketplace_source(left: str, right: str) -> bool:
    if source_is_path_like(left) and source_is_path_like(right):
        return same_path(left, right)
    left_source = marketplace_source_arg(left).strip().rstrip("/\\")
    right_source = marketplace_source_arg(right).strip().rstrip("/\\")
    return left_source == right_source


def same_marketplace_ref(left: str | None, right: str) -> bool:
    return (left or "").strip() == (right or "").strip()


def marketplace_source_binding_issues(
    catalog: SkillCatalog,
    binding: MarketplaceSourceBinding,
) -> list[str]:
    if binding.source_type == "local":
        if binding.revision is not None:
            return ["local marketplace source binding must not declare a Git revision"]
        if not same_path(binding.source, catalog.repo_root):
            return [
                "local marketplace source is not the validated canonical checkout; "
                f"expected {catalog.repo_root}, found {binding.source}"
            ]
        return []
    if binding.source_type != "git":
        return [f"unsupported marketplace source binding type: {binding.source_type!r}"]

    canonical_remote = git_remote_source(catalog.repo_root)
    if canonical_remote is None:
        return ["canonical checkout has no Git remote for Git marketplace binding"]
    if not same_marketplace_source(binding.source, canonical_remote):
        return [
            "Git marketplace source is not the canonical checkout remote; "
            f"expected {canonical_remote!r}, found {binding.source!r}"
        ]
    clean, reason = git_worktree_clean(catalog.repo_root)
    if not clean:
        return [f"canonical checkout cannot bind a Git package source: {reason}"]
    revision = git_head_revision(catalog.repo_root)
    if binding.revision != revision:
        return [
            "Git marketplace source is not pinned to the validated checkout revision; "
            f"expected {revision}, found {binding.revision!r}"
        ]
    return []


def ensure_git_marketplace_source(
    codex: str,
    *,
    codex_home: Path,
    marketplace_name: str,
    source: str,
    ref: str,
    env: dict[str, str],
    dry_run: bool,
) -> int:
    config = configured_marketplace(codex_home, marketplace_name)
    if config and config.get("source_type") == "git":
        configured_source = config.get("source")
        if (
            configured_source
            and same_marketplace_source(configured_source, source)
            and same_marketplace_ref(config.get("ref"), ref)
        ):
            return run(
                [codex, "plugin", "marketplace", "upgrade", marketplace_name],
                env=env,
                dry_run=dry_run,
                check=False,
            )

        print("Configured Git marketplace differs from requested source/ref; re-adding marketplace.")
        print(f"ConfiguredSource={configured_source or '<missing>'}")
        print(f"RequestedSource={source}")
        print(f"ConfiguredRef={config.get('ref') or '<missing>'}")
        print(f"RequestedRef={ref or '<none>'}")

    if config:
        remove_marketplace_source(
            codex,
            codex_home=codex_home,
            marketplace_name=marketplace_name,
            env=env,
            dry_run=dry_run,
        )

    command = [codex, "plugin", "marketplace", "add", marketplace_source_arg(source)]
    if ref:
        command += ["--ref", ref]
    return run(command, env=env, dry_run=dry_run, check=False)


def ensure_local_marketplace_source(
    codex: str,
    *,
    codex_home: Path,
    marketplace_name: str,
    source: str,
    env: dict[str, str],
    dry_run: bool,
) -> None:
    config = configured_marketplace(codex_home, marketplace_name)
    if config and config.get("source_type") == "local" and config.get("source"):
        if same_path(config["source"], source):
            return

    if config:
        remove_marketplace_source(
            codex,
            codex_home=codex_home,
            marketplace_name=marketplace_name,
            env=env,
            dry_run=dry_run,
        )

    run([codex, "plugin", "marketplace", "add", marketplace_source_arg(source)], env=env, dry_run=dry_run)


def ensure_marketplace_source(
    codex: str,
    *,
    codex_home: Path,
    marketplace_name: str,
    git_source: str | None,
    git_ref: str,
    git_request_explicit: bool,
    local_source: str,
    env: dict[str, str],
    dry_run: bool,
) -> MarketplaceSourceBinding:
    if not same_path(local_source, REPO_ROOT):
        raise SystemExit(
            "local marketplace source must be the validated canonical checkout: "
            f"expected {REPO_ROOT}, found {local_source}"
        )
    if git_request_explicit and not git_source:
        raise SystemExit(
            "explicit Git marketplace request cannot be honored because the canonical "
            f"checkout remote is unavailable for ref {git_ref!r}"
        )
    if not git_request_explicit:
        # The caller already validated the complete checkout distribution. Reuse
        # that source instead of asking Codex to acquire the same Git tree again.
        ensure_local_marketplace_source(
            codex, codex_home=codex_home, marketplace_name=marketplace_name,
            source=local_source, env=env, dry_run=dry_run,
        )
        print("Marketplace source mode: local (validated checkout reuse)")
        return MarketplaceSourceBinding(source_type="local", source=local_source)
    assert git_source is not None
    canonical_remote = git_remote_source(REPO_ROOT)
    if canonical_remote is None or not same_marketplace_source(git_source, canonical_remote):
        raise SystemExit(
            "Git marketplace source must be the canonical checkout remote; "
            f"expected {canonical_remote!r}, found {git_source!r}"
        )
    current, reason = git_remote_ref_status(REPO_ROOT, git_ref)
    if not current:
        raise SystemExit(
            f"explicit Git marketplace ref is not the validated checkout: {reason}"
        )
    pinned_revision = git_head_revision(REPO_ROOT)
    print(f"Pinning explicit Git marketplace source to validated revision: {pinned_revision}")
    git_exit = ensure_git_marketplace_source(
        codex, codex_home=codex_home, marketplace_name=marketplace_name,
        source=git_source, ref=pinned_revision, env=env, dry_run=dry_run,
    )
    if git_exit != 0:
        raise SystemExit(
            f"Git marketplace source {git_source!r} at validated revision "
            f"{pinned_revision} failed with exit code {git_exit}"
        )
    print("Marketplace source mode: git")
    return MarketplaceSourceBinding("git", git_source, pinned_revision)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh one registry-selected harness distribution."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    parser.add_argument(
        "--harness",
        help="Harness id from .agents/harnesses/registry.json (default: registry-owned).",
    )
    parser.add_argument("--registry", default=str(REGISTRY_FILE), help="Harness registry JSON path.")
    parser.add_argument(
        "--codex",
        help="Explicit Codex CLI executable. Defaults to CODEX_BIN, PATH, then managed install fallbacks.",
    )
    parser.add_argument("--codex-home", default=str(CODEX_HOME), help="Codex harness home directory.")
    parser.add_argument(
        "--home",
        default=str(MANAGER_HOME),
        help="oh-my-harness manager home (default: OH_MY_HARNESS_HOME or ~/.oh-my-harness).",
    )
    parser.add_argument(
        "--venv",
        help="Shared tooling venv path (default: <manager home>/venv).",
    )
    parser.add_argument("--python", help="Explicit tooling Python for hooks and diagnostics.")
    parser.add_argument(
        "--marketplace-source",
        help="Codex-only local marketplace source; defaults to this checkout.",
    )
    parser.add_argument(
        "--git-marketplace-source",
        help="Request Git acquisition from the canonical remote (default without this option: local checkout).",
    )
    parser.add_argument("--git-ref", help="Request Git acquisition at this ref (default with --git-marketplace-source: main).")
    parser.add_argument("--skip-bootstrap", action="store_true", help="Do not refresh the shared tooling venv.")
    parser.add_argument("--skip-agents", action="store_true", help="Do not sync the Codex subagent support file.")
    parser.add_argument("--skip-hooks", action="store_true", help="Do not refresh Codex Watcher hooks.")
    parser.add_argument("--skip-doctor", action="store_true", help="Do not run the Codex Watcher doctor.")
    parser.add_argument(
        "--migrate-marketplace",
        action="store_true",
        help="Apply the registry-owned retired Codex marketplace migration after bounded confirmation.",
    )
    parser.add_argument(
        "--migrate-from-repo",
        help=(
            "Codex-only former oh-my-harness checkout root whose exact managed "
            "registry instruction source symlink may be replaced after live confirmation."
        ),
    )
    parser.add_argument("--operation-id", help=argparse.SUPPRESS)
    parser.add_argument("--non-interactive", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm missing-instructions creation and exact managed-stale prune plans.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Force same-version Codex plugin re-materialization after source validation.",
    )
    args = parser.parse_args()

    codex_home = expand_path(args.codex_home)
    try:
        manager_home = resolve_manager_home(args.home)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    venv_path = (
        expand_path(args.venv)
        if args.venv
        else manager_venv_path(manager_home)
    )
    tooling_python = tooling_python_from_args(args, venv_path)
    env = build_env(
        codex_home=codex_home,
        tooling_python=tooling_python,
        manager_home=manager_home,
    )
    registry_environment = dict(os.environ)
    registry_environment["CODEX_HOME"] = str(codex_home)
    try:
        registry = load_harness_registry(expand_path(args.registry), repo_root=REPO_ROOT)
        plan = resolve_harness_plan(
            registry,
            args.harness,
            repo_root=REPO_ROOT,
            environ=registry_environment,
        )
    except HarnessRegistryError as exc:
        raise SystemExit(str(exc)) from exc

    if plan.harness_id != "codex":
        codex_only_options = []
        if args.git_marketplace_source is not None:
            codex_only_options.append("--git-marketplace-source")
        if args.git_ref is not None:
            codex_only_options.append("--git-ref")
        if args.marketplace_source is not None:
            codex_only_options.append("--marketplace-source")
        if args.migrate_marketplace:
            codex_only_options.append("--migrate-marketplace")
        if args.migrate_from_repo is not None:
            codex_only_options.append("--migrate-from-repo")
        if codex_only_options:
            raise SystemExit(
                "Codex marketplace options require --harness codex: "
                + ", ".join(codex_only_options)
            )
        irrelevant_skips = []
        if args.skip_agents:
            irrelevant_skips.append("--skip-agents")
        if args.skip_hooks:
            irrelevant_skips.append("--skip-hooks")
        if args.skip_doctor:
            irrelevant_skips.append("--skip-doctor")
        if irrelevant_skips:
            raise SystemExit(
                "Codex runtime-extra options require --harness codex: "
                + ", ".join(irrelevant_skips)
            )

    catalog = load_repo_skill_catalog()
    require_excluded_skill_roots_clear(catalog, plan.excluded_skill_roots)
    explicit_former_instruction_sources: tuple[Path, ...] = ()
    retired_repo: Path | None = None
    if args.migrate_from_repo is not None:
        retired_repo = expand_path(args.migrate_from_repo)
        if not retired_repo.is_absolute():
            raise SystemExit(
                "--migrate-from-repo must be an absolute path: "
                f"{args.migrate_from_repo!r}"
            )
        if retired_repo.resolve(strict=False) == REPO_ROOT.resolve(strict=False):
            raise SystemExit("--migrate-from-repo must identify a former checkout")
        try:
            current_relative = plan.instructions_source.relative_to(REPO_ROOT)
            peer_relative = plan.instructions_migration.peer_source.relative_to(
                REPO_ROOT
            )
        except ValueError as exc:  # pragma: no cover - registry resolution owns this
            raise SystemExit(
                "registry instruction migration sources are outside the repository"
            ) from exc
        explicit_former_instruction_sources = (
            retired_repo / current_relative,
            retired_repo / peer_relative,
        )
    managed_instruction_digests = operation_instruction_digests(
        manager_home,
        args.operation_id,
    )
    prepared_instructions = prepare_instruction_sync(
        plan,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        non_interactive=args.non_interactive,
        explicit_former_sources=explicit_former_instruction_sources,
        operation_managed_digests=managed_instruction_digests,
    )
    marketplace_name: str | None = None
    if plan.harness_id == "codex":
        if plan.marketplace_path is None or plan.install_manifest_path is None:
            raise SystemExit("codex harness did not resolve marketplace metadata paths")
        manifest = load_install_manifest(plan.install_manifest_path)
        raw_marketplace_name = manifest.get("marketplace")
        if not isinstance(raw_marketplace_name, str) or not raw_marketplace_name.strip():
            raise SystemExit(
                "install manifest marketplace must be a non-empty string: "
                f"{plan.install_manifest_path}"
            )
        marketplace_name = raw_marketplace_name.strip()

    codex: str | None = None
    prune_plan = CodexPrunePlan(configured=frozenset(), cached=frozenset())
    retired_states: tuple[RetiredMarketplaceState, ...] = ()
    if plan.harness_id == "codex":
        assert marketplace_name is not None
        migration = plan.harness.skills.marketplace_migration
        if migration is None:
            raise SystemExit("codex harness has no registry-owned marketplace migration policy")
        retired_states = retired_marketplace_states(
            plan.root,
            migration.retired_marketplace_names,
        )
        desired_plugin_names = default_plugin_names(
            "install",
            marketplace_name=marketplace_name,
            manifest_file=plan.install_manifest_path,
            marketplace_file=plan.marketplace_path,
        )
        prune_plan = plugin_prune_plan(
            codex_home=plan.root,
            marketplace_name=marketplace_name,
            desired_plugin_names=desired_plugin_names,
        )
        preflight_codex_distribution(
            catalog,
            codex_home=plan.root,
            marketplace_name=marketplace_name,
            marketplace_file=plan.marketplace_path,
            manifest_file=plan.install_manifest_path,
            ignored_stale_cache_plugins=prune_plan.cached,
        )
        codex = resolve_codex_executable(args.codex, codex_home=plan.root)
        require_codex_plugin_commands(
            codex,
            env=env,
            require_marketplace=True,
            require_add=True,
            require_list=True,
            require_remove=bool(prune_plan.names or retired_states),
        )
        if retired_states:
            require_codex_subcommand(
                codex,
                "plugin marketplace remove",
                ["plugin", "marketplace", "remove"],
                env=env,
            )
        confirm_retired_marketplace_migration(
            retired_states,
            requested=args.migrate_marketplace,
            dry_run=args.dry_run,
            assume_yes=args.yes,
        )
        retired_states = detach_relocated_retired_marketplace_sources(
            codex,
            codex_home=plan.root,
            states=retired_states,
            retired_repo=retired_repo,
            env=env,
            dry_run=args.dry_run,
        )
        _enabled_codex_harness_plugins(
            catalog,
            codex=codex,
            marketplace_name=marketplace_name,
            env=env,
            ignored_unclassified=set(prune_plan.configured),
            ignored_alternate_marketplaces={state.name for state in retired_states},
        )
        confirm_codex_prune(
            prune_plan,
            marketplace_name=marketplace_name,
            confirmation=plan.harness.skills.reconciliation.confirmation,
            dry_run=args.dry_run,
            assume_yes=args.yes,
        )

    if plan.harness.skills.driver == "directory-projection":
        expected_materialization = (
            "directory-junction" if os.name == "nt" else "directory-symlink"
        )
        if plan.skills_materialization != expected_materialization:
            raise SystemExit(
                "selected directory projection materialization is unsupported by the current driver: "
                f"{plan.skills_materialization!r}"
            )

    if not args.skip_bootstrap:
        run_tooling_bootstrap(venv_path=venv_path, env=env, dry_run=args.dry_run)

    if plan.harness_id == "codex":
        assert codex is not None
        assert marketplace_name is not None
        git_ref = args.git_ref or "main"
        git_request_explicit = (
            args.git_marketplace_source is not None or args.git_ref is not None
        )
        git_source = args.git_marketplace_source
        if git_request_explicit and not git_source:
            git_source = git_remote_source(REPO_ROOT)
        marketplace_source_binding = ensure_marketplace_source(
            codex,
            codex_home=plan.root,
            marketplace_name=marketplace_name,
            git_source=git_source,
            git_ref=git_ref,
            git_request_explicit=git_request_explicit,
            local_source=args.marketplace_source or str(REPO_ROOT),
            env=env,
            dry_run=args.dry_run,
        )
        if prune_plan.names:
            prune_stale_plugins(
                codex,
                codex_home=plan.root,
                marketplace_name=marketplace_name,
                plan=prune_plan,
                env=env,
                dry_run=args.dry_run,
            )
        apply_codex_harness(
            catalog,
            codex=codex,
            codex_home=plan.root,
            marketplace_name=marketplace_name,
            excluded_skill_roots=plan.excluded_skill_roots,
            marketplace_file=plan.marketplace_path,
            manifest_file=plan.install_manifest_path,
            marketplace_source_binding=marketplace_source_binding,
            env=env,
            dry_run=args.dry_run,
            repair=args.repair,
            ignored_stale_cache_plugins=(prune_plan.cached if args.dry_run else None),
            ignored_stale_enabled_plugins=(
                prune_plan.configured if args.dry_run else None
            ),
            ignored_alternate_marketplaces={state.name for state in retired_states},
        )
        apply_retired_marketplace_migration(
            codex,
            codex_home=plan.root,
            states=retired_states,
            env=env,
            dry_run=args.dry_run,
        )
        if retired_states and not args.dry_run:
            _, plugin_sources = preflight_codex_distribution(
                catalog,
                codex_home=plan.root,
                marketplace_name=marketplace_name,
                marketplace_file=plan.marketplace_path,
                manifest_file=plan.install_manifest_path,
            )
            require_harness_closure(
                "Codex post-migration",
                plugin_installation_issues(
                    catalog,
                    marketplace_name=marketplace_name,
                    excluded_skill_roots=plan.excluded_skill_roots,
                    codex_home=plan.root,
                    rows=read_codex_plugin_rows(
                        codex,
                        marketplace_name=marketplace_name,
                        plugin_names=set(catalog.plugin_names),
                        env=env,
                    ),
                    plugin_sources=plugin_sources,
                ),
            )
    else:
        if plan.skills_root is None:
            raise SystemExit(f"harness {plan.harness_id} has no skills projection root")
        sync_layer(
            catalog,
            target_root=plan.skills_root,
            dry_run=args.dry_run,
            prune=plan.harness.skills.reconciliation.prune_policy == "managed-stale",
        )

    apply_instruction_sync(prepared_instructions, dry_run=args.dry_run)

    if "codex-agent-support" in plan.harness.extras and not args.skip_agents:
        run_agent_sync(codex_home=plan.root, env=env, dry_run=args.dry_run)

    watcher_cli = REPO_ROOT / "plugins" / "watcher" / "scripts" / "watcher"
    if "watcher-hooks" in plan.harness.extras and not args.skip_hooks:
        if not args.dry_run and not tooling_python.is_file():
            raise SystemExit(f"tooling Python does not exist: {tooling_python}")
        if not watcher_cli.is_file():
            raise SystemExit(f"Watcher CLI does not exist: {watcher_cli}")
        run(
            [
                str(tooling_python),
                str(watcher_cli),
                "skill",
                "install-hook",
                "--apply",
                "--python",
                str(tooling_python),
                "--repo-root",
                str(REPO_ROOT),
            ],
            env=env,
            dry_run=args.dry_run,
        )

    if "watcher-doctor" in plan.harness.extras and not args.skip_doctor:
        if not args.dry_run and not tooling_python.is_file():
            raise SystemExit(f"tooling Python does not exist: {tooling_python}")
        if not watcher_cli.is_file():
            raise SystemExit(f"Watcher CLI does not exist: {watcher_cli}")
        run(
            [
                str(tooling_python),
                str(watcher_cli),
                "skill",
                "doctor",
                "--repo-root",
                str(REPO_ROOT),
            ],
            env=env,
            dry_run=args.dry_run,
        )

    if args.dry_run:
        print(f"dry-run only; no changes written (harness: {plan.harness_id})")
    else:
        print(f"refresh complete (harness: {plan.harness_id})")
        if "watcher-hooks" in plan.harness.extras and not args.skip_hooks:
            print("open /hooks in Codex to review and trust refreshed Watcher skill command hooks")


def cli() -> int:
    try:
        main()
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        message = str(exc.code)
        if message.startswith("action required:"):
            write_stderr(message, color="yellow")
        else:
            write_stderr(
                message if message.startswith("error:") else f"error: {message}"
            )
        return 1
    except Exception as exc:
        write_stderr(
            f"error: unexpected refresh failure ({type(exc).__name__}): {exc}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
