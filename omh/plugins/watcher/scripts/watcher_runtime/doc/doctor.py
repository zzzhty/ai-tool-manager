#!/usr/bin/env python3
"""Check Watcher doc-domain plugin, config, and runtime basics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit_repo import (
    FINDING_POLICIES,
    AuditFailure,
    expand_path,
    normalize_link_validation,
    paths_use_repo_skill_root,
    require_git_repo,
    resolve_repo_skill_root,
    resolve_state_dir,
)
from .audit_runtime import (
    authority_paths,
    docs_paths,
    load_config,
    repo_uses_resolved_skill_root,
    skill_root_candidates,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = REPO_ROOT / "config" / "repos.json"
EXAMPLE_CONFIG = REPO_ROOT / "config" / "repos.example.json"


class Doctor:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def ok(self, message: str) -> None:
        print(f"ok: {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"warn: {message}")

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"fail: {message}")

    def check_file(self, path: Path, label: str) -> None:
        if path.exists():
            self.ok(f"{label}: {path}")
        else:
            self.fail(f"{label} missing: {path}")

    def check_plugin(self) -> None:
        manifest = REPO_ROOT / ".codex-plugin" / "plugin.json"
        self.check_file(manifest, "plugin manifest")
        if not manifest.exists():
            return
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self.fail(
                f"invalid plugin manifest JSON: line {exc.lineno}, column {exc.colno}"
            )
            return
        if data.get("name") != "watcher":
            self.fail("plugin manifest name must be watcher")
        elif data.get("skills") == "./skills/":
            self.ok("plugin manifest points at skills/")
        else:
            self.fail("plugin manifest must point skills to ./skills/")

    def check_layout(self) -> None:
        self.check_file(
            REPO_ROOT / "skills" / "doc-alignment" / "SKILL.md", "audit skill"
        )
        self.check_file(
            REPO_ROOT / "skills" / "housekeeping" / "SKILL.md", "housekeeping skill"
        )
        self.check_file(
            REPO_ROOT
            / "skills"
            / "doc-alignment"
            / "scripts"
            / "check_planning_tree.py",
            "planning-tree helper",
        )
        self.check_file(REPO_ROOT / "scripts" / "watcher", "Watcher CLI adapter")
        runtime = REPO_ROOT / "scripts" / "watcher_runtime" / "doc"
        for name in ("audit_repo.py", "report.py", "commit_counter.py", "doctor.py"):
            self.check_file(runtime / name, f"doc runtime {name}")

    def check_state_dir(self, state_dir: Path) -> None:
        try:
            (state_dir / "reports").mkdir(parents=True, exist_ok=True)
            (state_dir / "audits").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.fail(
                f"cannot create runtime state directories under {state_dir}: {exc}"
            )
            return
        self.ok(f"runtime state dir writable: {state_dir}")

    def check_config(self, config_path: Path | None) -> None:
        if config_path is None:
            if DEFAULT_CONFIG.exists():
                config_path = DEFAULT_CONFIG
            elif EXAMPLE_CONFIG.exists():
                self.warn(
                    f"private config missing; example config exists: {EXAMPLE_CONFIG}"
                )
                config_path = EXAMPLE_CONFIG
            else:
                self.fail(f"no config found: {DEFAULT_CONFIG} or {EXAMPLE_CONFIG}")
                return

        try:
            config = load_config(config_path)
        except AuditFailure as exc:
            self.fail(str(exc))
            return
        self.ok(f"config loaded: {config_path}")
        for repo in config["repos"]:
            name = str(repo.get("name") or repo.get("path") or "repo")
            if "source_of_truth" in repo:
                self.warn(
                    f"repo {name} uses deprecated source_of_truth; rename it to authority_paths"
                )
            try:
                configured_authority_paths = authority_paths(repo)
                configured_docs = docs_paths(repo)
                candidates = skill_root_candidates(repo)
                normalize_link_validation(repo.get("link_validation"))
            except AuditFailure as exc:
                self.fail(f"repo {name} invalid profile config: {exc}")
                continue
            finding_policy = str(repo.get("finding_policy") or "actionable")
            if finding_policy not in FINDING_POLICIES:
                allowed = ", ".join(sorted(FINDING_POLICIES))
                self.fail(f"repo {name} finding_policy must be one of: {allowed}")
                continue
            path = repo.get("path")
            if not path:
                self.fail(f"repo {name} missing path")
                continue
            try:
                root = require_git_repo(expand_path(str(path)))
                skill_root = resolve_repo_skill_root(root, candidates)
            except AuditFailure as exc:
                self.fail(f"repo {name} invalid: {exc}")
                continue
            self.ok(f"repo {name}: {root}")
            if not repo_uses_resolved_skill_root(repo):
                continue
            selected = skill_root["selected"]
            token_configured = paths_use_repo_skill_root(
                configured_docs
            ) or paths_use_repo_skill_root(configured_authority_paths)
            if selected is None and token_configured:
                self.fail(
                    f"repo {name} cannot resolve @repo-skills from: "
                    + ", ".join(skill_root["candidates"])
                )
                continue
            if selected is None:
                self.warn(f"repo {name} has no detected repository skill root")
                continue
            self.ok(f"repo {name} selected repository skill root: {selected}")
            if skill_root["shadowed"]:
                self.warn(
                    f"repo {name} shadowed repository skill roots: "
                    + ", ".join(skill_root["shadowed"])
                )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watcher doc doctor",
        description="Check Watcher doc-domain plugin, config, and runtime basics.",
    )
    parser.add_argument(
        "--config",
        help="Repo config JSON path. Defaults to config/repos.json, then example config.",
    )
    parser.add_argument(
        "--state-dir",
        help="Runtime state directory. Defaults to $CODEX_HOME/watcher/doc.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    doctor = Doctor()
    doctor.check_plugin()
    doctor.check_layout()
    doctor.check_state_dir(resolve_state_dir(args.state_dir))
    doctor.check_config(expand_path(args.config) if args.config else None)
    if doctor.failures:
        print()
        print(
            f"doctor failed: {len(doctor.failures)} failure(s), {len(doctor.warnings)} warning(s)"
        )
        return 1
    print()
    print(f"doctor passed: {len(doctor.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
