---
name: summary-in-html
description: Create a standalone HTML developer reference or source-code walkthrough for a bounded scope, including step-by-step code handoffs from real entry points; generate visual assets only when explicitly requested.
---

# Summary In HTML

Create one inspectable HTML handoff from repository evidence.

Choose one document type:

- `summary` (default): explain ownership, structure, behavior, and developer operations.
- `source_walkthrough`: follow real entry points and function handoffs so a developer can take over unfamiliar code.

Use Watcher `doc-alignment` instead when the task is to find stale or contradictory documentation.

## Workflow

1. Freeze the scope, document type, and output path. Read `references/scope_contract.md` when the boundary is ambiguous.

## Common Evidence Inventory

Before mode-specific authoring, both document types share only this evidence-inventory stage. Collect a read-only inventory:

```bash
python <skill-folder>/scripts/collect_summary_inputs.py --root <repo-root> --scope <scope-path> --out <artifact>.inputs.json
```

Inspect candidate evidence from source, README/AGENTS files, package configuration, tests, scripts, and nearby docs. Record only the files and source-of-truth status needed to support the requested scope; mode-specific authoring determines later inspection.

## Document-Type Routing

- For every `summary`, read `references/chapter_contract.md`, choose only chapters supported by the evidence inventory, and inspect the evidence needed for those chapters.
- For `source_walkthrough`, read `references/source_walkthrough_contract.md`, find the real entry point, and trace the complete caller, handoff, and return route before authoring numbered handoff steps. Only this branch performs the complete route trace.

## Shared Artifact Steps

1. Read `references/artifact-schema.md`, write the structured JSON next to the target, and render:

```bash
python <skill-folder>/scripts/render_summary_html.py --input <summary>.json --out <summary>.html
```

2. When the user explicitly requests generated visuals, read `references/visual_asset_contract.md` and include accessible asset metadata. Otherwise keep the artifact text-first.
3. Validate and fix failures before completion:

```bash
python <skill-folder>/scripts/check_summary_html.py <summary>.html
```

## Completion

Report the scope, document type, HTML path, supporting assets, evidence paths or commands, validation result, and blind spots.

The result is standalone, source-grounded, and useful without remote fonts or scripts. Reader progress controls are navigation, not verification evidence. Preserve an existing summary unless replacement was requested; otherwise choose a more specific or versioned filename.
