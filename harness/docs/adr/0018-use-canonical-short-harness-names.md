# Use canonical short harness names

Status: Accepted
Date: 2026-10-04

## Context

ADR 0015 introduced `copilot` and `gemini` as aliases while retaining
`copilot-cli` and `gemini-cli` as public, persisted canonical IDs. This migration
promotes the short names to canonical IDs and retains the old names as aliases.
It does not broaden either distribution beyond GitHub Copilot CLI or Gemini CLI.

## Identity inventory and classification

| Surface | Classification and treatment |
| --- | --- |
| `.agents/harnesses/registry.json` keys and aliases | Public and persisted identity: explicitly migrate `copilot-cli` to `copilot` and `gemini-cli` to `gemini`; retain the old spellings as input aliases. The registry remains the single naming authority. |
| Registry resolver, bootstrap, lifecycle target selection, helper plans, generated help, and current README examples | Current consumers of that public contract: resolve either spelling to the short canonical ID and deduplicate before selecting a distribution. |
| `state/desired.json` harnesses and per-harness receipt names and payloads | Persisted contracts: accept legacy and mixed spellings on read; migrate through successful normal lifecycle mutations with canonical writes and ownership-checked cleanup. |
| Initial `state/install.json` receipt, including its `harness` field | Immutable record: resolve its harness in memory when needed, but preserve the original receipt and spelling on disk. |
| Update journal snapshots, recovery, and explicit downgrade targets | Cross-version persisted contracts: retain recovery evidence and translate rolling names for the executing revision through the managed update protocol below. |
| Registry, bootstrap, lifecycle, installer-recovery, and launcher tests | Current validation consumers: expect canonical short IDs for new state; retain or add explicit legacy fixtures for migration and immutable-receipt coverage. |
| Display names, vendor packages and URLs, `COPILOT_HOME`, `GEMINI_CLI_HOME`, `.copilot`, `.gemini`, and native instruction filenames | External/product contracts: preserve unchanged, including Gemini's replacement-home semantics. |
| `claude-code`, `pi-agent`, and their aliases; all other harness IDs | Public identities outside this migration: preserve unchanged. |
| Existing ADRs, dated research, archival records, and historical examples | Historical evidence: preserve unchanged. This ADR supersedes only ADR 0015's canonical-name decision for these two harnesses. |

## Decision and state migration

The registry declares `copilot` with alias `copilot-cli`, and `gemini` with alias
`gemini-cli`. Alias uniqueness and the existing lowercase name rules still
apply. `--all` enumerates each canonical distribution once. No alternate skill
roots, instruction targets, or alias-specific distributions are created.

State readers normalize recognized old names and mixed old/new desired harness
sets in memory, then deduplicate without changing the selected distributions or
saved update channel. Unknown desired IDs remain visible in `status`; selecting
an unsupported target for a mutation or check fails validation. Merely reading
old state does not rewrite it.

Successful normal lifecycle mutations write canonical IDs to rolling desired
state and per-harness receipts. Legacy receipt cleanup must prove that a path is
a manager-owned receipt for the same distribution before removing it; unknown
or unsafe paths must not be silently deleted. When retaining a distribution,
cleanup must not discard its only valid receipt before the canonical replacement
has been written successfully.
Removal by either spelling must not leave a stale alias-named receipt for the
removed distribution. Repeated migration must be idempotent.

The initial ready `state/install.json` remains immutable, even when its harness
uses an old name. New installations record the selected checkout revision's canonical name.
Bootstrap resolves against that checkout before writing its receipt or invoking
its lifecycle command, so explicitly installing a pre-alias ref still works.
Installer recovery preserves legacy spellings until the managed child resolves
them. The recovery wrapper allows an identity-equivalent alias rewrite by that
child while preserving the user's desired policy; a changed harness set remains
an error.
`status`, `check`, `doctor`, `update --check`, and dry-run commands perform no
name-migration state writes. This does not change `update --check`'s documented
remote-ref fetch behavior.

## Cross-version rollback and downgrade

Before switching revisions, `omh update` resolves the installed distributions
against the target revision's canonical registry keys. The target must represent
each selected distribution unambiguously. The manager records the update journal
before writing translated desired names and receipts. Receipt translation writes
the target-named replacement before removing equivalent source names; successful
downgrades therefore leave no short-named receipts that the older CLI cannot
clean up. This supports explicit
`--allow-downgrade` transitions to revisions that use `copilot-cli` and
`gemini-cli`, including revisions predating input aliases. The existing target
validation and downgrade authorization gates remain binding. Manual checkout
downgrades are unsupported.

During the new manager's `_resume-update`, stored legacy desired names remain
unchanged while the journal is active. Harness application resolves names in
memory, and per-harness receipt migration waits until the update journal closes
successfully. Only then do rolling desired state and receipts converge to this
revision's canonical names. This keeps a pre-alias caller able to roll back a
failed upgrade using its original name vocabulary.

If convergence fails after the update has committed, the manager warns and
returns update success, with valid aliases left for `omh refresh` to reconcile.
It must not cause an older caller to attempt rollback against a closed journal.
Rollback restores the previous revision and refreshes its harnesses; the new
rollback implementation then writes names canonical for that restored revision.
The initial install receipt is never bulk-migrated by either path.

## Verification

Behavioral coverage must establish canonical registry choices and help,
old/new alias equivalence on both platform materializations, deduplication,
canonical bootstrap and rolling receipts, and migration from legacy-only and
mixed desired state. It must also cover ownership-safe legacy receipt cleanup,
removal by either spelling, repeat mutations, byte-for-byte preservation of a
ready initial receipt, and no migration writes from read-only or dry-run paths.
Cross-version update, failure recovery, post-commit convergence failure, and
downgrade tests must enforce the policy above. Existing ownership,
immutable-state, lifecycle, and wrapper tests remain binding. This rename does
not bump `VERSION` or change plugin content or distribution identities.
