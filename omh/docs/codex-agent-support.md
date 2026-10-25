# Codex Agent Support

This document explains how `oh-my-harness` manages Codex agent support files. `agents/global-instructions.md` is the separate harness-global source; root `AGENTS.md` remains repository-local.

The repository currently keeps only one managed support file under `agents/`.
That file is copied into `$CODEX_HOME/agents/` so global instructions can refer
to it from any Codex session.

## Managed Source

```text
agents/operating-principles.md
```

## Managed Target

```text
$CODEX_HOME/agents/operating-principles.md
```

Use `scripts/sync_codex_agents.py` to copy repo-managed support files from
`agents/` into the target. The script currently syncs only the managed support
file listed above. Do not hand-edit managed target files; edit the source file
here and sync again.

## Current Policy

The sync script ignores local `agents/*.toml` custom-agent presets today. The
`workflow` plugin's `$orchestrate-subagents` skill uses unique `task_name`
assignments whose prompts declare read-only permission or an exact disjoint
write scope, so legacy local presets are neither synced nor installed by this
support-file path.

## Future Custom Agents

The [follow-up plan](todo/subagent-orchestration-follow-up.md) owns the evidence and design requirements for any future custom-agent presets.
