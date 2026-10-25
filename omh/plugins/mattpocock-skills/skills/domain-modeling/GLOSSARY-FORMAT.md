# Glossary Format

Use the repository's existing terminology owner and format first. Existing `GLOSSARY.md`, `CONTEXT.md`, their maps, and custom paths retain their names and ownership. The structures below are defaults for genuinely new owners, not instructions to migrate existing documents.

## Structure

```md
# {Context Name}

{One or two sentence description of what this context is and why it exists.}

## Language

**Order**:
{A one or two sentence description of the term}
_Avoid_: Purchase, transaction

**Invoice**:
A request for payment sent to a customer after delivery.
_Avoid_: Bill, payment request

**Customer**:
A person or organization that places orders.
_Avoid_: Client, buyer, account
```

## Rules

- **Be opinionated.** When multiple words exist for the same concept, pick the best one and list the others under `_Avoid_`.
- **Keep definitions tight.** One or two sentences max. Define what it IS, not what it does.
- **Only include terms specific to this project's context.** General programming concepts (timeouts, error types, utility patterns) don't belong even if the project uses them extensively. Before adding a term, ask: is this a concept unique to this context, or a general programming concept? Only the former belongs.
- **Group terms under subheadings** when natural clusters emerge. If all terms belong to a single cohesive area, a flat list is fine.

## Single vs multi-context repos

**Single context (most repos):** With no existing owner or convention, use one `GLOSSARY.md` at the repo root.

**Multiple contexts:** With no existing map or convention, use a `GLOSSARY-MAP.md` at the repo root to list the contexts, where they live, and how they relate to each other:

```md
# Glossary Map

## Contexts

- [Ordering](./src/ordering/GLOSSARY.md) — receives and tracks customer orders
- [Billing](./src/billing/GLOSSARY.md) — generates invoices and processes payments
- [Fulfillment](./src/fulfillment/GLOSSARY.md) — manages warehouse picking and shipping

## Relationships

- **Ordering → Fulfillment**: Ordering emits `OrderPlaced` events; Fulfillment consumes them to start picking
- **Fulfillment → Billing**: Fulfillment emits `ShipmentDispatched` events; Billing consumes them to generate invoices
- **Ordering ↔ Billing**: Shared types for `CustomerId` and `Money`
```

## Resolve the owner before writing

- Follow repository configuration and existing links first. Read `GLOSSARY-MAP.md`, `CONTEXT-MAP.md`, or a custom map when present, and follow it to the current topic's owner. A map may point to differently named documents; do not impose a filename on its targets.
- Without a map, use the existing glossary or domain terminology owner, including a root `GLOSSARY.md`, `CONTEXT.md`, or a custom location. Do not create a default file merely because one of those names is absent.
- If both conventions or multiple files exist, determine whether they cover different contexts or claim the same domain. Follow explicit repository ownership; if it remains ambiguous or conflicting, resolve it before writing. In read-only work, report the conflict with the proposed change. Do not write the same terms into parallel owners.
- Only when no existing owner or convention applies, create a new glossary or map using the defaults above, lazily when useful content exists and the write is in scope. If the topic's context is unclear, ask.
- Preserve existing document names, links, format and unrelated content. A rename needs a separately authorized migration with consumer inventory, compatibility impact, validation and rollback; updating this skill does not authorize one.
