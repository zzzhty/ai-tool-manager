#!/usr/bin/env python3
"""Validate a canonical serial Long-Running Goal Sequence."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit

SHARED = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SHARED))

from markdown_contract import render_errors, strip_fenced_blocks  # noqa: E402

from check_goal_ready import (  # noqa: E402
    MilestoneState,
    milestone_states,
    preflight_contract_errors,
)


ATOMIC_CHECKER = Path(__file__).with_name("check_goal_ready.py")
OVERALL_STATUS_RE = re.compile(
    r"(?im)^(?:overall status|整体状态|goal status|目标状态)"
    r"\s*[:：]\s*`?([^`\n]+)`?\s*$"
)
MARKDOWN_LINK_RE = re.compile(
    r'''^\[[^\]\n]+\]\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>[^\s)]+))'''
    r'''(?:\s+["'][^"'\n]*["'])?\s*\)$'''
)
CURRENT_MILESTONE_RE = re.compile(
    r"^(?P<name>M\d+|Close)\s+"
    r"(?P<status>Ready|In Progress|Blocked|Done)$",
    re.IGNORECASE,
)

PREFLIGHT_HEADER = ("Child ID", "Marker", "Status", "Source")
EXECUTION_HEADER = (
    "Order",
    "Child ID",
    "Parent milestone",
    "Live goal",
    "Closeout evidence",
    "Depends on",
    "State",
    "Current milestone",
    "Close revision",
)
TRANSITION_HEADER = (
    "Timestamp",
    "Child ID",
    "From",
    "To",
    "Predecessor close revision",
    "Handoff gate evidence",
)
CHILD_STATES = {"draft": "Draft", "ready": "Ready", "in progress": "In Progress", "closed": "Closed"}
NONE_VALUE = "n/a"
RFC3339_RE = re.compile(
    r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class PreflightRow:
    child_id: str
    marker: str
    status: str
    source: str


@dataclass(frozen=True)
class ExecutionRow:
    order: int | None
    child_id: str
    parent_milestone: str
    live_goal: str
    closeout_evidence: str
    depends_on: str
    state: str
    current_milestone: str
    close_revision: str


@dataclass(frozen=True)
class TransitionRow:
    timestamp: str
    child_id: str
    from_state: str
    to_state: str
    predecessor_close_revision: str
    handoff_gate_evidence: str


def _table_cells(line: str) -> list[str]:
    return [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]


def _h2_sections(text: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"(?ims)^##\s+{re.escape(heading)}\s*$\n"
        rf"(?P<body>.*?)(?=^##\s+|\Z)"
    )
    return [match.group("body") for match in pattern.finditer(text)]


def _without_h2_section(text: str, heading: str) -> str:
    return re.sub(
        rf"(?ims)^##\s+{re.escape(heading)}\s*$\n.*?(?=^##\s+|\Z)",
        "",
        text,
    )


def _visible_contract(text: str) -> str:
    without_fences = strip_fenced_blocks(text)
    return re.sub(r"(?s)<!--.*?(?:-->|\Z)", "", without_fences)


def _milestone_contract_sections(text: str) -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {}
    for match in re.finditer(
        r"(?ims)^#{2,3}\s+(?P<heading>(?P<name>M\d+)\b[^\n]*)\n"
        r"(?P<body>.*?)(?=^#{1,3}\s+|\Z)",
        text,
    ):
        sections.setdefault(match.group("name"), []).append(
            (match.group("heading").strip(), match.group("body"))
        )
    return sections


def _normalized_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("`", "").strip()).casefold()


def _parse_rfc3339(value: str) -> datetime | None:
    if not RFC3339_RE.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _canonical_table(
    section: str,
    expected_header: tuple[str, ...],
    label: str,
    errors: list[str],
) -> list[list[str]]:
    lines = section.splitlines()
    expected = [cell.casefold() for cell in expected_header]
    header_indexes: list[int] = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = _table_cells(line)
        if [cell.casefold() for cell in cells] == expected:
            header_indexes.append(index)

    if not header_indexes:
        errors.append(
            f"{label} must use canonical columns: " + " | ".join(expected_header)
        )
        return []
    if len(header_indexes) > 1:
        errors.append(f"{label} must contain exactly one canonical table")

    index = header_indexes[0]
    if index + 1 >= len(lines) or not lines[index + 1].lstrip().startswith("|"):
        errors.append(f"{label} is missing its Markdown separator row")
        return []
    separators = _table_cells(lines[index + 1])
    if len(separators) != len(expected_header) or any(
        not re.fullmatch(r":?-{3,}:?", cell) for cell in separators
    ):
        errors.append(f"{label} has an invalid Markdown separator row")
        return []

    rows: list[list[str]] = []
    for raw_row in lines[index + 2 :]:
        if not raw_row.lstrip().startswith("|"):
            break
        cells = _table_cells(raw_row)
        if len(cells) != len(expected_header):
            errors.append(
                f"{label} row has {len(cells)} cells; expected {len(expected_header)}"
            )
            continue
        rows.append(cells)
    return rows


def _single_field(text: str, label: str, subject: str, errors: list[str]) -> str | None:
    matches = re.findall(
        rf"(?im)^{re.escape(label)}\s*[:：]\s*`?([^`\n]+)`?\s*$",
        text,
    )
    if not matches:
        errors.append(f"{subject} is missing {label}")
        return None
    if len(matches) > 1:
        errors.append(f"{subject} has duplicate {label} fields")
        return None
    return matches[0].strip()


def _strict_preflight(
    text: str,
    subject: str,
    errors: list[str],
    *,
    expected: PreflightRow | None = None,
) -> str | None:
    marker = _single_field(text, "Planning preflight marker", subject, errors)
    status = _single_field(text, "Planning preflight status", subject, errors)
    source = _single_field(text, "Preflight source", subject, errors)

    if marker is not None and status is not None and source is not None:
        errors.extend(f"{subject}: {error}" for error in preflight_contract_errors(marker, status, source))
        if expected is not None:
            for label, actual, registered in (
                ("marker", marker, expected.marker),
                ("status", status, expected.status),
                ("source", source, expected.source),
            ):
                if actual != registered:
                    errors.append(
                        f"{subject} preflight {label} disagrees with Child Preflight Register: "
                        f"{actual} != {registered}"
                    )
    return marker


def _overall_status(text: str, subject: str, errors: list[str]) -> str | None:
    matches = [match.strip() for match in OVERALL_STATUS_RE.findall(text)]
    if not matches:
        errors.append(f"{subject} is missing overall goal status")
        return None
    if len(matches) != 1:
        errors.append(
            f"{subject} must declare exactly one overall goal status; found {len(matches)}"
        )
        return None
    normalized = matches[0].casefold()
    allowed = {
        "draft": "Draft",
        "ready": "Ready",
        "in progress": "In Progress",
        "closed": "Closed",
    }
    if normalized not in allowed:
        errors.append(f"{subject} has invalid overall goal status {matches[0]}")
        return None
    return allowed[normalized]


def _strict_open_decisions(text: str, subject: str, errors: list[str]) -> None:
    value = _single_field(text, "Open decisions", subject, errors)
    if value is None:
        return
    normalized = value.strip().strip("` ").rstrip(".").casefold()
    if normalized in {"none", NONE_VALUE, "not applicable"}:
        return
    unresolved = re.search(
        r"(?i)\b(?:tbd|pending|unresolved|to be decided|needs? approval|"
        r"awaiting approval|unknown)\b",
        value,
    )
    if unresolved or not re.search(r"(?i)\bruntime hard[- ]stop", value):
        errors.append(
            f"{subject} Open decisions may contain only bounded runtime hard stops; "
            f"found {value}"
        )


def _atomic_check(
    goal_path: Path,
    subject: str,
    errors: list[str],
    *,
    allow_draft: bool,
) -> None:
    command = [sys.executable, str(ATOMIC_CHECKER), str(goal_path)]
    if allow_draft:
        command.append("--allow-draft")
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode == 0:
        return
    detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
    errors.append(f"{subject} atomic goal checker failed: {detail}")


def _relative_markdown_target(
    cell: str,
    sequence_path: Path,
    subject: str,
    errors: list[str],
) -> Path | None:
    match = MARKDOWN_LINK_RE.fullmatch(cell)
    if not match:
        errors.append(f"{subject} must be a relative Markdown link; found {cell}")
        return None
    target = match.group("angle") or match.group("plain") or ""
    split = urlsplit(target)
    decoded_path = unquote(split.path)
    windows_path = PureWindowsPath(decoded_path)
    portable_absolute = (
        PurePosixPath(decoded_path).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    )
    if split.scheme or split.netloc or not decoded_path or portable_absolute:
        errors.append(f"{subject} must target a relative local Markdown file; found {target}")
        return None
    resolved = (sequence_path.parent / decoded_path).resolve()
    if resolved.suffix.casefold() != ".md":
        errors.append(f"{subject} must target a Markdown file; found {target}")
        return None
    if not resolved.is_file():
        errors.append(f"{subject} target does not exist: {target}")
        return None
    return resolved


def _current_rows(states: list[MilestoneState]) -> list[MilestoneState]:
    return [
        state
        for state in states
        if state.status.casefold() in {"ready", "in progress", "blocked"}
    ]


def _canonical_current_value(state: MilestoneState) -> str:
    names = {"ready": "Ready", "in progress": "In Progress", "blocked": "Blocked", "done": "Done"}
    return f"{state.name} {names[state.status.casefold()]}"


def _validate_child_document(
    path: Path,
    row: ExecutionRow,
    registered: PreflightRow | None,
    errors: list[str],
) -> str | None:
    subject = f"child {row.child_id}"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{subject} cannot read {path}: {exc}")
        return None
    visible = _visible_contract(text)
    actual_overall = _overall_status(visible, subject, errors)
    _strict_preflight(
        visible,
        subject,
        errors,
        expected=registered,
    )
    _strict_open_decisions(visible, subject, errors)
    _atomic_check(
        path,
        subject,
        errors,
        allow_draft=row.state.casefold() == "draft",
    )

    if actual_overall is not None and actual_overall != row.state:
        errors.append(
            f"{subject} overall status disagrees with Child Execution Register: "
            f"{actual_overall} != {row.state}"
        )

    states = milestone_states(visible)
    currents = _current_rows(states)
    if row.state == "Draft":
        if row.current_milestone != NONE_VALUE:
            errors.append(
                f"{subject} Draft Current milestone must be n/a; found {row.current_milestone}"
            )
        if currents:
            errors.append(
                f"{subject} Draft cannot have a promoted current milestone: "
                + ", ".join(_canonical_current_value(item) for item in currents)
            )
        executed = [
            item.name
            for item in states
            if (
                item.status.casefold(),
                item.review.casefold(),
                item.checkpoint.casefold(),
            )
            != ("not started", "pending", "pending")
        ]
        if executed:
            errors.append(
                f"{subject} Draft requires every atomic milestone and Close row "
                "Not Started/Pending/Pending; changed: " + ", ".join(executed)
            )
        return None

    if row.state == "Closed":
        close_rows = [item for item in states if item.name == "Close"]
        close_complete = len(close_rows) == 1 and (
            close_rows[0].status.casefold(),
            close_rows[0].review.casefold(),
            close_rows[0].checkpoint.casefold(),
        ) == ("done", "passed", "done")
        if not close_complete:
            errors.append(f"{subject} Closed row requires atomic Close Done/Passed/Done")
        if row.current_milestone != "Close Done":
            errors.append(
                f"{subject} Closed Current milestone must be Close Done; "
                f"found {row.current_milestone}"
            )
        return None

    if len(currents) != 1:
        errors.append(
            f"{subject} {row.state} requires exactly one current milestone; "
            f"found {len(currents)}"
        )
        return None
    if currents[0].status.casefold() == "blocked":
        child_sections = _milestone_contract_sections(visible)
        body_groups = child_sections.get(currents[0].name, [])
        body = body_groups[0][1] if len(body_groups) == 1 else ""
        _validate_runtime_hard_stop_evidence(
            body,
            row,
            f"child {row.child_id} {currents[0].name} Blocked",
            errors,
        )
    expected = _canonical_current_value(currents[0])
    parsed = CURRENT_MILESTONE_RE.fullmatch(row.current_milestone)
    if parsed is None or row.current_milestone.casefold() != expected.casefold():
        errors.append(
            f"{subject} Current milestone disagrees with atomic goal: "
            f"{row.current_milestone} != {expected}"
        )
    return currents[0].status.casefold()


def _parse_preflight_rows(raw_rows: list[list[str]], errors: list[str]) -> list[PreflightRow]:
    rows = [PreflightRow(*cells) for cells in raw_rows]
    seen: set[str] = set()
    for row in rows:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", row.child_id):
            errors.append(f"Child Preflight Register has invalid Child ID: {row.child_id}")
        if row.child_id in seen:
            errors.append(f"Child Preflight Register has duplicate Child ID: {row.child_id}")
        seen.add(row.child_id)
        errors.extend(
            f"child {row.child_id}: {error}"
            for error in preflight_contract_errors(row.marker, row.status, row.source)
        )
    return rows


def _parse_execution_rows(raw_rows: list[list[str]], errors: list[str]) -> list[ExecutionRow]:
    rows: list[ExecutionRow] = []
    for cells in raw_rows:
        try:
            order: int | None = int(cells[0])
        except ValueError:
            order = None
            errors.append(f"Child Execution Register has non-integer Order: {cells[0]}")
        normalized_state = CHILD_STATES.get(cells[6].casefold(), cells[6])
        rows.append(
            ExecutionRow(
                order,
                cells[1],
                cells[2],
                cells[3],
                cells[4],
                cells[5],
                normalized_state,
                cells[7],
                cells[8],
            )
        )
    return rows


def _parse_transition_rows(
    raw_rows: list[list[str]], errors: list[str]
) -> list[TransitionRow]:
    rows = [TransitionRow(*cells) for cells in raw_rows]
    seen: set[str] = set()
    for row in rows:
        if row.child_id in seen:
            errors.append(f"Transition Evidence has duplicate child promotion: {row.child_id}")
        seen.add(row.child_id)
        if _parse_rfc3339(row.timestamp) is None:
            errors.append(
                f"Transition Evidence for child {row.child_id} requires an RFC3339 timestamp; "
                f"found {row.timestamp}"
            )
        if row.from_state != "Draft":
            errors.append(
                f"Transition Evidence for child {row.child_id} must promote from Draft; "
                f"found {row.from_state}"
            )
        if row.to_state not in {"Ready", "In Progress"}:
            errors.append(
                f"Transition Evidence for child {row.child_id} must promote to Ready or "
                f"In Progress; found {row.to_state}"
            )
        normalized_evidence = row.handoff_gate_evidence.casefold()
        if normalized_evidence in {
            "",
            NONE_VALUE,
            "none",
            "pending",
            "tbd",
            "unknown",
            "-",
        } or len(row.handoff_gate_evidence) < 20 or not re.match(
            r"(?i)^Passed:\s+\S", row.handoff_gate_evidence
        ):
            errors.append(
                f"Transition Evidence for child {row.child_id} requires concrete passed "
                "handoff-gate evidence"
            )
    return rows


def _validate_transition_rows(
    transitions: list[TransitionRow],
    execution_rows: list[ExecutionRow],
    errors: list[str],
) -> None:
    execution_by_id = {row.child_id: row for row in execution_rows}
    transitions_by_id = {row.child_id: row for row in transitions}
    expected_transition_ids = [
        row.child_id for row in execution_rows if row.state != "Draft"
    ]
    actual_transition_ids = [row.child_id for row in transitions]
    if actual_transition_ids != expected_transition_ids:
        errors.append(
            "Transition Evidence child order must exactly match the promoted non-Draft "
            f"execution prefix: {actual_transition_ids} != {expected_transition_ids}"
        )

    parsed_times = [
        parsed
        for transition in transitions
        if (parsed := _parse_rfc3339(transition.timestamp)) is not None
    ]
    if len(parsed_times) == len(transitions) and any(
        later < earlier for earlier, later in zip(parsed_times, parsed_times[1:])
    ):
        errors.append("Transition Evidence timestamps must be non-decreasing in child order")

    for transition in transitions:
        execution = execution_by_id.get(transition.child_id)
        if execution is None:
            errors.append(
                f"Transition Evidence references unknown child {transition.child_id}"
            )
            continue
        if execution.state == "Ready" and transition.to_state != "Ready":
            errors.append(
                f"child {transition.child_id} Ready requires promotion To Ready; "
                f"found {transition.to_state}"
            )
        if execution.order == 1:
            if transition.predecessor_close_revision != NONE_VALUE:
                errors.append(
                    f"first child {transition.child_id} transition requires predecessor "
                    "close revision n/a"
                )
        elif execution.order is not None and execution.order > 1:
            predecessor = next(
                (row for row in execution_rows if row.order == execution.order - 1),
                None,
            )
            expected_revision = predecessor.close_revision if predecessor else None
            if (
                expected_revision is None
                or expected_revision.casefold() in {"", NONE_VALUE, "pending", "tbd"}
                or transition.predecessor_close_revision != expected_revision
            ):
                errors.append(
                    f"child {transition.child_id} transition predecessor close revision "
                    f"must match order {execution.order - 1}: "
                    f"{transition.predecessor_close_revision} != {expected_revision or 'missing'}"
                )

    for execution in execution_rows:
        if execution.state != "Draft" and execution.child_id not in transitions_by_id:
            errors.append(
                f"child {execution.child_id} {execution.state} requires timestamped "
                "Transition Evidence for its promotion and handoff gate"
            )
        if execution.state == "Draft" and execution.child_id in transitions_by_id:
            errors.append(
                f"Draft child {execution.child_id} must not have historical promotion "
                "Transition Evidence in strict v1"
            )


def _validate_runtime_hard_stop_evidence(
    section_body: str,
    row: ExecutionRow,
    subject: str,
    errors: list[str],
) -> str | None:
    matches = re.findall(
        r"(?im)^Runtime hard-stop evidence\s*[:：]\s*(\S[^\n]*)$",
        section_body,
    )
    if len(matches) != 1:
        errors.append(
            f"{subject} requires exactly one section-local Runtime hard-stop evidence field"
        )
        return None
    evidence = matches[0].strip()
    missing: list[str] = []
    if evidence.casefold() in {NONE_VALUE, "none", "pending", "tbd", "unknown", "-"}:
        missing.append("non-placeholder evidence")
    if not re.search(r"\b20\d{2}-\d{2}-\d{2}\b", evidence):
        missing.append("timestamp")
    if not re.search(
        rf"(?<![A-Za-z0-9_.-]){re.escape(row.child_id)}(?![A-Za-z0-9_.-])",
        evidence,
        re.IGNORECASE,
    ):
        missing.append("owning child ID")
    if not re.search(r"(?i)\bbreakpoint|\bdiagnos|\battempt|\bprobe|\bcheck", evidence):
        missing.append("breakpoint or attempted diagnostics")
    if missing:
        errors.append(f"{subject} evidence is missing: " + ", ".join(missing))
        return None
    return evidence


def _validate_promotion_drift_evidence(
    section_body: str,
    row: ExecutionRow,
    errors: list[str],
) -> None:
    subject = f"parent M{row.order} Blocked with Draft child {row.child_id}"
    evidence = _validate_runtime_hard_stop_evidence(
        section_body, row, subject, errors
    )
    if evidence is None:
        return
    missing: list[str] = []
    if not re.search(
        r"(?i)\bsemantic drift\b|\bfailed handoff\b|\bhandoff\b.*\bfail",
        evidence,
    ):
        missing.append("semantic drift or failed handoff")
    if not re.search(
        r"(?i)revalidat(?:e|ion)|grill-with-docs|re-?grill|external decision|approval", evidence
    ):
        missing.append("required decision revalidation or external decision")
    if missing:
        errors.append(f"{subject} evidence is missing: " + ", ".join(missing))


def _validate_parent_stage_hard_stop_evidence(
    section_body: str,
    stage: str,
    owner_token: str,
    errors: list[str],
) -> None:
    matches = re.findall(
        r"(?im)^Runtime hard-stop evidence\s*[:：]\s*(\S[^\n]*)$",
        section_body,
    )
    subject = f"parent {stage} Blocked"
    if len(matches) != 1:
        errors.append(
            f"{subject} requires exactly one section-local Runtime hard-stop evidence field"
        )
        return
    evidence = matches[0].strip()
    missing: list[str] = []
    if evidence.casefold() in {NONE_VALUE, "none", "pending", "tbd", "unknown", "-"}:
        missing.append("non-placeholder evidence")
    if not re.search(r"\b20\d{2}-\d{2}-\d{2}\b", evidence):
        missing.append("timestamp")
    if not re.search(
        rf"(?<![A-Za-z0-9_.-]){re.escape(owner_token)}(?![A-Za-z0-9_.-])",
        evidence,
        re.IGNORECASE,
    ):
        missing.append(f"{owner_token} stage owner")
    if not re.search(r"(?i)\bbreakpoint|\bdiagnos|\battempt|\bprobe|\bcheck", evidence):
        missing.append("breakpoint or attempted diagnostics")
    if missing:
        errors.append(f"{subject} evidence is missing: " + ", ".join(missing))


def _validate_register_shape(
    preflight_rows: list[PreflightRow],
    execution_rows: list[ExecutionRow],
    errors: list[str],
) -> None:
    if len(preflight_rows) < 2 or len(execution_rows) < 2:
        errors.append("Long-Running Goal Sequence requires at least two child goals")

    preflight_ids = [row.child_id for row in preflight_rows]
    execution_ids = [row.child_id for row in execution_rows]
    if set(preflight_ids) != set(execution_ids):
        errors.append(
            "Child Preflight Register and Child Execution Register Child ID sets disagree: "
            f"preflight={sorted(set(preflight_ids))}, execution={sorted(set(execution_ids))}"
        )
    duplicate_execution_ids = sorted(
        child_id for child_id in set(execution_ids) if execution_ids.count(child_id) > 1
    )
    for child_id in duplicate_execution_ids:
        errors.append(f"Child Execution Register has duplicate Child ID: {child_id}")

    markers = [row.marker for row in preflight_rows]
    duplicate_markers = sorted(
        marker for marker in set(markers) if markers.count(marker) > 1
    )
    for marker in duplicate_markers:
        errors.append(f"Child Preflight Register has duplicate Marker: {marker}")

    numeric_orders = [row.order for row in execution_rows if row.order is not None]
    duplicate_orders = sorted(
        order for order in set(numeric_orders) if numeric_orders.count(order) > 1
    )
    if duplicate_orders:
        errors.append(
            "Child Execution Register has duplicate Order values: "
            + ", ".join(str(order) for order in duplicate_orders)
        )
    expected_orders = list(range(1, len(execution_rows) + 1))
    if numeric_orders != expected_orders:
        errors.append(
            "Child Execution Register Order must be unique, contiguous, and table-ordered "
            f"from 1; found {numeric_orders}"
        )

    index_by_id = {row.child_id: index for index, row in enumerate(execution_rows)}
    for index, row in enumerate(execution_rows):
        expected_parent = f"M{index + 1}"
        if row.parent_milestone != expected_parent:
            errors.append(
                f"child {row.child_id} Parent milestone must be {expected_parent}; "
                f"found {row.parent_milestone}"
            )
        if row.depends_on == NONE_VALUE:
            continue
        dependencies = [item.strip().strip("`") for item in row.depends_on.split(",")]
        if any(not item for item in dependencies):
            errors.append(f"child {row.child_id} has an empty Depends on entry")
            continue
        for dependency in dependencies:
            dependency_index = index_by_id.get(dependency)
            if dependency_index is None:
                errors.append(f"child {row.child_id} depends on unknown child {dependency}")
            elif dependency_index >= index:
                errors.append(
                    f"child {row.child_id} dependency must reference an earlier child: {dependency}"
                )

    phase = "closed"
    current_count = 0
    for row in execution_rows:
        normalized = row.state.casefold()
        if normalized not in CHILD_STATES:
            errors.append(f"child {row.child_id} has invalid State: {row.state}")
            continue
        if normalized == "closed":
            if phase != "closed":
                errors.append(
                    f"child state order invalid: Closed child {row.child_id} follows a non-Closed child"
                )
        elif normalized in {"ready", "in progress"}:
            current_count += 1
            if phase == "draft":
                errors.append(
                    f"child state order invalid: current child {row.child_id} follows a Draft child"
                )
            phase = "current"
        else:
            phase = "draft"
    if current_count > 1:
        errors.append("Child Execution Register permits at most one Ready or In Progress child")


def _validate_parent_mapping(
    visible: str,
    parent_overall: str | None,
    rows: list[ExecutionRow],
    child_current_statuses: dict[str, str | None],
    errors: list[str],
) -> None:
    states = milestone_states(visible)
    by_name = {state.name: state for state in states}
    expected_names = {f"M{number}" for number in range(0, len(rows) + 2)} | {"Close"}
    actual_names = set(by_name)
    if actual_names != expected_names:
        errors.append(
            "sequence parent milestone set must be M0, one milestone per child, "
            f"M{len(rows) + 1} integration, and Close; "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
        return

    section_groups = _milestone_contract_sections(visible)
    expected_headings = {
        "M0": "M0 - Sequence Baseline And First Promotion",
        f"M{len(rows) + 1}": f"M{len(rows) + 1} - Integration Acceptance",
    }
    expected_headings.update(
        {f"M{row.order}": f"M{row.order} - Child {row.child_id}" for row in rows if row.order}
    )
    for milestone, expected_heading in expected_headings.items():
        groups = section_groups.get(milestone, [])
        if len(groups) != 1:
            errors.append(
                f"sequence parent requires exactly one owning section: {expected_heading}"
            )
            continue
        actual_heading = groups[0][0]
        if _normalized_heading(actual_heading) != _normalized_heading(expected_heading):
            errors.append(
                f"sequence parent owning section heading disagrees with register: "
                f"{actual_heading} != {expected_heading}"
            )
    m0 = by_name["M0"]
    non_draft_children = [row for row in rows if row.state != "Draft"]
    if non_draft_children and m0.status.casefold() != "done":
        errors.append("M0 must be Done before any child is Ready, In Progress, or Closed")

    if parent_overall == "Draft":
        if m0.status.casefold() != "not started":
            errors.append("Draft sequence parent requires M0 Not Started")
    elif parent_overall == "Ready":
        if m0.status.casefold() != "ready" or non_draft_children:
            errors.append("Ready sequence parent is only valid at M0 with every child Draft")
    if m0.status.casefold() == "blocked":
        body_groups = section_groups.get("M0", [])
        body = body_groups[0][1] if len(body_groups) == 1 else ""
        _validate_parent_stage_hard_stop_evidence(
            body, "M0", "sequence", errors
        )

    for row in rows:
        if row.order is None:
            continue
        parent = by_name[f"M{row.order}"]
        child_current = child_current_statuses.get(row.child_id)
        if row.state == "Closed":
            expected = "done"
        elif row.state == "Ready":
            expected = "in progress"
        elif row.state == "In Progress":
            expected = "blocked" if child_current == "blocked" else "in progress"
        else:
            expected = "not started"

        actual = parent.status.casefold()
        if actual == expected:
            if expected == "blocked":
                body_groups = section_groups.get(f"M{row.order}", [])
                body = body_groups[0][1] if len(body_groups) == 1 else ""
                _validate_runtime_hard_stop_evidence(
                    body,
                    row,
                    f"parent M{row.order} Blocked with executing child {row.child_id}",
                    errors,
                )
            continue
        if row.state == "Draft" and actual == "blocked":
            body_groups = section_groups.get(f"M{row.order}", [])
            body = body_groups[0][1] if len(body_groups) == 1 else ""
            _validate_promotion_drift_evidence(body, row, errors)
            continue
        errors.append(
            f"parent M{row.order} status disagrees with child {row.child_id} {row.state}: "
            f"{parent.status} != {expected.title()}"
        )

    integration = by_name[f"M{len(rows) + 1}"]
    all_closed = bool(rows) and all(row.state == "Closed" for row in rows)
    if not all_closed and integration.status.casefold() != "not started":
        errors.append(
            f"integration milestone M{len(rows) + 1} cannot start before every child is Closed"
        )
    if all_closed and integration.status.casefold() == "not started":
        errors.append(
            f"automatic-after-close requires integration milestone M{len(rows) + 1} "
            "to start after every child is Closed"
        )
    if integration.status.casefold() == "blocked":
        body_groups = section_groups.get(f"M{len(rows) + 1}", [])
        body = body_groups[0][1] if len(body_groups) == 1 else ""
        _validate_parent_stage_hard_stop_evidence(
            body, f"M{len(rows) + 1} Integration", "integration", errors
        )

    close = by_name["Close"]
    if close.status.casefold() != "not started" and not all_closed:
        errors.append("parent Close cannot start before every child is Closed")
    if close.status.casefold() == "blocked":
        close_sections = _h2_sections(visible, "Close Gate")
        body = close_sections[0] if len(close_sections) == 1 else ""
        _validate_parent_stage_hard_stop_evidence(
            body, "Close", "close", errors
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence_file", type=Path)
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Allow only the sequence parent lifecycle to remain Draft; all preflights stay mandatory.",
    )
    args = parser.parse_args()

    path = args.sequence_file
    if not path.exists():
        print(f"missing sequence file: {path}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"sequence path is not a file: {path}", file=sys.stderr)
        return 1

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"cannot read sequence file {path}: {exc}", file=sys.stderr)
        return 1
    visible = _visible_contract(text)
    errors: list[str] = []

    promotion_values = re.findall(
        r"(?im)^Promotion policy\s*[:：]\s*`?([^`\n]+)`?\s*$",
        visible,
    )
    if len(promotion_values) != 1:
        errors.append(
            "sequence must declare exactly one Promotion policy: automatic-after-close"
        )
    elif promotion_values[0].strip() != "automatic-after-close":
        errors.append(
            "Promotion policy must be automatic-after-close; "
            f"found {promotion_values[0].strip()}"
        )

    parent_overall = _overall_status(visible, "sequence parent", errors)
    parent_marker = _strict_preflight(visible, "sequence parent", errors)
    _strict_open_decisions(visible, "sequence parent", errors)

    harness_sections = _h2_sections(visible, "Loop Blueprint / Harness")
    if len(harness_sections) != 1:
        errors.append(
            "Long-Running Goal Sequence requires exactly one Loop Blueprint / Harness section"
        )
    else:
        mode = re.findall(
            r"(?im)^Execution mode\s*[:：]\s*`?([^`\n]+)`?\s*$",
            harness_sections[0],
        )
        if len(mode) != 1 or mode[0].strip() != "Loop-shaped execution":
            errors.append(
                "Long-Running Goal Sequence parent Execution mode must be "
                "Loop-shaped execution"
            )
    _atomic_check(path, "sequence parent", errors, allow_draft=args.allow_draft)

    preflight_sections = _h2_sections(visible, "Child Preflight Register")
    execution_sections = _h2_sections(visible, "Child Execution Register")
    transition_sections = _h2_sections(visible, "Transition Evidence")
    outside_execution_register = _without_h2_section(
        visible, "Child Execution Register"
    )
    copied_current_fields = re.findall(
        r"(?im)^(?:Current child(?: ID)?|Active child|Current child milestone)\s*[:：]",
        outside_execution_register,
    )
    if copied_current_fields:
        errors.append(
            "Child Execution Register is the sole current-state authority; remove "
            "Current child, Active child, or Current child milestone fields elsewhere"
        )
    if len(preflight_sections) != 1:
        errors.append(
            "missing canonical Child Preflight Register; migrate narrative umbrella to "
            "the Long-Running Goal Sequence canonical registers"
            if not preflight_sections
            else "Child Preflight Register must appear exactly once"
        )
    if len(execution_sections) != 1:
        errors.append(
            "missing canonical Child Execution Register; migrate narrative umbrella to "
            "the Long-Running Goal Sequence canonical registers"
            if not execution_sections
            else "Child Execution Register must appear exactly once"
        )
    if len(transition_sections) != 1:
        errors.append(
            "missing canonical Transition Evidence table for historical promotion and "
            "handoff evidence"
            if not transition_sections
            else "Transition Evidence must appear exactly once"
        )
    if (
        len(preflight_sections) != 1
        or len(execution_sections) != 1
        or len(transition_sections) != 1
    ):
        return render_errors(path, errors)

    raw_preflight = _canonical_table(
        preflight_sections[0], PREFLIGHT_HEADER, "Child Preflight Register", errors
    )
    raw_execution = _canonical_table(
        execution_sections[0], EXECUTION_HEADER, "Child Execution Register", errors
    )
    raw_transitions = _canonical_table(
        transition_sections[0], TRANSITION_HEADER, "Transition Evidence", errors
    )
    preflight_rows = _parse_preflight_rows(raw_preflight, errors)
    execution_rows = _parse_execution_rows(raw_execution, errors)
    transition_rows = _parse_transition_rows(raw_transitions, errors)
    _validate_register_shape(preflight_rows, execution_rows, errors)
    _validate_transition_rows(transition_rows, execution_rows, errors)

    registered = {row.child_id: row for row in preflight_rows}
    if parent_marker is not None and parent_marker in {row.marker for row in preflight_rows}:
        errors.append(
            "sequence parent and child goals must not share a planning preflight marker"
        )
    child_current_statuses: dict[str, str | None] = {}
    resolved_parent = path.resolve()
    child_targets: dict[Path, str] = {}
    for row in execution_rows:
        normalized_state = row.state.casefold()
        if normalized_state not in CHILD_STATES:
            child_current_statuses[row.child_id] = None
            continue

        source_path: Path | None = None
        if row.state == "Closed":
            if row.live_goal != NONE_VALUE:
                errors.append(f"child {row.child_id} Closed Live goal must be n/a")
            source_path = _relative_markdown_target(
                row.closeout_evidence,
                path,
                f"child {row.child_id} Closeout evidence",
                errors,
            )
            if row.close_revision.casefold() in {
                "",
                NONE_VALUE,
                "none",
                "pending",
                "tbd",
                "unknown",
                "-",
            }:
                errors.append(f"child {row.child_id} Closed requires a concrete Close revision")
        else:
            if row.closeout_evidence != NONE_VALUE:
                errors.append(
                    f"child {row.child_id} non-Closed Closeout evidence must be n/a"
                )
            if row.close_revision != NONE_VALUE:
                errors.append(
                    f"child {row.child_id} non-Closed Close revision must be n/a"
                )
            source_path = _relative_markdown_target(
                row.live_goal,
                path,
                f"child {row.child_id} Live goal",
                errors,
            )

        if source_path is not None:
            if source_path == resolved_parent:
                errors.append(
                    f"child {row.child_id} goal target must not be the sequence parent itself"
                )
                source_path = None
            elif source_path in child_targets:
                errors.append(
                    f"children {child_targets[source_path]} and {row.child_id} must not "
                    "share the same atomic goal target"
                )
                source_path = None
            else:
                child_targets[source_path] = row.child_id

        if source_path is not None:
            child_current_statuses[row.child_id] = _validate_child_document(
                source_path,
                row,
                registered.get(row.child_id),
                errors,
            )
        else:
            child_current_statuses[row.child_id] = None

    _validate_parent_mapping(
        visible,
        parent_overall,
        execution_rows,
        child_current_statuses,
        errors,
    )

    if errors:
        return render_errors(path, errors)
    print(f"{path}: long-running goal sequence checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
