#!/usr/bin/env python3
"""Run final closure checks for one registry-selected harness distribution."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from check_skill_discovery import (
    PluginListRow,
    codex_plugin_rows,
    excluded_skill_root_issues,
    marketplace_plugin_sources,
    plugin_installation_issues,
    plugin_package_issues,
)
from harness_registry import (
    REGISTRY_FILE,
    HarnessPlan,
    HarnessRegistryError,
    ensure_codex_harness_covers_catalog,
    load_harness_registry,
    resolve_harness_plan,
)
from refresh_harness import (
    CODEX_HOME,
    MANAGER_HOME,
    REPO_ROOT,
    build_env,
    cached_plugin_names,
    command_text,
    configured_marketplace_source_binding,
    configured_plugin_names,
    expand_path,
    load_install_manifest,
    marketplace_source_binding_issues,
    resolve_codex_executable,
    retired_marketplace_states,
    codex_plugin_selectors,
    stale_plugin_names,
    tooling_python_from_args,
)
from manager_paths import manager_home as resolve_manager_home
from manager_paths import venv_path as manager_venv_path
from repo_skill_catalog import SkillCatalog, load_repo_skill_catalog
from sync_harness_instructions import check_instruction_sync


WATCHER_SCRIPTS = REPO_ROOT / "plugins" / "watcher" / "scripts"
sys.path.insert(0, str(WATCHER_SCRIPTS))

from watcher_runtime.skill.codex_hook_config import HOOK_EVENTS, adapter_path, load_config  # noqa: E402
from watcher_runtime.skill.doctor import find_managed_hook_issues  # noqa: E402


def configure_output_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def decode_subprocess_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")


def print_text(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe = message.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
        print(safe)


class CheckRunner:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    def ok(self, message: str) -> None:
        print_text(f"OK   {message}")

    def warn(self, message: str) -> None:
        self.warnings += 1
        print_text(f"WARN {message}")

    def fail(self, message: str) -> None:
        self.failures += 1
        print_text(f"FAIL {message}")

    def run_command(self, command: list[str], *, env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        print("+ " + command_text(command), flush=True)
        try:
            result = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, capture_output=True)
            return subprocess.CompletedProcess(
                command,
                result.returncode,
                decode_subprocess_output(result.stdout),
                decode_subprocess_output(result.stderr),
            )
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(command, 127, "", f"command not found: {exc.filename}")
        except PermissionError as exc:
            return subprocess.CompletedProcess(command, 126, "", f"command not executable: {command[0]}: {exc}")

    def check_marketplace_file(
        self,
        expected_plugins: list[str],
        *,
        source_root: Path = REPO_ROOT,
        marketplace_file: Path | None = None,
    ) -> dict[str, Path] | None:
        try:
            marketplace_name, sources = marketplace_plugin_sources(
                source_root,
                marketplace_file=marketplace_file,
            )
        except ValueError as exc:
            self.fail(str(exc))
            return None
        selector_marketplaces = {selector.partition("@")[2] for selector in expected_plugins if "@" in selector}
        if selector_marketplaces != {marketplace_name}:
            self.fail(
                f"marketplace name mismatch: catalog has {marketplace_name!r}, "
                f"selectors require {', '.join(sorted(selector_marketplaces)) or 'none'}"
            )
            return None
        present = set(sources)
        expected = {selector.split("@", 1)[0] for selector in expected_plugins}
        missing = sorted(expected - present)
        if missing:
            self.fail(f"marketplace is missing plugins: {', '.join(missing)}")
            return None
        marketplace = marketplace_file or (
            source_root / ".agents" / "plugins" / "marketplace.json"
        )
        self.ok(f"marketplace file includes exact local plugin identities: {marketplace}")
        return sources

    def check_marketplace_source_binding(
        self,
        catalog: SkillCatalog,
        *,
        codex_home: Path,
        marketplace_name: str,
    ) -> None:
        try:
            binding = configured_marketplace_source_binding(codex_home, marketplace_name)
        except ValueError as exc:
            self.fail(str(exc))
            return
        issues = marketplace_source_binding_issues(catalog, binding)
        if issues:
            for issue in issues:
                self.fail(issue)
            return
        self.ok("configured marketplace is bound to the validated repository source")

    def check_retired_marketplaces(
        self,
        *,
        codex_home: Path,
        retired_names: tuple[str, ...],
    ) -> None:
        states = retired_marketplace_states(codex_home, retired_names)
        if states:
            for state in states:
                self.fail(
                    "retired marketplace state remains: "
                    f"{state.name} (configured={sorted(state.configured_plugins)}, "
                    f"cached={sorted(state.cached_plugins)}, source={dict(state.source_config)})"
                )
            return
        self.ok("retired marketplace config and cache state are absent")

    def check_plugin_packages(
        self,
        catalog: SkillCatalog,
        *,
        plugin_sources: dict[str, Path],
    ) -> None:
        issues = plugin_package_issues(catalog, plugin_sources=plugin_sources)
        if issues:
            for issue in issues:
                self.fail(issue)
            return
        self.ok("marketplace package sources match the repository callable catalog")

    def check_tooling_python(self, tooling_python: Path, *, env: dict[str, str]) -> None:
        if not tooling_python.is_file():
            self.fail(f"tooling Python missing: {tooling_python}")
            return
        result = self.run_command([str(tooling_python), "-c", "import yaml; print(yaml.__version__)"], env=env)
        if result.returncode == 0:
            self.ok(f"tooling Python imports PyYAML: {tooling_python} ({result.stdout.strip()})")
        else:
            output = (result.stderr or result.stdout).strip()
            self.fail(f"tooling Python cannot import PyYAML: {tooling_python}: {output}")

    def read_plugin_rows(
        self,
        codex: str,
        *,
        marketplace_name: str,
        plugin_names: set[str],
        env: dict[str, str],
    ) -> dict[tuple[str, str], PluginListRow] | None:
        result = self.run_command(
            [codex, "plugin", "list", "--json", "--available"],
            env=env,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()
            self.fail(f"`codex plugin list` failed: {output}")
            return None
        try:
            return codex_plugin_rows(
                result.stdout,
                marketplace_name=marketplace_name,
                plugin_names=plugin_names,
            )
        except ValueError as exc:
            self.fail(f"failed to parse `codex plugin list` output: {exc}")
            return None

    def check_excluded_skill_roots(
        self,
        catalog: SkillCatalog,
        *,
        roots: tuple[Path, ...],
    ) -> None:
        issues = excluded_skill_root_issues(catalog, roots=roots)
        if issues:
            for issue in issues:
                self.fail(issue)
            cleanup = REPO_ROOT / "scripts" / "sync_agents_skills.py"
            for root in roots:
                base = [
                    sys.executable,
                    str(cleanup),
                    "--repo-root",
                    str(catalog.repo_root),
                    "--target-root",
                    str(root),
                    "--remove-managed",
                ]
                print_text("     preview: " + command_text([*base, "--dry-run"]))
                print_text("     apply after review: " + command_text([*base, "--yes"]))
            return
        self.ok("excluded skill roots contain no repository catalog identities")

    def check_codex_harness(
        self,
        catalog: SkillCatalog,
        *,
        codex_home: Path,
        marketplace_name: str,
        rows: dict[tuple[str, str], PluginListRow],
        plugin_sources: dict[str, Path],
    ) -> None:
        issues = plugin_installation_issues(
            catalog,
            marketplace_name=marketplace_name,
            excluded_skill_roots=(),
            codex_home=codex_home,
            rows=rows,
            plugin_sources=plugin_sources,
        )
        if issues:
            for issue in issues:
                self.fail(issue)
            return
        self.ok("Codex harness matches repository, CLI, and cache")

    def check_no_stale_managed_plugins(
        self,
        plugins: list[str],
        *,
        codex_home: Path,
        marketplace_name: str,
    ) -> None:
        desired = [selector.split("@", 1)[0] for selector in plugins]
        stale = stale_plugin_names(
            codex_home=codex_home,
            marketplace_name=marketplace_name,
            desired_plugin_names=desired,
        )
        if stale:
            configured = configured_plugin_names(codex_home, marketplace_name)
            cached = cached_plugin_names(codex_home, marketplace_name)
            details = []
            for name in stale:
                locations = []
                if name in configured:
                    locations.append("config")
                if name in cached:
                    locations.append("cache")
                details.append(f"{name} ({'+'.join(locations) or 'unknown'})")
            self.fail(
                "stale managed atm-harness plugins remain. "
                "Run scripts/refresh_harness.py --harness codex. "
                f"Stale={', '.join(details)}"
            )
            return
        self.ok("no stale atm-harness plugin config or cache entries remain")

    def check_harness_instructions(self, plan: HarnessPlan) -> None:
        if plan.instructions_target is None:
            self.ok(f"harness {plan.harness_id} manages skills only; no global instructions target")
            return
        issues = check_instruction_sync(plan)
        if issues:
            for issue in issues:
                self.fail(issue)
            return
        self.ok(f"global instructions match for harness {plan.harness_id}")

    def check_hook_config(self, tooling_python: Path, *, hook_config: Path) -> None:
        if not hook_config.is_file():
            self.fail(f"Watcher skill hook config missing: {hook_config}")
            return
        try:
            config = load_config(hook_config)
        except SystemExit as exc:
            self.fail(str(exc))
            return
        matched_events, issues = find_managed_hook_issues(
            config,
            python_path=tooling_python,
            adapter=adapter_path(REPO_ROOT),
            repo_root=REPO_ROOT,
        )
        if issues:
            self.fail(
                "Watcher skill hook config has stale managed handlers. "
                "Run scripts/refresh_harness.py with the same harness. "
                f"Issues: {issues}"
            )
            return
        expected = set(HOOK_EVENTS)
        if matched_events != expected:
            self.fail(
                "Watcher skill hook config event coverage mismatch: "
                f"expected {sorted(expected)}, found {sorted(matched_events)}"
            )
            return
        self.ok(f"Watcher skill hooks match current schema: {hook_config}")

    def check_plugin_validation(
        self,
        tooling_python: Path,
        plugins: list[str],
        *,
        env: dict[str, str],
        validator: Path,
    ) -> None:
        plugin_names = [selector.split("@", 1)[0] for selector in plugins]
        if plugin_names and not validator.is_file():
            self.fail(f"plugin validator missing: {validator}")
            return
        for plugin_name in plugin_names:
            command = [
                str(tooling_python),
                str(validator),
                str(REPO_ROOT / "plugins" / plugin_name),
            ]
            result = self.run_command(command, env=env)
            if result.returncode == 0:
                self.ok(f"plugin validation passed: {plugin_name}")
            else:
                output = (result.stderr or result.stdout).strip()
                self.fail(f"plugin validation failed for {plugin_name}: {output}")

    def check_doctor(self, tooling_python: Path, *, env: dict[str, str]) -> None:
        watcher = REPO_ROOT / "plugins" / "watcher" / "scripts" / "watcher"
        result = self.run_command(
            [
                str(tooling_python),
                str(watcher),
                "skill",
                "doctor",
                "--repo-root",
                str(REPO_ROOT),
            ],
            env=env,
        )
        if result.returncode == 0:
            self.ok("Watcher skill doctor passed")
        else:
            output = (result.stderr or result.stdout).strip()
            self.fail(f"Watcher skill doctor failed: {output}")

    def check_agent_sync(self, *, codex_home: Path, env: dict[str, str]) -> None:
        sync_script = REPO_ROOT / "scripts" / "sync_codex_agents.py"
        if not sync_script.is_file():
            self.fail(f"agent sync script missing: {sync_script}")
            return
        result = self.run_command(
            [sys.executable, str(sync_script), "--check", "--prune", "--codex-home", str(codex_home)],
            env=env,
        )
        if result.returncode == 0:
            self.ok(f"subagent support file is synced: {codex_home / 'agents'}")
        else:
            output = (result.stderr or result.stdout).strip()
            self.fail(f"subagent support file is not synced: {output}")

    def check_skill_projection(
        self,
        tooling_python: Path,
        *,
        target_root: Path,
        env: dict[str, str],
    ) -> None:
        sync_script = REPO_ROOT / "scripts" / "sync_agents_skills.py"
        if not sync_script.is_file():
            self.fail(f"skills projection sync script missing: {sync_script}")
            return
        result = self.run_command(
            [
                str(tooling_python),
                str(sync_script),
                "--repo-root",
                str(REPO_ROOT),
                "--target-root",
                str(target_root),
                "--check",
                "--prune",
            ],
            env=env,
        )
        if result.returncode == 0:
            self.ok("skills projection is synced")
        else:
            output = (result.stderr or result.stdout).strip()
            self.fail(f"skills projection is not synced: {output}")

    def check_watcher_runtime_cutover(self, *, codex_home: Path) -> None:
        legacy_roots = [codex_home / "skill-watcher", codex_home / "doc-watcher"]
        existing = [path for path in legacy_roots if path.exists()]
        if existing:
            self.fail(
                "legacy Watcher runtime roots still exist. "
                "Run plugins/watcher/scripts/watcher migrate-state --apply. "
                f"Existing={'; '.join(str(path) for path in existing)}"
            )
            return
        self.ok("legacy Watcher runtime roots are absent")

    def finish(self, *, strict_warnings: bool) -> None:
        if strict_warnings and self.warnings:
            self.failures += self.warnings
        if self.failures:
            raise SystemExit(f"check failed with {self.failures} failure(s), {self.warnings} warning(s)")
        print(f"check passed with {self.warnings} warning(s)")


def main() -> None:
    configure_output_streams()

    parser = argparse.ArgumentParser(description="Check one registry-selected harness distribution.")
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
        help="atm-harness manager home (default: ATM_HOME or ~/.atm).",
    )
    parser.add_argument(
        "--venv",
        help="Shared tooling venv path (default: <manager home>/venv).",
    )
    parser.add_argument("--python", help="Explicit tooling Python expected in hooks and diagnostics.")
    parser.add_argument("--skip-hooks", action="store_true", help="Skip Codex Watcher hook checks.")
    parser.add_argument("--skip-agents", action="store_true", help="Skip Codex subagent support-file checks.")
    parser.add_argument("--skip-plugin-validation", action="store_true", help="Skip Codex package validation.")
    parser.add_argument("--skip-doctor", action="store_true", help="Skip the Codex Watcher doctor.")
    parser.add_argument("--strict-warnings", action="store_true", help="Treat warnings as failures.")
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
        irrelevant = []
        if args.skip_hooks:
            irrelevant.append("--skip-hooks")
        if args.skip_agents:
            irrelevant.append("--skip-agents")
        if args.skip_plugin_validation:
            irrelevant.append("--skip-plugin-validation")
        if args.skip_doctor:
            irrelevant.append("--skip-doctor")
        if irrelevant:
            raise SystemExit(
                "Codex-only check options require --harness codex: " + ", ".join(irrelevant)
            )

    catalog = load_repo_skill_catalog()
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
    if plan.harness_id == "codex":
        codex = resolve_codex_executable(args.codex, codex_home=plan.root)

    source_plugins = (
        [f"{plugin_name}@{marketplace_name}" for plugin_name in catalog.plugin_names]
        if marketplace_name is not None
        else []
    )
    validator = Path(env["PLUGIN_VALIDATOR"])
    runner = CheckRunner()
    runner.check_tooling_python(tooling_python, env=env)
    runner.check_excluded_skill_roots(catalog, roots=plan.excluded_skill_roots)

    if plan.harness_id == "codex":
        assert codex is not None
        assert marketplace_name is not None
        migration = plan.harness.skills.marketplace_migration
        if migration is None:
            runner.fail("codex harness has no registry-owned marketplace migration policy")
        else:
            runner.check_retired_marketplaces(
                codex_home=plan.root,
                retired_names=migration.retired_marketplace_names,
            )
        runner.check_marketplace_source_binding(
            catalog,
            codex_home=plan.root,
            marketplace_name=marketplace_name,
        )
        desired_plugins = codex_plugin_selectors(
            marketplace_name,
            action="check",
            manifest_file=plan.install_manifest_path,
            marketplace_file=plan.marketplace_path,
        )
        ensure_codex_harness_covers_catalog(
            catalog,
            desired_plugins,
            marketplace_name=marketplace_name,
        )
        plugin_sources = runner.check_marketplace_file(
            desired_plugins,
            marketplace_file=plan.marketplace_path,
        )
        rows = runner.read_plugin_rows(
            codex,
            marketplace_name=marketplace_name,
            plugin_names=set(catalog.plugin_names),
            env=env,
        )
        # Complete installation closure includes source validation. If CLI
        # discovery fails, still report source defects independently.
        if plugin_sources is not None and rows is None:
            runner.check_plugin_packages(catalog, plugin_sources=plugin_sources)
        if plugin_sources is not None and rows is not None:
            runner.check_codex_harness(
                catalog,
                codex_home=plan.root,
                marketplace_name=marketplace_name,
                rows=rows,
                plugin_sources=plugin_sources,
            )
        runner.check_no_stale_managed_plugins(
            desired_plugins,
            codex_home=plan.root,
            marketplace_name=marketplace_name,
        )
    else:
        if plan.skills_root is None:
            runner.fail(f"harness has no skills projection root: {plan.harness_id}")
        else:
            runner.check_skill_projection(
                tooling_python,
                target_root=plan.skills_root,
                env=env,
            )

    runner.check_harness_instructions(plan)
    if "watcher-hooks" in plan.harness.extras and not args.skip_hooks:
        runner.check_hook_config(tooling_python, hook_config=plan.root / "hooks.json")
    if plan.harness.extras:
        runner.check_watcher_runtime_cutover(codex_home=plan.root)
    if "codex-agent-support" in plan.harness.extras and not args.skip_agents:
        runner.check_agent_sync(codex_home=plan.root, env=env)
    if plan.harness_id == "codex" and not args.skip_plugin_validation:
        runner.check_plugin_validation(
            tooling_python,
            source_plugins,
            env=env,
            validator=validator,
        )
    if "watcher-doctor" in plan.harness.extras and not args.skip_doctor:
        runner.check_doctor(tooling_python, env=env)
    runner.finish(strict_warnings=args.strict_warnings)


if __name__ == "__main__":
    main()
