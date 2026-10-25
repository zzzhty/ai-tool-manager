---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

Write a compact handoff so another session, directory, harness or person can continue the work. Use the user's requested destination; otherwise save to the operating system's temporary directory and report its absolute path. A handoff does not require a formal goal contract.

Include the objective, confirmed decisions and their reasons, relevant environment/branch state, completed work and verification, unresolved questions or blockers, and the next concrete action. Tailor the emphasis to the user's stated next task. Add suggested skills only where they help that task.

Reference existing specs, plans, ADRs, issues, commits and diffs rather than copying them. Carry enough explanation to preserve decisions whose reasons those artifacts do not capture. Redact secrets and unnecessary personal information; point to credential locations without copying credential values.

Continue in the current session while its context is useful. Create a handoff when the user asks or work actually crosses a continuation boundary; a phase transition, prototype or fixed token count alone does not require one. Report the saved artifact and any unresolved verification; creating it does not authorize sending it to another person.
