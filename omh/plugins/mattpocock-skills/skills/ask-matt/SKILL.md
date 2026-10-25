---
name: ask-matt
description: Ask which skill or flow fits your situation. A router over the skills in this repo.
disable-model-invocation: true
---

# Choose a Skill

Recommend the smallest useful entrypoint for the user's task. Reuse the current request and decisions; a clear implementation task can go straight to work. These are choices, not a mandatory sequence.

| Need | Skill |
| --- | --- |
| Stress-test an idea or decision | `/grill-me`, using `/grilling` |
| Discuss a decision and retain domain knowledge | `/grill-with-docs`, combining `/grilling` and `/domain-modeling` |
| Clarify domain terms or record an architectural trade-off | `/domain-modeling` |
| Design a module interface | `/codebase-design` |
| Find architecture improvements | `/improve-codebase-architecture` |
| Investigate an incoming issue or PR | `/triage` |
| Diagnose a difficult failure or regression | `/diagnosing-bugs` |
| Turn settled discussion into a spec | `/to-spec` |
| Implement a spec or tickets | `/implement` |
| Build a behavior test-first | `/tdd` |
| Review changes against requirements and standards | `/code-review` |
| Write a PR body from changes and verification evidence | `/pr` |
| Answer a design question with runnable code | `/prototype` |
| Gather primary-source evidence | `/research` |
| Transfer context to another session, directory or person | `/handoff` |
| Learn a subject over several sessions | `/teach` |
| Write or revise agent instructions | `/writing-for-agents` |
| Review a coding session for environment or process improvements | `/retro`, only when the user selects it |

Choose documentation mode because decisions need to persist, not merely because a working directory exists. Use a prototype where its question and code belong; it does not require a new directory or a round-trip handoff.

Respect each entrypoint's invocation policy. Recommend explicit-only skills for the user to choose rather than silently starting their workflow. Ordinary planning uses the active environment; formal long-running goals still require the user's explicit choice. Follow that environment's context management instead of fixed token thresholds or mandatory clear/compact steps.
