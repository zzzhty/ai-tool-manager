# Watcher runtime

Watcher is optional hook/runtime content, with no callable skill entries.
The interactive doc-alignment, housekeeping, skill-maintainer, and skill-compressor
workflows live in the maintenance plugin. Their durable `watcher:*` attribution
identities remain unchanged; current `maintenance:*` selectors map to them.

## Runtime and catalog contract

ATM Rust validates and pins payload content, prepares only the selected Python
dependency group, and owns hook configuration changes. Importing this runtime or
preparing its interpreter does not enable hooks. Use `atm install hooks --harness
codex` or `atm uninstall hooks --harness codex` explicitly; this Python CLI has no
hook installation or uninstallation entrypoint.

`SessionStart` reads `canonical-catalog.json` from the explicit `--repo-root` /
`ATM_HARNESS_ROOT` payload root. Snapshot schema version 1 contains stable skill
identities, current source paths, source identity, aliases, and embedded attribution
overlays. Missing or unsupported snapshots fail clearly. Watcher does not import
an installer, scan an entire repository, or read plugin caches to enumerate skills.
The snapshot refreshes runtime metadata; historical JSONL logs remain unchanged.

Attribution overlays retain roles, aliases, supporting-skill relationships, logical
groups, and historical mappings. Declare supporting skills only for unconditional
dependencies; reports apply grouping at read time. Preserved unknown historical
identities remain visible rather than being silently dropped.

Hook observation, reports, and doc audits use the Python standard library. Explicit
maintenance proposals and candidate validation use the separate
`maintenance-validation` group and `requirements-maintenance.lock` (PyYAML 6.0.3,
wheel hashes for CPython 3.11–3.14). The hashes come from the local cached PyPI index;
wheel availability is checked by the Rust runtime preparer. No interpreter is
automatically downloaded, and no project or global Python environment is modified.

## Commands

Set `ATM_HARNESS_ROOT` to the verified payload root and `ATM_PAYLOAD_PYTHON` to the
exact prepared interpreter from its runtime receipt. Run from
`$ATM_HARNESS_ROOT/runtimes/watcher`; on Windows pass the explicit interpreter path
as one argument. `ATM_WATCHER_AUDIT_ROOT` selects the target Git worktree for the
example audit config and is separate from the catalog payload root.

```bash
atm_tooling_python="${ATM_PAYLOAD_PYTHON:?set explicit prepared payload interpreter}"
"$atm_tooling_python" -B scripts/watcher doc report --config config/repos.example.json --print-report
"$atm_tooling_python" -B scripts/watcher skill report --since 7d
"$atm_tooling_python" -B scripts/watcher skill propose --skill watcher:doc-alignment --skill-dir <actual-skill-source> --since 7d
"$atm_tooling_python" -B scripts/watcher skill doctor --repo-root "$ATM_HARNESS_ROOT"
"$atm_tooling_python" -B scripts/watcher migrate-state --dry-run
```

`skill propose` needs the exact log identity and window; use `--report` only for a
matching summary. It writes a worksheet and separate candidate path, never source
skill changes. Materialize an authorized candidate before running validation;
proposal generation itself does not validate it. Logs are untrusted evidence.

`skill doctor` inspects the snapshot and configured hooks without changing runtime
state; its smoke events use a temporary directory. `$CODEX_HOME/watcher` remains
logs/reports/runtime state and is preserved when the hook is removed.

Doc audit configs may define multiple named profiles for one repository. Keep current authority,
generated/upstream site, and history scopes separate:

- use `profile: "current-authority"` with explicit `docs`, `authority_paths`, active
  `watch_terms`, and `link_validation.mode: "markdown-relative"`;
- use `profile: "upstream-site"` with the repository's owner checker through
  `link_validation.mode: "owner-command"` instead of applying generic Markdown rules to a
  framework-specific route or asset dialect;
- use `profile: "history"` with `finding_policy: "report-only"` and no active watch terms.

Treat `owner-command` as trusted, unsandboxed execution. Watcher invokes its argv without a
shell, keeps its configured working directory inside the repository, enforces a timeout, and
bounds captured output, but cannot prove that the command is read-only. Review the
repository-owned validation workflow before configuring it.

`authority_paths` is an existence check for configured authority entry points. It does not prove
semantic equality or precedence between documents. The legacy `source_of_truth` config key remains
read-compatible but is deprecated. `check_change_alignment: false` disables the code-without-doc
heuristic for profiles where that comparison is not meaningful.

### Repository skill-root discovery

When `docs` is omitted, Watcher scans the normal entry files and documentation directories plus the
first existing repository skill root in this default priority order:

1. `.agents/skills`
2. `.codex/skills`
3. `.github/skills`
4. `.claude/skills`
5. `.grok/skills`

Watcher checks each complete skill directory, so an empty `.agents/` parent does not shadow an
existing fallback such as `.codex/skills`. Profiles may override the order with a non-empty
`skill_root_candidates` string list. The one-off audit CLI provides the repeatable
`--skill-root-candidate` option for the same purpose.

Use `@repo-skills` as a semantic path in configured `docs` and as a prefix in
`authority_paths`. For example:

```json
{
  "docs": ["AGENTS.md", "@repo-skills"],
  "authority_paths": ["AGENTS.md", "@repo-skills/README.md"]
}
```

The token resolves per repository from the ordered candidates. Ordinary configured paths stay
fail-closed: a literal stale `.codex/skills` path is reported missing and is not silently redirected.
If multiple candidate roots exist, Watcher reports the selected root and the shadowed roots and emits
a Medium finding when the resolved skill scope participates in that profile. A resolved-root change
also changes the effective config hash so commit-dependent audits become due immediately.

This resolver does not locate the Watcher config file itself. A moved
`.codex/watcher-doc-audit.json` still requires the caller's `--config` path to be updated.

Run `"$ATM_PAYLOAD_PYTHON" -B scripts/watcher migrate-state --apply` only when that explicit state migration is authorized to move `$CODEX_HOME/skill-watcher/` to `$CODEX_HOME/watcher/skill/` and `$CODEX_HOME/doc-watcher/` to `$CODEX_HOME/watcher/doc/`. The migration refuses to merge if the target already exists.
