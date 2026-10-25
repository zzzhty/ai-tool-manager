---
name: code-review
description: Review a PR, commit range or work-in-progress changes against repository standards and the requested behavior, including staged, unstaged and untracked work in scope.
---

# Code Review

Review along two independent axes: **Standards** (the repository's documented rules) and **Spec** (the requested behavior). Keep each axis visible even when findings overlap. Reviewing is read-only; missing tracker configuration does not authorize setup, file changes or external messages.

## Establish the scope

Use the user's or caller's stated range and task. Resolve refs and record the base, HEAD and working-tree status before reviewing. Infer a base from an identified PR or branch target when unambiguous; ask only when the missing choice changes the review scope.

- **Commit range:** compare the requested endpoints with `git diff <base> <tip>`. For a branch/PR review, resolve its merge-base with the target and compare that base to the branch tip. List relevant commits for intent and linked issues.
- **Uncommitted work:** inspect `git diff --cached` and `git diff` separately, plus `git ls-files --others --exclude-standard` and relevant untracked contents. `base...HEAD` alone excludes all of these.
- **Implementation review:** combine the caller's starting commit and change inventory with the current committed, staged, unstaged and untracked changes. Preserve the distinction between this task's work and pre-existing changes; do not infer ownership from status alone.

A combined diff can help read the net result, but must not conceal staged/unstaged differences. If the scope changes during review, report the coverage boundary. An empty in-scope diff means no changes to review; an invalid ref is a concrete diagnostic.

## Gather the requirements

Prefer the user-provided task/spec and originating PR or issue; then inspect linked commit references and relevant repository documents. Follow existing tracker instructions when needed. If no formal spec exists, review against the stated request and disclose missing requirements rather than fabricating them or running setup.

Read applicable AGENTS, CONTRIBUTING and coding standards. Repository rules override general design preferences. Use names, duplication, misplaced responsibilities, pass-through layers and speculative abstractions as investigation leads; report a design smell only when a changed path shows a concrete consequence. Do not turn every smell into a mandatory refactor or repeat findings already established by tooling.

## Review and report

For each axis, trace changed behavior through callers, dependencies and relevant tests. Check requirements that are missing, incorrectly implemented or outside the requested scope. Distinguish documented violations from design judgments and pre-existing defects.

Use independent reviewers when the scope warrants it and delegation is authorized. Give each a fixed scope, raw diff/spec/rules, read-only permission and a ban on writes. Report unavailable or incomplete coverage. Small reviews can cover both axes directly.

Merge duplicate findings and rank by impact, retaining their Standards/Spec labels. Each actionable finding names its location, trigger, consequence and supporting requirement or code path. Close with coverage and validation limits for both axes; no findings on one axis does not imply the other passed.
