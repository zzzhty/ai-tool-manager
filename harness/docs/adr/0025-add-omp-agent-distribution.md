---
status: accepted
---

# Add an OMP agent distribution

This follows the registry-selected distribution boundary in
[ADR 0007](0007-use-one-registry-selected-harness-distribution.md) and the
shared-resource rule in [ADR 0020](0020-distinguish-vscode-from-copilot-cli.md).
OMP natively loads `~/.omp/agent/skills/<name>/SKILL.md` through its
highest-priority native skill provider (which requires a `description` in each
skill's frontmatter; the repository catalog already satisfies this) and loads
`~/.omp/agent/AGENTS.md` as its highest-priority user context file. The registry
target therefore needs only the existing `directory-projection` skills driver
and the `managed-file` copy instructions driver. No new driver, root source,
schema field, or harness-specific consumer code is introduced.

The root candidates are the `PI_CODING_AGENT_DIR` environment variable — which
relocates OMP's default-profile agent directory — then the user home's
`.omp/agent`. That variable is shared with the `pi-agent` target: when both
installed targets resolve one directory, the skills links and the `AGENTS.md`
file are shared resources, and removal retains them for the remaining consumer
through the existing concrete-path sharing checks. Named OMP profiles
(`omp --profile`, `OMP_PROFILE`, `PI_PROFILE`) relocate the agent directory and
ignore `PI_CODING_AGENT_DIR`; they are outside this target, which always
resolves the default-profile directory. Run OMP without a named profile when
using this distribution.

The bounded identity inventory adds the public canonical harness id `omp` (no
alias) with display name `OMP`. Existing harness ids, aliases, drivers,
registry field names and schema version, persisted manager/receipt shapes, and
historical ADRs are unchanged. A managed downgrade to a revision lacking `omp`
fails through the existing cross-version identity resolver before checkout.

Native behavior verified from the OMP client documentation on 2026-10-25
(context files, skills, and settings references): skills are discovered
non-recursively as `<skills-root>/<name>/SKILL.md` from `~/.omp/agent/skills`;
`~/.omp/agent/AGENTS.md` is the native user context file that shadows the other
tools' user-level context files; `PI_CODING_AGENT_DIR` relocates the default
profile's agent directory while named profiles ignore it. Local lifecycle tests
use isolated homes and local Git sources, including the shared
`PI_CODING_AGENT_DIR` root with `pi-agent`. Native OMP discovery execution
remains a separate validation surface from `omh check`.
