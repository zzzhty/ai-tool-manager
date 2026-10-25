# Break Skill Watcher usage events into the new skill attribution schema

Skill Watcher usage events will move directly to the new attribution model instead of preserving compatibility with the old single-`skill_name` event shape. We accept a breaking migration because the old data model cannot represent supporting skills or effective skill usage, and keeping compatibility fields would preserve the misleading primary-only interpretation we are trying to remove.

## Consequences

Existing reports and historical JSONL data may be discarded, regenerated, or treated as pre-migration evidence only. New hook output and report code should use the new schema as the source of truth rather than maintaining parallel old-field semantics.

The migration should be explicit: archive the old `events.jsonl`, reset turn state, regenerate monitored skill metadata, and write a schema-version marker. Hooks should fail clearly on schema mismatch instead of silently mixing old and new event structures.

Installed plugin metadata is part of the runtime contract. Validation and `SessionStart` should fail visibly when a manifest references missing skills or invalid dependency entries, because silently dropping those relationships would make effective usage counts untrustworthy.

For upstream-synced skill packages such as `mattpocock-skills`, this work should add incremental metadata indexes rather than changing skill behavior text. Skill Watcher can consume canonical names, typed aliases, roles, and dependency relationships from plugin-owned metadata, but it should not require editing the upstream skill instructions themselves to make reporting accurate.

## Later decision

[ADR 0012](0012-maintain-a-local-mattpocock-selection.md) supersedes the Matt upstream-mirror ownership/version exception. The historical reasoning above remains recorded; current Matt skills are locally maintained.
