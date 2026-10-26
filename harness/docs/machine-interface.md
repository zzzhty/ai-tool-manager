# Rust harness application interface

The Python `machine --protocol 1` subprocess transport is retired. CLI and desktop
use `atm_core::distribution::Service` directly. `harness_machine` retains the typed
GUI capability, diagnostic and confirmation boundary; it does not launch an engine.
Past protocol envelopes and receipt identities remain historical evidence, not a
fallback to an older executable. ADRs 0022 and 0027 record the previous design.

## Application service

`Service` owns source validation, immutable content cache, target planning,
receipt ownership, locks, journaled apply/recovery, optional payload environments
and hook configuration. The CLI presents the same service through:

- `atm harness bootstrap|sync|status [--home ABS_PATH]`
- `atm harness plan <install|refresh|remove|repair> --harness ID[,ID...]`
- `atm install|update|uninstall|repair skills --harness ID[,ID...] [--dry-run]`
- `atm harness adopt --dry-run` for a read-only handoff plan, `atm harness adopt`
  and `atm harness recover` for explicit handoff/recovery
- `atm harness runtime prepare GROUP --python ABS_PATH [--external-venv ABS_PATH] [--offline]`
- `atm install|uninstall|check hooks --harness codex`

`harness --` parses only a bounded set of these known Rust operations. It cannot
execute arbitrary argv, Python, shell commands or the retired machine protocol.

## GUI boundary

Capabilities expose canonical registry harness IDs and operation descriptors with
`supported`, `requiresConfirmation`, `explicitHarnesses` and optional `reason`.
Supported mutations are install, refresh, remove and repair. They require a true
confirmation plus explicit, valid, unique targets. Aliases resolving to the same
target are rejected. An in-process gate avoids duplicate GUI execution; the service
lock also serializes independent processes. Upgrade/handoff and recovery remain
explicit terminal workflows. Demo mode continues to reject real mutations.

Diagnostics return `{operation, passed, exitCode}`. The service checks recorded
owned files, shared configuration, content cache and any enabled hook runtime;
static distributions have no Python prerequisite. Errors propagate through the
existing typed error view. There is no child-process log parser or engine timeout.
Optional Python payload provisioning owns its bounded process handling separately.

## Recorded observations

`harness::query` reads the service's recorded status and projects only the fields
shown by the GUI. Status includes product `atm-harness`, `manager`,
`desiredHarnesses`, `harnessReceipts`, `operation`, `observation: recorded-state-only`
and `worktreeClean: null`. A missing manager is not initialized. Unknown recorded
information remains unknown. Pending journal recovery is visible as degraded state.
A ready receipt is not a live-health claim.

Plans capture observations; apply validates them again under ownership and lock
rules. User edits and unowned collisions stop writes. Journal recovery preserves
conflicting later changes. The multi-file lifecycle is not a fully atomic transaction.
Legacy state enters Rust ownership only through an explicit validated handoff;
no ordinary read or installation silently adopts it.
