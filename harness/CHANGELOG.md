# Changelog

## 1.1.0 - 2026-10-26

### Changed
- The engine is vendored into the ATM (ai-tool-manager) repository as its
  embedded harness distribution engine; ATM is now the single source of truth.
- `atm harness bootstrap` materializes this tree into the manager home as a
  non-Git distribution whose identity is its content hash; `atm harness sync`
  re-materializes after ATM upgrades and adopts legacy Git-mode installs.
- Embedded mode refuses `update`, `recover` and `repair --reclone` with
  guidance to upgrade ATM; recorded revisions are derived from the embedded
  content identity instead of Git history.
- The user-facing CLI surface is now `atm <verb> skills|hooks --harness …`
  (verb-first); `install.sh`/`install.ps1` and the `upgrade_*` wrappers are
  retired entry points.
- Full de-brand to the ATM identity: the product/marketplace name is
  `atm-harness`, the manager home default is `~/.atm` (env `ATM_HOME`), and
  engine environment variables use the `ATM_*` prefix
  (`ATM_HARNESS_ROOT`, `ATM_BOOTSTRAP_PYTHON`, …). The engine CLI script is
  `scripts/engine.py` (was `omh.py`) with `atm harness --` as its program
  name; state written by `oh-my-harness` versions is rejected.
- Embedded homes no longer write standalone launcher shims (`bin/omh`,
  `bin/oh-my-harness`) or register PATH entries; `atm` is the only CLI entry,
  and runtime venv rebuilds run through `atm harness bootstrap --rebuild`.


## Unreleased

- Prioritize declared, authorized SOP recovery before stopping on recoverable validation failures; keep explicit stops and report-only boundaries, and clarify that failed Goal gates pause dependent steps while authorized current-milestone repairs continue.
- Add an Oh My Pi agent distribution (`oh-my-pi`, input alias `omp`) projecting skills and a managed `AGENTS.md` into the native `~/.omp/agent` directory, sharing `PI_CODING_AGENT_DIR` with `pi-agent` under the existing shared-resource rule.
- Add an explicit OpenClaw skills-only distribution using the existing owned directory projection lifecycle, with state, profile and home overrides and isolated-home regression coverage.
- Keep public status, version, check, and doctor read-only and usable while a mutation lock is held; report degraded runtime failures without implicit repair.
- Preserve pure JSON stdout for status/version and move command/bootstrap diagnostics to stderr.
- Avoid creating or modifying manager locks during install, refresh, and remove dry-run previews.
- Cover installed launchers with isolated-home regression tests for JSON, broken runtimes, concurrent locks, and no-write previews.

## 1.0.0 — 2026-08-24

First formal release of `oh-my-harness`.

- Establish one registry-selected distribution across Codex, ZCode, Claude Code, Copilot CLI, Gemini CLI, and OpenCode.
- Provide the manager-owned `~/.oh-my-harness` installation, upgrade, recovery, launcher, and tooling-runtime contracts.
- Package the Watcher, Workflow, and unchanged Matt Pocock skill mirror through the local Codex marketplace.
- Harden interrupted-install recovery against linked manager roots, dirty or remote-drifted checkouts, and revision changes during refresh.
- Introduce content-derived plugin generations and a release-level distribution identity so equal versions cannot silently represent different plugin content.
- Make `omh` the post-bootstrap lifecycle manager with `install`, `refresh`, explicit `refresh --repair`, `remove`, and transactional `update`.
- Add rolling manager/desired/per-harness receipts, a cross-process mutation lock, update journaling and recovery, and manager repair/uninstall flows.
- Move public launchers to a manager-home bootstrap shim so tooling repair and exact checkout reconstruction remain available outside the managed repository.
