# Planning Preflight

Before creating or converting a long-running goal, or first implementing one without a completed marker, verify its scope, owner boundaries, non-goals, compatibility, validation, rollback, milestone order, and action permissions.

## Required Flow And Reuse

Before `Ready` or implementation without a valid completed preflight:

Choose the path first: reuse of a verified, still-valid completed preflight does not repeat the interview unless the user requests a fresh one. An explicit user skip omits the interview but still requires decision and authorization coverage. For either path, apply the evidence and authorization sections below directly; otherwise complete the full flow:

1. Read the active request, existing decisions, current evidence and recorded authority. A valid completed preflight can be reused after checking that it still covers the affected contract. A marker or a complete-looking plan alone is insufficient.
2. Read and apply `mattpocock-skills:grilling` and `mattpocock-skills:domain-modeling`, using the active harness's identities. This required composition performs the `grill-with-docs` workflow without implicitly invoking its explicit-only entrypoint. If the user explicitly invokes `grill-with-docs`, use that entrypoint instead. If a required method cannot be loaded, report the missing skill and keep preflight incomplete; do not silently substitute self-review or claim completion.
3. Use grilling to check scope, ownership, non-goals, compatibility, validation, rollback, milestone order and the authorization coverage below. Reuse confirmed answers; ask only consequential unresolved questions in the method's dependency-aware rounds. Wait for required answers. No new questions are necessary when sourced answers already cover the entire contract, but the coverage check is still required.
4. Record the resolved decisions and their sources in the goal. Apply domain-modeling's document ownership and value criteria; reuse existing docs, and create glossary/ADR content only when useful and authorized.
5. Record the evidence below and run the applicable readiness checks before claiming `Ready`. Approval of action scope during planning does not itself request execution.

A completed marker with supporting evidence prevents repeated preflight. Revalidate only the affected decisions when scope, ownership, product semantics, order, or authorization changes enough to invalidate them. Ordinary path, command, baseline, estimate, milestone or context-transition updates do not invalidate the marker. For an older active goal, recover missing evidence from inspectable sources or complete the missing part now; never invent a past interview, approval or skip. Preserve Closed historical records.

## Record The Result

Record these fields in the goal:

```text
Planning preflight marker: preflight:<goal_slug>:<yyyymmdd>-<short-id>
Planning preflight status: Done
Preflight source: grilling + domain-modeling / grill-with-docs / existing decisions
Preflight evidence: Completed: <source reference and checked outcome>
Resolved decisions: <concrete summary or source paths>
Open decisions: <none or declared runtime hard stops>
Docs written: <written or reused doc paths / Not applicable: reason>
```

`Done` requires the completed workflow or a sourced, still-valid completed preflight. Direct composition uses source `grilling + domain-modeling`; an explicit wrapper invocation uses `grill-with-docs`. For `existing decisions`, use `Preflight evidence: Reused: <completed preflight id, source reference and current coverage result>`; ordinary design docs are inputs, not proof of a prior preflight.

Only an explicit user instruction skips the interview. Use a `preflight:<goal_slug>:skip:<yyyymmdd>-<short-id>` marker, status `Skipped by explicit user instruction`, source `user skip`, and `Preflight evidence: User skip: <user instruction source>`. Never infer skip from urgency, a complete plan, silence or a direct implementation request. Skip never supplies missing authority or turns unresolved required design into `Ready`; still complete authorization coverage and decision records.

Evidence references must locate the source: a Markdown link to an existing document or a dated user request/message/turn reference (or `conversation:<id> turn:<id>`). Keep evidence fields visible, one field per line. Checkers verify required evidence, local link existence and declared consistency; they do not authenticate user approval or prove that a method ran. Read and verify the cited source before consuming it.

## Authorization Coverage Through Close

Walk the actual planned actions from the first milestone through Close, including applicable source-skill edits, checkpoint commits, remote writes, installation/activation, release, automation and housekeeping. Do not ask about categories the plan does not use. For each action, record its target, scope, conditions and authority source in the existing `Pre-Approval / YOLO` section; use its `Authorization evidence` field to map sources to the covered actions and milestones. Cite Housekeeping's separate policy/source instead of granting cleanup here. Sequence parents reference each child's own authority.

Reuse authority already supplied by the request or an approved plan. Resolve uncovered permissions in the relevant grilling frontier, before `Ready`; do not routinely defer them to later milestones. Undefined boundaries remain `Draft`. A precise conditional approval, such as execution after validation passes, remains approval when its conditions hold. Future code or artifacts not yet existing is not by itself a reason to re-ask for an already covered action.

