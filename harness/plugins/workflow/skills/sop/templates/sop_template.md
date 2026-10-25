# SOP: <Name>

Status: Draft

## Trigger

<When this stable procedure applies.>

## Inputs

<Required inputs, source of truth, and working location when relevant.>

## Execution Harness

<Manual, agent-executed, or automated. Add only applicable orchestration, isolation, external permissions, independent verification, escalation, and durable writeback details.>

## Allowed Actions

<Read and write scope covered by the current authorization. State any material exclusions here.>

## Steps

### Step 1 - <Name>

Action: <Concrete command or action.>

Expected Output: <Observable result.>

## Validation

<Checks that establish the procedure succeeded. Add step-specific completion criteria only where these checks are insufficient.>

## Output Contract

<Results, evidence, changed paths, and artifact location to report.>

## Stop Conditions

<Explicit termination, missing-input, safety and permission stops take priority. Recovery is optional; if used, declare shared or step-local diagnosis, repair or bounded retries within current authorization. Pause dependent steps, preserve failure and diagnostic evidence, and keep report-only work non-mutating. Keep acceptance criteria unchanged: reuse still-valid passing evidence under the original owner/verifier's bindings; reassess coverage after relevant changes or later failures, which earlier passes cannot override. Revalidate failed checks and affected coverage, establish necessary state prerequisites, then continue unfinished steps once dependencies close; independent authorized work may continue. Preserve the original owner's applicable requirements for fresh/full execution, new-attempt state and operations, final readback, cleanup and complete transaction/rollback; do not splice old mutable state into qualification. A session, namespace or phase change alone neither invalidates evidence nor resets retry budgets. Do not blindly retry the same failure without a repair, relevant input change or new diagnosis. Stop and report when recovery is unavailable, exhausted or needs more authorization.>
