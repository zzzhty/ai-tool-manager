---
status: accepted
---

# Make `omh` the post-bootstrap lifecycle manager

The explicit installer recovery adapter in [ADR 0017](0017-explicit-installer-recovery.md)
extends the bootstrap-only entry-point boundary below; lifecycle authority stays
with the manager.

`install.sh` and `install.ps1` are standalone bootstrap-only entry points. When
a companion Python installer is unavailable, they may clone a temporary
bootstrap checkout from the canonical HTTPS repository or the explicit
`--repository` and `--ref`, then invoke that checkout's installer with the
original arguments. The temporary checkout is an acquisition adapter, is
removed after invocation, and never becomes lifecycle authority. The Python
installer may create the manager home, clone the first managed checkout,
install the stable bootstrap shim, build the tooling environment, write
launchers, and invoke the initial `omh install`. After that point, all supported
lifecycle mutation is owned by `omh`.

The public harness lifecycle is:

```text
omh install [HARNESS...]
omh refresh [HARNESS...] [--repair]
omh remove HARNESS... | --all
omh update [--check] [--channel stable|main] [--to REF]
```

`install` adds a harness to desired state after successful materialization.
`refresh` reconciles the current local release without fetching remote source.
`refresh --repair` is the explicit same-version re-materialization path and may
repair content-identity drift that ordinary refresh correctly rejects. `remove`
deletes only resources whose ownership can be proven and removes the harness
from desired state. `update` is the only normal command that fetches manager
source; it validates the target distribution identity in an isolated worktree,
switches the managed checkout, re-enters the new CLI after rebuilding tooling,
refreshes every desired harness, and rolls back the checkout and distribution if
the new revision cannot close.

The manager namespace owns self-lifecycle:

```text
omh manager repair
omh manager uninstall
```

`manager repair` reconstructs the recorded checkout before rebuilding tooling,
launchers, and desired harnesses. `manager uninstall` requires an empty desired
set unless `--with-harnesses` is explicit, validates the bounded manager-home
shape, and schedules deletion through the external bootstrap interpreter so
Windows does not need to delete the running Python environment in place.

`state/install.json` remains the immutable initial-install lifecycle receipt.
Rolling state lives beside it:

```text
state/
├── install.json
├── manager.json
├── desired.json
├── harnesses/
├── operations/
└── manager.lock
```

`manager.json` records the current repository/revision/release/bundle/channel.
`desired.json` owns the installed harness set and update policy. Per-harness
receipts are written only after closure. Mutating commands share one
cross-process manager lock. An update writes an operation journal before
checkout mutation; a failed rollback leaves that journal in a degraded phase and
blocks normal interpretation until `omh recover` is run.

The generated public launchers execute a manager-home bootstrap shim rather than
the repository wrapper directly. The shim is standard-library-only, keeps
`omh --help` available without rebuilding tooling, repairs the tooling environment
before lifecycle execution, and can reconstruct a missing managed checkout for
`omh manager repair` from the recorded repository and revision. Repository
`upgrade_oh_my_harness.sh/.ps1` wrappers remain legacy
compatibility surfaces but are no longer the public launcher authority.

Installation and lifecycle execution require Python 3.11 or newer. The external
installer and stable bootstrap shim enforce this before manager-home, checkout,
or tooling-environment mutation, while the top-level help path remains available
under an older standard-library Python. The minimum supported version is part of
the lifecycle CI matrix rather than an untested launcher assumption.

No-subcommand `omh` remains a compatibility alias for `omh refresh`. New scripts
and documentation must use explicit subcommands.
