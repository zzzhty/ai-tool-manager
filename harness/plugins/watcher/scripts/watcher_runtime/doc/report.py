#!/usr/bin/env python3
"""Generate a report-only Watcher doc audit summary for configured repos."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .audit_repo import (
    AuditFailure,
    audit_repository,
    expand_path,
    render_report,
    resolve_state_dir,
    safe_slug,
)
from .audit_runtime import (
    authority_paths,
    docs_paths,
    load_config,
    load_state,
    mark_current,
    repo_status,
    skill_root_candidates,
    state_path,
)

DEFAULT_CONFIG = Path("config/repos.json")


def default_report_path(state_dir: Path) -> Path:
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return state_dir / "reports" / f"{timestamp}-all-audit-report.md"


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(report, encoding="utf-8")
    except OSError as exc:
        raise AuditFailure(f"failed to write audit report {path}: {exc}") from exc


def finding_fingerprint(finding: dict[str, Any]) -> str:
    payload = {
        "severity": finding.get("severity"),
        "title": finding.get("title"),
        "evidence": finding.get("evidence"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def finding_records(result: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for finding in result.get("findings", []):
        if not isinstance(finding, dict):
            continue
        records.append(
            {
                "fingerprint": finding_fingerprint(finding),
                "classification": str(finding.get("classification") or "actionable"),
                "severity": str(finding.get("severity") or "Unknown"),
                "title": str(finding.get("title") or "Untitled finding"),
                "evidence": str(finding.get("evidence") or ""),
            }
        )
    return sorted(
        records, key=lambda item: (item["severity"], item["title"], item["evidence"])
    )


def previous_finding_records(
    state: dict[str, Any], repo_name: str
) -> list[dict[str, str]]:
    repos = state.get("repos")
    if not isinstance(repos, dict):
        return []
    repo_state = repos.get(repo_name)
    if not isinstance(repo_state, dict):
        return []
    findings = repo_state.get("findings")
    if not isinstance(findings, list):
        return []
    records: list[dict[str, str]] = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        fingerprint = item.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            records.append(
                {
                    "fingerprint": fingerprint,
                    "classification": str(item.get("classification") or "actionable"),
                    "severity": str(item.get("severity") or "Unknown"),
                    "title": str(item.get("title") or "Untitled finding"),
                    "evidence": str(item.get("evidence") or ""),
                }
            )
    return records


def finding_delta(
    *,
    previous: list[dict[str, str]],
    current: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    previous_by_fingerprint = {item["fingerprint"]: item for item in previous}
    current_by_fingerprint = {item["fingerprint"]: item for item in current}
    previous_keys = set(previous_by_fingerprint)
    current_keys = set(current_by_fingerprint)
    return {
        "new": [
            current_by_fingerprint[key] for key in sorted(current_keys - previous_keys)
        ],
        "resolved": [
            previous_by_fingerprint[key] for key in sorted(previous_keys - current_keys)
        ],
        "still_open": [
            current_by_fingerprint[key] for key in sorted(current_keys & previous_keys)
        ],
    }


def render_finding_items(items: list[dict[str, str]], *, limit: int = 8) -> list[str]:
    if not items:
        return ["- none"]
    lines = []
    for item in items[:limit]:
        lines.append(
            f"- [{item['classification']}/{item['severity']}] {item['title']}: {item['evidence']}"
        )
    if len(items) > limit:
        lines.append(f"- ... {len(items) - limit} more")
    return lines


def render_digest(
    *,
    generated_at: str,
    config_path: Path,
    repo_summaries: list[dict[str, Any]],
    skipped: list[str],
    failures: list[str],
) -> str:
    audited = [item for item in repo_summaries if item["status"] == "audited"]
    total_new = sum(len(item["delta"]["new"]) for item in audited)
    total_resolved = sum(len(item["delta"]["resolved"]) for item in audited)
    total_still_open = sum(len(item["delta"]["still_open"]) for item in audited)
    new_by_classification = {
        classification: sum(
            1
            for item in audited
            for finding in item["delta"]["new"]
            if finding["classification"] == classification
        )
        for classification in ("actionable", "owner-validator", "report-only")
    }
    lines = [
        "# Watcher Doc Audit Digest",
        "",
        f"- Generated: {generated_at}",
        f"- Config: `{config_path}`",
        f"- Audited repos: {len(audited)}",
        f"- Skipped repos: {len(skipped)}",
        f"- Failed repos: {len(failures)}",
        f"- New findings: {total_new}",
        f"- New actionable findings: {new_by_classification['actionable']}",
        f"- New owner-validator findings: {new_by_classification['owner-validator']}",
        f"- New report-only findings: {new_by_classification['report-only']}",
        f"- Resolved findings: {total_resolved}",
        f"- Still-open findings: {total_still_open}",
        "",
    ]
    if skipped:
        lines.extend(["## Skipped", ""])
        lines.extend(f"- {item}" for item in skipped)
        lines.append("")
    if failures:
        lines.extend(["## Failures", ""])
        lines.extend(f"- {item}" for item in failures)
        lines.append("")
    for item in audited:
        delta = item["delta"]
        status = item["repo_status"]
        lines.extend(
            [
                f"## Repo: {item['name']}",
                "",
                f"- Head: `{status['head']}`",
                f"- Commits since audit: {status['commits_since_audit']}",
                f"- Config changed: {status['config_changed']}",
                f"- New findings: {len(delta['new'])}",
                f"- Resolved findings: {len(delta['resolved'])}",
                f"- Still-open findings: {len(delta['still_open'])}",
                "",
                "### New",
                "",
                *render_finding_items(delta["new"]),
                "",
                "### Resolved",
                "",
                *render_finding_items(delta["resolved"]),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def audit_repo_from_config(repo_config: dict[str, Any]) -> dict[str, Any]:
    path_raw = repo_config.get("path")
    if not path_raw:
        raise AuditFailure(f"configured repo is missing required path: {repo_config}")
    path = expand_path(str(path_raw))
    name = str(repo_config.get("name") or path.name)
    return audit_repository(
        repo=path,
        name=name,
        profile=str(repo_config.get("profile") or "default"),
        docs=docs_paths(repo_config),
        authority_paths=authority_paths(repo_config),
        watch_terms=list(repo_config.get("watch_terms") or []),
        link_validation=repo_config.get("link_validation"),
        finding_policy=str(repo_config.get("finding_policy") or "actionable"),
        check_change_alignment=bool(repo_config.get("check_change_alignment", True)),
        recent_limit=int(repo_config.get("recent_limit") or 5),
        since_ref=repo_config.get("since_ref"),
        skill_root_candidates=skill_root_candidates(repo_config),
    )


def render_audit_report(
    *,
    generated_at: str,
    config_path: Path,
    reports: list[tuple[str, str]],
    skipped: list[str],
    failures: list[str],
) -> str:
    lines = [
        "# Watcher Doc Audit Report",
        "",
        f"- Generated: {generated_at}",
        f"- Config: `{config_path}`",
        f"- Audited repos: {len(reports)}",
        f"- Skipped repos: {len(skipped)}",
        f"- Failed repos: {len(failures)}",
        "",
    ]
    if skipped:
        lines.extend(["## Skipped", ""])
        lines.extend(f"- {item}" for item in skipped)
        lines.append("")
    if failures:
        lines.extend(["## Failures", ""])
        lines.extend(f"- {item}" for item in failures)
        lines.append("")
    for name, report in reports:
        lines.extend([f"## Repo: {name}", ""])
        body = report.strip().splitlines()
        if body and body[0].startswith("# "):
            body = body[1:]
        lines.extend(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watcher doc report",
        description="Write a report-only Watcher doc audit report under state reports/.",
    )
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG), help="Repo config JSON path."
    )
    parser.add_argument(
        "--state-dir",
        help="Runtime state directory. Defaults to $CODEX_HOME/watcher/doc.",
    )
    parser.add_argument(
        "--mode",
        choices=("all", "commit-dependent"),
        default="all",
        help="all audits all configured repos; commit-dependent audits only repos whose threshold is due.",
    )
    parser.add_argument(
        "--mark-audited",
        action="store_true",
        help="After successful audits, mark audited repos at current HEAD.",
    )
    parser.add_argument("--output", help="Explicit report output path.")
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Print a compact new/resolved/still-open finding digest.",
    )
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="Also print the full report to stdout.",
    )
    return parser.parse_args(argv)


def run_generate_report(
    *,
    config_path: Path,
    state_dir: Path,
    mode: str = "all",
    mark_audited: bool = False,
    output_path: Path | None = None,
    digest: bool = False,
    print_report: bool = False,
) -> dict[str, Any]:
    config = load_config(config_path)
    state = load_state(state_dir)
    audited_statuses: list[dict[str, Any]] = []
    reports: list[tuple[str, str]] = []
    repo_summaries: list[dict[str, Any]] = []
    findings_by_name: dict[str, list[dict[str, str]]] = {}
    skipped: list[str] = []
    failures: list[str] = []

    for repo_config in config["repos"]:
        name = str(
            repo_config.get("name") or Path(str(repo_config.get("path", "repo"))).name
        )
        try:
            status = repo_status(repo_config, state)
            if mode == "commit-dependent" and not status["due"]:
                skipped.append(
                    f"{name}: commits_since_audit={status['commits_since_audit']} "
                    f"threshold={status['commit_threshold']} config_changed={status['config_changed']}"
                )
                continue
            result = audit_repo_from_config(repo_config)
            current_findings = finding_records(result)
            delta = finding_delta(
                previous=previous_finding_records(state, name),
                current=current_findings,
            )
            reports.append((name, render_report(result)))
            audited_statuses.append(status)
            findings_by_name[name] = current_findings
            repo_summaries.append(
                {
                    "name": name,
                    "status": "audited",
                    "repo_status": status,
                    "delta": delta,
                }
            )
        except AuditFailure as exc:
            failures.append(f"{name}: {exc}")

    generated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report = render_audit_report(
        generated_at=generated_at,
        config_path=config_path,
        reports=reports,
        skipped=skipped,
        failures=failures,
    )
    output = output_path if output_path is not None else default_report_path(state_dir)
    write_report(output, report)
    stdout_lines = [
        f"report: {output}",
        f"audited: {len(reports)}",
        f"skipped: {len(skipped)}",
        f"failures: {len(failures)}",
    ]
    updated_state_path: Path | None = None

    if mark_audited and audited_statuses and not failures:
        mark_current(
            state_dir, state, audited_statuses, findings_by_name=findings_by_name
        )
        updated_state_path = state_path(state_dir)
        stdout_lines.append(f"updated state: {updated_state_path}")
    elif mark_audited and failures:
        stdout_lines.append("state not updated because at least one audit failed")

    if print_report:
        stdout_lines.extend(["", report.rstrip()])
    if digest:
        stdout_lines.extend(
            [
                "",
                render_digest(
                    generated_at=generated_at,
                    config_path=config_path,
                    repo_summaries=repo_summaries,
                    skipped=skipped,
                    failures=failures,
                ).rstrip(),
            ]
        )
    return {
        "exit_code": 1 if failures else 0,
        "stdout": "\n".join(stdout_lines) + "\n",
        "report_path": output,
        "updated_state_path": updated_state_path,
        "audited": len(reports),
        "skipped": len(skipped),
        "failures": len(failures),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_generate_report(
        config_path=expand_path(args.config),
        state_dir=resolve_state_dir(args.state_dir),
        mode=args.mode,
        mark_audited=args.mark_audited,
        output_path=expand_path(args.output) if args.output else None,
        digest=args.digest,
        print_report=args.print_report,
    )
    print(result["stdout"], end="")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
