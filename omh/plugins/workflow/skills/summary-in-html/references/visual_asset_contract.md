# Visual Asset Contract

Use this reference only when the summary includes a requested visual.

## When To Generate

Generate or place an image only when the user explicitly asks for a visual, such
as:

- "配图"
- "架构图"
- "流程图"
- "illustration"
- "infographic"
- "diagram image"
- "generate an image"

Do not generate images merely because the HTML template supports them.

## Diagram Strategy

- Use Mermaid, SVG, or styled HTML for precise architecture, sequence,
  dependency, state, or module diagrams.
- Use `imagegen` for raster images, illustrative architecture visuals,
  infographic-style images, conceptual graphics, or user-specified generated
  images.
- If exact labels or small text are required, prefer deterministic HTML-native
  diagrams over raster generation.

## Imagegen Coordination

When `imagegen` is required:

1. Extract a visual brief from inspected evidence.
2. State whether the asset is an architecture visual, process visual,
   infographic, chapter illustration, or user-specified image.
3. Generate the image with `imagegen`.
4. Inspect the result for accuracy, text errors, and missing requested elements.
5. Move or copy the selected project-bound image into the summary asset
   directory.
6. Reference the asset from summary JSON with `path`, `alt`, and `caption`.

## File Placement

Default project-bound asset directory:

```text
docs/summaries/assets/
```

Use descriptive filenames:

```text
<scope-slug>-architecture.png
<scope-slug>-flow.png
<scope-slug>-chapter-visual.png
```

Do not overwrite an existing image unless the user explicitly asks for
replacement. Use a versioned filename when needed.

## Accessibility And Evidence

Every visual must have:

1. `alt`: concise description of the image.
2. `caption`: why the image exists in this summary.
3. Local file path.
4. A note in the final response if any visual detail is inferred rather than
   directly supported by inspected files.

The summary artifact validator rejects an asset before rendering unless `path`,
`alt`, and `caption` are all non-empty strings. File existence remains a
post-render HTML validation concern.
