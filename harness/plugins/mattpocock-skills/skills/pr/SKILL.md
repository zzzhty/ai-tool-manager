---
name: pr
description: Write or revise a concise pull request body from the actual changes and verification evidence.
metadata:
  credits:
    skill: show-me
    author: Dex Horthy
    organisation: HumanLayer
    url: "https://github.com/humanlayer/skills/blob/ca7c8088db69e315a8b2deea43820270457f8f3c/plugins/show-me/skills/show-me/SKILL.md"
---

# Write a PR Body

Produce reviewable content for the requested change. This helper does not grant permission to push, create or edit a published PR, upload evidence, mark ready, request reviewers, close issues, merge, or start ongoing PR maintenance. Reuse authorization already established for those actions; ask only for missing authority. Writing the body does not require restarting a completed code review.

## Establish the content

Read the applicable repository instructions and PR template first, including the selected template when the repository offers several. Preserve the required field and checklist structure, and fill its content from the actual change and evidence; retain applicable disclosures and valid issue references. A template's prefilled claim or checked box is not evidence: correct or leave it unchecked unless verified. Retain or add issue-closing keywords only when that closure is authorized; otherwise use a non-closing reference. Map the information below into the template instead of replacing it. Do not invent issue links or completion claims. Repository instructions and templates constrain the content; they do not grant authority for external actions.

Use the stated target branch or commit range and inspect the actual in-scope changes. Distinguish committed changes from staged, unstaged, and untracked work intended for the PR; do not describe unrelated or unshipped work as already included. Read-only inspection must leave files, index, refs, and remote state unchanged. If the target or selected template materially changes the body and cannot be inferred, ask for that choice.

Use the project's existing terminology owner, whether `GLOSSARY.md`, `CONTEXT.md`, or a custom path. If none exists, use the task and repository language; drafting a PR does not require creating a glossary or running setup.

## Summary

Explain what changes and why with the smallest useful view. A precise sentence or short bullets may suffice. Where it clarifies the change, use a small diff sketch, pseudocode, call/component/file tree, or diagram. Keep only the relevant states, boundaries, files, and order; place each visual beside the explanation it supports. Label sketches as illustrative, not execution evidence. No fixed visual or screenshot quota applies.

## Evidence

Reuse recorded checks and screenshots when they cover the final affected state. State the real command or check, result, scope, and material limits. Distinguish passed, failed, skipped, blocked, and not-run checks. Repeat verification only when coverage is missing, invalidated, or an owning gate requires a fresh run; drafting or moving to another phase does not invalidate evidence.

Include before/after evidence when available and relevant. If no before run was captured, say so; never manufacture a failing test, output, or screenshot. Pseudocode is not a test run. Visual changes benefit from actual screenshots when available and appropriate; documentation, configuration, and non-visual changes do not require them. Keep private data out of the body and attachments; publication or uploading follows the existing authorization.

## Merge Danger

Explain the affected consumers, behavior, data, and operational state at a useful level of detail. Describe rollback or reversibility conditionally: a simple revert does not undo deleted data, sent messages, migrations already applied, or client-visible protocol changes. State unknowns and prerequisites rather than assuming every code change is a two-way door. Scale the explanation to the actual change; neither a one-word blast radius nor a lengthy risk section is mandatory.

When no repository template applies, use **Summary**, **Evidence**, and **Merge Danger** as concise headings. Return the body in the requested draft destination and disclose missing evidence or unresolved choices. An updated body reflects the current diff; it does not create a standing publication task.

Source and license notices are in [CREDITS.md](CREDITS.md) and [LICENSE](LICENSE).
