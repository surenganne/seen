# Changelog

## Unreleased

- **Overview is a dashboard:** five tiles with the change against the previous period and a trend line, an Activity chart
  (requests per day, file-changing vs talk-only), Spend by model with token and cache figures, where the work happened,
  commit outcomes, a weekday-by-hour rhythm, per-rule compliance, skills by approval status and PII by type. The API
  returns `by_day`, `prev`, `git`, `policies`, `skill_status`, `areas` and `rhythm`; `cost_by_day`, `recent_changes` and
  `top_files` are gone (Timeline and Changes cover them).
- **Timeline:** a page and `GET /api/projects/{pid}/timeline`: a spine of file-changing requests by day, each with a
  one-line headline, the pseudonymous user id, the folders touched, lines and the commit it ended on; day totals and
  gap markers. Talk-only turns are hidden (`all_turns` brings them back); Changes still lists every request. **Project memory removed** (ADR 0017): hook injection and the edit gate, the Memory page and API, `seen memory`, the
  `using-seen-memory` skill, the `[memory]` settings and migration `0005` (drops `change_memories` and `changes.mem_*`).
  Reinstall the CLI and plugin after upgrading: an older `seen-hook` cannot read the new schema and records nothing.
  Existing `.seen/memory/` files are left in place and ignored. Old audit events about memory stay as history.
- **Docker dashboard serves your real data** through a consistent snapshot (`seen docker-sync`). Mock data
  is for the test stacks only.
- **Privacy and recall:** a blocked prompt is no longer stored; custom PII rules have a cap and a deadline against
  ReDoS (a rule that times out fails closed: block mode stops the prompt and redaction withholds the text); `hook.log` keeps only frames and exception types. New detectors: quoted and URL-embedded secrets, Bearer,
  Google, Stripe and GitLab tokens, public IPv4, `91`-prefixed phones, Aadhaar VIDs (with a keyword).
  `ip` and `gstin` join the default PII types.
- **Erasure:** `seen purge`; team server key list, revoke and expiry, and user and project delete.
- **Upgrade flow:** `seen version`, `seen upgrade`, `/seen:upgrade`, skew checks and an update notice in
  `seen doctor`, `scripts/bump_version.py`, and a test that keeps every version in step.
- **Core correctness:** `audit verify` no longer reports tampering after a retention prune; `secret.key` is created
  once under races; parallel hooks no longer lose or corrupt session state; a planted FIFO cannot hang the pre-read
  scan, and a broken allowlist matcher fails closed; lockfile approvals ignore empty or malformed hashes; a streamed
  message is billed at its largest usage and a resumed subagent is counted only for the turn it ran in; racing
  ingests no longer drop an audit batch; memory rewrites refuse a symlinked `.seen/memory`.
- **Sync robustness:** permanently rejected batches are parked (`seen sync --retry-failed`, shown in
  `seen doctor`) instead of retried forever; the team server validates and caps ingest, limits body size, counts
  successful requests in its throttle and supports `SEEN_TEAM_PROXY_HOPS`; `sync.server` must be https (or localhost).
  Ledger migration 0004: run `seen upgrade`.
- **CI audit gates:** a new `audit` workflow (every pull request and push to `main`, plus weekly) runs pip-audit on the lockfile,
  `npm audit` on production dependencies, gitleaks over the full history, and trivy on the dashboard and team images;
  `ci` gains a Postgres job for the team server, concurrency groups, timeouts and caches; Dependabot covers uv, npm,
  Actions and Docker. Base images move to `python:3.12.15-slim-bookworm` (the old pin carried fixable OpenSSL CVEs). `ci` runs on pull requests and pushes to `main` only (no double runs per push); Dependabot ignores major and minor jumps of the python and node base images.
- **Accessibility and e2e:** axe runs on every dashboard page in both themes, on desktop and phone; new
  Playwright checks cover titles, the main landmark, a skip link, keyboard access to table rows, the error and empty
  states and reflow at 320px. Fixed along the way: scrollable tables are keyboard focusable regions, clickable rows
  contain a real link or button, each page sets its title, one `<main>` per page, and the project grids no longer
  overflow below 320px.
- **Dashboard weight and drill-down:** pages load on demand (first page 727 KB to about 311 KB of script, capped by a test),
  the router is created once, and every Overview tile links to the changes behind its number.
- **Page-level unit tests:** all nine dashboard pages render in vitest against captured API responses, in normal, empty and
  API-down states (13 to 47 tests); `scripts/capture_web_fixtures.py` refreshes the fixtures. Change detail headings cut at a word boundary.
- **The mark watches the pointer:** the eyes in the rail (topbar on a phone) follow the mouse and keyboard focus anywhere on the page, then go back to glancing; they stay still under reduced motion. The architecture diagram (`docs/architecture.html`) now has a light skin.
