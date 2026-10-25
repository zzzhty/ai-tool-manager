# Production Cutover Gate

Use this branch only for cutovers that compare a new implementation against an authoritative old path.

Freeze default, full-shadow diagnostic, and production/shadow-reduced modes before implementation. Full-shadow keeps both paths running and records diffs. The old path remains rollback until a review gate records a default/full-shadow/production comparison matrix, correctness evidence, mode-specific timing evidence, and the decision to change defaults.

Do not claim production speedup by disabling shadow checks while still depending on old-path metadata, output contracts, or side effects. Production timing counts only after the new path owns the metadata/output contract it needs, old hot-path work is actually skipped, reuse/allocator assumptions are frozen when relevant, and correctness gates still pass.

Completion criterion: the comparison matrix, correctness and mode-specific timing evidence, rollback path, ownership assumptions, and explicit default-change decision are recorded before cutover or speedup claims.
