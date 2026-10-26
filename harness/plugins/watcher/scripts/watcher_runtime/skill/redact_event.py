#!/usr/bin/env python3
"""Redact secret-like fields and values from Watcher skill events."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REDACTION = "[REDACTED]"

SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])("
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|"
    r"password|passwd|secret|client[_-]?secret|private[_-]?key|"
    r"authorization|credential|credentials"
    r")(?:$|[_-])",
    re.IGNORECASE,
)

SECRET_VALUE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
]


def is_secret_key(key: str) -> bool:
    return SECRET_KEY_RE.search(key) is not None


def redact_string(value: str) -> str:
    redacted = value
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTION, redacted)
    return redacted


def redact_event(value: Any, *, parent_key: str | None = None) -> Any:
    if parent_key is not None and is_secret_key(parent_key):
        return REDACTION
    if isinstance(value, dict):
        return {key: redact_event(item, parent_key=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_event(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


def read_payload(path: str | None) -> Any:
    if path:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"failed to read input path {path}: {exc}") from exc
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("no JSON input provided on stdin or --input")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        source = path or "stdin"
        raise SystemExit(f"invalid JSON from {source}: line {exc.lineno}, column {exc.colno}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watcher skill redact-event",
        description="Redact a Watcher skill event JSON object.",
    )
    parser.add_argument("--input", help="Path to a JSON file. Defaults to stdin.")
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation for stdout.")
    args = parser.parse_args(argv)

    payload = read_payload(args.input)
    json.dump(redact_event(payload), sys.stdout, indent=args.indent, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
