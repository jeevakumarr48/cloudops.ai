---
name: CloudOps AI
description: The operations console — a calm sage-and-teal workspace where every cloud measurement is plotted and every redline waits for review.
stack:
  app: "Vite + React 19 SPA over a FastAPI backend"
  styling: "Tailwind CSS v4 + shadcn (base-luma, Base UI primitives, Phosphor icons)"
  components: "Sidebar, Button, Badge, Table, Input, Alert, Tabs, Separator, Skeleton, Tooltip"
  theme: "Light only"
colors:
  # app tokens (src/styles/tokens.css)
  ground: "#f4f6f1"
  surface: "#fafbf8"
  surface-2: "#e9eee7"
  ink: "#171a18"
  ink-2: "#535d57"
  ink-3: "#535d57"
  text-muted: "#626c65"
  line: "#e0e5de"
  line-strong: "#c8d0c9"
  brand: "#52796f"
  brand-strong: "#354f52"
  brand-soft: "#dce5dc"
  brand-line: "#cad2c5"
  ok: "#247346"
  ok-soft: "#e6f4ea"
  warn: "#956000"
  warn-soft: "#fff3d6"
  danger: "#b42318"
  danger-soft: "#fce8e8"
  # shadcn theme (src/index.css)
  primary: "#354f52"
  primary-foreground: "#ffffff"
  secondary: "#eef2ee"
  accent: "#dce5dc"
  muted: "#e9eee7"
  border: "#e0e5de"
  input: "#c8d0c9"
  ring: "#52796f"
  chart: ["#cad2c5", "#84a98c", "#52796f", "#354f52", "#2f3e46"]
  success: "#247346"
  warning: "#956000"
  info: "#315db5"
typography:
  ui:
    fontFamily: "Inter, system-ui, sans-serif"
    reason: "A neutral UI grotesque with a tall x-height and clear numerals; even rhythm at 12-15px."
  data:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    reason: "Strictly identifiers, costs and tabular data: the measurement face, never a costume."
  scale:
    page: { fontSize: "20px", fontWeight: 600, letterSpacing: "-0.02em" }
    card: { fontSize: "15px", fontWeight: 600 }
    body: { fontSize: "13px", fontWeight: 400, lineHeight: 1.5 }
    meta: { fontSize: "12px" }
    kpi: { fontSize: "24px", fontWeight: 600, variantNumeric: "tabular-nums" }
    table: { fontSize: "13px", rowHeight: "48px" }
spacing: [4, 8, 12, 16, 20, 24, 32, 40, 56]
radius:
  control: "8px"
  card: "16px"
  pill: "999px"
elevation:
  card: "hairline border, no shadow"
  popover: "0 4px 12px rgba(47,62,70,0.12)"
layout:
  rail: "shadcn Sidebar, collapsible to icons; drawer under 768px"
  titleblock: "64px"
  contentMax: "1440px"
  contentPad: "16/24/32px"
---

# Design System: CloudOps AI

## Overview

**Creative North Star: "The Operations Console"** (pinned reference: the beehiiv
dashboard, `beehiiv Web 193.png`). Soft sage surfaces over a warm near-white
ground, one deep-teal data accent, comfortable density. The Overview is
chart-forward: the signal curve is the loudest element, the findings queue sits
beside it, and the measurement register is a quiet row of four above both.

The world refuses the dark glowing "AI dashboard", the navy dev-tool cliché,
and KPI-card wallpaper with no chart anywhere. There are no cards: the page is
the frame, and sections are separated by a single hairline rule. One container
per screen; spacing, type and rules, not frames inside frames. The read-only promise and the honesty rule
(an unmeasured value is an em dash, never an invented number) are part of the
design, not disclaimers under it.

## Stack

Tailwind CSS v4 through `@tailwindcss/vite`; the UI is built from shadcn
components (style `base-luma`, Base UI primitives, Phosphor icons). Generated
primitives live in `src/components/ui/` and are the only lint-exempt folder.
The shadcn theme variables (`src/index.css`) and the app tokens
(`src/styles/tokens.css`) carry the same palette and change together; `cn`
(tailwind-merge) is used for conditional classes.

## Colors

The sage system: greens for brand and data, a warm neutral for ground and ink,
and four status families. No gradients, no glows.

### Surfaces
- Ground `#f4f6f1` (page), card `#fafbf8`, sidebar `#e9eee7`, selected
  `#dce5dc`. Lines: default `#e0e5de`, strong `#c8d0c9` (form borders).

### Brand and data
- **Intelligence green** `#52796f`: the one data accent — chart traces, active
  navigation, links, the connection dot. Deep teal `#354f52` is the primary
  action ground and hover; sage mist `#cad2c5` and soft sage `#84a98c` round
  out the chart ramp with `#2f3e46`.
