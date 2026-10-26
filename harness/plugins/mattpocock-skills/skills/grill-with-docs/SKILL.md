---
name: grill-with-docs
description: A relentless interview to sharpen a plan or design, which also creates docs (ADR's and glossary) as we go.
disable-model-invocation: true
---

Load `grilling` and `domain-modeling` separately through the active harness's supported skill-loading mechanism. Use `grilling` for the discussion and `domain-modeling` to record resolved terms and durable decisions. Reuse existing answers and documents; create new material only when it carries useful knowledge.

This is the explicit user entrypoint. Workflows that require these methods compose `grilling` and `domain-modeling` directly under their own trigger and completion contract; they do not implicitly invoke this wrapper or inherit execution permission from it. Load both required methods before claiming completion; report an unavailable dependency instead of substituting an improvised interview. Completed planning does not itself authorize implementation.
