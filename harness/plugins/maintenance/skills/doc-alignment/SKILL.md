---
name: doc-alignment
description: Audit or align documentation, scripts, skills, runbooks, operational entry points, and planning trees against repository source of truth; keep review-only and scheduled Watcher runs non-mutating.
---

# Doc Alignment

Keep current guidance, names, references, ownership, navigation, and validation aligned with the current source of truth. Historical material may preserve prior terms, but it must not remain active guidance.

## Contract

1. Identify current truth before proposing or making changes: root instructions, current overview and architecture docs, active plans, runtime guides, scripts, package commands, CI, configs, tests, or Watcher reports.
2. Use the current task and accepted constraints to determine mode and scope. New messages refine that task unless they explicitly pause, replace, or redirect it; do not import unrelated older goals.
3. Keep current guidance separate from history. Preserve real compatibility identifiers and historical terms only where their role is explicit.
4. In implementation mode, update every active path people or tools follow, including hidden configuration, resolved repository skill roots, wrappers, package commands, indexes, READMEs, and runbooks.
5. In report-only and scheduled modes, inventory drift, collect evidence, propose bounded fixes; target repositories remain read-only. The only permitted writes are Watcher-owned report or runtime state allowed by the selected branch under `$CODEX_HOME/watcher/doc/` or an explicit output path.
6. Treat broken links, stale paths, inconsistent names, failed audit commands, and failed validation as first-class failures in every mode. Only implementation mode repairs root causes; report-only and scheduled modes record the exact breakpoint and recommendation.

## Mode

For review, audit, analysis, comparison, assessment, report-only or scheduled scans, or explicit no-edit language, select report-only or scheduled mode and run only non-mutating commands against target repositories.

Use implementation mode when the user asks to align, update, reorganize, prune, rename, fix, or otherwise make changes. Apply the smallest sufficient edits in the owning files and validate them.

## Workflow

1. Freeze the target, mode, current authority, active-versus-history boundary, and write scope.
2. For a configured, scheduled, commit-dependent, or one-repository Watcher audit, read `references/watcher-audit.md` and complete that branch.
3. Inventory current entry points and disputed names, paths, commands, links, ownership, and validation claims. For script or entry-point naming, documentation-tree placement, planning/TODO navigation, agent skills, classification, severity, reporting, or validation selection, read `references/alignment-reference.md` and apply every matching section.
4. Classify drift against current truth, then apply the selected mode's write boundary and report or repair requirements above.
5. Complete any missing required checks and reuse valid results under the global verification policy; re-run only invalidated checks or explicit fresh-run requirements. Report exact failures and partial checks without presenting them as full validation.

## Completion

Report the mode, scope, current truth, entry points reviewed, evidence, changed or proposed semantics, moved or preserved history, validation commands and results, unresolved conflicts, and preserved legacy identifiers.

Report-only completion requires the scoped inventory, evidence-backed findings, recommendations, and disclosed coverage gaps; unresolved target drift does not prevent completing the audit. Leave target repositories unchanged. Implementation completes when the affected guidance is aligned and its required checks pass.
