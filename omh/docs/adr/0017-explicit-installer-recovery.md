---
status: accepted
---

# Require explicit installer recovery for ready installations

The public `install.sh` and `install.ps1` wrappers share one Python classifier.
Fresh homes use bootstrap. Incomplete installations retain the exact receipt,
checkout, launcher and explicit fast-forward checks. Ready installations require
mutually exclusive `--repair` or `--reinstall`, or an interactive choice whose
default is Cancel. `--yes` cannot select a mode. Adoption and fast-forward flags
cannot bypass this boundary or be combined with ready recovery.

This extends the bootstrap adapter described in ADR 0010 without moving
lifecycle ownership out of the manager. Repair delegates to the independent
bootstrap and `omh repair`. Reinstall uses the same pipeline with exact-version
reclone and runtime rebuild. The existing manager lock, update journal recovery,
instruction replacement prompts and harness closure remain binding.

`manager.json` and `desired.json` remain the rolling authorities with unchanged
schemas. When both are absent on a legacy ready installation, the installer
validates the current managed checkout, remote and package identity before
deriving state from that revision. It does not restore the old initial receipt
revision or use the invoking checkout as version authority. One missing lifecycle
file is an error, not permission to initialize either file.

Ready recovery requires the install receipt's paths to identify this exact
manager home. Ordinary managed component roots can be reconstructed, while
linked/reparse roots and unproven paths stop the operation. Reinstall preserves
old checkouts through the existing checkout recovery owner and moves the old
venv into `state/repair-backups/` before rebuilding it. Failure restores the old
venv when no replacement exists; otherwise the backup remains inspectable.
Unknown files outside those replaced components are untouched.

The initial ready receipt is immutable. Manager repair completes an `installing`
receipt only; it no longer rewrites ready receipts or unchanged desired state.
For previously installed manager versions that still rewrite these files, the
installer preserves the original receipt and desired policy after execution,
including failure. An active update journal retains ownership of desired-state
rollback, so the adapter does not undo that transition. Unexpected harness-set
or channel changes outside journaled recovery are reported and preserved for
inspection rather than silently accepted.

Dry runs validate available ownership/state and print the recovery plan without
creating a lock, state, venv or PATH entry. They do not certify remote availability
or harness closure. A streamed wrapper may still acquire and remove its
temporary bootstrap source, as before.
PowerShell leaves session PATH unchanged and relies on Python-owned user PATH
registration plus reopening the terminal; a zero exit status from help or Cancel
must not trigger independent wrapper mutation.

Behavioral coverage includes mode choice/cancellation, incomplete-install gates,
legacy migration at the current revision, immutable state, backup/failure paths,
shared locking and native public wrapper integration through real harness closure.
The integration fixture provisions dependencies offline into disposable real
venvs; normal runtime bootstrap retains its own tests and lifecycle CI.
