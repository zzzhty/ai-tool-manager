# Resolve Harness Aliases at Input Boundaries

Status: Accepted
Date: 2026-09-18

## Context

Users naturally type client names such as `copilot`, while the distribution and
its persisted receipts use `copilot-cli`. Rejecting the short name makes setup
harder. The CLI also left target defaults and lifecycle effects unclear, and the
launcher could initialize tooling or repair a checkout before showing subcommand
help.

## Identity classification and scope

| Surface | Classification and treatment |
| --- | --- |
| Canonical registry keys (`copilot-cli`, `claude-code`, `gemini-cli`, `pi-agent`, and the other harness IDs) | Public and persisted identities: preserve them. |
| Installation receipt, desired harness set, per-harness receipts, resolved roots and instruction targets | Persisted contracts: preserve their names and formats; write canonical IDs only. No existing data migration is needed. |
| Registry `aliases` | New public input vocabulary authorized by the alias feature; the registry is its single owner. |
| Registry schema version | Advance from `2026-08-25` to `2026-09-18` with the schema and reader, following the README's schema-change rule. |
| Bootstrap `--harness`, public positional targets / `--harness`, and helper plan resolution | Current input consumers: normalize names before applying or recording a distribution. Shell and PowerShell wrappers forward to these consumers. |
| Existing command names, flags, no-command refresh behavior, and destructive confirmation rules | Preserve the public contract; explain defaults and effects in help. |
| Historical ADRs, records, and retired marketplace identities | Preserved evidence; no rename or rewrite. |

## Decision

Each harness may declare an `aliases` array. Initial aliases are `claude`,
`copilot`, `gemini`, and `pi`. Names must use the canonical ID syntax and be
globally unambiguous: reject duplicate aliases, aliases equal to any canonical
ID, and aliases shared by two harnesses. The schema validates array/name shape;
the registry reader owns cross-harness uniqueness.

Resolve aliases to canonical IDs at bootstrap parsing, lifecycle target parsing,
and shared harness-plan resolution. Deduplicate after resolution. Keep the
registry's canonical choices separate from aliases so `--all` never repeats a
distribution. Defaults remain canonical, and no alias-specific state or paths
are created. Unknown input fails before lifecycle state access.

Help is organized around setup, adding a harness, refreshing current files,
updating remote source, diagnostics, and removal. Lists and aliases come from
the registry. It documents target defaults, `--all`, saved update channels,
network activity for `update --check`, and confirmation limits. The bootstrap
forwards help requests directly to the requested subcommand before tooling
initialization or manager repair.

## Verification and compatibility

Behavioral tests cover aliases resolving to the same plan on both platform
materializations, registry/schema rejection, target deduplication, canonical
installation and lifecycle receipts, removal by alias, early unknown-name
failure, and help bypassing both runtime initialization and checkout repair.
Existing lifecycle, ownership, recovery, and wrapper tests remain binding.

The new source and schema ship together. Existing manager state requires no
conversion. Older manager revisions do not understand new aliases; update the
manager before using them. Development changes do not activate the managed
installation. No plugin contents or distribution identity algorithm changes.
