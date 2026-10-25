# Conditional Alignment Reference

Read only the sections triggered by the target named in `../SKILL.md`. The entry skill owns mode selection and audit safety. This reference owns classification, surface-specific alignment, severity, reporting detail, and validation selection. In report-only mode, use the alignment rules as audit criteria: record unmet conditions and recommendations without repairing targets. In implementation mode, satisfy the affected alignment rules and required checks before claiming completion.

## Review Inventory And Classification

Inventory the target and references. Prefer `rg`:

```bash
rg --files <target>
rg --hidden -n "<old-term>|<old-path>|<disputed-term>" <target> . --glob '!**/.git/**' --glob '!**/node_modules/**'
```

Read entry points first: `AGENTS.md`, root and area READMEs, current development, usage, operations, architecture and validation guides, package commands, devcontainer and CI files, runbooks, subdirectory indexes, active plans, skill metadata, and relevant Watcher reports.

Classify each file by its live role:

- **Overview**: current navigation and execution posture.
- **Guide**: current commands and expected environment.
- **Architecture / Contract**: ownership, relationships, wire shapes, and compatibility boundaries.
- **Validation / Audit**: commands, pass signals, and active blockers.
- **Template**: reusable skeleton without real task state.
- **TODO / Goal**: unfinished work, ordered milestones, or planned cleanup.
- **Archive**: dated or replaced material only.
- **Script / Runner**: executable entry point with a stable, discoverable name.
- **Skill**: reusable agent procedure with trigger metadata, instructions, and direct resources.

Align recursively: keep root docs as current posture plus links, select one typed owner for detail, use the same owner terms in active docs, move replaced evidence to the existing archive, and keep unresolved future work in the active planning location.

Classify findings:

- `High`: active guidance contradicts current truth, routes users to broken commands, links to missing required files, or describes removed workflows.
- `Medium`: stale terminology, missing docs for recent behavior, duplicated guidance, unclear ownership, or active watch-term hits.
- `Low`: cleanup-only wording drift, minor index issues, archive labeling, or future polish.

Each finding needs paths or command evidence, reasoning, severity, and a bounded next action. Final reporting identifies reviewed entry points, changed or proposed semantics, moves, archives, renames or preserved history, exact validation, unresolved conflicts, and legacy identifiers.


## Script And Entry-Point Naming

Follow local convention first. Without one, prefer short verb+noun names such as `run_tests.ps1`, `check_runtime.sh`, `start_proxy.bat`, or `sync_docs.py`.

Keep directory naming consistent:

- runtime checks: `check_<target>`
- startup helpers: `start_<target>`
- bootstrap helpers: `bootstrap_<target>`
- cleanup helpers: `clean_<target>`
- sync helpers: `sync_<target>`

Avoid names that encode old product semantics, local machine details, or implementation accidents. After renaming, update wrappers, package commands, `.devcontainer`, CI/workflow config, `.github`, the resolved repository skill root, README/runbook examples, and child runner calls. Preserve executable bits and validate syntax with the owning shell/runtime.


## Documentation Tree Alignment

1. Root docs are current overview and execution entry points only.
2. Architecture, API contracts, deployment, validation, runtime audit, templates, TODO plans, and archives belong in typed subdirectories when that structure exists.
3. Archives may keep old terms; active docs must not present deprecated, duplicate, or compatibility-only surfaces as product semantics.
4. If active docs mention old user-facing terms, replace them or explain the real code field, test, migration, compatibility boundary, or archive context.
5. Keep reusable templates free of concrete task state.


## Planning/TODO Tree Alignment

1. Active index files are navigation and execution posture, not completed checkpoint history.
2. Active TODO/goal files contain next actions, gates, and close criteria. Archive completed evidence, historical checkpoint logs, and replaced plans.
3. Archives may keep historical names, old conclusions, and prior metrics. Do not rewrite archive content unless the archive index or summary is wrong.
4. Open editor tabs, stale filenames, and old goal docs are not source of truth. Compare them against current code, docs, and active indexes before deleting, archiving, or reactivating them.
5. Before deleting an old TODO, verify whether the underlying code path or failure mode still exists. If it does, keep it active or rewrite it as a current next-step item.
6. When closing a goal, remove it from active navigation, update the archive entry, and keep residual/future work as a separate active item.

