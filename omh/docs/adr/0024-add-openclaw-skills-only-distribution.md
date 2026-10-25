---
status: accepted
---

# Add an explicit OpenClaw skills-only distribution

This extends the mandatory instructions boundary in [ADR 0007](0007-use-one-registry-selected-harness-distribution.md).
OpenClaw owns agent workspace instructions and personality files separately from
its shared skills. A registry target can therefore explicitly select
`instructions: {"driver": "none"}` with directory projection and no runtime
extras. Missing or null instructions remain invalid. The plan has no instructions
target or materialization, and the instruction helpers perform no file inspection
or mutation. Existing managed-file/settings-derived-file targets retain their
confirmation, integrity and ownership rules.

The `openclaw-state` structured root resolver selects explicit
`OPENCLAW_STATE_DIR`, then a named `OPENCLAW_PROFILE` under the effective
`OPENCLAW_HOME` or user home, then `.openclaw`. Overrides must be absolute
(leading `~` is expanded); profile names are bounded and cannot escape the root.
One receipt owns one selected state root. A profile change is root drift for
removal, not permission to delete either profile. The existing update preflight
rejects revisions that cannot represent an installed `openclaw` target.

Shared `<state-dir>/skills` uses the existing POSIX directory symlink / Windows
junction driver. User and ClawHub entries retain ownership; collisions fail and
only proven repository projections can be pruned or removed. `AGENTS.md`,
`SOUL.md`, `openclaw.json`, ClawHub metadata and permissions are outside this
target. The excluded `~/.agents/skills` policy stays in force. Skills and plugin
generations are unchanged; distribution does not grant implicit invocation,
tool permissions, or authority to publish.

The bounded identity inventory adds `openclaw`, `openclaw-state` and the exact
`none` driver branch. Existing public harness IDs/aliases, registry field names
and schema version, persisted manager/receipt shapes, instruction source
identities, and historical ADRs are preserved. Current plan/helper consumers and
the schema/reader gain the explicit no-target branch together.

Official rules verified on 2026-10-13: [skills](https://docs.openclaw.ai/tools/skills)
documents shared state-owned discovery and per-skill containment;
[skills config](https://docs.openclaw.ai/tools/skills-config) permits shared
skill-directory links without changing `allowSymlinkTargets`;
[CLI](https://docs.openclaw.ai/cli) and
[environment variables](https://docs.openclaw.ai/help/environment) define the
profile/state/home overrides. Local lifecycle tests use isolated homes and local
Git sources. Native OpenClaw discovery and Windows junction execution remain
separate validation surfaces from `omh check`.
