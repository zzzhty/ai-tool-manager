# Task Patterns

Choose only slices that answer independent questions. Keep narrow reviews and sequential debugging in the parent. All inspection assignments are read-only, explicitly forbidding edits and commits; external reads remain within the task's authorization.

| Task | Useful independent slices | Required evidence / boundary |
| --- | --- | --- |
| PR or branch review | Correctness, affected contracts, test gaps | Exact base/head or working diff; reachable code and findings with paths. No repository or external writes. |
| Debugging triage | Reproduction, code-path inspection, distinguishing diagnostics | Original command/symptom and environment; reproduction outputs explicitly authorized; report the breakpoint or access blocker without claiming an unobserved cause. |
| Implementation planning | Ownership map, options, validation/rollback | Each slice informs a named planning decision. No implementation. |
| Parallel implementation | Independent behavior in disjoint file groups | Exact writable paths, shared artifacts parent-owned; stop at cross-slice edits. Slice checks are evidence for parent integration. |
| API/schema inspection | Producer/consumer mapping, compatibility, fixture gaps | Contract versions, serializers, migrations and known consumers; authoritative evidence for external assumptions; disclose inaccessible consumers. |
| Documentation alignment | Active inventory, source comparison, entry/link checks | Name the source of truth, distinguish archives, run only non-mutating checks, and disclose uncovered areas. |
