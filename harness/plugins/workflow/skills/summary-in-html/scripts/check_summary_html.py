#!/usr/bin/env python3
"""Validate a summary-in-html artifact and local asset references."""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


REMOTE_CSS_URL_RE = re.compile(
    r"url\(\s*[\"']?\s*(?:https?:)?//",
    re.IGNORECASE,
)
CSS_IMPORT_RE = re.compile(r"@import\b", re.IGNORECASE)


class DocumentAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.image_sources: list[str] = []
        self.script_sources: list[str] = []
        self.stylesheet_hrefs: list[str] = []
        self.style_chunks: list[str] = []
        self._inside_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
        if tag == "a" and values.get("href"):
            self.hrefs.append(str(values["href"]))
        if tag == "img" and values.get("src"):
            self.image_sources.append(str(values["src"]))
        if tag == "script" and values.get("src"):
            self.script_sources.append(str(values["src"]))
        if tag == "link" and "stylesheet" in str(values.get("rel", "")).lower():
            self.stylesheet_hrefs.append(str(values.get("href", "")))
        if tag == "style":
            self._inside_style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._inside_style = False

    def handle_data(self, data: str) -> None:
        if self._inside_style:
            self.style_chunks.append(data)


def is_external(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "mailto:", "tel:", "data:"))


def local_path(base: Path, value: str) -> Path | None:
    if not value or value.startswith("#") or is_external(value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    return (base / path).resolve()


def same_page_fragment(path: Path, href: str) -> str | None:
    parsed = urlsplit(href)
    if not parsed.fragment:
        return None
    if not parsed.path:
        return unquote(parsed.fragment)
    target = (path.parent / unquote(parsed.path)).resolve()
    if target == path.resolve():
        return unquote(parsed.fragment)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_file", type=Path)
    args = parser.parse_args()

    path = args.html_file
    if not path.exists():
        print(f"missing HTML file: {path}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"HTML path is not a file: {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    lower = text.lower()
    if "<!doctype html>" not in lower:
        errors.append("missing <!doctype html>")
    if "<html" not in lower or "</html>" not in lower:
        errors.append("missing html root tags")
    if "<main" not in lower:
        errors.append("missing main element")
    if "<h1" not in lower:
        errors.append("missing h1 heading")
    if lower.count("<section") < 1:
        errors.append("missing section content")
    if "{{" in text or "}}" in text:
        errors.append("unresolved template braces")
    if "__TITLE__" in text or "__BODY__" in text:
        errors.append("unresolved template placeholder")

    audit = DocumentAudit()
    audit.feed(text)

    seen_ids: set[str] = set()
    for element_id in audit.ids:
        if element_id in seen_ids:
            errors.append(f"duplicate id: {element_id}")
        seen_ids.add(element_id)

    if audit.script_sources:
        for src in audit.script_sources:
            errors.append(f"external script dependency is not allowed: {src}")
    if audit.stylesheet_hrefs:
        for href in audit.stylesheet_hrefs:
            errors.append(f"external stylesheet dependency is not allowed: {href}")

    css = "\n".join(audit.style_chunks)
    if CSS_IMPORT_RE.search(css):
        errors.append("CSS @import dependency is not allowed")
    if REMOTE_CSS_URL_RE.search(css):
        errors.append("remote CSS url dependency is not allowed")

    base = path.parent
    for src in audit.image_sources:
        if src.lower().startswith(("http://", "https://", "//")):
            errors.append(f"remote image asset is not allowed: {src}")
            continue
        target = local_path(base, src)
        if target and not target.exists():
            errors.append(f"missing local image asset: {src}")

    for href in audit.hrefs:
        fragment = same_page_fragment(path, href)
        if fragment and fragment not in seen_ids:
            errors.append(f"missing local fragment target: {href}")
        target = local_path(base, href)
        if target and not target.exists():
            errors.append(f"missing local link target: {href}")

    if errors:
        for error in errors:
            print(f"{path}: {error}", file=sys.stderr)
        return 1

    print(f"{path}: HTML checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
