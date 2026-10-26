# Installer recovery (PR #21)

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

Scope: complete the explicit installer repair/reinstall entry point and merge
PR #21 after validation, following the user's subsequent merge request. The real
managed installation is not a test target; managed activation remains separate.

## Plan

1. Classify fresh, incomplete, ready and legacy-ready installs in shared Python;
   require a deliberate repair/reinstall choice for ready installs.
2. Reuse the manager bootstrap, locking, update recovery and harness closure.
   Preserve immutable receipts, desired policy, unknown files and user data.
3. Cover both public wrappers, cancellation, invalid ownership/state, legacy
   current-revision migration, exact incomplete recovery and reinstall failure.
4. Align README/ADR, remove the PR's temporary snapshot workflow, run affected
   checks and record coverage here.

## Contract inventory

- Public installer flags (`--repair`, adoption and fast-forward flags): preserve
  identities; make repair explicit and add mutually exclusive `--reinstall`.
- `state/install.json`: immutable persisted initial receipt; only the original
  `installing` to `ready` completion may write it.
- `manager.json` / `desired.json`: existing persisted lifecycle owners and schema;
  preserve current values. A legacy ready install has neither; derive them from
  its verified current managed checkout, never the invoking checkout or old SHA.
- Managed paths, launchers, update journal and ownership checks: retain existing
  identities and contracts. Reinstall stays at the recorded revision and uses
  existing recovery owners, with replaced managed components backed up.

## Progress

- PR fetched at `a42079ec8a056dc5f1537fbd9f05a7bb84b78898`; only a temporary
  snapshot workflow was present. Development and managed checkouts were clean.
- Found automatic repair bypassing incomplete-install validation and repair
  rewriting ready install receipts. Both are in the implementation scope.
- Local implementation complete: explicit selection; strict incomplete recovery;
  current-revision legacy migration; exact-version reinstall with checkout/runtime
  backups; receipt/policy preservation; read-only previews including import caches.
- Removed the temporary snapshot workflow. README and ADR 0017 describe the
  resulting behavior. PowerShell relies on persisted user PATH and reopening the
  terminal, so help/cancellation cannot alter session PATH.

## Validation (2026-09-20, macOS / Python 3.13.15)

Use `$HOME/.oh-my-harness/venv/bin/python -B` with
`PYTHONDONTWRITEBYTECODE=1`. All runs use disposable manager homes; the actual
managed checkout remains clean and was not activated or changed.

- Root unittest discovery: 305 tests, 6 platform skips, no failures, before the
  final recovery-boundary refinements. Unaffected results remain applicable.
- Final affected coverage: `test_installer_recovery*.py` (18 tests),
  `test_install_oh_my_harness.py` (27 tests, 2 skips),
  `test_manager_commands.py` (11 tests), and `test_install_wrappers.py`
  (4 tests, 2 skips): 60 tests total, 4 platform skips, no failures.
- Public integration exercised initial install, repair, reinstall, missing-repo
  recovery, legacy migration, public `omh check`, exact-revision retention and
  preservation of unrelated skills, receipt, policy and backup contents.
  Dependencies were provisioned offline into real disposable venvs; this is not
  evidence of a live pip/network installation. Managed-checkout dry runs were
  also exercised without `PYTHONDONTWRITEBYTECODE` to verify no import caches.
- `git diff --check` and `sh -n install.sh` passed.
- Native Windows/PowerShell and Linux execution remain unverified for this diff;
  the existing lifecycle CI matrix owns those checks after publication.

## Handoff

The implementation is on `fix/installer-repair-reinstall`, based on PR #21's
`a42079e`. The first requested publication/closure completed at `e1d696e` without
merge. The user subsequently requested merging: PR #21 was reopened and marked
ready, and native CI must pass before merge. Keep the feature branch and leave
the managed installation at its existing revision.

## Native CI follow-up

Run `35506973784` on `e1d696e` passed both macOS configurations and Ubuntu/Python
3.12, but failed Ubuntu/Python 3.11 and both Windows configurations.

- Windows: the missing-checkout fixture used `shutil.rmtree` on read-only Git
  objects. Move the disposable checkout aside instead, preserving the same
  missing-path scenario without platform-specific deletion.
- Windows: redirected empty input reached the interactive recovery prompt and
  returned successful cancellation. Require `GetConsoleMode` to establish a real
  Windows input console; CRT `isatty()` can accept the NUL character device.
- Ubuntu/Python 3.11: Git's local-path clone failed copying a loose object with
  `No such file or directory`. The precise trigger is unconfirmed. Use a local
  `file://` Git transport for this fixture, retaining real offline clone/recovery
  behavior while removing the failing direct-copy path. Native rerun is required.

Local affected tests pass; native validation of these fixes is pending.
