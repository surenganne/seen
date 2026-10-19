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
colour contrast of states axe cannot reach (hover, focus, open drawers). Follow-up the same day (web audit list): pages
load on demand (`React.lazy`), which took the first download from 727 KB to about 311 KB of script (recharts now ships with the
Overview page; a test caps the first page at 450 KB); the router is created once instead of inside render; each Overview tile
is a link to the rows behind its number, covered by a click-through test per tile. Polling in hidden tabs needed no change:
TanStack Query v5 already pauses `refetchInterval` while the tab is in the background. Page-level unit tests (`src/pages/pages.test.tsx`) now render all nine pages against responses captured from a seeded scratch home
(`scripts/capture_web_fixtures.py` writes `src/test/fixtures.json`; synthetic data only) with a fetch mock that can answer normally,
with every list empty, or with 500: each page is checked for loading, data, an alert when the API is down, and no alert when empty
(47 vitest tests, up from 13). A request shown as the Change detail heading is now cut at a word boundary with an ellipsis instead of
mid-word at 240 characters (`truncateWords`); it stays the heading on purpose, since the request is what the page is about, and it is
stored redacted by default. Re-run the capture script after a response shape changes.