Use the helper when it fits:

```bash
"${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}/venv/bin/python" -B <skill-folder>/scripts/check_planning_tree.py <planning-root>
```


## Skill Alignment

For agent skills:

1. Use the skill-creation/update workflow as companion truth for resource layout, `agents/openai.yaml`, and validation, subject to the target's owning invocation contract.
2. Preserve the target skill's current invocation mode unless the user explicitly requests a change.
3. For a model-invoked skill, omit `disable-model-invocation` and put every distinct model trigger branch in `description`.
4. For a user-invoked skill, preserve `disable-model-invocation: true` and keep `description` to a human-facing one-line summary rather than a trigger list.
5. Preserve other supported frontmatter interface fields, such as an owning `argument-hint`, when the target contract uses them.
6. Keep bodies imperative and procedural. Remove process history, repo-only assumptions, and redundant explanation.
7. Refer to bundled resources relative to the skill folder.
8. Prefer generic placeholders plus examples over repo-specific paths, unless the path is intrinsic.
9. Inspect and update `agents/openai.yaml` when display name, short description, default prompt, or invocation policy no longer matches.
10. Keep cache/build artifacts such as `__pycache__`, bytecode, temp validation output, and generated logs unchanged unless explicitly asked.
11. Validate with the skill validator when available.

When aligning multiple skills, process them in user order or foundational-first; finish and validate a dependency skill before its dependents; keep trigger descriptions distinct; move shared generic rules only when both skills need them; avoid duplicated validation snippets when scripts or helpers cover them; finish with a cross-skill stale-reference, obsolete-term, and broken-link check.


## Validation

Match validation to the changed surface. For docs and skills:

```bash
git diff --check -- <changed-paths>
```

If changed skills are outside the current Git worktree, say `git diff --check` is not applicable for those paths and validate the actual skill paths directly.

If Markdown moved or links changed, run a relative-link check scoped to the changed tree. Report every missing local target with file and line; ignore anchors, `http(s)`, `mailto`, and empty targets.

For script renames, use the owning parser and stale-reference scan:

```bash
bash -n <script>.sh
powershell -NoProfile -Command { [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw -LiteralPath '<script>.ps1'), [ref]$null) > $null }
rg --hidden -n "<old-script-name>|<old-path>" . --glob '!**/.git/**' --glob '!**/node_modules/**'
git diff --check -- <changed-paths>
```

Add lightweight dry-runs or `--summary` commands when entry points provide them. Do not run heavyweight runtime suites for naming-only alignment unless behavior or gates changed.

For Watcher doc-domain validation:

Set `OH_MY_HARNESS_ROOT` to the canonical Git worktree before using the example
repository config; do not infer repository authority from the plugin cache
location or current working directory.

```bash
omh_tooling_python="${OH_MY_HARNESS_HOME:-$HOME/.oh-my-harness}/venv/bin/python"
"$omh_tooling_python" -B scripts/watcher doc doctor --config config/repos.example.json
"$omh_tooling_python" -B - <<'PY'
from pathlib import Path

for source in Path("scripts/watcher_runtime").rglob("*.py"):
    compile(source.read_bytes(), str(source), "exec")
PY
omh_system_validator="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/validate_plugin.py"
omh_system_identifier="${CODEX_HOME:-$HOME/.codex}/skills/.system/plugin-creator/scripts/identifier_validation.py"
if [ -z "${PLUGIN_VALIDATOR:-}" ]; then
    if [ -f "$omh_system_validator" ] && [ -f "$omh_system_identifier" ]; then
        PLUGIN_VALIDATOR="$omh_system_validator"
    else
        PLUGIN_VALIDATOR="${OH_MY_HARNESS_ROOT:?set OH_MY_HARNESS_ROOT}/scripts/validate_plugin.py"
    fi
fi
"$omh_tooling_python" -B "$PLUGIN_VALIDATOR" .
```

If a dependency is missing, install it only when allowed; otherwise report the exact module and do not claim validator success. Manual frontmatter/link checks are partial checks, not validator substitutes.
