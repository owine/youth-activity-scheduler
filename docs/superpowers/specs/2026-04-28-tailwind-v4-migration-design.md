# Tailwind CSS v4 Migration

**Status:** design approved, ready for implementation plan
**Date:** 2026-04-28
**Depends on:** main at commit `7418480` (deps/easy-majors merged 2026-04-28)
**Succeeds into:** Phase 5b-1a backend slice (independent — order doesn't matter, but doing the Tailwind migration first avoids merging two large diffs in close succession)

## 1. Purpose and scope

Migrate the YAS frontend from Tailwind CSS v3.4 to v4.x, adopting the modern v4 idioms: CSS-first `@theme` configuration, the first-party Vite plugin, and freshly regenerated shadcn primitives. The migration replaces the v3 plugin chain (`tailwindcss-animate`, PostCSS plugin, JS config) with v4's Vite-integrated, CSS-driven equivalent.

This is a tooling and styling-config migration, not a UX redesign. The visual output should be unchanged in light and dark mode for all five Phase 5a pages.

### 1.1 In scope

- Replace `tailwindcss@3.4.19` with `tailwindcss@4.x` and add `@tailwindcss/vite@4.x`.
- Replace `tailwindcss-animate` with `tw-animate-css`.
- Remove `postcss` + `autoprefixer` + `frontend/postcss.config.js` (the Vite plugin handles the pipeline).
- Move every theme extension out of `frontend/tailwind.config.ts` and into `@theme` blocks in `frontend/src/styles/globals.css`. Delete `tailwind.config.ts`.
- Re-shadcn the 10 primitives in `frontend/src/components/ui/` against the v4 idiom (run `npx shadcn@latest add ...` once for the existing list).
- Apply the `@tailwindcss/upgrade` automated tool first to handle utility renames mechanically (e.g., `shadow-sm` → `shadow-xs`).
- Audit the 19 consumer components for any utility renames the tool missed and for any prop/variant changes from re-shadcn-ing.
- Verify all automated gates (typecheck, lint, vitest, build) plus the existing 4-test Playwright e2e against a docker stack.
- Manual click-through of all 5 Phase 5a pages in light and dark mode before merge.

### 1.2 Out of scope — explicitly deferred

- **OKLCH color migration.** Keep HSL `:root` and `.dark` CSS variables in `globals.css`. v4 supports both; converting is purely cosmetic and would invalidate any future shadcn add-ons that paste HSL var snippets.
- **New shadcn primitives.** Phase 5a's review pass flagged that `globals.css` lacks `--popover`, `--popover-foreground`, `--chart-*`, and `--sidebar-*` tokens. We are not adding those primitives in this migration; the missing tokens stay missing until Phase 5b-1b actually installs Popover/Tooltip/Command/Chart components with their token sets.
- **Container queries adoption.** v4 has built-in container queries (`@container`); Phase 5a uses none. YAGNI.
- **Eliminating `@apply`.** v4 still supports `@apply` in `@layer base`. Whether the upgrade tool rewrites the body rule's `@apply bg-background text-foreground` to native CSS is its choice; either form is acceptable.
- **Lint plugin for deprecated Tailwind classes.** Adding `eslint-plugin-tailwindcss` is a separate concern; we rely on the v4 upgrade tool's one-shot rewrite plus manual grep for residuals.

## 2. Tooling and config shape

### 2.1 Package changes

`frontend/package.json` updates:

**Remove:**
- `tailwindcss@3.4.19` (devDependencies)
- `tailwindcss-animate@1.0.7` (dependencies)
- `postcss@8.5.12` (devDependencies) — confirm no other Vite plugin peer-depends on `postcss` first; if one does, leave as a transitive instead of an explicit dep.
- `autoprefixer@10.5.0` (devDependencies)

**Add:**
- `tailwindcss@4.x` (devDependencies, exact-pinned per project convention)
- `@tailwindcss/vite@4.x` (devDependencies, exact-pinned)
- `tw-animate-css@1.x` (dependencies, exact-pinned — runtime CSS, not a build-time plugin)

All exact versions resolved by `npm install --save-exact` and committed to `package-lock.json`. Per project policy: no `^`/`~` prefixes anywhere.

### 2.2 File deletions

- Delete `frontend/postcss.config.js` (Vite plugin replaces it).
- Delete `frontend/tailwind.config.ts` (config moves into `globals.css`).

### 2.3 `frontend/vite.config.ts` change

Add the import and register the plugin:

```ts
import tailwindcss from '@tailwindcss/vite';
// …
plugins: [TanStackRouterVite(), tailwindcss(), react()],
```

Plugin order: TanStackRouterVite → tailwindcss → react. Tailwind sits between the router (which generates `routeTree.gen.ts`) and react (which transforms JSX) so its CSS pipeline runs against the final source set.

### 2.4 `frontend/src/styles/globals.css` shape

The file grows from 48 lines to ~80 lines and absorbs the theme tokens that previously lived in `tailwind.config.ts`. New shape:

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:where(.dark, .dark *));

