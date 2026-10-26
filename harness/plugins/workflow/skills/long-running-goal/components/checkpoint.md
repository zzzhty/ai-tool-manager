# Checkpoint Component

Use this component before marking any milestone or close step `Done`.

A checkpoint is required at every milestone boundary, but it is not always a new Git commit.

## Entry Conditions

Apply this component after the milestone review gate and validation commands have passed, and before changing the milestone status to `Done`.

## Required Flow

1. Confirm the milestone scope and validation evidence are recorded in the goal file.
2. Inspect the repository state with `git status --short` when the workspace uses Git.
3. Identify the changed files that belong to the current milestone.
4. Exclude unrelated dirty files from staging or revision evidence and record them. If they affect validation, rollback, or evidence, first isolate milestone work through authorized means while preserving user work and every required check. Stop only when that separation cannot be achieved without changing unrelated work or weakening those guarantees.
5. Choose the checkpoint type:
   - `git commit`: use when the project uses Git and the goal, user, or local workflow expects milestone commits.
   - `current HEAD`: use when Git is active but no milestone file changes remain to commit.
   - `artifact revision`: use when the durable evidence is a report, generated artifact, issue, task history, or document revision.
   - `not applicable`: use only when no version-control or equivalent durable revision exists.
6. For `git commit`, stage only milestone-scoped changes and inspect the full pending commit, including previously staged changes. Preserve unrelated staged work outside the commit; stop if the intended changes cannot be committed separately. Use the goal's recorded commit-message format, such as `<goal_slug> M<N>: <summary>`.
7. Do not create an empty commit unless the user or goal explicitly requires a marker commit.
8. Record the final revision evidence in the goal file.

## Output Evidence

Each milestone checkpoint must record:

```text
Checkpoint component: Done
Checkpoint type: <git commit / current HEAD / artifact revision / not applicable>
Revision: <commit hash / HEAD hash / artifact path / issue or task revision / n/a>
Changed files: <milestone-scoped paths or none>
Validation recorded: <commands and pass/fail result already recorded in the milestone>
Out-of-scope dirty changes: <none or excluded paths>
```
