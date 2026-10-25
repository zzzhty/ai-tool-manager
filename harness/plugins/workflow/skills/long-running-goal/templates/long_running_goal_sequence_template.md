# Long-Running Goal Sequence Template

Copy this template for a strict serial `Long-Running Goal Sequence`. `umbrella` is only an informal alias. Replace every `<...>` placeholder before authorization; never record project progress in this source template.

This two-child shape is the minimum. To add children, add matching rows to both registers, insert one `M<Order> - Child <Child ID>` section per child, renumber Integration Acceptance to `M(n+1)`, and update the milestone table.

Overall status: `Draft`

Artifact type: `Long-Running Goal Sequence`

Sequence alias: `umbrella`

Promotion policy: `automatic-after-close`

Goal name: `<Sequence Goal Name>`

Goal owner: `<owner / team / agent>`

Goal path: `<goal-dir>/<sequence_slug>_long_running_goal_sequence.md`

Planning root: `<planning-root>`

Goal directory: `<goal-dir>`

Continuation contract: `<Another agent can re-read this parent, validate both registers, and continue the registered strict-serial state without chat history.>`

Planning preflight marker: `preflight:<sequence_slug>:<yyyymmdd>-<short-id>`

Planning preflight status: `<Done / Skipped by explicit user instruction>`

Preflight source: `<grilling + domain-modeling / grill-with-docs / existing decisions / user skip>`

Preflight evidence: `<Completed: source and checked outcome / Reused: completed preflight id, source and current coverage / User skip: explicit user instruction source; use a Markdown link or a dated user request/message/turn reference>`

Resolved decisions: `<summary or ADR / context paths covering every child boundary and the sequence order>`

Open decisions: `<none or bounded runtime hard stops only>`

Docs written: `<CONTEXT.md / ADR paths / Not applicable with reason>`

## Preflight Time Assessment

Optional: record a useful remaining range and basis, or the concrete reason it is unknown. Distinguish known child costs, unknown costs, and parent overhead. Remove this section when unnecessary; it does not affect readiness.

## Task Temporary Cache / Housekeeping

Close housekeeping policy: `Disabled`

Only for Enabled, add Housekeeping decision source with explicit user confirmation and context.

Task temporary cache root strategy: `<Enabled/Disabled: resolve the host platform/runtime standard temporary root, allocate a sequence-owned namespace beneath it, and record the exact owner root before first use; Not applicable: no parent task temporary cache root will be created.>`

Recorded task temporary cache roots: `<one fully resolved owner-labeled absolute path entry per parent orchestration/integration root / Resolve and record before first use / None created / Not applicable>`

Housekeeping boundary: `<Enabled uses watcher:housekeeping only for inventoried sequence-owned orchestration/integration disposable candidates; Disabled preserves and reports parent roots; Not applicable creates no parent root; every child records and honors its own policy; durable evidence lives outside the roots.>`

## Template Use

1. Create each child from `long_running_goal_template.md`, complete its required preflight methods and authorization coverage through Close, and freeze its scope, owner, compatibility, validation, rollback, permission, release/deploy, privacy, housekeeping, and non-goal boundaries. Reuse confirmed answers and preserve sourced completion/reuse/explicit-skip evidence in each child; the register cannot replace it.
2. Use relative Markdown links, replacing the backticked examples with actual links. Follow the Sequence Execution Contract below for lifecycle and handoff.
3. Run `check_goal_sequence.py --allow-draft` while drafting and without that flag before authorization or execution. Draft mode never relaxes frozen child preflight boundaries.
4. Create only one active harness system goal for this parent, never nested system goals for children. Use `references/sequence-child-goals.md` for operational details and optional timing guidance.

## Child Preflight Register

| Child ID | Marker | Status | Source |
|---|---|---|---|
| `<child-a>` | `preflight:<child-a>:<yyyymmdd>-<short-id>` | `Done` | `existing decisions` |
| `<child-b>` | `preflight:<child-b>:<yyyymmdd>-<short-id>` | `Done` | `existing decisions` |

Every marker, status, and source must exactly match the linked child. Existing decisions and explicit user skips follow the atomic preflight rules; missing or inconsistent preflights are invalid.

## Child Execution Register

| Order | Child ID | Parent milestone | Live goal | Closeout evidence | Depends on | State | Current milestone | Close revision |
|---|---|---|---|---|---|---|---|---|
| 1 | `<child-a>` | `M1` | `[<child-a>](./<child-a>_long_running_goal_plan.md)` | `n/a` | `n/a` | `Draft` | `n/a` | `n/a` |
| 2 | `<child-b>` | `M2` | `[<child-b>](./<child-b>_long_running_goal_plan.md)` | `n/a` | `<child-a>` | `Draft` | `n/a` | `n/a` |

