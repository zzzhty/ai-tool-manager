#!/usr/bin/env python3
"""Collect read-only documentation drift evidence for one local Git repo."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
DEFAULT_STATE_DIR = CODEX_HOME / "watcher" / "doc"
ENTRY_FILES = (
    "README.md",
    "AGENTS.md",
    "CONTEXT.md",
    "CHANGELOG.md",
    "TODO.md",
    "todo.md",
)
DOC_DIRS = ("docs", "dev_docs", "wiki")
REPO_SKILL_ROOT_TOKEN = "@repo-skills"
DEFAULT_REPO_SKILL_ROOT_CANDIDATES = (
    ".agents/skills",
    ".codex/skills",
    ".github/skills",
    ".claude/skills",
    ".grok/skills",
)
DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".txt", ".yml", ".yaml", ".json", ".toml"}
LINK_VALIDATION_MODES = {"markdown-relative", "owner-command", "none"}
FINDING_POLICIES = {"actionable", "report-only"}
CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".ps1",
    ".sql",
}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


class AuditFailure(RuntimeError):
    """Raised when a required audit step cannot be completed."""


def resolve_state_dir(raw: str | None = None) -> Path:
    return expand_path(
        raw or os.environ.get("WATCHER_DOC_STATE_DIR") or DEFAULT_STATE_DIR
    )


def expand_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(str(raw))).expanduser()


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def safe_slug(value: str) -> str:
    slug = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in value.lower()
    )
    return re.sub(r"-+", "-", slug).strip("-") or "repo"


def run_git(repo: Path, args: list[str], *, allow_failure: bool = False) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        message = (
            f"git command failed in {repo}: git {' '.join(args)}\n"
            f"exit={proc.returncode}\n"
            f"stderr={proc.stderr.strip()}"
        )
        if allow_failure:
            return ""
        raise AuditFailure(message)
    return proc.stdout.strip()


def require_git_repo(repo: Path) -> Path:
    if not repo.exists():
        raise AuditFailure(f"repo path does not exist: {repo}")
    if not repo.is_dir():
        raise AuditFailure(f"repo path is not a directory: {repo}")
    # An engine tree is identified by its harness registry: it is its own
    # repository root even when nested inside another Git repository (the
    # ATM-vendored layout) or materialized without Git at all.
    if (repo / ".agents" / "harnesses" / "registry.json").is_file():
        return repo.resolve()
    root = run_git(repo, ["rev-parse", "--show-toplevel"])
    return Path(root).resolve()


def safe_repo_path(repo: Path, rel_path: str) -> Path:
    candidate = (repo / rel_path).resolve()
    try:
        candidate.relative_to(repo)
    except ValueError as exc:
        raise AuditFailure(f"configured path escapes repo: {rel_path}") from exc
    return candidate


def normalize_skill_root_candidates(
    configured: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    raw_candidates = (
        DEFAULT_REPO_SKILL_ROOT_CANDIDATES if configured is None else configured
    )
    if not isinstance(raw_candidates, (list, tuple)) or not raw_candidates:
        raise AuditFailure("skill_root_candidates must be a non-empty string list")

    normalized: list[str] = []
    for raw in raw_candidates:
        if not isinstance(raw, str) or not raw.strip():
            raise AuditFailure("skill_root_candidates must be a non-empty string list")
        path = Path(raw.strip())
        if path.is_absolute() or ".." in path.parts:
            raise AuditFailure(
                f"skill root candidate must stay relative to the repo: {raw}"
            )
        candidate = path.as_posix().rstrip("/")
        if candidate in {"", "."}:
            raise AuditFailure(
                f"skill root candidate must name a directory below the repo: {raw}"
            )
        if candidate in normalized:
            raise AuditFailure(f"duplicate skill root candidate: {candidate}")
        normalized.append(candidate)
    return tuple(normalized)


def resolve_repo_skill_root(
    repo: Path,
    configured: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    candidates = normalize_skill_root_candidates(configured)
    detected: list[str] = []
    for rel in candidates:
        path = safe_repo_path(repo, rel)
        if path.exists() and not path.is_dir():
            raise AuditFailure(f"skill root candidate is not a directory: {rel}")
        if path.is_dir():
            detected.append(rel)
    return {
        "candidates": list(candidates),
        "detected": detected,
        "selected": detected[0] if detected else None,
        "shadowed": detected[1:],
    }


def path_uses_repo_skill_root(path: str) -> bool:
    return path == REPO_SKILL_ROOT_TOKEN or path.startswith(f"{REPO_SKILL_ROOT_TOKEN}/")


def paths_use_repo_skill_root(paths: list[str] | None) -> bool:
    return any(path_uses_repo_skill_root(path) for path in paths or [])


def expand_repo_skill_path(path: str, selected_skill_root: str | None) -> str | None:
    if not path_uses_repo_skill_root(path):
        return path
    if selected_skill_root is None:
        return None
    suffix = path.removeprefix(REPO_SKILL_ROOT_TOKEN).lstrip("/")
    if not suffix:
        return selected_skill_root
    return f"{selected_skill_root}/{suffix}"


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.parts)


def is_doc_path(path: str | Path, *, selected_skill_root: str | None = None) -> bool:
    p = Path(path)
    skill_root_parts = (
        Path(selected_skill_root).parts if selected_skill_root is not None else ()
    )
    under_selected_skill_root = bool(skill_root_parts) and (
        p.parts[: len(skill_root_parts)] == skill_root_parts
    )
    return (
        p.name in ENTRY_FILES
        or p.suffix.lower() in DOC_EXTENSIONS
        or any(part in DOC_DIRS for part in p.parts)
        or under_selected_skill_root
    )


def is_code_path(path: str | Path) -> bool:
    p = Path(path)
    return p.suffix.lower() in CODE_EXTENSIONS or any(
        part in {"scripts", "src", "app", "backend", "frontend"} for part in p.parts
    )


def discover_doc_files(
    repo: Path,
    configured: list[str] | None,
    *,
    selected_skill_root: str | None,
) -> tuple[list[Path], list[str]]:
    missing: list[str] = []
    files: list[Path] = []

    if configured:
        candidates = configured
    else:
        candidates = [name for name in ENTRY_FILES if (repo / name).exists()]
        candidates.extend(name for name in DOC_DIRS if (repo / name).exists())
        if selected_skill_root is not None:
            candidates.append(selected_skill_root)

    for rel in candidates:
        expanded = expand_repo_skill_path(rel, selected_skill_root)
        if expanded is None:
            missing.append(rel)
            continue
        path = safe_repo_path(repo, expanded)
        if not path.exists():
            missing.append(rel)
            continue
        if path.is_file():
            files.append(path)
            continue
        for child in path.rglob("*"):
            if should_skip(child.relative_to(repo)):
                continue
            if child.is_file() and child.suffix.lower() in DOC_EXTENSIONS:
                files.append(child)

    unique = sorted(set(files), key=lambda item: item.relative_to(repo).as_posix())
    return unique, missing


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AuditFailure(f"failed to read {path}: {exc}") from exc


def find_broken_links(repo: Path, doc_files: list[Path]) -> list[dict[str, Any]]:
    broken: list[dict[str, Any]] = []
    for file_path in doc_files:
        if file_path.suffix.lower() not in {".md", ".mdx"}:
            continue
        text = read_text(file_path)
        for match in LINK_PATTERN.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = target.split("#", 1)[0].strip()
            if not target:
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target_path = (file_path.parent / target).resolve()
            try:
                target_path.relative_to(repo)
            except ValueError:
                continue
            exists = (
                target_path.is_dir() if target.endswith("/") else target_path.exists()
            )
            if not exists:
                line = text[: match.start()].count("\n") + 1
                broken.append(
                    {
                        "file": file_path.relative_to(repo).as_posix(),
                        "line": line,
                        "target": match.group(1),
                    }
                )
    return broken


def find_watch_terms(
    repo: Path, doc_files: list[Path], terms: list[str]
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not terms:
        return hits
    for file_path in doc_files:
        text = read_text(file_path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            for term in terms:
                if term and term in line:
                    hits.append(
                        {
                            "file": file_path.relative_to(repo).as_posix(),
                            "line": line_no,
                            "term": term,
                        }
                    )
    return hits


def recent_commits(repo: Path, limit: int) -> list[str]:
    output = run_git(
        repo, ["log", "--oneline", "--no-decorate", f"-n{limit}"], allow_failure=True
    )
    return [line for line in output.splitlines() if line.strip()]


def changed_files(
    repo: Path, recent_limit: int, since_ref: str | None = None
) -> tuple[list[str], str]:
    if since_ref:
        output = run_git(
            repo, ["diff", "--name-only", f"{since_ref}..HEAD"], allow_failure=True
        )
        return sorted(line for line in output.splitlines() if line.strip()), since_ref

    commits = run_git(
        repo,
        ["rev-list", f"--max-count={recent_limit + 1}", "HEAD"],
        allow_failure=True,
    ).splitlines()
    if len(commits) >= 2:
        base = commits[-1]
        output = run_git(
            repo, ["diff", "--name-only", f"{base}..HEAD"], allow_failure=True
        )
        return sorted(line for line in output.splitlines() if line.strip()), base
    if len(commits) == 1:
        output = run_git(
            repo, ["show", "--name-only", "--format=", commits[0]], allow_failure=True
        )
        return sorted(line for line in output.splitlines() if line.strip()), commits[0]
    return [], "none"


def configured_authority_path_status(
    repo: Path,
    paths: list[str] | None,
    *,
    selected_skill_root: str | None,
) -> list[dict[str, Any]]:
    status: list[dict[str, Any]] = []
    for rel in paths or []:
        expanded = expand_repo_skill_path(rel, selected_skill_root)
        if expanded is None:
            status.append(
                {
                    "path": rel,
                    "resolved_path": None,
                    "exists": False,
                    "kind": "missing",
                }
            )
            continue
        path = safe_repo_path(repo, expanded)
        status.append(
            {
                "path": rel,
                "resolved_path": expanded,
                "exists": path.exists(),
                "kind": "directory"
                if path.is_dir()
                else "file"
                if path.is_file()
                else "missing",
            }
        )
    return status


def normalize_link_validation(raw: dict[str, Any] | str | None) -> dict[str, Any]:
    if raw is None:
        return {"mode": "markdown-relative"}
    if isinstance(raw, str):
        config: dict[str, Any] = {"mode": raw}
    elif isinstance(raw, dict):
        config = dict(raw)
    else:
        raise AuditFailure("link_validation must be a string or object")

    mode = str(config.get("mode") or "markdown-relative")
    if mode not in LINK_VALIDATION_MODES:
        allowed = ", ".join(sorted(LINK_VALIDATION_MODES))
        raise AuditFailure(
            f"unsupported link_validation mode {mode!r}; expected one of: {allowed}"
        )
    config["mode"] = mode

    if mode != "owner-command":
        return config

    command = config.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        raise AuditFailure(
            "owner-command link_validation requires a non-empty string-list command"
        )
    cwd = config.get("cwd", ".")
    if not isinstance(cwd, str) or not cwd:
        raise AuditFailure(
            "owner-command link_validation cwd must be a non-empty string"
        )
    timeout_seconds = config.get("timeout_seconds", 120)
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise AuditFailure(
            "owner-command link_validation timeout_seconds must be a positive integer"
        )
    config["cwd"] = cwd
    config["timeout_seconds"] = timeout_seconds
    return config


def bounded_output(value: str, *, limit: int = 2000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... output truncated by Watcher ..."


def run_owner_link_validator(repo: Path, config: dict[str, Any]) -> dict[str, Any]:
    cwd = safe_repo_path(repo, str(config["cwd"]))
    if not cwd.is_dir():
        raise AuditFailure(
            f"owner-command link_validation cwd is not a directory: {config['cwd']}"
        )
    command = list(config["command"])
    timeout_seconds = int(config["timeout_seconds"])
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except OSError as exc:
        raise AuditFailure(
            f"failed to run owner link validator {command[0]!r}: {exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        return {
            "mode": "owner-command",
            "status": "failed",
            "command": command,
            "cwd": cwd.relative_to(repo).as_posix() or ".",
            "exit_code": None,
            "timeout_seconds": timeout_seconds,
            "stdout": bounded_output(exc.stdout or ""),
            "stderr": bounded_output(exc.stderr or ""),
            "reason": "timeout",
        }
    return {
        "mode": "owner-command",
        "status": "passed" if proc.returncode == 0 else "failed",
        "command": command,
        "cwd": cwd.relative_to(repo).as_posix() or ".",
        "exit_code": proc.returncode,
        "timeout_seconds": timeout_seconds,
        "stdout": bounded_output(proc.stdout),
        "stderr": bounded_output(proc.stderr),
        "reason": "exit",
    }


def classify_finding(
    finding: dict[str, Any], *, policy: str, owner_validator: bool = False
) -> dict[str, Any]:
    if policy == "report-only":
        classification = "report-only"
    elif owner_validator:
        classification = "owner-validator"
    else:
        classification = "actionable"
    return {**finding, "classification": classification}


def build_findings(
    *,
    missing_paths: list[str],
    authority_paths: list[dict[str, Any]],
    broken_links: list[dict[str, Any]],
    watch_hits: list[dict[str, Any]],
    changed: list[str],
    link_validation: dict[str, Any],
    finding_policy: str,
    check_change_alignment: bool,
    selected_skill_root: str | None,
    shadowed_skill_roots: list[str],
    skill_scope_used: bool,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rel in missing_paths:
        findings.append(
            classify_finding(
                {
                    "severity": "High",
                    "title": "Configured documentation path is missing",
                    "evidence": rel,
                    "recommendation": "Remove the stale config entry or restore the documented path.",
                },
                policy=finding_policy,
            )
        )
    for item in authority_paths:
        if item["exists"]:
            continue
        findings.append(
            classify_finding(
                {
                    "severity": "High",
                    "title": "Configured authority path is missing",
                    "evidence": item["path"],
                    "recommendation": "Restore the authority path or update the profile configuration.",
                },
                policy=finding_policy,
            )
        )
    for item in broken_links:
        findings.append(
            classify_finding(
                {
                    "severity": "High",
                    "title": "Markdown link target does not resolve",
                    "evidence": f"{item['file']}:{item['line']} -> {item['target']}",
                    "recommendation": "Update the link or move the target into the documented location.",
                },
                policy=finding_policy,
            )
        )
    for item in watch_hits:
        findings.append(
            classify_finding(
                {
                    "severity": "Medium",
                    "title": "Configured watch term still appears in active docs",
                    "evidence": f"{item['file']}:{item['line']} contains {item['term']}",
                    "recommendation": "Confirm whether this is historical text or stale active terminology.",
                },
                policy=finding_policy,
            )
        )

    if skill_scope_used and shadowed_skill_roots:
        findings.append(
            classify_finding(
                {
                    "severity": "Medium",
                    "title": "Additional repository skill roots are shadowed",
                    "evidence": (
                        f"selected={selected_skill_root}; "
                        f"shadowed={', '.join(shadowed_skill_roots)}"
                    ),
                    "recommendation": (
                        "Consolidate repository skills under the selected root or configure "
                        "the intended documentation roots explicitly."
                    ),
                },
                policy=finding_policy,
            )
        )

    if (
        link_validation["mode"] == "owner-command"
        and link_validation["status"] == "failed"
    ):
        command = " ".join(link_validation["command"])
        findings.append(
            classify_finding(
                {
                    "severity": "High",
                    "title": "Owner link validator failed",
                    "evidence": (
                        f"cwd={link_validation['cwd']} exit={link_validation['exit_code']} command={command}"
                    ),
                    "recommendation": "Fix the owner validator failure; do not substitute generic Markdown results.",
                },
                policy=finding_policy,
                owner_validator=True,
            )
        )

    if check_change_alignment:
        docs_changed = [
            path
            for path in changed
            if is_doc_path(path, selected_skill_root=selected_skill_root)
        ]
        code_changed = [
            path
            for path in changed
            if is_code_path(path)
            and not is_doc_path(path, selected_skill_root=selected_skill_root)
        ]
        if code_changed and not docs_changed:
            findings.append(
                classify_finding(
                    {
                        "severity": "Medium",
                        "title": "Recent code or runtime changes have no matching doc changes",
                        "evidence": ", ".join(code_changed[:12])
                        + (" ..." if len(code_changed) > 12 else ""),
                        "recommendation": "Review whether active docs, commands, or architecture notes need alignment.",
                    },
                    policy=finding_policy,
                )
            )
    return findings


def audit_repository(
    *,
    repo: Path,
    name: str,
    docs: list[str] | None = None,
    profile: str = "default",
    authority_paths: list[str] | None = None,
    source_of_truth: list[str] | None = None,
    watch_terms: list[str] | None = None,
    link_validation: dict[str, Any] | str | None = None,
    finding_policy: str = "actionable",
    check_change_alignment: bool = True,
    recent_limit: int = 5,
    since_ref: str | None = None,
    skill_root_candidates: list[str] | None = None,
) -> dict[str, Any]:
    if authority_paths is not None and source_of_truth is not None:
        raise AuditFailure(
            "use authority_paths; do not configure authority_paths and legacy source_of_truth together"
        )
    if finding_policy not in FINDING_POLICIES:
        allowed = ", ".join(sorted(FINDING_POLICIES))
        raise AuditFailure(
            f"unsupported finding_policy {finding_policy!r}; expected one of: {allowed}"
        )

    root = require_git_repo(repo)
    head = run_git(root, ["rev-parse", "HEAD"])
    branch = (
        run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"], allow_failure=True)
        or "unknown"
    )
    skill_root = resolve_repo_skill_root(root, skill_root_candidates)
    selected_skill_root = skill_root["selected"]
    configured_authority_paths = (
        authority_paths if authority_paths is not None else source_of_truth
    )
    skill_scope_used = (
        not docs
        or paths_use_repo_skill_root(docs)
        or paths_use_repo_skill_root(configured_authority_paths)
    )
    doc_files, missing_paths = discover_doc_files(
        root,
        docs,
        selected_skill_root=selected_skill_root,
    )
    validation_config = normalize_link_validation(link_validation)
    if validation_config["mode"] == "markdown-relative":
        broken = find_broken_links(root, doc_files)
        validation_result = {
            "mode": "markdown-relative",
            "status": "passed" if not broken else "failed",
        }
    elif validation_config["mode"] == "owner-command":
        broken = []
        validation_result = run_owner_link_validator(root, validation_config)
    else:
        broken = []
        validation_result = {
            "mode": "none",
            "status": "not-run",
        }
    hits = find_watch_terms(root, doc_files, watch_terms or [])
    changed, diff_base = changed_files(root, recent_limit, since_ref=since_ref)
    authority_status = configured_authority_path_status(
        root,
        configured_authority_paths,
        selected_skill_root=selected_skill_root,
    )
    findings = build_findings(
        missing_paths=missing_paths,
        authority_paths=authority_status,
        broken_links=broken,
        watch_hits=hits,
        changed=changed,
        link_validation=validation_result,
        finding_policy=finding_policy,
        check_change_alignment=check_change_alignment,
        selected_skill_root=selected_skill_root,
        shadowed_skill_roots=skill_root["shadowed"],
        skill_scope_used=skill_scope_used,
    )

    return {
        "name": name,
        "profile": profile,
        "repo": str(root),
        "branch": branch,
        "head": head,
        "generated_at": now_local().isoformat(timespec="seconds"),
        "recent_limit": recent_limit,
        "diff_base": diff_base,
        "recent_commits": recent_commits(root, recent_limit),
        "changed_files": changed,
        "doc_files": [path.relative_to(root).as_posix() for path in doc_files],
        "skill_root": {**skill_root, "used": skill_scope_used},
        "authority_paths": authority_status,
        "broken_links": broken,
        "link_validation": validation_result,
        "watch_hits": hits,
        "finding_policy": finding_policy,
        "check_change_alignment": check_change_alignment,
        "findings": findings,
    }


def render_report(result: dict[str, Any]) -> str:
    findings = result["findings"]
    changed = result["changed_files"]
    selected_skill_root = result["skill_root"]["selected"]
    doc_changed = [
        path
        for path in changed
        if is_doc_path(path, selected_skill_root=selected_skill_root)
    ]
    code_changed = [
        path
        for path in changed
        if is_code_path(path)
        and not is_doc_path(path, selected_skill_root=selected_skill_root)
    ]

    lines = [
        f"# Watcher Doc Audit: {result['name']}",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Repo: `{result['repo']}`",
        f"- Profile: `{result['profile']}`",
        f"- Branch: `{result['branch']}`",
        f"- Head: `{result['head']}`",
        f"- Diff base: `{result['diff_base']}`",
        "",
        "## Summary",
        "",
        f"- Documentation files scanned: {len(result['doc_files'])}",
        f"- Recent commits listed: {len(result['recent_commits'])}",
        f"- Changed files in audit window: {len(changed)}",
        f"- Changed doc files: {len(doc_changed)}",
        f"- Changed code/runtime files: {len(code_changed)}",
        f"- Broken links: {len(result['broken_links'])}",
        f"- Link validation: {result['link_validation']['mode']} / {result['link_validation']['status']}",
        f"- Watch term hits: {len(result['watch_hits'])}",
        f"- Findings: {len(findings)}",
        f"- Finding policy: {result['finding_policy']}",
        (
            f"- Repository skill root: `{selected_skill_root}`"
            if selected_skill_root is not None
            else "- Repository skill root: none detected"
        ),
        (
            "- Shadowed skill roots: "
            + ", ".join(f"`{path}`" for path in result["skill_root"]["shadowed"])
            if result["skill_root"]["shadowed"]
            else "- Shadowed skill roots: none"
        ),
        "",
        "## Configured Authority Path Presence",
        "",
        "This check proves only that configured authority paths exist; it does not prove semantic equality,",
        "precedence, or alignment between those documents.",
        "",
    ]

    source = result["authority_paths"]
    if source:
        for item in source:
            status = "present" if item["exists"] else "missing"
            resolved_path = item.get("resolved_path")
            display_path = f"`{item['path']}`"
            if resolved_path is not None and resolved_path != item["path"]:
                display_path += f" -> `{resolved_path}`"
            lines.append(f"- {display_path}: {status} ({item['kind']})")
    else:
        lines.append("- No configured authority paths.")

    lines.extend(["", "## Link Validation", ""])
    validation = result["link_validation"]
    lines.append(f"- Mode: `{validation['mode']}`")
    lines.append(f"- Status: `{validation['status']}`")
    if validation["mode"] == "owner-command":
        lines.append(f"- Cwd: `{validation['cwd']}`")
        lines.append(f"- Command: `{' '.join(validation['command'])}`")
        lines.append(f"- Exit: `{validation['exit_code']}`")
        if validation.get("stdout"):
            lines.extend(
                [
                    "",
                    "Owner validator stdout:",
                    "",
                    "```text",
                    validation["stdout"],
                    "```",
                ]
            )
        if validation.get("stderr"):
            lines.extend(
                [
                    "",
                    "Owner validator stderr:",
                    "",
                    "```text",
                    validation["stderr"],
                    "```",
                ]
            )

    lines.extend(["", "## Recent Commits", ""])
    if result["recent_commits"]:
        lines.extend(f"- {commit}" for commit in result["recent_commits"])
    else:
        lines.append("- No commits found or git log unavailable.")

    lines.extend(["", "## Changed Files", ""])
    if changed:
        lines.extend(f"- `{path}`" for path in changed[:80])
        if len(changed) > 80:
            lines.append(f"- ... {len(changed) - 80} more")
    else:
        lines.append("- No changed files detected in the audit window.")

    lines.extend(["", "## Deterministic Findings", ""])
    if findings:
        classification_titles = (
            ("actionable", "Actionable"),
            ("owner-validator", "Owner Validator"),
            ("report-only", "Report-Only"),
        )
        for classification, title in classification_titles:
            classified = [
                item for item in findings if item["classification"] == classification
            ]
            if not classified:
                continue
            lines.extend([f"### {title}", ""])
            for severity in ("High", "Medium", "Low"):
                scoped = [item for item in classified if item["severity"] == severity]
                if not scoped:
                    continue
                lines.extend([f"#### {severity}", ""])
                for item in scoped:
                    lines.append(f"- {item['title']}: {item['evidence']}")
                    lines.append(f"  Recommendation: {item['recommendation']}")
                lines.append("")
    else:
        lines.append(
            "- No deterministic findings. A semantic review may still find drift."
        )

    lines.extend(
        [
            "",
            "## Doc Alignment Focus",
            "",
            "- Confirm active entry points match the current workflow.",
            "- Separate current guidance from historical notes.",
            "- Check whether recent code/runtime changes require documentation updates.",
            "- Verify names, commands, paths, and validation gates use one current vocabulary.",
            "- Decide whether any finding should become a bounded implementation task.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def default_audit_path(state_dir: Path, name: str) -> Path:
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return state_dir / "audits" / f"{timestamp}-{safe_slug(name)}-audit.md"


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(report, encoding="utf-8")
    except OSError as exc:
        raise AuditFailure(f"failed to write audit report {path}: {exc}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watcher doc audit",
        description="Collect read-only documentation drift evidence for one Git repo.",
    )
    parser.add_argument("--repo", required=True, help="Local Git repository path.")
    parser.add_argument("--name", help="Display name. Defaults to repo directory name.")
    parser.add_argument(
        "--profile", default="default", help="Audit profile name shown in the report."
    )
    parser.add_argument(
        "--docs", nargs="*", help="Docs or directories to scan, relative to repo."
    )
    parser.add_argument(
        "--skill-root-candidate",
        action="append",
        help=(
            "Repository skill directory candidate in priority order; repeat to override "
            "the default candidate list."
        ),
    )
    parser.add_argument(
        "--authority-path",
        action="append",
        default=[],
        help="Configured authority path whose presence is checked; repeat for multiple paths.",
    )
    parser.add_argument(
        "--source-of-truth",
        nargs="*",
        help="Deprecated compatibility alias for configured authority path presence.",
    )
    parser.add_argument(
        "--watch-term",
        action="append",
        default=[],
        help="Term to flag when found in active docs.",
    )
    parser.add_argument(
        "--link-validation",
        choices=("markdown-relative", "none"),
        default="markdown-relative",
        help="One-off link validation mode. Owner-command validators are configured through repo profiles.",
    )
    parser.add_argument(
        "--finding-policy",
        choices=tuple(sorted(FINDING_POLICIES)),
        default="actionable",
        help="Classify deterministic findings as actionable or report-only.",
    )
    parser.add_argument(
        "--no-change-alignment",
        action="store_true",
        help="Disable the recent code-without-doc-change heuristic for this profile.",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=5,
        help="Recent commit window for changed-file evidence.",
    )
    parser.add_argument("--since-ref", help="Git ref to diff against HEAD.")
    parser.add_argument(
        "--state-dir",
        help="Runtime state directory. Defaults to $CODEX_HOME/watcher/doc.",
    )
    parser.add_argument(
        "--output", help="Audit report output path. Defaults to state audits/."
    )
    parser.add_argument(
        "--print-report", action="store_true", help="Print the report to stdout."
    )
    return parser.parse_args(argv)


def _run_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = expand_path(args.repo)
    name = args.name or repo.name
    authority_paths = args.authority_path or None
    if authority_paths is not None and args.source_of_truth is not None:
        raise AuditFailure(
            "use --authority-path; do not combine it with deprecated --source-of-truth"
        )
    result = audit_repository(
        repo=repo,
        name=name,
        docs=args.docs,
        profile=args.profile,
        authority_paths=authority_paths,
        source_of_truth=args.source_of_truth,
        watch_terms=args.watch_term,
        link_validation=args.link_validation,
        finding_policy=args.finding_policy,
        check_change_alignment=not args.no_change_alignment,
        recent_limit=args.recent,
        since_ref=args.since_ref,
        skill_root_candidates=args.skill_root_candidate,
    )
    report = render_report(result)
    output = (
        expand_path(args.output)
        if args.output
        else default_audit_path(resolve_state_dir(args.state_dir), name)
    )
    write_report(output, report)
    print(f"audit: {output}")
    print(f"findings: {len(result['findings'])}")
    if args.print_report:
        print()
        print(report, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run_main(argv)
    except AuditFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
