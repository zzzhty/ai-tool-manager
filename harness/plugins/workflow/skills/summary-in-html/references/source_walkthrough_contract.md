# Source Walkthrough Contract

Use this document type when the user asks to take over unfamiliar code from
scratch, trace real entry points, or receive a step-by-step code walkthrough.
Do not substitute generic learning advice, review methodology, or an
architecture inventory.

## Contents

- Evidence Route
- Document Shape
- Step Contract
- Red Lines

## Evidence Route

1. Record the inspected source revision and dirty state in `evidence`, `footer`,
   or both.
2. Find the real public entry: CLI, exported API, factory, framework hook, or
   actual caller. A representative test may be the closest observable entry.
3. If the scope has no public entry, say so and start at the nearest real
   boundary. Never invent a CLI or API.
4. Follow calls through the requested behavior until its observable return,
   side effect, or next subsystem boundary.
5. Use current source and focused tests for the active route. Keep historical
   context and evaluation results outside that route and label them explicitly.
   Set each evidence `role` to `current_source`, `historical_context`, or
   `evaluation`; include at least one current-source record.

## Document Shape

Set:
```json
{
  "document_type": "source_walkthrough",
  "source_root": "/absolute/repository/root",
  "source_revision": "HEAD abc1234; working tree dirty"
}
```

Then author sections in this order:

1. An unnumbered orientation section containing the complete call route before
   any detailed step. Include a non-empty `code` block with language
   `call-tree`.
2. Ordered source steps. Give only these sections a non-empty
   `completion_check`; the renderer numbers and counts them.
3. Optional unnumbered ownership map, change-routing guide, blind spots, or
   follow-up section.

## Step Contract

Each step answers five questions with structured section fields:

- `files`: which file to open; every path must exist beneath `source_root`.
- `entry_symbol`: which function, class, hook, or boundary to enter.
- `receives`, `does`, `hands_off_to`, and `returns`: non-empty string lists
  describing the complete handoff.
- `summary`, `paragraphs`, and `bullets`: optional explanation around the
  structured handoff.
- `code`: only the call route, shape ledger, command, or excerpt needed to
  remove ambiguity.
- `completion_check`: one behavioral self-check that proves the reader can
  locate or retell this handoff.

Do not put an ordinal such as `1.` or `Step 1.` in a step title; the renderer
owns numbering.

Example:
```json
{
  "title": "Request Path Source Walkthrough",
  "document_type": "source_walkthrough",
  "source_root": "/workspace/service",
  "source_revision": "HEAD abc1234; clean",
  "evidence": [
    {
      "label": "Current source",
      "path": "inventory.inputs.json",
      "role": "current_source"
    }
  ],
  "sections": [
    {
      "title": "Complete request route",
      "summary": "Read this route once before opening implementation details.",
      "code": [
        {
          "language": "call-tree",
          "text": "public handler\n  -> parse request\n  -> service method\n  -> repository\n  <- response"
        }
      ]
    },
    {
      "title": "Enter through the public handler",
      "summary": "Open handle_request() and keep the full route visible.",
      "entry_symbol": "handle_request()",
      "receives": ["The framework request."],
      "does": ["Binds request data to the domain command."],
      "hands_off_to": ["Service.execute()."],
      "returns": ["The framework response."],
      "files": [
        {"path": "src/handler.py", "note": "Public request boundary"}
      ],
      "completion_check": "I can locate the public handler and name its next call."
    }
  ],
  "blind_spots": ["Runtime behavior was not executed."]
}
```

## Red Lines

- Do not hard-code one repository's modules, number of steps, commands, model
  stages, or terminology into the skill or renderer.
- Do not number overview or follow-up sections merely because the document is a
  walkthrough.
- Do not put `completion_check` on a section that does not satisfy the complete
  step contract.
- Do not treat reader progress as source verification.
- Do not add a second template, renderer, or parallel skill for this mode.
- Keep the page readable when JavaScript or browser storage is unavailable.
