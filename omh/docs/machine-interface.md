# Machine interface (protocol 1)

> **Vendored deployment**: this engine now ships inside the ATM repository.
> The transport and protocol below are unchanged; the terminal entry point is
> `atm harness ...` and the distribution is materialized (non-Git) into
> `<home>/repo` by `scripts/atm_embed.py`, so the `repo/scripts/omh.py` path
> contract still holds. `update`/`recover`/`repair --reclone` are refused in
> embedded mode; upgrades arrive with ATM releases via `atm harness sync`.

ATM and other local clients integrate with the OMH CLI, not its state files.
OMH owns distribution, receipts, desired state, locks, update journals, recovery,
and cleanup. The standalone CLI remains supported, including its shorthand and
interactive confirmations.

## Discovery and transport

Run the verified OMH executable as an argument vector, never a shell string:

```text
omh [--home PATH] machine --protocol 1 capabilities
omh [--home PATH] machine --protocol 1 status
omh [--home PATH] machine --protocol 1 check [--harness ID ...]
omh [--home PATH] machine --protocol 1 doctor [--harness ID ...]
omh [--home PATH] machine --protocol 1 install --harness ID [--harness ID ...] --confirm
omh [--home PATH] machine --protocol 1 refresh --harness ID [--harness ID ...] --confirm
omh [--home PATH] machine --protocol 1 remove --harness ID [--harness ID ...] --confirm
omh [--home PATH] machine --protocol 1 repair --harness ID [--harness ID ...] --confirm
```

The explicit protocol version is required. Capability detection, rather than the
product's release version, determines compatibility: historic releases can share
the same `VERSION`. An old CLI may reject `machine`; treat that as unavailable,
never fall back to an unconfirmed lifecycle command. Probe before enabling
controls. Do not interpret an unknown or malformed response as success.

Every machine response is one JSON object on stdout:

```json
{"protocolVersion":1,"operation":"status","ok":true,"result":{},"error":null}
```

Failures use `ok: false`, `error: {"code": "...", "message": "..."}` and a
nonzero exit code. `result` may still contain diagnostics. Invalid requests can
have a null operation. Codes are:

- `invalid_request`: exit 2, malformed or unbounded request
- `unsupported_protocol`: exit 2, unsupported version
- `confirmation_required`: exit 3, missing confirmation or interactive-only work
- `busy`: exit 4, another OMH lifecycle mutation holds the existing lock
- `operation_failed`: exit 1, runtime, state, ownership, check, or lifecycle failure

Human diagnostics are not a parsing API. Child stdout/stderr are captured into
`result` instead of contaminating the outer JSON stream. Process startup failures
before the machine adapter loads (for example, a missing checkout/interpreter)
can still be ordinary CLI failures; clients must handle missing/invalid JSON.

## Capabilities and observations

`capabilities.result` contains `protocolVersion`, canonical `harnesses`, an
`operations` object keyed by operation, `instructionReplacement:
"interactive-only"`, and `statusObservation: "recorded-state-only"`.
Each operation describes `supported`, `requiresConfirmation`, and
`explicitHarnesses` (whether explicit harness targets are mandatory).
Unsupported operations also have a `reason`.

`status.result` has exactly the existing `omh status --json` recorded-state
payload, including `desiredHarnesses`, `manager`, `harnessReceipts`, `operation`,
`stateKind`, and `observation`. It does not validate live files, enumerate installed
client applications, or claim health. `worktreeClean` remains null. Missing state
is not initialized. A recorded interrupted operation remains visible for the
standalone recovery workflow.

`check` and `doctor` invoke their existing read-only validation paths. Doctor
fails on warnings as before. They neither repair nor bootstrap a runtime.
With no harness targets they validate the installed set. Their results, and
lifecycle results, are `{harnesses, exitCode, stdout, stderr, stdoutTruncated, stderrTruncated}`; an empty harnesses
array on a check means the normal installed-set selection, not zero checked.

## Confirmation and scope

Install, refresh, remove and scoped repair require one or more explicit `--harness` arguments.
Aliases are canonicalized and duplicates removed. There is no implicit default,
`--all`, arbitrary forwarded argument string, path override, migration option,
purge, or `--yes` in the machine protocol. ATM should show the operation and exact
selected targets, obtain the user's confirmation, then invoke once with
`--confirm`. Confirmation applies only to that invocation and its selected
harnesses. Repeated button clicks must not queue duplicate writes.

For install/refresh, confirmation covers missing instruction creation, skill
projections and the existing exact managed cleanup rules. It does **not** grant
permission to replace arbitrary existing instructions. All selected instruction
targets are preflighted inside the existing manager lock before distribution or
state mutation. A target requiring live replacement consent returns
`confirmation_required` before any selected harness is applied. The lock file
may be created/acquired; it is not a distribution or state migration.

The child instruction preflight also runs noninteractively, and existing
source/target snapshot revalidation still applies immediately before writing.
Existing exact registry-peer/operation-journal provenance rules are unchanged.
No general replacement consent token is introduced. `--yes` in the standalone
CLI still cannot authorize arbitrary instruction replacement.

Removal uses the same receipt validation, ownership checks, shared-resource
retention and manager lock as standalone removal. The machine adapter never
edits receipts or resources itself. Missing or unhealthy tooling is reported;
there is no runtime bootstrap, checkout restoration or PATH repair as a side
effect of machine calls.

### Scoped repair

`repair` is supported only with the existing healthy runtime and recorded
checkout. It repairs selected recorded installed harnesses and manager launchers;
it does not add harnesses. Its capability has
`scope: "existing-runtime-checkout-selected-harnesses"`,
`recoverySupported: false`, and `pathChanges: false`.

An active operation journal is rejected before automatic recovery. All selected
instruction targets are checked under the same repair lock before any launcher
or harness writes. Runtime bootstrap, checkout replacement, inferred former-repo
migration and PATH changes are disabled in this machine scope. Missing-runtime,
missing-checkout and interrupted-update recovery remain standalone operations.
Full machine recovery would require a stable-shim authorization contract and one
continuous lock through restoration, bootstrap and journaled lifecycle work.

## Current limits and client recovery

Protocol 1 advertises update and recover as unsupported and returns
`confirmation_required` without starting them, even with `--confirm`. Their
checkout transitions, journal recovery and manager-wide effects require the
standalone CLI until a bounded machine authorization path covers all phases.
An update invokes target and rollback revisions that may not support this
protocol, refreshes the entire desired set, can change registry-owned roots or
materialization, and modifies PATH. A safe cross-version extension must validate
both revisions, journal authorized full scope, and preflight final target plans;
simply passing --yes or a noninteractive flag is insufficient.
Never represent these controls as working GUI operations.

Like the existing lifecycle, multi-harness application is not an atomic filesystem
transaction. Initial replacement conflicts are caught before application, but a
later I/O error, external race or failed validation can leave partial work. Treat
any nonzero result as failure, display diagnostics and refresh recorded status.
Do not retry automatically, modify state, erase a journal or bypass ownership
checks. For busy results, let the existing operation finish before user retry.
Use the standalone `omh status`, `omh check`, `omh repair` or `omh recover` as
appropriate. A refresh should never be relabeled as update; it does not fetch.

Diagnostic streams are drained concurrently and retain at most 64 KiB each, with
truncation flags. The read-only runtime health probe times out after 30 seconds.
Lifecycle cancellation/time budgets belong to the client owning the entire
process tree. Terminating only the adapter does not establish that a descendant
stopped mutating; after cancellation, report an unknown outcome and inspect
status/lock before retry. The adapter does not impose an unsafe parent-only
mutation timeout or automatically retry.
