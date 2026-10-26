# Deepening

How to deepen a cluster of shallow modules safely, given its dependencies. Assumes the vocabulary in [SKILL.md](SKILL.md) — **module**, **interface**, **seam**, **adapter**.

## Dependency categories

When assessing a candidate for deepening, classify its dependencies. The category determines how the deepened module is tested across its seam.

### 1. In-process

Pure computation, in-memory state, no I/O. A candidate for consolidation when it reduces real coupling; test through the new interface directly. No adapter needed.

### 2. Local-substitutable

Dependencies that have local test stand-ins (PGLite for Postgres, in-memory filesystem). Use the stand-in when it preserves the relevant contract; retain integration checks for what it cannot model. The deepened module is tested with the stand-in running in the test suite. The seam is internal; no port at the module's external interface.

### 3. Remote but owned (Ports & Adapters)

Your own services across a network boundary (microservices, internal APIs). Define a **port** (interface) at the seam. The deep module owns the logic; the transport is injected as an **adapter**. Tests use an in-memory adapter. Production uses an HTTP/gRPC/queue adapter.

Recommendation shape: *"Define a port at the seam, implement an HTTP adapter for production and an in-memory adapter for testing, so the logic sits in one deep module even though it's deployed across a network."*

### 4. True external (Mock)

Third-party services (Stripe, Twilio, etc.) you don't control. The deepened module takes the external dependency as an injected port; tests provide a mock adapter.

## Seam and test choices

Reuse [the interface and seam principles](SKILL.md#principles). A deep module may have internal test interfaces; tests using them do not require exposing them to callers.

Write behavior tests at the deepened interface. Remove an old shallow-module test only after its failure mode is actually covered there. Preserve independent privacy, schema, error-handling and integration checks that the new tests do not replace. Consolidate shared setup and assertions for the same behavior; do not preserve or delete tests solely because of their location or level.
