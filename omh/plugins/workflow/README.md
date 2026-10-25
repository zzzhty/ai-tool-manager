# Workflow

Reusable agent workflow skills maintained from the oh-my-harness repository.

## Skills

- `long-running-goal`: explicitly requested continuation-ready staged goals and strict serial Long-Running Goal Sequences with explicit lifecycle, branch routing, execution authority, runtime hard stops, milestone scope gates, evidence, and close.
- `orchestrate-subagents`: user-requested subagent orchestration using bounded `task_name` assignments, prompt-declared permissions, evidence consolidation, failure handling, and parent-owned integration.
- `prompt-strategy-loop`: evidence-backed prompt and agent-strategy iteration with risk-proportional evaluation and bounded writeback.
- `scope-discipline`: explicit scope-and-evidence discipline that rejects unsupported expansion, keeps necessary consequences, and supplies the shared necessity gate used by long-running-goal milestones.
- `sop`: standard operating procedures for repeatable manual, agent-executed, or automated workflows with eight core sections: trigger, inputs, execution harness, allowed actions, steps, validation, output contract, and stop conditions. Declared authorized recovery pauses dependent steps until unchanged validation passes; explicit termination, safety and permission stops take priority. Recovery is optional; add further detail only when used.
- `summary-in-html`: standalone HTML developer summaries and entry-first source-code walkthroughs for a project, directory, module, feature area, documentation chapter, or user-specified scope, with optional image assets when explicitly requested.

## Shared Vocabulary

- `Continuation contract`: the durable goal file contract that lets the same or another agent continue without chat history.
- `Long-Running Goal Sequence`: the `Sequence Child Goals` branch that gives one parent authorization to a strict serial set of boundary-complete child goals; `umbrella` is only an informal alias.
- `Workflow component`: an internal reusable step used by a skill, such as `long-running-goal` planning preflight or checkpoint evidence, without becoming a standalone user-invoked skill.
- `Necessary consequence`: work not explicitly enumerated but proven by reachable current evidence to be required for the authorized result to remain correct, safe, compliant, or gate-complete.
- `Milestone scope gate`: the `long-running-goal` adapter that applies the shared scope-discipline necessity gate only to material scope or validation expansion, while preserving all work already frozen by the milestone and owner contracts.
- `YOLO non-stops`: authorized local continuation inside a Ready goal; see [execution authority and hard stops](skills/long-running-goal/SKILL.md).
- `Task temporary cache root`: an exact goal/sequence-owned temporary namespace; [execution](skills/long-running-goal/references/execute-and-close.md) binds it and [Close](skills/long-running-goal/references/close.md) applies its recorded housekeeping policy.
- `Runtime hard stops`: authorization boundaries stop the affected action immediately; technical recovery changes strategy after the first two runtime-reported native Goal failures and honors the third native Codex Goal stop; see the [goal contract](skills/long-running-goal/SKILL.md).

[Planning preflight](skills/long-running-goal/components/planning-preflight.md) owns required methods, sourced completion/reuse/skip evidence, and authorization coverage. [Sequence child goals](skills/long-running-goal/references/sequence-child-goals.md) applies that contract to the parent and child registers. `grill-with-docs` remains the explicit Matt entrypoint; Workflow composes its underlying methods.
