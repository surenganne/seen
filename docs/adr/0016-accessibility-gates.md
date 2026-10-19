# 0016: Accessibility gates in e2e

Status: accepted, 2026-10-19 (audit finding: the WCAG 2.2 AA promise in PRODUCT.md was unverified).

`web/e2e/a11y.spec.ts` (run by the existing Playwright CI job) uses `@axe-core/playwright` (pinned, dev only) with the
`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` rule sets on all nine routes, in light and dark, on the desktop
and phone projects, with no exclusions. It also asserts page titles, one `main` landmark, a skip link that moves focus,
real controls inside clickable rows, an alert (not a blank page) when the API fails, an empty list that still renders
and passes axe, and no horizontal page scroll at 320 CSS pixels.

First run findings, all fixed: scrollable tables were not keyboard reachable (they are now labelled, focusable regions);
no page set its own title (the layout does, from the route); every page rendered its own `main` and there was no skip
link (the layout owns one `main` and a skip link now); clickable rows were `tr tabindex=0` with Enter only, with no role
or name (each row now holds a link or button named by its main text, the row click stays for the mouse); the project and
two-column grids had a 300 or 320px minimum and overflowed a 320px screen (`min(320px, 100%)`).

Playwright's `fixtures.ts` gained an `expectedErrors` option so a test that forces an API 500 can allow that console
line while every other console error still fails the test.

Not covered by automation, so manual (docs/TESTING.md Part 16): screen-reader behaviour, 200% and 400% zoom, and
colour contrast of states axe cannot reach (hover, focus, open drawers). Not done from the audit list: lazy-loading pages,
a router created inside render, pausing polling in hidden tabs, and a click-through test per overview tile.
