#!/usr/bin/env python3
"""Render a structured summary JSON file to standalone HTML."""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote


SCRIPT_DIR = Path(__file__).resolve().parent
SHARED = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SHARED))
DEFAULT_TEMPLATE = SCRIPT_DIR.parent / "templates" / "summary.html"
WALKTHROUGH_STYLES = """
    .file-list a {
      color: var(--accent);
      text-underline-offset: 2px;
    }
    .call-tree {
      border: 1px solid #2a3a48;
      line-height: 1.75;
      white-space: pre;
    }
    .walkthrough-progress {
      position: sticky;
      z-index: 2;
      top: 16px;
      display: grid;
      grid-template-columns: auto auto minmax(120px, 1fr);
      gap: 12px;
      align-items: center;
      padding: 12px 16px;
      color: var(--muted);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(23, 32, 42, 0.08);
    }
    .walkthrough-progress progress {
      width: 100%;
      accent-color: var(--accent);
    }
    .walkthrough-progress noscript {
      grid-column: 1 / -1;
      font-size: 13px;
    }
    .walkthrough-step {
      position: relative;
      padding-left: 76px;
    }
    .step-number {
      position: absolute;
      top: 20px;
      left: 20px;
      display: grid;
      min-width: 40px;
      height: 32px;
      padding: 0 8px;
      place-items: center;
      color: #ffffff;
      background: var(--accent);
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .completion-check {
      display: flex;
      gap: 10px;
      align-items: flex-start;
      margin-top: 18px;
      padding: 12px;
      background: var(--accent-soft);
      border-radius: 8px;
    }
    .completion-check input {
      width: 18px;
      height: 18px;
      margin-top: 3px;
      accent-color: var(--accent);
    }
    .handoff-ledger {
      display: grid;
      grid-template-columns: minmax(90px, 140px) 1fr;
      margin: 16px 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .handoff-ledger dt,
    .handoff-ledger dd {
      margin: 0;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }
    .handoff-ledger dt {
      color: var(--accent);
      background: var(--accent-soft);
      font-weight: 700;
    }
    .handoff-ledger dd:last-child,
    .handoff-ledger dt:nth-last-child(2) {
      border-bottom: 0;
    }
    .handoff-ledger ul {
      margin-top: 0;
    }
    @media (max-width: 820px) {
      .walkthrough-progress {
        position: static;
        grid-template-columns: auto 1fr;
      }
      .walkthrough-progress progress {
        grid-column: 1 / -1;
      }
    }
    @media print {
      nav, .walkthrough-progress {
        display: none;
      }
      body, main {
        background: #ffffff;
      }
      main {
        display: block;
        width: 100%;
        margin: 0;
      }
      section, .visual, .meta {
        break-inside: avoid;
        box-shadow: none;
      }
    }
"""

from summary_artifact import SummaryArtifactError, load_summary_artifact  # noqa: E402


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "section"


def paragraph(text: str) -> str:
    return f"<p>{esc(text)}</p>"


def render_list(items: list[str]) -> str:
    if not items:
        return ""
    lis = "\n".join(f"<li>{esc(item)}</li>" for item in items)
    return f"<ul>\n{lis}\n</ul>"


def source_file_href(path_value: str, *, source_root: Path, output_dir: Path) -> str:
    raw_path = Path(path_value)
    target = raw_path.resolve() if raw_path.is_absolute() else (source_root / raw_path).resolve()
    try:
        target.relative_to(source_root)
    except ValueError as exc:
        raise SummaryArtifactError(f"source file is outside source_root: {path_value}") from exc
    if not target.is_file():
        raise SummaryArtifactError(f"source file does not exist: {path_value}")
    relative = Path(os.path.relpath(target, output_dir)).as_posix()
    return quote(relative, safe="/._-")


def render_files(
    files: list[dict[str, Any]],
    *,
    source_root: Path | None = None,
    output_dir: Path | None = None,
) -> str:
    if not files:
        return ""
    rows: list[str] = []
    for item in files:
        path = esc(item["path"])
        path_html = f"<code>{path}</code>"
        if source_root is not None and output_dir is not None:
            href = esc(
                source_file_href(
                    str(item["path"]),
                    source_root=source_root,
                    output_dir=output_dir,
                )
            )
            path_html = f"<a href=\"{href}\"><code>{path}</code></a>"
        note = item.get("note")
        note_html = f"<div class=\"muted\">{esc(note)}</div>" if note else ""
        rows.append(f"<li>{path_html}{note_html}</li>")
    return "<h3>Referenced Files</h3>\n<ul class=\"file-list\">\n" + "\n".join(rows) + "\n</ul>"


