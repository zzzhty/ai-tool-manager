# Current Docs And Close

Use only when entering Close. `../SKILL.md` owns supersession, execution authority, runtime hard stops and native goal-tool boundaries. For direct or resumed Close, apply the matching pre-implementation/resume preflight, readiness and authorization checks in `execute-and-close.md`; close routing does not waive them. If Close creates task-temporary data for the first time, apply that reference's recorded-root binding rule before any producer writes.

After creating, upgrading, or evolving a goal, update only the current docs that need concise pointers: active TODO/goal index, development/runtime/status docs, boundary registers, validation logs, or runtime test checklists. Keep detailed milestone plans in the goal file.

When all milestones are done:

1. Apply any deferred approval gate for Close before entering its work. Then mark the Close row `In Progress` and keep the overall goal `In Progress` while preparing close evidence.
2. Fill close execution evidence before removing or archiving the active goal.
3. Sync durable outcomes into current docs, indexes, validation logs, and status/boundary registers.
4. Apply the recorded task-temporary-cache outcome without re-resolving the platform temp root:
   - `None created` or `Not applicable`: record explicitly that no roots were created; do not invoke cleanup or invent size metrics.
   - concrete roots plus `Enabled`: confirm durable evidence is outside the recorded roots, then invoke `watcher:housekeeping` to inventory and clean only confirmed owner-specific disposable candidates. Do not replace it with raw recursive deletion, escalate privileges, cross symlink/junction/reparse-point boundaries, or delete dependencies, runtime state, logs, reports, unknown producers, or locked content. Record the policy, every exact root, the watcher action, and removed, preserved, failed, and residual sizes; safety-preserved residuals do not imply failure unless zero residue was separately confirmed in preflight.
   - concrete roots plus `Disabled`: do not clean; record the policy, every retained exact root, and the retained/preserved action. Size metrics are optional; omit them or record `unknown` with a brief diagnostic when measurement is unavailable. Do not scan retained trees solely to satisfy Close.
   - missing legacy field/section: treat cleanup as unauthorized, preserve any discovered roots, and record the legacy disposition without rerunning the full grill.
   If `watcher:housekeeping` is unavailable for an enabled policy, keep Close and the overall goal `In Progress`, or use `Blocked` only when the normal runtime hard-stop contract is met. Report the missing capability and do not fall back to `rm -rf`, PowerShell recursive deletion, or another raw delete command. Continue as `Disabled` only after the user explicitly evolves the recorded preflight policy.
5. Follow local archive conventions; do not invent dated archive trees or checked-in closed copies just to preserve history.
6. Remove closed goals from active navigation, or archive/delete the goal file according to local convention.
7. Validate index topology with `check_todo_index.py --mode closed --archived-goal <archive-path> <old-active-path> <index>...` after archiving, or `--mode absent <old-active-path> <index>...` after deletion without an archive.
8. Run `git diff --check -- <changed-paths>` and `check_md_links.py` when Markdown links changed.
9. Apply [the checkpoint component](../components/checkpoint.md) in full and record close checkpoint evidence. When its selected type is `git commit`, use the local close commit format, such as `<goal_slug> close: <summary>`.
10. Only after every close gate and evidence check passes, set the Close row to `Done/Passed/Done` and the overall goal status to `Closed`.

Completion criterion: every milestone is `Done`, close evidence and validation are recorded, the explicit or legacy task-temporary-cache disposition is recorded, durable current docs are synchronized, active navigation no longer points to closed work, and archive/delete handling follows local convention.
