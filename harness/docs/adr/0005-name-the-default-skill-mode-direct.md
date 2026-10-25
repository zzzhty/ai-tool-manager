---
status: superseded by ADR-0007
---

# Name the default skill mode direct

The former `universal` name described availability rather than the distribution boundary. The current CLI modes are `direct` and `plugin`: `direct` is the default and exposes canonical repository skills without activating skills-bearing plugins, while plugin selection remains explicit.

## Consequences

This is an intentional CLI break: `universal` is retired without an alias, fallback, or dual read. Direct mode continues to reject plugin pruning; pruning requires explicit plugin mode. Earlier ADRs and TODO entries retain `universal` as historical terminology.
