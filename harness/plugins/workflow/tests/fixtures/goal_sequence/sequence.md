# Demo Long-Running Goal Sequence

Overall status: Ready

Planning preflight marker: preflight:demo-sequence:20260713-parent

Planning preflight status: Done

Preflight source: grill-with-docs

Preflight evidence: Completed: 2026-09-09 user turn 1 confirmed design, documentation ownership, and action permissions through Close.

Resolved decisions: Both child scopes, owners, compatibility, order, rollback, permissions, release/deploy, privacy, and non-goal boundaries are frozen for this fixture.

Promotion policy: automatic-after-close

Open decisions: None.

Docs written: Not applicable: this goal records its owner-specific durable decisions.

## Preflight Time Assessment

Assessment target: Ready-to-Closed

Assessment mode: Distribution only

Rough elapsed-time estimate: Not quickly estimable

Basis or blocker: 2026-07-20 no representative child-b validation or integration elapsed-time evidence exists for a defensible serial range, and external CI wait is unknown.

Critical-path time-cost distribution:
- child-a assessment — Material — The bounded local implementation has a child-owned rough range.
- child-b validation — Unknown — The validation path lacks representative elapsed-time evidence.
- parent integration and Close — Minor — The parent owns only final composed checks and archive work.

## Child Preflight Register

| Child ID | Marker | Status | Source |
|---|---|---|---|
| child-a | preflight:demo-child-a:20260713-a | Done | grill-with-docs |
| child-b | preflight:demo-child-b:20260713-b | Done | grill-with-docs |

## Child Execution Register

| Order | Child ID | Parent milestone | Live goal | Closeout evidence | Depends on | State | Current milestone | Close revision |
|---|---|---|---|---|---|---|---|---|
| 1 | child-a | M1 | [child-a](children/child-a.md) | n/a | n/a | Draft | n/a | n/a |
| 2 | child-b | M2 | [child-b](children/child-b.md) | n/a | child-a | Draft | n/a | n/a |

## M0 - Sequence Baseline And First Promotion

The sequence baseline is frozen and ready for the one parent execution authorization.

## M1 - Child child-a

Execute child-a only through its linked atomic goal contract.

## M2 - Child child-b

Execute child-b only after child-a is Closed and its handoff gate passes.

## M3 - Integration Acceptance

Validate the combined outcome only after every child is Closed.

## Milestone status table

| Milestone | Status | Review | Checkpoint |
|---|---|---|---|
| M0 | Ready | Pending | Pending |
| M1 | Not Started | Pending | Pending |
| M2 | Not Started | Pending | Pending |
| M3 | Not Started | Pending | Pending |
| Close | Not Started | Pending | Pending |

## Boundary contract

Scope, owners, compatibility, dependency order, validation, rollback, and permission boundaries are frozen in the parent and both child goals. The parent authorization cannot widen a child boundary.

## Review gate

Review the canonical registers, frozen child boundaries, and handoff evidence before each transition.

## Checkpoint evidence

Checkpoint component: `components/checkpoint.md`

## Planning preflight

Planning preflight component: `components/planning-preflight.md`; parent and child preflights are mandatory and cannot be skipped.

## Loop Blueprint / Harness

Execution mode: Loop-shaped execution

Trigger:
- Start once on explicit parent authorization, then resume on predecessor Close or an explicit continuation request.
Inputs:
- Read the parent, both registers, linked child goals, closeouts, and validation evidence.
Triage and orchestration:
- Select and advance exactly one registered child in strict order.
Worktree and isolation:
- Serialize all fixture edits in one isolated temporary workspace.
Skills and context:
- Read workflow:long-running-goal and the Sequence Child Goals reference.
Connector read/write boundaries:
- Not applicable: this fixture has no connector or external write.
Independent verification:
- Run the atomic and sequence checkers without trusting transition prose.
Runtime hard stops:
- Stop at the owning child when frozen semantics drift or required evidence is unavailable.
Durable learning:
- Persist current state only in the Execution Register and history in Transition Evidence.

## Rollback path

Rollback restores the prior parent register revision and follows the owning child rollback contract.

## Close and archive procedure

Close after both children and integration are complete, then archive or remove active planning pointers according to local convention.

## Validation evidence

Run both atomic goal checks, the sequence checker, link checks, and project validations.

## Failure handling

Keep a hard stop at its owning child and record the exact breakpoint without promoting a successor.

## Continuation contract

Treat the Child Execution Register as the sole current-state authority and follow the first legal transition.

## Pre-Approval / YOLO

Authorization evidence: 2026-09-09 user turn 1 authorized the sequence parent bounded local edits, tests, validation, and continuation through Close within the recorded owner scope; housekeeping remains governed by its independent policy and decision source.

Pre-approved YOLO local operations:

- Planned non-destructive local code and documentation edits, tests, validation, and register synchronization inside each frozen child boundary.

Pre-approved external reads/writes:

- Not applicable: this fixture does not access external systems.

Runtime hard stops:

- Stop only when repeated local diagnostics cannot make progress, required inputs are unavailable,
  frozen semantics drift, or the next action is unapproved and destructive or externally visible.

Non-stops:

- Continue through automatic handoff, milestone boundaries, checkpoints, rebuilds, and recoverable validation.

## Runtime Hard Stops

Stop at the owning child on unavailable authority, semantic drift, or destructive scope expansion.

## Non-Stops

Continue through ordinary local validation and eligible automatic promotion.

## Transition Evidence

Timestamped transitions record historical from/to states and revisions without restating a current child or milestone.

| Timestamp | Child ID | From | To | Predecessor close revision | Handoff gate evidence |
|---|---|---|---|---|---|

## Reusable Prompt

Re-read this sequence, inspect the Child Execution Register, run the combination checker, and continue from the registered state without copying it into this prompt.
