#!/usr/bin/env python3
"""Minimal terminal emphasis with plain redirected output."""

from __future__ import annotations

import os
import sys
from typing import Literal, TextIO


TerminalColor = Literal["red", "yellow"]
ANSI_CODES: dict[TerminalColor, str] = {
    "red": "1;31",
    "yellow": "1;33",
}


def color_enabled(stream: TextIO) -> bool:
    if "NO_COLOR" in os.environ or os.environ.get("TERM", "").lower() == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, OSError):
        return False


def emphasize(text: str, *, color: TerminalColor, stream: TextIO) -> str:
    if not color_enabled(stream):
        return text
    return f"\x1b[{ANSI_CODES[color]}m{text}\x1b[0m"


def write_stderr(text: str, *, color: TerminalColor = "red") -> None:
    stream = sys.stderr
    print(emphasize(text, color=color, stream=stream), file=stream, flush=True)
