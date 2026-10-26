---
name: to-spec
description: Turn the current conversation into a spec and publish it to the project issue tracker — no interview, just synthesis of what you've already discussed.
disable-model-invocation: true
---

# Write a Spec

Synthesize the current discussion and repository evidence into an implementable spec. Reuse confirmed requirements, domain terms, ADRs and test boundaries. Ask only about consequential gaps; do not restart an interview or require a long list of user stories.

Inspect the relevant code when the current implementation is not yet understood. Prefer existing interfaces and tests; `/codebase-design` owns seam principles. State any proposed interface change separately from an agreed decision.

Include the sections that carry information:

- **Problem and outcome:** the user's problem and observable resulting behavior.
- **Requirements:** concrete scenarios and acceptance criteria, sized to the feature.
- **Implementation decisions:** agreed interfaces, interactions, schema or architectural choices; include specific paths or concise prototype snippets when they clarify the decision.
- **Verification:** behavior to protect, chosen interfaces and relevant existing checks. Reference shared testing guidance instead of reproducing it.
- **Scope and open questions:** explicit exclusions and unresolved decisions that affect implementation.

Use the requested destination and existing tracker conventions. When publication is authorized, publish to that tracker and apply its established readiness label only if the spec is ready. A request to draft does not authorize posting an issue or creating configuration. If publication lacks necessary tracker details, complete the draft and report the missing destination/configuration rather than running setup automatically.

Report the artifact and remaining decisions; an incomplete requirement set is not ready for unattended implementation.
