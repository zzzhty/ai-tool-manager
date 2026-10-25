## Matt Pocock local edition

This plugin is maintained by oh-my-harness. Its selected skills may be revised locally; README.md records the upstream baseline and attribution. [ADR 0012](../../docs/adr/0012-maintain-a-local-mattpocock-selection.md) owns the migration from the complete upstream mirror.

- Edit the owning skill and its references together. Preserve existing invocation policies unless the task explicitly changes them.
- Resolve skill-relative resources from the selected skill directory. If a required resource is missing, report its path rather than substituting another skill's resource.
- For upstream updates, follow [README.md — Upstream updates](README.md#upstream-updates): compare upstream revisions against the local edition, select changes, and record decisions and deferred work. Preserve local adaptations and attribution; keep the complete-tree importer retired.
- Follow the root validation and generation workflow. Installed caches and harness projections remain generated outputs.
