# OMH content contract

Status: accepted, 2026-10-27. This is the import/export contract for the authorized
OMH Hub transition. Installation continues to use the existing Rust service.

## Decision and ownership

OMH authors skills, optional script runtimes, compositions and versions. ATM owns
target policy, acquisition, plans, receipts, runtime preparation and recovery.
`policy/harnesses/registry.json` is compiled into ATM; supplier content cannot
replace it. `content-manifest.json` declares internal content only, never host
paths, install commands, credentials or hook activation.

`atm harness export` exports one complete composition from a reviewed checkout.
The current composition contains whole native plugins; partial plugin exports are
rejected. The resulting `.omh` file is a bounded JSON data archive with base64
file bodies. It has no links, executable installation metadata or extraction
commands. `content-lock.json` independently pins the supplier repository, immutable
revision, release asset URL, composition, manifest and files. The installation
receipt remains `state/distribution.json`; importing never writes that receipt.

`atm harness import --lock /absolute/content.lock.json [--archive /absolute/content.omh]`
creates an inactive verified cache. `atm harness fetch --lock /absolute/content.lock.json
--output /absolute/payload` prepares a portable payload without a manager receipt.
Downloads use only the reviewed lock's HTTPS GitHub release URL, with bounded
GitHub asset redirects, size limits and digest verification. Complete verified
caches work offline. Neither operation runs Python, client commands or scripts.
The selected source changes only through explicit bootstrap/sync and target apply.

## Validation and identity

The existing package identity algorithm remains `sha256-canonical-plugin-tree-v1`.
The new `sha256-omh-content-v1` contract hashes canonical JSON lock fields (sorted
keys, UTF-8, no whitespace), excluding `contentIdentity` and `archiveSha256`,
prefixed by the algorithm and NUL, then an eight-byte big-endian length record.
The separate archive digest pins transport bytes. This identity gate is owned by
the content cache: semantic catalog checks alone cannot detect altered script
bodies or injected files from a remote archive. Existing file normalization,
size limits, portable paths, plugin identity and catalog validation are reused.

Unknown manifest/archive fields, unsupported schemas, traversal, case collisions,
links, reparse points, injected cache files and native hook/MCP/command declarations
are rejected. Skill-watcher collection remains retired. The private import stage
is published with an exclusive rename; an existing destination is either verified
as exactly the selected content or left intact. A crash before publication may
leave an inactive `.omh-import-*` stage; it is never an owner or an install source.
Export refuses existing outputs; an interrupted export may leave an incomplete
archive/lock pair that cannot be imported until explicitly regenerated elsewhere.

## Identifier and compatibility inventory

| Surface | Classification and treatment |
| --- | --- |
| ATM registry build and adapter readers | Current internal authority moves together to `policy/harnesses/`; supplier registry is ignored. Legacy payload copies remain byte-identical for old cache identities. |
| `distribution-manifest.json`, receipt schema 1, journal | Persisted contracts: keep existing readers, algorithms and recovery. Hub metadata uses separate version-1 schemas; reject ambiguous dual manifests. |
| `content-manifest.json`, `content-lock.json`, `.omh` | New cross-repository version-1 contracts. The strict Rust implementation is shared by export, import and package verification. |
| Plugin versions, catalog schema 1, historical `watcher:*` IDs | Preserve semantics and existing validation. Imported content does not establish execution evidence. |
| `~/.oh-my-harness` | Persisted installation state; this contract does not move it. A separate explicit journaled handoff must preserve backups and rebuild final-path runtimes. |

Rollback before installation is selecting the earlier locked source. Rollback
after installation uses an explicit service plan and retained receipt/cache;
changing a Git lock alone does not undo client files. This first change retains
the current bundled authoring tree until OMH publishes its validated content
release. A later ATM change pins that release and removes the vendored source.

## Verification mapping

`distribution_hub` covers inert export/import, offline reuse, user-file protection,
unknown capabilities, archive tampering/traversal/duplicates and cache injection.
`distribution_adapters` proves supplier registries cannot redirect local targets.
CLI tests run export/import/static install with empty PATH. Existing source,
receipt, transaction/recovery, runtime, native-platform and portable-package gates
continue to apply; old migration CI does not count as evidence for these changes.
