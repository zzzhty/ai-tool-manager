# Read-only public CLI release readiness

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

## Scope

Candidate against `47799a71424500dc6dea9ca09c0e215fa7cb902b` (VERSION remains 1.0.0).
No release, tag, merge, installed-user migration, plugin identity change, or upstream skill-content change is included.

- Public status/version/check/doctor skip mutation locking and runtime bootstrap.
- An existing interpreter is probed without bytecode writes. Missing/unstartable runtime, wrong venv prefix, unsupported Python, or missing imports produces a nonzero error and repair guidance; JSON diagnostic commands produce a structured preflight error.
- Command traces and bootstrap progress use stderr; successful status/version JSON stays parseable.
- Install/refresh/remove previews avoid the creating ManagerLock. Public previews propagate no-bytecode and no-optional-Git-lock settings.
- Concurrent observations are not guaranteed to be an atomic installation snapshot.
- Update `--check` still fetches remote metadata; it is deliberately outside the no-write preview contract.

## Validation

Linux, Python 3.12.14, isolated temporary HOME/USERPROFILE; no network installation required.

- Full command: `HOME="$ISO_HOME" USERPROFILE="$ISO_HOME" PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_*.py' -v`
- 317 tests: 309 passed, 7 Windows-only skips, 1 pre-existing host-sensitive failure.
- Failure: `test_manager_environment.UserEnvironmentTests.test_shell_execution_quotes_paths_and_deduplicates_entries` with zsh and initially empty PATH. The host zsh supplies `/usr/local/bin:/usr/bin:/bin:/usr/games`, violating the test's empty-PATH expectation. The same failure reproduces from a clean `git archive origin/main` baseline running only `test_manager_environment.py` (13 tests, 1 failure).
- All nine new real public-launcher tests pass on Linux, including no-write snapshots of the entire isolated user tree (file bytes, mode, mtime, directories and symlinks), help/option abbreviations, absent/held manager locks, valid JSON, explicit runtime failures, and failing harness validation. The suite now uses native launchers on Windows too, rather than skipping that platform.
- Re-review reproduced a mutation with the valid global `--ho` / `--hom` home-option prefixes. Normalize these (including `=PATH` forms) before command dispatch; regression coverage checks pure JSON and unchanged files for all supported home spellings.
- Watcher suite: 86 tests, 83 passed and 3 platform skips. Workflow suite: 94 tests passed. Compile checks and distribution identity validation passed.
- `python -m json.tool` succeeds for marketplace, install manifest, harness registry and registry schema.
- Repository plugin validation passes for watcher, workflow and mattpocock-skills; no packaged content changed.
- `git diff --check` passes.

## Remaining gates

- Verify the final PR head's six-platform/Python matrix, including the newly enabled Windows public-launcher tests. The PR description records the live CI result; the local results above do not substitute for Windows execution.
- Resolve or explicitly accept the baseline host-zsh test limitation before claiming a completely green release suite.
- Final merge and release remain separate decisions. Existing installed launchers only receive the changed bootstrap through the normal managed update/repair distribution process.
