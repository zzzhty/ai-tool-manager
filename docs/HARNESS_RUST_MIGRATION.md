# Harness Rust migration verification

Implementation worktree: `codex/harness-rust-migration`, based on `df63e0c6bc4acb29d8df508b9f2b62c62b87fdda`. The checkpoints below record validation before merge and deployment. At those checkpoints, Home's original `main` checkout, installed ATM entry points, real harnesses, venvs, credentials and independent OMH work were unchanged. The user subsequently authorized committing, validating cross-platform CI, merging to `main` and distributing to Home's recorded targets; new hooks remain subject to separate confirmation. That authorization does not turn the isolated checks below into live deployment evidence.

## Four implementation stages

1. **Contracts and content split:** versioned distribution manifest, content locks, canonical catalog, runtime groups and Rust receipt; Watcher helpers under `runtimes/watcher`; four interactive workflows under `plugins/maintenance`. Stable `watcher:*` logging identities and historical aliases remain, logs are never rewritten.
2. **Rust static distribution:** verified source and immutable cache; recorded status, pure plans, apply, install/update/remove and physical target ownership. Empty-PATH tests exercise the actual CLI and complete offline cached content. CLI and desktop use the same service.
3. **Payload runtime and hooks:** Python is explicitly selected by dependency group, with absolute interpreter and final-path versioned venv; hashed dependencies and offline wheel-cache diagnostics. External venvs are read-only. Preparing a runtime does not enable hooks. Shared hook config merges preserve foreign groups and reject edits to owned entries. Watcher consumes Rust catalog JSON without importing the installer or scanning the repository.
4. **Adapters and handoff:** registry client adapters, settings-derived Gemini instructions, Codex native marketplace/cache and support files; explicit legacy proof/archive/retirement, journaled recovery and single owner. Retired Python engine/installer entry points are removed; portable packaging copies only the manifest inventory.

## Old test retirement and replacement

The old Python distributor is removed, so tests whose implementation under test was that distributor are retired with it. Their behavioral boundaries map to the Rust acceptance below. Payload and developer identity tests remain executable. Removing an implementation-specific test is not evidence that every old integration environment has been retested.

| Retired Python tests (`harness/tests/`) | Replacement and retained behavior |
| --- | --- |
| `test_atm_embed`, `test_engine_lifecycle`, `test_manager_environment`, `test_bootstrap_tooling_env` | `distribution_source`, `distribution_service`, `distribution_runtime` and CLI `rust_distribution_*`: source lock, cache drift, offline missing dependencies, runtime selection, no Python static lifecycle, final-path environments and failed preparation retention. Whole-tree Python materialization is intentionally retired. |
| `test_sync_agents_skills`, `test_sync_harness_instructions`, `test_instruction_materialization`, `test_sync_codex_agents` | `distribution_adapters`, `distribution_service`, `distribution_legacy`: exact file ownership, user-edit rejection, instruction shadow guards, shared config merge/restore, agent support and old link/copy evidence. New ordinary copies use exact byte hashes; they do not normalize arbitrary target edits. |
| `test_harness_registry`, `test_vscode_harness`, `test_openclaw_harness`, `test_oh_my_pi_harness`, `test_macos_codex_discovery`, `test_harness_name_migration`, `test_harness_name_transitions` | `tool_catalog` plus `distribution_adapters`: registry IDs/aliases/root overrides, every current driver, shared physical root rejection, OpenClaw skills-only behavior, Gemini setting validation. Persisted old names are handled only by explicit legacy proof. macOS discovery/path cases do not constitute macOS execution evidence. |
| `test_check_harness`, `test_check_harness_helpers`, `test_closure_phase_reuse`, `test_refresh_harness`, `test_refresh_harness_integration`, `test_manager_review_regressions` | `distribution_source`, `distribution_service`, `distribution_adapters`: full canonical source/package identities, drift diagnosis, stale/foreign file refusal, config observations and optimistic-plan revalidation. No live Codex subprocess is used by the new distributor. |
| `test_installer_recovery`, `test_installer_recovery_integration`, `test_manager_repair_resilience`, `test_install_oh_my_harness` | `distribution::transaction` unit tests and `distribution_legacy`: OS lock denial, hard-interruption states, tree staging/backup, rollback refusal on user edits, retained initial receipts/logs, explicit one-time source/ownership handoff and no dual owner. Global install/PATH mutation is retired. |
| `test_machine`, `test_manager_commands`, `test_lightweight_commands`, `test_public_launcher_contract`, `test_manager_paths`, `test_terminal_output` | Rust harness bridge tests and CLI tests: shared service, capability/confirmation guards, recorded status, explicit manager home, bounded grammar and rejection of retired raw Python protocol. Terminal rendering and Python launcher internals are retired. |
| `test_windows_plugin_retry` | The former Codex CLI copy/retry path is retired; Rust transaction uses platform file replacement and explicit error propagation. Synthetic Windows path/argv cases remain, but native Windows copy, locking, junction and interruption behavior is **not verified here**, and the prior external Codex copy bug is not claimed fixed. |
| Watcher Python hook install/uninstall-specific cases | `distribution_hooks` and legacy exact-hook retirement: repeat enable/disable, foreign config preservation, same-name conflict, edited owned entry rejection, explicit runtime verification and opt-in execution. Event/report/proposal/domain tests remain under `runtimes/watcher/tests`. |

