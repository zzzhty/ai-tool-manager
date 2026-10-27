# ADR 0028: Rust distribution and optional payload runtimes

Status: accepted by the user, 2026-10-26. Supersedes ADR 0027's Python distribution execution and whole-tree packaging, preserving its ownership and historical evidence boundaries.

ATM's internal `atm-core::distribution::Service` owns source validation, locked content cache, plans, receipts, client adapters, runtime preparation and hook ownership. CLI and GUI call this service. `machine.py`, `engine.py` and Python installer subprocess fallbacks are retired. No new repository or Hub service is introduced.

## Identity inventory

| Surface | Classification and treatment |
| --- | --- |
| `ATM_HOME`, `atm-harness`, registry tool IDs and aliases, persisted prior receipts | Public/persisted: preserve names; explicit one-time handoff archives exact old state and retires its execution authority. |
| Four `watcher:*` interactive workflow identities | Persisted logging identities: retain stable IDs and alias new `maintenance:*` selectors in the versioned catalog; never rewrite logs. |
| `plugins/watcher` current payload packaging | Authorized package migration: interactive workflows move to `plugins/maintenance`, event/report helpers move to `runtimes/watcher`; runtime has no callable skills. |
| Existing plugin generation algorithm | Preserve canonical plugin tree identity, including directories and package content; regenerate once after content changes and verify against existing oracle. |
| Distribution source manifest, Rust receipt and canonical catalog | New versioned contracts owned by Rust; catalog records source identity, stable skill IDs, source paths and attribution overlays. |
| Prior ADRs, dated acceptance records, historical logs | Preserve immutable evidence; current entry points explicitly supersede obsolete execution instructions. |

## Sources and runtimes

The manifest locks an explicit payload inventory by digest and a package version. Rust rejects missing content, traversal, case collisions, links/reparse points and identity mismatch. Portable releases carry that inventory, never the repository's complete `scripts` tree. The installed cache is pinned by complete source identity; status reads receipts only, without source scanning, client invocation, dependency probes or network access.

Installing, updating, removing and inspecting static skills requires no Python. Python helpers remain payloads. Explicit runtime preparation requires an absolute interpreter, declared minimum version, isolated dependency group and hashed requirement lock. Optional external venvs are verified without writes. No shell activation, project `.venv`, global package install or interpreter download is permitted. Versioned environments are created and validated at their final paths; failed creation retains prior references. Offline preparation uses complete cached wheels or gives a missing dependency error.

Preparing a runtime never enables hooks. Hook enabling is an explicit service operation and merges only receipt-owned configuration entries, retaining foreign groups and refusing user-edited owned values. Removal keeps logs, reports and unowned files. Runtime/cache versions remain retained while references may exist; automatic destructive garbage collection is outside this change.

Watcher reads `canonical-catalog.json` and embedded attribution overlays. It neither dynamically imports the Python installer catalog nor scans a full repository. Maintenance workflows reference prepared runtimes explicitly; their capabilities remain available.

## Transactions and recovery

One manager OS lock serializes mutations. Plans record exact prior file/config evidence and apply rejects changed observations, unknown owners and same-name collisions. One physical target has one receipt. Shared client config records only owned fields, so uninstall restores those fields while retaining unrelated user values. Cross-file visibility is not atomic: a durable journal contains before/after evidence and recovery only restores targets still matching known transaction states. Changed files stop recovery without deletion. Interrupted work remains visible through recorded status.

Legacy handoff is explicit, validates the previous source and independently resolved target roots, refuses active/pending old operations, archives exact rolling state and retires old engine entry points. It never runs the old engine or silently initializes partial legacy state. Immutable receipts and logs remain historical evidence, not a second writer.

## Validation

Synthetic Rust tests own distributor acceptance: Python-free lifecycle, verified cache/offline failure, user modifications, same physical target ownership, client config merge, hooks, runtime argv and locks, recovery, and explicit old state handoff. Python tests only validate helper payloads and developer package metadata. Native Windows/macOS execution and real client/hook integration must be reported separately from Linux/synthetic evidence. Tests must use disposable homes and no real installations, venvs, credentials or network settings.
