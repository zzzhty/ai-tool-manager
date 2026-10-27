---
status: accepted
---

# Consume locked OMH content and explicitly relocate manager ownership

The user authorized the content Hub transition and `.oh-my-harness` to `.atm`
handoff with one owner, retained backups and no skill-watcher hooks.

OMH is the sole source author. ATM retains a reviewed immutable release lock and
local target policy, obtains the content through its Rust validator, and packages
an inactive offline payload. Remove the vendored authoring tree; retain the
ATM-specific prior migration ADRs, identifier policy and receipt/catalog/runtime
schemas under ATM's own docs/policy paths. Other OMH history remains in OMH and Git
history, not a second current authority.

The content manifests, plugin IDs, historical attribution IDs, receipt schema 1
and journal schema 2 preserve their declared meanings. The new relocation record
is a separate version-1 preparation/recovery contract containing the prior receipt,
source/destination and selected content identity. It is not another active receipt.
The old public manager path is changed only by explicit preview/apply and a later
backed-up shell/archive step; existing cached releases and old venvs remain intact.

Migration reuses adapter plans, ownership checks, manager locks and the existing
journal. Both managers are locked; the destination stays inactive during runtime
preparation. The handoff first blocks the old manager, updates references, removes
its receipt, then publishes the destination receipt. Explicit recovery locks both
homes. No directory rename substitutes for venv reconstruction, and no unknown
client file or hook becomes owned through relocation.

## Verification ownership

- ATM retains core/CLI, source/adapters, legacy adoption, runtime, hook retirement,
  journal/user-edit recovery and all native GUI/package gates. New migration tests
  cover static dual-client handoff, destination races, user edits, every journal
  boundary, final-path runtime rebuilding and recovery after old-home archival.
- OMH owns authoring/catalog/package identity, maintenance/workflow semantics,
  snapshot-only runtime and historical evidence suites. Its content release CI
  covers Python 3.11/3.12 on Linux/macOS/Windows. ATM's existing Python jobs check
  out the exact lock revision and run those owner suites; the full source is never
  packaged or committed here. Local/macOS verification checks the imported runtime
  with the explicit runner, while static commands still execute with empty PATH.
- Source inventory follows the relocated policies/docs and new Rust code. The
  release package remains both complete binaries plus allowlisted content. The
  current source/CI result must be checked after the final lock and source edits;
  old migration CI is not a substitute.

See `docs/HARNESS_USAGE.md` for backup, apply, interruption and rollback steps.
Native client loading remains a separate acceptance claim from disk/helper checks.