## Deferred Approval Gates

After authorization coverage, a known later action may await approval when the user explicitly retains that decision or an applicable rule requires final review of concrete results. Record the source and the review material/condition still required. Do not create a gate merely because the action happens later. Record deferred actions outside the pre-approved operations; omit the section when none are deferred:

```markdown
## Deferred approval gates

| Milestone | Action | Status | Approval evidence | Deferral basis |
| --- | --- | --- | --- | --- |
| M2 | Publish the reviewed release to the named production target | Pending | None | User decision: 2026-09-09 user turn 3 reserves approval until the release diff is reviewed |
```

Each row must name an existing milestone (`M0` through `Close`) and a concrete action, target, scope and conditions. Its status is `Pending` or `Approved`. `Deferral basis` starts with `User decision:` or `Required review:` and includes a source reference; preserve it after approval. `Approved` requires sourced actual user authorization in `Approval evidence`. Do not duplicate an action's gate or list the same covered action as both pre-approved and Pending. Different targets, scopes or conditions must be explicit in the action text.

Complete preparation in preceding milestones. At the gated milestone, first reconcile recorded approval with its source and any later change or withdrawal. If current authority covers the action, record Approved evidence and continue without asking again. Otherwise ask only for the reserved or uncovered decision. A pending gate can remain future/Ready or become `Blocked` with section-local evidence; it cannot be `In Progress`, `Done`, or bypassed at Close. Do not infer approval from `Ready`, a resume request, elapsed time, or checker success. Unspecified permission boundaries still keep the goal `Draft`; do not move or remove an existing gate without authorization.

## Optional Time Assessment

Estimate only when useful for a planning or scheduling decision. Use evidence already gathered plus at most one bounded inspection; do not launch builds, benchmarks, installs, CI waits, or external reads solely to estimate time.

A short `Preflight Time Assessment` section may give a rough remaining wall-clock range and its basis, including external waits and serial/parallel assumptions. If unknown, state the concrete reason; no distribution, fixed sentinel, or driver count is required. Estimates do not determine readiness and are not SLAs. Refresh only when the user asks or changed evidence affects a decision; an overrun alone is a non-stop. Sequence estimates must distinguish known child costs from unknown ones rather than imply a complete total.

## Task Temporary Cache / Housekeeping

Default to `Disabled`: retain task-owned temporary roots at Close. Do not ask the user merely to confirm this default. Use `Not applicable` when the plan creates no task temporary cache roots. Use `Enabled` only with explicit user authorization for the recorded cleanup scope; the goal remains `Draft` if its planned cleanup needs missing permission.

An existing `Enabled` contract remains in force; the default cannot silently replace it. A goal without this section grants no cleanup permission.

When recording a policy, include:

```text
Close housekeeping policy: Disabled
Task temporary cache root strategy: <owner-specific platform/runtime-resolved namespace, or no-root strategy>
Recorded task temporary cache roots: <owner-labeled absolute paths / Resolve and record before first use / None created / Not applicable>
Housekeeping boundary: <retention or authorized bounded cleanup and preservation rules>
```

Only `Enabled` additionally requires `Housekeeping decision source` with the user's explicit confirmation and date or turn context.

For `Enabled` or `Disabled`, before a producer writes temporary data, use the host platform or runtime's standard temporary-directory resolver, then allocate an owner-specific goal/sequence namespace beneath the resolved root. Do not prescribe `/tmp`, a fixed Windows path, an environment-variable expression, the shared system/user temporary root itself, a generic `tmp` / `temp` / `cache` root, or another owner's directory. Record each fully resolved absolute owner root with a `goal-owned:` or `sequence-owned:` label and bind subsequent task-temporary writes to that recorded namespace. Reuse the recorded value at Close rather than resolving the platform root again. For `Not applicable`, record directly that no task temporary cache root will be created; do not resolve or allocate one.

`Enabled` authorizes the housekeeping workflow, not unconditional recursive deletion. Inventory first; preserve dependencies, runtime state, logs, reports, durable evidence, unknown producers, locked files, permission boundaries, and symlink/junction/reparse-point escapes. Keep durable Close evidence outside the temporary cache root. If `watcher:housekeeping` is unavailable, do not substitute a raw delete command: keep Close and the overall goal `In Progress`, or mark Close `Blocked` only when the normal runtime hard-stop contract is met. Only a new explicit user decision recorded as a preflight-policy evolution may switch the policy to `Disabled`.
