# HTML Report Format

When the user requests a visual report, deliver one self-contained HTML file at the requested destination, or in the OS temp directory when none is specified. Inline the CSS and diagrams; the delivered report must render offline without CDN scripts, remote fonts, external stylesheets, or runtime imports. Use static inline SVG for graphs and arrows, and HTML/CSS for bands, nested boxes, and callouts. No build pipeline is required.

## Scaffold

Adapt the labels, shapes, and content to the reviewed code. This minimal card demonstrates the offline structure; it is not a required diagram shape.

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Architecture review — {{repo name}}</title>
    <style>
      * { box-sizing: border-box; }
      body { margin: 0; background: #fafaf9; color: #0f172a; font: 16px/1.5 system-ui, sans-serif; }
      main { max-width: 68rem; margin: auto; padding: 3rem 1.5rem; }
      h1, h2, h3 { line-height: 1.2; }
      article, .recommendation { margin: 2rem 0; padding: 1.5rem; background: white; border: 1px solid #cbd5e1; border-radius: .5rem; }
      .comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.5rem; }
      figure { margin: 0; min-width: 0; }
      figcaption { font-weight: 600; margin-bottom: .5rem; }
      svg { display: block; width: 100%; height: auto; }
      svg text { font: 14px system-ui, sans-serif; fill: #0f172a; }
      .module { fill: #f1f5f9; stroke: #64748b; stroke-width: 2; }
      .deep { fill: #0f172a; stroke: #0f172a; stroke-width: 4; }
      .deep-label { fill: white; }
      .seam { fill: none; stroke: #64748b; stroke-dasharray: 4 4; }
      .leak { stroke: #dc2626; stroke-width: 2; }
      .badge { display: inline-block; padding: .15rem .5rem; border-radius: .25rem; background: #e2e8f0; }
      .strong { background: #d1fae5; } .explore, .adr { background: #fef3c7; }
      .files { font: .875rem/1.5 ui-monospace, monospace; overflow-wrap: anywhere; }
      .adr { padding: .75rem; } a { color: #047857; }
      @media (max-width: 42rem) { .comparison { grid-template-columns: 1fr; } }
      @media print { body { background: white; } article { break-inside: avoid; } }
    </style>
  </head>
  <body>
    <main>
      <header>
        <h1>{{repo name}} — Architecture review</h1>
        <p>{{date}} · Box: module · Dashed: seam · Red arrow: leakage · Dark: deep module</p>
      </header>
      <section id="candidates" aria-label="Candidates">
        <article id="candidate-1">
          <h2>{{candidate title}}</h2>
          <p><span class="badge strong">Strong</span> <span class="badge">{{dependency category}}</span></p>
          <p class="files">{{reviewed source paths}}</p>
          <div class="comparison">
            <figure>
              <figcaption>Before</figcaption>
              <svg viewBox="0 0 360 180" role="img" aria-labelledby="before-title">
                <title id="before-title">{{current dependency and leakage}}</title>
                <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="#dc2626" /></marker></defs>
                <rect class="module" x="10" y="55" width="130" height="70" rx="4" />
                <text x="75" y="95" text-anchor="middle">{{caller}}</text>
                <path class="leak" d="M145 90 H210" marker-end="url(#arrow)" />
                <rect class="module" x="220" y="55" width="130" height="70" rx="4" />
                <text x="285" y="95" text-anchor="middle">{{dependency}}</text>
              </svg>
            </figure>
            <figure>
              <figcaption>After</figcaption>
              <svg viewBox="0 0 360 180" role="img" aria-labelledby="after-title">
                <title id="after-title">{{proposed responsibility and seam}}</title>
                <rect class="seam" x="10" y="10" width="340" height="160" rx="8" />
                <rect class="deep" x="30" y="30" width="300" height="120" rx="4" />
                <text class="deep-label" x="180" y="95" text-anchor="middle">{{deep module}}</text>
              </svg>
            </figure>
          </div>
          <p><strong>Problem:</strong> {{observable cost}}</p>
          <p><strong>Solution:</strong> {{interface or ownership change}}</p>
          <ul><li>{{concrete benefit}}</li></ul>
        </article>
      </section>
      <section class="recommendation" id="top-recommendation">
        <h2>Top recommendation</h2>
        <p><a href="#candidate-1">{{candidate title}}</a> — {{reason}}</p>
      </section>
    </main>
  </body>
</html>
```

## Content And Diagrams

Start with repo name, date, and legend, then candidates. Each candidate names the deepening, recommendation strength (`Strong`, `Worth exploring`, or `Speculative`), dependency category, and relevant files. Pair before/after diagrams with a concise problem, solution, concrete benefits, and an ADR callout when applicable. Adapt the strength badge and avoid unsupported certainty.

Choose a diagram that explains the candidate:

- **Dependencies or call flow:** inline SVG nodes and directed edges; label the meaningful relationships. A sequence of messages can show round-trip reduction.
- **Layered shallowness:** horizontal bands before, one consolidated responsibility after.
- **Interface and implementation:** paired rectangles illustrating interface burden versus capability, not a line-count depth metric.
- **Call-graph collapse:** nested boxes before, one module with faded internal calls after.

Keep diagrams legible, approximately 320px high when useful, and use unique SVG IDs per card. Prefer whitespace and sparse color: one accent, red for leakage, amber for warnings. Use the `/codebase-design` vocabulary while respecting repository terms. The top recommendation links to its candidate with a concrete reason.

Before delivery, open the file with network access disabled and confirm styles, labels, diagrams, and internal links still work. Evidence links may point to external sources; rendering must not depend on them.
