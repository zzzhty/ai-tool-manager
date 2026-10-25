#!/usr/bin/env python3
"""Lightweight readiness checks for an SOP Markdown file."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SHARED))

from markdown_contract import (  # noqa: E402
    placeholder_errors,
    render_errors,
    strip_fenced_blocks,
)


STATUS_RE = re.compile(
    r"(?mi)^(?:Status|状态)\s*[:：]\s*`?(?P<status>[^`\n]+?)`?\s*$"
)
H2_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
H3_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
FENCE_RE = re.compile(r"^[ ]{0,3}(?P<marker>`{3,}|~{3,})")

SECTION_PATTERNS = {
    "summary": r"(?:摘要|Summary)",
    "trigger": r"(?:触发条件|Trigger)",
    "preconditions": r"(?:前置条件|Preconditions)",
    "working directory": r"(?:工作目录|Working Directory)",
    "inputs": r"(?:输入|Inputs)",
    "execution harness": r"(?:Execution Harness|执行 Harness|执行约束)",
    "allowed actions": r"(?:允许动作|Allowed Actions)",
    "forbidden actions": r"(?:禁止动作|Forbidden Actions)",
    "steps": r"(?:标准步骤|Steps)",
    "validation": r"(?:验证标准|Validation)",
    "output contract": r"(?:输出合同|Output Contract)",
    "stop conditions": r"(?:停止条件|Stop Conditions)",
    "update rules": r"(?:更新规则|Update Rules)",
    "reuse prompt": r"(?:复用 Prompt|Reuse Prompt)",
}
STEP_FIELD_PATTERNS = {
    "action": r"(?:操作|Action)",
    "expected output": r"(?:预期输出|Expected Output)",
    "failure handling": r"(?:失败处理|Failure Handling)",
    "completion criterion": r"(?:完成条件|Completion Criterion)",
}
REQUIRED_SECTIONS = {
    "trigger", "inputs", "execution harness", "allowed actions", "steps",
    "validation", "output contract", "stop conditions",
}
REQUIRED_STEP_FIELDS = {"action", "expected output"}


def markdown_h2_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    active_fence: tuple[str, int] | None = None
    for line in text.splitlines():
        if active_fence is not None:
            stripped = line.lstrip()
            marker, minimum_length = active_fence
            if len(stripped) >= minimum_length and set(stripped.rstrip()) == {marker}:
                active_fence = None
            if sections:
                sections[-1][1].append(line)
            continue

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group("marker")
            active_fence = (marker[0], len(marker))
            if sections:
                sections[-1][1].append(line)
            continue

        heading = H2_RE.match(line)
        if heading:
            sections.append((heading.group("title").strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in sections]


def substantive_content(text: str) -> bool:
    prose_lines: list[str] = []
    table_rows = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or FENCE_RE.match(raw_line) or H3_RE.match(raw_line):
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", line):
            continue
        if line.startswith("|") and line.endswith("|"):
            table_rows += 1
            continue
        prose_lines.append(line)
    return bool(prose_lines or table_rows >= 2)


def mask_fenced_structure(text: str) -> str:
    """Mask fenced blocks without changing offsets used to slice field values."""
    masked: list[str] = []
    active_fence: tuple[str, int] | None = None
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        line_ending = raw_line[len(line) :]
        if active_fence is not None:
            marker, minimum_length = active_fence
            stripped = line.lstrip(" ")
            candidate = stripped.rstrip(" \t")
            if (
                len(line) - len(stripped) <= 3
                and len(candidate) >= minimum_length
                and set(candidate) == {marker}
            ):
                active_fence = None
            masked.append(" " * len(line) + line_ending)
            continue

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group("marker")
            active_fence = (marker[0], len(marker))
            masked.append(" " * len(line) + line_ending)
            continue
        masked.append(raw_line)
    return "".join(masked)


def matching_section_bodies(text: str) -> tuple[dict[str, str], list[str]]:
    matches: dict[str, str] = {}
    errors: list[str] = []
    for title, body in markdown_h2_sections(text):
        for label, pattern in SECTION_PATTERNS.items():
            if re.fullmatch(pattern, title, flags=re.IGNORECASE):
                if label in matches:
                    errors.append(f"duplicate required section: {label}")
                else:
                    matches[label] = body
                break
    for label in SECTION_PATTERNS:
        if label not in matches:
            if label in REQUIRED_SECTIONS:
                errors.append(f"missing required section: {label}")
        elif not substantive_content(matches[label]):
            errors.append(f"required section has no substantive content: {label}")
    return matches, errors


def step_contract_errors(steps_body: str) -> list[str]:
    visible_structure = mask_fenced_structure(steps_body)
    matches = list(re.finditer(r"(?mi)^###\s+Step\b[^\n]*$", visible_structure))
    if not matches:
        return ["steps section must include at least one `### Step` entry"]

    errors: list[str] = []
    for index, match in enumerate(matches, start=1):
        end = matches[index].start() if index < len(matches) else len(steps_body)
        block_start = match.end()
        visible_block = visible_structure[block_start:end]
        raw_block = steps_body[block_start:end]
        field_matches: list[tuple[str, re.Match[str]]] = []
        for label, pattern in STEP_FIELD_PATTERNS.items():
            for field in re.finditer(
                rf"(?mi)^(?:{pattern})\s*[:：][ \t]*",
                visible_block,
            ):
                field_matches.append((label, field))

        field_matches.sort(key=lambda item: item[1].start())
        for label in STEP_FIELD_PATTERNS:
            candidates = [field for name, field in field_matches if name == label]
            if not candidates:
                if label in REQUIRED_STEP_FIELDS:
                    errors.append(f"Step {index} missing required field: {label}")
                continue
            field = candidates[0]
            content_end = min(
                (
                    following.start()
                    for _, following in field_matches
                    if following.start() > field.start()
                ),
                default=len(raw_block),
            )
            content = raw_block[field.end() : content_end]
            if not substantive_content(content):
                errors.append(f"Step {index} has empty required field: {label}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sop_file", type=Path)
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="Accept a structurally complete Draft without authorizing execution.",
    )
    args = parser.parse_args()

    path = args.sop_file
    if not path.exists():
        print(f"missing SOP file: {path}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"SOP path is not a file: {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    visible_text = strip_fenced_blocks(text)
    errors: list[str] = []

    errors.extend(placeholder_errors(text))

    sections, section_errors = matching_section_bodies(text)
    errors.extend(section_errors)
    if "steps" in sections:
        errors.extend(step_contract_errors(sections["steps"]))

    preamble = re.split(r"(?m)^##\s+", visible_text, maxsplit=1)[0]
    statuses = [match.group("status").strip() for match in STATUS_RE.finditer(preamble)]
    if not statuses:
        errors.append("missing top-level SOP status; expected Status/状态: Ready")
    elif len(statuses) > 1:
        errors.append("top-level SOP statuses disagree: " + ", ".join(statuses))
    elif statuses[0].casefold() not in {"draft", "ready"}:
        errors.append(
            "invalid top-level SOP status; expected Draft or Ready; found " + statuses[0]
        )
    elif statuses[0].casefold() == "draft" and not args.allow_draft:
        errors.append("SOP status must be Ready; found Draft")

    if errors:
        return render_errors(path, errors)

    lifecycle = statuses[0].title() if statuses else "Unknown"
    print(f"{path}: SOP {lifecycle} contract checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
