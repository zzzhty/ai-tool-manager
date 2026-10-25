# Execute, Checkpoint, And Evolve

Use this reference after `../SKILL.md` routes an execute, resume, continue, advance, or evolve branch here. Load `close.md` only when entering Close. The inline supersession, pre-approval/YOLO, runtime-hard-stop, and goal-tool boundaries remain authoritative.

## Execute, Checkpoint, And Evolve

Follow the goal file rather than improvising. After context transition, interruption, or compaction, re-read the newest user request and active goal document before resuming.

Before implementation or resumed work, verify the marker and sourced preflight evidence under `../components/planning-preflight.md`, then run the applicable readiness checker without `--allow-draft`. For Sequence promotion, follow its child-readiness procedure. If evidence is missing, recover it from inspectable sources or complete the affected preflight before implementation. Reuse valid evidence; never manufacture an old interview or approval. Refresh an optional estimate only when changed evidence matters to a decision; missing timing and overruns are not runtime hard stops.

At milestone entry and after context transitions, resolve the action's target, scope and conditions against the recorded authorization sources and the newest request, including withdrawals. Use existing coverage directly; do not ask again because the milestone changed, a checkpoint passed or a condition was satisfied. A tool's access or sandbox permission is not task authorization, and recorded task approval does not override a tool's own execution restrictions.

For an `Enabled` or `Disabled` policy, apply this rule: Before any command may write task-temporary data, resolve the platform/runtime temporary root once, create the recorded goal/sequence-owned child namespace beneath it, replace a deferred roots field with the fully resolved absolute owner path, and bind every task-temporary producer in this goal to that recorded namespace. Reuse the recorded value for the rest of execution and at Close; if no producer ever creates a root, record the runtime outcome `None created` instead. A sequence parent binds only its orchestration/integration producers and never routes child temporary data through the parent root. A `Not applicable` policy creates no root.

At each milestone entry, apply `../components/milestone-scope-gate.md` to derive the current boundary. Reapply it only before material scope or validation expansion and after checkpoint evidence is recorded to confirm the exit condition; do not run it for every ordinary command or edit.

For each milestone:

1. Check any `Deferred approval gates` for this milestone before its work begins. Reconcile the row with sourced actual authorization first; when still covered, record Approved evidence and continue without another question. Otherwise ask only for the reserved final approval or uncovered increment, stop at the gate and record section-local runtime hard-stop evidence. Mark the milestone `In Progress` only after its approval gates pass. Do not remove a user-retained final gate on the strength of generic pre-approval.
2. Apply `../components/milestone-scope-gate.md`, then implement only its recorded scope and necessary consequences.
3. For an observed weakness in the contract, apply [Contract Evolution](#contract-evolution) before continuing affected mutation.
4. Satisfy the milestone validation commands and complete its review gate. Reuse still-valid passing results under the global verification policy; a checkpoint or skill transition alone does not require rerunning them. Explicit lifecycle fresh-run requirements, including the readiness check above, remain binding.
5. Record scope and necessary-consequence completion, changed files, behavior impact, command results, doc sync, rollback path, and remaining risk.
6. If the milestone exercises a Loop Blueprint, also record trigger/input path, orchestration or worktree isolation evidence, connector read/write evidence, independent verification, YOLO actions, and runtime-hard-stop decisions.
7. Apply `../components/checkpoint.md`.
8. Confirm the milestone-scope exit gate.
9. Mark milestone `Done`, review `Passed`, and checkpoint `Done` only after evidence is recorded.

When both the review gate and milestone-scope exit gate pass, advance to the next milestone and check its approval gates. When a review or scope gate fails, keep fixing and diagnosing in scope while the next useful step is clear; stop only at the runtime-hard-stop boundary.

Completion criterion: the current milestone has passing scope and review gates plus recorded behavior, docs, rollback, risk, Loop evidence when applicable, validation, review status, and checkpoint evidence before it is marked `Done` or execution advances.

## Adaptive Recovery

For the same unresolved required outcome, use failure evidence to choose a different causal approach before another attempt. A command error, diagnostic probe, failed test assertion, or reviewer comment is not automatically one native Goal failure. Follow the native runtime's reported failure/stop state; if its count is unavailable, record the observed recovery history without claiming to know or control its counter.

- After the first runtime-reported native Goal failure: identify the failed assumption or method, inspect the relevant evidence, and choose an authorized alternative that addresses that cause (for example, repair the dependency, change the algorithm, or use an equivalent supported interface).
- After the second runtime-reported native Goal failure: use both results to reject disproven assumptions and choose a materially different direction or re-plan the implementation within the same outcome and acceptance criteria. Do not simply repeat either failed approach.
- At the third runtime-reported native Goal failure/stop: honor the native Codex Goal hard stop. Preserve available evidence and report the failed approaches, remaining dependency or decision, and what would be needed for a user-authorized resume. Once that native boundary occurs, do not launch another recovery attempt, reset the count, or switch to a new goal to continue the same blocked work. Three ordinary failed commands alone do not establish this boundary.

Keep the first two recoverable native Goal failures `In Progress`; a failed review/gate still prevents dependent integration or milestone advancement. A changed flag, command wording, agent, or backend is not a new direction unless it changes the failed assumption or relevant conditions. Retrying the same operation is useful only with evidence that its cause has changed, such as restored connectivity; record that evidence instead of asserting that repetition is a new approach.

Use existing milestone evidence, not a new ledger or mandatory schema: observed failure/runtime state, approach and result, causal diagnosis, next strategy and why it differs, and validation needed. Read it on resume. Progress, context compaction, a new milestone, and strategy changes do not authorize manually resetting the native counter. If the runtime stops earlier or is unavailable, respect its actual boundary and report the limitation; these instructions cannot grant extra retries.

Before every recovery action, apply existing authorization and scope rules. A new direction may change implementation means, not the user's goal, frozen semantics, required verifier, safety boundary or definition of success. Missing permission or a required semantic decision stops the affected action immediately, even before any native Goal failure. Obtain that decision rather than treating an alternate tool or identity as a workaround. When all authorized alternatives are exhausted before the threshold, report and wait for the needed input or environment recovery without pointless attempts; do not pretend the third native failure occurred. Continue independent authorized work only while the runtime permits it. Sequence recovery stays in the current child; do not skip a child or start a nested native goal.

## Contract Evolution

When execution exposes a weak gate, validation rule, rollback path, milestone boundary, Loop field, or skill strategy, state the gap and evidence, update the active goal within its existing authority, validate the affected contract, and resume the original milestone. Pause affected mutation for that update; do not ask for permission unless a runtime hard stop applies. Change a reusable skill or template only when source mutation is authorized; otherwise record a bounded improvement suggestion without blocking independent authorized work. If the evolved rule invalidates completed work, reopen affected milestone evidence or mark the gate failed and fix the issue. Do not silently weaken acceptance criteria after implementation, bypass gates with fallback/alternate backends/fake success/hidden partial success/silent degradation, or repackage deprecated surfaces as current semantics unless the goal explicitly requires it and docs are updated.

## Current Docs And Close

Use [close.md](close.md) when entering Close; it owns current-doc synchronization and close completion.
