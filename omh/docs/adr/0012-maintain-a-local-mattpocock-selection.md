# ADR 0012: Maintain a local Matt Pocock selection

> The decision remains current. Original local baseline and worktree observations
> below refer to the private pre-rebuild archive. Upstream provenance is unchanged.

Status: Accepted for implementation on 2026-09-08.

## Context

The user approved the [consolidated selection and behavioral oracle](../../dev_docs/mattpocock-skills-improvement-proposals.md) and requested execution. The source baseline is `8a252783d9c4bddbd7569daf151e7fb150aa7cd1`; the only initial working-tree change is that proposal. Matt source has no pre-existing staged, unstaged, untracked, or ignored changes.

The upstream v1.2.3 mirror at `6acc160e4e0cd062dbbbd7a1b26ae92855edf07e` includes useful engineering methods, but its full workflow and mandatory steps do not match this repository. Usage supports retaining lightweight entrypoints; source review identifies specific review-scope, conflict-staging and repeated-interview problems.

## Decision

Keep 20 locally maintained skills under the existing `mattpocock-skills` namespace. Retire `to-questionnaire`, `to-tickets`, `wait-what`, `wayfinder`, and `wizard` from the source catalog and distribution. Keep the other ten repository skills. Core/specialized groups in the proposal describe maintenance priority, not separate installation modes.

Keep upstream attribution and license in the plugin. Retire the full-mirror updater and upstream lock. All plugins use the repository `VERSION` and existing content-derived generation, catalog and plugin validation. This supersedes the Matt-specific unchanged-source guidance in ADR 0001 and the upstream-version exception in ADR 0009; their historical context remains intact.

Future upstream releases are inputs to a local comparison and selection process. The plugin README owns that procedure; the [upstream review record](../../dev_docs/mattpocock-upstream-review.md) owns the last fully reviewed upstream revision and unresolved changes, including selected changes not yet applied. Original attribution, review progress and locally adopted content are separate facts. `omh update` distributes the reviewed local edition and does not import Matt upstream changes.

The installed Codex plugin validator rejects all ten retained `disable-model-invocation: true` declarations with “must be false”. The approved selection preserves those declarations and their native `allow_implicit_invocation: false` policies. Therefore the lifecycle uses the existing repository plugin validator for every package, with invocation consistency checked by the canonical catalog. Unix/PowerShell wrappers and Python lifecycle resolution share that default; explicit `PLUGIN_VALIDATOR` overrides remain authoritative and their failures are not retried with a different tool. This replaces automatic preference for a separately installed system validator, without removing source, schema, path, distribution or cache checks. Watcher's standalone doctor still validates only its own compatible package; lifecycle calls pass the resolved validator to it.

## Identity and consumer inventory

| Surface | Classification and disposition |
| --- | --- |
| Plugin name, 20 retained skill names, invocation policies | Published interfaces; preserve. |
| Five retired skill names | Published interfaces; removal explicitly approved in this migration. No callable aliases or backup package. |
| ask-matt routes, PHASE-BOUNDARIES.md, setup tracker references | Current repository-owned consumers; update together, move useful handoff guidance to its owner and remove redundant resources. |
| Updater, upstream lock, check_harness special case, README commands, updater tests | Current owner-specific tooling; retire with the mirror contract. Transfer independent metadata/validation coverage to existing owners. |
| Lifecycle validator resolver, system-validator helper/constants, shell and PowerShell defaults | Internal implementation consumers; remove automatic system selection together, retain the external PLUGIN_VALIDATOR override. |
| Plugin version authority and generated distribution identities | Persisted contract; change explicitly from upstream 1.2.3 to repository VERSION (currently 1.0.0) plus a new generation. Verify target identity rather than numeric maximum. |
| Watcher metadata | Remove retired active identities and mappings to them; retain valid mappings to selected skills. Supporting metadata remains attribution, not execution. |
| Upstream update procedure and review record | Repository-local maintenance guidance and durable review progress; README owns the steps, the review record owns progress, and original provenance stays unchanged. No runtime selector or new lock format. |
| Historical logs, ADRs, user projects and prior reports | Preserved evidence and external state; do not rewrite or delete. Reports retain raw historical names even outside the current catalog. |

## Validation and recovery

The approved proposal's behavior scenarios are frozen before source edits: complete requested review range, unrelated work preserved, resolved decisions reused, read-only stays read-only, independent regression coverage retained, ordinary handoff stays independent, resources/invocation policies resolve, and historical events survive catalog removal.

The follow-up upstream-update clarification must preserve local adaptations when the same upstream lines change, leave new or retired skills outside the catalog unless selected, keep deferred changes visible after advancing review progress, keep incomplete reviews from advancing that progress, and distinguish a comparison request from authorization to apply source changes. These are semantic review scenarios, not new runtime gates.

Retain exact content identity for distribution and cache integrity; upstream byte equality no longer owns done. Run the owning tests before generating the new identity once, then validate the complete selected distribution. Verify isolated installation/projection behavior before any authorized live activation.

Git preserves the source baseline and retired skills. A rollback restores the complete reviewed source and generated identities through the normal manager lifecycle; no parallel skill tree is maintained. This implementation does not authorize rewriting external tasks, installing on the work server, or sending messages to others.
