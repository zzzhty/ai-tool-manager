# OpenClaw local validation — 2026-10-13

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

Local checkout base: `e68df7a8a1c8ce3e445ec87674716a39964b2b3f` from
`zzzhty/oh-my-harness`. At the end of local validation the development checkout
was uncommitted; no push, pull request, release, client install, real manager
install, or real user configuration change had been performed. Draft PR
publication was subsequently authorized. Merge and release remain out of scope.

## Change and boundary

- Registry/schema and reader add the `openclaw` target, the structured
  `openclaw-state` resolver, and exact `instructions: {"driver": "none"}`.
- State, named profile and relocated home select one skills root; invalid
  profiles/relative overrides fail. Existing targets keep their instructions.
- Instruction preparation/check/removal and shared-resource removal handle a
  plan with no instructions target. Refresh/update reuse the existing projection
  driver and receipts; no new projection or permission mechanism was added.
- Tests cover real local Git update/re-entry, read-only snapshots and dry runs,
  root drift, old target revisions lacking OpenClaw, shared consumers,
  unmanaged/ClawHub collisions, preserved user files, excluded roots, and
  POSIX/Windows materialization/path transport.
- README, CONTEXT, Unreleased changelog and ADR 0024 record the capability.
  Canonical skills, Matt upstream synchronization, plugin manifests/generations,
  permission settings, and the original `~/.agents/skills` exclusion are unchanged.

## Automated checks

Runner: existing tooling Python 3.13.15 with PyYAML 6.0.3 and jsonschema.
All lifecycle execution used disposable HOME/USERPROFILE values with client
override variables cleared; child fixtures supply their own isolated values.
Only fixture dependency acquisition is substituted with an offline temporary
venv. Fixture commits and update sources are local disposable Git repositories.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_*.py'` | 462 tests, OK; 9 conditional skips |
| `python -m unittest discover -s plugins/watcher/tests -p 'test_*.py'` | 87 tests, OK; 3 conditional skips |
| `python -m unittest discover -s plugins/workflow/tests -p 'test_*.py'` | 95 tests, OK |
| `scripts/check_plugin_generations.py` | Pass; existing bundle `sha256:992f882741e00c6ddad4640a65ce52a573bd182f6fb14d524b67ed973aab3168` |
| `scripts/validate_plugin.py` for all three plugins | Pass |
| Compile scripts/tests/Watcher/Workflow with an external `/tmp` bytecode cache | Pass |
| Registry JSON/schema validation and strict-reader rejection cases | Pass in registry tests |
| `git diff --check` | Pass |

## Installed OpenClaw discovery

An existing OpenClaw **2026.10.2 (`b8952d4`)** was available; it was not installed
or upgraded for this task. A minimal environment pointed HOME, state/config,
cache and temporary paths into `/tmp/omh-openclaw-discovery-*` and set
`OPENCLAW_OFFLINE=1`. Only skills projection, list/check and version/help
commands were run; no skill, model turn, Gateway session or dependency installer
was invoked.

| Scope | Discovered / eligible repository skills | Invocation policy |
| --- | --- | --- |
| Default `.openclaw/skills` | 30 / 30 | 10 explicit-only skills remain `modelVisible: false` |
| Relocated home and `--profile work` | 30 / 30 | Same 10 explicit-only skills; no mismatch |
| Absolute custom state directory with spaces | 30 / 30 | Same 10 explicit-only skills; no mismatch |

The explicit-only names are `ask-matt`, `grill-me`, `grill-with-docs`, `handoff`,
`implement`, `improve-codebase-architecture`, `retro`, `teach`, `to-spec`, and
`triage`. Directory links expose the original skill files byte-for-byte.

OpenClaw 2026.10.2 showed a CLI discrepancy when only `OPENCLAW_PROFILE=work`
was supplied: its workspace used the profile, while `managedSkillsDir` remained
the default root and no profile-managed skills appeared. `openclaw --profile work`
or an explicit `OPENCLAW_STATE_DIR` resolved the matching root. The README
documents this observation; no fallback projection, config edit, or symlink
trust expansion was introduced.

Official sources: [skills](https://docs.openclaw.ai/tools/skills),
[skills config](https://docs.openclaw.ai/tools/skills-config),
[CLI](https://docs.openclaw.ai/cli), and
[environment variables](https://docs.openclaw.ai/help/environment).

## Remaining verification

Native Windows junction execution and macOS were not run in this Linux workspace;
Windows resolver/materialization and junction argument transport are covered by
unit tests, and the existing CI matrix remains the native platform check.
Python 3.11/3.12 were not run locally. Discovery was verified in disposable homes,
not against the user's live Gateway or agent configuration. One installed target
records one state root; simultaneous separately recorded profiles remain outside
this change. There is no local implementation blocker. The subsequent draft PR
and its exact-head CI results are reported separately from these local checks.
