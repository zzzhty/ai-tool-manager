---
name: diagnosing-bugs
description: Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow.
---

# Diagnosing Bugs

Build an evidence-backed explanation of the reported symptom, then verify the smallest root-cause fix. Read relevant domain terms and ADRs when present.

## Evidence and feedback

Record expected versus observed behavior, the affected environment and relevant recent changes. Inspect code, configuration and existing logs to form falsifiable hypotheses; label inference separately from observation.

Choose a check that distinguishes the user's symptom from nearby failures: a focused test, CLI/HTTP/UI reproduction, sanitized trace replay, or comparison with a known-good version. For performance, establish a timing/profile baseline before changing code. For intermittent failures, record the conditions and observed frequency rather than calling a few green runs a fix.

Tighten or minimize the reproduction when doing so separates causes or makes iteration practical. A minimal input, fixed hypothesis count or seconds-long loop is not a prerequisite for every investigation. If reproduction is unavailable, continue with useful read-only evidence and state what remains unverified. Request only the missing access or observation that blocks the next necessary step; do not change production instrumentation without authorization.

Keep secrets out of displayed commands and artifacts: use environment variables for credentials, redact auth headers and quote only relevant output. If a redacted capture cannot answer the question, describe the missing signal without exposing the secret.

## Test the explanation

For each plausible cause, state a prediction and the observation that would falsify it. Test the strongest discriminator first; add competing hypotheses when the evidence leaves a real ambiguity. Change one relevant variable at a time.

Use debugger inspection, targeted temporary instrumentation, or a measured experiment. Mark instrumentation so it can be removed. A human-operated reproduction may use [the HITL template](scripts/hitl-loop.template.sh) when manual interaction is necessary; ordinary code/log investigation does not require that template.

## Fix and verify

Once the evidence supports a cause, apply the smallest fix. When a persistent regression test protects a distinct failure mode, first make it fail on the original behavior and then pass with the fix. Use the interface that reproduces the real failure pattern; a shallow test that cannot trigger it gives no assurance. When the test boundary itself needs design, load `codebase-design` through the active harness's supported skill-loading mechanism. If unavailable, report the dependency and the blocked design step; independent read-only investigation can continue.

Recheck the original scenario, not only a reduced fixture. If that verification is blocked, report the exact limit and available evidence instead of declaring the bug resolved. Preserve useful user artifacts and remove only the temporary instrumentation and disposable files created for this investigation.

Report the cause, change, observed result and remaining uncertainty. Recommend architectural follow-up only when the investigation demonstrates a missing test boundary or coupling problem; it does not automatically start another workflow.
