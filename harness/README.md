# ATM Harness

> **This tree is now vendored into [ATM (ai-tooling-manager)](https://github.com/zzzhty/ai-tooling-manager)**
> as its embedded harness distribution engine. ATM is the single source of truth;
> the standalone repository and `install.sh` / `omh update` flows are retired.
> Terminal entry point: `atm harness bootstrap` (materialize + venv), then the
> verb-first grammar `atm install/update/uninstall/check/repair skills --harness …`.
> The engine's own commands remain documented below in `atm harness -- …`
> form, reachable through that escape hatch or inside the materialized
> `<home>/repo`.

> This repository starts from a reviewed source snapshot with new Git ancestry. Existing
> installations do not have a transparent fast-forward upgrade path. Read
> [clean rebuild boundaries](docs/clean-rebuild.md) before installing, updating or repairing.
> Pre-rebuild tags, PRs, CI results and artifacts remain in the private archive.

Registry-managed distribution of personal development skills and global instructions across coding harnesses, including the local Codex marketplace.

This repository is the development mainline for the plugins and personal Codex configuration listed below. Edit the source copies here, then reinstall or refresh the Codex plugin cache when a change should be available to new Codex sessions.

`agents/global-instructions.md` is the registry-selected global instructions source. Root `AGENTS.md` contains only repository-local routing and is not distributed to harness-global targets.

## Quick Start

Install your coding client separately. ATM Harness adds skills and global
instructions to it; it does not install Copilot, Claude Code, or the other apps.

From an ATM checkout with the vendored engine:

```bash
atm harness bootstrap            # materialize the embedded engine + venv (first run fetches Python deps)
atm harness status               # recorded-state snapshot
atm harness -- install vscode --dry-run        # preview with the engine escape hatch
atm install skills --harness vscode             # apply (interactive confirmations stay native)
```

Legacy Git-mode installs are adopted by `atm harness sync`; `atm harness -- update`,
`atm harness -- recover` and `repair --reclone` are refused in embedded mode because
upgrades now arrive with ATM releases.
After setup, use `atm harness --` for everyday engine work:

```bash
atm harness -- install claude gemini --dry-run  # Preview adding more harnesses
atm harness -- install claude gemini           # Apply after reviewing the preview
atm harness -- refresh                        # Reapply the installed version
atm harness sync                             # Sync the engine shipped by the upgraded ATM
atm update skills --harness vscode            # Reapply the selected distribution
atm harness -- check                          # Check installed skills and instructions
atm harness -- remove copilot --dry-run       # Preview removing managed Copilot resources
```

Use `atm harness -- --help` for an overview and `atm harness -- COMMAND --help` for defaults,
options, and examples. `copilot-cli` and `gemini-cli` are canonical harness names;
`copilot` and `gemini` are their short aliases. Aliases work in setup, install,
refresh, repair, check, doctor, and remove.

## Plugins

- `watcher`: observes Codex skill usage, audits documentation drift, and packages `doc-alignment`, `housekeeping`, `skill-maintainer`, and `skill-compressor` workflows.
- `workflow`: packages reusable workflow skills, including continuation-ready long-running goal plans with frozen YOLO non-stops and runtime hard stops, SOP execution harnesses, prompt/strategy loops, explicit subagent orchestration, and standalone summaries.
- `mattpocock-skills`: packages 20 locally maintained engineering skills derived from `mattpocock/skills`, with upstream attribution and native Codex metadata.

The old `plugins/doc-watcher` and `plugins/skill-watcher` source trees were removed after the Watcher migration. The private pre-rebuild archive retains those retired plugin sources; restoring one requires a separate scope review.

## Harness Distributions

`plugins/*/skills/*/SKILL.md` is the canonical skill catalog. The frontmatter `name` is the bare catalog name even when a physical directory has a different name; marketplace state, plugin caches, and user-level directories are projections, not source authority.

Each harness target selects one registry-declared distribution, including an
explicit skills-only capability where the client owns its instructions. Public commands accept
`HARNESS...`; the lower-level helpers accept `--harness`. The strict JSON authority is `.agents/harnesses/registry.json`, validated by `.agents/harnesses/registry.schema.json` and `scripts/harness_registry.py`. The registry owns canonical names, aliases, root resolution, the skills driver, global instructions, platform materialization, reconciliation, excluded skill roots, and optional runtime extras. The default is `codex`.

| Canonical harness | Alias | Skills | Global instructions |
| --- | --- | --- | --- |
| `codex` | — | Exact `.agents/plugins/install-manifest.json` package set through Codex marketplace install | `$CODEX_HOME/AGENTS.md` |
| `zcode` | — | `~/.zcode/skills` projection | `~/.zcode/AGENTS.md` |
| `claude-code` | `claude` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` projection | `${CLAUDE_CONFIG_DIR:-~/.claude}/CLAUDE.md` |
| `copilot-cli` | `copilot` | `${COPILOT_HOME:-~/.copilot}/skills` projection | `${COPILOT_HOME:-~/.copilot}/copilot-instructions.md` |
| `vscode` | — | `~/.copilot/skills` projection | `~/.copilot/copilot-instructions.md` (Copilot Agent Host; see below) |
| `gemini-cli` | `gemini` | `${GEMINI_CLI_HOME:-$HOME}/.gemini/skills` projection | configured `context.fileName`, otherwise `GEMINI.md` |
| `opencode` | — | `~/.config/opencode/skills` projection | `~/.config/opencode/AGENTS.md` |
| `openclaw` | — | `<state-dir>/skills` projection (default `~/.openclaw/skills`) | None; skills only |
| `pi-agent` | `pi` | `${PI_CODING_AGENT_DIR:-~/.pi/agent}/skills` projection | `${PI_CODING_AGENT_DIR:-~/.pi/agent}/AGENTS.md` |
| `oh-my-pi` | `omp` | `${PI_CODING_AGENT_DIR:-~/.omp/agent}/skills` projection | `${PI_CODING_AGENT_DIR:-~/.omp/agent}/AGENTS.md` |

Aliases are exact lowercase input names declared once in the registry. They
resolve to the canonical ID before selecting paths or writing state. For example,
`atm harness -- install copilot copilot-cli` installs one distribution and records only
`copilot-cli`. `--all` also selects each distribution once. The short names still
select the GitHub Copilot CLI and Gemini CLI distributions; their native
directories, environment variables, and instruction filenames are unchanged.

`vscode` selects **VS Code (GitHub Copilot)** independently of `copilot-cli`
(GitHub Copilot CLI). Use `atm harness -- install vscode`, `atm harness -- check vscode`, or
`atm harness -- remove vscode` without having to choose a CLI you do not use. Selecting
both records two consumers, even though their default skill and instruction
resources share `~/.copilot`. Removing one retains each resource still used by
the other; removing the last consumer performs the existing ownership-checked
cleanup. Bulk remove, dry runs, and manager uninstall follow the same rule.
Changed/unmanaged files remain protected. If the environment no longer resolves
a relevant recorded root, removal asks you to restore that configuration first.
If another client's dynamic instruction configuration cannot be inspected,
removal warns and retains the potentially shared instruction file while still
removing unrelated managed skills and the selected client's logical state. This
can leave a safe residual instruction file; it is not complete physical cleanup.

VS Code discovers personal skills under `~/.copilot/skills`. The
`copilot-instructions.md` global file is supported by **Copilot Agent Host**;
VS Code local-agent user instructions are profile-managed and are not installed
by this target. Select/configure the appropriate agent and profile in VS Code;
`atm harness -- check vscode` checks the managed files, not whether every VS Code agent
mode loads them. See the official [agent skills][vscode-skills] and
[custom instructions][vscode-instructions] documentation.

`COPILOT_HOME` remains a **CLI-only** override in this registry. The `vscode`
target uses the current user's `~/.copilot`; it does not assume VS Code honors
that CLI variable. This root is the present skills/instructions distribution
location, not a universal VS Code settings directory. MCP is not managed today.
A future MCP feature must resolve VS Code's own user/profile configuration
separately from Copilot CLI's configuration; sharing these two resources does
not merge client identity or imply that MCP or other settings share paths.

[vscode-skills]: https://code.visualstudio.com/docs/agent-customization/agent-skills
[vscode-instructions]: https://code.visualstudio.com/docs/agent-customization/custom-instructions

Existing desired state may contain the old names or both spellings. The manager
normalizes and deduplicates them in memory, then persists canonical names during
a successful normal lifecycle mutation. New per-harness receipts use canonical
names; obsolete alias-named receipts are removed only after ownership validation.
`status`, `check`, `doctor`, `update --check`, and dry runs do not rewrite state to
migrate names. The immutable initial `state/install.json` keeps its original
name on disk, including `copilot` or `gemini` from an older installation.
Managed updates and explicitly authorized downgrades translate rolling names
for the target revision; manual checkout downgrades are unsupported.
See [ADR 0023](docs/adr/0023-use-full-canonical-harness-names.md) for the migration
scope and compatibility contract.

`codex` deliberately uses the existing marketplace/plugin driver, not `$CODEX_HOME/skills`. Its exact-shape install manifest declares `harness: "codex"` and must cover every package that owns canonical skills. The manifest has no independent schema-version field; its repository-owned reader rejects missing or unsupported fields. Each package manifest exposes exactly `./skills/`; source and cache identities are checked against the repository catalog. Plugin activation rolls back newly attempted packages when closure fails.

### OpenClaw skills

Install and configure OpenClaw separately. The `openclaw` target projects the
canonical skill directories into OpenClaw's shared managed skills directory:

```bash
atm harness -- install openclaw --dry-run
atm harness -- install openclaw
atm harness -- refresh openclaw
atm harness -- check openclaw
atm harness -- remove openclaw --dry-run
```

The state root is an absolute `OPENCLAW_STATE_DIR` when set, otherwise
`<home>/.openclaw-<OPENCLAW_PROFILE>` for a named profile, otherwise
`<home>/.openclaw`. A blank or case-insensitive `default` profile selects the
default state. Profile names preserve case and accept 1–64 letters, digits,
underscores or hyphens, starting with a letter or digit. `<home>` is the current
user's home unless `OPENCLAW_HOME` overrides it. `~` in either path override
expands against the relevant home; relative paths and invalid profiles fail
before projection. Legacy state locations require an explicit state override.

Use the same environment for every lifecycle command. To manage a profile
normally launched with `openclaw --profile work`, set `OPENCLAW_PROFILE=work`
for `atm harness --`, or supply its exact state directory:

```bash
OPENCLAW_PROFILE=work atm harness -- install openclaw --dry-run
OPENCLAW_STATE_DIR="$HOME/.openclaw-work" atm harness -- install openclaw
```

PowerShell equivalents use `$env:OPENCLAW_PROFILE = 'work'` or
`$env:OPENCLAW_STATE_DIR = Join-Path $HOME '.openclaw-work'` before calling `atm harness --`.
The OpenClaw CLI's `--profile` flag does not propagate to a separate engine
process. One recorded `openclaw` target represents one state root; removal
rejects a changed root until its recorded environment is restored. Installing
multiple profiles as separate recorded targets is not supported.

The registry explicitly selects `instructions: {"driver": "none"}`. This target
does not manage `AGENTS.md`, `SOUL.md`, workspace bootstrap files, `openclaw.json`,
permissions, or ClawHub metadata. Same-name unmanaged skills cause an error;
unrelated user/ClawHub skills are preserved. POSIX uses directory symlinks and
Windows uses directory junctions, with the existing ownership checks for refresh
and removal. Shared managed OpenClaw skills accept directory links without
changing `skills.load.allowSymlinkTargets`; the per-skill `SKILL.md` containment
rule still applies. Workspace and `extraDirs` discovery have different boundaries.

The projection preserves skill files and their explicit-invocation/read-only
instructions. It grants no tool permissions or publication authority. OpenClaw
controls readiness, agent allowlists and runtime visibility; `atm harness -- check` verifies
the managed projection. After installation, use the matching OpenClaw environment
with `openclaw skills list --json` and `openclaw skills check` to inspect discovery
and readiness. For a named profile, use `openclaw --profile work skills list --json`
or set the exact `OPENCLAW_STATE_DIR` for OpenClaw as well. In the local
OpenClaw 2026.10.2 smoke test, the environment-only profile selected the profile
workspace but reported the default managed skills root; the explicit CLI flag
resolved the matching profile root. See the official [skills][openclaw-skills],
[skills configuration][openclaw-skills-config], [CLI profiles][openclaw-cli] and
[environment variables][openclaw-environment] documentation, and
[ADR 0024](docs/adr/0024-add-openclaw-skills-only-distribution.md).

[openclaw-skills]: https://docs.openclaw.ai/tools/skills
[openclaw-skills-config]: https://docs.openclaw.ai/tools/skills-config
[openclaw-cli]: https://docs.openclaw.ai/cli
[openclaw-environment]: https://docs.openclaw.ai/help/environment

### Oh My Pi agent

The `oh-my-pi` target projects the canonical skill directories into Oh My
Pi's native user agent directory and manages `~/.omp/agent/AGENTS.md` as a
copied global instructions file. Oh My Pi loads both natively:
`~/.omp/agent/skills/<name>/SKILL.md` through its highest-priority native
skill provider (which requires a `description` in each skill's frontmatter;
the catalog satisfies this), and `~/.omp/agent/AGENTS.md` as the user
context file that shadows every other tool's user-level context file inside
Oh My Pi sessions. Keep that shadowing in mind when other targets also
distribute global instructions.

`PI_CODING_AGENT_DIR` is shared with the `pi-agent` target: it relocates Oh
My Pi's default-profile agent directory. Installing both targets while it
points at one directory records two consumers of the same skills root and
the same `AGENTS.md`, following the existing shared-resource rule from
`vscode`/`copilot-cli`: removing one retains the resources the other still
uses. Named Oh My Pi profiles (`omp --profile`, `OMP_PROFILE`, `PI_PROFILE`)
are not modeled; they relocate the agent directory and ignore
`PI_CODING_AGENT_DIR`, so this target always resolves the default profile's
directory. Run Oh My Pi without a named profile when using this distribution.

See [ADR 0025](docs/adr/0025-add-omp-agent-distribution.md) for the
distribution boundary and
[ADR 0026](docs/adr/0026-use-full-canonical-name-for-oh-my-pi.md) for the
canonical-name decision.

## Lifecycle Manager

Historically `install.sh` and `install.ps1` (now retired; use `atm harness
bootstrap`) bootstraped new installations and exposed explicit
`--repair` / `--reinstall` recovery for existing ones. Recovery delegates to the
same manager lifecycle used by the engine:

| Task | Command | Default scope and effect |
| --- | --- | --- |
| Add a harness | `atm harness -- install copilot` | No target means `codex`; records the harness for future updates. |
| Reapply current files | `atm harness -- refresh` | All installed harnesses; no remote fetch. An explicit target does not add it to the recorded set: use `install` for that. |
| Repair Codex caches | `atm harness -- refresh codex --repair` | Explicitly rebuilds caches at the current version. |
| Sync an ATM upgrade | `atm harness sync` | Copies the shipped engine; preserves receipts and desired targets. |
| Reapply an upgrade | `atm update skills --harness <ID>` | Applies the synced distribution to an already installed target. |
| Inspect state | `atm harness status` | Reads recorded harnesses, channel, successful receipts, and active operation; no live health check. |
| Validate files | `atm harness -- check` | Read-only; all installed harnesses unless targets are given. |
| Diagnose warnings | `atm harness -- doctor` | The same checks, with warnings treated as failures; does not repair. |
| Remove a harness | `atm harness -- remove copilot` | Explicit targets or `--all` required; removes only proven managed resources. |
| Repair a distribution | `atm repair skills --harness <ID>` | Repairs selected managed resources without changing PATH; use `atm harness sync` for engine drift. |
| Recover a failed sync | Inspect `state/repair-backups/sync-*` | Ordinary failures restore the previous engine and rolling state; hard interruption requires explicit inspection. |
| Uninstall the manager | `atm harness -- manager uninstall` | Requires an empty harness set, or `--with-harnesses`; unknown files block deletion unless `--purge-unknown` is explicit. |

Running `atm harness --` without a command means `atm harness -- refresh`. `--home PATH` goes before
the command. `install`, `refresh`, `repair`, and `remove` accept `--dry-run` to preview
changes. `--yes` confirms creation and bounded managed cleanup; replacing different
existing instructions still requires a live confirmation. Public command help
bypasses tooling initialization and manager repair, including `atm harness -- manager repair --help`.

Help and argument validation use the base Python and the registry's structural
metadata before runtime preparation or a mutation lock. They do not require Git,
Codex, plugin hashing, or tooling dependencies. Invalid arguments (including a
repair dry run) return a usage error without repairing anything. Help remains
available with damaged instruction sources; a corrupt registry still permits
generic command help but blocks execution that requires harness metadata.

`atm harness status` and `atm harness -- version` are **recorded-state snapshots**. They do not start
Git or Codex, hash plugin files, probe/rebuild a venv, or contact the network.
`status --json` retains `worktreeClean` with the explicit value `null` (unchecked);
consumers must not interpret null as clean or dirty. `observation` is
`recorded-state-only`, and per-harness receipts describe the last successful
record, not current health. Use existing `atm harness -- check` or `atm harness -- doctor` for live
validation; check tolerates warnings, while doctor fails on warnings too.
When both rolling files are absent, status reports `legacy-receipt-only` or
`unknown`, and version fields are null: the immutable initial receipt is never
presented as the current revision. One missing rolling file or malformed state
still fails clearly. Snapshot reads do not initialize or migrate state and are
not an atomic view of a concurrent update; inspect the displayed operation.

The materialized engine and tooling venv must exist for delegated commands.
If the engine is missing or damaged, use `atm harness sync`; bootstrap creates
the venv on first use. Release builds resolve only the adjacent `harness/` tree
or explicit `ATM_ENGINE_SOURCE`, never the build machine checkout.

`HARNESS` selects an atm-harness distribution, not the harness application
itself. Install and configure the Pi, Claude Code, Gemini CLI, or other client
separately. Run `atm harness -- install --help` in a new environment to list the current
registry-owned choices; the list is generated from `.agents/harnesses/registry.json`
rather than duplicated in the CLI. `atm harness -- install --all` installs every current
registry choice, while `--all` on refresh, repair, remove, check, or doctor selects the
desired harness set already recorded by the manager.

When a harness is added in a newer ATM release, upgrade the complete ATM
package and run `atm harness sync` before selecting it. Do not move, edit or
pull `${ATM_HOME:-$HOME/.atm}/repo` directly. Embedded mode rejects Git update,
recover and reclone; use the packaged source for sync and inspect manager status
if an active operation blocks it. Legacy standalone Git lifecycle behavior is
retained in source solely for old-install recovery and synthetic tests.

The immutable `state/install.json` remains the initial bootstrap receipt.
Rolling manager state is kept in `manager.json`, `desired.json`, per-harness
receipts, and an update operation journal. Mutating lifecycle commands share one
manager lock.

## Release And Plugin Distribution Identity

ATM materialization owns `engineIdentity` (`atm-engine-content-v1`) over the
complete shipped tree. Sync compares both the package and installed tree; the
embedded write boundary refuses drift. `embeddedIdentity` / `bundleIdentity`
keep their narrower plugin-generation meaning and existing tests. Recorded
status does not hash content. See [ADR 0027](docs/adr/0027-atm-embedded-distribution.md).


`VERSION` is the canonical `atm-harness` release version. All repository plugins use that value as their base version. Every complete plugin version ends in `+codex.<generation>`, where `generation` is derived from the canonical plugin package content rather than a timestamp. `.agents/plugins/distribution-identity.json` records the full per-package SHA-256 values and the release-level bundle identity.

Use the repository-owned tools instead of editing cachebusters manually:

```bash
python3 scripts/update_plugin_generations.py
python3 scripts/check_plugin_generations.py
```

A source edit without a regenerated identity fails before Codex mutation. An already installed plugin is skipped only when its full cache content identity matches the source; same-version drift fails closed instead of silently retaining stale content.

Directory projections use directory symlinks on POSIX and directory junctions on Windows. They manage only entries proven to target canonical skill directories in this checkout, prune only repository-owned stale links, preserve unrelated user skills, and refuse unmanaged same-name entries. A retry may recover an exact canonical empty ordinary directory left by an interrupted link creation; recovery rejects non-empty directories and reparse points and uses only non-recursive `rmdir()`. Matt skills are maintained in the source catalog under the same rules as the other local plugins.

Harnesses with a managed instructions driver include instructions in their plan; the explicit `none` driver owns no instructions target. A missing managed target requires confirmation, and `--yes` may confirm its creation. Replacing a different existing file always requires live confirmation; `--yes` does not authorize replacement. Directories, unknown reparse points, unmanaged symlinks, configured shadow files, and source or target changes after preflight fail closed. POSIX Codex instructions use a symlink; other managed entries use atomic copies.

`~/.agents/skills` remains an excluded skill root because it may conflict with product-specific discovery. The OpenClaw skills-only capability does not authorize a generic shared projection there. Refresh fails before mutation, and closure fails, when it contains a repository catalog identity or stale repository-owned projection. Unrelated user skills remain untouched. Codex marketplace packages expose `${plugin}:${catalog-name}`; other harnesses retain their native identity behavior, so a bare prompt reference is not a promise of one cross-harness runtime identity.

Source-package validation is independent of the selected harness:

```bash
PLUGIN_VALIDATOR="${PLUGIN_VALIDATOR:-${ATM_HARNESS_ROOT:-$PWD}/scripts/validate_plugin.py}"
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" "$PLUGIN_VALIDATOR" plugins/watcher
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" "$PLUGIN_VALIDATOR" plugins/workflow
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" "$PLUGIN_VALIDATOR" plugins/mattpocock-skills
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/check_plugin_generations.py
```

Lifecycle validation uses the repository-owned `scripts/validate_plugin.py` for every package and preserves an explicit `PLUGIN_VALIDATOR` override. The local contract supports the selected cross-harness frontmatter plus native Codex invocation metadata; it does not inherit a separately installed validator's incompatible requirement to make every frontmatter invocation flag false. An explicit validator failure remains a failure, with no retry through another validator.

The public lifecycle commands own refresh and closure; the Python helpers remain lower-level implementation surfaces:

```bash
atm harness -- refresh codex
atm harness -- check codex
atm harness -- refresh zcode
```

`scripts/sync_agents_skills.py` is the low-level directory-projection tool. It has no default target. Use the harness-aware refresh entry point for normal activation; supply the exact root when inspecting an already selected projection:

```bash
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/sync_agents_skills.py --target-root "$HOME/.zcode/skills" --check --prune
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/refresh_harness.py
```

To retire repository-owned links from the excluded `~/.agents/skills` root, preview first and then run the separately confirmed cleanup. It removes only links revalidated against this checkout and exact canonical empty interruption residues; unmanaged canonical names and a linked/reparse/mount target root remain hard stops:

```bash
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/sync_agents_skills.py --target-root "$HOME/.agents/skills" --remove-managed --dry-run
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/sync_agents_skills.py --target-root "$HOME/.agents/skills" --remove-managed --yes
```

Windows PowerShell:

```powershell
$ManagerHome = if ($env:ATM_HOME) { $env:ATM_HOME } else { Join-Path $HOME ".atm" }
$ToolingPython = Join-Path $ManagerHome "venv\Scripts\python.exe"
& $ToolingPython scripts\sync_agents_skills.py --target-root (Join-Path $HOME ".agents\skills") --remove-managed --dry-run
& $ToolingPython scripts\sync_agents_skills.py --target-root (Join-Path $HOME ".agents\skills") --remove-managed --yes
```

## Matt Pocock Local Selection

`plugins/mattpocock-skills/` is a locally maintained selection of 20 skills, originally derived from upstream v1.2.3 with selected v1.3.1 changes. The plugin [README](plugins/mattpocock-skills/README.md) records attribution and the selected entrypoints; [ADR 0012](docs/adr/0012-maintain-a-local-mattpocock-selection.md) records the migration from the complete upstream mirror.

Edit the selected source skills directly. For upstream releases, follow the [comparison and selection workflow](plugins/mattpocock-skills/README.md#upstream-updates) and retain review progress and deferred changes in the [upstream review record](dev_docs/mattpocock-upstream-review.md). `atm harness -- update` distributes the resulting local edition; it does not import Matt upstream releases. The complete-tree importer and upstream lock remain retired. Source catalog checks preserve cross-harness invocation policy consistency, and the shared plugin validator and distribution identity gates apply to Matt as to every other package.

The selection removes to-questionnaire, to-tickets, wait-what, wayfinder, wizard, setup-matt-pocock-skills and resolving-merge-conflicts from installed discovery. The lightweight `pr` helper replaces the retired conflict entry; it prepares content without granting publication authority. The explicit-only `retro` entrypoint adds optional session-level environment and process proposals, bringing the catalog to 20. The retired entrypoints are no longer available; The private pre-rebuild archive and the attributed upstream releases retain their source. Existing logs and user-created artifacts are preserved. The remaining skill names and invocation policies are unchanged. All three plugins use repository `VERSION` plus their own content generation; activation must select that exact identity even though Matt's base changes from upstream 1.2.3 to local 1.0.0.

After reviewing the source diff, reconcile the complete Codex harness distribution:

```bash
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/refresh_harness.py --harness codex
```

## Orchestration Workflow

Use the `workflow` plugin's `$orchestrate-subagents` skill when the user invokes
it or explicitly asks for bounded Codex subagents or parallel agents. Ordinary
environment-authorized delegation does not invoke this skill by itself:

```text
Use $orchestrate-subagents to review this branch against main.
```

The same workflow can be requested in natural language, such as `Use parallel
subagents to review this branch against main.` The full workflow lives in
`plugins/workflow/skills/orchestrate-subagents/SKILL.md`. Keep root docs
limited to install, validation, and entry-point guidance.

The orchestration workflow identifies each bounded assignment with a unique
`task_name`; its assignment prompt declares read-only permission or an exact
disjoint write scope. The managed support file lives in
`agents/operating-principles.md`; repo-facing notes live in
`docs/codex-agent-support.md`. Local custom-agent preset TOML is not maintained
in this repository.

## Archived Standalone Install Reference

The following section describes the retired standalone OMH installer and its
persisted layout, for interpreting old receipts and recovery tests. It is not
the ATM installation path. New installations use the complete ATM package and
`atm harness bootstrap`; an existing OMH home is explicitly adopted with
`atm harness sync --home /absolute/old/home`. No harness receipt or target
configuration is rewritten during that adoption.


The initializer creates one manager-owned installation under
`${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}`. The retired `install.sh` /
`install.ps1` wrappers
are standalone bootstrap entry points: when run from a checkout they use its
Python installer directly; when streamed or downloaded alone they clone a
temporary bootstrap checkout and invoke the same installer from there. The
Python installer remains the sole owner of the managed `repo/` clone, `venv/`,
`state/install.json`, and ordinary `oh-my-harness` and `omh` launchers under
`bin/`. The temporary checkout is removed after the installer exits and never
becomes installation authority.

Git and Python 3.11 or newer must already be available. A streamed install uses
the canonical HTTPS repository and `main` by default. Documented
`--repository` and `--ref` arguments select both the temporary bootstrap source
and the managed installation source, so a custom source does not execute an
installer from a different repository.

`state/install.json` records one initialization lifecycle and its source
snapshot. It has no independent schema-version field, and its recorded
repository and revision are an installation receipt rather than rolling Git
authority. A ready installation requires an explicit recovery choice: pass
`--repair` or `--reinstall`, or select one at the interactive prompt (default:
Cancel). Noninteractive reruns fail with instructions; `--yes` does not select a
recovery mode. The two flags are mutually exclusive and cannot be combined with
adoption or fast-forward resume. Use `omh update` for an upgrade.
An installer launched from either the managed
repository or another checkout targets the same managed `repo/`; neither the
invoking checkout nor the working directory becomes installation authority.
Incomplete-install reruns, legacy adoption and fast-forward resume retain their
strict receipt checks. A checkout already
moved to the managed path with no incomplete installation record still requires
the explicit `--adopt-current-checkout` option before the initializer may claim
it.

For an existing ready installation, the equivalent recovery entry today is
`python scripts/install_oh_my_harness.py --home <home> --repair|--reinstall …`
(the retired wrappers exec'd exactly this installer in checkout mode); for
embedded installs use `atm harness sync`.

Repair reuses healthy components and restores damaged ones. Reinstall clones
the exact recorded revision and rebuilds the tooling venv, then runs manager
repair and checks every installed harness. It requires access to the recorded
repository. Replaced checkouts and venvs are preserved under
`state/repair-backups/`; unrelated files, user skills, desired harnesses and
update policy remain intact. The initial ready `install.json` is preserved even
when recovery executes an older manager. Neither mode selects a newer release
or adds a harness; use `omh update` or `omh install` for those actions.

Legacy ready installations without either lifecycle file are migrated only
after verifying the current managed checkout, its remote and distribution
identity. That current revision becomes manager authority; the historical
initial revision and the invoking checkout do not. Partial lifecycle state,
unproven paths or a dirty legacy checkout stop recovery. Interrupted updates
retain the manager's journaled rollback flow. `--dry-run` writes no manager
files or PATH changes; it previews recovery without claiming harness closure.

Unix:

```bash
./install.sh --harness codex --yes
# Open a new terminal; PATH registration is automatic.
omh --help
```

The same initializer can be run without a pre-existing checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/zzzhty/oh-my-harness/main/install.sh | bash
```

The streamed wrapper reads live confirmations from the controlling terminal.
For a non-interactive first install, forward `--yes` explicitly:

```bash
curl -fsSL https://raw.githubusercontent.com/zzzhty/oh-my-harness/main/install.sh | bash -s -- --yes
```

To relocate an existing authoritative checkout into the manager home, move it
first and then adopt that exact path. This is a one-time migration, not an
alternate install layout. When Codex instructions still point to the former
checkout, `--migrate-from-repo` permits only that exact symlink to enter the
normal replacement flow; answer the live replacement prompt after inspecting
the printed source and target. `--yes` still cannot approve this replacement.

Unix example:

```bash
old_repo="$HOME/.codex/my-codex"
manager_home="${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}"
mkdir -p "$manager_home"
mv "$old_repo" "$manager_home/repo"
cd "$manager_home/repo"
./install.sh --adopt-current-checkout --migrate-from-repo "$old_repo" --migrate-marketplace --yes
```

Windows PowerShell example:

```powershell
$OldRepo = Join-Path $HOME ".codex\my-codex"
$ManagerHome = if ($env:OH_MY_HARNESS_HOME) { $env:OH_MY_HARNESS_HOME } else { Join-Path $HOME ".oh-my-harness" }
New-Item -ItemType Directory -Force -Path $ManagerHome | Out-Null
Move-Item -LiteralPath $OldRepo -Destination (Join-Path $ManagerHome "repo")
Set-Location -LiteralPath (Join-Path $ManagerHome "repo")
.\install.ps1 --adopt-current-checkout --migrate-from-repo $OldRepo -MigrateMarketplace --yes
```

If initialization stops after writing `status: "installing"`, rerun the
same installer command from either the original external checkout or the
managed checkout. `--adopt-current-checkout` is not required for recovery.
Re-pass any workflow authorization still required by the failed operation, such
as `--migrate-marketplace --yes` on Unix or `-MigrateMarketplace` on Windows
PowerShell. Automatic recovery always uses the managed `repo/` and proceeds only
after the recorded repository, revision, harness, owned paths, launcher bytes,
and venv shape all match exactly; otherwise it stops without changing manager
state. If repairing the failed installer required advancing that managed
checkout, pass `--resume-fast-forward` explicitly. This narrow recovery accepts
only a clean checkout whose `HEAD` equals the requested `origin/<ref>`, whose
remote still matches the recorded repository, and whose recorded revision is an
ancestor of `HEAD`; every other recorded field and owned path remains exact.

```bash
./install.sh --resume-fast-forward --migrate-marketplace --yes
```

```powershell
.\install.ps1 -MigrateMarketplace --resume-fast-forward --yes
```

Expected installer failures are written to standard error as `error: <reason>`
and return a nonzero exit code. A failing child command includes its command and
exit code. The PowerShell install and upgrade wrappers preserve that exit code;
an upgrade stage reports `error: <stage> failed with exit code <code>` after the
child diagnostic, and neither wrapper replaces the reason with a `throw`
exception stack. Interactive terminals render errors and exit codes in bright
red and required actions or confirmation prompts in bright yellow. Redirected
output remains plain text; set `NO_COLOR` to disable emphasis explicitly.

Windows PowerShell:

```powershell
.\install.ps1 --harness codex --yes
# Open a new terminal when running from a separate PowerShell process.
omh --help
```

PowerShell can likewise bootstrap without a checkout:

```powershell
irm https://raw.githubusercontent.com/zzzhty/oh-my-harness/main/install.ps1 | iex
```

Installation, repair, and update automatically register the manager `bin/` in
the current user's environment. On Linux/macOS this edits only the active shell's
configuration: `.bashrc` for bash, `.zshrc` for zsh, or
`fish/conf.d/oh-my-harness.fish` for fish, respecting `ZDOTDIR` and
`XDG_CONFIG_HOME`. It does not register PATH in `.profile`, `.zprofile`,
`.bash_profile`, or `.bash_login`. Other shells require manual PATH setup.
On Windows it updates only `HKCU\Environment\Path`.
No machine-wide PATH or system profile is changed. Unrelated profile content
and dotfile symlinks are preserved; repeated registration does not duplicate
the managed block.

Shell profiles use a short comment and a readable deduplication check on every
POSIX platform. For bash/zsh, a default installation looks like this (the
actual manager path is written, with shell quoting when needed):

```sh
# oh-my-harness PATH
case ":${PATH:-}:" in
    *:/Users/you/.oh-my-harness/bin:*) ;;
    *) export PATH=/Users/you/.oh-my-harness/bin${PATH:+:"$PATH"} ;;
esac
```

Fish uses the same comment followed by `if not contains`, `set -gx PATH`, and `end`.
Windows keeps using the user registry and does not add a PowerShell profile
snippet. Repeated sourcing does not add duplicate PATH entries. An empty PATH
stays free of an implicit current-directory entry.

Pass `--no-path` to the initializer or `omh repair` to skip registration for that
invocation; it is not a saved preference and later `omh update` registers PATH.
A child process cannot change the environment of an already-open parent shell;
open a new terminal after installation rather than editing profiles manually.
`state/environment.json` records ownership so uninstall removes only managed
blocks or Windows entries added by this installation. Same-user external shell
config roots remain cleanup targets after their environment variables change.
Edited managed blocks are preserved and reported, not silently overwritten.

Both command names dispatch to the same manager-home bootstrap shim;
`oh-my-harness` is canonical and `omh` is the short form. Neither launcher is a
symlink. Launchers resolve their home from their own location, so moving the
whole manager directory does not retain a hardcoded old launcher path; run the
launcher from its new `bin/` path with `repair` to reconcile PATH and outputs.

The managed installation layout is:

```text
~/.oh-my-harness/
├── bootstrap/
│   └── omh_bootstrap.py
├── repo/
├── venv/
├── bin/
│   ├── oh-my-harness
│   └── omh
└── state/
    ├── install.json
    ├── manager.json
    ├── desired.json
    ├── environment.json
    ├── repair-backups/  # created when checkout replacement preserves a backup
    ├── harnesses/
    ├── operations/
    └── manager.lock
```

On Windows the two launcher files use the `.cmd` suffix. Development checkouts
may exist elsewhere, but installed hooks and marketplace state bind to the one
managed `repo/` checkout. A local marketplace may report that checkout with the
Windows extended-length `\\?\` prefix; source-binding checks treat equivalent
drive and UNC spellings as the same path while still rejecting a different
directory.

If initialization fails, `state/install.json` remains `installing`. Rerun the
same installer request from either checkout to resume the exact incomplete
installation; `--repair` and `--reinstall` require ready state. Corrupt state, foreign ownership, linked manager-owned paths,
and unsupported interrupted operations are preserved and reported instead of
being reset. Repair does not implicitly upgrade a ready installation; use
`omh update` for that. Explicit legacy adoption/resume flags retain their
stricter identity and snapshot checks.

Use the harness-aware refresh command for global instructions. It resolves the target from the registry and applies the required confirmation policy; do not force-copy over an existing instructions file.

## Tooling Runtime

Shared atm-harness Python tooling uses a runtime venv outside plugin source trees:

Python 3.11 or newer is required for installation and lifecycle commands. The
top-level `atm harness -- --help` path remains standard-library-only and can still render
before this version check. Installers and generated launchers honor
`ATM_BOOTSTRAP_PYTHON` when the default `python3` or `python` is too
old; invoke `scripts/bootstrap_tooling_env.py` with a supported interpreter
directly when using that script outside the launcher flow. Unsupported Python
versions fail before manager-home, checkout, or tooling-venv mutation.

Unix:

```bash
python3 scripts/bootstrap_tooling_env.py
```

Windows PowerShell:

```powershell
py scripts\bootstrap_tooling_env.py
```

The shared interpreter is:

```text
${ATM_HOME:-$HOME/.atm}/venv/bin/python
%USERPROFILE%\.atm\venv\Scripts\python.exe
```

Use this interpreter for Codex hooks, Watcher maintenance scripts, and skill/plugin validation that needs atm-harness tooling dependencies.

## Windows/Unix Compatibility Notes

This repository evolved from the Unix-first `zzzhty/my-codex` workflow; that
name is historical, not a current product or marketplace alias. The
cross-platform compatibility surface is intentionally narrow: it does not add
separate plugins, skills, manifests, or top-level modules for Windows. Windows
support lives in install documentation, shared tooling venv path selection,
Watcher hook command generation, hook schema alignment, and Windows-aware error
messages.

Key platform differences:

- Unix venv Python: `${ATM_HOME:-$HOME/.atm}/venv/bin/python`
- Windows venv Python: `%USERPROFILE%\.atm\venv\Scripts\python.exe` by default
- POSIX directory projections: directory symlinks
- Windows directory projections: directory junctions
- POSIX Codex instructions: symlink into `$CODEX_HOME/AGENTS.md`
- Windows and current non-Codex managed instructions: atomic copy into the registry-selected target

Windows skill projection does not require file-symlink privilege. The projection helper validates junction targets and uses a strictly validated non-recursive `rmdir()` only for an empty ordinary directory left by an interrupted link creation.

`scripts/bootstrap_tooling_env.py` is cross-platform and selects the venv interpreter by platform:

- Windows: `Scripts\python.exe`
- Unix: `bin/python`

A healthy tooling venv with unchanged requirements and importable dependencies is reused without recreating the venv or running pip. Changed requirements or failed dependency imports trigger dependency repair; `atm harness -- repair --rebuild` explicitly rebuilds the venv. The bootstrap resolves the selected base Python to its real executable before creating the venv. This prevents PATH aliases or uv-managed Python symlinks from producing a `pyvenv.cfg` that cannot locate the standard library. If an existing tooling venv cannot start, reports the wrong prefix, or was created from a different base interpreter, bootstrap rebuilds it and restores the previous directory if creation or dependency validation fails. `--dry-run` performs the same read-only health preflight and prints whether a rebuild would occur.

Public `atm harness status`, `atm harness -- version`, `check`, and `doctor` never bootstrap or repair
runtime dependencies, acquire the mutation lock, or create Python bytecode/Git
index refresh files. They remain available while another lifecycle mutation
holds the lock. They are observations, not an atomic snapshot of a concurrently
changing installation. With a missing checkout, missing/unstartable tooling
Python, or failed dependency imports, they exit nonzero and direct you to
`atm harness -- repair`; they do not silently report a healthy installation. `status --json`
and `version --json` return one JSON object on stdout (including a structured
`runtime_unavailable` error when that read-only runtime preflight fails). Command
traces and bootstrap progress go to stderr.
The Windows launcher parses its invocation and exit in one command block before
starting Python. An update can then replace the launcher without CMD reading
the new file at the old byte offset; the actual child exit status and quoted
arguments, including literal exclamation marks, are preserved.

`install`, `refresh`, and `remove --dry-run` do not create or update manager locks
or receipts; `repair --dry-run` and `manager repair --dry-run` also remain
no-write previews. Previewing does not repair a broken runtime, and can fail if
its existing interpreter or dependencies are unavailable. `update --check` is
different: it fetches remote Git metadata and is not a no-write preview.


If a tooling command reports that `PyYAML` or the registry validator
`jsonschema` is missing, refresh the shared tooling venv from the repository
root:

Unix:

```bash
python3 scripts/bootstrap_tooling_env.py
```

Windows PowerShell:

```powershell
py scripts\bootstrap_tooling_env.py
```

## Harness Refresh And Hook Debugging

Use the lifecycle CLI directly after bootstrap:

```bash
atm harness -- refresh
atm harness -- refresh zcode
atm harness -- refresh codex --repair
atm harness -- check codex
```

With no subcommand, `atm harness --` remains a compatibility alias for
`atm harness -- refresh`; new scripts should use the explicit form. `refresh` without targets reconciles the
desired harness set, while `install` without a target selects the registry
default (currently `codex`). The bootstrap shim only restores tooling and enters
the unified Python CLI; `atm harness -- --help` remains available without a tooling rebuild,
and harness defaults, choices, and paths remain registry authority. Global
instructions, when declared, are preflighted before skills or marketplace mutation.

For `codex`, refresh validates the complete manifest, marketplace policy, nested source-package containment, current cache shape, and marketplace source binding before mutation. By default, installation reuses the validated canonical checkout as its local marketplace source, avoiding a second Git acquisition. An explicit Git source/ref still requires the canonical remote and is pinned to the validated checkout commit; explicit Git failures stop without local fallback. Codex CLI resolution uses explicit `--codex`/`-CodexPath`, `CODEX_BIN`, `PATH`, standalone installs, then platform-managed fallbacks.


On Windows, `plugin add` retries only a failed command whose output contains both
`failed to copy plugin file` and `(os error 5)`: at most three attempts, with
0.5-second then 1-second delays. Each attempt keeps the same selector and source;
it does not restart the update or delete caches. A failed copy can leave a
`plugin-install-*` staging directory that Codex does not clean up. The retry
wrapper snapshots each attempt and retains only a unique newly observed staging
candidate with the expected plugin/version layout and paths from the validated
source. Do not run another Codex install/update against the same `CODEX_HOME`
during this operation. The manager lock does not serialize external Codex
processes; a matching snapshot is not proof of which process created the entry.
Multiple matching candidates stop the operation and remain in place. Before
returning, it moves this residue to
`$CODEX_HOME/plugins/atm-harness-install-residue/<marketplace>/<staging-name>/cache-entry`
and writes `context.json` beside it. Existing entries, other plugins/versions,
backup directories, unexpected files, and symlinks/junctions are preserved in
place and still fail normal closure. Changed directory/file metadata or layout,
or a failed quarantine, stops successful activation; it never overwrites retained
evidence or edits ACLs. Other command failures return immediately. Exhaustion
still fails the transaction and invokes the existing rollback. A successful command must pass the normal package/cache and harness
closure checks before an update is recorded as successful. Diagnostics retain
Codex output and report the plugin, expected version, stage, exit code, attempt,
and validated source path. Actual temporary destination paths are available only
if Codex reports them.

This handles one observed intermittent failure, not its unconfirmed underlying
cause. Fresh caches and local sources can also fail; neither local source reuse
nor a few successful attempts proves the problem has disappeared. The engine does not
recommend clearing all caches, elevation, disabling security software, or adding
security exclusions as the default remedy.

`atm harness -- update --channel main` remains the complete upgrade path for the manager and
all recorded harnesses (`atm harness -- update --check --channel main` previews it). The
updated implementation must be present on that channel first. Codex plugin-level
CLI upgrades still use its copy operation; installer `--repair` / `--reinstall`
and `atm harness -- repair` restore the recorded revision and are not upgrade substitutes.
An old Windows launcher cannot be fixed retroactively while it is executing.
For the first update from that launcher, use the healthy managed Python to enter
the same update CLI from PowerShell (after the fix is on the selected channel):

```powershell
$ManagerHome = if ($env:ATM_HOME) { $env:ATM_HOME } else { Join-Path $env:USERPROFILE '.atm' }
$Python = Join-Path $ManagerHome 'venv\Scripts\python.exe'
$Cli = Join-Path $ManagerHome 'repo\scripts\engine.py'
& $Python $Cli --home $ManagerHome update --check --channel main
# Proceed only if the preview permits the update and returns 0:
& $Python $Cli --home $ManagerHome update --channel main
atm harness -- check
```

This bypasses only the old batch reader; ancestry, source identity, journal,
refresh, closure, and rollback checks still run. Once updated, normal
`atm harness -- update --check --channel main`, `atm harness -- update --channel main`, and `atm harness -- check`
use the corrected launcher.

An installation at an unpublished local commit requires a separate ancestry
check. Applying its diff, squashing it, or cherry-picking it into the channel
produces different commits: matching code does not establish a fast-forward.
The channel must descend from the installed commit for the normal update above.
Preserve the original commit objects/history when integrating, or separately
review a supported history transition; a diff alone cannot supply those objects.
Do not reset the managed checkout or disable the fast-forward gate to make the
update appear successful. An explicit `--to <commit>` still runs all update
checks and does not establish ancestry for later channel updates.
See [ADR 0021](docs/adr/0021-retry-windows-plugin-copy-and-track-materialized-instructions.md)
for source/retry and instruction journal boundaries.

Codex stale-plugin reconciliation is on by default because the registry declares `managed-stale`. Only configured entries and cache directories inside the selected marketplace namespace are eligible. A nonempty exact plan is printed before mutation and requires confirmation; `--yes` or `-Yes` may confirm it. An enabled plugin visible only through the CLI and not proven by managed config/cache remains a hard failure. Other harnesses use only their registry-selected directory projection and never prune Codex plugins.

The registry records `my-codex` only as the retired marketplace identity consumed
by the explicit one-time migration. A normal refresh stops after printing the
bounded legacy config/cache plan. Run
`atm harness -- refresh codex --migrate-marketplace --yes` to install and verify the new
marketplace, retire the old selectors and source, and remove the validated old
cache namespace. The closure check rejects any remaining retired state.
The registry `schemaVersion` is an ISO calendar date (`YYYY-MM-DD`), currently
`2026-09-18`; advance it only when the registry schema changes.

`--migrate-from-repo <absolute-path>` is independent of marketplace discovery:
it authorizes only recognition of the former checkout's exact registry-declared
current and peer instruction sources and, when relocation has made that retired
local marketplace source unavailable, detaches only the broken source
registration so Codex discovery can continue. Retired selectors and cache
remain until the new marketplace passes closure. This does not make the former
path a fallback checkout or compatibility alias; dry-run stops at this
detachment breakpoint.

`--yes` never authorizes replacement of a different existing instructions file. That action always requires a live confirmation after the target type and content digest are shown.

Migrate legacy Watcher runtime roots explicitly before final checks:

```bash
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" plugins/watcher/scripts/watcher migrate-state --dry-run
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" plugins/watcher/scripts/watcher migrate-state --apply
```

This moves `$CODEX_HOME/skill-watcher/` to `$CODEX_HOME/watcher/skill/` and `$CODEX_HOME/doc-watcher/` to `$CODEX_HOME/watcher/doc/`. It refuses to merge when a target directory already exists.

Direct Python entry-point usage remains supported after `scripts/bootstrap_tooling_env.py` has created the shared tooling venv:

```bash
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/refresh_harness.py
# alternative: "${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/refresh_harness.py --harness zcode
```

Windows PowerShell:

```powershell
$ManagerHome = if ($env:ATM_HOME) { $env:ATM_HOME } else { Join-Path $HOME ".atm" }
$ToolingPython = Join-Path $ManagerHome "venv\Scripts\python.exe"
& $ToolingPython scripts\refresh_harness.py
# alternative: & $ToolingPython scripts\refresh_harness.py --harness zcode
```

Run the final closure check after refresh:

Unix:

```bash
"${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/check_harness.py
# alternative: "${ATM_HOME:-$HOME/.atm}/venv/bin/python" scripts/check_harness.py --harness zcode
```

Windows PowerShell:

```powershell
$ManagerHome = if ($env:ATM_HOME) { $env:ATM_HOME } else { Join-Path $HOME ".atm" }
$ToolingPython = Join-Path $ManagerHome "venv\Scripts\python.exe"
& $ToolingPython scripts\check_harness.py
# alternative: & $ToolingPython scripts\check_harness.py --harness zcode
```

The check script verifies the selected harness skills, declared instructions, and excluded-root policy. Codex closure also verifies the exact marketplace/source package set, manifest `./skills/` projection, enabled CLI state, cache identities, tooling Python, Watcher hooks, subagent support, source plugin validation, and Watcher doctor. Native directory harnesses verify their selected projection and any managed instructions; OpenClaw checks only its skill projection. The check is read-only.

After the helper refreshes hooks, open `/hooks` in Codex and trust the refreshed Watcher skill command hook definitions. Codex skips non-managed command hooks until the exact hook definition is trusted.

For a managed instructions driver, refresh preflights global instructions before distribution mutation and verifies them after an atomic write. The final closure check reads the same registry-resolved plan.

Watcher installs user-level Codex command hooks in `$CODEX_HOME/hooks.json`. It does not use plugin manifest hooks and does not modify `.codex-plugin/plugin.json`.

The generated hook handlers observe:

- `SessionStart`
- `UserPromptSubmit`
- `PostToolUse`
- `Stop`

`SessionStart` refreshes `$CODEX_HOME/watcher/skill/skill-metadata-cache.json` and is not persisted by default. The skill inventory comes only from the repository catalog under the explicit `--repo-root`; marketplace metadata, plugin manifests, plugin cache, and the runtime cache are not catalog authorities. Repository `.codex-plugin/skill-watcher.json` files are non-callable attribution overlays for namespaced Watcher identities, roles, aliases, supporting relationships, logical groups, and legacy mappings. Missing repository source, catalog failures, unknown overlay schemas, and invalid references fail visibly.

Expected command-hook schema:

```json
{
  "type": "command",
  "async": false,
  "command": "... watcher skill observe --repo-root <atm-harness-root>",
  "timeoutSec": 10,
  "statusMessage": "Watcher skill: observe <event>"
}
```

Windows hook commands are rendered with Windows command-line quoting and should point at `Scripts\python.exe`. Unix hook commands use POSIX quoting and should point at `bin/python`.

Install or refresh Watcher skill hooks from the source checkout:

Unix:

```bash
"$ATM_HARNESS_PYTHON" "$ATM_HARNESS_ROOT/plugins/watcher/scripts/watcher" skill install-hook --repo-root "$ATM_HARNESS_ROOT" --dry-run
"$ATM_HARNESS_PYTHON" "$ATM_HARNESS_ROOT/plugins/watcher/scripts/watcher" skill install-hook --repo-root "$ATM_HARNESS_ROOT" --apply
```

Windows PowerShell:

```powershell
$python = "$env:USERPROFILE\.atm\venv\Scripts\python.exe"
& $python "$env:ATM_HARNESS_ROOT\plugins\watcher\scripts\watcher" skill install-hook --repo-root $env:ATM_HARNESS_ROOT --dry-run --python $python
& $python "$env:ATM_HARNESS_ROOT\plugins\watcher\scripts\watcher" skill install-hook --repo-root $env:ATM_HARNESS_ROOT --apply --python $python
```

After applying hooks, open `/hooks` in Codex and trust the Watcher skill command hook definitions. Codex skips non-managed command hooks until the exact hook definition is trusted.

Runtime Watcher skill state is written under `$CODEX_HOME/watcher/skill/`:

```text
logs/events.jsonl
reports/
proposals/
snapshots/
rejected/
backups/
turns/
```

The hook adapter records summaries, lengths, hashes, tool names, outcomes, and redacted metadata. It does not store full prompts, full assistant messages, full shell commands, full tool responses, file contents, secrets, or private business data.

Watcher monitors the canonical repository skill set by default and can be narrowed with `WATCHER_SKILL_MONITORED_SKILLS`. Installed hooks embed the explicit repository root, so repository and harness-projection execution share the same source runtime and do not depend on plugin cache or working-directory inference. Because Codex hook payloads do not provide a stable native skill id, attribution is recorded as `provided`, `prompt_mention`, `assistant_announcement`, or `unknown`. Successful tool calls are counted in transient turn state but are not persisted as individual records; failed tool calls and one `turn_summary` are persisted for active monitored skills.

When the user explicitly invokes a monitored skill, the adapter stores a redacted `user_skill_context` summary/hash for the extra information mentioned with that skill. This is intended as future skill-improvement evidence without retaining the raw prompt.

## Validation

Unix:

```bash
python3 -m json.tool .agents/plugins/marketplace.json >/dev/null
python3 -m json.tool .agents/plugins/install-manifest.json >/dev/null
python3 -m json.tool .agents/harnesses/registry.json >/dev/null
python3 -m json.tool .agents/harnesses/registry.schema.json >/dev/null
PLUGIN_VALIDATOR="${PLUGIN_VALIDATOR:-${ATM_HARNESS_ROOT:-$PWD}/scripts/validate_plugin.py}"
"$ATM_HARNESS_PYTHON" "$PLUGIN_VALIDATOR" "$ATM_HARNESS_ROOT/plugins/watcher"
"$ATM_HARNESS_PYTHON" "$PLUGIN_VALIDATOR" "$ATM_HARNESS_ROOT/plugins/workflow"
"$ATM_HARNESS_PYTHON" "$PLUGIN_VALIDATOR" "$ATM_HARNESS_ROOT/plugins/mattpocock-skills"
"$ATM_HARNESS_PYTHON" -m unittest discover -s tests -p 'test_*.py' -v
```

Windows PowerShell:

```powershell
& $env:ATM_HARNESS_PYTHON -m json.tool .agents\plugins\marketplace.json | Out-Null
& $env:ATM_HARNESS_PYTHON -m json.tool .agents\plugins\install-manifest.json | Out-Null
& $env:ATM_HARNESS_PYTHON -m json.tool .agents\harnesses\registry.json | Out-Null
& $env:ATM_HARNESS_PYTHON -m json.tool .agents\harnesses\registry.schema.json | Out-Null
$PluginValidator = if ($env:PLUGIN_VALIDATOR) {
    $env:PLUGIN_VALIDATOR
} else {
    Join-Path $env:ATM_HARNESS_ROOT "scripts\validate_plugin.py"
}
& $env:ATM_HARNESS_PYTHON $PluginValidator "$env:ATM_HARNESS_ROOT\plugins\watcher"
& $env:ATM_HARNESS_PYTHON $PluginValidator "$env:ATM_HARNESS_ROOT\plugins\workflow"
& $env:ATM_HARNESS_PYTHON $PluginValidator "$env:ATM_HARNESS_ROOT\plugins\mattpocock-skills"
& $env:ATM_HARNESS_PYTHON -m unittest discover -s tests -p 'test_*.py' -v
```

## Layout

```text
.agents/plugins/marketplace.json
.agents/plugins/install-manifest.json
.agents/harnesses/registry.json
.agents/harnesses/registry.schema.json
plugins/
  watcher/
  workflow/
  mattpocock-skills/
install.sh
install.ps1
requirements.txt
scripts/bootstrap_tooling_env.py
scripts/check_harness.py
scripts/harness_registry.py
scripts/install_engine.py
scripts/manager_paths.py
scripts/manager_state.py
scripts/engine.py
scripts/atm_bootstrap.py
scripts/remove_harness.py
scripts/refresh_harness.py
scripts/validate_plugin.py
scripts/sync_agents_skills.py
scripts/sync_codex_agents.py
scripts/sync_harness_instructions.py
scripts/upgrade_oh_my_harness.ps1
scripts/upgrade_oh_my_harness.sh
tests/
agents/
```

### Local application integration

ATM and other local clients can use the [versioned machine interface](docs/machine-interface.md)
for capability discovery, recorded status, read-only validation and explicitly
confirmed, bounded install/refresh/remove and existing-manager repair operations. The engine remains the lifecycle
authority; clients must not write its state or silently fall back to interactive
commands. Update and full manager recovery remain capability-gated in protocol 1.
