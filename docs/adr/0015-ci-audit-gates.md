# 0015: CI audit gates

Status: accepted, 2026-10-19 (audit finding: no dependency, secret or image scanning in CI).

`.github/workflows/audit.yml` runs on every push to main, every pull request and weekly (new advisories appear without
a commit):
- **python-deps:** `pip-audit` (pinned) over `uv export --frozen --all-packages --no-dev`, so it checks the lockfile
  rather than whatever is installed.
- **npm-deps:** `npm audit --omit=dev --audit-level=high` in `web/`. The dashboard ships as a built bundle, so dev
  tooling does not reach users; advisories that only affect dev tools or server-side rendering are not gated.
- **secrets:** gitleaks over the full git history with `.gitleaks.toml`. Two reviewed false positives (a documented fake
  API key and a test marker) are listed by fingerprint in `.gitleaksignore`; add to it only after reading the finding.
- **images:** trivy on the dashboard and team images, failing on fixable HIGH or CRITICAL findings (`--ignore-unfixed`).

Tools run from pinned versions or image digests so the gate cannot change under us; no new third-party Action is used.
`ci.yml` gains a `team-pg` job (the team test suite against Postgres 16, the production database) plus concurrency
groups, job timeouts and caches. The hook-latency gate already runs inside `pytest` in the `python` job (the `perf`
tests are not excluded there); only containers skip it. Dependabot proposes weekly grouped updates for uv, npm, Actions
and both Dockerfile directories.

First run findings: pip-audit and `npm audit` were clean. trivy found fixable OpenSSL CVEs in the
`python:3.12.9-slim-bookworm` base; both Dockerfiles now use `python:3.12.15-slim-bookworm` and rescan at zero. gitleaks
found the two false positives above.

Not done: SAST (CodeQL), SBOM and image signing, scanning unfixed CVEs as a gate, and pinning base images by digest
(Dependabot's docker ecosystem updates the tags instead).
