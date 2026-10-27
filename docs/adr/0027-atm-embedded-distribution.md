# 0027: Make ATM the embedded distribution owner

Status: accepted for the authorized AI Tooling Manager stages 1–3, 2026-10-26.

The repository and current package branding become `ai-tooling-manager`; CLI
`atm`, `ATM_HOME`, manager homes, receipt schemas, plugin names and historical
records remain stable. The user's vault is empty, so OS protection identities
are replaced directly; this does not authorize discarding harness state or
user configuration. Old nonempty encrypted vaults are outside this transition.

## Complete engine identity

The plugin generation ledger cannot detect an engine-only scripts/registry/agents
change. Comparing that ledger with a marker also misses installed-tree drift.
Both gaps were reproduced. The owning materializer therefore records one
`engineIdentity` using `atm-engine-content-v1`: sorted regular-file paths and
length-delimited bytes, excluding Git metadata, Python caches, venv and its own
marker. Links are rejected. Empty directories and file timestamps are not part
of this content contract. `embeddedIdentity` and `bundleIdentity` retain the
existing plugin contract; plugin generations are neither replaced nor rebased.

Sync stages and verifies the package, keeps the old repo and rolling state in
`state/repair-backups/sync-*`, swaps the repo, then commits manager state. An
ordinary exception restores the old repo and state together. A hard interruption
retains the named recovery backup; it is not claimed to be an atomic transaction
or automatically resumed. Historical install receipts, desired state, per-harness
receipts, local skill registries/projections and target configuration are preserved.
Known `oh-my-harness` product state is accepted only by explicit ATM sync; normal
state readers keep their strict product validation. New state is `atm-harness`.

Full content checks belong to materialization and embedded execution validation.
Ordinary recorded status stays lightweight. Portable releases ship CLI, desktop
and adjacent `harness/`; a release executable has no build-checkout fallback.
Python 3.11+ and first-bootstrap dependency installation remain explicit prerequisites.

## Shared application boundary

`.agents/harnesses/registry.json` owns tool IDs, aliases and root rules. Rust builds
its local tool catalog from that source without requiring Python at runtime.
Optional `localSkillsPath` describes Codex's native local-skills surface separately
from its engine marketplace driver. Old receipt IDs remain readable. Aliases and
tools sharing a physical target may not establish competing local ownership.

`atm-core::application` owns configuration/template/preview and usage services.
The desktop adapter owns IPC authorization, native dialogs and windows.
Configuration opens lazily; failure blocks configuration editing while independent
skills, harness and Codex queries remain usable. Schema checks, preview confirmation,
one-use previews and encrypted metadata formats retain their prior contracts.

## Acceptance and rollback

Synthetic tests cover actual old-product adoption, engine-only upgrades, drift,
failed state commit restoration, receipt/config preservation, alias ownership,
schema enforcement and vault failure isolation. Each native package is extracted
outside the checkout and exercises bootstrap, installation, sync and reapplication.
Rollback uses the prior program package and the matching named engine/state backup;
restoring a package alone does not restore rolling state. No test uses real accounts,
keys, installed harnesses or user configuration.
