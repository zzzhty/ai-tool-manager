# Clean source rebuild boundaries

The repository starts from one reviewed source snapshot. The owner retains the
pre-rebuild repository privately, including its history, PRs, release tag and
artifacts. No old Git objects, refs, tags, logs or installed manager state are
imported. `VERSION` is retained as source metadata; it does not create a new
release or repoint the old `v1.0.0` tag.

## Fresh installations

A reviewed fresh installation may select `main` explicitly and a new empty
manager home. Validate the selected source and package identities first. The
installer, harness selection, ownership checks and permission confirmations remain
the existing implementation. The source rebuild does not install or refresh the
owner's real manager, clients, skills, hooks or credentials.

The clean repository initially has no release tags. Stable-channel selection must
fail safely until a separate release decision creates an appropriate new release.
Do not copy the old tag object or silently recreate `v1.0.0` at different content.

## Existing installations

Existing clones still using the original repository URL will resolve to the new
repository after the name is reused. Their recorded revision and rollback objects
belong to the pre-rebuild history. Keep the existing installation and its private
recovery material; do not push old branches to the new repository.

Ordinary `omh update` requires a fast-forward descendant. A new root is not a
descendant and must be rejected. `--allow-downgrade` exists for an explicitly
reviewed transition; it is not an automatic migration plan or permission to bypass
state, instruction, ownership or package checks.

`omh repair --reclone` restores the recorded repository and exact revision. It
cannot fetch an old recorded revision from the new repository. Repair must fail
before replacing the current checkout when that revision is unavailable. A
healthy local checkout can remain usable, but that does not prove remote recovery
is available through the reused URL.

The registry's `requiredPredecessorRevision` is a semantic-split checkpoint, not a
credential. It remains unchanged. Existing receipts, instruction checkpoints,
rollback state and external consumers need their own explicit transition review.
Do not edit recorded SHAs, receipts or repository strings just to silence checks.

## Validation and release

Use temporary repositories and empty fixture homes to validate fresh bootstrap,
non-ancestor rejection, missing stable-tag rejection, unavailable recorded-revision
repair failure, checkpoint/rollback behavior and the read-only machine protocol.
The existing root, Watcher and Workflow suites own these contracts. Native Windows
and Linux behavior requires the corresponding environments; local tests do not
establish cross-platform CI success.

Historical design and upstream review records are labelled as pre-rebuild
evidence. Third-party licenses and notices, the Matt release-only selection
workflow, local maintenance contracts and upstream provenance pins remain intact.
Public availability, a new release/tag and existing-installation migration are
separate decisions. This source snapshot does not claim those steps happened.
