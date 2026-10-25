# Consolidate watcher plugins without merging skill invocation boundaries

DocWatcher and Skill Watcher will be consolidated into one `watcher` plugin packaging and runtime surface. The consolidation replaces the old `doc-watcher` and `skill-watcher` plugin install entries rather than keeping both installed as long-term compatibility layers.

## Decision

The consolidated plugin should use `watcher` as its canonical plugin slug and own shared watcher helpers, validation, report-artifact conventions, and install/refresh integration. It should preserve distinct skill invocation boundaries for `doc-alignment`, `housekeeping`, `skill-maintainer`, and `skill-compressor`.

The old plugin slugs should not remain as separately installed plugins after the migration. The migration should instead provide explicit local migration scripts and Skill Watcher attribution legacy mappings so old names can still be interpreted in reports where needed.

Runtime state should move to a shared watcher root with domain subdirectories:

```text
$CODEX_HOME/watcher/
  skill/
  doc/
```

The `skill/` subtree owns skill usage logs, reports, proposals, transient turn state, schema markers, and skill metadata caches. The `doc/` subtree owns documentation audit reports, audit packs, repository state, and cockpit run records.

DocWatcher legacy patch generation, remote provider write flows, Doc PR services, and webhook PR update surfaces should not be migrated as active watcher surfaces. The watcher migration should carry only the current audit-first cockpit, read model, report runner scripts, and `doc-alignment`/`housekeeping` skills.

The consolidated source should expose one primary CLI entrypoint, `scripts/watcher`, with domain subcommands such as `skill` and `doc`. Existing script behavior may move behind this CLI as internal modules, but old plugin-specific top-level scripts should not remain long-term user entrypoints.

## Consequences

This is a packaging and runtime consolidation, not a semantic skill merger. The leading words and trigger boundaries for documentation alignment, housekeeping, skill maintenance, and skill compression remain separate because they represent different user intents and completion criteria.

Refresh and check tooling must move from two plugin entries to the consolidated plugin entry. Hook installation must point at the consolidated source path. Runtime state migration should be explicit and observable, with clear failure messages if old and new layouts are mixed.

Historical names such as `doc-watcher:*` and `skill-watcher:*` should be treated as legacy attribution names, not as active plugin package identities or active skill entrypoints.

The migration should move `$CODEX_HOME/skill-watcher/` to `$CODEX_HOME/watcher/skill/` and `$CODEX_HOME/doc-watcher/` to `$CODEX_HOME/watcher/doc/` explicitly. The consolidated plugin should not write new state to the old top-level watcher directories after migration.

Legacy attribution names are reporting and migration metadata only. They should let old logs, old reports, and residual context resolve to current `watcher:*` skill identities, but they should not keep old plugin slugs installed, expose duplicate skills, or preserve old source paths as supported runtime entrypoints.

Removing the legacy DocWatcher patch/PR/provider/webhook source during consolidation is acceptable when the ADR and current README record the audit-first product boundary. The private pre-rebuild archive retains those retired experiments; the clean repository does not contain that Git history.

A single CLI reduces wrapper duplication while preserving domain language. Report commands should stay domain-qualified, such as `watcher skill report` and `watcher doc report`, so skill usage reports and documentation audit reports do not collapse into an ambiguous flat command.
