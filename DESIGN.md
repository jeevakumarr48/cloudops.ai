---
name: CloudOps AI
description: The Drafting Sheet — a measured engineering-drawing interface for cloud infrastructure.
colors:
  paper: "#f3f5f7"
  paper-2: "#eceff2"
  sheet: "#ffffff"
  ink: "#16202b"
  ink-2: "#35424e"
  ink-3: "#4b5865"
  ink-4: "#5e6a76"
  rule: "#dbe1e7"
  rule-2: "#c7d0d8"
  grid: "#e8edf1"
  drafting-blue: "#1f5fbf"
  drafting-blue-strong: "#174b99"
  drafting-blue-soft: "#e9f0fa"
  drafting-blue-line: "#aec7e8"
  red-pencil: "#c2482f"
  amber-signal: "#7d560b"
  ok-green: "#2c7a57"
  slate: "#33414f"
typography:
  display:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Archivo, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "10px"
    fontWeight: 500
    letterSpacing: "0.1em"
  measurement:
    fontFamily: "JetBrains Mono, monospace"
    fontSize: "24px"
    fontWeight: 500
    lineHeight: 1.1
rounded:
  xs: "2px"
  sm: "3px"
  md: "4px"
  lg: "6px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
  s7: "32px"
  s8: "40px"
  s9: "56px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.xs}"
    padding: "8px 12px"
  button-primary-hover:
    backgroundColor: "{colors.drafting-blue}"
    textColor: "{colors.sheet}"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
    padding: "8px 12px"
  panel:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xs}"
---

# Design System: CloudOps AI

## Overview

**Creative North Star: "The Drafting Sheet"**

CloudOps AI renders an AWS account as a measured engineering drawing. The interface is a drawing set: a numbered sheet index, a title block, a register of measured dimensions, and figures plotted on graph paper. It exists to make cloud state legible and, above all, honest — what was measured, what was not, and what to redline.

The system refuses the category's default glowing dark AI dashboard. There is no neon, no purple gradient, no glass, no hero-metric card wall. Depth comes from hairline rules and paper value, not from soft shadows or rounded cards. Density is high but ruled: every section is separated by a 1px line and aligned to a consistent measure.

Expression is deliberately quiet because the surface is Operate: cloud engineers, architects, FinOps teams, and evaluators need to trust the tool immediately and read real signal fast. The drafting world supplies precision, not decoration.

**Key Characteristics:**
- Cool drafting paper with hairline rules and a faint 24px graph grid reserved for measurement surfaces.
- Ink for text, one structural drafting-blue accent, and red-pencil reserved for severity.
- Archivo for all interface text; JetBrains Mono for every number, key, and ID.
- Flat white sheet panels with near-square corners and corner registration ticks; no soft shadows.
- Honest empty states: an unmeasured value is an em dash, never a fabricated figure.

## Colors

A restrained palette: two paper neutrals, a four-step ink ramp, one structural blue, and a small set of functional signal colors.

