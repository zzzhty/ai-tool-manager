# Create Or Upgrade And Loop Harness

Use the matching sections after `../SKILL.md` routes a creation, upgrade, or Loop-shaped branch here. The inline `Ready`, pre-approval/YOLO, hard-stop, and goal-tool boundaries remain authoritative.

## Create Or Upgrade

Here, `upgrade` means converting or reshaping an existing TODO, PRD, issue, checklist, or rough plan into a long-running-goal contract. It does not mean ordinary runtime evolution during milestone execution.

Use `../templates/long_running_goal_template.md` for one goal and `../templates/long_running_goal_sequence_template.md` for a strict sequence unless the repository has a stronger local convention. Prefer the user-specified path, then an existing active goal/TODO directory or index, and use `docs/todo/<goal_slug>_long_running_goal_plan.md` only as a fallback. Do not create a parallel planning tree or append `/todo` to a directory that already serves as the goal directory. Templates and readiness checkers own field shape and structural completeness.

1. Read the current sources needed to establish this goal's scope, authority and acceptance criteria. Use instructions, area overviews, active plans, contracts and validation evidence as relevant; consult historical or archived material only when it explains a current decision.
2. Read and complete `../components/planning-preflight.md` before freezing the goal, including its required methods, sourced decision evidence and authorization coverage through Close. Reuse settled answers without exempting a complete-looking plan from the workflow.
3. Create or reshape the goal file as a continuation contract, preserve useful findings from existing TODOs, and record the planning-preflight marker with completion/reuse/explicit-skip evidence, an optional time estimate, and the task-temporary-cache policy (default `Disabled`).
4. Freeze the contract before implementation:
   - product semantics, owner boundaries, compatibility surface, future/non-goals
   - sequential milestones, usually `M0 Contract Review / Design Freeze`, implementation milestones, docs/release closeout, then `Close`
   - milestone scope, review gate, validation commands, evidence slots, checkpoint expectations
   - execution shape: manual staged execution or Loop-shaped execution
   - pre-approved YOLO local operations, pre-approved external reads/writes, runtime hard stops
   - policy-specific temporary-cache root-or-no-root strategy and `Enabled / Disabled / Not applicable` Close housekeeping policy; `Enabled` records the user's cleanup intent and the `watcher:housekeeping` dependency, not a guarantee that the dependency will still be available at Close
   - Loop harness fields when applicable: trigger, inputs, triage/orchestration, isolation, connector boundaries, independent verifier, durable learning
5. Settle design and permission boundaries before `Ready`. Record actual pre-approvals and sources separately from sourced user-retained or required final-review decisions in `Deferred approval gates` under `../components/planning-preflight.md`; do not defer a permission merely because its action is later. Undefined boundaries keep the goal `Draft`; a Pending gate stops entry into its owning milestone, not earlier authorized preparation. Planned `Enabled` cleanup still requires explicit authorization at preflight.
6. Add close criteria and a reusable continuation prompt that names the exact goal path and directs the next agent to its frozen authority, required gates, current state, and close handling.

Completion criterion: the goal contains the current baseline, frozen contract, ordered milestones and gates, settled approval boundaries, a task-temporary-cache policy with explicit authorization if `Enabled`, close criteria, reusable prompt, and a completed or explicitly skipped planning-preflight marker; otherwise it remains `Draft`. Legacy goals without the housekeeping section remain compatible but grant no cleanup authorization.

Creation may produce a non-executable `Draft` with known facts and unresolved decisions, or a complete `Ready` contract. Validate Draft with `check_goal_ready.py --allow-draft` (and the applicable sequence check); never invent design or authority to satisfy a checker. Current navigation must point to the active contract. Templates and readiness checkers own field shape and structural completeness.

## Loop Blueprint Harness

Do not force automation into small or one-off plans. For manual staged execution, say `Not applicable` with the reason.

When a goal uses recurring triggers, multiple agents, worktrees, connectors, external side effects, or automated triage, make the harness explicit before implementation starts. The plan must answer:

1. Trigger: what starts or resumes the loop.
2. Inputs: which source-of-truth artifacts are read.
3. Triage and orchestration: how findings become scoped tasks and who owns each step.
4. Worktree and isolation: shared checkout, separate worktrees/branches, or serialized edits.
5. Skills and context: mandatory skills, runbooks, docs, specs, or prior decisions.
6. Connector read/write boundaries: readable/mutable systems, pre-approved writes, and specified later writes assigned to deferred approval gates. Undefined boundaries keep the goal `Draft`.
7. Independent verification: subagent, script, test, reviewer, or gate that checks producer work without trusting self-evaluation.
8. Runtime hard stops: exact technical breakpoints where execution stops and asks the user.
9. Durable learning: where results are written back, such as a skill, TODO, report, validation log, runbook, automation memory, or current doc.

If the goal claims automation, connector writes, subagent orchestration, worktree parallelism, or any future approval breakpoint but leaves the corresponding harness or pre-approval field unspecified, keep it `Draft`.

Completion criterion: every applicable harness field is explicit, `Not applicable` is reasoned for manual execution, and any unspecified approval-sensitive field keeps the goal `Draft`.
