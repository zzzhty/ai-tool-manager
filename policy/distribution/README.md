# Rust distribution contracts

New OMH content uses separate manifest and version-lock schemas described in
[the content contract](../../docs/OMH_CONTENT_CONTRACT.md). These schemas preserve
legacy cache, catalog, runtime and receipt compatibility; they are owned by ATM.

Legacy cached bundles use `distribution-manifest.json` schema 1. It locks the
release and every deployable file by portable relative path and SHA-256.
`sha256-atm-distribution-v1` canonicalizes UTF-8 text without NUL from CRLF to
LF; binary bytes stay exact. Its bundle identity hashes the algorithm plus NUL,
then length-prefixed canonical JSON manifest, followed by sorted path/bytes
records. Lengths are unsigned big-endian 64-bit. It excludes its own file from
the file inventory and includes the complete manifest in the identity.

`source::seal` is an explicit developer/package operation after owning tests and
plugin generation. Install/update/load never reseal or accept drift. The trusted
release or explicit local source authorizes content; hashes detect drift and pin
subsequent cache use, and do not claim publisher signature verification.

Only selected canonical plugin trees, registry, instructions and declared
runtime packages are eligible. Plugin tests/docs remain payload content to
preserve `sha256-canonical-plugin-tree-v1`; Rust verifies that complete identity
and ledger. The manifest records directories as well as files, preserving empty
directories covered by the plugin contract. Installer scripts, entire repository
trees, runtime-package tests and venvs are excluded.
Unlisted files are neither executed nor distributed. Symlinks, junctions,
reparse points, nonregular files, unsafe paths and case collisions fail closed.
No network or interpreter is needed to load a text-only distribution.

`canonical-catalog.json` schema 1 has product `atm-harness-catalog`, a 64-hex
`sourceIdentity`, `skills` and `attributionOverlays`. Each skill has stable `id`,
current `plugin`, frontmatter `name`, `directoryName`, payload-relative directory
`path` and qualified `aliases`. Each overlay is `{plugin,path,data}` containing
its exact validated attribution JSON. Rust builds this snapshot from verified
content. Watcher consumes the snapshot; it never imports the Python installer
or scans the full repository.

`historicalIdentities` maps current `maintenance:name` identities to durable
`watcher:name` event identities for the four retained interactive workflows.
This mapping preserves old logs and attribution without rewriting events or
creating duplicate callable skill entries. Historical ADRs and records remain
unchanged. `runtimeBindings` maps selected payload identities to an optional
`runtimeGroups` declaration; content import alone does not prepare environments
or authorize hook execution.

Runtime groups declare `id`, `minimumPython`, optional `requirementsLock` and
`imports`. Every lock file is itself part of the verified inventory. Runtime
preparation validates exact pins and hashes; no lock or dependency resolution
is inferred from arbitrary package contents. Interpreter and external venv
selection are explicit service inputs, not source-controlled executable paths.

`receipt.schema.json` describes the Rust receipt authority at
`state/distribution.json`, including per-client source/release identity, exact
managed-file hashes, explicit empty directories, shared-field ownership, runtime
references and one-time legacy evidence. A Rust integration test validates written
receipts against it. `runtime.schema.json` describes optional Python runtime groups;
Rust additionally validates portable paths, import names and hashed lock grammar.
The existing transaction journal uses schema 2 with a unique transaction
ID and exact before/after nodes; it is recovery evidence, not a second owner.
