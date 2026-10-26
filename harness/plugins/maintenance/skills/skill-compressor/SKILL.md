---
name: skill-compressor
description: Reduce the instruction footprint of agent skills, plugin guidance, and their references while preserving trigger coverage, required behavior, and validation owned by the changed surface.
---

# Skill Compressor

Use this skill for behavior-preserving instruction reduction. Use `workflow:prompt-strategy-loop` when the requested change intentionally redesigns routing, permissions, safety, failure, or validation behavior. Use `skill-maintainer` when Watcher usage evidence should produce a proposal rather than direct compression. Deterministic scripts remain out of scope unless the user explicitly includes them.

## Core Rule

Compare the candidate with the inspected baseline and a scoped inventory of affected meanings. A smaller file is not equivalent when trigger coverage, permissions, stop or failure behavior, validators, or unique edge cases drift.

When the inventory identifies an intentional meaning change, stop this behavior-preserving workflow and route the candidate through `workflow:prompt-strategy-loop`. Its Core Rule is the single owner of proportional review decisions. If that skill is unavailable or its required evaluation cannot run, keep the candidate explicitly unverified.

Invoking this skill authorizes only the read-only semantic comparison needed for compression; mutation and unrelated delegation still follow the active request and environment.

## Workflow

1. Bound the editable skill metadata, body, references, templates, and helper surfaces. Preserve unrelated dirty work.
2. Identify the exact input being compared. Before mutation, ensure a recoverable baseline through Git history, diff, or an authorized bounded copy. Read-only analysis of dirty, untracked, or non-Git inputs may continue without creating a backup; describe the inspected input and leave any untested candidate explicitly unverified.
3. Inventory the affected trigger/routing branches, permissions, stops, failure handling, validators, and unique edge cases; freeze this affected-meaning inventory as the equivalence oracle.
4. Compress attention, not meaning:
   - keep common execution steps and non-default invariants inline;
   - disclose conditional detail one level deep behind a strong pointer;
   - leave field-heavy contracts with existing templates, scripts, schemas, or checkers;
   - remove duplicated meaning, stale history, motivation, obvious advice, and repeated examples unless one disambiguates behavior;
   - prefer positive target behavior while retaining true destructive, privacy, external-write, and source/cache guardrails.
5. Validate only the affected surface: skill/frontmatter validation, relative links, owning plugin or domain checks when their contract changed, and `git diff --check -- <changed-paths>`.
6. Compare the candidate with the baseline and equivalence oracle, fix unintended drift, and repeat only affected checks.
7. Refresh installed state only when activation is authorized.

## Completion

Report changed files, size change when relevant, preserved and intentionally changed behavior, checks run, reviewer status, blockers, and residual risk. Claim equivalence only when every affected meaning remains reachable and the candidate passes its equivalence oracle.
