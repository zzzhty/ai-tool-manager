---
status: superseded by ADR-0006
---

# Accept native Codex skill invocation identities

Repository `SKILL.md` content remains the only canonical skill source, and universal discovery continues to expose that source through bare-name user-level links. For canonical skills that resolve inside a plugin-owned source tree, current Codex exposes the plugin-qualified `${plugin}:${catalog-name}` invocation identity in both plugin and universal skill modes. We accept that native identity surface and treat the bare frontmatter name as the catalog name and a possible request reference, not as a promised runtime identity.

## Consequences

The migration keeps the existing `plugins/*/skills/*` physical authority and rejects a neutral-copy, source-relocation, or packaging workaround whose only purpose would be to erase plugin context. M5 must verify the exact catalog-name-to-qualified-identity mapping, bare request resolution, implicit routing, and mode-specific source locators. Watcher durable identities may intentionally use the same spelling while remaining separately owned persisted attribution keys; plugin installation coordinates remain separate distribution identities.
