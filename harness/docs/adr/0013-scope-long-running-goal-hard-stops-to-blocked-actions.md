# ADR 0013: Scope long-running goal hard stops to blocked actions

Status: Accepted for implementation on 2026-09-08.

The decision and consumer contract remain current. Evaluation results and recovery references below describe pre-rebuild work retained in the private pre-rebuild archive; they do not validate the clean repository's new root.

## Context and authority

The user requested correction of the reviewed hard-stop rules. Source inspection found four unnecessary stops: locally missing but obtainable prerequisites, separable unrelated changes, fully specified later actions awaiting approval, and mandatory size accounting when cleanup is Disabled. The readiness checker also rejects legitimate credential or tool failures merely because their description contains words such as `checkpoint` or `rebuild`. Usage logs do not establish a hard-stop frequency.

`plugins/workflow/skills/long-running-goal/` owns the behavior, templates and checkers. This change explicitly revises their admission and Disabled-close contracts; it does not authorize goal execution, publication or installed-cache mutation.

## Decision and consumer inventory

| Surface | Classification and treatment |
| --- | --- |
| Skill, plugin README, checkpoint/preflight components, creation/execution/sequence references | Current instruction owners and consumers; align the five corrections together. |
| Atomic and sequence templates; readiness and sequence checkers/tests | Persisted contract producers and consumers. Preserve existing fields and milestone states. Add an optional `Deferred approval gates` table keyed to an existing milestone, with action, Pending/Approved status and approval evidence. Pending gates permit earlier authorized stages, but cannot enter their owning milestone's work or pass Close. |
| Existing goal files and historical evidence | Preserve. Goals without deferred gates retain their existing contract. Do not move an existing permission boundary or change Enabled cleanup without user authority. |
| Workflow package manifest and distribution identity | Existing exact-content contract; regenerate once after source changes and owning tests. |

Preflight must settle scope, design and permission boundaries. A specified future approval can remain Pending at Ready; unspecified permissions remain Draft. Place preparation before the gated milestone. Only actual user authorization changes a gate to Approved. Sequence execution stays strictly serial, and parent authorization never supplies a child's missing permission.

Acquire or restore prerequisites only through authorized means. Isolate unrelated changes without modifying user work or weakening required validation. Disabled cleanup still records every exact owned root and affirmative retention, but sizes are optional and may be unknown. Enabled cleanup retains its existing authorization, Watcher dependency and evidence requirements. Limit the recoverable-stop heuristic to explicit unconditional stop declarations; natural-language keyword occurrence cannot establish a hard stop.

## Frozen behavioral oracle

Compare the no-change baseline with this smallest scoped candidate:

- An authorized dependency restore continues; unavailable credentials beyond authorized recovery stop the affected action without inventing permission.
- Separable dirty files do not block a checkpoint. Required validation, rollback and evidence must still hold, and unrelated staged work must not enter the checkpoint commit.
- A fully specified pending release gate allows preceding local milestones. Its milestone cannot run or become Done until authorized; unknown gates, missing action/evidence, unresolved preapproval and premature Closed states fail validation.
- A Sequence can prepare earlier children while a later child declares a pending gate. It cannot skip a blocked child or inherit external-write authority from the parent.
- A legitimate checkpoint credential or rebuild-tool hard stop passes. An explicit instruction to stop at every checkpoint or the first validation failure still fails.
- Disabled Close passes with exact roots and affirmative retention even without numeric sizes. Missing roots, deletion under Disabled, and incomplete Enabled cleanup still fail.

Run the owning behavior checks and independent semantic and permission/counterexample reviews, then validate the generated distribution. These checks do not measure live model adherence or real-world stop frequency.

## Pre-rebuild evaluation

The no-change baseline rejects legitimate resource failures and requires unnecessary Disabled size accounting. The selected candidate keeps the existing gates except for the explicitly revised cases above. Independent semantic review found two candidate gaps: unconditional checkpoint stops followed by an ask/wait instruction escaped detection, and an unknown action or explicitly negative approval evidence could pass. Both were corrected and the reviewer reran the two affected regression tests successfully. A separate permission/counterexample reviewer checked twelve cases and found no additional boundary regression; Sequence coverage from that review was static, supplemented by the owning integration test.

Readiness validation checks declared contract consistency, not the truth of an approval claim or every natural-language formulation. Execution still requires actual user authority. No real goal or installed environment was changed during evaluation.

Validation completed with the managed tooling Python (`PYTHONDONTWRITEBYTECODE=1`, `-B`): all 86 Workflow tests passed; the root test suite exited successfully; all three source plugins, Workflow relative links, the generated repository identity, and `git diff --check` passed. Windows-specific execution remains subject to the suite's platform skips. Initial new-test failures were fixture issues (a milestone helper also matched approval rows, then combined snapshots duplicated promotion history); both were fixed without changing the production Sequence contract.

After the source edits and owning tests, one generation update produced Workflow `1.0.0+codex.d356f8473bc1c38a`. Matt and Watcher retained their already prepared identities. Publication and managed-install activation were not part of this correction.

## Recovery

The private pre-rebuild archive retains the previous contract and its validation/recovery references. Restoring it requires a separate review of source and generated identity together; a direct revert in the clean repository cannot recover that earlier contract. Newly instantiated deferred-gate goals would need their pending approval resolved or status returned to Draft before using the older checker; no compatibility alias or second contract authority is introduced.
