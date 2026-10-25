---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the user's spec or tickets within the agreed scope. Reuse confirmed requirements and test boundaries; resolve only missing decisions that block the implementation.

Record the starting commit and relevant pre-existing work so this task's changes remain identifiable. For behaviors that warrant persistent tests, load `tdd` through the active harness's supported skill-loading mechanism. Follow repository verification requirements. Load each required method separately; report an unavailable method and stop work that depends on it rather than claiming that step is complete. Run focused checks while iterating. At completion, satisfy required gates with evidence covering the final affected state; reuse valid results from `tdd` or other stages under the global verification policy instead of rerunning them just because this skill is finishing. Required code review remains separate.

Before finishing, separately load `code-review` through the active harness's supported skill-loading mechanism and conduct its read-only review with the task/spec, starting commit and changed-file inventory. Explicitly include this task's committed, staged, unstaged and untracked changes; a comparison ending at HEAD alone cannot review uncommitted implementation.

Address actionable findings and report remaining limits. Commit when the user's existing authorization includes it. Stage only this task's changes and check the entire pending commit, including content staged before the task. If unrelated content cannot be excluded without altering the user's work or staging state, preserve that state and report the blocker.
