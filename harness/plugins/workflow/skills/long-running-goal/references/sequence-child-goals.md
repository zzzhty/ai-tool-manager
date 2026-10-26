# Sequence Child Goals

Use this branch for a `Long-Running Goal Sequence`: one continuation-ready parent that authorizes and coordinates two or more already-bounded child goals in strict serial order. `umbrella` is only an informal alias; do not create a separate lifecycle or skill.

The parent and children retain the ordinary `Draft / Ready / In Progress / Closed`, `M0...Close`, checkpoint, YOLO, runtime-hard-stop, and close contracts from `../SKILL.md`. This reference adds cross-child rules; it never weakens the atomic rules.

## Contents

- Goal-tool and version boundary
- Mandatory planning preflights
- Canonical registers and state mapping
- Authorization, handoff, hard stops, validation, and close

## Goal-Tool And Version Boundary

1. Create at most one active harness system goal for the sequence parent. Child goal files are execution contracts, not nested system goals.
2. Version 1 is strictly serial. Do not model parallel children, DAG scheduling, per-child execution authorization, or an alternate promotion policy.
3. Use `../templates/long_running_goal_sequence_template.md`. Do not treat a narrative umbrella without both canonical registers as a sequence.
4. Give the parent milestones this exact shape: `M0` freezes the sequence baseline and promotes the first child; `M1...Mn` map one-to-one to child order; `M(n+1)` performs integration acceptance; then `Close`.
5. Set the sequence parent harness to `Loop-shaped execution`; predecessor Close and resume events drive automatic handoff inside one authorization. Child harness modes remain child-owned.

## Mandatory Planning Preflights

Before the sequence becomes `Ready`, the parent and every child must have a complete preflight marker/status/source tuple and supporting decision and authorization evidence under `../components/planning-preflight.md`. Direct `grilling + domain-modeling`, explicit `grill-with-docs`, sourced completed-preflight reuse via `existing decisions`, and explicit user skips follow the same rules as atomic goals. The `Child Preflight Register` must repeat each child's exact marker, status, and source; it does not replace reading the child and its evidence. Sequence `--allow-draft` relaxes lifecycle only, not these frozen child boundaries. Address uncovered child permissions during the planning frontier rather than asking again at each promotion.

Each newly created or explicitly evolved parent or child artifact must preflight its scope, owner, compatibility surface, dependency position, validation and rollback gates, external writes, destructive/privacy-sensitive actions, release/deploy boundary, non-goals, and task-temporary-cache housekeeping policy (default `Disabled`, explicit authorization for `Enabled`). The parent records a separate policy only for parent-owned orchestration/integration caches; it never inherits, widens, or overrides a child's policy. An untouched legacy parent or child whose entire new section is absent remains checker-compatible but grants no cleanup authorization; Close preserves any discovered roots and records that artifact's legacy disposition. `Open decisions` may contain only bounded runtime hard stops. Any unresolved scope, owner, dependency, permission for planned cleanup, or behavioral decision keeps a newly created or explicitly evolved artifact `Draft`.

A fully specified later action with a sourced user-retained or required final-review decision may remain Pending in its owner's `Deferred approval gates` under `../components/planning-preflight.md`. Put child gates in the child contract; parent execution or promotion never approves them. Reuse still-valid child-specific authority across promotion and context transitions. Earlier authorized stages follow the existing strict order, and the gated milestone's work waits for actual authorization. This does not add per-child execution approval or permit skipping a blocked child.

Timing is optional and stays out of canonical registers. If estimating the sequence, distinguish known child costs, unknown costs, and parent M0/Integration/Close overhead; do not claim a complete serial range from incomplete evidence.

Revalidate affected decisions and replace the marker for every affected parent or child marker when scope, ownership, compatibility semantics, child order/dependencies, or the external authorization surface changes materially. A path, command, tool version, or observed baseline change that does not alter those semantics is an evidence rebaseline and does not repeat preflight.

## Canonical Registers

Use these exact H2 headings and headers:

```markdown
## Child Preflight Register

| Child ID | Marker | Status | Source |
|---|---|---|---|

## Child Execution Register

| Order | Child ID | Parent milestone | Live goal | Closeout evidence | Depends on | State | Current milestone | Close revision |
|---|---|---|---|---|---|---|---|---|
```

Both registers must contain the same unique set of at least two child IDs. `Order` is unique and contiguous from `1`; `Parent milestone` is exactly `M<Order>`. `Depends on` may be `n/a` or name only earlier child IDs; the strict serial gate applies even when no dependency is listed.

Use only relative Markdown links or `n/a` in the two link columns. A non-`Closed` child must have a `Live goal` link and `Closeout evidence = n/a`. A `Closed` child uses `Live goal = n/a`, a relative `Closeout evidence` link to its complete archived atomic child goal (not a summary), a non-`n/a` revision, and `Current milestone = Close Done`; the archived goal must itself validate as `Closed`.

`State` is the child's overall lifecycle state. A `Draft` child records `Current milestone = n/a` and every atomic row as `Not Started / Pending / Pending`. A `Ready` child records `<M-id> Ready`; an `In Progress` child records `<M-id> In Progress` or `<M-id> Blocked`, matching the child file's unique current row.

The `Child Execution Register` is the sole current-state authority for child lifecycle and milestone position. Do not add `Current child:`, `Active child:`, or `Current child milestone:` fields elsewhere, and do not restate those values in prose, transition logs, handoff notes, or the resume prompt.

