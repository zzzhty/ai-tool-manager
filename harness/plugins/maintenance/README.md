# Maintenance skills

This plugin preserves four distinct interactive workflows:

- `doc-alignment`: audit and align current documentation and operational guidance.
- `housekeeping`: remove inventoried disposable artifacts while protecting user work.
- `skill-maintainer`: produce evidence-backed proposals without overwriting source skills.
- `skill-compressor`: reduce instruction size while preserving required behavior.

Collection, event processing, and report helpers are optional Watcher runtime
content at `$ATM_HARNESS_ROOT/runtimes/watcher`. This plugin contains no automatic
hooks. Installing skills or preparing Python does not authorize hook activation;
use the explicit ATM hook command when requested.

For runtime commands set `ATM_PAYLOAD_PYTHON` to the exact prepared interpreter
recorded in the runtime receipt, then run `"$atm_tooling_python" -B scripts/watcher`
from the runtime directory after assigning `atm_tooling_python="$ATM_PAYLOAD_PYTHON"`.
The `maintenance-validation` group includes the hash-locked PyYAML dependency
needed by proposal and candidate validation helpers. Static skills need no Python.

Stable attribution remains `watcher:doc-alignment`, `watcher:housekeeping`,
`watcher:skill-maintainer`, and `watcher:skill-compressor`. The Rust canonical catalog
maps the current `maintenance:*` selectors and earlier `doc-watcher:*` /
`skill-watcher:*` names to those identities. Historical logs and reports are not
rewritten. `.codex-plugin/skill-watcher.json` supplies attribution metadata only.
