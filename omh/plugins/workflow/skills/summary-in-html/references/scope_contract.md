# Scope Contract

Use this reference when the requested summary boundary is broader or narrower
than a whole repository.

## Scope Types

- **Project / repository**: summarize the repo's purpose, top-level layout,
  runtime commands, plugin or package boundaries, tests, docs, scripts, and
  known blind spots.
- **Directory / package**: summarize ownership, public entry points, internal
  subdirectories, upstream/downstream dependencies, tests, and local commands.
- **Module / feature area**: summarize user-visible behavior, code paths,
  important types or schemas, integration points, and regression-prone flows.
- **Documentation chapter**: summarize the chapter's topic, claims, linked
  source-of-truth files, terminology, decisions, and follow-up references.
- **User-provided material**: summarize only the provided inputs unless the user
  asks to inspect surrounding project files.

## Boundary Rules

1. Use the user's named path or topic as the primary scope.
2. Inspect nearby entry points before expanding scope.
3. Expand only far enough to explain dependencies, commands, tests, or adjacent
   concepts that a developer needs to understand the requested scope.
4. Mark omitted areas as blind spots when they could materially affect the
   summary.
5. Do not treat archive, generated, cache, vendored, or dependency directories as
   current source of truth unless the user explicitly points at them.

## Evidence Priority

Prefer these inputs when they exist:

1. Root and scope `AGENTS.md`.
2. Root and scope `README.md`.
3. Package manifests and runtime config.
4. Source entry points and exported APIs.
5. Tests around the scope.
6. Scripts and CI commands.
7. Current docs, runbooks, TODO indexes, and active planning files.
8. Recent command output or generated inventories.

## Output Naming

Use a stable slug based on the scope:

- repository root: `project-overview.html`
- `plugins/workflow`: `plugins-workflow.html`
- `agents/operating-principles.md`: `chapter-agent-operating-principles.html`
- feature topic: `<feature-slug>.html`

If the file already exists and replacement was not requested, append a short
qualifier such as `-v2`, `-module`, or `-chapter`.
