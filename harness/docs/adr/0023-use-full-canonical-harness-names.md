# Use full canonical harness names

Status: Accepted
Date: 2026-10-09

## Context and bounded identity inventory

Canonical harness IDs should use the complete distribution name, with short
names reserved for aliases. This explicitly authorized migration supersedes
ADR 0018's naming direction for Copilot CLI and Gemini CLI only.

| Surface | Classification and treatment |
| --- | --- |
| Registry keys and aliases | Public and persisted contracts: migrate `copilot` to `copilot-cli` and `gemini` to `gemini-cli`, retaining the short spellings as input aliases. |
| README and generated help, bootstrap and lifecycle selection | Current consumers: describe full canonical IDs and resolve either spelling through the registry before deduplication. Short command examples remain valid alias examples. |
| Desired state and per-harness receipt paths/payloads | Persisted contracts: accept short, full, or mixed spellings; converge only through successful normal lifecycle mutations with ownership-validated cleanup. |
| Initial install receipt and active update journal | Immutable or recovery evidence: preserve initial receipt bytes and recorded recovery identity/evidence; journal phases may advance. Resolve names in memory. Delay receipt/desired convergence until `finish_operation` closes the journal. |
| Migration, transition, registry, installer, lightweight-command, lifecycle, and VS Code tests | Current validation consumers: update canonical expectations and deliberately seed short legacy state; exercise both cross-version directions rather than turning migration tests into no-ops. |
| Native roots, environment variables, filenames, display names, product/vendor references and local fixture directory names | External or non-identity contracts: unchanged. In particular `.copilot`, `.gemini`, `COPILOT_HOME`, `GEMINI_CLI_HOME`, and instruction filenames keep their semantics. |
| All existing ADRs and dated research | Historical evidence: unchanged, including ADRs 0015, 0018 and 0020. |
| `claude-code` / `claude`, `pi-agent` / `pi`, `codex`, `zcode`, `opencode`, `vscode` | Public identities outside this migration: unchanged. |

## Decision and compatibility

The registry remains the single authority, including for custom registries.
There is no hard-coded global alias map, schema change, new resource root, or
alias-specific distribution. Shared VS Code/Copilot resource ownership remains
per resolved resource as specified in ADR 0020; changing the CLI's canonical ID
does not merge those clients.

The generic migration protocol introduced in ADR 0018 is reused in the opposite
naming direction. Read-only commands and dry runs do not rewrite state. A normal
successful mutation writes the canonical replacement receipt before deleting a
validated alias receipt and preserves the desired update policy. Unknown or
unsafe receipt paths still block cleanup. Initial `state/install.json` is never
rewritten by migration, whether it records short or full names.

Managed updates translate rolling names to the target revision's registry.
While an update journal is active, its input vocabulary remains available to
the old caller for failure rollback. After successful journal closure, rolling
state converges to this revision's full names. Post-commit convergence failures
warn and defer cleanup to a later refresh rather than triggering stale rollback.
Explicitly authorized downgrades translate back to short-canonical revisions;
pre-alias full-name revisions remain representable. The existing ancestry and
`--allow-downgrade` gates still apply. Manual checkout downgrades are unsupported.
Rollback uses the restored revision's registry and preserves the initial receipt.

## Verification and rollback

Tests cover both input spellings, canonical choices/help/bootstrap receipts,
short-only and mixed persisted state, immutable install bytes, no-write reads
and previews, failed writes/materialization, ownership-safe cleanup and repeated
mutations. Transition tests preserve short names throughout an active journal,
then assert full-name convergence, and test legacy short-canonical and pre-alias
full-canonical target registries. Existing custom-registry and shared-resource
ownership tests remain binding on both platform materializations.

Rollback of this source change restores the previous registry direction; use
the managed update/downgrade protocol above for installed state. Do not rewrite
historical records or manually rename receipt files. No plugin content,
distribution fingerprint, schema version, or release version changes are needed.
