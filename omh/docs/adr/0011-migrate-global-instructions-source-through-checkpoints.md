---
status: accepted
---

# Migrate the global instructions source through ordered commits

The repository currently uses the root `AGENTS.md` as both the global harness
instructions source and the project-local instructions file. Codex therefore
loads the same global policy through the installed harness and again from the
repository root. The source must move to `agents/global-instructions.md` before
the two documents can own distinct semantics.

This migration uses three linear, immutable checkpoint commits without changing
`VERSION`, creating a release tag, or publishing a GitHub release:

1. `bridge-ready`: `AGENTS.md` remains current and
   `agents/global-instructions.md` is its byte-identical registry peer.
2. `source-switched`: the global file becomes current, the root file remains its
   byte-identical peer, and the registry records the exact bridge-ready commit as
   its required predecessor.
3. `semantic-split`: the two files receive their distinct global and project
   responsibilities, and the registry records the exact source-switched commit
   as its required predecessor.

The structured `sources.instructions` registry entry owns the migration id,
stage, current source, peer, and—after the first checkpoint—the required
predecessor revision. `bridge-ready` and `source-switched` require both sources
to be ordinary, byte-identical files. The semantic split is the first stage in
which their content may differ. Checkpoints must be traversed in order; after
source cutover, a transition cannot silently leave the migration contract.

Instruction target classification has one evidence source:

- `current` matches the current registry path or content.
- `registry-peer` matches the exact peer path or content and may be migrated
  atomically without a prompt.
- `operation-journal` matches an exact old or new source digest recorded for the
  active update and may refresh a copy target during update or rollback.
- `explicit-former-repo` comes only from `--migrate-from-repo` and continues to
  require live confirmation; `--yes` does not grant that authority.
- `unmanaged` has no manager provenance. Regular files require live replacement
  confirmation, while unmanaged links and unsupported target types fail closed.

Update preflight reads both revisions from Git objects and records their source
paths and SHA-256 digests in the operation journal. When an update enters a new
migration stage, preflight and the resumed updater verify its predecessor before
writing manager state or refreshing a harness. This check also protects a direct
jump made by a client predating the bridge. Updates that remain within the same
stage do not replay its historical predecessor check. Refresh accepts journal
provenance only when the operation id, operation type, and checked-out revision
match the active journal. Rollback and explicit recovery use the same evidence,
so copy targets can move in either direction without weakening ordinary
replacement confirmation.

The registry peer remains active after the semantic split until a separately
authorized retirement. Commit A, B, and C must not be amended, squashed, rebased,
or force-pushed after a later checkpoint records their SHA.
