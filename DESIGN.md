# Seen dashboard: design system

Product UI for three readers at once: engineering leads, developers and compliance reviewers (see
[PRODUCT.md](PRODUCT.md)). Personality: **precise, calm, trustworthy**. The page stays quiet until something
needs a human, then says exactly what and links straight to the evidence.

Source of truth: `web/src/styles/tokens.css` (tokens) and `web/src/styles/index.css` (components).
Change tokens there, never hard-code colours in components.

## Colour

OKLCH throughout, built on the ExampleOrg palette. Strategy is **restrained**: tinted neutrals and one accent
(orange) under 10% of any screen. Status colours are separate from the accent and always come with an
icon and a word, never colour alone.

| Token | Light | Use |
|---|---|---|
| `--navy` | `oklch(0.27 0.06 255)` (#0A2540) | Rail, brand ink |
| `--accent` | `oklch(0.66 0.19 40)` (#E85D26) | Active nav icon, focus, tab underline, chart series 1 |
| `--accent-strong` | `oklch(0.555 0.175 40)` | Primary button fill (white text 5.1:1) |
| `--accent-ink` | `oklch(0.52 0.17 40)` | Orange text and links on light surfaces |
| `--bg` / `--surface` | near-white, chroma 0.004 toward navy / white | Page / panels. No cream or paper tones |
| `--ink` / `--ink-2` / `--ink-3` | navy-tinted greys | Body / secondary / muted (all ≥ 4.5:1) |
| `--border` / `--control-border` | | Panel hairlines / inputs and buttons (≥ 3:1) |
| `--good` `--warning` `--critical` `--info` | each with a `-soft` tint | Status badges, notes, alert tiles |

Dark mode is its own palette (navy-black `oklch(0.165 0.035 258)` page, `oklch(0.205 0.04 257)` panels),
selected by the OS or the theme switch (`data-theme` on `<html>`). Every text pair was checked for WCAG 2.2 AA
contrast in both modes.

Charts follow the `dataviz` method: fixed categorical order (colour follows the tool, never its rank), one
y-axis, 2px surface gaps between stacked segments, hover tooltip on every chart, and a table view.

## Type

One family: **IBM Plex Sans** (400/500/600) for UI, **IBM Plex Mono** (400/500) for paths, hashes, ids,
money and timestamps. Self-hosted through `@fontsource`; the CSP allows `'self'` only. Numbers use tabular
figures. Hierarchy comes from size and weight steps, not extra typefaces. No all-caps eyebrows.

## Layout

- **Shell**: navy rail (240px) with the mark, project switcher, nav and the audit-chain footer; a topbar
  with breadcrumbs, date range (7/14/28 days) and theme. Under 860px the rail becomes a scrolling nav strip
  and the project switcher moves to the topbar (only one is ever rendered).
- **Page**: `PageHead` (title, one-line description that says what the page proves, actions on the right),
  then panels.
- **Panels** (`.panel`, `Card`): 1px border, 10px radius, no drop shadow. `flush` panels hold tables and
  row lists edge to edge. Never nested.
- **Summary strip** (`.strip` / `Tile`): one panel divided into cells, not a grid of cards. A tile that
  needs attention gets a soft critical tint and an icon, not a coloured side stripe.
- **Tables** (`table.data`): sticky header, mono timestamps, right-aligned numbers, the whole row clickable
  and keyboard-focusable (`Enter` opens it). Tables scroll inside their own container on phones.
- **Drawers** (`.drawer`): skill and audit-event detail slide in from the right.

## Components

| Component | Where | Notes |
|---|---|---|
| `Badge` | everywhere | tone + lucide icon + label |
| `.tag` | kind, type, trigger | plain categorical label, no icon |
| `Note` | info / warning / critical callouts | full border and tint, icon first |
| `Seal` | audit page | "Chain verified · N events", or the first break |
| `.meter` | cost share, compliance, PII by type | single hue magnitude bar |
| `Empty` | every list | says what was checked and what to do next |
| `Loading` | every query | skeleton rows with `role="status"`, no spinners |
| `.attention` | Overview | what needs a human, each with a Review link to the filtered changes |

## The mark

`components/Eyes.tsx` and `assets/brand/eyes.svg`: two round eyes with brows on a transparent background,
white sclera, ExampleOrg-orange rim and brows, blue iris (`#5AA9E6 → #1F5F99 → #0A2540`), navy pupil and a double
glint. The colours never change, so the mark reads the same everywhere. Idle: looks around, blinks and lifts
its brows now and then. Alert (the selected project has open high-confidence PII or a missed rule): stops,
stares ahead with the brows drawn down, pupil narrows; the accessible name becomes "Seen: needs attention".
Project cards always show the idle mark; their status is the "Needs attention" badge. Static, mono and PNG
variants live in `assets/brand/`.

## Motion

150–250ms with an ease-out curve, for hover, theme change, the drawer and the eyes. Every animation has a
`prefers-reduced-motion` fallback (the eyes stop; the drawer appears without sliding).

## Accessibility

WCAG 2.2 AA: visible 2px focus ring on every control, labelled inputs (`aria-label` where the label is
visual only), `role="tablist"` tabs, `aria-pressed` filter chips, `aria-selected` rows, status never by
colour alone, 24px minimum targets, and Playwright runs every flow on a phone viewport with a CSP-violation
and console-error guard.

## Don'ts

Paper or cream backgrounds, purple gradients, gradient text, side-stripe borders, glass cards, bare
"clean" badges (say what was checked instead), numbered or eyebrow section labels, spinners.
