---
status: accepted
---

# Retire skill-watcher hook collection

The user no longer needs automatic skill-watcher collection in new distributions.
This supersedes the hook activation capability in the Rust migration without
removing the four maintenance skills or historical evidence.

Remove Rust hook command generation, the Python `skill observe` command and its
collector, the Python hook command generator, and the shipped `hook:watcher`
binding. `atm install hooks` returns `HARNESS_HOOK_RETIRED` before lock, runtime
or configuration mutation. The remaining Watcher runtime serves historical
reports, explicit event tools and doc audits; importing it does not enable hooks.

Keep the persisted schema-1 Rust HookOwnership fields, predecessor command proofs,
old catalog/manifest readers, metadata-cache/schema fields, historical identities,
logs and recovery journals. Exact receipt-bound removal remains available without
executing or validating an old Python interpreter. Existing owned groups must be
removed explicitly before content sync; edited, duplicate or unproven groups stop
removal. Unrelated hooks, old runtime environments and user files are preserved.

Move repository-internal metadata helpers from the removed collector into
`catalog_metadata.py` and update every reader together. Those module/function
references are internal implementation; persisted metadata names and behavior do
not change. `skill doctor` remains read-only and reports retired handlers without
collecting synthetic events or recommending hook installation. No skill text,
invocation rule or permission contract changes. Canonical catalog schema 1 and
existing aliases remain available for interpreting history; they are not proof
of native client loading or execution.

The existing manifest digest owns payload byte identity, so seal the final runtime
inventory after source edits and owner tests. No new checksum or identity gate is
introduced. Plugin contents are unchanged and keep their existing identities.

## Verification mapping

- Old Rust enable/re-enable and generated-command tests retire with command
  generation. Replacement tests reject enable before state/Python mutation and
  retain foreign-config, exact ownership, duplicate, edited-group and idempotent
  removal checks. Legacy Windows quoting/source-proof tests remain because they
  still govern predecessor retirement.
- Old Python observation/lifecycle/turn-state and generated-hook tests retire
  with the collector. Preserve catalog-path/schema/alias checks, redaction,
  historical report deduplication, proposal validation and explicit migration
  boundaries. Test that `observe` is unavailable without writes, metadata reads
  work without a repository/installer, doctor writes no events and history readers
  preserve their input. Tests use historical event fixtures, not a hidden collector.
- Existing receipt/journal recovery suites remain unchanged. Native package tests
  require no shipped collector or hook binding and validate retained metadata with
  the runner's explicit Python; the distributor still runs with empty PATH.

Real historical logs are never reset or rewritten during retirement. Previously
cached payloads remain as recovery evidence; retaining a cache is not an active
hook or permission to resume collection. OMH Hub work must not reintroduce the
retired collector. Report-evidence semantics can be reconciled separately with
OMH ADR 0027; this decision does not claim that reconciliation is complete.