Retained Python developer suites: 26 tests (`test_plugin_package_identity`, `test_repo_skill_catalog`, `test_validate_plugin`, `test_retro_contract`). Retained payload suites: Watcher 66, maintenance 11, workflow 96. The package generation oracle is retained; plugin identities were regenerated after content tests and then checked. Source sealing is a separate Rust step.

## Evidence and limits

All execution in this change used Linux and disposable homes. Rust core/CLI/service tests, frontend TypeScript/Vitest/Vite, native Linux development and optimized release builds were run separately; counts and package evidence are recorded below. A real compiled CLI also boots with empty PATH and consumes a copied complete cache after its original source is removed. A Python `-S -B` observer consumes that Rust-generated catalog and resolves current and historical maintenance names to the stable old identity. No actual hook is enabled on the user's machine.

Runtime provisioning tests use fake interpreter/pip processes. These validate argv, locks, dependency verification and failure/reference behavior, not successful installation of every real package on every platform. The initial archive smoke used a synthetic CLI-only archive. The subsequent complete release-package checkpoint below supersedes that packaging limitation: both release binaries and the allowlisted payload were packaged, extracted and checked together. The desktop check inspects embedded resources before GUI/storage initialization; no interactive GUI was launched, and no release was published.

Windows/macOS native builds and execution, real clients, real hook execution, real external venvs and clean-Git legacy source handoff remain unverified. Legacy partial/degraded state, pending old journal, user-edited/unrecognized hooks, mismatched target roots and Git-bound Codex marketplace settings fail closed. Cache/runtime versions are retained conservatively; automated garbage collection is outside this change. These refusals never invoke a hidden Python fallback.

The supplied independent OMH commit `e0ce46da5e1cbca5313a6db14401cdfa07b4d5a7` was absent from the local independent clone; no fetch or independent repo edit was performed. Existing report evidence semantics and tests were preserved; this is not a claim of having compared that commit.

## Initial full Linux gate

- `CARGO_HOME="$PWD/.validation-cache/cargo" scripts/Verify-Local.sh`: PASS — Rust **257 passed, 1 ignored** (existing live Secret Service gate), frontend **89**, Python developer/payload **199** (26 + 66 + 11 + 96), formatting, scoped Clippy and source audit **366 readable source files**. The prior optional Python gate still required retired `jsonschema`; that obsolete dependency was removed, and all retained Python suites now run.
- `cargo clippy --locked --offline --workspace --all-targets -- -D warnings`: PASS, including native desktop compilation.
- `cargo build --locked --offline -p atm -p atm-cli`: PASS, native Linux development binaries. Missing global-cache crate `rfd` was supplied from a copy of the already-existing Home validation cache, without network or changes to the original cache.
- Extracted synthetic CLI-only archive: PASS with empty PATH, complete offline cache, both ZCode and Codex lifecycle, and user-file/config preservation. The later complete release check is recorded below.
- Source verification: **179 payload files / 30 skills**, identity `39e162a3285c2074f64f0d650e93930ed2335bf37f89b6684e78e776452b4d18`. Canonical plugin generation check passes.
- Final independent review found no remaining concern in its requested scope after regressions for empty-directory population, foreign-file permissions, Codex cache extras and Windows path identity comparisons. Synthetic path tests do not replace native Windows execution.

An intermediate run of the existing vault lock test reported `VAULT_BUSY` after dropping its test vault. Its isolated rerun and subsequent full final gate passed; no credentials/storage-domain code was changed.

Logs are retained locally under `artifacts/harness-rust-migration/` (ignored build evidence). At this initial checkpoint all source changes were uncommitted on the isolated branch, and the original Home checkout was clean at the starting HEAD. No real hooks, installations, venvs, credentials or network settings had been changed; no deployment, entry-point refresh, commit, push or PR had been performed.

## Ignored test and bounded legacy limitation

The one ignored test is `crates/atm-core/tests/secret_service_ci.rs::isolated_secret_service_lifecycle`.
Its `#[ignore]` reason is **“CI-only: requires isolated HOME, D-Bus and TEST_ONLY keyring”**.
It initializes a real Secret Service item, locks the test collection, restarts the test daemon
and reopens encrypted test state. It requires `CI=true`, `ATM_ISOLATED_KEYRING_TEST=1`,
a private `ATM_TEST_ROOT`, a matching isolated HOME and a dedicated D-Bus session.
Those prerequisites were deliberately not established for the harness migration; running
it against the user's session would violate the task boundary. It remains a separate
`Test-LinuxKeyring.sh` CI gate. Its ignored result is neither a pass nor a failure of
Python-free skill distribution, and this change does not modify that storage domain.