- **Focus ring** `#52796f`.

### Text
- Ink `#171a18` (headings, values), ink-2/ink-3 `#535d57` (body, table), muted
  `#626c65` (captions). The brief's muted `#77817a` was darkened to `#626c65`
  so captions clear WCAG AA (4.5:1) on the ground, cards and sidebar.

### Status
- Success `#247346` on `#e6f4ea`; Warning `#956000` on `#fff3d6`; Critical
  `#b42318` on `#fce8e8`; Information `#315db5` on `#eaf0fc`. Status is carried
  as **hue + word + dot**, not as a filled chip: a coloured dot and coloured
  text keep the row quiet and remove another box.

### Named Rules
**The One-Accent Rule.** Teal carries data and selection; ink carries actions;
status hues carry state. Three jobs, never confused.
**The Fewer-Boxes Rule.** The page is the frame. Standalone sections are
separated by spacing and a single hairline rule. A small set earns a box: the
four KPI register cards, and a tight pair that reads as one unit (the cost curve
and the findings queue). Everything else stays on the page. In-row status is a
dot + word, not a chip; buttons that only navigate are links.
**The Honesty Rule.** A value the API did not return is an em dash with the
reason beside it. Never a zero, never a guess.

## Typography

**UI:** Inter (self-hosted via `@fontsource-variable/inter`), metric-matched
Arial fallback. **Data:** JetBrains Mono, tabular figures, for instance IDs,
costs, dates and table numerals.

Hierarchy: page title 20/600; card title 16/600; body 14/1.5; caption 12; KPI
value 24/600 tabular; table 13px rows. Sentence case everywhere. Numbers that
align or change are mono + tabular.

## Layout

A shadcn `Sidebar` (collapsible to icons, drawer under 768px) and a sticky
`SidebarInset` header with the sidebar trigger, the connection status and the
primary action. Content is capped at 1440px and padded 16/24/32px.
The Overview: heading row with the data-status pill and Refresh, a single
row of four KPI cards, then the cost curve and the findings queue as two boxed
panels side by side, then the resource table and the IaC record on the page.
Cost Analysis leads with its period tabs and has no page title. Register cells go four-across at
`lg`, two at `sm`, one on phones.

## Elevation & Depth

Flat by default: no card borders and no card shadows. Sections are separated by
a single hairline rule at the top edge; popovers, tooltips and the sidebar
drawer are the only elevated surfaces.
Forced-colors mode keeps every control's shape through transparent borders.

## Shapes

Control radius 8px, card radius 16px, dots and the utilization meter are pills.
Inner radii nest concentrically.

## Components

- **Sidebar** — brand header, Monitor/Govern groups, a `Read-only review` badge
  in the footer, Settings last. Collapses to icons; becomes a Sheet on phones.
- **Header** — sidebar trigger, wordmark and account, connection `StatusPill`,
  region, dark primary `Add a scan` button.
- **Register** — four KPI cards in a row: each a label, a 30/600 tabular value
  and a source note. Unmeasured values are an em dash in muted.
- **Cost panel** (boxed, left of the findings queue) — recharts step-area, 2px teal stroke, teal gradient fill,
  hairline grid, mono ticks, a popover tooltip. Draws in over ~900ms; reduced
  motion gets the static frame.
- **Findings queue** — a severity dot, the issue in full (never truncated), a
  coloured severity word, the mono resource id, the reported saving, and a
  `Review` link that expands to action / evidence / saving / resource.
- **Table** — no card: `Input` search, state filter buttons with counts, a sort
toggle, hairline rows, mono IDs, a dot+word state and a utilization meter, sitting
directly on the page.
- **IaC record** — a two-column spec of six fields, each an em dash with its
  reason, in mono tabular figures. Read-only: no plan is submitted from the UI.
- **Sample banner** — an `Alert` in warning ink on warning ground; data is
  sample by default and `?sample=0` opts into the live backend.

## Do's and Don'ts

### Do:
- Keep the chart the loudest element on the Overview.
- Set IDs, costs and dates in mono tabular figures.
- Use teal for data and selection only; ink for actions; dot+word+hue for status.
- Render unavailable measurements as em dashes with the reason and the fix.
- Keep one container per idea; separate with spacing or dividers.
- Keep shadcn theme variables and app tokens in step when the palette changes.

### Don't:
- Nest bordered, rounded boxes inside cards.
- Add gradients, glows, orbs, or a dark "AI" theme.
- Put a KPI row above a chart that does not exist yet.
- Use teal decoration outside data/selection, or status hue without its word.
- Fabricate deltas, trends, savings, or "vs last period" numbers the API does
  not return.
- Put hover-only information on the phone; the queue and table are complete
  without hover.
