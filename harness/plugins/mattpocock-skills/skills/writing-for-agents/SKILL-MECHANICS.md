# Skill Mechanics

Use the active harness's supported metadata and installed skill tooling. Keep the required `name` and `description`; preserve other supported fields and the existing invocation choice.

In this repository, `agents/openai.yaml` carries Codex UI metadata and `policy.allow_implicit_invocation`. A value of `false` keeps an entrypoint explicit-only. Some skills also carry `disable-model-invocation: true` for harnesses that consume that frontmatter; keep the two policies consistent when both are present.

Descriptions identify the capability and relevant trigger. Bodies supply the workflow, references supply conditional detail. Do not infer identical loading or cross-skill invocation behavior across every harness from a single frontmatter flag.

## Loading shared methods

When a workflow requires another skill, actually load that named method through the active harness's supported skill-loading mechanism before applying it. Naming a method in prose is not loading it. Load each method separately, using its installed identity; do not assume a tool named `Skill` or a shared invocation syntax exists in every harness. Read required references from the loaded skill's own directory. If a required method or resource is unavailable, report the exact dependency and blocked step; do not silently improvise a replacement or claim completion. Independent authorized work can continue.

Explicit-only entrypoints require the user's selection; another skill must not implicitly invoke one. Compose shared methods directly under the calling workflow's own trigger and completion contract instead of invoking an explicit wrapper such as `grill-with-docs`. Loading a method does not expand authorization: discussion, document writes, implementation and external actions retain their existing boundaries. Reading the existing domain terminology owner for vocabulary does not itself activate domain-modeling or authorize documentation changes.

A router helps users select among entrypoints; it should not turn every task into a complete workflow. Its labels and recommendations do not load or start a skill. Recommend explicit-only entrypoints in accordance with the current harness and user request. Shared methods can remain independent skills or ordinary references where their actual consumers justify that structure.
