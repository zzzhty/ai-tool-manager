# Watcher Skill Log Schema

Watcher writes one redacted skill-domain JSON object per line to `$CODEX_HOME/watcher/skill/logs/events.jsonl`.

Core fields:

- `schema_version`: current value `2`.
- `event_id`: collector-generated UUID when absent.
- `timestamp`: collector-generated UTC ISO-8601 timestamp when absent.
- `agent`: defaults to `codex`.
- `event_type`: lifecycle label such as `user_prompt_submit`, `post_tool_use`, `turn_summary`, `user_feedback`, or `failure`.
- `workspace`, `session_id`, `trigger_reason`.
- `tools_used`: array of tool or command names.
- `files_touched`: array of paths, without file contents.
- `outcome`: raw event outcome such as `success`, `failure`, `partial`, or `unknown`.
- `task_outcome`: turn-level task outcome when known; do not infer it from tool failures alone.
- `failure_type`: optional category such as `tool_error`, `wrong_assumption`, `missed_validation`, `format_error`, or `user_correction`.
- `skill_attribution`: primary/supporting/effective/mentioned skill attribution.
- `tests_or_checks`: array of validation actions.
- `user_feedback` and `notes`: short factual summaries.
- `codex`: hook metadata, turn id, redacted summaries, and turn summaries.

Skill attribution fields:

- `skill_attribution.primary`: entry skill name, source, role, typed alias evidence, and confidence.
- `skill_attribution.supporting`: unconditional supporting skills declared by plugin metadata; alternatives and conditional branches remain undeclared.
- `skill_attribution.effective`: primary plus supporting skill names, used by default reporting.
- `skill_attribution.mentioned`: extra runtime text matches that are evidence only.
- `codex.user_skill_context`: redacted summary/hash of extra user context.
- `codex.turn_summary`: per-turn task outcome, tool counts, and tool failure observations written on `Stop`.

Collectors must avoid full prompts, file contents, complete command transcripts, secrets, and private business data. Store summaries, hashes, counts, and explicit skill context signals instead.
