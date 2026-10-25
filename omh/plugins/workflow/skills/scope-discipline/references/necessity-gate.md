# Necessity Gate

This reference owns the reusable decision for material scope and validation expansion. Apply it after the active request and owner contracts have already defined the current result.

## Decision Questions

Before adding work that is not already authorized, answer:

1. Is this work already requested or authorized by the user or an active owner contract?
2. Is it a necessary consequence of completing the current result correctly?
3. Which reachable code, data, caller, test, deployment state, acceptance rule, legal requirement, or platform contract proves that necessity?
4. Would omitting it make the current result fail its gate, remain false, become unsafe, or become non-compliant?

A future possibility, generic best practice, preference for completeness, or desire to display diligence is not sufficient evidence.

## Decision Routing

Route the proposed expansion to exactly one outcome:

- **Authorized current work**: execute it under the existing scope.
- **Necessary consequence**: expand only the owning current scope, record the concrete evidence, and continue without asking for permission unless the owner contract requires it.
- **Later-stage or separately owned work**: leave it with the existing later milestone or owner; do not implement it early and do not create a parallel planning surface.
- **Speculative expansion**: do not implement it. Report it only when it materially affects a future decision.
- **Semantic conflict**: pause mutation, record the contradictory evidence, and evolve the owning contract. Ask the user only when that contract's existing hard-stop or approval boundary applies.

Do not use fixed limits on files, lines, tests, tool calls, agents, or elapsed time as a substitute for this decision. Necessary work can be large; unnecessary work can be one line.

## Validation Expansion

Declared validation, review gates, compatibility checks, safety checks, and checkpoint evidence are already authorized and are not candidates for removal.

Before adding broader validation, apply the same four questions. Broader validation is justified when current evidence exposes an affected shared interface, persisted schema, migration, cross-platform path, runtime flow, security or privacy boundary, release requirement, or failing integration.

Stop expanding validation when:

- the declared checks pass;
- the current review gate passes;
- no new failure or affected contract is visible;
- the result can be completed without making an unsupported claim.

Do not repeat a search, test, review, or audit with no new oracle merely to increase confidence cosmetically.

## Evidence Boundary

Record only material expansion, a consequential deferral, or a semantic conflict in the existing task owner. Do not create a per-command scope log, another completion report, or a final audit pass solely for this gate.
