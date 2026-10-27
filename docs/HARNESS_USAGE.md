# Harness content and manager workflow

ATM installs versioned OMH content through the Rust distribution service. It
supports inert import, explicit source selection, preview/apply, owned runtimes
and recovery. It does not maintain a skill Hub or an independent Python installer.
`content/omh.lock.json` pins the release; target paths come from `policy/harnesses`.

For a source checkout run `python scripts/Prepare-Content.py` before tests or
packaging. This builds `atm-cli` and uses its locked fetch/validator to materialize
ignored `harness/`. Existing complete content works offline. An unexpected or
stale destination is refused; preserve it and prepare the new payload in an empty
location instead of silently overwriting it. Portable releases retain CLI, desktop
and the verified offline payload together.

```sh
atm harness bootstrap
atm harness plan install --harness claude-code,codex
atm install skills --harness claude-code,codex
atm check skills --harness claude-code,codex --strict
atm harness status
atm harness -- doctor
```

`bootstrap --source /absolute/payload` and `sync --source /absolute/payload` select
a verified source. Neither applies client files nor invokes Python. `update skills
--harness ...` reconciles selected targets and refuses edited or foreign files.
`uninstall skills --harness ...` removes only recorded ownership. Local skill
commands without `--harness` continue to protect distribution-owned resources.

To import a reviewed lock use `harness import --lock /absolute/omh.lock.json`, with
`--archive /absolute/omh.omh` for a local artifact. Import creates only inactive
cache. The content contract is in [OMH_CONTENT_CONTRACT.md](OMH_CONTENT_CONTRACT.md).
Python helper groups require explicit `harness runtime prepare <group> --python
/absolute/interpreter`; `--offline` uses existing hash-locked wheels. No project or
global environment is owned by ATM. Skill-watcher hooks cannot be enabled;
`uninstall hooks --harness codex --dry-run` previews exact receipt-based retirement.
Historical logs and unrelated hooks remain intact.

## Explicit manager-home handoff

First back up the current manager, affected client files and shell references to
an independent private location. `migrate` requires an absent destination, or the
same incomplete reservation from an earlier attempt. It refuses overlap, changed
receipts, target-root drift, edited files, active old hooks and external runtimes.
All currently recorded targets move together; it does not discover new targets.

```sh
atm harness migrate --home /absolute/old-home --to /absolute/new-home \
  --source /absolute/verified/payload --dry-run
atm harness migrate --home /absolute/old-home --to /absolute/new-home \
  --source /absolute/verified/payload --python /absolute/base-python --offline
```

The preview writes nothing. Apply reserves the destination without an active
receipt, caches content and rebuilds exactly the recorded runtime groups at their
final paths. It preserves old environments and copies available offline wheels;
selected dependency hashes are still enforced. Failed preparation leaves inactive
reusable destination state and the original owner intact.

One existing journal at the destination then marks the source retired, reconciles
client references, removes its old active receipt and publishes the new receipt.
The destination `state/relocation.json` retains the original receipt and source
path. `state/relocated.json` blocks further changes through the old manager.
Cross-file visibility is journaled, not claimed to be fully atomic. Ordinary
operations refuse an incomplete destination; recover explicitly with
`atm harness recover --home /absolute/new-home`, which locks both managers and
preserves any post-crash user edits for manual resolution. Do not delete journals.

After successful receipt, repeat-plan and explicit interpreter checks, switch the
proven shell `ATM_HOME` reference to the new path. Archive the old manager outside
its former active location; do not rename its venvs into the new manager or leave
an alias owner behind. A stale shell pointing to the former home is refused using
the canonical `.atm` owner's retained handoff record; start a new login shell.
Keep the independent backup and historical logs. A rollback
requires restoring the consistent backed-up manager/client/shell set; starting an
old binary against new state is not rollback.

Disk distribution, fresh-shell command resolution and helper health are separate
from actual client loading/invocation. Do not enable hooks to test loading.
