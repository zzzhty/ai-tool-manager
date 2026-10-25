---
status: accepted
---

# Use content-derived plugin distribution identities

`oh-my-harness` release identity is rooted in the repository `VERSION` file. The
first formal release is `1.0.0`. First-party plugin packages without an upstream
identity lock use that release version as their base version. Mirrored packages
with `.codex-plugin/upstream-lock.json` keep the locked upstream release as their
base version; for example, the Matt Pocock mirror remains based on upstream
`1.2.3` while participating in the `oh-my-harness` `1.0.0` distribution.

Every plugin manifest version has the form:

```text
<base-version>+codex.<generation>
```

`generation` is the first 16 hexadecimal characters of a SHA-256 digest over a
canonical plugin tree. The digest covers sorted relative POSIX paths, ordinary
directories, and ordinary file payloads. UTF-8 CRLF payloads canonicalize to LF,
binary payloads remain byte-exact, file modes and timestamps are excluded, and
the manifest version is replaced with a stable placeholder containing the base
version before hashing. Links, junctions, reparse points, unsupported entry
types, and case-colliding paths fail closed. Standard transient Python/test
caches and `.DS_Store` are outside the canonical payload and ignored on both
source and cache sides.

The generated `.agents/plugins/distribution-identity.json` records the release
version, algorithm, full per-plugin SHA-256 values, complete plugin versions,
and one bundle identity derived from the ordered package identities. It is a
generated receipt, not a second editing authority. `scripts/update_plugin_generations.py`
updates manifest generations and this receipt transactionally;
`scripts/check_plugin_generations.py` is the read-only gate.

Source preflight rejects plugin content whose manifest generation or generated
receipt is stale. A Codex plugin at the same installed version is skipped only
when its complete canonical cache identity equals the source identity. Version
or content drift fails before mutation, and final closure repeats the complete
source/cache identity comparison. Normal refresh does not hide a same-version
cache repair behind an automatic remove/add cycle; a future repair command must
be explicit and preserve the existing rollback boundary.

This contract makes the existing Codex version-sensitive cache behavior safe:
equal complete versions mean equal canonical plugin content, while a content
change deterministically produces a new generation and therefore a new cache
directory.

## Later decision

[ADR 0012](0012-maintain-a-local-mattpocock-selection.md) supersedes the Matt upstream-mirror ownership/version exception. The historical reasoning above remains recorded; current Matt skills are locally maintained.
