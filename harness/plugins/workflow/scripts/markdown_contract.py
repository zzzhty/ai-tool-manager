#!/usr/bin/env python3
"""Shared Markdown contract checks for Workflow skills."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.parse import unquote, urlsplit


PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")
FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
PLACEHOLDER_EXAMPLE_TOKEN = "placeholder-example"


@dataclass(frozen=True)
class LinkIssue:
    file_path: Path
    line: int
    target: str


@dataclass(frozen=True)
class RelativeMarkdownLink:
    file_path: Path
    line: int
    target: str
    resolved: Path


def _opening_fence(line: str) -> tuple[str, int, str] | None:
    match = FENCE_OPEN_RE.match(line)
    if not match:
        return None
    marker = match.group("marker")
    return marker[0], len(marker), match.group("info").strip()


def _is_closing_fence(line: str, marker: str, minimum_length: int) -> bool:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return False
    candidate = stripped.rstrip(" \t")
    return len(candidate) >= minimum_length and set(candidate) == {marker}


def strip_fenced_blocks(text: str) -> str:
    lines: list[str] = []
    active_fence: tuple[str, int] | None = None
    for line in text.splitlines():
        if active_fence:
            if _is_closing_fence(line, *active_fence):
                active_fence = None
            continue
        opening = _opening_fence(line)
        if opening:
            marker, length, _ = opening
            active_fence = (marker, length)
            continue
        lines.append(line)
    return "\n".join(lines)


def strip_placeholder_example_blocks(text: str) -> str:
    """Remove only fences explicitly marked as documentation-only examples."""
    lines: list[str] = []
    active_fence: tuple[str, int] | None = None
    is_example = False
    for line in text.splitlines():
        if active_fence:
            if _is_closing_fence(line, *active_fence):
                if not is_example:
                    lines.append(line)
                active_fence = None
                is_example = False
            elif not is_example:
                lines.append(line)
            continue

        opening = _opening_fence(line)
        if opening:
            marker, length, info = opening
            active_fence = (marker, length)
            is_example = PLACEHOLDER_EXAMPLE_TOKEN in {
                token.casefold() for token in info.split()
            }
            if not is_example:
                lines.append(line)
            continue
        lines.append(line)
    return "\n".join(lines)


def _placeholder_scan(markdown_text: str) -> tuple[str, list[str]]:
    lines: list[str] = []
    active_fence: tuple[str, int] | None = None
    is_example = False
    example_lines: list[str] = []
    example_start_line: int | None = None
    for line_number, line in enumerate(markdown_text.splitlines(), start=1):
        if active_fence:
            if _is_closing_fence(line, *active_fence):
                active_fence = None
                is_example = False
                example_lines = []
                example_start_line = None
            elif is_example:
                example_lines.append(line)
            elif not is_example:
                lines.append(line)
            continue

        opening = _opening_fence(line)
        if opening:
            marker, length, info = opening
            active_fence = (marker, length)
            is_example = PLACEHOLDER_EXAMPLE_TOKEN in {
                token.casefold() for token in info.split()
            }
            if is_example:
                example_start_line = line_number
            continue
        lines.append(line)

    errors: list[str] = []
    if active_fence and is_example:
        lines.extend(example_lines)
        errors.append(
            f"unclosed {PLACEHOLDER_EXAMPLE_TOKEN} fence at line {example_start_line}"
        )
    return "\n".join(lines), errors


def placeholder_errors(markdown_text: str) -> list[str]:
    """Report placeholders, including fenced content unless explicitly example-only."""
    scannable_text, errors = _placeholder_scan(markdown_text)
    placeholders = PLACEHOLDER_RE.findall(scannable_text)
    if not placeholders:
        return errors
    preview = ", ".join(sorted(set(placeholders))[:10])
    return [*errors, f"unresolved placeholders: {preview}"]


def missing_required_pattern_errors(
    visible_text: str,
    required_patterns: dict[str, str],
    *,
    message: str,
) -> list[str]:
    errors: list[str] = []
    for label, pattern in required_patterns.items():
        if not re.search(pattern, visible_text):
            errors.append(f"{message}: {label}")
    return errors


def iter_markdown(path: Path):
    if path.is_file():
        if path.suffix.lower() == ".md":
            yield path
        return
    yield from path.rglob("*.md")


def is_external(target: str) -> bool:
    lower = target.lower()
    return (
        not target
        or target.startswith("#")
        or lower.startswith(("http://", "https://", "mailto:", "tel:"))
        or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) is not None
    )


def _mask_inline_code(line: str) -> str:
    masked = list(line)
    index = 0
    while index < len(line):
        if line[index] != "`":
            index += 1
            continue
        run_end = index
        while run_end < len(line) and line[run_end] == "`":
            run_end += 1
        marker = line[index:run_end]
        closing = line.find(marker, run_end)
        if closing < 0:
            index = run_end
            continue
        for position in range(index, closing + len(marker)):
            masked[position] = " "
        index = closing + len(marker)
    return "".join(masked)


def _navigable_lines(markdown_text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    active_fence: tuple[str, int] | None = None
    in_comment = False
    for line_number, raw_line in enumerate(markdown_text.splitlines(), start=1):
        if active_fence:
            if _is_closing_fence(raw_line, *active_fence):
                active_fence = None
            continue
        opening = _opening_fence(raw_line)
        if opening:
            marker, length, _ = opening
            active_fence = (marker, length)
            continue
        if raw_line.startswith(("    ", "\t")):
            continue

        line = raw_line
        visible: list[str] = []
        cursor = 0
        while cursor < len(line):
            if in_comment:
                end = line.find("-->", cursor)
                if end < 0:
                    cursor = len(line)
                    continue
                in_comment = False
                cursor = end + 3
                continue
            start = line.find("<!--", cursor)
            if start < 0:
                visible.append(line[cursor:])
                break
            visible.append(line[cursor:start])
            in_comment = True
            cursor = start + 4
        lines.append((line_number, _mask_inline_code("".join(visible))))
    return lines


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _matching_delimiter(
    text: str,
    start: int,
    opening: str,
    closing: str,
    *,
    honor_quotes: bool = False,
) -> int | None:
    depth = 1
    quote: str | None = None
    for index in range(start + 1, len(text)):
        char = text[index]
        if _is_escaped(text, index):
            continue
        if honor_quotes and char in {'"', "'"}:
            quote = None if quote == char else char if quote is None else quote
            continue
        if quote:
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _markdown_destination(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.startswith("<"):
        closing = value.find(">")
        if closing < 0:
            return None
        destination = value[1:closing]
        remainder = value[closing + 1 :].strip()
    else:
        depth = 0
        end = len(value)
        for index, char in enumerate(value):
            if _is_escaped(value, index):
                continue
            if char == "(":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif char.isspace() and depth == 0:
                end = index
                break
        destination = value[:end]
        remainder = value[end:].strip()

    if remainder and not (
        (remainder.startswith('"') and remainder.endswith('"'))
        or (remainder.startswith("'") and remainder.endswith("'"))
        or (remainder.startswith("(") and remainder.endswith(")"))
    ):
        return None
    return re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", destination)


def _reference_label(value: str) -> str:
    return " ".join(value.split()).casefold()


def _reference_definitions(lines: list[tuple[int, str]]) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for _, line in lines:
        match = re.match(r"^[ ]{0,3}\[([^\]]+)\]:\s*(.+)$", line)
        if not match:
            continue
        destination = _markdown_destination(match.group(2))
        if destination is not None:
            definitions.setdefault(_reference_label(match.group(1)), destination)
    return definitions


def _line_links(line: str, definitions: dict[str, str]) -> list[str]:
    targets: list[str] = []
    index = 0
    while index < len(line):
        if line[index] != "[" or _is_escaped(line, index):
            index += 1
            continue
        if index > 0 and line[index - 1] == "!" and not _is_escaped(line, index - 1):
            index += 1
            continue
        label_end = _matching_delimiter(line, index, "[", "]")
        if label_end is None:
            index += 1
            continue
        cursor = label_end + 1
        target: str | None = None
        final_index = label_end
        if cursor < len(line) and line[cursor] == "(":
            target_end = _matching_delimiter(
                line,
                cursor,
                "(",
                ")",
                honor_quotes=True,
            )
            if target_end is not None:
                target = _markdown_destination(line[cursor + 1 : target_end])
                final_index = target_end
        elif cursor < len(line) and line[cursor] == "[":
            reference_end = _matching_delimiter(line, cursor, "[", "]")
            if reference_end is not None:
                reference = line[cursor + 1 : reference_end]
                if not reference:
                    reference = line[index + 1 : label_end]
                target = definitions.get(_reference_label(reference))
                final_index = reference_end
        elif not (cursor < len(line) and line[cursor] == ":"):
            target = definitions.get(_reference_label(line[index + 1 : label_end]))
        if target is not None:
            targets.append(target)
            index = final_index + 1
        else:
            index = label_end + 1
    return targets


def relative_markdown_links(
    file_path: Path, *, markdown_text: str | None = None
) -> list[RelativeMarkdownLink]:
    links: list[RelativeMarkdownLink] = []
    lines = _navigable_lines(
        file_path.read_text(encoding="utf-8") if markdown_text is None else markdown_text
    )
    definitions = _reference_definitions(lines)
    for line_number, line in lines:
        for target in _line_links(line, definitions):
            normalized_target = target.strip()
            if normalized_target.startswith("<") and normalized_target.endswith(">"):
                normalized_target = normalized_target[1:-1]
            if is_external(normalized_target):
                continue
            path_only = unquote(urlsplit(normalized_target).path)
            if not path_only:
                continue
            links.append(
                RelativeMarkdownLink(
                    file_path=file_path,
                    line=line_number,
                    target=target,
                    resolved=(file_path.parent / path_only).resolve(),
                )
            )
    return links


def missing_relative_links(root: Path) -> list[LinkIssue]:
    missing: list[LinkIssue] = []
    for file_path in iter_markdown(root):
        for link in relative_markdown_links(file_path):
            ok = link.resolved.is_dir() if link.target.split("#", 1)[0].endswith(("/", "\\")) else link.resolved.exists()
            if not ok:
                missing.append(
                    LinkIssue(
                        file_path=file_path,
                        line=link.line,
                        target=link.target,
                    )
                )
    return missing


def render_errors(path: Path, errors: list[str], *, stderr: TextIO | None = None) -> int:
    stream = stderr or sys.stderr
    for error in errors:
        print(f"{path}: {error}", file=stream)
    return 1 if errors else 0


def render_link_errors(issues: list[LinkIssue], *, stderr: TextIO | None = None) -> int:
    stream = stderr or sys.stderr
    for issue in issues:
        print(f"{issue.file_path}:{issue.line}: missing {issue.target}", file=stream)
    return 1 if issues else 0
