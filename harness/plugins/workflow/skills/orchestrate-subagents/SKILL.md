---
name: orchestrate-subagents
description: Use when the user explicitly asks for `$orchestrate-subagents`, subagents, parallel agents, or multi-agent delegation; tool availability and task parallelism alone are not triggers.
---

# Orchestrate Subagents

Use only when the user explicitly asks for this skill, subagents, parallel agents, or multi-agent delegation. The active instruction chain or an approved plan owns delegation and mutation authority; capability alone does not grant either.

## Assignment Contract

Choose the minimum useful set of independent assignments. Each assignment uses a unique `task_name` and a self-contained assignment prompt naming:

- the task, bounded scope, relevant context and evidence;
- expected output and stopping condition;
- explicit read-only permission with a ban on edits and commits, or an exact disjoint write scope with shared and forbidden paths identified.

Use natural prose or a short structure as needed; these facts matter, not a fixed prompt shape. For reproduction commands, name any authorized temporary/build outputs even when source is read-only. Implementation assignments preserve concurrent work and stop before edits outside their owned paths.

## Workflow

1. Freeze the parent outcome, required gates, non-goals, and shared artifacts. Use the applicable row of [task patterns](references/task-patterns.md) to choose useful slices; no fixed number of branches or reviewers is required.
2. Keep the parent agent responsible for planning, final decisions, shared files, generated artifacts, integration, cross-slice validation, and the user-facing conclusion. Continue independent parent work while agents run.
3. Wait for selected results. Surface missing tools, policy blocks, timeouts, incomplete coverage, conflicts, and missing evidence as `partial` or `blocked`. Apply the global subagent-failure policy before integration; do not substitute assumptions for missing results.
4. Review returned evidence and resolve disagreements. Subagent output is input to parent judgment, not final validation.

## Completion

Account for every selected assignment and confirm the parent independently reviewed its evidence. Report findings, commands/results, coverage gaps, and blockers; for implementation include changed behavior and parent validation. Keep failures visible and write scopes disjoint.