@theme inline {
  --color-border: hsl(var(--border));
  --color-input: hsl(var(--input));
  --color-ring: hsl(var(--ring));
  --color-background: hsl(var(--background));
  --color-foreground: hsl(var(--foreground));
  --color-primary: hsl(var(--primary));
  --color-primary-foreground: hsl(var(--primary-foreground));
  /* …secondary, destructive, muted, accent, card with foreground variants… */

  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);

  /* No --container-* tokens here. v3's `container: { center: true,
     padding: '1rem' }` config does not translate to @theme tokens.
     v4 customises the container utility via `@utility container`
     (see immediately below). */
}

@layer base {
  :root {
    --background: 0 0% 100%;
    /* …all existing HSL variables, unchanged… */
    --radius: 0.5rem;
  }
  .dark {
    /* …all existing dark-mode HSL variables, unchanged… */
  }
  body {
    background: hsl(var(--background));
    color: hsl(var(--foreground));
  }
}

@utility container {
  margin-inline: auto;
  padding-inline: 1rem;
}
```

The `@utility container` block translates v3's `container: { center: true, padding: '1rem' }` config into v4's customisation idiom. Existing usage (`container max-w-5xl py-6` in `AppShell.tsx`) keeps working because consumers compose `container` with `max-w-5xl` etc.

The `@custom-variant dark` line replaces v3's `darkMode: 'class'` config. The `@theme inline` block declares Tailwind's color/radius tokens, mapping them through to the existing HSL CSS variables defined in `:root`/`.dark`. The `body` rule is rewritten to native CSS (the upgrade tool may leave `@apply` — either form passes).

### 2.5 `frontend/components.json`

No structural change. The shadcn CLI continues to read this file in v4 mode; existing settings (`style: default`, `rsc: false`, `tsx: true`, `baseColor: slate`, `cssVariables: true`) apply. Bump the `$schema` URL only if the CLI's regeneration writes a different one — accept whatever the CLI emits.

## 3. shadcn primitive regeneration

Run once after the v4 config is in place:

```bash
cd frontend
rm src/components/ui/{alert,badge,button,card,collapsible,input,sheet,skeleton,slider,tabs}.tsx
npx shadcn@latest add alert badge button card collapsible input sheet skeleton slider tabs
```

Expected differences in the regenerated primitives:

- **`tw-animate-css` references** — the new Sheet/Tabs/Collapsible primitives reference `animate-in`/`slide-in-from-right`/etc. utilities that come from the imported `tw-animate-css` package, not a Tailwind plugin.
- **Latest Radix prop API** — minor adjustments to `Sheet` props and `Slider` thumb rendering. Surface as type errors during `npm run typecheck`.
- **No vestigial markings** — the existing primitives carry `"use client"` directives in `slider.tsx`/`tabs.tsx` (Phase 5a code-review note) and double-spaces in `sheet.tsx` (also flagged); these go away naturally on regeneration.

After regeneration, run `npm run typecheck`. Any prop or variant rename in a consumer (the 19 `*.tsx` files in `src/components/{alerts,common,inbox,layout,matches,sites}/` and the 7 route files) surfaces as a type error. Fix in the same commit; do not split.

## 4. Migration sequencing

Run, in order, in a single PR (one branch, one or more commits — the implementer chooses based on review readability, but no partial-state ships to main):

1. **Run `npx @tailwindcss/upgrade`** — the official codemod. It rewrites deprecated utilities in `.tsx`/`.css`, scaffolds the `@theme` block in `globals.css`, and updates `package.json`. Commit its output as the first commit so reviewers can isolate "automated changes" from "manual changes."
2. **Manual config fixups** — switch the upgrade tool's default `@tailwindcss/postcss` to `@tailwindcss/vite`. Delete `postcss.config.js` and `tailwind.config.ts`. Update `vite.config.ts`. Resolve `package-lock.json`.
3. **Re-shadcn** — delete and regenerate the 10 primitives. Fix any consumer type errors in the same commit.
4. **Audit pass** — grep `frontend/src` for bare `\bborder\b(?!-\w)` (default-color change risk), for any leftover `tailwindcss-animate` import paths, and for any utility names the tool missed. Patch if found.

## 5. Utility renames the upgrade tool handles

Catalogued so reviewers recognize them in the diff:

- `shadow-sm` → `shadow-xs`, `shadow` → `shadow-sm`
- `rounded-sm` → `rounded-xs`, `rounded` → `rounded-sm`
- `outline-none` → `outline-hidden`
- `ring` → `ring-3`
- `blur` → `blur-sm`
- `decoration-clone`/`decoration-slice` → `box-decoration-clone`/`box-decoration-slice` (unused in YAS; mentioned for completeness)

What the tool does NOT do automatically — manual checks:

- **Default border color** changed from `gray-200` to `currentColor` in v4. Phase 5a uses `border-border` everywhere (mapped to `--border`), so the change is benign — but search `frontend/src` for orphan `border` classes that would flip from gray to `currentColor`. Use `rg` (PCRE-compatible) since BSD/macOS `grep` doesn't support lookahead: `rg '\bborder\b(?!-)' frontend/src`.
- **`@apply` in body rule** — `@apply bg-background text-foreground` at `globals.css:46`. Either form (`@apply` or native `background:`/`color:`) is acceptable.

## 6. Testing and verification

### 6.1 Automated gates

All must pass before merge:

```bash
cd frontend
npm run typecheck   # catches shadcn primitive prop renames
npm run lint        # max-warnings 0
npm run test -- --run   # 21 vitest tests
npm run build       # primary signal — v4's Lightning CSS emits only used utilities

