---
status: superseded by ADR-0007
---

# Use mode-specific Codex skill invocation identities

Repository `SKILL.md` content remains the only canonical skill source, but the active skill mode determines the invocation identity that Codex exposes. Direct Skill Mode exposes the bare `<catalog-name>` through the direct projection, such as `long-running-goal`. Plugin Skill Mode exposes `${plugin}:${catalog-name}`, such as `workflow:long-running-goal`, from the same canonical source.

A prompt-level request reference is a resolution input, not a cross-mode runtime identity promise. A bare reference may match the direct invocation identity or resolve to a plugin-qualified identity in Plugin Skill Mode. This supersedes ADR-0004's conclusion that both modes expose the same plugin-qualified identity.

## Consequences

The two modes retain one shared catalog and mutually exclusive activation, while identity validation becomes mode-specific. Direct closure validates bare catalog-name projection basenames. Plugin source and cache validation verifies the plugin-to-catalog mapping from which Codex derives qualified identities. We do not add aliases, duplicate source trees, adapters, fallbacks, or source relocation to force one identity spelling across both modes.

Watcher durable identities remain namespaced persisted attribution keys and may use `${plugin}:${catalog-name}` in either mode; that spelling is not evidence that Direct Skill Mode exposes a qualified Codex invocation identity. Plugin installation coordinates remain separate distribution identities.
