---
name: tdd
description: Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests.
---

# Test-Driven Development

Use a red → green → refactor loop to implement one behavior at a time. Reuse the project's domain language and existing design/test decisions.

## Choose the behavior and interface

State the behavior the next test will protect. Prefer an existing interface that exposes it. When that interface or test boundary needs design, load `codebase-design` through the active harness's supported skill-loading mechanism for the shared interface and seam principles. If unavailable, report the dependency and the blocked design step. An internal interface is appropriate when it protects an independent behavior or regression that a higher-level check does not cover.

Reuse already confirmed boundaries. Resolve new product or interface decisions only when they materially affect the task; routine test placement within the agreed design does not require another confirmation.

## Run the loop

1. Write the smallest meaningful test and observe it fail for the intended missing behavior.
2. Implement enough to make it pass. Avoid speculative features and bulk tests for an imagined design.
3. Refactor when it simplifies the working code, keeping the behavior tests green; then choose the next behavior.

Expected values must come from the requirement, a worked example or an independent oracle. Tests that restate the implementation cannot detect its errors. Prefer behavior assertions over collaborator call counts or private structure unless those interactions are the contract under test.

Use [tests.md](tests.md) for contrasting test examples and [mocking.md](mocking.md) when choosing test doubles. Run affected checks through the loop. At completion, satisfy required repository gates with evidence covering the final affected state; reuse valid results under the global verification policy and pass them to the caller rather than starting a second completion run. This does not replace observing the intended red failure or verifying the changed implementation. Preserve independent regression coverage when consolidating tests; higher-level tests replace an old test only when they actually cover its failure mode.
