# CRITIQUE.md — CloudOps AI frontend redesign

Three rounds: `r1` (drafting world, clean but replaced by the user's pinned
beehiiv reference), `r2` (drafting fixes), `r3` (the beehiiv-referenced console,
this file's subject). Scanned with `shoot.mjs --app` at 390/768/1280/1440,
matrixed at Windows 125/150%, High Contrast, Linux, Android, 320px reflow,
reduced motion and l10n stress, and scored line by line against the rubric.

**No subagent runtime was available in this harness, so the critic is the
author, scored harder than fair. Scores are still evidence-based against
`shots/`.**

## Rubric scores (r3)

| # | Line | Score | Evidence |
|---|---|---|---|
| 1 | Concept on the page | 4 | Every sheet reads as one console: register cards, one signal chart, findings queue. Naming it "the operations console in the beehiiv family" from any screen is possible; it is not unique to CloudOps. |
| 2 | Not the category average | 4 | Refuses the dark "AI dashboard" and the KPI-wallpaper dashboard; it is a category-shaped console because the pinned reference is the category leader's product. Recorded, not accidental. |
| 3 | Not a slop face | 4 | Shares three features with the shadcn Dashboard face (sidebar, KPI row, status chips); the chart-forward first screen, single pink accent and honest unavailable states pull it clear. Not the overcorrection: real data is the loudest element. |
| 4 | First screen | 5 | What it is, the measurements and the primary action all above the fold at 1440 and 390; squint lands on the signal chart. |
| 5 | Typography | 4 | Schibsted Grotesk with a written reason, JetBrains Mono strictly for identifiers/costs, tabular figures, 28→12 scale with real steps. Not 5: the 11px label register and KPI scale stay close to category norms. |
| 6 | Colour | 5 | Palette sampled from the pinned reference, one accent with one job, four-state status set, every pair measured (green darkened to `#0a7a47` for 4.8:1 on its tint; red text on tint `#b8452c`). High Contrast holds via transparent borders. |
| 7 | Richness | 4 | The product's own measured data is the image (the signal curve). No photography: the honest choice for an Operate tool. |
| 8 | Structure and rhythm | 4 | Sections answer the visitor's questions in order; tight groups, generous breaks; the 4-up register is category-normal but the two-column work area carries the weight. |
| 9 | Craft | 4 | No clipping or button wraps in any scan or matrix pass; one icon set at one stroke; concentric radii (8/10/12); skeletons, empty, unavailable, offline and sample states all designed. |
| 10 | Responsive | 4 | Phone designed (register stacks, table scrolls inside its card, IaC flow goes vertical), 768 two-column, 1920 holds inside 1440 max. 320 reflow clean. |
| 11 | Everyone's computer | 4 | Windows 125/150%, High Contrast, Linux, Android, 320px, reduced motion, l10n and l10n-phone all clean. **Firefox, Safari and Safari/iPhone unverified: WebKit/Firefox engines are not installed and the engine download is blocked in this environment.** |
| 12 | Signature | 3 | The signal curve draw-in and the tab slide are right-sized and reduced-motion-safe, but a dashboard-standard move. Deferred idea: a crosshair read-out that follows the pointer over the curve. |
| 13 | Screenshot test | 4 | The chart card and queue are screenshot-worthy; the whole page is calm and complete. |

**Total 52/65.** Passes: no line below 3, average 4.0.

## Fixed between rounds

- r1: `series` shape mismatch crashed the plot (NaN geometry) — fixed at the
  call site; scan FAILs (sub-11px text, 3.67:1 contrast, 768 button wraps) all
  fixed.
- r2→r3: world replaced to the pinned reference; contrast FAIL on the running
  chip (green to `#0a7a47`); High Contrast shape FAILs on nav items, tabs, text
  buttons and the search input (transparent borders); sample banner pill above
  the headline removed; phone title-block wrap fixed.

## Warnings answered (kept deliberately)

- **JetBrains Mono is default-reach.** Justified in DIRECTION.md: it is the
  measurement face (identifiers, costs, tabular data), not a costume.
- **Em dashes in visible copy.** All are data-position em dashes for
  unmeasured values, the product's honesty rule (PRODUCT.md). Prose uses full
  stops and colons.
- **11px labels.** The label register (nav group labels, chips, table headers)
  is deliberate; nothing carrying reading text is under 12px.
- **30 small uppercase labels** reduced from 45 (drafting era) — remaining are
  the label register, not eyebrows over headings.

## Not verified

- Real Windows ClearType and glyph shapes; real iPhone Safari; screen readers;
- live-backend renders (backend is read-only-untouched and offline here; the
  live path was exercised through its real failure mode — unavailable states —
  and the populated path through the `?sample=1` fixture).
- Firefox/WebKit engines (blocked download).

## Verdict for the next round (optional)

Signature line 12 is the weakest. One more round is justified only if the user
wants the crosshair read-out; otherwise ship as is.