def render_code_blocks(blocks: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for block in blocks:
        raw_language = str(block.get("language", "text"))
        language = esc(raw_language)
        text = esc(block["text"])
        pre_class = " class=\"call-tree\"" if raw_language == "call-tree" else ""
        rendered.append(f"<pre{pre_class}><code data-language=\"{language}\">{text}</code></pre>")
    return "\n".join(rendered)


def render_handoff_ledger(section: dict[str, Any]) -> str:
    rows = [
        ("Enter", f"<code>{esc(section['entry_symbol'])}</code>"),
        ("Receives", render_list(section["receives"])),
        ("Does", render_list(section["does"])),
        ("Hands off to", render_list(section["hands_off_to"])),
        ("Returns", render_list(section["returns"])),
    ]
    body = "\n".join(f"<dt>{esc(label)}</dt><dd>{value}</dd>" for label, value in rows)
    return f"<dl class=\"handoff-ledger\">\n{body}\n</dl>"


def render_sections(
    sections: list[dict[str, Any]],
    *,
    document_type: str,
    source_root: Path | None,
    output_dir: Path,
) -> tuple[str, str, list[str]]:
    nav_items: list[str] = []
    section_items: list[str] = []
    completion_ids: list[str] = []
    used_ids: set[str] = set()
    step_number = 0
    for index, section in enumerate(sections, start=1):
        title = str(section.get("title") or f"Section {index}")
        base_id = slugify(title)
        section_id = base_id
        counter = 2
        while section_id in used_ids:
            section_id = f"{base_id}-{counter}"
            counter += 1
        used_ids.add(section_id)
        nav_items.append(f"<a href=\"#{section_id}\">{esc(title)}</a>")

        completion_check = section.get("completion_check")
        is_step = document_type == "source_walkthrough" and bool(completion_check)
        section_class = " class=\"walkthrough-step\"" if is_step else ""
        parts: list[str] = [f"<section id=\"{section_id}\"{section_class}>"]
        if is_step:
            step_number += 1
            completion_ids.append(section_id)
            parts.append(f"<span class=\"step-number\">Step {step_number}</span>")
        parts.append(f"<h2>{esc(title)}</h2>")
        summary = section.get("summary")
        if summary:
            parts.append(paragraph(str(summary)))
        for item in section.get("paragraphs", []) or []:
            parts.append(paragraph(str(item)))
        if is_step:
            parts.append(render_handoff_ledger(section))
        parts.append(render_list(section.get("bullets", []) or []))
        parts.append(
            render_files(
                section.get("files", []) or [],
                source_root=source_root if document_type == "source_walkthrough" else None,
                output_dir=output_dir if document_type == "source_walkthrough" else None,
            )
        )
        parts.append(render_code_blocks(section.get("code", []) or []))
        if is_step:
            parts.append(
                "<label class=\"completion-check\">"
                f"<input type=\"checkbox\" data-progress-check data-progress-key=\"{section_id}\">"
                f"<span>{esc(completion_check)}</span>"
                "</label>"
            )
        parts.append("</section>")
        section_items.append("\n".join(part for part in parts if part))
    return "\n".join(nav_items), "\n".join(section_items), completion_ids


def render_walkthrough_progress(completion_ids: list[str]) -> str:
    if not completion_ids:
        return ""
    total = len(completion_ids)
    return (
        "<div class=\"walkthrough-progress\" aria-label=\"Walkthrough progress\">"
        "<strong>Progress</strong>"
        f"<span data-progress-count>0 / {total}</span>"
        f"<progress data-progress-bar value=\"0\" max=\"{total}\">0 / {total}</progress>"
        "<noscript>Progress persistence requires JavaScript; every walkthrough step remains readable below.</noscript>"
        "</div>"
    )


def render_walkthrough_script(completion_ids: list[str], data: dict[str, Any]) -> str:
    if not completion_ids:
        return ""
    identity = "\n".join(
        [
            str(data.get("title", "")),
            str(data.get("source_root", "")),
            str(data.get("scope_label", "")),
            *completion_ids,
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    script = """<script>
(() => {
  const checks = [...document.querySelectorAll("[data-progress-check]")];
  const count = document.querySelector("[data-progress-count]");
  const bar = document.querySelector("[data-progress-bar]");
  const storagePrefix = "summary-in-html:walkthrough:__DIGEST__:";
  let storage = null;

  try {
    const probe = `${storagePrefix}probe`;
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    storage = localStorage;
  } catch {
    storage = null;
  }

  const update = () => {
    const completed = checks.filter((check) => check.checked).length;
    if (count) count.textContent = `${completed} / ${checks.length}`;
    if (bar) {
      bar.value = completed;
      bar.textContent = `${completed} / ${checks.length}`;
    }
  };

  checks.forEach((check) => {
    const key = `${storagePrefix}${check.dataset.progressKey}`;
    if (storage) check.checked = storage.getItem(key) === "true";
    check.addEventListener("change", () => {
      if (storage) storage.setItem(key, String(check.checked));
      update();
    });
  });

  update();
})();
</script>"""
    return script.replace("__DIGEST__", digest)


def render_meta(data: dict[str, Any]) -> str:
    rows: list[str] = []
    for label, key in [
        ("Scope", "scope_label"),
        ("Source root", "source_root"),
        ("Source revision", "source_revision"),
        ("Generated", "generated_at"),
    ]:
        value = data.get(key)
        if value:
            rows.append(f"<div><strong>{label}:</strong> <code>{esc(value)}</code></div>")
    evidence = data.get("evidence", []) or []
    if evidence:
        chips = []
        for item in evidence:
            label = item.get("label", "Evidence")
            path = item["path"]
            role = item.get("role")
            if role:
                label = f"{label} ({str(role).replace('_', ' ')})"
            chips.append(f"<span class=\"pill\">{esc(label)}: {esc(path)}</span>")
        rows.append("<div>" + " ".join(chips) + "</div>")
    if not rows:
        return ""
    return "<div class=\"meta\">\n" + "\n".join(rows) + "\n</div>"


def render_visuals(assets: list[dict[str, Any]]) -> str:
    if not assets:
        return ""
    figures: list[str] = []
    for asset in assets:
        src = esc(asset["path"])
        alt = esc(asset["alt"])
        caption = esc(asset["caption"])
        figures.append(
            "<figure class=\"visual\">"
            f"<img src=\"{src}\" alt=\"{alt}\">"
            f"<figcaption>{caption}</figcaption>"
            "</figure>"
        )
    return "\n".join(figures)


def render_blind_spots(items: list[str]) -> str:
    if not items:
        return ""
    return "<section id=\"blind-spots\">\n<h2>Blind Spots</h2>\n" + render_list(items) + "\n</section>"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Structured summary JSON file.")
    parser.add_argument("--out", required=True, type=Path, help="Output HTML file.")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    args = parser.parse_args()

    try:
        artifact = load_summary_artifact(args.input)
    except SummaryArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    data = artifact.data
    artifact.ensure_generated_at()
    title = artifact.title
    document_type = str(data.get("document_type", "summary"))
    source_root: Path | None = None
    if document_type == "source_walkthrough":
        raw_source_root = Path(str(data["source_root"])).expanduser()
        if not raw_source_root.is_absolute():
            print("source_walkthrough source_root must be an absolute path", file=sys.stderr)
            return 1
        source_root = raw_source_root.resolve()
        if not source_root.is_dir():
            print(f"source_walkthrough source_root is not a directory: {source_root}", file=sys.stderr)
            return 1
    try:
        nav, sections_html, completion_ids = render_sections(
            artifact.sections,
            document_type=document_type,
            source_root=source_root,
            output_dir=args.out.parent.resolve(),
        )
    except SummaryArtifactError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    subtitle = data.get("subtitle")
    subtitle_html = f"<p class=\"subtitle\">{esc(subtitle)}</p>" if subtitle else ""
    footer = "Generated by the summary-in-html workflow."

    try:
        template = args.template.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"failed to read template: {args.template}: {exc}", file=sys.stderr)
        return 1

    replacements = {
        "{{title}}": esc(title),
        "{{heading}}": esc(data.get("heading", title)),
        "{{document_class}}": "source-walkthrough" if document_type == "source_walkthrough" else "reference-summary",
        "{{walkthrough_styles}}": WALKTHROUGH_STYLES if document_type == "source_walkthrough" else "",
        "{{subtitle}}": subtitle_html,
        "{{nav}}": nav,
        "{{meta}}": render_meta(data),
        "{{progress}}": render_walkthrough_progress(completion_ids),
        "{{visuals}}": render_visuals(data.get("assets", []) or []),
        "{{sections}}": sections_html,
        "{{blind_spots}}": render_blind_spots(data.get("blind_spots", []) or []),
        "{{footer}}": esc(data.get("footer", footer)),
        "{{script}}": render_walkthrough_script(completion_ids, data),
    }
    html_text = template
    for needle, value in replacements.items():
        html_text = html_text.replace(needle, value)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_text, encoding="utf-8")
    print(f"wrote html: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
