# ATM Harness content and optional runtimes

ATM's Rust `atm-core::distribution::Service` owns distribution. The CLI and GUI
share that service. This tree supplies verified content, registry metadata and
optional Python payload helpers; no Python installer or whole-repository scanner
is needed to install, update, remove or inspect static skills.

## Install and maintain content

```sh
atm harness bootstrap
atm harness plan install --harness zcode
atm install skills --harness zcode
atm check skills --harness zcode
atm update skills --harness zcode --dry-run
atm update skills --harness zcode
atm uninstall skills --harness zcode
atm harness status --json
```

`ATM_HOME` selects an absolute manager home (default `~/.atm`). Tool roots and
input aliases come from `.agents/harnesses/registry.json`. Registered tools are
Codex, ZCode, Claude Code, Copilot CLI, VS Code, Gemini CLI, OpenCode, OpenClaw,
Pi Agent and Oh My Pi. OpenClaw receives skills only. Multiple logical names
cannot establish separate owners for the same physical target.

Bootstrap validates `distribution-manifest.json`, content hashes and plugin
identities, then generates `canonical-catalog.json` in the immutable content
cache. A complete cache supports the static lifecycle offline. Missing or changed
content is an error; it never falls back to a Python engine or downloads code.
After an ATM package upgrade, run `atm harness sync`, then reapply the intended
targets. `ATM_ENGINE_SOURCE` is an explicit absolute payload source override.
Release binaries otherwise read the adjacent `harness/`, never a build checkout.

Plans are reviewable and apply revalidates their observations. Receipt ownership
protects user edits and unmanaged same-name entries. Cross-file operations use a
journal; they are not completely atomic. An interrupted operation blocks new
mutation until `atm harness recover`. Changed recovery targets are preserved and
reported instead of overwritten. Uninstall preserves logs, reports and user files.

## Python is a payload requirement

Installing static content does not create a shared Python tooling environment.
Only a selected Python skill or hook needs its declared runtime. Prepare that
group with an explicit interpreter:

```sh
atm harness runtime prepare workflow --python /absolute/path/to/python3 --offline
atm harness runtime prepare maintenance --python /absolute/path/to/python3 --offline
atm harness runtime prepare watcher --python /absolute/path/to/python3 --offline
# Explicit external environment: validate it without installing or changing packages.
atm harness runtime prepare watcher --python /absolute/path/to/python3 --external-venv /absolute/path/to/existing-venv --offline
```

The returned `prepared.python` is the interpreter to use for that group's scripts.
On Windows supply the absolute `python.exe` path, including spaces/Unicode as one
quoted argument. No `activate` command is used. Missing Python gives a diagnostic;
ATM does not download interpreters. Dependency-bearing groups use exact versions
and hashes. Offline mode uses `<ATM_HOME>/cache/wheels` and fails if a needed locked
wheel is absent. Group and content versions get separate environments created and
checked at their final paths; failed preparation keeps the prior valid reference.
Project `.venv`, global Python and explicit external environments are not modified.

Current groups are `workflow`, `maintenance`, `watcher` (stdlib helpers) and
`maintenance-validation` (locked PyYAML for skill candidate validation). Runtime
bindings in the manifest identify which payload needs each group.

## Watcher and maintenance workflows

`runtimes/watcher/` contains collection, event handling, reporting and audit helpers.
It has no callable skill entry. Its catalog loader reads the versioned Rust
snapshot, including stable identities, source paths and attribution overlays.
It does not import `scripts/repo_skill_catalog.py` or scan the original repository.

`plugins/maintenance/` retains the interactive `doc-alignment`, `housekeeping`,
`skill-maintainer` and `skill-compressor` workflows. Their historical
`watcher:<name>` identities remain in the catalog mapping so existing evidence
stays readable. User logs are not rewritten. Workflow and Matt Pocock skills remain
separate packages with their own attribution.

Runtime preparation does not authorize hook execution. Activation is explicit:

```sh
atm install hooks --harness codex --dry-run
atm install hooks --harness codex
atm check hooks --harness codex
atm uninstall hooks --harness codex --dry-run
atm uninstall hooks --harness codex
```

Rust merges only owned hook entries and preserves unrelated configuration.
Repeated enable/disable is idempotent; edited owned entries cause a conflict.
Disabling hooks does not delete logs, reports or retained runtime environments.

## One-time legacy handoff

Normal bootstrap/sync refuse a legacy Python installation. Use `atm harness adopt`
only for an explicit handoff. The Rust migration validates old state, source and
ownership, preserves historical evidence, then replaces the active ownership in a
journaled transition. It never rewrites user logs or runs the old distributor.
Unsupported or ambiguous legacy state stops with evidence intact. There is no
long-lived dual engine or automatic fallback. The former raw Python `machine`
transport and arbitrary `harness --` passthrough are retired.

## Contributor checks

Read [AGENTS.md](AGENTS.md) and the identifier-evolution policy before changing
persisted identities. Historical ADRs describe past designs, not executable
fallback instructions. The current Rust service boundary is described in
[the interface notes](docs/machine-interface.md).

```sh
cargo fmt --all --check
cargo clippy --locked --offline -p atm-core -p atm-cli --all-targets -- -D warnings
cargo test --locked --offline -p atm-core -p atm-cli --all-targets
# Run from harness/; Python here is a development/test dependency.
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover -s runtimes/watcher/tests -p 'test_*.py'
python3 -m unittest discover -s plugins/maintenance/tests -p 'test_*.py'
python3 -m unittest discover -s plugins/workflow/tests -p 'test_*.py'
python3 scripts/check_plugin_generations.py
```

Finish all plugin source edits and owning tests before running
`scripts/update_plugin_generations.py` once. Then seal the explicit distribution
manifest from the ATM root using
`cargo run --locked --offline -p atm-core --example seal_distribution -- /absolute/path/to/harness`,
then run `atm harness verify-source`.
Package generation copies only manifest files/directories and revalidates them
with the native CLI. Root `scripts/Test-Distribution.py` exercises the extracted
package with an empty PATH and a disposable user home. Native Windows/macOS
behavior and real client integrations require separate platform evidence.
