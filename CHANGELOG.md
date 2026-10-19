# Changelog

## Unreleased

- **Docker dashboard serves your real data** through a consistent snapshot (`seen docker-sync`, ADR 0011). Mock data
  is for the test stacks only.
- **Privacy and recall:** a blocked prompt is no longer stored; custom PII rules have a cap and a deadline against
  ReDoS (a rule that times out fails closed: block mode stops the prompt and redaction withholds the text); `hook.log` keeps only frames and exception types. New detectors: quoted and URL-embedded secrets, Bearer,
  Google, Stripe and GitLab tokens, public IPv4, `91`-prefixed phones, Aadhaar VIDs (with a keyword).
  `ip` and `gstin` join the default PII types.
- **Erasure (DPDP, ADR 0012):** `seen purge`; team server key list, revoke and expiry, and user and project delete.
- **Upgrade flow (ADR 0013):** `seen version`, `seen upgrade`, `/seen:upgrade`, skew checks and an update notice in
  `seen doctor`, `scripts/bump_version.py`, and a test that keeps every version in step.
- **Core correctness:** `audit verify` no longer reports tampering after a retention prune; `secret.key` is created
  once under races; parallel hooks no longer lose or corrupt session state; a planted FIFO cannot hang the pre-read
  scan, and a broken allowlist matcher fails closed; lockfile approvals ignore empty or malformed hashes; a streamed
  message is billed at its largest usage and a resumed subagent is counted only for the turn it ran in; racing
  ingests no longer drop an audit batch; memory rewrites refuse a symlinked `.seen/memory`.
- **Sync robustness (ADR 0014):** permanently rejected batches are parked (`seen sync --retry-failed`, shown in
  `seen doctor`) instead of retried forever; the team server validates and caps ingest, limits body size, counts
  successful requests in its throttle and supports `SEEN_TEAM_PROXY_HOPS`; `sync.server` must be https (or localhost).
  Ledger migration 0004: run `seen upgrade`.
- **CI audit gates (ADR 0015):** a new `audit` workflow (every push and PR, plus weekly) runs pip-audit on the lockfile,
  `npm audit` on production dependencies, gitleaks over the full history, and trivy on the dashboard and team images;
  `ci` gains a Postgres job for the team server, concurrency groups, timeouts and caches; Dependabot covers uv, npm,
  Actions and Docker. Base images move to `python:3.12.15-slim-bookworm` (the old pin carried fixable OpenSSL CVEs).
- **Accessibility and e2e (ADR 0016):** axe runs on every dashboard page in both themes, on desktop and phone; new
  Playwright checks cover titles, the main landmark, a skip link, keyboard access to table rows, the error and empty
  states and reflow at 320px. Fixed along the way: scrollable tables are keyboard focusable regions, clickable rows
  contain a real link or button, each page sets its title, one `<main>` per page, and the project grids no longer
  overflow below 320px.
- **The mark watches the pointer:** the eyes in the rail (topbar on a phone) follow the mouse and keyboard focus anywhere on the page, then go back to glancing; they stay still under reduced motion. The architecture diagram (`docs/architecture.html`) now has a light skin.