Allowed `State` values are `Draft`, `Ready`, `In Progress`, and `Closed`. A promoted child records one exact atomic current row such as `M0 Ready`, `M1 In Progress`, or `M1 Blocked`. A Closed child records `Close Done`, `Live goal = n/a`, its complete archived atomic goal under `Closeout evidence` (never just a summary), and a close revision.

## Baseline And Frozen Boundaries

Current baseline:

1. `<Current code, docs, runtime, and already-delivered capability.>`
2. `<Current compatibility or legacy surface.>`
3. `<Known failure breakpoints and rollback/disable paths.>`

Current sources of truth read:

1. `<Root instructions, README, current indexes, and active planning docs.>`
2. `<Architecture, contract, validation, runtime, release, or permission docs.>`
3. `<Every child goal and relevant prior closeout.>`

Frozen sequence boundaries:

1. `<Child-a scope, owner, compatibility, dependency, permissions, and non-goals.>`
2. `<Child-b scope, owner, compatibility, dependency, permissions, and non-goals.>`

## Loop Blueprint / Harness

Execution mode: `Loop-shaped execution`

1. Trigger: `<One explicit parent execution authorization, then resume or predecessor Close events.>`
2. Inputs: `<This parent, both registers, linked child goals, source-of-truth docs, validation and checkpoint evidence.>`
3. Triage and orchestration: `<Strict serial selection from the Execution Register; at most one Ready or In Progress child.>`
4. Worktree and isolation: `<Shared-checkout serialization or explicit child-scoped isolation and collision rules.>`
5. Skills and context: `<workflow:long-running-goal, sequence-child-goals.md, child-required skills, runbooks, and specs.>`
6. Connector read/write boundaries: `<Exact child-by-child pre-approved external reads/writes and specified later actions in each owner's Deferred approval gates; undefined boundaries keep the sequence Draft.>`
7. Independent verification: `<check_goal_sequence.py plus project-specific tests or reviewer gates.>`
8. Runtime hard stops: `<Uncovered authorization/semantic-decision boundary: stop the affected action immediately. Technical failure: adapt after the first and second runtime-reported native Goal failures; honor the third native Codex Goal hard stop. Use the skill's adaptive recovery procedure; do not override runtime counting or retry denied access.>`
9. Durable learning: `<Parent/child evidence, current docs, validation logs, closeouts, and any reusable strategy update.>`

## Pre-Approval / YOLO

Authorization evidence: `<Source references mapping actual actions, targets, scopes, conditions and milestones to existing approvals; use Markdown links or dated user request/message/turn references. Reference each child's authority and separate housekeeping policy/source; the parent adds no child permission.>`

1. Pre-approved YOLO local operations: `<Only planned non-destructive local code/docs edits, tests, lint, formatting, rebuilds, refreshes, reinstalls, link checks, plugin/cache refreshes, and project-owned generated-artifact cleanup inside each child boundary; task temporary cache housekeeping remains separately governed.>`
2. Pre-approved external reads/writes: `<Exact union of already-approved child-specific surfaces, or Not applicable; the parent grants no additional permission.>`
3. Runtime hard stops: `<Uncovered authorization/semantic-decision boundary: stop the affected action immediately. Technical failure: adapt after the first and second runtime-reported native Goal failures; honor the third native Codex Goal hard stop. Use the skill's adaptive recovery procedure; do not override runtime counting or retry denied access.>`
4. Non-stops: `<M0, child handoff after passed gates, review/checkpoint boundaries, timing rebaseline after a range overrun, evidence recording, rebuild/refresh/reinstall, docs sync, and locally repairable validation failures.>`

## Deferred approval gates

Omit this section when no parent-owned actions await approval. Put child action gates in the owning child goal, using `components/planning-preflight.md`; the parent grants no additional permission. Record a sourced user-retained decision or required final review, not routine later-stage deferral. Preparation precedes the gated milestone. Pending blocks its work, In Progress/Done and Close; reconcile existing authority before asking, and record Approved when its source still covers the action. Preserve actual final-review gates.

| Milestone | Action | Status | Approval evidence | Deferral basis |
| --- | --- | --- | --- | --- |
| <Existing parent milestone> | <Concrete action, target, scope and conditions> | Pending | None | <User decision: source and reserved decision / Required review: rule source and required review material> |

## Sequence Execution Contract

