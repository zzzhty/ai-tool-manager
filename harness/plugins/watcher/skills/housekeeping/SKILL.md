---
name: housekeeping
description: Remove inventoried disposable artifacts after migration, validation, audit, or other bounded workspace work while preserving user work, durable state, and semantic guidance.
---

# Housekeeping

Use this skill for bounded implementation-mode removal of physical disposable artifacts. Use `doc-alignment` to audit or repair semantic guidance.

## Core Contract

Delete only artifacts whose ownership and disposability are established by inspection. Preserve everything else unless the user approves the exact path or class.

Classify candidates into three groups:

1. **Disposable generated artifacts** — ignored Python/test caches, OS/editor noise, files under known temporary/cache roots, and confirmed superseded local plugin cache versions. These may be removed after inventory.
2. **Protected or approval-required state** — tracked or untracked source-looking files, local/private configuration, databases, reports, audit/runtime state, dependency installs, build/deploy output, migrations, and unknown binaries. Preserve and report these unless explicitly authorized.
3. **Semantic guidance** — README, AGENTS, runbook, skill, TODO, or index content. Keep it unchanged in this workflow and hand active drift to `doc-alignment` with the exact path and evidence.

Archive content remains protected. Hand active-navigation or current-summary drift to `doc-alignment`.

## Workflow

1. Read current truth: root instructions, relevant cleanup guidance, `.gitignore`, manifests, hook configuration, and artifact ownership rules.
2. Inventory the target. Use the default `git` target kind for a worktree; set `HOUSEKEEPING_TARGET_KIND=cache` only for an already identified non-Git cache root. Git inventory failures remain failures, not evidence of a non-Git target. The executable block below is for POSIX Bash; on Windows, use native PowerShell commands with the same absolute-path, read-only, exclusion, and symlink-boundary gates:

```bash
set -euo pipefail
: "${HOUSEKEEPING_TARGET:?set HOUSEKEEPING_TARGET to an absolute bounded path}"
housekeeping_target=$HOUSEKEEPING_TARGET
[[ "$housekeeping_target" == /* && -d "$housekeeping_target" ]] || {
  printf 'invalid housekeeping target: %s\n' "$housekeeping_target" >&2
  exit 2
}
case "${HOUSEKEEPING_TARGET_KIND:-git}" in
  git)
    git -C "$housekeeping_target" status --short -- .
    git -C "$housekeeping_target" status --ignored --short -- .
    ;;
  cache) ;;
  *) printf 'unknown housekeeping target kind\n' >&2; exit 2 ;;
esac
find "$housekeeping_target" \
  \( -type d \( -name .git -o -name node_modules -o -name .venv \) -prune \) -o \
  \( -type d \( -name __pycache__ -o -name .pytest_cache \) -print \)
```

3. Record the classification and reason for each candidate class.
4. Remove disposable artifacts with exact paths or tightly bounded patterns. Keep protected state and semantic guidance untouched; identify required approval or the `doc-alignment` handoff.
5. Re-run the relevant physical inventory. Use the owning validator only when the artifact-producing configuration or script changed.
6. When an artifact-producing configuration, script, tool, or hook recreates disposable noise, repair that production behavior only when the user's mutation scope explicitly includes it; this is code/config behavior, not semantic-guidance alignment. Otherwise report the recreating command and blocker.

## Completion

Report what was removed, preserved, or handed to `doc-alignment`, the evidence supporting each classification, validation results, and unresolved approval-required state. Cleanup is complete only when the targeted physical noise is gone without losing user work, durable state, semantic guidance, or historical evidence.
