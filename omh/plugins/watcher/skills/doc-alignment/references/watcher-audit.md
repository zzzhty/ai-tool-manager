# Watcher Doc Audit

Trigger: read this reference for configured, scheduled, commit-dependent, or one-repository Watcher document audits. `../SKILL.md` remains the owner of mode selection and the read-only boundary.

## Select The Evidence Branch

If a current report already exists and no fresh audit was requested, review it directly under Report Review; do not generate or run fresh audit commands. Check its repository, revision or time window, profiles, and coverage against the requested scope, and disclose stale or missing evidence.

Otherwise follow Fresh Audit, then review the resulting report.

## Fresh Audit

Before running config-driven commands, set `OH_MY_HARNESS_ROOT` to the
canonical Git worktree. The example config consumes that explicit root so the
same audit remains valid from the source plugin or an installed plugin cache.

From the Watcher plugin root, start with deterministic evidence:

```bash
omh_tooling_python="${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}/venv/bin/python"
"$omh_tooling_python" -B scripts/watcher doc doctor --config config/repos.example.json
"$omh_tooling_python" -B scripts/watcher doc report --config config/repos.example.json --mode commit-dependent --mark-audited --digest
```

Run `scripts/watcher doc commit-counter` only when a separate threshold-status preview is needed; `doc report` computes eligibility itself.

Use `config/repos.json` when an approved private config exists. For one repository:

```bash
"$omh_tooling_python" -B scripts/watcher doc audit --repo <repo-path> --name <repo-name> --print-report
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