Git **repository source evidence** and a Git **Codex marketplace configuration binding**
are different contracts. Legacy source inspection can recognize a clean, pinned Git
checkout by matching HEAD, recorded origin and working-tree cleanliness; this route
has not been exercised in the present Linux migration run. Codex ownership import is
currently implemented only for an exact local marketplace table (`source_type = "local"`,
source equal to the verified legacy repository) and exact enabled plugin tables.
A table with `source_type = "git"` is explicitly unsupported, even if the local checkout
or installed plugin files appear equivalent. Additional or edited fields also refuse
ownership rather than being silently adopted.

The Git-bound case now returns `HARNESS_LEGACY_MARKETPLACE_UNSUPPORTED`. A service-level
regression confirms that this failure leaves the old manager state, immutable initial
receipt, engine entry point and Codex config intact, creates no Rust receipt and does
not archive/retire the old owner. Source-cache preparation may already have occurred;
that cache alone is not successful ownership handoff. There is no Python fallback.

The bounded next step is to inventory the actual old Codex Git source/ref metadata,
define how it proves the exact installed commit and canonical package identities, then
add offline fixtures and an explicit journaled ownership conversion. Merely changing
`source_type` to local or inferring equality from a branch name is not that proof.
No support for this path, no remote fetch and no real configuration migration is claimed
by the current implementation or by the release-package checks below.

## Complete Linux release-package checkpoint

The repository's documented packaging sequence completed offline on Linux x86_64:

```sh
npm run build
CARGO_HOME="$PWD/.validation-cache/cargo" cargo build --locked --offline --release -p atm -p atm-cli
python3 scripts/Package-Release.py --output artifacts/harness-rust-migration/ai-tooling-manager-linux-x86_64
python3 scripts/Test-Distribution.py artifacts/harness-rust-migration/ai-tooling-manager-linux-x86_64.tar.gz
```

The generated archive is **7,943,102 bytes**, SHA-256
`52d5cf93c1af5b57f107e9308d26c51d3838079538577eceb0ebe5a4119380c2`.
It contains the optimized `atm` and `atm-desktop` binaries, license/readme and exactly
the manifest plus **179 payload files / 30 skills**. No complete repository scripts
or tests tree and no Python distribution engine are included. Source identity remains
`39e162a3285c2074f64f0d650e93930ed2335bf37f89b6684e78e776452b4d18`.

The extracted-package check passed in a disposable Unicode/space-containing directory
with empty PATH, fake HOME/XDG/ATM_HOME and no display/session environment:

- Desktop `--verify-distribution` proves the release build embeds nonempty HTML and
  its referenced JS/CSS, and resolves the same adjacent verified payload as the CLI.
  It exits before creating a window, vault, keyring connection or application state.
- CLI bootstrap, read-only status/plan, ZCode and native Codex install/update/check/
  uninstall, explicit sync and user-file/config preservation all pass. After removing
  the adjacent source, static operations use the complete verified cache; explicit
  CLI/desktop source probes fail with `HARNESS_SOURCE_MISSING`, proving no release
  fallback to the build checkout.
- The Rust-generated catalog resolves every packaged skill and attribution overlay.
  Declared dependency locks and Python scripts are present and parseable; packaged
  Watcher observes current/historical aliases via the runner's explicit Python
  without writing files, preparing a venv or enabling hooks. The distributor's PATH
  remains empty throughout. Dependency wheel downloads/real venv preparation are
  outside this check and are not claimed.
- Affected adapter/handoff regressions: **25 passed** (10 adapter + 15 legacy),
  including the explicit unsupported Git-marketplace error with old ownership intact.
  This is a scoped rerun after the initial full gate, not a second full-suite count.

Evidence is retained in `artifacts/harness-rust-migration/`:
`release-frontend-build.log`, `release-build-linux.log`, `release-package.log`,
`release-extracted-smoke.log`, `release-handoff-regression.log`, and
`release-final-checks.log`. Native Windows/macOS package execution, interactive Linux
GUI rendering and live client/hooks remain unverified. No environment blocker remained
for this Linux package check. The archive is a local validation artifact, not a deployment.

## Commit preparation

The staged-file whitespace check found two trailing blank lines in the moved Watcher
hook classifier. Removing them changed payload bytes without changing behavior.
All 66 Watcher tests passed again, and Rust resealed the 179-file/30-skill payload as
`a5eaf17fea5943034e29733ba5e82616b508a9e879e9c41c27c19176cc461b48`.
The earlier package hash and source identity above remain evidence for that earlier
checkpoint; cross-platform CI and deployment must validate the committed identity.