### Primary
- **Drafting Blue** (#1f5fbf): the only structural accent. Used for links, primary-action hover, active navigation cues, focus rings, chart traces, and the "field note" marker. Rarity is the point.

### Secondary
- **Red Pencil** (#c2482f): severity and annotations only — high-severity findings, the redline callout number, error icons. Never decorative.
- **Signal Amber** (#7d560b): "not available" / pending / medium severity. Darkened from a typical amber so it passes contrast on its own tint.

### Neutral
- **Ink** (#16202b): primary text, strong rules, the primary button ground.
- **Ink-2** (#35424e): secondary text and body copy in cards.
- **Ink-3** (#4b5865): tertiary text, table body.
- **Ink-4** (#5e6a76): metadata, labels, field keys (passes ≥4.5:1 on both paper and paper-2).
- **Paper** (#f3f5f7) and **Paper-2** (#eceff2): the app ground and the secondary chrome layer (sidebar).
- **Sheet** (#ffffff): panel and table surfaces.
- **Rule** (#dbe1e7) / **Rule-2** (#c7d0d8): hairline dividers and control borders.

### Named Rules
**The Ruled-Not-Shadowed Rule.** Boundaries are drawn with 1px hairlines and paper value, never with soft shadow or a colored stripe.
**The Red-Pencil Rule.** Red is reserved for severity and annotation. It never appears as decoration or as a primary action color.

## Typography

**Display Font:** Archivo (with system-ui, sans-serif)
**Body Font:** Archivo (with system-ui, sans-serif)
**Label/Mono Font:** JetBrains Mono (with ui-monospace, monospace)

**Character:** A single technical grotesque carries the whole interface, so hierarchy comes from size, weight, and the mono/sans split rather than a display pairing. Monospace is strictly the language of measurement: dimensions, IDs, costs, keys, and tabular figures.

### Hierarchy
- **Display** (600, 26px, 1.15, -0.02em): the sheet title (page h1). One per sheet.
- **Title** (600, 18px, 1.2): block and panel headings (h2).
- **Body** (400, 13px, 1.5): prose and descriptions; measure capped at 68–72ch.
- **Label** (500, 10px, 0.1em, uppercase): field keys, section labels, table headers, plot metadata.
- **Measurement** (500, 24px, JetBrains Mono): register values, rendered with tabular numerals.

### Named Rules
**The Mono-For-Measurement Rule.** Monospace is used only for data, identifiers, and measurement, never as a costume for "technical."

## Layout

A fixed 264px sheet-index rail on the left, a 64px title-block header, and a content column capped at 1560px with 28/32px padding. The density rhythm steps 4/8/12/16/20/24/32/40/56px (`--s1`–`--s9`); sections are separated by 32px with a 1px ink rule above each block head, always more space above a heading than below.

The measurement register is a single bordered row of four cells divided by hairlines. Plotted frames sit two-up on desktop. Responsive behavior is structural: the sidebar becomes a drawer at 860px, the register drops to two then one column at 1180/560px, chart panels stack at 860px, and wide tables scroll inside their panel rather than overflowing the page.

## Elevation & Depth

The system is flat by default. Depth is conveyed by tonal layering — paper ground, white sheet panels, hairline borders — not by shadows. Radius stays near-square (2px–4px), reinforcing a drawn and measured character.

### Shadow Vocabulary
- **Toast float** (`0 10px 30px rgba(22, 32, 43, 0.14)`): the only elevated surface, for the transient toast.
- **Panel** (`0 1px 2px rgba(22, 32, 43, 0.04)`): a barely-there register hint; no card uses a soft drop shadow.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest; a shadow appears only on a transient overlay, never on a content card.

## Shapes

Near-square corners: 2px for controls and panels, 4px maximum, 6px only for the schematic nodes, and a pill only for status dots. Form language is rectilinear and ruled. The recurring motifs are the hairline border, the corner registration tick on register cells, and the graph grid inside plot frames. No large rounded cards, no blobs.

## Components

**Buttons** — rectilinear controls in the drafting vocabulary.
- **Shape:** 2px radius, 1px border, 8px 12px padding, 12px/500 label.
- **Primary:** ink ground with white text; hover shifts to drafting blue.
- **Secondary / Ghost:** white ground with a rule-2 border; hover fills paper-2.
- **Focus:** 2px drafting-blue outline at 2px offset.

**Chips / Status pills** — mono uppercase labels at 10px, 2px radius, tone-tinted background and border (info/ok/warn/danger/neutral). A status dot is a 7px circle; loading/pending uses a soft ring.

**Cards / Containers** — white sheet panels with a 1px rule border, 2px radius, flat (no shadow), 16–20px internal padding. Register cells add a 5px corner registration tick.

**Inputs / Fields** — the search field is a 1px rule-2 bordered box with a mono placeholder; focus swaps the border to drafting blue with a soft blue ring. Disabled controls drop to 50% opacity and are not focusable.

**Navigation** — a numbered "sheet index": mono 01–07 numbers, a 16px line icon, and a label. Active state is a white fill, a 1px drafting-blue-line border, and a blue index number; hover lifts to a white fill with a rule border. At 860px it becomes an off-canvas drawer.

**Plotted Frame (signature)** — a bordered panel whose body is a 24px graph grid; when empty it shows a dashed inner frame with "NO MEASUREMENTS RECORDED". Data is drawn as a thin 1.75px trace with open-circle markers, mono axis ticks, and a mono tooltip.

**Redline Callout (signature)** — a recommendation as a numbered revision balloon: a red 24px circle number, a severity marker, an "Example component" tag, and a spec list of resource / evidence / action.

**IaC Schematic (signature)** — a horizontal flow of numbered nodes (pull request → Terraform plan → Infracost → CloudOps AI → human review) joined by ruled connectors with arrow icons, above a six-field review strip all set to honest dashes.

## Do's and Don'ts

### Do:
- **Do** use hairline rules and paper value for separation; keep panels flat.
- **Do** set every number, ID, and key in JetBrains Mono with tabular figures.
- **Do** use drafting blue only for structure and state, and red pencil only for severity/annotations.
- **Do** render unmeasured data as an em dash and label unavailable capability "Not available".
- **Do** tag any illustrative example explicitly ("Example component") so it cannot be mistaken for real output.
- **Do** keep body measure at 65–75ch and metadata text at ≥4.5:1 contrast.

### Don't:
- **Don't** add eyebrow/kicker labels above headings; the heading carries its own weight.
- **Don't** use a colored `border-left`/`border-right` accent above 1px on cards, list items, callouts, or alerts.
- **Don't** use gradients, glass/blur decoration, neon, or purple "AI" styling.
- **Don't** use soft drop shadows on content cards or large rounded-card shapes.
- **Don't** use Unicode glyphs or emoji as icons; use the icon set.
- **Don't** fabricate AWS metrics, costs, resources, savings, accounts, or regions.
- **Don't** treat the decorative graph grid as a generic background; reserve it for measurement surfaces.
