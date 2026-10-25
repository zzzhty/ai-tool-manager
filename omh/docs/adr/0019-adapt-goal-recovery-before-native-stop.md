# ADR 0019: Adapt goal recovery before the native stop

Status: Accepted for implementation on 2026-10-08.

## Decision and scope

The user identifies the three-failure stop as Codex Goal's native rule and requests
using the first two failures to change strategy, then associating the third with
that native hard stop. The previous skill's “at least three attempts or distinct
approaches” wording permitted unchanged retries and implied an extensible local
threshold. Replace that instruction with evidence-led adaptive recovery; do not
implement, infer, reset or override the native runtime's counter.

The skill and execution reference own the procedure. Atomic/sequence templates,
the sequence reference, plugin README and disclosure tests are current consumers
and change together. Existing milestone states and evidence fields remain intact;
no new persisted schema, retry ledger, hook or native goal is introduced. Existing
goal artifacts and historical ADRs are preserved. Source changes require the
existing content-derived package identity regeneration, not a new integrity gate.

## Behavioral oracle

- First runtime-reported native Goal failure: diagnose the failed assumption and choose an authorized approach
  addressing it. Second native failure: use both results to choose a materially different
  direction within the same outcome and acceptance criteria.
- An unchanged command, new agent or renamed backend is not a new approach. A
  same-operation retry needs evidence of changed causal conditions.
- First/second recoverable native Goal failures remain In Progress. Required failed gates still
  block dependent work; Sequence cannot skip the current child.
- The third native failure stops recovery. Earlier native stop signals also bind.
  Never continue recovery after that native boundary or recreate a goal to obtain a fresh budget. Three ordinary failed commands alone do not establish the boundary.
- A tool error is not automatically a native failure. With no exposed counter,
  record observed history and disclose the uncertainty, without fabricating state.
- Missing authorization or a decision that changes frozen semantics stops the
  affected action immediately. An alternate tool cannot bypass denied access.
- If no authorized alternative exists before the threshold, explain the dependency
  and wait rather than manufacture failures. Independent authorized work may
  continue only while the runtime permits it.
- Resume reads existing milestone recovery evidence; a context transition cannot
  justify restarting disproven approaches or manually resetting the native count.

## Validation and limits

Disclosure tests protect instruction ownership and the above boundary cues;
existing Workflow tests cover readiness, milestone and sequence constraints. These
are not execution tests of Codex's private runtime counter and do not prove model
adherence. Review the candidate against the oracle and report actual test results
in the change/PR. No live native goal or managed installation is exercised.

## Recovery

Revert the source and its generated Workflow identity together. Existing goal
artifacts require no schema migration and retain their recorded permission gates.
