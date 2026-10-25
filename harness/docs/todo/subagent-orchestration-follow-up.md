# Subagent Orchestration Follow-Up

Status: Future TODO after skill-slimming S1.

S1 established the current baseline: `agents/global-instructions.md` owns global delegation authority and failure consequences, root `AGENTS.md` owns repository-local routing, `agents/operating-principles.md` maps Codex support paths and assignment permissions, and `workflow:orchestrate-subagents` owns the bounded orchestration workflow. This note tracks only evidence-driven improvements beyond that baseline.

## Future Scope

- Collect real read-only review runs for broad PR, branch, architecture, skill, prompt, docs, and contract tasks; use the evidence to refine recipes only when a repeated failure or friction pattern exists.
- Decide whether repeated validated assignment prompts require custom-agent TOML, and document model, sandbox, availability/fallback behavior, write-conflict handling, sync validation, rollback, and parent integration before adding any preset.
- Mine Superpowers only for targeted workflow ideas such as staged implementer, specification review, and quality review, while preserving `workflow` as the owner and avoiding duplicate orchestration layers.
- Keep parent ownership of planning, write-scope decisions, final judgment, integration, validation, and user-facing conclusions.

## Non-Goals

- Importing Superpowers wholesale.
- Adding custom-agent TOML before `task_name` assignments plus prompt-declared permissions prove insufficient in repeated real runs.
- Expanding read-only review authorization into implicit mutation.
- Reopening the S1 instruction ownership or entry-interface design without regression evidence.
