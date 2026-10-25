---
name: domain-modeling
description: Build and sharpen a project's domain model. Use when discussing codebase domain terminology or a ubiquitous language, writing or editing a glossary, or recording or editing an architectural decision record (ADR).
---

# Domain Modeling

Actively build and sharpen the project's domain model as you design. This is the *active* discipline — challenging terms, inventing edge-case scenarios, and writing the glossary and decisions down the moment they crystallise. Merely reading the project's existing domain terminology owner for vocabulary does not activate this skill or authorize documentation changes.

## File structure

Resolve the existing glossary, context map, and ADR owners first. Follow repository configuration and links, including `GLOSSARY.md` / `GLOSSARY-MAP.md`, `CONTEXT.md` / `CONTEXT-MAP.md`, and custom paths. For multiple contexts, follow the map to the owner of the current topic. If files claim the same domain and the repository does not resolve ownership, clarify the owner before writing; in read-only work, report the ambiguity. Do not fork or synchronize competing glossaries.

Read [GLOSSARY-FORMAT.md](GLOSSARY-FORMAT.md) when creating or updating terminology or a context map. Preserve existing document names, links and formats; renaming user documents requires a separately authorized migration. Only when no existing owner or convention applies, default to a root `GLOSSARY.md`, `GLOSSARY-MAP.md` for multiple contexts, and `docs/adr/` for decisions. Create a missing owner lazily, only when useful content exists and the write is in scope.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing domain terminology owner, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update the glossary owner inline

When documentation changes are in scope and a term is resolved, update its existing glossary owner. In a read-only task, report the proposed term instead of writing. Follow the existing format, using [GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md) for guidance.

Keep glossary definitions focused on domain language, without implementation details, specs or scratch notes. Preserve unrelated sections when the existing owner is a mixed-purpose document; do not repurpose or rewrite it as a pure glossary.

### Offer ADRs sparingly

For requested edits to an existing ADR, follow its owner, template and history/status conventions. In read-only work, propose the change instead of writing.

Record or propose a new ADR when all three are true; reuse existing authorization to write one:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).
