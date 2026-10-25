---
name: prompt-strategy-loop
description: Improve prompts, skill guidance, reviewer rubrics, or agent strategy from observed evidence through a frozen oracle, bounded candidates, and proportional review.
---

# Prompt Strategy Loop

Use this skill to improve agent behavior from evidence rather than wording preference. The result may be a recommendation, proposal, or source edit when mutation is authorized.

## Core Rule

Freeze observable success and regression criteria before writing candidates. Compare the no-change baseline with the smallest viable change.

Independent evaluation is required when a candidate changes invocation or routing, permissions, safety or privacy, destructive or external actions, recurring automation, persisted or external contracts, or removes a stop or validation gate. Add a separate risk or counterexample pass for permission, safety/privacy, destructive-action, or external-write changes. When required review is unavailable, keep the candidate explicitly unverified.

## Workflow

1. Define the target behavior, evidence scope, non-goals, and write boundary.
2. Collect relevant failures, successful examples, logs, feedback, diffs, reports, benchmark tasks, or source artifacts. A single anecdote is sufficient only when the user intentionally scoped the review to it.
3. Freeze the oracle: observable improvement criteria and regressions the candidate must avoid.
4. Compare the no-change baseline with the smallest candidate. Add alternatives only for real design branches exposed by evidence.
5. Apply the Core Rule. Give evaluators the raw evidence, oracle, bounded task, and stop condition without a preferred answer.
6. Select the smallest candidate that satisfies the oracle. Record material disagreement, missing evidence, rejected alternatives, validation, and residual risk.
7. Write to the owning source only when authorized. Installed copies, generated caches, hooks, or activation state change only when that activation is in scope.

## Report-Only Mode

For an audit, recommendation, or implementation plan, perform the workflow through selection, publish the evidence-backed result, and stop before source or installed-state mutation. Create a durable report only when requested.

## Completion And Boundaries

State the evidence, frozen oracle, selected and materially rejected candidates, reviewer coverage, writeback boundary, affected-surface validation, blockers, and residual risk.

Stop at a proposal when evidence or an oracle is missing, required review conflicts or is unavailable, mutation is unauthorized, or the candidate weakens correctness, permissions, failure handling, or an owning contract. When the iteration may need a durable multi-milestone objective, suggest `long-running-goal` and wait for explicit user confirmation before creating or converting its contract.

Evaluator delegation requires that the active environment or plan authorizes delegation and does not invoke `orchestrate-subagents`; use that skill only when the user explicitly requests subagent orchestration.