1. Parent and child preflight tuples must be complete, consistent, and match the register. `--allow-draft` relaxes lifecycle only. V1 is strict serial: no parallel, DAG, per-child authorization, or alternate promotion mode.
2. The Execution Register is the sole child current-state authority; do not copy `Current child:`, `Active child:`, or `Current child milestone:` fields into other sections or the resume prompt. Closed children form a prefix, at most one child is `Ready` or `In Progress`, and every later child remains `Draft / n/a` with atomic rows `Not Started / Pending / Pending`. Transition evidence is historical.
3. Parent mapping is fixed: Draft child -> `Not Started`; Ready -> `In Progress`; In Progress -> `In Progress`; In Progress with a Blocked atomic milestone -> `Blocked`; Closed -> `Done`.
4. Promotion-drift exception: a parent child stage may be `Blocked` while its child remains `Draft / n/a`, but that exact section must record real section-local runtime hard-stop evidence and no later child may start.
5. In the all-Draft snapshot all parent milestones are Not Started. After every preflight and check passes, set only parent Overall status and M0 to Ready for the one authorization. When M0 starts, set parent Overall status to In Progress and keep it there until Closed; M0 Done promotes the first child, and promoted Ready children map to In Progress parent stages. Each `M<Order>` owns one child. Integration remains Not Started until all children are Closed; Close remains Not Started until integration is Done.
6. After a predecessor Close, verify its archived atomic closeout and revision, parent review/checkpoint and milestone-scope exit gate, next-child preflight/boundaries, handoff inputs, and sequence checker; then promote automatically within frozen child authority, without another authorization. Parent approval never expands release, deploy, destructive, privacy-sensitive, external-write, externally visible, or child housekeeping permission.
7. A child hard stop remains at the owning child. Keep its overall state `In Progress`, mark its atomic current milestone and mapped parent stage `Blocked`, and put `Runtime hard-stop evidence:` in both owning sections with a date, child ID, and breakpoint or attempted diagnostics. Promotion drift additionally names semantic drift/failed handoff and the required decision revalidation/external decision. Parent-only M0, Integration, or Close evidence uses the same date and diagnostics rule plus the stage owner token `sequence`, `integration`, or `close`. Do not skip or reorder children.
8. Apply `components/checkpoint.md` before every parent milestone or Close becomes Done. Record commands, behavior, docs, rollback, risks, harness evidence, revision, and out-of-scope dirt; after a parent milestone records checkpoint evidence, confirm `components/milestone-scope-gate.md` before marking it Done or promoting the next child.
9. Do not widen gates, hide failure, use fallback or alternate backends, report partial work as success, or convert a permission boundary into a non-stop.
10. Only an explicit `Enabled` policy may invoke `watcher:housekeeping`, and only for inventoried disposable candidates beneath the exact recorded owner root. Do not re-resolve the host temp root at Close or perform unconditional whole-directory deletion. If watcher is unavailable, keep parent Close/overall `In Progress` (`Blocked` only at a runtime hard stop), use no recursive-delete fallback, and change to `Disabled` only through explicit user preflight-policy evolution. Parent and child policies remain independent; parent policy covers only its orchestration/integration roots. Never add housekeeping columns to the child registers.
11. Close only after every child is Closed, integration is Done, every parent/child housekeeping disposition is recorded, close evidence passes, current docs are synchronized, and active navigation is clean.

12. Semantic changes to scope, owner, compatibility, dependency order, behavior, or external authorization invalidate affected markers and require decision revalidation; path, command, tool-version, or non-semantic baseline updates only rebaseline evidence.

## Transition Evidence

This append-only table records timestamped historical transitions only. Never label a row as the current child or current milestone.

| Timestamp | Child ID | From | To | Predecessor close revision | Handoff gate evidence |
|---|---|---|---|---|---|

Add one row per promoted non-Draft child in child order, use an RFC3339 timestamp, match the predecessor Close revision, and start concrete positive handoff evidence with `Passed:`. Draft children have no transition row in strict v1.

## Milestones

### M0 - Sequence Baseline And First Promotion

Scope: `<Verify parent/child preflights and boundaries, freeze canonical registers and authorization, then promote child order 1.>`

Review gate:

1. Both registers have matching unique IDs and contiguous order.
2. Parent and every child pass the shared atomic preflight checks.
3. Sequence permissions do not exceed any child boundary, and `check_goal_sequence.py` passes.

Validation evidence: `<commands and actual results>`

Rollback evidence: `<Return first child to Draft only before implementation mutation; otherwise use its frozen rollback contract.>`

Runtime hard-stop evidence: `n/a while this stage is not Blocked`

Checkpoint evidence: `<components/checkpoint.md result, revision, changed files, validation, and excluded dirt>`

### M1 - Child <child-a>

Scope: `<Execute only the registered live child-a contract through its Close gate.>`

Review gate:

1. Child state, atomic current milestone, and this parent stage remain mapped.
2. Child validation, rollback, review, checkpoint, docs, and Close evidence are complete.
3. Archived atomic closeout, close revision, handoff inputs, and sequence check pass before promotion.

Validation evidence: `<child commands, parent checker, and actual results>`

Rollback evidence: `<Use child-a frozen rollback/disable path without widening scope.>`

Runtime hard-stop evidence: `n/a while this stage is not Blocked`