cd ..
./scripts/e2e_phase5a.sh   # 4 Playwright e2e tests against a real browser
```

The e2e is the strongest visual-regression signal we have today; it renders the inbox, the alert drawer, the kid matches list, and the deep-link route in a real Chromium and asserts on visible text. If a primitive breaks visually, the test most likely surfaces the failure (e.g., the drawer not opening because `Sheet` animations broke).

### 6.2 Manual visual verification

After automated gates pass, run `npm run dev` and click through each Phase 5a page in both light and dark mode (toggle via the TopBar `ThemeToggle`):

1. **Inbox** (`/`) — alerts list, kid match cards, site-activity sentence. Click an alert: drawer (`Sheet`) opens with slide-in animation, displays `AlertTypeBadge`, summary text, and JSON payload. Drawer closes on overlay click and on Escape.
2. **Kid Matches** (`/kids/1/matches`) — urgency groups (`Card` primitives) collapse/expand correctly. The `urgent` border style on cards in the "opens this week" group is visibly red. Drawer opens on card click.
3. **Watchlist** (`/kids/1/watchlist`) — `KidTabs` indicator (border-bottom) tracks the active route. `Badge` variants `outline` ("ignores hard gates") and `secondary` ("inactive") render correctly.
4. **Sites** (`/sites`, `/sites/1`) — Card hover state (`hover:bg-accent`), Badge muted/inactive variants, crawl history list with status Badges.
5. **Settings** (`/settings`) — three sections, table layout for alert routing, no orphan unstyled elements.

A failure mode tells: an unstyled element (no padding, no color) usually means an unrenamed v3 utility class is in the source but produces no v4 rule.

### 6.3 Bundle size sanity

Baseline (post-easy-majors merge):
- JS: 422.45 KB / 130.65 KB gzip
- CSS: 19.27 KB / 4.72 KB gzip

Expectation after migration:
- JS: roughly unchanged (Tailwind only emits CSS, not JS).
- CSS: expected to drop. v4's Lightning CSS engine is more aggressive at deduplication; the previous CSS already shipped only used utilities (v3's JIT also did this), but the v4 engine is faster and may slightly shrink output. A growth of more than ~5 KB indicates a misconfiguration.

### 6.4 Risk handling

- **If the upgrade tool produces unexpected diffs**, commit its output unmodified as the first commit on the migration branch. Reviewers can isolate "what the tool did" from "what we did" easily.
- **If a primitive's prop API broke a consumer**, fix the consumer in the same commit. Do not split into a follow-up PR.
- **If the manual click-through reveals a visual regression**, fix in the same PR before merge. There is no incremental ship strategy — Tailwind v4 is a global build-tool change; a partially migrated state cannot be supported.

## 7. Exit criteria

- All automated gates green: `npm run typecheck`, `npm run lint`, `npm run test -- --run`, `npm run build`, plus `./scripts/e2e_phase5a.sh` (4 Playwright tests).
- Manual visual click-through of all 5 Phase 5a pages in light and dark mode reports no regressions.
- CSS bundle size within ±5 KB of baseline (19.27 KB).
- `tailwind.config.ts` and `postcss.config.js` no longer exist; `globals.css` carries the full theme.
- `tailwindcss-animate` no longer in `package.json`; `tw-animate-css` is.
- Single PR opened, CI passes, merged with `--no-ff` to `main`.

When this lands, proceed to **Phase 5b-1a — Alert Close (Backend)** as planned, or to whatever the next priority is at that time.
