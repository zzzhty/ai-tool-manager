---
status: accepted
---

# Use the full canonical name for Oh My Pi

## Context and bounded identity inventory

`omp` is the CLI binary abbreviation of the Oh My Pi coding agent
(`~/.omp/agent`, `OMP_PROFILE`). ADR 0025 added its distribution under the
canonical harness id `omp` with no alias, while every other abbreviated client
name in the registry follows ADR 0023: the complete distribution name is the
canonical id and the short name is an input alias (`pi-agent`/`pi`,
`copilot-cli`/`copilot`, `gemini-cli`/`gemini`).

| Surface | Classification and treatment |
| --- | --- |
| Registry key, display name, aliases | Public and persisted contracts: migrate `omp` to `oh-my-pi`, retain `omp` as an input alias, and use the display name `Oh My Pi`. |
| README harness table and the Oh My Pi section, CHANGELOG unreleased entry | Current consumers: describe the full canonical id with `omp` as the alias; the entry is still unreleased, so it records the final naming only. |
| Registry and lifecycle tests | Current validation consumers: canonical choices, alias map, plan resolution and receipts; alias inputs continue to exercise resolution before any state write. |
| Desired state and per-harness receipts | Persisted contracts: only pre-release local installations can record `omp`; the existing ADR 0023 protocol applies unchanged — read-only commands never rewrite, a successful mutation converges to `oh-my-pi`, and alias-named receipts are deleted only after ownership validation. The immutable initial `state/install.json` keeps its original bytes. |
| Native paths, environment variables and binary names (`~/.omp/agent`, `PI_CODING_AGENT_DIR`, `OMP_PROFILE`, `PI_PROFILE`, `omp` CLI, `OMP_*` prefix) | External or non-identity contracts: unchanged. |
| ADR 0025 and dated research | Historical evidence: unchanged. This ADR supersedes only ADR 0025's canonical-id inventory sentence, not its distribution boundary. |

## Decision

The registry remains the single authority and reuses the ADR 0023 migration
machinery in the same direction as `pi-agent`: `resolve_id` maps `omp` to
`oh-my-pi` before selecting paths or writing state, `--all` still selects the
distribution once, and cross-version update/downgrade translation resolves
equivalent ids through each revision's own registry. No schema change, new
driver, resource root, hard-coded alias map, plugin content, distribution
fingerprint, or release version change is involved.

## Verification

Registry tests assert the new choices set, the `omp` alias mapping and the
unchanged `~/.omp/agent` plan surface. The lifecycle test installs through the
`omp` alias and records only canonical state: desired `oh-my-pi`, a
`state/harnesses/oh-my-pi.json` receipt, and no alias-named receipt. Managed
downgrades to the `omp`-canonical pre-revision registry remain representable
through the existing rolling-name translation.
