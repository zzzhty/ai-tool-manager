# Watcher Doc Audit

Trigger: read this reference for configured, scheduled, commit-dependent, or one-repository Watcher document audits. `../SKILL.md` remains the owner of mode selection and the read-only boundary.

## Select The Evidence Branch

If a current report already exists and no fresh audit was requested, review it directly under Report Review; do not generate or run fresh audit commands. Check its repository, revision or time window, profiles, and coverage against the requested scope, and disclose stale or missing evidence.

Otherwise follow Fresh Audit, then review the resulting report.

## Fresh Audit

Set `ATM_WATCHER_AUDIT_ROOT` to the target Git worktree for the example config.
Keep `ATM_HARNESS_ROOT` bound to the verified ATM payload root containing the
canonical catalog; it does not select the repository being audited. Use the
optional Watcher runtime at `$ATM_HARNESS_ROOT/runtimes/watcher` and the exact
prepared payload interpreter from its receipt. Preparing a runtime does not
enable hooks. From the Watcher runtime directory, start with deterministic evidence:

```bash
atm_tooling_python="${ATM_PAYLOAD_PYTHON:?set explicit prepared payload interpreter}"
"$atm_tooling_python" -B scripts/watcher doc doctor --config config/repos.example.json
"$atm_tooling_python" -B scripts/watcher doc report --config config/repos.example.json --mode commit-dependent --mark-audited --digest
```

Run `scripts/watcher doc commit-counter` only when a separate threshold-status preview is needed; `doc report` computes eligibility itself.

Use `config/repos.json` when an approved private config exists. For one repository:

```bash
"$atm_tooling_python" -B scripts/watcher doc audit --repo <repo-path> --name <repo-name> --print-report
```

When commit-dependent report skips a repository, record it as skipped. Configuration changes can make a repository due below its commit threshold. A normal repository audit covers its configured profile set; use a profile selector only for an explicit narrow run and do not treat unselected profiles as disabled. If any repository fails, surface the repository, command or path, and exact failure text.

## Profiles And Trust Boundary

Use repository-owned named profiles when current authority, framework-owned site documentation, and history need different checks:

- current authority: active watch terms plus generic Markdown-relative link validation;
- framework-owned site documentation: its owning validator through `owner-command`;
- history: `report-only` findings with no active watch terms.

`owner-command` is trusted, unsandboxed execution. Watcher constrains its working directory, timeout, and captured output, but it cannot prove the command is read-only. Inspect the repository-owned workflow before enabling it.

Configured `authority_paths` prove only that named entry points exist. They do not prove semantic precedence or equality. Keep change-alignment checks enabled when recent code changed without relevant docs; disable them only when that comparison is intentionally meaningless for the profile. The review workflow in `../SKILL.md` still decides alignment.

## Report Review

Review reports for:

- stale active guidance or history mixed into current navigation;
- mismatched product, command, path, identity, ownership, or validation terms;
- recent behavior changes without current documentation;
- active watch-term hits;
- broken links and missing referenced files;
- resolved skill-root selection and shadowing when repository skill roots participate in the profile.

Completion criterion: apply the selected evidence branch below.

- **Existing report review:** record the report source, applicability, findings, and coverage gaps. No new doctor or audit run is required; do not claim fresh verification.
- **Fresh audit:** doctor and the selected audit/report command complete or their exact failures are recorded; every due or skipped repository is accounted for, and profile trust boundaries are explicit.

Both branches hand findings to the common review workflow and preserve its target-repository read-only boundary.
