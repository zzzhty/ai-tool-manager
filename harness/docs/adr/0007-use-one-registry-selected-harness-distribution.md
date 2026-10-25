---
status: accepted
---

# Use one complete registry-selected harness distribution

Every refresh and closure check selects one complete distribution with `--harness`. A harness always owns skills, global instructions, root resolution, platform materialization, reconciliation, and optional runtime extras as one bundle. The strict repository-owned `.agents/harnesses/registry.json` is the only target authority. Shell and PowerShell wrappers forward the harness id and do not duplicate its defaults or paths.

The default harness is `codex`. Its skills driver remains the existing Codex marketplace/plugin installation path; it is not a directory projection into `$CODEX_HOME/skills`. Its exact-shape install manifest must cover the canonical skills-bearing package set exactly. The manifest has no independent schema-version field; its repository-owned reader rejects missing or unsupported fields. Registry-owned reconciliation prunes only stale configured or cached entries proven to belong to the selected marketplace. A nonempty exact prune plan is printed and confirmed; `--yes` may confirm that bounded plan.

The first registry also includes `zcode`, `claude-code`, `copilot-cli`, `gemini-cli`, and `opencode`. These harnesses project canonical skill directories and the repository root `AGENTS.md` through their native paths without converting Codex plugin packages. Product-specific roots remain structured resolver data: ZCode and OpenCode use documented user-home paths, Claude Code and Copilot CLI accept final config-root overrides, and Gemini CLI treats its override as a replacement user home before appending `.gemini`. Cursor is deferred because its global User Rules do not yet have an official file-backed target that this workflow can safely manage.

`pi-agent` was added later as the complete native Pi Agent distribution. `PI_CODING_AGENT_DIR` replaces its global configuration root, which otherwise resolves to `~/.pi/agent`; the harness projects skills into `skills/`, copies global instructions to `AGENTS.md`, and treats a sibling `AGENTS.override.md` as a shadowing conflict.

`~/.agents/skills` is not a harness. A skills-only projection cannot carry the required instructions projection and can be discovered alongside product-specific distributions, creating duplicate identities and precedence conflicts. The registry therefore declares it as an Excluded Skill Root. Every refresh fails before mutation, and every closure check fails, when that root contains a canonical catalog identity or any stale repository-owned projection link. Unrelated user skills remain outside repository ownership.

Excluded-root cleanup is explicit and separate from harness refresh. The low-level projection tool requires an exact `--target-root`; `--remove-managed --dry-run` previews only repository-owned links and exact canonical empty interruption residues, and a real cleanup additionally requires `--yes`. It preserves unrelated entries, refuses unmanaged canonical names, revalidates each link destination, and retains the strictly validated non-recursive `rmdir()` boundary. Refresh never deletes excluded-root state automatically.

One `--harness` value selects the complete bundle reconciled by one invocation; it does not purge another complete native harness distribution. Global instructions are part of the selected plan rather than a second CLI choice. Missing targets require confirmation, which `--yes` may provide. Replacing a different existing instructions file always requires live confirmation; `--yes` does not authorize replacement. Directories, unknown reparse points, unmanaged symlinks, shadowing files, and source or target changes after preflight fail closed.

## Consequences

The former `--skill-mode`, `direct`, `plugin`, `shared`, and two-parameter skills/instructions designs are retired without aliases, dual reads, or wrapper fallbacks. Historical ADRs and TODO entries retain their original terminology. Codex marketplace packages expose plugin-qualified identities; other harnesses own their native identity behavior. The registry does not promise one cross-harness spelling.

Adding a harness requires a schema-valid registry entry plus resolver, skills, instructions, and closure coverage. A partial skills-only target belongs in the excluded-root policy, not the harness table. The registry contains only allowlisted structured data and never arbitrary commands.
