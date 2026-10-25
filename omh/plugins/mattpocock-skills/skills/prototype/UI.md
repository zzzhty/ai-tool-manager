# UI Prototype

Build the smallest UI prototype that answers the design question. Start with one design; add alternatives only when comparison is needed. For multiple variants, use one route with a URL selector and a floating switcher so the user can compare them in the browser.

If the question is about logic/state rather than what something looks like — wrong branch. Use [LOGIC.md](LOGIC.md).

## When this is the right shape

- "What should this page look like?"
- "I want to see a few options for this dashboard before committing."
- "Try a different layout for the settings screen."
- Any time the user would otherwise spend a day picking between three vague mockups in their head.

## Two sub-shapes — strongly prefer sub-shape A

A UI prototype is much easier to judge when it's **butting up against the rest of the app** — real header, real sidebar, real data, real density. A throwaway route on its own is a vacuum: every variant looks fine in isolation. Default to sub-shape A whenever there's a plausible existing page to host the variants. Only reach for sub-shape B if the prototype genuinely has no nearby home.

### Sub-shape A — adjustment to an existing page (preferred)

The route already exists. Render the prototype **on the same route**. When comparing variants, select their rendering with a `?variant=` URL search param. The existing data fetching, params, and auth all stay — only the rendering swaps. This is the default; pick it unless there's a specific reason not to.

If the prototype is for something that doesn't yet have a page but *would naturally live inside one* (a new section of the dashboard, a new card on the settings screen, a new step in an existing flow) — that's still sub-shape A. Mount the prototype inside the host page.

### Sub-shape B — a new page (last resort)

Only use this when the thing being prototyped genuinely has no existing page to live inside — e.g. an entirely new top-level surface, or a flow that can't be embedded anywhere sensible.

Create a **throwaway route** following whatever routing convention the project already uses — don't invent a new top-level structure. Name it so it's obviously a prototype (e.g. include the word `prototype` in the path or filename). Use `?variant=` only when comparing multiple variants.

Before committing to sub-shape B, sanity-check: is there really no existing page this could be embedded in? An empty route hides design problems that a populated one would expose.

Both sub-shapes use the same floating bottom bar only when comparing multiple variants.

## Process

### 1. State the question and pick N

Start with one variant. Add only alternatives needed to resolve a concrete design trade-off; use a requested count when the user specifies one.

Write down the plan in one line, in the prototype's location or a top-of-file comment:

> "One settings-page layout on the existing `/settings` route."

This works whether the user is here to push back or not.

### 2. Build the prototype or chosen variants

Build the prototype or each chosen variant around:

- The page's purpose and the data it has access to.
- The project's component library / styling system (TailwindCSS, shadcn, MUI, plain CSS, whatever).
- A clear exported component name, e.g. `VariantA`, `VariantB`, `VariantC`.

When comparing different layouts or information hierarchies, make variants differ on that decision. Redo a variant only if it fails to test a needed alternative. For a single prototype, proceed directly to Hand it over.

### 3. Wire multiple variants together (comparison only)

Create a single switcher component on the route:

```tsx
// pseudo-code — adapt to the project's framework
const variant = searchParams.get('variant') ?? 'A';
return (
  <>
    {variant === 'A' && <VariantA {...data} />}
    {variant === 'B' && <VariantB {...data} />}
    {variant === 'C' && <VariantC {...data} />}
    <PrototypeSwitcher variants={['A','B','C']} current={variant} />
  </>
);
```

For sub-shape A (existing page): keep all the existing data fetching above the switcher; only the rendered subtree changes per variant.

For sub-shape B (new page): the throwaway route under `/prototype/<name>` mounts the same switcher.

### 4. Build the floating switcher (comparison only)

A small fixed-position bar at the bottom-centre of the screen with three pieces:

- **Left arrow** — cycles to the previous variant (wraps around).
- **Variant label** — shows the current variant key and, if the variant exports a name, that name too. e.g. `B — Sidebar layout`.
- **Right arrow** — cycles forward (wraps around).

Behaviour:

- Clicking an arrow updates the URL search param (use the framework's router — `router.replace` on Next, `navigate` on React Router, etc) so the variant is shareable and reload-stable.
- Keyboard: `←` and `→` arrow keys also cycle. Don't intercept arrow keys when an `<input>`, `<textarea>`, or `[contenteditable]` is focused.
- Visually distinct from the page (e.g. high-contrast pill, subtle shadow) so it's obviously not part of the design being evaluated.
- Hidden in production builds — gate on `process.env.NODE_ENV !== 'production'` or an equivalent check, so a stray prototype merge can't ship the bar to users.

Put the switcher in a single shared component so both sub-shapes can reuse it. Locate it wherever shared UI lives in the project.

### 5. Hand it over

Surface the URL and, for a comparison, the `?variant=` keys. The user can inspect the prototype or compare alternatives whenever they get to it. For multiple variants, feedback such as **"I want the header from B with the sidebar from C"** can identify the design they want.

### 6. Capture the answer and clean up

Once the prototype has answered the question, record the conclusion and why, along with the runnable artifact or URL, as the [SKILL](SKILL.md) describes. Keep the prototype and any compared variants as local evidence. When production integration is already authorized:

- **Sub-shape A** — fold the chosen design into the existing page; remove any unused variants and switcher from main.
- **Sub-shape B** — promote the chosen design to a real route; remove the throwaway route and any switcher from main.

When removing experiment code from production paths, preserve runnable local prototype evidence and record its path. Branch creation, publication and issue updates follow the main skill's authorization rules. A design choice alone does not authorize production integration or deleting the evidence.

## Anti-patterns

- **Variants that do not help resolve the design question.** Add a variant only when it tests a needed alternative.
- **Shared code that prevents a useful comparison.** When comparing layouts, keep variants free to change structure; reuse shared code that does not constrain the dimension being compared.
- **Wiring variants to real mutations.** Read-only prototypes are fine. If a variant needs to mutate, point it at a stub — the question is "what should this look like", not "does the backend work".
- **Promoting the prototype directly to production.** The variant code was written under prototype constraints (no tests, minimal error handling). Rewrite it properly when you fold it in.