Checkpoint evidence: `<components/checkpoint.md result, revision, changed files, validation, and excluded dirt>`

### M2 - Child <child-b>

Scope: `<After automatic promotion, execute only the registered live child-b contract through its Close gate.>`

Review gate:

1. Child-a remains Closed with valid closeout/revision and child-b is the only current child.
2. Child-b validation, rollback, review, checkpoint, docs, and Close evidence are complete.
3. Archived atomic closeout, close revision, integration inputs, and sequence check pass.

Validation evidence: `<child commands, parent checker, and actual results>`

Rollback evidence: `<Use child-b frozen rollback/disable path without widening scope.>`

Runtime hard-stop evidence: `n/a while this stage is not Blocked`

Checkpoint evidence: `<components/checkpoint.md result, revision, changed files, validation, and excluded dirt>`

### M3 - Integration Acceptance

Scope: `<Validate the composed outcome only after every child is Closed; do not reopen or widen child scope.>`

Review gate:

1. Every child has a valid archived atomic closeout and close revision.
2. Cross-child behavior, compatibility, rollback, docs, and project-specific integration tests pass.
3. The sequence checker passes with Integration Acceptance as the only current parent milestone.

Validation evidence: `<integration commands and actual results>`

Rollback evidence: `<Composed rollback order using only frozen child rollback contracts.>`

Runtime hard-stop evidence: `n/a while this stage is not Blocked`

Checkpoint evidence: `<components/checkpoint.md result, revision, changed files, validation, and excluded dirt>`

## Milestone Status Table

| Milestone | Status | Review | Checkpoint |
|---|---|---|---|
| M0 Sequence Baseline And First Promotion | Not Started | Pending | Pending |
| M1 Child `<child-a>` | Not Started | Pending | Pending |
| M2 Child `<child-b>` | Not Started | Pending | Pending |
| M3 Integration Acceptance | Not Started | Pending | Pending |
| Close | Not Started | Pending | Pending |

## Close Gate

Close remains `Not Started` until M3 is Done. Pass any deferred approval gate for Close before its work begins. Then set Close and Overall status to `In Progress`, validate, record evidence, and only then set Close to `Done / Passed / Done` and Overall status to `Closed`.

Close requirements:

1. Every child is Closed with a valid archived atomic goal and close revision.
2. M0 through Integration Acceptance are Done/Passed/Done.
3. Final sequence, project-specific, link, and `git diff --check` validations have actual passing results.
4. Current docs, status registers, validation logs, close/archive handling, and active navigation are synchronized.
5. Every non-legacy child has honored its own housekeeping policy, every untouched legacy child has recorded a cleanup-unauthorized no-cleanup disposition, and the parent has handled only its own scope: when no parent root exists, explicitly record that no task temporary cache roots were created; for concrete sequence-owned roots record exact paths and actions, with durable evidence outside those roots. Removed / preserved / failed / residual sizes are required only for Enabled; under Disabled omit them or record unknown with a diagnostic.
6. Final rollback, residual risk, harness conclusion, and checkpoint revision are recorded.

Close execution evidence: `<changed artifacts, final behavior, validation commands/results, docs sync, rollback, residual risk, archive outcome, and parent/child task temporary cache dispositions>`

Temporary cache / housekeeping evidence:

- Recorded policy: `<Enabled / Disabled / Not applicable>`
- Exact parent roots / Roots outcome: `<repeat each sequence-owned absolute path / None created>`
- Child dispositions: `<each non-legacy child policy or legacy no-cleanup disposition evidence link; never inherit or override it>`
- Action: `<Enabled watcher:housekeeping action / Disabled retained action / no-roots disposition>`
- Removed size: `<required only for Enabled concrete parent roots, for example 0 B; otherwise omit or record if useful>`
- Preserved size: `<required only for Enabled concrete parent roots, for example 0 B; otherwise omit or record if useful>`
- Failed size: `<required only for Enabled concrete parent roots, for example 0 B; otherwise omit or record if useful>`
- Residual size: `<required only for Enabled concrete parent roots, for example 0 B; otherwise omit or record if useful>`

Checkpoint evidence: `<components/checkpoint.md close result, revision, changed files, validation, and excluded dirt>`

## Reusable Resume Prompt

```text placeholder-example
Use workflow:long-running-goal to resume <sequence-goal-path> as a Long-Running Goal Sequence.

Re-read the parent and references/sequence-child-goals.md. Run check_goal_sequence.py before mutation, resume from Child Execution Register, and apply the Sequence Execution Contract, frozen boundaries, and owning milestone gates. Do not infer current state from transition history or this prompt.
```

## Related Documents

1. `<Current goal/TODO index>`
2. `<Architecture / contract / validation / runtime docs>`
3. `<Child-specific specs, ADRs, and runbooks>`
