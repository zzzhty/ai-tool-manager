# ADR 0014: Require goal preflight and reuse recorded authorization

Status: Accepted and implemented on 2026-09-09.

The decision and consumer contract remain current. Validation results and recovery references below describe pre-rebuild work retained in the private pre-rebuild archive; they do not validate the clean repository's new root.

## Evidence and decision

The user authorized the reviewed hardening plan, including the explicit `grill-with-docs` entrypoint and tests. The current preflight permits a complete-looking plan to omit the interview; its checker accepts a completion tuple without decision evidence. Deferred gates can postpone known permissions without a reason, and duplicate Approved/Pending rows can stop an already authorized action again.

Require the planning workflow, while reusing confirmed answers and valid completed preflights. The long-running-goal component directly composes `grilling` and `domain-modeling`; `grill-with-docs` remains an explicit-only entrypoint to the same methods. No harness-independent implicit invocation of that wrapper is assumed. Missing required methods block completion rather than authorize an improvised substitute.

During planning, inspect actual operations through Close, reuse existing authority, and resolve uncovered permissions in the relevant grilling frontier. Persist action, target, scope, conditions and source in the existing Pre-Approval owner. Housekeeping retains its independent policy/source. Deferred approval requires a sourced user decision or a required final review; future implementation alone does not invalidate precise conditional approval. Execution consumes still-valid authority across milestones and context transitions, asking only for an uncovered increment or a recorded final approval. Permission to prepare a goal or approve its actions does not itself start execution.

## Consumer classification and migration

| Scoped matches | Identity class and treatment |
| --- | --- |
| Workflow skill, planning component, creation/execution/sequence references, README | Current instruction owners/consumers; align the mandatory flow and authorization reuse together. |
| Atomic/sequence templates, readiness/sequence checkers and synthetic test fixtures | Persisted contract producers/consumers; retain marker/status/source names and child register shape. Add sourced `Preflight evidence`, validate existing decision/document fields, and add `Authorization evidence` within Pre-Approval. Extend Deferred approval gates with `Deferral basis`. |
| Workflow shared Markdown link parser | Current internal consumer; reuse its existing destination semantics for normalized evidence text through an optional text input. Default file parsing remains unchanged. |
| `grill-with-docs`, `grilling`, `domain-modeling`, Matt documentation and invocation metadata | Existing public skill identities; preserve all names and explicit wrapper policy. Clarify direct method composition and dependencies without changing discovery or copying interview methods into Workflow. |
| Existing active user goals | Preserve files and actual decisions. Before execution, supplement missing evidence from inspectable sources or complete the affected preflight. Never fabricate an old interview, approval or skip; unresolved required permissions remain Draft or stop the affected action. |
| Closed historical goals and earlier ADRs/reports | Preserve history. A Closed record with neither new evidence field may use the old structural contract; this exception cannot authorize resumed work. A partially upgraded record must satisfy the new contract. |
| Plugin manifests and distribution identity | Existing exact-package integrity contract; regenerate once after all source edits, reviews and owning tests, then validate the resulting single current identity. |

The source values `grill-with-docs` and `existing decisions` remain readable. New direct composition records `grilling + domain-modeling`; an explicit wrapper invocation records `grill-with-docs`. Reuse records a completed preflight and its source, not merely a design document. Only an explicit user skip records `User skip` evidence. Source references are Markdown links or locatable dated conversation/turn references. Checkers validate presence, local link existence and declared consistency; they cannot authenticate a conversation or establish semantic equivalence of differently worded actions.

## Frozen behavioral oracle

- A complete-looking new plan still applies the required methods and authorization coverage review; known answers need no duplicate questions or gratuitous ADR.
- Completion, reuse and explicit skip each require their own sourced evidence. An old marker alone cannot prove an interview or grant permission.
- Already authorized actions, including conditional approval after validation, continue across milestone/checkpoint/context transitions. New targets, changed conditions or revoked authority stop only the affected work.
- Known uncovered permissions are addressed during grilling. A sourced final-review gate still permits preceding preparation and blocks its owning milestone until approved.
- Duplicate approval rows, direct Approved/Pending conflicts, missing evidence and broken local evidence links fail structural validation.
- Draft does not execute; Sequence stays serial, and a parent's execution permission never supplies a child's missing action or cleanup permission.
- Time assessment stays optional; Disabled housekeeping requires no confirmation; Enabled keeps its own explicit authorization and safety checks.

The no-change baseline fails the first, second and fourth cases. Adding only MUST/no-reapproval leaves contradictory routes intact. Removing all future gates would violate final-review and scope-change boundaries. The selected candidate strengthens the existing owners without a parallel authorization ledger, hook, transcript archive or content-identity proof.

## Pre-rebuild validation

All 94 Workflow tests passed, together with 12 root catalog/plugin-validation tests. The owning tests cover completion/reuse/skip evidence, missing sources, actual local link existence, active/Draft/historical Closed admission, Deferred preparation and execution/Close gates, duplicate/conflicting approvals, child evidence, invocation policy and the unchanged shared Markdown behavior. The source long-running-goal skill check, both affected source plugin validations, Workflow/Matt relative links and diff hygiene passed. The repository plugin validator owns Matt's preserved explicit-only frontmatter; its supported invocation contract takes precedence over the system quick validator's smaller key set.

Independent semantic and permission/counterexample review found three candidate errors: code-styled evidence values hid broken links, a duplicate action across two milestones escaped detection, and substring matching conflated different target names. These were fixed without widening authority. The reviewer independently reproduced the corrected cases, and the two affected behavior tests were rerun with additional assertions for all evidence owners, cross-milestone duplication, distinct targets and distinct conditions. No blocking review findings remain.

Two isolated forward executions used a local Python greeting project and the current source skills. The first agent read and applied both Matt methods, verified the supplied decisions and permissions through Close, produced a Ready plan, and left product code untouched without asking duplicate questions. A second agent, with no scenario conversation history, read only the durable request/plan and a new execution request. It reused valid authority, completed M0/M1/M2/Close without further permission questions, and passed five behavior assertions covering default/en/zh, unsupported language and keyword-only invocation. The final Closed plan passed readiness, local links and retained navigation checks. Initial plan/checkpoint formatting errors were recorded and corrected in the scenario; none required changed product semantics or permissions. These bounded runs provide observed behavior, not a claim about adherence rates for every model or real task.

References to the original scenario artifacts are retained with the pre-rebuild validation record in the private archive; no project cache cleanup or live goal execution occurred during that evaluation. One generation update after source completion produced the Workflow and Matt identities recorded there; the subsequent identity check and both affected plugin checks passed. `.agents/plugins/distribution-identity.json` remains the sole current-value owner. Publication and managed-install activation were outside that change.

## Recovery

The private pre-rebuild archive retains the old contract and its validation/recovery references. Restoring it requires a separate review of source and generated identity together while preserving user evidence; a direct revert in the clean repository cannot recover that earlier contract. A newly created direct-composition record would need its workflow source and extra gate column deliberately adapted before an older checker can consume it. Never relabel a composed run as an explicit wrapper invocation merely to pass that older checker.
