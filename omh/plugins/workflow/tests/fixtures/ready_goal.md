# Demo Goal

Overall status: Ready

Planning preflight marker: preflight:demo:20260710-ready

Planning preflight status: Done

Preflight source: grill-with-docs

Preflight evidence: Completed: 2026-09-09 user turn 1 confirmed design, documentation ownership, and action permissions through Close.

Resolved decisions: The demo owns bounded local code and documentation edits, validation, and rollback through Close.

Open decisions: None.

Docs written: Not applicable: the goal records all durable decisions for this fixture.

## M0 milestone

Baseline recorded.

## Milestone status table

| Milestone | Status | Review | Checkpoint |
|---|---|---|---|
| M0 | Ready | Pending | Pending |
| Close | Not Started | Pending | Pending |

## Review gate

Review gate accepted.

## Checkpoint evidence

Checkpoint component: `components/checkpoint.md`

## Planning preflight

Planning preflight component: `components/planning-preflight.md`

## Preflight Time Assessment

Assessment target: Ready-to-Closed

Assessment mode: Rough range

Rough elapsed-time estimate: 2-4 hours

Basis or blocker: 2026-07-20 range assumes serial execution of the bounded local milestone, targeted validation, warm dependency state, and no external waits.

Critical-path time-cost distribution: Not required: rough range recorded.

## Task Temporary Cache / Housekeeping

Close housekeeping policy: Enabled

Housekeeping decision source: Explicit user confirmation recorded for this demo.

Task temporary cache root strategy: Resolve the host platform/runtime standard temporary root, allocate a goal-owned namespace beneath the resolved root, and record the exact owner root before first use.

Recorded task temporary cache roots: Resolve and record before first use.

Housekeeping boundary: Use `watcher:housekeeping` only for inventoried goal-owned disposable cache candidates, preserve unknown or unsafe content, and keep durable evidence outside the cache root.

## Loop Blueprint / Harness

Execution mode: Manual staged execution

Not applicable: manual staged execution because this demo has no recurring trigger,
connector, subagent orchestration, worktree parallelism, or external side effect.

## Rollback path

Rollback restores the prior revision.

## Close and archive procedure

Close after validation and archive the plan.

## Validation evidence

Tests passed.

## Failure handling

Report the failed command and breakpoint.

## Continuation contract

Continue from the first incomplete milestone.

## Pre-Approval / YOLO

Authorization evidence: 2026-09-09 user turn 1 authorized the demo bounded local edits, tests, validation, and continuation through Close within the recorded owner scope; housekeeping remains governed by its independent policy and decision source.

Pre-approved YOLO local operations:

- Planned non-destructive local code and documentation edits, tests, and validation.

Pre-approved external reads/writes:

- Not applicable: this demo does not access external systems.

Runtime hard stops:

- Stop only when repeated local diagnostics cannot make progress, required inputs are
  unavailable, or the next action is unapproved and destructive or externally visible.

Non-stops:

- Continue through milestone boundaries, checkpoints, rebuilds, and recoverable validation.

## Runtime Hard Stops

Stop on permissions or destructive scope changes.

## Non-Stops

Continue through ordinary local validation.

## Reusable Prompt

Resume this demo goal.

## Documented placeholder example

```text placeholder-example
Template syntax uses <goal-path> here.
```
