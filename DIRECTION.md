# DIRECTION.md — CloudOps AI frontend redesign (beehiiv-referenced)

## Brief

- **What:** the CloudOps AI workspace (React/Vite SPA, FastAPI backend untouched).
- **Who:** cloud engineers, architects, FinOps teams evaluating one AWS account.
- **The one job:** open the workspace and know the state of the account in ten
  seconds: what was measured, what it costs, what needs a decision.
- **Pinned reference (user-given, 2026-10):** `beehiiv Web 193.png` — the beehiiv
  dashboard. White cards on a cool near-white ground, one magenta-pink data
  accent, comfortable density, chart-forward Overview, dark near-black primary
  button, grouped white sidebar with a pink-50 active state.
- The brief is recorded, not self-authored: the reference image and "make it
  good, don't touch the backend" are the instructions. No paid image generation.

## Current (before)

Shipped frontend audited in `shots/before` (earlier rounds of this work): first
a generic shadcn dashboard (KPI cards in tinted icon squares, DM Sans, AWS
blue), then a drafting-sheet world (paper ground, hairline rules, Archivo,
drafting blue). The drafting world scanned clean but was replaced by the user
with the pinned beehiiv reference. The current world is therefore superseded;
this file now describes the new direction. Kept from earlier rounds: the honest
state model (em dash for unmeasured, unavailable reasons, `?sample=1` fixture
mode), the working table filters, expandable row details, and the read-only
language. The new world must differ from the drafting world on all six history
columns: ground (cool near-white vs paper), type (Schibsted Grotesk + JetBrains
Mono vs Archivo + mono), accent (magenta-pink vs drafting blue), richness
(gradient area charts vs register cells), grammar (console dashboard vs
drawing set), density (comfortable vs compact).

## Concept

**CloudOps AI is the account's operations console.** A calm white desk: the
account greets you with what it measured, the chart is the loudest thing on the
first screen, and every finding waits its turn in a queue. It borrows from the
beehiiv reference only what an Operate tool may borrow: type, palette, density,
and one signature move (the signal curve). It refuses the dark glowing "AI
dashboard", the neon-on-navy dev-tool cliché, and KPI-card wallpaper with no
chart anywhere.

## Tokens

Sampled from the pinned reference (measured on the PNG, not guessed):

| Role | Value | Source in reference |
|---|---|---|
| Ground | `#f9fbfc` | page behind the cards |
| Surface | `#ffffff` | every card and the sidebar |
| Ink | `#141721` | headings and values |
| Ink secondary | `#3d4351` / meta `#6b7280` | body and captions |
| Line | `#e9edf1` | card borders and hairlines |
| Accent | `#dc589a` (soft `#fcf2f8`, line `#f2c4dd`, strong `#b02368`) | chart trace, sidebar active tint, links |
| OK | `#0d8a51` (soft `#e7f6ee`) | connected, running, reported savings |
| Warn | `#b54708` (soft `#fdf3e4`) | unavailable / pending / medium severity |
| Danger | `#b42318` (soft `#fdecea`) | high severity |
| Button ground | `#202936` | the "Start writing" primary |

- **Type:** Schibsted Grotesk (self-hosted variable; a precise neo-grotesque
  close to the reference's neutral UI voice, not the default-reach list) for
  interface text; JetBrains Mono strictly for identifiers, costs, and tabular
  data in tables and figures. Scale: page title 28/600, card title 15/600, body
  13, meta 12, KPI value 30/600 tabular, table 13/48px rows.
- **Radius family:** 8 controls, 10 cards, 12 panels, pill for chips and dots.
- **Elevation:** card = `0 1px 2px rgba(20,23,33,.05)`; one soft layer, hover tints only.
  toast is the only float. Flat by default, hover tints, no lift.
- **Spacing:** 4/8/12/16/20/24/32/40/56; page padding 32; sections 24.

## Shell and grammar

Sidebar (seven sheets justify it): white, grouped navigation (Monitor: Overview,
Resources, Cost Analysis, AI Insights; Govern: IaC Review, Governance), pink-50
active state, read-only note and system status at the bottom. Title block: 64px
white bar, wordmark, AWS Account, connection chip, dark "Add a scan" primary.

Overview = the console: page heading ("CloudOps AI — here's how your AWS
account is doing"), the measurement register as four white KPI cards (label,
value, note; no invented deltas), then the signal card (area chart of cost by
service, with exact service rows beneath) and the findings queue card, then the
resource table card and the IaC review card. Cost Analysis adds a real period
toggle (Month to date / Last 30 days) driving the chart.

## Content (voice: brief, exact, engineer-to-engineer)

- Page intro: "Here's how your AWS account is doing. Unavailable measurements
  stay marked, never filled in."
- KPI labels: Monthly cloud cost / Resources / Potential savings / Active
  findings, each with its data source as the note.
- Empty plot: "No measurements recorded" with the action that would fill it.
- Unavailable: "Not available" plus the reason and the permission that fixes it.
- Findings queue: issue, resource, action, evidence, reported saving or em dash.

## Signature (motion.md §3)

**The signal curve draws itself in.** Trigger: cost data lands on the Overview
or Cost Analysis chart. Frames: the area chart's stroke draws left to right and
its pink gradient fade rises with it (~900ms, `cubic-bezier(.2,.8,.2,1)`),
value markers settle after; tab underline slides between period tabs (200ms).
Reduced motion: complete static chart, no draw-in. The still frame (first
paint of a loaded chart) is designed to stand alone.

## States

Loading: skeletons matching card layout after ~300ms. Empty: one sentence and
the action that fills it. Filtered: the filter named, with a way to clear.
Unavailable: reason and permission. Offline: banner and the connection chip.
Every state reachable by URL (`?state=empty|offline|error`, `?sample=1`).