## Serial State And Parent Mapping

At every valid snapshot, closed children form a prefix, at most one child is `Ready` or `In Progress`, and all later children remain `Draft`. Map each parent child stage exactly:

| Child state | Child current milestone | Parent child-stage status |
|---|---|---|
| `Draft` | `n/a` | `Not Started` |
| `Ready` | `<M-id> Ready` | `In Progress` |
| `In Progress` | `<M-id> In Progress` | `In Progress` |
| `In Progress` | `<M-id> Blocked` | `Blocked` |
| `Closed` | `Close Done` | `Done` |

The only exception is promotion drift: the owning parent child stage may be `Blocked` while that child remains `Draft / n/a`. There must be exactly one H2/H3 `M<N> - Child <Child ID>` owning section with non-placeholder `Runtime hard-stop evidence:` naming the owning child, timestamp, semantic drift or failed handoff, attempted diagnostics, and required decision revalidation or external decision. No later child may be promoted.

The initial all-Draft snapshot has a Draft parent, every parent milestone `Not Started`, and every child `Draft / n/a`. After all preflights and checks pass, set only the parent and M0 to `Ready` for the one sequence authorization. When M0 starts, set the parent overall state to `In Progress` and keep it there until `Closed`; after M0 is `Done`, promote the first child and set M1 to `In Progress`.

`M0` is the only parent milestone that may be `Ready`. A promoted `Ready` child maps to an `In Progress` parent child stage, so the parent never returns to `Ready` for a per-child authorization. After all children are `Closed`, `M(n+1) Integration Acceptance` may become current. It and `Close` must remain `Not Started` before that point; `Close` cannot start until integration is `Done`.

## Authorization, Handoff, And Hard Stops

The user authorizes execution once at the parent after the sequence and all children pass preflight and consistency checks. That authorization permits automatic handoff only inside each frozen child contract. It does not add or widen release, deploy, destructive, privacy-sensitive, externally visible, connector, API, issue, PR, CI, automation, messaging, task-temporary-cache housekeeping, or other external-write permission.

With `Promotion policy: automatic-after-close`, promote the next child without asking again only after all of these pass:

1. The predecessor is `Closed`, its Close row and close gate passed, and its closeout link and revision are recorded.
2. The parent mapped stage has passing review and checkpoint evidence.
3. The next child remains boundary-complete, its required preflight is valid, and no semantic drift invalidated it.
4. The handoff/integration assumptions and required source-of-truth outputs are present.
5. `check_goal_sequence.py` passes for the promoted snapshot.

Record each promotion in the template's canonical timestamped `Transition Evidence` table with exact header `Timestamp | Child ID | From | To | Predecessor close revision | Handoff gate evidence`. Start concrete positive evidence cells with `Passed:`. This log is historical evidence only and must not claim which child or milestone is current.

Apply the adaptive recovery procedure in `execute-and-close.md` within the current child; the first two recoverable native Goal failures do not block the mapped parent stage. When an executing child reaches an authorization boundary or the native Goal technical-failure stop, keep that child's overall state `In Progress`, mark its current atomic milestone and mapped parent stage `Blocked`, and record section-local `Runtime hard-stop evidence:` in both contracts. Each evidence field must include a date, owning child ID, and breakpoint or attempted diagnostics. For promotion drift, also name semantic drift or failed handoff plus the required decision revalidation/external decision, then use the `Draft / n/a` exception above. Never skip, reorder, or partially start another child to route around a stop.

If parent-only M0, Integration Acceptance, or Close is `Blocked`, its owning section must instead record a date, the `sequence`, `integration`, or `close` stage owner respectively, and the breakpoint or attempted diagnostics.

## Resume, Validation, And Close

The reusable resume prompt must direct the next agent to re-read the parent and `Child Execution Register`, run the combination checker, then follow the registered state. It must not copy a child ID or current milestone that can drift.

Validate with the current Python interpreter:

```bash
python <skill-folder>/scripts/check_goal_sequence.py <sequence-file>
python <skill-folder>/scripts/check_goal_sequence.py <sequence-file> --allow-draft
```

The second form permits the parent to remain lifecycle `Draft`; registered future children may remain `Draft` in either mode. Neither mode permits a missing or inconsistent preflight. The checker composes `check_goal_ready.py` for the parent and every linked live or archived child goal, then validates markers, register identity, strict order, dependencies, current-child cardinality, child/parent state mapping, handoff evidence, promotion policy, closeout revisions, and integration/Close ordering. Fix legacy narrative plans by migrating them to the canonical template; do not add a fallback parser.

Close the sequence only after every child is `Closed`, integration acceptance is `Done`, each non-legacy child has honored its own housekeeping policy, each untouched legacy child has recorded its cleanup-unauthorized no-cleanup disposition, the parent has handled only its recorded parent-owned orchestration/integration roots, parent close evidence is complete, durable current docs are synchronized, and active navigation is clean.

Completion criterion: the parent and every child have complete consistent preflight tuples and frozen boundaries; both canonical registers agree; strict serial state, milestone mapping, handoff, closeout, authorization, and hard-stop evidence pass `check_goal_sequence.py`; all children are `Closed` before integration and parent `Close`; and only the parent is represented by an active harness system goal.
