#!/usr/bin/env python3
"""Shared Watcher skill report pipeline."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .codex_hook_adapter import load_runtime_metadata
from .runtime_paths import report_state_path, reports_dir, safe_slug, utc_now


DEFAULT_OVERLAP_MINUTES = 5


@dataclass(frozen=True)
class ReportQuery:
    state_dir: Path
    log_file: Path
    skill: str | None = None
    since_raw: str | None = None
    incremental: bool = False
    overlap_minutes: int = DEFAULT_OVERLAP_MINUTES
    display_since_raw: bool = False


@dataclass(frozen=True)
class ReportOutputPolicy:
    output: Path | None = None
    write_output: bool = False


@dataclass(frozen=True)
class ReportResult:
    report: str
    output: Path | None
    state_path: Path | None
    window_since: datetime | None
    window_until: datetime
    events: list[dict[str, Any]]
    outcome_counts: Counter[str]

    @property
    def event_count(self) -> int:
        return len(self.events)


def parse_timestamp(raw: str) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_since(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    now = datetime.now(timezone.utc)
    unit = value[-1].lower()
    amount = value[:-1]
    if unit in {"h", "d", "w"} and amount.isdigit():
        count = int(amount)
        if unit == "h":
            return now - timedelta(hours=count)
        if unit == "d":
            return now - timedelta(days=count)
        return now - timedelta(weeks=count)
    parsed = parse_timestamp(value)
    if parsed is not None:
        return parsed
    raise SystemExit(f"invalid --since value {raw!r}; use forms like 12h, 7d, 2w, or ISO timestamp")


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_event_line(log_file: Path, line: str, *, line_number: int | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        location = f" at line {line_number}" if line_number is not None else ""
        raise SystemExit(
            f"invalid JSONL in {log_file}{location}: "
            f"line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(payload, dict):
        location = f" at line {line_number}" if line_number is not None else ""
        raise SystemExit(f"invalid JSONL in {log_file}{location}: event must be an object")
    return payload


def read_events(log_file: Path) -> list[dict[str, Any]]:
    if not log_file.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with log_file.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                events.append(parse_event_line(log_file, line, line_number=line_number))
    except OSError as exc:
        raise SystemExit(f"failed to read log file {log_file}: {exc}") from exc
    return events


def read_events_since(log_file: Path, since: datetime | None, *, block_size: int = 65536) -> list[dict[str, Any]]:
    if since is None:
        return read_events(log_file)
    if not log_file.exists():
        return []

    events: list[dict[str, Any]] = []
    carry = b""
    try:
        with log_file.open("rb") as handle:
            position = handle.seek(0, os.SEEK_END)
            while position > 0:
                size = min(block_size, position)
                position -= size
                handle.seek(position)
                data = handle.read(size)
                lines = (data + carry).splitlines()
                if position > 0:
                    carry = lines[0] if lines else b""
                    complete_lines = lines[1:]
                else:
                    carry = b""
                    complete_lines = lines

                should_stop = False
                for raw_line in reversed(complete_lines):
                    if not raw_line.strip():
                        continue
                    line = raw_line.decode("utf-8", errors="replace")
                    event = parse_event_line(log_file, line)
                    timestamp = parse_timestamp(str(event.get("timestamp", "")))
                    if timestamp is not None and timestamp < since:
                        should_stop = True
                        break
                    events.append(event)
                if should_stop:
                    break
    except OSError as exc:
        raise SystemExit(f"failed to read log file {log_file}: {exc}") from exc
    return list(reversed(events))


def filter_events(
    events: list[dict[str, Any]],
    *,
    skill: str | None,
    since: datetime | None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for event in events:
        if skill and skill not in effective_skill_names(event):
            continue
        if since is not None:
            timestamp = parse_timestamp(str(event.get("timestamp", "")))
            if timestamp is None or timestamp < since:
                continue
        filtered.append(event)
    return filtered


def skill_attribution(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("skill_attribution")
    return value if isinstance(value, dict) else {}


def primary_skill_name(event: dict[str, Any]) -> str | None:
    primary = skill_attribution(event).get("primary")
    if isinstance(primary, dict) and isinstance(primary.get("name"), str):
        return primary["name"]
    return None


def primary_skill_role(event: dict[str, Any]) -> str:
    primary = skill_attribution(event).get("primary")
    if isinstance(primary, dict) and isinstance(primary.get("role"), str):
        return primary["role"]
    return ""


def supporting_skill_entries(event: dict[str, Any]) -> list[dict[str, Any]]:
    supporting = skill_attribution(event).get("supporting")
    return [item for item in supporting if isinstance(item, dict)] if isinstance(supporting, list) else []


def supporting_skill_names(event: dict[str, Any]) -> list[str]:
    names = []
    for item in supporting_skill_entries(event):
        name = item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def effective_skill_names(event: dict[str, Any]) -> list[str]:
    effective = skill_attribution(event).get("effective")
    if isinstance(effective, list):
        names = [item for item in effective if isinstance(item, str) and item]
        if names:
            return names
    primary = primary_skill_name(event)
    names = [primary] if primary else []
    names.extend(supporting_skill_names(event))
    return sorted(dict.fromkeys(name for name in names if name))


def turn_key(event: dict[str, Any]) -> tuple[str, str]:
    session_id = str(event.get("session_id") or "")
    codex = event.get("codex") if isinstance(event.get("codex"), dict) else {}
    turn_id = str(codex.get("turn_id") or event.get("event_id") or "")
    return (session_id, turn_id)


def turn_summary_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event_type") == "turn_summary"]


def turn_task_outcome(event: dict[str, Any]) -> str:
    codex = event.get("codex") if isinstance(event.get("codex"), dict) else {}
    summary = codex.get("turn_summary") if isinstance(codex.get("turn_summary"), dict) else {}
    value = summary.get("task_outcome") if isinstance(summary, dict) else None
    if isinstance(value, str) and value:
        return value
    value = event.get("task_outcome")
    if isinstance(value, str) and value:
        return value
    return str(event.get("outcome") or "unknown")


def turn_tool_failure_count(event: dict[str, Any]) -> int:
    codex = event.get("codex") if isinstance(event.get("codex"), dict) else {}
    summary = codex.get("turn_summary") if isinstance(codex.get("turn_summary"), dict) else {}
    value = summary.get("tool_failure_count") if isinstance(summary, dict) else None
    return value if isinstance(value, int) else 0


def count_values(events: list[dict[str, Any]], key: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in events:
        value = event.get(key)
        if isinstance(value, str) and value:
            counter[value] += 1
        elif value:
            counter[str(value)] += 1
    return counter


def count_codex_values(events: list[dict[str, Any]], key: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in events:
        codex = event.get("codex")
        if not isinstance(codex, dict):
            continue
        value = codex.get(key)
        if isinstance(value, str) and value:
            counter[value] += 1
        elif value:
            counter[str(value)] += 1
    return counter


def count_task_outcomes(events: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in turn_summary_events(events):
        counter[turn_task_outcome(event)] += 1
    return counter


def count_tool_failure_observations(events: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in turn_summary_events(events):
        failures = turn_tool_failure_count(event)
        if failures:
            counter["turns_with_tool_failures"] += 1
            counter["tool_failure_count"] += failures
    return counter


def render_counter(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["- none"]
    return [f"- `{key}`: {count}" for key, count in sorted(counter.items())]


def render_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["- none"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def skill_logical_groups(metadata: dict[str, Any]) -> dict[str, str]:
    skills = metadata.get("skills")
    if not isinstance(skills, dict):
        return {}
    groups: dict[str, str] = {}
    for name, values in skills.items():
        if not isinstance(name, str) or not isinstance(values, dict):
            continue
        logical_group = values.get("logical_group")
        if isinstance(logical_group, str) and logical_group:
            groups[name] = logical_group
    return groups


def usage_rows(
    events: list[dict[str, Any]],
    logical_groups: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    logical_groups = logical_groups or {}
    summaries = turn_summary_events(events)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "effective_turns": set(),
            "primary_turns": set(),
            "supporting_turns": set(),
            "role": "",
        }
    )
    for event in summaries:
        key = turn_key(event)
        primary = primary_skill_name(event)
        if primary:
            stats[primary]["primary_turns"].add(key)
            stats[primary]["effective_turns"].add(key)
            role = primary_skill_role(event)
            if role:
                stats[primary]["role"] = role
        for item in supporting_skill_entries(event):
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            stats[name]["supporting_turns"].add(key)
            stats[name]["effective_turns"].add(key)
            role = item.get("role")
            if isinstance(role, str) and role:
                stats[name]["role"] = role
    rows = []
    for name, values in stats.items():
        primary_count = len(values["primary_turns"])
        supporting_count = len(values["supporting_turns"])
        effective_count = len(values["effective_turns"])
        if effective_count == 0:
            usage_class = "zero effective usage"
        elif primary_count == 0 and supporting_count > 0:
            usage_class = "supporting-only"
        elif effective_count < 10:
            usage_class = "low effective usage"
        else:
            usage_class = "active"
        rows.append(
            {
                "skill": name,
                "role": values["role"] or "",
                "logical_group": logical_groups.get(name, ""),
                "effective_turns": effective_count,
                "primary_turns": primary_count,
                "supporting_turns": supporting_count,
                "usage_class": usage_class,
            }
        )
    return sorted(rows, key=lambda row: (-row["effective_turns"], row["skill"]))


def logical_group_rows(
    events: list[dict[str, Any]],
    logical_groups: dict[str, str],
    *,
    skill: str | None,
) -> list[dict[str, Any]]:
    observed = {
        name
        for event in turn_summary_events(events)
        for name in effective_skill_names(event)
    }
    selected = {
        name: group
        for name, group in logical_groups.items()
        if skill is None or name == skill or name in observed
    }
    if not selected:
        return []

    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "skills": set(),
            "effective_turns": set(),
            "primary_turns": set(),
            "supporting_turns": set(),
        }
    )
    for name, group in selected.items():
        stats[group]["skills"].add(name)

    for event in turn_summary_events(events):
        key = turn_key(event)
        primary = primary_skill_name(event)
        primary_group = selected.get(primary or "")
        if primary_group:
            stats[primary_group]["primary_turns"].add(key)
            stats[primary_group]["effective_turns"].add(key)
        for supporting in supporting_skill_names(event):
            supporting_group = selected.get(supporting)
            if not supporting_group:
                continue
            stats[supporting_group]["supporting_turns"].add(key)
            stats[supporting_group]["effective_turns"].add(key)

    rows = [
        {
            "logical_group": group,
            "effective_turns": len(values["effective_turns"]),
            "primary_turns": len(values["primary_turns"]),
            "supporting_turns": len(values["supporting_turns"]),
            "skills": sorted(values["skills"]),
        }
        for group, values in stats.items()
    ]
    return sorted(rows, key=lambda row: (-row["effective_turns"], row["logical_group"]))


def render_samples(events: list[dict[str, Any]], key: str, *, limit: int = 5) -> list[str]:
    samples: list[str] = []
    for event in events:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            samples.append(f"- {value.strip()}")
        if len(samples) >= limit:
            break
    return samples or ["- none"]


def render_skill_context_samples(events: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    samples: list[str] = []
    seen: set[str] = set()
    for event in events:
        codex = event.get("codex")
        if not isinstance(codex, dict):
            continue
        contexts = []
        if isinstance(codex.get("user_skill_context"), dict):
            contexts.append(codex["user_skill_context"])
        turn_summary = codex.get("turn_summary")
        if isinstance(turn_summary, dict) and isinstance(turn_summary.get("user_skill_context"), dict):
            contexts.append(turn_summary["user_skill_context"])
        for context in contexts:
            summary = context.get("summary")
            if isinstance(summary, str) and summary.strip():
                value = summary.strip()
                if value in seen:
                    continue
                seen.add(value)
                samples.append(f"- {value}")
                break
        if len(samples) >= limit:
            break
    return samples or ["- none"]


def build_report(
    events: list[dict[str, Any]],
    *,
    skill: str | None,
    since_raw: str | None,
    log_file: Path,
    logical_groups: dict[str, str] | None = None,
) -> str:
    logical_groups = logical_groups or {}
    raw_outcome_counts = count_values(events, "outcome")
    task_outcome_counts = count_task_outcomes(events)
    failure_counts = count_values(events, "failure_type")
    event_type_counts = count_values(events, "event_type")
    tool_failure_counts = count_tool_failure_observations(events)
    failed_events = [event for event in events if event.get("outcome") == "failure" or event.get("failure_type")]
    feedback_events = [event for event in events if event.get("user_feedback")]
    rows = usage_rows(events, logical_groups)
    group_rows = logical_group_rows(events, logical_groups, skill=skill)

    group_section: list[str] = []
    if group_rows:
        group_section = [
            "## Usage By Logical Group",
            *render_table(
                ["logical group", "effective turns", "primary turns", "supporting turns", "grouped skills"],
                [
                    [
                        row["logical_group"],
                        row["effective_turns"],
                        row["primary_turns"],
                        row["supporting_turns"],
                        ", ".join(f"`{name}`" for name in row["skills"]),
                    ]
                    for row in group_rows
                ],
            ),
            "",
        ]

    lines = [
        "# Watcher Skill Report",
        "",
        f"- Log file: `{log_file}`",
        f"- Effective skill filter: `{skill or 'all'}`",
        f"- Since: `{since_raw or 'all'}`",
        f"- Event count: {len(events)}",
        f"- Turn summaries: {len(turn_summary_events(events))}",
        "",
        *group_section,
        "## Usage By Effective Skill",
        *render_table(
            [
                "skill",
                "role",
                "logical group",
                "effective turns",
                "primary turns",
                "supporting turns",
                "class",
            ],
            [
                [
                    f"`{row['skill']}`",
                    row["role"] or "",
                    row["logical_group"],
                    row["effective_turns"],
                    row["primary_turns"],
                    row["supporting_turns"],
                    row["usage_class"],
                ]
                for row in rows
            ],
        ),
        "",
        "## Event Types",
        *render_counter(event_type_counts),
        "",
        "## Task Outcomes",
        *render_counter(task_outcome_counts),
        "",
        "## Tool Failure Observations",
        *render_counter(tool_failure_counts),
        "",
        "## Raw Event Outcomes",
        *render_counter(raw_outcome_counts),
        "",
        "## Failure Summary",
        *render_counter(failure_counts),
        "",
        "## Failure Notes",
        *render_samples(failed_events, "notes"),
        "",
        "## User Feedback",
        *render_samples(feedback_events, "user_feedback"),
        "",
        "## User Skill Context",
        *render_skill_context_samples(events),
        "",
    ]
    return "\n".join(lines)


def load_report_state(state_dir: Path) -> dict[str, Any]:
    path = report_state_path(state_dir)
    if not path.exists():
        return {"version": 1, "reports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid report state JSON {path}: line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"report state must contain an object: {path}")
    data.setdefault("version", 1)
    data.setdefault("reports", {})
    if not isinstance(data["reports"], dict):
        raise SystemExit(f"report state reports must be an object: {path}")
    return data


def save_report_state(state_dir: Path, state: dict[str, Any]) -> None:
    path = report_state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to write report state {path}: {exc}") from exc


def report_state_key(skill: str | None) -> str:
    return safe_slug(skill or "all", fallback="all")


def report_state_entry(state: dict[str, Any], key: str) -> dict[str, Any]:
    reports = state.get("reports")
    if not isinstance(reports, dict):
        return {}
    entry = reports.get(key)
    return entry if isinstance(entry, dict) else {}


def state_since(state: dict[str, Any], key: str) -> datetime | None:
    entry = report_state_entry(state, key)
    raw = entry.get("last_successful_report_until")
    return parse_since(raw) if isinstance(raw, str) and raw else None


def event_hash(event: dict[str, Any]) -> str:
    payload = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def recent_event_hashes(state: dict[str, Any], key: str) -> set[str]:
    raw_hashes = report_state_entry(state, key).get("recent_event_hashes")
    if not isinstance(raw_hashes, list):
        return set()
    return {item for item in raw_hashes if isinstance(item, str) and item}


def merge_recent_hashes(existing: set[str], events: list[dict[str, Any]], *, limit: int = 500) -> list[str]:
    hashes = sorted(existing | {event_hash(event) for event in events})
    return hashes[-limit:]


def update_report_state(
    state: dict[str, Any],
    *,
    key: str,
    since: datetime | None,
    until: datetime,
    event_count: int,
    output: Path,
    recent_hashes: list[str],
) -> None:
    reports = state.setdefault("reports", {})
    reports[key] = {
        "last_successful_report_since": format_timestamp(since) if since is not None else None,
        "last_successful_report_until": format_timestamp(until),
        "last_event_count": event_count,
        "last_report_path": str(output),
        "recent_event_hashes": recent_hashes,
        "updated_at": format_timestamp(utc_now()),
    }


def outcome_counts(events: list[dict[str, Any]]) -> Counter[str]:
    task_counts = count_task_outcomes(events)
    return task_counts or count_values(events, "outcome")


def default_report_path(state_dir: Path, skill: str | None) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return reports_dir(state_dir) / f"{timestamp}-{safe_slug(skill or 'all', fallback='all')}-report.md"


def report_since_display(query: ReportQuery, since: datetime | None) -> str | None:
    if query.display_since_raw:
        return query.since_raw
    if since is not None:
        return format_timestamp(since)
    return query.since_raw


def write_report(output: Path, report: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(report + "\n", encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to write report {output}: {exc}") from exc


def select_report_events(
    query: ReportQuery,
    *,
    since: datetime | None,
    until: datetime,
    last_until: datetime | None,
    seen_hashes: set[str],
) -> list[dict[str, Any]]:
    raw_events = filter_events(read_events_since(query.log_file, since), skill=query.skill, since=since)
    events: list[dict[str, Any]] = []
    for event in raw_events:
        timestamp = parse_timestamp(str(event.get("timestamp", "")))
        if timestamp is None or timestamp > until:
            continue
        if last_until is not None and timestamp <= last_until and event_hash(event) in seen_hashes:
            continue
        events.append(event)
    return events


def generate_report(query: ReportQuery, output_policy: ReportOutputPolicy) -> ReportResult:
    fallback_since = parse_since(query.since_raw)
    state = load_report_state(query.state_dir) if query.incremental else None
    key = report_state_key(query.skill)
    last_until = state_since(state, key) if state is not None else None
    seen_hashes = recent_event_hashes(state, key) if state is not None else set()
    if last_until is not None:
        since = last_until - timedelta(minutes=max(query.overlap_minutes, 0))
    else:
        since = fallback_since
    until = utc_now()
    events = select_report_events(
        query,
        since=since,
        until=until,
        last_until=last_until,
        seen_hashes=seen_hashes,
    )
    report = build_report(
        events,
        skill=query.skill,
        since_raw=report_since_display(query, since),
        log_file=query.log_file,
        logical_groups=skill_logical_groups(
            load_runtime_metadata(query.state_dir, allow_discovery=False)
        ),
    )

    output = output_policy.output
    if output is None and output_policy.write_output:
        output = default_report_path(query.state_dir, query.skill)
    if output is not None:
        write_report(output, report)

    state_path: Path | None = None
    if state is not None:
        if output is None:
            raise SystemExit("incremental reports require an output path")
        update_report_state(
            state,
            key=key,
            since=since,
            until=until,
            event_count=len(events),
            output=output,
            recent_hashes=merge_recent_hashes(seen_hashes, events),
        )
        save_report_state(query.state_dir, state)
        state_path = report_state_path(query.state_dir)

    return ReportResult(
        report=report,
        output=output,
        state_path=state_path,
        window_since=since,
        window_until=until,
        events=events,
        outcome_counts=outcome_counts(events),
    )
