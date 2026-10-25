# Internal Identifier Evolution

Use this policy before renaming, replacing, or migrating a repository-owned identifier, path, field, event, skill, instruction, or fingerprint semantic.

## Classification Gate

Classify every scoped match before editing:

| Identity class | Required treatment |
| --- | --- |
| Current, repository-owned, repo-local, non-public, non-persisted, and atomically replaceable across every consumer | Use one stable semantic name. Replace every current consumer in one change without aliases, dual reads or writes, fallbacks, duplicate paths, parallel authorities, or generation labels. |
| Package or release, standard or protocol, public API, migration or feature flag, milestone or phase, user or business term, immutable record, persisted state or contract, archival evidence, historical identity, or cross-repository consumer | Preserve the identity until an explicit migration inventories consumers and data, defines compatibility impact, validation, and rollback, and receives scoped authorization. |

An ambiguous match belongs to the preserved class until evidence proves it satisfies every condition in the first row.

## Execution Contract

1. Inventory the bounded consumers and record the classification for each match.
2. Stop before a repository-wide regex or bulk rename, a silent rebaseline, or any public, persisted, external, archival, or historical identity change that lacks explicit migration authority.
3. For an eligible internal identity, change the owning source and every affected current consumer atomically. Git history and an applicable checkpoint or validation ledger carry revision history.
4. Preserve archives and historical evidence. Do not rewrite them to make the present look consistent.
5. If a canonical algorithm, fingerprint field, payload, or semantic changes, record what it replaces, regenerate the expected value from the changed source, and validate the single current value against its oracle.

Completion requires every inventoried current consumer to use the one canonical identity, every preserved match to remain unchanged, and the smallest affected-surface checks to pass without compatibility scaffolding or silent rebaselining.
