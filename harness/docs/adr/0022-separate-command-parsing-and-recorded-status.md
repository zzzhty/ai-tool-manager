---
status: accepted
---

# Separate command parsing, recorded state, and mutation validation

The existing help shortcut already avoided bootstrap. The additional change is
to remove its dependency on tooling Python and live instruction-source files,
and to validate arguments before runtime repair, locks, or other writes.
The checkout owns one parser, reused by the stable shim; metadata parsing keeps
the registry's structural rules but runtime consumers retain strict file checks.
A corrupt registry permits generic help, not execution with guessed harnesses.
Legacy no-command refresh, bare harness names, aliases, home overrides and option
delimiters remain supported. A missing or partially damaged checkout has only the bounded restoration
adapter for plain repair; it rejects extra tokens before mutation rather than guessing a catalog.
A shim can survive an older checkout after a revision switch, so it also uses the
older CLI's existing parser API when the new parsing entry point is absent.
Older parsing/state costs are not silently waived or rewritten.

## Recorded-state compatibility

`manager.json`, `desired.json`, relevant harness receipts and the current journal
are sufficient for status. Structural/schema/product checks remain; no state is
initialized and no Git, Codex, plugin identity, dependency probe or repair runs.
Unknown recorded harness IDs remain visible without resolving arbitrary paths.
If both rolling files are absent, the initial receipt is historical evidence only;
current manager/version is unknown. Partial or corrupt rolling state fails.
A pending operation and degraded state are visible without blocking inspection.
These separate reads are a best-effort snapshot, not a transactional or live
health claim. Existing check/doctor retain real verification and warning policy.

The public JSON `worktreeClean` identity is preserved, but its value is now null
(never checked). Clients must explicitly handle null; false must not be inferred.
The `observation: recorded-state-only` marker makes the boundary explicit.
`version` likewise reports recorded identity, with nulls when it is unknown.
No persisted schema, file identity, digest semantics, or ownership rule changes.
Runtime validation and all mutation journal/rollback boundaries remain strict.

## Bounded duplicate work

Within a single closure call, one source validation produces source identities
used by its cache comparisons. Standalone helpers still validate their inputs,
and a later closure re-reads source/cache. If Codex listing fails, source defects
are still diagnosed. A single pre-activation CLI snapshot supplies enabled and
unknown/alternate-plugin checks; a separate post-mutation snapshot is mandatory.
Default local marketplace reuse no longer resolves an unused Git remote;
explicit Git requests retain their existing validation and failure semantics.

This is phase-local reuse, not a persistent/global hash cache. No source evidence
is reused across checkout switches, acquisition, add/remove, marketplace changes,
resume/recovery or rollback boundaries. Windows copy retry/quarantine observation
and exact instruction ownership/materialization checks remain unchanged.

Behavioral tests assert calls and side effects, not flaky latency thresholds.
Cross-platform CI tests the public launchers; Linux fixture counts do not measure
Windows performance or prove the intermittent upstream Copy fault eliminated.
